#!/usr/bin/env python3
"""Downscale a still image to a maximum height with PIL lanczos resampling.

Standalone CLI port of the retired workflow-runner ``image_downscale`` step
(branch eb198d5, .claude/skills/workflow-runner/steps.py). The n8n starter
pipeline's "Downscale (PIL)" Execute Command node shells out to this.

Contract mirrors the retired step body exactly:
  - open the source, convert to RGB
  - if the source is already within max_height, copy through unchanged
    (NEVER upscale)
  - otherwise scale width by the same ratio and resize with LANCZOS
  - write to --out and print the output path to stdout (the node reads it)

Usage:
    downscale.py --src <path> --max-height <int> --out <path>

NOTE: requires Pillow AND python3 in whatever environment runs it. The
official n8n container image ships neither, so inside the container this node
is a documented stub until either (a) python3 + Pillow are layered in, or
(b) it is run on the host. See workflows/README.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

__all__ = ["downscale"]


def downscale(src: Path, max_height: int, out: Path) -> Path:
    """Downscale ``src`` to at most ``max_height`` px tall, writing to ``out``.

    Never upscales: a source already within ``max_height`` is copied through
    unchanged. Returns the ``out`` path on success.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        if rgb.height <= max_height:
            rgb.save(out)  # already within bounds; never upscale
        else:
            width = round(rgb.width * (max_height / rgb.height))
            rgb.resize((width, max_height), Image.Resampling.LANCZOS).save(out)
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Downscale an image to a max height (PIL lanczos).")
    parser.add_argument("--src", required=True, type=Path, help="Source image path.")
    parser.add_argument("--max-height", required=True, type=int, help="Height cap in pixels.")
    parser.add_argument("--out", required=True, type=Path, help="Destination image path.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.src.exists():
        raise SystemExit(f"source image not found: {args.src}")
    result = downscale(args.src, args.max_height, args.out)
    print(result)  # stdout is the Execute Command node's return channel


if __name__ == "__main__":
    main()
