---
title: Use artifact-serve.py as the live 9099 UI entrypoint
topic: artifact-service-ui-live-entrypoint
date: 2026-07-26
status: active
supersedes: 
tags: []
---

Use artifact-serve.py as the live 9099 UI entrypoint for the unified Lodestar owned review UI.

## Rationale

The current port 9099 service runs artifact-serve.py and returns 404 on /_/review, while the approved UI implementation currently exists only in review-serve.py. The user also forbade starting a new server, so the existing artifact-serve runtime must become the reviewed UI path.

## Refs

/var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/scripts/artifact-serve.py,/var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/scripts/review-serve.py,/var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/assets/css/theme.css,agent-workbench-wh0
