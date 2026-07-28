"""Coverage for the agent-workbench CLI's top-level surface.

Invokes the real `agent-workbench` executable as a subprocess (rather than
importing `cli.main` in-process) so these tests are robust against
import-path collisions with any other `cli` package elsewhere on
sys.path, and exercise the CLI exactly the way a real user/agent does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "agent-workbench"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the agent-workbench executable with `args`, capturing output."""
    return subprocess.run(
        [sys.executable, str(EXECUTABLE), *args],
        capture_output=True, text=True, check=False,
    )


def test_top_level_help_lists_expected_subcommands() -> None:
    """--help lists kb/bd/artifact/install/init-workspace/doctor/scratch,
    not hub/board/deploy."""
    result = run_cli("--help")
    assert result.returncode == 0
    assert "kb" in result.stdout
    assert "bd" in result.stdout
    assert "artifact" in result.stdout
    assert "install" in result.stdout
    assert "init-workspace" in result.stdout
    assert "doctor" in result.stdout
    assert "scratch" in result.stdout
    # The old separate top-level `hub`/`board` subcommands were folded into
    # `bd`; the exact choices set proves they no longer appear as top-level
    # subcommands (a stray "hub"/"board" would only show up folded inside
    # `bd`'s own help text, checked separately in test_bd_help_lists_*).
    assert (
        "{kb,bd,artifact,install,init-workspace,doctor,scratch}"
        in result.stdout
    )


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_top_level_help_flags_both_work(flag: str) -> None:
    """Both --help and -h produce the same usage/exit behavior."""
    result = run_cli(flag)
    assert result.returncode == 0
    assert "usage: agent-workbench" in result.stdout


def test_bd_help_lists_expected_sub_subcommands() -> None:
    """`bd --help` lists the folded hub and issue subcommands."""
    result = run_cli("bd", "--help")
    assert result.returncode == 0
    for name in ("init", "add", "sync", "list", "path", "status",
                 "ready", "search", "dep"):
        assert name in result.stdout


def test_artifact_help_lists_expected_sub_subcommands() -> None:
    """`artifact --help` lists publish/feedback/serve/status."""
    result = run_cli("artifact", "--help")
    assert result.returncode == 0
    for name in ("publish", "feedback", "serve", "status"):
        assert name in result.stdout


def test_install_help_shows_mutually_exclusive_flags() -> None:
    """`install --help` documents --link/--copy/--uninstall."""
    result = run_cli("install", "--help")
    assert result.returncode == 0
    assert "--link" in result.stdout
    assert "--copy" in result.stdout
    assert "--uninstall" in result.stdout


def test_install_with_no_flags_errors_nonzero() -> None:
    """`install` with no flag given is a required-mutually-exclusive-group error."""
    result = run_cli("install")
    assert result.returncode != 0
    assert "one of the arguments --link --copy --uninstall is required" in result.stderr


def test_retired_deploy_subcommand_is_rejected() -> None:
    """`deploy` was retired in favour of docker-compose; argparse must reject it."""
    result = run_cli("deploy", "status")
    assert result.returncode != 0
    assert "invalid choice: 'deploy'" in result.stderr


def test_missing_top_level_subcommand_errors_nonzero() -> None:
    """No subcommand at all is also a hard argparse error (required=True)."""
    result = run_cli()
    assert result.returncode != 0
