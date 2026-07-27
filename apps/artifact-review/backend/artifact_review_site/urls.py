"""Root URL configuration for the artifact review backend."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("", include("artifact_review.urls")),
]

__all__ = ["urlpatterns"]
