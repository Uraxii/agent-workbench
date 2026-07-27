"""Tests for the HTTP-backed `agent-workbench artifact` CLI."""
from __future__ import annotations

import io
import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tarfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "agent-workbench"
ARTIFACT_MODULE = REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "cli" / "artifact.py"


@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str


class RecordingArtifactHandler(BaseHTTPRequestHandler):
    """Small artifact API fake that records publish requests."""

    publishes: list[dict[str, object]] = []
    error_mode: str | None = None

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/_/health":
            self._send_json(200, {"status": "ok"}, csrf_cookie=True)
        elif self.path == "/_/api/artifacts":
            self._send_json(200, {"artifacts": [{"artifact_id": "proj/item"}]})
        elif self.path == "/_/api/threads?artifact=proj%2Fitem":
            self._send_json(200, {"threads": [{"id": 1}]})
        else:
            self._send_json(404, {"reason": "missing"})

    def do_POST(self) -> None:
        if self.error_mode == "json_error":
            self._send_json(503, {"reason": "publish unavailable"})
            return
        if self.error_mode == "not_json":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"not-json")
            return
        self._record_publish()
        self._send_json(201, {"artifact_id": "proj/item", "url": "/proj/item/"})

    def _record_publish(self) -> None:
        length = int(self.headers["Content-Length"])
        content_type = self.headers["Content-Type"]
        raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n"
        message = BytesParser(policy=default).parsebytes(raw + self.rfile.read(length))
        fields: dict[str, object] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                fields[str(name)] = part.get_payload(decode=True)
            else:
                fields[str(name)] = part.get_content()
        self.publishes.append({
            "path": self.path,
            "project": fields.get("project"),
            "as": fields.get("as"),
            "artifact_id": fields.get("artifact_id"),
            "archive": fields["archive"],
            "csrf": self.headers.get("X-CSRFToken"),
            "cookie": self.headers.get("Cookie"),
        })

    def _send_json(self, status: int, payload: dict[str, object], csrf_cookie: bool = False) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if csrf_cookie:
            self.send_header("Set-Cookie", "csrftoken=server-csrf-token; Path=/")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def artifact_server() -> Iterator[tuple[str, type[RecordingArtifactHandler]]]:
    RecordingArtifactHandler.publishes = []
    RecordingArtifactHandler.error_mode = None
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingArtifactHandler)
    except PermissionError:
        yield "mock://artifact", RecordingArtifactHandler
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", RecordingArtifactHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_cli(*args: str, base_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ARTIFACT_SERVE_URL"] = base_url
    return subprocess.run(
        [sys.executable, str(EXECUTABLE), "artifact", *args],
        capture_output=True, text=True, check=False, env=env,
    )


