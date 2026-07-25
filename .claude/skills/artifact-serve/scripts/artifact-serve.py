#!/usr/bin/env python3
"""artifact-serve — stage and serve generated artifacts.

stdlib only. See ../REFERENCE.md for behaviour, ../SKILL.md for quick start.
"""
from __future__ import annotations

import argparse
import errno
import html
import http.server
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Names allowed for --project and --as (kebab-case + underscore).
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Durable feedback storage (survives /tmp/ wipe + reboot).
FEEDBACK_ROOT = Path.home() / ".local" / "share" / "claude-artifacts"
FEEDBACK_DB = FEEDBACK_ROOT / "feedback.db"
UPLOAD_ROOT = FEEDBACK_ROOT / "uploads"

# Upload guardrails.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB per file
# Extension allowlist (lowercase, leading dot).
UPLOAD_EXT_ALLOW = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".pdf", ".txt", ".md", ".log", ".csv", ".json", ".yaml", ".yml", ".toml",
        ".zip", ".tar", ".gz", ".7z",
        ".fig", ".psd", ".xcf", ".sketch",
        ".mp4", ".webm", ".mov",
    }
)
# Extensions hard-blocked even if otherwise allowed.
UPLOAD_EXT_BLOCK = frozenset(
    {".exe", ".dll", ".sh", ".bash", ".zsh", ".bat", ".cmd",
     ".ps1", ".js", ".mjs", ".html", ".htm", ".xhtml", ".svg", ".com"}
)

# Hard cap on multipart POST body size (sum of fields + files).
# Per-file cap is MAX_UPLOAD_BYTES; per-request cap allows several
# files to be uploaded in one comment.
MAX_REQUEST_BYTES = 500 * 1024 * 1024  # 500 MB

# Multipart boundary regex helpers.
_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_DISP_NAME_RE = re.compile(r'name="([^"]+)"')
_DISP_FILENAME_RE = re.compile(r'filename="([^"]*)"')

# ── constants ─────────────────────────────────────────────────────────

ROOT = Path("/tmp/claude-artifacts")
PID_FILE = ROOT / ".serve.pid"
PORT_FILE = ROOT / ".serve.port"
LOG_FILE = ROOT / ".serve.log"
INDEX_FILE = ROOT / "index.html"
DEFAULT_PORT = 9099
EXIT_OK = 0
EXIT_CALLER = 1
EXIT_SERVER = 2

log = logging.getLogger("artifact-serve")


# ── filesystem helpers ────────────────────────────────────────────────


def ensure_root() -> None:
    """Create /tmp/claude-artifacts/ if missing. Idempotent."""
    ROOT.mkdir(parents=True, exist_ok=True)


