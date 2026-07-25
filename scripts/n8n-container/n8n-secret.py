#!/usr/bin/env python3
"""Resolve n8n secrets (encryption key, Public API key) from n8n.env.

n8n's ``N8N_ENCRYPTION_KEY`` encrypts stored credentials inside n8n's own
sqlite DB. It is REQUIRED and must PERSIST across restarts -- losing or
changing it orphans every credential already stored. ``N8N_API_KEY`` is
OPTIONAL: it authenticates agent calls to n8n's Public REST API and has no
effect on n8n's own startup. This script is the standalone equivalent of
kb-serve.py's load_kb_env / resolve_api_key / cmd_resolve_secret trio,
mirrored here because the official n8n image is not our source (there is
no n8n app of ours to hang this off of).

Config file: ``<data-dir>/n8n.env`` (default data dir ``~/.local/share/n8n``,
beside the persistent DB it configures -- mirrors kb.env living beside the
KB it configures). Each secret has two mutually exclusive modes, vault
command wins:

    N8N_ENCRYPTION_KEY      -- static value (simplest, least secure)
    N8N_ENCRYPTION_KEY_CMD  -- a vault CLI command; its stdout is the key
    N8N_API_KEY              -- static value (simplest, least secure)
    N8N_API_KEY_CMD           -- a vault CLI command; its stdout is the key

Neither resolved value is ever logged.

``resolve-secret`` prints exactly one line, ``N8N_ENCRYPTION_KEY=<value>``,
which the quadlet's ExecStartPre writes to a tmpfs ``%t/n8n.env`` (mode
0600, gone at logout) for ``EnvironmentFile=`` to load. An unset/empty key
still prints the line with an empty value (exit 0); n8n itself then fails
fast at startup, the intended loud failure for an unconfigured deploy.

``resolve-api-key`` prints the raw key only (no ``KEY=`` prefix), meant for
capture into a shell variable for a curl header. It has no such startup
safety net, so it fails loudly itself: exit 1 with a stderr message if
unresolved.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "load_n8n_env",
    "resolve_encryption_key",
    "resolve_api_key",
    "cmd_resolve_secret",
    "cmd_resolve_api_key",
]

log = logging.getLogger("n8n-secret")

DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "n8n"
VAULT_CMD_TIMEOUT_SEC = 15


def load_n8n_env(data_dir: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines from ``<data_dir>/n8n.env``.

    Missing file, blank lines, and '#' comments are silently skipped;
    never raises. Not a shell parser -- values may be optionally wrapped
    in matching quotes, nothing fancier (matches n8n.env.example's shape,
    identical to kb-serve.py's load_kb_env).

    Postcondition: returns a dict of the KEY=VALUE pairs found (possibly
    empty); never raises for a missing or malformed file.
    """
    env_path = data_dir / "n8n.env"
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_encryption_key(env: Mapping[str, str]) -> str | None:
    """Resolve the n8n encryption key from parsed config.

    ``N8N_ENCRYPTION_KEY_CMD`` (a vault CLI command, e.g. Proton Pass's
    ``pass-cli item view ... --field password``) wins over a static
    ``N8N_ENCRYPTION_KEY``. Returns None if neither yields a value.

    Precondition: ``env`` is the merged mapping (file under process env).
    Postcondition: the resolved value is NEVER written to a log; a failed
    vault command is logged only by its exception text, never its output.
    """
    cmd = env.get("N8N_ENCRYPTION_KEY_CMD", "").strip()
    if cmd:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=VAULT_CMD_TIMEOUT_SEC, check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("N8N_ENCRYPTION_KEY_CMD failed (%s); no key resolved", exc)
            return None
        return result.stdout.strip() or None
    return env.get("N8N_ENCRYPTION_KEY", "").strip() or None


def resolve_api_key(env: Mapping[str, str]) -> str | None:
    """Resolve the n8n Public API key from parsed config.

    ``N8N_API_KEY_CMD`` (a vault CLI command) wins over a static
    ``N8N_API_KEY``. Returns None if neither yields a value. Symmetric to
    ``resolve_encryption_key`` above; same precedence, same
    subprocess-failure handling, same never-log-the-value rule.

    Precondition: ``env`` is the merged mapping (file under process env).
    Postcondition: the resolved value is NEVER written to a log; a failed
    vault command is logged only by its exception text, never its output.
    """
    cmd = env.get("N8N_API_KEY_CMD", "").strip()
    if cmd:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=VAULT_CMD_TIMEOUT_SEC, check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("N8N_API_KEY_CMD failed (%s); no key resolved", exc)
            return None
        return result.stdout.strip() or None
    return env.get("N8N_API_KEY", "").strip() or None


def cmd_resolve_secret(args: argparse.Namespace) -> int:
    """Print exactly ``N8N_ENCRYPTION_KEY=<value>`` for an EnvironmentFile=.

    The only line ever written to stdout; the resolved value is never
    logged. Empty value (key still printed, blank) when neither mode
    resolves -- callers treat that identically to "no key configured".
    """
    merged = {**load_n8n_env(args.data_dir), **os.environ}
    print(f"N8N_ENCRYPTION_KEY={resolve_encryption_key(merged) or ''}")
    return 0


def cmd_resolve_api_key(args: argparse.Namespace) -> int:
    """Print the raw N8N Public API key to stdout, for capture into a shell
    variable (e.g. ``KEY=$(n8n-secret.py resolve-api-key)``) to pass as a
    curl ``X-N8N-API-KEY`` header.

    Unlike ``cmd_resolve_secret``, there is no downstream "n8n fails loudly
    at startup" safety net for an unresolved key -- this CLI must fail
    loudly itself. Prints nothing but an error to stderr and returns exit
    code 1 if the key does not resolve.
    """
    merged = {**load_n8n_env(args.data_dir), **os.environ}
    key = resolve_api_key(merged)
    if key is None:
        print(
            "no N8N_API_KEY / N8N_API_KEY_CMD resolved "
            f"(checked {args.data_dir / 'n8n.env'} and the process env)",
            file=sys.stderr,
        )
        return 1
    print(key)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Parser with the ``resolve-secret`` and ``resolve-api-key`` subcommands."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    secret_cmd = sub.add_parser(
        "resolve-secret",
        help="print the resolved N8N_ENCRYPTION_KEY for a systemd EnvironmentFile=",
    )
    secret_cmd.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="n8n data dir holding n8n.env (default: ~/.local/share/n8n)",
    )
    secret_cmd.set_defaults(func=cmd_resolve_secret)

    api_key_cmd = sub.add_parser(
        "resolve-api-key",
        help="print the raw N8N Public API key for a shell variable / curl header",
    )
    api_key_cmd.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="n8n data dir holding n8n.env (default: ~/.local/share/n8n)",
    )
    api_key_cmd.set_defaults(func=cmd_resolve_api_key)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the parsed subcommand. Returns its exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
