# agent-workbench container hardening + port plan

Ready-to-apply spec for implementation-specialist. Covers the two
Containerfiles + two quadlets, the review-serve.py env surface, the
scope decisions (H3, review-serve blast radius), the delete list, and the
M1/M3/M4/LOW fold-in mapping. Skeleton for the CLI lives at
`.claude/skills/agent-workbench/`.

## Scope-decision recommendations (tech-lead to `record-decision`)

- **H3:** Do NOT try to make quadlets honor `KB_HOME` / `ARTIFACTS_HOME`
  (quadlet supports only `%h`, not arbitrary env substitution, so there is
  no clean fix); instead state plainly in `agent-workbench.env.example` +
  SKILL.md that those two are non-functional once containerized and keep
  only `BEADS_HUB_DIR` as a real override. (Done in the env.example +
  SKILL.md already written.)
- **review-serve blast radius:** Keep the broad `%h:%h:ro` mount (needed to
  resolve artifact symlinks whose targets are not known statically) but
  shadow the known credential dirs with empty tmpfs mounts and layer
  read-only rootfs + `cap-drop=ALL` + `no-new-privileges` + default
  seccomp over it, rather than attempting a static path-enumeration narrow.

## Base image digest pin (both Containerfiles)

Resolved now via `skopeo inspect docker://docker.io/library/python:3.13-slim`:

```
python:3.13-slim -> sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91
```

Pin as `FROM python@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91`
(multi-arch manifest-list digest; podman resolves the host arch from it).
Re-resolve on a deliberate bump with:
`podman pull python:3.13-slim && podman image inspect python:3.13-slim --format '{{index .RepoDigests 0}}'`.

## cap-drop reasoning (both containers)

A plain `python http.server` + `sqlite3` + `urllib` process needs no
Linux capabilities: it binds a high port (9100 / 9099 > 1024, so no
`NET_BIND_SERVICE`), writes only to its bind-mounted data root as the
keep-id user (no chown/setuid/setgid), and forks nothing privileged.
`DropCapability=ALL` with nothing added back. Default seccomp profile is
applied automatically by podman (we never pass `seccomp=unconfined`), so
there is nothing to add for seccomp beyond NOT disabling it.

---

## File 1: scripts/kb-container/Containerfile (full new content)

```dockerfile
FROM python@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# kb-serve.py is stdlib-only; its /clip endpoint reuses kb-clip.py, which
# depends on lxml + readability-lxml (pre-existing project deps). Only pip
# installs here.
RUN pip install --no-cache-dir lxml readability-lxml

WORKDIR /app
COPY kb-serve.py kb-atomize.py kb-index.py kb-clip.py ./

EXPOSE 9100

# H2 fix: do NOT bake --port. kb-serve.py's `run` --port default already
# reads KB_SERVE_PORT (env, else 9100), so the quadlet's KB_SERVE_PORT now
# actually flows through instead of being overridden by a hardcoded flag.
# --host default reads KB_SERVE_HOST (quadlet sets 0.0.0.0).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python3", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('KB_SERVE_PORT','9100')+'/health', timeout=3)"]

ENTRYPOINT ["python3", "/app/kb-serve.py", "run"]
```

Changes vs current: base pinned by digest; `--port 9100` dropped from
ENTRYPOINT (H2); HEALTHCHECK added.

## File 2: scripts/kb-container/kb-serve.container

Keep the existing `[Unit]`, `[Container]` identity, User/Group/UserNS,
`Environment=HOME`/`KB_HOME`, `Environment=KB_SERVE_HOST=0.0.0.0`, the
single `Volume=%h/.knowledgebase:%h/.knowledgebase:rw`, the
`EnvironmentFile=%t/kb-serve.env`, `SecurityLabelDisable=true`, and the
whole `[Service]` block (ExecStartPre secret staging) + `[Install]`
UNCHANGED. ADD to the `[Container]` section:

```ini
# H2: make the port genuinely env-driven now that the ENTRYPOINT no longer
# bakes it. Change this + PublishPort together to move the port.
Environment=KB_SERVE_PORT=9100
PublishPort=127.0.0.1:9100:9100

# Hardening.
ReadOnly=true
Tmpfs=/tmp
NoNewPrivileges=true
DropCapability=ALL
```