def load_artifact_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("artifact_cli_under_test", ARTIFACT_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeCsrfOpener:
    def __init__(self, handler: type[RecordingArtifactHandler]) -> None:
        self.handler = handler

    def open(self, request: Request, timeout: int) -> FakeResponse:
        request.add_unredirected_header("Cookie", "csrftoken=mock-csrf-token")
        return fake_urlopen(self.handler)(request, timeout)


def run_publish(
    args: list[str],
    base_url: str,
    handler: type[RecordingArtifactHandler],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CliResult:
    if base_url != "mock://artifact":
        return run_cli(*args, base_url=base_url)
    module = load_artifact_module()
    monkeypatch.setenv("ARTIFACT_SERVE_URL", base_url)
    monkeypatch.setattr(module, "urlopen", fake_urlopen(handler))
    monkeypatch.setattr(module, "_csrf_opener", lambda base, post: (FakeCsrfOpener(handler), "mock-csrf-token"))
    namespace = argparse.Namespace(project=args[2], src=args[4], as_name=None, artifact_id=None)
    if "--as" in args:
        namespace.as_name = args[args.index("--as") + 1]
    if "--id" in args:
        namespace.artifact_id = args[args.index("--id") + 1]
    returncode = module.cmd_publish(namespace)
    captured = capsys.readouterr()
    return CliResult(returncode, captured.out, captured.err)


def fake_urlopen(handler: type[RecordingArtifactHandler]):
    def _fake_urlopen(request: Request, timeout: int) -> FakeResponse:
        assert timeout > 0
        assert request.full_url == "mock://artifact/_/api/publish"
        if handler.error_mode == "json_error":
            raise HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                {},
                io.BytesIO(b'{"reason": "publish unavailable"}'),
            )
        if handler.error_mode == "not_json":
            return FakeResponse(b"not-json")
        header_items = dict(request.header_items())
        content_type = header_items["Content-type"]
        raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n"
        message = BytesParser(policy=default).parsebytes(raw + bytes(request.data))
        fields: dict[str, object] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            fields[str(name)] = part.get_payload(decode=True) if part.get_filename() else part.get_content()
        handler.publishes.append({
            "path": "/_/api/publish",
            "project": fields.get("project"),
            "as": fields.get("as"),
            "artifact_id": fields.get("artifact_id"),
            "archive": fields["archive"],
            "csrf": header_items.get("X-csrftoken"),
            "cookie": header_items.get("Cookie"),
        })
        return FakeResponse(json.dumps({"artifact_id": "proj/item", "url": "/proj/item/"}).encode())
    return _fake_urlopen


def read_tar_names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            assert member.isfile() or member.isdir()
            assert member.uid == 0
            assert member.gid == 0
            assert member.uname == ""
            assert member.gname == ""
            assert not member.issym()
            assert not member.name.startswith("/")
            assert ".." not in Path(member.name).parts
        return [member.name for member in archive.getmembers()]


def closed_port_url() -> str:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{sock.getsockname()[1]}"
    except PermissionError:
        return "http://127.0.0.1:9"


def test_publish_single_file_builds_safe_regular_tar(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    source = tmp_path / "page.html"
    source.write_text("<h1>ok</h1>", encoding="utf-8")

    result = run_publish(["publish", "--project", "proj", "--src", str(source)], base_url, handler, monkeypatch, capsys)

    assert result.returncode == 0
    assert json.loads(result.stdout)["artifact_id"] == "proj/item"
    assert handler.publishes[0]["path"] == "/_/api/publish"
    assert read_tar_names(bytes(handler.publishes[0]["archive"])) == ["page.html"]


def test_publish_directory_tree_skips_symlink_and_unsafe_paths(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    source = tmp_path / "dist"
    (source / "nested").mkdir(parents=True)
    (source / "index.html").write_text("index", encoding="utf-8")
    (source / "nested" / "app.js").write_text("js", encoding="utf-8")
    (source / "link").symlink_to(tmp_path / "outside.txt")

    result = run_publish(
        ["publish", "--project", "proj", "--src", str(source), "--as", "site", "--id", "proj/site"],
        base_url, handler, monkeypatch, capsys,
    )

    assert result.returncode == 0
    assert handler.publishes[0]["as"] == "site"
    assert handler.publishes[0]["artifact_id"] == "proj/site"
    assert read_tar_names(bytes(handler.publishes[0]["archive"])) == ["index.html", "nested", "nested/app.js"]


def test_publish_posts_to_url_without_local_artifact_writes(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    source = tmp_path / "out"
    source.mkdir()
    (source / "file.txt").write_text("body", encoding="utf-8")
    tmp_artifacts = tmp_path / "artifacts"
    home_artifacts = tmp_path / "home" / ".local" / "share" / "artifacts"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    result = run_publish(["publish", "--project", "proj", "--src", str(source)], base_url, handler, monkeypatch, capsys)

    assert result.returncode == 0
    assert handler.publishes[0]["path"] == "/_/api/publish"
    assert not tmp_artifacts.exists()
    assert not home_artifacts.exists()


def test_publish_sends_csrf_header_and_cookie(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    source = tmp_path / "file.txt"
    source.write_text("body", encoding="utf-8")

    result = run_publish(["publish", "--project", "proj", "--src", str(source)], base_url, handler, monkeypatch, capsys)

    expected_token = "mock-csrf-token" if base_url == "mock://artifact" else "server-csrf-token"
    assert result.returncode == 0
    assert handler.publishes[0]["csrf"] == expected_token
    assert f"csrftoken={expected_token}" in str(handler.publishes[0]["cookie"])


@pytest.mark.parametrize("verb,args", [
    ("publish", ["publish", "--project", "proj", "--src"]),
    ("feedback", ["feedback", "--artifact", "proj/item"]),
    ("status", ["status"]),
])
def test_dead_port_failures_name_url_and_os_error(verb: str, args: list[str], tmp_path: Path) -> None:
    base_url = closed_port_url()
    if verb == "publish":
        source = tmp_path / "file.txt"
        source.write_text("body", encoding="utf-8")
        args = [*args, str(source)]

    result = run_cli(*args, base_url=base_url)

    assert result.returncode != 0
    assert base_url in result.stderr
    assert "Connection refused" in result.stderr or "Operation not permitted" in result.stderr


def test_status_flattens_artifact_list(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = load_artifact_module()

    def fake_json_request(url: str) -> object:
        if url.endswith("/_/health"):
            return {"status": "ok"}
        if url.endswith("/_/api/artifacts"):
            return {"artifacts": [{"artifact_id": "proj/item"}]}
        raise AssertionError(url)

    monkeypatch.setenv("ARTIFACT_SERVE_URL", "http://artifact.test")
    monkeypatch.setattr(module, "_json_request", fake_json_request)

    result = module.cmd_status(argparse.Namespace())

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "artifacts": [{"artifact_id": "proj/item"}],
        "endpoint": "http://artifact.test",
        "health": {"status": "ok"},
    }


def test_non_2xx_json_error_surfaces_reason(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    handler.error_mode = "json_error"
    source = tmp_path / "file.txt"
    source.write_text("body", encoding="utf-8")

    result = run_publish(["publish", "--project", "proj", "--src", str(source)], base_url, handler, monkeypatch, capsys)

    assert result.returncode != 0
    assert "publish unavailable" in result.stderr


def test_non_json_response_fails_loudly(
    artifact_server: tuple[str, type[RecordingArtifactHandler]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, handler = artifact_server
    handler.error_mode = "not_json"
    source = tmp_path / "file.txt"
    source.write_text("body", encoding="utf-8")

    result = run_publish(["publish", "--project", "proj", "--src", str(source)], base_url, handler, monkeypatch, capsys)

    assert result.returncode != 0
    assert "invalid JSON response" in result.stderr
