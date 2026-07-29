"""Unit tests for cli/doctor.py's prerequisite checks.

Monkeypatches `shutil.which` / `subprocess.run` / the module's own
`KB_ENV_PATH` on the `doctor` module directly (never invokes a real binary
and never touches the real ~/.knowledgebase), matching this repo's existing
test_cli_install.py / test_cli_bd.py conventions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench"

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from cli import doctor, install  # noqa: E402  (path shim must precede this import)


def _write_marker(target: Path, commit: str | None, source: str = "s") -> None:
    """Stand in for a --copy install's marker with a chosen `commit` /
    `source` (defaults to a source that matches nothing real, i.e. the
    "source unreachable" case)."""
    target.mkdir(parents=True, exist_ok=True)
    (target / install.INSTALL_MARKER).write_text(
        json.dumps({"commit": commit, "source": source, "installed_at": "t"}),
        encoding="utf-8",
    )


def _raise_repo_root_unreachable() -> Path:
    raise RuntimeError("agent-workbench: repository root not found.")


def _which_only(*names: str):
    """A `shutil.which` stand-in that reports only `names` as present."""
    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in names else None
    return fake_which


def _fake_run_ok(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
    """A `subprocess.run` stand-in reporting success for any command."""
    return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")


def _fake_run_fail(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
    """A `subprocess.run` stand-in reporting failure for any command."""
    return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"")


def _kb_env_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the kb.env check at a real file under `tmp_path`."""
    kb_env = tmp_path / "kb.env"
    kb_env.write_text("KB_ENRICH=0\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "KB_ENV_PATH", kb_env)


def _kb_env_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the kb.env check at a path that does not exist."""
    monkeypatch.setattr(doctor, "KB_ENV_PATH", tmp_path / "missing" / "kb.env")


def _all_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Wire every required + optional prerequisite as satisfied."""
    monkeypatch.setattr(
        doctor.shutil, "which",
        _which_only("docker", "podman", "podman-compose", "docker-compose",
                    "git", "tailscale"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_ok)
    _kb_env_present(monkeypatch, tmp_path)


def test_all_present_passes_and_reports_tailscale_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Every required + optional check present -> overall ok, exit 0."""
    _all_present(monkeypatch, tmp_path)

    checks = doctor.run_checks()

    assert doctor.all_required_ok(checks)
    tailscale = next(c for c in checks if c.name == "tailscale")
    assert tailscale.ok is True
    assert tailscale.fix_hint == ""


def test_no_check_is_named_rootless(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The retired rootless gate must not come back (mount-ownership decision)."""
    _all_present(monkeypatch, tmp_path)

    assert not hasattr(doctor, "check_rootless")
    assert all(c.name != "rootless" for c in doctor.run_checks())


def test_rootful_podman_still_passes_the_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A rootful runtime is not an install failure -- the regression the
    retired check caused on a working host."""
    def fake_run_rootful(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if cmd[0] == "podman" and "info" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=b'{"host":{"security":{"rootless":false}}}', stderr=b"",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        doctor.shutil, "which",
        _which_only("podman", "podman-compose", "git"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", fake_run_rootful)
    _kb_env_present(monkeypatch, tmp_path)

    assert doctor.cmd_doctor(argparse.Namespace(json=False)) == 0


def test_missing_required_check_fails_overall_and_cmd_doctor_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git missing (a required check) fails the gate and the handler's exit code."""
    monkeypatch.setattr(
        doctor.shutil, "which",
        _which_only("docker", "podman-compose", "tailscale"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_ok)
    _kb_env_present(monkeypatch, tmp_path)

    exit_code = doctor.cmd_doctor(argparse.Namespace(json=False))

    assert exit_code != 0
    assert "MISSING" in capsys.readouterr().out


def test_optional_missing_does_not_fail_the_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """All required present, tailscale (optional) missing -> still exit 0."""
    monkeypatch.setattr(
        doctor.shutil, "which",
        _which_only("docker", "podman-compose", "git"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_ok)
    _kb_env_present(monkeypatch, tmp_path)

    exit_code = doctor.cmd_doctor(argparse.Namespace(json=False))

    assert exit_code == 0


def test_optional_missing_renders_warn_never_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A failing optional check renders [WARN], not [SKIP], and still exits 0."""
    monkeypatch.setattr(
        doctor.shutil, "which",
        _which_only("docker", "podman-compose", "git"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_ok)
    _kb_env_present(monkeypatch, tmp_path)

    checks = doctor.run_checks()
    rendered = doctor.render_human(checks)

    assert "[WARN] tailscale" in rendered
    assert "SKIP" not in rendered
    assert doctor.all_required_ok(checks)


def test_json_flag_round_trips_through_json_loads_with_expected_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--json output is genuinely parseable JSON, not text wrapped in quotes."""
    _all_present(monkeypatch, tmp_path)

    exit_code = doctor.cmd_doctor(argparse.Namespace(json=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)
    for check in payload["checks"]:
        assert {"name", "required", "ok", "detail", "fix_hint"} <= check.keys()


def test_compose_check_distinguishes_docker_present_but_compose_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker on PATH but `docker compose version` fails, and no other
    compose impl present -> compose check reports missing, not ok."""
    monkeypatch.setattr(doctor.shutil, "which", _which_only("docker"))
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_fail)

    result = doctor.check_compose()

    assert result.ok is False
    assert result.required is True
    assert result.fix_hint != ""


def test_compose_check_ok_when_docker_compose_version_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docker on PATH and `docker compose version` succeeds -> compose ok."""
    monkeypatch.setattr(doctor.shutil, "which", _which_only("docker"))
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_ok)

    result = doctor.check_compose()

    assert result.ok is True
    assert "docker compose" in result.detail


def test_compose_check_fails_when_binary_is_on_path_but_will_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compose binary on PATH that exits non-zero is not a working compose.

    Presence is not workingness: a partially installed podman-compose sits on
    PATH and fails on every invocation.
    """
    monkeypatch.setattr(doctor.shutil, "which", _which_only("podman-compose"))
    monkeypatch.setattr(doctor.subprocess, "run", _fake_run_fail)

    result = doctor.check_compose()

    assert result.ok is False
    assert result.required is True
    assert "not runnable" in result.detail
    assert "podman-compose" in result.detail
    assert result.fix_hint != ""


def test_compose_check_survives_a_binary_that_cannot_be_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling symlink on PATH is "not runnable", not a doctor crash.

    which() succeeds and the exec then fails with OSError; doctor must report
    a broken machine rather than fall over on one.
    """
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(doctor.shutil, "which", _which_only("podman-compose"))
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_compose()

    assert result.ok is False
    assert "not runnable: podman-compose" in result.detail
    assert result.fix_hint != ""


def test_compose_check_passes_but_names_the_broken_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One working impl is enough, but a broken one still gets named."""
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        # `docker compose` fails (plugin absent), podman-compose works.
        code = 1 if cmd[0] == "docker" else 0
        return subprocess.CompletedProcess(cmd, code, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        doctor.shutil, "which", _which_only("docker", "podman-compose"),
    )
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor.check_compose()

    assert result.ok is True
    assert "found: podman-compose" in result.detail
    assert "not runnable: docker compose" in result.detail


def test_container_runtime_reports_both_when_both_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both docker and podman present -> both named in the detail."""
    monkeypatch.setattr(doctor.shutil, "which", _which_only("docker", "podman"))

    result = doctor.check_container_runtime()

    assert result.ok is True
    assert "docker" in result.detail
    assert "podman" in result.detail


def test_container_runtime_missing_reports_fix_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither runtime present -> required check fails with a fix hint."""
    monkeypatch.setattr(doctor.shutil, "which", _which_only("git"))

    result = doctor.check_container_runtime()

    assert result.ok is False
    assert result.required is True
    assert "podman" in result.fix_hint


def test_kb_env_check_fails_when_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Missing ~/.knowledgebase/kb.env is a required failure with a cp hint."""
    _kb_env_absent(monkeypatch, tmp_path)

    result = doctor.check_kb_env()

    assert result.name == "kb.env"
    assert result.required is True
    assert result.ok is False
    assert doctor.KB_ENV_EXAMPLE in result.fix_hint


def test_kb_env_check_passes_when_file_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An existing kb.env satisfies the check with no fix hint."""
    _kb_env_present(monkeypatch, tmp_path)

    result = doctor.check_kb_env()

    assert result.ok is True
    assert result.fix_hint == ""


def test_python_check_passes_on_the_running_interpreter() -> None:
    """The interpreter running the suite is by definition new enough."""
    result = doctor.check_python()

    assert result.ok is True
    assert result.required is True
    assert sys.executable in result.detail


def test_python_check_fails_below_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A floor above the running interpreter fails with a fix hint."""
    monkeypatch.setattr(doctor, "MIN_PYTHON", (99, 0))

    result = doctor.check_python()

    assert result.ok is False
    assert "need >= 99.0" in result.detail
    assert result.fix_hint != ""


# -- check_skill_install --------------------------------------------------

def test_skill_install_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Nothing at the install target -> not-ok, not required, has a hint."""
    monkeypatch.setattr(doctor.install, "install_target", lambda: tmp_path / "gone")

    result = doctor.check_skill_install()

    assert result.name == "skill install"
    assert result.required is False
    assert result.ok is False
    assert "not installed" in result.detail
    assert result.fix_hint != ""


def test_skill_install_symlink_flags_dev_defect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A symlink target is the defect: reported not-ok with the resolved
    path and an exact --copy reinstall hint."""
    real = tmp_path / "dev-repo-skill"
    real.mkdir()
    target = tmp_path / "target"
    target.symlink_to(real)
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert "dev symlink" in result.detail
    assert str(real.resolve()) in result.detail
    assert result.fix_hint.endswith("install --copy")


def test_skill_install_broken_symlink_is_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A dangling symlink is not a healthy dev symlink: `target.exists()`
    must be checked before assuming a symlink is a live dev install, and
    the fix hint must point at a path that actually exists (not the dead
    resolved target)."""
    target = tmp_path / "target"
    target.symlink_to(tmp_path / "gone-forever")
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert "broken symlink" in result.detail
    assert "gone-forever" in result.detail
    assert "does not exist" in result.detail
    assert "gone-forever" not in result.fix_hint
    assert result.fix_hint.endswith("install --copy")


def _mkdir_marker_source(repo_root: Path) -> str:
    """Create `<repo_root>/.claude/skills/agent-workbench` plus a
    `<repo_root>/scripts` dir (the plausibility test `check_skill_install`
    requires before trusting a derived repo root) on disk, and return the
    skill dir as the marker `source` string."""
    skill_dir = repo_root / ".claude" / "skills" / "agent-workbench"
    skill_dir.mkdir(parents=True)
    (repo_root / "scripts").mkdir()
    return str(skill_dir.resolve())


def test_skill_install_matches_repo_head_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Marker commit == repo HEAD -> ok, short SHA shown, no fix hint."""
    target = tmp_path / "target"
    commit = "deadbeef" * 5
    source = _mkdir_marker_source(tmp_path / "repo")
    _write_marker(target, commit, source=source)
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "git_head", lambda root: commit)

    result = doctor.check_skill_install()

    assert result.ok is True
    assert commit[:12] in result.detail
    assert result.fix_hint == ""


def test_skill_install_head_unreadable_is_warn_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Marker source exists but `paths.git_head` returns None (HEAD could
    not be read, e.g. a tarball checkout) -> not-ok (WARN, never gated on
    required), pinned short SHA shown, never called "stale", no fix hint.

    `ok=True` here used to render `[OK]` on a check that had just said it
    did not check -- indistinguishable from a verified match."""
    target = tmp_path / "target"
    commit = "deadbeef" * 5
    source = _mkdir_marker_source(tmp_path / "repo")
    _write_marker(target, commit, source=source)
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "git_head", lambda root: None)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "stale --" not in result.detail
    assert commit[:12] in result.detail
    assert "could not be read" in result.detail
    assert result.fix_hint == ""


def test_skill_install_stale_marker_is_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Marker commit != repo HEAD -> not-ok, both short SHAs shown."""
    target = tmp_path / "target"
    installed = "aaaa" * 10
    current = "bbbb" * 10
    source = _mkdir_marker_source(tmp_path / "repo")
    _write_marker(target, installed, source=source)
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "git_head", lambda root: current)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert "stale" in result.detail
    assert installed[:12] in result.detail
    assert current[:12] in result.detail
    assert result.fix_hint != ""


def test_skill_install_derives_repo_root_from_marker_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`check_skill_install` must call `paths.git_head` with the repo root
    derived from the marker's recorded source (its grandparent's parent),
    not from this file's own on-disk location -- the actual root cause of
    the defect (`paths._compute_root` walking up from cli/doctor.py itself
    lands under $HOME on a --copy install, which has no scripts/)."""
    target = tmp_path / "target"
    repo_root = tmp_path / "repo"
    commit = "deadbeef" * 5
    source = _mkdir_marker_source(repo_root)
    _write_marker(target, commit, source=source)
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    seen_roots: list[Path] = []

    def fake_git_head(root: Path) -> str:
        seen_roots.append(root)
        return commit

    monkeypatch.setattr(doctor.paths, "git_head", fake_git_head)

    result = doctor.check_skill_install()

    assert seen_roots == [repo_root.resolve()]
    assert result.ok is True


def test_skill_install_source_resolves_to_target_itself_is_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Degenerate case: the marker's source resolves to the install target
    itself (a stray $HOME that happens to look like a repo). Must not
    compare HEAD -- comparing against whatever unrelated repo happens to
    live at $HOME (a dotfiles repo, say) could false-report "stale" --
    WARN instead, and `git_head` must never even be called."""
    target = tmp_path / "target"
    target.mkdir(parents=True)
    _write_marker(target, "cccc" * 10, source=str(target))

    def fail_git_head(root: Path) -> str:
        raise AssertionError("git_head must not be called for a "
                              "self-referencing source")

    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "git_head", fail_git_head)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "stale --" not in result.detail
    assert result.fix_hint == ""


