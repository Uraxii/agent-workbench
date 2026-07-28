"""Tests for scripts/kb_embed.py -- the vector half of the derived layer.

The embedding backend is inert until KB_EMBED_MODEL and an API key are
both configured, so the properties worth pinning are: disabled means zero
network calls and zero stored vectors; `sync_vectors` embeds and upserts
exactly the notes it is given and never touches any other stored row --
that scoping is the whole incremental fix (see
`test_ingest_embeds_only_the_new_note_and_its_children` in
test_kb_svc.py for the end-to-end regression tripwire); `mark_all_stale`
clears hashes without ever deleting a vector row, so an in-flight `full`
regenerate never degrades retrieval to keyword-only; the legacy
two-column table gains a hash column without losing a single stored
vector; and the fusion step reorders the keyword hits without ever
inventing a row the keyword filters excluded.
"""

from __future__ import annotations

import json
import sqlite3
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


def _read_vector_rows(db_path: Path) -> dict[str, str]:
    """``{path: vector_json}`` straight off disk, for byte-identity checks
    that must not go through kb_embed's own read path."""
    connection = sqlite3.connect(db_path)
    try:
        return dict(connection.execute("SELECT path, vector FROM kb_vector"))
    finally:
        connection.close()


# ── disabled by default ───────────────────────────────────────────────


def test_embeddings_disabled_without_a_model(tmp_path: Path) -> None:
    assert kb_embed.embeddings_enabled(_config(tmp_path)) is False


def test_sync_with_no_backend_stores_nothing_and_makes_no_calls(
    tmp_path: Path,
) -> None:
    """If a disabled config ever reaches the backend, an unconfigured kb
    would start leaking outbound requests instead of degrading to
    keyword-only. Replaces
    test_rebuild_with_no_backend_stores_nothing_and_makes_no_calls
    (rebuild_vectors is deleted); the assertions are unchanged."""
    db_path = tmp_path / "kb.db"
    with patch.object(kb_embed, "embed_texts") as mock_embed:
        counts = kb_embed.sync_vectors(
            _config(tmp_path), db_path, [("a.md", "text")],
        )
    mock_embed.assert_not_called()
    assert counts.embedded == 0
    assert kb_embed.count_vectors(db_path) == 0


def test_search_ranking_with_no_backend_returns_nothing(tmp_path: Path) -> None:
    """Ported from the rebuild_vectors era to sync_vectors as setup; the
    assertion (disabled search makes zero calls and returns nothing) is
    unchanged."""
    db_path = tmp_path / "kb.db"
    kb_embed.sync_vectors(_config(tmp_path), db_path, [])
    with patch.object(kb_embed, "embed_texts") as mock_embed:
        assert kb_embed.search_ranking(_config(tmp_path), db_path, "q") == []
    mock_embed.assert_not_called()


# ── sync_vectors: scoped writes, not a full replace ────────────────────


def test_sync_never_deletes_rows_it_was_not_given(tmp_path: Path) -> None:
    """Replaces test_rebuild_replaces_previous_vectors_rather_than_appending.

    That test pinned rebuild_vectors's full-replace-every-call behaviour,
    which is exactly the defect this module exists to remove: a
    full-replace rebuild is what forced every ingest to re-embed the
    whole vault. sync_vectors's contract is the opposite -- a row for a
    path NOT in the given notes is left alone -- so re-asserting "replace"
    here would pin the bug back in. This is a deliberate replacement of
    the old test, not a weakened one: it still proves count_vectors stays
    correct, just for the opposite (correct) behaviour.
    """
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        kb_embed.sync_vectors(config, db_path, [("a.md", "a"), ("b.md", "b")])
        assert kb_embed.count_vectors(db_path) == 2
        kb_embed.sync_vectors(config, db_path, [("a.md", "a")])
    # b.md was not in the second call's notes: it must still be there.
    assert kb_embed.count_vectors(db_path) == 2


def test_sync_embeds_only_the_notes_it_was_given(tmp_path: Path) -> None:
    """If a caller ever re-embeds one note and the OTHER 49 rows are
    touched, ingest is back to O(vault size) instead of O(1)."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [(f"n{i}.md", f"text {i}") for i in range(50)]
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        kb_embed.sync_vectors(config, db_path, notes)
    rows_before = _read_vector_rows(db_path)
    assert len(rows_before) == 50

    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[9.0, 9.0]] * len(texts), []),
    ) as mock_embed:
        kb_embed.sync_vectors(config, db_path, [notes[0]])

    mock_embed.assert_called_once()
    _, texts = mock_embed.call_args.args
    assert texts == ["text 0"]
    rows_after = _read_vector_rows(db_path)
    other_paths = [path for path, _ in notes[1:]]
    assert {p: rows_after[p] for p in other_paths} == {
        p: rows_before[p] for p in other_paths
    }


def test_sync_skips_notes_whose_content_is_unchanged(tmp_path: Path) -> None:
    """stale_notes -> sync_vectors is the normal caller pattern (see
    rebuild_derived / regenerate): a second pass over unchanged notes
    must make zero backend calls, or a `full` regenerate could never
    converge."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [(f"n{i}.md", f"text {i}") for i in range(10)]
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        first = kb_embed.sync_vectors(
            config, db_path, kb_embed.stale_notes(db_path, notes),
        )
    assert first.embedded == 10

    with patch.object(kb_embed, "embed_texts") as mock_embed:
        stale = kb_embed.stale_notes(db_path, notes)
        second = kb_embed.sync_vectors(config, db_path, stale)
    mock_embed.assert_not_called()
    assert second.embedded == 0


