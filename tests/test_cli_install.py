"""Unit tests for cli/install.py's link/copy/uninstall helpers.

Exercises `_install_link`, `_install_copy`, and `_uninstall` directly
against `tmp_path` fixtures standing in for the real
`~/.claude/skills/agent-workbench` target -- the real path is never
touched.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench"

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from cli import install, paths  # noqa: E402  (path shim must precede this import)


def _git(cwd: Path, *args: str) -> None:
    """Run `git <args>` in `cwd` with a throwaway identity, for test fixtures
    only -- never used by the shipped CLI itself."""
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _git_output(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _rev_parse(cwd: Path, rev: str) -> str:
    return _git_output(cwd, "rev-parse", rev)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """A real one-commit git repo under `tmp_path`, for exercising
    `paths.git_head` against real git-managed files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


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


def test_install_copy_refuses_unstamped_real_dir(source: Path, tmp_path: Path) -> None:
    """--copy refuses rather than merging over a real dir it did not
    install, and leaves that dir untouched.

    The refusal is signalled by a non-zero return, not an exception, so the
    CLI reports it as a clean exit code rather than a traceback. See
    test_cmd_install_copy_propagates_refusal_as_exit_1 for the end-to-end
    path.
    """
    target = tmp_path / "real-dir"
    target.mkdir()
    (target / "unrelated.txt").write_text("keep me\n", encoding="utf-8")

    assert install._install_copy(target, source) == 1

    assert target.is_dir()
    assert not target.is_symlink()
    assert (target / "unrelated.txt").is_file()
    assert not (target / "SKILL.md").exists()


def test_install_copy_reinstalls_over_own_stamped_dir(
    source: Path, target: Path,
) -> None:
    """Re-running --copy over a dir it previously stamped is fine
    (idempotent reinstall)."""
    install._install_copy(target, source)
    assert install.read_marker(target) is not None

    (source / "SKILL.md").write_text("updated\n", encoding="utf-8")
    install._install_copy(target, source)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "updated\n"
    assert install.read_marker(target) is not None


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


def test_install_copy_reinstall_removes_orphan_file_not_in_source(
    source: Path, target: Path,
) -> None:
    """A reinstall over a prior marked copy produces exactly the source
    tree: a file the old install had that source no longer has (e.g. a
    retired module) must not survive."""
    install._install_copy(target, source)
    orphan = target / "cli" / "scratch.py"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("pass\n", encoding="utf-8")
    assert orphan.exists()

    exit_code = install._install_copy(target, source)

    assert exit_code == 0
    assert not orphan.exists()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "marker\n"
    assert install.read_marker(target) is not None


def test_install_copy_refuses_foreign_real_dir_and_leaves_it_intact(
    source: Path, target: Path,
) -> None:
    """A real dir at target with no INSTALL_MARKER is not this repo's own
    copy install -- refuse, exit 1, and never touch its contents."""
    target.mkdir(parents=True)
    (target / "unrelated.txt").write_text("keep me\n", encoding="utf-8")

    exit_code = install._install_copy(target, source)

    assert exit_code == 1
    assert target.is_dir()
    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "keep me\n"
    assert not (target / "SKILL.md").exists()
    assert install.read_marker(target) is None


