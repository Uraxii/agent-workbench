from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench"

if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from cli import bd  # noqa: E402


def build_bd_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-workbench")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bd.register(subparsers)
    return parser


@pytest.fixture
def captured_posts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, object]]]:
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_post(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        posts.append((endpoint, payload))
        return {"ok": True}

    monkeypatch.setattr(bd, "_post_json", fake_post)
    return posts


@pytest.mark.parametrize(
    ("argv", "func", "endpoint", "payload"),
    [
        (["bd", "init"], bd.cmd_init, "/hub/init", {}),
        (["bd", "add", "proj"], bd.cmd_add, "/hub/add", {"name": "proj"}),
        (["bd", "add", "proj", "p"], bd.cmd_add, "/hub/add", {"name": "proj", "prefix": "p"}),
        (["bd", "sync"], bd.cmd_sync, "/hub/sync", {}),
        (["bd", "repos"], bd.cmd_repos, "/hub/repos", {}),
        (["bd", "path", "proj"], bd.cmd_path, "/hub/path", {"name": "proj"}),
        (["bd", "status"], bd.cmd_status, "/hub/status", {}),
        (["bd", "list", "--board", "proj", "--status", "open", "--assignee", "me",
          "--label", "a", "--label", "b", "--limit", "5", "--all"], bd.cmd_list,
         "/issue/list", {"board": "proj", "status": "open", "assignee": "me",
                          "labels": ["a", "b"], "limit": "5", "all": True}),
        (["bd", "show", "A1", "--board", "proj"], bd.cmd_show,
         "/issue/show", {"board": "proj", "id": "A1"}),
        (["bd", "create", "T", "--board", "proj", "-d", "D", "-p", "2", "-l", "x",
          "--parent", "P1", "--assignee", "me"], bd.cmd_create, "/issue/create",
         {"board": "proj", "title": "T", "description": "D", "priority": "2",
          "labels": ["x"], "parent": "P1", "assignee": "me"}),
        (["bd", "update", "A1", "--status", "blocked", "--assignee", "me", "-p", "1",
          "-d", "D", "--add-label", "x", "--remove-label", "y", "--claim",
          "--overwrite-description", "--board", "proj"],
         bd.cmd_update, "/issue/update", {"board": "proj", "id": "A1", "status": "blocked",
         "assignee": "me", "priority": "1", "description": "D", "add_labels": ["x"],
         "remove_labels": ["y"], "claim": True, "overwrite_description": True}),
        (["bd", "close", "A1", "--reason", "done", "--board", "proj"],
         bd.cmd_close, "/issue/close", {"board": "proj", "id": "A1", "reason": "done"}),
        (["bd", "note", "A1", "hello", "--board", "proj"], bd.cmd_note, "/issue/note",
         {"board": "proj", "id": "A1", "text": "hello"}),
        (["bd", "link", "A1", "B2", "--type", "related", "--board", "proj"],
         bd.cmd_link, "/issue/link",
         {"board": "proj", "from_id": "A1", "to_id": "B2", "type": "related"}),
        (["bd", "children", "A1", "--board", "proj"], bd.cmd_children,
         "/issue/children", {"board": "proj", "id": "A1"}),
        (["bd", "priority", "A1", "4", "--board", "proj"], bd.cmd_priority,
         "/issue/priority", {"board": "proj", "id": "A1", "priority": "4"}),
        (["bd", "ready", "--board", "proj", "--assignee", "me", "--label", "a",
          "--label", "b", "--limit", "5"], bd.cmd_ready, "/issue/ready",
         {"board": "proj", "assignee": "me", "labels": ["a", "b"], "limit": "5"}),
        (["bd", "search", "needle", "--board", "proj", "--status", "open",
          "--limit", "5"], bd.cmd_search, "/issue/search",
         {"board": "proj", "query": "needle", "status": "open", "limit": "5"}),
        (["bd", "dep", "A1", "--board", "proj", "--direction", "up",
          "--type", "blocks"], bd.cmd_dep, "/issue/dep",
         {"board": "proj", "id": "A1", "direction": "up", "type": "blocks"}),
    ],
)
def test_bd_verbs_post_expected_payloads(
    argv: list[str],
    func: object,
    endpoint: str,
    payload: dict[str, object],
    captured_posts: list[tuple[str, dict[str, object]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = build_bd_parser().parse_args(argv)
    assert args.func is func
    assert args.func(args) == 0
    assert captured_posts == [(endpoint, payload)]
    assert capsys.readouterr().out.strip() == '{"ok": true}'


@pytest.mark.parametrize(
    "argv",
    [
        ["bd", "list"],
        ["bd", "show", "A1"],
        ["bd", "children", "A1"],
        ["bd", "ready"],
        ["bd", "search", "needle"],
        ["bd", "dep", "A1"],
        ["bd", "create", "T"],
        ["bd", "update", "A1"],
        ["bd", "close", "A1"],
        ["bd", "note", "A1", "hello"],
        ["bd", "link", "A1", "B2"],
        ["bd", "priority", "A1", "4"],
    ],
)
def test_issue_verbs_require_board(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_bd_parser().parse_args(argv)


def test_unreachable_service_error_names_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real closed port, so the loud-failure path runs end to end."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    monkeypatch.setenv("BD_SVC_HOST", "127.0.0.1")
    monkeypatch.setenv("BD_SVC_PORT", str(port))
    with pytest.raises(RuntimeError) as excinfo:
        bd.cmd_list(argparse.Namespace(board="hub", status=None, assignee=None, label=[],
                                       limit=None, all=False))
    message = str(excinfo.value)
    assert f"http://127.0.0.1:{port}/issue/list" in message
    assert "Connection refused" in message or "Errno 111" in message
