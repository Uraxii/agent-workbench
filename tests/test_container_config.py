"""Regression check for the H2 container env-surface change: neither
Containerfile's ENTRYPOINT bakes a --port flag (only KB_SVC_PORT /
ARTIFACT_SVC_PORT env vars, set by the quadlet, may steer the bound port).
A baked --port would override the env var and silently defeat H2.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_CONTAINERFILES = [
    _REPO_ROOT / "scripts" / "kb-container" / "Containerfile",
    _REPO_ROOT / "apps" / "artifact-review" / "Containerfile",
]


@pytest.mark.parametrize("containerfile", _CONTAINERFILES, ids=lambda p: p.parent.name)
def test_entrypoint_line_never_bakes_a_port_flag(containerfile: Path) -> None:
    lines = containerfile.read_text(encoding="utf-8").splitlines()
    [entrypoint_line] = [line for line in lines if line.startswith("ENTRYPOINT")]
    assert "--port" not in entrypoint_line


# The author's own machine, never a real prerequisite -- a path that only
# breaks on someone else's install. Excluded directories, and why:
#   spikes/ -- owned by a concurrent agent's in-flight work.
#   vault/  -- historical decision records; their frontmatter carries the
#              recording author's path by design and must stay untouched.
# Built by concatenation, not one literal, so this very check does not
# trip on its own source when git-tracked.
_AUTHOR_NAME = "nic" + "ole"
_AUTHOR_HOME_MARKERS = (
    f"/home/{_AUTHOR_NAME}",
    f"/var/home/{_AUTHOR_NAME}",
    "~" + "/Projects/agent-workbench",
)
_EXCLUDED_DIR_PREFIXES = ("spikes/", "vault/")


def _tracked_files() -> list[Path]:
    """Every git-tracked file (not a filesystem walk, so untracked scratch
    files -- including this test's own before/after proof edits -- never
    trip the check)."""
    result = subprocess.run(
        ["git", "ls-files"], cwd=_REPO_ROOT, capture_output=True,
        check=True, text=True,
    )
    return [_REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_no_tracked_file_hardcodes_the_author_home() -> None:
    """A path baked in that only breaks on someone else's machine -- the
    bug this whole workstream exists to kill."""
    offenders: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(_EXCLUDED_DIR_PREFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary file, not a path source
        except FileNotFoundError:
            continue  # a git-tracked symlink target absent on this host
        if any(marker in text for marker in _AUTHOR_HOME_MARKERS):
            offenders.append(rel)

    assert not offenders, (
        "tracked file(s) hardcode the author's home, breaking a fresh "
        f"install on any other machine: {offenders}"
    )
