#!/usr/bin/env python3
"""kb-serve.py -- containerizable HTTP facade over the personal
knowledgebase vault (see scripts/kb.sh).

A thin facade, not a rewrite: every endpoint delegates to the existing
kb-index.py (FTS5 build/query) and kb-clip.py (deterministic web capture)
scripts, loaded by path since their hyphenated filenames aren't importable
as normal modules. The only genuinely new logic here is deterministic
atomization (kb-atomize.py, sibling script) and the optional, pluggable
LLM enrichment pass.

Endpoints (all JSON):
    GET  /health              -> {status, kb_home, indexed_count}
    POST /put                 -> write a note, atomize, reindex
    POST /clip                -> capture a URL, atomize, reindex
    GET  /query                -> FTS5 search (q, project, type, all)
    POST /enrich               -> fill question/summary via the configured
                                   LLM provider; clean no-op if disabled
    POST /atomize               -> ingest a URL or raw content, split it into
                                   atomic notes via a cheap LLM tier, falling
                                   back to the deterministic heading-splitter
                                   if disabled or the call fails; reindex

CLI (also usable without the HTTP server, same functions):
    kb-serve.py run [--host H] [--port P] [--kb-home DIR]
    kb-serve.py put PROJECT TITLE [--type T] [--source S] [--kb-home DIR]
                    (content read from stdin)
    kb-serve.py clip URL [--project P] [--kb-home DIR]
    kb-serve.py query Q [--project P] [--type T] [--all] [--kb-home DIR]
    kb-serve.py atomize (--url URL | --content) [--project P] [--title T]
                    [--type T] [--kb-home DIR]
                    (with --content, content is read from stdin)
    kb-serve.py resolve-secret [--kb-home DIR]
                    prints "KB_LLM_API_KEY=<value>" for an EnvironmentFile=
                    to consume; never logs the value.

Enrichment config (env, optionally sourced from the gitignored
<kb_home>/kb.env): KB_ENRICH (0/1, default 0), KB_LLM_BASE_URL (default
OpenRouter), KB_LLM_MODEL (default openai/gpt-4o-mini), KB_ATOMIZE_MODEL
(default anthropic/claude-sonnet-4.5, a capable general model chosen for
reliable decontextualization; used only by /atomize, override for a
cheaper tier if desired), and the API key via either KB_LLM_API_KEY (static) or
KB_LLM_API_KEY_CMD (a vault CLI command whose stdout is the key, e.g.
Proton Pass's pass-cli -- wins over the static value if both are set).
With KB_ENRICH=0 or no resolvable key, /enrich is a clean no-op (zero
network calls, zero crashes) and /atomize falls back to the deterministic
splitter. The put/clip/query path never depends on any of this.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import types
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

__all__ = [
    "KbServeConfig",
    "build_config",
    "build_parser",
    "contained_path",
    "kb_atomize",
    "kb_atomize_via_llm",
    "kb_clip_and_atomize",
    "kb_enrich",
    "kb_ingest_and_atomize",
    "kb_put",
    "load_kb_env",
    "main",
    "request_atomize_split",
    "resolve_api_key",
]

log = logging.getLogger("kb-serve")

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_PORT = 9100
TYPE_TO_DIR = {
    "decision": "decisions", "note": "notes",
    "research": "research", "source": "sources",
}
DEFAULT_NOTE_TYPE = "note"

# ── security baseline (docs/design/security-baseline-threat-model.md) ──
# Loopback is NOT a trust boundary: any local process, including a browser
# tab running an attacker's JavaScript against 127.0.0.1, can reach this
# port. These constants are the workbench-wide baseline every non-artifact
# service sends and enforces; keep them identical across services.

# Every response, including errors. This service returns only JSON, so its
# CSP can forbid literally every fetch: nothing here is ever a document.
SECURITY_HEADERS = {
    "Content-Security-Policy":
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}

# Host header allowlist, checked per request: a DNS-rebinding attack sends
# the attacker's own hostname while the browser treats the connection as
# same-origin, so Origin alone cannot catch it.
ALLOWED_HOST_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})

# Requiring a JSON body content type forces a CORS preflight on any
# cross-origin POST; this service answers no preflight and sends no
# Access-Control-Allow-Origin, so the browser blocks the real request.
JSON_CONTENT_TYPE = "application/json"

# Path components that come from a request (project names): one path
# segment, no separators, no leading dot, so "..", "/etc", and
# "../../.ssh" can never be spelled.
SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"
# A capable general-purpose model: atomize's decontextualization + section
# granularity needs stay reliable. Override via KB_ATOMIZE_MODEL for a
# cheaper tier if desired.
DEFAULT_ATOMIZE_MODEL = "anthropic/claude-sonnet-4.5"
LLM_TIMEOUT_SEC = 30.0
API_KEY_CMD_TIMEOUT_SEC = 15.0
# Atomizing needs the whole document to find its section boundaries,
# hence a much bigger cap than enrich's 4000 (which only needs a gist).
ATOMIZE_PROMPT_CHAR_LIMIT = 12000
# ponytail: bounds one /enrich call's model spend to a fixed batch; call
# /enrich again to keep going rather than adding pagination for a personal
# vault of this size.
ENRICH_BATCH_LIMIT = 20

# Bounds the frontmatter block a rewrite touches: "---\n...\n---\n", so
# question/summary get patched in place without disturbing the body.
FRONTMATTER_BOUNDS_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def _load_sibling(name: str) -> types.ModuleType:
    """Dynamically import a hyphenated sibling script as a module.

    kb-index.py / kb-clip.py are executable CLIs with hyphenated
    filenames, which a normal `import` statement cannot name. Loading them
    by path lets kb-serve.py call their functions directly instead of
    copy-pasting logic (it stays a thin facade, per its own docstring).
    """
    path = SCRIPT_DIR / f"{name}.py"
    module_name = name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.11+) resolves annotations via sys.modules[cls.__module__],
    # so the module must be registered there BEFORE exec_module runs any
    # @dataclass decorators inside it, else that lookup returns None and
    # dataclass() raises AttributeError.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_kb_index_module: types.ModuleType | None = None
_kb_clip_module: types.ModuleType | None = None
_kb_atomize_module: types.ModuleType | None = None


def kb_index_module() -> types.ModuleType:
    global _kb_index_module
    if _kb_index_module is None:
        _kb_index_module = _load_sibling("kb-index")
    return _kb_index_module


def kb_clip_module() -> types.ModuleType:
    global _kb_clip_module
    if _kb_clip_module is None:
        _kb_clip_module = _load_sibling("kb-clip")
    return _kb_clip_module


def kb_atomize_module() -> types.ModuleType:
    global _kb_atomize_module
    if _kb_atomize_module is None:
        _kb_atomize_module = _load_sibling("kb-atomize")
    return _kb_atomize_module


# ── config + secret resolution ────────────────────────────────────────


@dataclass(frozen=True)
class KbServeConfig:
    """Resolved runtime config for one server/CLI invocation."""

    kb_home: Path
    enrich_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None
    atomize_model: str = DEFAULT_ATOMIZE_MODEL


def load_kb_env(kb_home: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines from <kb_home>/kb.env.

    Missing file, blank lines, and '#' comments are silently skipped;
    never raises. Not a shell parser -- values may be optionally wrapped
    in matching quotes, nothing fancier (matches kb.env.example's shape).
    """
    env_path = kb_home / "kb.env"
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_api_key(env: Mapping[str, str]) -> str | None:
    """Resolve the LLM API key: KB_LLM_API_KEY_CMD (a vault CLI command,
    e.g. Proton Pass's `pass-cli item view ... --field api-key`) wins over
    a static KB_LLM_API_KEY when it succeeds with a non-empty result. If
    the command is unset, fails, or yields nothing usable, falls back to
    the static KB_LLM_API_KEY. Returns None if neither yields one. Never
    logs the resolved value.
    """
    static_key = env.get("KB_LLM_API_KEY", "").strip() or None
    cmd = env.get("KB_LLM_API_KEY_CMD", "").strip()
    if not cmd:
        return static_key
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=API_KEY_CMD_TIMEOUT_SEC, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("KB_LLM_API_KEY_CMD failed (%s); no key resolved", exc)
        return static_key
    return result.stdout.strip() or static_key


