"""Tests for the pure-Python agent-workbench CLI at
.claude/skills/agent-workbench/cli/.

One subcommand module per section (hub, board, init-workspace, deploy,
main dispatcher; the kb HTTP client's own tests live in
tests/test_cli_kb.py). Every test keeps KB_HOME / BEADS_HUB_DIR /
XDG_RUNTIME_DIR / HOME pinned under tmp_path (or mocks the subprocess /
urllib calls a real host would otherwise receive), so nothing here ever
touches the real ~/.knowledgebase, ~/.beads-hub, or a live kb-serve /
artifact-serve / bdui process. Mirrors tests/test_kb_serve.py's style:
tmp_path per vault, mocked urllib for anything that would hit the
network, real subprocess only where it is provably read-only (never
here -- deploy's mutating verbs are always mocked).

Each audit-fix test names its fix (M1/M3/M4/LOW) in its docstring; see
docs/agent-workbench-hardening-plan.md's "Audit fold-in mapping" table.
"""
from __future__ import annotations

import argparse
import io
import json
import socket
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

_AGENT_WORKBENCH_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "agent-workbench"
if str(_AGENT_WORKBENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_WORKBENCH_DIR))

from cli import board, deploy, hub, init_workspace, kb  # noqa: E402
from cli import main as cli_main  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# hub
# ═══════════════════════════════════════════════════════════════════════


def test_hub_root_honors_beads_hub_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    assert hub.hub_root() == tmp_path / "hub"


@pytest.mark.parametrize(
    ("layout", "expected"),
    [
        ("embeddeddolt_dir", True),
        ("db_file", True),
        ("empty", False),
        ("absent", False),
    ],
)
def test_board_exists_keys_off_dolt_db_not_dir_presence(
    tmp_path: Path, layout: str, expected: bool,
) -> None:
    beads_dir = tmp_path / "proj" / ".beads"
    if layout == "embeddeddolt_dir":
        (beads_dir / "embeddeddolt").mkdir(parents=True)
    elif layout == "db_file":
        beads_dir.mkdir(parents=True)
        (beads_dir / "board.db").write_text("", encoding="utf-8")
    elif layout == "empty":
        beads_dir.mkdir(parents=True)
    # "absent": never create beads_dir at all
    assert hub.board_exists(beads_dir) is expected


def test_cmd_status_uninitialized_hub_reports_false_and_no_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    hub.cmd_status(argparse.Namespace())
    body = json.loads(capsys.readouterr().out)
    assert body == {"hub_root": str(tmp_path / "hub"), "initialized": False, "repos": []}


def test_bd_env_without_beads_dir_strips_ambient_beads_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 fix: the env dict handed to `bd init` never carries an ambient
    BEADS_DIR, even though the real process env has one set."""
    monkeypatch.setenv("BEADS_DIR", "/decoy/path/.beads")
    env = hub._bd_env_without_beads_dir()
    assert "BEADS_DIR" not in env
    import os
    assert os.environ["BEADS_DIR"] == "/decoy/path/.beads"  # ambient env itself untouched


def test_init_board_runs_bd_init_with_beads_dir_stripped_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4 fix, end to end: init_board's own `bd init` subprocess call
    never receives an ambient BEADS_DIR that could redirect it."""
    monkeypatch.setenv("BEADS_DIR", "/decoy/path/.beads")
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], cwd: object = None, env: dict[str, str] | None = None, check: bool = False) -> subprocess.CompletedProcess:
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(hub.subprocess, "run", fake_run)
    hub.init_board(tmp_path / "proj", "proj")
    assert "BEADS_DIR" not in captured["env"]


def test_init_board_removes_only_the_incidental_git_repo_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW fix (hub naming/TOCTOU): git_repo_preexisted is sensed BEFORE
    `bd init` runs and correctly gates cleanup -- a .git dir bd's
    --stealth mode incidentally creates gets removed, but a .git dir that
    was already there before init_board ran is never touched."""

    def fake_run_creates_git(cmd: list[str], cwd: Path, env: dict[str, str], check: bool) -> subprocess.CompletedProcess:
        (cwd / ".git").mkdir()  # simulates bd --stealth's incidental repo
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(hub.subprocess, "run", fake_run_creates_git)

    fresh_dir = tmp_path / "fresh"
    hub.init_board(fresh_dir, "fresh")
    assert not (fresh_dir / ".git").is_dir()  # incidental repo: removed


def test_init_board_keeps_a_preexisting_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LOW fix (hub naming/TOCTOU), inverse case: a .git dir that already
    existed before init_board ran survives (never mistaken for bd's
    incidental one)."""
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    (existing_dir / ".git").mkdir()

    monkeypatch.setattr(
        hub.subprocess, "run",
        lambda cmd, cwd, env, check: subprocess.CompletedProcess(cmd, 0),
    )
    hub.init_board(existing_dir, "existing")
    assert (existing_dir / ".git").is_dir()  # preexisting repo: untouched


