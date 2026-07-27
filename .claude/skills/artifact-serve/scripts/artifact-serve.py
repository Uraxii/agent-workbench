#!/usr/bin/env python3
"""artifact-serve  -  stage and serve generated artifacts for review.

Rebuild of artifact-serve into a review app: deep-zoom image gallery
(OpenSeadragon), pin-to-region annotations (Annotorious), threaded resolvable
comments, per-line code feedback, and an optional bd mirror. Same bones as the
legacy script: staging-by-symlink, stdlib http.server + sqlite3 daemon,
optional `tailscale serve` HTTPS, durable DB + uploads under
~/.local/share/claude-artifacts/, agent read-back as JSON.

stdlib only. See spikes/review-app/DESIGN.md for the full design.
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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "Anchor",
    "Reply",
    "Thread",
    "Upload",
    "build_parser",
    "db_connect",
    "main",
]

log = logging.getLogger("artifact-serve")

# ── names + paths ─────────────────────────────────────────────────────

# Names allowed for --project and --as (kebab-case + underscore). The first
# character class forbids a project literally named "_", so the entire
# reserved "/_/..." app namespace can never collide with a pushed artifact.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Throwaway staging root (wipes on reboot).
ROOT = Path("/tmp/claude-artifacts")
PID_FILE = ROOT / ".serve.pid"
PORT_FILE = ROOT / ".serve.port"
LOG_FILE = ROOT / ".serve.log"
INDEX_FILE = ROOT / "index.html"

# Durable feedback storage (survives /tmp/ wipe + reboot).
FEEDBACK_ROOT = Path.home() / ".local" / "share" / "claude-artifacts"
FEEDBACK_DB = FEEDBACK_ROOT / "feedback.db"
UPLOAD_ROOT = FEEDBACK_ROOT / "uploads"

# Vendored static frontend (OpenSeadragon + Annotorious), served under
# /_/assets/. Lives beside this script in the skill dir.
SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_ROOT = SKILL_DIR / "assets"

# Repo root, used only to locate the agent-workbench CLI for the
# optional bd mirror (section 11): `agent-workbench bd path <project>`.
# This script always lives at
# <repo>/.claude/skills/artifact-serve/scripts/artifact-serve.py, so the repo
# root is computed relative to this file rather than hardcoded  -  keeps the
# path-standard identity-leak lint happy and the script portable.
REPO_ROOT = Path(__file__).resolve().parents[4]
AGENT_WORKBENCH_CLI = (
    REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "agent-workbench"
)

DEFAULT_PORT = 9099
EXIT_OK = 0
EXIT_CALLER = 1
EXIT_SERVER = 2

# ── review-app constants ──────────────────────────────────────────────

# Current on-disk schema version. Bumped by the v1->v2 backfill migration.
SCHEMA_VERSION = 3

# Anchor kinds a thread may carry.
ANCHOR_PAGE = "page"
ANCHOR_IMAGE_REGION = "image_region"
ANCHOR_CODE_LINE = "code_line"
ANCHOR_KINDS = frozenset({ANCHOR_PAGE, ANCHOR_IMAGE_REGION, ANCHOR_CODE_LINE})

# Selector types accepted inside an image_region anchor. SvgSelector is
# rejected server-side: Annotorious's setAnnotations() parses SVG selector
# markup into the live DOM (stored XSS), and the drawing UI only ever emits
# FragmentSelector rects, so SvgSelector is attacker-only input.
SELECTOR_FRAGMENT = "FragmentSelector"

# Hard cap on the anchor_data JSON blob (defensive: do not trust client JSON).
MAX_ANCHOR_BYTES = 8 * 1024

# Strict media-fragment value for a FragmentSelector (x,y,w,h).
FRAGMENT_XYWH_RE = re.compile(
    r"^xywh=(pixel:|percent:)?"
    r"\d+(\.\d+)?,\d+(\.\d+)?,\d+(\.\d+)?,\d+(\.\d+)?$"
)

# Image extensions the gallery + OSD viewer treat as viewable.
IMAGE_EXT = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)

# Extensions the per-line code view (render_code_page) can meaningfully
# render as text. Used by the directory-browse gallery to decide whether a
# non-image file links into the code view or falls back to a raw link (e.g.
# a .pdf or a binary blob would render as garbage in the code view).
CODE_EXT = frozenset(
    {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".md", ".txt", ".log",
        ".csv", ".yaml", ".yml", ".toml", ".sh", ".bash", ".zsh", ".css",
        ".html", ".htm", ".xml", ".c", ".cpp", ".h", ".hpp", ".go", ".rs",
        ".java", ".rb", ".gd", ".cfg", ".ini", ".sql",
    }
)

# Upload guardrails (unchanged from legacy  -  do not regress).
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_REQUEST_BYTES = 500 * 1024 * 1024
UPLOAD_EXT_ALLOW = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".pdf", ".txt", ".md", ".log", ".csv", ".json", ".yaml", ".yml",
        ".toml", ".zip", ".tar", ".gz", ".7z",
        ".fig", ".psd", ".xcf", ".sketch",
        ".mp4", ".webm", ".mov",
    }
)
UPLOAD_EXT_BLOCK = frozenset(
    {".exe", ".dll", ".sh", ".bash", ".zsh", ".bat", ".cmd",
     ".ps1", ".js", ".mjs", ".html", ".htm", ".xhtml", ".svg", ".com"}
)

# Comment body length cap (unchanged from legacy).
MAX_BODY_CHARS = 20000


# ── data model ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Upload:
    """One file attached to a reply, stored on disk under UPLOAD_ROOT."""

    id: int
    reply_id: int | None
    filename: str
    stored_path: Path
    mime: str | None
    size: int
    created_at: int


@dataclass(frozen=True)
class Reply:
    """One message within a thread. A thread's first reply is its opener."""

    id: int
    thread_id: int
    body: str
    author: str | None
    created_at: int
    uploads: Sequence[Upload] = field(default_factory=tuple)


@dataclass(frozen=True)
class Anchor:
    """Where a thread is pinned.

    kind is one of ANCHOR_KINDS. data is the parsed, already-validated anchor
    payload: None for a page anchor, the W3C selector dict for an image region,
    or {"line": int, "end_line": int | None} for a code line. The raw JSON
    string that produced this is never trusted; see validate_anchor.
    """

    kind: str
    data: dict[str, object] | None


@dataclass(frozen=True)
class Thread:
    """A comment thread anchored somewhere on a served page or file."""

    id: int
    artifact_id: str
    sub_path: str
    anchor: Anchor
    resolved: bool
    author: str | None
    created_at: int
    bd_ticket: str | None = None
    round_id: int | None = None
    round_number: int | None = None
    round_inferred: bool = False
    replies: Sequence[Reply] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReviewItem:
    """One owned review target shown in the unified queue and landing cards."""

    name: str
    rel_path: str
    kind: str
    href: str
    preview_src: str | None
    open_threads: int
    total_threads: int


@dataclass(frozen=True)
class ReviewListing:
    """Owned review data for one artifact directory path."""

    directory: str
    items: Sequence[ReviewItem] = field(default_factory=tuple)
    folder_count: int = 0
    image_count: int = 0
    code_count: int = 0
    open_threads: int = 0
    total_threads: int = 0


# ── schema ────────────────────────────────────────────────────────────

# Full DDL. Idempotent (CREATE ... IF NOT EXISTS). The v1->v2 backfill in
# migrate_schema handles the one-time upload-table rebuild and legacy
# comment -> thread/reply copy. See DESIGN.md section 6-7.
SCHEMA_DDL = """
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

CREATE TABLE IF NOT EXISTS artifact_round (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id  TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    project      TEXT,
    subdir       TEXT,
    src_path     TEXT,
    created_at   INTEGER NOT NULL,
    inferred     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (artifact_id, round_number),
    CHECK (inferred IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_artifact_round_artifact
    ON artifact_round(artifact_id, round_number);

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

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    sub_path    TEXT NOT NULL DEFAULT '',
    anchor_kind TEXT NOT NULL DEFAULT 'page',
    anchor_data TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0,
    author      TEXT,
    created_at  INTEGER NOT NULL,
    bd_ticket   TEXT,
    round_id    INTEGER,
    CHECK (anchor_kind IN ('page', 'image_region', 'code_line')),
    CHECK (resolved IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_thread_artifact_path
    ON thread(artifact_id, sub_path);
CREATE INDEX IF NOT EXISTS idx_thread_round ON thread(round_id);

CREATE TABLE IF NOT EXISTS reply (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  INTEGER NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    author     TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reply_thread ON reply(thread_id);

CREATE TABLE IF NOT EXISTS upload (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reply_id    INTEGER REFERENCES reply(id) ON DELETE CASCADE,
    comment_id  INTEGER,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT,
    size        INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id);
CREATE INDEX IF NOT EXISTS idx_upload_comment ON upload(comment_id);
"""


