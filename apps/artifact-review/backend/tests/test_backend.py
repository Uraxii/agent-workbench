"""Backend publish, schema, and response security tests."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponse
from django.test import Client, override_settings

from artifact_review import artifact_paths, publish_policy, views_api
from artifact_review.feedback_database import ensure_feedback_schema
from artifact_review.models import ArtifactIndex, Reply, Setting, Thread, Upload
from artifact_review.response_headers import APP_CSP, ARTIFACT_CSP


@pytest.fixture
def roots(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Provide isolated configured roots."""
    stage_root = tmp_path / "stage"
    feedback_root = tmp_path / "feedback"
    spa_root = tmp_path / "spa"
    stage_root.mkdir()
    feedback_root.mkdir()
    spa_root.mkdir()
    with override_settings(
        ARTIFACT_SVC_STAGE_ROOT=stage_root,
        ARTIFACT_SVC_FEEDBACK_ROOT=feedback_root,
        ARTIFACT_SVC_SPA_ROOT=spa_root,
        ARTIFACT_SVC_PUBLISH_ENABLED="1",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(feedback_root / "feedback.db"),
                "OPTIONS": {"timeout": 10},
                "TEST": {"NAME": str(feedback_root / "feedback-test.db")},
            }
        },
    ):
        yield stage_root, feedback_root, spa_root


@pytest.fixture(autouse=True)
def clean_database(roots: tuple[Path, Path, Path], db: object) -> None:
    """Ensure unmanaged sqlite tables exist and start empty."""
    del roots, db
    ensure_feedback_schema()
    Upload.objects.all().delete()
    Reply.objects.all().delete()
    Thread.objects.all().delete()
    ArtifactIndex.objects.all().delete()
    Setting.objects.exclude(key="schema_version").delete()


def test_unmanaged_models_match_feedback_schema_v2() -> None:
    """Prove unmanaged models write through the v2 sqlite schema."""
    Setting.objects.create(key="author", value="alice")
    ArtifactIndex.objects.create(
        project="demo",
        subdir="shot",
        artifact_id="demo/shot",
        src_path=str(Path("/artifact/source")),
        last_pushed=123,
    )
    thread = Thread.objects.create(
        artifact_id="demo/shot",
        sub_path="image.png",
        anchor_kind="image_region",
        anchor_data='{"selector":{"type":"FragmentSelector","value":"xywh=1,2,3,4"}}',
        resolved=0,
        author="alice",
        created_at=124,
    )
    reply = Reply.objects.create(thread=thread, body="looks good", author="bob", created_at=125)
    Upload.objects.create(
        reply=reply,
        filename="note.txt",
        stored_path=str(Path("/uploads/1/note.txt")),
        mime="text/plain",
        size=4,
        created_at=126,
    )

    fetched_thread = Thread.objects.prefetch_related("replies__uploads").get(id=thread.id)
    fetched_reply = fetched_thread.replies.get()
    fetched_upload = fetched_reply.uploads.get()

    assert fetched_thread.anchor_kind == "image_region"
    assert fetched_reply.body == "looks good"
    assert fetched_upload.filename == "note.txt"
    assert ArtifactIndex._meta.managed is False
    assert Setting.objects.get(key="schema_version").value == "2"

    with connection.cursor() as cursor:
        cursor.execute("PRAGMA table_info(thread)")
        thread_columns = [row[1] for row in cursor.fetchall()]
        cursor.execute("PRAGMA table_info(upload)")
        upload_columns = [row[1] for row in cursor.fetchall()]
    assert thread_columns == [
        "id",
        "artifact_id",
        "sub_path",
        "anchor_kind",
        "anchor_data",
        "resolved",
        "author",
        "created_at",
        "bd_ticket",
    ]
    assert "comment_id" not in upload_columns


