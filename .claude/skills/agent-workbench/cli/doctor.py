"""`doctor` subcommand -- check every prerequisite a fresh machine needs
to bring the agent-workbench stack up, printing one line per item with a
concrete fix hint, and exiting non-zero if anything REQUIRED is missing.

Required: a container runtime (docker or podman), a compose implementation
(the ``docker compose`` CLI plugin or the standalone ``docker-compose``
binary, both held to ``MIN_DOCKER_COMPOSE``, or ``podman-compose`` at any
version), ``git``, and a Python new enough to run this CLI.

The docker-flavoured candidates are version-checked because
docker-compose.yml uses the compose-spec 2.24+ long ``env_file`` form
(``required: false``) so a missing optional kb.env never blocks startup;
below that floor, ``up`` fails to parse the whole compose model and dies on
a cryptic schema error instead. There is no defensible podman-compose
floor -- the only version this repo has ever exercised is 1.6.0 -- so
podman-compose is only checked for "runs at all".

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
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli import install, paths

__all__ = ["register", "run_checks", "Check"]

MIN_PYTHON = (3, 9)

# compose-spec 2.24 is the first release that parses docker-compose.yml's
# long `env_file` form (`required: false`); below this, `up` fails to
# parse the whole compose model. Applies only to the docker-flavoured
# compose candidates (see COMPOSE_CANDIDATES) -- there is no defensible
# podman-compose floor.
MIN_DOCKER_COMPOSE = (2, 24)

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


# Each entry is (label, binary to look for on PATH, version command, floor).
# Every candidate has to actually run: `docker compose` is a plugin that may
# be absent from a docker CLI, and podman-compose is a Python entry point
# that can sit on PATH while its package is broken. Presence is not
# workingness -- trusting PATH alone is what made the retired rootless check
# report a working host as broken.
#
# The two docker-flavoured candidates run `version --short`, which both
# Compose v1 (prints `1.29.2`) and v2 (prints e.g. `2.29.7`) support, and are
# held to MIN_DOCKER_COMPOSE. `docker-compose` (the standalone binary name)
# is a real candidate: Docker's own "Compose standalone" install drops a v2
# binary under that exact name with no plugin present, so the name alone
# cannot tell v1 from v2 -- the version check does that now.
#
# podman-compose has no defensible floor -- the only version this repo has
# ever exercised is 1.6.0 -- so it keeps the old "it runs successfully"
# check with no version comparison.
COMPOSE_CANDIDATES = (
    ("docker compose", "docker",
     ["docker", "compose", "version", "--short"], MIN_DOCKER_COMPOSE),
    ("docker-compose", "docker-compose",
     ["docker-compose", "version", "--short"], MIN_DOCKER_COMPOSE),
    ("podman-compose", "podman-compose", ["podman-compose", "version"], None),
)


def _parse_major_minor(text: str) -> tuple[int, int] | None:
    """Parse `major.minor` out of the LAST parseable `major.minor` token
    in `text`, scanning every whitespace-separated token.

    Tolerant of a leading `v`, trailing build metadata (`+build`, `-rc1`),
    and surrounding words (e.g. `Docker Compose version v2.29.7`). Taking
    the last token (not the first) survives contaminated multi-line stdout
    where an earlier line carries an unrelated numeric token. Returns None
    on anything unparseable -- callers must then ACCEPT the candidate:
    under-detecting a working host is worse than the false MISSING this
    floor exists to fix.
    """
    found: tuple[int, int] | None = None
    for token in text.split():
        major, _, rest = token.lstrip("v").partition(".")
        minor = rest.split(".", 1)[0].split("-", 1)[0].split("+", 1)[0]
        if major.isdigit() and minor.isdigit():
            found = (int(major), int(minor))
    return found


def _compose_sibling_note(outdated: list[str], broken: list[str]) -> str:
    """Clause naming any non-working candidates; empty when there are
    none. Shared by the "ok with a broken/outdated sibling" and the
    "nothing works" branches of `check_compose`."""
    parts = []
    if outdated:
        parts.append(f"too old: {', '.join(outdated)}")
    if broken:
        parts.append(f"not runnable: {', '.join(broken)}")
    return f"on PATH but {'; '.join(parts)}" if parts else ""


def _compose_not_working_hint(outdated: list[str], broken: list[str]) -> str:
    """Fix hint for a compose check where something ran but nothing usable
    was found -- named per bucket, since upgrade and repair are different
    fixes."""
    hints = []
    if outdated:
        hints.append(
            "upgrade to docker compose or docker-compose >= "
            f"{MIN_DOCKER_COMPOSE[0]}.{MIN_DOCKER_COMPOSE[1]} "
            "(`docker compose version --short`), or install podman-compose"
        )
    if broken:
        hints.append(
            "the not-runnable one is installed but fails to start -- run it "
            "by hand to see why (a broken podman-compose usually means a "
            "partial pip install; reinstall it), or install another "
            "implementation"
        )
    return "; ".join(hints)


def check_compose() -> Check:
    """Required: a compose implementation that actually runs and, for the
    docker-flavoured candidates, is not older than MIN_DOCKER_COMPOSE.

    Reports three states distinctly, because each needs a different fix:
    absent (install one), on PATH but not runnable (repair/reinstall), and
    on PATH but too old (upgrade).
    """
    working: list[str] = []
    outdated: list[str] = []
    broken: list[str] = []
    for label, binary, version_cmd, floor in COMPOSE_CANDIDATES:
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
        if result.returncode != 0:
            broken.append(label)
            continue
        found = _parse_major_minor(result.stdout.decode("utf-8", "replace")) if floor else None
        if floor and found is not None and found < floor:
            outdated.append(
                f"{label} {found[0]}.{found[1]} (need >= {floor[0]}.{floor[1]})"
            )
        else:
            working.append(label)

    note = _compose_sibling_note(outdated, broken)
    if working:
        detail = f"found: {', '.join(working)}"
        return Check("compose", True, True, f"{detail} ({note})" if note else detail, "")

    if note:
        return Check(
            "compose", True, False, note,
            _compose_not_working_hint(outdated, broken),
        )

    return Check(
        "compose", True, False, "no compose implementation found",
        "install podman-compose (`sudo dnf install podman-compose` or "
        "`pip install --user podman-compose`) or the docker compose CLI "
        f"plugin / docker-compose >= {MIN_DOCKER_COMPOSE[0]}."
        f"{MIN_DOCKER_COMPOSE[1]} (`docker compose version --short`)",
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


def _dotenv_overrides() -> dict[str, str]:
    """Parse the repo-root `.env` file the same KEY=VALUE way compose
    reads it, into a plain dict. Empty when no repo root or no `.env` is
    found -- a copy install has no repo-root `.env` to read, matching how
    compose itself never sees one from that install either.
    """
    try:
        env_path = paths.repo_root() / ".env"
    except RuntimeError:
        return {}
    if not env_path.is_file():
        return {}
    overrides: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        overrides[key.strip()] = value.strip()
    return overrides


def _resolved_root(var: str, default: str, overrides: dict[str, str]) -> Path:
    """The same precedence docker-compose.yml's `${VAR:-default}` gives a
    setting: a real shell-exported env var wins, then the repo's `.env`
    file, then the compose default."""
    raw = os.environ.get(var) or overrides.get(var) or default
    return Path(raw).expanduser()


def check_data_roots() -> Check:
    """Report each service's resolved durable data root, so a stray
    ``/tmp`` default (or override) is visible instead of silently
    inferred. Never required -- this is visibility, not a prerequisite --
    but WARNs if any resolved root sits under ``/tmp``, since ``/tmp``
    clears on reboot and every root here is meant to survive that.

    kb-svc's KB_HOME and bd-svc's BEADS_HUB_DIR are not `.env`-overridable
    today (docker-compose.yml hardcodes them to ``$HOME``-relative
    paths), so those two are always reported at their fixed location.
    """
    overrides = _dotenv_overrides()
    feedback_root = _resolved_root(
        "ARTIFACT_SVC_FEEDBACK_ROOT", str(Path.home() / ".local/share/artifacts"),
        overrides,
    )
    stage_root = _resolved_root(
        "ARTIFACT_SVC_STAGE_ROOT", str(feedback_root / "stage"), overrides,
    )
    roots = {
        "kb-svc KB_HOME": Path.home() / ".knowledgebase",
        "bd-svc BEADS_HUB_DIR": Path.home() / ".beads-hub",
        "artifact-svc FEEDBACK_ROOT": feedback_root,
        "artifact-svc STAGE_ROOT": stage_root,
    }
    under_tmp = [name for name, root in roots.items() if root.is_relative_to("/tmp")]
    detail = "; ".join(f"{name}={root}" for name, root in roots.items())
    if under_tmp:
        return Check(
            "data roots", False, False, detail,
            f"{', '.join(under_tmp)} resolve under /tmp, which clears on "
            "reboot -- durable data must live elsewhere",
        )
    return Check("data roots", False, True, detail, "")


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


def _plausible_repo_root(path: Path) -> bool:
    """True if `path` looks like a real source repo root -- the same "has
    a scripts/ dir" plausibility test `paths._compute_root` uses. Guards
    against a marker source too shallow to have 3 real parents, or one
    that resolves somewhere implausible (e.g. $HOME) landing a false
    match/mismatch against an unrelated git repo."""
    return (path / "scripts").is_dir()


def check_skill_install() -> Check:
    """Optional: report the installed skill's provenance.

    Distinguishes: not installed, a dev symlink (the defect -- tracks
    whatever branch that working tree has checked out), a pinned copy
    matching the source repo's current HEAD, a stale pinned copy, a legacy
    copy with no recorded commit, a pinned copy whose marker source no
    longer exists on disk (moved or deleted after install), and a real
    dir this repo did not install. Never required: this reports, it does
    not gate -- but an unreachable source renders WARN, not OK, because a
    staleness check that silently declines must never look identical to a
    verified match.
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

    # The marker already records the source repo's skill dir -- trust that
    # directly rather than re-deriving a root from this file's own on-disk
    # location, which is wrong on a --copy install (paths._compute_root
    # walks up from cli/doctor.py itself, landing under $HOME with no
    # scripts/ dir). Trusting the recorded source is also strictly better
    # at answering "is the repo I can see the repo this came from" than an
    # independently-resolved root ever was.
    marker_source = marker.get("source")
    if not marker_source:
        return Check(
            name, False, False,
            f"pinned at {short}; marker has no recorded source, staleness "
            "could not be checked",
            "",
        )

    source_path = Path(str(marker_source))
    if not source_path.is_dir():
        return Check(
            name, False, False,
            f"pinned at {short}, installed from {marker_source} which no "
            "longer exists; staleness could not be checked",
            "",
        )

    # source_path is <repo>/.claude/skills/agent-workbench, so its
    # grandparent's parent is the repo root -- but two degenerate cases
    # must not fall through to a HEAD comparison: the source resolving to
    # the install target itself (a stray $HOME that happens to look like
    # a repo), and a source too shallow to even have 3 parents (would
    # IndexError). Either way, treat it the same as "not a usable repo
    # root" and just like paths._compute_root(), require a scripts/ dir
    # as the plausibility test before trusting it -- a false STALE against
    # an unrelated repo (e.g. a dotfiles repo living at $HOME) would be
    # exactly the false report this check exists to stop.
    resolved_source = source_path.resolve()
    parents = resolved_source.parents
    repo_root = parents[2] if len(parents) >= 3 else None
    if (
        resolved_source == target.resolve()
        or repo_root is None
        or not _plausible_repo_root(repo_root)
    ):
        return Check(
            name, False, False,
            f"pinned at {short}, installed from {marker_source}; that is "
            "not a usable repo root, staleness could not be checked",
            "",
        )

    head = paths.git_head(repo_root)
    if head is None:
        return Check(
            name, False, False,
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
        check_data_roots(),
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
