"""Tests for scripts/scratch.py -- the repo dev/test harness's pure guard
logic -- no podman needed.

`scratch` brings up a throwaway service container; the container-boundary
half of that is exercised manually (see the task's verification section),
never here, so this file never touches ports 9099/9100/9101 and never
shells out to podman. What IS pure logic, and must fail loudly rather than
silently falling back to the live stack, is covered here:

- an unknown service name is rejected by argparse before scratch.py runs
- a repo root with no docker-compose.yml raises, naming the missing files,
  instead of defaulting to live ports
- a scratch invocation with no wrapped command raises instead of no-op'ing
- the two non-target services are pointed at a `.invalid` sentinel host,
  never the live defaults
- a service already redirected by an enclosing `scratch` run (nesting) is
  left alone rather than re-sentineled
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import scratch  # noqa: E402


def test_unknown_service_name_rejected() -> None:
    """`scratch.py bogus -- ...` fails loudly and non-zero, never runs."""
    with pytest.raises(SystemExit) as exc_info:
        scratch.build_parser().parse_args(["bogus", "--", "echo", "hi"])
    assert exc_info.value.code != 0


def test_missing_compose_file_raises(monkeypatch) -> None:
    """No docker-compose.yml at the repo root -> loud RuntimeError.

    Never falls through to the live-stack default ports -- this must raise
    before any container is ever considered.
    """
    monkeypatch.setattr(scratch, "REPO_ROOT", Path("/nonexistent-aw-root"))
    with pytest.raises(RuntimeError, match="docker-compose"):
        scratch._compose_files()


def test_empty_command_raises() -> None:
    """`scratch.py kb --` with nothing after `--` refuses instead of no-op."""
    with pytest.raises(RuntimeError, match="no command given"):
        scratch._command_args(["--"], "kb")


def test_podman_compose_chatter_stays_off_stdout(
    tmp_path: Path, monkeypatch,
) -> None:
    """podman-compose's own `up`/`down` output must never share stdout with
    the wrapped command -- an agent piping scratch's stdout to `jq` would
    otherwise see container IDs and project lines ahead of the JSON.

    No podman: every subprocess.run call is faked and recorded. Asserts
    `up` and `down` redirect stdout away from the process's own stdout,
    the `port` lookup (already capture_output=True) doesn't leak either,
    and the wrapped command's own subprocess.run call is untouched -- no
    `stdout` kwarg at all, so it inherits the real stdout.
    """
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], *args: object, **kwargs: object):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="127.0.0.1:12345\n")

    template = tmp_path / "docker-compose.scratch.yml"
    template.write_text("services: {}\n")  # placeholder has none to replace
    base = tmp_path / "docker-compose.yml"

    monkeypatch.setattr(scratch.subprocess, "run", fake_run)
    monkeypatch.setattr(scratch, "_require_podman_compose", lambda: None)
    monkeypatch.setattr(scratch, "_compose_files", lambda: (base, template))
    monkeypatch.setattr(scratch, "_wait_healthy", lambda *a, **kw: None)

    args = argparse.Namespace(service="kb", command=["--", "echo", "hi"])
    returncode = scratch.cmd_scratch(args)
    assert returncode == 0

    def find(token: str) -> dict[str, object]:
        [kwargs] = [kw for cmd, kw in calls if token in cmd]
        return kwargs

    assert find("up")["stdout"] is sys.stderr
    assert find("down")["stdout"] is sys.stderr
    # port lookup already uses capture_output=True; must not ALSO leak
    # to the process's own stdout via an explicit stdout= kwarg.
    assert "stdout" not in find("port")

    wrapped_cmd, wrapped_kwargs = calls[-2]  # up, port, [wrapped], down
    assert wrapped_cmd == ["echo", "hi"]
    assert "stdout" not in wrapped_kwargs


def test_non_target_services_get_sentinel_host(monkeypatch) -> None:
    """`scratch kb` must not leave BD_SVC_HOST/ARTIFACT_SVC_HOST at their
    live defaults -- a chained call to either must fail loudly, never
    silently reach the real service.
    """
    monkeypatch.delenv(scratch.ACTIVE_ENV, raising=False)
    env = scratch._scratch_env(scratch.SERVICES["kb"], 12345, "kb")

    assert env["KB_SVC_HOST"] == "127.0.0.1"
    assert env["KB_SVC_PORT"] == "12345"
    assert env["BD_SVC_HOST"] == "bd-svc-not-started-by-this-scratch-run.invalid"
    assert env["ARTIFACT_SVC_HOST"] == (
        "artifact-svc-not-started-by-this-scratch-run.invalid"
    )
    assert env[scratch.ACTIVE_ENV] == "kb"


def test_nested_scratch_leaves_outer_service_alone(monkeypatch) -> None:
    """`scratch.py kb -- scratch.py bd -- ...`: the inner `scratch bd` must
    not overwrite the outer run's live KB_SVC_HOST/PORT with the sentinel.
    """
    monkeypatch.setenv("KB_SVC_HOST", "127.0.0.1")
    monkeypatch.setenv("KB_SVC_PORT", "55555")
    monkeypatch.setenv(scratch.ACTIVE_ENV, "kb")

    env = scratch._scratch_env(scratch.SERVICES["bd"], 12345, "bd")

    assert env["KB_SVC_HOST"] == "127.0.0.1"
    assert env["KB_SVC_PORT"] == "55555"
    assert env["BD_SVC_HOST"] == "127.0.0.1"
    assert env["BD_SVC_PORT"] == "12345"
    assert env["ARTIFACT_SVC_HOST"] == (
        "artifact-svc-not-started-by-this-scratch-run.invalid"
    )
    assert env[scratch.ACTIVE_ENV] == "bd,kb"
