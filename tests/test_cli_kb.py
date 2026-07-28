"""Tests for the `kb` CLI: an HTTP client with no vault logic at all.

Two properties matter here and nothing else does. First, each verb calls
the endpoint it claims to call, with the payload it claims to send.
Second, a service that is down or unhappy produces a LOUD failure naming
the endpoint and the error, never a silent fallback -- a fallback would
be a second way into the vault, which is the one thing the service layer
exists to prevent.

Every test mocks urllib, so nothing here reaches a real kb-svc.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

_AGENT_WORKBENCH_DIR = (
    Path(__file__).resolve().parent.parent / ".claude" / "skills" / "agent-workbench"
)
if str(_AGENT_WORKBENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_WORKBENCH_DIR))

from cli import kb, kb_decision, kb_embed  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for urllib.request.urlopen()'s context manager."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _capture_request(payload: dict[str, object]):
    """Patch urlopen, returning ``payload`` and recording the Request."""
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request, *args, **kwargs):  # noqa: ANN001 stdlib shape
        seen.append(request)
        return _FakeResponse(payload)

    return patch("urllib.request.urlopen", side_effect=fake_urlopen), seen


def _run(argv: list[str]) -> argparse.Namespace:
    """Parse ``argv`` through the real parser the CLI registers."""
    parser = argparse.ArgumentParser()
    kb.register(parser.add_subparsers(dest="command", required=True))
    return parser.parse_args(["kb", *argv])


# ── service address ───────────────────────────────────────────────────


def test_service_base_url_honors_host_and_port_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KB_SVC_HOST", "10.0.0.7")
    monkeypatch.setenv("KB_SVC_PORT", "9999")
    assert kb.service_base_url() == "http://10.0.0.7:9999"


def test_service_base_url_defaults_to_loopback_9100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KB_SVC_HOST", raising=False)
    monkeypatch.delenv("KB_SVC_PORT", raising=False)
    assert kb.service_base_url() == "http://127.0.0.1:9100"


# ── loud failure, never a fallback ────────────────────────────────────


def test_unreachable_service_raises_naming_the_endpoint_and_error() -> None:
    refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    with patch("urllib.request.urlopen", side_effect=refused):
        with pytest.raises(RuntimeError) as excinfo:
            kb.get_json("/status")
    message = str(excinfo.value)
    assert "/status" in message
    assert "unreachable" in message
    assert "Connection refused" in message


def test_http_error_surfaces_the_response_body_instead_of_swallowing_it() -> None:
    error = urllib.error.HTTPError(
        url="http://127.0.0.1:9100/put",
        code=400,
        msg="Bad Request",
        hdrs=None,  # type: ignore[arg-type]  stdlib accepts None here
        fp=io.BytesIO(b'{"error": "invalid project name'
                      b" '../escape'\"}"),
    )
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="invalid project name"):
            kb.post_json("/put", {"project": "../escape"})


def test_a_failed_verb_never_falls_back_to_touching_the_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the service layer: no second write path."""
    monkeypatch.setenv("KB_HOME", str(tmp_path))
    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    with patch("urllib.request.urlopen", side_effect=refused):
        with pytest.raises(RuntimeError):
            kb.cmd_add(_run(["add", "proj1"]))
    assert list(tmp_path.iterdir()) == []


# ── verb -> endpoint mapping ──────────────────────────────────────────


@pytest.mark.parametrize(
    ("argv", "method", "path"),
    [
        (["init"], "POST", "/vault/init"),
        (["add", "proj1"], "POST", "/project/init"),
        (["index"], "POST", "/reindex"),
        (["status"], "GET", "/status"),
        (["path", "proj1"], "GET", "/project?project=proj1"),
        (["query", "widgets"], "GET", "/query?q=widgets"),
        (["enrich"], "POST", "/enrich"),
        (["embed", "missing"], "POST", "/embed/missing"),
        (["embed", "all"], "POST", "/embed/all"),
    ],
)
def test_verb_calls_its_endpoint(
    argv: list[str], method: str, path: str, capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"path": "/vault/proj1", "results": []})
    args = _run(argv)
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.get_method() == method
    assert request.full_url == f"http://127.0.0.1:9100{path}"
    capsys.readouterr()


