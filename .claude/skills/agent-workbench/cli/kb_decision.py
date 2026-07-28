"""`kb decision` sub-subcommands -- HTTP client for decision notes.

A decision is one markdown file under ``<kb_home>/<project>/decisions/``,
grouped by a stable ``topic`` key, and the knowledgebase service writes
it. All the logic -- the frontmatter dialect, the revision flip and
the chain walk that orders an audit -- lives in ``scripts/kb_decision.py``
inside that service. This module only parses arguments, calls the
endpoint, and formats the answer.

Sub-subcommands (registered under `kb` by ``cli.kb``):
    decision record --topic T --title T --text T --project P [...]
        -> POST /decision
    decision audit TOPIC [--project P] [--human]
        -> GET  /decision/audit
"""
from __future__ import annotations

import argparse
import json

__all__ = ["register", "cmd_record", "cmd_audit"]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `decision` parser and its record/audit verbs to `kb`.

    Postcondition: both leaf parsers have ``func`` set to a ``cmd_*``
    handler, matching the dispatch contract in ``cli.main.main``.
    """
    parser = subparsers.add_parser(
        "decision", help="record/audit dated decision notes",
    )
    sub = parser.add_subparsers(dest="decision_command", required=True)

    record_cmd = sub.add_parser("record", help="record a new decision")
    record_cmd.add_argument("--project", required=True)
    record_cmd.add_argument("--topic", required=True)
    record_cmd.add_argument("--title", required=True)
    record_cmd.add_argument("--text", required=True)
    record_cmd.add_argument("--rationale", default="")
    record_cmd.add_argument("--refs", default="")
    record_cmd.add_argument("--tags", default="", help="comma-separated")
    record_cmd.add_argument(
        "--revises",
        default=None,
        help="path of the note to revise; default is the topic's "
             "current active note",
    )
    record_cmd.set_defaults(func=cmd_record)

    audit_cmd = sub.add_parser("audit", help="show a topic's decision chain")
    audit_cmd.add_argument("topic")
    audit_cmd.add_argument(
        "--project",
        default=None,
        help="narrow to one project; default scans every project",
    )
    audit_cmd.add_argument(
        "--human", action="store_true", help="table instead of JSON",
    )
    audit_cmd.set_defaults(func=cmd_audit)


def cmd_record(args: argparse.Namespace) -> int:
    """Record a decision through the service and print the result JSON.

    The service revises the topic's prior active note and reindexes in
    the same call, so a just-recorded decision is immediately findable by
    `kb query`.
    """
    from cli import kb

    payload: dict[str, object] = {
        "project": args.project,
        "topic": args.topic,
        "title": args.title,
        "text": args.text,
        "rationale": args.rationale,
        "refs": args.refs,
        "tags": args.tags,
    }
    if args.revises:
        payload["revises"] = args.revises
    print(json.dumps(kb.post_json("/decision", payload)))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Print a topic's decision chain: JSON by default, table with --human.

    Read-only. The service scans every project's decisions dir unless
    ``--project`` narrows it, because topic keys are globally unique by
    convention and a reader auditing a topic rarely knows which project
    holds it.
    """
    from cli import kb

    params = {"topic": args.topic, "project": args.project}
    result = kb.get_json(f"/decision/audit{kb.query_string(params)}")
    chain = result.get("chain", [])
    if args.human:
        for note in chain:
            print(
                f"{note['date']}  {note['status']:12} {note['title']}"
                f"  (revises: {note['revises'] or '-'})"
            )
        return 0
    print(json.dumps(chain, indent=2))
    return 0