def test_skill_install_source_too_shallow_is_warn_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A marker source resolving to a path with fewer than 3 parents (so
    a naive `.parents[2]` would raise `IndexError`) must WARN, never
    crash -- `doctor` reports a broken machine, it does not fall over on
    one, the same argument this file already makes for `check_compose`."""
    target = tmp_path / "target"
    shallow = tmp_path / "root-link"
    shallow.symlink_to("/")
    _write_marker(target, "cccc" * 10, source=str(shallow))
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "stale --" not in result.detail
    assert result.fix_hint == ""


def test_skill_install_source_repo_root_missing_scripts_is_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The computed repo root (source's grandparent's parent) has no
    scripts/ dir -- not a plausible source repo, the same test
    `paths._compute_root` uses -- WARN, never a HEAD comparison against
    whatever unrelated repo might happen to live there."""
    target = tmp_path / "target"
    repo_root = tmp_path / "not-a-repo"
    skill_dir = repo_root / ".claude" / "skills" / "agent-workbench"
    skill_dir.mkdir(parents=True)  # no repo_root/scripts
    _write_marker(target, "cccc" * 10, source=str(skill_dir.resolve()))
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    def fail_git_head(root: Path) -> str:
        raise AssertionError("git_head must not be called for an "
                              "implausible repo root")

    monkeypatch.setattr(doctor.paths, "git_head", fail_git_head)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "stale --" not in result.detail
    assert result.fix_hint == ""


