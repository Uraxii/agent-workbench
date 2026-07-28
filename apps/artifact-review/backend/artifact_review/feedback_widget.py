"""Small SPA helpers for artifact feedback."""

from __future__ import annotations


def artifact_url(project: str, subdir: str, rel: str = "") -> str:
    """Return the raw artifact URL path."""
    suffix = f"/{rel.lstrip('/')}" if rel else "/"
    return f"/{project}/{subdir}{suffix}"


__all__ = ["artifact_url"]
