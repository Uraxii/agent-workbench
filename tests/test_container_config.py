"""Regression check for the H2 container env-surface change: neither
Containerfile's ENTRYPOINT bakes a --port flag (only KB_SVC_PORT /
ARTIFACT_SVC_PORT env vars, set by the quadlet, may steer the bound port).
A baked --port would override the env var and silently defeat H2.
"""
from __future__ import annotations

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
