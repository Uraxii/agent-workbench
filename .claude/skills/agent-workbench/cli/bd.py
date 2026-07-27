"""`bd` subcommand -- one argparse front door over the `hub` (board hub)
and `board` (bdui web front end) implementation modules.

Folds the former separate top-level `hub` and `board` subcommands into
one `bd` subcommand, since both exist only to drive the `bd` (beads)
board tooling. Sub-subcommands:
    init                init the aggregator board (idempotent)      [hub]
    add NAME [PREFIX]   create+register $HUB_ROOT/NAME/.beads       [hub]
    sync                hydrate the aggregator from all repos       [hub]
    list                list registered repos                       [hub]
    path NAME           print $HUB_ROOT/NAME/.beads                 [hub]
    status              JSON: hub_root, initialized?, repos         [hub]
    ui-up [REPO_DIR]    start (or reuse) the board UI; prints URL   [board]
    ui-down [REPO_DIR]  stop the board UI for REPO_DIR              [board]
    ui-status           list running board UIs                      [board]

This module carries no logic of its own: every sub-subcommand's `func`
is the corresponding `cmd_*` handler already defined in `hub.py` /
`board.py`, reused directly. See those modules for the actual
implementation and folded audit-fix notes.
"""
from __future__ import annotations

import argparse

from cli import board, hub

__all__ = ["register"]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `bd` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("bd", help="bd (beads) board hub + web UI ops")
    sub = parser.add_subparsers(dest="bd_command", required=True)

    init_cmd = sub.add_parser("init", help="init the aggregator board (idempotent)")
    init_cmd.set_defaults(func=hub.cmd_init)

    add_cmd = sub.add_parser("add", help="create+register $HUB_ROOT/NAME/.beads")
    add_cmd.add_argument("name")
    add_cmd.add_argument("prefix", nargs="?", default=None)
    add_cmd.set_defaults(func=hub.cmd_add)

    sync_cmd = sub.add_parser("sync", help="hydrate the aggregator from all repos")
    sync_cmd.set_defaults(func=hub.cmd_sync)

    list_cmd = sub.add_parser("list", help="list registered repos")
    list_cmd.set_defaults(func=hub.cmd_list)

    path_cmd = sub.add_parser("path", help="print $HUB_ROOT/NAME/.beads")
    path_cmd.add_argument("name")
    path_cmd.set_defaults(func=hub.cmd_path)

    status_cmd = sub.add_parser("status", help="JSON: hub_root, initialized?, repos")
    status_cmd.set_defaults(func=hub.cmd_status)

    ui_up_cmd = sub.add_parser("ui-up", help="start (or reuse) the board UI; prints URL")
    ui_up_cmd.add_argument("repo_dir", nargs="?", default=".")
    ui_up_cmd.set_defaults(func=board.cmd_up)

    ui_down_cmd = sub.add_parser("ui-down", help="stop the board UI for REPO_DIR")
    ui_down_cmd.add_argument("repo_dir", nargs="?", default=".")
    ui_down_cmd.set_defaults(func=board.cmd_down)

    ui_status_cmd = sub.add_parser("ui-status", help="list running board UIs")
    ui_status_cmd.set_defaults(func=board.cmd_status)