def build_config(kb_home: Path) -> KbServeConfig:
    """Merge kb.env under the real process env (env wins) and resolve the
    enrichment flags + API key. The put/clip/query/atomize path never
    touches any value built here."""
    merged: dict[str, str] = {**load_kb_env(kb_home), **os.environ}
    enrich_enabled = merged.get("KB_ENRICH", "0") == "1"
    api_key = resolve_api_key(merged) if enrich_enabled else None
    return KbServeConfig(
        kb_home=kb_home,
        enrich_enabled=enrich_enabled,
        llm_base_url=merged.get("KB_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_model=merged.get("KB_LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_api_key=api_key,
        atomize_model=merged.get("KB_ATOMIZE_MODEL", "").strip() or DEFAULT_ATOMIZE_MODEL,
    )


# ── deterministic core: put / clip / atomize / query ──────────────────


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"{key!r} is required")
    return value


def _require_name(payload: Mapping[str, object], key: str) -> str:
    """Require a value usable as ONE path segment under the vault root.

    Every request field that becomes a directory name goes through here
    (currently only 'project'), so a traversal attempt is rejected once,
    at the entry point, rather than per call site.
    """
    value = _require_str(payload, key)
    if not SAFE_NAME_RE.fullmatch(value):
        raise ValueError(
            f"{key!r} must match {SAFE_NAME_RE.pattern} "
            f"(one path segment, no separators), got {value!r}"
        )
    return value


