"""ASGI config for the artifact review backend."""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "artifact_review_site.settings")

application = get_asgi_application()

__all__ = ["application"]
