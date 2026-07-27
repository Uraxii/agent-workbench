"""Vector half of the derived retrieval layer.

The vault's markdown is the only source of truth. The FTS5 table and the
vectors in this module are BOTH derived artifacts of it: a rebuild reads
the vault and nothing else, which is why the rebuild endpoint is the
recovery path.

Vectors live in a plain table in the same ``index/kb.db`` as the FTS5
index, so one file holds the whole derived layer and one rebuild drops
and repopulates both.

STATUS: the backend seam is wired to an OpenAI-compatible ``/embeddings``
endpoint and is INERT until ``KB_EMBED_MODEL`` is set (plus a resolvable
API key). With no model configured, ``rebuild_vectors`` stores nothing
and ``search_ranking`` returns nothing, so retrieval is keyword-only and
never fails. Nothing else in the ingest path depends on it.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from kb_config import KbServeConfig

__all__ = [
    "VECTOR_TABLE",
    "count_vectors",
    "embed_texts",
    "embeddings_enabled",
    "fuse_rankings",
    "rebuild_vectors",
    "search_ranking",
]

log = logging.getLogger("kb-serve")

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


def embeddings_enabled(config: KbServeConfig) -> bool:
    """True when a model and an API key are both configured."""
    return bool(config.embed_model and config.llm_api_key)


def embed_texts(config: KbServeConfig, texts: Sequence[str]) -> list[list[float]]:
    """Embed ``texts`` via the configured OpenAI-compatible endpoint.

    Raises on any network or parse failure; callers decide how to
    degrade. Batched so one rebuild of a large vault does not post the
    whole corpus in a single request.
    """
    vectors: list[list[float]] = []
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
    return vectors


def _reset_table(connection: sqlite3.Connection) -> None:
    connection.execute(f"DROP TABLE IF EXISTS {VECTOR_TABLE}")
    connection.execute(
        f"CREATE TABLE {VECTOR_TABLE} (path TEXT PRIMARY KEY, vector TEXT)"
    )


def rebuild_vectors(
    config: KbServeConfig, db_path: Path, notes: Sequence[tuple[str, str]],
) -> int:
    """Drop and repopulate the vector table from ``(path, text)`` pairs.

    Returns the number of vectors stored: 0 when no backend is configured
    (the table is still reset, so a disabled service never serves stale
    vectors) and 0 when the backend call fails, which is logged and
    degrades retrieval to keyword-only rather than failing the ingest.
    """
    connection = sqlite3.connect(db_path)
    try:
        with connection:
            _reset_table(connection)
            if not embeddings_enabled(config) or not notes:
                return 0
            try:
                vectors = embed_texts(config, [text for _, text in notes])
            except (OSError, KeyError, IndexError, ValueError) as exc:
                log.warning("embedding backend failed, keyword-only: %s", exc)
                return 0
            rows = [
                (path, json.dumps(vector))
                for (path, _), vector in zip(notes, vectors)
            ]
            connection.executemany(
                f"INSERT OR REPLACE INTO {VECTOR_TABLE} (path, vector) "
                "VALUES (?, ?)",
                rows,
            )
            return len(rows)
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
        query_vector = embed_texts(config, [query])[0]
    except (OSError, KeyError, IndexError, ValueError) as exc:
        log.warning("query embedding failed, keyword-only: %s", exc)
        return []

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
