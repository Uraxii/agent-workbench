"""Tests for scripts/kb_vault.py -- the service's trust boundary.

kb-serve binds loopback with no authentication, so every value that
reaches the filesystem has to be validated before it gets there. These
tests are the check on that: a project name that is not a plain directory
name, a note path that resolves outside the vault, and a frontmatter
scalar carrying a newline all have to be refused, and the refusal has to
happen before anything is created on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import kb_vault  # noqa: E402


# ── project names ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "..",
        "../escape",
        "a/../../b",
        "/etc",
        "proj/sub",
        ".obsidian",
        "index",
        ".hidden",
        "",
        "with space",
        "with\nnewline",
        "nul\x00byte",
        "x" * 65,
    ],
)
def test_validate_project_rejects_anything_that_is_not_a_plain_name(
    name: str,
) -> None:
    with pytest.raises(ValueError):
        kb_vault.validate_project(name)


def test_validate_project_rejects_a_non_string() -> None:
    with pytest.raises(ValueError):
        kb_vault.validate_project(None)


@pytest.mark.parametrize(
    "name", ["inbox", "agent-workbench", "proj_1", "v1.2", "A9"],
)
def test_validate_project_accepts_a_plain_name(name: str) -> None:
    assert kb_vault.validate_project(name) == name


def test_project_init_refuses_to_create_a_traversing_project(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        kb_vault.project_init(tmp_path / "vault", "../escape")
    assert not (tmp_path / "escape").exists()


# ── note paths ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    ["../outside.md", "../../etc/passwd", "/etc/passwd", "proj/note.txt", ""],
)
def test_resolve_vault_path_rejects_escapes_and_non_markdown(
    tmp_path: Path, raw: str,
) -> None:
    with pytest.raises(ValueError):
        kb_vault.resolve_vault_path(tmp_path, raw)


def test_resolve_vault_path_rejects_a_symlink_pointing_out_of_the_vault(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "proj").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (vault / "proj" / "link.md").symlink_to(outside)
    with pytest.raises(ValueError):
        kb_vault.resolve_vault_path(vault, "proj/link.md")


def test_resolve_vault_path_accepts_a_note_inside_the_vault(
    tmp_path: Path,
) -> None:
    resolved = kb_vault.resolve_vault_path(tmp_path, "proj/notes/a.md")
    assert resolved == (tmp_path / "proj" / "notes" / "a.md").resolve()


# ── frontmatter scalars ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "value", ["forged\nstatus: active", "carriage\rreturn", "nul\x00", "x" * 201],
)
def test_validate_scalar_rejects_values_that_could_forge_frontmatter(
    value: str,
) -> None:
    with pytest.raises(ValueError):
        kb_vault.validate_scalar(value, "title")


def test_validate_scalar_requires_a_value_when_asked() -> None:
    with pytest.raises(ValueError):
        kb_vault.validate_scalar("   ", "title", required=True)


def test_write_note_refuses_a_newline_title_before_writing_anything(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        kb_vault.write_note(
            tmp_path, "proj1", "note", "bad\ntitle", "", "body",
        )
    assert list(tmp_path.rglob("*.md")) == []


def test_write_note_rejects_an_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        kb_vault.write_note(tmp_path, "proj1", "invoice", "T", "", "body")


def test_write_note_writes_into_the_type_directory(tmp_path: Path) -> None:
    note_path = kb_vault.write_note(
        tmp_path, "proj1", "research", "My Finding", "https://example.com", "Body.",
    )
    assert note_path.parent == tmp_path / "proj1" / "research"
    text = note_path.read_text(encoding="utf-8")
    assert 'title: "My Finding"' in text
    assert 'type: "research"' in text
    assert "Body." in text


# ── vault status ──────────────────────────────────────────────────────


def test_vault_status_lists_projects_but_not_the_vaults_own_dirs(
    tmp_path: Path,
) -> None:
    kb_vault.project_init(tmp_path, "proj1")
    kb_vault.project_init(tmp_path, "proj2")
    (tmp_path / "index").mkdir(exist_ok=True)
    status = kb_vault.vault_status(tmp_path)
    assert status["initialized"] is True
    assert status["projects"] == ["proj1", "proj2"]


def test_vault_status_on_an_uninitialized_vault_reports_no_projects(
    tmp_path: Path,
) -> None:
    status = kb_vault.vault_status(tmp_path)
    assert status == {
        "kb_home": str(tmp_path), "initialized": False, "projects": [],
    }


def test_a_symlinked_project_dir_cannot_be_written_through(
    tmp_path: Path,
) -> None:
    """A name passing the pattern is not enough: if <kb_home>/proj is a
    symlink out of the vault, every write below it lands outside."""
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "proj1").symlink_to(outside)

    with pytest.raises(ValueError, match="outside the vault"):
        kb_vault.write_note(vault, "proj1", "note", "Title", "", "body")
    with pytest.raises(ValueError, match="outside the vault"):
        kb_vault.project_init(vault, "proj1")
    assert list(outside.iterdir()) == []
