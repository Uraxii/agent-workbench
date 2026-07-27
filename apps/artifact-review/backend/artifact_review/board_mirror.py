"""Feedback board mirroring is disabled because the container has no bd binary."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def mirror_thread_change(*args: Any, **kwargs: Any) -> None:
    """No-op mirror hook for environments without bd."""
    LOGGER.debug("bd mirroring disabled in artifact review container", extra={"args": args, "kwargs": kwargs})
    return None


__all__ = ["mirror_thread_change"]
