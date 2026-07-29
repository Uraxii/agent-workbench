"""Tests for scripts/ephemeral-service.py -- the repo dev/test harness's
pure guard logic -- no podman needed.

`ephemeral-service` brings up a throwaway service container; the
container-boundary half of that is exercised manually (see the task's
verification section), never here, so this file never touches ports
9099/9100/9101 and never shells out to podman. What IS pure logic, and
must fail loudly rather than silently falling back to the live stack, is
covered here:

- an unknown service name is rejected by argparse before
  ephemeral-service.py runs
- a repo root with no docker-compose.yml raises, naming the missing files,
  instead of defaulting to live ports
- an ephemeral-service invocation with no wrapped command raises instead
  of no-op'ing
- the two non-target services are pointed at a `.invalid` sentinel host,
  never the live defaults
- `_split_argv` splits ephemeral-service's own flags from the wrapped
  command on the FIRST `--` only, regardless of flag position or a `--`
  inside the wrapped command itself
- every run builds this run's own image -- there is no flag to skip it
- the image-identity line lands on stderr, never stdout
- `_assert_container_runs_the_build` (the freshness check) actually
  rejects a mismatched or unverifiable running image, in isolation, no
  container needed -- a no-op, or a self-vs-self comparison, of this
  function must not leave the suite green
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "ephemeral-service.py"
)


def _load_ephemeral_service():
    spec = importlib.util.spec_from_file_location(
        "ephemeral_service_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ephemeral_service = _load_ephemeral_service()


def test_overlay_pins_every_service_to_the_ephemeral_tag_placeholder() -> None:
    """The REAL docker-compose.ephemeral.yml must override `image:` to the
    `__AW_EPHEMERAL_TAG__` placeholder for every service ephemeral-service
    can run -- `cmd_ephemeral_service` substitutes it with this run's own
    unique tag before handing the file to podman-compose.

    This is the whole of defect 1's fix: without the override the overlay
    inherits `image: localhost/kb-svc:latest` from docker-compose.yml and
    an ephemeral-service run exercises whatever the live stack's tag
    points at. Every other test stubs compose out and never reads this
    file, so nothing else here would notice the override being removed.
    """
    overlay = (
        Path(__file__).resolve().parent.parent / "docker-compose.ephemeral.yml"
    ).read_text(encoding="utf-8")

    image_lines = [
        line.strip() for line in overlay.splitlines()
        if line.strip().startswith("image:")
    ]

    for spec in ephemeral_service.SERVICES.values():
        expected = f"image: localhost/{spec.image_repo}:" \
            f"{ephemeral_service.EPHEMERAL_TAG_PLACEHOLDER}"
        assert expected in image_lines, (
            f"{spec.compose_name} is not pinned to the ephemeral tag "
            "placeholder"
        )
    # Prose about :latest is fine; an actual `image:` naming it is the defect.
    assert not [line for line in image_lines if ":latest" in line]
    assert len(image_lines) == len(ephemeral_service.SERVICES)


def _stub_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[list[str], dict[str, object]]]:
    """Fake every subprocess.run call ephemeral-service.py would make
    against podman-compose/podman, recording (cmd, kwargs) pairs. No
    podman needed: `port`, `ps -q`, the two `inspect` calls, and `rmi` get
    canned stdout, anything else (build/up/down/the wrapped command) just
    succeeds.

    The image-identity path is modelled as the three real calls it makes:
    `ps -q` for the container id, `container inspect` for the image the
    container actually runs, `image inspect` for that image's timestamp.
    A fourth, `image inspect <tag> --format {{.Id}}`, models
    `_just_built_image_id`'s post-build lookup -- same id as the
    container's own image, so the freshness check
    (`_assert_container_runs_the_build`), which now runs on every
    bring-up, sees a match.
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
                returncode=0,
                stdout="deadbeef localhost/kb-svc:aw-ephemeral-cafef00d00\n",
            )
        if "inspect" in cmd and "{{.Id}}" in cmd:
            return SimpleNamespace(returncode=0, stdout="deadbeef\n")
        if "inspect" in cmd:
            return SimpleNamespace(returncode=0, stdout="2026-01-01T00:00:00Z\n")
        return SimpleNamespace(returncode=0, stdout="")

    template = tmp_path / "docker-compose.ephemeral.yml"
    template.write_text("services: {}\n")  # placeholder has none to replace
    base = tmp_path / "docker-compose.yml"

    monkeypatch.setattr(ephemeral_service.subprocess, "run", fake_run)
    monkeypatch.setattr(ephemeral_service, "_require_podman_compose", lambda: None)
    monkeypatch.setattr(ephemeral_service, "_compose_files", lambda: (base, template))
    monkeypatch.setattr(ephemeral_service, "_wait_healthy", lambda *a, **kw: None)
    return calls


def test_unknown_service_name_rejected() -> None:
    """`ephemeral-service.py bogus -- ...` fails loudly and non-zero,
    never runs."""
    with pytest.raises(SystemExit) as exc_info:
        ephemeral_service.build_parser().parse_args(["bogus"])
    assert exc_info.value.code != 0


