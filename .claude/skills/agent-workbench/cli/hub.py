"""`hub` subcommand -- pure-Python port of scripts/beads-hub.sh.

Global bd (beads) board hub: all project boards live centrally under one
hub root (``$BEADS_HUB_DIR`` or ~/.beads-hub), aggregated into one
cross-project view via bd's multi-repo support. Subcommands:
    init                init the aggregator board (idempotent)
    add NAME [PREFIX]    create+register $HUB_ROOT/NAME/.beads
    sync                hydrate the aggregator from all repos
    list                list registered repos
    path NAME           print $HUB_ROOT/NAME/.beads
    status              JSON: hub_root, initialized?, repos

Invokes the ``bd`` CLI via subprocess (stdlib subprocess, argument-list
form, never a shell string). Reads ``bd repo list`` text output line by
line ("  - <path>" prefix) since bd 1.1.0 ignores --json for that verb.

Folded audit fixes:
  * M4: ``bd init`` must not be redirectable by an ambient ``BEADS_DIR``
    env var. ``init_board`` runs bd with an env that has BEADS_DIR removed
    so the board can only ever be written where the hub layout dictates.
  * LOW (naming + TOCTOU): the old shell used ``git_preexisted`` set to 1
    to mean "did NOT preexist" -- inverted and confusing. The port uses a
    correctly-sensed boolean ``git_repo_preexisted`` (True only if a
    ``.git`` dir existed BEFORE bd init ran); the incidental-repo cleanup
    keys off ``not git_repo_preexisted``. add() also resolves the
    "already registered" check against a freshly read repo list to avoid
    the check-then-add race.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

__all__ = ["register", "hub_root", "board_exists", "init_board"]

BD_BIN = "bd"
AGGREGATOR_NAME = "hub"
AGGREGATOR_PREFIX = "hub"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `hub` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("hub", help="bd (beads) board hub ops")
    sub = parser.add_subparsers(dest="hub_command", required=True)

    init_cmd = sub.add_parser("init", help="init the aggregator board (idempotent)")
    init_cmd.set_defaults(func=cmd_init)

    add_cmd = sub.add_parser("add", help="create+register $HUB_ROOT/NAME/.beads")
    add_cmd.add_argument("name")
    add_cmd.add_argument("prefix", nargs="?", default=None)
    add_cmd.set_defaults(func=cmd_add)

    sync_cmd = sub.add_parser("sync", help="hydrate the aggregator from all repos")
    sync_cmd.set_defaults(func=cmd_sync)

    list_cmd = sub.add_parser("list", help="list registered repos")
    list_cmd.set_defaults(func=cmd_list)

    path_cmd = sub.add_parser("path", help="print $HUB_ROOT/NAME/.beads")
    path_cmd.add_argument("name")
    path_cmd.set_defaults(func=cmd_path)

    status_cmd = sub.add_parser("status", help="JSON: hub_root, initialized?, repos")
    status_cmd.set_defaults(func=cmd_status)


def hub_root() -> Path:
    """Resolve the hub root: ``$BEADS_HUB_DIR`` else ~/.beads-hub.

    Note: default is NOT under any ``.beads``-named dir -- bd 1.1.0 refuses
    to init a board whose path has a ``.beads`` ancestor.
    """
    env = os.environ.get("BEADS_HUB_DIR")
    return Path(env) if env else Path.home() / ".beads-hub"


def board_exists(beads_dir: Path) -> bool:
    """True iff a board's Dolt db exists at ``beads_dir``.

    A dir can pre-date its board, so existence is keyed on
    ``beads_dir/embeddeddolt`` OR any ``beads_dir/*.db``, not on the dir
    itself.
    """
    if (beads_dir / "embeddeddolt").is_dir():
        return True
    return any(beads_dir.glob("*.db"))


def _bd_env_without_beads_dir() -> dict[str, str]:
    """Return a copy of ``os.environ`` with ``BEADS_DIR`` removed.

    M4 fix: prevents an ambient BEADS_DIR from redirecting where a
    ``bd init`` (run with cwd inside the target dir) writes its board.
    """
    env = dict(os.environ)
    env.pop("BEADS_DIR", None)
    return env


def init_board(directory: Path, prefix: str) -> None:
    """Run ``bd init`` for a board at ``directory/.beads`` then undo the
    incidental bare git repo bd's --stealth creates when ``directory`` was
    not already a git repo.

    M4 fix: the ``bd init`` subprocess runs with cwd=directory and an env
    from ``_bd_env_without_beads_dir`` so ambient BEADS_DIR cannot
    redirect it.

    LOW fix (naming): captures ``git_repo_preexisted =
    (directory/".git").is_dir()`` BEFORE init; removes the ``.git`` dir
    afterward only when ``not git_repo_preexisted``.

    bd flags used: ``--non-interactive --skip-agents --skip-hooks
    --stealth --prefix <prefix>``.
    """
    directory.mkdir(parents=True, exist_ok=True)
    git_repo_preexisted = (directory / ".git").is_dir()

    subprocess.run(
        [BD_BIN, "init", "--non-interactive", "--skip-agents", "--skip-hooks",
         "--stealth", "--prefix", prefix],
        cwd=directory, env=_bd_env_without_beads_dir(), check=True,
    )

    if not git_repo_preexisted and (directory / ".git").is_dir():
        shutil.rmtree(directory / ".git")
        print(f"beads-hub: removed incidental git repo bd init created at {directory}")


def registered_repos() -> list[str]:
    """Return registered repo paths, one per parsed ``bd repo list`` line.

    Runs ``bd repo list`` with ``BEADS_DIR`` pointed at the aggregator,
    parsing the stable ``  - <path>`` prefix (bd ignores --json here).
    """
    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    env = {**os.environ, "BEADS_DIR": str(aggregator_beads)}
    result = subprocess.run(
        [BD_BIN, "repo", "list"], env=env, capture_output=True, text=True, check=False,
    )
    return [line[len("  - "):] for line in result.stdout.splitlines() if line.startswith("  - ")]


def cmd_init(args: argparse.Namespace) -> int:
    """Init the aggregator board (idempotent)."""
    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    if board_exists(aggregator_beads):
        print(f"beads-hub: aggregator already initialized at {aggregator_beads}")
        return 0
    init_board(hub_root() / AGGREGATOR_NAME, AGGREGATOR_PREFIX)
    print(f"beads-hub: aggregator initialized at {aggregator_beads}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Create + register ``$HUB_ROOT/<name>/.beads`` (idempotent).

    LOW fix: re-reads ``registered_repos`` immediately before the
    ``bd repo add`` to close the check-then-add TOCTOU window.
    """
    name = args.name
    prefix = args.prefix or name
    project_dir = hub_root() / name
    project_beads = project_dir / ".beads"

    if not board_exists(hub_root() / AGGREGATOR_NAME / ".beads"):
        cmd_init(args)

    if board_exists(project_beads):
        print(f"beads-hub: {name} already has a board at {project_beads}")
    else:
        init_board(project_dir, prefix)
        print(f"beads-hub: created board for {name} at {project_beads}")

    if str(project_dir) in registered_repos():
        print(f"beads-hub: {name} already registered in aggregator")
        return 0

    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    env = {**os.environ, "BEADS_DIR": str(aggregator_beads)}
    subprocess.run([BD_BIN, "repo", "add", str(project_dir)], env=env, check=True)
    print(f"beads-hub: registered {name} in aggregator")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Hydrate the aggregator from all registered repos (``bd repo sync``)."""
    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    env = {**os.environ, "BEADS_DIR": str(aggregator_beads)}
    subprocess.run([BD_BIN, "repo", "sync"], env=env, check=True)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Print the aggregator's registered repos (``bd repo list``)."""
    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    env = {**os.environ, "BEADS_DIR": str(aggregator_beads)}
    result = subprocess.run([BD_BIN, "repo", "list"], env=env, check=True)
    return result.returncode


def cmd_path(args: argparse.Namespace) -> int:
    """Print ``$HUB_ROOT/<name>/.beads``; error if that board is absent."""
    project_beads = hub_root() / args.name / ".beads"
    if not board_exists(project_beads):
        raise ValueError(f"beads-hub: no board for {args.name} at {project_beads}")
    print(project_beads)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print JSON: ``{hub_root, initialized, repos[]}``."""
    aggregator_beads = hub_root() / AGGREGATOR_NAME / ".beads"
    initialized = board_exists(aggregator_beads)
    repos = registered_repos() if initialized else []
    print(json.dumps({"hub_root": str(hub_root()), "initialized": initialized, "repos": repos}))
    return 0