def test_put_sends_stdin_as_the_note_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("body from stdin"))
    patcher, seen = _capture_request({"path": "/vault/note.md"})
    args = _run(["put", "proj1", "My Note", "--type", "research"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == "http://127.0.0.1:9100/put"
    assert json.loads(request.data) == {
        "project": "proj1", "title": "My Note", "type": "research",
        "source": "", "content": "body from stdin",
    }
    capsys.readouterr()


def test_query_passes_every_filter_through(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"results": []})
    args = _run(["query", "widgets", "--project", "proj1", "--type", "note", "--all"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == (
        "http://127.0.0.1:9100/query?q=widgets&project=proj1&type=note&all=1"
    )
    capsys.readouterr()


def test_enrich_passes_project_and_note_through(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"enriched": 0, "message": "disabled"})
    args = _run(["enrich", "--project", "proj1", "--note", "proj1/notes/a.md"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == "http://127.0.0.1:9100/enrich"
    assert json.loads(request.data) == {
        "project": "proj1", "note": "proj1/notes/a.md",
    }
    capsys.readouterr()


def test_enrich_with_no_flags_sends_an_empty_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"enriched": 0, "message": "disabled"})
    args = _run(["enrich"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert json.loads(request.data) == {}
    capsys.readouterr()


def test_path_prints_only_the_path_the_service_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, _ = _capture_request({"path": "/vault/proj1", "exists": True})
    args = _run(["path", "proj1"])
    with patcher:
        args.func(args)
    assert capsys.readouterr().out.strip() == "/vault/proj1"


# ── decision verbs ────────────────────────────────────────────────────


def test_decision_record_posts_every_field(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"path": "/vault/d.md", "supersedes": ""})
    args = _run([
        "decision", "record", "--project", "proj1", "--topic", "shape",
        "--title", "Round", "--text", "Widgets are round", "--tags", "a, b",
    ])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == "http://127.0.0.1:9100/decision"
    assert json.loads(request.data) == {
        "project": "proj1", "topic": "shape", "title": "Round",
        "text": "Widgets are round", "rationale": "", "refs": "", "tags": "a, b",
    }
    capsys.readouterr()


def test_decision_audit_human_prints_one_line_per_note(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chain = {"chain": [
        {"date": "2026-07-01", "status": "superseded", "title": "Round",
         "path": "/vault/a.md", "supersedes": ""},
        {"date": "2026-07-02", "status": "active", "title": "Square",
         "path": "/vault/b.md", "supersedes": "/vault/a.md"},
    ]}
    patcher, seen = _capture_request(chain)
    args = _run(["decision", "audit", "shape", "--human"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == "http://127.0.0.1:9100/decision/audit?topic=shape"
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("2026-07-01  superseded   Round")
    assert lines[1].endswith("(supersedes: /vault/a.md)")


def test_decision_audit_json_prints_the_chain_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [{"date": "2026-07-01", "status": "active", "title": "Round",
             "path": "/vault/a.md", "supersedes": ""}]
    patcher, _ = _capture_request({"chain": rows})
    args = _run(["decision", "audit", "shape", "--project", "proj1"])
    with patcher:
        assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out) == rows


def test_decision_module_holds_no_vault_logic() -> None:
    """The chain walk and frontmatter dialect live in the service now."""
    assert not hasattr(kb_decision, "render_decision")
    assert not hasattr(kb_decision, "audit")


# ── embed verbs ───────────────────────────────────────────────────────


def test_embed_dry_run_flag_reaches_the_payload(
    capsys: pytest.CaptureFixture[str],
) -> None:
    patcher, seen = _capture_request({"mode": "missing", "dry_run": True})
    args = _run(["embed", "missing", "--dry-run"])
    with patcher:
        assert args.func(args) == 0
    [request] = seen
    assert request.full_url == "http://127.0.0.1:9100/embed/missing"
    assert json.loads(request.data) == {"dry_run": True}
    capsys.readouterr()


def test_embed_module_holds_no_vault_logic() -> None:
    """Mirrors test_decision_module_holds_no_vault_logic: kb_embed.py (the
    CLI one) is an HTTP client only. The batching, staleness comparison
    and embedding all live in scripts/kb_embed.py inside the service."""
    assert not hasattr(kb_embed, "sync_vectors")
    assert not hasattr(kb_embed, "stale_notes")
