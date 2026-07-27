"""`install` subcommand -- (un)install this repo's agent-workbench skill
into ``~/.claude/skills/agent-workbench``.

Replaces hand-managed symlinks with a scripted, reversible step:
    --link       symlink ~/.claude/skills/agent-workbench -> this repo's
                 .claude/skills/agent-workbench (replaces any existing
                 symlink there; refuses a real dir or file)
    --copy       same target, but a recursive copy instead of a symlink
                 (__pycache__ excluded)
    --uninstall  remove ~/.claude/skills/agent-workbench, but only if it
                 is a symlink pointing at this repo's skill dir -- refuses
                 (does nothing) on a real dir or a symlink elsewhere, so a
                 different install is never deleted by accident

Flags are mutually exclusive; exactly one is required.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from cli import paths

__all__ = ["register", "install_target"]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `install` parser with its mutually exclusive flags."""
    parser = subparsers.add_parser(
        "install", help="(un)install this repo's skill into ~/.claude/skills",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--link", action="store_true", help="symlink the skill in")
    group.add_argument("--copy", action="store_true", help="recursively copy the skill in")
    group.add_argument("--uninstall", action="store_true", help="remove a repo-owned install")
    parser.set_defaults(func=cmd_install)


def install_target() -> Path:
    """``~/.claude/skills/agent-workbench``, the fixed install location."""
    return Path.home() / ".claude" / "skills" / "agent-workbench"


def source_dir() -> Path:
    """This repo's own agent-workbench skill dir (the thing being installed)."""
    return paths.REPO_ROOT / ".claude" / "skills" / "agent-workbench"


def _ignore_pycache(_dir: str, names: list[str]) -> set[str]:
    """``shutil.copytree`` ignore hook: skip ``__pycache__`` dirs."""
    return {name for name in names if name == "__pycache__"}


def _install_link(target: Path, source: Path) -> None:
    """Replace ``target`` with a symlink to ``source`` (idempotent)."""
    if target.is_symlink() and target.resolve() == source.resolve():
        print(f"agent-workbench: already linked at {target}")
        return
    if target.is_dir() and not target.is_symlink():
        raise RuntimeError(f"agent-workbench: refusing to replace real dir {target}")
    target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    print(f"agent-workbench: linked {target} -> {source}")


def _install_copy(target: Path, source: Path) -> None:
    """Recursively copy ``source`` over ``target`` (__pycache__ excluded)."""
    if target.is_symlink():
        target.unlink()
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=_ignore_pycache)
    print(f"agent-workbench: copied {source} -> {target}")


def _uninstall(target: Path, source: Path) -> None:
    """Remove ``target`` only if it is a symlink pointing at ``source``."""
    if not target.exists() and not target.is_symlink():
        print(f"agent-workbench: nothing installed at {target}")
        return
    if not (target.is_symlink() and target.resolve() == source.resolve()):
        print(
            f"agent-workbench: refusing to remove {target} -- not this repo's "
            "own symlink (real dir, or points elsewhere)",
        )
        return
    target.unlink()
    print(f"agent-workbench: removed {target}")


def cmd_install(args: argparse.Namespace) -> int:
    """Dispatch to link/copy/uninstall per the chosen mutually exclusive flag."""
    target, source = install_target(), source_dir()
    if args.link:
        _install_link(target, source)
    elif args.copy:
        _install_copy(target, source)
    else:
        _uninstall(target, source)
    return 0
