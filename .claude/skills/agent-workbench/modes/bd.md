# agent-workbench: bd mode

bd board hub (init/add/sync/list/path/status) + bdui web front end
(ui-up/ui-down/ui-status). Replaces `scripts/beads-hub.sh` +
`scripts/board-ui.sh`.

```bash
agent-workbench bd add <name> [prefix]
agent-workbench bd ui-up [REPO_DIR]        # prints the UI URL
```

`bd`'s `ui-*` verbs validate the hub board (`$HUB_ROOT/<name>/.beads`),
not a stale repo-local `<repo>/.beads`.

`bd`'s board-hub verbs run `bd init` with `BEADS_DIR` stripped from the
child env so an ambient value cannot redirect where the board is
written, and use a correctly-sensed `git_repo_preexisted` flag for
incidental-repo cleanup.

## Two bd UIs, not one

There are two distinct ways to view a bd board, and they are not the
same thing:

- **`agent-workbench bd ui-up [REPO_DIR]`** -- bare-host, per-repo
  dev-workstation tool. Scans a free port and shows one project's own
  board. Use this for ad-hoc local inspection of a single repo.
- **`bdui` (the always-on compose/quadlet-managed service)** -- a
  `deploy`-managed quadlet unit like kb-serve and artifact-serve, not
  compose-only: `deploy up` builds `localhost/bdui:latest`, installs
  `scripts/bdui-container/bdui.container`, and health-checks
  `http://127.0.0.1:3100/`; `deploy down` removes it if this bundle owns
  the installed quadlet. It runs with `UserNS=keep-id` so the
  container's user maps to the real host user, matching ownership of
  the bind-mounted `~/.beads-hub` board files (0700/0600). It serves the
  bd **hub aggregator** board (the cross-project view, not a single
  repo) via the `${HOME}/.beads-hub` mount, and is also reachable via
  `podman-compose -f docker-compose.yml up -d` (on by default in
  compose, no profile gate). Either path publishes at
  `http://127.0.0.1:3100`, built from
  `scripts/bdui-container/Containerfile`.

Use `bd ui-up` for a quick look at one repo's board; use the always-on
`bdui` service for the standing cross-project hub view.
