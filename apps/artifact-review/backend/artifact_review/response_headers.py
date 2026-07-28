"""Apply artifact response security headers."""

from __future__ import annotations

from django.http import HttpResponse
from django.http.request import HttpRequest

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


def stamp_security_headers(get_response) -> callable:  # type: ignore[no-untyped-def]
    """Backstop the security baseline onto any response a view never touched."""

    def middleware(request: HttpRequest) -> HttpResponse:
        response = get_response(request)
        response.headers.setdefault("Content-Security-Policy", APP_CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        response.headers["Permissions-Policy"] = "camera=() microphone=() geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        response.headers.pop("Access-Control-Allow-Origin", None)
        return response

    return middleware


def apply_artifact_headers(response: HttpResponse) -> HttpResponse:
    """Apply restrictive headers for untrusted artifact bytes."""
    response["Content-Security-Policy"] = ARTIFACT_CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    response["X-Frame-Options"] = "SAMEORIGIN"
    response["Cross-Origin-Embedder-Policy"] = "require-corp"
    response["Permissions-Policy"] = "camera=() microphone=() geolocation=()"
    response["Cache-Control"] = "no-store"
    content_type = response.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type not in INLINE_CONTENT_TYPES:
        response["Content-Disposition"] = "attachment"
    return response


def apply_app_headers(response: HttpResponse) -> HttpResponse:
    """Apply SPA and JSON API headers."""
    response["Content-Security-Policy"] = APP_CSP
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Frame-Options"] = "DENY"
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    response["Cross-Origin-Embedder-Policy"] = "require-corp"
    response["Permissions-Policy"] = "camera=() microphone=() geolocation=()"
    response["Cache-Control"] = "no-store"
    return response


__all__ = [
    "APP_CSP",
    "ARTIFACT_CSP",
    "INLINE_CONTENT_TYPES",
    "apply_app_headers",
    "apply_artifact_headers",
    "stamp_security_headers",
]