def db_connect() -> sqlite3.Connection:
    """Open feedback DB; ensure schema + run pending migrations.

    Postcondition: returns a live connection with foreign_keys ON, all tables
    from SCHEMA_DDL present, and setting['schema_version'] == str(SCHEMA_VERSION).
    Caller owns closing.
    """
    ensure_feedback_root()
    conn = sqlite3.connect(str(FEEDBACK_DB), timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")

    ddl = SCHEMA_DDL
    upload_cols = {row[1] for row in conn.execute("PRAGMA table_info(upload)")}
    thread_cols = {row[1] for row in conn.execute("PRAGMA table_info(thread)")}
    if upload_cols and "reply_id" not in upload_cols:
        # ponytail: a real legacy DB's `upload` table predates the reply_id
        # column, and CREATE TABLE IF NOT EXISTS is a no-op against it, so
        # SCHEMA_DDL's trailing `CREATE INDEX ... ON upload(reply_id)` would
        # fail before that column exists. Skip just that one index here;
        # migrate_schema's one-time rebuild (_rebuild_upload_table_if_legacy)
        # recreates both upload indexes once the table has the new shape.
        ddl = ddl.replace(
            "CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id);",
            "",
        )
    if thread_cols and "round_id" not in thread_cols:
        ddl = ddl.replace(
            "CREATE INDEX IF NOT EXISTS idx_thread_round ON thread(round_id);",
            "",
        )
    conn.executescript(ddl)
    conn.commit()
    migrate_schema(conn)
    return conn


def _rebuild_upload_table_if_legacy(conn: sqlite3.Connection) -> None:
    """Rebuild `upload` once so comment_id is nullable and reply_id exists.

    No-op if the table already has the new shape (fresh DB, or an already
    migrated one)  -  sqlite cannot drop a NOT NULL constraint in place, so a
    one-time table rebuild is the standard move (DESIGN.md section 7 step 2).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(upload)")}
    if "reply_id" in cols:
        return
    conn.execute(
        "CREATE TABLE upload_new ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "reply_id INTEGER REFERENCES reply(id) ON DELETE CASCADE, "
        "comment_id INTEGER, filename TEXT NOT NULL, "
        "stored_path TEXT NOT NULL, mime TEXT, size INTEGER NOT NULL, "
        "created_at INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO upload_new "
        "(id, comment_id, filename, stored_path, mime, size, created_at) "
        "SELECT id, comment_id, filename, stored_path, mime, size, created_at "
        "FROM upload"
    )
    conn.execute("DROP TABLE upload")
    conn.execute("ALTER TABLE upload_new RENAME TO upload")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_upload_comment ON upload(comment_id)"
    )


def _backfill_legacy_comments(conn: sqlite3.Connection) -> None:
    """Copy each legacy comment row into one page-level thread + one reply.

    Remaps that comment's uploads onto the new reply. Ordered by id so the
    result is deterministic; the caller's schema_version gate is what makes
    a second run a no-op (DESIGN.md section 7 step 3).
    """
    rows = conn.execute(
        "SELECT id, artifact_id, sub_path, body, author, created_at "
        "FROM comment ORDER BY id ASC"
    ).fetchall()
    for cid, artifact_id, sub_path, body, author, created_at in rows:
        thread_id = conn.execute(
            "INSERT INTO thread "
            "(artifact_id, sub_path, anchor_kind, anchor_data, resolved, "
            " author, created_at) VALUES (?, ?, 'page', NULL, 0, ?, ?)",
            (artifact_id, sub_path, author, created_at),
        ).lastrowid
        reply_id = conn.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, body, author, created_at),
        ).lastrowid
        conn.execute(
            "UPDATE upload SET reply_id=? WHERE comment_id=?", (reply_id, cid)
        )


def _ensure_round_table_if_legacy(conn: sqlite3.Connection) -> None:
    """Add thread.round_id in place for pre-round databases."""
    thread_cols = {row[1] for row in conn.execute("PRAGMA table_info(thread)")}
    if "round_id" not in thread_cols:
        conn.execute("ALTER TABLE thread ADD COLUMN round_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_round ON thread(round_id)")


def _next_round_number(conn: sqlite3.Connection, artifact_id: str) -> int:
    """Return the next ordered round number for one artifact_id."""
    row = conn.execute(
        "SELECT COALESCE(MAX(round_number), 0) FROM artifact_round WHERE artifact_id=?",
        (artifact_id,),
    ).fetchone()
    return int(row[0]) + 1


def _insert_round_row(
    conn: sqlite3.Connection,
    artifact_id: str,
    round_number: int,
    created_at: int,
    *,
    project: str | None,
    subdir: str | None,
    src_path: str | None,
    inferred: bool,
) -> int:
    """Insert one artifact_round row and return its id."""
    cur = conn.execute(
        "INSERT INTO artifact_round "
        "(artifact_id, round_number, project, subdir, src_path, created_at, inferred) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, round_number, project, subdir, src_path, created_at, 1 if inferred else 0),
    )
    if cur.lastrowid is None:
        raise sqlite3.Error("no rowid from artifact_round insert")
    return int(cur.lastrowid)


def _latest_index_row(
    conn: sqlite3.Connection, artifact_id: str
) -> tuple[str, str, str, int] | None:
    """Return the latest artifact_index row for one artifact_id."""
    row = conn.execute(
        "SELECT project, subdir, src_path, last_pushed FROM artifact_index "
        "WHERE artifact_id=? ORDER BY last_pushed DESC, rowid DESC LIMIT 1",
        (artifact_id,),
    ).fetchone()
    if row is None:
        return None
    return (str(row[0]), str(row[1]), str(row[2]), int(row[3]))


def _assign_threads_to_round(
    conn: sqlite3.Connection, thread_ids: Sequence[int], round_id: int
) -> None:
    """Stamp one round_id onto a set of legacy thread rows."""
    for thread_id in thread_ids:
        conn.execute("UPDATE thread SET round_id=? WHERE id=?", (round_id, thread_id))


def _backfill_legacy_rounds(conn: sqlite3.Connection) -> None:
    """Infer ordered rounds for legacy feedback using timestamp clues.

    Heuristic: if legacy thread timestamps exist on both sides of the latest
    artifact_index.last_pushed for an artifact, split them into one inferred
    pre-push round and one inferred current round. Otherwise collapse all
    legacy feedback for that artifact into a single inferred round.
    """
    artifact_rows = conn.execute(
        "SELECT DISTINCT artifact_id FROM artifact_index UNION SELECT DISTINCT artifact_id FROM thread"
    ).fetchall()
    for (artifact_id,) in artifact_rows:
        count_row = conn.execute(
            "SELECT COUNT(*) FROM artifact_round WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        round_count = int(count_row[0]) if count_row else 0
        unassigned = conn.execute(
            "SELECT id, created_at FROM thread WHERE artifact_id=? AND round_id IS NULL "
            "ORDER BY created_at ASC, id ASC",
            (artifact_id,),
        ).fetchall()
        latest = _latest_index_row(conn, artifact_id)
        if round_count:
            if unassigned:
                current_row = conn.execute(
                    "SELECT id FROM artifact_round WHERE artifact_id=? "
                    "ORDER BY round_number DESC, id DESC LIMIT 1",
                    (artifact_id,),
                ).fetchone()
                if current_row is not None:
                    _assign_threads_to_round(
                        conn, [int(thread_id) for thread_id, _ in unassigned], int(current_row[0])
                    )
            continue

        if latest is None:
            if not unassigned:
                continue
            first_ts = int(unassigned[0][1])
            round_id = _insert_round_row(
                conn, artifact_id, 1, first_ts, project=None, subdir=None, src_path=None, inferred=True
            )
            _assign_threads_to_round(conn, [int(thread_id) for thread_id, _ in unassigned], round_id)
            continue

        project, subdir, src_path, last_pushed = latest
        if not unassigned:
            _insert_round_row(
                conn, artifact_id, 1, last_pushed, project=project, subdir=subdir, src_path=src_path, inferred=True
            )
            continue

        old_ids = [int(thread_id) for thread_id, created_at in unassigned if int(created_at) < last_pushed]
        current_ids = [int(thread_id) for thread_id, created_at in unassigned if int(created_at) >= last_pushed]
        if old_ids:
            first_old_ts = min(int(created_at) for _, created_at in unassigned if int(created_at) < last_pushed)
            old_round_id = _insert_round_row(
                conn, artifact_id, 1, first_old_ts, project=project, subdir=subdir, src_path=src_path, inferred=True
            )
            current_round_id = _insert_round_row(
                conn, artifact_id, 2, last_pushed, project=project, subdir=subdir, src_path=src_path, inferred=True
            )
            _assign_threads_to_round(conn, old_ids, old_round_id)
            _assign_threads_to_round(conn, current_ids, current_round_id)
            continue

        round_id = _insert_round_row(
            conn, artifact_id, 1, last_pushed, project=project, subdir=subdir, src_path=src_path, inferred=True
        )
        _assign_threads_to_round(conn, [int(thread_id) for thread_id, _ in unassigned], round_id)


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Run idempotent schema backfills up to the current version."""
    row = conn.execute(
        "SELECT value FROM setting WHERE key='schema_version'"
    ).fetchone()
    current = int(row[0]) if row else 1
    if current >= SCHEMA_VERSION:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        if current < 2:
            _rebuild_upload_table_if_legacy(conn)
            _backfill_legacy_comments(conn)
        if current < 3:
            _ensure_round_table_if_legacy(conn)
            _backfill_legacy_rounds(conn)
        conn.execute(
            "INSERT INTO setting (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
    except sqlite3.Error:
        conn.rollback()
        raise
    else:
        conn.commit()


# ── setting k/v ───────────────────────────────────────────────────────


def setting_get(key: str) -> str | None:
    """Fetch a value from the `setting` table, or None if absent."""
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
    """Upsert (key, value) into the `setting` table."""
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
    """Remove a row from the `setting` table. No-op if absent."""
    conn = db_connect()
    try:
        conn.execute("DELETE FROM setting WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()


def record_push_round(
    artifact_id: str,
    project: str,
    subdir: str,
    src_path: str,
    *,
    created_at: int | None = None,
    inferred: bool = False,
) -> int:
    """Append one ordered review round for a pushed artifact_id."""
    conn = db_connect()
    try:
        round_id = _insert_round_row(
            conn,
            artifact_id,
            _next_round_number(conn, artifact_id),
            int(time.time()) if created_at is None else int(created_at),
            project=project,
            subdir=subdir,
            src_path=src_path,
            inferred=inferred,
        )
        conn.commit()
    finally:
        conn.close()
    return round_id


def round_history(artifact_id: str) -> list[dict[str, object]]:
    """Return ordered round metadata for one artifact_id."""
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT id, round_number, project, subdir, src_path, created_at, inferred "
            "FROM artifact_round WHERE artifact_id=? ORDER BY round_number ASC, id ASC",
            (artifact_id,),
        ).fetchall()
    finally:
        conn.close()
    current_id = int(rows[-1][0]) if rows else None
    return [
        {
            "id": int(row[0]),
            "round_number": int(row[1]),
            "label": f"Round {int(row[1])}",
            "project": row[2],
            "subdir": row[3],
            "src_path": row[4],
            "created_at": int(row[5]),
            "created_at_iso": iso_utc(int(row[5])),
            "inferred": bool(row[6]),
            "current": int(row[0]) == current_id,
        }
        for row in rows
    ]


def current_round(artifact_id: str) -> dict[str, object] | None:
    """Return the current round metadata for one artifact_id."""
    rounds = round_history(artifact_id)
    return rounds[-1] if rounds else None


# ── artifact resolution + fs helpers (preserved from legacy) ──────────


def ensure_root() -> None:
    """Create /tmp/claude-artifacts/ if missing. Idempotent."""
    ROOT.mkdir(parents=True, exist_ok=True)


def ensure_feedback_root() -> None:
    """Create durable feedback dirs. Idempotent."""
    FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def _check_name(value: str, kind: str) -> str:
    """Validate a project or subdir name against NAME_RE; raise if bad."""
    if not value or not NAME_RE.match(value):
        raise ValueError(
            f"invalid --{kind} {value!r}: must match {NAME_RE.pattern} "
            "(lowercase kebab-case + underscore)"
        )
    return value


def _check_artifact_id(value: str) -> str:
    """Validate a user-supplied --id against NAME_RE (plus one `/`).

    Same charset as project/subdir names, since artifact_id is embedded
    unescaped into an inline `<script>` json.dumps(...) call on the viewer
    and code pages (see _api_*_page). Rejects anything that could break out
    of that script block, e.g. `</script>`.
    """
    parts = value.split("/")
    if len(parts) > 2 or not all(NAME_RE.match(p) for p in parts):
        raise ValueError(
            f"invalid --id {value!r}: must match {NAME_RE.pattern}, "
            "optionally as <project>/<subdir>"
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


def resolve_artifact_id(url_path: str) -> tuple[str | None, str]:
    """Map a URL path to (artifact_id, sub_path).

    URL form: /<project>/<subdir>/<rest...>. Looks up (project, subdir) in
    artifact_index; falls back to "<project>/<subdir>". Returns (None, "") for
    URLs that do not address a staged artifact (root index, /_/... reserved
    paths, depth < 2). Preserved verbatim from legacy.
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


def _artifact_location(artifact_id: str) -> tuple[Path, str, str] | None:
    """Resolve (root_dir, project, subdir) for an artifact_id, or None.

    Looks up artifact_index first (trusted values from a real push); only
    falls back to splitting "<project>/<subdir>" when both halves pass
    NAME_RE, which blocks path traversal via an unvalidated artifact_id
    (NAME_RE forbids '.' and '/', so no ".." can survive the fallback).
    """
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT project, subdir FROM artifact_index "
                "WHERE artifact_id=? ORDER BY last_pushed DESC LIMIT 1",
                (artifact_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        row = None

    if row:
        project, subdir = row
    elif "/" in artifact_id:
        project, subdir = artifact_id.split("/", 1)
        if not (NAME_RE.match(project) and NAME_RE.match(subdir)):
            return None
    else:
        return None

    root = (ROOT / project / subdir).resolve()
    if not root.is_dir():
        return None
    return root, project, subdir


def staged_source_path(artifact_id: str, rel: str) -> Path | None:
    """Resolve a review `src` relpath to a real file under the staged root.

    Used by the /_/review image and code routes. Returns the resolved real
    path only if it stays inside the pushed artifact's staged directory
    (normalize + is_relative_to guard); returns None on traversal escape or
    missing file. See DESIGN.md section 10.4.
    """
    loc = _artifact_location(artifact_id)
    if loc is None:
        return None
    root = loc[0]
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def iso_utc(ts: int | None) -> str | None:
    """Format an epoch int as ISO-8601 UTC, or None. Preserved from legacy."""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def safe_upload_filename(name: str) -> str:
    """Sanitize an uploaded filename: basename, kebab-safe. Preserved."""
    base = Path(name).name or "unnamed"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base.lstrip(".") or "unnamed"
    return base[:200]


def upload_ext_ok(filename: str) -> tuple[bool, str]:
    """Validate extension against allowlist/blocklist. Preserved."""
    ext = Path(filename).suffix.lower()
    if ext in UPLOAD_EXT_BLOCK:
        return False, f"extension {ext!r} is blocked"
    if ext not in UPLOAD_EXT_ALLOW:
        return False, f"extension {ext!r} is not in allowlist"
    return True, ""


# Multipart boundary regex helpers (preserved from legacy).
_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)
_DISP_NAME_RE = re.compile(r'name="([^"]+)"')
_DISP_FILENAME_RE = re.compile(r'filename="([^"]*)"')


def parse_multipart_form(
    content_type: str, body: bytes
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Parse multipart/form-data into (fields, files). Preserved from legacy.

    stdlib-only replacement for the removed cgi.FieldStorage. Loads the whole
    body into memory; callers enforce MAX_REQUEST_BYTES first.
    """
    m = _BOUNDARY_RE.search(content_type)
    if not m:
        raise ValueError("Content-Type has no boundary")
    boundary = b"--" + m.group(1).encode("latin-1")
    fields: dict[str, str] = {}
    files: list[dict[str, object]] = []
    for raw in body.split(boundary):
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
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


# ── anchor validation (trust boundary) ────────────────────────────────


def _validate_fragment_selector(selector: dict[str, object]) -> dict[str, object]:
    """Validate + re-serialize a FragmentSelector. Raises ValueError."""
    value = selector.get("value")
    if not isinstance(value, str) or not FRAGMENT_XYWH_RE.match(value):
        raise ValueError("FragmentSelector value is malformed")
    clean: dict[str, object] = {"type": SELECTOR_FRAGMENT, "value": value}
    conforms_to = selector.get("conformsTo")
    if isinstance(conforms_to, str):
        clean["conformsTo"] = conforms_to
    return clean


def validate_anchor(anchor_kind: str, anchor_data_raw: str | None) -> Anchor:
    """Validate a client-supplied anchor and return a normalized Anchor.

    Defensive: never trust the raw JSON blob (see DESIGN.md section 10.2).
    Contract:
      - anchor_kind must be in ANCHOR_KINDS, else ValueError.
      - anchor_data_raw longer than MAX_ANCHOR_BYTES -> ValueError.
      - page: anchor_data_raw must be empty/None; Anchor.data is None.
      - image_region: object with a `selector` object whose `type` is
        SELECTOR_FRAGMENT (value matches FRAGMENT_XYWH_RE). Any other selector
        type (e.g. SvgSelector) is rejected: ValueError.
      - code_line: object with int `line` >= 1 and optional int `end_line`
        >= line. Else ValueError.
    Returns an Anchor holding the re-serialized, validated payload (unknown
    extra keys dropped). Raises ValueError with a caller-safe message on any
    violation.
    """
    if anchor_kind not in ANCHOR_KINDS:
        raise ValueError(f"invalid anchor_kind {anchor_kind!r}")
    if anchor_data_raw and len(anchor_data_raw.encode("utf-8")) > MAX_ANCHOR_BYTES:
        raise ValueError(f"anchor_data exceeds {MAX_ANCHOR_BYTES}B cap")

    if anchor_kind == ANCHOR_PAGE:
        if anchor_data_raw and anchor_data_raw.strip():
            raise ValueError("page anchor must not carry anchor_data")
        return Anchor(kind=ANCHOR_PAGE, data=None)

    if not anchor_data_raw or not anchor_data_raw.strip():
        raise ValueError(f"{anchor_kind} anchor requires anchor_data")
    try:
        parsed = json.loads(anchor_data_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"anchor_data is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("anchor_data must be a JSON object")

    if anchor_kind == ANCHOR_IMAGE_REGION:
        selector = parsed.get("selector")
        if not isinstance(selector, dict):
            raise ValueError("image_region anchor requires a selector object")
        sel_type = selector.get("type")
        if sel_type == SELECTOR_FRAGMENT:
            clean_selector = _validate_fragment_selector(selector)
        else:
            raise ValueError(f"unsupported selector type {sel_type!r}")
        return Anchor(kind=ANCHOR_IMAGE_REGION, data={"selector": clean_selector})

    # ANCHOR_CODE_LINE
    line = parsed.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        raise ValueError("code_line anchor requires integer line >= 1")
    data: dict[str, object] = {"line": line}
    end_line = parsed.get("end_line")
    if end_line is not None:
        if (
            not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < line
        ):
            raise ValueError("code_line end_line must be an integer >= line")
        data["end_line"] = end_line
    return Anchor(kind=ANCHOR_CODE_LINE, data=data)


def serialize_anchor(anchor: Anchor) -> str | None:
    """Serialize a validated Anchor back to the anchor_data column string.

    Returns None for a page anchor, else compact JSON. Inverse of the parse
    half of validate_anchor.
    """
    if anchor.kind == ANCHOR_PAGE:
        return None
    return json.dumps(anchor.data, separators=(",", ":"), sort_keys=True)


# ── thread + reply store ──────────────────────────────────────────────


def _store_uploads(
    conn: sqlite3.Connection, reply_id: int, files: Iterable[dict[str, object]]
) -> list[dict[str, object]]:
    """Write upload files to disk under UPLOAD_ROOT/<reply_id>/ + insert rows.

    Returns saved upload metadata dicts. Caller commits the transaction.
    """
    saved: list[dict[str, object]] = []
    files = list(files)
    if not files:
        return saved
    rdir = UPLOAD_ROOT / str(reply_id)
    rdir.mkdir(parents=True, exist_ok=True)
    for f in files:
        raw_name = str(f.get("filename") or "unnamed")
        safe = safe_upload_filename(raw_name)
        data: bytes = f.get("data", b"")  # type: ignore[assignment]  # multipart part payload is always bytes
        target = rdir / safe
        i = 1
        stem, suf = target.stem, target.suffix
        while target.exists():
            target = rdir / f"{stem}-{i}{suf}"
            i += 1
        target.write_bytes(data)
        mime, _ = mimetypes.guess_type(safe)
        conn.execute(
            "INSERT INTO upload "
            "(reply_id, filename, stored_path, mime, size, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (reply_id, safe, str(target), mime, len(data), int(time.time())),
        )
        saved.append({"filename": safe, "size": len(data), "mime": mime})
    return saved


def uploads_for_reply(reply_id: int) -> list[dict[str, object]]:
    """Fetch one reply's uploads, in the same shape GET /_/api/threads uses.

    Used by the create-thread/create-reply API handlers so their 201 bodies
    carry an `uploads` list matching DESIGN.md section 9, same shape as
    _thread_json's replies[].uploads. Empty list if the reply has none.
    """
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT id, reply_id, filename, stored_path, mime, size, "
            "created_at FROM upload WHERE reply_id=? ORDER BY id ASC",
            (reply_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        _upload_json(
            Upload(id=u[0], reply_id=u[1], filename=u[2],
                   stored_path=Path(u[3]), mime=u[4], size=u[5],
                   created_at=u[6])
        )
        for u in rows
    ]


def create_thread(
    artifact_id: str,
    sub_path: str,
    anchor: Anchor,
    body: str,
    author: str | None,
    files: Iterable[dict[str, object]],
) -> tuple[int, int]:
    """Open a thread with its first reply. Returns (thread_id, reply_id).

    Preconditions: anchor is already validated; body non-empty and within the
    length cap; files already passed upload_ext_ok + size caps. Author falls
    back to setting['author'] when None (preserved behavior). Inserts thread +
    reply + uploads in one transaction, writes upload bytes under
    UPLOAD_ROOT/<reply_id>/. If the bd_mirror setting is on, best-effort
    mirror_thread_create (never raises out).
    """
    if author is None:
        author = setting_get("author")
    now = int(time.time())
    anchor_data = serialize_anchor(anchor)
    conn = db_connect()
    try:
        round_meta = current_round(artifact_id)
        round_id = int(round_meta["id"]) if round_meta is not None else None
        cur = conn.execute(
            "INSERT INTO thread "
            "(artifact_id, sub_path, anchor_kind, anchor_data, resolved, "
            " author, created_at, round_id) VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
            (artifact_id, sub_path, anchor.kind, anchor_data, author, now, round_id),
        )
        thread_id = cur.lastrowid
        if thread_id is None:
            raise sqlite3.Error("no rowid from thread insert")
        reply_cur = conn.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, body, author, now),
        )
        reply_id = reply_cur.lastrowid
        if reply_id is None:
            raise sqlite3.Error("no rowid from reply insert")
        _store_uploads(conn, reply_id, files)
        conn.commit()
    finally:
        conn.close()

    if bd_mirror_enabled():
        reply = Reply(id=reply_id, thread_id=thread_id, body=body, author=author,
                       created_at=now, uploads=())
        thread_obj = Thread(
            id=thread_id, artifact_id=artifact_id, sub_path=sub_path,
            anchor=anchor, resolved=False, author=author, created_at=now,
            bd_ticket=None, replies=(reply,),
        )
        ticket = mirror_thread_create(thread_obj)
        if ticket:
            conn2 = db_connect()
            try:
                conn2.execute(
                    "UPDATE thread SET bd_ticket=? WHERE id=?",
                    (ticket, thread_id),
                )
                conn2.commit()
            finally:
                conn2.close()
    return thread_id, reply_id


def add_reply(
    thread_id: int,
    body: str,
    author: str | None,
    files: Iterable[dict[str, object]],
) -> int:
    """Append a reply to an existing thread. Returns reply_id.

    Preconditions as create_thread's reply half. Raises KeyError if thread_id
    is absent. If the thread has a bd_ticket, best-effort mirror_reply_add.
    """
    if author is None:
        author = setting_get("author")
    now = int(time.time())
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT id, bd_ticket FROM thread WHERE id=?", (thread_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"thread {thread_id} not found")
        bd_ticket = row[1]
        cur = conn.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) "
            "VALUES (?, ?, ?, ?)",
            (thread_id, body, author, now),
        )
        reply_id = cur.lastrowid
        if reply_id is None:
            raise sqlite3.Error("no rowid from reply insert")
        _store_uploads(conn, reply_id, files)
        conn.commit()
    finally:
        conn.close()

    if bd_ticket:
        reply = Reply(id=reply_id, thread_id=thread_id, body=body,
                       author=author, created_at=now, uploads=())
        mirror_reply_add(bd_ticket, reply)
    return reply_id


