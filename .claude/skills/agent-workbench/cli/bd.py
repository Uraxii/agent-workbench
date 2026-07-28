"""`bd` subcommand: HTTP client for the bd-svc board service.

Carries no board logic of its own. Every verb is one POST to bd-svc
(``scripts/bd-svc.py``), which owns ``~/.beads-hub`` and is the only thing
that runs the ``bd`` binary. There is deliberately NO in-process fallback: if
the service is down, the verb fails loudly naming the endpoint URL and the
underlying error, rather than quietly touching the board on disk.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

__all__ = [
    "cmd_add",
    "cmd_children",
    "cmd_close",
    "cmd_create",
    "cmd_dep",
    "cmd_init",
    "cmd_link",
    "cmd_list",
    "cmd_note",
    "cmd_path",
    "cmd_priority",
    "cmd_ready",
    "cmd_repos",
    "cmd_search",
    "cmd_show",
    "cmd_status",
    "cmd_sync",
    "cmd_update",
    "register",
    "service_base_url",
]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9101
# Comfortably above bd-svc's own 30s subprocess timeout, so a slow `bd`
# surfaces as the service's 502 rather than as a client-side timeout.
REQUEST_TIMEOUT_SEC = 60.0


def service_base_url() -> str:
    host = os.environ.get("BD_SVC_HOST", DEFAULT_HOST)
    port = os.environ.get("BD_SVC_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def _post_json(endpoint: str, payload: dict[str, object]) -> dict[str, object]:
    url = f"{service_base_url()}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"bd-svc POST {endpoint} failed ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        raise RuntimeError(f"bd-svc unreachable at {url}: {reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"bd-svc unreachable at {url}: {exc}") from exc


def _print_result(endpoint: str, payload: dict[str, object]) -> int:
    print(json.dumps(_post_json(endpoint, payload)))
    return 0


def _board_payload(args: argparse.Namespace) -> dict[str, object]:
    return {"board": args.board}


def cmd_init(args: argparse.Namespace) -> int:
    return _print_result("/hub/init", {})


def cmd_add(args: argparse.Namespace) -> int:
    payload: dict[str, object] = {"name": args.name}
    if args.prefix is not None:
        payload["prefix"] = args.prefix
    return _print_result("/hub/add", payload)


def cmd_sync(args: argparse.Namespace) -> int:
    return _print_result("/hub/sync", {})


def cmd_repos(args: argparse.Namespace) -> int:
    return _print_result("/hub/repos", {})


def cmd_path(args: argparse.Namespace) -> int:
    return _print_result("/hub/path", {"name": args.name})


def cmd_status(args: argparse.Namespace) -> int:
    return _print_result("/hub/status", {})


def cmd_list(args: argparse.Namespace) -> int:
    payload = _board_payload(args)
    if args.status is not None:
        payload["status"] = args.status
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    if args.label:
        payload["labels"] = args.label
    if args.limit is not None:
        payload["limit"] = args.limit
    if args.all:
        payload["all"] = True
    return _print_result("/issue/list", payload)


def cmd_show(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id}
    return _print_result("/issue/show", payload)


def cmd_create(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "title": args.title}
    if args.description is not None:
        payload["description"] = args.description
    if args.priority is not None:
        payload["priority"] = args.priority
    if args.label:
        payload["labels"] = args.label
    if args.parent is not None:
        payload["parent"] = args.parent
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    return _print_result("/issue/create", payload)


def cmd_update(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id}
    if args.status is not None:
        payload["status"] = args.status
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    if args.priority is not None:
        payload["priority"] = args.priority
    if args.description is not None:
        payload["description"] = args.description
    if args.add_label:
        payload["add_labels"] = args.add_label
    if args.remove_label:
        payload["remove_labels"] = args.remove_label
    if args.claim:
        payload["claim"] = True
    if args.overwrite_description:
        payload["overwrite_description"] = True
    return _print_result("/issue/update", payload)


def cmd_close(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id}
    if args.reason is not None:
        payload["reason"] = args.reason
    return _print_result("/issue/close", payload)


def cmd_note(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id, "text": args.text}
    return _print_result("/issue/note", payload)


def cmd_link(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "from_id": args.from_id, "to_id": args.to_id}
    if args.type is not None:
        payload["type"] = args.type
    return _print_result("/issue/link", payload)


def cmd_children(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id}
    return _print_result("/issue/children", payload)


def cmd_priority(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id, "priority": args.priority}
    return _print_result("/issue/priority", payload)


def cmd_ready(args: argparse.Namespace) -> int:
    payload = _board_payload(args)
    if args.assignee is not None:
        payload["assignee"] = args.assignee
    if args.label:
        payload["labels"] = args.label
    if args.limit is not None:
        payload["limit"] = args.limit
    return _print_result("/issue/ready", payload)


def cmd_search(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "query": args.query}
    if args.status is not None:
        payload["status"] = args.status
    if args.limit is not None:
        payload["limit"] = args.limit
    return _print_result("/issue/search", payload)


def cmd_dep(args: argparse.Namespace) -> int:
    payload = {**_board_payload(args), "id": args.id}
    if args.direction is not None:
        payload["direction"] = args.direction
    if args.type is not None:
        payload["type"] = args.type
    return _print_result("/issue/dep", payload)


def _add_board_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--board", required=True)


def _register_hub(sub: argparse._SubParsersAction) -> None:
    init_cmd = sub.add_parser("init", help="init the aggregator board")
    init_cmd.set_defaults(func=cmd_init)

    add_cmd = sub.add_parser("add", help="create+register a board")
    add_cmd.add_argument("name")
    add_cmd.add_argument("prefix", nargs="?", default=None)
    add_cmd.set_defaults(func=cmd_add)

    sync_cmd = sub.add_parser("sync", help="sync registered repos")
    sync_cmd.set_defaults(func=cmd_sync)

    repos_cmd = sub.add_parser("repos", help="list registered repos")
    repos_cmd.set_defaults(func=cmd_repos)

    path_cmd = sub.add_parser("path", help="print a board path")
    path_cmd.add_argument("name")
    path_cmd.set_defaults(func=cmd_path)

    status_cmd = sub.add_parser("status", help="JSON: hub_root, initialized, repos")
    status_cmd.set_defaults(func=cmd_status)


def _register_issue_read(sub: argparse._SubParsersAction) -> None:
    list_cmd = sub.add_parser("list", help="list issues")
    _add_board_arg(list_cmd)
    list_cmd.add_argument("--status", default=None)
    list_cmd.add_argument("--assignee", default=None)
    list_cmd.add_argument("--label", action="append", default=[])
    list_cmd.add_argument("--limit", default=None)
    list_cmd.add_argument("--all", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    show_cmd = sub.add_parser("show", help="show an issue")
    show_cmd.add_argument("id")
    _add_board_arg(show_cmd)
    show_cmd.set_defaults(func=cmd_show)

    children_cmd = sub.add_parser("children", help="list child issues")
    children_cmd.add_argument("id")
    _add_board_arg(children_cmd)
    children_cmd.set_defaults(func=cmd_children)

    ready_cmd = sub.add_parser("ready", help="list ready issues")
    _add_board_arg(ready_cmd)
    ready_cmd.add_argument("--assignee", default=None)
    ready_cmd.add_argument("--label", action="append", default=[])
    ready_cmd.add_argument("--limit", default=None)
    ready_cmd.set_defaults(func=cmd_ready)

    search_cmd = sub.add_parser("search", help="search issues")
    search_cmd.add_argument("query")
    _add_board_arg(search_cmd)
    search_cmd.add_argument("--status", default=None)
    search_cmd.add_argument("--limit", default=None)
    search_cmd.set_defaults(func=cmd_search)

    dep_cmd = sub.add_parser("dep", help="list issue dependencies")
    dep_cmd.add_argument("id")
    _add_board_arg(dep_cmd)
    dep_cmd.add_argument("--direction", choices=("up", "down"), default=None)
    dep_cmd.add_argument("--type", default=None)
    dep_cmd.set_defaults(func=cmd_dep)


def _register_issue_write(sub: argparse._SubParsersAction) -> None:
    create_cmd = sub.add_parser("create", help="create an issue")
    create_cmd.add_argument("title")
    _add_board_arg(create_cmd)
    create_cmd.add_argument("-d", "--description", default=None)
    create_cmd.add_argument("-p", "--priority", default=None)
    create_cmd.add_argument("-l", "--label", action="append", default=[])
    create_cmd.add_argument("--parent", default=None)
    create_cmd.add_argument("--assignee", default=None)
    create_cmd.set_defaults(func=cmd_create)

    update_cmd = sub.add_parser("update", help="update an issue")
    update_cmd.add_argument("id")
    _add_board_arg(update_cmd)
    update_cmd.add_argument("--status", default=None)
    update_cmd.add_argument("--assignee", default=None)
    update_cmd.add_argument("-p", "--priority", default=None)
    update_cmd.add_argument("-d", "--description", default=None)
    update_cmd.add_argument("--add-label", action="append", default=[])
    update_cmd.add_argument("--remove-label", action="append", default=[])
    update_cmd.add_argument("--claim", action="store_true")
    update_cmd.add_argument("--overwrite-description", action="store_true")
    update_cmd.set_defaults(func=cmd_update)

    close_cmd = sub.add_parser("close", help="close an issue")
    close_cmd.add_argument("id")
    _add_board_arg(close_cmd)
    close_cmd.add_argument("--reason", default=None)
    close_cmd.set_defaults(func=cmd_close)

    note_cmd = sub.add_parser("note", help="add an issue note")
    note_cmd.add_argument("id")
    note_cmd.add_argument("text")
    _add_board_arg(note_cmd)
    note_cmd.set_defaults(func=cmd_note)


def _register_issue_linking(sub: argparse._SubParsersAction) -> None:
    link_cmd = sub.add_parser("link", help="link two issues")
    link_cmd.add_argument("from_id")
    link_cmd.add_argument("to_id")
    _add_board_arg(link_cmd)
    link_cmd.add_argument("--type", default=None)
    link_cmd.set_defaults(func=cmd_link)

    priority_cmd = sub.add_parser("priority", help="set issue priority")
    priority_cmd.add_argument("id")
    priority_cmd.add_argument("priority")
    _add_board_arg(priority_cmd)
    priority_cmd.set_defaults(func=cmd_priority)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("bd", help="bd (beads) board hub + issue ops")
    sub = parser.add_subparsers(dest="bd_command", required=True)
    _register_hub(sub)
    _register_issue_read(sub)
    _register_issue_write(sub)
    _register_issue_linking(sub)
