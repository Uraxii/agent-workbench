"""Django app registration for artifact review."""

from __future__ import annotations

from django.apps import AppConfig


class ArtifactReviewConfig(AppConfig):
    """Configure the artifact review Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "artifact_review"

    def ready(self) -> None:
        """Load connection hooks without touching the database."""
        from artifact_review import feedback_database

        del feedback_database


__all__ = ["ArtifactReviewConfig"]
