"""Regression: artifact-svc's stage root must never default under /tmp.

/tmp clears on reboot; the artifact index (ArtifactIndex rows in
feedback.db, under the durable ARTIFACT_SVC_FEEDBACK_ROOT) survives it.
A /tmp stage default means the published bytes vanish on reboot while
the index keeps reporting the artifact as published -- see
ARTIFACT_SVC_STAGE_ROOT in artifact_review_site/settings.py.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "apps/artifact-review/backend"


def _stage_root_default(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Import artifact_review_site.settings fresh, with no env override,
    and return its resolved ARTIFACT_SVC_STAGE_ROOT default. Settings.py
    has no Django-setup dependency; importing it directly (not via
    django.conf.settings) is enough to read the plain module-level
    default."""
    monkeypatch.delenv("ARTIFACT_SVC_STAGE_ROOT", raising=False)
    monkeypatch.syspath_prepend(str(BACKEND_DIR))
    sys.modules.pop("artifact_review_site.settings", None)
    settings = importlib.import_module("artifact_review_site.settings")
    return settings.ARTIFACT_SVC_STAGE_ROOT


def test_stage_root_default_is_not_under_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A /tmp default would make published artifact bytes vanish on
    reboot while the durable index still reports them as published."""
    root = _stage_root_default(monkeypatch)
    assert not root.is_relative_to("/tmp"), (
        f"ARTIFACT_SVC_STAGE_ROOT default {root} is under /tmp -- it "
        "clears on reboot while the durable index still reports "
        "artifacts as published"
    )
