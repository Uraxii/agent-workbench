"""Tests for scripts/kb_embed.py -- the vector half of the derived layer.

The embedding backend is inert until KB_EMBED_MODEL and an API key are
both configured, so the properties worth pinning are: disabled means zero
network calls and zero stored vectors; a rebuild is a full replace, never
an append; and the fusion step reorders the keyword hits without ever
inventing a row the keyword filters excluded.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import kb_embed  # noqa: E402
from kb_config import KbServeConfig  # noqa: E402


def _config(tmp_path: Path, *, embed_model: str | None = None) -> KbServeConfig:
    return KbServeConfig(
        kb_home=tmp_path,
        enrich_enabled=False,
        llm_base_url="https://example.invalid/v1",
        llm_model="fake/model",
        llm_api_key="fake-key" if embed_model else None,
        embed_model=embed_model,
    )


# ── disabled by default ───────────────────────────────────────────────


def test_embeddings_disabled_without_a_model(tmp_path: Path) -> None:
    assert kb_embed.embeddings_enabled(_config(tmp_path)) is False


def test_rebuild_with_no_backend_stores_nothing_and_makes_no_calls(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "kb.db"
    with patch.object(kb_embed, "embed_texts") as mock_embed:
        stored = kb_embed.rebuild_vectors(
            _config(tmp_path), db_path, [("a.md", "text")],
        )
    mock_embed.assert_not_called()
    assert stored == 0
    assert kb_embed.count_vectors(db_path) == 0


def test_search_ranking_with_no_backend_returns_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "kb.db"
    kb_embed.rebuild_vectors(_config(tmp_path), db_path, [])
    with patch.object(kb_embed, "embed_texts") as mock_embed:
        assert kb_embed.search_ranking(_config(tmp_path), db_path, "q") == []
    mock_embed.assert_not_called()


# ── rebuild is a full replace ─────────────────────────────────────────


def test_rebuild_replaces_previous_vectors_rather_than_appending(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    with patch.object(kb_embed, "embed_texts", side_effect=lambda _c, texts: [[1.0, 0.0]] * len(texts)):
        kb_embed.rebuild_vectors(config, db_path, [("a.md", "a"), ("b.md", "b")])
        assert kb_embed.count_vectors(db_path) == 2
        kb_embed.rebuild_vectors(config, db_path, [("a.md", "a")])
    assert kb_embed.count_vectors(db_path) == 1


def test_a_failing_backend_degrades_to_keyword_only(tmp_path: Path) -> None:
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    with patch.object(kb_embed, "embed_texts", side_effect=OSError("no route")):
        stored = kb_embed.rebuild_vectors(config, db_path, [("a.md", "a")])
    assert stored == 0
    assert kb_embed.count_vectors(db_path) == 0


def test_search_ranking_orders_by_cosine_similarity(tmp_path: Path) -> None:
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    vectors = {"far.md": [0.0, 1.0], "near.md": [1.0, 0.0]}
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: [vectors[t] for t in texts],
    ):
        kb_embed.rebuild_vectors(
            config, db_path, [(path, path) for path in vectors],
        )
    with patch.object(kb_embed, "embed_texts", return_value=[[1.0, 0.0]]):
        ranking = kb_embed.search_ranking(config, db_path, "query")
    assert ranking == ["near.md", "far.md"]


# ── fusion ────────────────────────────────────────────────────────────


def test_fuse_without_vectors_leaves_keyword_order_untouched() -> None:
    keyword = [{"path": "a.md"}, {"path": "b.md"}]
    assert kb_embed.fuse_rankings(keyword, []) == keyword


def test_fuse_promotes_a_note_both_halves_agree_on() -> None:
    keyword = [{"path": "a.md"}, {"path": "b.md"}, {"path": "c.md"}]
    fused = kb_embed.fuse_rankings(keyword, ["c.md", "b.md"])
    assert [row["path"] for row in fused] == ["c.md", "b.md", "a.md"]


def test_fuse_never_adds_a_note_the_keyword_filters_excluded() -> None:
    keyword = [{"path": "a.md"}]
    fused = kb_embed.fuse_rankings(keyword, ["secret.md", "a.md"])
    assert [row["path"] for row in fused] == ["a.md"]
