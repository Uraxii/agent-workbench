"""Resolve staged artifact filesystem paths."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate_name(name: str) -> str:
    """Return a validated project or subdir name."""
    if not NAME_RE.fullmatch(name):
        raise ValueError("invalid name")
    return name


def stage_root() -> Path:
    """Return the configured staged artifact root."""
    return settings.ARTIFACT_SVC_STAGE_ROOT


def feedback_root() -> Path:
    """Return the configured feedback storage root."""
    return settings.ARTIFACT_SVC_FEEDBACK_ROOT


def safe_join(root: Path, relative: str) -> Path:
    """Resolve a path beneath root and reject containment escapes."""
    root_path = root.resolve()
    target_path = (root_path / relative).resolve()
    if not target_path.is_relative_to(root_path):
        raise ValueError("path escapes root")
    return target_path


__all__ = ["NAME_RE", "feedback_root", "safe_join", "stage_root", "validate_name"]
