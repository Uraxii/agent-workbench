"""`board` subcommand -- pure-Python port of scripts/board-ui.sh.

Per-project lifecycle helper for bdui (bd's web front end). Each repo gets
its own isolated bdui daemon by pointing ``BDUI_RUNTIME_DIR`` at a
per-repo runtime dir, so up/down/status never collide across projects.
Subcommands:
    up [REPO_DIR]      start (or reuse) the board UI for REPO_DIR; prints URL
    down [REPO_DIR]    stop the board UI for REPO_DIR
    status              list running board UIs

REPO_DIR defaults to the current directory. bdui itself is a node binary
invoked via subprocess (argument-list form).

Folded audit fix:
  * M1: the old ``resolve_repo`` (board-ui.sh:54) required a
    ``<repo>/.beads`` dir, which is stale under the beads-hub layout where
    boards live at ``$HUB_ROOT/<name>/.beads``, never in the repo. The
    port validates against the hub board for that repo's name (via the
    ``hub`` module's ``hub_root`` / ``board_exists``) instead of a
    repo-local ``.beads``.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from cli import hub, paths

__all__ = ["register", "resolve_repo", "repo_runtime_dir", "find_free_port"]

PORT_START = 3000
PORT_TRIES = 100
# node/npm only exist via linuxbrew on this dev host, not on default PATH.
# Prepended to PATH (cmd_up) only when the dir actually exists, so this
# stays a no-op on hosts without a linuxbrew install.
LINUXBREW_BIN = "/home/linuxbrew/.linuxbrew/bin"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `board` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser("board", help="bdui web front end lifecycle")
    sub = parser.add_subparsers(dest="board_command", required=True)

    up_cmd = sub.add_parser("up", help="start (or reuse) the board UI; prints URL")
    up_cmd.add_argument("repo_dir", nargs="?", default=".")
    up_cmd.set_defaults(func=cmd_up)

    down_cmd = sub.add_parser("down", help="stop the board UI for REPO_DIR")
    down_cmd.add_argument("repo_dir", nargs="?", default=".")
    down_cmd.set_defaults(func=cmd_down)

    status_cmd = sub.add_parser("status", help="list running board UIs")
    status_cmd.set_defaults(func=cmd_status)


def bdui_bin() -> Path:
    """Path to the bdui executable under scripts/bdui-container node_modules.

    Precondition: the returned path is executable (callers raise a clear
    error otherwise).
    """
    bin_path = paths.REPO_ROOT / "scripts" / "bdui-container" / "node_modules" / ".bin" / "bdui"
    if not os.access(bin_path, os.X_OK):
        raise RuntimeError(f"board-ui: bdui not found at {bin_path}")
    return bin_path


def runtime_root() -> Path:
    """``$XDG_RUNTIME_DIR/board-ui`` (else ``/tmp/board-ui``)."""
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    return Path(xdg) / "board-ui" if xdg else Path("/tmp/board-ui")


def repo_runtime_dir(repo_dir: Path) -> Path:
    """Per-repo runtime dir: ``<runtime_root>/<basename>-<sha1[:8]>``.

    Also handed to bdui as BDUI_RUNTIME_DIR so its server.pid / daemon.log
    land scoped to this one repo.
    """
    digest = hashlib.sha1(str(repo_dir).encode("utf-8")).hexdigest()[:8]
    return runtime_root() / f"{repo_dir.name}-{digest}"


def resolve_repo(raw: str) -> Path:
    """Resolve REPO_DIR to an absolute path and confirm it has a hub board.

    M1 fix: validity is "a bd board exists for this repo's name under the
    hub root" (hub.board_exists(hub.hub_root() / <name> / ".beads")), NOT
    the stale ``<repo>/.beads`` check the shell used.

    Raises:
        SystemExit / ValueError: if the dir is missing or has no hub board.
    """
    candidate = Path(raw)
    if not candidate.is_dir():
        raise ValueError(f"board-ui: no such directory: {raw}")
    repo_dir = candidate.resolve()
    board_path = hub.hub_root() / repo_dir.name / ".beads"
    if not hub.board_exists(board_path):
        raise ValueError(f"board-ui: no hub board for {repo_dir.name} at {board_path}")
    return repo_dir


def find_free_port() -> int:
    """First free 127.0.0.1 TCP port from PORT_START upward.

    Uses a stdlib ``socket`` bind probe (the shell used a /dev/tcp trick).
    Raises if none free within PORT_TRIES.
    """
    for port in range(PORT_START, PORT_START + PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"board-ui: no free port in {PORT_START}-{PORT_START + PORT_TRIES - 1}")


def is_alive(pid: int) -> bool:
    """True iff a process with ``pid`` exists (``os.kill(pid, 0)``)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_or(path: Path, default: str) -> str:
    """File contents (stripped), or ``default`` if the file is absent."""
    return path.read_text(encoding="utf-8").strip() if path.is_file() else default


