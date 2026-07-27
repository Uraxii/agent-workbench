"""Serialize feedback rows to JSON shapes."""

from __future__ import annotations

from dataclasses import asdict
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
        "reply_id": upload.reply_id,
        "filename": upload.filename,
        "mime": upload.mime,
        "size": upload.size,
        "url": f"/_/api/uploads/{upload.id}",
        "created_at": upload.created_at,
    }


def reply_to_json(reply: Reply) -> dict[str, Any]:
    """Serialize a reply row."""
    uploads = list(getattr(reply, "uploads").all()) if reply.id else []
    return {
        "id": reply.id,
        "thread_id": reply.thread_id,
        "body": reply.body,
        "author": reply.author,
        "created_at": reply.created_at,
        "uploads": [upload_to_json(upload) for upload in uploads],
    }


def thread_to_json(thread: Thread) -> dict[str, Any]:
    """Serialize a thread with nested replies."""
    replies = list(getattr(thread, "replies").all()) if thread.id else []
    return {
        "id": thread.id,
        "artifact_id": thread.artifact_id,
        "sub_path": thread.sub_path,
        "anchor_kind": thread.anchor_kind,
        "anchor_data": thread.anchor_data,
        "resolved": bool(thread.resolved),
        "author": thread.author,
        "created_at": thread.created_at,
        "bd_ticket": thread.bd_ticket,
        "replies": [reply_to_json(reply) for reply in replies],
    }


def artifact_to_json(artifact: ArtifactSummary) -> dict[str, Any]:
    """Serialize an artifact summary."""
    return asdict(artifact)


__all__ = ["artifact_to_json", "reply_to_json", "setting_map", "thread_to_json", "upload_to_json"]
