"""Smoke tests for the agent-workbench deploy bundle.

Two kinds of coverage:

- test_kb_serve_health / test_artifact_serve_health: assert the LIVE stack
  answers HTTP 200 when it is already up (via `deploy/agent-workbench/
  agent-workbench up`). Skip cleanly whenever the tooling or the service
  itself is not present -- these never start, stop, or otherwise mutate
  either service.
- test_kb_serve_container_boundary / test_artifact_serve_container_boundary:
  ALWAYS run (skip only if podman itself is missing), independent of
  whether the live stack is up. They build the two hardened images under
  distinct test tags on alternate host ports, run them standalone via
  `podman run` (never via the real quadlets/systemctl), curl for health,
  and tear the containers down in a fixture `finally` regardless of
  pass/fail. This is what actually exercises the container boundary in a
  clean/CI environment where the live stack has never been started.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

KB_HEALTH_URL = "http://127.0.0.1:9100/health"
ARTIFACT_SERVE_URL = "http://127.0.0.1:9099/"
REQUEST_TIMEOUT_SEC = 3

REPO_ROOT = Path(__file__).parent.parent

KB_TEST_IMAGE = "localhost/kb-serve:hardened-test"
KB_TEST_CONTAINER = "kb-serve-hardened-test"
KB_TEST_PORT = 19100

ARTIFACT_SERVE_TEST_IMAGE = "localhost/artifact-serve:hardened-test"
ARTIFACT_SERVE_TEST_CONTAINER = "artifact-serve-hardened-test"
ARTIFACT_SERVE_TEST_PORT = 19099

BUILD_TIMEOUT_SEC = 180
RUN_TIMEOUT_SEC = 30
HEALTH_POLL_TRIES = 20
HEALTH_POLL_DELAY_SEC = 0.5


def _require_tooling() -> None:
    for tool in ("podman", "systemctl"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not available on this host")


def _require_podman() -> None:
    if shutil.which("podman") is None:
        pytest.skip("podman not available on this host")


def _http_status(url: str) -> int | None:
    """Return the HTTP status code for url, or None if unreachable."""
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SEC) as resp:
            return resp.status
    except (urllib.error.URLError, OSError):
        return None


def _wait_for_status(url: str) -> int | None:
    """Poll url until it answers or the poll budget is exhausted."""
    for _ in range(HEALTH_POLL_TRIES):
        status = _http_status(url)
        if status is not None:
            return status
        time.sleep(HEALTH_POLL_DELAY_SEC)
    return None


def _run(cmd: list[str], timeout: float) -> None:
    """Run a podman command, failing the test with stderr on error."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"command failed: {' '.join(cmd)}\n{result.stderr}")


def test_kb_serve_health() -> None:
    _require_tooling()
    status = _http_status(KB_HEALTH_URL)
    if status is None:
        pytest.skip("kb-serve not reachable at 127.0.0.1:9100 -- stack not up")
    assert status == 200


def test_artifact_serve_health() -> None:
    _require_tooling()
    status = _http_status(ARTIFACT_SERVE_URL)
    if status is None:
        pytest.skip("artifact-serve not reachable at 127.0.0.1:9099 -- stack not up")
    assert status == 200


@pytest.fixture()
def kb_serve_boundary(tmp_path: Path):
    """Build + run the hardened kb-serve image standalone, then tear down.

    Isolated from the live stack: distinct image tag, container name, and
    host port. Never touches the real kb-serve quadlet/systemd unit.
    """
    _require_podman()
    _run(
        [
            "podman", "build", "-t", KB_TEST_IMAGE,
            "-f", str(REPO_ROOT / "scripts/kb-container/Containerfile"),
            str(REPO_ROOT / "scripts"),
        ],
        timeout=BUILD_TIMEOUT_SEC,
    )
    kb_home = tmp_path / "kb-home"
    kb_home.mkdir()
    subprocess.run(["podman", "rm", "-f", KB_TEST_CONTAINER], capture_output=True)
    _run(
        [
            "podman", "run", "--rm", "-d", "--name", KB_TEST_CONTAINER,
            "-p", f"{KB_TEST_PORT}:9100",
            "--user", f"{os.getuid()}:{os.getgid()}", "--userns=keep-id",
            "-e", f"KB_HOME={kb_home}", "-e", "KB_SERVE_HOST=0.0.0.0",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable",
            "-v", f"{kb_home}:{kb_home}:rw",
            KB_TEST_IMAGE,
        ],
        timeout=RUN_TIMEOUT_SEC,
    )
    try:
        yield
    finally:
        subprocess.run(["podman", "rm", "-f", KB_TEST_CONTAINER], capture_output=True)


@pytest.fixture()
def artifact_serve_boundary(tmp_path: Path):
    """Build + run the hardened artifact-serve image standalone, then tear down.

    Isolated from the live stack: distinct image tag, container name, and
    host port. Never touches the real artifact-serve quadlet/systemd unit.
    """
    _require_podman()
    _run(
        [
            "podman", "build", "-t", ARTIFACT_SERVE_TEST_IMAGE,
            "-f", str(REPO_ROOT / ".claude/skills/artifact-serve/container/Containerfile"),
            str(REPO_ROOT / ".claude/skills/artifact-serve"),
        ],
        timeout=BUILD_TIMEOUT_SEC,
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    artifacts_root = tmp_path / "claude-artifacts"
    artifacts_root.mkdir()
    subprocess.run(
        ["podman", "rm", "-f", ARTIFACT_SERVE_TEST_CONTAINER], capture_output=True,
    )
    _run(
        [
            "podman", "run", "--rm", "-d", "--name", ARTIFACT_SERVE_TEST_CONTAINER,
            "-p", f"{ARTIFACT_SERVE_TEST_PORT}:9099",
            "--user", f"{os.getuid()}:{os.getgid()}", "--userns=keep-id",
            "-e", f"HOME={fake_home}",
            "-e", "ARTIFACT_SERVE_HOST=0.0.0.0", "-e", "ARTIFACT_SERVE_PORT=9099",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable",
            "-v", f"{artifacts_root}:/tmp/claude-artifacts:rw",
            "-v", f"{fake_home}:{fake_home}:rw",
            ARTIFACT_SERVE_TEST_IMAGE,
        ],
        timeout=RUN_TIMEOUT_SEC,
    )
    try:
        yield
    finally:
        subprocess.run(
            ["podman", "rm", "-f", ARTIFACT_SERVE_TEST_CONTAINER], capture_output=True,
        )


def test_kb_serve_container_boundary(kb_serve_boundary: None) -> None:
    status = _wait_for_status(f"http://127.0.0.1:{KB_TEST_PORT}/health")
    assert status == 200


def test_artifact_serve_container_boundary(artifact_serve_boundary: None) -> None:
    status = _wait_for_status(f"http://127.0.0.1:{ARTIFACT_SERVE_TEST_PORT}/")
    assert status == 200
