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
# A file the Containerfile actually COPYs -- the defect-3 check appends a
# one-line marker to it, builds, then restores the ORIGINAL content before
# this module ever returns control to pytest, success or failure.
_KB_MARKER_FILE = _SCRIPTS_DIR / "kb-svc.py"
_REFERENCE_TAG = "localhost/kb-svc:container-tier-reference"
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


ps = _run([
    "podman", "ps", "-q", "--filter",
    "label=io.podman.compose.service=" + SPEC.compose_name,
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

# Decoy retag target for the tag-vs-container check: the build's own
# immediate parent image, guaranteed already cached locally by the build
# that just ran -- never pulled or run, only used as a harmless alias.
base_ref = [
    line.split(maxsplit=1)[1] for line in
    open("__CONTAINERFILE__").read().splitlines()
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
    probe.write_text(
        _PROBE_SRC
        .replace("__SCRIPTS_DIR__", str(_SCRIPTS_DIR))
        .replace("__CONTAINERFILE__", str(_KB_CONTAINERFILE))
        .replace("__RESULT_FILE__", str(result_file))
    )

    args = argparse.Namespace(
        service="kb", command=[sys.executable, str(probe)], build=build,
    )
    returncode = scratch.cmd_scratch(args)
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


def test_default_build_rejects_a_stale_prebuilt_tag(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Defect 3, for real: a `:scratch` tag left over from a previous,
    DIFFERENT build (imagine one from an earlier branch) must not survive
    a fresh `cmd_scratch(build=True)` run -- the default, build-on-every-
    run path this tier actually exercises by default. `--no-build`
    knowingly waives this (see the test above and scripts/scratch.py's own
    docstring); `build=True` must not.

    Builds a "stale" image from a one-line, harmless, marker-mutated copy
    of kb-svc.py -- written and reverted here, in this function, before
    it ever returns control, success or failure -- and tags it `:scratch`
    as if it were a leftover from a previous run. Compares the ACTUAL
    bring-up's image id against a `--no-cache`-forced reference build of
    the real, current source (tagged separately, never `:scratch` itself,
    so it can never be confused with the stale tag under test).

    Id equality, not a `.Created` timestamp, is the signal: verified
    empirically against this repo's own kb-container build that a
    same-content rebuild (no `--no-cache`) reuses the EXACT previous
    image, `.Created` included, so a ".Created must be >= now" check
    would misfire on every ordinary cache hit -- podman-compose's own
    `build` is exactly such a cache-hit rebuild whenever the source is
    unchanged, which is the normal case for every OTHER scratch run.
    """
    _require_container_runtime()

    original = _KB_MARKER_FILE.read_text(encoding="utf-8")
    marker = f"\n# scratch-container-tier stale marker {uuid.uuid4().hex}\n"
    try:
        _KB_MARKER_FILE.write_text(original + marker, encoding="utf-8")
        _podman(
            [
                "podman", "build", "-t", "localhost/kb-svc:scratch",
                "-f", str(_KB_CONTAINERFILE), str(_SCRIPTS_DIR),
            ],
            timeout=_BUILD_TIMEOUT_SEC,
        )
    finally:
        _KB_MARKER_FILE.write_text(original, encoding="utf-8")

    try:
        _podman(
            [
                "podman", "build", "--no-cache", "-t", _REFERENCE_TAG,
                "-f", str(_KB_CONTAINERFILE), str(_SCRIPTS_DIR),
            ],
            timeout=_BUILD_TIMEOUT_SEC,
        )
        reference_id = _podman(
            ["podman", "image", "inspect", _REFERENCE_TAG, "--format", "{{.Id}}"]
        )

        result = _run_kb_scratch_probe(tmp_path_factory, build=True)
        assert result.ground_truth_id == reference_id, (
            "a stale :scratch tag survived the default build-on path -- "
            f"running {result.ground_truth_id}, expected the freshly "
            f"rebuilt {reference_id}"
        )
    finally:
        subprocess.run(
            ["podman", "rmi", "-f", _REFERENCE_TAG], capture_output=True,
        )
