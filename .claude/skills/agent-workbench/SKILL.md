---
name: agent-workbench
description: Locally deployable agent workbench (knowledgebase vault + bd board hub + bdui web front end + hardened kb-serve/artifact-serve containers) driven by ONE pure-Python CLI. Use to run knowledgebase clip/put/query, manage bd boards under the central hub, launch the board web UI, scaffold a repo's agent workspace, build and deploy the artifact and knowledgebase containers locally, or record/audit an architectural or scope decision the moment it's settled ("record decision", "we decided", "log this decision").
---

# agent-workbench

One skill, one executable, six subcommands. Every tool is pure Python
(argparse, stdlib + the two pre-existing lxml/readability deps kb-clip
already used). No bash, no `.sh` shims. The CLI lives BESIDE the hardened
container, never inside its image.

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW <subcommand> [ARGS]
```

## Subcommands

| Subcommand | Replaces | Purpose |
|---|---|---|
| `kb` | `scripts/kb.sh` | knowledgebase service client: init/add/path/index/clip/put/query/atomize/status/decision |
| `bd` | `scripts/beads-hub.sh` + `scripts/board-ui.sh` | bd board hub (init/add/sync/list/path/status) + bdui web front end (ui-up/ui-down/ui-status, bare-host, per-repo -- separate from the always-on compose `bdui` service below, which is the single global hub-aggregator view) |
| `artifact` | (new) | artifact review app: publish/feedback/serve/status, a facade over `.claude/skills/artifact-serve/scripts/artifact-serve.py` |
| `deploy` | `deploy/agent-workbench/agent-workbench` | build + run the kb-serve / artifact-serve / bdui containers |
| `install` | (new) | (un)install this repo's skill into `$HOME/.claude/skills/agent-workbench` (`--link`/`--copy`/`--uninstall`) |
| `init-workspace` | `scripts/init-agent-workspace.sh` | scaffold docs/kb + workstreams + bd board + reindex hook into a repo |

- `kb` -- see `modes/kb.md` for the full kb walkthrough (clip/put/query,
  decisions, the derived-index rebuild, the optional LLM passes).
- `bd` -- see `modes/bd.md` for board-hub + bdui detail (bare-host
  `ui-up` vs the always-on hub-aggregator `bdui` service).
- `artifact` -- see `modes/artifact.md` for the artifact review app
  (publish/feedback/serve/status), which now also carries everything the
  retired standalone `artifact-serve` skill used to document.

### deploy / install / init-workspace

```bash
$AW install --link
$AW init-workspace [TARGET_DIR] [--prefix PREFIX]
$AW deploy up | down | status
```

`install` (un)installs this repo's skill dir into
`$HOME/.claude/skills/agent-workbench`. `init-workspace` scaffolds
`docs/kb/` + `workstreams/` + a bd board + the reindex hook into a target
repo. `deploy` is detailed in "Deploy + hardening" below.

## How it differs from the old scripts

**Pure Python, single entrypoint.** The five separate shell scripts + the
bash deploy driver collapse into one executable with subcommands. The
`kb` family is now an HTTP client of the knowledgebase service (which
owns the vault outright -- no CLI code touches it), and `artifact` is a
facade over `scripts/artifact-serve.py`; the `bd` family
(former `hub`/`board`) and `init-workspace`/`deploy` are genuine
rewrites. kb- and bd-specific audit fixes are documented in their own
mode docs above.

## Deploy + hardening

`deploy up` builds and starts kb-serve, artifact-serve, and bdui as
rootless podman-quadlet user units (n8n's quadlet is also installed, but
its image is pulled by digest rather than built -- see the n8n note
below). Hardening (read-only rootfs, `cap-drop=ALL`, `no-new-privileges`,
seccomp default, digest-pinned base image, HEALTHCHECK, narrowed mounts)
and the env config surface are documented in
`docs/agent-workbench-hardening-plan.md`.

bdui (the bd board web front end) is a `deploy`-managed quadlet unit like
the other two, not compose-only: `deploy up` builds
`localhost/bdui:latest`, installs `scripts/bdui-container/bdui.container`,
and health-checks `http://127.0.0.1:3100/`; `deploy down` removes it if
this bundle owns the installed quadlet. It runs with `UserNS=keep-id` so
the container's user maps to the real host user, matching ownership of
the bind-mounted `$HOME/.beads-hub` board files (0700/0600). See `modes/bd.md`
for how this compares to the bare-host `bd ui-up`.

