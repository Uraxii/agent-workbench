---
title: Infer legacy review rounds from last push boundary
topic: artifact-review-round-migration
date: 2026-07-26
status: active
supersedes: 
tags: []
---

When migrating legacy artifact feedback into review rounds, split into two inferred rounds only when legacy thread timestamps exist on both sides of the latest artifact_index.last_pushed for that artifact; otherwise keep all legacy feedback in one inferred round.

## Rationale

artifact_index.last_pushed is the only deterministic resubmission clue in stored legacy data, so this preserves contractor submission to client feedback to resubmission ordering without inventing extra rounds from weak signals.

## Refs

/var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/scripts/review-serve.py,/var/home/nicole/Projects/agent-workbench/tests/test_artifact_serve_rounds.py,task-3
