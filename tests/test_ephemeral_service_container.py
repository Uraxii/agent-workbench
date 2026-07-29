"""Container-backed tier for scripts/ephemeral-service.py: the unit suite
never starts a container, so real defects (a broken `podman-compose ps
<service>` call, the docker-compose.ephemeral.yml override losing the
merge, a leaked container/pod/network/image tag on teardown) could each
slip past a suite that stubs `subprocess.run` wholesale (see
tests/test_ephemeral_service.py's `_stub_compose`).

kb-svc ONLY -- its build context (`./scripts`) is fast. bd-svc/artifact-svc
are deliberately out of scope here: artifact-svc alone can take up to 900s
to build cold (tests/test_deploy_smoke.py), which does not belong in a
tier meant to run by default on every `pytest tests/`.

Reuses scripts/ephemeral-service.py's own machinery end to end
(`ephemeral_service.cmd_ephemeral_service`, build+up+health-wait+teardown-
in-`finally`) rather than reimplementing any of it -- every real container
this module brings up is created and torn down entirely through that
existing code path.

Marked `container` (see pytest.ini) so `-m "not container"` opts out.
Skips cleanly, never fails and never silently passes, when podman or
podman-compose is absent (a fresh clone with no runtime must still see a
green suite).
"""
from __future__ import annotations

import argparse
import importlib.util
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
_SCRIPT_PATH = _SCRIPTS_DIR / "ephemeral-service.py"


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

pytestmark = pytest.mark.container

# The probe script below is a HOST process: it is what
# ephemeral_service.cmd_ephemeral_service runs as the WRAPPED COMMAND
# (`subprocess.run(command, env=env, ...)`, on the host), not code
# executing inside the container. It talks to the container only the way
# any host process would -- through the podman CLI and the container's
# published port -- so it can inspect the running container while it is
# still up and before ephemeral-service's own teardown runs. Placeholders
# are substituted with plain str.replace (never a compose ${VAR}-style
# hole), same convention as docker-compose.ephemeral.yml's own
# __AW_EPHEMERAL__ substitution. Loads scripts/ephemeral-service.py via
# importlib (not a plain `import` statement): the hyphenated filename is
# not a valid Python identifier.
_PROBE_SRC = '''
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ephemeral_service_under_test", Path("__SCRIPTS_DIR__") / "ephemeral-service.py"
)
ephemeral_service = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ephemeral_service
_spec.loader.exec_module(ephemeral_service)

SPEC = ephemeral_service.SERVICES["kb"]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


# Filters on BOTH labels, same as ephemeral_service._print_image_identity
# does -- a service-only filter would also match a live kb-svc container
# running under a different compose project.
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

identity = ephemeral_service._print_image_identity(project, SPEC)

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
    """What one real kb-svc ephemeral-service bring-up reported about
    itself.

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


def _run_kb_ephemeral_probe(
    tmp_path_factory: pytest.TempPathFactory,
) -> ProbeResult:
    """Bring up ONE real kb-svc ephemeral-service container through
    ephemeral_service.py's own `cmd_ephemeral_service` (build+health-wait,
    teardown in its own `finally`), run the probe script above as the
    wrapped command (a HOST process, see the module comment above), and
    return what it captured. Shared by every test below that needs a real
    bring-up.
    """
    work = tmp_path_factory.mktemp("ephemeral-container")
    result_file = work / "result.json"
    probe = work / "probe.py"

    # cmd_ephemeral_service names its own compose project via
    # `uuid.uuid4()` right before bringing the container up. Pin that
    # value here and force ephemeral_service's uuid4 to return it, so the
    # probe's own filter (above) can target this run's project
    # specifically, same label pair
    # ephemeral_service._print_image_identity itself filters on.
    project_uuid = uuid.uuid4()
    project = f"aw-ephemeral-{project_uuid.hex[:10]}"
    probe.write_text(
        _PROBE_SRC
        .replace("__SCRIPTS_DIR__", str(_SCRIPTS_DIR))
        .replace("__RESULT_FILE__", str(result_file))
        .replace("__PROJECT__", project)
    )

    args = argparse.Namespace(
        service="kb", command=[sys.executable, str(probe)],
    )
    real_uuid4 = ephemeral_service.uuid.uuid4
    ephemeral_service.uuid.uuid4 = lambda: project_uuid
    try:
        returncode = ephemeral_service.cmd_ephemeral_service(args)
    finally:
        ephemeral_service.uuid.uuid4 = real_uuid4
    assert returncode == 0, (
        "probe script (a host process talking to the container over its "
        "published port) failed"
    )

    return ProbeResult(**json.loads(result_file.read_text()))


@pytest.fixture(scope="module")
def kb_ephemeral_probe(tmp_path_factory: pytest.TempPathFactory) -> ProbeResult:
    """The tier's one shared bring-up."""
    _require_container_runtime()
    return _run_kb_ephemeral_probe(tmp_path_factory)


def test_bring_up_reports_image_identity(kb_ephemeral_probe: ProbeResult) -> None:
    """Defect 1: a `podman-compose ps <service>` call (compose rejects a
    service argument on `ps`, exit 2) inside `_print_image_identity` would
    raise, get caught, and silently return None. A real bring-up must
    return a real identity instead of swallowing that failure.
    """
    assert kb_ephemeral_probe.identity is not None


def test_effective_image_is_this_runs_own_tag(
    kb_ephemeral_probe: ProbeResult,
) -> None:
    """Defect 2: swapping the `-f base -f override` order in
    scripts/ephemeral-service.py's `up_cmd` makes the LAST file win the
    merge -- docker-compose.yml's `image: localhost/kb-svc:latest` would
    then beat the override's per-run tag pin. Reads the EFFECTIVE image
    off the actually created container (`podman container inspect`),
    never the override file's text -- a text-match test cannot see this
    class of bug.
    """
    assert kb_ephemeral_probe.effective_image == (
        f"localhost/kb-svc:{kb_ephemeral_probe.project}"
    )


def test_mounts_point_at_ephemeral_tmpdir_never_the_real_vault(
    kb_ephemeral_probe: ProbeResult,
) -> None:
    """Highest-consequence invariant docker-compose.ephemeral.yml's
    `volumes: !override` exists to guarantee: the container's own mounts
    point at the ephemeral run's disposable `aw-ephemeral-*` tmpdir, and
    never at the developer's real `~/.knowledgebase`. Reads `podman
    container inspect --format '{{.Mounts}}'` off the actually created
    container -- the safety half of defect 2 (reasoned-not-executed for
    the unsafe `-f`-swap end-to-end case, see this task's DO NOT
    section).
    """
    assert "aw-ephemeral-" in kb_ephemeral_probe.mounts
    assert ".knowledgebase" not in kb_ephemeral_probe.mounts


def test_teardown_leaves_no_container_pod_network_or_image_tag(
    kb_ephemeral_probe: ProbeResult,
) -> None:
    """By the time this fixture value exists, `cmd_ephemeral_service`'s
    own `finally` has already run. Nothing named after this run's project
    may still exist -- neither the container, nor the pod, nor the
    network podman-compose created for it, nor this run's own per-run
    image tag (`_remove_image`). `down <service>` (an earlier version's
    teardown) only ever removed the named container; the project's own
    pod + bridge network survived every run, accumulating forever. A
    per-run tag left un-removed would do the same to images.
    """
    project = kb_ephemeral_probe.project

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

    images = _podman([
        "podman", "images", "--filter", f"reference=localhost/kb-svc:{project}",
        "--format", "{{.Repository}}:{{.Tag}}",
    ])
    assert images == "", f"leaked image tag(s) for {project}: {images}"
