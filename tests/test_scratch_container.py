"""Container-backed tier for scripts/scratch.py: the ~492-test suite never
starts a container, so three real defects (a broken `podman-compose ps
<service>` call, the docker-compose.scratch.yml override losing the merge,
a stale image passing health silently) could each slip past a suite that
stubs `subprocess.run` wholesale (see tests/test_scratch.py's `_stub_compose`).

kb-svc ONLY -- its build context (`./scripts`) is fast. bd-svc/artifact-svc
are deliberately out of scope here: artifact-svc alone can take up to 900s
to build cold (tests/test_deploy_smoke.py), which does not belong in a
tier meant to run by default on every `pytest tests/`.

Reuses scripts/scratch.py's own machinery end to end (`scratch.cmd_scratch`,
build+up+health-wait+teardown-in-`finally`) rather than reimplementing any
of it -- the ONE real container this module brings up is created and torn
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
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import scratch  # noqa: E402

pytestmark = pytest.mark.container

# Runs inside the scratch container's OWN process (spawned by
# scratch.cmd_scratch as the wrapped command), not this test process, so it
# can inspect the running container -- and, for the defect-3 check, briefly
# retag `localhost/kb-svc:scratch` -- while the container is still up and
# before scratch's own teardown runs. Placeholders are substituted with
# plain str.replace (never a compose ${VAR}-style hole), same convention as
# docker-compose.scratch.yml's own __AW_SCRATCH__ substitution.
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

# Decoy retag target for the defect-3 check: the build's own immediate
# parent image, guaranteed already cached locally by the build that just
# ran -- never pulled or run, only used as a harmless alias.
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
        "ground_truth_id": ground_truth_id,
        "effective_image": effective_image,
        "identity": identity,
    }, fh)
'''


def _require_container_runtime() -> None:
    """Skip cleanly (never pass, never fail) when the runtime is absent."""
    if shutil.which("podman-compose") is None or shutil.which("podman") is None:
        pytest.skip(
            "container tier skipped: podman/podman-compose not on PATH"
        )


@pytest.fixture(scope="module")
def kb_scratch_probe(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Bring up ONE real kb-svc scratch container through scratch.py's own
    `cmd_scratch` (build+up+health-wait, teardown in its own `finally`),
    run the probe script above as the wrapped command, and return what it
    captured. Shared by all three defect checks below -- one real build
    and bring-up, not three.
    """
    _require_container_runtime()

    work = tmp_path_factory.mktemp("scratch-container")
    result_file = work / "result.json"
    probe = work / "probe.py"
    kb_containerfile = _SCRIPTS_DIR / "kb-container" / "Containerfile"
    probe.write_text(
        _PROBE_SRC
        .replace("__SCRIPTS_DIR__", str(_SCRIPTS_DIR))
        .replace("__CONTAINERFILE__", str(kb_containerfile))
        .replace("__RESULT_FILE__", str(result_file))
    )

    args = argparse.Namespace(
        service="kb", command=[sys.executable, str(probe)], build=True,
    )
    returncode = scratch.cmd_scratch(args)
    assert returncode == 0, "probe script failed inside the scratch container"

    return json.loads(result_file.read_text())


def test_bring_up_reports_image_identity(kb_scratch_probe: dict) -> None:
    """Defect 1: a `podman-compose ps <service>` call (compose rejects a
    service argument on `ps`, exit 2) inside `_print_image_identity` would
    raise, get caught, and silently return None. A real bring-up must
    return a real identity instead of swallowing that failure.
    """
    assert kb_scratch_probe["identity"] is not None


def test_effective_image_is_the_scratch_tag(kb_scratch_probe: dict) -> None:
    """Defect 2: swapping the `-f base -f override` order in
    scripts/scratch.py's `up_cmd` makes the LAST file win the merge --
    docker-compose.yml's `image: localhost/kb-svc:latest` would then beat
    the override's `:scratch` pin. Reads the EFFECTIVE image off the
    actually created container (`podman container inspect`), never the
    override file's text -- a text-match test cannot see this class of bug.
    """
    assert kb_scratch_probe["effective_image"] == "localhost/kb-svc:scratch"


def test_identity_matches_the_container_not_a_retagged_tag(
    kb_scratch_probe: dict,
) -> None:
    """Defect 3: while the container is running, the probe retags
    `localhost/kb-svc:scratch` to a harmless decoy and restores it
    afterwards. `_print_image_identity` must report the id the CONTAINER
    is actually running, not whatever the tag happens to point at right
    now -- exactly the race its own container-inspect (never tag-inspect)
    design exists to defend against, and the "nothing asserts the
    container is running the code that was just built" gap named in the
    task.
    """
    identity_id, _created = kb_scratch_probe["identity"]
    assert identity_id == kb_scratch_probe["ground_truth_id"]
