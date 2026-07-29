"""Tests for scripts/scratch.py -- the repo dev/test harness's pure guard
logic -- no podman needed.

`scratch` brings up a throwaway service container; the container-boundary
half of that is exercised manually (see the task's verification section),
never here, so this file never touches ports 9099/9100/9101 and never
shells out to podman. What IS pure logic, and must fail loudly rather than
silently falling back to the live stack, is covered here:

- an unknown service name is rejected by argparse before scratch.py runs
- a repo root with no docker-compose.yml raises, naming the missing files,
  instead of defaulting to live ports
- a scratch invocation with no wrapped command raises instead of no-op'ing
- the two non-target services are pointed at a `.invalid` sentinel host,
  never the live defaults
- `_split_argv` splits scratch's own flags from the wrapped command on the
  FIRST `--` only, regardless of flag position or a `--` inside the
  wrapped command itself
- build runs by default and only `--no-build` skips it
- the image-identity line lands on stderr, never stdout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import scratch  # noqa: E402


def test_overlay_pins_every_service_to_its_scratch_tag() -> None:
    """The REAL docker-compose.scratch.yml must override `image:` to the
    `:scratch` tag for every service scratch can run.

    This is the whole of defect 1's fix: without the override the overlay
    inherits `image: localhost/kb-svc:latest` from docker-compose.yml and
    a scratch run exercises whatever the live stack's tag points at. Every
    other test stubs compose out and never reads this file, so nothing
    else here would notice the override being removed -- and
    `_print_image_identity` would keep printing `:scratch` while the
    container ran `:latest`, certifying the wrong image.
    """
    overlay = (
        Path(__file__).resolve().parent.parent / "docker-compose.scratch.yml"
    ).read_text(encoding="utf-8")

    image_lines = [
        line.strip() for line in overlay.splitlines()
        if line.strip().startswith("image:")
    ]

    for spec in scratch.SERVICES.values():
        assert f"image: {scratch._scratch_image(spec)}" in image_lines, (
            f"{spec.compose_name} is not pinned to its :scratch tag"
        )
    # Prose about :latest is fine; an actual `image:` naming it is the defect.
    assert not [line for line in image_lines if ":latest" in line]
    assert len(image_lines) == len(scratch.SERVICES)


def _stub_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[list[str], dict[str, object]]]:
    """Fake every subprocess.run call scratch.py would make against
    podman-compose/podman, recording (cmd, kwargs) pairs. No podman
    needed: `port`, `ps -q` and the two `inspect` calls get canned stdout,
    anything else (build/up/down/the wrapped command) just succeeds.

    The image-identity path is modelled as the three real calls it makes:
    `ps -q` for the container id, `container inspect` for the image the
    container actually runs, `image inspect` for that image's timestamp.
    """
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], *args: object, **kwargs: object):
        calls.append((cmd, kwargs))
        if "port" in cmd:
            return SimpleNamespace(returncode=0, stdout="127.0.0.1:12345\n")
        if "ps" in cmd:
            return SimpleNamespace(returncode=0, stdout="containerid123\n")
        if "container" in cmd and "inspect" in cmd:
            return SimpleNamespace(
                returncode=0, stdout="deadbeef localhost/kb-svc:scratch\n",
            )
        if "inspect" in cmd:
            return SimpleNamespace(returncode=0, stdout="2026-01-01T00:00:00Z\n")
        return SimpleNamespace(returncode=0, stdout="")

    template = tmp_path / "docker-compose.scratch.yml"
    template.write_text("services: {}\n")  # placeholder has none to replace
    base = tmp_path / "docker-compose.yml"

    monkeypatch.setattr(scratch.subprocess, "run", fake_run)
    monkeypatch.setattr(scratch, "_require_podman_compose", lambda: None)
    monkeypatch.setattr(scratch, "_compose_files", lambda: (base, template))
    monkeypatch.setattr(scratch, "_wait_healthy", lambda *a, **kw: None)
    return calls


def test_unknown_service_name_rejected() -> None:
    """`scratch.py bogus -- ...` fails loudly and non-zero, never runs."""
    with pytest.raises(SystemExit) as exc_info:
        scratch.build_parser().parse_args(["bogus"])
    assert exc_info.value.code != 0


def test_missing_compose_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """No docker-compose.yml at the repo root -> loud RuntimeError.

    Never falls through to the live-stack default ports -- this must raise
    before any container is ever considered.
    """
    monkeypatch.setattr(scratch, "REPO_ROOT", Path("/nonexistent-aw-root"))
    with pytest.raises(RuntimeError, match="docker-compose"):
        scratch._compose_files()


def test_empty_command_raises() -> None:
    """`scratch.py kb --` with nothing after `--` refuses instead of no-op.

    Goes through `_split_argv` exactly as `main()` does: handing
    `_command_args` a raw leading `--` is a shape the real entry point can
    no longer produce, and testing it would drift from production.
    """
    _, command = scratch._split_argv(["kb", "--"])

    with pytest.raises(RuntimeError, match="no command given"):
        scratch._command_args(command, "kb")


def test_split_argv_wrapped_command() -> None:
    """`kb -- bash -c 'a && b'`: everything after the first `--` is the
    wrapped command, untouched.
    """
    scratch_argv, command_argv = scratch._split_argv(
        ["kb", "--", "bash", "-c", "a && b"]
    )
    assert scratch_argv == ["kb"]
    assert command_argv == ["bash", "-c", "a && b"]


def test_split_argv_flag_before_separator() -> None:
    """`kb --no-build -- true`: scratch's own flag stays out of the
    wrapped command regardless of where it sits relative to `--`.
    """
    scratch_argv, command_argv = scratch._split_argv(
        ["kb", "--no-build", "--", "true"]
    )
    assert scratch_argv == ["kb", "--no-build"]
    assert command_argv == ["true"]


def test_split_argv_preserves_inner_separator() -> None:
    """Only the FIRST `--` is scratch's own separator -- a `--` inside the
    wrapped command (e.g. `kb query --`) must reach the command intact.
    """
    scratch_argv, command_argv = scratch._split_argv(
        ["kb", "--", "kb", "query", "--", "foo"]
    )
    assert scratch_argv == ["kb"]
    assert command_argv == ["kb", "query", "--", "foo"]


def test_split_argv_missing_command_fails_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`scratch.py kb` with no `--` at all -> loud, rc=1, never a no-op.

    No stubbing needed: `_command_args` raises before scratch ever touches
    podman-compose.
    """
    assert scratch.main(["kb"]) == 1
    assert "no command given" in capsys.readouterr().err


