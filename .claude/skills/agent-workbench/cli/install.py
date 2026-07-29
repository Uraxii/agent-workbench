"""`install` subcommand -- (un)install this repo's agent-workbench skill
into ``~/.claude/skills/agent-workbench``.

Replaces hand-managed symlinks with a scripted, reversible step:
    --link       symlink ~/.claude/skills/agent-workbench -> this repo's
                 .claude/skills/agent-workbench (replaces any existing
                 symlink there; refuses a real dir or file)
    --copy       same target, but a recursive copy instead of a symlink
                 (__pycache__ excluded); stamps the install with a marker
                 file so --uninstall can safely remove it. A reinstall over
                 a prior marked copy produces exactly the source tree (no
                 stale orphans); refuses on a real dir with no marker
    --uninstall  remove ~/.claude/skills/agent-workbench; succeeds on a
                 symlink pointing at this repo's skill dir, or on a real
                 dir stamped by --copy; refuses otherwise to avoid
                 deleting a different install

Flags are mutually exclusive; exactly one is required.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from cli import paths

__all__ = ["register", "install_target", "read_marker"]

# Marker file written by --copy to indicate the install can be safely
# removed. Holds a small JSON object: {"commit", "source", "installed_at"}.
# A pre-existing empty marker (the old touch()-only format) is still valid:
# see read_marker().
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
    """This repo's own agent-workbench skill dir (the thing being installed).
    
    Raises RuntimeError if the repo root cannot be found.
    """
    return paths.repo_root() / ".claude" / "skills" / "agent-workbench"


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


def _write_marker(target: Path, source: Path) -> None:
    """Write INSTALL_MARKER: the source commit (if resolvable), the
    absolute source dir, and an ISO 8601 UTC install timestamp."""
    try:
        commit = paths.git_head(paths.repo_root())
    except RuntimeError:
        commit = None
    marker = {
        "commit": commit,
        "source": str(source.resolve()),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    (target / INSTALL_MARKER).write_text(json.dumps(marker), encoding="utf-8")


def read_marker(target: Path) -> dict[str, object] | None:
    """Parse ``target``'s INSTALL_MARKER, or None if it is absent.

    An empty or corrupt marker (including the pre-JSON, empty-``touch()``
    format this file used to be) parses as ``{}`` -- present, but no
    recorded commit -- never a crash and never "absent".
    """
    marker_path = target / INSTALL_MARKER
    if not marker_path.is_file():
        return None
    text = marker_path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _install_copy(target: Path, source: Path) -> int:
    """Recursively copy ``source`` over ``target`` (__pycache__ excluded),
    producing exactly the source tree -- a reinstall leaves no orphan file
    that the source no longer has.

    Builds the fresh copy in a sibling temp dir and swaps it in rather than
    clearing ``target`` first: a copy that fails partway (disk full,
    permission, interrupt) leaves the previous install intact instead of a
    half-deleted target, for a handful of extra lines.

    Refuses -- and leaves ``target`` untouched -- if ``target`` exists but
    is neither this repo's own symlink nor a real dir carrying
    INSTALL_MARKER (a foreign real dir, or a plain file): not ours to
    clear.

    Stamps the fresh install with INSTALL_MARKER so --uninstall (and the
    next --copy) can recognize it as ours.

    The temp dir is always removed on the way out, success or failure --
    ``~/.claude/skills/`` is exactly the directory Claude Code enumerates
    for skills, so a surviving ``*.tmp-<pid>`` there (it carries a valid
    marker once ``_write_marker`` has run) would register as a second,
    permanently stale copy of the skill.

    Returns 0 on success, 1 if refused.
    """
    if target.is_symlink():
        target.unlink()
    elif target.exists() and not target.is_dir():
        print(
            f"agent-workbench: refusing to overwrite {target} -- not a "
            "directory, not this repo's own copy install. Move it aside "
            "yourself, then re-run install --copy.",
        )
        return 1
    elif target.is_dir() and read_marker(target) is None:
        print(
            f"agent-workbench: refusing to overwrite {target} -- real dir "
            "with no install marker, not this repo's own copy install. "
            "Move it aside yourself, then re-run install --copy.",
        )
        return 1

    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        shutil.copytree(source, tmp, ignore=_ignore_pycache)
        _write_marker(tmp, source)
        if target.exists():
            shutil.rmtree(target)
        tmp.replace(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"agent-workbench: copied {source} -> {target}")
    return 0


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
    """Dispatch to link/copy/uninstall per the chosen mutually exclusive flag.
    
    Returns 0 on success, 1 on failure.
    """
    target = install_target()
    
    if args.link:
        try:
            source = source_dir()
        except RuntimeError as e:
            print(f"agent-workbench: {e}")
            return 1
        _install_link(target, source)
        return 0
    
    elif args.copy:
        try:
            source = source_dir()
        except RuntimeError as e:
            print(f"agent-workbench: {e}")
            return 1
        return _install_copy(target, source)
    
    else:  # args.uninstall
        try:
            source = source_dir()
        except RuntimeError:
            # For uninstall, if we can't find the repo root, use a dummy source
            # so we can still check if target is a stamped copy install
            source = Path("/nonexistent/repo")
        
        return 0 if _uninstall(target, source) else 1