def test_missing_compose_file_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """No docker-compose.yml at the repo root -> loud RuntimeError.

    Never falls through to the live-stack default ports -- this must raise
    before any container is ever considered.
    """
    monkeypatch.setattr(ephemeral_service, "REPO_ROOT", Path("/nonexistent-aw-root"))
    with pytest.raises(RuntimeError, match="docker-compose"):
        ephemeral_service._compose_files()


def test_empty_command_raises() -> None:
    """`ephemeral-service.py kb --` with nothing after `--` refuses
    instead of no-op'ing.

    Goes through `_split_argv` exactly as `main()` does: handing
    `_command_args` a raw leading `--` is a shape the real entry point can
    no longer produce, and testing it would drift from production.
    """
    _, command = ephemeral_service._split_argv(["kb", "--"])

    with pytest.raises(RuntimeError, match="no command given"):
        ephemeral_service._command_args(command, "kb")


def test_split_argv_wrapped_command() -> None:
    """`kb -- bash -c 'a && b'`: everything after the first `--` is the
    wrapped command, untouched.
    """
    own_argv, command_argv = ephemeral_service._split_argv(
        ["kb", "--", "bash", "-c", "a && b"]
    )
    assert own_argv == ["kb"]
    assert command_argv == ["bash", "-c", "a && b"]


def test_split_argv_flag_before_separator() -> None:
    """`kb -h -- true`: ephemeral-service's own flag stays out of the
    wrapped command regardless of where it sits relative to `--`.
    """
    own_argv, command_argv = ephemeral_service._split_argv(
        ["kb", "-h", "--", "true"]
    )
    assert own_argv == ["kb", "-h"]
    assert command_argv == ["true"]


def test_split_argv_preserves_inner_separator() -> None:
    """Only the FIRST `--` is ephemeral-service's own separator -- a `--`
    inside the wrapped command (e.g. `kb query --`) must reach the command
    intact.
    """
    own_argv, command_argv = ephemeral_service._split_argv(
        ["kb", "--", "kb", "query", "--", "foo"]
    )
    assert own_argv == ["kb"]
    assert command_argv == ["kb", "query", "--", "foo"]


def test_split_argv_missing_command_fails_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`ephemeral-service.py kb` with no `--` at all -> loud, rc=1, never
    a no-op.

    No stubbing needed: `_command_args` raises before ephemeral-service
    ever touches podman-compose.
    """
    assert ephemeral_service.main(["kb"]) == 1
    assert "no command given" in capsys.readouterr().err


def test_podman_compose_chatter_stays_off_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """podman-compose's own `up`/`down` output must never share stdout
    with the wrapped command -- an agent piping ephemeral-service's stdout
    to `jq` would otherwise see container IDs and project lines ahead of
    the JSON.

    Asserts `up` and `down` redirect stdout away from the process's own
    stdout, the `port` lookup (already capture_output=True) doesn't leak
    either, and the wrapped command's own subprocess.run call is untouched
    -- no `stdout` kwarg at all, so it inherits the real stdout.
    """
    calls = _stub_compose(tmp_path, monkeypatch)

    args = argparse.Namespace(service="kb", command=["echo", "hi"])
    returncode = ephemeral_service.cmd_ephemeral_service(args)
    assert returncode == 0

    def find(token: str) -> dict[str, object]:
        [kwargs] = [kw for cmd, kw in calls if token in cmd]
        return kwargs

    assert find("up")["stdout"] is sys.stderr
    assert find("down")["stdout"] is sys.stderr
    # port lookup already uses capture_output=True; must not ALSO leak
    # to the process's own stdout via an explicit stdout= kwarg.
    assert "stdout" not in find("port")

    # up, port, inspect, [wrapped], down, rmi -- the wrapped command is
    # the third call from the end.
    wrapped_cmd, wrapped_kwargs = calls[-3]
    assert wrapped_cmd == ["echo", "hi"]
    assert "stdout" not in wrapped_kwargs


def test_build_always_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`podman-compose ... build <svc>` always runs before `up` -- there
    is no flag to skip it. A per-run image tag means there is nothing to
    reuse: skipping the build would only leave the container with no
    image to run. (Replaces the old `--no-build`-flag pair of tests: that
    flag, and the shared-tag staleness hazard it existed to opt out of,
    were deleted -- a per-run tag can never be "left over from an earlier
    branch" because no run ever reuses another run's tag.)
    """
    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"])
    ephemeral_service.cmd_ephemeral_service(args)

    build_calls = [cmd for cmd, _ in calls if "build" in cmd]
    assert len(build_calls) == 1
    assert build_calls[0][-2:] == ["build", "kb-svc"]


