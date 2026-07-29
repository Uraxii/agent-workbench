#!/usr/bin/env python3
"""scratch -- repo dev/test harness: run a command against a throwaway
service instance instead of the live stack.

    scripts/scratch.py <kb|bd|artifact> [--no-build] -- <command...>

e.g. ``scripts/scratch.py kb -- "$AW" kb status``

Builds the scratch image from the working tree by default on every run
(pass ``--no-build`` to skip it) -- see ``_bring_up`` for why this can't
default off.

This is repo tooling, not a CLI verb -- it is NOT part of the shipped
agent-workbench skill (see ../.claude/skills/agent-workbench/cli/), which
is a pure HTTP client with no container-runtime access. Only useful from a
repo checkout: it shells out to `podman-compose` and reuses this repo's
own docker-compose.yml + docker-compose.scratch.yml.

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

__all__ = ["main"]

REPO_ROOT = Path(__file__).resolve().parents[1]
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
    image_repo: str  # local image repo name, e.g. "kb-svc"


SERVICES: dict[str, ServiceSpec] = {
    "kb": ServiceSpec(
        "kb-svc", 9100, "/health", "KB_SVC_HOST", "KB_SVC_PORT", ("",),
        "kb-svc",
    ),
    "bd": ServiceSpec(
        "bd-svc", 9101, "/health", "BD_SVC_HOST", "BD_SVC_PORT", ("",),
        "bd-svc",
    ),
    "artifact": ServiceSpec(
        "artifact-svc", 9099, "/_/health",
        "ARTIFACT_SVC_HOST", "ARTIFACT_SVC_PORT", ("stage", "feedback"),
        "artifact-review",
    ),
}


def _scratch_image(spec: ServiceSpec) -> str:
    """The scratch overlay's own tag for this service -- never :latest."""
    return f"localhost/{spec.image_repo}:scratch"


def build_parser() -> argparse.ArgumentParser:
    """Build the `scratch.py` parser: SERVICE followed by `-- COMMAND...`."""
    # `_split_argv` consumes the wrapped command before argparse ever sees
    # it, so there is no `command` positional for argparse to document.
    # Spell the `-- COMMAND...` half in `usage` by hand, or `--help` would
    # advertise an invocation that always errors.
    parser = argparse.ArgumentParser(
        prog="scratch.py",
        usage="scratch.py [-h] [--no-build] {artifact,bd,kb} -- COMMAND...",
        description="run a command against a throwaway service instance, "
                     "never the live stack",
        epilog="COMMAND is everything after the literal `--`, e.g. "
               "`scratch.py kb -- kb query 'foo'`. Chain multi-step probes "
               "inside one command: `-- bash -c 'first && second'`.",
    )
    parser.add_argument("service", choices=sorted(SERVICES))
    parser.add_argument(
        "--no-build", dest="build", action="store_false", default=True,
        help="skip the default rebuild of the scratch image from the "
             "working tree before `up` (opt out only when you already "
             "know the :scratch tag is current -- podman-compose's own "
             "`up` build-if-missing only triggers when the tag is "
             "entirely absent, so without a rebuild a stale :scratch tag "
             "from an earlier branch is reused forever)",
    )
    return parser


