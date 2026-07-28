#!/usr/bin/env python3
"""HTTP facade over bd board hub and issue operations."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

__all__ = [
    "SECURITY_HEADERS",
    "BdRequestHandler",
    "ValidationError",
    "board_exists",
    "build_parser",
    "dispatch_post",
    "hub_root",
    "main",
    "payload_write_board",
    "run_bd",
    "serve_forever",
]

log = logging.getLogger("bd-svc")

BD_BIN = "bd"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9101
BD_TIMEOUT_SEC = 30
MAX_BODY_BYTES = 1_000_000
# Host header values a legitimate local client sends. Anything else means the
# request arrived via a hostname that resolved here -- the DNS-rebinding shape.
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Every response, including errors. This service returns only JSON, so its
# CSP can forbid literally every fetch: nothing here is ever a document.
# These constants are the workbench-wide baseline every non-artifact service
# sends and enforces; keep them identical across services.
SECURITY_HEADERS = {
    "Content-Security-Policy":
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}

AGGREGATOR_NAME = "hub"
AGGREGATOR_PREFIX = "hub"

BOARD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")

STATUSES = {"open", "in_progress", "blocked", "deferred", "closed", "pinned", "hooked"}
LINK_TYPES = {"blocks", "tracks", "related", "parent-child", "discovered-from"}


class ValidationError(ValueError):
    """Request validation failure safe to return as HTTP 400."""


class BdRunError(RuntimeError):
    """bd subprocess failure safe to return as HTTP 502."""

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        super().__init__(str(result.get("stderr", "")))


def hub_root() -> Path:
    raw = os.environ.get("BEADS_HUB_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".beads-hub"


def board_exists(beads_dir: Path) -> bool:
    if (beads_dir / "embeddeddolt").is_dir():
        return True
    return any(beads_dir.glob("*.db"))


def validate_board_name(value: object, field: str = "board") -> str:
    if not isinstance(value, str) or not BOARD_NAME_RE.fullmatch(value):
        raise ValidationError(f"{field}: invalid board name")
    return value


def validate_issue_id(value: object, field: str = "id") -> str:
    if not isinstance(value, str) or not ISSUE_ID_RE.fullmatch(value):
        raise ValidationError(f"{field}: invalid issue id")
    return value


def validate_label(value: object, field: str = "label") -> str:
    if not isinstance(value, str) or not LABEL_RE.fullmatch(value):
        raise ValidationError(f"{field}: invalid label")
    return value


def validate_text(value: object, field: str, limit: int, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field}: must be a string")
    if required and not value:
        raise ValidationError(f"{field}: must be non-empty")
    if len(value) > limit:
        raise ValidationError(f"{field}: too long")
    for char in value:
        if char == "\x00" or (ord(char) < 32 and char not in ("\n", "\t")):
            raise ValidationError(f"{field}: contains a control character")
    return value


def validate_status(value: object, field: str = "status") -> str:
    if not isinstance(value, str) or value not in STATUSES:
        raise ValidationError(f"{field}: invalid status")
    return value


def validate_link_type(value: object, field: str = "type") -> str:
    if not isinstance(value, str) or value not in LINK_TYPES:
        raise ValidationError(f"{field}: invalid link type")
    return value


def validate_priority(value: object, field: str = "priority") -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        priority = value
    elif isinstance(value, str) and value.isdigit():
        priority = int(value)
    else:
        raise ValidationError(f"{field}: invalid priority")
    if priority < 0 or priority > 4:
        raise ValidationError(f"{field}: invalid priority")
    return priority


def validate_limit(value: object, field: str = "limit") -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        limit = value
    elif isinstance(value, str) and value.isdigit():
        limit = int(value)
    else:
        raise ValidationError(f"{field}: invalid limit")
    if limit < 1 or limit > 500:
        raise ValidationError(f"{field}: invalid limit")
    return limit


def validate_labels(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field}: must be a list")
    return [validate_label(item, field) for item in value]


def validate_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field}: must be a boolean")
    return value


def board_beads(name: str) -> Path:
    board = validate_board_name(name)
    beads = hub_root() / board / ".beads"
    try:
        if hub_root().resolve() not in beads.resolve().parents:
            raise ValidationError("board: path escapes hub root")
    except OSError as exc:
        raise ValidationError(f"board: cannot resolve path: {exc}") from exc
    return beads


def _parse_stdout(text: str) -> object:
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _run_process(argv: list[str], env: Mapping[str, str], cwd: Path) -> dict[str, object]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=BD_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        data = {
            "ok": False, "returncode": None,
            "stdout": exc.stdout or "", "stderr": "bd timed out",
        }
        raise BdRunError(data) from exc
    data = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": _parse_stdout(result.stdout),
        "stderr": result.stderr,
    }
    if result.returncode != 0:
        raise BdRunError(data)
    return data


def run_bd(board: str, argv: list[str], *, json_output: bool = True) -> dict[str, object]:
    env = dict(os.environ)
    env["BEADS_DIR"] = str(board_beads(board))
    full_argv = [BD_BIN]
    if json_output:
        full_argv.append("--json")
    full_argv.extend(argv)
    return _run_process(full_argv, env, hub_root())


def _bd_env_without_beads_dir() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("BEADS_DIR", None)
    return env


def init_board(directory: Path, prefix: str) -> dict[str, object]:
    validate_text(prefix, "prefix", 500, True)
    directory.mkdir(parents=True, exist_ok=True)
    git_repo_preexisted = (directory / ".git").is_dir()
    result = _run_process(
        [
            BD_BIN, "init", "--non-interactive", "--skip-agents", "--skip-hooks",
            "--stealth", "--prefix", prefix,
        ],
        _bd_env_without_beads_dir(),
        directory,
    )
    if not git_repo_preexisted and (directory / ".git").is_dir():
        shutil.rmtree(directory / ".git")
    return result


def registered_repos() -> list[str]:
    result = run_bd(AGGREGATOR_NAME, ["repo", "list"], json_output=False)
    stdout = result["stdout"]
    text = stdout if isinstance(stdout, str) else json.dumps(stdout)
    return [line[len("  - "):] for line in text.splitlines() if line.startswith("  - ")]


def handle_hub_init(payload: Mapping[str, object]) -> dict[str, object]:
    require_empty(payload)
    beads = board_beads(AGGREGATOR_NAME)
    if not board_exists(beads):
        init_board(hub_root() / AGGREGATOR_NAME, AGGREGATOR_PREFIX)
    return {"hub_root": str(hub_root()), "initialized": board_exists(beads)}


def handle_hub_add(payload: Mapping[str, object]) -> dict[str, object]:
    name = validate_board_name(payload.get("name"), "name")
    prefix = validate_text(payload.get("prefix") or name, "prefix", 500, True)
    project_dir = hub_root() / name
    project_beads = board_beads(name)
    if not board_exists(board_beads(AGGREGATOR_NAME)):
        handle_hub_init({})
    created = False
    if not board_exists(project_beads):
        init_board(project_dir, str(prefix))
        created = True
    fresh_repos = registered_repos()
    registered = str(project_dir) in fresh_repos
    if not registered:
        run_bd(AGGREGATOR_NAME, ["repo", "add", str(project_dir)], json_output=False)
    return {"name": name, "path": str(project_beads), "created": created, "registered": True}


def handle_hub_sync(payload: Mapping[str, object]) -> dict[str, object]:
    require_empty(payload)
    return run_bd(AGGREGATOR_NAME, ["repo", "sync"], json_output=False)


def handle_hub_repos(payload: Mapping[str, object]) -> dict[str, object]:
    require_empty(payload)
    return {"repos": registered_repos()}


def handle_hub_path(payload: Mapping[str, object]) -> dict[str, object]:
    name = validate_board_name(payload.get("name"), "name")
    path = board_beads(name)
    if not board_exists(path):
        raise FileNotFoundError(f"no board for {name} at {path}")
    return {"path": str(path)}


def handle_hub_status(payload: Mapping[str, object]) -> dict[str, object]:
    require_empty(payload)
    initialized = board_exists(board_beads(AGGREGATOR_NAME))
    repos = registered_repos() if initialized else []
    return {"hub_root": str(hub_root()), "initialized": initialized, "repos": repos}


def require_empty(payload: Mapping[str, object]) -> None:
    if payload:
        raise ValidationError("body: must be empty")


def payload_board(payload: Mapping[str, object]) -> str:
    return validate_board_name(payload.get("board", AGGREGATOR_NAME), "board")


def payload_write_board(payload: Mapping[str, object]) -> str:
    board = payload_board(payload)
    if board == AGGREGATOR_NAME:
        raise ValidationError(
            f"{AGGREGATOR_NAME}: aggregate board is read-only; "
            "write to a project board instead",
        )
    return board


def current_description(board: str, issue_id: str) -> str:
    result = run_bd(board, ["show", issue_id])
    stdout = result.get("stdout")
    if isinstance(stdout, list) and stdout and isinstance(stdout[0], dict):
        return str(stdout[0].get("description") or "")
    return ""


def handle_issue_list(payload: Mapping[str, object]) -> dict[str, object]:
    argv = ["list"]
    if "status" in payload:
        argv.extend(["--status", validate_status(payload.get("status"))])
    if "assignee" in payload:
        assignee = validate_text(payload.get("assignee"), "assignee", 500, True)
        argv.extend(["--assignee", str(assignee)])
    for label in validate_labels(payload.get("labels"), "labels"):
        argv.extend(["--label", label])
    if "limit" in payload:
        argv.extend(["--limit", str(validate_limit(payload.get("limit")))])
    if payload.get("all") is not None and validate_bool(payload.get("all"), "all"):
        argv.append("--all")
    return run_bd(payload_board(payload), argv)


def handle_issue_show(payload: Mapping[str, object]) -> dict[str, object]:
    issue_id = validate_issue_id(payload.get("id"))
    return run_bd(payload_board(payload), ["show", issue_id])


def handle_issue_create(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    title = str(validate_text(payload.get("title"), "title", 500, True))
    argv = ["create", f"--title={title}"]
    description = validate_text(payload.get("description"), "description", 20000, False)
    if description is not None:
        argv.extend(["-d", description])
    if "priority" in payload:
        argv.extend(["-p", str(validate_priority(payload.get("priority")))])
    labels = validate_labels(payload.get("labels"), "labels")
    if labels:
        argv.extend(["--labels", ",".join(labels)])
    if "parent" in payload:
        argv.extend(["--parent", validate_issue_id(payload.get("parent"), "parent")])
    if "assignee" in payload:
        argv.extend(["-a", str(validate_text(payload.get("assignee"), "assignee", 500, True))])
    return run_bd(board, argv)


def handle_issue_update(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    issue_id = validate_issue_id(payload.get("id"))
    argv = ["update", issue_id]
    overwrite_description = False
    if "overwrite_description" in payload:
        overwrite_description = validate_bool(
            payload.get("overwrite_description"), "overwrite_description",
        )
    if "status" in payload:
        argv.extend(["--status", validate_status(payload.get("status"))])
    if "assignee" in payload:
        argv.extend(["-a", str(validate_text(payload.get("assignee"), "assignee", 500, True))])
    if "priority" in payload:
        argv.extend(["-p", str(validate_priority(payload.get("priority")))])
    description = validate_text(payload.get("description"), "description", 20000, False)
    if description is not None:
        if current_description(board, issue_id) and not overwrite_description:
            raise ValidationError(
                "description: existing description is non-empty; pass "
                "overwrite_description or use /issue/note to ADD context instead",
            )
        argv.extend(["-d", description])
    for label in validate_labels(payload.get("add_labels"), "add_labels"):
        argv.extend(["--add-label", label])
    for label in validate_labels(payload.get("remove_labels"), "remove_labels"):
        argv.extend(["--remove-label", label])
    if payload.get("claim") is not None and validate_bool(payload.get("claim"), "claim"):
        argv.append("--claim")
    return run_bd(board, argv)


def handle_issue_close(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    issue_id = validate_issue_id(payload.get("id"))
    argv = ["close", issue_id]
    reason = validate_text(payload.get("reason"), "reason", 500, False)
    if reason is not None:
        argv.extend(["--reason", reason])
    return run_bd(board, argv)


def handle_issue_note(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    issue_id = validate_issue_id(payload.get("id"))
    text = str(validate_text(payload.get("text"), "text", 20000, True))
    return run_bd(board, ["note", issue_id, "--", text])


def handle_issue_link(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    from_id = validate_issue_id(payload.get("from_id"), "from_id")
    to_id = validate_issue_id(payload.get("to_id"), "to_id")
    argv = ["link", from_id, to_id]
    if "type" in payload:
        argv.extend(["--type", validate_link_type(payload.get("type"))])
    return run_bd(board, argv)


def handle_issue_children(payload: Mapping[str, object]) -> dict[str, object]:
    issue_id = validate_issue_id(payload.get("id"))
    return run_bd(payload_board(payload), ["children", issue_id])


def handle_issue_priority(payload: Mapping[str, object]) -> dict[str, object]:
    board = payload_write_board(payload)
    issue_id = validate_issue_id(payload.get("id"))
    priority = validate_priority(payload.get("priority"))
    return run_bd(board, ["priority", issue_id, str(priority)])


def handle_issue_ready(payload: Mapping[str, object]) -> dict[str, object]:
    argv = ["ready"]
    if "assignee" in payload:
        assignee = validate_text(payload.get("assignee"), "assignee", 500, True)
        argv.extend(["-a", str(assignee)])
    for label in validate_labels(payload.get("labels"), "labels"):
        argv.extend(["--label", label])
    if "limit" in payload:
        argv.extend(["--limit", str(validate_limit(payload.get("limit")))])
    return run_bd(payload_board(payload), argv)


def handle_issue_search(payload: Mapping[str, object]) -> dict[str, object]:
    query = str(validate_text(payload.get("query"), "query", 500, True))
    argv = ["search", f"--query={query}"]
    if "status" in payload:
        argv.extend(["--status", validate_status(payload.get("status"))])
    if "limit" in payload:
        argv.extend(["--limit", str(validate_limit(payload.get("limit")))])
    return run_bd(payload_board(payload), argv)


def handle_issue_dep(payload: Mapping[str, object]) -> dict[str, object]:
    issue_id = validate_issue_id(payload.get("id"))
    argv = ["dep", "list", issue_id]
    if "direction" in payload:
        direction = payload.get("direction")
        if direction not in {"up", "down"}:
            raise ValidationError("direction: invalid direction")
        argv.extend(["--direction", str(direction)])
    if "type" in payload:
        argv.extend(["--type", validate_link_type(payload.get("type"))])
    return run_bd(payload_board(payload), argv)


Endpoint = Callable[[Mapping[str, object]], dict[str, object]]

ENDPOINTS: dict[str, Endpoint] = {
    "/hub/init": handle_hub_init,
    "/hub/add": handle_hub_add,
    "/hub/sync": handle_hub_sync,
    "/hub/repos": handle_hub_repos,
    "/hub/path": handle_hub_path,
    "/hub/status": handle_hub_status,
    "/issue/list": handle_issue_list,
    "/issue/show": handle_issue_show,
    "/issue/create": handle_issue_create,
    "/issue/update": handle_issue_update,
    "/issue/close": handle_issue_close,
    "/issue/note": handle_issue_note,
    "/issue/link": handle_issue_link,
    "/issue/children": handle_issue_children,
    "/issue/priority": handle_issue_priority,
    "/issue/ready": handle_issue_ready,
    "/issue/search": handle_issue_search,
    "/issue/dep": handle_issue_dep,
}


def dispatch_post(path: str, payload: Mapping[str, object]) -> tuple[int, dict[str, object]]:
    endpoint = ENDPOINTS.get(path)
    if endpoint is None:
        return 404, {"error": "not found"}
    try:
        result = endpoint(payload)
    except ValidationError as exc:
        return 400, {"error": str(exc)}
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except BdRunError as exc:
        return 502, {"error": "bd failed", **exc.result}
    return 200, result


class BdRequestHandler(BaseHTTPRequestHandler):
    """Routes GET /health and the POST endpoints in ``ENDPOINTS``."""

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def end_headers(self) -> None:
        """Stamp the security baseline onto EVERY response.

        Here rather than in _send_json so that the stdlib's own
        send_error() replies (405/501 for methods this handler does not
        implement) carry the headers too.
        """
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_browser_origin(self) -> str | None:
        """Return a refusal reason if this looks like a web page's request.

        The service listens unauthenticated on loopback, so a page open in a
        browser on this machine is the realistic attacker. Three cheap checks
        keep it out: an ``Origin`` header means a web origin sent this and is
        never legitimate here; requiring ``application/json`` means a
        cross-origin attempt can no longer be a "simple request" and must pass
        a preflight this service never answers; and requiring ``Host`` to be a
        loopback literal blocks DNS rebinding, where an attacker-controlled
        name resolves to 127.0.0.1. A missing ``Host`` is refused too: HTTP/1.1
        requires it and every real client here sends it.
        """
        if self.headers.get("Origin"):
            return "origin: browser-origin requests are refused"
        target = urlparse(self.path)
        if target.scheme or target.netloc:
            return "target: must be an origin-form path"
        host_headers = self.headers.get_all("Host") or []
        if len(host_headers) > 1:
            return "host: exactly one Host header is required"
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in LOOPBACK_HOSTS:
            return "host: must be a loopback address"
        if self.command != "POST":
            return None
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if content_type.lower() != "application/json":
            return "content-type: must be application/json"
        return None

    def _read_json_body(self) -> dict[str, object]:
        # A body this handler cannot frame exactly must never be treated as an
        # empty payload: that silently turns "here is my body" into "run the
        # endpoint with its defaults". Chunked bodies and duplicate/ambiguous
        # Content-Length are refused rather than ignored.
        if self.headers.get("Transfer-Encoding"):
            raise ValidationError("body: transfer-encoding is not supported")
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) > 1:
            raise ValidationError("body: duplicate content length")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("body: invalid content length") from exc
        if length < 0:
            raise ValidationError("body: negative content length")
        if length > MAX_BODY_BYTES:
            raise ValidationError("body: too large")
        raw = self.rfile.read(length) if length else b""
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValidationError("body: must be a JSON object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        refusal = self._reject_browser_origin()
        if refusal is not None:
            self._send_json(403, {"error": refusal})
            return
        if parsed.path == "/health":
            initialized = board_exists(board_beads(AGGREGATOR_NAME))
            self._send_json(200, {
                "status": "ok", "hub_root": str(hub_root()), "initialized": initialized,
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        refusal = self._reject_browser_origin()
        if refusal is not None:
            self._send_json(403, {"error": refusal})
            return
        if parsed.path not in ENDPOINTS:
            self._send_json(404, {"error": "not found"})
            return
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"body: invalid JSON: {exc}"})
        except ValidationError as exc:
            self._send_json(400, {"error": str(exc)})
        else:
            status, result = dispatch_post(parsed.path, payload)
            self._send_json(status, result)


def serve_forever(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BdRequestHandler)
    log.info("bd-svc listening on %s:%s (hub_root=%s)", host, port, hub_root())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_run(args: argparse.Namespace) -> int:
    serve_forever(args.host, args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run", help="serve the HTTP facade in the foreground")
    run_cmd.add_argument("--host", default=os.environ.get("BD_SVC_HOST", DEFAULT_HOST))
    run_cmd.add_argument(
        "--port", type=int, default=int(os.environ.get("BD_SVC_PORT", DEFAULT_PORT)),
    )
    run_cmd.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