def test_publish_single_file_tar_lands_real_file(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """A one-member tar publishes as a real staged file."""
    stage_root, _, _ = roots
    response = _publish(client, {"index.html": b"<h1>ok</h1>"})

    assert response.status_code == 201
    path = stage_root / "demo" / "shot" / "index.html"
    assert path.read_bytes() == b"<h1>ok</h1>"
    assert path.is_file()
    assert not path.is_symlink()


def test_publish_multi_file_directory_tar_lands_real_files(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """A multi-member tar publishes a directory tree with real files."""
    stage_root, _, _ = roots
    response = _publish(client, {"index.html": b"home", "assets/app.css": b"body{}"})

    assert response.status_code == 201
    assert response.json()["files"] == 2
    assert (stage_root / "demo" / "shot" / "assets" / "app.css").read_bytes() == b"body{}"
    assert not (stage_root / "demo" / "shot" / "assets" / "app.css").is_symlink()


@pytest.mark.parametrize(
    ("members", "reason"),
    [
        ({"/abs.txt": b"x"}, "bad_member_name"),
        ({"../escape.txt": b"x"}, "bad_member_name"),
    ],
)
def test_publish_rejects_bad_member_names(
    client: Client,
    roots: tuple[Path, Path, Path],
    members: dict[str, bytes],
    reason: str,
) -> None:
    """Bad archive paths are rejected."""
    response = _publish(client, members)

    assert response.status_code == 400
    assert response.json()["reason"] == reason


def test_publish_rejects_symlink_member(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Symlink tar members are rejected."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "index.html"
        tar.addfile(member)
    archive.seek(0)
    archive.name = "artifact.tar"

    response = client.post(
        "/_/api/publish",
        {"project": "demo", "as": "shot", "archive": archive},
    )

    assert response.status_code == 400
    assert response.json()["reason"] == "unsupported_member_type"


def test_publish_rejects_oversize_archive(
    client: Client,
    roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real request body larger than the archive limit is rejected before publish."""
    archive = _tar_bytes({"index.html": b"x"})
    monkeypatch.setattr(publish_policy, "MAX_ARCHIVE_BYTES", len(archive.getvalue()) - 1)
    response = client.post(
        "/_/api/publish",
        {"project": "demo", "as": "shot", "archive": archive},
    )

    assert response.status_code == 413
    assert response.json()["reason"] == "archive_too_large"


def test_publish_rejects_bad_project_name(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Project names must match the conservative name regex."""
    response = _publish(client, {"index.html": b"x"}, project="../bad")

    assert response.status_code == 400
    assert response.json()["reason"] == "bad_artifact_name"


def test_publish_write_failure_returns_json_error(
    client: Client,
    roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filesystem failures during publish return a machine-readable JSON 500."""
    stage_root, _, _ = roots
    response = _publish(client, {"index.html": b"old"})
    assert response.status_code == 201

    def raise_os_error(stage_root: Path, project: str, subdir: str, temp_path: Path, artifact_id: str) -> None:
        del stage_root, project, subdir, temp_path, artifact_id
        raise OSError("permission denied")

    monkeypatch.setattr(views_api, "_swap_published_tree", raise_os_error)
    response = _publish(client, {"index.html": b"new"})

    assert response.status_code == 500
    assert response.headers["Content-Type"] == "application/json"
    assert response.json()["reason"] == "publish_write_failed"
    assert response.json()["detail"] == "permission denied"
    assert (stage_root / "demo" / "shot" / "index.html").read_bytes() == b"old"


def test_publish_without_csrf_token_is_rejected(roots: tuple[Path, Path, Path]) -> None:
    """CSRF middleware rejects unauthenticated local POSTs without a token."""
    del roots
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/_/api/publish",
        {"project": "demo", "as": "shot", "archive": _tar_bytes({"index.html": b"x"})},
    )

    assert response.status_code == 403
    _assert_app_security_headers(response)


def test_publish_with_valid_csrf_token_succeeds(roots: tuple[Path, Path, Path]) -> None:
    """Clients that first obtain a CSRF cookie can publish."""
    del roots
    client = Client(enforce_csrf_checks=True)
    token_response = client.get("/_/health")
    csrf_token = token_response.cookies["csrftoken"].value

    response = client.post(
        "/_/api/publish",
        {"project": "demo", "as": "shot", "archive": _tar_bytes({"index.html": b"x"})},
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 201


def test_publish_rejects_url_field(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """SSRF guard rejects request fields that ask the server to fetch."""
    response = _publish(client, {"index.html": b"x"}, extra={"url": "http://127.0.0.1/x"})

    assert response.status_code == 400
    assert response.json()["reason"] == "remote_fetch_rejected"


def test_safe_join_rejects_escape_attempts(tmp_path: Path) -> None:
    """Path containment rejects parent traversal."""
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ValueError):
        artifact_paths.safe_join(root, "../escape")


def test_root_returns_missing_spa_500_with_named_path(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Missing SPA bundle returns a named-path JSON 500."""
    _, _, spa_root = roots

    response = client.get("/")

    assert response.status_code == 500
    assert response.json()["path"] == str(spa_root / "index.html")
    _assert_app_security_headers(response)


def test_root_returns_spa_shell_when_present(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Present SPA bundle is served as the app shell."""
    _, _, spa_root = roots
    (spa_root / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")

    response = client.get("/")

    assert response.status_code == 200
    assert b"<div id=\"root\"></div>" in b"".join(response.streaming_content)
    _assert_app_security_headers(response)


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("index.html", b"<script>window.__pwned = 1</script>"),
        ("image.svg", b"<svg><script>window.__pwned = 1</script></svg>"),
    ],
)
def test_artifact_scriptable_content_gets_sandbox_csp(
    client: Client,
    roots: tuple[Path, Path, Path],
    filename: str,
    body: bytes,
) -> None:
    """HTML and SVG artifacts are returned with the stored-XSS defense headers."""
    response = _publish(client, {filename: body})
    assert response.status_code == 201

    response = client.get(f"/demo/shot/{filename}")

    assert response.status_code == 200
    _assert_artifact_security_headers(response)


def test_artifact_404_gets_sandbox_csp(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Artifact misses still carry the untrusted-bytes policy."""
    del roots
    response = client.get("/demo/shot/nope.html")

    assert response.status_code == 404
    _assert_artifact_security_headers(response)


def test_feedback_upload_gets_sandbox_csp(
    client: Client,
    roots: tuple[Path, Path, Path],
) -> None:
    """Feedback uploads are caller-supplied bytes and get artifact headers."""
    del roots
    thread_response = client.post(
        "/_/api/threads",
        {
            "artifact": "demo/shot",
            "sub_path": "",
            "body": "A feedback",
            "files": SimpleUploadedFile("note.txt", b"plain feedback", content_type="text/plain"),
        },
    )
    assert thread_response.status_code == 201
    upload_id = thread_response.json()["uploads"][0]["id"]

    response = client.get(f"/_/api/uploads/{upload_id}")

    assert response.status_code == 200
    _assert_artifact_security_headers(response)


def test_feedback_upload_rejects_active_content(
    client: Client,
    roots: tuple[Path, Path, Path],
) -> None:
    """Feedback uploads reject active-content extensions."""
    del roots
    response = client.post(
        "/_/api/threads",
        {
            "artifact": "demo/shot",
            "sub_path": "",
            "body": "A feedback",
            "files": SimpleUploadedFile("note.html", b"<script>1</script>", content_type="text/html"),
        },
    )

    assert response.status_code == 400
    assert response.json()["reason"] == "bad_upload_extension"


def test_app_routes_use_app_csp_and_never_artifact_csp(
    client: Client,
    roots: tuple[Path, Path, Path],
) -> None:
    """SPA, health, and JSON API routes carry only APP_CSP."""
    _, _, spa_root = roots
    (spa_root / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")

    responses = [
        client.get("/"),
        client.get("/_/health"),
        client.get("/_/api/settings"),
        client.get("/_/api/artifacts"),
        client.get("/_/api/threads?artifact=demo%2Fshot"),
    ]

    for response in responses:
        assert response.status_code == 200
        _assert_app_security_headers(response)


def test_threads_filter_by_required_artifact_and_echo_scope(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Thread listing is scoped by the public artifact query parameter."""
    del roots
    first = client.post(
        "/_/api/threads",
        {
            "artifact": "artifact/A",
            "sub_path": "",
            "body": "A feedback",
            "files": SimpleUploadedFile("note.txt", b"note", content_type="text/plain"),
        },
    )
    second = client.post(
        "/_/api/threads",
        {
            "artifact": "artifact/B",
            "sub_path": "",
            "body": "B feedback",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get("/_/api/threads?artifact=artifact/A")

    assert response.status_code == 200
    data = response.json()
    assert list(data.keys()) == ["artifact_id", "sub_path", "threads"]
    assert data["artifact_id"] == "artifact/A"
    assert data["sub_path"] == ""
    assert [thread["id"] for thread in data["threads"]] == [first.json()["thread_id"]]
    thread = data["threads"][0]
    assert list(thread.keys()) == [
        "id",
        "sub_path",
        "anchor_kind",
        "anchor",
        "resolved",
        "author",
        "created_at",
        "created_at_iso",
        "bd_ticket",
        "replies",
    ]
    reply = thread["replies"][0]
    assert list(reply.keys()) == ["id", "body", "author", "created_at", "created_at_iso", "uploads"]
    upload = reply["uploads"][0]
    assert list(upload.keys()) == ["id", "filename", "stored_path", "mime", "size", "created_at", "created_at_iso"]


def test_threads_requires_artifact_query(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Unscoped thread listing is rejected."""
    del roots
    response = client.get("/_/api/threads")

    assert response.status_code == 400
    assert response.json()["reason"] == "artifact_required"


def test_feedback_mutation_response_keys_match_contract(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Mutation endpoints return the top-level keys validated by clients."""
    del roots
    create_thread = client.post(
        "/_/api/threads",
        {
            "artifact": "artifact/A",
            "sub_path": "",
            "body": "Thread body",
            "anchor_kind": "page",
            "files": SimpleUploadedFile("thread.txt", b"thread", content_type="text/plain"),
        },
    )
    assert create_thread.status_code == 201
    assert list(create_thread.json().keys()) == [
        "thread_id",
        "reply_id",
        "artifact_id",
        "sub_path",
        "anchor_kind",
        "uploads",
    ]
    assert list(create_thread.json()["uploads"][0].keys()) == [
        "id",
        "filename",
        "stored_path",
        "mime",
        "size",
        "created_at",
        "created_at_iso",
    ]

    thread_id = create_thread.json()["thread_id"]
    create_reply = client.post(
        f"/_/api/threads/{thread_id}/replies",
        {
            "body": "Reply body",
            "files": SimpleUploadedFile("reply.txt", b"reply", content_type="text/plain"),
        },
    )
    assert create_reply.status_code == 201
    assert list(create_reply.json().keys()) == ["reply_id", "thread_id", "uploads"]
    assert list(create_reply.json()["uploads"][0].keys()) == [
        "id",
        "filename",
        "stored_path",
        "mime",
        "size",
        "created_at",
        "created_at_iso",
    ]

    resolve = client.post(
        f"/_/api/threads/{thread_id}/resolve",
        {"resolved": True},
        content_type="application/json",
    )
    assert resolve.status_code == 200
    assert list(resolve.json().keys()) == ["id", "resolved"]


def test_artifacts_response_keys_match_contract(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Artifact listing returns the top-level keys validated by clients."""
    del roots
    publish = _publish(client, {"index.html": b"<h1>ok</h1>"})
    assert publish.status_code == 201

    response = client.get("/_/api/artifacts")

    assert response.status_code == 200
    data = response.json()
    assert list(data.keys()) == ["artifacts"]
    artifact = data["artifacts"][0]
    assert list(artifact.keys()) == [
        "project",
        "subdir",
        "artifact_id",
        "last_pushed",
        "last_pushed_iso",
        "entry_count",
    ]
    assert artifact["project"] == "demo"
    assert artifact["subdir"] == "shot"
    assert artifact["artifact_id"] == "demo/shot"
    assert isinstance(artifact["last_pushed"], int)
    assert artifact["last_pushed_iso"].endswith("Z")
    assert artifact["entry_count"] == 1


def test_publish_unexpected_exception_returns_json_error(
    client: Client,
    roots: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected exception in publish returns JSON 500, not HTML."""
    def raise_unexpected(project: str, subdir: str, artifact_id: str, archive_bytes: bytes) -> dict:
        del project, subdir, artifact_id, archive_bytes
        raise RuntimeError("unexpected database error")

    monkeypatch.setattr(views_api, "_publish_archive", raise_unexpected)
    response = _publish(client, {"index.html": b"test"})

    assert response.status_code == 500
    assert response.headers["Content-Type"] == "application/json"
    assert response.json()["reason"] == "internal_error"
    assert "traceback" not in response.text.lower()
    assert "RuntimeError" not in response.text


def test_disallowed_host_returns_400_with_security_headers() -> None:
    """DisallowedHost errors carry security headers."""
    client = Client()
    response = client.get("/_/health", HTTP_HOST="evil.example")

    assert response.status_code == 400
    _assert_app_security_headers(response)


def test_method_not_allowed_carries_security_headers() -> None:
    """Method not allowed responses carry security headers."""
    client = Client()
    response = client.delete("/_/api/threads")

    assert response.status_code == 405
    _assert_app_security_headers(response)


def _publish(
    client: Client,
    members: dict[str, bytes],
    project: str = "demo",
    subdir: str = "shot",
    extra: dict[str, str] | None = None,
):
    archive = _tar_bytes(members)
    data = {"project": project, "as": subdir, "archive": archive}
    if extra:
        data.update(extra)
    return client.post("/_/api/publish", data)


def _tar_bytes(members: dict[str, bytes]) -> io.BytesIO:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name, body in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            tar.addfile(member, io.BytesIO(body))
    archive.seek(0)
    archive.name = "artifact.tar"
    return archive


def _assert_artifact_security_headers(response: HttpResponse) -> None:
    csp = response.headers["Content-Security-Policy"]
    assert csp == ARTIFACT_CSP
    assert _csp_directive_present(csp, "sandbox")
    assert "script-src 'none'" in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert "Permissions-Policy" in response.headers
    assert response.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in response.headers
    assert csp != APP_CSP


def _assert_app_security_headers(response: HttpResponse) -> None:
    csp = response.headers["Content-Security-Policy"]
    assert csp == APP_CSP
    assert csp != ARTIFACT_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert "Permissions-Policy" in response.headers
    assert response.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in response.headers


def _csp_directive_present(csp: str, directive: str) -> bool:
    return directive in {part.strip() for part in csp.split(";")}
