"""Static artifact and SPA view stubs for the artifact review backend."""
# TODO(slice-4): serve staged artifacts, vendored assets, SPA files, and galleries.

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse

from artifact_review.views_api import not_implemented_response


def root_index(request: HttpRequest) -> JsonResponse:
    """Return the deployment health response for GET /."""
    return JsonResponse({"status": "ok"})


def vendored_asset(request: HttpRequest, rel: str) -> JsonResponse:
    """Return a vendored review asset."""
    return not_implemented_response()


def static_artifact(
    request: HttpRequest,
    project: str,
    subdir: str,
    rel: str = "",
) -> HttpResponse:
    """Return a staged artifact file or directory gallery."""
    return not_implemented_response()


def spa_asset(request: HttpRequest, rel: str) -> JsonResponse:
    """Return a React SPA asset."""
    return not_implemented_response()


def spa_index(request: HttpRequest, rel: str) -> JsonResponse:
    """Return the React SPA shell for a frontend route."""
    return not_implemented_response()


__all__ = ["root_index", "spa_asset", "spa_index", "static_artifact", "vendored_asset"]
