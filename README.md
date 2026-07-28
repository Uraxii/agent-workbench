# agent-workbench

Standalone home for the local agent-workbench service stack. This repo owns the code and deploy files for:

- `bdui`
- `kb-serve`
- `artifact-review`
- `n8n`
- the supporting `agent-workbench` CLI that drives them

## Install on a fresh machine

Compose is the only deploy path. There is nothing host-specific to install
beyond the prerequisites below.

### 1. Prerequisites

| Need | Why | Get it |
| --- | --- | --- |
| A container runtime: `podman` or `docker` | The services only ever run as containers | `sudo dnf install podman` / `sudo apt install podman`, or https://docs.docker.com/engine/install/ |
| A compose implementation: `podman-compose`, `docker compose`, or `docker-compose` | Brings the stack up | `sudo dnf install podman-compose`, or the docker compose CLI plugin |
| `git` | Cloning this repo | your package manager |
| Python 3.9 or newer | Runs the CLI. It is stdlib-only, so there is no venv and nothing to `pip install` | your package manager |
| `bd`, the beads board CLI | The `bd`/`init-workspace` verbs shell out to it | https://github.com/steveyegge/beads |

`tailscale` is optional and only needed if you want the mesh-networked access
path. Local-only use does not need it.

### 2. Clone

```bash
git clone <this-repo> ~/Projects/agent-workbench
cd ~/Projects/agent-workbench
```

### 3. Create the kb service config

`docker-compose.yml` declares `~/.knowledgebase/kb.env` as an `env_file`, so
compose refuses to start without it. Copy the tracked example and edit it:

```bash
mkdir -p ~/.knowledgebase
cp scripts/kb-container/kb.env.example ~/.knowledgebase/kb.env
```

The real `kb.env` is gitignored and never committed.

### 4. Check the prerequisites

```bash
python3 .claude/skills/agent-workbench/agent-workbench doctor
```

It prints one line per prerequisite with a fix hint, and exits non-zero if a
required one is missing. `doctor --json` emits the same report as one JSON
object for scripts and agents.

### 5. Bring the stack up

```bash
podman-compose up -d    # or: docker compose up -d
```

That starts `kb-serve` (127.0.0.1:9100), `artifact-serve` (127.0.0.1:9099) and
`bdui` (127.0.0.1:3100). `n8n` is opt-in: add `--profile n8n` and create
`~/.local/share/n8n/n8n.env` with an `N8N_ENCRYPTION_KEY` first.

### 6. Install the skill

```bash
python3 .claude/skills/agent-workbench/agent-workbench install --link
```

This symlinks `~/.claude/skills/agent-workbench` at this checkout. Use
`--copy` instead if you want a snapshot rather than a live link, and
`--uninstall` to reverse it (it refuses to remove anything that is not its own
symlink).

### 7. Verify

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench doctor
curl -fsS http://127.0.0.1:9100/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9099/
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3100/
```

`$HOME/.claude/skills/agent-workbench/agent-workbench <verb>` is the documented
invocation once the skill is installed.

## The one ownership caveat

agent-workbench does **not** require a rootless container runtime, and
`doctor` does not check for one. The containers are the only writers to the
mounted data directories, so whichever uid they run as is internally
consistent.

The caveat is narrower, and it is a caveat rather than an install gate: the
knowledgebase vault stays human-readable Obsidian-compatible markdown. A
runtime that writes files the invoking user cannot read still starts the stack
and still serves every endpoint, but it breaks two things a human does
directly:

- opening the vault in Obsidian or an editor
- user-run backups of `~/.knowledgebase`

If you hit that, the fix is on the runtime side (rootless podman, rootless
Docker, or `userns-remap`), not in this repo. Nothing here gates on it.

## What stays outside the repo

Live runtime data stays where it already lives. This split does **not** move or delete it.

- `~/.beads-hub/`
- `~/.knowledgebase/`
- `~/.local/share/artifacts/`
- `/tmp/artifacts/`
- `~/.local/share/n8n/`

## Repo layout

- `docker-compose.yml` the deploy for the stack
- `scripts/kb-container/` kb-serve container files
- `scripts/bdui-container/` beads-ui container files
- `scripts/n8n-container/` n8n helpers
- `scripts/kb-serve.py` and sibling helpers for the knowledgebase service
- `.claude/skills/agent-workbench/` CLI used for board, hub, kb, workspace, and deploy flows
- `apps/artifact-review/` Django + React artifact review service

## Quick checks

```bash
cd ~/Projects/agent-workbench
rg -n 'Projects/agent-workbench|agent-workbench' scripts .claude docker-compose.yml
python3 .claude/skills/agent-workbench/agent-workbench --help
```
