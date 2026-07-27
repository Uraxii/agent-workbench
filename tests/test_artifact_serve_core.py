"""Function-level tests for artifact-serve: DB round trip, anchor validation,
thread/reply/resolve store, feedback JSON dump, and path-safety helpers.

Always runs against a temp DB (tests/artifact_serve_support.temp_env), never
~/.local/share/claude-artifacts/feedback.db.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifact_serve_support import push_artifact, artifact_serve, temp_env  # noqa: E402,F401

Anchor = artifact_serve.Anchor


def test_db_connect_creates_schema(temp_env: Path) -> None:
    conn = artifact_serve.db_connect()
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert {"thread", "reply", "upload", "artifact_index", "setting"} <= names


def test_setting_set_get_delete_roundtrip(temp_env: Path) -> None:
    assert artifact_serve.setting_get("author") is None
    artifact_serve.setting_set("author", "nicole")
    assert artifact_serve.setting_get("author") == "nicole"
    artifact_serve.setting_delete("author")
    assert artifact_serve.setting_get("author") is None


def test_validate_anchor_page_rejects_extra_data(temp_env: Path) -> None:
    anchor = artifact_serve.validate_anchor("page", None)
    assert anchor.kind == "page" and anchor.data is None
    with pytest.raises(ValueError):
        artifact_serve.validate_anchor("page", '{"line": 1}')


def test_validate_anchor_image_region_accepts_fragment_selector(temp_env: Path) -> None:
    data = json.dumps({"selector": {"type": "FragmentSelector", "value": "xywh=1,2,3,4"}})
    anchor = artifact_serve.validate_anchor("image_region", data)
    assert anchor.kind == "image_region"
    assert anchor.data["selector"]["value"] == "xywh=1,2,3,4"


def test_validate_anchor_image_region_rejects_svg_selector(temp_env: Path) -> None:
    """SvgSelector is stored-XSS-capable (parsed into live DOM); server must reject it."""
    data = json.dumps({"selector": {"type": "SvgSelector", "value": "<svg onload=alert(1)>"}})
    with pytest.raises(ValueError, match="unsupported selector type"):
        artifact_serve.validate_anchor("image_region", data)


def test_validate_anchor_code_line_requires_positive_int(temp_env: Path) -> None:
    anchor = artifact_serve.validate_anchor("code_line", json.dumps({"line": 5}))
    assert anchor.data == {"line": 5}
    with pytest.raises(ValueError):
        artifact_serve.validate_anchor("code_line", json.dumps({"line": 0}))
    with pytest.raises(ValueError):
        artifact_serve.validate_anchor("code_line", json.dumps({"line": "5"}))


def test_validate_anchor_code_line_end_before_line_rejected(temp_env: Path) -> None:
    with pytest.raises(ValueError):
        artifact_serve.validate_anchor(
            "code_line", json.dumps({"line": 10, "end_line": 3})
        )


def test_create_thread_and_list_threads_roundtrip(temp_env: Path) -> None:
    thread_id, reply_id = artifact_serve.create_thread(
        "proj/art", "", Anchor(kind="page", data=None), "first comment", "alice", []
    )
    threads = artifact_serve.list_threads("proj/art", "")
    assert len(threads) == 1
    t = threads[0]
    assert t.id == thread_id
    assert t.resolved is False
    assert len(t.replies) == 1
    assert t.replies[0].id == reply_id
    assert t.replies[0].body == "first comment"
    assert t.replies[0].author == "alice"


def test_add_reply_appends_to_thread(temp_env: Path) -> None:
    thread_id, _ = artifact_serve.create_thread(
        "proj/art", "", Anchor(kind="page", data=None), "opener", "alice", []
    )
    reply_id = artifact_serve.add_reply(thread_id, "a follow-up", "bob", [])
    threads = artifact_serve.list_threads("proj/art", "")
    replies = threads[0].replies
    assert [r.id for r in replies] == sorted(r.id for r in replies)
    assert replies[-1].id == reply_id
    assert replies[-1].body == "a follow-up"
    assert replies[-1].author == "bob"


def test_add_reply_unknown_thread_raises_keyerror(temp_env: Path) -> None:
    with pytest.raises(KeyError):
        artifact_serve.add_reply(999999, "body", None, [])


def test_set_resolved_toggle_and_explicit(temp_env: Path) -> None:
    thread_id, _ = artifact_serve.create_thread(
        "proj/art", "", Anchor(kind="page", data=None), "opener", None, []
    )
    assert artifact_serve.set_resolved(thread_id, True) is True
    assert artifact_serve.set_resolved(thread_id, None) is False  # toggle
    assert artifact_serve.set_resolved(thread_id, None) is True  # toggle back
    assert artifact_serve.set_resolved(thread_id, False) is False


def test_set_resolved_missing_thread_raises_keyerror(temp_env: Path) -> None:
    with pytest.raises(KeyError):
        artifact_serve.set_resolved(999999, True)


def test_feedback_dump_shape(temp_env: Path) -> None:
    artifact_serve.create_thread(
        "proj/art", "sub.png", Anchor(kind="page", data=None), "hello", "alice", []
    )
    payload = artifact_serve.feedback_dump("proj/art")
    assert payload["artifact_id"] == "proj/art"
    assert isinstance(payload["pushes"], list)
    assert len(payload["threads"]) == 1
    assert payload["threads"][0]["replies"][0]["body"] == "hello"
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["body"] == "hello"


def test_feedback_dump_unknown_artifact_returns_empty(temp_env: Path) -> None:
    payload = artifact_serve.feedback_dump("nobody/nothing")
    assert payload == {
        "artifact_id": "nobody/nothing",
        "current_round": None,
        "rounds": [],
        "pushes": [],
        "threads": [],
        "comments": [],
    }


def test_cmd_feedback_prints_json_matching_feedback_dump(
    temp_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifact_serve.create_thread(
        "proj/art", "", Anchor(kind="page", data=None), "cli round trip", "alice", []
    )
    parser = artifact_serve.build_parser()
    args = parser.parse_args(["feedback", "--artifact", "proj/art"])
    rc = artifact_serve.cmd_feedback(args)
    assert rc == artifact_serve.EXIT_OK
    out = capsys.readouterr().out
    dumped = json.loads(out)
    assert dumped == artifact_serve.feedback_dump("proj/art")
    assert dumped["threads"][0]["replies"][0]["body"] == "cli round trip"


def test_cmd_feedback_no_artifact_id_is_caller_error(
    temp_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = artifact_serve.build_parser()
    args = parser.parse_args(["feedback", "--artifact", "  "])
    rc = artifact_serve.cmd_feedback(args)
    assert rc == artifact_serve.EXIT_CALLER


def test_safe_upload_filename_strips_traversal_and_specials(temp_env: Path) -> None:
    assert artifact_serve.safe_upload_filename("../../etc/passwd") == "passwd"
    assert artifact_serve.safe_upload_filename("normal-name_1.png") == "normal-name_1.png"
    assert artifact_serve.safe_upload_filename("weird$name!.png") == "weird_name_.png"


def test_upload_ext_ok_allows_and_blocks(temp_env: Path) -> None:
    assert artifact_serve.upload_ext_ok("photo.png") == (True, "")
    ok, why = artifact_serve.upload_ext_ok("script.exe")
    assert ok is False and "blocked" in why
    ok, why = artifact_serve.upload_ext_ok("mystery.xyz")
    assert ok is False and "not in allowlist" in why


def test_staged_source_path_blocks_traversal_outside_root(
    temp_env: Path, tmp_path: Path
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hello", encoding="utf-8")
    artifact_id = push_artifact(src_dir, "proj2", "art-a")

    real = artifact_serve.staged_source_path(artifact_id, "a.txt")
    assert real is not None
    assert real.read_text(encoding="utf-8") == "hello"

    assert artifact_serve.staged_source_path(artifact_id, "../../../etc/passwd") is None
    assert artifact_serve.staged_source_path(artifact_id, "does-not-exist.txt") is None


def test_resolve_artifact_id_falls_back_when_not_indexed(temp_env: Path) -> None:
    artifact_id, sub_path = artifact_serve.resolve_artifact_id("/some-proj/some-sub/x.png")
    assert artifact_id == "some-proj/some-sub"
    assert sub_path == "x.png"


def test_migrate_schema_is_idempotent(temp_env: Path) -> None:
    conn = artifact_serve.db_connect()
    try:
        artifact_serve.migrate_schema(conn)  # second call must be a no-op, not raise
        version = conn.execute(
            "SELECT value FROM setting WHERE key='schema_version'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert int(version) == artifact_serve.SCHEMA_VERSION


@pytest.mark.parametrize("subcommand", ["run", "start"])
def test_build_parser_port_and_host_honor_env_vars(
    subcommand: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2 fix: --port/--host default from ARTIFACT_SERVE_PORT/ARTIFACT_SERVE_HOST
    instead of a hardcoded DEFAULT_PORT/"127.0.0.1" literal, so a container
    or systemd unit can steer the bound address without an extra CLI flag."""
    monkeypatch.setenv("ARTIFACT_SERVE_PORT", "9321")
    monkeypatch.setenv("ARTIFACT_SERVE_HOST", "0.0.0.0")
    args = artifact_serve.build_parser().parse_args([subcommand])
    assert args.port == 9321
    assert args.host == "0.0.0.0"


@pytest.mark.parametrize("subcommand", ["run", "start"])
def test_build_parser_port_and_host_default_when_env_absent(
    subcommand: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARTIFACT_SERVE_PORT", raising=False)
    monkeypatch.delenv("ARTIFACT_SERVE_HOST", raising=False)
    args = artifact_serve.build_parser().parse_args([subcommand])
    assert args.port == artifact_serve.DEFAULT_PORT
    assert args.host == "127.0.0.1"
