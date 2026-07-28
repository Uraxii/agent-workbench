"""API views for the artifact review backend."""

from __future__ import annotations

import io
import json
import logging
import shutil
import tarfile
import time
import uuid
from pathlib import Path
from typing import Any

from django.db import connection, transaction
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse

from artifact_review import artifact_paths, artifact_resolution, feedback_forms, feedback_json, publish_policy, ssrf_guard
from artifact_review.feedback_database import ensure_feedback_schema
from artifact_review.models import Reply, Setting, Thread, Upload
from artifact_review.response_headers import apply_app_headers, apply_artifact_headers
from artifact_review.upload_validation import validate_archive_member

logger = logging.getLogger(__name__)


def api_settings(request: HttpRequest) -> JsonResponse:
    """Return stored review server settings."""
    ensure_feedback_schema()
    rows = list(Setting.objects.order_by("key"))
    return apply_app_headers(JsonResponse({"settings": feedback_json.setting_map(rows)}))


def api_upload(request: HttpRequest, id: int) -> HttpResponse:
    """Return stored upload bytes."""
    ensure_feedback_schema()
    upload = Upload.objects.filter(id=id).first()
    if upload is None:
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    try:
        path = artifact_paths.safe_join(artifact_paths.feedback_root(), upload.stored_path)
    except ValueError:
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    if not path.is_file():
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    response = FileResponse(path.open("rb"), content_type=upload.mime or "application/octet-stream")
    return apply_artifact_headers(response)


def api_threads(request: HttpRequest) -> JsonResponse:
    """List feedback threads for an artifact."""
    ensure_feedback_schema()
    artifact_id = request.GET.get("artifact", "").strip()
    if not artifact_id:
        return _json_error("artifact_required", 400)
    sub_path = request.GET.get("sub_path", "")
    queryset = (
        Thread.objects.prefetch_related("replies__uploads")
        .filter(artifact_id=artifact_id, sub_path=sub_path)
        .order_by("created_at", "id")
    )
    return apply_app_headers(
        JsonResponse(
            {
                "artifact_id": artifact_id,
                "sub_path": sub_path,
                "threads": [feedback_json.thread_to_json(thread) for thread in queryset],
            }
        )
    )


def api_create_thread(request: HttpRequest) -> JsonResponse:
    """Create a feedback thread."""
    ensure_feedback_schema()
    try:
        data = feedback_forms.request_data(request)
        now = _now()
        with transaction.atomic():
            thread = Thread.objects.create(
                artifact_id=feedback_forms.require_artifact(data),
                sub_path=feedback_forms.optional_text(data, "sub_path"),
                anchor_kind=feedback_forms.optional_text(data, "anchor_kind", "page"),
                anchor_data=_json_text(data.get("anchor_data")),
                resolved=0,
                author=feedback_forms.optional_text(data, "author") or None,
                created_at=now,
            )
            reply = Reply.objects.create(
                thread=thread,
                body=feedback_forms.require_text(data, "body"),
                author=feedback_forms.optional_text(data, "author") or None,
                created_at=now,
            )
            _store_feedback_uploads(request, reply)
        reply = Reply.objects.prefetch_related("uploads").get(id=reply.id)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 400)
    return apply_app_headers(
        JsonResponse(
            {
                "thread_id": thread.id,
                "reply_id": reply.id,
                "artifact_id": thread.artifact_id,
                "sub_path": thread.sub_path,
                "anchor_kind": thread.anchor_kind,
                "uploads": [feedback_json.upload_to_json(upload) for upload in reply.uploads.all()],
            },
            status=201,
        )
    )


def api_create_reply(request: HttpRequest, id: int) -> JsonResponse:
    """Create a reply for a thread."""
    ensure_feedback_schema()
    thread = Thread.objects.filter(id=id).first()
    if thread is None:
        return _json_error("not_found", 404)
    try:
        data = feedback_forms.request_data(request)
        with transaction.atomic():
            reply = Reply.objects.create(
                thread=thread,
                body=feedback_forms.require_text(data, "body"),
                author=feedback_forms.optional_text(data, "author") or None,
                created_at=_now(),
            )
            _store_feedback_uploads(request, reply)
        reply = Reply.objects.prefetch_related("uploads").get(id=reply.id)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 400)
    return apply_app_headers(
        JsonResponse(
            {
                "reply_id": reply.id,
                "thread_id": thread.id,
                "uploads": [feedback_json.upload_to_json(upload) for upload in reply.uploads.all()],
            },
            status=201,
        )
    )


def api_resolve_thread(request: HttpRequest, id: int) -> JsonResponse:
    """Resolve or reopen a thread."""
    ensure_feedback_schema()
    thread = Thread.objects.filter(id=id).first()
    if thread is None:
        return _json_error("not_found", 404)
    try:
        data = feedback_forms.request_data(request)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 400)
    resolved = data.get("resolved", True)
    thread.resolved = 1 if resolved in {True, "true", "1", 1} else 0
    thread.save(update_fields=["resolved"])
    return apply_app_headers(JsonResponse({"id": thread.id, "resolved": bool(thread.resolved)}))


def api_artifacts(request: HttpRequest) -> JsonResponse:
    """List staged artifacts."""
    artifacts = [feedback_json.artifact_to_json(artifact) for artifact in artifact_resolution.list_artifacts()]
    return apply_app_headers(JsonResponse({"artifacts": artifacts}))