def cmd_up(args: argparse.Namespace) -> int:
    """Start or reuse the board UI for REPO_DIR; print its URL.

    Reuses a live instance if its recorded pid is alive; prunes a stale
    pidfile otherwise, picks a free port, launches bdui with
    BDUI_RUNTIME_DIR set, records port + repo.
    """
    bdui = bdui_bin()
    repo_dir = resolve_repo(args.repo_dir)
    run_dir = repo_runtime_dir(repo_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    pid_file, port_file = run_dir / "server.pid", run_dir / "port"
    if pid_file.is_file():
        pid = int(_read_or(pid_file, "0"))
        if is_alive(pid) and port_file.is_file():
            print(f"http://127.0.0.1:{_read_or(port_file, '?')}")
            return 0
        pid_file.unlink(missing_ok=True)
        port_file.unlink(missing_ok=True)

    port = find_free_port()
    path = os.environ.get("PATH", "")
    if Path(LINUXBREW_BIN).is_dir():
        path = f"{LINUXBREW_BIN}:{path}"
    env = {**os.environ, "PATH": path, "BDUI_RUNTIME_DIR": str(run_dir)}
    result = subprocess.run(
        [str(bdui), "start", "--host", "127.0.0.1", "--port", str(port)],
        cwd=repo_dir, env=env, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"board-ui: bdui start failed for {repo_dir}")

    port_file.write_text(f"{port}\n", encoding="utf-8")
    (run_dir / "repo").write_text(f"{repo_dir}\n", encoding="utf-8")
    print(f"http://127.0.0.1:{port}")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    """Stop the board UI for REPO_DIR and remove its runtime dir."""
    bdui = bdui_bin()
    repo_dir = resolve_repo(args.repo_dir)
    run_dir = repo_runtime_dir(repo_dir)

    if not (run_dir / "server.pid").is_file():
        print(f"board-ui: no board UI running for {repo_dir}", file=sys.stderr)
        return 0

    env = {**os.environ, "BDUI_RUNTIME_DIR": str(run_dir)}
    subprocess.run([str(bdui), "stop"], env=env, check=False)
    shutil.rmtree(run_dir, ignore_errors=True)
    print(f"board-ui: stopped {repo_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """List running board UIs, pruning stale runtime dirs as it scans."""
    root = runtime_root()
    if not root.is_dir():
        return 0
    for run_dir in sorted(root.iterdir()):
        pid_file = run_dir / "server.pid"
        if not pid_file.is_file():
            continue
        pid = int(_read_or(pid_file, "0"))
        if not is_alive(pid):
            shutil.rmtree(run_dir, ignore_errors=True)
            continue
        port = _read_or(run_dir / "port", "?")
        repo = _read_or(run_dir / "repo", "?")
        print(f"{repo} -> http://127.0.0.1:{port} ({pid})")
    return 0
