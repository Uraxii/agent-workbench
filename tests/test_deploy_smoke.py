"""Smoke tests for the agent-workbench container stack.

Two kinds of coverage:

- test_kb_serve_health / test_artifact_serve_health: assert the LIVE stack
  answers HTTP 200 when it is already up (via `podman-compose up -d`, the
  one supported deploy path). Skip cleanly whenever the runtime or the
  service itself is not present -- these never start, stop, or otherwise
  mutate either service.
- test_kb_serve_container_boundary / test_artifact_serve_container_boundary:
  ALWAYS run (skip only if podman itself is missing), independent of
  whether the live stack is up. They build the two hardened images under
  distinct test tags on alternate host ports, run them standalone via
  `podman run` (never through the compose stack), curl for health, and
  tear the containers down in a fixture `finally` regardless of pass/fail.
  This is what actually exercises the container boundary in a clean/CI
  environment where the live stack has never been started.
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

ARTIFACT_SERVE_TEST_IMAGE = "localhost/artifact-review:hardened-test"
ARTIFACT_SERVE_TEST_CONTAINER = "artifact-review-hardened-test"
ARTIFACT_SERVE_TEST_PORT = 19099

BUILD_TIMEOUT_SEC = 180
# The artifact-review image builds the React SPA (npm ci + vitest + vite
# build) before the Python stage, so a cold build is minutes, not seconds.
ARTIFACT_BUILD_TIMEOUT_SEC = 900
RUN_TIMEOUT_SEC = 30
HEALTH_POLL_TRIES = 20
HEALTH_POLL_DELAY_SEC = 0.5


def _require_podman() -> None:
    """Skip when no container runtime is present.

    Only podman is checked. The stack is compose-managed, so there is no
    systemd unit to query and nothing here should gate on systemctl.
    """
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
    _require_podman()
    status = _http_status(KB_HEALTH_URL)
    if status is None:
        pytest.skip("kb-serve not reachable at 127.0.0.1:9100 -- stack not up")
    assert status == 200


def test_artifact_serve_health() -> None:
    _require_podman()
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
    """Build + run the hardened artifact-review image standalone, then tear down.

    Isolated from the live stack: distinct image tag, container name, and
    host port. Never touches the real artifact-serve quadlet/systemd unit.
    Builds the `runtime` target only -- the `test` stage on top of it runs
    the backend suite, which belongs to the app's own build, not here.
    """
    _require_podman()
    app_dir = REPO_ROOT / "apps/artifact-review"
    _run(
        [
            "podman", "build", "-t", ARTIFACT_SERVE_TEST_IMAGE,
            "--target", "runtime",
            "-f", str(app_dir / "Containerfile"),
            str(app_dir),
        ],
        timeout=ARTIFACT_BUILD_TIMEOUT_SEC,
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    feedback_root = tmp_path / "feedback"
    feedback_root.mkdir()
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
            "-e", "ARTIFACT_SERVE_ALLOWED_HOSTS=127.0.0.1,localhost",
            "-e", "ARTIFACT_SERVE_STAGE_ROOT=/tmp/artifacts",
            "-e", f"ARTIFACT_SERVE_FEEDBACK_ROOT={feedback_root}",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable",
            "-v", f"{artifacts_root}:/tmp/artifacts:rw",
            "-v", f"{feedback_root}:{feedback_root}:rw",
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


def _path_visible_in_container(container: str, path: Path) -> str:
    """Report whether path exists from inside container, as 'True'/'False'."""
    result = subprocess.run(
        [
            "podman", "exec", container, "python3", "-c",
            f"import pathlib; print(pathlib.Path({str(path)!r}).exists())",
        ],
        capture_output=True, text=True, timeout=RUN_TIMEOUT_SEC, check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"podman exec failed: {result.stderr}")
    return result.stdout.strip()


def test_kb_serve_container_boundary(kb_serve_boundary: None) -> None:
    status = _wait_for_status(f"http://127.0.0.1:{KB_TEST_PORT}/health")
    assert status == 200


def test_artifact_serve_container_boundary(artifact_serve_boundary: None) -> None:
    status = _wait_for_status(
        f"http://127.0.0.1:{ARTIFACT_SERVE_TEST_PORT}/_/health"
    )
    assert status == 200
    # The repo itself is never mounted, so the container must not see it.
    assert _path_visible_in_container(
        ARTIFACT_SERVE_TEST_CONTAINER, REPO_ROOT,
    ) == "False"

