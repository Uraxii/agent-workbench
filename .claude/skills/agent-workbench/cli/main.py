"""Top-level argparse dispatcher for the agent-workbench CLI.

Builds one parent parser, lets each subcommand module register its own
subparser (setting ``func``), then routes ``args.func(args)``. Mirrors the
build_parser/dispatch shape scripts/kb-svc.py already uses, so the two
stay stylistically consistent.
"""
from __future__ import annotations

import argparse
import logging

from cli import artifact, bd, doctor, init_workspace, install, kb

__all__ = ["build_parser", "main"]

log = logging.getLogger("agent-workbench")

SUBCOMMAND_MODULES = (
    kb, bd, artifact, install, init_workspace, doctor,
)


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser with every subcommand registered.

    Each subcommand module exposes ``register(subparsers)`` which adds its
    parser and calls ``set_defaults(func=<handler>)``. Postcondition: the
    returned parser requires a subcommand (``required=True``).
    """
    parser = argparse.ArgumentParser(
        prog="agent-workbench",
        description="Locally deployable agent workbench: knowledgebase "
                     "vault (kb), bd board hub (bd), the "
                     "artifact review app (artifact), workspace scaffold "
                     "(init-workspace), and fresh-machine prerequisite "
                     "checks (doctor).",
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
    except (RuntimeError, ValueError, OSError) as exc:
        log.error("%s", exc)
        return 1
