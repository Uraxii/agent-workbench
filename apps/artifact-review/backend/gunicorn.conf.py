"""Gunicorn settings for the artifact review service."""

from __future__ import annotations

import os

DEFAULT_PORT = "9099"

bind = f"0.0.0.0:{os.environ.get('ARTIFACT_SERVE_PORT', DEFAULT_PORT)}"
workers = 4
accesslog = "-"
