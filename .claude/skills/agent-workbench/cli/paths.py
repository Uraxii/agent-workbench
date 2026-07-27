"""Repo-root, sibling-artifact and vault path resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Every
ported subcommand needs to locate artifacts elsewhere in the repo: the
`kb` port delegates to ``<repo>/scripts/kb-serve.py`` (and its hyphenated
siblings), and the `artifact` port delegates to
``<repo>/.claude/skills/artifact-serve/scripts/artifact-serve.py``.
Centralizing that math here keeps it out of the individual subcommand
modules.

``resolve_kb_home`` lives here for the same reason: both `cli.kb` and
`cli.kb_decision` need the vault root, and `cli.kb` already imports
`cli.kb_decision` to register its `decision` verb, so a shared home here
is what keeps those two from importing each other in a cycle. `cli.kb`
re-exports it, so ``kb.resolve_kb_home`` still resolves.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "SCRIPTS_DIR",
    "ARTIFACT_SKILL_DIR",
    "repo_root",
    "resolve_kb_home",
]

# This module sits at <repo>/.claude/skills/agent-workbench/cli/paths.py, so
# the repo root is four parents up. Resolved once at import.
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"
ARTIFACT_SKILL_DIR: Path = REPO_ROOT / ".claude" / "skills" / "artifact-serve"


def repo_root() -> Path:
    """Return the resolved repository root.

    Postcondition: the returned path contains a ``scripts/`` directory.
    """
    return REPO_ROOT


def resolve_kb_home(explicit: str | None) -> Path:
    """Resolve KB_HOME: explicit arg, else $KB_HOME, else ~/.knowledgebase.

    Same precedence kb-index.py and kb-clip.py apply, so the CLI and the
    scripts it delegates to can never disagree about which vault they are
    talking about.
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get("KB_HOME")
    return Path(env) if env else Path.home() / ".knowledgebase"