def _require_project(payload: Mapping[str, object], kb_home: Path) -> str:
    """Validate the 'project' field and confirm it lands inside the vault.

    The single choke point for every request that turns a project name
    into a directory, including the ones that delegate the actual write
    to kb-clip.py.
    """
    project = _require_name(payload, "project")
    contained_path(kb_home, project)
    return project


def contained_path(root: Path, *parts: str) -> Path:
    """Join parts under root, refusing any result outside it.

    Belt and braces behind _require_name: symlinked or oddly-cased vault
    layouts are re-checked after resolution, so nothing writes outside
    the vault even if a name rule is later loosened.
    """
    candidate = root.joinpath(*parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path {candidate} escapes the vault root {root}")
    return candidate


def render_note(note_type: str, title: str, source: str, project: str, body: str) -> str:
    """Serialize one manually-put note: LOCKED frontmatter + body + Refs.

    Same frontmatter shape as kb-clip.py's captured source notes (reuses
    its field list + quoting helpers), just generic to any note type.
    """
    frontmatter = {
        "type": note_type, "title": title, "source": source, "author": "",
        "site": "", "published": "", "fetched": date.today().isoformat(),
        "description": "", "tags": kb_clip_module().yaml_list([]), "project": project,
        "status": "active", "question": "", "summary": "",
    }
    lines = ["---"]
    for key in kb_clip_module().FRONTMATTER_FIELDS:
        value = frontmatter[key]
        rendered = value if key == "tags" else kb_clip_module().yaml_quote(str(value))
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", body, "", "## Refs", ""])
    if source:
        lines.append(f"- {source}")
    return "\n".join(lines) + "\n"


def build_index(kb_home: Path) -> None:
    """Rebuild kb.db from every project. Thin wrapper over kb-index.py."""
    kb_index_module().build_index(kb_home, kb_home / "index" / "kb.db")


def kb_atomize(note_path: Path, kb_home: Path) -> list[Path]:
    """Split a long source/research note into atomic children. See
    kb-atomize.py's own docstring for the deterministic split rule."""
    return kb_atomize_module().kb_atomize(note_path, kb_home)


def _write_note_file(
    kb_home: Path, project: str, note_type: str, title: str, source: str, content: str,
) -> Path:
    """Build the note's path under kb_home/<project>/<type dir>, render it,
    and write it. Raises ValueError on an unrecognized note_type."""
    dir_name = TYPE_TO_DIR.get(note_type)
    if dir_name is None:
        raise ValueError(f"unknown type {note_type!r}, expected one of {sorted(TYPE_TO_DIR)}")
    notes_dir = contained_path(kb_home, project, dir_name)
    notes_dir.mkdir(parents=True, exist_ok=True)
    note_path = kb_clip_module().build_note_path(notes_dir, kb_clip_module().slugify(title))
    note_path.write_text(render_note(note_type, title, source, project, content), encoding="utf-8")
    return note_path


def kb_put(kb_home: Path, config: KbServeConfig, payload: Mapping[str, object]) -> dict[str, object]:
    """Write one note, atomize it if it qualifies, reindex. Returns the
    created note path(s). Raises KeyError/ValueError on bad input."""
    project = _require_project(payload, kb_home)
    content = _require_str(payload, "content")
    note_type = str(payload.get("type") or DEFAULT_NOTE_TYPE)
    title = str(payload.get("title") or "untitled")
    source = str(payload.get("source") or "")

    note_path = _write_note_file(kb_home, project, note_type, title, source, content)

    children, _method = kb_atomize_via_llm(config, note_path, kb_home)
    build_index(kb_home)
    return {"path": str(note_path), "children": [str(p) for p in children]}


def kb_clip_and_atomize(kb_home: Path, payload: Mapping[str, object]) -> dict[str, object]:
    """Capture a URL (kb-clip.py), atomize it if it qualifies, reindex."""
    url = _require_str(payload, "url")
    project = _require_project(payload, kb_home)
    note_path = kb_clip_module().clip(url, project, kb_home)
    children = kb_atomize(note_path, kb_home)
    build_index(kb_home)
    return {"path": str(note_path), "children": [str(p) for p in children]}


def run_query(kb_home: Path, q: str, project: str | None, note_type: str | None, include_all: bool) -> list[dict]:
    """Thin wrapper over kb-index.py's FTS5 query."""
    db_path = kb_home / "index" / "kb.db"
    return kb_index_module().query_index(db_path, q, project, note_type, include_all)


def count_indexed_notes(kb_home: Path) -> int:
    """Row count in kb.db, or 0 if it hasn't been built yet."""
    db_path = kb_home / "index" / "kb.db"
    if not db_path.exists():
        return 0
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
    finally:
        con.close()


# ── LLM enrichment (the only model-spend path, off by default) ────────


def find_unenriched_notes(
    kb_home: Path, project: str | None, note_filter: str | None,
) -> list[Path]:
    """Notes with an empty question or summary, capped at
    ENRICH_BATCH_LIMIT. note_filter, if given, targets exactly that path,
    resolved against kb_home -- an absolute or ../-escaping value that
    lands outside kb_home is treated as "no matching note" (empty list),
    never read, per this module's clean-no-op philosophy."""
    if note_filter:
        candidate = (kb_home / note_filter).resolve()
        if not candidate.is_relative_to(kb_home.resolve()) or not candidate.is_file():
            return []
        return [candidate]
    unenriched: list[Path] = []
    for path in kb_index_module().find_markdown_files(kb_home):
        if project and kb_index_module().derive_project(path, kb_home) != project:
            continue
        fields, _ = kb_index_module().parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fields.get("question") or not fields.get("summary"):
            unenriched.append(path)
        if len(unenriched) >= ENRICH_BATCH_LIMIT:
            break
    return unenriched


def _chat_completion_json(config: KbServeConfig, model: str, prompt: str) -> dict:
    """One chat-completions POST expecting a JSON object back; shared by
    request_enrichment and request_atomize_split -- only the model and
    prompt differ between the two call sites.

    Raises on any network/parse failure; callers decide how to degrade.
    """
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{config.llm_base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SEC) as response:
        data = json.loads(response.read())
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def request_enrichment(config: KbServeConfig, title: str, body: str) -> dict[str, str]:
    """One chat-completions call asking for {question, summary} JSON.

    Raises on any network/parse failure; kb_enrich decides how to degrade
    (skip that note, keep going).
    """
    prompt = (
        "Given this knowledgebase note, respond with ONLY a JSON object "
        '{"question": "...", "summary": "..."}. question = the question '
        "someone would search to find this note. summary = a 2-3 sentence "
        f"summary of its content.\n\nTitle: {title}\n\n{body[:4000]}"
    )
    parsed = _chat_completion_json(config, config.llm_model, prompt)
    return {
        "question": str(parsed.get("question", "")),
        "summary": str(parsed.get("summary", "")),
    }


def _hard_cut_chunks(text: str, limit: int) -> list[str]:
    return [text[index:index + limit] for index in range(0, len(text), limit)]


def _paragraph_chunks(section: str, limit: int) -> list[str]:
    paragraphs = section.split("\n\n")
    chunks: list[str] = []
    current = ""
    for index, paragraph in enumerate(paragraphs):
        suffix = "\n\n" if index < len(paragraphs) - 1 else ""
        unit = f"{paragraph}{suffix}"
        if len(unit) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_cut_chunks(unit, limit))
        elif current and len(current) + len(unit) > limit:
            chunks.append(current)
            current = unit
        else:
            current += unit
    if current:
        chunks.append(current)
    return chunks