def test_cmd_add_rereads_registered_repos_immediately_before_bd_repo_add(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOW fix (hub naming/TOCTOU): cmd_add checks registration against a
    freshly read repo list right before `bd repo add`, closing the
    check-then-add race the old shell script left open."""
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    (tmp_path / "hub" / "hub" / ".beads" / "embeddeddolt").mkdir(parents=True)
    (tmp_path / "hub" / "myproj" / ".beads" / "embeddeddolt").mkdir(parents=True)

    reads: list[str] = []
    monkeypatch.setattr(hub, "registered_repos", lambda: reads.append("read") or [])

    add_calls: list[list[str]] = []

    def fake_run(cmd: list[str], env: dict[str, str], check: bool) -> subprocess.CompletedProcess:
        add_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(hub.subprocess, "run", fake_run)

    result = hub.cmd_add(argparse.Namespace(name="myproj", prefix=None))
    assert result == 0
    assert reads == ["read"]
    assert add_calls == [[hub.BD_BIN, "repo", "add", str(tmp_path / "hub" / "myproj")]]


def test_cmd_add_skips_bd_repo_add_when_already_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    (tmp_path / "hub" / "hub" / ".beads" / "embeddeddolt").mkdir(parents=True)
    project_dir = tmp_path / "hub" / "myproj"
    (project_dir / ".beads" / "embeddeddolt").mkdir(parents=True)
    monkeypatch.setattr(hub, "registered_repos", lambda: [str(project_dir)])

    add_calls: list[list[str]] = []
    monkeypatch.setattr(
        hub.subprocess, "run",
        lambda cmd, env, check: add_calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    assert hub.cmd_add(argparse.Namespace(name="myproj", prefix=None)) == 0
    assert add_calls == []  # error path: no redundant re-registration


def test_cmd_path_missing_board_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    with pytest.raises(ValueError, match="no board for myproj"):
        hub.cmd_path(argparse.Namespace(name="myproj"))


# ═══════════════════════════════════════════════════════════════════════
# board
# ═══════════════════════════════════════════════════════════════════════


def test_resolve_repo_validates_against_hub_board_not_stale_repo_local_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1 fix: resolve_repo validates against the hub board
    ($HUB_ROOT/<name>/.beads), never a repo-local .beads. A repo dir with
    NO .beads of its own but a matching hub board still resolves -- the
    old board-ui.sh:54 required <repo>/.beads and would have failed this
    exact case."""
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    assert not (repo_dir / ".beads").exists()  # no local board: the old check dies here
    (tmp_path / "hub" / "myrepo" / ".beads" / "embeddeddolt").mkdir(parents=True)

    assert board.resolve_repo(str(repo_dir)) == repo_dir.resolve()


def test_resolve_repo_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such directory"):
        board.resolve_repo(str(tmp_path / "does-not-exist"))


def test_resolve_repo_dir_without_any_hub_board_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    with pytest.raises(ValueError, match="no hub board"):
        board.resolve_repo(str(repo_dir))


def test_find_free_port_skips_an_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", board.PORT_START))
        blocker.listen(1)
        port = board.find_free_port()
    assert port != board.PORT_START


def test_cmd_status_with_no_runtime_root_is_a_clean_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg-never-created"))
    assert board.cmd_status(argparse.Namespace()) == 0
    assert capsys.readouterr().out == ""


# ═══════════════════════════════════════════════════════════════════════
# init-workspace
# ═══════════════════════════════════════════════════════════════════════


def test_cmd_init_workspace_scaffolds_a_tmp_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(init_workspace.hub, "cmd_add", lambda args: 0)  # never touch a real bd board

    result = init_workspace.cmd_init_workspace(
        argparse.Namespace(target_dir=str(tmp_path), prefix=None),
    )

    assert result == 0
    assert (tmp_path / "docs" / "kb").is_dir()
    assert (tmp_path / "workstreams").is_dir()
    assert (tmp_path / "kb.db").is_file()  # build-kb-index ran for real (pure sqlite, no network)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111  # installed executable


def test_cmd_init_workspace_missing_target_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such directory"):
        init_workspace.cmd_init_workspace(
            argparse.Namespace(target_dir=str(tmp_path / "nope"), prefix=None),
        )


def test_install_post_commit_hook_never_overwrites_an_existing_hook(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    existing = hooks_dir / "post-commit"
    existing.write_text("#!/usr/bin/env bash\necho custom-hook\n", encoding="utf-8")

    assert init_workspace.install_post_commit_hook(tmp_path) is False
    assert existing.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho custom-hook\n"


# ═══════════════════════════════════════════════════════════════════════
# deploy
# ═══════════════════════════════════════════════════════════════════════


def test_cmd_status_only_runs_read_only_systemctl_status_never_mutating_verbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """deploy status happy path: proves the read-only path never invokes
    build/start/stop, and no real network call is made (health probe is
    mocked unreachable), so this test cannot touch a live host service."""
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))  # keep hub.hub_root() off the real host
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess, "run",
        lambda cmd, check=False, **kwargs: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    monkeypatch.setattr(deploy, "_http_status", lambda url: None)

    assert deploy.cmd_status(argparse.Namespace(json=False)) == 0
    assert calls == [
        ["systemctl", "--user", "is-active", "kb-serve"],
        ["systemctl", "--user", "is-active", "artifact-serve"],
        ["systemctl", "--user", "is-active", "bdui"],
        ["systemctl", "--user", "is-active", "n8n"],
    ]
    assert "unreachable" in capsys.readouterr().out


