---
name: agent-workbench
description: Locally deployable agent workbench (knowledgebase vault + bd board hub + bdui web front end + hardened kb-serve/review-serve containers) driven by ONE pure-Python CLI. Use to run knowledgebase clip/put/query, manage bd boards under the central hub, launch the board web UI, scaffold a repo's agent workspace, or build and deploy the two review/knowledgebase containers locally. Replaces the old scripts/*.sh shell tools and the bash deploy driver.
---

# agent-workbench

One skill, one executable, five subcommands. Every tool is pure Python
(argparse, stdlib + the two pre-existing lxml/readability deps kb-clip
already used). No bash, no `.sh` shims. The CLI lives BESIDE the hardened
container, never inside its image.

```bash
.claude/skills/agent-workbench/agent-workbench <subcommand> [ARGS]
```

## Subcommands

| Subcommand | Replaces | Purpose |
|---|---|---|
| `kb` | `scripts/kb.sh` | knowledgebase vault: init/add/path/index/clip/put/query/atomize/status |
| `hub` | `scripts/beads-hub.sh` | bd board hub: init/add/sync/list/path/status |
| `board` | `scripts/board-ui.sh` | bdui web front end: up/down/status (bare-host, per-repo -- separate from the always-on compose `bdui` service below, which is the single global hub-aggregator view) |
| `init-workspace` | `scripts/init-agent-workspace.sh` | scaffold docs/kb + workstreams + bd board + reindex hook into a repo |
| `deploy` | `deploy/agent-workbench/agent-workbench` | build + run the kb-serve / review-serve / bdui containers |

### kb

```bash
agent-workbench kb clip "<url>" --project <project>
agent-workbench kb put <project> "<title>" --type note --source "<url>"  # body on stdin
agent-workbench kb query "<terms>" --project <project> --type source
agent-workbench kb index
agent-workbench kb status
```

`clip` / `put` / `query` prefer the running kb-serve HTTP service (so the
call also atomizes + reindexes) and fall back to an in-process kb-serve.py
call when the service is down. Same behavior kb.sh had.

### hub / board / init-workspace / deploy

```bash
agent-workbench hub add <name> [prefix]
agent-workbench board up [REPO_DIR]        # prints the UI URL
agent-workbench init-workspace [TARGET_DIR] [--prefix PREFIX]
agent-workbench deploy up | down | status
```

## How it differs from the old scripts

- **Pure Python, single entrypoint.** The five separate shell scripts +
  the bash deploy driver collapse into one executable with subcommands.
  The `kb` family stays a thin facade over the existing
  `scripts/kb-serve.py` (which already facades kb-index / kb-clip /
  kb-atomize); hub/board/init-workspace/deploy are genuine rewrites.
- **Audit fixes folded in:**
  - `kb` honors `KB_SERVE_HOST` (not only `KB_SERVE_PORT`) and surfaces
    the HTTP error body on failure instead of swallowing it.
  - `board` validates the hub board (`$HUB_ROOT/<name>/.beads`), not a
    stale repo-local `<repo>/.beads`.
  - `hub` runs `bd init` with `BEADS_DIR` stripped from the child env so
    an ambient value cannot redirect where the board is written, and uses
    a correctly-sensed `git_repo_preexisted` flag for incidental-repo
    cleanup.
- **The clip path preserves kb-clip.py's http/https scheme allowlist
  verbatim** (it delegates to the same `check_url_scheme`), so `file://`
  and other schemes stay rejected with zero new code.

## Deploy + hardening

`deploy up` builds and starts kb-serve, review-serve, and bdui as
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
the bind-mounted `~/.beads-hub` board files (0700/0600).

Optional data-root overrides live in
`.claude/skills/agent-workbench/agent-workbench.env.example`. NOTE:
`KB_HOME` / `ARTIFACTS_HOME` are NOT functional overrides once the
containers are running (the quadlets bind `%h`-relative paths); only
`BEADS_HUB_DIR` is read directly by the Python code. See the env.example
comments.

**review-serve's network artifact-publish endpoint is NOT shipped.** It is
held back pending an XSS lockdown (tracked as `agent-workbench-wxh`). As
deployed (quadlet or compose), review-serve is local/loopback-only
(127.0.0.1-bound) -- do not assume or rely on a network publish path.

### docker-compose (portable alternative to the quadlets)

`docker-compose.yml` at the repo root describes kb-serve, review-serve,
n8n, and bdui as a podman-compose-compatible stack. It COEXISTS with the
quadlets, it does not replace them: `agent-workbench deploy up/down`
(podman-quadlet user units) remains the live/production deploy mechanism
on this host. The compose file is an additional portable artifact for
hosts without systemd-quadlet (plain docker, a cloud VM).

It mirrors the same hardening as the quadlets: read-only rootfs,
`cap-drop=ALL`, `no-new-privileges`, tmpfs mounts, healthchecks, ports
bound to 127.0.0.1, and the same pinned n8n image digest. n8n sits behind
a compose `profiles: ["n8n"]` entry, so a plain compose-up brings up only
kb-serve + review-serve, matching n8n's current intentionally-down state:

```bash
podman-compose -f docker-compose.yml up -d               # kb-serve + review-serve + bdui
podman-compose --profile n8n -f docker-compose.yml up -d # adds n8n
```

`bdui` (web front end for `bd`) is on by default in compose -- no profile
gate, it comes up with every plain compose-up -- and is also
`deploy`-managed as its own quadlet unit (see "Deploy + hardening"
above); either path publishes at `http://127.0.0.1:3100`, built from
`scripts/bdui-container/Containerfile`, and serves the bd hub aggregator
board (the cross-project view, not a single repo) via the
`${HOME}/.beads-hub` mount. This is distinct from the bare-host
`agent-workbench board up <repo_dir>` subcommand above, which is a
per-repo dev-workstation tool for viewing one project's own board on a
scanned free port.

## kb-serve LLM endpoints (agent-facing)

Two optional, LLM-backed endpoints exist on the running kb-serve service
(see `scripts/kb-serve.py`'s module docstring for exact behavior):

- `POST /enrich` -- fills in a note's `question`/`summary` frontmatter
  fields via the configured LLM. Gated by `KB_ENRICH` (must be `1`;
  default `0` is a clean no-op, zero network calls) plus a resolvable API
  key (`KB_LLM_API_KEY`, or preferably `KB_LLM_API_KEY_CMD`, a vault CLI
  command whose stdout is the key -- see
  `scripts/kb-container/kb.env.example` for the exact modes/format).
- `POST /atomize` -- LLM-assisted atomize/split of a URL or raw document
  content into decontextualized child notes, using a "strong" model tier
  (bigger than enrich's, since atomize needs real
  decontextualization/section-splitting, not just a gist). If
  `KB_ENRICH`/the key isn't configured, it falls back to the deterministic
  heading-based split (no model call) -- never fails, just degrades.

Both are off/degraded by default; opt in via `KB_ENRICH=1` plus a
configured key in the real `~/.knowledgebase/kb.env` (see
`scripts/kb-container/kb.env.example` for the template -- never document
or imply a real secret value there).

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
API_KEY=$(scripts/n8n-container/n8n-secret.py resolve-api-key --data-dir ~/.local/share/n8n)
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
