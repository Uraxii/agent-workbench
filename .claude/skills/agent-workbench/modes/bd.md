# agent-workbench: bd mode

bd mode is the CLI client for `bd-serve`, the HTTP service on
`127.0.0.1:9101` that owns `$BEADS_HUB_DIR` or `$HOME/.beads-hub` and runs
the `bd` binary. There is no filesystem fallback: if `bd-serve` is down, CLI
commands fail loudly with the endpoint URL and the connection error.

Documented invocation form:

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd <verb>
```

Hub verbs:

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd init
$HOME/.claude/skills/agent-workbench/agent-workbench bd add NAME [PREFIX]
$HOME/.claude/skills/agent-workbench/agent-workbench bd sync
$HOME/.claude/skills/agent-workbench/agent-workbench bd repos
$HOME/.claude/skills/agent-workbench/agent-workbench bd path NAME
$HOME/.claude/skills/agent-workbench/agent-workbench bd status
```

Issue verbs:

```bash
$HOME/.claude/skills/agent-workbench/agent-workbench bd list [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd show ID [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd create TITLE [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd update ID [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd close ID [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd note ID TEXT [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd link FROM_ID TO_ID [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd children ID [--board B]
$HOME/.claude/skills/agent-workbench/agent-workbench bd priority ID N [--board B]
```

`bd list` now means issue listing, matching bd's natural verb. The old hub repo
listing behavior moved to `bd repos`.

`bd`'s `ui-*` verbs validate the hub board (`$HUB_ROOT/<name>/.beads`),
not a stale repo-local `<repo>/.beads`.

## Two bd UIs, not one

There are two distinct ways to view a bd board, and they are not the
same thing:

- **`$HOME/.claude/skills/agent-workbench/agent-workbench bd ui-up [REPO_DIR]`**
  -- bare-host, per-repo
  dev-workstation tool. Scans a free port and shows one project's own
  board. Use this for ad-hoc local inspection of a single repo.
- **`bdui` (the always-on compose service)** -- brought up by
  `docker-compose.yml` alongside kb-serve and artifact-serve, and
  published at `http://127.0.0.1:3100/`. It serves the
  bd **hub aggregator** board (the cross-project view, not a single
  repo) via the `${HOME}/.beads-hub` mount. Bring it up with
  `podman-compose -f docker-compose.yml up -d` (on by default in
  compose, no profile gate). It is built from
  `scripts/bdui-container/Containerfile`.

Use `bd ui-up` for a quick look at one repo's board; use the always-on
`bdui` service for the standing cross-project hub view.
