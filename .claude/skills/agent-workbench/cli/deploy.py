"""`deploy` subcommand -- pure-Python port of the bash deploy driver at
deploy/agent-workbench/agent-workbench.

One-command local deploy of the hardened agent-workbench containers
(kb-serve + review-serve + bdui) as rootless podman-quadlet systemd user
units.
Subcommands:
    up      build images, install quadlets (symlink), start + health-check
    down    stop + disable + remove ONLY the quadlets this bundle installed
    status  systemctl status + HTTP health for both, plus bd hub presence

Ownership rule (PRESERVED): `up` never restarts an already-active
review-serve; `down` only touches a unit whose installed quadlet is this
bundle's own symlink (a hand-installed real file is left untouched).

Invokes ``podman``, ``systemctl --user`` via subprocess (argument-list
form). HTTP health checks use stdlib ``urllib`` (no curl dependency), and
already surface the status code the way the old ``curl -w`` did.

Naming: the old bash driver was a file literally named
``agent-workbench`` inside a dir also named ``agent-workbench`` (cold
reader learns nothing). It becomes the ``deploy`` subcommand of the one
skill CLI; the whole ``deploy/agent-workbench/`` tree is deleted once this
lands (see the hardening plan's delete list).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from cli import hub, paths

__all__ = ["register", "build_image", "install_quadlet", "wait_for_http"]

KB_IMAGE = "localhost/kb-serve:latest"
REVIEW_IMAGE = "localhost/review-serve:latest"
BDUI_IMAGE = "localhost/bdui:latest"
# n8n is the OFFICIAL image, pinned by its multi-arch manifest-list digest
# (n8n 2.31.5) -- NOT built here. The quadlet's Image= carries the same
# digest and Podman auto-pulls it on first start, so `up` has no
# build_image step for n8n (a single-owner service like kb-serve, not a
# shared one like review-serve). ponytail: rely on quadlet auto-pull rather
# than adding a pull_image() helper.
N8N_IMAGE = (
    "docker.io/n8nio/n8n@sha256:"
    "cda6bafc7bb4873533e7affb82d1bd47282a7614bdf83242c2293f8ff281261a"
)
KB_HEALTH_URL = "http://127.0.0.1:9100/health"
REVIEW_HEALTH_URL = "http://127.0.0.1:9099/"
BDUI_HEALTH_URL = "http://127.0.0.1:3100/"
N8N_HEALTH_URL = "http://127.0.0.1:5678/healthz"
HEALTH_WAIT_TRIES = 15
# n8n runs DB migrations on first boot; give it more headroom than the
# build-and-start services.
N8N_HEALTH_WAIT_TRIES = 30
HEALTH_CHECK_TIMEOUT_SEC = 3


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `deploy` parser and its sub-subcommands; set func handlers."""
    parser = subparsers.add_parser(
        "deploy", help="build + run the kb-serve/review-serve containers",
    )
    sub = parser.add_subparsers(dest="deploy_command", required=True)

    up_cmd = sub.add_parser("up", help="build images, install quadlets, start + health-check")
    up_cmd.set_defaults(func=cmd_up)

    down_cmd = sub.add_parser("down", help="stop + disable + remove bundle-owned quadlets")
    down_cmd.set_defaults(func=cmd_down)

    status_cmd = sub.add_parser("status", help="systemctl status + HTTP health for both units")
    status_cmd.set_defaults(func=cmd_status)


def quadlet_dir() -> Path:
    """``$HOME/.config/containers/systemd`` (the user quadlet dir)."""
    return Path.home() / ".config" / "containers" / "systemd"


def build_image(tag: str, containerfile: str, context_dir: str) -> None:
    """``podman build -t <tag> -f <containerfile> <context_dir>``."""
    print(f"agent-workbench: building {tag}")
    subprocess.run(["podman", "build", "-t", tag, "-f", containerfile, context_dir], check=True)


