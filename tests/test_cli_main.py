"""Coverage for the agent-workbench CLI's top-level surface.

Invokes the real `agent-workbench` executable as a subprocess (rather than
importing `cli.main` in-process) so these tests are robust against
import-path collisions with any other `cli` package elsewhere on
sys.path, and exercise the CLI exactly the way a real user/agent does.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "agent-workbench"
CLI_DIR = REPO_ROOT / ".claude" / "skills" / "agent-workbench" / "cli"

# doctor.py is the sole allowed exception to "the CLI never shells out":
# its entire job is probing the host for prerequisites (container runtime,
# compose impl) via `which`/`--version` checks. It never starts a container
# or manages persisted data, unlike the shelling-out module this invariant
# guards against re-adding (1dacb62 broke this, 869697a repaired it).
SHELL_OUT_ALLOWLIST = {"doctor.py"}

# Modules/attributes that mean "this file can launch a subprocess".
_BANNED_MODULES = {"subprocess", "tempfile", "podman", "docker"}
_BANNED_ATTRS = {("os", "system"), ("shutil", "which")}


def _shell_out_violations(source: str, filename: str) -> list[str]:
    """AST-based scan of `source` for the banned shelling-out primitives
    (subprocess, tempfile/mkdtemp, shutil.which, os.system, os.exec*, or a
    podman/docker import). Parses with `ast` rather than grepping raw text,
    so a docstring/comment mentioning these words never trips it, and a
    real import cannot hide from it."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BANNED_MODULES:
                    violations.append(f"import {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in _BANNED_MODULES:
                violations.append(f"from {node.module} import ... (line {node.lineno})")
            for alias in node.names:
                if node.module == "os" and (
                    alias.name == "system" or alias.name.startswith("exec")
                ):
                    violations.append(f"from os import {alias.name} (line {node.lineno})")
                if node.module == "shutil" and alias.name == "which":
                    violations.append(f"from shutil import which (line {node.lineno})")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            if (base, node.attr) in _BANNED_ATTRS or (
                base == "os" and node.attr.startswith("exec")
            ):
                violations.append(f"{base}.{node.attr} (line {node.lineno})")
    return violations


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the agent-workbench executable with `args`, capturing output."""
    return subprocess.run(
        [sys.executable, str(EXECUTABLE), *args],
        capture_output=True, text=True, check=False,
    )


def test_top_level_help_lists_expected_subcommands() -> None:
    """--help lists kb/bd/artifact/install/init-workspace/doctor,
    not hub/board/deploy/scratch."""
    result = run_cli("--help")
    assert result.returncode == 0
    assert "kb" in result.stdout
    assert "bd" in result.stdout
    assert "artifact" in result.stdout
    assert "install" in result.stdout
    assert "init-workspace" in result.stdout
    assert "doctor" in result.stdout
    # The old separate top-level `hub`/`board` subcommands were folded into
    # `bd`; the exact choices set proves they no longer appear as top-level
    # subcommands (a stray "hub"/"board" would only show up folded inside
    # `bd`'s own help text, checked separately in test_bd_help_lists_*).
    # `scratch` is repo dev tooling now (scripts/scratch.py), not a CLI
    # subcommand -- its absence here proves that.
    assert (
        "{kb,bd,artifact,install,init-workspace,doctor}"
        in result.stdout
    )
    assert "scratch" not in result.stdout


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_top_level_help_flags_both_work(flag: str) -> None:
    """Both --help and -h produce the same usage/exit behavior."""
    result = run_cli(flag)
    assert result.returncode == 0
    assert "usage: agent-workbench" in result.stdout


def test_bd_help_lists_expected_sub_subcommands() -> None:
    """`bd --help` lists the folded hub and issue subcommands."""
    result = run_cli("bd", "--help")
    assert result.returncode == 0
    for name in ("init", "add", "sync", "list", "path", "status",
                 "ready", "search", "dep"):
        assert name in result.stdout


def test_artifact_help_lists_expected_sub_subcommands() -> None:
    """`artifact --help` lists publish/feedback/serve/status."""
    result = run_cli("artifact", "--help")
    assert result.returncode == 0
    for name in ("publish", "feedback", "serve", "status"):
        assert name in result.stdout


def test_install_help_shows_mutually_exclusive_flags() -> None:
    """`install --help` documents --link/--copy/--uninstall."""
    result = run_cli("install", "--help")
    assert result.returncode == 0
    assert "--link" in result.stdout
    assert "--copy" in result.stdout
    assert "--uninstall" in result.stdout


def test_install_with_no_flags_errors_nonzero() -> None:
    """`install` with no flag given is a required-mutually-exclusive-group error."""
    result = run_cli("install")
    assert result.returncode != 0
    assert "one of the arguments --link --copy --uninstall is required" in result.stderr


def test_retired_deploy_subcommand_is_rejected() -> None:
    """`deploy` was retired in favour of docker-compose; argparse must reject it."""
    result = run_cli("deploy", "status")
    assert result.returncode != 0
    assert "invalid choice: 'deploy'" in result.stderr


def test_missing_top_level_subcommand_errors_nonzero() -> None:
    """No subcommand at all is also a hard argparse error (required=True)."""
    result = run_cli()
    assert result.returncode != 0


def test_cli_modules_never_shell_out_except_doctor() -> None:
    """The CLI is a pure HTTP client of kb-svc/bd-svc/artifact-svc. This
    has already been broken and repaired once (1dacb62 broke it, 869697a
    repaired it) with nothing stopping a third round -- this is that
    guard. Fails loudly, naming the offending file and symbol, if a
    subprocess/tempfile/shutil.which/os.system/os.exec*/podman/docker
    primitive reappears anywhere outside doctor.py."""
    offenders = {
        path.name: violations
        for path in sorted(CLI_DIR.rglob("*.py"))
        if path.relative_to(CLI_DIR).as_posix() not in SHELL_OUT_ALLOWLIST
        and (violations := _shell_out_violations(
            path.read_text(encoding="utf-8"), str(path),
        ))
    }

    assert not offenders, (
        "cli/*.py must stay a pure HTTP client of kb-svc/bd-svc/"
        "artifact-svc -- it never shells out, spawns a subprocess, or "
        "invokes podman/docker directly (doctor.py is the sole allowed "
        "exception: its whole job is probing host prerequisites for "
        "presence, never starting a container or managing data). "
        f"Offending file(s): {offenders}"
    )
