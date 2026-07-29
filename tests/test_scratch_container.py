"""Container-backed tier for scripts/scratch.py: the ~492-test suite never
starts a container, so real defects (a broken `podman-compose ps
<service>` call, the docker-compose.scratch.yml override losing the merge,
a stale `:scratch` tag surviving a bring-up, leaked pod/network on
teardown) could each slip past a suite that stubs `subprocess.run`
wholesale (see tests/test_scratch.py's `_stub_compose`).

kb-svc ONLY -- its build context (`./scripts`) is fast. bd-svc/artifact-svc
are deliberately out of scope here: artifact-svc alone can take up to 900s
to build cold (tests/test_deploy_smoke.py), which does not belong in a
tier meant to run by default on every `pytest tests/`.

Reuses scripts/scratch.py's own machinery end to end (`scratch.cmd_scratch`,
build+up+health-wait+teardown-in-`finally`) rather than reimplementing any
of it -- every real container this module brings up is created and torn
down entirely through that existing code path.

Marked `container` (see pytest.ini) so `-m "not container"` opts out.
Skips cleanly, never fails and never silently passes, when podman or
podman-compose is absent (a fresh clone with no runtime must still see a
green suite).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import scratch  # noqa: E402

pytestmark = pytest.mark.container

_KB_CONTAINERFILE = _SCRIPTS_DIR / "kb-container" / "Containerfile"
_BUILD_TIMEOUT_SEC = 180.0

# Runs inside the scratch container's OWN process (spawned by
# scratch.cmd_scratch as the wrapped command), not this test process, so it
# can inspect the running container -- and, for the tag-vs-container check,
# briefly retag `localhost/kb-svc:scratch` -- while the container is still
# up and before scratch's own teardown runs. Placeholders are substituted
# with plain str.replace (never a compose ${VAR}-style hole), same
# convention as docker-compose.scratch.yml's own __AW_SCRATCH__
# substitution.
_PROBE_SRC = '''
import json
import subprocess
import sys

sys.path.insert(0, "__SCRIPTS_DIR__")
import scratch  # noqa: E402

SPEC = scratch.SERVICES["kb"]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


# Filters on BOTH labels, same as scratch._print_image_identity does --
# a service-only filter would also match a live kb-svc container running
# under a different compose project.
ps = _run([
    "podman", "ps", "-q", "--filter",
    "label=io.podman.compose.service=" + SPEC.compose_name,
    "--filter",
    "label=io.podman.compose.project=__PROJECT__",
])
container = ps.stdout.split()[-1]

project = _run([
    "podman", "container", "inspect", container, "--format",
    \'{{index .Config.Labels "io.podman.compose.project"}}\',
]).stdout.strip()

ground_truth_id = _run([
    "podman", "container", "inspect", container, "--format", "{{.Image}}",
]).stdout.strip()

effective_image = _run([
    "podman", "container", "inspect", container, "--format", "{{.ImageName}}",
]).stdout.strip()

mounts = _run([
    "podman", "container", "inspect", container, "--format", "{{.Mounts}}",
]).stdout.strip()

# Decoy retag target for the tag-vs-container check: the build's own
# immediate parent image, guaranteed already cached locally by the build
# that just ran -- never pulled or run, only used as a harmless alias.
with open("__CONTAINERFILE__") as fh:
    containerfile_lines = fh.read().splitlines()
base_ref = [
    line.split(maxsplit=1)[1] for line in containerfile_lines
    if line.startswith("FROM")
][0]
_run(["podman", "tag", base_ref, "localhost/kb-svc:scratch"])
try:
    identity = scratch._print_image_identity(project, SPEC)
finally:
    _run(["podman", "tag", ground_truth_id, "localhost/kb-svc:scratch"])

with open("__RESULT_FILE__", "w") as fh:
    json.dump({
        "project": project,
        "ground_truth_id": ground_truth_id,
        "effective_image": effective_image,
        "mounts": mounts,
        "identity": identity,
    }, fh)
'''


class ProbeResult(NamedTuple):
    """What one real kb-svc scratch bring-up reported about itself.

    `identity` is a JSON round-trip of `_print_image_identity`'s
    (image_id, created) return -- a 2-item list, not a tuple, once it
    comes back through `json.loads`.
    """

    project: str
    ground_truth_id: str
    effective_image: str
    mounts: str
    identity: list[str] | None


def _require_container_runtime() -> None:
    """Skip cleanly (never pass, never fail) when the runtime is absent."""
    if shutil.which("podman-compose") is None or shutil.which("podman") is None:
        pytest.skip(
            "container tier skipped: podman/podman-compose not on PATH"
        )


def _podman(cmd: list[str], timeout: float = 60.0) -> str:
    """Run a podman/podman-compose command, fail the test loudly with
    stderr on error, return stripped stdout."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def _run_kb_scratch_probe(
    tmp_path_factory: pytest.TempPathFactory, build: bool,
) -> ProbeResult:
    """Bring up ONE real kb-svc scratch container through scratch.py's own
    `cmd_scratch` (health-wait, teardown in its own `finally`), run the
    probe script above as the wrapped command, and return what it
    captured. Shared by every test below that needs a real bring-up --
    each call is its own build+up+down, never hand-rolled.
    """
    work = tmp_path_factory.mktemp("scratch-container")
    result_file = work / "result.json"
    probe = work / "probe.py"

    # cmd_scratch names its own compose project via `uuid.uuid4()` right
    # before bringing the container up. Pin that value here and force
    # scratch's uuid4 to return it, so the probe's own filter (above) can
    # target this run's project specifically, same label pair
    # scratch._print_image_identity itself filters on.
    project_uuid = uuid.uuid4()
    project = f"aw-scratch-{project_uuid.hex[:10]}"
    probe.write_text(
        _PROBE_SRC
        .replace("__SCRIPTS_DIR__", str(_SCRIPTS_DIR))
        .replace("__CONTAINERFILE__", str(_KB_CONTAINERFILE))
        .replace("__RESULT_FILE__", str(result_file))
        .replace("__PROJECT__", project)
    )

    args = argparse.Namespace(
        service="kb", command=[sys.executable, str(probe)], build=build,
    )
    real_uuid4 = scratch.uuid.uuid4
    scratch.uuid.uuid4 = lambda: project_uuid
    try:
        returncode = scratch.cmd_scratch(args)
    finally:
        scratch.uuid.uuid4 = real_uuid4
    assert returncode == 0, "probe script failed inside the scratch container"

    return ProbeResult(**json.loads(result_file.read_text()))