def _split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv on the first literal `--`: scratch's own flags before it,
    the wrapped command after.

    Done by hand rather than via argparse `nargs=REMAINDER` on a trailing
    `command` argument: REMAINDER swallows any later recognized flag (e.g.
    `--no-build`) into the wrapped command once positional matching begins,
    breaking `scratch.py kb --no-build -- true` (flag after the service).
    """
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1:]
    return argv, []


def _command_args(raw: list[str], service: str) -> list[str]:
    """Require a non-empty command.

    Does NOT strip a leading `--`: `_split_argv` has already consumed the
    separator, so a `--` still present here is the caller's own argument
    (`scratch.py kb -- -- foo`) and eating it would silently drop a token
    the wrapped command was meant to receive.
    """
    command = list(raw)
    if not command:
        raise RuntimeError(
            "scratch: no command given, e.g. "
            f"`scratch.py {service} -- kb status`"
        )
    return command


def _compose_files() -> tuple[Path, Path]:
    """Locate docker-compose.yml + docker-compose.scratch.yml at the repo root.

    Raises:
        RuntimeError: naming what is missing, if either file is absent.
    """
    base = REPO_ROOT / "docker-compose.yml"
    override = REPO_ROOT / "docker-compose.scratch.yml"
    missing = [p for p in (base, override) if not p.is_file()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise RuntimeError(f"scratch: missing {names}.")
    return base, override


def _require_podman_compose() -> None:
    if shutil.which("podman-compose") is None:
        raise RuntimeError("scratch: `podman-compose` not found on PATH.")


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
        f"scratch: {spec.compose_name} never answered "
        f"{url} after {HEALTH_POLL_TRIES * HEALTH_POLL_DELAY_SEC:.0f}s"
    )


def _host_port(base: Path, override: Path, project: str, spec: ServiceSpec) -> int:
    # ponytail: parses the whole captured stdout via rsplit(":", 1) instead
    # of its last non-empty line; podman-compose chatter on `port` would
    # break this. Fails loudly (int() raises), no live-data risk -- switch
    # to last-line parsing if that chatter ever actually appears.
    result = subprocess.run(
        [
            "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
            "port", spec.compose_name, str(spec.internal_port),
        ],
        capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip().rsplit(":", 1)[-1])


def _build(
    base: Path, override: Path, project: str, spec: ServiceSpec,
) -> None:
    """Build the scratch image from the working tree."""
    subprocess.run(
        [
            "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
            "build", spec.compose_name,
        ],
        stdout=sys.stderr, check=True,
    )


def _print_image_identity(
    project: str, spec: ServiceSpec,
) -> tuple[str, str] | None:
    """Print the image the CREATED CONTAINER is running, to stderr -- the
    tripwire that makes a wrong scratch image diagnosable from the
    transcript instead of silently passing. Returns (image_id, created),
    or None if the inspection itself failed, so a caller (the container-
    backed test tier) can assert on the real identity instead of only
    the swallowed stderr line.

    Deliberately inspects the container, not `_scratch_image(spec)`. The
    `:scratch` tag is global to this host while builds are per-worktree,
    so two concurrent scratch runs race for it: last writer wins, `up`
    resolves the tag at container-create time, and inspecting the tag
    afterwards can report an image the container is not running. Reading
    the container's own `.Image` is the only answer that cannot disagree
    with what is actually serving the requests.
    """
    try:
        # `podman-compose ps` takes no service argument (verified: it
        # accepts only -q/-f and exits 2 on one), so ask podman directly
        # via the labels compose stamps on every container it creates.
        ps = subprocess.run(
            [
                "podman", "ps", "-aq",
                "--filter", f"label=io.podman.compose.project={project}",
                "--filter", f"label=io.podman.compose.service={spec.compose_name}",
            ],
            capture_output=True, text=True, check=True,
        )
        container = ps.stdout.split()[-1]
        result = subprocess.run(
            [
                "podman", "container", "inspect", container,
                "--format", "{{.Image}} {{.ImageName}}",
            ],
            capture_output=True, text=True, check=True,
        )
        image_id, image_name = result.stdout.strip().split(" ", 1)
        created = subprocess.run(
            ["podman", "image", "inspect", image_id, "--format", "{{.Created}}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        print(
            f"scratch: {spec.compose_name} image {image_name} id {image_id} "
            f"created {created}",
            file=sys.stderr,
        )
        return image_id, created
    except (subprocess.CalledProcessError, IndexError, ValueError) as exc:
        print(
            f"scratch: warning: could not inspect the running container for "
            f"{spec.compose_name}: {exc}",
            file=sys.stderr,
        )
        return None


def _just_built_image_id(spec: ServiceSpec) -> str:
    """The id of the image `_build` just produced for this service's
    `:scratch` tag, read immediately after `_build` returns -- before `up`
    has run, so no concurrent scratch run has had a chance to repoint the
    tag first (see `_print_image_identity`'s own race note).
    """
    result = subprocess.run(
        [
            "podman", "image", "inspect", _scratch_image(spec),
            "--format", "{{.Id}}",
        ],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _assert_container_runs_the_build(
    identity: tuple[str, str] | None, built_image_id: str, spec: ServiceSpec,
) -> None:
    """Reject a bring-up whose container isn't running the image `_build`
    just produced -- e.g. `up` resolving a different tag/image than the
    one this run just built. Only called when `build` was True; there is
    nothing to compare a `--no-build` run against (see `_bring_up`).

    Compares image IDs, not `.Created` timestamps: verified empirically
    (`podman build` on this repo's own kb-container image, unchanged
    source, run twice) that a same-content rebuild reuses the exact prior
    image id AND `.Created` -- a "`.Created` must be >= now" check would
    misfire on every ordinary cache-hit rebuild, which is the normal case
    whenever the working tree hasn't changed since the last scratch run.
    """
    if identity is None:
        raise RuntimeError(
            f"scratch: could not verify {spec.compose_name} ran the image "
            "just built (see the inspection warning above)"
        )
    running_image_id, _created = identity
    if running_image_id != built_image_id:
        raise RuntimeError(
            f"scratch: {spec.compose_name} is running image "
            f"{running_image_id}, not the {built_image_id} this run just "
            "built -- refusing a stale image"
        )


def _bring_up(
    base: Path, override: Path, project: str, spec: ServiceSpec, build: bool,
) -> int:
    """Build (unless `--no-build`), then `up -d` the service, wait for
    health, return its host port.

    Build defaults ON. podman-compose (1.6.0) only builds automatically
    inside `up` when the tag is entirely absent (its own source:
    ``if_not_exists=(not args.build)``) -- a `:scratch` tag left over from
    an earlier branch is otherwise reused forever, silently verifying a
    stale image. `--no-build` waives this only when the caller already
    knows the tag is current.
    """
    built_image_id = None
    if build:
        _build(base, override, project, spec)
        built_image_id = _just_built_image_id(spec)
    up_cmd = [
        "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
        "up", "-d", spec.compose_name,
    ]
    # stdout=sys.stderr: podman-compose writes container IDs / project
    # lines to stdout. The wrapped command's stdout must be the ONLY
    # thing on scratch's own stdout (agents pipe it to `jq`), so
    # podman-compose's own chatter goes to stderr instead.
    subprocess.run(up_cmd, stdout=sys.stderr, check=True)
    port = _host_port(base, override, project, spec)
    print(
        f"scratch: {spec.compose_name} up at 127.0.0.1:{port}",
        file=sys.stderr,
    )
    identity = _print_image_identity(project, spec)
    if built_image_id is not None:
        _assert_container_runs_the_build(identity, built_image_id, spec)
    _wait_healthy(port, spec)
    return port


def _sentinel_host(spec: ServiceSpec) -> str:
    """RFC-2606 `.invalid` host naming the cause in the DNS error itself."""
    return f"{spec.compose_name}-not-started-by-this-scratch-run.invalid"


def _scratch_env(spec: ServiceSpec, port: int, service: str) -> dict[str, str]:
    """Env for the wrapped command.

    The target service gets the scratch port. The other two get a
    `.invalid` sentinel host so a cross-service call fails immediately
    instead of silently reaching the live stack. Chain multi-step probes
    inside the single wrapped command instead of nesting `scratch` runs
    (see the module docstring) -- a nested run now fails loudly on this
    same `.invalid` DNS error, the correct failure mode for an
    unsupported workflow.
    """
    env = os.environ.copy()
    for name, other in SERVICES.items():
        if name == service:
            continue
        env[other.host_env] = _sentinel_host(other)
    env[spec.host_env] = "127.0.0.1"
    env[spec.port_env] = str(port)
    env.pop("ARTIFACT_SVC_URL", None)  # would otherwise outrank host/port
    return env


def cmd_scratch(args: argparse.Namespace) -> int:
    """Bring up a throwaway service instance, run the command, tear down.

    Returns the wrapped command's exit code. Raises RuntimeError if the
    compose files are missing, podman-compose is unavailable, or the
    instance never becomes healthy -- never falls back to the live stack.
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
    # No trailing service name: `down <service>` only ever removes that
    # one container, leaking the project's own pod + network forever
    # (verified: podman-compose 1.6.0 creates one pod + one bridge
    # network per PROJECT, not per service, and only a project-wide
    # `down` tears either down). The other services declared in the
    # compose files were never started for this project, so podman-
    # compose prints a harmless "no container ... found" per absent
    # service and still exits 0.
    down_cmd = [
        "podman-compose", "-p", project, "-f", str(base), "-f", str(override),
        "down", "-v", "-t", str(DOWN_TIMEOUT_SEC),
    ]
    # ponytail: only SIGINT unwinds this `finally`; SIGTERM/SIGKILL bypass
    # it, leaking the container + tmpdir. Add a signal handler if scratch
    # ever runs somewhere it gets killed rather than Ctrl-C'd.
    try:
        port = _bring_up(base, override, project, spec, args.build)
        env = _scratch_env(spec, port, args.service)
        result = subprocess.run(command, env=env, check=False)
        return result.returncode
    finally:
        # ponytail: check=False swallows a failed `down`, leaking the
        # container with no signal; upgrade to check the returncode and
        # warn on stderr if this ever bites in practice.
        # Same stdout=sys.stderr reasoning as `up` in _bring_up above.
        subprocess.run(down_cmd, stdout=sys.stderr, check=False)
        shutil.rmtree(scratch_dir, ignore_errors=True)


def main(argv: list[str]) -> int:
    """Parse argv and run `scratch`. Never falls back to the live stack."""
    scratch_argv, command_argv = _split_argv(argv)
    args = build_parser().parse_args(scratch_argv)
    args.command = command_argv
    try:
        return cmd_scratch(args)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"scratch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
