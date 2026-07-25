"""Top-level argparse dispatcher for the agent-workbench CLI.

Builds one parent parser, lets each subcommand module register its own
subparser (setting ``func``), then routes ``args.func(args)``. Mirrors the
build_parser/dispatch shape scripts/kb-serve.py already uses, so the two
stay stylistically consistent.
"""
from __future__ import annotations

import argparse
import logging
import subprocess

from cli import board, deploy, hub, init_workspace, kb

__all__ = ["build_parser", "main"]

log = logging.getLogger("agent-workbench")

SUBCOMMAND_MODULES = (kb, hub, board, init_workspace, deploy)


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser with every subcommand registered.

    Each subcommand module exposes ``register(subparsers)`` which adds its
    parser and calls ``set_defaults(func=<handler>)``. Postcondition: the
    returned parser requires a subcommand (``required=True``).
    """
    parser = argparse.ArgumentParser(
        prog="agent-workbench",
        description="Locally deployable agent workbench: knowledgebase "
                     "vault, bd board hub, board web UI, workspace "
                     "scaffold, and hardened kb-serve/review-serve "
                     "containers.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in SUBCOMMAND_MODULES:
        module.register(subparsers)
    return parser


def main(argv: list[str]) -> int:
    """Parse argv and dispatch to the selected subcommand handler.

    Args:
        argv: process args without the program name.

    Returns:
        The subcommand's process exit code (0 on success).
    """
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except subprocess.CalledProcessError as exc:
        log.error("%s", exc)
        return exc.returncode or 1
    except (RuntimeError, ValueError, OSError) as exc:
        log.error("%s", exc)
        return 1
