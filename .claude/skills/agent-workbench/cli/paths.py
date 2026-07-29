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
    "git_head",
]

# This module sits at <repo>/.claude/skills/agent-workbench/cli/paths.py, so
# the repo root is four parents up. Resolved once at import.
# Under a symlink install, this resolves to the actual repo root.
# Under a --copy install, this resolves to $HOME, which has no scripts/ or
# docker-compose.yml. That is OK -- resolution is lazy, and only repo_root()
# will raise if needed.
REPO_ROOT: Path | None = None
_attempted = False


def _compute_root() -> Path | None:
    """Compute the repo root by trying parents[4] and checking it looks
    like this repo (has scripts/ and docker-compose.yml).

    Returns the root if found, None if this is likely a copy install.
    Does not raise.
    """
    candidate = Path(__file__).resolve().parents[4]
    looks_like_repo = (
        (candidate / "scripts").is_dir()
        and (candidate / "docker-compose.yml").is_file()
    )
    if looks_like_repo:
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


def git_head(root: Path) -> str | None:
    """Return the current commit SHA of the git repo at `root`, or None.

    Pure stdlib: reads git's on-disk files directly instead of shelling out
    to `git`. Handles a linked worktree's `.git` file (resolving `commondir`
    to find shared `refs/`), a loose ref, and `packed-refs`. Returns None
    rather than raising on anything unexpected -- this is diagnostic
    metadata, not a trust boundary.
    """
    try:
        dot_git = root / ".git"
        if dot_git.is_file():
            line = dot_git.read_text(encoding="utf-8").partition("gitdir:")[2]
            gitdir = Path(line.strip())
            gitdir = gitdir if gitdir.is_absolute() else (root / gitdir).resolve()
        elif dot_git.is_dir():
            gitdir = dot_git
        else:
            return None

        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if len(head) == 40 and all(c in "0123456789abcdef" for c in head):
            return head
        if not head.startswith("ref:"):
            return None
        ref = head.removeprefix("ref:").strip()

        commondir_file = gitdir / "commondir"
        common = gitdir
        if commondir_file.is_file():
            entry = Path(commondir_file.read_text(encoding="utf-8").strip())
            common = entry if entry.is_absolute() else (gitdir / entry).resolve()

        ref_file = common / ref
        if ref_file.is_file():
            return ref_file.read_text(encoding="utf-8").strip()
        packed = common / "packed-refs"
        if packed.is_file():
            for packed_line in packed.read_text(encoding="utf-8").splitlines():
                if packed_line.endswith(f" {ref}"):
                    return packed_line.split()[0]
        return None
    except OSError:
        return None
