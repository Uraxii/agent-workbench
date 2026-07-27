# agent-workbench

Standalone home for the local agent-workbench service stack. This repo owns the code and deploy files for:

- `bdui`
- `kb-serve`
- `artifact-serve`
- `n8n`
- the supporting `agent-workbench` and `artifact-serve` skills/CLI that drive them

## What stays outside the repo

Live runtime data stays where it already lives. This split does **not** move or delete it.

- `~/.beads-hub/`
- `~/.knowledgebase/`
- `~/.local/share/claude-artifacts/`
- `/tmp/claude-artifacts/`
- `~/.local/share/n8n/`

## Repo layout

- `docker-compose.yml` portable compose deploy for the stack
- `scripts/kb-container/` kb-serve container + quadlet files
- `scripts/bdui-container/` beads-ui container files
- `scripts/n8n-container/` n8n quadlet + helpers
- `scripts/kb-serve.py` and sibling helpers for the knowledgebase service
- `.claude/skills/agent-workbench/` CLI used for board, hub, kb, and workspace flows
- `.claude/skills/artifact-serve/` review app service code and assets

## Quick checks

```bash
cd ~/Projects/agent-workbench
rg -n 'Projects/agent-workbench|agent-workbench' scripts .claude docker-compose.yml
python3 .claude/skills/agent-workbench/agent-workbench --help
```
