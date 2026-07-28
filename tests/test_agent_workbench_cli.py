"""Tests for the pure-Python agent-workbench CLI at
.claude/skills/agent-workbench/cli/.

One subcommand module per section (init-workspace, main dispatcher; the kb
HTTP client's own tests live in tests/test_cli_kb.py). Tests mock urllib for
anything that would hit the network, so nothing here ever touches a live
kb-svc, bd-svc, artifact-svc, or bdui process.

Each audit-fix test names its fix (M1/M3/M4/LOW) in its docstring; see
docs/agent-workbench-hardening-plan.md's "Audit fold-in mapping" table.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

_AGENT_WORKBENCH_DIR = (
    Path(__file__).resolve().parent.parent / ".claude" / "skills" / "agent-workbench"
)
if str(_AGENT_WORKBENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_WORKBENCH_DIR))

from cli import init_workspace, kb  # noqa: E402
from cli import main as cli_main  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# init-workspace
# ═══════════════════════════════════════════════════════════════════════


def test_cmd_init_workspace_scaffolds_a_tmp_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(init_workspace.bd, "cmd_add", lambda args: 0)

    result = init_workspace.cmd_init_workspace(
        argparse.Namespace(target_dir=str(tmp_path), prefix=None),
    )

    assert result == 0
    assert (tmp_path / "docs" / "kb").is_dir()
    assert (tmp_path / "workstreams").is_dir()
    # No repo-local index and no reindex hook: the vault under KB_HOME is the
    # searchable knowledgebase, and scripts/kb-index.py is its only indexer.
    assert not (tmp_path / "kb.db").exists()
    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()


def test_cmd_init_workspace_missing_target_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such directory"):
        init_workspace.cmd_init_workspace(
            argparse.Namespace(target_dir=str(tmp_path / "nope"), prefix=None),
        )


# ═══════════════════════════════════════════════════════════════════════
# main dispatcher
# ═══════════════════════════════════════════════════════════════════════


def test_build_parser_registers_every_subcommand() -> None:
    parser = cli_main.build_parser()
    [command_action] = [
        action for action in parser._subparsers._group_actions if action.dest == "command"
    ]
    assert set(command_action.choices) == {
        "kb", "bd", "artifact", "install", "init-workspace", "doctor",
    }


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli_main.main([])


def test_main_converts_a_handler_runtimeerror_to_exit_code_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(kb, "cmd_path", boom)
    assert cli_main.main(["kb", "path", "proj1"]) == 1
