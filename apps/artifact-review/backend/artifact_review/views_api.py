"""API view stubs for the artifact review backend."""
# TODO(slice-2): replace API stubs with feedback database and upload behavior.

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse


def not_implemented_response() -> JsonResponse:
    """Return the skeleton response for routes outside the health slice."""
    return JsonResponse({"error": "not implemented"}, status=501)


def api_settings(request: HttpRequest) -> JsonResponse:
    """Return stored review server settings."""
    return not_implemented_response()


def api_upload(request: HttpRequest, id: int) -> JsonResponse:
    """Return stored upload bytes."""
    return not_implemented_response()


def api_threads(request: HttpRequest) -> JsonResponse:
    """List feedback threads for an artifact."""
    return not_implemented_response()


def api_create_thread(request: HttpRequest) -> JsonResponse:
    """Create a feedback thread."""
    return not_implemented_response()


def api_create_reply(request: HttpRequest, id: int) -> JsonResponse:
    """Create a reply for a thread."""
    return not_implemented_response()


def api_resolve_thread(request: HttpRequest, id: int) -> JsonResponse:
    """Resolve or reopen a thread."""
    return not_implemented_response()


def api_comments(request: HttpRequest) -> JsonResponse:
    """List legacy page comments."""
    return not_implemented_response()


def api_create_comment(request: HttpRequest) -> JsonResponse:
    """Create a legacy page comment."""
    return not_implemented_response()


def api_publish(request: HttpRequest) -> JsonResponse:
    """Handle the disabled HTTP publish route."""
    return not_implemented_response()


__all__ = [
    "api_comments",
    "api_create_comment",
    "api_create_reply",
    "api_create_thread",
    "api_publish",
    "api_resolve_thread",
    "api_settings",
    "api_threads",
    "api_upload",
    "not_implemented_response",
]