def test_teardown_removes_this_runs_own_image_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-run tag is a per-run resource: `cmd_ephemeral_service`'s
    `finally` must remove it (`podman rmi -f`) alongside the container and
    temp dir, or every invocation leaks one image onto the host.
    """
    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"])
    ephemeral_service.cmd_ephemeral_service(args)

    rmi_calls = [cmd for cmd, _ in calls if cmd[:2] == ["podman", "rmi"]]
    assert len(rmi_calls) == 1
    assert rmi_calls[0][-1].startswith("localhost/kb-svc:aw-ephemeral-")


def test_image_identity_printed_to_stderr_not_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The image tripwire line must land on stderr -- the wrapped
    command's stdout is the only thing ephemeral-service's own stdout may
    carry.
    """
    _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"])
    ephemeral_service.cmd_ephemeral_service(args)

    captured = capsys.readouterr()
    assert "localhost/kb-svc:aw-ephemeral-cafef00d00" in captured.err
    assert "id deadbeef" in captured.err
    assert "localhost/kb-svc:aw-ephemeral-cafef00d00" not in captured.out


def test_image_identity_inspects_the_container_not_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tripwire must read the CREATED CONTAINER's image, never a tag
    string.

    Reading the container's own `.Image` is the only answer that cannot
    disagree with what is actually serving requests -- independent of
    whether anything else on the host ever repointed the tag (e.g. a
    human retagging it by hand for debugging). This still holds even
    though each run's tag is now unique to it and nothing else should
    ordinarily touch it.
    """
    calls = _stub_compose(tmp_path, monkeypatch)
    args = argparse.Namespace(service="kb", command=["true"])
    ephemeral_service.cmd_ephemeral_service(args)

    inspects = [cmd for cmd, _ in calls if "inspect" in cmd]
    assert any(cmd[:3] == ["podman", "container", "inspect"] for cmd in inspects), (
        "never inspected the running container"
    )
    # `_print_image_identity`'s own image inspect (--format {{.Created}})
    # is the tripwire under test: it must read the image BY ID, from the
    # container's own .Image, never by tag. A SEPARATE image inspect
    # (--format {{.Id}}) legitimately reads the freshly built tag right
    # after `_build`, in `_just_built_image_id` -- that one is by design
    # (it is how the id to compare against is learned in the first place)
    # and is not this test's concern.
    identity_inspects = [
        cmd for cmd in inspects
        if cmd[:3] == ["podman", "image", "inspect"] and "{{.Created}}" in cmd
    ]
    assert identity_inspects, "never inspected the identity image by id"
    for cmd in identity_inspects:
        assert cmd[3] == "deadbeef", (
            f"image inspected by tag, not by the container's image id: {cmd}"
        )


def test_freshness_check_rejects_a_mismatched_running_image() -> None:
    """`_assert_container_runs_the_build` must reject a bring-up whose
    container is running a DIFFERENT image than the one `_build` just
    produced -- the pure-unit proof that a no-op, or a "compare the
    running id against itself" rewrite, of this function cannot pass
    unnoticed. This test does not depend on `_build` at all.
    """
    with pytest.raises(RuntimeError, match="refusing a stale image"):
        ephemeral_service._assert_container_runs_the_build(
            ("running-id", "2026-01-01T00:00:00Z"), "built-id",
            ephemeral_service.SERVICES["kb"],
        )


def test_freshness_check_rejects_an_unverifiable_identity() -> None:
    """`identity=None` (the container inspection itself failed, see
    `_print_image_identity`'s own swallowed `CalledProcessError`) must
    also raise instead of silently passing.
    """
    with pytest.raises(RuntimeError, match="could not verify"):
        ephemeral_service._assert_container_runs_the_build(
            None, "built-id", ephemeral_service.SERVICES["kb"],
        )


def test_freshness_check_passes_a_matching_running_image() -> None:
    """Sanity companion to the two rejections above: identical ids must
    not raise -- the normal, healthy bring-up.
    """
    ephemeral_service._assert_container_runs_the_build(
        ("same-id", "2026-01-01T00:00:00Z"), "same-id",
        ephemeral_service.SERVICES["kb"],
    )


def test_command_args_keeps_a_caller_supplied_separator() -> None:
    """`ephemeral-service.py kb -- -- foo` must pass `--` through to the
    wrapped command. `_split_argv` already ate the real separator, so a
    second one is the caller's own argument and stripping it silently
    drops a token.
    """
    _, command = ephemeral_service._split_argv(["kb", "--", "--", "foo"])

    assert ephemeral_service._command_args(command, "kb") == ["--", "foo"]


def test_non_target_services_get_sentinel_host() -> None:
    """`ephemeral-service kb` must not leave BD_SVC_HOST/ARTIFACT_SVC_HOST
    at their live defaults -- a chained call to either must fail loudly,
    never silently reach the real service.
    """
    env = ephemeral_service._ephemeral_env(
        ephemeral_service.SERVICES["kb"], 12345, "kb"
    )

    assert env["KB_SVC_HOST"] == "127.0.0.1"
    assert env["KB_SVC_PORT"] == "12345"
    assert env["BD_SVC_HOST"] == (
        "bd-svc-not-started-by-this-ephemeral-service-run.invalid"
    )
    assert env["ARTIFACT_SVC_HOST"] == (
        "artifact-svc-not-started-by-this-ephemeral-service-run.invalid"
    )
