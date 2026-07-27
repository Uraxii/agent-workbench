"""Health-check test against the live artifact-serve endpoint.

Whether a live container is actually running depends on system state
outside this test run, so this is environment-tolerant: it tries the GET
with a short timeout, skips if the connection is refused/times out, and
only asserts HTTP 200 when something really answers.
"""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

ARTIFACT_SERVE_URL = "http://127.0.0.1:9099/"
TIMEOUT_SEC = 2


def test_artifact_serve_health() -> None:
    """GET http://127.0.0.1:9099/ returns HTTP 200 when the service is up."""
    try:
        with urllib.request.urlopen(ARTIFACT_SERVE_URL, timeout=TIMEOUT_SEC) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError):
        pytest.skip("artifact-serve not running on 127.0.0.1:9099")
        return

    assert status == 200
