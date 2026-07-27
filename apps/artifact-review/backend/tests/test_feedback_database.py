"""Unit tests for feedback database model mapping."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class FeedbackDatabaseModelTest(unittest.TestCase):
    """Prove unmanaged models write through the v2 sqlite schema."""

    feedback_root: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.feedback_root = tempfile.TemporaryDirectory()
        os.environ["DJANGO_SETTINGS_MODULE"] = "artifact_review_site.settings"
        os.environ["REVIEW_SERVE_FEEDBACK_ROOT"] = cls.feedback_root.name

        import django

        django.setup()

        from artifact_review.feedback_database import ensure_feedback_schema

        ensure_feedback_schema()

    @classmethod
    def tearDownClass(cls) -> None:
        from django.db import connection

        connection.close()
        cls.feedback_root.cleanup()
        super().tearDownClass()

    def test_unmanaged_models_match_feedback_schema_v2(self) -> None:
        from django.db import connection

        from artifact_review.models import ArtifactIndex, Reply, Setting, Thread, Upload

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

        self.assertEqual(fetched_thread.anchor_kind, "image_region")
        self.assertEqual(fetched_reply.body, "looks good")
        self.assertEqual(fetched_upload.filename, "note.txt")
        self.assertFalse(ArtifactIndex._meta.managed)
        self.assertEqual(Setting.objects.get(key="schema_version").value, "2")

        expected_thread_columns = [
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
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(thread)")
            thread_columns = [row[1] for row in cursor.fetchall()]
        self.assertEqual(thread_columns, expected_thread_columns)


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    del loader, pattern
    return tests


if __name__ == "__main__":
    unittest.main()
