"""`doctor` subcommand -- check every prerequisite a fresh machine needs
to bring the agent-workbench stack up, printing one line per item with a
concrete fix hint, and exiting non-zero if anything REQUIRED is missing.

Required: a container runtime (docker or podman), a compose implementation
(``docker compose`` CLI plugin >= 2.24, or ``podman-compose`` >= 1.1),
``git``, and a Python new enough to run this CLI.

``docker-compose`` v1 is NOT a supported implementation: docker-compose.yml
uses the compose-spec 2.24+ long ``env_file`` form (``required: false``) so a
missing optional kb.env never blocks startup, and v1 validates against the
older v3 schema where that form fails the whole compose model. A
``docker-compose`` binary that is actually a v2 shim is fine; only the real
v1 (final 1.29.2, EOL) is excluded.

Optional, reported but never failing the exit code: ``tailscale`` and
``~/.knowledgebase/kb.env`` (only needed to turn on LLM enrichment; the
stack comes up and answers health checks with it absent).

There is deliberately NO rootless-runtime check. The containers are the only
writers to the mounted data dirs, so whichever uid they run as is internally
consistent; the surviving concern (a human must still be able to read the
markdown vault) is a README caveat, not an install gate.

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

from cli import install, paths

__all__ = ["register", "run_checks", "Check"]

MIN_PYTHON = (3, 9)

KB_ENV_PATH = Path.home() / ".knowledgebase" / "kb.env"
KB_ENV_EXAMPLE = "scripts/kb-container/kb.env.example"  # repo-root-relative


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
#
# `docker-compose` (v1) is deliberately NOT a candidate: `version` exits 0
# on v1 too, so it would greenlight a binary that then fails to parse
# docker-compose.yml's compose-spec 2.24+ long `env_file` form and kills the
# whole compose model on `up`. There is no version-parsing here to tell a v1
# binary from a v2 shim reached via the same name -- the false green is
# worse than under-detecting, so the candidate is dropped, not inspected.
COMPOSE_CANDIDATES = (
    ("docker compose", "docker", ["docker", "compose", "version"]),
    ("podman-compose", "podman-compose", ["podman-compose", "version"]),
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
        "install podman-compose >= 1.1 (`sudo dnf install podman-compose` or "
        "`pip install --user podman-compose`) or the docker compose CLI "
        "plugin >= 2.24 (`docker compose version`). docker-compose v1 does "
        "NOT count: docker-compose.yml uses the compose-spec 2.24+ long "
        "env_file form so a missing optional kb.env never blocks startup, "
        "and v1 fails the whole compose model on that syntax. A "
        "`docker-compose` binary that is actually a v2 shim is fine -- "
        "only the real v1 is excluded",
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


def _kb_env_example_hint() -> str:
    """The kb.env.example source path, absolute when the repo root is
    reachable from here, else the repo-root-relative form it is defined
    at (with a note that it is relative)."""
    try:
        root = paths.repo_root()
    except RuntimeError:
        return f"{KB_ENV_EXAMPLE} (relative to the repo root)"
    return str(root / KB_ENV_EXAMPLE)


def check_kb_env() -> Check:
    """Optional: ``~/.knowledgebase/kb.env`` exists.

    docker-compose.yml declares it as kb-svc's ``env_file`` with
    ``required: false``, so the stack comes up and kb-svc answers health
    checks with this file absent. It is only needed to turn on LLM
    enrichment (an API key) or override defaults; the stack runs fully
    offline without it.
    """
    if KB_ENV_PATH.is_file():
        return Check("kb.env", False, True, f"found at {KB_ENV_PATH}", "")
    return Check(
        "kb.env", False, False, f"not found at {KB_ENV_PATH} (optional)",
        f"only needed for LLM enrichment; to enable it: "
        f"mkdir -p {KB_ENV_PATH.parent} && "
        f"cp {_kb_env_example_hint()} {KB_ENV_PATH}",
    )


def check_tailscale() -> Check:
    """Optional: `tailscale` on PATH (mesh-networked access path)."""
    return _binary_check(
        "tailscale", False,
        "install tailscale from https://tailscale.com/download if you want "
        "the mesh-networked access path; not required for local-only use",
    )


def _copy_reinstall_hint() -> str:
    """The exact --copy reinstall command, rooted at this repo when it is
    reachable from here."""
    try:
        root = paths.repo_root()
    except RuntimeError:
        root = None
    skill_dir = (
        f"{root}/.claude/skills/agent-workbench" if root is not None
        else "<agent-workbench repo>/.claude/skills/agent-workbench"
    )
    return f"{skill_dir}/agent-workbench install --copy"


def check_skill_install() -> Check:
    """Optional: report the installed skill's provenance.

    Distinguishes: not installed, a dev symlink (the defect -- tracks
    whatever branch that working tree has checked out), a pinned copy
    matching the source repo's current HEAD, a stale pinned copy, a legacy
    copy with no recorded commit, a copy whose source repo cannot be
    reached from here (the normal state for a production install), and a
    real dir this repo did not install. Never required: this reports, it
    does not gate.
    """
    name = "skill install"
    target = install.install_target()

    if target.is_symlink():
        resolved = target.resolve()
        if not target.exists():
            return Check(
                name, False, False,
                f"broken symlink -> {resolved} (target does not exist)",
                _copy_reinstall_hint(),
            )
        return Check(
            name, False, False,
            f"dev symlink -> {resolved} (tracks whatever branch that "
            "working tree currently has checked out)",
            f"{resolved}/agent-workbench install --copy",
        )
    if not target.exists():
        return Check(
            name, False, False, f"not installed at {target}",
            _copy_reinstall_hint(),
        )

    marker = install.read_marker(target)
    if marker is None:
        return Check(
            name, False, False,
            f"real dir at {target}, no install marker -- not installed by "
            "this repo's installer",
            f"move or rename {target} yourself (this repo did not install "
            f"it), then run: {_copy_reinstall_hint()}",
        )

    commit = marker.get("commit")
    if not commit:
        return Check(
            name, False, False,
            "installed copy has no recorded commit (legacy install, "
            "unknown provenance)",
            _copy_reinstall_hint(),
        )

    short = str(commit)[:12]
    try:
        repo_root = paths.repo_root()
    except RuntimeError:
        return Check(
            name, False, True,
            f"pinned at {short} (source repo unreachable from here; "
            "staleness could not be checked)",
            "",
        )

    # A repo root resolves here (e.g. this machine has an unrelated
    # ~/scripts dir) but it may not be the repo this copy came FROM --
    # including the degenerate case where it resolves to `target` itself.
    # Only compare HEAD when the marker's recorded source still matches.
    marker_source = marker.get("source")
    resolved_source = install.source_dir().resolve()
    if marker_source is None or Path(str(marker_source)).resolve() != resolved_source:
        return Check(
            name, False, True,
            f"pinned at {short}, installed from {marker_source or 'unknown source'}; "
            "that source is not reachable from here, staleness not checked",
            "",
        )

    head = paths.git_head(repo_root)
    if head is None:
        return Check(
            name, False, True,
            f"pinned at {short}, repo HEAD could not be read (staleness "
            "not checked)",
            "",
        )
    if head == commit:
        return Check(name, False, True, f"pinned at {short}, matches repo HEAD", "")
    return Check(
        name, False, False,
        f"stale -- installed at {short}, repo HEAD is now {head[:12]}",
        _copy_reinstall_hint(),
    )


def run_checks() -> list[Check]:
    """Run every prerequisite check and return the full report."""
    return [
        check_container_runtime(),
        check_compose(),
        check_git(),
        check_python(),
        check_kb_env(),
        check_tailscale(),
        check_skill_install(),
    ]


def all_required_ok(checks: list[Check]) -> bool:
    """True iff every required check in `checks` passed."""
    return all(check.ok for check in checks if check.required)


def render_human(checks: list[Check]) -> str:
    """Render `checks` as one human-readable line per check."""
    lines = []
    for check in checks:
        glyph = "OK" if check.ok else ("MISSING" if check.required else "WARN")
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
