"""Shared loader + fixtures for artifact-serve tests.

artifact-serve.py lives at
.claude/skills/artifact-serve/scripts/artifact-serve.py and (because of the
hyphen in its filename) cannot be imported with a plain `import` statement,
so it is loaded once here via importlib and reused by every artifact-serve
test module. Not a conftest.py: pytest only auto-loads files literally named
conftest.py, so this stays a plain helper module each test file imports
explicitly (kept additive, not touching the shared tests/conftest.py per
artifact-serve task rules).
"""

from __future__ import annotations

import http.server
import importlib.util
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "artifact-serve" / "scripts" / "artifact-serve.py"
)
_MODULE_NAME = "artifact_serve"

if _MODULE_NAME in sys.modules:
    artifact_serve: ModuleType = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"cannot load artifact-serve.py from {_SCRIPT_PATH}")
    artifact_serve = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = artifact_serve
    _spec.loader.exec_module(artifact_serve)


@pytest.fixture()
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every artifact-serve path constant at tmp_path. Never the real DB."""
    root = tmp_path / "artifacts"
    feedback_root = tmp_path / "feedback"
    monkeypatch.setattr(artifact_serve, "ROOT", root)
    monkeypatch.setattr(artifact_serve, "PID_FILE", root / ".serve.pid")
    monkeypatch.setattr(artifact_serve, "PORT_FILE", root / ".serve.port")
    monkeypatch.setattr(artifact_serve, "LOG_FILE", root / ".serve.log")
    monkeypatch.setattr(artifact_serve, "INDEX_FILE", root / "index.html")
    monkeypatch.setattr(artifact_serve, "FEEDBACK_ROOT", feedback_root)
    monkeypatch.setattr(artifact_serve, "FEEDBACK_DB", feedback_root / "feedback.db")
    monkeypatch.setattr(artifact_serve, "UPLOAD_ROOT", feedback_root / "uploads")
    artifact_serve.ensure_root()
    artifact_serve.ensure_feedback_root()
    return root


@pytest.fixture()
def live_server(temp_env: Path) -> Iterator[str]:
    """Boot a real HTTP server on an ephemeral port against temp_env.

    Bypasses cmd_start/cmd_run (fork, pidfile, tailscale) entirely: builds the
    handler class directly and serves it with a plain ThreadingHTTPServer in a
    background thread, so tests never touch the daemon lifecycle (no
    `artifact-serve.py stop`, no pidfile, no tailscale).
    """
    handler_cls = artifact_serve._make_handler()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def push_artifact(src_dir: Path, project: str, subdir: str) -> str:
    """Stage src_dir under (project, subdir) via the real cmd_push. Returns artifact_id."""
    parser = artifact_serve.build_parser()
    args = parser.parse_args(
        ["push", "--project", project, "--src", str(src_dir), "--as", subdir]
    )
    rc = artifact_serve.cmd_push(args)
    assert rc == artifact_serve.EXIT_OK
    return f"{project}/{subdir}"


def multipart_body(fields: dict[str, str]) -> tuple[bytes, str]:
    """Build a multipart/form-data body carrying only text fields."""
    boundary = "----artifactservetestboundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def multipart_with_file(
    fields: dict[str, str], filename: str, content: bytes, file_field: str = "upload"
) -> tuple[bytes, str]:
    """Build a multipart/form-data body carrying text fields plus one file part."""
    boundary = "----artifactservetestboundaryfile"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        .encode("utf-8")
    )
    parts.append(content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def http_request(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> tuple[int, bytes, dict[str, str]]:
    """Issue a real HTTP request; returns (status, body, response_headers).

    Never raises on 4xx/5xx: urllib's HTTPError is caught and its status/body
    surfaced the same as a success response, so callers can assert on error
    paths without a try/except at every call site.
    """
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), _lower_keys(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), _lower_keys(exc.headers)


def _lower_keys(headers: object) -> dict[str, str]:
    """Lowercase header names: stdlib's own send_head() sends 'Content-type'
    (lowercase t) while artifact-serve's own handlers send 'Content-Type', so
    callers should never have to guess the casing."""
    return {str(k).lower(): str(v) for k, v in headers.items()}  # type: ignore[attr-defined]