def test_sync_reembeds_a_note_whose_text_changed(tmp_path: Path) -> None:
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [(f"n{i}.md", f"text {i}") for i in range(10)]
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        kb_embed.sync_vectors(
            config, db_path, kb_embed.stale_notes(db_path, notes),
        )

    changed_notes = list(notes)
    changed_notes[3] = ("n3.md", "text 3 CHANGED")
    stale = kb_embed.stale_notes(db_path, changed_notes)
    assert stale == [("n3.md", "text 3 CHANGED")]

    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ) as mock_embed:
        kb_embed.sync_vectors(config, db_path, stale)

    mock_embed.assert_called_once()
    _, texts = mock_embed.call_args.args
    assert texts == ["text 3 CHANGED"]


def test_sync_commits_each_batch_so_an_interruption_keeps_progress(
    tmp_path: Path,
) -> None:
    """A run that dies partway through must not lose already-committed
    batches: sync_vectors commits per EMBED_BATCH_SIZE batch specifically
    so a timeout or crash keeps whatever finished."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [(f"n{i}.md", f"text {i}") for i in range(kb_embed.EMBED_BATCH_SIZE + 8)]

    call_count = 0

    def flaky_embed(_config: KbServeConfig, texts: list[str]):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("backend down")
        return [[1.0, 0.0]] * len(texts), []

    with patch.object(kb_embed, "embed_texts", side_effect=flaky_embed):
        counts = kb_embed.sync_vectors(config, db_path, notes)

    assert counts.error is not None
    assert counts.embedded == kb_embed.EMBED_BATCH_SIZE
    stored = kb_embed.stored_fingerprints(db_path)
    first_batch_paths = {path for path, _ in notes[:kb_embed.EMBED_BATCH_SIZE]}
    assert set(stored) == first_batch_paths
    assert all(value is not None for value in stored.values())


def test_a_failing_backend_degrades_to_keyword_only(tmp_path: Path) -> None:
    """Ported from the rebuild_vectors era to sync_vectors; the assertions
    (nothing embedded, nothing stored) are unchanged."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    with patch.object(kb_embed, "embed_texts", side_effect=OSError("no route")):
        counts = kb_embed.sync_vectors(config, db_path, [("a.md", "a")])
    assert counts.embedded == 0
    assert kb_embed.count_vectors(db_path) == 0


# ── prune / mark_all_stale ───────────────────────────────────────────


def test_prune_removes_only_vectors_whose_note_is_gone(tmp_path: Path) -> None:
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [("keep.md", "keep text"), ("gone.md", "gone text")]
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        kb_embed.sync_vectors(config, db_path, notes)

    pruned = kb_embed.prune_vectors(db_path, {"keep.md"})

    assert pruned == 1
    assert set(kb_embed.stored_fingerprints(db_path)) == {"keep.md"}


