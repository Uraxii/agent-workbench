"""Django settings for the artifact review backend."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "artifact-review-development-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

REVIEW_SERVE_HOST = os.environ.get("REVIEW_SERVE_HOST", "127.0.0.1")
REVIEW_SERVE_PORT = int(os.environ.get("REVIEW_SERVE_PORT", "9099"))
REVIEW_SERVE_STAGE_ROOT = Path(os.environ.get("REVIEW_SERVE_STAGE_ROOT", "/tmp/claude-artifacts")).expanduser()
REVIEW_SERVE_FEEDBACK_ROOT = Path(
    os.environ.get("REVIEW_SERVE_FEEDBACK_ROOT", "~/.local/share/claude-artifacts")
).expanduser()
REVIEW_SERVE_SPA_ROOT = Path(os.environ.get("REVIEW_SERVE_SPA_ROOT", str(BASE_DIR / "spa"))).expanduser()
REVIEW_SERVE_ASSETS_ROOT = Path(
    os.environ.get("REVIEW_SERVE_ASSETS_ROOT", str(BASE_DIR / "artifact_review" / "assets"))
).expanduser()
REVIEW_SERVE_PUBLISH_ENABLED = os.environ.get("REVIEW_SERVE_PUBLISH_ENABLED", "0")

ALLOWED_HOSTS = [REVIEW_SERVE_HOST, "127.0.0.1", "localhost", "testserver"]
ROOT_URLCONF = "artifact_review_site.urls"
WSGI_APPLICATION = "artifact_review_site.wsgi.application"
ASGI_APPLICATION = "artifact_review_site.asgi.application"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "artifact_review",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(REVIEW_SERVE_FEEDBACK_ROOT / "feedback.db"),
        "OPTIONS": {"timeout": 10},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"

__all__ = [
    "ALLOWED_HOSTS",
    "ASGI_APPLICATION",
    "BASE_DIR",
    "DATABASES",
    "DEBUG",
    "DEFAULT_AUTO_FIELD",
    "INSTALLED_APPS",
    "MIDDLEWARE",
    "REVIEW_SERVE_ASSETS_ROOT",
    "REVIEW_SERVE_FEEDBACK_ROOT",
    "REVIEW_SERVE_HOST",
    "REVIEW_SERVE_PORT",
    "REVIEW_SERVE_PUBLISH_ENABLED",
    "REVIEW_SERVE_SPA_ROOT",
    "REVIEW_SERVE_STAGE_ROOT",
    "ROOT_URLCONF",
    "SECRET_KEY",
    "STATIC_URL",
    "TIME_ZONE",
    "USE_TZ",
    "WSGI_APPLICATION",
]
