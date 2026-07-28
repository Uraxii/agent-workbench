"""`kb` subcommand -- HTTP client for the knowledgebase service.

The service owns ``$KB_HOME`` and is the only thing that opens it. This
module holds no vault logic at all: every verb is one HTTP call, and when
the service is unreachable the command FAILS, naming the endpoint it
tried and the error it got. There is deliberately no filesystem fallback
-- a fallback path is a second way into the vault, and the whole point of
the service is that there is exactly one.

Subcommands:
    init                       create the vault            POST /vault/init
    add PROJECT                create a project's dirs     POST /project/init
    path PROJECT               print the project's path    GET  /project
    index                      rebuild the derived index   POST /reindex
    clip URL [--project P]     capture a web source        POST /clip
    put PROJECT TITLE [...]    write a note (body stdin)   POST /put
    atomize [--url U]          ingest + split              POST /atomize
    query Q [--project P ...]  hybrid search               GET  /query
    status                     vault root + projects       GET  /status
    decision record|audit      dated decision notes        [cli/kb_decision.py]
    enrich [--project P]       fill question/summary       POST /enrich
           [--note N]
    embed missing|all          bounded vector backfill     [cli/kb_embed.py]
          [--dry-run]

The service address comes from ``KB_SVC_HOST`` (default 127.0.0.1) and
``KB_SVC_PORT`` (default 9100).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from cli import kb_decision, kb_embed

__all__ = [
    "register",
    "get_json",
    "post_json",
    "query_string",
    "service_base_url",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9100
REQUEST_TIMEOUT_SEC = 120.0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `kb` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("kb", help="knowledgebase service client")
    sub = parser.add_subparsers(dest="kb_command", required=True)

    init_cmd = sub.add_parser("init", help="create the vault (idempotent)")
    init_cmd.set_defaults(func=cmd_init)

    add_cmd = sub.add_parser("add", help="create PROJECT's note dirs")
    add_cmd.add_argument("project")
    add_cmd.set_defaults(func=cmd_add)

    path_cmd = sub.add_parser("path", help="print PROJECT's vault path")
    path_cmd.add_argument("project")
    path_cmd.set_defaults(func=cmd_path)

    index_cmd = sub.add_parser(
        "index", help="rebuild the derived index from the vault",
    )
    index_cmd.set_defaults(func=cmd_index)

    clip_cmd = sub.add_parser("clip", help="capture a web source")
    clip_cmd.add_argument("url")
    clip_cmd.add_argument("--project", default="inbox")
    clip_cmd.set_defaults(func=cmd_clip)

    put_cmd = sub.add_parser("put", help="write a note (body on stdin)")
    put_cmd.add_argument("project")
    put_cmd.add_argument("title")
    put_cmd.add_argument("--type", default="note")
    put_cmd.add_argument("--source", default="")
    put_cmd.set_defaults(func=cmd_put)

    kb_decision.register(sub)
    kb_embed.register(sub)

    query_cmd = sub.add_parser("query", help="hybrid keyword + vector search")
    query_cmd.add_argument("q")
    query_cmd.add_argument("--project", default=None)
    query_cmd.add_argument("--type", default=None)
    query_cmd.add_argument(
        "--all", action="store_true", help="include revised notes",
    )
    query_cmd.set_defaults(func=cmd_query)

    atomize_cmd = sub.add_parser(
        "atomize", help="ingest a URL or stdin content and split it",
    )
    atomize_cmd.add_argument("--url", default=None)
    atomize_cmd.add_argument("--project", default="inbox")
    atomize_cmd.add_argument("--title", default="untitled")
    atomize_cmd.add_argument("--type", default="source")
    atomize_cmd.set_defaults(func=cmd_atomize)

    status_cmd = sub.add_parser("status", help="vault root and projects")
    status_cmd.set_defaults(func=cmd_status)

    enrich_cmd = sub.add_parser(
        "enrich", help="fill question/summary frontmatter via the LLM",
    )
    enrich_cmd.add_argument("--project", default=None)
    enrich_cmd.add_argument("--note", default=None)
    enrich_cmd.set_defaults(func=cmd_enrich)


# ── HTTP client ───────────────────────────────────────────────────────


def service_base_url() -> str:
    """Return ``http://<KB_SVC_HOST>:<KB_SVC_PORT>``."""
    host = os.environ.get("KB_SVC_HOST", DEFAULT_HOST)
    port = os.environ.get("KB_SVC_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def _request(
    method: str, path: str, payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Call the service and return parsed JSON, or raise loudly.

    Raises:
        RuntimeError: naming the endpoint and the error, for both an HTTP
            error status (with the response body) and an unreachable
            service. Never silently degrades: ``cli.main`` turns this into
            a non-zero exit with the message on stderr.
    """
    url = f"{service_base_url()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"kb service {method} {url} failed ({exc.code} {exc.reason}): {body}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"kb service unreachable: {method} {url} failed ({exc}). "
            "Start it with `docker compose up -d kb-svc`."
        ) from exc


def get_json(path: str) -> dict[str, object]:
    """GET a service endpoint."""
    return _request("GET", path)


def post_json(path: str, payload: dict[str, object]) -> dict[str, object]:
    """POST JSON to a service endpoint."""
    return _request("POST", path, payload)


def query_string(params: dict[str, object]) -> str:
    """Encode non-empty params into a leading-``?`` query string."""
    present = {key: str(value) for key, value in params.items() if value}
    return f"?{urllib.parse.urlencode(present)}" if present else ""


# ── command handlers ──────────────────────────────────────────────────


def cmd_init(_args: argparse.Namespace) -> int:
    """Create the vault dirs through the service."""
    print(json.dumps(post_json("/vault/init", {})))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Create a project's four note dirs through the service."""
    print(json.dumps(post_json("/project/init", {"project": args.project})))
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    """Print the vault path the service reports for a project."""
    result = get_json(f"/project{query_string({'project': args.project})}")
    print(result["path"])
    return 0


def cmd_index(_args: argparse.Namespace) -> int:
    """Rebuild the derived index and embeddings from the vault alone."""
    print(json.dumps(post_json("/reindex", {})))
    return 0


def cmd_clip(args: argparse.Namespace) -> int:
    """Capture a URL into the vault (atomized and indexed by the service)."""
    payload = {"url": args.url, "project": args.project}
    print(json.dumps(post_json("/clip", payload)))
    return 0


def cmd_put(args: argparse.Namespace) -> int:
    """Write a note, body read from stdin."""
    payload = {
        "project": args.project,
        "title": args.title,
        "type": args.type,
        "source": args.source,
        "content": sys.stdin.read(),
    }
    print(json.dumps(post_json("/put", payload)))
    return 0


def cmd_atomize(args: argparse.Namespace) -> int:
    """Ingest a URL or stdin content and split it into atomic notes."""
    payload: dict[str, object] = {
        "project": args.project, "title": args.title, "type": args.type,
    }
    if args.url:
        payload["url"] = args.url
    else:
        payload["content"] = sys.stdin.read()
    print(json.dumps(post_json("/atomize", payload)))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Hybrid keyword + vector search."""
    params: dict[str, object] = {
        "q": args.q,
        "project": args.project,
        "type": args.type,
        "all": "1" if args.all else None,
    }
    print(json.dumps(get_json(f"/query{query_string(params)}"), indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    """Print the vault root, whether it is initialized, and its projects."""
    print(json.dumps(get_json("/status")))
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """Fill question/summary frontmatter on unenriched notes via the LLM."""
    payload: dict[str, object] = {}
    if args.project:
        payload["project"] = args.project
    if args.note:
        payload["note"] = args.note
    print(json.dumps(post_json("/enrich", payload)))
    return 0
