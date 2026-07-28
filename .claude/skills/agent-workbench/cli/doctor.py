"""`doctor` subcommand -- check every prerequisite a fresh machine needs
to bring the agent-workbench stack up, printing one line per item with a
concrete fix hint, and exiting non-zero if anything REQUIRED is missing.

Required: a container runtime (docker or podman), a compose implementation
(``docker compose`` CLI plugin, ``podman-compose``, or ``docker-compose``),
``git``, a Python new enough to run this CLI, ``bd`` (the board CLI the hub
verbs shell out to), and ``~/.knowledgebase/kb.env`` (compose declares it as
an ``env_file``, so ``up`` fails outright when it is absent).

Optional, reported but never failing the exit code: ``tailscale``.

There is deliberately NO rootless-runtime check. The containers are the only
writers to the mounted data dirs, so whichever uid they run as is internally
consistent; the surviving concern (a human must still be able to read the
markdown vault) is a README caveat, not an install gate. See
~/.knowledgebase/agent-workbench/decisions/agent-workbench-mount-ownership__2026-07-27.md

``--json`` emits a machine-readable report instead of the human lines,
per this project's machine-facing-output-defaults-to-JSON convention.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["register", "run_checks", "Check"]

MIN_PYTHON = (3, 9)

KB_ENV_PATH = Path.home() / ".knowledgebase" / "kb.env"
KB_ENV_EXAMPLE = "scripts/kb-container/kb.env.example"


@dataclass(frozen=True)
class Check:
    """Result of one prerequisite check."""

    name: str
    required: bool
    ok: bool
    detail: str
    fix_hint: str  # empty when ok


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `doctor` parser with its `--json` flag."""
    parser = subparsers.add_parser(
        "doctor", help="check prerequisites for using this repo",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable JSON report",
    )
    parser.set_defaults(func=cmd_doctor)


def _binary_check(name: str, required: bool, fix_hint: str) -> Check:
    """A plain "is `name` on PATH" check."""
    found = shutil.which(name)
    if found:
        return Check(name, required, True, f"found at {found}", "")
    return Check(name, required, False, "not found on PATH", fix_hint)


def check_container_runtime() -> Check:
    """Required: `docker` or `podman` on PATH (either satisfies it)."""
    found = [name for name in ("docker", "podman") if shutil.which(name)]
    if found:
        return Check("container runtime", True, True, f"found: {', '.join(found)}", "")
    return Check(
        "container runtime", True, False, "neither docker nor podman found on PATH",
        "install podman (`sudo dnf install podman` / `sudo apt install podman`) "
        "or docker (https://docs.docker.com/engine/install/)",
    )


# Each entry is (label, binary to look for on PATH, command proving it runs).
# Every candidate has to actually run: `docker compose` is a plugin that may
# be absent from a docker CLI, and podman-compose is a Python entry point that
# can sit on PATH while its package is broken. Presence is not workingness --
# trusting PATH alone is what made the retired rootless check report a
# working host as broken.
COMPOSE_CANDIDATES = (
    ("docker compose", "docker", ["docker", "compose", "version"]),
    ("podman-compose", "podman-compose", ["podman-compose", "version"]),
    ("docker-compose", "docker-compose", ["docker-compose", "version"]),
)


def check_compose() -> Check:
    """Required: a compose implementation that actually runs.

    Reports a binary that is on PATH but fails to run separately from one
    that is simply absent, because the two need different fixes.
    """
    working: list[str] = []
    broken: list[str] = []
    for label, binary, version_cmd in COMPOSE_CANDIDATES:
        if not shutil.which(binary):
            continue
        try:
            result = subprocess.run(version_cmd, capture_output=True, check=False)
        except OSError:
            # The binary was on PATH a moment ago but could not be executed:
            # a dangling symlink, a bad interpreter line, a lost mount. That
            # is "present but not runnable", never a doctor crash -- doctor
            # exists to report a broken machine, not to fall over on one.
            broken.append(label)
            continue
        (working if result.returncode == 0 else broken).append(label)

    if working:
        detail = f"found: {', '.join(working)}"
        if broken:
            detail += f" (on PATH but not runnable: {', '.join(broken)})"
        return Check("compose", True, True, detail, "")

    if broken:
        return Check(
            "compose", True, False,
            f"on PATH but not runnable: {', '.join(broken)}",
            "the compose binary is installed but fails to start -- run it by "
            "hand to see why (a broken podman-compose usually means a partial "
            "pip install; reinstall it), or install another implementation",
        )

    return Check(
        "compose", True, False, "no compose implementation found",
        "install podman-compose (`sudo dnf install podman-compose` or "
        "`pip install --user podman-compose`) or the docker compose CLI plugin",
    )


