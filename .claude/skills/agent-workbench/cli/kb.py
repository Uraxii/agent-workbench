"""`kb` subcommand -- pure-Python port of scripts/kb.sh.

Personal machine-local knowledgebase vault ops. Subcommands:
    init                       create the vault (idempotent)
    add PROJECT                create PROJECT's note dirs (idempotent)
    path PROJECT               print $KB_HOME/PROJECT
    index                      rebuild the global FTS5 index
    clip URL [--project P]     deterministic web-source capture
    put PROJECT TITLE [...]    write a note (body on stdin)
    query Q [--project P ...]  FTS5 search
    atomize FILE               deterministic split into atomic notes
    status                     JSON: kb_home, initialized?, projects

Service-vs-in-process fallback (PRESERVED from kb.sh): clip / put / query
prefer the running kb-serve.py HTTP service when it answers /health, so
that path also atomizes + reindexes; otherwise they call the same
kb-serve.py functions in-process. init / add / path / index / atomize /
status never need the service.

Folded audit fixes:
  * M3: honor KB_SERVE_HOST, not only KB_SERVE_PORT (kb.sh:36 hardcoded
    127.0.0.1). See ``service_base_url``.
  * LOW: surface a JSON/text error BODY on an HTTP-path failure instead of
    swallowing it the way ``curl -sf`` did. See ``_post_json`` / ``_get``.
  * H1 (inherited, automatic): the clip path delegates to kb-serve.py ->
    kb-clip.clip -> fetch_html -> check_url_scheme, so kb-clip.py's
    http/https scheme allowlist is preserved verbatim with zero code here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cli import siblings

__all__ = ["register", "service_base_url", "service_up"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9100
HEALTH_TIMEOUT_SEC = 1.0
NOTE_DIRS = ("decisions", "notes", "research", "sources")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `kb` parser and its own sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("kb", help="knowledgebase vault ops")
    sub = parser.add_subparsers(dest="kb_command", required=True)

    init_cmd = sub.add_parser("init", help="create the vault (idempotent)")
    init_cmd.add_argument("--kb-home", default=None)
    init_cmd.set_defaults(func=cmd_init)

    add_cmd = sub.add_parser("add", help="create PROJECT's note dirs (idempotent)")
    add_cmd.add_argument("project")
    add_cmd.add_argument("--kb-home", default=None)
    add_cmd.set_defaults(func=cmd_add)

    path_cmd = sub.add_parser("path", help="print $KB_HOME/PROJECT")
    path_cmd.add_argument("project")
    path_cmd.add_argument("--kb-home", default=None)
    path_cmd.set_defaults(func=cmd_path)

    index_cmd = sub.add_parser("index", help="rebuild the global FTS5 index")
    index_cmd.add_argument("--kb-home", default=None)
    index_cmd.set_defaults(func=cmd_index)

    clip_cmd = sub.add_parser("clip", help="deterministic web-source capture")
    clip_cmd.add_argument("url")
    clip_cmd.add_argument("--project", default="inbox")
    clip_cmd.add_argument("--kb-home", default=None)
    clip_cmd.set_defaults(func=cmd_clip)

    put_cmd = sub.add_parser("put", help="write a note (body on stdin)")
    put_cmd.add_argument("project")
    put_cmd.add_argument("title")
    put_cmd.add_argument("--type", default="note")
    put_cmd.add_argument("--source", default="")
    put_cmd.add_argument("--kb-home", default=None)
    put_cmd.set_defaults(func=cmd_put)

    query_cmd = sub.add_parser("query", help="FTS5 search")
    query_cmd.add_argument("q")
    query_cmd.add_argument("--project", default=None)
    query_cmd.add_argument("--type", default=None)
    query_cmd.add_argument("--all", action="store_true", help="include superseded notes")
    query_cmd.add_argument("--kb-home", default=None)
    query_cmd.set_defaults(func=cmd_query)

    atomize_cmd = sub.add_parser("atomize", help="deterministic split into atomic notes")
    atomize_cmd.add_argument("file")
    atomize_cmd.add_argument("--kb-home", default=None)
    atomize_cmd.set_defaults(func=cmd_atomize)

    status_cmd = sub.add_parser("status", help="JSON: kb_home, initialized?, projects")
    status_cmd.add_argument("--kb-home", default=None)
    status_cmd.set_defaults(func=cmd_status)


# ── service discovery (M3 fix folded in) ──────────────────────────────


def service_base_url() -> str:
    """Return the kb-serve base URL from env.

    M3 fix: reads BOTH ``KB_SERVE_HOST`` (default 127.0.0.1) and
    ``KB_SERVE_PORT`` (default 9100); kb.sh:36 ignored KB_SERVE_HOST.
    Postcondition: a well-formed ``http://<host>:<port>`` string.
    """
    host = os.environ.get("KB_SERVE_HOST", DEFAULT_HOST)
    port = os.environ.get("KB_SERVE_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def service_up() -> bool:
    """True iff the kb-serve /health endpoint answers 200 within timeout.

    Never raises; a connection refusal / timeout returns False (the caller
    then takes the in-process path).
    """
    try:
        with urllib.request.urlopen(
            f"{service_base_url()}/health", timeout=HEALTH_TIMEOUT_SEC
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


# ── HTTP path helpers (LOW fix: surface error bodies) ──────────────────


def _do_request(request: urllib.request.Request, label: str) -> dict[str, object]:
    """Shared GET/POST execution: parse JSON, or raise with the error body.

    LOW fix: an HTTP error status's response body is read and folded into
    the raised error instead of being dropped the way ``curl -sf`` did.
    """
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"kb-serve {label} failed ({exc.code}): {body}") from exc


def _get(path_and_query: str) -> dict[str, object]:
    """GET the service, returning parsed JSON.

    LOW fix: on an HTTP error status, read and include the response body
    text in the raised error, rather than dropping it like ``curl -sf``.
    """
    url = f"{service_base_url()}{path_and_query}"
    return _do_request(urllib.request.Request(url, method="GET"), f"GET {path_and_query}")


def _post_json(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    """POST JSON to the service, returning parsed JSON.

    LOW fix: on an HTTP error status, surface the response body in the
    raised error.
    """
    url = f"{service_base_url()}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"},
    )
    return _do_request(request, f"POST {endpoint}")


# ── command handlers ──────────────────────────────────────────────────


def resolve_kb_home(explicit: str | None) -> Path:
    """Resolve KB_HOME: explicit arg, else $KB_HOME, else ~/.knowledgebase."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("KB_HOME")
    return Path(env) if env else Path.home() / ".knowledgebase"