def test_install_copy_refuses_plain_file_target_and_leaves_it_untouched(
    source: Path, target: Path,
) -> None:
    """A target that is a regular file -- neither a symlink nor a dir --
    falls through both existing guards and must be refused outright, not
    copied over and then `rmtree`'d (which raises NotADirectoryError)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not a skill dir\n", encoding="utf-8")

    exit_code = install._install_copy(target, source)

    assert exit_code == 1
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "not a skill dir\n"


def test_install_copy_removes_temp_dir_when_copytree_fails(
    source: Path, target: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any failure past `copytree` must not leave the sibling temp dir
    behind -- ``~/.claude/skills/`` is exactly what Claude Code enumerates
    for skills, so a surviving ``*.tmp-<pid>`` there (carrying a valid
    marker once `_write_marker` has run) would register as a second,
    permanently stale copy of the skill."""
    # Fail AFTER copytree has populated the temp dir. Failing copytree
    # itself leaves nothing on disk to clean up, so such a test passes
    # even with the `finally` deleted -- it can never catch the defect.
    def fail_write_marker(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(install, "_write_marker", fail_write_marker)

    with pytest.raises(OSError, match="disk full"):
        install._install_copy(target, source)

    leftovers = list(target.parent.glob(f"{target.name}.tmp-*"))
    assert leftovers == [], f"temp dir survived: {leftovers}"


def test_cmd_install_copy_propagates_refusal_as_exit_1(
    source: Path, target: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`install --copy` onto a foreign dir must EXIT 1, not just print.

    `_install_copy` returning 1 is worthless if `cmd_install` drops it:
    the caller sees success for an install that never happened, which is
    the exact "a failed operation must not look like a success" failure
    this branch exists to remove. Nothing else exercises `cmd_install`.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    (target / "unrelated.txt").write_text("not ours\n", encoding="utf-8")

    monkeypatch.setattr(install, "install_target", lambda: target)
    monkeypatch.setattr(install, "source_dir", lambda: source)

    args = argparse.Namespace(link=False, copy=True, uninstall=False)

    assert install.cmd_install(args) == 1
    assert (target / "unrelated.txt").read_text(encoding="utf-8") == "not ours\n"
    assert not (target / "SKILL.md").exists()


def test_cmd_install_copy_returns_0_on_success(
    source: Path, target: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The success direction of the same seam, so the refusal test above
    cannot pass by `cmd_install` simply always returning 1."""
    monkeypatch.setattr(install, "install_target", lambda: target)
    monkeypatch.setattr(install, "source_dir", lambda: source)

    args = argparse.Namespace(link=False, copy=True, uninstall=False)

    assert install.cmd_install(args) == 0
    assert (target / "SKILL.md").exists()


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


# -- paths.git_head -----------------------------------------------------

def test_git_head_resolves_normal_checkout(git_repo: Path) -> None:
    """A plain (non-worktree) checkout resolves via the symbolic HEAD ref."""
    expected = _rev_parse(git_repo, "HEAD")

    assert paths.git_head(git_repo) == expected


def test_git_head_resolves_linked_worktree(
    git_repo: Path, tmp_path: Path,
) -> None:
    """A linked worktree's `.git` file + `commondir` resolves too."""
    worktree = tmp_path / "wt"
    _git(git_repo, "worktree", "add", "-q", str(worktree))
    expected = _rev_parse(worktree, "HEAD")

    assert (worktree / ".git").is_file()
    assert paths.git_head(worktree) == expected


def test_git_head_resolves_packed_ref(git_repo: Path) -> None:
    """A ref that only exists in `packed-refs` (loose ref pruned) still
    resolves."""
    branch_ref = _git_output(git_repo, "symbolic-ref", "HEAD")
    _git(git_repo, "pack-refs", "--all")
    (git_repo / ".git" / branch_ref).unlink(missing_ok=True)
    expected = _rev_parse(git_repo, "HEAD")

    assert paths.git_head(git_repo) == expected


def test_git_head_resolves_detached_head(git_repo: Path) -> None:
    """A raw 40-char SHA in HEAD (detached) is returned as-is."""
    sha = _rev_parse(git_repo, "HEAD")
    _git(git_repo, "checkout", "-q", "--detach", sha)

    assert paths.git_head(git_repo) == sha


def test_git_head_returns_none_on_garbage(tmp_path: Path) -> None:
    """No `.git` at all, a malformed HEAD, and a dangling gitdir file all
    return None instead of raising."""
    assert paths.git_head(tmp_path / "not-a-repo") is None

    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / ".git").mkdir()
    (junk / ".git" / "HEAD").write_text("nonsense\n", encoding="utf-8")
    assert paths.git_head(junk) is None

    dangling = tmp_path / "dangling"
    dangling.mkdir()
    (dangling / ".git").write_text("gitdir: /nonexistent/x\n", encoding="utf-8")
    assert paths.git_head(dangling) is None


# -- paths._compute_root --------------------------------------------------

def _fake_paths_module_file(tree_root: Path) -> Path:
    """A synthetic ``cli/paths.py`` path five levels under `tree_root`,
    mirroring this repo's real ``<repo>/.claude/skills/agent-workbench/
    cli/paths.py`` depth, so `parents[4]` lands back on `tree_root`."""
    return (
        tree_root / ".claude" / "skills" / "agent-workbench" / "cli"
        / "paths.py"
    )


def test_compute_root_rejects_scripts_dir_without_docker_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tree with `scripts/` but no `docker-compose.yml` is NOT accepted
    as the repo root (e.g. a user's own `~/scripts` under a --copy
    install's `$HOME` candidate)."""
    candidate = tmp_path / "not-the-repo"
    (candidate / "scripts").mkdir(parents=True)
    monkeypatch.setattr(
        paths, "__file__", str(_fake_paths_module_file(candidate)),
    )

    assert paths._compute_root() is None


def test_compute_root_accepts_scripts_and_docker_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tree with both `scripts/` and `docker-compose.yml` is accepted."""
    candidate = tmp_path / "the-repo"
    (candidate / "scripts").mkdir(parents=True)
    (candidate / "docker-compose.yml").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(
        paths, "__file__", str(_fake_paths_module_file(candidate)),
    )

    assert paths._compute_root() == candidate


# -- install marker -------------------------------------------------------

def test_install_copy_writes_marker_json_with_commit_source_timestamp(
    source: Path, target: Path, git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--copy stamps a JSON marker carrying commit, source, and timestamp."""
    monkeypatch.setattr(paths, "repo_root", lambda: git_repo)
    expected_commit = _rev_parse(git_repo, "HEAD")

    install._install_copy(target, source)

    marker = install.read_marker(target)
    assert marker is not None
    assert marker["commit"] == expected_commit
    assert marker["source"] == str(source.resolve())
    datetime.fromisoformat(str(marker["installed_at"]))  # does not raise


def test_read_marker_returns_none_when_absent(target: Path) -> None:
    """No marker file at all -> None, distinct from an empty/legacy one."""
    assert install.read_marker(target) is None


def test_read_marker_legacy_empty_file_reads_as_present_no_commit(
    target: Path,
) -> None:
    """The old `touch()`-only marker parses as `{}`: present, no commit."""
    target.mkdir(parents=True)
    (target / install.INSTALL_MARKER).touch()

    assert install.read_marker(target) == {}


def test_read_marker_corrupt_json_reads_as_present_empty(target: Path) -> None:
    """Corrupt marker contents parse as `{}`, not a crash."""
    target.mkdir(parents=True)
    (target / install.INSTALL_MARKER).write_text("{not json", encoding="utf-8")

    assert install.read_marker(target) == {}


def test_uninstall_accepts_legacy_empty_marker(source: Path, target: Path) -> None:
    """--uninstall still removes a copy install stamped by the old empty
    touch()-only marker."""
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("x\n", encoding="utf-8")
    (target / install.INSTALL_MARKER).touch()

    assert install._uninstall(target, source) is True
    assert not target.exists()