def ensure_feedback_root() -> None:
    """Create durable feedback dirs. Idempotent."""
    FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def db_connect() -> sqlite3.Connection:
    """Open feedback DB; init schema on first use."""
    ensure_feedback_root()
    conn = sqlite3.connect(str(FEEDBACK_DB), timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifact_index (
            project     TEXT NOT NULL,
            subdir      TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            src_path    TEXT NOT NULL,
            last_pushed INTEGER NOT NULL,
            PRIMARY KEY (project, subdir)
        );
        CREATE INDEX IF NOT EXISTS idx_index_artifact
            ON artifact_index(artifact_id);

        CREATE TABLE IF NOT EXISTS comment (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id TEXT NOT NULL,
            sub_path    TEXT NOT NULL DEFAULT '',
            body        TEXT NOT NULL,
            author      TEXT,
            created_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_comment_artifact_path
            ON comment(artifact_id, sub_path);

        CREATE TABLE IF NOT EXISTS upload (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id  INTEGER NOT NULL
                        REFERENCES comment(id) ON DELETE CASCADE,
            filename    TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime        TEXT,
            size        INTEGER NOT NULL,
            created_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_upload_comment ON upload(comment_id);

        CREATE TABLE IF NOT EXISTS setting (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def resolve_artifact_id(url_path: str) -> tuple[str | None, str]:
    """Map URL path to (artifact_id, sub_path).

    URL form: /<project>/<subdir>/<rest...>. Look up
    (project, subdir) in artifact_index; if missing, fall back to
    "<project>/<subdir>" as the artifact_id. sub_path is the
    remainder after the artifact root (leading slash stripped).
    Returns (None, "") for URLs that don't address a staged artifact
    (root index, /_/api/..., assets at depth 1, etc.).
    """
    parts = [p for p in url_path.split("/") if p]
    if len(parts) < 2:
        return None, ""
    project, subdir = parts[0], parts[1]
    if not (NAME_RE.match(project) and NAME_RE.match(subdir)):
        return None, ""
    sub_path = "/".join(parts[2:])
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT artifact_id FROM artifact_index "
                "WHERE project=? AND subdir=?",
                (project, subdir),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        row = None
    artifact_id = row[0] if row else f"{project}/{subdir}"
    return artifact_id, sub_path


def iso_utc(ts: int | None) -> str | None:
    """Format an epoch int as ISO-8601 UTC ('2026-05-19T16:25:49Z')."""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def setting_get(key: str) -> str | None:
    """Fetch a value from the `setting` k/v table, or None if absent."""
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT value FROM setting WHERE key=?", (key,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def setting_set(key: str, value: str) -> None:
    """Upsert (key, value) into the `setting` k/v table."""
    conn = db_connect()
    try:
        conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def setting_delete(key: str) -> None:
    """Remove a row from the `setting` k/v table. No-op if absent."""
    conn = db_connect()
    try:
        conn.execute("DELETE FROM setting WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()


def safe_upload_filename(name: str) -> str:
    """Sanitize an uploaded filename: basename, kebab-safe chars only."""
    base = Path(name).name or "unnamed"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base.lstrip(".") or "unnamed"
    return base[:200]


def upload_ext_ok(filename: str) -> tuple[bool, str]:
    """Validate extension against allowlist/blocklist."""
    ext = Path(filename).suffix.lower()
    if ext in UPLOAD_EXT_BLOCK:
        return False, f"extension {ext!r} is blocked"
    if ext not in UPLOAD_EXT_ALLOW:
        return False, f"extension {ext!r} is not in allowlist"
    return True, ""


def parse_multipart_form(
    content_type: str, body: bytes
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Parse multipart/form-data body bytes into (fields, files).

    fields: dict of name → string value for non-file parts.
    files: list of dicts with keys: name, filename, content_type, data (bytes).

    stdlib-only replacement for the removed cgi.FieldStorage. Loads
    the entire body into memory; callers should enforce a request-size
    cap before invoking. Multipart spec per RFC 7578.
    """
    m = _BOUNDARY_RE.search(content_type)
    if not m:
        raise ValueError("Content-Type has no boundary")
    boundary = b"--" + m.group(1).encode("latin-1")
    fields: dict[str, str] = {}
    files: list[dict[str, object]] = []
    for raw in body.split(boundary):
        # Strip surrounding CRLF + trailing "--" sentinel on the final part.
        chunk = raw.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        header_blob, _, payload = chunk.partition(b"\r\n\r\n")
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        headers: dict[str, str] = {}
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                k, _, v = line.partition(b":")
                headers[k.strip().lower().decode("ascii", "replace")] = (
                    v.strip().decode("latin-1", "replace")
                )
        disp = headers.get("content-disposition", "")
        name_m = _DISP_NAME_RE.search(disp)
        if not name_m:
            continue
        name = name_m.group(1)
        fname_m = _DISP_FILENAME_RE.search(disp)
        if fname_m and fname_m.group(1):
            files.append(
                {
                    "name": name,
                    "filename": fname_m.group(1),
                    "content_type": headers.get(
                        "content-type", "application/octet-stream"
                    ),
                    "data": payload,
                }
            )
        else:
            # Text field; decode as UTF-8 best-effort.
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


def _check_name(value: str, kind: str) -> str:
    """Validate a project or subdir name against NAME_RE; raise if bad."""
    if not value or not NAME_RE.match(value):
        raise ValueError(
            f"invalid --{kind} {value!r}: must match {NAME_RE.pattern} "
            "(lowercase kebab-case + underscore)"
        )
    return value


def project_dir(project: str) -> Path:
    """Return /tmp/claude-artifacts/<project>/, creating it on access."""
    safe = _check_name(project, "project")
    p = ROOT / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def atomic_write(target: Path, content: str) -> None:
    """Write file via tempfile + os.replace for crash safety."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=str(target.parent), delete=False, encoding="utf-8"
    ) as fh:
        fh.write(content)
        tmp = Path(fh.name)
    os.replace(tmp, target)


def remove_entry(entry: Path) -> None:
    """Delete a pushed entry (symlink, file, or dir). No-op if absent."""
    if entry.is_symlink() or entry.is_file():
        entry.unlink(missing_ok=True)
    elif entry.is_dir():
        shutil.rmtree(entry)


# ── pid / port plumbing ───────────────────────────────────────────────


def read_pid() -> int | None:
    """Return live daemon pid, or None if stale/absent."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return None
        raise
    return pid


def read_port() -> int | None:
    """Return active port if recorded, else None."""
    if not PORT_FILE.exists():
        return None
    try:
        return int(PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def clear_runtime_files() -> None:
    """Remove pid/port files. Leaves staging + log intact."""
    for p in (PID_FILE, PORT_FILE):
        p.unlink(missing_ok=True)


# ── index regeneration ────────────────────────────────────────────────


def _entry_meta(entry: Path) -> tuple[str, int, str]:
    """Return (kind, file_count, mtime_iso) for an entry."""
    if entry.is_symlink():
        target = os.readlink(entry)
        kind = f"symlink → {html.escape(target)}"
    elif entry.is_dir():
        kind = "copy (dir)"
    elif entry.is_file():
        kind = "copy (file)"
    else:
        kind = "unknown"

    count = 0
    try:
        for sub in entry.rglob("*"):
            if sub.is_file():
                count += 1
                if count > 9999:
                    break
    except OSError:
        count = -1

    try:
        mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        mtime_iso = mtime.strftime("%Y-%m-%d %H:%M UTC")
    except OSError:
        mtime_iso = "?"

    return kind, count, mtime_iso


def regenerate_index() -> None:
    """Rebuild /tmp/claude-artifacts/index.html. Atomic write."""
    ensure_root()
    projects: list[tuple[str, list[Path]]] = []
    for child in sorted(ROOT.iterdir()):
        if child.name.startswith(".") or child.name == "index.html":
            continue
        if not child.is_dir():
            continue
        entries = [p for p in sorted(child.iterdir()) if not p.name.startswith(".")]
        projects.append((child.name, entries))

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    port = read_port() or DEFAULT_PORT
    total_entries = sum(len(e) for _, e in projects)

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append("<html lang='en'><head><meta charset='utf-8'>")
    parts.append("<title>artifact-serve</title>")
    parts.append(
        "<style>"
        "body{background:#1a1612;color:#e6e6eb;"
        "font-family:ui-sans-serif,system-ui,sans-serif;"
        "margin:0;padding:2rem;line-height:1.45}"
        "h1{font-size:1.4rem;margin:0 0 .25rem}"
        "h2{font-size:1.05rem;margin:2rem 0 .5rem;"
        "border-bottom:1px solid #3a3028;padding-bottom:.25rem}"
        ".meta{color:#8a7a68;font-size:.85rem;margin-bottom:1.5rem}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));"
        "gap:.75rem}"
        ".tile{background:#241e17;border:1px solid #3a3028;"
        "border-radius:4px;padding:.85rem 1rem;text-decoration:none;color:inherit;"
        "display:block;transition:background .12s}"
        ".tile:hover{background:#2e2620;border-color:#5a4a38}"
        ".tile h3{margin:0 0 .25rem;font-size:1rem;color:#f0e8d4}"
        ".tile .sub{font-size:.8rem;color:#a08858;word-break:break-all}"
        ".tile .stats{font-size:.75rem;color:#6a5540;margin-top:.4rem}"
        ".empty{color:#6a5540;font-style:italic;padding:2rem 0}"
        "code{background:#0e0c09;padding:.1rem .3rem;border-radius:2px;"
        "font-size:.85em}"
        "</style></head><body>"
    )
    parts.append("<h1>artifact-serve</h1>")
    parts.append(
        f"<div class='meta'>port <code>{port}</code> · "
        f"{len(projects)} project(s) · {total_entries} entry(ies) · "
        f"regenerated {now}</div>"
    )

    if not projects:
        parts.append(
            "<div class='empty'>No artifacts pushed yet. Run "
            "<code>artifact-serve push --project NAME --src PATH</code>.</div>"
        )

    for project_name, entries in projects:
        parts.append(f"<h2>{html.escape(project_name)}</h2>")
        if not entries:
            parts.append("<div class='empty'>(empty)</div>")
            continue
        parts.append("<div class='grid'>")
        for entry in entries:
            kind, count, mtime_iso = _entry_meta(entry)
            href = f"/{html.escape(project_name)}/{html.escape(entry.name)}/"
            parts.append(
                f"<a class='tile' href='{href}'>"
                f"<h3>{html.escape(entry.name)}</h3>"
                f"<div class='sub'>{kind}</div>"
                f"<div class='stats'>{count} file(s) · {mtime_iso}</div>"
                "</a>"
            )
        parts.append("</div>")

    parts.append("</body></html>")
    atomic_write(INDEX_FILE, "\n".join(parts))


# ── http server ───────────────────────────────────────────────────────


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


_WIDGET_JS = r"""
(function(){
  const path = window.location.pathname;
  const headers = {'Accept': 'application/json'};
  const root = document.getElementById('artifact-serve-comments');
  if (!root) return;

  async function loadSettings(){
    try {
      const r = await fetch('/_/api/settings', {headers});
      if (!r.ok) return;
      const s = await r.json();
      if (s && typeof s.author === 'string' && s.author){
        const inp = root.querySelector('input[name=author]');
        if (inp && !inp.value) inp.value = s.author;
      }
    } catch (e){ /* ignore */ }
  }

  async function load(){
    const r = await fetch('/_/api/comments?url=' + encodeURIComponent(path), {headers});
    if (!r.ok){ root.querySelector('.as-list').innerHTML =
      '<p class="as-err">failed to load comments: ' + r.status + '</p>'; return; }
    const data = await r.json();
    const list = root.querySelector('.as-list');
    list.innerHTML = '';
    if (data.artifact_id){
      root.querySelector('.as-aid').textContent = data.artifact_id;
    }
    if (!data.comments.length){
      list.innerHTML = '<p class="as-empty">no comments yet</p>';
      return;
    }
    for (const c of data.comments){
      const li = document.createElement('article');
      li.className = 'as-comment';
      const meta = document.createElement('header');
      const when = new Date(c.created_at * 1000).toISOString().replace('T',' ').slice(0,16);
      meta.innerHTML = '<span class="as-author">' +
        (c.author ? escape(c.author) : 'anonymous') + '</span>' +
        ' <span class="as-when">' + when + ' UTC</span>';
      li.appendChild(meta);
      const body = document.createElement('div');
      body.className = 'as-body';
      body.textContent = c.body;
      li.appendChild(body);
      if (c.uploads && c.uploads.length){
        const ul = document.createElement('ul');
        ul.className = 'as-uploads';
        for (const u of c.uploads){
          const item = document.createElement('li');
          const a = document.createElement('a');
          a.href = '/_/api/uploads/' + u.id;
          a.textContent = u.filename + ' (' + Math.round(u.size/1024) + ' KB)';
          a.target = '_blank';
          item.appendChild(a);
          ul.appendChild(item);
        }
        li.appendChild(ul);
      }
      list.appendChild(li);
    }
  }
  function escape(s){ return s.replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  const form = root.querySelector('form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const status = root.querySelector('.as-status');
    status.textContent = 'posting...';
    const fd = new FormData(form);
    fd.append('url', path);
    try {
      const r = await fetch('/_/api/comments', {method:'POST', body: fd});
      if (!r.ok){
        const t = await r.text();
        status.textContent = 'error: ' + r.status + ' ' + t.slice(0,200);
        return;
      }
      status.textContent = 'posted.';
      form.reset();
      load();
    } catch (err){
      status.textContent = 'network error: ' + err;
    }
  });

  loadSettings();
  load();
})();
"""

_WIDGET_CSS = r"""
#artifact-serve-comments {
  font-family: ui-sans-serif, system-ui, sans-serif;
  background: #1a1612;
  color: #e6e6eb;
  padding: 2rem;
  border-top: 4px solid #5a4a38;
  margin-top: 2rem;
  line-height: 1.45;
}
#artifact-serve-comments h2 {
  margin: 0 0 .25rem; font-size: 1.05rem; color: #f0e8d4;
}
#artifact-serve-comments .as-aid {
  font-family: ui-monospace, monospace; color: #a08858; font-size: .8rem;
}
#artifact-serve-comments .as-list { margin: 1rem 0; max-width: 920px; }
#artifact-serve-comments .as-empty { color: #6a5540; font-style: italic; }
#artifact-serve-comments .as-comment {
  background: #241e17; border: 1px solid #3a3028; border-radius: 4px;
  padding: .75rem 1rem; margin-bottom: .5rem;
}
#artifact-serve-comments .as-comment header {
  font-size: .8rem; color: #a08858; margin-bottom: .35rem;
}
#artifact-serve-comments .as-author { font-weight: 600; color: #f0e8d4; }
#artifact-serve-comments .as-body {
  white-space: pre-wrap; word-break: break-word;
}
#artifact-serve-comments .as-uploads {
  margin: .5rem 0 0; padding-left: 1.25rem; font-size: .85rem;
}
#artifact-serve-comments .as-uploads a {
  color: #c8a058; text-decoration: none;
}
#artifact-serve-comments .as-uploads a:hover { text-decoration: underline; }
#artifact-serve-comments form {
  background: #241e17; border: 1px solid #3a3028; border-radius: 4px;
  padding: 1rem; max-width: 920px;
}
#artifact-serve-comments label {
  display: block; font-size: .8rem; color: #a08858; margin-bottom: .25rem;
}
#artifact-serve-comments input[type=text],
#artifact-serve-comments textarea {
  width: 100%; background: #0e0c09; color: #e6e6eb;
  border: 1px solid #3a3028; border-radius: 3px;
  padding: .5rem; font-family: inherit; font-size: .9rem;
  margin-bottom: .75rem; box-sizing: border-box;
}
#artifact-serve-comments textarea { min-height: 5rem; }
#artifact-serve-comments input[type=file] { color: #a08858; font-size: .85rem; }
#artifact-serve-comments button {
  background: #5a4a38; color: #f0e8d4; border: 1px solid #7a6040;
  padding: .5rem 1rem; border-radius: 3px; cursor: pointer;
  font-family: inherit; margin-top: .5rem;
}
#artifact-serve-comments button:hover { background: #6a5a48; }
#artifact-serve-comments .as-status {
  margin-top: .5rem; font-size: .85rem; color: #c8a058;
}
#artifact-serve-comments .as-err { color: #e08868; }
"""

_INJECT_BLOCK = """
<style>__CSS__</style>
<section id="artifact-serve-comments">
  <h2>Feedback</h2>
  <div>artifact: <span class="as-aid">(loading)</span></div>
  <div class="as-list"><p class="as-empty">loading...</p></div>
  <form enctype="multipart/form-data">
    <label>name (optional)</label>
    <input type="text" name="author" maxlength="80" placeholder="anonymous">
    <label>comment</label>
    <textarea name="body" required maxlength="20000"
              placeholder="your feedback..."></textarea>
    <label>attachments (optional, multiple)</label>
    <input type="file" name="files" multiple>
    <button type="submit">post comment</button>
    <div class="as-status"></div>
  </form>
