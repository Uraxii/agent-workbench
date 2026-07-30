#!/usr/bin/env python3
"""kb-svc.py -- the knowledgebase service.

Endpoints only, no UI: Obsidian already opens the vault. This process is
the ONLY thing that opens ``$KB_HOME``; the agent-workbench CLI is an
HTTP client of it and there is no filesystem fallback anywhere.

The vault is Obsidian-compatible markdown and is the only source of
truth. ``index/kb.db`` (FTS5 rows plus vectors) is derived from it and
nothing else, which is why ``POST /reindex`` is a complete recovery path.
Atomization, indexing and embedding are unconditional on every ingest
route -- there is no flag that skips them and no ingest path that omits
them. Embedding is scoped to the ingested note and its children, not the
whole vault: see POST /embed/* to backfill everything else.

Endpoints (all JSON):
    GET  /health                     status, vault, indexed + vector counts
    GET  /status                     vault root, initialized, projects
    GET  /project?project=P          P's vault path and whether it exists
    GET  /query?q=&project=&type=&all=1
                                     hybrid keyword + vector search
    GET  /decision/audit?topic=&project=
                                     a topic's revision chain
    POST /vault/init                 create the vault dirs (idempotent)
    POST /project/init {project}     create a project's note dirs
    POST /put   {project,title,type,source,content}
                                     write a note, atomize, reindex
    POST /clip  {url,project}        capture a URL, atomize, reindex
    POST /atomize {project,url|content,title,type}
                                     ingest either shape, atomize, reindex
    POST /reindex                    rebuild every derived artifact
    POST /decision {project,topic,title,text,...}
                                     record a decision, revise the prior
    POST /enrich {project?,note?}    fill question/summary via the LLM
    POST /embed/missing {dry_run?}
                                     embed stale notes, bounded + resumable
    POST /embed/all {dry_run?}
                                     mark every note stale, then one bounded
                                     batch

CLI:
    kb-svc.py run [--host H] [--port P] [--kb-home DIR]
    kb-svc.py resolve-secret [--kb-home DIR]
        prints "KB_LLM_API_KEY=<value>" for an EnvironmentFile to consume;
        never logs the value. Exists only for the kb-svc quadlet's
        ExecStartPre and retires with it.

Config (env, optionally from the gitignored ``<kb_home>/kb.env``) is
documented in kb_config.py. Everything model-backed is off by default and
degrades to the deterministic path rather than failing.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import urllib.error
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_decision  # noqa: E402
import kb_embed  # noqa: E402
import kb_llm  # noqa: E402
import kb_vault  # noqa: E402
from kb_config import (  # noqa: E402
    DEFAULT_PORT,
    KbServeConfig,
    build_config,
    load_kb_env,
    load_sibling,
    resolve_api_key,
    resolve_kb_home,
)
from kb_llm import (  # noqa: E402
    apply_enrichment,
    find_unenriched_notes,
    fold_call_records,
    kb_atomize_via_llm,
    kb_enrich,
    request_atomize_split,
    request_enrichment,
)

__all__ = [
    "KbServeConfig",
    "apply_enrichment",
    "backfill_embeddings",
    "build_config",
    "build_parser",
    "cmd_resolve_secret",
    "count_indexed_notes",
    "find_unenriched_notes",
    "fold_call_records",
    "kb_atomize_via_llm",
    "kb_clip_and_atomize",
    "kb_clip_module",
    "kb_enrich",
    "kb_ingest_and_atomize",
    "kb_put",
    "load_kb_env",
    "main",
    "rebuild_derived",
    "record_decision",
    "request_atomize_split",
    "request_enrichment",
    "resolve_api_key",
    "search",
]

log = logging.getLogger("kb-svc")

INDEX_DIR = "index"
INDEX_DB_NAME = "kb.db"
# Prefix for the copy-pasteable command in a /embed response's "next"
# field. Left as the literal "$HOME" the CLI docs already use everywhere
# else (see modes/kb.md's `AW=$HOME/...` line): the caller's shell expands
# it, this process never does.
NEXT_COMMAND_PREFIX = "$HOME/.claude/skills/agent-workbench/agent-workbench"
ATOMIZE_BACKFILL_MESSAGE = (
    "re-atomizing is out of scope by decision, not unimplemented: it "
    "requires deleting a note's prior atomize children first, which the "
    "standing no-delete decision forbids. Re-atomizing is a human "
    "out-of-band operation; this route covers the vector tier only."
)
EMBEDDINGS_DISABLED_MESSAGE = (
    "KB_EMBED_MODEL is unset or no API key resolved (checked "
    "KB_LLM_API_KEY_CMD, KB_LLM_API_KEY); embeddings disabled"
)
# One request body is one note, not a file upload: 8 MiB is far past any
# real note and keeps an unauthenticated loopback caller from making the
# service read an unbounded body into memory.
MAX_BODY_BYTES = 8 * 1024 * 1024

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


def kb_index_module() -> ModuleType:
    """The FTS5 index script (hyphenated filename, loaded by path)."""
    return load_sibling("kb-index")


def kb_clip_module() -> ModuleType:
    """The deterministic web-capture script."""
    return load_sibling("kb-clip")


def index_db_path(kb_home: Path) -> Path:
    """``<kb_home>/index/kb.db`` -- the whole derived layer, one file.

    Checked like every other vault path: if ``index/`` is a symlink out
    of the vault, the service would create and write the database
    somewhere it does not own.
    """
    return kb_vault.assert_inside_vault(
        kb_home, kb_home / INDEX_DIR / INDEX_DB_NAME,
    )


# ── derived layer: rebuildable from the vault alone ───────────────────


def _note_texts(kb_home: Path) -> list[tuple[str, str]]:
    """``(path, text)`` for every vault note, skipping unreadable ones."""
    texts: list[tuple[str, str]] = []
    for path in kb_index_module().find_markdown_files(kb_home):
        try:
            texts.append((str(path), path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skipping unreadable note %s: %s", path, exc)
    return texts


def _rebuild_index(kb_home: Path, db_path: Path) -> int:
    """Rebuild the FTS5 index whole from the vault markdown alone.

    Local and offline (measured 0.604s for the whole vault) and a full
    rebuild is the only trivially-idempotent shape, so every derived-layer
    entry point rebuilds it whole rather than trying to patch it in place.
    """
    kb_vault.vault_init(kb_home)
    return kb_index_module().build_index(kb_home, db_path)


def rebuild_derived(config: KbServeConfig) -> dict[str, object]:
    """Rebuild every derived artifact from the vault markdown alone.

    Rebuilds the FTS5 index whole, then incrementally syncs (embeds only
    what is stale) and prunes the vector table. Takes no input but the
    vault, which is what makes it the recovery path when the index is
    lost or the vault was edited outside this service.

    Deliberately still UNBOUNDED: this is the documented complete
    recovery path (``POST /reindex``) and must converge in one call. On a
    cold or freshly migrated database it costs exactly what it cost
    before this change -- a strict non-regression. ``POST
    /embed/missing`` is the bounded, resumable route for keeping
    vectors current day to day; this is the "start over" path.
    """
    kb_home = config.kb_home
    db_path = index_db_path(kb_home)
    indexed = _rebuild_index(kb_home, db_path)
    notes = _note_texts(kb_home)
    stale = kb_embed.stale_notes(db_path, notes)
    embed_counts = kb_embed.sync_vectors(config, db_path, stale)
    kb_embed.prune_vectors(db_path, {path for path, _ in notes})
    return {
        "indexed": indexed, "embedded": embed_counts.embedded, "db": str(db_path),
    }


def count_indexed_notes(kb_home: Path) -> int:
    """FTS5 row count, or 0 if the index has not been built yet."""
    db_path = index_db_path(kb_home)
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


def search(
    config: KbServeConfig,
    query: str,
    project: str | None,
    note_type: str | None,
    include_all: bool,
) -> list[dict[str, object]]:
    """Hybrid retrieval: FTS5 keyword hits, reranked by vector similarity.

    The keyword half decides WHICH notes match (and applies the project,
    type and revised filters); the vector half only reorders them, so
    an unavailable or unconfigured embedding backend degrades to plain
    keyword ranking instead of changing what is visible.
    """
    db_path = index_db_path(config.kb_home)
    if not db_path.exists():
        return []
    keyword_results = kb_index_module().query_index(
        db_path, query, project, note_type, include_all,
    )
    vector_paths = kb_embed.search_ranking(config, db_path, query)
    return kb_embed.fuse_rankings(keyword_results, vector_paths)


# ── ingest: atomize + index + embed, always ───────────────────────────


def _embed_notes(
    config: KbServeConfig, paths: Sequence[Path],
) -> kb_embed.EmbedCounts:
    """Read ``paths`` off disk and sync exactly their vectors.

    O(len(paths)) in both file reads and backend calls, independent of
    vault size. Unreadable notes are skipped with a warning, matching
    ``_note_texts``.
    """
    notes: list[tuple[str, str]] = []
    for path in paths:
        try:
            notes.append((str(path), path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skipping unreadable note %s: %s", path, exc)
    db_path = index_db_path(config.kb_home)
    return kb_embed.sync_vectors(config, db_path, notes)


def _finish_ingest(
    config: KbServeConfig, note_path: Path,
) -> dict[str, object]:
    """Atomize, reindex, then embed only the note and its children.

    Keeping this on one path is the invariant: no caller can write a NEW
    note into the vault through this function without its children, its
    index rows and its vectors being produced in the same request.
    Embedding is scoped to ``[note_path] + children`` rather than the
    whole vault: ingest is O(1) in vault size no matter how many stale
    rows exist elsewhere, which is also what makes the vector migration
    safe. ``kb decision record`` also flips a PRIOR note's status to
    ``revised`` in place, outside this function; the whole-vault
    ``_rebuild_index`` call below already reads that new status off
    disk, so the index row is fresh for free, and ``record_decision``
    separately feeds the prior path through ``_embed_notes`` so its
    vector does not go stale either.

    DELIBERATE ASYMMETRY (also see ``backfill_embeddings``): an embedding failure
    here still returns normally with ``embed_error`` set, never raises,
    because the note is already safely in the vault and failing the
    write would be worse.
    """
    children, method, call_records = kb_llm.kb_atomize_via_llm(
        config, note_path, config.kb_home,
    )
    db_path = index_db_path(config.kb_home)
    indexed = _rebuild_index(config.kb_home, db_path)
    embed_counts = _embed_notes(config, [note_path, *children])
    response = {
        "path": str(note_path),
        "children": [str(child) for child in children],
        "method": method,
        "indexed": indexed,
        "embedded": embed_counts.embedded,
    }
    if embed_counts.error:
        response["embed_error"] = embed_counts.error
    if call_records:
        response["usage"] = fold_call_records(call_records)
    return response


def kb_put(
    kb_home: Path, config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Write one note, atomize it, rebuild the derived layer."""
    note_path = kb_vault.write_note(
        kb_home,
        payload.get("project"),
        payload.get("type"),
        payload.get("title"),
        payload.get("source"),
        payload.get("content"),
    )
    return _finish_ingest(config, note_path)


