"""Vector half of the derived retrieval layer.

The vault's markdown is the only source of truth. The FTS5 table and the
vectors in this module are BOTH derived artifacts of it: a rebuild reads
the vault and nothing else, which is why the rebuild endpoint is the
recovery path.

Vectors live in a plain table in the same ``index/kb.db`` as the FTS5
index, so one file holds the whole derived layer.

Each stored row carries a ``content_hash`` (see ``content_fingerprint``)
alongside its vector. That single column is what makes embedding
incremental: ``stale_notes`` compares it against the note's current
fingerprint to find exactly the notes that need re-embedding, instead of
every ingest re-embedding the whole vault (the defect this module
replaces). ``mark_all_stale`` resets every hash to NULL rather than
dropping rows, so a full re-embed stays resumable and never degrades
retrieval to keyword-only mid-run.

STATUS: the backend seam is wired to an OpenAI-compatible ``/embeddings``
endpoint and is INERT until ``KB_EMBED_MODEL`` is set (plus a resolvable
API key). With no model configured, ``sync_vectors`` stores nothing and
``search_ranking`` returns nothing, so retrieval is keyword-only and
never fails. Nothing else in the ingest path depends on it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import urllib.request
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import NamedTuple

from kb_config import KbServeConfig
from kb_llm import fold_call_records

__all__ = [
    "EmbedCounts",
    "REGENERATE_BATCH_LIMIT",
    "VECTOR_TABLE",
    "content_fingerprint",
    "count_vectors",
    "embed_payload_chars",
    "embed_texts",
    "embeddings_enabled",
    "ensure_vector_schema",
    "fuse_rankings",
    "mark_all_stale",
    "prune_vectors",
    "search_ranking",
    "stale_notes",
    "stored_fingerprints",
    "sync_vectors",
]

log = logging.getLogger("kb-svc")

VECTOR_TABLE = "kb_vector"
EMBED_TIMEOUT_SEC = 30.0
EMBED_BATCH_SIZE = 32
# Embedding one whole long note is pointless past the model's window; the
# atomized children carry the detail.
EMBED_CHAR_LIMIT = 6000
# Reciprocal-rank-fusion constant from the original RRF paper. Damps the
# influence of a single list's top rank so neither half dominates.
RRF_K = 60
VECTOR_CANDIDATE_LIMIT = 50
# 6 x EMBED_BATCH_SIZE, i.e. exactly six backend requests per call. Sized to
# finish inside the CLI's 120s REQUEST_TIMEOUT_SEC with room to spare; a
# timeout is not data loss, since every batch commits.
REGENERATE_BATCH_LIMIT = 192

# Failures a backend call or its response parsing can raise; callers that
# want to degrade to keyword-only rather than fail catch exactly this set.
_BACKEND_FAILURES = (OSError, KeyError, IndexError, ValueError)


class EmbedCounts(NamedTuple):
    """What one vector sync actually did."""
    embedded: int
    chars_sent: int
    usage: dict[str, object] | None
    error: str | None


def embeddings_enabled(config: KbServeConfig) -> bool:
    """True when a model and an API key are both configured."""
    return bool(config.embed_model and config.llm_api_key)


def content_fingerprint(text: str) -> str:
    """sha256 hex of the exact text ``_note_texts`` passes to embedding.

    Hashes the FULL note text, frontmatter included. ``/enrich`` rewrites
    the question/summary fields, which ARE part of the embedded payload,
    so a changed fingerprint after enrichment is correct, not spurious.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_vector_schema(connection: sqlite3.Connection) -> None:
    """Create ``kb_vector``, or ADD COLUMN onto a legacy 2-column table.

    Idempotent; safe to call on every connect. A legacy table (just
    ``path, vector``) keeps every row -- this only adds the missing
    ``content_hash`` column, leaving existing hashes NULL (stale by the
    same rule ``stale_notes`` applies to everything else). NEVER drops or
    recreates the table: that would discard live vectors and force a
    whole-vault re-embed, which is the exact defect this module removes.
    """
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {VECTOR_TABLE} "
        "(path TEXT PRIMARY KEY, vector TEXT, content_hash TEXT)"
    )
    columns = {row[1] for row in connection.execute(
        f"PRAGMA table_info({VECTOR_TABLE})"
    )}
    if "content_hash" not in columns:
        connection.execute(
            f"ALTER TABLE {VECTOR_TABLE} ADD COLUMN content_hash TEXT"
        )
    connection.commit()


