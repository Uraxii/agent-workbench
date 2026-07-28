"""HTTP client for the containerized artifact review service."""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import posixpath
import sys
import tarfile
import uuid
from http.cookiejar import CookieJar
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, OpenerDirector, Request, build_opener, urlopen

__all__ = ["REQUEST_TIMEOUT_SECONDS", "register"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9099
REQUEST_TIMEOUT_SECONDS = 10


class ArtifactRequestError(RuntimeError):
    """Raised when an artifact service request fails."""


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `artifact` parser and its HTTP-backed commands."""
    parser = subparsers.add_parser(
        "artifact",
        help="artifact review app ops",
        description="HTTP client for artifact review; server startup is handled by deploy or docker-compose.",
    )
    sub = parser.add_subparsers(dest="artifact_command", required=True)

    publish_cmd = sub.add_parser("publish", help="publish an artifact for review")
    publish_cmd.add_argument("--project", required=True)
    publish_cmd.add_argument("--src", required=True)
    publish_cmd.add_argument("--as", dest="as_name", default=None)
    publish_cmd.add_argument(
        "--id", dest="artifact_id", default=None,
        help="Artifact ID for feedback correlation. Default: service assigned.",
    )
    publish_cmd.add_argument("--force", action="store_true", help="Overwrite existing artifact")
    publish_cmd.set_defaults(func=cmd_publish)

    feedback_cmd = sub.add_parser(
        "feedback", help="dump threads + reply chains for an artifact as JSON",
    )
    feedback_cmd.add_argument("--artifact", dest="artifact_id", required=True)
    feedback_cmd.add_argument("--sub-path", dest="sub_path", default=None, help="Filter to specific sub-path")
    feedback_cmd.add_argument("--all-paths", action="store_true", help="Show threads from all sub-paths")
    feedback_cmd.set_defaults(func=cmd_feedback)


    comment_cmd = sub.add_parser("comment", help="create a feedback thread")
    comment_cmd.add_argument("--artifact", dest="artifact_id", required=True)
    comment_cmd.add_argument("--body", required=True)
    comment_cmd.add_argument("--sub-path", dest="sub_path", default="")
    comment_cmd.add_argument("--author", default="")
    comment_cmd.add_argument("--anchor-kind", dest="anchor_kind", default="page")
    comment_cmd.set_defaults(func=cmd_comment)

    reply_cmd = sub.add_parser("reply", help="add a reply to a feedback thread")
    reply_cmd.add_argument("--thread", type=int, required=True)
    reply_cmd.add_argument("--body", required=True)
    reply_cmd.add_argument("--author", default="")
    reply_cmd.set_defaults(func=cmd_reply)

    resolve_cmd = sub.add_parser("resolve", help="resolve or reopen a feedback thread")
    resolve_cmd.add_argument("--thread", type=int, required=True)
    resolve_cmd.add_argument("--reopen", action="store_true", help="reopen instead of resolve")
    resolve_cmd.set_defaults(func=cmd_resolve)

    status_cmd = sub.add_parser("status", help="artifact service health + entries")
    status_cmd.set_defaults(func=cmd_status)


def _base_url() -> str:
    env_url = os.environ.get("ARTIFACT_SVC_URL")
    if env_url:
        return env_url.rstrip("/")
    host = os.environ.get("ARTIFACT_SVC_HOST", DEFAULT_HOST)
    port = os.environ.get("ARTIFACT_SVC_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def _json_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    opener: OpenerDirector | None = None,
) -> object:
    request = Request(url, data=data, headers=headers or {}, method="POST" if data else "GET")
    try:
        open_request = opener.open if opener else urlopen
        with open_request(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except HTTPError as exc:
        body = exc.read()
        detail = _http_error_detail(exc, body)
        raise ArtifactRequestError(detail) from exc
    except URLError as exc:
        raise ArtifactRequestError(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise ArtifactRequestError(str(exc)) from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactRequestError(f"invalid JSON response: {exc}") from exc


def _csrf_opener(base_url: str, post_url: str) -> tuple[OpenerDirector, str]:
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    health_url = f"{base_url}/_/health"
    try:
        _json_request(health_url, opener=opener)
    except ArtifactRequestError as exc:
        raise ArtifactRequestError(f"CSRF token request failed for {health_url}: {exc}") from exc
    for cookie in jar:
        if cookie.name == "csrftoken":
            return opener, cookie.value
    raise ArtifactRequestError(f"missing CSRF token from {health_url} before POST {post_url}")


def _http_error_detail(exc: HTTPError, body: bytes) -> str:
    prefix = f"HTTP {exc.code} {exc.reason}"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = body.decode("utf-8", errors="replace").strip()
        return f"{prefix}: {text}" if text else prefix
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return f"{prefix}: {reason}" if reason else f"{prefix}: {json.dumps(payload, sort_keys=True)}"


def _print_service_error(verb: str, url: str, exc: ArtifactRequestError) -> int:
    print(f"artifact {verb} failed for {url}: {exc}", file=sys.stderr)
    return 1


def _safe_tar_name(name: str) -> str | None:
    normalized = posixpath.normpath(name.replace(os.sep, "/"))
    path = PurePosixPath(normalized)
    if normalized in ("", ".") or path.is_absolute() or ".." in path.parts:
        return None
    return normalized


def _add_tar_dir(archive: tarfile.TarFile, name: str, source_path: Path) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = source_path.stat().st_mode & 0o777
    info.mtime = int(source_path.stat().st_mtime)
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info)


def _add_tar_file(archive: tarfile.TarFile, name: str, source_path: Path) -> None:
    stat = source_path.stat()
    info = tarfile.TarInfo(name)
    info.type = tarfile.REGTYPE
    info.mode = stat.st_mode & 0o777
    info.mtime = int(stat.st_mtime)
    info.size = stat.st_size
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    with source_path.open("rb") as file_obj:
        archive.addfile(info, file_obj)


def _tar_entries(source: Path) -> list[tuple[Path, str]]:
    if source.is_file():
        name = _safe_tar_name(source.name)
        return [(source, name)] if name else []
    entries: list[tuple[Path, str]] = []
    for path in sorted(source.rglob("*")):
        rel_name = _safe_tar_name(path.relative_to(source).as_posix())
        if rel_name:
            entries.append((path, rel_name))
    return entries


def _build_tar(source_text: str) -> bytes:
    source = Path(source_text).expanduser()
    if not source.exists():
        raise ArtifactRequestError(f"source does not exist: {source}")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path, name in _tar_entries(source):
            if path.is_dir():
                _add_tar_dir(archive, name, path)
            elif path.is_file():
                _add_tar_file(archive, name, path)
    return buffer.getvalue()


def _multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    data: bytes,
) -> tuple[bytes, str]:
    boundary = f"agent-workbench-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode("utf-8"), b"\r\n",
        ])
    content_type = mimetypes.guess_type(filename)[0] or "application/x-tar"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data, b"\r\n", f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _run_json_command(verb: str, url: str, **request_kwargs: object) -> int:
    try:
        payload = _json_request(url, **request_kwargs)
    except ArtifactRequestError as exc:
        return _print_service_error(verb, url, exc)
    print(json.dumps(payload, sort_keys=True))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Publish an artifact archive to the artifact service."""
    url = f"{_base_url()}/_/api/publish"
    try:
        archive = _build_tar(args.src)
    except ArtifactRequestError as exc:
        return _print_service_error("publish", url, exc)
    as_name = args.as_name if args.as_name is not None else Path(args.src).name
    fields = {"project": args.project, "as": as_name}
    if args.artifact_id:
        fields["artifact_id"] = args.artifact_id
    if args.force:
        fields["overwrite"] = "1"
    body, content_type = _multipart(fields, "archive", "artifact.tar", archive)
    headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    try:
        opener, csrf_token = _csrf_opener(_base_url(), url)
    except ArtifactRequestError as exc:
        return _print_service_error("publish", url, exc)
    headers["X-CSRFToken"] = csrf_token
    return _run_json_command("publish", url, data=body, headers=headers, opener=opener)


def cmd_feedback(args: argparse.Namespace) -> int:
    """Fetch artifact feedback threads from the artifact service."""
    query_params = {"artifact": args.artifact_id}
    if args.all_paths:
        # Don't add sub_path to get all sub-paths
        pass
    elif args.sub_path is not None:
        # Use specified sub_path
        query_params["sub_path"] = args.sub_path
    else:
        # Default: filter to empty sub_path (root level only)
        query_params["sub_path"] = ""
    query = urlencode(query_params)
    url = f"{_base_url()}/_/api/threads?{query}"
    return _run_json_command("feedback", url)


def cmd_comment(args: argparse.Namespace) -> int:
    """Create a feedback thread for an artifact."""
    url = f"{_base_url()}/_/api/threads"
    fields = {
        "artifact": args.artifact_id,
        "body": args.body,
        "sub_path": args.sub_path,
        "author": args.author,
        "anchor_kind": args.anchor_kind,
    }
    fields = {k: v for k, v in fields.items() if v}
    body = urlencode(fields).encode("utf-8")
    try:
        opener, csrf_token = _csrf_opener(_base_url(), url)
    except ArtifactRequestError as exc:
        return _print_service_error("comment", url, exc)
    headers = {"X-CSRFToken": csrf_token, "Content-Type": "application/x-www-form-urlencoded"}
    return _run_json_command("comment", url, data=body, headers=headers, opener=opener)


def cmd_reply(args: argparse.Namespace) -> int:
    """Add a reply to a feedback thread."""
    url = f"{_base_url()}/_/api/threads/{args.thread}/replies"
    fields = {
        "body": args.body,
        "author": args.author,
    }
    fields = {k: v for k, v in fields.items() if v}
    body = urlencode(fields).encode("utf-8")
    try:
        opener, csrf_token = _csrf_opener(_base_url(), url)
    except ArtifactRequestError as exc:
        return _print_service_error("reply", url, exc)
    headers = {"X-CSRFToken": csrf_token, "Content-Type": "application/x-www-form-urlencoded"}
    return _run_json_command("reply", url, data=body, headers=headers, opener=opener)


def cmd_resolve(args: argparse.Namespace) -> int:
    """Resolve or reopen a feedback thread."""
    url = f"{_base_url()}/_/api/threads/{args.thread}/resolve"
    resolved = "false" if args.reopen else "true"
    fields = {"resolved": resolved}
    body = urlencode(fields).encode("utf-8")
    try:
        opener, csrf_token = _csrf_opener(_base_url(), url)
    except ArtifactRequestError as exc:
        return _print_service_error("resolve", url, exc)
    headers = {"X-CSRFToken": csrf_token, "Content-Type": "application/x-www-form-urlencoded"}
    return _run_json_command("resolve", url, data=body, headers=headers, opener=opener)


def cmd_status(args: argparse.Namespace) -> int:
    """Fetch service health and staged artifact list."""
    base = _base_url()
    health_url = f"{base}/_/health"
    artifacts_url = f"{base}/_/api/artifacts"
    try:
        health = _json_request(health_url)
        artifact_payload = _json_request(artifacts_url)
    except ArtifactRequestError as exc:
        url = health_url if "health" not in locals() else artifacts_url
        return _print_service_error("status", url, exc)
    artifacts = artifact_payload.get("artifacts") if isinstance(artifact_payload, dict) else artifact_payload
    print(json.dumps({"endpoint": base, "health": health, "artifacts": artifacts}, sort_keys=True))
    return 0
