"""URL routes for the artifact review backend."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.urls import path

from artifact_review import views_api, views_static

View = Callable[[HttpRequest], HttpResponse]


def route_by_method(method_views: Mapping[str, View]) -> View:
    """Dispatch one URL path to method-specific view functions."""
    allowed_methods = tuple(method_views)

    def view(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        selected_view = method_views.get(request.method)
        if selected_view is None:
            return HttpResponseNotAllowed(allowed_methods)
        return selected_view(request, *args, **kwargs)

    return view


urlpatterns = [
    path("_/api/settings", views_api.api_settings, name="api_settings"),
    path("_/api/artifacts", views_api.api_artifacts, name="api_artifacts"),
    path("_/api/uploads/<int:id>", views_api.api_upload, name="api_upload"),
    path(
        "_/api/threads",
        route_by_method({"GET": views_api.api_threads, "POST": views_api.api_create_thread}),
        name="api_threads",
    ),
    path("_/api/threads/<int:id>/replies", views_api.api_create_reply, name="api_create_reply"),
    path("_/api/threads/<int:id>/resolve", views_api.api_resolve_thread, name="api_resolve_thread"),
    path("_/api/publish", views_api.api_publish, name="api_publish"),
    path("_/health", views_static.health, name="health"),
    path("", views_static.root_index, name="root_index"),
    path("spa/<path:rel>", views_static.spa_asset, name="spa_asset"),
    path("<str:project>/<str:subdir>/", views_static.static_artifact, name="static_artifact_directory"),
    path("<str:project>/<str:subdir>/<path:rel>", views_static.static_artifact, name="static_artifact"),
    path("<path:rel>", views_static.spa_index, name="spa_index"),
]

__all__ = ["route_by_method", "urlpatterns"]
