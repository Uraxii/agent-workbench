"""Repo-root and sibling-artifact path resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Every
ported subcommand needs to locate artifacts elsewhere in the repo: the
`kb` port delegates to ``<repo>/scripts/kb-serve.py`` (and its hyphenated
siblings), and `deploy` builds from the two Containerfiles under
``<repo>/scripts/kb-container/`` and
``<repo>/.claude/skills/artifact-serve/container/``. Centralizing that
math here keeps it out of the individual subcommand modules.
"""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "SCRIPTS_DIR",
    "KB_CONTAINER_DIR",
    "N8N_CONTAINER_DIR",
    "BDUI_CONTAINER_DIR",
    "REVIEW_SKILL_DIR",
    "REVIEW_CONTAINER_DIR",
    "repo_root",
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
REVIEW_SKILL_DIR: Path = REPO_ROOT / ".claude" / "skills" / "artifact-serve"
REVIEW_CONTAINER_DIR: Path = REVIEW_SKILL_DIR / "container"


def repo_root() -> Path:
    """Return the resolved repository root.

    Postcondition: the returned path contains a ``scripts/`` directory.
    """
    return REPO_ROOT
