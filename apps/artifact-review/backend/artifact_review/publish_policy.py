"""Enforce the HTTP publish policy, enabled by default for the container writer."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest

from artifact_review import artifact_paths
from artifact_review.upload_validation import MAX_ARCHIVE_BYTES


@dataclass(frozen=True)
class PublishPolicyError(Exception):
    """A publish rejection with an HTTP status and machine reason."""

    status: int
    reason: str


def check(request: HttpRequest) -> None:
    """Validate publish request metadata before artifact bytes are written."""
    if settings.ARTIFACT_SVC_PUBLISH_ENABLED != "1":
        raise PublishPolicyError(403, "publish_disabled")
    if request.method != "POST":
        raise PublishPolicyError(405, "method_not_allowed")

    content_length = request.headers.get("Content-Length")
    if content_length is None:
        raise PublishPolicyError(411, "content_length_required")
    try:
        byte_count = int(content_length)
    except ValueError as exc:
        raise PublishPolicyError(400, "bad_content_length") from exc
    if byte_count < 0 or byte_count > MAX_ARCHIVE_BYTES:
        raise PublishPolicyError(413, "archive_too_large")

    content_type = request.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/"):
        raise PublishPolicyError(415, "multipart_required")

    try:
        artifact_paths.validate_name(request.POST.get("project", ""))
        artifact_paths.validate_name(request.POST.get("as", ""))
    except ValueError as exc:
        raise PublishPolicyError(400, "bad_artifact_name") from exc


__all__ = ["PublishPolicyError", "check"]