@pytest.fixture(scope="module")
def kb_scratch_probe(tmp_path_factory: pytest.TempPathFactory) -> ProbeResult:
    """The tier's one shared, default (`build=True`) bring-up."""
    _require_container_runtime()
    return _run_kb_scratch_probe(tmp_path_factory, build=True)


def test_bring_up_reports_image_identity(kb_scratch_probe: ProbeResult) -> None:
    """Defect 1: a `podman-compose ps <service>` call (compose rejects a
    service argument on `ps`, exit 2) inside `_print_image_identity` would
    raise, get caught, and silently return None. A real bring-up must
    return a real identity instead of swallowing that failure.
    """
    assert kb_scratch_probe.identity is not None


def test_effective_image_is_the_scratch_tag(kb_scratch_probe: ProbeResult) -> None:
    """Defect 2: swapping the `-f base -f override` order in
    scripts/scratch.py's `up_cmd` makes the LAST file win the merge --
    docker-compose.yml's `image: localhost/kb-svc:latest` would then beat
    the override's `:scratch` pin. Reads the EFFECTIVE image off the
    actually created container (`podman container inspect`), never the
    override file's text -- a text-match test cannot see this class of bug.
    """
    assert kb_scratch_probe.effective_image == "localhost/kb-svc:scratch"


def test_mounts_point_at_scratch_tmpdir_never_the_real_vault(
    kb_scratch_probe: ProbeResult,
) -> None:
    """Highest-consequence invariant docker-compose.scratch.yml's
    `volumes: !override` exists to guarantee: the container's own mounts
    point at scratch's disposable `aw-scratch-*` tmpdir, and never at the
    developer's real `~/.knowledgebase`. Reads `podman container inspect
    --format '{{.Mounts}}'` off the actually created container -- the
    safety half of defect 2 (reasoned-not-executed for the unsafe
    `-f`-swap end-to-end case, see this task's DO NOT section).
    """
    assert "aw-scratch-" in kb_scratch_probe.mounts
    assert ".knowledgebase" not in kb_scratch_probe.mounts


def test_identity_matches_the_container_not_a_retagged_tag(
    kb_scratch_probe: ProbeResult,
) -> None:
    """While the container is running, the probe retags
    `localhost/kb-svc:scratch` to a harmless decoy and restores it
    afterwards. `_print_image_identity` must report the id the CONTAINER
    is actually running, not whatever the tag happens to point at right
    now -- exactly the race its own container-inspect (never tag-inspect)
    design exists to defend against.
    """
    assert kb_scratch_probe.identity is not None, (
        "no identity was reported at all -- see "
        "test_bring_up_reports_image_identity for that failure mode"
    )
    identity_id, _created = kb_scratch_probe.identity
    assert identity_id == kb_scratch_probe.ground_truth_id


