"""Validate multipart feedback requests."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest
from django.utils.datastructures import MultiValueDict

from artifact_review.upload_validation import MAX_UPLOAD_COUNT, validate_feedback_upload


def request_data(request: HttpRequest) -> dict[str, Any]:
    """Return JSON or form data as a plain dict."""
    if request.content_type.split(";", 1)[0] == "application/json":
        if not request.body:
            return {}
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json_object_required")
        return data
    return request.POST.dict()


def require_text(data: dict[str, Any], name: str) -> str:
    """Return a required non-empty text field."""
    value = str(data.get(name, "")).strip()
    if not value:
        raise ValueError(f"{name}_required")
    return value


def require_artifact(data: dict[str, Any]) -> str:
    """Return the required artifact id from the public API field."""
    value = str(data.get("artifact", data.get("artifact_id", ""))).strip()
    if not value:
        raise ValueError("artifact_required")
    return value


def optional_text(data: dict[str, Any], name: str, default: str = "") -> str:
    """Return an optional text field."""
    value = data.get(name, default)
    return "" if value is None else str(value)


def validated_upload_names(files: MultiValueDict[str, object]) -> list[tuple[str, str]]:
    """Validate uploaded feedback file names and sizes."""
    uploads = files.getlist("uploads") + files.getlist("files") + files.getlist("file")
    if len(uploads) > MAX_UPLOAD_COUNT:
        raise ValueError("too_many_uploads")

    validated: list[tuple[str, str]] = []
    for upload in uploads:
        name = getattr(upload, "name", "")
        size = int(getattr(upload, "size", 0))
        content_type = str(getattr(upload, "content_type", ""))
        validated.append((name, validate_feedback_upload(name, size, content_type)))
    return validated


__all__ = ["optional_text", "request_data", "require_artifact", "require_text", "validated_upload_names"]
