"""Static artifact and SPA views for the artifact review backend."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse

from artifact_review import artifact_paths
from artifact_review.response_headers import apply_app_headers, apply_artifact_headers


def health(request: HttpRequest) -> JsonResponse:
    """Return the container health response."""
    return apply_app_headers(JsonResponse({"status": "ok"}))


def root_index(request: HttpRequest) -> HttpResponse:
    """Return the React SPA shell."""
    return _spa_shell_response()


def static_artifact(
    request: HttpRequest,
    project: str,
    subdir: str,
    rel: str = "",
) -> HttpResponse:
    """Return a staged artifact file or directory listing."""
    try:
        artifact_paths.validate_name(project)
        artifact_paths.validate_name(subdir)
        artifact_root = artifact_paths.safe_join(artifact_paths.stage_root(), f"{project}/{subdir}")
        target_path = artifact_paths.safe_join(artifact_root, rel or "")
    except ValueError:
        return apply_artifact_headers(JsonResponse({"error": "not found"}, status=404))

    if not target_path.exists():
        return apply_artifact_headers(JsonResponse({"error": "not found"}, status=404))
    if target_path.is_dir():
        index_path = artifact_paths.safe_join(target_path, "index.html")
        if index_path.exists() and index_path.is_file():
            return _file_response(index_path, artifact=True)
        entries = sorted(child.name + ("/" if child.is_dir() else "") for child in target_path.iterdir())
        return apply_artifact_headers(JsonResponse({"path": rel, "entries": entries}))
    if not target_path.is_file():
        return apply_artifact_headers(JsonResponse({"error": "not found"}, status=404))
    return _file_response(target_path, artifact=True)


def spa_asset(request: HttpRequest, rel: str) -> HttpResponse:
    """Return a React SPA asset."""
    try:
        target_path = artifact_paths.safe_join(settings.ARTIFACT_SERVE_SPA_ROOT, rel)
    except ValueError:
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    if not target_path.is_file():
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    return _file_response(target_path, artifact=False)


def spa_index(request: HttpRequest, rel: str) -> HttpResponse:
    """Return the React SPA shell for a frontend route."""
    if rel.startswith("_/") or rel.startswith("spa/"):
        return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    parts = rel.strip("/").split("/")
    if len(parts) >= 2:
        try:
            staged_path = artifact_paths.safe_join(artifact_paths.stage_root(), f"{parts[0]}/{parts[1]}")
        except ValueError:
            staged_path = None
        if staged_path is not None and staged_path.exists():
            return apply_app_headers(JsonResponse({"error": "not found"}, status=404))
    return _spa_shell_response()


def _spa_shell_response() -> HttpResponse:
    index_path = artifact_paths.safe_join(settings.ARTIFACT_SERVE_SPA_ROOT, "index.html")
    if not index_path.is_file():
        return apply_app_headers(JsonResponse({"error": "spa bundle missing", "path": str(index_path)}, status=500))
    return _file_response(index_path, artifact=False)


def _file_response(path: Path, artifact: bool) -> HttpResponse:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = FileResponse(path.open("rb"), content_type=content_type)
    if artifact:
        return apply_artifact_headers(response)
    return apply_app_headers(response)


__all__ = ["health", "root_index", "spa_asset", "spa_index", "static_artifact"]