Optional data-root overrides live in
`$HOME/.claude/skills/agent-workbench/agent-workbench.env.example`. NOTE:
`KB_HOME` / `ARTIFACTS_HOME` are NOT functional overrides once the
containers are running (the quadlets bind `%h`-relative paths); only
`BEADS_HUB_DIR` is read directly by the Python code. See the env.example
comments.

**artifact-serve's network artifact-publish endpoint is NOT shipped.** It
is held back pending an XSS lockdown (tracked as `agent-workbench-wxh`).
As deployed (quadlet or compose), artifact-serve is local/loopback-only
(127.0.0.1-bound) -- do not assume or rely on a network publish path. See
`modes/artifact.md` for the full detail on this holdback.

### docker-compose (portable alternative to the quadlets)

`docker-compose.yml` at the repo root describes kb-serve, artifact-serve,
n8n, and bdui as a podman-compose-compatible stack. It COEXISTS with the
quadlets, it does not replace them:
`$HOME/.claude/skills/agent-workbench/agent-workbench deploy up/down`
(podman-quadlet user units) remains the live/production deploy mechanism
on this host. The compose file is an additional portable artifact for
hosts without systemd-quadlet (plain docker, a cloud VM).

It mirrors the same hardening as the quadlets: read-only rootfs,
`cap-drop=ALL`, `no-new-privileges`, tmpfs mounts, healthchecks, ports
bound to 127.0.0.1, and the same pinned n8n image digest. n8n sits behind
a compose `profiles: ["n8n"]` entry, so a plain compose-up brings up only
kb-serve + artifact-serve, matching n8n's current intentionally-down state:

```bash
podman-compose -f docker-compose.yml up -d               # kb-serve + artifact-serve + bdui
podman-compose --profile n8n -f docker-compose.yml up -d # adds n8n
```

`bdui` (web front end for `bd`) is on by default in compose -- no profile
gate, it comes up with every plain compose-up -- and is also
`deploy`-managed as its own quadlet unit (see above); either path
publishes at `http://127.0.0.1:3100`. See `modes/bd.md` for the full
bare-host-vs-always-on comparison.

## n8n Public API (agent-facing)

n8n's Public REST API is enabled (pinned in `n8n.container`), letting an
agent create and trigger workflows without a human in the loop for the
API calls themselves.

**One-time human bootstrap** (already done for the owner account setup;
only the API key step remains): log into the n8n editor at
http://127.0.0.1:5678, go to Settings -> n8n API -> Create an API Key,
then store the value per `scripts/n8n-container/n8n.env.example`'s
`N8N_API_KEY` / `N8N_API_KEY_CMD` Mode 2 block. There is no headless mint
path for this key in n8n Community edition.

**Agent resolves the key:**

```bash
API_KEY=$(scripts/n8n-container/n8n-secret.py resolve-api-key --data-dir $HOME/.local/share/n8n)
```

**Create a workflow** (body = a workflow JSON file):

```bash
curl -X POST http://127.0.0.1:5678/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-N8N-API-KEY: $API_KEY" \
  --data @path/to/workflow.json
```

**Activate it** (makes its trigger nodes live):

```bash
curl -X POST http://127.0.0.1:5678/api/v1/workflows/<id>/activate \
  -H "X-N8N-API-KEY: $API_KEY"
```

**Trigger an already-activated Webhook-triggered workflow** (no API key
needed for the webhook call itself, only the two calls above use it):

```bash
curl -X POST http://127.0.0.1:5678/webhook/<path>
```

This only works for workflows containing a Webhook trigger node. The
starter workflow at `workflows/image-approval-pipeline.n8n.json` uses a
Form Trigger instead, so it is NOT webhook-triggerable as-is -- a
separate, already-ticketed workflow-design concern.

All endpoints above are `http://127.0.0.1:5678` (loopback-published;
reachable over Tailscale via the host, same as the rest of this stack).