def test_mark_all_stale_keeps_the_vectors_and_only_clears_the_hashes(
    tmp_path: Path,
) -> None:
    """This is the guarantee that stops anyone reintroducing a DELETE:
    marking every note stale must never drop a vector row, or an
    interrupted `full` regenerate would degrade retrieval to
    keyword-only mid-run."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    notes = [("a.md", "text a"), ("b.md", "text b")]
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([[1.0, 0.0]] * len(texts), []),
    ):
        kb_embed.sync_vectors(config, db_path, notes)
    vectors_before = _read_vector_rows(db_path)

    marked = kb_embed.mark_all_stale(db_path)

    assert marked == 2
    assert _read_vector_rows(db_path) == vectors_before  # byte-identical
    hashes = kb_embed.stored_fingerprints(db_path)
    assert set(hashes) == {"a.md", "b.md"}
    assert all(value is None for value in hashes.values())


# ── legacy 2-column table migration ──────────────────────────────────


def test_legacy_two_column_table_gains_content_hash_without_losing_vectors(
    tmp_path: Path,
) -> None:
    """Build the exact live DDL (VERIFIED against the running vault: 2380
    rows on `CREATE TABLE kb_vector (path TEXT PRIMARY KEY, vector
    TEXT)`). The migration must be additive only -- dropping and
    recreating the table would discard those vectors and force a
    whole-vault re-embed, which is the exact defect this module removes.
    """
    db_path = tmp_path / "kb.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE kb_vector (path TEXT PRIMARY KEY, vector TEXT)")
    connection.execute(
        "INSERT INTO kb_vector (path, vector) VALUES (?, ?)",
        ("legacy.md", json.dumps([1.0, 2.0])),
    )
    connection.commit()
    connection.close()

    connection = sqlite3.connect(db_path)
    try:
        kb_embed.ensure_vector_schema(connection)
        columns = [row[1] for row in connection.execute("PRAGMA table_info(kb_vector)")]
        rows = connection.execute(
            "SELECT path, vector, content_hash FROM kb_vector"
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 1
    assert set(columns) == {"path", "vector", "content_hash"}
    assert rows == [("legacy.md", json.dumps([1.0, 2.0]), None)]


def test_legacy_rows_are_stale_until_reembedded(tmp_path: Path) -> None:
    db_path = tmp_path / "kb.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE kb_vector (path TEXT PRIMARY KEY, vector TEXT)")
    connection.execute(
        "INSERT INTO kb_vector (path, vector) VALUES (?, ?)",
        ("legacy.md", json.dumps([1.0, 2.0])),
    )
    connection.commit()
    connection.close()

    notes = [("legacy.md", "legacy text"), ("new.md", "new text")]
    stale = kb_embed.stale_notes(db_path, notes)

    assert stale == notes


# ── embed_payload_chars / embed_texts ────────────────────────────────


def test_embed_payload_chars_matches_what_embed_texts_actually_sends(
    tmp_path: Path,
) -> None:
    """Keeps the dry-run `chars_to_send` figure honest: if embed_texts
    ever truncates differently than embed_payload_chars predicts, a dry
    run would report a number the real call does not match."""
    config = _config(tmp_path, embed_model="fake/embed")
    long_text = "x" * (kb_embed.EMBED_CHAR_LIMIT + 500)
    captured_batches: list[list[str]] = []

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=None):  # noqa: ANN001 stdlib shape
        payload = json.loads(request.data)
        captured_batches.append(payload["input"])
        body = json.dumps({
            "data": [{"embedding": [0.0, 0.0]} for _ in payload["input"]],
        }).encode("utf-8")
        return _FakeResponse(body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        kb_embed.embed_texts(config, [long_text])

    sent_texts = [text for batch in captured_batches for text in batch]
    assert kb_embed.embed_payload_chars([long_text]) == sum(
        len(text) for text in sent_texts
    )


def test_embed_texts_returns_a_call_record_per_backend_call(tmp_path: Path) -> None:
    """The embeddings API returns no generation id, so id must read '',
    never crash and never silently keep a stale id from elsewhere; usage
    fields must land unchanged in the record."""
    config = _config(tmp_path, embed_model="fake/embed")

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=None):  # noqa: ANN001 stdlib shape
        payload = json.loads(request.data)
        body = json.dumps({
            "model": "text-embedding-3-small",
            "data": [{"embedding": [0.1, 0.2]} for _ in payload["input"]],
            "usage": {"prompt_tokens": 42, "total_tokens": 42},
        }).encode("utf-8")
        return _FakeResponse(body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        vectors, call_records = kb_embed.embed_texts(config, ["one text"])

    assert vectors == [[0.1, 0.2]]
    assert len(call_records) == 1
    record = call_records[0]
    assert record["id"] == ""
    assert record["model"] == "text-embedding-3-small"
    assert record["prompt_tokens"] == 42
    assert record["completion_tokens"] == 0
    assert record["total_tokens"] == 42


def test_embed_texts_raises_when_backend_returns_fewer_vectors_than_inputs(
    tmp_path: Path,
) -> None:
    """A short response must RAISE, not silently truncate: `zip()` in
    `sync_vectors` would otherwise under-count `embedded`, so `remaining`
    never reaches 0 and an agent following `next` loops forever -- the
    exact wait-loop failure this design exists to make unreachable."""
    config = _config(tmp_path, embed_model="fake/embed")

    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def __enter__(self) -> "_FakeResponse":
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def fake_urlopen(request, timeout=None):  # noqa: ANN001 stdlib shape
        # Two texts sent this batch, only one embedding comes back.
        body = json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode("utf-8")
        return _FakeResponse(body)

    with (
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        pytest.raises(ValueError, match="1 vectors for 2 inputs"),
    ):
        kb_embed.embed_texts(config, ["one", "two"])


# ── search ranking ────────────────────────────────────────────────────


def test_search_ranking_orders_by_cosine_similarity(tmp_path: Path) -> None:
    """Ported from the rebuild_vectors era to sync_vectors as setup; the
    assertion (near.md ranks ahead of far.md) is unchanged."""
    config = _config(tmp_path, embed_model="fake/embed")
    db_path = tmp_path / "kb.db"
    vectors = {"far.md": [0.0, 1.0], "near.md": [1.0, 0.0]}
    with patch.object(
        kb_embed, "embed_texts",
        side_effect=lambda _c, texts: ([vectors[t] for t in texts], []),
    ):
        kb_embed.sync_vectors(
            config, db_path, [(path, path) for path in vectors],
        )
    with patch.object(kb_embed, "embed_texts", return_value=([[1.0, 0.0]], [])):
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
