"""`kb embed` sub-subcommands -- HTTP client for the bounded, resumable
vector backfill.

Backfilling embeddings is the one thing a normal ingest deliberately does
NOT do for the whole vault (see scripts/kb_embed.py's staleness rule).
This module is the operator-facing way to run that backfill in bounded
batches instead of paying for a whole-vault re-embed on the next
`kb put`.

Sub-subcommands (registered under `kb` by `cli.kb`):
    embed missing [--dry-run]
        -> POST /embed/missing
        Embed only notes never embedded or changed since.
    embed all [--dry-run]
        -> POST /embed/all
        Mark every note stale, then run one bounded batch.

Both answers carry a `next` field naming the exact command to run again;
call it until `next` is null. There is no `--limit`: the batch size is a
fixed module constant (`kb_embed.BACKFILL_BATCH_LIMIT`, 3 backend
requests x EMBED_TIMEOUT_SEC(30s) = 90s worst case), which stays inside
the CLI's 120s REQUEST_TIMEOUT_SEC with real margin.
"""
from __future__ import annotations

import argparse
import json

__all__ = ["register", "cmd_missing", "cmd_all"]


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `embed` parser and its missing/all verbs to `kb`."""
    parser = subparsers.add_parser(
        "embed", help="backfill embeddings for stale or all notes",
    )
    sub = parser.add_subparsers(dest="embed_command", required=True)
    missing_cmd = sub.add_parser(
        "missing", help="embed only notes never embedded or changed since",
    )
    missing_cmd.add_argument(
        "--dry-run", action="store_true",
        help="report exactly what would be sent, make zero network calls",
    )
    missing_cmd.set_defaults(func=cmd_missing)
    all_cmd = sub.add_parser(
        "all", help="mark every note stale, then run one batch",
    )
    all_cmd.add_argument(
        "--dry-run", action="store_true",
        help="report exactly what would be sent, make zero network calls",
    )
    all_cmd.set_defaults(func=cmd_all)


def cmd_missing(args: argparse.Namespace) -> int:
    """Embed only notes never embedded or changed since, one bounded batch."""
    from cli import kb

    print(json.dumps(kb.post_json("/embed/missing", {"dry_run": args.dry_run})))
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    """Mark every note stale, then embed one bounded batch."""
    from cli import kb

    print(json.dumps(kb.post_json("/embed/all", {"dry_run": args.dry_run})))
    return 0
