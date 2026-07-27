#!/usr/bin/env python3
"""artifact-serve compatibility entrypoint for the owned review runtime.

Preserves the existing artifact-serve script path and CLI surface while
loading the already-implemented review UI/runtime from review-serve.py.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

__all__ = [
    "Anchor",
    "Reply",
    "Thread",
    "Upload",
    "build_parser",
    "db_connect",
    "main",
    "render_code_page",
    "render_gallery_page",
    "render_viewer_page",
]

_SCRIPT_DIR = Path(__file__).resolve().parent
_IMPL_PATH = _SCRIPT_DIR / "review-serve.py"
_IMPL_MODULE_NAME = "artifact_serve_review_impl"
_PUBLIC_EXPORTS = tuple(__all__)


def _load_impl() -> ModuleType:
    """Load review-serve.py as a module from its file path."""
    spec = importlib.util.spec_from_file_location(_IMPL_MODULE_NAME, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load implementation from {_IMPL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_IMPL_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()


def _apply_env_aliases() -> None:
    """Map artifact-serve env names onto review-serve's env surface."""
    if "REVIEW_SERVE_HOST" not in os.environ and "ARTIFACT_SERVE_HOST" in os.environ:
        os.environ["REVIEW_SERVE_HOST"] = os.environ["ARTIFACT_SERVE_HOST"]
    if "REVIEW_SERVE_PORT" not in os.environ and "ARTIFACT_SERVE_PORT" in os.environ:
        os.environ["REVIEW_SERVE_PORT"] = os.environ["ARTIFACT_SERVE_PORT"]


for _name in _PUBLIC_EXPORTS:
    if _name in {"build_parser", "main"}:
        continue
    globals()[_name] = getattr(_IMPL, _name)


def __getattr__(name: str) -> object:
    """Proxy unknown attributes to the review implementation module."""
    return getattr(_IMPL, name)


def build_parser() -> argparse.ArgumentParser:
    """Build the artifact-serve CLI parser backed by the review runtime."""
    _apply_env_aliases()
    parser = _IMPL.build_parser()
    parser.prog = "artifact-serve"
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse args and dispatch using the review runtime implementation."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
