"""Django settings for the artifact review backend."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or secrets.token_urlsafe(50)
# This service has no sessions, auth, or signed cookies, so an ephemeral key is acceptable.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ARTIFACT_SVC_HOST = os.environ.get("ARTIFACT_SVC_HOST", "127.0.0.1")
ARTIFACT_SVC_PORT = int(os.environ.get("ARTIFACT_SVC_PORT", "9099"))
ARTIFACT_SVC_STAGE_ROOT = Path(
    os.environ.get("ARTIFACT_SVC_STAGE_ROOT", "~/.local/share/artifacts/stage")
).expanduser()
ARTIFACT_SVC_FEEDBACK_ROOT = Path(
    os.environ.get("ARTIFACT_SVC_FEEDBACK_ROOT", "~/.local/share/artifacts")
).expanduser()
ARTIFACT_SVC_SPA_ROOT = Path(os.environ.get("ARTIFACT_SVC_SPA_ROOT", str(BASE_DIR / "spa"))).expanduser()
ARTIFACT_SVC_ASSETS_ROOT = Path(
    os.environ.get("ARTIFACT_SVC_ASSETS_ROOT", str(BASE_DIR / "artifact_review" / "assets"))
).expanduser()
ARTIFACT_SVC_PUBLISH_ENABLED = os.environ.get("ARTIFACT_SVC_PUBLISH_ENABLED", "1")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ARTIFACT_SVC_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if host.strip()
]
ROOT_URLCONF = "artifact_review_site.urls"
WSGI_APPLICATION = "artifact_review_site.wsgi.application"
ASGI_APPLICATION = "artifact_review_site.asgi.application"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "artifact_review",
]

MIDDLEWARE = [
    "artifact_review.response_headers.stamp_security_headers",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(ARTIFACT_SVC_FEEDBACK_ROOT / "feedback.db"),
        "OPTIONS": {"timeout": 10},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
STATIC_URL = "static/"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
X_FRAME_OPTIONS = "DENY"

__all__ = [
    "ALLOWED_HOSTS",
    "ARTIFACT_SVC_ASSETS_ROOT",
    "ARTIFACT_SVC_FEEDBACK_ROOT",
    "ARTIFACT_SVC_HOST",
    "ARTIFACT_SVC_PORT",
    "ARTIFACT_SVC_PUBLISH_ENABLED",
    "ARTIFACT_SVC_SPA_ROOT",
    "ARTIFACT_SVC_STAGE_ROOT",
    "ASGI_APPLICATION",
    "BASE_DIR",
    "DATABASES",
    "DEBUG",
    "DEFAULT_AUTO_FIELD",
    "INSTALLED_APPS",
    "MIDDLEWARE",
    "ROOT_URLCONF",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "SECURE_REFERRER_POLICY",
    "SECRET_KEY",
    "STATIC_URL",
    "TIME_ZONE",
    "USE_TZ",
    "WSGI_APPLICATION",
    "X_FRAME_OPTIONS",
]
