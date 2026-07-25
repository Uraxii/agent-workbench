"""`init-workspace` subcommand -- pure-Python port of
scripts/init-agent-workspace.sh.

Scaffold the standard per-project agent workspace into a target repo:
  * bd board            created + registered via the ``hub`` module (lives
                        centrally under the hub root, never in the repo)
  * docs/kb/            distilled markdown KB entries (tracked)
  * workstreams/        per-workstream status.md + artifacts
  * kb.db               FTS5 index over docs/kb/ (build-kb-index.py)
  * post-commit hook    reindexes docs/kb/ when a commit touches it

Idempotent: safe to re-run; each component reports "already initialized"
rather than clobbering. Usage:
    init-workspace [TARGET_DIR] [--prefix PREFIX]

Reuses the `hub` module directly for board creation (in-process call to
hub.cmd_add-equivalent), not a subprocess to the old beads-hub.sh.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from cli import hub, paths, siblings

__all__ = ["register", "scaffold_dirs", "install_post_commit_hook"]

WORKSPACE_DIRS = ("docs/kb", "workstreams")

POST_COMMIT_HOOK = """#!/usr/bin/env bash
# Post-commit KB reindex hook (untracked, installed by
# agent-workbench init-workspace). Reindexes docs/kb/ into kb.db only when
# this commit touched docs/kb/; no-op otherwise.
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
if git diff-tree --no-commit-id --name-only -r --root HEAD | grep -q '^docs/kb/'; then
  "{indexer}" --root "$repo_root"
fi
"""


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


def build_index(target_dir: Path) -> None:
    """Rebuild ``target_dir``'s docs/kb FTS5 index via build-kb-index.py.

    Loaded in-process through cli.siblings, not shelled out.
    """
    build_kb_index = siblings.load_script("build-kb-index")
    build_kb_index.main(["--root", str(target_dir)])


def install_post_commit_hook(target_dir: Path) -> bool:
    """Install the docs/kb reindex post-commit hook.

    Never overwrites an existing hook: returns False and leaves a manual
    instruction to stdout if ``.git/hooks/post-commit`` already exists;
    returns True when it writes (mode 0o755) the hook.

    Precondition: ``target_dir`` is a git working tree.
    """
    hook_path = target_dir / ".git" / "hooks" / "post-commit"
    indexer = paths.SCRIPTS_DIR / "build-kb-index.py"
    if hook_path.is_file():
        print(f"init-agent-workspace: WARNING {hook_path} already exists, not overwriting.")
        print("  Add this line to it manually to keep the KB index current:")
        print(
            "  git diff-tree --no-commit-id --name-only -r --root HEAD | "
            f"grep -q '^docs/kb/' && \"{indexer}\" --root \"$(git rev-parse --show-toplevel)\""
        )
        return False

    hook_path.write_text(POST_COMMIT_HOOK.format(indexer=indexer), encoding="utf-8")
    hook_path.chmod(0o755)
    print("init-agent-workspace: installed post-commit KB reindex hook")
    return True


def cmd_init_workspace(args: argparse.Namespace) -> int:
    """Run the full scaffold against TARGET_DIR (default cwd).

    Order: register the bd board via the `hub` module (fatal on failure --
    it is the project's only board), scaffold dirs, build the index,
    install the hook.
    """
    raw_target = Path(args.target_dir)
    if not raw_target.is_dir():
        raise ValueError(f"init-agent-workspace: no such directory: {args.target_dir}")
    target_dir = raw_target.resolve()
    prefix = args.prefix or target_dir.name

    hub.cmd_add(argparse.Namespace(name=prefix, prefix=None))
    print(f"init-agent-workspace: bd board ready via hub (prefix: {prefix})")

    scaffold_dirs(target_dir)
    build_index(target_dir)
    install_post_commit_hook(target_dir)

    print(f"init-agent-workspace: done ({target_dir})")
    return 0
