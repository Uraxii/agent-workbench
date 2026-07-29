# Contributing

This file carries only what you cannot discover by reading the code. For
verb-level usage, see `SKILL.md` and `modes/*.md` under
`.claude/skills/agent-workbench/`.

## Never verify against the live stack

Curling `127.0.0.1:9099`/`9100`/`9101` directly, or running any `kb`/`bd`/
`artifact` verb with no `KB_SVC_*`/`BD_SVC_*`/`ARTIFACT_SVC_*` override, is
**not** an acceptable way to verify a change. The live stack is real user
data; a "verification" run against it leaves permanent residue. See
`SKILL.md` for the sanctioned way to verify against an isolated instance
instead.

## Running the test suite

```bash
/usr/bin/python3 -m pytest tests/
```

Run from the repo root. Use the system interpreter explicitly (not a bare
`pytest`) so the run matches the stdlib-only CLI it is testing.

Some tests are marked `container` (see `pytest.ini`) and need a container
runtime on PATH; they add roughly 35s. Opt out with:

```bash
/usr/bin/python3 -m pytest tests/ -m "not container"
```

Caveat: `-m "not container"` does not fully avoid containers.
`tests/test_deploy_smoke.py`'s container-boundary tests
(`test_kb_svc_container_boundary`, `test_artifact_svc_container_boundary`)
are not marked `container` and always run when podman is present.

## Django tests are separate

`apps/artifact-review/backend/`'s Django tests are not run by
`pytest tests/`. They only run via the container test build target, from
`apps/artifact-review/`:

```bash
podman build --target test -f Containerfile .
```

## Architecture constraints

These are load-bearing, not stylistic. A change that violates one of these
will be rejected regardless of how well it otherwise works:

- Only services touch disk. The CLI never reads or writes vault/hub/artifact
  data directly.
- CLI access is HTTP-only, with no filesystem fallback. A service being
  unreachable is a loud failure (non-zero exit, error to stderr), never a
  silent local-disk substitute.
- The host CLI (`cli/**`) is stdlib-only Python. No new pip dependency, ever.
- `cli/**` may never shell out. `tests/test_cli_main.py` enforces this with
  an AST guard over every module in `cli/`; `cli/doctor.py` is the sole
  allowed exception. Do not add a shell-out to any other `cli/**` module,
  and do not extend the allowlist.
