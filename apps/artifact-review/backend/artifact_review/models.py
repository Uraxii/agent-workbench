"""Unmanaged models for the existing artifact feedback database."""

from __future__ import annotations

from django.db import models


class ArtifactIndex(models.Model):
    """A staged artifact path mapped to its stable artifact identity."""

    pk = models.CompositePrimaryKey("project", "subdir")
    project = models.TextField()
    subdir = models.TextField()
    artifact_id = models.TextField()
    src_path = models.TextField()
    last_pushed = models.IntegerField()

    class Meta:
        managed = False
        db_table = "artifact_index"
        indexes = [models.Index(fields=["artifact_id"], name="idx_index_artifact")]


class LegacyComment(models.Model):
    """Legacy flat page comment row kept for compatibility."""

    id = models.AutoField(primary_key=True)
    artifact_id = models.TextField()
    sub_path = models.TextField(default="")
    body = models.TextField()
    author = models.TextField(null=True, blank=True)
    created_at = models.IntegerField()

    class Meta:
        managed = False
        db_table = "comment"
        indexes = [models.Index(fields=["artifact_id", "sub_path"], name="idx_comment_artifact_path")]


class Setting(models.Model):
    """Feedback database key-value setting."""

    key = models.TextField(primary_key=True)
    value = models.TextField()

    class Meta:
        managed = False
        db_table = "setting"


class Thread(models.Model):
    """Feedback discussion thread anchored to a page, image region, or code line."""

    id = models.AutoField(primary_key=True)
    artifact_id = models.TextField()
    sub_path = models.TextField(default="")
    anchor_kind = models.TextField(default="page")
    anchor_data = models.TextField(null=True, blank=True)
    resolved = models.IntegerField(default=0)
    author = models.TextField(null=True, blank=True)
    created_at = models.IntegerField()
    bd_ticket = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "thread"
        indexes = [models.Index(fields=["artifact_id", "sub_path"], name="idx_thread_artifact_path")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(anchor_kind__in=["page", "image_region", "code_line"]),
                name="thread_anchor_kind_valid",
            ),
            models.CheckConstraint(condition=models.Q(resolved__in=[0, 1]), name="thread_resolved_bool"),
        ]


class Reply(models.Model):
    """A reply in a feedback thread."""

    id = models.AutoField(primary_key=True)
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField()
    author = models.TextField(null=True, blank=True)
    created_at = models.IntegerField()

    class Meta:
        managed = False
        db_table = "reply"
        indexes = [models.Index(fields=["thread"], name="idx_reply_thread")]


class Upload(models.Model):
    """Uploaded file attached to a reply or legacy comment."""

    id = models.AutoField(primary_key=True)
    reply = models.ForeignKey(Reply, on_delete=models.CASCADE, null=True, blank=True, related_name="uploads")
    comment_id = models.IntegerField(null=True, blank=True)
    filename = models.TextField()
    stored_path = models.TextField()
    mime = models.TextField(null=True, blank=True)
    size = models.IntegerField()
    created_at = models.IntegerField()

    class Meta:
        managed = False
        db_table = "upload"
        indexes = [
            models.Index(fields=["reply"], name="idx_upload_reply"),
            models.Index(fields=["comment_id"], name="idx_upload_comment"),
        ]


__all__ = [
    "ArtifactIndex",
    "LegacyComment",
    "Reply",
    "Setting",
    "Thread",
    "Upload",
]