def api_publish(request: HttpRequest) -> JsonResponse:
    """Publish a tar archive into the artifact store."""
    try:
        ssrf_guard.reject_remote_fetch(request)
        publish_policy.check(request)
        archive = request.FILES.get("archive")
        if archive is None:
            return _json_error("archive_required", 400)
        project = artifact_paths.validate_name(request.POST["project"])
        subdir = artifact_paths.validate_name(request.POST["as"])
        destination = artifact_paths.safe_join(artifact_paths.stage_root(), f"{project}/{subdir}")
        try:
            result = _publish_archive(
                project=project,
                subdir=subdir,
                artifact_id=request.POST.get("artifact_id") or f"{request.POST['project']}/{request.POST['as']}",
                archive_bytes=archive.read(),
            )
        except OSError as exc:
            logger.error("Publish write failed for %s: %s", destination, exc)
            return apply_app_headers(
                JsonResponse(
                    {
                        "error": "publish write failed",
                        "reason": "publish_write_failed",
                        "detail": str(exc),
                    },
                    status=500,
                )
            )
    except ssrf_guard.RemoteFetchRejected:
        return _json_error("remote_fetch_rejected", 400)
    except publish_policy.PublishPolicyError as exc:
        return _json_error(exc.reason, exc.status)
    except (tarfile.TarError, ValueError) as exc:
        return _json_error(str(exc), 400)
    except Exception as exc:
        logger.exception("Unexpected error in publish")
        return apply_app_headers(
            JsonResponse(
                {"error": "server error", "reason": "internal_error"},
                status=500,
            )
        )
    return apply_app_headers(JsonResponse(result, status=201))


def _publish_archive(project: str, subdir: str, artifact_id: str, archive_bytes: bytes) -> dict[str, Any]:
    ensure_feedback_schema()
    stage_root = artifact_paths.stage_root()
    stage_root.mkdir(parents=True, exist_ok=True)
    temp_path = artifact_paths.safe_join(stage_root, f".publish-{uuid.uuid4().hex}")
    temp_path.mkdir(parents=True)
    files = 0
    bytes_written = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            for member in archive:
                validate_archive_member(member)
                destination = artifact_paths.safe_join(temp_path, member.name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                parent = artifact_paths.safe_join(temp_path, str(destination.relative_to(temp_path).parent))
                parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("bad_member")
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                files += 1
                bytes_written += member.size
        if files == 0:
            raise ValueError("empty_archive")
        _swap_published_tree(stage_root, project, subdir, temp_path, artifact_id)
    except Exception:
        shutil.rmtree(temp_path, ignore_errors=True)
        raise

    return {
        "artifact_id": artifact_id,
        "project": project,
        "subdir": subdir,
        "files": files,
        "bytes": bytes_written,
        "url": f"/{project}/{subdir}/",
    }


def _swap_published_tree(stage_root: Path, project: str, subdir: str, temp_path: Path, artifact_id: str) -> None:
    project_path = artifact_paths.safe_join(stage_root, project)
    project_path.mkdir(parents=True, exist_ok=True)
    destination = artifact_paths.safe_join(stage_root, f"{project}/{subdir}")
    backup_path = artifact_paths.safe_join(stage_root, f".old-{uuid.uuid4().hex}")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO artifact_index (project, subdir, artifact_id, src_path, last_pushed) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project, subdir) DO UPDATE SET "
                "artifact_id=excluded.artifact_id, src_path=excluded.src_path, last_pushed=excluded.last_pushed",
                [project, subdir, artifact_id, str(destination), _now()],
            )
        replaced = destination.exists()
        if replaced:
            destination.rename(backup_path)
        try:
            temp_path.rename(destination)
        except Exception:
            if replaced:
                backup_path.rename(destination)
            raise
        shutil.rmtree(backup_path, ignore_errors=True)


def _store_feedback_uploads(request: HttpRequest, reply: Reply) -> None:
    validated_names = feedback_forms.validated_upload_names(request.FILES)
    uploads = request.FILES.getlist("uploads") + request.FILES.getlist("files") + request.FILES.getlist("file")
    upload_root = artifact_paths.safe_join(artifact_paths.feedback_root(), f"uploads/{reply.id}")
    upload_root.mkdir(parents=True, exist_ok=True)
    for upload, (_, sanitized_name) in zip(uploads, validated_names, strict=True):
        destination = artifact_paths.safe_join(upload_root, sanitized_name)
        with destination.open("wb") as output:
            for chunk in upload.chunks():
                output.write(chunk)
        Upload.objects.create(
            reply=reply,
            filename=sanitized_name,
            stored_path=f"uploads/{reply.id}/{sanitized_name}",
            mime=getattr(upload, "content_type", "") or None,
            size=int(getattr(upload, "size", 0)),
            created_at=_now(),
        )


def _json_error(reason: str, status: int) -> JsonResponse:
    return apply_app_headers(JsonResponse({"error": reason, "reason": reason}, status=status))


def _json_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"))


def _now() -> int:
    return int(time.time())


__all__ = [
    "api_artifacts",
    "api_create_reply",
    "api_create_thread",
    "api_publish",
    "api_resolve_thread",
    "api_settings",
    "api_threads",
    "api_upload",
]
