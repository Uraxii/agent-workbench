"""`artifact` subcommand -- thin facade over
``.claude/skills/artifact-serve/scripts/artifact-serve.py`` (the artifact
review app: deep-zoom image gallery, pin-to-region annotations, threaded
resolvable comments).

Subcommands:
    publish              stage an artifact for review          [push]
    feedback             dump threads + replies as JSON        [feedback]
    serve [--foreground] start (or reuse) the local daemon,     [start/run]
                          or run it supervised in the foreground
    status                daemon pid/port + staged entries      [status]

Same load-by-path facade shape as `kb.py` over kb-serve.py: each handler
here loads artifact-serve.py in-process via ``cli.siblings`` and calls
straight into its own already-implemented ``cmd_*`` functions, passing an
``argparse.Namespace`` shaped exactly like the attributes those functions
already expect. No logic is reimplemented here.
"""
from __future__ import annotations

import argparse
import os

from cli import siblings

__all__ = ["register"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9099


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `artifact` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("artifact", help="artifact review app ops")
    sub = parser.add_subparsers(dest="artifact_command", required=True)

    publish_cmd = sub.add_parser("publish", help="stage an artifact for review")
    publish_cmd.add_argument("--project", required=True)
    publish_cmd.add_argument("--src", required=True)
    publish_cmd.add_argument("--as", dest="as_name", default=None)
    publish_cmd.add_argument(
        "--id", dest="artifact_id", default=None,
        help="Artifact ID for feedback correlation. Default: <project>/<subdir>.",
    )
    publish_cmd.set_defaults(func=cmd_publish)

    feedback_cmd = sub.add_parser(
        "feedback", help="dump threads + reply chains for an artifact as JSON",
    )
    feedback_cmd.add_argument("--artifact", dest="artifact_id", required=True)
    feedback_cmd.set_defaults(func=cmd_feedback)

    serve_cmd = sub.add_parser("serve", help="start (or reuse) the local daemon")
    serve_cmd.add_argument(
        "--port", type=int,
        default=int(os.environ.get("ARTIFACT_SERVE_PORT", DEFAULT_PORT)),
    )
    serve_cmd.add_argument(
        "--host", default=os.environ.get("ARTIFACT_SERVE_HOST", DEFAULT_HOST),
    )
    serve_cmd.add_argument("--expose", action="store_true", help="Also publish via tailscale.")
    serve_cmd.add_argument(
        "--foreground", action="store_true",
        help="Run in the foreground (no fork/pidfile); for container/systemd supervision.",
    )
    serve_cmd.set_defaults(func=cmd_serve)

    status_cmd = sub.add_parser("status", help="daemon pid/port + staged entries")
    status_cmd.set_defaults(func=cmd_status)


def cmd_publish(args: argparse.Namespace) -> int:
    """Stage an artifact for review (artifact-serve.py's `push` verb)."""
    return siblings.load_artifact_serve().cmd_push(args)


def cmd_feedback(args: argparse.Namespace) -> int:
    """Dump feedback JSON for an artifact (artifact-serve.py's `feedback` verb)."""
    return siblings.load_artifact_serve().cmd_feedback(args)


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the daemon: foregrounded (`run`) if --foreground, else `start`."""
    impl = siblings.load_artifact_serve()
    if args.foreground:
        return impl.cmd_run(args)
    return impl.cmd_start(args)


def cmd_status(args: argparse.Namespace) -> int:
    """Daemon pid/port + staged entries (artifact-serve.py's `status` verb)."""
    return siblings.load_artifact_serve().cmd_status(args)
