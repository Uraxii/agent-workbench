"""Apply artifact response security headers."""

from __future__ import annotations

from django.http import HttpResponse

ARTIFACT_CSP = "sandbox; default-src 'none'; script-src 'none'; object-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src 'self' data:; media-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
APP_CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"

INLINE_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
        "image/webp",
        "text/css",
        "text/html",
        "text/plain",
    }
)


def apply_artifact_headers(response: HttpResponse) -> HttpResponse:
    """Apply restrictive headers for untrusted artifact bytes."""
    response["Content-Security-Policy"] = ARTIFACT_CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    response["X-Frame-Options"] = "SAMEORIGIN"
    content_type = response.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type not in INLINE_CONTENT_TYPES:
        response["Content-Disposition"] = "attachment"
    return response


def apply_app_headers(response: HttpResponse) -> HttpResponse:
    """Apply SPA and JSON API headers."""
    response["Content-Security-Policy"] = APP_CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


__all__ = ["APP_CSP", "ARTIFACT_CSP", "INLINE_CONTENT_TYPES", "apply_app_headers", "apply_artifact_headers"]
