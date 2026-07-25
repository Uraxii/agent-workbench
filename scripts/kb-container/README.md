# kb-serve container

Rootless-podman packaging of `kb-serve.py` (the personal knowledgebase HTTP
facade) for durable, boot-surviving deployment via a systemd user quadlet.
Mirrors the pattern already established in
`.claude/skills/artifact-serve/container/` (see that README for the
`Network=host` background this one improves on).

## Files

- `Containerfile` — builds the image (`python:3.13-slim` + `pip install
  lxml readability-lxml`, the two pre-existing deps `kb-clip.py` needs;
  everything kb-serve.py adds itself is stdlib-only).
- `kb-serve.container` — the quadlet unit. Tracked copy; install target is
  `~/.config/containers/systemd/kb-serve.container` (see Install below).
- `kb.env.example` — placeholder config/secret file. Copy it to
  `~/.knowledgebase/kb.env` and edit (see Config below). The real
  `kb.env` is gitignored and never committed.

## Build

```bash
cd ~/Projects/agent-workbench/scripts
podman build -t localhost/kb-serve:latest -f kb-container/Containerfile .
```

## Config: `~/.knowledgebase/kb.env`

```bash
cp ~/Projects/agent-workbench/scripts/kb-container/kb.env.example ~/.knowledgebase/kb.env
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
2. **Vault command** (preferred) — `KB_LLM_API_KEY_CMD="<command>"`. kb-serve
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

- **Container/quadlet**: the quadlet's `ExecStartPre=` builds one tmpfs
  env file **on the host**, before the container starts. It first copies
  over the non-secret passthrough keys (`KB_ENRICH`, `KB_LLM_BASE_URL`,
  `KB_LLM_MODEL`) from `kb.env`, if that file exists, then runs
  `kb-serve.py resolve-secret`, which runs `KB_LLM_API_KEY_CMD` if set
  (else falls back to the static `KB_LLM_API_KEY`) and prints exactly one
  `KB_LLM_API_KEY=<value>` line — never logs it. `umask 077` plus the
  redirect writes all of that to `%t/kb-serve.env` (the user's XDG
  runtime dir, i.e. `/run/user/<uid>/kb-serve.env`, mode 0600, tmpfs),
  which the container's `EnvironmentFile=` then loads. A missing `kb.env`
  is a clean no-op — podman's `--env-file` requires its target to exist,
  so passthrough config can't be read straight from `kb.env` itself, only
  folded into this always-present tmpfs file. The file lives only in
  tmpfs: regenerated on every start, gone at logout/reboot, never written
  to a persistent disk path.
- **Bare `kb-serve.py run`** (no container): the same resolution runs
  in-process at startup (`build_config`); the key is held in memory only,
  never written anywhere.

If neither source yields a key and `KB_ENRICH=1`, `/enrich` logs one clear
line and returns a no-op response — it never crashes, and the
put/clip/query/atomize path never depends on any of this.

## Install the quadlet

```bash
mkdir -p ~/.config/containers/systemd
cp ~/Projects/agent-workbench/scripts/kb-container/kb-serve.container \
   ~/.config/containers/systemd/kb-serve.container
systemctl --user daemon-reload
systemctl --user start kb-serve
```

`WantedBy=default.target` auto-wires it into `default.target.wants` on
every `daemon-reload`/boot — no separate `systemctl enable` needed. Needs
`loginctl enable-linger $USER` (one-time per host) so the user's systemd
instance, and the container with it, keeps running without an active
login session.

Re-run the `cp` + `daemon-reload` after any edit to the tracked quadlet
file; the `~/.config/containers/systemd/` copy is the live one, not a
symlink to the repo.

## Networking

Unlike `artifact-serve`, this container does NOT use `Network=host`.
`kb-serve.py`'s own bind address defaults to `127.0.0.1` (correct for a
bare host run), but the quadlet overrides it to `0.0.0.0` via
`Environment=KB_SERVE_HOST=0.0.0.0` so the container listens on its own
non-loopback interface — the interface Podman's `PublishPort=` NAT path
(pasta/slirp4netns) can actually reach. `PublishPort=127.0.0.1:9100:9100`
then restricts the HOST-side socket to loopback only. Net effect: the
service is reachable at `127.0.0.1:9100` on the host, nowhere else,
exactly as if it were `Network=host` — but this container keeps its own
network namespace, a smaller blast radius than sharing the host's.

Tailscale, as with `artifact-serve`, stays entirely a host concern — never
run inside the container:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9100
```

## Mounts

| Mount | Path | Mode | Why |
|---|---|---|---|
| vault | `~/.knowledgebase` | rw | notes, index, kb.env |

Narrower than `artifact-serve`'s `~` ro mount: kb-serve never symlinks or
reads arbitrary host paths outside `KB_HOME`, so only the vault itself
needs to be visible. `SecurityLabelDisable=true` sidesteps an SELinux
relabel of that mount (same trade-off as `artifact-serve`, smaller
surface here).

## Foreground mode (`run` verb)

Same shape as `artifact-serve`'s `run` verb: `kb-serve.py run` blocks in
the foreground (no fork, no pidfile), logging to stdout (`podman logs` /
`journalctl --user -u kb-serve`), so the container runtime is the process
supervisor.
