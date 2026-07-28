"""Repo-root resolution for the CLI.

The skill lives at ``<repo>/.claude/skills/agent-workbench/``. Some
subcommands need to locate files elsewhere in the repo (e.g., install.py
needs to find the source dir to copy/link from). This module centralizes
repo-root calculation.

For copy-installed skills, REPO_ROOT resolution may be unavailable, and
that is OK -- the CLI is a pure HTTP client of kb-svc / bd-svc / 
artifact-svc and does not need a repo root on normal paths. Only install
and board maintenance subcommands need it; they fail at call time if
unavailable.

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
# Under a symlink install, this resolves to the actual repo root.
# Under a --copy install, this resolves to ~/.claude, which has no scripts/.
# That is OK -- resolution is lazy, and only repo_root() will raise if needed.
REPO_ROOT: Path | None = None
_attempted = False


def _compute_root() -> Path | None:
    """Compute the repo root by trying parents[4] and checking for scripts/.
    
    Returns the root if found, None if this is likely a copy install.
    Does not raise.
    """
    candidate = Path(__file__).resolve().parents[4]
    if (candidate / "scripts").is_dir():
        return candidate
    # Copy install or misc misconfiguration -- return None, let caller decide
    return None


def repo_root() -> Path:
    """Return the resolved repository root.
    
    Raises RuntimeError if the root cannot be found (e.g., on a copy
    install or misconfigured installation).
    
    Postcondition (on success): the returned path contains a ``scripts/``
    directory.
    """
    global REPO_ROOT, _attempted
    if REPO_ROOT is not None:
        return REPO_ROOT
    if _attempted:
        raise RuntimeError(
            "agent-workbench: repository root not found. This may indicate "
            "a misconfigured or corrupted installation. Copy-installed skills "
            "require access to the original repository to use install verbs."
        )
    _attempted = True
    REPO_ROOT = _compute_root()
    if REPO_ROOT is None:
        raise RuntimeError(
            "agent-workbench: repository root not found. This may indicate "
            "a misconfigured or corrupted installation. Copy-installed skills "
            "require access to the original repository to use install verbs."
        )
    return REPO_ROOT
