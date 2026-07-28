"""Tests for the `scratch` CLI verb's pure guard logic -- no podman needed.

`scratch` brings up a throwaway service container; the container-boundary
half of that is exercised manually (see the task's verification section),
never here, so this file never touches ports 9099/9100/9101 and never
shells out to podman. What IS pure logic, and must fail loudly rather than
silently falling back to the live stack, is covered here:

- an unknown service name is rejected by argparse before scratch.py runs
- a repo root with no docker-compose.yml (e.g. a copy-installed skill)
  raises, naming the missing files, instead of defaulting to live ports
- a scratch invocation with no wrapped command raises instead of no-op'ing
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_AGENT_WORKBENCH_DIR = (
    Path(__file__).resolve().parent.parent / ".claude" / "skills" / "agent-workbench"
)
if str(_AGENT_WORKBENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_WORKBENCH_DIR))

from cli import scratch  # noqa: E402
from cli.main import build_parser  # noqa: E402


def test_unknown_service_name_rejected() -> None:
    """`scratch bogus -- ...` fails loudly and non-zero, never runs."""
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["scratch", "bogus", "--", "echo", "hi"])
    assert exc_info.value.code != 0


def test_missing_compose_file_raises(tmp_path: Path, monkeypatch) -> None:
    """No docker-compose.yml at the resolved root -> loud RuntimeError.

    Never falls through to the live-stack default ports -- this must raise
    before any container is ever considered.
    """
    monkeypatch.setattr(scratch.paths, "repo_root", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="docker-compose"):
        scratch._compose_files()


def test_empty_command_raises() -> None:
    """`scratch kb --` with nothing after `--` refuses instead of no-op."""
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