def test_skill_install_marker_source_missing_is_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A pinned copy whose marker records no `source` at all -> not-ok
    (renders WARN, since the check is not required), no fix hint, and
    `paths.repo_root` is never consulted."""
    target = tmp_path / "target"
    target.mkdir(parents=True)
    (target / install.INSTALL_MARKER).write_text(
        json.dumps({"commit": "cccc" * 10, "installed_at": "t"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "repo_root", _raise_repo_root_unreachable)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "no recorded source" in result.detail
    assert result.fix_hint == ""


def test_skill_install_marker_source_no_longer_exists_is_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The real bug this fix targets: on a --copy install, the source repo
    genuinely IS reachable, but a marker whose recorded source path was
    since moved or deleted must still report WARN (not silently OK) --
    "staleness could not be checked" must never look identical to a
    verified match."""
    target = tmp_path / "target"
    _write_marker(
        target, "cccc" * 10,
        source=str(tmp_path / "repo" / ".claude" / "skills" / "agent-workbench"),
    )
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "no longer exists" in result.detail
    assert result.fix_hint == ""


def test_skill_install_legacy_empty_marker_is_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Marker present but no recorded commit -> not-ok, unknown provenance."""
    target = tmp_path / "target"
    target.mkdir(parents=True)
    (target / install.INSTALL_MARKER).touch()
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert "legacy" in result.detail
    assert result.fix_hint != ""


def test_skill_install_unreachable_source_is_warn_not_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Marker has a commit but its recorded source path does not exist on
    disk -- this used to report `[OK] ... staleness could not be checked`
    (the defect: a silent decline that reads identical to a verified
    match). It must now report not-ok (WARN), never gated on required."""
    target = tmp_path / "target"
    _write_marker(target, "cccc" * 10)  # default source="s": not a real dir
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)
    monkeypatch.setattr(doctor.paths, "repo_root", _raise_repo_root_unreachable)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert result.required is False
    assert "staleness could not be checked" in result.detail
    assert result.fix_hint == ""