def cmd_init(args: argparse.Namespace) -> int:
    """Create ``$KB_HOME/.obsidian`` and ``$KB_HOME/index`` (idempotent)."""
    kb_home = resolve_kb_home(args.kb_home)
    (kb_home / ".obsidian").mkdir(parents=True, exist_ok=True)
    (kb_home / "index").mkdir(parents=True, exist_ok=True)
    print(f"kb: vault ready at {kb_home}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Create the four note dirs for a project under KB_HOME (idempotent)."""
    cmd_init(args)
    kb_home = resolve_kb_home(args.kb_home)
    for note_dir in NOTE_DIRS:
        (kb_home / args.project / note_dir).mkdir(parents=True, exist_ok=True)
    print(f"kb: {args.project} ready at {kb_home / args.project}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    """Print ``$KB_HOME/<project>``."""
    print(resolve_kb_home(args.kb_home) / args.project)
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Rebuild the global FTS5 index (in-process kb-serve.build_index)."""
    kb_home = resolve_kb_home(args.kb_home)
    kb_serve = siblings.load_kb_serve()
    kb_serve.build_index(kb_home)
    return 0


def cmd_clip(args: argparse.Namespace) -> int:
    """Capture a URL. HTTP service if up (atomizes+reindexes), else
    in-process kb-serve.kb_clip_and_atomize."""
    payload = {"url": args.url, "project": args.project}
    if service_up():
        result = _post_json("/clip", payload)
    else:
        kb_serve = siblings.load_kb_serve()
        result = kb_serve.kb_clip_and_atomize(resolve_kb_home(args.kb_home), payload)
    print(json.dumps(result))
    return 0


def cmd_put(args: argparse.Namespace) -> int:
    """Write a note (body read from stdin). HTTP service if up, else
    in-process kb-serve.kb_put."""
    payload = {
        "project": args.project, "title": args.title, "type": args.type,
        "source": args.source, "content": sys.stdin.read(),
    }
    if service_up():
        result = _post_json("/put", payload)
    else:
        kb_serve = siblings.load_kb_serve()
        kb_home = resolve_kb_home(args.kb_home)
        result = kb_serve.kb_put(kb_home, kb_serve.build_config(kb_home), payload)
    print(json.dumps(result))
    return 0


def _query_path_and_query(args: argparse.Namespace) -> str:
    """Build the GET /query path+query string from parsed CLI args."""
    query = urllib.parse.urlencode({"q": args.q})
    path_and_query = f"/query?{query}"
    if args.project:
        path_and_query += f"&project={urllib.parse.quote(args.project)}"
    if args.type:
        path_and_query += f"&type={urllib.parse.quote(args.type)}"
    if args.all:
        path_and_query += "&all=1"
    return path_and_query


def cmd_query(args: argparse.Namespace) -> int:
    """FTS5 search. HTTP service if up, else in-process kb-serve.run_query."""
    if service_up():
        result = _get(_query_path_and_query(args))
    else:
        kb_serve = siblings.load_kb_serve()
        kb_home = resolve_kb_home(args.kb_home)
        results = kb_serve.run_query(kb_home, args.q, args.project, args.type, args.all)
        result = {"results": results}
    print(json.dumps(result, indent=2))
    return 0


def cmd_atomize(args: argparse.Namespace) -> int:
    """Deterministic split of a note into atomic children (in-process)."""
    note_path = Path(args.file).resolve()
    kb_serve = siblings.load_kb_serve()
    children = kb_serve.kb_atomize(note_path, resolve_kb_home(args.kb_home))
    print(json.dumps({"parent": str(note_path), "children": [str(p) for p in children]}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print JSON: ``{kb_home, initialized, projects[]}``."""
    kb_home = resolve_kb_home(args.kb_home)
    initialized = (kb_home / ".obsidian").is_dir()
    projects: list[str] = []
    if initialized:
        projects = sorted(
            entry.name for entry in kb_home.iterdir()
            if entry.is_dir() and entry.name not in (".obsidian", "index")
        )
    print(json.dumps({"kb_home": str(kb_home), "initialized": initialized, "projects": projects}))
    return 0