def _heading_sections(body: str) -> list[str]:
    headings = list(re.finditer(r"(?m)^#", body))
    if not headings:
        return [body]
    sections: list[str] = []
    if headings[0].start() > 0:
        sections.append(body[:headings[0].start()])
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        sections.append(body[heading.start():end])
    return [section for section in sections if section]


def _atomize_prompt_body_chunks(body: str) -> list[str]:
    if len(body) <= ATOMIZE_PROMPT_CHAR_LIMIT:
        return [body]
    chunks: list[str] = []
    current = ""
    for section in _heading_sections(body):
        if len(section) > ATOMIZE_PROMPT_CHAR_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_paragraph_chunks(section, ATOMIZE_PROMPT_CHAR_LIMIT))
        elif current and len(current) + len(section) > ATOMIZE_PROMPT_CHAR_LIMIT:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)
    return chunks


def _parse_atomize_notes(parsed: dict[str, object]) -> list[dict[str, str]]:
    notes = parsed["notes"]
    if not isinstance(notes, list):
        raise KeyError("'notes' in atomize response is not a list")
    return [
        {"title": str(item.get("title", "")), "body": str(item.get("body", ""))}
        for item in notes if isinstance(item, dict)
    ]


def request_atomize_split(config: KbServeConfig, title: str, body: str) -> list[dict[str, str]]:
    """Ask the cheap atomize tier to split a document into self-contained
    atomic notes: {"notes": [{"title", "body"}, ...]}.

    Raises on any network/parse failure (including a missing/malformed
    "notes" list); kb_atomize_via_llm decides how to degrade (falls back
    to the deterministic splitter).
    """
    notes: list[dict[str, str]] = []
    for chunk in _atomize_prompt_body_chunks(body):
        prompt = (
            "Split the following knowledgebase note into distinct, "
            "self-contained atomic notes. Respond with ONLY a JSON object "
            '{"notes": [{"title": "...", "body": "..."}, ...]}.\n\n'
            f"Title: {title}\n\n{chunk}"
        )
        parsed = _chat_completion_json(config, config.atomize_model, prompt)
        notes.extend(_parse_atomize_notes(parsed))
    return notes