def test_skill_install_real_dir_no_marker_is_not_ok_and_offers_no_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A real dir this repo never installed -> not-ok, not installed by us,
    and the fix hint never instructs deleting it."""
    target = tmp_path / "target"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("unrelated\n", encoding="utf-8")
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()

    assert result.ok is False
    assert "not installed by this repo" in result.detail
    assert "rm " not in result.fix_hint
    assert "delete" not in result.fix_hint
    assert result.fix_hint != ""


def test_skill_install_never_required_so_never_gates_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Whatever state the install check is in, it cannot flip doctor's
    overall required-ok verdict: a failing (not-ok, not-required) skill
    install check must not change `all_required_ok`."""
    target = tmp_path / "target"
    target.symlink_to(tmp_path)  # guaranteed not-ok state
    monkeypatch.setattr(doctor.install, "install_target", lambda: target)

    result = doctor.check_skill_install()
    other_required_checks = [
        doctor.Check("git", True, True, "found", ""),
        doctor.Check("python3", True, True, "found", ""),
    ]

    assert result.required is False
    assert result.ok is False
    assert doctor.all_required_ok([*other_required_checks, result]) is True


def test_run_checks_includes_skill_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`run_checks` (and therefore --json) includes the new check by name."""
    _all_present(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor.install, "install_target", lambda: tmp_path / "gone")

    names = [c.name for c in doctor.run_checks()]

    assert "skill install" in names