</section>
<script>__JS__</script>
"""


def _injection_html() -> bytes:
    """Return the assembled injection block (CSS + section + JS) as bytes."""
    block = (
        _INJECT_BLOCK.replace("__CSS__", _WIDGET_CSS).replace("__JS__", _WIDGET_JS)
    )
    return block.encode("utf-8")


def _api_list_comments(artifact_id: str, sub_path: str) -> dict[str, object]:
    """Return JSON-ready dict for GET /_/api/comments."""
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT id, body, author, created_at FROM comment "
            "WHERE artifact_id=? AND sub_path=? ORDER BY created_at ASC",
            (artifact_id, sub_path),
        ).fetchall()
        comments: list[dict[str, object]] = []
        for cid, body, author, ts in rows:
            ups = conn.execute(
                "SELECT id, filename, size, mime FROM upload "
                "WHERE comment_id=? ORDER BY id ASC",
                (cid,),
            ).fetchall()
            comments.append(
                {
                    "id": cid,
                    "body": body,
                    "author": author,
                    "created_at": ts,
                    "created_at_iso": iso_utc(ts),
                    "uploads": [
                        {"id": u[0], "filename": u[1], "size": u[2], "mime": u[3]}
                        for u in ups
                    ],
                }
            )
    finally:
        conn.close()
    return {"artifact_id": artifact_id, "sub_path": sub_path, "comments": comments}


def _make_handler() -> type[http.server.SimpleHTTPRequestHandler]:
    root_str = str(ROOT)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__(*a, directory=root_str, **kw)  # type: ignore[arg-type]

        def log_message(self, fmt: str, *args: object) -> None:
            log.info("%s - %s", self.address_string(), fmt % args)

        # ── routing ──────────────────────────────────────────────────

        def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
            url = urllib.parse.urlsplit(self.path)
            if url.path.startswith("/_/api/comments"):
                self._handle_api_comments_get(url)
                return
            if url.path.startswith("/_/api/uploads/"):
                self._handle_api_upload_get(url.path[len("/_/api/uploads/"):])
                return
            if url.path == "/_/api/settings":
                self._handle_api_settings_get()
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/_/api/comments":
                self._handle_api_comments_post()
                return
            self.send_error(404, "not found")

        # ── HTML injection ───────────────────────────────────────────

        def send_head(self):  # type: ignore[override]
            """Wrap text/html responses to append the feedback widget.

            Keying off `_sent_ctype` (captured during super().send_head's
            send_header calls) catches BOTH explicit .html requests AND
            directory requests that resolve to an index.html — guessing
            type from the URL path alone misses the dir case.
            """
            self._sent_ctype = ""
            f = super().send_head()
            if f is None:
                return None
            if not self._sent_ctype.startswith("text/html"):
                return f
            try:
                body = f.read()
            finally:
                f.close()
            inject = _injection_html()
            idx = body.lower().rfind(b"</body>")
            if idx == -1:
                merged = body + inject
            else:
                merged = body[:idx] + inject + body[idx:]
            return io.BytesIO(merged)

        # Override the header emission to (a) capture the Content-Type the
        # server is actually about to send, and (b) suppress Content-Length
        # on text/html responses so the mutated-body length doesn't lie.
        # We use connection-close framing for HTML (HTTP/1.0 default).
        def send_header(self, keyword: str, value: str) -> None:  # type: ignore[override]
            lk = keyword.lower()
            if lk == "content-type":
                self._sent_ctype = value.lower()
            if lk == "content-length":
                if getattr(self, "_sent_ctype", "").startswith("text/html"):
                    return
            super().send_header(keyword, value)

        # ── API: GET comments ────────────────────────────────────────

        def _handle_api_comments_get(self, url: urllib.parse.SplitResult) -> None:
            params = urllib.parse.parse_qs(url.query)
            artifact_id: str | None = None
            sub_path = ""
            if "artifact" in params:
                artifact_id = params["artifact"][0]
            elif "url" in params:
                artifact_id, sub_path = resolve_artifact_id(params["url"][0])
            if artifact_id is None:
                self._send_json(404, {"error": "could not resolve artifact"})
                return
            try:
                payload = _api_list_comments(artifact_id, sub_path)
            except sqlite3.Error as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return
            self._send_json(200, payload)

        # ── API: POST a comment (multipart) ──────────────────────────

        def _handle_api_comments_post(self) -> None:
            ctype_hdr = self.headers.get("Content-Type", "")
            if not ctype_hdr.startswith("multipart/form-data"):
                self._send_json(400, {"error": "expected multipart/form-data"})
                return
            try:
                clen = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(411, {"error": "Content-Length required"})
                return
            if clen <= 0:
                self._send_json(411, {"error": "Content-Length required"})
                return
            if clen > MAX_REQUEST_BYTES:
                self._send_json(
                    413,
                    {"error": f"request body {clen}B exceeds {MAX_REQUEST_BYTES}B"},
                )
                return

            try:
                body = self.rfile.read(clen)
            except OSError as exc:
                self._send_json(400, {"error": f"read failed: {exc}"})
                return

            try:
                fields, files = parse_multipart_form(ctype_hdr, body)
            except ValueError as exc:
                self._send_json(400, {"error": f"bad multipart: {exc}"})
                return

            url_field = fields.get("url", "")
            artifact_field = fields.get("artifact", "")
            text_body = (fields.get("body") or "").strip()
            author = (fields.get("author") or "").strip() or None
            # If reviewer left name blank, fall back to globally-set default.
            if author is None:
                author = setting_get("author")
            if not text_body:
                self._send_json(400, {"error": "body required"})
                return
            if len(text_body) > 20000:
                self._send_json(400, {"error": "body too long (>20000 chars)"})
                return

            if artifact_field:
                artifact_id, sub_path = artifact_field, ""
            elif url_field:
                artifact_id, sub_path = resolve_artifact_id(url_field)
                if artifact_id is None:
                    self._send_json(
                        400, {"error": "url does not resolve to an artifact"}
                    )
                    return
            else:
                self._send_json(400, {"error": "url or artifact required"})
                return

            # Validate per-file caps + extensions BEFORE inserting comment.
            for f in files:
                raw_name = str(f.get("filename") or "unnamed")
                safe = safe_upload_filename(raw_name)
                ok, why = upload_ext_ok(safe)
                if not ok:
                    self._send_json(400, {"error": f"{raw_name}: {why}"})
                    return
                size = len(f.get("data", b""))  # type: ignore[arg-type]
                if size > MAX_UPLOAD_BYTES:
                    self._send_json(
                        413,
                        {
                            "error": f"{raw_name}: {size}B exceeds "
                            f"{MAX_UPLOAD_BYTES}B cap"
                        },
                    )
                    return

            now = int(time.time())
            try:
                conn = db_connect()
                try:
                    cur = conn.execute(
                        "INSERT INTO comment "
                        "(artifact_id, sub_path, body, author, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (artifact_id, sub_path, text_body, author, now),
                    )
                    comment_id = cur.lastrowid
                    if comment_id is None:
                        raise sqlite3.Error("no rowid from comment insert")
                    saved: list[dict[str, object]] = []
                    if files:
                        cdir = UPLOAD_ROOT / str(comment_id)
                        cdir.mkdir(parents=True, exist_ok=True)
                        for f in files:
                            raw_name = str(f.get("filename") or "unnamed")
                            safe = safe_upload_filename(raw_name)
                            data: bytes = f.get("data", b"")  # type: ignore[assignment]
                            target = cdir / safe
                            i = 1
                            stem, suf = target.stem, target.suffix
                            while target.exists():
                                target = cdir / f"{stem}-{i}{suf}"
                                i += 1
                            try:
                                target.write_bytes(data)
                            except OSError as exc:
                                conn.rollback()
                                self._send_json(
                                    500, {"error": f"write failed: {exc}"}
                                )
                                return
                            mime, _ = mimetypes.guess_type(safe)
                            conn.execute(
                                "INSERT INTO upload "
                                "(comment_id, filename, stored_path, mime, "
                                "size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    comment_id,
                                    safe,
                                    str(target),
                                    mime,
                                    len(data),
                                    int(time.time()),
                                ),
                            )
                            saved.append(
                                {"filename": safe, "size": len(data), "mime": mime}
                            )
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return

            self._send_json(
                201,
                {
                    "id": comment_id,
                    "artifact_id": artifact_id,
                    "sub_path": sub_path,
                    "uploads": saved,
                },
            )

        # ── API: GET upload by id ────────────────────────────────────

        def _handle_api_upload_get(self, suffix: str) -> None:
            try:
                upload_id = int(suffix.split("/", 1)[0])
            except ValueError:
                self.send_error(404, "not found")
                return
            try:
                conn = db_connect()
                try:
                    row = conn.execute(
                        "SELECT filename, stored_path, mime, size "
                        "FROM upload WHERE id=?",
                        (upload_id,),
                    ).fetchone()
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self.send_error(500, f"db: {exc}")
                return
            if not row:
                self.send_error(404, "not found")
                return
            filename, stored_path, mime, size = row
            path = Path(stored_path)
            if not path.is_file():
                self.send_error(410, "upload file missing on disk")
                return
            # Force download for non-image to dodge inline-script risks.
            inline_mimes = {
                "image/png", "image/jpeg", "image/webp", "image/gif",
                "image/bmp", "application/pdf", "text/plain",
            }
            mime_used = mime or "application/octet-stream"
            disposition = "inline" if mime_used in inline_mimes else "attachment"
            self.send_response(200)
            self.send_header("Content-Type", mime_used)
            self.send_header("Content-Length", str(size))
            safe_disp_name = filename.replace('"', '')
            self.send_header(
                "Content-Disposition",
                f'{disposition}; filename="{safe_disp_name}"',
            )
            super().end_headers()
            with path.open("rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        # ── helpers ──────────────────────────────────────────────────

        def _handle_api_settings_get(self) -> None:
            """Return all (key, value) pairs from the `setting` table."""
            try:
                conn = db_connect()
                try:
                    rows = conn.execute("SELECT key, value FROM setting").fetchall()
                finally:
                    conn.close()
            except sqlite3.Error as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return
            self._send_json(200, {k: v for k, v in rows})

        def _send_json(self, code: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            super().end_headers()
            self.wfile.write(body)

    return Handler


def _redirect_stdio_to_log() -> None:
    """Child process: close stdin, send stdout/stderr to LOG_FILE."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd_in = os.open(os.devnull, os.O_RDONLY)
    fd_out = os.open(str(LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd_in, 0)
    os.dup2(fd_out, 1)
    os.dup2(fd_out, 2)
    os.close(fd_in)
    if fd_out > 2:
        os.close(fd_out)


def _serve_forever(port: int) -> None:
    """Child process entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    def _on_sig(_signum: int, _frame: object) -> None:
        log.info("received signal, shutting down")
        clear_runtime_files()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sig)
    signal.signal(signal.SIGINT, _on_sig)

    handler_cls = _make_handler()
    try:
        with ReusableTCPServer(("127.0.0.1", port), handler_cls) as httpd:
            log.info("serving %s on 127.0.0.1:%d", ROOT, port)
            httpd.serve_forever()
    except OSError as exc:
        log.error("bind failed: %s", exc)
        clear_runtime_files()
        sys.exit(EXIT_SERVER)


def _port_free(port: int) -> bool:
    """Probe whether 127.0.0.1:<port> can be bound with SO_REUSEADDR.

    Mirrors the real server's allow_reuse_address=True so we don't reject
    a port that's only in TIME_WAIT from a recently-stopped daemon.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


# ── tailscale wiring ──────────────────────────────────────────────────


def _tailscale_available() -> bool:
    return shutil.which("tailscale") is not None


def _tailscale_serve_on(port: int) -> tuple[bool, str]:
    """Publish 127.0.0.1:<port> via tailscale serve. Returns (ok, message)."""
    if not _tailscale_available():
        return False, "tailscale CLI not on PATH"
    try:
        # First-time HTTPS cert provisioning can take 30-60s on a fresh
        # tailnet. Subsequent calls are fast (cert cached).
        proc = subprocess.run(
            [
                "tailscale",
                "serve",
                "--bg",
                "--https=443",
                f"http://127.0.0.1:{port}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"tailscale call failed: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip() or f"rc={proc.returncode}"
    return True, (proc.stdout or proc.stderr).strip()


def _tailscale_serve_off() -> tuple[bool, str]:
    if not _tailscale_available():
        return False, "tailscale CLI not on PATH"
    try:
        proc = subprocess.run(
            ["tailscale", "serve", "--https=443", "off"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"tailscale call failed: {exc}"
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()


def _tailscale_public_url() -> str | None:
    """Extract tailnet URL from `tailscale serve status --json`."""
    if not _tailscale_available():
        return None
    try:
        proc = subprocess.run(
            ["tailscale", "serve", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    web = data.get("Web") if isinstance(data, dict) else None
    if not isinstance(web, dict):
        return None
    for key in web.keys():
        if isinstance(key, str) and key.startswith(("https://", "http://")):
            return key.rstrip("/") + "/"
        if isinstance(key, str) and ":" in key:
            host = key.split(":", 1)[0]
            return f"https://{host}/"
    return None


# ── verb implementations ──────────────────────────────────────────────


def cmd_push(args: argparse.Namespace) -> int:
    # Preserve user's literal path: do NOT call .resolve() (which would
    # dereference any intermediate symlinks). .absolute() only anchors
    # relative paths against cwd without walking the symlink chain.
    src = Path(args.src).expanduser().absolute()
    if not src.exists():
        print(f"error: --src does not exist: {src}", file=sys.stderr)
        return EXIT_CALLER

    ensure_root()
    try:
        project = project_dir(args.project)
        subdir = _check_name(args.as_name or src.name, "as")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CALLER

    dest = project / subdir
    remove_entry(dest)

    rel = os.path.relpath(src, dest.parent)
    os.symlink(rel, dest)
    print(f"symlink {dest} → {rel}")

    # Record this push in the durable artifact index for feedback resolution.
    # --id is opaque (no charset rule); falls back to "<project>/<subdir>".
    artifact_id = (args.artifact_id or "").strip() or f"{args.project}/{subdir}"
    try:
        conn = db_connect()
        try:
            conn.execute(
                "INSERT INTO artifact_index "
                "(project, subdir, artifact_id, src_path, last_pushed) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project, subdir) DO UPDATE SET "
                "  artifact_id = excluded.artifact_id, "
                "  src_path    = excluded.src_path, "
                "  last_pushed = excluded.last_pushed",
                (args.project, subdir, artifact_id, str(src), int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()
        print(f"artifact_id: {artifact_id}")
    except sqlite3.Error as exc:
        log.warning("artifact_index update failed: %s", exc)

    regenerate_index()
    return EXIT_OK


def cmd_unpush(args: argparse.Namespace) -> int:
    try:
        project = project_dir(args.project)
        subdir = _check_name(args.subdir, "subdir")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CALLER
    dest = project / subdir
    if not (dest.exists() or dest.is_symlink()):
        print(f"(absent) {dest}")
        return EXIT_OK
    remove_entry(dest)
    print(f"removed {dest}")
    regenerate_index()
    return EXIT_OK


def cmd_start(args: argparse.Namespace) -> int:
    ensure_root()
    port = args.port

    existing_pid = read_pid()
    existing_port = read_port()
    if existing_pid and existing_port == port:
        print(f"daemon already running pid={existing_pid} port={port}")
        print(f"local:   http://127.0.0.1:{port}/")
        regenerate_index()
        if args.expose:
            ok, msg = _tailscale_serve_on(port)
            if not ok:
                print(f"expose failed: {msg}", file=sys.stderr)
                return EXIT_SERVER
            url = _tailscale_public_url() or "(tailscale URL unknown)"
            print(f"tailnet: {url}")
        return EXIT_OK

    if existing_pid and existing_port and existing_port != port:
        print(
            f"error: daemon already running on port {existing_port} "
            f"(pid {existing_pid}); stop it first",
            file=sys.stderr,
        )
        return EXIT_SERVER

    if not _port_free(port):
        print(f"error: port {port} already in use by another process", file=sys.stderr)
        return EXIT_SERVER

    regenerate_index()

    pid = os.fork()
    if pid > 0:
        # parent
        for _ in range(40):
            if PID_FILE.exists():
                break
            time.sleep(0.05)
        PID_FILE.write_text(str(pid))
        PORT_FILE.write_text(str(port))
        print(f"daemon started pid={pid} port={port}")
        print(f"local:   http://127.0.0.1:{port}/")
        if args.expose:
            ok, msg = _tailscale_serve_on(port)
            if not ok:
                print(f"expose failed: {msg}", file=sys.stderr)
                return EXIT_SERVER
            url = _tailscale_public_url() or "(tailscale URL unknown)"
            print(f"tailnet: {url}")
        return EXIT_OK

    # child
    os.setsid()
    _redirect_stdio_to_log()
    PID_FILE.write_text(str(os.getpid()))
    PORT_FILE.write_text(str(port))
    _serve_forever(port)
    return EXIT_OK  # not reached


def cmd_expose(_args: argparse.Namespace) -> int:
    pid = read_pid()
    port = read_port()
    if not pid or not port:
        print("error: daemon not running; run `start` first", file=sys.stderr)
        return EXIT_SERVER
    ok, msg = _tailscale_serve_on(port)
    if not ok:
        print(f"expose failed: {msg}", file=sys.stderr)
        return EXIT_SERVER
    url = _tailscale_public_url() or "(tailscale URL unknown)"
    print(f"tailnet: {url}")
    return EXIT_OK


def cmd_unexpose(_args: argparse.Namespace) -> int:
    ok, msg = _tailscale_serve_off()
    if not ok:
        print(f"unexpose: {msg}", file=sys.stderr)
        return EXIT_SERVER
    print("unexposed")
    return EXIT_OK


def cmd_status(_args: argparse.Namespace) -> int:
    pid = read_pid()
    port = read_port()
    if pid and port:
        print(f"daemon:  pid={pid} port={port}")
        print(f"local:   http://127.0.0.1:{port}/")
    else:
        print("daemon:  stopped")
    tailnet = _tailscale_public_url()
    print(f"tailnet: {tailnet or '(not exposed)'}")
    print(f"root:    {ROOT}")
    ensure_root()
    projects = [p for p in sorted(ROOT.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    if not projects:
        print("entries: (none)")
        return EXIT_OK
    print("entries:")
    for proj in projects:
        entries = [e for e in sorted(proj.iterdir()) if not e.name.startswith(".")]
        for entry in entries:
            kind = "→ " + os.readlink(entry) if entry.is_symlink() else "(copy)"
            print(f"  {proj.name}/{entry.name}  {kind}")
    return EXIT_OK


def cmd_stop(_args: argparse.Namespace) -> int:
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            print(f"kill failed: {exc}", file=sys.stderr)
            return EXIT_SERVER
        # wait briefly for graceful exit
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        print(f"stopped pid={pid}")
    else:
        print("daemon already stopped")
    _tailscale_serve_off()
    clear_runtime_files()
    return EXIT_OK


def cmd_name(args: argparse.Namespace) -> int:
    """Get / set / clear the global comment-author name."""
    try:
        if args.clear:
            setting_delete("author")
            print("cleared")
            return EXIT_OK
        if args.value is None:
            current = setting_get("author")
            print(current if current else "(unset)")
            return EXIT_OK
        v = args.value.strip()
        if not v:
            print(
                "error: empty value; use --clear to unset",
                file=sys.stderr,
            )
            return EXIT_CALLER
        if len(v) > 80:
            print("error: name too long (>80 chars)", file=sys.stderr)
            return EXIT_CALLER
        setting_set("author", v)
        print(f"author = {v}")
    except sqlite3.Error as exc:
        print(f"error: db: {exc}", file=sys.stderr)
        return EXIT_SERVER
    return EXIT_OK


def cmd_feedback(args: argparse.Namespace) -> int:
    """Dump comments + upload metadata for an artifact as JSON."""
    artifact_id = args.artifact_id.strip()
    if not artifact_id:
        print("error: --artifact required", file=sys.stderr)
        return EXIT_CALLER
    try:
        conn = db_connect()
        try:
            rows = conn.execute(
                "SELECT id, sub_path, body, author, created_at "
                "FROM comment WHERE artifact_id=? "
                "ORDER BY sub_path ASC, created_at ASC",
                (artifact_id,),
            ).fetchall()
            comments: list[dict[str, object]] = []
            for cid, sub_path, body, author, ts in rows:
                ups = conn.execute(
                    "SELECT id, filename, stored_path, mime, size, created_at "
                    "FROM upload WHERE comment_id=? ORDER BY id ASC",
                    (cid,),
                ).fetchall()
                comments.append(
                    {
                        "id": cid,
                        "sub_path": sub_path,
                        "body": body,
                        "author": author,
                        "created_at": ts,
                        "created_at_iso": iso_utc(ts),
                        "uploads": [
                            {
                                "id": u[0],
                                "filename": u[1],
                                "stored_path": u[2],
                                "mime": u[3],
                                "size": u[4],
                                "created_at": u[5],
                                "created_at_iso": iso_utc(u[5]),
                            }
                            for u in ups
                        ],
                    }
                )
            idx_rows = conn.execute(
                "SELECT project, subdir, src_path, last_pushed "
                "FROM artifact_index WHERE artifact_id=?",
                (artifact_id,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"error: db: {exc}", file=sys.stderr)
        return EXIT_SERVER
    payload = {
        "artifact_id": artifact_id,
        "pushes": [
            {
                "project": r[0],
                "subdir": r[1],
                "src_path": r[2],
                "last_pushed": r[3],
                "last_pushed_iso": iso_utc(r[3]),
            }
            for r in idx_rows
        ],
        "comments": comments,
    }
    print(json.dumps(payload, indent=2, default=str))
    return EXIT_OK


def cmd_clean(args: argparse.Namespace) -> int:
    if not args.project:
        print("error: --project required (no global wipe)", file=sys.stderr)
        return EXIT_CALLER
    try:
        name = _check_name(args.project, "project")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CALLER
    target = ROOT / name
    if not target.exists():
        print(f"(absent) {target}")
        return EXIT_OK
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return EXIT_CALLER
    shutil.rmtree(target)
    print(f"removed {target}")
    regenerate_index()
    return EXIT_OK


# ── arg parsing ───────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="artifact-serve",
        description="Stage and serve artifacts under /tmp/claude-artifacts/.",
    )
    sub = p.add_subparsers(dest="verb", required=True)

    sp = sub.add_parser("push", help="Stage an artifact (symlink only).")
    sp.add_argument("--project", required=True)
    sp.add_argument("--src", required=True)
    sp.add_argument("--as", dest="as_name", default=None)
    sp.add_argument(
        "--id",
        dest="artifact_id",
        default=None,
        help="Artifact ID for feedback correlation. Default: <project>/<subdir>.",
    )
    sp.set_defaults(func=cmd_push)

    sp = sub.add_parser("unpush", help="Remove a staged entry.")
    sp.add_argument("--project", required=True)
    sp.add_argument("--subdir", required=True)
    sp.set_defaults(func=cmd_unpush)

    sp = sub.add_parser("start", help="Boot the local daemon.")
    sp.add_argument("--port", type=int, default=DEFAULT_PORT)
    sp.add_argument("--expose", action="store_true", help="Also publish via tailscale.")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("expose", help="Publish via tailscale serve.")
    sp.set_defaults(func=cmd_expose)

    sp = sub.add_parser("unexpose", help="Take down tailscale serve.")
    sp.set_defaults(func=cmd_unexpose)

    sp = sub.add_parser("status", help="Show daemon + entries.")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("stop", help="Stop the daemon + unexpose.")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("clean", help="Remove one project's staging dir.")
    sp.add_argument("--project", required=True)
    sp.set_defaults(func=cmd_clean)

    sp = sub.add_parser(
        "feedback",
        help="Dump comments + upload metadata for an artifact as JSON.",
    )
    sp.add_argument("--artifact", dest="artifact_id", required=True)
    sp.set_defaults(func=cmd_feedback)

    sp = sub.add_parser(
        "name",
        help="Get/set/clear the global default comment-author name.",
    )
    sp.add_argument(
        "value",
        nargs="?",
        default=None,
        help="New name. Omit to print current. Use --clear to unset.",
    )
    sp.add_argument("--clear", action="store_true", help="Unset the name.")
    sp.set_defaults(func=cmd_name)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