def embed_payload_chars(texts: Sequence[str]) -> int:
    """Exact characters the backend would receive for ``texts``.

    Applies ``EMBED_CHAR_LIMIT`` the same way ``embed_texts`` does, so a
    dry-run figure can never drift from what a real call would send.
    """
    return sum(len(text[:EMBED_CHAR_LIMIT]) for text in texts)


def embed_texts(
    config: KbServeConfig, texts: Sequence[str],
) -> tuple[list[list[float]], list[dict[str, object]]]:
    """Embed ``texts`` via the configured OpenAI-compatible endpoint.

    Returns ``(vectors, call_records)``: one call_record per backend
    request, in the shape ``kb_llm.fold_call_records`` consumes. The
    embeddings API returns no generation id and no completion tokens, so
    ``id`` reads ``""`` and ``completion_tokens`` reads ``0``; every usage
    field is read with ``.get()`` defaults so a backend that omits
    ``usage`` degrades to zeros rather than raising.

    Raises on any network or parse failure; callers decide how to
    degrade. Batched so one call does not post the whole corpus in a
    single request.
    """
    vectors: list[list[float]] = []
    call_records: list[dict[str, object]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = [text[:EMBED_CHAR_LIMIT] for text in texts[start:start + EMBED_BATCH_SIZE]]
        payload = json.dumps({"model": config.embed_model, "input": batch})
        request = urllib.request.Request(
            f"{config.llm_base_url}/embeddings",
            data=payload.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {config.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=EMBED_TIMEOUT_SEC) as response:
            data = json.loads(response.read())
        vectors.extend([item["embedding"] for item in data["data"]])
        usage = data.get("usage", {})
        call_records.append({
            "id": data.get("id", ""),
            "model": data.get("model", ""),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        })
    return vectors, call_records


def stored_fingerprints(db_path: Path) -> dict[str, str | None]:
    """``{path: content_hash}`` for every stored vector, ``{}`` if no table."""
    if not db_path.exists():
        return {}
    connection = sqlite3.connect(db_path)
    try:
        ensure_vector_schema(connection)
        rows = connection.execute(
            f"SELECT path, content_hash FROM {VECTOR_TABLE}"
        ).fetchall()
        return dict(rows)
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def stale_notes(
    db_path: Path, notes: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Subset of ``notes`` needing embedding, in input order.

    Stale when: no stored row, OR the stored hash is NULL (a legacy row,
    or a ``mark_all_stale`` reset), OR the stored hash differs from the
    note's current fingerprint. Pure read, zero network -- measured at
    0.044s for the whole 2380-note vault, so no cache, no watcher, no job
    table is needed.
    """
    stored = stored_fingerprints(db_path)
    return [
        (path, text) for path, text in notes
        if stored.get(path) != content_fingerprint(text)
    ]


def mark_all_stale(db_path: Path) -> int:
    """``UPDATE kb_vector SET content_hash = NULL``; rows marked, 0 if none.

    Deliberately NOT a DELETE: vectors stay in place and keep serving
    ``search_ranking`` while the backfill runs, so an interrupted or
    in-flight ``full`` regenerate never degrades retrieval to
    keyword-only. Do not reintroduce a DROP/DELETE here.
    """
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        ensure_vector_schema(connection)
        cursor = connection.execute(f"UPDATE {VECTOR_TABLE} SET content_hash = NULL")
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def sync_vectors(
    config: KbServeConfig, db_path: Path, notes: Sequence[tuple[str, str]],
) -> EmbedCounts:
    """Embed and upsert exactly ``notes``; touch no other stored vector.

    Preconditions: ``notes`` is already the caller's work set (callers
    filter with ``stale_notes``) and is already bounded -- this function
    does not cap it. Postconditions: every path in ``notes`` ends with a
    vector AND a matching content_hash; rows for paths NOT in ``notes``
    are untouched.

    Commits once per ``EMBED_BATCH_SIZE``-sized batch, so an interrupted
    or failing run keeps every batch that already committed instead of
    losing the whole call. Returns ``EmbedCounts(0, 0, None, None)`` when
    embeddings are disabled or ``notes`` is empty. On backend failure,
    returns the counts committed so far with ``error`` set.
    """
    if not embeddings_enabled(config) or not notes:
        return EmbedCounts(0, 0, None, None)

    connection = sqlite3.connect(db_path)
    try:
        ensure_vector_schema(connection)
        embedded = 0
        chars_sent = 0
        call_records: list[dict[str, object]] = []
        error: str | None = None
        for start in range(0, len(notes), EMBED_BATCH_SIZE):
            batch = notes[start:start + EMBED_BATCH_SIZE]
            texts = [text for _, text in batch]
            try:
                vectors, batch_records = embed_texts(config, texts)
            except _BACKEND_FAILURES as exc:
                log.warning("embedding backend failed, keyword-only: %s", exc)
                error = str(exc)
                break
            call_records.extend(batch_records)
            rows = [
                (path, json.dumps(vector), content_fingerprint(text))
                for (path, text), vector in zip(batch, vectors)
            ]
            connection.executemany(
                f"INSERT OR REPLACE INTO {VECTOR_TABLE} "
                "(path, vector, content_hash) VALUES (?, ?, ?)",
                rows,
            )
            connection.commit()
            embedded += len(rows)
            chars_sent += embed_payload_chars(texts)
        usage = fold_call_records(call_records) if call_records else None
        return EmbedCounts(embedded, chars_sent, usage, error)
    finally:
        connection.close()


def prune_vectors(db_path: Path, live_paths: Collection[str]) -> int:
    """Delete vector rows whose note no longer exists.

    Callers MUST pass the full live vault path set, never a batch slice
    -- a partial set here would delete vectors for notes that still
    exist. Returns the number of rows deleted, 0 if there is no table.
    """
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        ensure_vector_schema(connection)
        stored_paths = {
            row[0] for row in connection.execute(f"SELECT path FROM {VECTOR_TABLE}")
        }
        stale_paths = stored_paths - set(live_paths)
        if not stale_paths:
            return 0
        connection.executemany(
            f"DELETE FROM {VECTOR_TABLE} WHERE path = ?",
            [(path,) for path in stale_paths],
        )
        connection.commit()
        return len(stale_paths)
    finally:
        connection.close()


def count_vectors(db_path: Path) -> int:
    """Rows in the vector table, or 0 when it has never been built."""
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            f"SELECT COUNT(*) FROM {VECTOR_TABLE}"
        ).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def search_ranking(
    config: KbServeConfig, db_path: Path, query: str,
) -> list[str]:
    """Note paths ranked by vector similarity to ``query``, best first.

    Returns ``[]`` when embeddings are disabled, the table is empty, or
    the backend call fails, so the caller falls back to keyword-only
    retrieval without special-casing anything.

    # ponytail: brute-force cosine over every stored vector in Python.
    # A personal vault is thousands of notes, not millions; swap in
    # sqlite-vec if the scan ever shows up in a profile.
    """
    if not embeddings_enabled(config) or not count_vectors(db_path):
        return []
    try:
        vectors, _ = embed_texts(config, [query])
    except _BACKEND_FAILURES as exc:
        log.warning("query embedding failed, keyword-only: %s", exc)
        return []
    query_vector = vectors[0]

    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            f"SELECT path, vector FROM {VECTOR_TABLE}"
        ).fetchall()
    finally:
        connection.close()
    scored = [
        (path, _cosine(query_vector, json.loads(vector)))
        for path, vector in rows
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [path for path, _ in scored[:VECTOR_CANDIDATE_LIMIT]]


def fuse_rankings(
    keyword_results: list[dict[str, object]], vector_paths: Sequence[str],
) -> list[dict[str, object]]:
    """Blend keyword and vector rankings with reciprocal rank fusion.

    Only notes the keyword search already returned can be reordered: the
    vector list contributes ranking signal, not extra rows, so a caller
    never sees a result the FTS5 filters (project, type, superseded)
    would have excluded. Returns ``keyword_results`` unchanged when the
    vector list is empty.
    """
    if not vector_paths:
        return keyword_results
    vector_rank = {path: index for index, path in enumerate(vector_paths)}
    fused = []
    for index, result in enumerate(keyword_results):
        score = 1.0 / (RRF_K + index + 1)
        position = vector_rank.get(str(result["path"]))
        if position is not None:
            score += 1.0 / (RRF_K + position + 1)
        fused.append({**result, "score": score})
    fused.sort(key=lambda item: item["score"], reverse=True)
    return fused
