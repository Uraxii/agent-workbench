"""Review page view stubs for the artifact review backend."""
# TODO(slice-5): render gallery, image review, code review, and future tile responses.

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from artifact_review.views_api import not_implemented_response


def review_page(request: HttpRequest) -> JsonResponse:
    """Render an artifact review page."""
    return not_implemented_response()


def deep_zoom_tile(request: HttpRequest, artifact: str, tile_path: str) -> JsonResponse:
    """Return a future deep zoom tile response."""
    return not_implemented_response()


__all__ = ["deep_zoom_tile", "review_page"]
