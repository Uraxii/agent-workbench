# kb-svc container

Container packaging of `kb-svc.py`, the knowledgebase service. The
service is the only thing that opens `$KB_HOME`; the agent-workbench CLI
reaches it over HTTP.

`docker-compose.yml` at the repo root is the only deploy path. There is no
systemd unit here and nothing host-specific to install, so the same files
work on any host with a container runtime.

## Files

- `Containerfile` — builds the image (`python:3.13-slim` + `pip install
  lxml readability-lxml`, the two pre-existing deps `kb-clip.py` needs;
  everything kb-svc.py adds itself is stdlib-only).
- `kb.env.example` — placeholder config/secret file. Copy it to
  `~/.knowledgebase/kb.env` and edit (see Config below). The real
  `kb.env` is gitignored and never committed.

## Build

From this repo's root:

```bash
podman build -t localhost/kb-svc:latest -f scripts/kb-container/Containerfile scripts
```

## Config: `~/.knowledgebase/kb.env`

From this repo's root:

```bash
cp scripts/kb-container/kb.env.example ~/.knowledgebase/kb.env
chmod 600 ~/.knowledgebase/kb.env
$EDITOR ~/.knowledgebase/kb.env
```

Keys (all optional, see `kb.env.example` for full comments):

| Key | Default | Notes |
|---|---|---|
| `KB_ENRICH` | `0` | must be `1` to spend any model calls |
| `KB_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | any OpenAI-compatible endpoint |
| `KB_LLM_MODEL` | `openai/gpt-4o-mini` | any model your provider accepts |
| `KB_LLM_API_KEY` | none | static key (mode 1, simplest) |
| `KB_LLM_API_KEY_CMD` | none | vault command (mode 2, preferred — wins over the static key) |

### Two ways to supply the LLM API key

1. **Static** — `KB_LLM_API_KEY=<raw>` directly in `kb.env`. Simplest, but
   the raw key sits in a plaintext file (gitignored, `chmod 600`, but
   still on disk).
2. **Vault command** (preferred) — `KB_LLM_API_KEY_CMD="<command>"`. kb-svc
   runs this exact shell command and uses its stdout as the key. Works
   with any vault CLI, provider-agnostic: `pass show ...`, `op read
   op://...`, `gopass show ...`, or Proton Pass's `pass-cli` (see
   `~/.claude/skills/proton-pass-cli/SKILL.md` for the exact invocation
   and its `PROTON_PASS_SESSION_DIR`/`PROTON_PASS_AGENT_REASON`
   requirements). Example:
   ```
   KB_LLM_API_KEY_CMD="pass-cli item view --vault-name MachineSecrets --item-title openrouter --field api-key"
   ```

**Either way, the raw key never touches the container image or a tracked
file.** Resolution happens at start time:

- **Container**: compose passes `~/.knowledgebase/kb.env` straight through
  as an `env_file`, and `kb-svc.py`'s own `resolve_api_key()` runs
  `KB_LLM_API_KEY_CMD` in-process at startup, inside the container. The
  resolved key is held in memory and never logged or written. If the vault
  CLI named by `_CMD` is not present in the image, resolution logs one
  warning and returns no key — a safe no-op, since `KB_ENRICH` defaults to
  `0`. Compose refuses to start when `kb.env` is missing, which is why the
  fresh-machine install copies `kb.env.example` into place first.
- **Bare `kb-svc.py run`** (no container): the same resolution runs
  in-process at startup (`build_config`); the key is held in memory only,
  never written anywhere.

If neither source yields a key and `KB_ENRICH=1`, `/enrich` logs one clear
line and returns a no-op response — it never crashes, and the
put/clip/query/atomize path never depends on any of this.

## Run it

From this repo's root:

```bash
podman-compose up -d kb-svc    # or: docker compose up -d kb-svc
```

`restart: unless-stopped` in `docker-compose.yml` is what survives a
reboot, so there is no unit to enable and no lingering to configure.

## Networking

The container keeps its own network namespace. `kb-svc.py`'s own bind
address defaults to `127.0.0.1` (correct for a bare host run), but compose
overrides it to `0.0.0.0` via `KB_SVC_HOST` so the container listens on
the interface the runtime's NAT path (pasta/slirp4netns) can actually
reach. The `127.0.0.1:9100:9100` port mapping then restricts the HOST-side
socket to loopback only. Net effect: the service is reachable at
`127.0.0.1:9100` on the host and nowhere else.

Loopback is not treated as a trust boundary: the service also enforces a
Host-header allowlist, refuses any request carrying an `Origin`, and
refuses a POST that is not declared `application/json`. See
`docs/design/security-baseline-threat-model.md`.

Tailscale stays entirely a host concern — never run inside the container:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9100
```

## Mounts

| Mount | Path | Mode | Why |
|---|---|---|---|
| vault | `~/.knowledgebase` | rw | notes, index, kb.env |

One mount, deliberately: kb-svc never symlinks or reads arbitrary host
paths outside `KB_HOME`, so only the vault itself needs to be visible.

## Foreground mode (`run` verb)

`kb-svc.py run` blocks in the foreground (no fork, no pidfile), logging
to stdout (`podman logs kb-svc`), so the container runtime is the
process supervisor.
