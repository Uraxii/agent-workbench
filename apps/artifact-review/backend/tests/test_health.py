"""Smoke tests for the artifact review backend health route."""

from __future__ import annotations

from django.test import Client


def test_root_health_route_returns_ok(client: Client) -> None:
    """GET / returns 200 for container and deploy health checks."""
    response = client.get("/")

    assert response.status_code == 200
