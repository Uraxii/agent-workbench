"""Unit tests for cli/install.py's link/copy/uninstall helpers.

Exercises `_install_link`, `_install_copy`, and `_uninstall` directly
against `tmp_path` fixtures standing in for the real
`~/.claude/skills/agent-workbench` target -- the real path is never
touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench"

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from cli import install  # noqa: E402  (path shim must precede this import)


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """A fake skill source dir with one marker file, standing in for
    this repo's real .claude/skills/agent-workbench."""
    src = tmp_path / "source-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("marker\n", encoding="utf-8")
    return src


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    """The fake install target, standing in for ~/.claude/skills/agent-workbench."""
    return tmp_path / "install-target" / "agent-workbench"


def test_install_link_creates_symlink_to_source(source: Path, target: Path) -> None:
    """--link creates a symlink pointing at source."""
    install._install_link(target, source)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()


def test_install_link_is_idempotent_when_already_linked(
    source: Path, target: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Re-running --link when already correctly linked is a no-op, no error."""
    install._install_link(target, source)
    capsys.readouterr()

    install._install_link(target, source)

    assert target.is_symlink()
    assert target.resolve() == source.resolve()
    assert "already linked" in capsys.readouterr().out


def test_install_link_refuses_real_dir(source: Path, tmp_path: Path) -> None:
    """--link raises rather than replacing a real (non-symlink) directory."""
    target = tmp_path / "real-dir"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to replace real dir"):
        install._install_link(target, source)

    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / "unrelated.txt").is_file()


def test_install_copy_recursively_copies_and_excludes_pycache(
    source: Path, target: Path,
) -> None:
    """--copy recursively copies source contents, skipping __pycache__ dirs."""
    (source / "sub").mkdir()
    (source / "sub" / "nested.py").write_text("pass\n", encoding="utf-8")
    pycache = source / "__pycache__"
    pycache.mkdir()
    (pycache / "nested.cpython-312.pyc").write_bytes(b"\x00\x01")

    install._install_copy(target, source)

    assert not target.is_symlink()
    assert target.is_dir()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "marker\n"
    assert (target / "sub" / "nested.py").is_file()
    assert not (target / "__pycache__").exists()


def test_install_copy_replaces_existing_symlink(source: Path, target: Path) -> None:
    """--copy over a pre-existing symlink target unlinks it first, then copies."""
    other_source = target.parent / "other-source"
    other_source.mkdir(parents=True)
    (other_source / "SKILL.md").write_text("other\n", encoding="utf-8")
    install._install_link(target, other_source)
    assert target.is_symlink()

    install._install_copy(target, source)

    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "marker\n"


def test_uninstall_removes_correctly_pointing_symlink(
    source: Path, target: Path,
) -> None:
    """--uninstall removes a symlink that points at this repo's own source."""
    install._install_link(target, source)
    assert target.is_symlink()

    install._uninstall(target, source)

    assert not target.exists()
    assert not target.is_symlink()


def test_uninstall_refuses_real_dir(source: Path, tmp_path: Path) -> None:
    """--uninstall does NOT delete a real (non-symlink) directory."""
    target = tmp_path / "real-dir"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep me\n", encoding="utf-8")

    install._uninstall(target, source)

    assert target.is_dir()
    assert (target / "unrelated.txt").is_file()


def test_uninstall_refuses_symlink_pointing_elsewhere(
    source: Path, target: Path, tmp_path: Path,
) -> None:
    """--uninstall does NOT remove a symlink that points at a different source."""
    other_source = tmp_path / "other-source"
    other_source.mkdir()
    install._install_link(target, other_source)
    assert target.is_symlink()

    install._uninstall(target, source)

    assert target.is_symlink()
    assert target.resolve() == other_source.resolve()


def test_uninstall_no_op_when_nothing_installed(
    target: Path, source: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """--uninstall on a target that doesn't exist at all is a clean no-op."""
    install._uninstall(target, source)

    assert not target.exists()
    assert "nothing installed" in capsys.readouterr().out