def test_build_image_surfaces_subprocess_failure_instead_of_swallowing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], check: bool) -> None:
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        deploy.build_image("localhost/kb-serve:latest", "Containerfile", "ctx")


def test_wait_for_http_returns_true_on_first_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, "_http_status", lambda url: 200)
    monkeypatch.setattr(deploy.time, "sleep", lambda s: None)
    assert deploy.wait_for_http("http://127.0.0.1:9100/health") is True


def test_wait_for_http_gives_up_after_max_tries_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, "_http_status", lambda url: None)
    monkeypatch.setattr(deploy.time, "sleep", lambda s: None)
    assert deploy.wait_for_http("http://127.0.0.1:9100/health") is False


def test_quadlet_owned_true_only_for_this_bundles_own_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deploy.Path, "home", classmethod(lambda cls: tmp_path))
    src = tmp_path / "kb-serve.container"
    src.write_text("", encoding="utf-8")
    assert deploy.quadlet_owned("kb-serve", str(src)) is False  # nothing installed yet

    quadlet_dir = deploy.quadlet_dir()
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "kb-serve.container").symlink_to(src)
    assert deploy.quadlet_owned("kb-serve", str(src)) is True

    hand_installed = quadlet_dir / "artifact-serve.container"
    hand_installed.write_text("", encoding="utf-8")  # real file, not our symlink
    assert deploy.quadlet_owned("artifact-serve", str(src)) is False


def test_n8n_image_is_pinned_by_digest_never_a_floating_tag() -> None:
    """Regression: N8N_IMAGE must stay a manifest-list digest pin, never
    ``:latest`` or any other floating tag."""
    assert deploy.N8N_IMAGE.startswith("docker.io/n8nio/n8n@sha256:")


def test_cmd_up_installs_and_starts_n8n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_up wires n8n alongside kb-serve/artifact-serve: quadlet installed,
    unit started, health-waited -- none of it touches a live host."""
    monkeypatch.setattr(deploy.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("BEADS_HUB_DIR", str(tmp_path / "hub"))
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
        calls.append(cmd)
        returncode = 1 if "is-active" in cmd else 0  # nothing pre-existing is active
        return subprocess.CompletedProcess(cmd, returncode)

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    monkeypatch.setattr(deploy, "wait_for_http", lambda url, tries=None: True)

    assert deploy.cmd_up(argparse.Namespace()) == 0

    assert ["systemctl", "--user", "start", "n8n"] in calls
    n8n_src = str(deploy.paths.N8N_CONTAINER_DIR / "n8n.container")
    assert deploy.quadlet_owned("n8n", n8n_src) is True


def test_cmd_down_stops_and_removes_bundle_owned_n8n_quadlet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deploy.Path, "home", classmethod(lambda cls: tmp_path))
    n8n_src = str(deploy.paths.N8N_CONTAINER_DIR / "n8n.container")
    quadlet_dir = deploy.quadlet_dir()
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "n8n.container").symlink_to(Path(n8n_src).resolve())
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess, "run",
        lambda cmd, check=False: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )

    assert deploy.cmd_down(argparse.Namespace()) == 0

    assert ["systemctl", "--user", "stop", "n8n"] in calls
    assert ["systemctl", "--user", "disable", "n8n"] in calls
    assert not (quadlet_dir / "n8n.container").exists()


def test_cmd_down_leaves_hand_installed_n8n_quadlet_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deploy.Path, "home", classmethod(lambda cls: tmp_path))
    quadlet_dir = deploy.quadlet_dir()
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "n8n.container").write_text("", encoding="utf-8")  # real file, not our symlink
    calls: list[list[str]] = []
    monkeypatch.setattr(
        deploy.subprocess, "run",
        lambda cmd, check=False: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )

    assert deploy.cmd_down(argparse.Namespace()) == 0

    assert ["systemctl", "--user", "stop", "n8n"] not in calls
    assert (quadlet_dir / "n8n.container").is_file()


# ═══════════════════════════════════════════════════════════════════════
# main dispatcher
# ═══════════════════════════════════════════════════════════════════════


def test_build_parser_registers_all_six_subcommands() -> None:
    parser = cli_main.build_parser()
    [command_action] = [
        action for action in parser._subparsers._group_actions if action.dest == "command"
    ]
    assert set(command_action.choices) == {
        "kb", "bd", "artifact", "deploy", "install", "init-workspace",
    }


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli_main.main([])


def test_main_converts_a_handler_runtimeerror_to_exit_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(kb, "cmd_path", boom)
    assert cli_main.main(["kb", "path", "proj1"]) == 1