(The existing `PublishPort=127.0.0.1:9100:9100` line stays; do not
duplicate it -- the block above lists it only to show it pairs with the
new `Environment=KB_SERVE_PORT`.) Read-only rootfs is safe: kb-serve
writes only under the rw vault mount; `Tmpfs=/tmp` covers any transient +
Python's inability to write `__pycache__` under a read-only `/app` is
harmless.

## File 3: .claude/skills/artifact-serve/container/Containerfile (full new content)

```dockerfile
FROM python@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

# review-serve.py is stdlib-only: no pip step. Layout mirrors the source
# repo so review-serve.py's Path(__file__) asset/root math is unchanged.
WORKDIR /app
COPY scripts/review-serve.py .claude/skills/artifact-serve/scripts/review-serve.py
COPY assets/ .claude/skills/artifact-serve/assets/

EXPOSE 9099

# H2 fix: no baked --port; review-serve.py's run --port default reads
# REVIEW_SERVE_PORT (see the env-surface change spec below), --host reads
# REVIEW_SERVE_HOST (quadlet sets 0.0.0.0).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python3", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('REVIEW_SERVE_PORT','9099')+'/', timeout=3)"]

ENTRYPOINT ["python3", "/app/.claude/skills/artifact-serve/scripts/review-serve.py", "run"]
```

## File 4: .claude/skills/artifact-serve/container/review-serve.container (full new content)

```ini
[Unit]
Description=review-serve artifact review app
After=network-online.target

[Container]
Image=localhost/review-serve:latest
ContainerName=review-serve

User=%U
Group=%U
UserNS=keep-id

Environment=HOME=%h

# H2: env-driven bind + port end to end, replacing the Network=host
# workaround (which dropped all network-namespace isolation). Container
# binds 0.0.0.0 internally; PublishPort restricts the host side to
# loopback -- podman's normal, intended model, same as kb-serve.
Environment=REVIEW_SERVE_HOST=0.0.0.0
Environment=REVIEW_SERVE_PORT=9099
PublishPort=127.0.0.1:9099:9099

# rw: throwaway staging root review-serve symlinks artifacts into.
Volume=/tmp/claude-artifacts:/tmp/claude-artifacts:rw
# rw: durable feedback sqlite DB + uploaded review files.
Volume=%h/.local/share/claude-artifacts:%h/.local/share/claude-artifacts:rw
# ro: broad home mount so artifact symlink targets (unknown statically)
# resolve. Blast radius is contained by the tmpfs credential shadows below
# plus read-only rootfs + cap-drop + no-new-privileges + default seccomp.
Volume=%h:%h:ro

# Shadow credential dirs with empty tmpfs so the broad ro mount cannot read
# them (defense in depth). Present on this host: .ssh .gnupg .aws
# .config/gh .config/containers. Add any other credential dir here.
Tmpfs=%h/.ssh
Tmpfs=%h/.gnupg
Tmpfs=%h/.aws
Tmpfs=%h/.config/gh
Tmpfs=%h/.config/containers

# Hardening.
ReadOnly=true
Tmpfs=/tmp
NoNewPrivileges=true
DropCapability=ALL

# SELinux: broad %h bind still needs the label check disabled (relabeling
# the whole home dir is invasive); the tmpfs shadows + hardening layers are
# the compensating controls.
SecurityLabelDisable=true

[Service]
Restart=on-failure
TimeoutStartSec=30

[Install]
WantedBy=default.target
```

Removed vs current: `Network=host` (replaced by 0.0.0.0-bind + PublishPort).
Added: REVIEW_SERVE_HOST/PORT env, PublishPort, the five credential-dir
tmpfs shadows, ReadOnly/Tmpfs/NoNewPrivileges/DropCapability.

> review-serve stages uploads/feedback under `/tmp/claude-artifacts` and
> `~/.local/share/claude-artifacts` (both rw mounts) -- confirm those are
> the only writable paths it needs before shipping read-only rootfs; if it
> writes elsewhere on rootfs, add a targeted `Tmpfs=` for that path.

## review-serve.py env-surface change (additive; do NOT rewrite the body)