def test_podman_compose_chatter_stays_off_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """podman-compose's own `up`/`down` output must never share stdout with
    the wrapped command -- an agent piping scratch's stdout to `jq` would
    otherwise see container IDs and project lines ahead of the JSON.

    Asserts `up` and `down` redirect stdout away from the process's own
    stdout, the `port` lookup (already capture_output=True) doesn't leak
    either, and the wrapped command's own subprocess.run call is untouched
    -- no `stdout` kwarg at all, so it inherits the real stdout.
    """
    calls = _stub_compose(tmp_path, monkeypatch)

    args = argparse.Namespace(service="kb", command=["echo", "hi"], build=False)
    returncode = scratch.cmd_scratch(args)
    assert returncode == 0

    def find(token: str) -> dict[str, object]:
        [kwargs] = [kw for cmd, kw in calls if token in cmd]
        return kwargs

    assert find("up")["stdout"] is sys.stderr
    assert find("down")["stdout"] is sys.stderr
    # port lookup already uses capture_output=True; must not ALSO leak
    # to the process's own stdout via an explicit stdout= kwarg.
    assert "stdout" not in find("port")

    wrapped_cmd, wrapped_kwargs = calls[-2]  # up, port, inspect, [wrapped], down
    assert wrapped_cmd == ["echo", "hi"]
    assert "stdout" not in wrapped_kwargs


