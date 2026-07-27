from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bd-serve.py"


def _load_bd_serve():
    spec = importlib.util.spec_from_file_location("bd_serve_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bd_serve = _load_bd_serve()


@pytest.fixture
def fake_bd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    argv_path = tmp_path / "argv.jsonl"
    script = tmp_path / "bd"
    script.write_text(
        """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_BD_ARGV"]
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "beads_dir": os.environ.get("BEADS_DIR"),
    }) + "\\n")
if os.environ.get("FAKE_BD_FAIL"):
    print(os.environ.get("FAKE_BD_FAIL"), file=sys.stderr)
    raise SystemExit(7)
if sys.argv[1:] == ["repo", "list"]:
    print(os.environ.get("FAKE_BD_REPOS", ""))
elif len(sys.argv) > 2 and sys.argv[1] == "--json":
    print(json.dumps({"argv": sys.argv[2:]}))
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_BD_ARGV", str(argv_path))
    return argv_path


@pytest.fixture
def service_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_bd: Path,
) -> tuple[Path, Path]:
    hub = tmp_path / "hub"
    monkeypatch.setenv("BEADS_HUB_DIR", str(hub))
    return hub, fake_bd


def _post(path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    return bd_serve.dispatch_post(path, payload)


def _calls(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for call in calls:
        call["argv"][0] = Path(str(call["argv"][0])).name
    return calls


def _init_board(hub: Path, name: str = "hub") -> None:
    (hub / name / ".beads" / "embeddeddolt").mkdir(parents=True)


@pytest.mark.parametrize(
    ("endpoint", "payload", "argv", "board"),
    [
        ("/issue/list", {"status": "open", "assignee": "me", "labels": ["a", "b"],
                         "limit": 3, "all": True}, ["list", "--status", "open",
                         "--assignee", "me", "--label", "a", "--label", "b",
                         "--limit", "3", "--all"], "hub"),
        ("/issue/show", {"id": "ABC-1"}, ["show", "ABC-1"], "hub"),
        ("/issue/create", {"board": "proj", "title": "T", "description": "D",
                           "priority": 2, "labels": ["a", "b"], "parent": "P1",
                           "assignee": "me"}, ["create", "T", "-d", "D", "-p", "2",
                           "--labels", "a,b", "--parent", "P1", "-a", "me"], "proj"),
        ("/issue/update", {"id": "A1", "status": "blocked", "assignee": "me",
                           "priority": "4", "description": "D", "add_labels": ["x"],
                           "remove_labels": ["y"], "claim": True}, ["update", "A1",
                           "--status", "blocked", "-a", "me", "-p", "4", "-d", "D",
                           "--add-label", "x", "--remove-label", "y", "--claim"], "hub"),
        ("/issue/close", {"id": "A1", "reason": "done"}, ["close", "A1",
                           "--reason", "done"], "hub"),
        ("/issue/note", {"id": "A1", "text": "hello"}, ["note", "A1", "hello"], "hub"),
        ("/issue/link", {"from_id": "A1", "to_id": "B2", "type": "blocks"},
         ["link", "A1", "B2", "--type", "blocks"], "hub"),
        ("/issue/children", {"id": "A1"}, ["children", "A1"], "hub"),
        ("/issue/priority", {"id": "A1", "priority": 0}, ["priority", "A1", "0"], "hub"),
    ],
)
def test_issue_endpoints_build_expected_argv(
    service_env: tuple[Path, Path],
    endpoint: str,
    payload: dict[str, object],
    argv: list[str],
    board: str,
) -> None:
    hub, argv_path = service_env
    _init_board(hub, board)
    status, _ = _post(endpoint, payload)
    assert status == 200
    call = _calls(argv_path)[-1]
    assert call["argv"] == ["bd", "--json", *argv]
    assert call["beads_dir"] == str(hub / board / ".beads")


def test_hub_endpoints_build_expected_argv(service_env: tuple[Path, Path]) -> None:
    hub, argv_path = service_env

    assert _post("/hub/init", {})[0] == 200
    assert _calls(argv_path)[-1]["argv"] == [
        "bd", "init", "--non-interactive", "--skip-agents", "--skip-hooks",
        "--stealth", "--prefix", "hub",
    ]
    assert _calls(argv_path)[-1]["beads_dir"] is None

    argv_path.unlink()
    assert _post("/hub/add", {"name": "proj", "prefix": "p"})[0] == 200
    calls = _calls(argv_path)
    assert calls[-2]["argv"] == ["bd", "repo", "list"]
    assert calls[-1]["argv"] == ["bd", "repo", "add", str(hub / "proj")]
    assert calls[-1]["beads_dir"] == str(hub / "hub" / ".beads")

    argv_path.unlink()
    _init_board(hub)
    assert _post("/hub/sync", {})[0] == 200
    assert _calls(argv_path)[-1]["argv"] == ["bd", "repo", "sync"]

    argv_path.unlink()
    assert _post("/hub/repos", {})[0] == 200
    assert _calls(argv_path)[-1]["argv"] == ["bd", "repo", "list"]

    assert _post("/hub/path", {"name": "hub"})[0] == 200

    argv_path.unlink()
    assert _post("/hub/status", {})[0] == 200
    assert _calls(argv_path)[-1]["argv"] == ["bd", "repo", "list"]


@pytest.mark.parametrize(
    "bad",
    ["--force", "-rf", "--db=/etc/passwd", "../../../etc/passwd", "a; rm -rf /",
     "$(whoami)", "`whoami`", "a b", "a\x00b", "a" * 200, ""],
)
def test_hostile_issue_ids_rejected_without_subprocess(
    service_env: tuple[Path, Path], bad: str,
) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    status, _ = _post("/issue/show", {"id": bad})
    assert status == 400
    assert not argv_path.exists()


@pytest.mark.parametrize(
    "bad",
    ["--force", "-rf", "--db=/etc/passwd", "../../../etc/passwd", "a; rm -rf /",
     "$(whoami)", "`whoami`", "a b", "a\x00b", "a" * 200, ""],
)
def test_hostile_board_names_rejected_without_subprocess(
    service_env: tuple[Path, Path], bad: str,
) -> None:
    _hub, argv_path = service_env
    status, _ = _post("/issue/show", {"board": bad, "id": "A1"})
    assert status == 400
    assert not argv_path.exists()


def test_shell_metacharacters_in_text_arrive_as_one_argument(
    service_env: tuple[Path, Path],
) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    text = "title with ; && spaces and 'quotes' \"here\""
    status, _ = _post("/issue/create", {"title": text, "description": text})
    assert status == 200
    assert _calls(argv_path)[-1]["argv"] == ["bd", "--json", "create", text, "-d", text]


def test_title_starting_with_dash_rejected(service_env: tuple[Path, Path]) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    status, _ = _post("/issue/create", {"title": "-bad"})
    assert status == 400
    assert not argv_path.exists()


@pytest.mark.parametrize("priority", [5, -1, "high", "2; rm -rf /"])
def test_bad_priorities_rejected(
    service_env: tuple[Path, Path], priority: object,
) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    status, _ = _post("/issue/priority", {"id": "A1", "priority": priority})
    assert status == 400
    assert not argv_path.exists()


@pytest.mark.parametrize("priority", [0, 1, 2, 3, 4])
def test_good_priorities_accepted(
    service_env: tuple[Path, Path], priority: int,
) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    status, _ = _post("/issue/priority", {"id": "A1", "priority": priority})
    assert status == 200
    assert _calls(argv_path)[-1]["argv"][-1] == str(priority)


def test_unknown_link_type_and_status_rejected(service_env: tuple[Path, Path]) -> None:
    hub, argv_path = service_env
    _init_board(hub)
    assert _post("/issue/link", {"from_id": "A1", "to_id": "B2", "type": "bad"})[0] == 400
    assert _post("/issue/list", {"status": "bad"})[0] == 400
    assert not argv_path.exists()


def test_bd_nonzero_surfaces_stderr(
    service_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub, _argv_path = service_env
    _init_board(hub)
    monkeypatch.setenv("FAKE_BD_FAIL", "nope")
    status, body = _post("/issue/show", {"id": "A1"})
    assert status == 502
    assert body["returncode"] == 7
    assert body["stderr"].strip() == "nope"


def test_no_shell_true_or_os_system() -> None:
    text = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert "os.system" not in text


@pytest.fixture
def live_service(service_env: tuple[Path, Path]) -> Iterator[tuple[str, Path, Path]]:
    """A real bd-serve HTTP server on an ephemeral loopback port."""
    hub, argv_path = service_env
    server = ThreadingHTTPServer(("127.0.0.1", 0), bd_serve.BdRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", hub, argv_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _http_post(base_url: str, path: str, payload: object) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_live_health_reports_hub_root(live_service: tuple[str, Path, Path]) -> None:
    base_url, hub, _argv_path = live_service
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
        body = json.loads(response.read())
    assert response.status == 200
    assert body == {"status": "ok", "hub_root": str(hub), "initialized": False}


def test_live_every_response_carries_the_security_header_baseline(
    live_service: tuple[str, Path, Path],
) -> None:
    base_url, _hub, _argv_path = live_service
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as response:
        headers = dict(response.headers)
    for name, value in bd_serve.SECURITY_HEADERS.items():
        assert headers[name] == value
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_live_error_response_also_carries_the_security_headers(
    live_service: tuple[str, Path, Path],
) -> None:
    base_url, _hub, _argv_path = live_service
    try:
        urllib.request.urlopen(f"{base_url}/no-such-route", timeout=10)
        raise AssertionError("expected HTTP 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        assert exc.headers["X-Content-Type-Options"] == "nosniff"


def test_live_unimplemented_method_reply_also_carries_the_security_headers(
    live_service: tuple[str, Path, Path],
) -> None:
    """OPTIONS is answered by the stdlib's own send_error(), not by
    _send_json, so the headers have to be stamped in end_headers()."""
    base_url, _hub, _argv_path = live_service
    request = urllib.request.Request(f"{base_url}/health", method="OPTIONS")
    try:
        urllib.request.urlopen(request, timeout=10)
        raise AssertionError("expected an error status")
    except urllib.error.HTTPError as exc:
        assert exc.code == 501
        assert exc.headers["Content-Security-Policy"] == \
            bd_serve.SECURITY_HEADERS["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in exc.headers


def test_live_hostile_id_rejected_over_the_wire(
    live_service: tuple[str, Path, Path],
) -> None:
    base_url, hub, argv_path = live_service
    _init_board(hub)
    status, body = _http_post(base_url, "/issue/show", {"id": "--db=/etc/passwd"})
    assert status == 400
    assert "invalid issue id" in str(body["error"])
    assert not argv_path.exists()


def test_live_unknown_path_and_malformed_body_rejected(
    live_service: tuple[str, Path, Path],
) -> None:
    base_url, hub, argv_path = live_service
    _init_board(hub)
    assert _http_post(base_url, "/issue/exec", {"cmd": "rm -rf /"})[0] == 404
    assert _http_post(base_url, "/issue/show", ["not", "an", "object"])[0] == 400
    request = urllib.request.Request(
        f"{base_url}/issue/show", data=b"{not json", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=10)
        raise AssertionError("expected HTTP 400")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    assert not argv_path.exists()


def test_live_browser_shaped_requests_refused(
    live_service: tuple[str, Path, Path],
) -> None:
    """A page in a browser must not be able to drive the loopback port."""
    base_url, hub, argv_path = live_service
    _init_board(hub)
    body = json.dumps({"title": "browser-created"}).encode("utf-8")
    browser_headers = [
        # A "simple request" needs no preflight, so text/plain is the shape a
        # cross-origin page would actually use.
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/json", "Origin": "https://evil.example"},
    ]
    for headers in browser_headers:
        request = urllib.request.Request(
            f"{base_url}/issue/create", data=body, method="POST", headers=headers,
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError(f"expected HTTP 403 for {headers}")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    assert not argv_path.exists()


def test_live_rebinding_host_header_refused(
    live_service: tuple[str, Path, Path],
) -> None:
    base_url, hub, argv_path = live_service
    _init_board(hub)
    request = urllib.request.Request(
        f"{base_url}/issue/create",
        data=json.dumps({"title": "rebound"}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Host": "attacker.example:9101"},
    )
    try:
        urllib.request.urlopen(request, timeout=10)
        raise AssertionError("expected HTTP 403")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    assert not argv_path.exists()


def _raw_request(base_url: str, request_text: str) -> bytes:
    """Send a hand-written HTTP request and return the whole raw response."""
    host, port = base_url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as connection:
        connection.sendall(request_text.encode("ascii"))
        connection.shutdown(socket.SHUT_WR)
        response = b""
        while chunk := connection.recv(4096):
            response += chunk
    return response


_JSON_BODY = '{"id":"A1"}'


@pytest.mark.parametrize(
    ("label", "request_text", "expected"),
    [
        ("absent Host", f"POST /issue/show HTTP/1.0\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
        ("Origin: null", f"POST /issue/show HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: null\r\n"
                         f"Content-Type: application/json\r\n"
                         f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
        ("lowercase headers", f"POST /issue/show HTTP/1.1\r\nhost: 127.0.0.1\r\n"
                              f"origin: https://evil.example\r\ncontent-type: application/json\r\n"
                              f"content-length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
        ("multipart form post", f"POST /issue/show HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                f"Content-Type: multipart/form-data; boundary=x\r\n"
                                f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
        ("form-urlencoded post", f"POST /issue/show HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                 f"Content-Type: application/x-www-form-urlencoded\r\n"
                                 f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
        ("rebinding host on unknown path", "POST /issue/exec HTTP/1.1\r\n"
                                           "Host: attacker.example\r\n"
                                           "Content-Type: application/json\r\n"
                                           "Content-Length: 2\r\n\r\n{}", b" 403 "),
        ("bracketed ipv6 host", f"POST /issue/show HTTP/1.1\r\nHost: [::1]:1\r\n"
                                f"Content-Type: application/json\r\n"
                                f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 200 "),
        ("json with charset", f"POST /issue/show HTTP/1.1\r\nHost: localhost\r\n"
                              f"Content-Type: application/json; charset=utf-8\r\n"
                              f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 200 "),
        ("PUT", "PUT /issue/show HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}", b" 501 "),
        ("OPTIONS preflight", "OPTIONS /issue/show HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                              "Origin: https://evil.example\r\n\r\n", b" 501 "),
        ("HEAD", "HEAD /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", b" 501 "),
        ("absolute-form target", f"POST http://attacker.example/issue/show HTTP/1.1\r\n"
                                 f"Host: 127.0.0.1\r\nContent-Type: application/json\r\n"
                                 f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}",
         b" 403 "),
        # /issue/list, not /issue/show: list needs no parameters, so an
        # unframeable body silently read as `{}` would REACH bd. This case
        # fails loudly if the Transfer-Encoding guard is removed.
        ("chunked body refused", "POST /issue/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                                 "Content-Type: application/json\r\n"
                                 "Transfer-Encoding: chunked\r\n\r\n"
                                 "b\r\n{\"id\":\"A1\"}\r\n0\r\n\r\n", b" 400 "),
        ("duplicate content length refused",
         "POST /issue/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
         "Content-Type: application/json\r\nContent-Length: 0\r\n"
         "Content-Length: 11\r\n\r\n" + _JSON_BODY, b" 400 "),
        ("duplicate host refused",
         f"POST /issue/list HTTP/1.1\r\nHost: 127.0.0.1\r\nHost: attacker.example\r\n"
         f"Content-Type: application/json\r\n"
         f"Content-Length: {len(_JSON_BODY)}\r\n\r\n{_JSON_BODY}", b" 403 "),
    ],
)
def test_live_http_attack_matrix(
    live_service: tuple[str, Path, Path], label: str, request_text: str, expected: bytes,
) -> None:
    base_url, hub, argv_path = live_service
    _init_board(hub)
    response = _raw_request(base_url, request_text)
    assert expected in response.split(b"\r\n", 1)[0], f"{label}: {response[:120]!r}"
    if expected != b" 200 ":
        assert not argv_path.exists(), label


def test_live_negative_content_length_refused(
    live_service: tuple[str, Path, Path],
) -> None:
    """`Content-Length: -1` must not become a read-until-EOF."""
    base_url, hub, argv_path = live_service
    _init_board(hub)
    host, port = base_url.removeprefix("http://").split(":")
    request = (
        "POST /issue/create HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: -1\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection((host, int(port)), timeout=10) as connection:
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        response = b""
        while chunk := connection.recv(4096):
            response += chunk
    assert b" 400 " in response.split(b"\r\n", 1)[0]
    # Named explicitly: without the guard the read blocks until EOF and the
    # request still happens to end in a 400, which would hide the defect.
    assert b"negative content length" in response
    assert not argv_path.exists()


def test_live_good_request_reaches_bd(live_service: tuple[str, Path, Path]) -> None:
    base_url, hub, argv_path = live_service
    _init_board(hub)
    status, _body = _http_post(base_url, "/issue/show", {"id": "A1"})
    assert status == 200
    assert _calls(argv_path)[-1]["argv"] == ["bd", "--json", "show", "A1"]
