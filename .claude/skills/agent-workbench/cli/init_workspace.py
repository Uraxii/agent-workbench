"""`init-workspace` subcommand -- pure-Python port of
scripts/init-agent-workspace.sh.

Scaffold the standard per-project agent workspace into a target repo:
  * bd board            created + registered via the ``bd`` module (lives
                        centrally under the hub root, never in the repo)
  * docs/kb/            distilled markdown KB entries (tracked)
  * workstreams/        per-workstream status.md + artifacts

No per-repo search index is scaffolded. The searchable knowledgebase is the
central vault under KB_HOME, and ``scripts/kb-index.py`` is the one indexer
over it, reached through ``kb query``. A second, repo-local index over
docs/kb/ would be a second lineage of the same thing, free to drift.

Idempotent: safe to re-run; each component reports "already initialized"
rather than clobbering. Usage:
    init-workspace [TARGET_DIR] [--prefix PREFIX]

Uses the `bd` module for board creation, not a subprocess to the old
beads-hub.sh.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from cli import bd

__all__ = ["register", "scaffold_dirs"]

WORKSPACE_DIRS = ("docs/kb", "workstreams")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `init-workspace` parser; set its func handler."""
    parser = subparsers.add_parser(
        "init-workspace", help="scaffold a repo's agent workspace",
    )
    parser.add_argument("target_dir", nargs="?", default=".")
    parser.add_argument("--prefix", default=None)
    parser.set_defaults(func=cmd_init_workspace)


def scaffold_dirs(target_dir: Path) -> list[str]:
    """Create docs/kb and workstreams under ``target_dir`` if absent.

    Returns the list of dirs actually created (empty if all pre-existed).
    """
    created: list[str] = []
    for rel in WORKSPACE_DIRS:
        dir_path = target_dir / rel
        if dir_path.is_dir():
            print(f"init-agent-workspace: {rel} already exists, skipping")
            continue
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"init-agent-workspace: created {rel}")
        created.append(rel)
    return created


def cmd_init_workspace(args: argparse.Namespace) -> int:
    """Run the full scaffold against TARGET_DIR (default cwd).

    Order: register the bd board via the `bd` module (fatal on failure --
    it is the project's only board), then scaffold the dirs.
    """
    raw_target = Path(args.target_dir)
    if not raw_target.is_dir():
        raise ValueError(f"init-agent-workspace: no such directory: {args.target_dir}")
    target_dir = raw_target.resolve()
    prefix = args.prefix or target_dir.name

    bd.cmd_add(argparse.Namespace(name=prefix, prefix=None))
    print(f"init-agent-workspace: bd board ready via hub (prefix: {prefix})")

    scaffold_dirs(target_dir)

    print(f"init-agent-workspace: done ({target_dir})")
    return 0
