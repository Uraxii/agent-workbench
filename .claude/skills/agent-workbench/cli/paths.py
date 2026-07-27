"""Repo-root, sibling-artifact and vault path resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Every
ported subcommand needs to locate artifacts elsewhere in the repo: the
`kb` port delegates to ``<repo>/scripts/kb-serve.py`` (and its hyphenated
siblings), and `deploy` builds from the two Containerfiles under
``<repo>/scripts/kb-container/`` and
``<repo>/.claude/skills/artifact-serve/container/``. Centralizing that
math here keeps it out of the individual subcommand modules.

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
    "KB_CONTAINER_DIR",
    "N8N_CONTAINER_DIR",
    "BDUI_CONTAINER_DIR",
    "ARTIFACT_SKILL_DIR",
    "ARTIFACT_CONTAINER_DIR",
    "repo_root",
    "resolve_kb_home",
]

# This module sits at <repo>/.claude/skills/agent-workbench/cli/paths.py, so
# the repo root is four parents up. Resolved once at import.
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
SCRIPTS_DIR: Path = REPO_ROOT / "scripts"
KB_CONTAINER_DIR: Path = SCRIPTS_DIR / "kb-container"
BDUI_CONTAINER_DIR: Path = SCRIPTS_DIR / "bdui-container"
# n8n has no Containerfile of ours (official image, pinned by digest in its
# quadlet). This dir holds only the n8n.container quadlet, n8n-secret.py,
# and n8n.env.example; `deploy` installs the quadlet but never builds here.
N8N_CONTAINER_DIR: Path = SCRIPTS_DIR / "n8n-container"
ARTIFACT_SKILL_DIR: Path = REPO_ROOT / ".claude" / "skills" / "artifact-serve"
ARTIFACT_CONTAINER_DIR: Path = ARTIFACT_SKILL_DIR / "container"


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
