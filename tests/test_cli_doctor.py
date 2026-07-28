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

from cli import doctor  # noqa: E402  (path shim must precede this import)


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