def apply_enrichment(note_path: Path, question: str, summary: str) -> None:
    """Rewrite only the question/summary frontmatter lines in place; every
    other line, including the body, is left byte-for-byte untouched."""
    text = note_path.read_text(encoding="utf-8")
    match = FRONTMATTER_BOUNDS_RE.match(text)
    if not match:
        return
    head, raw_fields, tail = match.groups()
    raw_fields = re.sub(
        r"^question:.*$", f"question: {kb_clip_module().yaml_quote(question)}",
        raw_fields, count=1, flags=re.MULTILINE,
    )
    raw_fields = re.sub(
        r"^summary:.*$", f"summary: {kb_clip_module().yaml_quote(summary)}",
        raw_fields, count=1, flags=re.MULTILINE,
    )
    note_path.write_text(head + raw_fields + tail + text[match.end():], encoding="utf-8")


def kb_enrich(config: KbServeConfig, payload: Mapping[str, object]) -> dict[str, object]:
    """Fill question/summary on unenriched notes via the configured LLM.

    Clean no-op (zero network calls) if KB_ENRICH=0 or no API key
    resolved -- the caller always gets a 200 with a clear `message`,
    never a crash.
    """
    if not config.enrich_enabled:
        return {"enriched": 0, "message": "KB_ENRICH is 0; enrichment disabled"}
    if not config.llm_api_key:
        return {
            "enriched": 0,
            "message": "KB_ENRICH=1 but no API key resolved "
                       "(checked KB_LLM_API_KEY_CMD, KB_LLM_API_KEY)",
        }

    project = payload.get("project")
    note_filter = payload.get("note")
    notes = find_unenriched_notes(
        config.kb_home,
        str(project) if project else None,
        str(note_filter) if note_filter else None,
    )
    enriched: list[str] = []
    for note_path in notes:
        try:
            fields, body = kb_index_module().parse_frontmatter(note_path.read_text(encoding="utf-8"))
            result = request_enrichment(config, str(fields.get("title", note_path.stem)), body)
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
            log.warning("enrichment failed for %s: %s", note_path, exc)
            continue
        apply_enrichment(note_path, result["question"], result["summary"])
        enriched.append(str(note_path))

    if enriched:
        build_index(config.kb_home)
    return {"enriched": len(enriched), "notes": enriched}


