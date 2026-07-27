"""HTTP-level tests for artifact-serve: real requests against a real socket
(ThreadingHTTPServer bound to an ephemeral port), backed by a temp DB and a
temp staging root. Never touches /tmp/claude-artifacts or the real
~/.local/share/claude-artifacts/feedback.db, and never calls `stop` (no
daemon/pidfile/tailscale involved at all -- see live_server in
artifact_serve_support.py).

artifact-serve has no dedicated /health route; GET / (the index page, always
200 once regenerate_index() has run) is the closest liveness check and is
what test_index_route_is_live below exercises.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artifact_serve_support import (  # noqa: E402,F401
    http_request,
    live_server,
    multipart_body,
    multipart_with_file,
    push_artifact,
    artifact_serve,
    temp_env,
)

FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nnot-a-real-png-just-test-bytes"


def test_index_route_is_live(live_server: str) -> None:
    """No dedicated /health route exists; GET / is the nearest liveness check."""
    artifact_serve.regenerate_index()
    status, body, headers = http_request(live_server + "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"artifact-serve" in body


def test_pushed_image_served_200_with_correct_bytes(
    live_server: str, tmp_path: Path
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "shot.png").write_bytes(FAKE_PNG_BYTES)
    push_artifact(src_dir, "projimg", "art-b")

    status, body, headers = http_request(live_server + "/projimg/art-b/shot.png")
    assert status == 200
    assert body == FAKE_PNG_BYTES
    assert headers["content-type"] == "image/png"


def test_gallery_route_lists_pushed_image(live_server: str, tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "shot.png").write_bytes(FAKE_PNG_BYTES)
    artifact_id = push_artifact(src_dir, "projgal", "art-c")

    status, body, headers = http_request(
        live_server + f"/_/review?artifact={artifact_id}"
    )
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"shot.png" in body


def test_viewer_route_for_pushed_image(live_server: str, tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "shot.png").write_bytes(FAKE_PNG_BYTES)
    artifact_id = push_artifact(src_dir, "projview", "art-d")

    status, body, _ = http_request(
        live_server + f"/_/review?artifact={artifact_id}&src=shot.png&view=image"
    )
    assert status == 200
    assert b"OpenSeadragon" in body


def test_viewer_route_404_for_missing_source(live_server: str, tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "shot.png").write_bytes(FAKE_PNG_BYTES)
    artifact_id = push_artifact(src_dir, "projmiss", "art-e")

    status, _, _ = http_request(
        live_server + f"/_/review?artifact={artifact_id}&src=nope.png&view=image"
    )
    assert status == 404


def test_thread_create_get_reply_resolve_roundtrip_via_http(live_server: str) -> None:
    # create the opening thread
    body, ctype = multipart_body(
        {
            "artifact": "projthread/art-f",
            "sub_path": "",
            "anchor_kind": "page",
            "body": "please fix the color",
            "author": "alice",
        }
    )
    status, resp, _ = http_request(
        live_server + "/_/api/threads",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    assert status == 201
    created = json.loads(resp)
    thread_id = created["thread_id"]

    # read it back
    status, resp, _ = http_request(
        live_server + "/_/api/threads?artifact=projthread/art-f&sub_path="
    )
    assert status == 200
    listed = json.loads(resp)
    assert len(listed["threads"]) == 1
    assert listed["threads"][0]["resolved"] is False
    assert listed["threads"][0]["replies"][0]["body"] == "please fix the color"

    # reply to it
    reply_body, reply_ctype = multipart_body({"body": "fixed, thanks", "author": "bob"})
    status, resp, _ = http_request(
        live_server + f"/_/api/threads/{thread_id}/replies",
        data=reply_body,
        headers={"Content-Type": reply_ctype},
        method="POST",
    )
    assert status == 201

    # resolve it
    status, resp, _ = http_request(
        live_server + f"/_/api/threads/{thread_id}/resolve",
        data=json.dumps({"resolved": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    assert status == 200
    assert json.loads(resp) == {"id": thread_id, "resolved": True}

    # confirm resolved + both replies present, and feedback_dump agrees
    status, resp, _ = http_request(
        live_server + "/_/api/threads?artifact=projthread/art-f&sub_path="
    )
    listed = json.loads(resp)
    assert listed["threads"][0]["resolved"] is True
    assert [r["body"] for r in listed["threads"][0]["replies"]] == [
        "please fix the color",
        "fixed, thanks",
    ]

    dump = artifact_serve.feedback_dump("projthread/art-f")
    assert dump["threads"][0]["resolved"] is True
    assert len(dump["threads"][0]["replies"]) == 2


def test_thread_create_missing_body_returns_400(live_server: str) -> None:
    body, ctype = multipart_body({"artifact": "projx/arty", "anchor_kind": "page"})
    status, resp, _ = http_request(
        live_server + "/_/api/threads",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    assert status == 400
    assert "body required" in json.loads(resp)["error"]


def test_image_region_anchor_rejects_svg_selector_via_http(live_server: str) -> None:
    """Server-side XSS guard: SvgSelector must never reach the store, even over HTTP."""
    anchor_data = json.dumps(
        {"selector": {"type": "SvgSelector", "value": "<svg onload=alert(1)>"}}
    )
    body, ctype = multipart_body(
        {
            "artifact": "projsvg/art-g",
            "anchor_kind": "image_region",
            "anchor_data": anchor_data,
            "body": "malicious pin",
        }
    )
    status, resp, _ = http_request(
        live_server + "/_/api/threads",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    assert status == 400
    assert "unsupported selector type" in json.loads(resp)["error"]


def test_resolve_unknown_thread_returns_404(live_server: str) -> None:
    status, resp, _ = http_request(
        live_server + "/_/api/threads/999999/resolve",
        data=json.dumps({"resolved": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    assert status == 404


def test_upload_file_stored_and_retrievable(live_server: str) -> None:
    body, ctype = multipart_with_file(
        {"artifact": "projup/art-h", "anchor_kind": "page", "body": "see attached"},
        filename="evidence.png",
        content=FAKE_PNG_BYTES,
    )
    status, resp, _ = http_request(
        live_server + "/_/api/threads",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    assert status == 201
    created = json.loads(resp)
    assert len(created["uploads"]) == 1
    upload_id = created["uploads"][0]["id"]

    status, resp, headers = http_request(live_server + f"/_/api/uploads/{upload_id}")
    assert status == 200
    assert resp == FAKE_PNG_BYTES
    assert "evidence.png" in headers["content-disposition"]


def test_upload_blocked_extension_rejected(live_server: str) -> None:
    body, ctype = multipart_with_file(
        {"artifact": "projup/art-i", "anchor_kind": "page", "body": "see attached"},
        filename="malware.exe",
        content=b"MZ...",
    )
    status, resp, _ = http_request(
        live_server + "/_/api/threads",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    assert status == 400
    assert "blocked" in json.loads(resp)["error"]


def test_settings_route_reflects_only_explicit_settings(live_server: str) -> None:
    # schema_version is stamped by migrate_schema on first db_connect(); no
    # other setting exists until one is explicitly set.
    status, resp, _ = http_request(live_server + "/_/api/settings")
    assert status == 200
    assert json.loads(resp) == {"schema_version": str(artifact_serve.SCHEMA_VERSION)}

    artifact_serve.setting_set("author", "nicole")
    status, resp, _ = http_request(live_server + "/_/api/settings")
    assert json.loads(resp) == {
        "schema_version": str(artifact_serve.SCHEMA_VERSION),
        "author": "nicole",
    }


def test_no_secret_leaked_in_any_response(
    live_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret sitting in the process environment must never round-trip
    into a served page or API response, however unrelated the route."""
    secret = "sk-supersecret-test-token-should-never-leak-9f8e7d"
    monkeypatch.setenv("ARTIFACT_SERVE_TEST_SECRET", secret)
    artifact_serve.regenerate_index()

    body, ctype = multipart_body(
        {"artifact": "projsec/art-j", "anchor_kind": "page", "body": "normal comment"}
    )
    _, thread_resp, _ = http_request(
        live_server + "/_/api/threads", data=body,
        headers={"Content-Type": ctype}, method="POST",
    )

    responses = [
        http_request(live_server + "/")[1],
        http_request(live_server + "/_/api/settings")[1],
        http_request(live_server + "/_/api/threads?artifact=projsec/art-j&sub_path=")[1],
        thread_resp,
    ]
    for resp in responses:
        assert secret.encode("utf-8") not in resp
