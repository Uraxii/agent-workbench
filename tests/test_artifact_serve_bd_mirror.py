"""Tests for artifact-serve's bd-mirror board resolution (_bd_beads_dir).

Covers the agent-workbench-CLI-backed `hub path` lookup that replaced the
deleted scripts/beads-hub.sh, and its degrade-to-None contract when the CLI
is unavailable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifact_serve_support import push_artifact, artifact_serve, temp_env  # noqa: E402,F401


def test_bd_beads_dir_resolves_via_agent_workbench_hub(
    temp_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: real agent-workbench CLI, real `hub path` subprocess call."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hello", encoding="utf-8")
    artifact_id = push_artifact(src_dir, "bd-mirror-proj", "art-a")

    hub_root = tmp_path / "hub"
    project_beads = hub_root / "bd-mirror-proj" / ".beads"
    (project_beads / "embeddeddolt").mkdir(parents=True)
    monkeypatch.setenv("BEADS_HUB_DIR", str(hub_root))

    assert artifact_serve._bd_beads_dir(artifact_id) == str(project_beads)


def test_bd_beads_dir_none_when_cli_missing(
    temp_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same degrade-to-None contract as the deleted beads-hub.sh: a missing
    CLI file must never raise, just return None."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hello", encoding="utf-8")
    artifact_id = push_artifact(src_dir, "bd-mirror-proj2", "art-a")

    monkeypatch.setattr(
        artifact_serve, "AGENT_WORKBENCH_CLI", tmp_path / "no-such-cli"
    )

    assert artifact_serve._bd_beads_dir(artifact_id) is None
