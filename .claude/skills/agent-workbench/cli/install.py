"""`install` subcommand -- (un)install this repo's agent-workbench skill
into ``~/.claude/skills/agent-workbench``.

Replaces hand-managed symlinks with a scripted, reversible step:
    --link       symlink ~/.claude/skills/agent-workbench -> this repo's
                 .claude/skills/agent-workbench (replaces any existing
                 symlink there; refuses a real dir or file)
    --copy       same target, but a recursive copy instead of a symlink
                 (__pycache__ excluded); stamps the install with a marker
                 file so --uninstall can safely remove it
    --uninstall  remove ~/.claude/skills/agent-workbench; succeeds on a
                 symlink pointing at this repo's skill dir, or on a real
                 dir stamped by --copy; refuses otherwise to avoid
                 deleting a different install

Flags are mutually exclusive; exactly one is required.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from cli import paths

__all__ = ["register", "install_target"]

# Marker file written by --copy to indicate the install can be safely removed.
INSTALL_MARKER = ".installed-by-agent-workbench"


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
    """Recursively copy ``source`` over ``target`` (__pycache__ excluded).
    
    Stamps the install with INSTALL_MARKER so --uninstall can safely
    remove it later.
    """
    if target.is_symlink():
        target.unlink()
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=_ignore_pycache)
    (target / INSTALL_MARKER).touch()
    print(f"agent-workbench: copied {source} -> {target}")


def _uninstall(target: Path, source: Path) -> bool:
    """Remove ``target`` if it is a symlink pointing at ``source`` or a
    stamped copy install.
    
    Returns: True if uninstall succeeded, False if refused.
    """
    if not target.exists() and not target.is_symlink():
        print(f"agent-workbench: nothing installed at {target}")
        return True
    
    # Case 1: symlink pointing to this repo's skill dir (old installs)
    if target.is_symlink() and target.resolve() == source.resolve():
        target.unlink()
        print(f"agent-workbench: removed symlink {target}")
        return True
    
    # Case 2: real dir stamped by --copy install
    if (
        target.is_dir()
        and not target.is_symlink()
        and (target / INSTALL_MARKER).exists()
    ):
        shutil.rmtree(target)
        print(f"agent-workbench: removed stamped copy install at {target}")
        return True
    
    # Refuse: not ours to delete
    print(
        f"agent-workbench: refusing to remove {target} -- not this repo's "
        "own symlink or stamped copy install (real dir, or points elsewhere)",
    )
    return False


def cmd_install(args: argparse.Namespace) -> int:
    """Dispatch to link/copy/uninstall per the chosen mutually exclusive flag."""
    target, source = install_target(), source_dir()
    if args.link:
        _install_link(target, source)
        return 0
    elif args.copy:
        _install_copy(target, source)
        return 0
    else:  # args.uninstall
        return 0 if _uninstall(target, source) else 1
