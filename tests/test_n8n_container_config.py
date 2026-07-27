"""Regression checks on the raw text of scripts/n8n-container/n8n.container
(a podman quadlet, not a Containerfile -- kept separate from
test_container_config.py, which is Containerfile-specific house style).

Guards two crash-loop/security regressions:
- losing the /home/node/.cache tmpfs makes n8n ENOENT crash-loop seconds
  after "n8n ready" (the /tmp tmpfs alone is not enough).
- the image drifting off its digest pin, or the Public API env line
  disappearing.
"""
from __future__ import annotations

from pathlib import Path

_QUADLET_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "n8n-container" / "n8n.container"
)


def _lines() -> list[str]:
    return _QUADLET_PATH.read_text(encoding="utf-8").splitlines()


def test_home_node_cache_tmpfs_present() -> None:
    """Critical regression guard: without this tmpfs n8n crash-loops with
    'Error: ENOENT: no such file or directory, mkdir /home/node/.cache'."""
    assert "Tmpfs=/home/node/.cache" in _lines()


def test_tmp_tmpfs_present() -> None:
    assert "Tmpfs=/tmp" in _lines()


def test_image_is_digest_pinned_never_a_floating_tag() -> None:
    [image_line] = [line for line in _lines() if line.startswith("Image=")]
    assert "@sha256:" in image_line
    assert ":latest" not in image_line


def test_public_api_env_line_present() -> None:
    assert "Environment=N8N_PUBLIC_API_DISABLED=false" in _lines()
