"""Serialize feedback rows to JSON shapes."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from artifact_review.artifact_resolution import ArtifactSummary
from artifact_review.models import Reply, Setting, Thread, Upload


def setting_map(rows: list[Setting]) -> dict[str, str]:
    """Serialize settings as a key-value object."""
    return {row.key: row.value for row in rows}


def upload_to_json(upload: Upload) -> dict[str, Any]:
    """Serialize an upload row."""
    return {
        "id": upload.id,
        "filename": upload.filename,
        "stored_path": upload.stored_path,
        "mime": upload.mime,
        "size": upload.size,
        "created_at": upload.created_at,
        "created_at_iso": _created_at_iso(upload.created_at),
    }


def reply_to_json(reply: Reply) -> dict[str, Any]:
    """Serialize a reply row."""
    uploads = list(getattr(reply, "uploads").all()) if reply.id else []
    return {
        "id": reply.id,
        "body": reply.body,
        "author": reply.author,
        "created_at": reply.created_at,
        "created_at_iso": _created_at_iso(reply.created_at),
        "uploads": [upload_to_json(upload) for upload in uploads],
    }


def thread_to_json(thread: Thread) -> dict[str, Any]:
    """Serialize a thread with nested replies."""
    replies = list(getattr(thread, "replies").all()) if thread.id else []
    return {
        "id": thread.id,
        "sub_path": thread.sub_path,
        "anchor_kind": thread.anchor_kind,
        "anchor": _anchor_to_json(thread),
        "resolved": bool(thread.resolved),
        "author": thread.author,
        "created_at": thread.created_at,
        "created_at_iso": _created_at_iso(thread.created_at),
        "bd_ticket": thread.bd_ticket,
        "replies": [reply_to_json(reply) for reply in replies],
    }


def artifact_to_json(artifact: ArtifactSummary) -> dict[str, Any]:
    """Serialize an artifact summary."""
    return {
        "project": artifact.project,
        "subdir": artifact.subdir,
        "artifact_id": artifact.artifact_id,
        "last_pushed": artifact.last_pushed,
        "last_pushed_iso": _created_at_iso(artifact.last_pushed),
        "entry_count": artifact.entry_count,
    }


def _anchor_to_json(thread: Thread) -> Any:
    if thread.anchor_kind == "page" or not thread.anchor_data:
        return None
    return json.loads(thread.anchor_data)


def _created_at_iso(created_at: int) -> str:
    return datetime.fromtimestamp(created_at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["artifact_to_json", "reply_to_json", "setting_map", "thread_to_json", "upload_to_json"]
