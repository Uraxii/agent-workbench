"""Repo-root resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Some
subcommands need to locate files elsewhere in the repo. This module
centralizes repo-root calculation, which is needed by install.py to
find the source directory being installed.

The vault root deliberately does NOT live here. The knowledgebase
service resolves ``$KB_HOME`` itself and is the only thing that opens it;
`cli.kb` is an HTTP client that never needs a vault path.
"""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "repo_root",
]

# This module sits at <repo>/.claude/skills/agent-workbench/cli/paths.py, so
# the repo root is four parents up. Resolved once at import.
# Validation: REPO_ROOT must contain a scripts/ directory. Under a `--copy`
# install, Path.__file__.resolve() follows the real path (not symlinks), so
# this catches misconfigured installs early.
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
if not (REPO_ROOT / "scripts").is_dir():
    raise RuntimeError(
        f"agent-workbench: REPO_ROOT {REPO_ROOT} does not contain scripts/ "
        f"(install may be misconfigured, or this skill is not from "
        f"agent-workbench repo)"
    )


def repo_root() -> Path:
    """Return the resolved repository root."""
    return REPO_ROOT
