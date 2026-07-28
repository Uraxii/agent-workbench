"""Tests for scripts/kb-index.py -- frontmatter parsing and the FTS5
index build over the personal knowledgebase vault.

Covers the skeptic-gate Bug 1 fix: parse_frontmatter used to bracket-parse
ANY value starting with "[" as a tag list, not just the `tags` field, so a
decision note whose title happens to start with "[" (e.g. "[H3] container
kb-home override") got its title parsed into a list, which then crashed
the sqlite3 insert in build_index and left kb.db dropped-and-empty. Also
covers the defense-in-depth fix: one malformed note must be skipped with
a warning, never abort the whole rebuild.

Mirrors tests/test_kb_clip.py's load-by-path style; everything runs
against tmp_path vaults, never the real ~/.knowledgebase.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "kb-index.py"


def _load_kb_index():
    spec = importlib.util.spec_from_file_location("kb_index_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kb_index = _load_kb_index()

_BRACKET_TITLE_NOTE = (
    "---\n"
    "title: [H3] container kb-home override\n"
    "topic: some-topic\n"
    "date: 2026-07-27\n"
    "status: active\n"
    "supersedes: \n"
    "tags: [a, b]\n"
    "---\n\n"
    "Body.\n"
)


# ── parse_frontmatter: list-parsing gated on the tags KEY, not the value ─


def test_bracket_leading_non_tags_value_stays_a_plain_string() -> None:
    fields, _ = kb_index.parse_frontmatter(_BRACKET_TITLE_NOTE)
    assert fields["title"] == "[H3] container kb-home override"
    assert isinstance(fields["title"], str)


def test_quoted_tags_still_parse_as_before() -> None:
    """Regression guard for kb-serve's existing notes: render_note's
    quoted tag-list schema (`tags: ["alpha", "beta"]`) must keep parsing
    the same way after gating on the key instead of the leading bracket."""
    text = (
        '---\n'
        'type: "note"\n'
        'title: "Some Note"\n'
        'tags: ["alpha", "beta"]\n'
        '---\n\n'
        'Body.\n'
    )
    fields, _ = kb_index.parse_frontmatter(text)
    assert fields["tags"] == ["alpha", "beta"]


def test_bare_tags_list_parses_for_decision_notes() -> None:
    text = (
        "---\n"
        "title: A decision\n"
        "topic: some-topic\n"
        "tags: [a, b, c]\n"
        "---\n\n"
        "Body.\n"
    )
    fields, _ = kb_index.parse_frontmatter(text)
    assert fields["tags"] == ["a", "b", "c"]


def test_load_note_on_bracket_leading_title_does_not_crash_or_produce_a_list(
    tmp_path: Path,
) -> None:
    """Reproduces the reviewer's exact repro shape."""
    project_dir = tmp_path / "proj" / "decisions"
    project_dir.mkdir(parents=True)
    note_path = project_dir / "note__2026-07-27.md"
    note_path.write_text(_BRACKET_TITLE_NOTE, encoding="utf-8")

    note = kb_index.load_note(note_path, tmp_path)

    assert note.title == "[H3] container kb-home override"
    assert isinstance(note.title, str)


# ── build_index: one malformed note must not wipe the whole rebuild ──────


def test_build_index_skips_one_unreadable_note_and_keeps_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    decisions_dir = tmp_path / "proj" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "good.md").write_text(
        "---\ntitle: Fine\ntopic: fine\ndate: 2026-07-27\nstatus: active\n"
        "supersedes: \ntags: [x]\n---\n\nFine body.\n",
        encoding="utf-8",
    )
    with (decisions_dir / "broken.md").open("wb") as handle:
        handle.write(b"---\ntitle: broken\n---\n\nBad byte: \xff\n")

    db_path = tmp_path / "index" / "kb.db"
    indexed = kb_index.build_index(tmp_path, db_path)

    assert indexed == 1
    assert "broken.md" in capsys.readouterr().err

    con = kb_index.sqlite3.connect(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM kb").fetchone()[0] == 1
    finally:
        con.close()


def test_build_index_full_rebuild_indexes_every_good_note(tmp_path: Path) -> None:
    decisions_dir = tmp_path / "proj" / "decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "one.md").write_text(_BRACKET_TITLE_NOTE, encoding="utf-8")
    (decisions_dir / "two__2026-07-27.md").write_text(
        "---\ntitle: Second\ntopic: other\ndate: 2026-07-27\nstatus: active\n"
        "supersedes: \ntags: [y]\n---\n\nSecond body.\n",
        encoding="utf-8",
    )

    indexed = kb_index.build_index(tmp_path, tmp_path / "index" / "kb.db")

    assert indexed == 2


def test_find_markdown_files_skips_anything_resolving_outside_the_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A symlinked project dir (or note) would otherwise pull outside
    files into the index and into the set of notes /enrich rewrites."""
    vault = tmp_path / "vault"
    (vault / "proj" / "notes").mkdir(parents=True)
    (vault / "proj" / "notes" / "real.md").write_text("real", encoding="utf-8")

    outside = tmp_path / "outside"
    (outside / "notes").mkdir(parents=True)
    (outside / "notes" / "secret.md").write_text("secret", encoding="utf-8")
    (vault / "escaped").symlink_to(outside)
    (vault / "proj" / "notes" / "link.md").symlink_to(outside / "notes" / "secret.md")

    found = kb_index.find_markdown_files(vault)

    assert found == [vault / "proj" / "notes" / "real.md"]
    warning = capsys.readouterr().err
    assert "escaped" in warning
    assert "link.md" in warning
