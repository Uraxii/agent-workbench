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

import sys
from pathlib import Path

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
