"""Repo-root, sibling-script and vault path resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Some
subcommands need to locate files elsewhere in the repo, e.g.
`init-workspace` runs scripts out of ``<repo>/scripts/``. Centralizing
that math here keeps it out of the individual subcommand modules.

The vault root deliberately does NOT live here. The knowledgebase
service resolves ``$KB_HOME`` itself and is the only thing that opens it;
`cli.kb` is an HTTP client that never needs a vault path.
"""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "SCRIPTS_DIR",
    "repo_root",
]

# This module sits at <repo>/.claude/skills/agent-workbench/cli/paths.py, so
# the repo root is four parents up. Resolved once at import.
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"


def repo_root() -> Path:
    """Return the resolved repository root.

    Postcondition: the returned path contains a ``scripts/`` directory.
    """
    return REPO_ROOT