review-serve.py currently hardcodes `127.0.0.1` and reads no host/port
env. Make host + port configurable, mirroring kb-serve.py's argparse
pattern. Precise edits (line numbers per this worktree's copy):

1. `_serve_forever` (def at 3051): change signature
   `def _serve_forever(port: int) -> None:` ->
   `def _serve_forever(host: str, port: int) -> None:`. At line 3069 change
   the bind `ReusableTCPServer(("127.0.0.1", port), handler_cls)` ->
   `ReusableTCPServer((host, port), handler_cls)`; update the log line 3070
   to interpolate `host`.
2. `_port_free` (def at 3078): change signature to
   `def _port_free(host: str, port: int) -> bool:`; at line 3083 bind
   `s.bind((host, port))`.
3. `cmd_run` (3309): read `host = args.host`; call
   `_port_free(host, port)` and `_serve_forever(host, port)`.
4. `cmd_start` (3246) and its forked child path (`_serve_forever(port)` at
   3305): thread `host = args.host` through and call
   `_serve_forever(host, port)` / `_port_free(host, port)`.
5. `build_parser` (3477): on BOTH the `run` (3515-3520) and `start`
   (3510-3512) subparsers:
   - change `--port` default `DEFAULT_PORT` ->
     `int(os.environ.get("REVIEW_SERVE_PORT", DEFAULT_PORT))`.
   - add `sp.add_argument("--host", default=os.environ.get("REVIEW_SERVE_HOST", "127.0.0.1"))`.

Default behavior for bare-host CLI users is unchanged (no env -> 127.0.0.1,
DEFAULT_PORT). `os` is already imported.

---

## Delete list (after the port lands + all references updated)

Old shell tools, the bash deploy driver, and its sidecars:

```
scripts/kb.sh
scripts/beads-hub.sh
scripts/board-ui.sh
scripts/init-agent-workspace.sh
deploy/agent-workbench/agent-workbench
deploy/agent-workbench/agent-workbench.env.example   # moved -> .claude/skills/agent-workbench/agent-workbench.env.example
deploy/agent-workbench/README.md                     # content folded into SKILL.md + this plan
```

(If `deploy/agent-workbench/` is then empty, remove the dir. Do NOT delete
`scripts/kb-serve.py`, `kb-index.py`, `kb-clip.py`, `kb-atomize.py`,
`build-kb-index.py` -- the CLI delegates to them.)

## Reference-update list (repoint old-script mentions at the new CLI)

Update these to
`.claude/skills/agent-workbench/agent-workbench <subcommand>`:

```
CLAUDE.md
.claude/skills/capture-source/SKILL.md
.claude/agents/zakia.md
.claude/rules/orchestration.md
docs/kb/doctrine-v2-board-kb-layer.md
docs/migrate-to-knowledgebase.md
tests/test_deploy_smoke.py
deploy/agent-workbench/README.md   # (being deleted; ensure nothing else links it)
```

## Audit fold-in mapping

| ID | Where folded | Fix |
|---|---|---|
| M1 | `cli/board.py::resolve_repo` | validate the hub board `$HUB_ROOT/<name>/.beads`, not stale `<repo>/.beads` |
| M3 | `cli/kb.py::service_base_url` | honor `KB_SERVE_HOST` + `KB_SERVE_PORT` |
| M4 | `cli/hub.py::init_board` / `_bd_env_without_beads_dir` | strip `BEADS_DIR` from the `bd init` child env |
| H2 | Files 1-4 + review-serve.py env surface | port genuinely env-driven; drop `Network=host` |
| H3 | env.example + SKILL.md | KB_HOME/ARTIFACTS_HOME documented non-functional in containers |
| LOW clip TOCTOU | `scripts/kb-clip.py::build_note_path` | use `os.open(..., O_CREAT\|O_EXCL)` in the collision loop, return the fd/path atomically |
| LOW curl error body | `cli/kb.py::_get` / `_post_json` | read + surface the HTTP error response body |
| LOW hub naming/TOCTOU | `cli/hub.py::init_board` / `cmd_add` | correctly-sensed `git_repo_preexisted`; re-read repo list before `bd repo add` |
| H1 | inherited automatically | clip path delegates to kb-clip.check_url_scheme (http/https allowlist), preserved verbatim, zero new code |
```