def set_resolved(thread_id: int, resolved: bool | None) -> bool:
    """Set or toggle a thread's resolved flag. Returns the new state.

    resolved None toggles; True/False sets. Raises KeyError if absent. If the
    thread has a bd_ticket, best-effort mirror_resolve_toggle.
    """
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT resolved, bd_ticket FROM thread WHERE id=?", (thread_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"thread {thread_id} not found")
        current, bd_ticket = bool(row[0]), row[1]
        new_state = (not current) if resolved is None else bool(resolved)
        conn.execute(
            "UPDATE thread SET resolved=? WHERE id=?",
            (1 if new_state else 0, thread_id),
        )
        conn.commit()
    finally:
        conn.close()
    if bd_ticket:
        mirror_resolve_toggle(bd_ticket, new_state)
    return new_state


def list_threads(artifact_id: str, sub_path: str) -> list[Thread]:
    """Return all threads for (artifact_id, sub_path) with replies + uploads.

    Ordered by thread.created_at, replies by reply.created_at. anchor_data is
    parsed into Anchor.data. Empty list if none.
    """
    conn = db_connect()
    try:
        thread_rows = conn.execute(
            "SELECT t.id, t.artifact_id, t.sub_path, t.anchor_kind, t.anchor_data, "
            "t.resolved, t.author, t.created_at, t.bd_ticket, t.round_id, "
            "ar.round_number, COALESCE(ar.inferred, 0) "
            "FROM thread t LEFT JOIN artifact_round ar ON ar.id=t.round_id "
            "WHERE t.artifact_id=? AND t.sub_path=? "
            "ORDER BY COALESCE(ar.round_number, 0) ASC, t.created_at ASC, t.id ASC",
            (artifact_id, sub_path),
        ).fetchall()
        threads: list[Thread] = []
        for (tid, aid, sp, kind, adata, resolved, author, created_at,
             bd_ticket, round_id, round_number, round_inferred) in thread_rows:
            anchor = Anchor(kind=kind, data=json.loads(adata) if adata else None)
            reply_rows = conn.execute(
                "SELECT id, body, author, created_at FROM reply "
                "WHERE thread_id=? ORDER BY created_at ASC",
                (tid,),
            ).fetchall()
            replies: list[Reply] = []
            for rid, body, r_author, r_created in reply_rows:
                upload_rows = conn.execute(
                    "SELECT id, reply_id, filename, stored_path, mime, "
                    "size, created_at FROM upload "
                    "WHERE reply_id=? ORDER BY id ASC",
                    (rid,),
                ).fetchall()
                uploads = [
                    Upload(id=u[0], reply_id=u[1], filename=u[2],
                           stored_path=Path(u[3]), mime=u[4], size=u[5],
                           created_at=u[6])
                    for u in upload_rows
                ]
                replies.append(
                    Reply(id=rid, thread_id=tid, body=body, author=r_author,
                          created_at=r_created, uploads=tuple(uploads))
                )
            threads.append(
                Thread(id=tid, artifact_id=aid, sub_path=sp, anchor=anchor,
                       resolved=bool(resolved), author=author,
                       created_at=created_at, bd_ticket=bd_ticket,
                       round_id=round_id, round_number=round_number,
                       round_inferred=bool(round_inferred), replies=tuple(replies))
            )
    finally:
        conn.close()
    return threads


def _upload_json(u: Upload) -> dict[str, object]:
    """Build the agent-facing JSON dict for one upload."""
    return {
        "id": u.id,
        "filename": u.filename,
        "stored_path": str(u.stored_path),
        "mime": u.mime,
        "size": u.size,
        "created_at": u.created_at,
        "created_at_iso": iso_utc(u.created_at),
    }


def _reply_json(r: Reply) -> dict[str, object]:
    """Build the agent-facing JSON dict for one reply."""
    return {
        "id": r.id,
        "body": r.body,
        "author": r.author,
        "created_at": r.created_at,
        "created_at_iso": iso_utc(r.created_at),
        "uploads": [_upload_json(u) for u in r.uploads],
    }


def _thread_json(t: Thread) -> dict[str, object]:
    """Build the agent-facing JSON dict for one thread (DESIGN.md section 8)."""
    return {
        "id": t.id,
        "sub_path": t.sub_path,
        "anchor_kind": t.anchor.kind,
        "anchor": t.anchor.data,
        "resolved": t.resolved,
        "author": t.author,
        "created_at": t.created_at,
        "created_at_iso": iso_utc(t.created_at),
        "bd_ticket": t.bd_ticket,
        "round_id": t.round_id,
        "round_number": t.round_number,
        "round_inferred": t.round_inferred,
        "round_label": (f"Round {t.round_number}" if t.round_number else None),
        "replies": [_reply_json(r) for r in t.replies],
    }


def feedback_dump(artifact_id: str) -> dict[str, object]:
    """Build the full agent-facing JSON payload for one artifact.

    Shape per DESIGN.md section 8: {artifact_id, pushes[], threads[], comments[]}
    where `threads` is canonical (anchor parsed, resolved bool, replies with
    uploads) and `comments` is the deprecated flattened page-level convenience.
    Used by cmd_feedback and reusable by tests.
    """
    conn = db_connect()
    try:
        idx_rows = conn.execute(
            "SELECT project, subdir, src_path, last_pushed FROM artifact_index "
            "WHERE artifact_id=?",
            (artifact_id,),
        ).fetchall()
        sub_path_rows = conn.execute(
            "SELECT DISTINCT sub_path FROM thread WHERE artifact_id=? "
            "ORDER BY sub_path ASC",
            (artifact_id,),
        ).fetchall()
    finally:
        conn.close()

    rounds = round_history(artifact_id)
    current = rounds[-1] if rounds else None

    threads: list[Thread] = []
    for (sub_path,) in sub_path_rows:
        threads.extend(list_threads(artifact_id, sub_path))
    threads.sort(key=lambda t: (t.round_number or 0, t.sub_path, t.created_at))

    comments_json: list[dict[str, object]] = []
    for t in threads:
        if t.anchor.kind != ANCHOR_PAGE:
            continue
        for r in t.replies:
            comments_json.append(
                {
                    "id": r.id,
                    "thread_id": t.id,
                    "sub_path": t.sub_path,
                    "body": r.body,
                    "author": r.author,
                    "created_at": r.created_at,
                    "created_at_iso": iso_utc(r.created_at),
                    "resolved": t.resolved,
                    "round_id": t.round_id,
                    "round_number": t.round_number,
                    "round_inferred": t.round_inferred,
                    "uploads": [_upload_json(u) for u in r.uploads],
                }
            )

    return {
        "artifact_id": artifact_id,
        "current_round": current,
        "rounds": rounds,
        "pushes": [
            {
                "project": r[0], "subdir": r[1], "src_path": r[2],
                "last_pushed": r[3], "last_pushed_iso": iso_utc(r[3]),
            }
            for r in idx_rows
        ],
        "threads": [_thread_json(t) for t in threads],
        "comments": comments_json,
    }


# ── optional bd mirror (flag-gated, never a hard dependency) ──────────


def bd_mirror_enabled() -> bool:
    """True only if setting['bd_mirror'] is on AND the `bd` CLI is on PATH.

    Absence of bd is a no-op, never an error. See DESIGN.md section 11.
    """
    return setting_get("bd_mirror") == "1" and shutil.which("bd") is not None