def _clip_url(kb_home: Path, url: object, project: object) -> Path:
    """Capture a URL into the vault, validating both inputs first.

    kb-clip.py owns the URL checks (http/https scheme allowlist, refusal
    to fetch a private or loopback destination); this only guarantees the
    project directory it writes into is a legitimate one.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url is required")
    name = kb_vault.validate_project(project)
    kb_vault.project_init(kb_home, name)
    return kb_clip_module().clip(url, name, kb_home)


def kb_clip_and_atomize(
    kb_home: Path, config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Capture a URL, atomize it, rebuild the derived layer."""
    note_path = _clip_url(kb_home, payload.get("url"), payload.get("project"))
    return _finish_ingest(config, note_path)


def kb_ingest_and_atomize(
    kb_home: Path, config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Ingest a URL or raw content, atomize, rebuild the derived layer.

    Raises KeyError/ValueError on bad input, OSError/URLError on a failed
    fetch.
    """
    url = payload.get("url")
    if url:
        note_path = _clip_url(kb_home, url, payload.get("project"))
    elif payload.get("content"):
        note_path = kb_vault.write_note(
            kb_home,
            payload.get("project"),
            payload.get("type") or "source",
            payload.get("title"),
            "",
            payload.get("content"),
        )
    else:
        raise ValueError("either 'url' or 'content' is required")

    result = _finish_ingest(config, note_path)
    return {"parent": result["path"], **result}


def record_decision(
    config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Record a decision note, then finish it like any other ingest.

    Recording writes markdown into the vault, so it goes through the same
    ``_finish_ingest`` as put and clip rather than around it. The
    atomizer's own type rule then reports a decision as already atomic,
    which is the answer, not an exemption.

    Recording also flips a PRIOR note to ``revised`` in place (see
    ``kb_decision.record``); ``_finish_ingest``'s whole-vault reindex
    already picks up that new status, so only its vector is still stale
    afterward. This refreshes that vector too, in the same request,
    through the same scoped ``_embed_notes`` ingest uses -- reported as
    ``revised_embedded`` (0 when there is no prior note, embeddings are
    off, or the topic is new; see ``embeddings_enabled``). Same
    asymmetry as ``_finish_ingest``: a failure here sets
    ``revised_embed_error`` and never raises.
    """
    result = kb_decision.record(config.kb_home, payload)
    finished = _finish_ingest(config, Path(result["path"]))
    revises = result["revises"]
    response = {**finished, "revises": revises}
    if revises:
        revised_counts = _embed_notes(config, [Path(revises)])
        response["revised_embedded"] = revised_counts.embedded
        if revised_counts.error:
            response["revised_embed_error"] = revised_counts.error
    return response


def audit_decisions(
    kb_home: Path, topic: str, project: str | None,
) -> list[dict[str, str]]:
    """A topic's revision chain as plain JSON rows, oldest first."""
    dirs = kb_decision.find_decision_dirs(kb_home, project)
    return [
        {
            "date": note.decision_date,
            "status": note.status,
            "title": note.title,
            "path": str(note.path),
            "revises": note.revises,
        }
        for note in kb_decision.audit(dirs, topic)
    ]


# ── embed: bounded, resumable vector backfill ──────────────────────────


def _backfill_atomize_block() -> dict[str, object]:
    """The always-present, always-disabled atomize block (see SCOPE
    BOUNDARY in the embed-backfill design: re-atomizing needs a note's
    prior atomize children deleted first, which the standing no-delete
    decision forbids).

    ``processed``/``remaining`` are ``null``, not ``0``: a real ``0``
    reads as "nothing to do", which is not true here -- this tier has
    never run at all, and null must never be mistaken for a completed
    pass.
    """
    return {
        "enabled": False, "processed": None, "remaining": None,
        "message": ATOMIZE_BACKFILL_MESSAGE,
    }


def _backfill_disabled(mode: str, dry_run: bool) -> dict[str, object]:
    """The whole-response shape when no embedding backend is configured.

    200, never an error: offline is a fallback for this route exactly
    like every other one.
    """
    embeddings = {
        "enabled": False, "embedded": 0, "pruned": 0,
        "remaining": 0, "chars_sent": 0,
        "message": EMBEDDINGS_DISABLED_MESSAGE,
    }
    return {
        "mode": mode, "dry_run": dry_run,
        "embeddings": embeddings, "atomize": _backfill_atomize_block(),
        "next": None,
    }


def _backfill_dry_run(
    mode: str, db_path: Path, stale: list[tuple[str, str]], live_paths: set[str],
) -> dict[str, object]:
    """Report what the WHOLE remaining job would send, with zero side
    effects.

    Unlike a real call, a dry run is never capped to one
    ``BACKFILL_BATCH_LIMIT`` batch: its purpose is previewing the full
    operation (how much data leaves the machine, how many invocations
    the ``next``-loop will take) before an operator starts paying for it,
    so ``stale`` here is the entire remaining set, not one call's slice.
    """
    chars_to_send = kb_embed.embed_payload_chars([text for _, text in stale])
    calls_required = -(-len(stale) // kb_embed.BACKFILL_BATCH_LIMIT)
    would_prune = len(set(kb_embed.stored_fingerprints(db_path)) - live_paths)
    embeddings = {
        "enabled": True,
        "would_embed": len(stale),
        "would_prune": would_prune,
        "chars_to_send": chars_to_send,
        "estimated_tokens": chars_to_send // 4,
        "estimated_tokens_basis":
            "chars_to_send // 4; an estimate, not a billed count",
        "batch_limit": kb_embed.BACKFILL_BATCH_LIMIT,
        "calls_required": calls_required,
    }
    # A dry run's next always names the verb you just dry-ran: running it
    # for real is the whole point, and there is nothing to wait on.
    next_command = (
        None if not stale else f"{NEXT_COMMAND_PREFIX} kb embed {mode}"
    )
    return {
        "mode": mode, "dry_run": True,
        "embeddings": embeddings, "atomize": _backfill_atomize_block(),
        "next": next_command,
    }


def _backfill_real(
    config: KbServeConfig,
    mode: str,
    db_path: Path,
    work: list[tuple[str, str]],
    live_paths: set[str],
    stale_count: int,
) -> dict[str, object]:
    """Embed ``work``, prune, and report what actually happened.

    DELIBERATE ASYMMETRY (also see ``_finish_ingest``): on ``/put``
    ``/clip`` ``/atomize`` ``/decision`` an embedding failure still
    returns 2xx and degrades to keyword-only, because the note is safely
    in the vault and failing the write would be worse. Here, embedding
    IS the operation, so a backend failure comes back as an ``error`` key
    (the HTTP layer turns that into 502), with whatever batches already
    committed kept and counted.
    """
    embed_counts = kb_embed.sync_vectors(config, db_path, work)
    pruned = kb_embed.prune_vectors(db_path, live_paths)
    remaining = stale_count - embed_counts.embedded
    embeddings = {
        "enabled": True,
        "embedded": embed_counts.embedded,
        "pruned": pruned,
        "remaining": remaining,
        "chars_sent": embed_counts.chars_sent,
    }
    if embed_counts.usage:
        embeddings["usage"] = embed_counts.usage
    # all never points back at itself: it resets every hash on every
    # call, so a caller that kept calling "all" until remaining hit 0
    # would never terminate. missing is the only convergent loop target.
    next_command = (
        None if remaining == 0 else f"{NEXT_COMMAND_PREFIX} kb embed missing"
    )
    result = {
        "mode": mode, "dry_run": False,
        "embeddings": embeddings, "atomize": _backfill_atomize_block(),
        "next": next_command,
    }
    if embed_counts.error:
        result["error"] = f"embedding backend failed: {embed_counts.error}"
    return result


def backfill_embeddings(
    config: KbServeConfig, reset: bool, dry_run: bool,
) -> dict[str, object]:
    """One bounded, resumable vector-backfill pass.

    ``reset`` is the ONLY difference between the two routes: True marks
    every stored hash NULL first (``/embed/all``), False does not
    (``/embed/missing``). Everything after is one code path, so
    ``all`` inherits ``missing``'s boundedness and resumability for
    free. At most ``kb_embed.BACKFILL_BATCH_LIMIT`` notes are embedded
    per call. ``dry_run`` runs the identical scan, skips the reset, the
    prune and every network call, and reports the exact
    ``chars_to_send`` (see ``_backfill_dry_run``).

    Ships the embeddings tier only: the returned ``atomize`` block always
    carries ``enabled: false`` naming the settled no-delete-routes
    decision that blocks it permanently, never a placeholder to fill in
    later.
    """
    mode = "all" if reset else "missing"
    kb_home = config.kb_home
    # Guarantees index/kb.db's directory exists even against a vault no
    # ingest route has ever touched yet, exactly like every other entry
    # point that opens it (_rebuild_index, cmd_run). Cheap and idempotent:
    # creates dirs only, no FTS or vector work.
    kb_vault.vault_init(kb_home)
    db_path = index_db_path(kb_home)

    if not kb_embed.embeddings_enabled(config):
        return _backfill_disabled(mode, dry_run)

    notes = _note_texts(kb_home)
    if reset and not dry_run:
        kb_embed.mark_all_stale(db_path)
    # reset means "every note is stale" by definition -- computed directly
    # rather than via stale_notes so a dry run never has to consult (or
    # mutate) stored hashes to know the answer for `all`.
    stale = notes if reset else kb_embed.stale_notes(db_path, notes)
    live_paths = {path for path, _ in notes}

    if dry_run:
        return _backfill_dry_run(mode, db_path, stale, live_paths)
    work = stale[:kb_embed.BACKFILL_BATCH_LIMIT]
    return _backfill_real(config, mode, db_path, work, live_paths, len(stale))


# ── HTTP server ───────────────────────────────────────────────────────


class KbHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the resolved KbServeConfig.

    ``embed_lock`` serializes ``/reindex`` and ``/embed/*``: they are
    the only routes that embed an unbounded-ish set of notes, and two of
    them running at once would embed the same stale notes twice, which is
    duplicate model spend -- the exact cost this workstream exists to
    remove. Every other route (including ``_finish_ingest``'s bounded,
    per-note embed) is left unlocked on purpose.
    """

    def __init__(
        self,
        address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        config: KbServeConfig,
    ) -> None:
        self.config = config
        self.embed_lock = threading.Lock()
        super().__init__(address, handler_cls)


class KbRequestHandler(BaseHTTPRequestHandler):
    """Routes the JSON endpoints onto the module functions above.

    Carries no vault logic of its own: every path, project name and
    frontmatter scalar is validated by kb_vault before it is used, and
    this class only turns the resulting exceptions into status codes.
    """

    server: KbHTTPServer  # type: ignore[assignment]  # narrows the stdlib base

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

    def _reject_browser_origin(self) -> bool:
        """Answer 403 and return True when the request looks like it came
        from a web page rather than the CLI.

        Several checks, because none covers the others: a cross-origin
        request carries an Origin header we never allowlist; a DNS-rebound
        request is same-origin (no Origin header at all) but carries the
        attacker's hostname in Host; an absolute-form request target lets
        a caller route on one authority while Host says another; and two
        Host headers let the value this check reads differ from the value
        anything in front of it reads.

        Kept deliberately identical in effect to bd-svc's own guard --
        the baseline is workbench-wide, so the two services must not
        diverge on which requests they refuse.
        """
        if self.headers.get("Origin"):
            self._send_json(403, {"error": "cross-origin requests are refused"})
            return True
        target = urlparse(self.path)
        if target.scheme or target.netloc:
            self._send_json(
                403, {"error": "request target must be an origin-form path"},
            )
            return True
        host_headers = self.headers.get_all("Host") or []
        if len(host_headers) > 1:
            self._send_json(
                403, {"error": "exactly one Host header is required"},
            )
            return True
        host = self.headers.get("Host", "")
        # urlparse strips the :port and the IPv6 brackets for us.
        hostname = urlparse(f"//{host}").hostname or ""
        if hostname not in ALLOWED_HOST_NAMES:
            self._send_json(403, {"error": f"unexpected Host header {host!r}"})
            return True
        return False

    def _read_json_body(self) -> dict[str, object]:
        # A body this handler cannot frame exactly must never be read as an
        # empty payload: that silently turns "here is my body" into "run
        # the endpoint with its defaults". Chunked bodies and duplicate
        # Content-Length are refused rather than ignored.
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) > 1:
            raise ValueError("duplicate Content-Length")
        length = int(self.headers.get("Content-Length", "0"))
        # A negative length matters as much as an oversized one: rfile
        # .read(-1) drains to EOF, which would ignore the cap entirely.
        if not 0 <= length <= MAX_BODY_BYTES:
            raise ValueError(
                f"Content-Length must be 0..{MAX_BODY_BYTES}, got {length}"
            )
        raw = self.rfile.read(length) if length else b""
        parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    # ── GET ───────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802 stdlib override name
        if self._reject_browser_origin():
            return
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        routes = {
            "/health": self._handle_health,
            "/status": self._handle_status,
            "/project": self._handle_project,
            "/query": self._handle_query,
            "/decision/audit": self._handle_audit,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            return self._send_json(404, {"error": "not found"})
        try:
            handler(params)
        except (KeyError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
        except sqlite3.Error as exc:
            self._send_json(503, {"error": f"database unavailable: {exc}"})

    def _handle_health(self, _params: dict[str, list[str]]) -> None:
        config = self.server.config
        self._send_json(200, {
            "status": "ok",
            "kb_home": str(config.kb_home),
            "indexed_count": count_indexed_notes(config.kb_home),
            "vector_count": kb_embed.count_vectors(index_db_path(config.kb_home)),
            "embeddings_enabled": kb_embed.embeddings_enabled(config),
        })

    def _handle_status(self, _params: dict[str, list[str]]) -> None:
        self._send_json(200, kb_vault.vault_status(self.server.config.kb_home))

    def _handle_project(self, params: dict[str, list[str]]) -> None:
        name = kb_vault.validate_project((params.get("project") or [""])[0])
        path = self.server.config.kb_home / name
        self._send_json(200, {
            "project": name, "path": str(path), "exists": path.is_dir(),
        })

    def _handle_query(self, params: dict[str, list[str]]) -> None:
        query = (params.get("q") or [""])[0]
        if not query.strip():
            return self._send_json(400, {"error": "q is required"})
        results = search(
            self.server.config,
            query,
            (params.get("project") or [None])[0],
            (params.get("type") or [None])[0],
            (params.get("all") or ["0"])[0] == "1",
        )
        self._send_json(200, {"results": results})

    def _handle_audit(self, params: dict[str, list[str]]) -> None:
        topic = (params.get("topic") or [""])[0]
        if not topic.strip():
            return self._send_json(400, {"error": "topic is required"})
        project = (params.get("project") or [None])[0]
        chain = audit_decisions(self.server.config.kb_home, topic, project)
        self._send_json(200, {"chain": chain})

    # ── POST ──────────────────────────────────────────────────────────

    def do_POST(self) -> None:  # noqa: N802 stdlib override name
        if self._reject_browser_origin():
            return
        # Media types are case-insensitive (RFC 9110), so compare folded:
        # "Application/JSON" is the same type and must not be refused.
        content_type = (
            self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        )
        if content_type != JSON_CONTENT_TYPE:
            return self._send_json(415, {
                "error": f"Content-Type must be {JSON_CONTENT_TYPE}, "
                         f"got {content_type or 'none'}",
            })
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
        except (json.JSONDecodeError, ValueError) as exc:
            return self._send_json(400, {"error": f"invalid request body: {exc}"})

        routes = {
            "/vault/init": self._handle_vault_init,
            "/project/init": self._handle_project_init,
            "/put": self._handle_put,
            "/clip": self._handle_clip,
            "/atomize": self._handle_atomize,
            "/reindex": self._handle_reindex,
            "/decision": self._handle_decision,
            "/enrich": self._handle_enrich,
            "/embed/all": self._handle_embed_all,
            "/embed/missing": self._handle_embed_missing,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            return self._send_json(404, {"error": "not found"})
        try:
            handler(payload)
        except (KeyError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
        except sqlite3.Error as exc:
            # sqlite3.OperationalError (e.g. "database is locked") is not
            # an OSError, so it would otherwise fall through every catch
            # here and drop the connection with no status and no body --
            # exactly the failure a /embed retry loop must never see.
            self._send_json(503, {"error": f"database unavailable: {exc}"})
        except (OSError, urllib.error.URLError) as exc:
            self._send_json(502, {"error": f"vault operation failed: {exc}"})

    def _handle_vault_init(self, _payload: dict[str, object]) -> None:
        self._send_json(200, kb_vault.vault_init(self.server.config.kb_home))

    def _handle_project_init(self, payload: dict[str, object]) -> None:
        result = kb_vault.project_init(
            self.server.config.kb_home, payload.get("project"),
        )
        self._send_json(201, result)

    def _handle_put(self, payload: dict[str, object]) -> None:
        config = self.server.config
        self._send_json(201, kb_put(config.kb_home, config, payload))

    def _handle_clip(self, payload: dict[str, object]) -> None:
        config = self.server.config
        self._send_json(
            201, kb_clip_and_atomize(config.kb_home, config, payload),
        )

    def _handle_atomize(self, payload: dict[str, object]) -> None:
        config = self.server.config
        self._send_json(
            201, kb_ingest_and_atomize(config.kb_home, config, payload),
        )

    def _try_acquire_embed_lock(self, retry_command: str) -> bool:
        """Acquire ``embed_lock``; on contention, answer 409 and return
        False.

        The 409 body's ``next`` names the exact command a retrying caller
        already has, so the retry loop this route is built for (see
        modes/kb.md) just re-runs what it already printed instead of
        constructing anything new. True means the caller now owns the
        lock and MUST release it.
        """
        if self.server.embed_lock.acquire(blocking=False):
            return True
        self._send_json(409, {
            "error": "another reindex or embed backfill is already running",
            "next": f"{NEXT_COMMAND_PREFIX} {retry_command}",
        })
        return False

    def _handle_reindex(self, _payload: dict[str, object]) -> None:
        if not self._try_acquire_embed_lock("kb index"):
            return
        try:
            result = rebuild_derived(self.server.config)
        finally:
            self.server.embed_lock.release()
        self._send_json(200, result)

    def _handle_decision(self, payload: dict[str, object]) -> None:
        self._send_json(201, record_decision(self.server.config, payload))

    def _handle_enrich(self, payload: dict[str, object]) -> None:
        config = self.server.config
        result = kb_enrich(config, payload)
        if result.get("enriched"):
            db_path = index_db_path(config.kb_home)
            _rebuild_index(config.kb_home, db_path)
            _embed_notes(config, [Path(str(p)) for p in result["notes"]])
        self._send_json(200, result)

    def _handle_embed(self, payload: dict[str, object], reset: bool) -> None:
        command = "kb embed all" if reset else "kb embed missing"
        if not self._try_acquire_embed_lock(command):
            return
        try:
            dry_run = payload.get("dry_run", False)
            if not isinstance(dry_run, bool):
                raise ValueError("dry_run must be a boolean")
            result = backfill_embeddings(self.server.config, reset, dry_run)
        finally:
            self.server.embed_lock.release()
        self._send_json(502 if "error" in result else 200, result)

    def _handle_embed_all(self, payload: dict[str, object]) -> None:
        self._handle_embed(payload, reset=True)

    def _handle_embed_missing(self, payload: dict[str, object]) -> None:
        self._handle_embed(payload, reset=False)


def serve_forever(config: KbServeConfig, host: str, port: int) -> None:
    """Bind and serve until interrupted."""
    server = KbHTTPServer((host, port), KbRequestHandler, config)
    log.info(
        "kb-svc listening on %s:%s (kb_home=%s)", host, port, config.kb_home,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ── CLI ───────────────────────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> int:
    """Serve in the foreground. The only subcommand: everything else is
    reached over HTTP through the agent-workbench CLI."""
    kb_home = resolve_kb_home(args.kb_home)
    kb_vault.vault_init(kb_home)
    (kb_home / INDEX_DIR).mkdir(parents=True, exist_ok=True)
    serve_forever(build_config(kb_home), args.host, args.port)
    return 0


def cmd_resolve_secret(args: argparse.Namespace) -> int:
    """Print ``KB_LLM_API_KEY=<value>`` for an EnvironmentFile to consume.

    The only line ever written to stdout; the resolved value is never
    logged. Prints the key with an empty value when nothing resolves, and
    callers treat that the same as "no key configured".

    Written for a host-side pre-start hook that resolved the key before
    the container started. Compose has no pre-start hook and resolves the
    key in-process instead (see ``resolve_api_key``), so nothing in this
    repo calls this verb any more. It is kept only as the documented
    escape hatch for a host that wants to resolve the key outside the
    container; ``scripts/n8n-container/n8n-secret.py`` mirrors its shape.
    """
    kb_home = resolve_kb_home(args.kb_home)
    merged = {**load_kb_env(kb_home), **os.environ}
    print(f"KB_LLM_API_KEY={resolve_api_key(merged) or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    secret_cmd = sub.add_parser(
        "resolve-secret",
        help="print the resolved LLM API key for a systemd EnvironmentFile",
    )
    secret_cmd.add_argument("--kb-home", default=None)
    run_cmd = sub.add_parser("run", help="serve the knowledgebase service")
    run_cmd.add_argument(
        "--host", default=os.environ.get("KB_SVC_HOST", "127.0.0.1"),
    )
    run_cmd.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KB_SVC_PORT", DEFAULT_PORT)),
    )
    run_cmd.add_argument("--kb-home", default=None)
    return parser


def main(argv: list[str]) -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    dispatch = {"run": cmd_run, "resolve-secret": cmd_resolve_secret}
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
