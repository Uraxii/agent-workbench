"""Validate upload names, sizes, and extensions."""

from __future__ import annotations

import re
import tarfile
from pathlib import PurePosixPath

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_UPLOAD_COUNT = 8
MAX_MEMBER_NAME_BYTES = 512

RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+=, /-]*$")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_UPLOAD_EXTENSIONS = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".webp",
}


def validate_archive_member(member: tarfile.TarInfo) -> None:
    """Reject tar members that cannot be safely extracted as files or dirs."""
    name = member.name
    if not member.isfile() and not member.isdir():
        raise ValueError("unsupported_member_type")
    if member.size > MAX_MEMBER_BYTES:
        raise ValueError("member_too_large")
    if not name or name.startswith("/") or "\\" in name:
        raise ValueError("bad_member_name")
    if len(name.encode("utf-8")) > MAX_MEMBER_NAME_BYTES:
        raise ValueError("member_name_too_long")
    if not RELATIVE_PATH_RE.fullmatch(name):
        raise ValueError("bad_member_name")

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "" in path.parts:
        raise ValueError("bad_member_name")


def validate_feedback_upload(name: str, size: int, content_type: str) -> str:
    """Return a sanitized feedback upload filename."""
    del content_type
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("upload_too_large")

    raw_name = PurePosixPath(name).name.strip().strip(".")
    sanitized_name = SAFE_FILENAME_RE.sub("_", raw_name)
    if not sanitized_name:
        raise ValueError("bad_upload_name")

    suffix = PurePosixPath(sanitized_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("bad_upload_extension")
    return sanitized_name[:128]


__all__ = [
    "ALLOWED_UPLOAD_EXTENSIONS",
    "MAX_ARCHIVE_BYTES",
    "MAX_MEMBER_BYTES",
    "MAX_MEMBER_NAME_BYTES",
    "MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_COUNT",
    "validate_archive_member",
    "validate_feedback_upload",
]