def unit_active(unit: str) -> bool:
    """True iff ``systemctl --user is-active <unit>`` reports active."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", unit], check=False,
    )
    return result.returncode == 0


def install_quadlet(unit_name: str, src: str) -> None:
    """Symlink a tracked quadlet into the user quadlet dir.

    Skips entirely if ``<unit_name>.service`` is already active (a running
    service is never touched). Idempotent when the symlink already points
    at ``src``.
    """
    if unit_active(f"{unit_name}.service"):
        print(f"agent-workbench: {unit_name}.service active, "
              "leaving its installed quadlet untouched")
        return
    quadlet_dir().mkdir(parents=True, exist_ok=True)
    target = quadlet_dir() / f"{unit_name}.container"
    src_path = Path(src).resolve()
    if target.is_symlink() and target.resolve() == src_path:
        return
    target.unlink(missing_ok=True)
    target.symlink_to(src_path)
    print(f"agent-workbench: linked {target} -> {src_path}")


def quadlet_owned(unit_name: str, src: str) -> bool:
    """True iff the installed quadlet for ``unit_name`` is this bundle's own
    symlink to ``src`` (vs. a real hand-installed file, or nothing installed)."""
    target = quadlet_dir() / f"{unit_name}.container"
    return target.is_symlink() and target.resolve() == Path(src).resolve()


def uninstall_quadlet(unit_name: str, src: str) -> None:
    """Remove the quadlet symlink this bundle installed; never a real file."""
    if not quadlet_owned(unit_name, src):
        return
    target = quadlet_dir() / f"{unit_name}.container"
    target.unlink()
    print(f"agent-workbench: removed {target}")


def _http_status(url: str) -> int | None:
    """HTTP status of a GET, or None on a refused/failed connection (the
    Python analog of curl's "000" on connect failure)."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_CHECK_TIMEOUT_SEC) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return None


def wait_for_http(url: str, tries: int = HEALTH_WAIT_TRIES) -> bool:
    """Poll ``url`` up to ``tries`` times (1s apart) for HTTP 200.

    Default ``tries`` preserves the existing kb-serve/review-serve
    behavior; n8n passes N8N_HEALTH_WAIT_TRIES for its slower first boot.
    Uses stdlib urllib; a refused/again-later connection counts as not-yet
    and is retried, never raised.
    """
    for _ in range(tries):
        if _http_status(url) == 200:
            return True
        time.sleep(1)
    return False


def _health_line(url: str) -> str:
    """"health: 200" on success, else "health: unreachable (got <code>)"."""
    status = _http_status(url)
    if status == 200:
        return f"health: {status}"
    return f"health: unreachable (got {status if status is not None else '000'})"


def _ensure_data_dirs() -> None:
    """Create the bare-host KB_HOME / ARTIFACTS_HOME dirs so podman never
    auto-creates them (root-owned) on first bind mount. Same defaults the
    quadlets bind under %h; the env overrides are host-side bookkeeping
    only (H3: non-functional once containerized)."""
    kb_home = os.environ.get("KB_HOME", str(Path.home() / ".knowledgebase"))
    artifacts_home = os.environ.get(
        "ARTIFACTS_HOME", str(Path.home() / ".local" / "share" / "claude-artifacts"),
    )
    Path(kb_home).mkdir(parents=True, exist_ok=True)
    Path(artifacts_home).mkdir(parents=True, exist_ok=True)
    # n8n data dir the quadlet binds at /home/node/.n8n -- no env override,
    # the quadlet path is fixed. n8n.env, if used, also lives in this dir.
    Path(Path.home() / ".local" / "share" / "n8n").mkdir(parents=True, exist_ok=True)


def cmd_up(args: argparse.Namespace) -> int:
    """Build both images, install both quadlets, daemon-reload, start +
    health-check. Leaves an already-active review-serve running."""
    _ensure_data_dirs()

    build_image(
        KB_IMAGE, str(paths.KB_CONTAINER_DIR / "Containerfile"), str(paths.SCRIPTS_DIR),
    )
    build_image(
        REVIEW_IMAGE, str(paths.REVIEW_CONTAINER_DIR / "Containerfile"),
        str(paths.REVIEW_SKILL_DIR),
    )
    build_image(
        BDUI_IMAGE, str(paths.BDUI_CONTAINER_DIR / "Containerfile"),
        str(paths.BDUI_CONTAINER_DIR),
    )

    install_quadlet("kb-serve", str(paths.KB_CONTAINER_DIR / "kb-serve.container"))
    install_quadlet("review-serve", str(paths.REVIEW_CONTAINER_DIR / "review-serve.container"))
    install_quadlet("bdui", str(paths.BDUI_CONTAINER_DIR / "bdui.container"))
    install_quadlet("n8n", str(paths.N8N_CONTAINER_DIR / "n8n.container"))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    subprocess.run(["systemctl", "--user", "start", "kb-serve"], check=True)
    print("agent-workbench: waiting for kb-serve health...")
    if wait_for_http(KB_HEALTH_URL):
        print(f"agent-workbench: kb-serve up at {KB_HEALTH_URL}")
    else:
        print("agent-workbench: kb-serve not healthy yet -- check: journalctl --user -u kb-serve")

    if unit_active("review-serve.service"):
        print("agent-workbench: review-serve already active, leaving it running")
    else:
        subprocess.run(["systemctl", "--user", "start", "review-serve"], check=True)
        print("agent-workbench: waiting for review-serve health...")
        if wait_for_http(REVIEW_HEALTH_URL):
            print(f"agent-workbench: review-serve up at {REVIEW_HEALTH_URL}")
        else:
            print("agent-workbench: review-serve not healthy yet -- "
                  "check: journalctl --user -u review-serve")

    if unit_active("bdui.service"):
        print("agent-workbench: bdui already active, leaving it running")
    else:
        subprocess.run(["systemctl", "--user", "start", "bdui"], check=True)
        print("agent-workbench: waiting for bdui health...")
        if wait_for_http(BDUI_HEALTH_URL):
            print(f"agent-workbench: bdui up at {BDUI_HEALTH_URL}")
        else:
            print("agent-workbench: bdui not healthy yet -- check: journalctl --user -u bdui")

    if unit_active("n8n.service"):
        print("agent-workbench: n8n already active, leaving it running")
    else:
        subprocess.run(["systemctl", "--user", "start", "n8n"], check=True)
        print("agent-workbench: waiting for n8n health...")
        if wait_for_http(N8N_HEALTH_URL, tries=N8N_HEALTH_WAIT_TRIES):
            print(f"agent-workbench: n8n up at {N8N_HEALTH_URL}")
        else:
            print("agent-workbench: n8n not healthy yet -- check: journalctl --user -u n8n")

    beads_hub_dir = hub.hub_root()
    if beads_hub_dir.is_dir():
        print(f"agent-workbench: bd hub present at {beads_hub_dir}")
    else:
        print(f"agent-workbench: bd hub not found at {beads_hub_dir} -- "
              "not a service, created on demand by 'agent-workbench hub add'")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    """Stop/disable/remove only bundle-owned quadlets, then daemon-reload."""
    review_src = str(paths.REVIEW_CONTAINER_DIR / "review-serve.container")
    if quadlet_owned("review-serve", review_src):
        print("agent-workbench: stopping review-serve -- this interrupts the shared review "
              "app; re-run 'up' or 'systemctl --user start review-serve' to bring it back")
        subprocess.run(["systemctl", "--user", "stop", "review-serve"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "review-serve"], check=False)
        uninstall_quadlet("review-serve", review_src)
    else:
        print("agent-workbench: review-serve not installed by this bundle, leaving it untouched")

    kb_src = str(paths.KB_CONTAINER_DIR / "kb-serve.container")
    if quadlet_owned("kb-serve", kb_src):
        subprocess.run(["systemctl", "--user", "stop", "kb-serve"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "kb-serve"], check=False)
        uninstall_quadlet("kb-serve", kb_src)
    else:
        print("agent-workbench: kb-serve not installed by this bundle, leaving it untouched")

    bdui_src = str(paths.BDUI_CONTAINER_DIR / "bdui.container")
    if quadlet_owned("bdui", bdui_src):
        subprocess.run(["systemctl", "--user", "stop", "bdui"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "bdui"], check=False)
        uninstall_quadlet("bdui", bdui_src)
    else:
        print("agent-workbench: bdui not installed by this bundle, leaving it untouched")

    n8n_src = str(paths.N8N_CONTAINER_DIR / "n8n.container")
    if quadlet_owned("n8n", n8n_src):
        subprocess.run(["systemctl", "--user", "stop", "n8n"], check=False)
        subprocess.run(["systemctl", "--user", "disable", "n8n"], check=False)
        uninstall_quadlet("n8n", n8n_src)
    else:
        print("agent-workbench: n8n not installed by this bundle, leaving it untouched")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print systemctl status + HTTP health for both units and hub presence."""
    print("--- kb-serve ---")
    subprocess.run(["systemctl", "--user", "status", "kb-serve", "--no-pager"], check=False)
    print(_health_line(KB_HEALTH_URL))
    print()
    print("--- review-serve ---")
    subprocess.run(["systemctl", "--user", "status", "review-serve", "--no-pager"], check=False)
    print(_health_line(REVIEW_HEALTH_URL))
    print()
    print("--- bdui ---")
    subprocess.run(["systemctl", "--user", "status", "bdui", "--no-pager"], check=False)
    print(_health_line(BDUI_HEALTH_URL))
    print()
    print("--- n8n ---")
    subprocess.run(["systemctl", "--user", "status", "n8n", "--no-pager"], check=False)
    print(_health_line(N8N_HEALTH_URL))
    print()
    print("--- bd hub (not a service) ---")
    beads_hub_dir = hub.hub_root()
    presence = "present" if beads_hub_dir.is_dir() else "absent"
    print(f"data: {beads_hub_dir} ({presence})")
    return 0
