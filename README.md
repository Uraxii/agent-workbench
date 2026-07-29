# agent-workbench

Standalone home for the local agent-workbench service stack. This repo owns the code and deploy files for:

- `bdui`
- `kb-svc`
- `bd-svc`
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
| A compose implementation: `podman-compose` (any version), or `docker compose` / `docker-compose` >= 2.24 | Brings the stack up. The docker-flavoured floor exists because `docker-compose.yml` uses the compose-spec 2.24+ long `env_file` form so a missing optional kb.env does not block startup; older compose fails the whole file on that syntax | `sudo dnf install podman-compose`, or the docker compose CLI plugin |
| `git` | Cloning this repo | your package manager |
| Python 3.9 or newer | Runs the CLI. It is stdlib-only, so there is no venv and nothing to `pip install` | your package manager |

`tailscale` is optional and only needed if you want the mesh-networked access
path. Local-only use does not need it.

### 2. Clone

```bash
git clone <this-repo>
cd agent-workbench
```

The stack runs fully offline with no other config. To turn on LLM enrichment,
copy the tracked example into place first (gitignored, never committed):

```bash
mkdir -p ~/.knowledgebase
cp scripts/kb-container/kb.env.example ~/.knowledgebase/kb.env
```

### 3. Check the prerequisites

```bash
python3 .claude/skills/agent-workbench/agent-workbench doctor
```

It prints one line per prerequisite with a fix hint, and exits non-zero if a
required one is missing. `doctor --json` emits the same report as one JSON
object for scripts and agents.

### 4. Bring the stack up

```bash
podman-compose up -d    # or: docker compose up -d    # or: docker-compose up -d
```

That starts `kb-svc` (127.0.0.1:9100), `bd-svc` (127.0.0.1:9101),
`artifact-svc` (127.0.0.1:9099) and `bdui` (127.0.0.1:3100). `n8n` is
opt-in: add `--profile n8n` and create `~/.local/share/n8n/n8n.env` with an
`N8N_ENCRYPTION_KEY` first.

### 5. Install the skill

```bash
python3 .claude/skills/agent-workbench/agent-workbench install --copy
```

This copies a pinned snapshot to `~/.claude/skills/agent-workbench`.
Re-running `--copy` always reproduces exactly this repo's current tree: any
file the source no longer has is removed rather than left behind. It refuses
to overwrite a real directory at the target that it did not itself install,
so move such a directory aside yourself first. `--uninstall` reverses either
install, and refuses to remove anything that is not its own symlink or its
own stamped copy.

Use `--link` instead only if you are hacking on this repo and want the
install to symlink and track this checkout's current branch live. `doctor`
reports a linked install as a warning, because it silently changes with the
branch.

### 6. Verify

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench doctor
curl -fsS http://127.0.0.1:9100/health
curl -fsS http://127.0.0.1:9101/health
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
- `scripts/kb-container/` kb-svc container files
- `scripts/bd-container/` bd-svc container files
- `scripts/bdui-container/` beads-ui container files
- `scripts/n8n-container/` n8n helpers
- `scripts/kb-svc.py` and sibling helpers for the knowledgebase service
- `scripts/bd-svc.py` the board service
- `.claude/skills/agent-workbench/` CLI used for board, hub, kb, and workspace flows
- `apps/artifact-review/` Django + React artifact review service
