"""`scratch` subcommand -- run a command against a throwaway service
instance instead of the live stack.

    $AW scratch <kb|bd|artifact> -- <command...>

Brings up ONE disposable container for the named service on a free host
port against a fresh temp data dir, exports the env vars the existing
``kb``/``bd``/``artifact`` clients already read (``KB_SVC_HOST`` etc.) so
``<command...>`` transparently talks to it, runs the command, and tears the
container + temp dir down in a ``finally`` -- self-cleaning even on failure
or Ctrl-C. Exit code is the command's exit code.

This is the ONLY sanctioned way to HTTP-probe kb-svc/bd-svc/artifact-svc
for verification. Probing the live stack (the real ports 9099/9100/9101,
or the real ~/.knowledgebase / ~/.beads-hub / feedback dirs) leaves
permanent residue and is not an acceptable substitute.

Reuses ``docker-compose.yml`` (the one place the SELinux/rootless-podman
mount fixes live) via a small override, ``docker-compose.scratch.yml``, so
none of that hardening is reimplemented here. See that file's header for
why it does its own placeholder substitution instead of a compose
``${VAR}``.

No separate up/down mode: chain multi-step probes inside the single
wrapped command, e.g. ``-- bash -c 'first && second'``.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import NamedTuple

from cli import paths

__all__ = ["register"]

HEALTH_POLL_TRIES = 20
HEALTH_POLL_DELAY_SEC = 0.5
DOWN_TIMEOUT_SEC = 5
SCRATCH_PLACEHOLDER = "__AW_SCRATCH__"


class ServiceSpec(NamedTuple):
    """Everything `scratch` needs to know about one compose service."""

    compose_name: str
    internal_port: int
    health_path: str
    host_env: str
    port_env: str
    data_subdirs: tuple[str, ...]  # relative to the scratch dir; "" = root


SERVICES: dict[str, ServiceSpec] = {
    "kb": ServiceSpec(
        "kb-svc", 9100, "/health", "KB_SVC_HOST", "KB_SVC_PORT", ("",),
    ),
    "bd": ServiceSpec(
        "bd-svc", 9101, "/health", "BD_SVC_HOST", "BD_SVC_PORT", ("",),
    ),
    "artifact": ServiceSpec(
        "artifact-svc", 9099, "/_/health",
        "ARTIFACT_SVC_HOST", "ARTIFACT_SVC_PORT", ("stage", "feedback"),
    ),
}


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `scratch` parser: SERVICE followed by `-- COMMAND...`."""
    parser = subparsers.add_parser(
        "scratch",
        help="run a command against a throwaway service instance, "
             "never the live stack",
    )
    parser.add_argument("service", choices=sorted(SERVICES))
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="command to run against the scratch instance, e.g. "
             "-- kb query 'foo'",
    )
    parser.set_defaults(func=cmd_scratch)


def _command_args(raw: list[str], service: str) -> list[str]:
    """Strip a leading `--` and require a non-empty command."""
    command = raw[1:] if raw[:1] == ["--"] else list(raw)
    if not command:
        raise RuntimeError(
            "agent-workbench scratch: no command given, e.g. "
            f"`scratch {service} -- kb status`"
        )
    return command


def _compose_files() -> tuple[Path, Path]:
    """Locate docker-compose.yml + docker-compose.scratch.yml.

    Raises:
        RuntimeError: naming what to do, if this is a copy install or
            either file is missing from the resolved repo root.
    """
    try:
        root = paths.repo_root()
    except RuntimeError as exc:
        raise RuntimeError(
            "agent-workbench scratch: docker-compose.yml not found (this "
            "looks like a copy-installed skill, which has no repo "
            "checkout beside it). Run `scratch` from a checkout of the "
            "agent-workbench repo instead."
        ) from exc
    base = root / "docker-compose.yml"
    override = root / "docker-compose.scratch.yml"
    missing = [p for p in (base, override) if not p.is_file()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise RuntimeError(
            f"agent-workbench scratch: missing {names}. Run `scratch` "
            "from a checkout of the agent-workbench repo."
        )
    return base, override


def _require_podman_compose() -> None:
    if shutil.which("podman-compose") is None:
        raise RuntimeError(
            "agent-workbench scratch: `podman-compose` not found on PATH."
        )


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status
    except (urllib.error.URLError, OSError):
        return None


def _wait_healthy(port: int, spec: ServiceSpec) -> None:
    url = f"http://127.0.0.1:{port}{spec.health_path}"
    for _ in range(HEALTH_POLL_TRIES):
        if _http_status(url) == 200:
            return
        time.sleep(HEALTH_POLL_DELAY_SEC)
    raise RuntimeError(
        f"agent-workbench scratch: {spec.compose_name} never answered "
        f"{url} after {HEALTH_POLL_TRIES * HEALTH_POLL_DELAY_SEC:.0f}s"
    )


def _host_port(base: Path, override: Path, project: str, spec: ServiceSpec) -> int:
    result = subprocess.run(
        [
            "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
            "port", spec.compose_name, str(spec.internal_port),
        ],
        capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip().rsplit(":", 1)[-1])


def _bring_up(
    base: Path, override: Path, project: str, spec: ServiceSpec,
) -> int:
    """`up -d` the service, wait for health, return its host port."""
    # stdout=sys.stderr: podman-compose writes container IDs / project
    # lines to stdout. The wrapped command's stdout must be the ONLY
    # thing on scratch's own stdout (agents pipe it to `jq`), so
    # podman-compose's own chatter goes to stderr instead.
    subprocess.run(
        [
            "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
            "up", "-d", spec.compose_name,
        ],
        stdout=sys.stderr, check=True,
    )
    port = _host_port(base, override, project, spec)
    print(
        f"agent-workbench scratch: {spec.compose_name} up at "
        f"127.0.0.1:{port}",
        file=sys.stderr,
    )
    _wait_healthy(port, spec)
    return port


def _scratch_env(spec: ServiceSpec, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env[spec.host_env] = "127.0.0.1"
    env[spec.port_env] = str(port)
    env.pop("ARTIFACT_SVC_URL", None)  # would otherwise outrank host/port
    return env


def cmd_scratch(args: argparse.Namespace) -> int:
    """Bring up a throwaway service instance, run the command, tear down.

    Returns the wrapped command's exit code. Raises RuntimeError (turned
    into a non-zero exit by cli.main) if the compose files are missing,
    podman-compose is unavailable, or the instance never becomes healthy
    -- never falls back to the live stack.
    """
    spec = SERVICES[args.service]
    command = _command_args(args.command, args.service)
    _require_podman_compose()
    base, template = _compose_files()

    scratch_dir = Path(tempfile.mkdtemp(prefix="aw-scratch-"))
    for sub in spec.data_subdirs:
        (scratch_dir / sub).mkdir(parents=True, exist_ok=True)
    override = scratch_dir / "compose.override.yml"
    override.write_text(
        template.read_text().replace(SCRATCH_PLACEHOLDER, str(scratch_dir))
    )
    project = f"aw-scratch-{uuid.uuid4().hex[:10]}"
    down_cmd = [
        "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
        "down", "-v", "-t", str(DOWN_TIMEOUT_SEC), spec.compose_name,
    ]
    try:
        port = _bring_up(base, override, project, spec)
        env = _scratch_env(spec, port)
        result = subprocess.run(command, env=env, check=False)
        return result.returncode
    finally:
        # Same stdout=sys.stderr reasoning as `up` in _bring_up above.
        subprocess.run(down_cmd, stdout=sys.stderr, check=False)
        shutil.rmtree(scratch_dir, ignore_errors=True)