def check_git() -> Check:
    """Required: `git` on PATH."""
    return _binary_check(
        "git", True,
        "install git via your package manager, e.g. `sudo apt install git` "
        "or `sudo dnf install git`",
    )


def check_python() -> Check:
    """Required: the interpreter running this CLI is >= MIN_PYTHON.

    The host CLI is stdlib-only by design, so the interpreter version is the
    whole of its dependency list.
    """
    floor = ".".join(str(part) for part in MIN_PYTHON)
    running = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] >= MIN_PYTHON:
        return Check("python3", True, True, f"{running} at {sys.executable}", "")
    return Check(
        "python3", True, False, f"{running} at {sys.executable} (need >= {floor})",
        f"install python {floor} or newer and run the CLI with it; the host "
        "CLI is stdlib-only, so no venv or pip install is needed",
    )


def check_bd() -> Check:
    """Required: `bd` (the beads board CLI) on PATH.

    The hub and init-workspace verbs shell out to it directly (cli/hub.py).
    """
    return _binary_check(
        "bd", True,
        "install bd (the beads board CLI) from "
        "https://github.com/steveyegge/beads",
    )


def check_kb_env() -> Check:
    """Required: ``~/.knowledgebase/kb.env`` exists.

    docker-compose.yml declares it as kb-serve's ``env_file``, and compose
    refuses to start the stack when a declared env_file is missing.
    """
    if KB_ENV_PATH.is_file():
        return Check("kb.env", True, True, f"found at {KB_ENV_PATH}", "")
    return Check(
        "kb.env", True, False, f"not found at {KB_ENV_PATH}",
        f"mkdir -p {KB_ENV_PATH.parent} && cp {KB_ENV_EXAMPLE} {KB_ENV_PATH} "
        "(from the repo root); compose declares it as an env_file, so `up` "
        "fails without it",
    )


def check_tailscale() -> Check:
    """Optional: `tailscale` on PATH (mesh-networked access path)."""
    return _binary_check(
        "tailscale", False,
        "install tailscale from https://tailscale.com/download if you want "
        "the mesh-networked access path; not required for local-only use",
    )


def run_checks() -> list[Check]:
    """Run every prerequisite check and return the full report."""
    return [
        check_container_runtime(),
        check_compose(),
        check_git(),
        check_python(),
        check_bd(),
        check_kb_env(),
        check_tailscale(),
    ]


def all_required_ok(checks: list[Check]) -> bool:
    """True iff every required check in `checks` passed."""
    return all(check.ok for check in checks if check.required)


def render_human(checks: list[Check]) -> str:
    """Render `checks` as one human-readable line per check."""
    lines = []
    for check in checks:
        glyph = "OK" if check.ok else ("MISSING" if check.required else "SKIP")
        line = f"[{glyph}] {check.name}: {check.detail}"
        if check.fix_hint:
            line += f" -- {check.fix_hint}"
        lines.append(line)
    return "\n".join(lines)


def render_json(checks: list[Check]) -> str:
    """Render `checks` as one JSON object: {ok, checks: [...]}."""
    return json.dumps({
        "ok": all_required_ok(checks),
        "checks": [
            {
                "name": check.name,
                "required": check.required,
                "ok": check.ok,
                "detail": check.detail,
                "fix_hint": check.fix_hint,
            }
            for check in checks
        ],
    })


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run every check, print the report, and exit non-zero if a
    required check failed."""
    checks = run_checks()
    print(render_json(checks) if args.json else render_human(checks))
    return 0 if all_required_ok(checks) else 1