def test_build_runs_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `--no-build` -> `podman-compose ... build <svc>` runs before
    `up`. Build defaulting ON is load-bearing: podman-compose's `up` only
    builds a missing image, so without this a stale `:scratch` tag left
    over from an earlier branch would be reused forever.
    """
    # The PARSER DEFAULT is the fix, so assert on it directly. Handing
    # cmd_scratch a hand-built `build=True` namespace only exercises
    # _bring_up's dispatch and passes even with the default flipped back
    # to opt-in, which is the exact defect this test exists to catch.
    assert scratch.build_parser().parse_args(["kb"]).build is True

    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"], build=True)
    scratch.cmd_scratch(args)

    build_calls = [cmd for cmd, _ in calls if "build" in cmd]
    assert len(build_calls) == 1
    assert build_calls[0][-2:] == ["build", "kb-svc"]


def test_no_build_skips_build_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--no-build` (build=False) must not call `podman-compose ... build`."""
    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"], build=False)
    scratch.cmd_scratch(args)

    assert not any("build" in cmd for cmd, _ in calls)


def test_image_identity_printed_to_stderr_not_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The image tripwire line must land on stderr -- the wrapped
    command's stdout is the only thing scratch's own stdout may carry.
    """
    _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"], build=False)
    scratch.cmd_scratch(args)

    captured = capsys.readouterr()
    assert "localhost/kb-svc:scratch" in captured.err
    assert "id deadbeef" in captured.err
    assert "localhost/kb-svc:scratch" not in captured.out


def test_image_identity_inspects_the_container_not_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tripwire must read the CREATED CONTAINER's image, never the
    `:scratch` tag.

    The tag is global to the host while builds are per-worktree, so two
    concurrent scratch runs race for it: `up` resolves the tag at create
    time, so a later tag read can report an image the container is not
    running -- the branch's own failure class, re-entered via concurrency
    instead of staleness.
    """
    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"], build=False)
    scratch.cmd_scratch(args)

    inspects = [cmd for cmd, _ in calls if "inspect" in cmd]
    assert any(cmd[:3] == ["podman", "container", "inspect"] for cmd in inspects), (
        "never inspected the running container"
    )
    # A bare `podman image inspect <tag>` is the defect: it asks the tag,
    # not the container. Any image inspect must be BY ID, from the
    # container's own .Image.
    for cmd in inspects:
        if cmd[:3] == ["podman", "image", "inspect"]:
            assert cmd[3] == "deadbeef", (
                f"image inspected by tag, not by the container's image id: {cmd}"
            )


def test_command_args_keeps_a_caller_supplied_separator() -> None:
    """`scratch.py kb -- -- foo` must pass `--` through to the wrapped
    command. `_split_argv` already ate the real separator, so a second one
    is the caller's own argument and stripping it silently drops a token.
    """
    _, command = scratch._split_argv(["kb", "--", "--", "foo"])

    assert scratch._command_args(command, "kb") == ["--", "foo"]


def test_non_target_services_get_sentinel_host() -> None:
    """`scratch kb` must not leave BD_SVC_HOST/ARTIFACT_SVC_HOST at their
    live defaults -- a chained call to either must fail loudly, never
    silently reach the real service.
    """
    env = scratch._scratch_env(scratch.SERVICES["kb"], 12345, "kb")

    assert env["KB_SVC_HOST"] == "127.0.0.1"
    assert env["KB_SVC_PORT"] == "12345"
    assert env["BD_SVC_HOST"] == "bd-svc-not-started-by-this-scratch-run.invalid"
    assert env["ARTIFACT_SVC_HOST"] == (
        "artifact-svc-not-started-by-this-scratch-run.invalid"
    )