# ── LLM-tier atomize (deterministic fallback, second model-spend path) ──


def _write_llm_child_note(
    note_path: Path, fields: dict[str, object], item: dict[str, str],
) -> Path:
    """Write one LLM-proposed atomic child note as a sibling of
    note_path, reusing kb-atomize.py's own child-note renderer."""
    slug = f"{note_path.stem}--{kb_clip_module().slugify(item['title'])}"
    child_path = kb_clip_module().build_note_path(note_path.parent, slug)
    child_path.write_text(
        kb_atomize_module().render_child_note(fields, note_path, item["title"], item["body"]),
        encoding="utf-8",
    )
    return child_path


def kb_atomize_via_llm(config: KbServeConfig, note_path: Path, kb_home: Path) -> tuple[list[Path], str]:
    """Split note_path into atomic children via the configured cheap LLM
    tier; falls back to the deterministic heading-splitter (kb_atomize)
    when disabled, no key resolved, or the call fails -- same no-op
    philosophy as kb_enrich, applied per-note. Returns (children, method)
    where method is "llm" or "deterministic".
    """
    fields, body = kb_index_module().parse_frontmatter(note_path.read_text(encoding="utf-8"))
    if config.enrich_enabled and config.llm_api_key:
        try:
            notes = request_atomize_split(config, str(fields.get("title", note_path.stem)), body)
        except (
            OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError,
            KeyError, IndexError, ValueError,
        ) as exc:
            log.warning("LLM atomize failed for %s: %s", note_path, exc)
        else:
            children = [_write_llm_child_note(note_path, fields, item) for item in notes]
            return children, "llm"

    return kb_atomize(note_path, kb_home), "deterministic"