def _bd_beads_dir(artifact_id: str) -> str | None:
    """Resolve the ~/.beads-hub board dir for the project that pushed
    artifact_id, via `agent-workbench bd path <project>`. None on any
    failure (missing CLI, unknown project, non-zero exit)."""
    if not AGENT_WORKBENCH_CLI.is_file():
        return None
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT project FROM artifact_index WHERE artifact_id=? "
                "ORDER BY last_pushed DESC LIMIT 1",
                (artifact_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        row = None
    if not row:
        return None
    try:
        proc = subprocess.run(
            [str(AGENT_WORKBENCH_CLI), "bd", "path", row[0]],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _bd_run(beads_dir: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a bd CLI invocation against beads_dir. None on any failure."""
    env = os.environ.copy()
    env["BEADS_DIR"] = beads_dir
    try:
        return subprocess.run(
            ["bd", *args], check=False, capture_output=True, text=True,
            timeout=15, env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _artifact_id_for_thread(thread_id: int) -> str | None:
    """Look up a thread's artifact_id. None if the thread is gone or on
    any db error (best-effort, used only by the bd mirror)."""
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT artifact_id FROM thread WHERE id=?", (thread_id,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _artifact_id_for_bd_ticket(bd_ticket: str) -> str | None:
    """Look up the artifact_id of the thread carrying bd_ticket. None if
    absent or on any db error (best-effort, used only by the bd mirror)."""
    try:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT artifact_id FROM thread WHERE bd_ticket=? LIMIT 1",
                (bd_ticket,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def mirror_thread_create(thread: Thread) -> str | None:
    """Best-effort create a bd ticket for a new thread. Returns ticket id/None.

    No-op returning None if bd_mirror_enabled() is False. Any subprocess
    failure logs a warning and returns None; never raises.
    """
    if not bd_mirror_enabled():
        return None
    # ponytail: assumes `bd create <title>` prints the new ticket id as the
    # first whitespace-separated token of stdout. Reasonable, unverified
    # against a live bd CLI (best-effort mirror only; never blocks a write).
    beads_dir = _bd_beads_dir(thread.artifact_id)
    if not beads_dir:
        return None
    first_body = thread.replies[0].body if thread.replies else ""
    title = (
        f"[review] {thread.artifact_id} {thread.sub_path} "
        f"({thread.anchor.kind}): {first_body[:80]}"
    )
    proc = _bd_run(beads_dir, ["create", title])
    if proc is None or proc.returncode != 0:
        log.warning("bd mirror create failed for thread %s", thread.id)
        return None
    tokens = proc.stdout.strip().split()
    return tokens[0] if tokens else None


def mirror_reply_add(bd_ticket: str, reply: Reply) -> None:
    """Best-effort append a reply as a bd comment. No-op if disabled/absent."""
    if not bd_mirror_enabled():
        return
    artifact_id = _artifact_id_for_thread(reply.thread_id)
    if not artifact_id:
        return
    beads_dir = _bd_beads_dir(artifact_id)
    if not beads_dir:
        return
    proc = _bd_run(beads_dir, ["comment", bd_ticket, reply.body])
    if proc is None or proc.returncode != 0:
        log.warning("bd mirror comment failed for ticket %s", bd_ticket)


def mirror_resolve_toggle(bd_ticket: str, resolved: bool) -> None:
    """Best-effort close/reopen the mirrored bd ticket. No-op if disabled."""
    if not bd_mirror_enabled():
        return
    artifact_id = _artifact_id_for_bd_ticket(bd_ticket)
    if not artifact_id:
        return
    beads_dir = _bd_beads_dir(artifact_id)
    if not beads_dir:
        return
    verb = "close" if resolved else "reopen"
    proc = _bd_run(beads_dir, [verb, bd_ticket])
    if proc is None or proc.returncode != 0:
        log.warning("bd mirror %s failed for ticket %s", verb, bd_ticket)


# ── index regeneration (preserved) ───────────────────────────────────


def _entry_meta(entry: Path) -> tuple[str, int, str]:
    """Return (kind, file_count, mtime_iso) for an entry."""
    if entry.is_symlink():
        target = os.readlink(entry)
        kind = f"symlink &rarr; {html.escape(target)}"
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


def _gallery_href(project: str, entry_name: str) -> str | None:
    """Return the /_/review gallery URL for an entry if it holds any image
    files, else None. Looks up the entry's artifact_id via artifact_index."""
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT artifact_id FROM artifact_index WHERE project=? AND subdir=?",
            (project, entry_name),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    entry = ROOT / project / entry_name
    has_image = any(
        p.is_file() and p.suffix.lower() in IMAGE_EXT for p in entry.rglob("*")
    )
    if not has_image:
        return None
    return f"/_/review?artifact={urllib.parse.quote(row[0])}"


def regenerate_index() -> None:
    """Rebuild /tmp/claude-artifacts/index.html tile grid. Atomic write.

    Preserved from legacy; tiles now link into the /_/review gallery route for
    image-bearing artifacts. See DESIGN.md section 5.
    """
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

    body_parts: list[str] = [render_page_header("artifact-serve")]
    body_parts.append(
        f"<div class='meta'>port <code>{port}</code> &middot; "
        f"{len(projects)} project(s) &middot; {total_entries} entry(ies) &middot; "
        f"regenerated {now}</div>"
    )

    if not projects:
        body_parts.append(
            "<div class='empty'>No artifacts pushed yet. Run "
            "<code>artifact-serve.py push --project NAME --src PATH</code>.</div>"
        )

    for project_name, entries in projects:
        body_parts.append(f"<h2 style='padding:0 var(--space-6)'>{html.escape(project_name)}</h2>")
        if not entries:
            body_parts.append("<div class='empty'>(empty)</div>")
            continue
        body_parts.append("<div class='grid'>")
        for entry in entries:
            kind, count, mtime_iso = _entry_meta(entry)
            href = f"/{html.escape(project_name)}/{html.escape(entry.name)}/"
            gallery = _gallery_href(project_name, entry.name)
            gallery_html = (
                f"<a class='gallery-link' href='{gallery}'>review gallery &rarr;</a>"
                if gallery else ""
            )
            body_parts.append(
                f"<a class='card tile' href='{href}'>"
                f"<h3>{html.escape(entry.name)}</h3>"
                f"<div class='sub'>{kind}</div>"
                f"<div class='stats'>{count} file(s) &middot; {mtime_iso}</div>"
                f"{gallery_html}"
                "</a>"
            )
        body_parts.append("</div>")

    # No manual theme-toggle button here (include_theme_toggle=False): this
    # file is served as a plain static page, so send_head's
    # injected_page_widget() splices the feedback widget (and its own toggle
    # button) in before </body> same as any other served HTML -- adding a
    # second button here would double it up. .grid/.empty/.meta are
    # index-only layout, not shared by any other page, so they stay local to
    # this head_extra rather than living in assets/css/theme.css.
    html_out = render_page(
        title="artifact-serve",
        head_extra=(
            "<style>"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:var(--space-3);padding:var(--space-6)}"
            ".empty{color:var(--text-muted);font-style:italic;padding:var(--space-6)}"
            ".meta{color:var(--text-muted);font-size:14px;padding:0 var(--space-6)}"
            "</style>"
        ),
        body_html="".join(body_parts),
        include_theme_toggle=False,
    )
    atomic_write(INDEX_FILE, html_out)


# ── review page templates (inlined, like the legacy widget) ───────────

# Vendored asset URLs the review pages load. Real files under ASSETS_ROOT,
# served by the daemon under /_/assets/.
OSD_SCRIPT_URL = "/_/assets/openseadragon/openseadragon.min.js"
ANNOTORIOUS_SCRIPT_URL = "/_/assets/annotorious/annotorious-openseadragon.min.js"
ANNOTORIOUS_CSS_URL = "/_/assets/annotorious/annotorious.min.css"
THEME_CSS_URL = "/_/assets/css/theme.css"

# Lodestar-derived design tokens (colors, type, spacing, radius). Page-owning
# templates load them via assets/css/theme.css, linked into <head> by
# render_page() below. The page-comment widget injected into arbitrary
# pushed HTML can't rely on that external stylesheet being present on a page
# it doesn't own, so it keeps its own scoped copy, baked at module load time
# via search-replace on the __THEME_TOGGLE_CSS__ etc. tokens (same mechanism
# the legacy widget used for __CSS__/__JS__  -  avoids a .format() call
# colliding with the CSS/JS braces).
#
# Three modes, same custom-property names in every scope so every existing
# var(--...) call site just works:
#   - :root (no explicit choice = AUTO): defaults to dark, swaps to light
#     inside @media (prefers-color-scheme: light) so the app follows the OS.
#   - html[data-theme="dark"|"light"]: an explicit user choice, applied by
#     the pre-paint script from localStorage. Wins over the media query
#     because the selector carries more specificity, regardless of source
#     order (see _THEME_TOGGLE_JS + _THEME_PREPAINT_SCRIPT below).

# Color tokens only (not font/space/radius, which never change with theme).
# Mapped from the Lodestar dark-graphite default and light alternate.
_COLOR_TOKENS_DARK = r"""
  --bg-base: #191b1e;
  --bg-elevated: #212429;
  --bg-overlay: #131518;
  --text-primary: #c4c7ca;
  --text-secondary: #9aa0a7;
  --text-muted: #767c84;
  --border: #2c3137;
  --border-strong: #3b4148;
  --accent: #5a9bc9;
  --accent-hover: #78b1d8;
  --on-accent: #12161b;
  --status-resolved: #6e8a70;
  --status-unresolved: #b07a3d;
  --status-danger: #be6b5b;
  --shadow-overlay: 0 18px 48px rgba(0, 0, 0, 0.24);
"""

_COLOR_TOKENS_LIGHT = r"""
  --bg-base: #f7f6f3;
  --bg-elevated: #ffffff;
  --bg-overlay: #f0efeb;
  --text-primary: #1c1b18;
  --text-secondary: #55524a;
  --text-muted: #8a857a;
  --border: #ddd9d0;
  --border-strong: #c4bfb2;
  --accent: #86603c;
  --accent-hover: #6b4c30;
  --on-accent: #fbf8f3;
  --status-resolved: #4f6951;
  --status-unresolved: #8f622d;
  --status-danger: #a45344;
  --shadow-overlay: 0 18px 48px rgba(28, 27, 24, 0.12);
"""

# Theme toggle: one fixed-position control, present on every page type
# (gallery, viewer, code view, project index, and the widget injected into
# arbitrary pushed pages) so switching modes anywhere is visible everywhere.
# Default is dark-graphite; the toggle flips dark-graphite <-> light and keeps
# the shared choice in localStorage under _THEME_STORAGE_KEY.
_THEME_STORAGE_KEY = "lodestar-theme"

_THEME_TOGGLE_CSS = r"""
.theme-toggle {
  position: fixed; top: var(--space-3); right: var(--space-3); z-index: 1000;
  background: var(--bg-elevated); color: var(--text-secondary);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; font-size: 12px; font-family: var(--font-ui);
  cursor: pointer; line-height: 1.4;
}
.theme-toggle:hover { border-color: var(--border-strong); color: var(--text-primary); }
"""

_THEME_TOGGLE_HTML = (
    # No static aria-label: the button's own textContent (set by render() in
    # _THEME_TOGGLE_JS) already doubles as its accessible name and updates on
    # every click, so screen readers hear the current mode too.
    '<button type="button" class="theme-toggle" '
    'id="artifact-serve-theme-toggle"></button>'
)

# Pre-paint: apply a stored explicit theme before first paint. With no saved
# value, the stylesheet's dark-graphite :root tokens already match the
# approved default.
_THEME_PREPAINT_SCRIPT = (
    "<script>try{var t=localStorage.getItem(" + json.dumps(_THEME_STORAGE_KEY)
    + ");if(t==='light'||t==='dark-graphite')"
    "document.documentElement.setAttribute('data-theme',t);}catch(e){}</script>"
)

# Toggle + persist, shared verbatim by every page type. __STORAGE_KEY__ is
# substituted at module load (same search-replace idiom used by the widget's
# own CSS/JS below).
_THEME_TOGGLE_JS_RAW = r"""
(function(){
  var KEY = '__STORAGE_KEY__';
  var THEMES = ['dark-graphite', 'light'];
  var LABELS = {
    'dark-graphite': 'Theme: Dark graphite',
    light: 'Theme: Light',
  };
  function current(){
    try {
      var saved = localStorage.getItem(KEY);
      return THEMES.indexOf(saved) >= 0 ? saved : 'dark-graphite';
    } catch (e) {
      return 'dark-graphite';
    }
  }
  function apply(mode){
    document.documentElement.setAttribute('data-theme', mode);
  }
  function render(btn, mode){ btn.textContent = LABELS[mode] || mode; }
  var btn = document.getElementById('artifact-serve-theme-toggle');
  if (!btn) return;
  apply(current());
  render(btn, current());
  btn.addEventListener('click', function(){
    var next = current() === 'dark-graphite' ? 'light' : 'dark-graphite';
    apply(next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
    render(btn, next);
  });
})();
"""
_THEME_TOGGLE_JS = _THEME_TOGGLE_JS_RAW.replace(
    "__STORAGE_KEY__", _THEME_STORAGE_KEY
)

# Button + script together, for the pages that own their own <head> (gallery,
# viewer, code, project index). The widget (injected into arbitrary pushed
# HTML it doesn't own) wires the same two constants in separately, next to
# its own script tag; see PAGE_COMMENT_WIDGET below.
_THEME_TOGGLE_BLOCK = (
    _THEME_TOGGLE_HTML + "\n<script>" + _THEME_TOGGLE_JS + "</script>"
)

def render_page(
    title: str,
    head_extra: str = "",
    body_html: str = "",
    *,
    include_theme_toggle: bool = True,
) -> str:
    """Assemble one full themed HTML page shared by every artifact-serve page.

    Wraps body_html in the standard doctype/head/body shell: the pre-paint
    theme script, the shared assets/css/theme.css stylesheet, any
    page-specific head_extra (extra <link>/<style> tags), and -- unless
    include_theme_toggle is False -- the theme-toggle button. title is
    html.escape'd here; callers must pass the raw, unescaped title.
    """
    toggle = _THEME_TOGGLE_BLOCK if include_theme_toggle else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        + _THEME_PREPAINT_SCRIPT
        + f"<title>{html.escape(title)}</title>"
        + f'<link rel="stylesheet" href="{THEME_CSS_URL}">'
        + head_extra
        + "</head><body>"
        + toggle
        + body_html
        + "</body></html>"
    )


def render_page_header(title_html: str, subline_html: str = "") -> str:
    """Shared page-header block used by every page type except the viewer.

    title_html/subline_html are caller-supplied HTML fragments that must
    already be escaped/safe, matching the convention used elsewhere in this
    file (callers html.escape user-controlled strings before passing them).
    """
    return f'<header class="page-header"><h1>{title_html}</h1>{subline_html}</header>'




def _plural(count: int, noun: str) -> str:
    """Return a simple count label, e.g. 1 image / 2 images."""
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _raw_artifact_href(project: str, subdir: str, rel_path: str) -> str:
    """Return the raw staged-file URL for one artifact-relative path."""
    return (
        f"/{urllib.parse.quote(project)}/{urllib.parse.quote(subdir)}"
        f"/{urllib.parse.quote(rel_path)}"
    )


def _review_href(artifact_id: str, rel_path: str, *, is_dir: bool = False) -> str:
    """Return the owned review route for a file or child directory."""
    if is_dir:
        return (
            f"/_/review?artifact={urllib.parse.quote(artifact_id)}"
            f"&path={urllib.parse.quote(rel_path)}"
        )
    ext = Path(rel_path).suffix.lower()
    view = "image" if ext in IMAGE_EXT else "code" if ext in CODE_EXT else ""
    if not view:
        return ""
    return (
        f"/_/review?artifact={urllib.parse.quote(artifact_id)}"
        f"&src={urllib.parse.quote(rel_path)}&view={view}"
    )


def _thread_counts(artifact_id: str, sub_path: str) -> tuple[int, int]:
    """Return (open_threads, total_threads) for one exact review target."""
    threads = list_threads(artifact_id, sub_path)
    total_threads = len(threads)
    open_threads = sum(1 for thread in threads if not thread.resolved)
    return open_threads, total_threads


def _subtree_thread_counts(artifact_id: str, directory: str) -> tuple[int, int]:
    """Return (open_threads, total_threads) for one review path subtree."""
    conn = db_connect()
    try:
        if directory:
            prefix = directory.rstrip("/")
            rows = conn.execute(
                "SELECT resolved FROM thread WHERE artifact_id=? "
                "AND (sub_path=? OR sub_path LIKE ?)",
                (artifact_id, prefix, prefix + "/%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT resolved FROM thread WHERE artifact_id=?",
                (artifact_id,),
            ).fetchall()
    finally:
        conn.close()
    total_threads = len(rows)
    open_threads = sum(1 for (resolved,) in rows if not resolved)
    return open_threads, total_threads


def _build_review_listing(artifact_id: str, directory: str = "") -> ReviewListing:
    """Return the owned review queue data for one artifact directory."""
    loc = _artifact_location(artifact_id)
    if loc is None:
        return ReviewListing(directory=directory)
    root, project, subdir = loc
    listing_dir = (root / directory).resolve()
    if not listing_dir.is_relative_to(root) or not listing_dir.is_dir():
        return ReviewListing(directory=directory)

    items: list[ReviewItem] = []
    folder_count = 0
    image_count = 0
    code_count = 0
    for entry in sorted(
        listing_dir.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())
    ):
        if entry.name.startswith("."):
            continue
        rel_path = entry.relative_to(root).as_posix()
        if entry.is_dir():
            folder_count += 1
            items.append(
                ReviewItem(
                    name=entry.name,
                    rel_path=rel_path,
                    kind="folder",
                    href=_review_href(artifact_id, rel_path, is_dir=True),
                    preview_src=None,
                    open_threads=0,
                    total_threads=0,
                )
            )
            continue
        ext = entry.suffix.lower()
        if ext not in IMAGE_EXT and ext not in CODE_EXT:
            continue
        open_threads, total_threads = _thread_counts(artifact_id, rel_path)
        kind = "image" if ext in IMAGE_EXT else "code"
        if kind == "image":
            image_count += 1
        else:
            code_count += 1
        items.append(
            ReviewItem(
                name=entry.name,
                rel_path=rel_path,
                kind=kind,
                href=_review_href(artifact_id, rel_path),
                preview_src=(
                    _raw_artifact_href(project, subdir, rel_path)
                    if kind == "image"
                    else None
                ),
                open_threads=open_threads,
                total_threads=total_threads,
            )
        )

    open_threads, total_threads = _subtree_thread_counts(artifact_id, directory)
    return ReviewListing(
        directory=directory,
        items=tuple(items),
        folder_count=folder_count,
        image_count=image_count,
        code_count=code_count,
        open_threads=open_threads,
        total_threads=total_threads,
    )


def _render_review_queue(
    listing: ReviewListing, *, active_rel: str = "", active_href: str = ""
) -> str:
    """Render the shared owned-page review queue."""
    cards: list[str] = []
    for item in listing.items:
        active = item.rel_path == active_rel or (
            not active_rel and active_href and item.href == active_href
        )
        item_class = "qitem active" if active else "qitem"
        kind_label = {"folder": "DIR", "image": "IMG", "code": "CODE"}[item.kind]
        if item.kind == "folder":
            state_html = '<span class="state review">browse</span>'
            count_html = '<div class="count">dir<small>open</small></div>'
        elif item.open_threads:
            state_html = (
                f'<span class="state open">{_plural(item.open_threads, "open thread")}</span>'
            )
            count_html = (
                f'<div class="count">{item.total_threads}<small>threads</small></div>'
            )
        elif item.total_threads:
            state_html = '<span class="state resolved">resolved</span>'
            count_html = (
                f'<div class="count">{item.total_threads}<small>threads</small></div>'
            )
        else:
            state_html = f'<span class="state review">{item.kind}</span>'
            count_html = '<div class="count">0<small>threads</small></div>'
        cards.append(
            f'<a class="{item_class}" href="{item.href}">'
            f'<span class="typebox">{kind_label}</span>'
            f'<div><div class="qname">{html.escape(item.name)}</div>'
            f'<div class="qmeta">{state_html}'
            f'<span class="mono">{html.escape(item.rel_path or ".")}</span></div></div>'
            f'{count_html}</a>'
        )
    if not cards:
        cards.append('<p class="empty">no reviewable items in this path</p>')

    detail_bits = [
        _plural(listing.image_count, "image"),
        _plural(listing.code_count, "code file"),
    ]
    if listing.folder_count:
        detail_bits.append(_plural(listing.folder_count, "folder"))
    path_label = html.escape(listing.directory or ".")
    return (
        '<aside class="queue" aria-label="Review queue">'
        '<div class="queue-head"><span class="title">Work queue</span>'
        f'<span class="progress">{_plural(listing.open_threads, "open thread")}</span></div>'
        '<div class="queue-tools">'
        f'<span>path {path_label}</span>'
        f'<span>{html.escape(" · ".join(detail_bits))}</span></div>'
        f'<div class="queue-list">{"".join(cards)}</div></aside>'
    )


def _render_round_history_section(artifact_id: str) -> str:
    """Render one shared round-history block for owned review pages."""
    rounds = round_history(artifact_id)
    if not rounds:
        return (
            '<section class="review-rail-section"><h2>Round history</h2>'
            '<p class="empty">no review rounds recorded yet</p></section>'
        )
    items: list[str] = []
    for round_meta in reversed(rounds):
        state = "unresolved" if round_meta["current"] else "resolved"
        state_text = "current" if round_meta["current"] else "history"
        inferred = " · inferred" if round_meta["inferred"] else ""
        items.append(
            '<div class="review-list-item">'
            f'<span>{html.escape(str(round_meta["label"]))}{inferred}</span>'
            f'<span class="thread-badge {state}">{state_text}</span></div>'
        )
    current = rounds[-1]
    return (
        '<section class="review-rail-section"><h2>Round history</h2>'
        f'<p>Current review uses {html.escape(str(current["label"]))}. '
        'Re-pushing the same artifact_id opens the next round.</p>'
        f'<div class="review-list">{"".join(items)}</div></section>'
    )


def _render_owned_review_shell(
    *,
    title: str,
    subtitle_html: str,
    quiet_html: str,
    queue_html: str,
    main_html: str,
    rail_html: str,
    head_extra: str = "",
    shell_class: str = "inspector",
) -> bytes:
    """Wrap one owned /_/review page in the approved Lodestar shell."""
    body_html = (
        '<div class="review-shell">'
        '<header class="topbar">'
        f'<div class="caption"><b>Artifact review</b><span>{subtitle_html}</span></div>'
        '<div class="top-actions">'
        f'<span class="quiet">{quiet_html}</span>{_THEME_TOGGLE_BLOCK}</div>'
        '</header>'
        f'<div class="app {shell_class}">'
        + queue_html
        + main_html
        + rail_html
        + '</div></div>'
    )
    return render_page(
        title=title,
        head_extra=head_extra,
        body_html=body_html,
        include_theme_toggle=False,
    ).encode("utf-8")


def render_gallery_page(artifact_id: str, sub_path: str) -> bytes:
    """Render the owned review landing page for one staged artifact path."""
    listing = _build_review_listing(artifact_id, sub_path)
    title = f"{artifact_id} / {sub_path or '.'}"
    subtitle_html = html.escape(f"{artifact_id}, gallery, {sub_path or '.'}")
    quiet_html = html.escape(
        f"{_plural(listing.open_threads, 'open thread')} · "
        f"{_plural(listing.total_threads, 'thread')} in path"
    )
    queue_html = _render_review_queue(listing)

    folders = [item for item in listing.items if item.kind == "folder"]
    images = [item for item in listing.items if item.kind == "image"]
    code_files = [item for item in listing.items if item.kind == "code"]

    def render_card(item: ReviewItem) -> str:
        if item.preview_src:
            thumb = (
                f'<div class="review-thumb"><img src="{item.preview_src}" '
                f'loading="lazy" alt="{html.escape(item.name)}"></div>'
            )
        else:
            label = "folder" if item.kind == "folder" else "code"
            thumb = f'<div class="review-thumb review-thumb-label">{label}</div>'
        if item.kind == "folder":
            meta = '<span class="state review">browse</span><span class="mono">open path</span>'
            note = "Drill into a child path without leaving the owned review shell."
        elif item.open_threads:
            meta = (
                f'<span class="state open">{_plural(item.open_threads, "open thread")}</span>'
                f'<span class="mono">{_plural(item.total_threads, "thread")}</span>'
            )
            note = "Continue review where unresolved feedback already exists."
        elif item.total_threads:
            meta = (
                f'<span class="state resolved">resolved</span>'
                f'<span class="mono">{_plural(item.total_threads, "thread")}</span>'
            )
            note = "Review history stays attached even after the thread closes."
        else:
            meta = f'<span class="state review">{item.kind}</span><span class="mono">new review</span>'
            note = "Open the owned viewer and start the first thread from there."
        return (
            f'<a class="review-card" href="{item.href}">{thumb}'
            '<div class="review-card-copy">'
            f'<div class="review-card-title">{html.escape(item.name)}</div>'
            f'<div class="review-card-meta">{meta}</div>'
            f'<div class="review-card-note">{note}</div>'
            '</div></a>'
        )

    sections: list[str] = []
    if folders:
        sections.append(
            '<section class="review-section">'
            '<div class="review-section-head"><div><h2>Browse deeper</h2>'
            '<p>Child paths stay on the owned review route instead of falling back to the raw server.</p>'
            '</div></div>'
            f'<div class="review-card-grid">{"".join(render_card(item) for item in folders)}</div>'
            '</section>'
        )
    if images:
        sections.append(
            '<section class="review-section">'
            '<div class="review-section-head"><div><h2>Image review</h2>'
            '<p>Launch the Inspector viewer with real region threads and zoomable source pixels.</p>'
            '</div></div>'
            f'<div class="review-card-grid">{"".join(render_card(item) for item in images)}</div>'
            '</section>'
        )
    if code_files:
        sections.append(
            '<section class="review-section">'
            '<div class="review-section-head"><div><h2>Code review</h2>'
            '<p>Open per-line review without leaving the shared queue and thread shell.</p>'
            '</div></div>'
            f'<div class="review-card-grid">{"".join(render_card(item) for item in code_files)}</div>'
            '</section>'
        )
    if not sections:
        sections.append(
            '<section class="review-section"><p class="empty">no reviewable images or code files in this path</p></section>'
        )

    visible_items = listing.image_count + listing.code_count + listing.folder_count
    summary_html = (
        '<section class="summary">'
        '<div><h3>Owned review landing</h3>'
        '<div class="summary-line">Use the app shell to browse images, code, and open feedback from one queue.</div>'
        '</div>'
        '<div class="facts">'
        f'<div class="fact"><span>Artifact</span>{html.escape(artifact_id)}</div>'
        f'<div class="fact"><span>Path</span>{html.escape(sub_path or ".")}</div>'
        f'<div class="fact"><span>Visible items</span>{visible_items}</div>'
        f'<div class="fact"><span>Open threads</span>{listing.open_threads}</div>'
        '</div></section>'
    )
    main_html = (
        '<main class="hero review-gallery-main" aria-label="Owned review landing">'
        + summary_html
        + '<div class="review-sections">'
        + ''.join(sections)
        + '</div></main>'
    )

    open_items = [item for item in listing.items if item.open_threads]
    open_list = ''.join(
        f'<a class="review-list-item" href="{item.href}"><span>{html.escape(item.name)}</span>'
        f'<span class="thread-badge unresolved">{_plural(item.open_threads, "open thread")}</span></a>'
        for item in open_items
    )
    if not open_list:
        open_list = '<p class="empty">no open threads in this path</p>'
    rail_html = (
        '<aside class="rail" aria-label="Path review summary">'
        f'<div class="rail-head"><span class="title">Path summary</span><span class="progress">{html.escape(sub_path or ".")}</span></div>'
        '<div class="threads">'
        '<section class="review-rail-section">'
        '<h2>What lives here</h2>'
        f'<p>{_plural(listing.image_count, "image")}, {_plural(listing.code_count, "code file")}, and {_plural(listing.folder_count, "folder")} stay inside the same owned review shell.</p>'
        '</section>'
        '<section class="review-rail-section">'
        '<h2>Open items</h2>'
        f'<div class="review-list">{open_list}</div>'
        '</section>'
        + _render_round_history_section(artifact_id) +
        '</div></aside>'
    )
    return _render_owned_review_shell(
        title=title,
        subtitle_html=subtitle_html,
        quiet_html=quiet_html,
        queue_html=queue_html,
        main_html=main_html,
        rail_html=rail_html,
    )


def _browse_tile(name: str, href: str, thumb_src: str | None) -> str:
    """One directory-browse gallery tile.

    thumb_src renders an <img> thumbnail (an image file); None renders a
    caption-only tile (a subdirectory or a non-image file).
    """
    thumb = (
        f'<img src="{thumb_src}" loading="lazy" alt="{html.escape(name)}">'
        if thumb_src else ""
    )
    return (
        f'<a class="card gallery-tile" href="{href}">{thumb}'
        f'<div class="gallery-caption">{html.escape(name)}</div></a>'
    )


def render_directory_gallery(url_path: str, fs_dir: Path) -> bytes:
    """Render a themed gallery for a browsed directory.

    Used by do_GET in place of the raw SimpleHTTPRequestHandler autoindex, so
    browsing a pushed directory never dead-ends on bare file links. Reuses
    the same render_page()-built gallery shell (theme, tile CSS) as
    render_gallery_page. Lists fs_dir's direct children only (one level,
    matching how a directory listing normally behaves); each becomes one
    tile:
      - a subdirectory links to its own URL, so nested browsing recurses
        through this same renderer instead of ever falling back to raw
        autoindex;
      - an image file links into the OSD deep-zoom + Annotorious viewer
        (`view=image`) when it resolves to a real pushed artifact via
        resolve_artifact_id, else falls back to its raw URL;
      - a CODE_EXT file links into the per-line code view (`view=code`)
        under the same condition, else falls back to raw.
    A dotted or otherwise NAME_RE-invalid child name (e.g. a legacy file
    dropped in outside `push`) cannot carry a trusted artifact_id, so it
    degrades to a plain raw link rather than being denied a link entirely.
    """
    base = url_path if url_path.endswith("/") else url_path + "/"
    tiles: list[str] = []
    for entry in sorted(fs_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        quoted_name = urllib.parse.quote(entry.name)
        child_path = f"{base}{entry.name}"
        raw_href = f"{base}{quoted_name}" + ("/" if entry.is_dir() else "")

        if entry.is_dir():
            tiles.append(_browse_tile(entry.name, raw_href, None))
            continue

        ext = entry.suffix.lower()
        artifact_id, sub_path = resolve_artifact_id(child_path)
        if ext in IMAGE_EXT:
            href = raw_href
            if artifact_id is not None:
                href = (
                    f"/_/review?artifact={urllib.parse.quote(artifact_id)}"
                    f"&src={urllib.parse.quote(sub_path)}&view=image"
                )
            tiles.append(_browse_tile(entry.name, href, raw_href))
        else:
            href = raw_href
            if artifact_id is not None and ext in CODE_EXT:
                href = (
                    f"/_/review?artifact={urllib.parse.quote(artifact_id)}"
                    f"&src={urllib.parse.quote(sub_path)}&view=code"
                )
            tiles.append(_browse_tile(entry.name, href, None))

    grid = "".join(tiles) if tiles else '<p class="empty">(empty directory)</p>'
    title = url_path or "/"
    body_html = (
        render_page_header(
            "Gallery", f'<div class="thread-meta mono">{html.escape(title)}</div>'
        )
        + f'<div class="gallery-grid">{grid}</div>'
    )
    return render_page(title=title, body_html=body_html).encode("utf-8")


# Viewer page: OpenSeadragon simple-image deep zoom + Annotorious OSD plugin
# pins. Pin creation posts an image_region thread; existing region threads
# round-trip through anno.setAnnotations() on load (DESIGN.md section 4.2/4.4).
#
# ponytail: pins use Annotorious's own rectangle shapes (recolored per
# resolved state via its formatter API) rather than custom circular numbered
# SVG badges hand-synced to OSD viewport transforms on every pan/zoom  -  that
# is a lot of hand-rolled canvas math for a stdlib-only, no-bundler skeleton
# fill. The ordinal number instead appears in the sidebar thread list, which
# also supports click-to-select-annotation. Resolved/unresolved recoloring
# and hover state match the Linear theme exactly; only the "numbered circular
# marker" shape itself is a lighter-weight stand-in.
# Viewer-only head CSS (no theme tokens/reset -- those live in
# assets/css/theme.css, linked separately by render_page()). Layout for the
# OpenSeadragon canvas inside the owned Inspector shell, plus the Annotorious
# pin recolor rules.
_VIEWER_HEAD_CSS = r"""
#osd-viewer { width: 100%; height: 100%; min-height: 70vh; background: var(--bg-overlay); }
.review-viewer-main .stage { min-height: calc(100vh - 240px); }
#thread-panel { display: flex; flex-direction: column; gap: var(--space-3); }
#thread-panel .thread-card { margin-bottom: 0; }
/* Outer ring stays a fixed dark halo (Annotorious's own default) so a pin
   reads against any image backdrop. Inner ring carries the themed status color. */
.a9s-annotation.a9s-unresolved .a9s-outer { stroke: rgba(0, 0, 0, .7); stroke-width: 3px; }
.a9s-annotation.a9s-unresolved .a9s-inner { stroke: var(--accent); }
.a9s-annotation.a9s-unresolved:hover .a9s-inner { stroke: var(--accent-hover); }
.a9s-annotation.a9s-resolved .a9s-outer { stroke: rgba(0, 0, 0, .7); stroke-width: 3px; }
.a9s-annotation.a9s-resolved .a9s-inner { stroke: var(--status-resolved); opacity: .6; }
.a9s-annotation.selected .a9s-inner { stroke: var(--accent-hover); stroke-width: 2px; }
"""

_VIEWER_BODY_RAW = r"""<main class="hero review-viewer-main" aria-label="Inspector artifact viewer">
  <div class="toolbar">
    <span class="review-chip">image</span>
    <span class="mono">__SRC_REL__</span>
    <span class="quiet">__THREAD_SUMMARY__</span>
  </div>
  <div class="viewer"><div class="stage"><div id="osd-viewer"></div></div></div>
</main>
<aside class="rail" aria-label="Region thread rail">
  <div class="rail-head"><span class="title">Threads</span><span class="progress" id="thread-panel-progress">loading...</span></div>
  <div class="threads">
    <div class="review-rail-note">Draw a region to start a thread. Click a thread card to focus its annotation.</div>
    __ROUND_HISTORY__
    <div id="thread-panel"><p class="empty">loading...</p></div>
  </div>
</aside>
<script src="__OSD_URL__"></script>
<script src="__ANNO_JS_URL__"></script>
<script>
(function(){
  const IMAGE_URL = __IMAGE_URL__;
  const ARTIFACT_ID = __ARTIFACT_ID__;
  const SUB_PATH = __SUB_PATH__;
  let threadsById = {};

  const viewer = OpenSeadragon({
    id: 'osd-viewer',
    prefixUrl: '/_/assets/openseadragon/images/',
    tileSources: { type: 'image', url: IMAGE_URL },
    showNavigator: true,
  });
  const anno = OpenSeadragon.Annotorious(viewer, { drawingEnabled: true });
  anno.formatter = function(annotation){
    const t = threadsById[annotation.id];
    return { className: (t && t.resolved) ? 'a9s-resolved' : 'a9s-unresolved' };
  };

  function fmtTime(ts){
    return new Date(ts * 1000).toISOString().replace('T',' ').slice(0,16) + ' UTC';
  }

  function renderSidebar(threads){
    const panel = document.getElementById('thread-panel');
    const progress = document.getElementById('thread-panel-progress');
    panel.innerHTML = '';
    const openCount = threads.filter(function(thread){ return !thread.resolved; }).length;
    if (progress) progress.textContent = openCount ? (openCount + ' open') : (threads.length + ' reviewed');
    if (!threads.length){
      const p = document.createElement('p');
      p.className = 'empty';
      p.textContent = 'no region comments yet';
      panel.appendChild(p);
      if (progress) progress.textContent = '0 open';
      return;
    }
    threads.forEach(function(t, i){
      const card = document.createElement('article');
      card.className = 'thread-card' + (t.resolved ? ' resolved' : '');
      const header = document.createElement('div');
      header.className = 'thread-meta';
      const num = document.createElement('span');
      num.className = 'thread-badge unresolved';
      num.textContent = '#' + (i + 1);
      header.appendChild(num);
      const badge = document.createElement('span');
      badge.className = 'thread-badge ' + (t.resolved ? 'resolved' : 'unresolved');
      badge.textContent = t.resolved ? 'Resolved' : 'Open';
      header.appendChild(badge);
      if (t.round_label){
        const roundBadge = document.createElement('span');
        roundBadge.className = 'thread-badge resolved';
        roundBadge.textContent = t.round_label;
        header.appendChild(roundBadge);
      }
      card.appendChild(header);
      for (const r of t.replies){
        const body = document.createElement('div');
        body.className = 'thread-body';
        const meta = document.createElement('div');
        meta.className = 'thread-meta';
        meta.textContent = (r.author || 'anonymous') + ' · ' + fmtTime(r.created_at);
        body.appendChild(meta);
        const text = document.createElement('div');
        text.textContent = r.body;
        body.appendChild(text);
        card.appendChild(body);
      }
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.textContent = t.resolved ? 'reopen' : 'resolve';
      toggle.addEventListener('click', async function(ev){
        ev.stopPropagation();
        await fetch('/_/api/threads/' + t.id + '/resolve', {
          method: 'POST', body: JSON.stringify({resolved: !t.resolved}),
        });
        loadThreads();
      });
      card.appendChild(toggle);
      card.addEventListener('click', function(){
        anno.selectAnnotation('thread-' + t.id);
      });
      panel.appendChild(card);
    });
  }

  async function loadThreads(){
    const r = await fetch('/_/api/threads?artifact=' + encodeURIComponent(ARTIFACT_ID) +
      '&sub_path=' + encodeURIComponent(SUB_PATH));
    if (!r.ok) return;
    const data = await r.json();
    threadsById = {};
    const annotations = [];
    const regionThreads = [];
    for (const t of data.threads){
      if (t.anchor_kind !== 'image_region') continue;
      const id = 'thread-' + t.id;
      threadsById[id] = t;
      annotations.push({ id: id, type: 'Annotation', body: [],
        target: { selector: t.anchor.selector } });
      regionThreads.push(t);
    }
    anno.setAnnotations(annotations);
    renderSidebar(regionThreads);
  }

  anno.on('createAnnotation', async function(annotation){
    anno.removeAnnotation(annotation.id);
    const body = window.prompt('comment:');
    if (!body) return;
    const fd = new FormData();
    fd.append('artifact', ARTIFACT_ID);
    fd.append('sub_path', SUB_PATH);
    fd.append('anchor_kind', 'image_region');
    fd.append('anchor_data', JSON.stringify({ selector: annotation.target.selector }));
    fd.append('body', body);
    const r = await fetch('/_/api/threads', { method: 'POST', body: fd });
    if (r.ok) loadThreads();
  });

  viewer.addHandler('open', loadThreads);
})();
</script>
"""


def render_viewer_page(artifact_id: str, src_rel: str) -> bytes:
    """Render the OpenSeadragon deep-zoom viewer HTML for one image."""
    loc = _artifact_location(artifact_id)
    project, subdir = (loc[1], loc[2]) if loc else ("", "")
    image_url = _raw_artifact_href(project, subdir, src_rel)
    title = f"{artifact_id} / {src_rel}"
    parent_dir = Path(src_rel).parent.as_posix()
    listing = _build_review_listing(artifact_id, "" if parent_dir == "." else parent_dir)
    open_threads, total_threads = _thread_counts(artifact_id, src_rel)
    thread_summary = (
        f"{_plural(open_threads, 'open thread')} · {_plural(total_threads, 'thread')} on image"
    )
    body_html = (
        _VIEWER_BODY_RAW
        .replace("__IMAGE_URL__", json.dumps(image_url))
        .replace("__ARTIFACT_ID__", json.dumps(artifact_id))
        .replace("__SUB_PATH__", json.dumps(src_rel))
        .replace("__OSD_URL__", OSD_SCRIPT_URL)
        .replace("__ANNO_JS_URL__", ANNOTORIOUS_SCRIPT_URL)
        .replace("__SRC_REL__", html.escape(src_rel))
        .replace("__THREAD_SUMMARY__", html.escape(thread_summary))
        .replace("__ROUND_HISTORY__", _render_round_history_section(artifact_id))
    )
    head_extra = (
        f'<link rel="stylesheet" href="{ANNOTORIOUS_CSS_URL}">'
        f"<style>{_VIEWER_HEAD_CSS}</style>"
    )
    return _render_owned_review_shell(
        title=title,
        subtitle_html=html.escape(f"{artifact_id}, image, {src_rel}"),
        quiet_html=html.escape(thread_summary),
        queue_html=_render_review_queue(listing, active_rel=src_rel),
        main_html=body_html,
        rail_html='',
        head_extra=head_extra,
    )


# Code-page-only head CSS (no theme tokens/reset -- those live in
# assets/css/theme.css, linked separately by render_page()).
_CODE_PAGE_CSS = r"""
.review-code-main .stage { min-height: calc(100vh - 240px); padding: 0; }
.code-view { height: 100%; overflow: auto; font-family: var(--font-mono); font-size: 13px; line-height: 1.55; }
.code-line { display: flex; padding: 0 var(--space-4); cursor: pointer; border-left: 3px solid transparent; }
.code-line:hover { background: var(--bg-elevated); border-left-color: var(--accent); }
.code-line.has-thread { border-left-color: var(--status-unresolved); }
.code-line.selected { background: color-mix(in srgb, var(--bg-elevated) 76%, var(--accent) 24%); border-left-color: var(--accent-hover); }
.code-gutter { width: 3.5em; text-align: right; color: var(--text-muted); user-select: none; margin-right: var(--space-3); }
.code-src { white-space: pre; color: var(--text-secondary); }
#code-thread-panel { display: flex; flex-direction: column; gap: var(--space-3); }
#code-thread-panel .thread-card { margin-bottom: 0; }
#code-thread-panel form { padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-base); }
#code-thread-panel textarea { min-height: 5rem; margin: var(--space-3) 0; }
"""

_CODE_PAGE_BODY_RAW = r"""<main class="hero review-code-main" aria-label="Code review">
  <div class="toolbar">
    <span class="review-chip">code</span>
    <span class="mono">__SRC_REL__</span>
    <span class="quiet">__CODE_SUMMARY__</span>
  </div>
  <div class="viewer"><div class="stage"><div class="code-view">__CODE__</div></div></div>
</main>
<aside class="rail" aria-label="Line thread rail">
  <div class="rail-head"><span class="title">Line review</span><span class="progress" id="code-thread-status">loading...</span></div>
  <div class="threads">
    <div class="review-rail-note">Select a line to open or add a thread. Existing replies stay pinned to the source line.</div>
    __ROUND_HISTORY__
    <div id="code-thread-panel"><p class="empty">select a line to inspect its thread history</p></div>
  </div>
</aside>
<script>
(function(){
  const ARTIFACT_ID = __ARTIFACT_ID__;
  const SUB_PATH = __SUB_PATH__;
  const status = document.getElementById('code-thread-status');
  let byLine = {};
  let activeLine = null;

  function fmtTime(ts){
    return new Date(ts * 1000).toISOString().replace('T',' ').slice(0,16) + ' UTC';
  }

  function setSelectedLine(line){
    activeLine = line;
    document.querySelectorAll('.code-line').forEach(function(node){
      node.classList.toggle('selected', parseInt(node.dataset.line, 10) === line);
    });
  }

  function renderThreadCard(t){
    const card = document.createElement('article');
    card.className = 'thread-card' + (t.resolved ? ' resolved' : '');
    const header = document.createElement('div');
    header.className = 'thread-meta';
    const badge = document.createElement('span');
    badge.className = 'thread-badge ' + (t.resolved ? 'resolved' : 'unresolved');
    badge.textContent = t.resolved ? 'Resolved' : 'Open';
    header.appendChild(badge);
    if (t.round_label){
      const roundBadge = document.createElement('span');
      roundBadge.className = 'thread-badge resolved';
      roundBadge.textContent = t.round_label;
      header.appendChild(roundBadge);
    }
    card.appendChild(header);
    for (const r of t.replies){
      const body = document.createElement('div');
      body.className = 'thread-body';
      const meta = document.createElement('div');
      meta.className = 'thread-meta';
      meta.textContent = (r.author || 'anonymous') + ' · ' + fmtTime(r.created_at);
      body.appendChild(meta);
      const text = document.createElement('div');
      text.textContent = r.body;
      body.appendChild(text);
      card.appendChild(body);
    }
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.textContent = t.resolved ? 'reopen' : 'resolve';
    toggle.addEventListener('click', async function(){
      await fetch('/_/api/threads/' + t.id + '/resolve', {
        method: 'POST', body: JSON.stringify({resolved: !t.resolved}),
      });
      loadThreads();
    });
    card.appendChild(toggle);
    return card;
  }

  function openPanel(line, threads){
    const panel = document.getElementById('code-thread-panel');
    panel.innerHTML = '';
    setSelectedLine(line);
    const h = document.createElement('h2');
    h.textContent = 'Line ' + line;
    panel.appendChild(h);
    if (!threads.length){
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'no line comments yet';
      panel.appendChild(empty);
    }
    for (const t of threads) panel.appendChild(renderThreadCard(t));

    const form = document.createElement('form');
    const ta = document.createElement('textarea');
    ta.placeholder = 'new comment on line ' + line;
    ta.required = true;
    form.appendChild(ta);
    const btn = document.createElement('button');
    btn.type = 'submit';
    btn.textContent = 'post';
    form.appendChild(btn);
    form.addEventListener('submit', async function(e){
      e.preventDefault();
      const fd = new FormData();
      fd.append('artifact', ARTIFACT_ID);
      fd.append('sub_path', SUB_PATH);
      fd.append('anchor_kind', 'code_line');
      fd.append('anchor_data', JSON.stringify({ line: line }));
      fd.append('body', ta.value);
      await fetch('/_/api/threads', { method: 'POST', body: fd });
      loadThreads();
    });
    panel.appendChild(form);
    panel.scrollIntoView({ behavior: 'smooth' });
  }

  async function loadThreads(){
    const r = await fetch('/_/api/threads?artifact=' + encodeURIComponent(ARTIFACT_ID) +
      '&sub_path=' + encodeURIComponent(SUB_PATH));
    if (!r.ok) return;
    const data = await r.json();
    byLine = {};
    let openCount = 0;
    document.querySelectorAll('.code-line').forEach(function(el){
      el.classList.remove('has-thread');
    });
    for (const t of data.threads){
      if (t.anchor_kind !== 'code_line') continue;
      const line = t.anchor.line;
      if (!byLine[line]) byLine[line] = [];
      byLine[line].push(t);
      if (!t.resolved) openCount += 1;
      const el = document.getElementById('L' + line);
      if (el) el.classList.add('has-thread');
    }
    if (status) status.textContent = openCount ? (openCount + ' open') : (data.threads.length + ' reviewed');
    if (activeLine !== null) openPanel(activeLine, byLine[activeLine] || []);
  }

  document.querySelectorAll('.code-line').forEach(function(el){
    el.addEventListener('click', function(){
      const line = parseInt(el.dataset.line, 10);
      openPanel(line, byLine[line] || []);
    });
  });

  loadThreads();
})();
</script>
"""


def render_code_page(artifact_id: str, src_rel: str) -> bytes:
    """Render the per-line code view HTML for one served text file."""
    path = staged_source_path(artifact_id, src_rel)
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path else ""
    except OSError:
        text = ""
    lines = text.splitlines()

    rows = [
        f'<div class="code-line" data-line="{i}" id="L{i}">'
        f'<span class="code-gutter">{i}</span>'
        f'<span class="code-src">{html.escape(line)}</span></div>'
        for i, line in enumerate(lines, start=1)
    ]
    code_html = "\n".join(rows) if rows else '<p class="empty">(empty file)</p>'

    title = f"{artifact_id} / {src_rel}"
    parent_dir = Path(src_rel).parent.as_posix()
    listing = _build_review_listing(artifact_id, "" if parent_dir == "." else parent_dir)
    open_threads, total_threads = _thread_counts(artifact_id, src_rel)
    code_summary = (
        f"{len(lines)} lines · {_plural(open_threads, 'open thread')} · {_plural(total_threads, 'thread')} on file"
    )
    body_html = (
        _CODE_PAGE_BODY_RAW
        .replace("__CODE__", code_html)
        .replace("__ARTIFACT_ID__", json.dumps(artifact_id))
        .replace("__SUB_PATH__", json.dumps(src_rel))
        .replace("__SRC_REL__", html.escape(src_rel))
        .replace("__CODE_SUMMARY__", html.escape(code_summary))
        .replace("__ROUND_HISTORY__", _render_round_history_section(artifact_id))
    )
    return _render_owned_review_shell(
        title=title,
        subtitle_html=html.escape(f"{artifact_id}, code, {src_rel}"),
        quiet_html=html.escape(code_summary),
        queue_html=_render_review_queue(listing, active_rel=src_rel),
        main_html=body_html,
        rail_html='',
        head_extra=f"<style>{_CODE_PAGE_CSS}</style>",
    )


# Page-level comment widget, injected before </body> of any served HTML page
# (send_head splices this in  -  see _make_handler). Upgraded from the legacy
# flat-comment widget to the thread model: shows only anchor_kind='page'
# threads (image/code threads belong to their own /_/review viewer pages),
# supports resolve/reopen. Every user string goes through textContent.
_PAGE_WIDGET_JS_RAW = r"""
(function(){
  const path = window.location.pathname;
  const root = document.getElementById('artifact-serve-dock');
  const toggle = document.getElementById('artifact-serve-dock-toggle');
  if (!root || !toggle) return;
  const closeButton = root.querySelector('.rs-close');
  const list = root.querySelector('.rs-list');
  const status = root.querySelector('.rs-status');
  const form = root.querySelector('form');
  const headers = {'Accept': 'application/json'};

  function fmtTime(ts){
    return new Date(ts * 1000).toISOString().replace('T',' ').slice(0,16) + ' UTC';
  }

  function setOpen(open){
    document.documentElement.classList.toggle('artifact-serve-dock-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) root.removeAttribute('hidden');
    else root.setAttribute('hidden', 'hidden');
  }

  async function loadSettings(){
    try {
      const r = await fetch('/_/api/settings', {headers});
      if (!r.ok) return;
      const s = await r.json();
      if (s && typeof s.author === 'string' && s.author){
        const inp = root.querySelector('input[name=author]');
        if (inp && !inp.value) inp.value = s.author;
      }
    } catch (e) { /* ignore */ }
  }

  function renderThread(t){
    const card = document.createElement('article');
    card.className = 'thread-card' + (t.resolved ? ' resolved' : '');
    const header = document.createElement('div');
    header.className = 'thread-meta';
    const badge = document.createElement('span');
    badge.className = 'thread-badge ' + (t.resolved ? 'resolved' : 'unresolved');
    badge.textContent = t.resolved ? 'Resolved' : 'Open';
    header.appendChild(badge);
    if (t.round_label){
      const roundBadge = document.createElement('span');
      roundBadge.className = 'thread-badge resolved';
      roundBadge.textContent = t.round_label;
      header.appendChild(roundBadge);
    }
    header.appendChild(document.createTextNode(' ' + (t.author || 'anonymous')));
    card.appendChild(header);

    for (const r of t.replies){
      const reply = document.createElement('div');
      reply.className = 'thread-body';
      const meta = document.createElement('div');
      meta.className = 'thread-meta';
      meta.textContent = (r.author || 'anonymous') + ' · ' + fmtTime(r.created_at);
      reply.appendChild(meta);
      const bodyEl = document.createElement('div');
      bodyEl.textContent = r.body;
      reply.appendChild(bodyEl);
      if (r.uploads && r.uploads.length){
        const ul = document.createElement('ul');
        for (const u of r.uploads){
          const li = document.createElement('li');
          const a = document.createElement('a');
          a.href = '/_/api/uploads/' + u.id;
          a.textContent = u.filename + ' (' + Math.round(u.size/1024) + ' KB)';
          a.target = '_blank';
          li.appendChild(a);
          ul.appendChild(li);
        }
        reply.appendChild(ul);
      }
      card.appendChild(reply);
    }

    const actions = document.createElement('div');
    actions.className = 'rs-actions';
    const resolve = document.createElement('button');
    resolve.type = 'button';
    resolve.textContent = t.resolved ? 'reopen' : 'resolve';
    resolve.addEventListener('click', async function(){
      await fetch('/_/api/threads/' + t.id + '/resolve', {
        method: 'POST', body: JSON.stringify({resolved: !t.resolved}),
      });
      load();
    });
    actions.appendChild(resolve);
    card.appendChild(actions);
    return card;
  }

  async function load(){
    const r = await fetch('/_/api/threads?url=' + encodeURIComponent(path), {headers});
    if (!r.ok){
      list.textContent = 'failed to load: ' + r.status;
      return;
    }
    const data = await r.json();
    root.querySelector('.rs-aid').textContent = data.artifact_id || '';
    list.innerHTML = '';
    const pageThreads = data.threads.filter(function(t){ return t.anchor_kind === 'page'; });
    if (!pageThreads.length){
      const p = document.createElement('p');
      p.className = 'empty';
      p.textContent = 'no page discussion yet';
      list.appendChild(p);
      return;
    }
    pageThreads.forEach(function(t){ list.appendChild(renderThread(t)); });
  }

  form.addEventListener('submit', async function(e){
    e.preventDefault();
    status.textContent = 'posting...';
    const fd = new FormData(form);
    fd.append('url', path);
    fd.append('anchor_kind', 'page');
    try {
      const r = await fetch('/_/api/threads', {method: 'POST', body: fd});
      if (!r.ok){
        const t = await r.text();
        status.textContent = 'error: ' + r.status + ' ' + t.slice(0, 200);
        return;
      }
      status.textContent = 'posted.';
      form.reset();
      await loadSettings();
      await load();
      setOpen(true);
    } catch (err){
      status.textContent = 'network error: ' + err;
    }
  });

  toggle.addEventListener('click', function(){ setOpen(!document.documentElement.classList.contains('artifact-serve-dock-open')); });
  closeButton.addEventListener('click', function(){ setOpen(false); toggle.focus(); });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && document.documentElement.classList.contains('artifact-serve-dock-open')) {
      setOpen(false);
      toggle.focus();
    }
  });

  loadSettings();
  load();
})();
"""

_PAGE_WIDGET_CSS_RAW = r"""
#artifact-serve-dock {
  /* Theme tokens scoped to this dock, not :root. It lands inside arbitrary
     pushed HTML that never loads assets/css/theme.css, so it carries its own
     copy of the same review-app custom properties. */
__DARK_TOKENS__
  --font-ui: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
  --font-reading: "Iowan Old Style", "Palatino Linotype", Georgia, ui-serif, serif;
  --font-mono: ui-monospace, "SF Mono", "Cascadia Code", "Consolas", monospace;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 24px; --space-6: 32px; --space-7: 48px;
  --radius-sm: 3px; --radius-md: 6px; --radius-lg: 10px; --radius-pill: 9999px;

  position: fixed; top: 0; right: 0; z-index: 998;
  width: min(380px, calc(100vw - 24px)); height: 100vh;
  display: flex; flex-direction: column; min-height: 0;
  border-left: 1px solid var(--border); background: var(--bg-base);
  color: var(--text-primary); font-family: var(--font-ui);
  box-shadow: var(--shadow-overlay);
  transform: translateX(100%); transition: transform .18s ease;
}
#artifact-serve-dock[hidden] { display: none; }
html.artifact-serve-dock-open #artifact-serve-dock {
  transform: translateX(0); display: flex;
}
html[data-theme="dark-graphite"] #artifact-serve-dock {
__DARK_TOKENS__
}
html[data-theme="light"] #artifact-serve-dock {
__LIGHT_TOKENS__
}
__THEME_TOGGLE_CSS__
#artifact-serve-dock-toggle {
  position: fixed; right: var(--space-3); bottom: var(--space-3); z-index: 999;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-elevated); color: var(--text-primary);
  padding: 9px 12px; font: 500 13px/1.2 var(--font-ui); cursor: pointer;
  box-shadow: var(--shadow-overlay);
}
html.artifact-serve-dock-open #artifact-serve-dock-toggle { opacity: 0; pointer-events: none; }
#artifact-serve-dock .rs-head {
  display: flex; align-items: flex-start; gap: var(--space-3);
  padding: calc(var(--space-6) + 4px) var(--space-4) var(--space-4);
  border-bottom: 1px solid var(--border); background: var(--bg-elevated);
}
#artifact-serve-dock .rs-kicker {
  margin: 0 0 4px; color: var(--text-muted); font-size: 11px;
  font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
}
#artifact-serve-dock h2 { margin: 0 0 4px; font-size: 18px; }
#artifact-serve-dock .rs-aid { font-family: var(--font-mono); color: var(--text-muted); font-size: 12px; }
#artifact-serve-dock .rs-scroll {
  display: flex; flex-direction: column; gap: var(--space-4);
  min-height: 0; overflow: auto; padding: var(--space-4);
}
#artifact-serve-dock .thread-card {
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: var(--space-4);
  margin-bottom: var(--space-3); border-left: 3px solid var(--status-unresolved);
}
#artifact-serve-dock .thread-card.resolved {
  border-left-color: var(--status-resolved); opacity: .78;
}
#artifact-serve-dock .thread-badge {
  display: inline-block; font-size: 12px; padding: 2px 8px;
  border-radius: var(--radius-pill); font-weight: 500;
}
#artifact-serve-dock .thread-badge.unresolved {
  color: var(--status-unresolved);
  background: color-mix(in srgb, var(--status-unresolved) 16%, transparent);
}
#artifact-serve-dock .thread-badge.resolved {
  color: var(--status-resolved);
  background: color-mix(in srgb, var(--status-resolved) 16%, transparent);
}
#artifact-serve-dock .thread-body {
  color: var(--text-primary); white-space: pre-wrap; word-break: break-word;
  line-height: 1.55;
}
#artifact-serve-dock .thread-meta { color: var(--text-muted); font-size: 13px; margin-bottom: var(--space-2); }
#artifact-serve-dock .empty { color: var(--text-muted); font-style: italic; }
#artifact-serve-dock button {
  background: var(--accent); color: var(--on-accent); border: 1px solid var(--accent);
  border-radius: var(--radius-sm); padding: var(--space-2) var(--space-4);
  font-family: var(--font-ui); font-size: 14px; cursor: pointer;
}
#artifact-serve-dock button:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
#artifact-serve-dock textarea, #artifact-serve-dock input[type=text] {
  background: var(--bg-overlay); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3); font-family: inherit; font-size: 14px; width: 100%;
  box-sizing: border-box;
}
#artifact-serve-dock textarea:focus, #artifact-serve-dock input:focus { border-color: var(--border-strong); outline: none; }
#artifact-serve-dock form {
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: var(--space-4);
}
#artifact-serve-dock label { display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
#artifact-serve-dock textarea { min-height: 5rem; margin-bottom: var(--space-3); }
#artifact-serve-dock input[type=file] { color: var(--text-muted); font-size: 13px; }
#artifact-serve-dock .rs-status { color: var(--text-muted); font-size: 13px; }
#artifact-serve-dock .rs-actions { margin-top: var(--space-3); }
#artifact-serve-dock .rs-close { margin-left: auto; white-space: nowrap; }
"""

_PAGE_WIDGET_BLOCK_RAW = """
<style>__CSS__</style>
__THEME_TOGGLE_HTML__
<button type="button" id="artifact-serve-dock-toggle" aria-controls="artifact-serve-dock" aria-expanded="false">Discussion</button>
<aside id="artifact-serve-dock" aria-label="Page discussion" hidden>
  <div class="rs-head">
    <div>
      <p class="rs-kicker">Page discussion</p>
      <h2>Discussion</h2>
      <div class="rs-aid">(loading)</div>
    </div>
    <button type="button" class="rs-close">Close</button>
  </div>
  <div class="rs-scroll">
    <div class="rs-list"><p class="empty">loading...</p></div>
    <form enctype="multipart/form-data">
      <label>name (optional)</label>
      <input type="text" name="author" maxlength="80" placeholder="anonymous">
      <label>comment</label>
      <textarea name="body" required maxlength="20000" placeholder="start a page thread..."></textarea>
      <label>attachments (optional, multiple)</label>
      <input type="file" name="files" multiple>
      <div class="rs-actions"><button type="submit">post comment</button></div>
      <div class="rs-status"></div>
    </form>
  </div>
</aside>
<script>__THEME_JS__</script>
<script>__JS__</script>
"""

# ponytail: the widget can't run a head pre-paint on pages it doesn't own
# (it's spliced in just before </body> of arbitrary pushed HTML), so an
# explicit choice made elsewhere on the same origin can show a brief flash
# of auto/OS-default here before this script runs. Acceptable: the widget's
# own themed area is a small corner control + a footer section, not the
# page content, and localStorage still keeps every page in sync afterward.
PAGE_COMMENT_WIDGET = (
    _PAGE_WIDGET_BLOCK_RAW
    .replace(
        "__CSS__",
        _PAGE_WIDGET_CSS_RAW
        .replace("__DARK_TOKENS__", _COLOR_TOKENS_DARK)
        .replace("__LIGHT_TOKENS__", _COLOR_TOKENS_LIGHT)
        .replace("__THEME_TOGGLE_CSS__", _THEME_TOGGLE_CSS),
    )
    .replace("__THEME_TOGGLE_HTML__", _THEME_TOGGLE_HTML)
    .replace("__THEME_JS__", _THEME_TOGGLE_JS)
    .replace("__JS__", _PAGE_WIDGET_JS_RAW)
)


def injected_page_widget() -> bytes:
    """Return the page-level thread widget spliced before </body>.

    Upgraded from the legacy flat-comment widget to the thread model (page
    anchor). All user strings rendered via textContent. Returns UTF-8 bytes.
    """
    return PAGE_COMMENT_WIDGET.encode("utf-8")


# ── http server ───────────────────────────────────────────────────────


def _make_handler() -> type[http.server.SimpleHTTPRequestHandler]:
    """Build the request handler class bound to the staging ROOT.

    Routing (see DESIGN.md section 9). do_GET dispatch order, most specific
    first, so the reserved /_/ namespace always wins over static files:
      GET  /_/assets/<rel>                 -> vendored OSD/Annotorious file
      GET  /_/api/threads                  -> _api_threads_get
      GET  /_/api/uploads/<id>             -> _api_upload_get (preserved)
      GET  /_/api/settings                 -> _api_settings_get (preserved)
      GET  /_/api/comments                 -> legacy read shim (page threads)
      GET  /_/review                       -> gallery|image|code by query params
      GET  <any directory without its own index.html>
                                            -> themed directory-browse gallery
                                               (render_directory_gallery),
                                               never the raw autoindex
      *                                    -> static file + page widget inject
    do_POST dispatch:
      POST /_/api/threads                  -> _api_thread_create
      POST /_/api/threads/<id>/replies     -> _api_reply_create
      POST /_/api/threads/<id>/resolve     -> _api_resolve_toggle
      POST /_/api/comments                 -> legacy write shim (page thread)
    """
    root_str = str(ROOT)
    assets_root = ASSETS_ROOT.resolve()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__(*a, directory=root_str, **kw)  # type: ignore[arg-type]  # stdlib base ctor accepts a directory kwarg the typeshed stub for *a/**kw does not model precisely here

        def log_message(self, fmt: str, *args: object) -> None:
            log.info("%s - %s", self.address_string(), fmt % args)

        # ── routing ──────────────────────────────────────────────────

        def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
            url = urllib.parse.urlsplit(self.path)
            if url.path.startswith("/_/assets/"):
                self._serve_asset(url.path[len("/_/assets/"):])
                return
            if url.path == "/_/api/threads":
                self._api_threads_get(url)
                return
            if url.path.startswith("/_/api/uploads/"):
                self._api_upload_get(url.path[len("/_/api/uploads/"):])
                return
            if url.path == "/_/api/settings":
                self._api_settings_get()
                return
            if url.path == "/_/api/comments":
                self._api_comments_get(url)
                return
            if url.path == "/_/review":
                self._serve_review(url)
                return
            if not url.path.startswith("/_/"):
                fs_path = Path(self.translate_path(self.path))
                if fs_path.is_dir() and not (fs_path / "index.html").is_file():
                    self._serve_directory_gallery(url.path, fs_path)
                    return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/_/api/threads":
                self._api_thread_create()
                return
            m = re.match(r"^/_/api/threads/(\d+)/replies$", url.path)
            if m:
                self._api_reply_create(int(m.group(1)))
                return
            m = re.match(r"^/_/api/threads/(\d+)/resolve$", url.path)
            if m:
                self._api_resolve_toggle(int(m.group(1)))
                return
            if url.path == "/_/api/comments":
                self._api_comments_post()
                return
            self.send_error(404, "not found")

        # ── static assets ────────────────────────────────────────────

        def _serve_asset(self, rel: str) -> None:
            """Serve a vendored file from ASSETS_ROOT under /_/assets/.

            Traversal-guarded (normalize + is_relative_to ASSETS_ROOT). 404 on
            escape or missing file. Sets mime from the extension.
            """
            rel = urllib.parse.unquote(rel)
            target = (ASSETS_ROOT / rel).resolve()
            if not target.is_relative_to(assets_root) or not target.is_file():
                self.send_error(404, "not found")
                return
            mime, _ = mimetypes.guess_type(str(target))
            mime = mime or "application/octet-stream"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            super().end_headers()
            self.wfile.write(data)

        # ── review page routes ───────────────────────────────────────

        def _serve_review(self, url: urllib.parse.SplitResult) -> None:
            """Dispatch /_/review by query params to gallery/image/code render."""
            params = urllib.parse.parse_qs(url.query)
            artifact_id = (params.get("artifact") or [""])[0]
            if not artifact_id:
                self.send_error(400, "artifact required")
                return
            view = (params.get("view") or [""])[0]
            src = (params.get("src") or [""])[0]
            path_param = (params.get("path") or [""])[0]

            if view in ("image", "code"):
                if staged_source_path(artifact_id, src) is None:
                    self.send_error(404, "not found")
                    return
                body = (
                    render_viewer_page(artifact_id, src) if view == "image"
                    else render_code_page(artifact_id, src)
                )
            else:
                body = render_gallery_page(artifact_id, path_param)

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            super().end_headers()
            self.wfile.write(body)

        def _serve_directory_gallery(self, raw_path: str, fs_path: Path) -> None:
            """Render a browsed directory via render_directory_gallery instead
            of falling through to the raw SimpleHTTPRequestHandler autoindex."""
            body = render_directory_gallery(urllib.parse.unquote(raw_path), fs_path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            super().end_headers()
            self.wfile.write(body)

        # ── HTML injection (page-level widget, preserved mechanism) ──

        def send_head(self):  # type: ignore[override]  # stdlib returns BinaryIO|None
            """Splice injected_page_widget() into text/html responses.

            Preserved from legacy: keys off the actually-sent Content-Type,
            suppresses Content-Length on text/html (close-framing).
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
            inject = injected_page_widget()
            idx = body.lower().rfind(b"</body>")
            merged = body + inject if idx == -1 else body[:idx] + inject + body[idx:]
            return io.BytesIO(merged)

        def send_header(self, keyword: str, value: str) -> None:  # type: ignore[override]  # legacy content-length suppression
            lk = keyword.lower()
            if lk == "content-type":
                self._sent_ctype = value.lower()
            if lk == "content-length":
                if getattr(self, "_sent_ctype", "").startswith("text/html"):
                    return
            super().send_header(keyword, value)

        # ── API: threads ─────────────────────────────────────────────

        def _resolve_target(
            self, params: dict[str, list[str]]
        ) -> tuple[str | None, str]:
            """Resolve (artifact_id, sub_path) from query params: either
            ?artifact=&sub_path= directly, or ?url= via resolve_artifact_id."""
            if "artifact" in params:
                return params["artifact"][0], (params.get("sub_path") or [""])[0]
            if "url" in params:
                return resolve_artifact_id(params["url"][0])
            return None, ""

        def _resolve_target_fields(
            self, fields: dict[str, str]
        ) -> tuple[str | None, str]:
            """Same as _resolve_target but reading multipart form fields."""
            if fields.get("artifact"):
                return fields["artifact"], fields.get("sub_path", "")
            if fields.get("url"):
                return resolve_artifact_id(fields["url"])
            return None, ""

        def _api_threads_get(self, url: urllib.parse.SplitResult) -> None:
            """GET /_/api/threads?url=|artifact= -> list_threads as JSON."""
            params = urllib.parse.parse_qs(url.query)
            artifact_id, sub_path = self._resolve_target(params)
            if artifact_id is None:
                self._send_json(404, {"error": "could not resolve artifact"})
                return
            try:
                rounds = round_history(artifact_id)
                current = rounds[-1] if rounds else None
                all_threads = list_threads(artifact_id, sub_path)
            except sqlite3.Error as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return
            current_round_id = int(current["id"]) if current is not None else None
            threads = list(all_threads)
            history_threads = []
            self._send_json(
                200,
                {
                    "artifact_id": artifact_id,
                    "sub_path": sub_path,
                    "current_round": current,
                    "rounds": rounds,
                    "threads": [_thread_json(t) for t in threads],
                    "history_threads": [_thread_json(t) for t in history_threads],
                },
            )

        def _validate_upload_files(self, files: list[dict[str, object]]) -> bool:
            """Validate each file's extension + size cap.

            Sends the error response and returns False on the first
            violation; True if all files pass.
            """
            for f in files:
                raw_name = str(f.get("filename") or "unnamed")
                safe = safe_upload_filename(raw_name)
                ok, why = upload_ext_ok(safe)
                if not ok:
                    self._send_json(400, {"error": f"{raw_name}: {why}"})
                    return False
                size = len(f.get("data", b""))  # type: ignore[arg-type]  # multipart payload is always bytes
                if size > MAX_UPLOAD_BYTES:
                    self._send_json(
                        413,
                        {"error": f"{raw_name}: {size}B exceeds {MAX_UPLOAD_BYTES}B cap"},
                    )
                    return False
            return True

        def _api_thread_create(self) -> None:
            """POST /_/api/threads (multipart) -> create_thread.

            Reads + caps the multipart body, resolves artifact/sub_path,
            validates the anchor (validate_anchor), validates uploads, then
            create_thread. 201 {thread_id, reply_id, ...}. 400 on bad anchor
            or missing body.
            """
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                self._send_json(400, {"error": "expected multipart/form-data"})
                return
            raw = self._read_capped_body()
            if raw is None:
                return
            try:
                fields, files = parse_multipart_form(ctype, raw)
            except ValueError as exc:
                self._send_json(400, {"error": f"bad multipart: {exc}"})
                return

            artifact_id, sub_path = self._resolve_target_fields(fields)
            if artifact_id is None:
                self._send_json(400, {"error": "url or artifact required"})
                return

            text_body = (fields.get("body") or "").strip()
            if not text_body:
                self._send_json(400, {"error": "body required"})
                return
            if len(text_body) > MAX_BODY_CHARS:
                self._send_json(
                    400, {"error": f"body too long (>{MAX_BODY_CHARS} chars)"}
                )
                return
            author = (fields.get("author") or "").strip() or None

            anchor_kind = fields.get("anchor_kind", ANCHOR_PAGE)
            try:
                anchor = validate_anchor(anchor_kind, fields.get("anchor_data"))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return

            if not self._validate_upload_files(files):
                return

            try:
                thread_id, reply_id = create_thread(
                    artifact_id, sub_path, anchor, text_body, author, files
                )
            except (sqlite3.Error, OSError) as exc:
                self._send_json(500, {"error": f"create failed: {exc}"})
                return

            self._send_json(
                201,
                {
                    "thread_id": thread_id,
                    "reply_id": reply_id,
                    "artifact_id": artifact_id,
                    "sub_path": sub_path,
                    "anchor_kind": anchor.kind,
                    "uploads": uploads_for_reply(reply_id),
                },
            )

        def _api_reply_create(self, thread_id: int) -> None:
            """POST /_/api/threads/<id>/replies (multipart) -> add_reply."""
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                self._send_json(400, {"error": "expected multipart/form-data"})
                return
            raw = self._read_capped_body()
            if raw is None:
                return
            try:
                fields, files = parse_multipart_form(ctype, raw)
            except ValueError as exc:
                self._send_json(400, {"error": f"bad multipart: {exc}"})
                return

            text_body = (fields.get("body") or "").strip()
            if not text_body:
                self._send_json(400, {"error": "body required"})
                return
            if len(text_body) > MAX_BODY_CHARS:
                self._send_json(
                    400, {"error": f"body too long (>{MAX_BODY_CHARS} chars)"}
                )
                return
            author = (fields.get("author") or "").strip() or None

            if not self._validate_upload_files(files):
                return

            try:
                reply_id = add_reply(thread_id, text_body, author, files)
            except KeyError:
                self._send_json(404, {"error": f"thread {thread_id} not found"})
                return
            except (sqlite3.Error, OSError) as exc:
                self._send_json(500, {"error": f"reply failed: {exc}"})
                return

            self._send_json(
                201,
                {
                    "reply_id": reply_id,
                    "thread_id": thread_id,
                    "uploads": uploads_for_reply(reply_id),
                },
            )

        def _api_resolve_toggle(self, thread_id: int) -> None:
            """POST /_/api/threads/<id>/resolve (JSON) -> set_resolved.

            Body {resolved: bool} sets; empty body toggles. 200 {id, resolved}.
            """
            raw = self._read_capped_body()
            if raw is None:
                return
            resolved: bool | None = None
            if raw.strip():
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "body must be JSON"})
                    return
                if isinstance(payload, dict) and "resolved" in payload:
                    resolved = bool(payload["resolved"])
            try:
                new_state = set_resolved(thread_id, resolved)
            except KeyError:
                self._send_json(404, {"error": f"thread {thread_id} not found"})
                return
            self._send_json(200, {"id": thread_id, "resolved": new_state})

        # ── API: uploads + settings (preserved) ──────────────────────

        def _api_upload_get(self, suffix: str) -> None:
            """GET /_/api/uploads/<id> -> upload bytes. Preserved from legacy."""
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
            inline_mimes = {
                "image/png", "image/jpeg", "image/webp", "image/gif",
                "image/bmp", "application/pdf", "text/plain",
            }
            mime_used = mime or "application/octet-stream"
            disposition = "inline" if mime_used in inline_mimes else "attachment"
            self.send_response(200)
            self.send_header("Content-Type", mime_used)
            self.send_header("Content-Length", str(size))
            self.send_header("X-Content-Type-Options", "nosniff")
            safe_disp_name = filename.replace('"', '')
            self.send_header(
                "Content-Disposition",
                f'{disposition}; filename="{safe_disp_name}"',
            )
            super().end_headers()
            with path.open("rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        def _api_settings_get(self) -> None:
            """GET /_/api/settings -> {key: value}. Preserved from legacy."""
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

        # ── API: legacy comment shims ────────────────────────────────

        def _api_comments_get(self, url: urllib.parse.SplitResult) -> None:
            """GET /_/api/comments -> page-level threads flattened to old shape."""
            params = urllib.parse.parse_qs(url.query)
            artifact_id, sub_path = self._resolve_target(params)
            if artifact_id is None:
                self._send_json(404, {"error": "could not resolve artifact"})
                return
            try:
                threads = list_threads(artifact_id, sub_path)
            except sqlite3.Error as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return
            comments: list[dict[str, object]] = []
            for t in threads:
                if t.anchor.kind != ANCHOR_PAGE:
                    continue
                for r in t.replies:
                    comments.append(
                        {
                            "id": r.id,
                            "body": r.body,
                            "author": r.author,
                            "created_at": r.created_at,
                            "created_at_iso": iso_utc(r.created_at),
                            "uploads": [_upload_json(u) for u in r.uploads],
                        }
                    )
            self._send_json(
                200,
                {"artifact_id": artifact_id, "sub_path": sub_path, "comments": comments},
            )

        def _api_comments_post(self) -> None:
            """POST /_/api/comments -> create a page-level thread (compat)."""
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                self._send_json(400, {"error": "expected multipart/form-data"})
                return
            raw = self._read_capped_body()
            if raw is None:
                return
            try:
                fields, files = parse_multipart_form(ctype, raw)
            except ValueError as exc:
                self._send_json(400, {"error": f"bad multipart: {exc}"})
                return

            artifact_id, sub_path = self._resolve_target_fields(fields)
            if artifact_id is None:
                self._send_json(400, {"error": "url or artifact required"})
                return
            text_body = (fields.get("body") or "").strip()
            if not text_body:
                self._send_json(400, {"error": "body required"})
                return
            if len(text_body) > MAX_BODY_CHARS:
                self._send_json(
                    400, {"error": f"body too long (>{MAX_BODY_CHARS} chars)"}
                )
                return
            author = (fields.get("author") or "").strip() or None

            if not self._validate_upload_files(files):
                return

            try:
                thread_id, reply_id = create_thread(
                    artifact_id, sub_path, Anchor(kind=ANCHOR_PAGE, data=None),
                    text_body, author, files,
                )
            except (sqlite3.Error, OSError) as exc:
                self._send_json(500, {"error": f"db: {exc}"})
                return

            self._send_json(
                201,
                {"id": reply_id, "thread_id": thread_id,
                 "artifact_id": artifact_id, "sub_path": sub_path},
            )

        # ── helpers ──────────────────────────────────────────────────

        def _read_capped_body(self) -> bytes | None:
            """Read the request body enforcing MAX_REQUEST_BYTES.

            Returns None (after sending the appropriate 4xx) on missing/oversize
            Content-Length. Content-Length: 0 is valid (e.g. an empty-body
            resolve-toggle POST). Preserved from legacy comment POST, extended
            to allow the zero-length case the new resolve endpoint needs.
            """
            raw_clen = self.headers.get("Content-Length")
            if raw_clen is None:
                self._send_json(411, {"error": "Content-Length required"})
                return None
            try:
                clen = int(raw_clen)
            except ValueError:
                self._send_json(411, {"error": "Content-Length required"})
                return None
            if clen < 0:
                self._send_json(411, {"error": "Content-Length required"})
                return None
            if clen > MAX_REQUEST_BYTES:
                self._send_json(
                    413,
                    {"error": f"request body {clen}B exceeds {MAX_REQUEST_BYTES}B"},
                )
                return None
            try:
                return self.rfile.read(clen)
            except OSError as exc:
                self._send_json(400, {"error": f"read failed: {exc}"})
                return None

        def _send_json(self, code: int, payload: dict[str, object]) -> None:
            """Send a JSON response. Preserved from legacy."""
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            super().end_headers()
            self.wfile.write(body)

    return Handler


# ── daemon plumbing (preserved from legacy) ───────────────────────────


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def read_pid() -> int | None:
    """Return the live daemon pid, or None if stale/absent. Preserved."""
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
    """Return the active port if recorded, else None. Preserved."""
    if not PORT_FILE.exists():
        return None
    try:
        return int(PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def clear_runtime_files() -> None:
    """Remove pid/port files. Leaves staging + log intact. Preserved."""
    for p in (PID_FILE, PORT_FILE):
        p.unlink(missing_ok=True)


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


def _serve_forever(host: str, port: int) -> None:
    """Child process entrypoint: bind host:<port> and serve. Preserved."""
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
        with ReusableTCPServer((host, port), handler_cls) as httpd:
            log.info("serving %s on %s:%d", ROOT, host, port)
            httpd.serve_forever()
    except OSError as exc:
        log.error("bind failed: %s", exc)
        clear_runtime_files()
        sys.exit(EXIT_SERVER)


def _port_free(host: str, port: int) -> bool:
    """Probe whether host:<port> can be bound (SO_REUSEADDR). Preserved."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


# ── tailscale wiring (preserved from legacy) ──────────────────────────


def _tailscale_available() -> bool:
    return shutil.which("tailscale") is not None


def _tailscale_serve_on(port: int) -> tuple[bool, str]:
    """Publish 127.0.0.1:<port> via `tailscale serve`. Preserved."""
    if not _tailscale_available():
        return False, "tailscale CLI not on PATH"
    try:
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
    """Take down `tailscale serve`. Preserved."""
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
    """Extract the tailnet URL from serve status JSON. Preserved."""
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
# Verb surface preserved verbatim (muscle memory):
#   push, unpush, start, expose, unexpose, status, stop, clean, feedback, name


def cmd_push(args: argparse.Namespace) -> int:
    """Stage --src as a relative symlink under <project>/<subdir>. Preserved."""
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
        if args.artifact_id:
            _check_artifact_id(args.artifact_id.strip())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CALLER

    dest = project / subdir
    remove_entry(dest)

    rel = os.path.relpath(src, dest.parent)
    os.symlink(rel, dest)
    print(f"symlink {dest} → {rel}")

    # Record this push in the durable artifact index for feedback resolution.
    artifact_id = (args.artifact_id or "").strip() or f"{args.project}/{subdir}"
    try:
        pushed_at = int(time.time())
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
                (args.project, subdir, artifact_id, str(src), pushed_at),
            )
            conn.commit()
        finally:
            conn.close()
        round_id = record_push_round(artifact_id, args.project, subdir, str(src), created_at=pushed_at)
        print(f"artifact_id: {artifact_id}")
        print(f"round_id: {round_id}")
    except sqlite3.Error as exc:
        log.warning("artifact_index update failed: %s", exc)

    regenerate_index()
    return EXIT_OK


def cmd_unpush(args: argparse.Namespace) -> int:
    """Remove a staged entry. Feedback rows untouched. Preserved."""
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
    """Boot the local daemon (fork), write pid/port, regen index. Preserved."""
    ensure_root()
    host = args.host
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

    if not _port_free(host, port):
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
    _serve_forever(host, port)
    return EXIT_OK  # not reached


def cmd_run(args: argparse.Namespace) -> int:
    """Run the server in the foreground: no fork, no setsid, no pidfile.

    For a process supervisor that already owns the process lifecycle (a
    container runtime, systemd) and wants a single foreground process it can
    start/stop/restart and read logs from directly via stdout. `start`'s
    fork+pidfile daemon model is for interactive CLI use; this is the
    supervised equivalent.
    """
    ensure_root()
    host = args.host
    port = args.port
    if not _port_free(host, port):
        print(f"error: port {port} already in use by another process", file=sys.stderr)
        return EXIT_SERVER
    regenerate_index()
    _serve_forever(host, port)
    return EXIT_OK  # not reached; _serve_forever blocks until SIGTERM/SIGINT


def cmd_expose(_args: argparse.Namespace) -> int:
    """Publish the running daemon via tailscale serve. Preserved."""
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
    """Take down tailscale serve. Preserved."""
    ok, msg = _tailscale_serve_off()
    if not ok:
        print(f"unexpose: {msg}", file=sys.stderr)
        return EXIT_SERVER
    print("unexposed")
    return EXIT_OK


def cmd_status(_args: argparse.Namespace) -> int:
    """Print daemon pid/port, URLs, and staged entries. Preserved."""
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
    projects = [
        p for p in sorted(ROOT.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    ]
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
    """Stop the daemon, unexpose, clear pid/port files. Preserved."""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            print(f"kill failed: {exc}", file=sys.stderr)
            return EXIT_SERVER
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


def cmd_clean(args: argparse.Namespace) -> int:
    """Remove one project's staging dir. Feedback DB untouched. Preserved."""
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


def cmd_feedback(args: argparse.Namespace) -> int:
    """Print feedback_dump(artifact_id) as JSON for agent consumption.

    Extended shape (threads + anchors + resolved + reply chains) per
    DESIGN.md section 8. Still a single JSON dump; backward friendly.
    """
    artifact_id = args.artifact_id.strip()
    if not artifact_id:
        print("error: --artifact required", file=sys.stderr)
        return EXIT_CALLER
    try:
        payload = feedback_dump(artifact_id)
    except sqlite3.Error as exc:
        print(f"error: db: {exc}", file=sys.stderr)
        return EXIT_SERVER
    print(json.dumps(payload, indent=2, default=str))
    return EXIT_OK


def cmd_name(args: argparse.Namespace) -> int:
    """Get/set/clear the global default comment-author name. Preserved."""
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
            print("error: empty value; use --clear to unset", file=sys.stderr)
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


# ── arg parsing ───────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Preserves the verb surface verbatim: push, unpush, start, expose,
    unexpose, status, stop, clean, feedback, name. `run` is new: a foreground
    variant of `start` for container/systemd supervision (no fork/pidfile).
    Other review capabilities are reached over HTTP, not new verbs (bd mirror
    is a `setting`, toggled via the existing name/setting path). See
    DESIGN.md section 11.
    """
    p = argparse.ArgumentParser(
        prog="artifact-serve",
        description="Stage and serve artifacts for review under /tmp/claude-artifacts/.",
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
    sp.add_argument(
        "--port", type=int,
        default=int(os.environ.get("ARTIFACT_SERVE_PORT", DEFAULT_PORT)),
    )
    sp.add_argument("--host", default=os.environ.get("ARTIFACT_SERVE_HOST", "127.0.0.1"))
    sp.add_argument("--expose", action="store_true", help="Also publish via tailscale.")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser(
        "run",
        help="Run the server in the foreground (no fork/pidfile); "
        "for container/systemd supervision.",
    )
    sp.add_argument(
        "--port", type=int,
        default=int(os.environ.get("ARTIFACT_SERVE_PORT", DEFAULT_PORT)),
    )
    sp.add_argument("--host", default=os.environ.get("ARTIFACT_SERVE_HOST", "127.0.0.1"))
    sp.set_defaults(func=cmd_run)

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
        help="Dump threads + reply chains + upload metadata for an artifact as JSON.",
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
    """Parse args and dispatch to the chosen verb. Returns process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
