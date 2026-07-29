# agent-workbench: bd mode

bd mode is the CLI client for `bd-svc`, the HTTP service on
`127.0.0.1:9101` that owns `$BEADS_HUB_DIR` or `$HOME/.beads-hub` and runs
the `bd` binary. There is no filesystem fallback: if `bd-svc` is down, the
CLI fails loudly, printing the `bd-svc` endpoint URL plus the HTTP status
and body.

Documented invocation form:

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd <verb>
```

Response shape for every verb: one JSON object on stdout with keys `ok`,
`returncode`, `stdout`, `stderr`, where `stdout` is the parsed `bd --json`
payload -- an object for hub verbs, a list of issue objects for
list/show/ready/search/dep.

## Never verify against the live stack

Never probe the live bd-svc (port 9101, the real `~/.beads-hub`) to verify
a change works -- that leaves permanent residue in the real board hub. See
`SKILL.md` for the ephemeral-service verification rule and how to invoke
it (`scripts/ephemeral-service.py bd -- ...`) from a repo checkout;
`--help` documents the mechanics.

## Hub verbs

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd init
$HOME/.claude/skills/agent-workbench/agent-workbench bd add NAME [PREFIX]
$HOME/.claude/skills/agent-workbench/agent-workbench bd sync
$HOME/.claude/skills/agent-workbench/agent-workbench bd repos
$HOME/.claude/skills/agent-workbench/agent-workbench bd path NAME
$HOME/.claude/skills/agent-workbench/agent-workbench bd status
```

## Issue verbs

`--board B` is REQUIRED on every issue verb below. There is no default
board anymore. The old default was `hub`, which silently misfiled issues
onto the read-only aggregator -- that is exactly how issue `hub-ltr` got
stranded on `hub`. Always name the real project board.

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd list --board B [--status S] [--assignee A] [--label L]... [--limit N] [--all]
$HOME/.claude/skills/agent-workbench/agent-workbench bd show ID --board B
$HOME/.claude/skills/agent-workbench/agent-workbench bd children ID --board B
$HOME/.claude/skills/agent-workbench/agent-workbench bd ready --board B [--assignee A] [--label L]... [--limit N]
$HOME/.claude/skills/agent-workbench/agent-workbench bd search QUERY --board B [--status S] [--limit N]
$HOME/.claude/skills/agent-workbench/agent-workbench bd dep ID --board B [--direction up|down] [--type T]
$HOME/.claude/skills/agent-workbench/agent-workbench bd create TITLE --board B [-d DESC] [-p N] [-l LABEL]... [--parent ID] [--assignee A]
$HOME/.claude/skills/agent-workbench/agent-workbench bd update ID --board B [--status S] [--assignee A] [-p N] [-d DESC] [--overwrite-description] [--add-label L]... [--remove-label L]... [--claim]
$HOME/.claude/skills/agent-workbench/agent-workbench bd close ID --board B [--reason R]
$HOME/.claude/skills/agent-workbench/agent-workbench bd note ID TEXT --board B
$HOME/.claude/skills/agent-workbench/agent-workbench bd link FROM_ID TO_ID --board B [--type T]
$HOME/.claude/skills/agent-workbench/agent-workbench bd priority ID N --board B
```

Valid `--status` values: `open`, `in_progress`, `blocked`, `deferred`,
`closed`, `pinned`, `hooked`.

Valid `--type` link types (for `link` and `dep`): `blocks`, `tracks`,
`related`, `parent-child`, `discovered-from`.

`-p/--priority` is `0`-`4`. `--limit` is `1`-`500`.

## `hub` is read-only

`hub` is a read-only aggregate hydrated by `bd sync`. `bd-svc` REFUSES
every issue WRITE addressed to board `hub` at the service layer with a
400, regardless of what the CLI sends: `create`, `update`, `close`,
`note`, `link`, `priority`. READS against `--board hub` are fine and are
the point of the aggregate: `bd list --board hub`, `bd show`, `bd
children`, `bd ready`, `bd search`, `bd dep`. Write to the project board,
then `bd sync`.

## The three new verbs

`bd ready --board B` lists work that is actually claimable: open issues
with no active blocker. It excludes `in_progress`, `blocked`, `deferred`,
and `hooked`. `bd list --board B --status open` does NOT do this: it
returns blocked issues as if they were claimable. `bd ready` is the
correct verb for "what can I pick up" -- it's what makes the `blocks`
links written by `bd link ... --type blocks` actually consumable.

`bd search QUERY --board B` searches titles and IDs. Excludes closed
issues unless `--status closed` is passed.

`bd dep ID --board B` lists dependency edges for an issue. `--direction
down` (default) is what ID depends on; `--direction up` is what depends
on ID. `--type` filters to one link type.

## `bd update -d` overwrite semantics

`-d/--description` on `bd update` REPLACES the issue's entire
description. It is not append. Live issues carry long scope-correction
history in their descriptions, and a naive `-d` destroys it. `bd-svc`
refuses to replace a NON-EMPTY description unless `--overwrite-description`
is also passed:

```bash
# Blocked without the flag if the issue already has a non-empty description:
$HOME/.claude/skills/agent-workbench/agent-workbench bd update ID --board B -d "new description"
# Forces the replacement:
$HOME/.claude/skills/agent-workbench/agent-workbench bd update ID --board B -d "new description" --overwrite-description
```

To ADD context to an issue instead, use `bd note`, which appends rather
than replacing:

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd note ID "extra context" --board B
```

## The board UI

The board UI is the always-on compose `bdui` service, published at
`http://127.0.0.1:3100/`. It serves the bd **hub aggregator** board (the
cross-project view) via the `${HOME}/.beads-hub` mount, built from
`scripts/bdui-container/Containerfile`. Bring it up with
`podman-compose -f docker-compose.yml up -d`. There is no per-repo board
UI and no CLI verb for it.

Board resolution for any verb is `bd path NAME`, which POSTs `/hub/path`;
a 404 means there is no hub board of that name.

## Deletion is out-of-band

Deletion is a deliberate HUMAN out-of-band operation. There is no delete
verb and no delete route, by decision.

Delete an issue (destructive, no undo; also strips its dependency links
and rewrites references to `[deleted:ID]`):

```bash
BEADS_DIR="$HOME/.beads-hub/<board>/.beads" bd delete <issue-id> --force
```

Preview first with `--dry-run` instead of `--force`.

Delete a whole board: unregister it from the aggregator, then remove its
directory:

```bash
BEADS_DIR="$HOME/.beads-hub/hub/.beads" bd repo remove "$HOME/.beads-hub/<board>"
rm -rf "$HOME/.beads-hub/<board>"
BEADS_DIR="$HOME/.beads-hub/hub/.beads" bd repo sync
```

Known residue a human may want to clear, as of this writing:

- issue `hub-ltr` on the `hub` board (stranded by the old `--board hub`
  default)
- throwaway boards `aw-skill-port-init-git-throwaway`,
  `aw-skill-port-init-throwaway`, `aw-skill-port-throwaway-test`,
  `bdws-probe`

Do not delete any of this from within bd mode. These are named here only
so a human knows what to clean up.