def kb_ingest_and_atomize(
    kb_home: Path, config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Ingest a URL or raw content, atomize it via the configured LLM
    tier (deterministic fallback), reindex. Mirrors kb_put's and
    kb_clip_and_atomize's shape; unit-testable without a server. Raises
    KeyError/ValueError on bad input, OSError/URLError on a failed fetch.
    """
    project = _require_project(payload, kb_home)
    url = payload.get("url")
    content = payload.get("content")
    title = str(payload.get("title") or "untitled")
    note_type = str(payload.get("type") or "source")

    if url:
        note_path = kb_clip_module().clip(str(url), project, kb_home)
    elif content:
        note_path = _write_note_file(kb_home, project, note_type, title, source="", content=str(content))
    else:
        raise KeyError("either 'url' or 'content' is required")

    children, method = kb_atomize_via_llm(config, note_path, kb_home)
    build_index(kb_home)
    return {"parent": str(note_path), "children": [str(p) for p in children], "method": method}


# ── HTTP server ─────────────────────────────────────────────────────────


class KbHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the resolved KbServeConfig."""

    def __init__(self, address: tuple[str, int], handler_cls: type, config: KbServeConfig) -> None:
        self.config = config
        super().__init__(address, handler_cls)


class KbRequestHandler(BaseHTTPRequestHandler):
    """Dispatches the JSON endpoints onto the module-level pure functions
    above; carries no logic of its own beyond wiring."""

    server: KbHTTPServer  # type: ignore[assignment]  # narrows the stdlib base's untyped .server attr

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def end_headers(self) -> None:
        """Stamp the security baseline onto EVERY response.

        Here rather than in _send_json so that the stdlib's own
        send_error() replies (405/501 for methods this handler does not
        implement) carry the headers too.
        """
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}

    def _reject_browser_origin(self) -> bool:
        """Answer 403 and return True when the request looks like it came
        from a web page rather than the CLI.

        Two checks, because neither covers the other: a cross-origin
        request carries an Origin header we never allowlist, and a
        DNS-rebound request is same-origin (no Origin header at all) but
        carries the attacker's hostname in Host.
        """
        if self.headers.get("Origin"):
            self._send_json(403, {"error": "cross-origin requests are refused"})
            return True
        host = self.headers.get("Host", "")
        # urlparse strips the :port and the IPv6 brackets for us.
        hostname = urlparse(f"//{host}").hostname or ""
        if hostname not in ALLOWED_HOST_NAMES:
            self._send_json(403, {"error": f"unexpected Host header {host!r}"})
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802 stdlib override name
        if self._reject_browser_origin():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            kb_home = self.server.config.kb_home
            return self._send_json(200, {
                "status": "ok", "kb_home": str(kb_home),
                "indexed_count": count_indexed_notes(kb_home),
            })
        if parsed.path == "/query":
            return self._handle_query(parse_qs(parsed.query))
        self._send_json(404, {"error": "not found"})

    def _handle_query(self, qs: dict[str, list[str]]) -> None:
        q = (qs.get("q") or [""])[0]
        if not q:
            return self._send_json(400, {"error": "q is required"})
        project = (qs.get("project") or [None])[0]
        note_type = (qs.get("type") or [None])[0]
        include_all = (qs.get("all") or ["0"])[0] == "1"
        results = run_query(self.server.config.kb_home, q, project, note_type, include_all)
        self._send_json(200, {"results": results})

    def do_POST(self) -> None:  # noqa: N802 stdlib override name
        if self._reject_browser_origin():
            return
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type != JSON_CONTENT_TYPE:
            return self._send_json(415, {
                "error": f"Content-Type must be {JSON_CONTENT_TYPE}, "
                         f"got {content_type or 'none'}",
            })
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError as exc:
            return self._send_json(400, {"error": f"invalid JSON body: {exc}"})

        if parsed.path == "/put":
            return self._handle_put(payload)
        if parsed.path == "/clip":
            return self._handle_clip(payload)
        if parsed.path == "/enrich":
            return self._send_json(200, kb_enrich(self.server.config, payload))
        if parsed.path == "/atomize":
            return self._handle_atomize(payload)
        self._send_json(404, {"error": "not found"})

    def _handle_put(self, payload: dict[str, object]) -> None:
        try:
            result = kb_put(self.server.config.kb_home, self.server.config, payload)
        except (KeyError, ValueError) as exc:
            return self._send_json(400, {"error": str(exc)})
        self._send_json(201, result)

    def _handle_clip(self, payload: dict[str, object]) -> None:
        try:
            result = kb_clip_and_atomize(self.server.config.kb_home, payload)
        except (KeyError, ValueError) as exc:
            return self._send_json(400, {"error": str(exc)})
        except (OSError, urllib.error.URLError) as exc:
            return self._send_json(502, {"error": f"clip fetch failed: {exc}"})
        self._send_json(201, result)

    def _handle_atomize(self, payload: dict[str, object]) -> None:
        try:
            result = kb_ingest_and_atomize(self.server.config.kb_home, self.server.config, payload)
        except (KeyError, ValueError) as exc:
            return self._send_json(400, {"error": str(exc)})
        except (OSError, urllib.error.URLError) as exc:
            return self._send_json(502, {"error": f"atomize fetch failed: {exc}"})
        self._send_json(201, result)


