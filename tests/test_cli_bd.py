"""Light-touch coverage for cli/bd.py.

cli/bd.py carries no logic of its own: it is a pure re-registration of
`hub.py`/`board.py`'s existing `cmd_*` handlers under one `bd`
sub-subcommand tree. This just asserts the wiring is correct (each
sub-subcommand's `func` is the expected existing function object), not
`hub.py`/`board.py`'s actual behavior (unchanged, pre-existing, out of
scope here).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench"

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from cli import bd, board, hub  # noqa: E402  (path shim must precede this import)


def build_bd_parser() -> argparse.ArgumentParser:
    """A standalone parser with only `bd` registered under it."""
    parser = argparse.ArgumentParser(prog="agent-workbench")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bd.register(subparsers)
    return parser


def test_bd_init_wires_to_hub_cmd_init() -> None:
    args = build_bd_parser().parse_args(["bd", "init"])
    assert args.func is hub.cmd_init


def test_bd_add_wires_to_hub_cmd_add_with_name_and_optional_prefix() -> None:
    args = build_bd_parser().parse_args(["bd", "add", "myproj"])
    assert args.func is hub.cmd_add
    assert args.name == "myproj"
    assert args.prefix is None

    args = build_bd_parser().parse_args(["bd", "add", "myproj", "mp"])
    assert args.func is hub.cmd_add
    assert args.prefix == "mp"


def test_bd_sync_wires_to_hub_cmd_sync() -> None:
    args = build_bd_parser().parse_args(["bd", "sync"])
    assert args.func is hub.cmd_sync


def test_bd_list_wires_to_hub_cmd_list() -> None:
    args = build_bd_parser().parse_args(["bd", "list"])
    assert args.func is hub.cmd_list


def test_bd_path_wires_to_hub_cmd_path() -> None:
    args = build_bd_parser().parse_args(["bd", "path", "myproj"])
    assert args.func is hub.cmd_path
    assert args.name == "myproj"


def test_bd_status_wires_to_hub_cmd_status() -> None:
    args = build_bd_parser().parse_args(["bd", "status"])
    assert args.func is hub.cmd_status


def test_bd_ui_up_wires_to_board_cmd_up_with_default_repo_dir() -> None:
    args = build_bd_parser().parse_args(["bd", "ui-up"])
    assert args.func is board.cmd_up
    assert args.repo_dir == "."

    args = build_bd_parser().parse_args(["bd", "ui-up", "/some/repo"])
    assert args.repo_dir == "/some/repo"


def test_bd_ui_down_wires_to_board_cmd_down_with_default_repo_dir() -> None:
    args = build_bd_parser().parse_args(["bd", "ui-down"])
    assert args.func is board.cmd_down
    assert args.repo_dir == "."


def test_bd_ui_status_wires_to_board_cmd_status() -> None:
    args = build_bd_parser().parse_args(["bd", "ui-status"])
    assert args.func is board.cmd_status


def test_bd_requires_a_sub_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_bd_parser().parse_args(["bd"])
