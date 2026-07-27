"""WSGI config for the artifact review backend."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "artifact_review_site.settings")

application = get_wsgi_application()

__all__ = ["application"]