def serve_forever(config: KbServeConfig, host: str, port: int) -> None:
    server = KbHTTPServer((host, port), KbRequestHandler, config)
    log.info("kb-serve listening on %s:%s (kb_home=%s)", host, port, config.kb_home)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ── CLI ─────────────────────────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    (kb_home / "index").mkdir(parents=True, exist_ok=True)
    serve_forever(build_config(kb_home), args.host, args.port)
    return 0


def cmd_put(args: argparse.Namespace) -> int:
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    payload = {
        "project": args.project, "title": args.title, "type": args.type,
        "source": args.source, "content": sys.stdin.read(),
    }
    print(json.dumps(kb_put(kb_home, build_config(kb_home), payload)))
    return 0


def cmd_clip(args: argparse.Namespace) -> int:
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    print(json.dumps(kb_clip_and_atomize(kb_home, {"url": args.url, "project": args.project})))
    return 0


def cmd_atomize(args: argparse.Namespace) -> int:
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    payload: dict[str, object] = {"project": args.project, "title": args.title, "type": args.type}
    if args.url:
        payload["url"] = args.url
    else:
        payload["content"] = sys.stdin.read()
    print(json.dumps(kb_ingest_and_atomize(kb_home, build_config(kb_home), payload)))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    results = run_query(kb_home, args.q, args.project, args.type, args.all)
    print(json.dumps({"results": results}, indent=2))
    return 0


def cmd_resolve_secret(args: argparse.Namespace) -> int:
    """Print `KB_LLM_API_KEY=<value>` for an EnvironmentFile= to consume.

    The only line ever written to stdout; the resolved value is never
    logged. Empty value (still prints the key, blank) if neither
    KB_LLM_API_KEY_CMD nor KB_LLM_API_KEY resolves -- callers treat that
    the same as "no key configured".
    """
    kb_home = kb_index_module().resolve_kb_home(args.kb_home)
    merged = {**load_kb_env(kb_home), **os.environ}
    print(f"KB_LLM_API_KEY={resolve_api_key(merged) or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="serve the HTTP facade in the foreground")
    run_cmd.add_argument("--host", default=os.environ.get("KB_SERVE_HOST", "127.0.0.1"))
    run_cmd.add_argument("--port", type=int, default=int(os.environ.get("KB_SERVE_PORT", DEFAULT_PORT)))
    run_cmd.add_argument("--kb-home", default=None)

    put_cmd = sub.add_parser("put", help="write + atomize + index one note (content on stdin)")
    put_cmd.add_argument("project")
    put_cmd.add_argument("title")
    put_cmd.add_argument("--type", default=DEFAULT_NOTE_TYPE)
    put_cmd.add_argument("--source", default="")
    put_cmd.add_argument("--kb-home", default=None)

    clip_cmd = sub.add_parser("clip", help="capture a URL + atomize + index")
    clip_cmd.add_argument("url")
    clip_cmd.add_argument("--project", default="inbox")
    clip_cmd.add_argument("--kb-home", default=None)

    atomize_cmd = sub.add_parser(
        "atomize",
        help="ingest a URL or raw content (stdin), atomize via the LLM tier "
             "(deterministic fallback), index",
    )
    atomize_cmd.add_argument("--url", default=None, help="URL to ingest; omit to read content from stdin")
    atomize_cmd.add_argument("--project", default="inbox")
    atomize_cmd.add_argument("--title", default="untitled")
    atomize_cmd.add_argument("--type", default="source")
    atomize_cmd.add_argument("--kb-home", default=None)

    query_cmd = sub.add_parser("query", help="full-text search the index")
    query_cmd.add_argument("q")
    query_cmd.add_argument("--project", default=None)
    query_cmd.add_argument("--type", default=None)
    query_cmd.add_argument("--all", action="store_true", help="include superseded notes")
    query_cmd.add_argument("--kb-home", default=None)

    secret_cmd = sub.add_parser(
        "resolve-secret",
        help="print the resolved LLM API key for a systemd EnvironmentFile=",
    )
    secret_cmd.add_argument("--kb-home", default=None)

    return parser


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    dispatch = {
        "run": cmd_run, "put": cmd_put, "clip": cmd_clip, "atomize": cmd_atomize,
        "query": cmd_query, "resolve-secret": cmd_resolve_secret,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
