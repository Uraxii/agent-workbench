"""Backend publish, schema, and response security tests."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from django.db import connection
from django.test import Client, override_settings

from artifact_review import artifact_paths
from artifact_review.feedback_database import ensure_feedback_schema
from artifact_review.models import ArtifactIndex, Reply, Setting, Thread, Upload
from artifact_review.response_headers import APP_CSP, ARTIFACT_CSP
from artifact_review.upload_validation import MAX_ARCHIVE_BYTES


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Ensure unmanaged sqlite tables exist and start empty."""
    ensure_feedback_schema()
    Upload.objects.all().delete()
    Reply.objects.all().delete()
    Thread.objects.all().delete()
    ArtifactIndex.objects.all().delete()
    Setting.objects.exclude(key="schema_version").delete()


@pytest.fixture
def roots(tmp_path: Path):
    """Provide isolated configured roots."""
    stage_root = tmp_path / "stage"
    feedback_root = tmp_path / "feedback"
    spa_root = tmp_path / "spa"
    stage_root.mkdir()
    feedback_root.mkdir()
    spa_root.mkdir()
    with override_settings(
        ARTIFACT_SERVE_STAGE_ROOT=stage_root,
        ARTIFACT_SERVE_FEEDBACK_ROOT=feedback_root,
        ARTIFACT_SERVE_SPA_ROOT=spa_root,
        ARTIFACT_SERVE_PUBLISH_ENABLED="1",
    ):
        yield stage_root, feedback_root, spa_root


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


def test_publish_rejects_oversize_archive(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Content-Length larger than the archive limit is rejected before publish."""
    archive = io.BytesIO(b"not a tar")
    archive.name = "artifact.tar"
    response = client.post(
        "/_/api/publish",
        {"project": "demo", "as": "shot", "archive": archive},
        CONTENT_LENGTH=str(MAX_ARCHIVE_BYTES + 1),
    )

    assert response.status_code == 413
    assert response.json()["reason"] == "archive_too_large"


def test_publish_rejects_bad_project_name(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Project names must match the conservative name regex."""
    response = _publish(client, {"index.html": b"x"}, project="../bad")

    assert response.status_code == 400
    assert response.json()["reason"] == "bad_artifact_name"


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
    assert response.headers["Content-Security-Policy"] == APP_CSP


def test_root_returns_spa_shell_when_present(client: Client, roots: tuple[Path, Path, Path]) -> None:
    """Present SPA bundle is served as the app shell."""
    _, _, spa_root = roots
    (spa_root / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")

    response = client.get("/")

    assert response.status_code == 200
    assert b"<div id=\"root\"></div>" in b"".join(response.streaming_content)
    assert response.headers["Content-Security-Policy"] == APP_CSP


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
    assert "sandbox" in response.headers["Content-Security-Policy"]
    assert "script-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_app_routes_use_app_csp_and_artifact_routes_do_not(
    client: Client,
    roots: tuple[Path, Path, Path],
) -> None:
    """App JSON routes carry APP_CSP and artifact routes carry ARTIFACT_CSP."""
    publish_response = _publish(client, {"index.html": b"<h1>ok</h1>"})
    assert publish_response.status_code == 201

    app_response = client.get("/_/health")
    artifact_response = client.get("/demo/shot/index.html")

    assert app_response.headers["Content-Security-Policy"] == APP_CSP
    assert artifact_response.headers["Content-Security-Policy"] == ARTIFACT_CSP
    assert artifact_response.headers["Content-Security-Policy"] != APP_CSP


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