def test_teardown_leaves_no_container_pod_or_network(
    kb_scratch_probe: ProbeResult,
) -> None:
    """By the time this fixture value exists, `cmd_scratch`'s own
    `finally` has already run. Nothing named after this run's project may
    still exist -- neither the container, nor the pod, nor the network
    podman-compose created for it. `down <service>` (scratch.py's old
    teardown) only ever removed the named container; the project's own
    pod + bridge network survived every run, accumulating forever.
    """
    project = kb_scratch_probe.project

    containers = _podman([
        "podman", "ps", "-a", "--filter",
        f"label=io.podman.compose.project={project}",
        "--format", "{{.Names}}",
    ])
    assert containers == "", f"leaked container(s) for {project}: {containers}"

    pods = _podman([
        "podman", "pod", "ps", "--filter", f"name={project}",
        "--format", "{{.Name}}",
    ])
    assert pods == "", f"leaked pod(s) for {project}: {pods}"

    networks = _podman([
        "podman", "network", "ls", "--filter", f"name={project}",
        "--format", "{{.Name}}",
    ])
    assert networks == "", f"leaked network(s) for {project}: {networks}"


def test_no_build_reuses_the_current_tag_without_rebuilding(
    kb_scratch_probe: ProbeResult, tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Exercises `--no-build` (`build=False`), never run by this tier
    before this fix. The shared fixture above already left
    `localhost/kb-svc:scratch` pointing at a known-good, current-source
    build -- a second bring-up with `build=False` must run against that
    SAME image; `--no-build` skipping the rebuild is documented, intended
    behaviour (scripts/scratch.py's own `--no-build` help text), not
    itself a defect. The defect-3 catch below is the `build=True` path.
    """
    result = _run_kb_scratch_probe(tmp_path_factory, build=False)
    assert result.ground_truth_id == kb_scratch_probe.ground_truth_id


def test_default_build_path_does_not_leave_the_stale_tag_running(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Defect 3, END TO END OUTCOME ONLY: a `:scratch` tag left over from a
    previous, DIFFERENT build (imagine one from an earlier branch) is not
    what the default `cmd_scratch(build=True)` bring-up ends up running.

    Does NOT exercise the freshness check
    (`_assert_container_runs_the_build`) in isolation, and must not be read
    as covering it: `_build` alone already rebuilds from the working tree
    on every run, so the running id changing here would hold even with
    that check reduced to a no-op. See test_scratch.py's
    test_freshness_check_rejects_a_mismatched_running_image /
    test_freshness_check_rejects_an_unverifiable_identity for the actual
    unit coverage of the check itself.

    Builds a "stale" image from a one-line, harmless, marker-mutated
    TEMP COPY of scripts/ (never the tracked kb-svc.py in place -- a
    SIGKILL/timeout/crash mid-build must never leave a tracked file
    dirty), tags it `:scratch` as if it were a leftover from a previous
    run. Records that stale image's own id, then asserts the default
    build-on bring-up's running container is a DIFFERENT id -- proof
    enough that the stale tag did not survive, with no second build to
    compare against and no assumption that a same-content rebuild is
    id-stable.

    An earlier version of this test compared ids against a `--no-cache`
    "reference" build of current source instead, and was flaky: two
    `--no-cache` builds of identical source produce DIFFERENT image ids
    for this repo's kb-container, because the Containerfile's `pip
    install lxml readability-lxml` is unpinned and non-deterministic at
    the layer level.
    """
    _require_container_runtime()

    stale_scripts = tmp_path_factory.mktemp("stale-scripts") / "scripts"
    shutil.copytree(_SCRIPTS_DIR, stale_scripts)
    marker = f"\n# scratch-container-tier stale marker {uuid.uuid4().hex}\n"
    stale_kb_svc = stale_scripts / "kb-svc.py"
    stale_kb_svc.write_text(
        stale_kb_svc.read_text(encoding="utf-8") + marker, encoding="utf-8"
    )

    _podman(
        [
            "podman", "build", "-t", "localhost/kb-svc:scratch",
            "-f", str(stale_scripts / "kb-container" / "Containerfile"),
            str(stale_scripts),
        ],
        timeout=_BUILD_TIMEOUT_SEC,
    )

    stale_id = _podman(
        [
            "podman", "image", "inspect", "localhost/kb-svc:scratch",
            "--format", "{{.Id}}",
        ]
    )

    result = _run_kb_scratch_probe(tmp_path_factory, build=True)
    assert result.ground_truth_id != stale_id, (
        "a stale :scratch tag survived the default build-on path -- "
        f"still running the stale image {stale_id}"
    )
