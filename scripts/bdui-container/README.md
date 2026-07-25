# bdui: web front end for the bd issue tracker

`bdui` (npm package `beads-ui`) is a small local web UI for the `bd`
board: Blocked / Ready / In progress / Closed columns, inline editing,
comments, live reload on DB changes.

This directory holds the npm install (`package.json` +
`package-lock.json`, one dependency: `beads-ui`) and the `bd` CLI
installer (`install-bd.sh`), used two ways:

- Containerized as the `bdui` service in the repo root
  `docker-compose.yml` (see `Containerfile` in this dir). This is the
  primary, always-on path.
- Bare-host, per-repo dev daemon via `agent-workbench board up/down/status`
  (`.claude/skills/agent-workbench/cli/board.py`), which resolves the
  `bdui` binary at `node_modules/.bin/bdui` in this directory. Useful for
  spinning up an isolated UI against one project's board without touching
  the container.

## Install (bare-host use only; the container installs its own copy)

```sh
npm install
bash install-bd.sh   # installs the bd CLI to ~/.local/bin
```

## Write path

beads-ui writes over a websocket at `/ws`. Message types include
`update-status`, `update-assignee`, `update-priority`, `edit-text`,
`create-issue`, `add-comment`. Each one shells out to the `bd` CLI on the
server side, so browser edits are real board edits — confirmed by
driving the websocket directly and checking the result via `bd show` /
`bd comments`.

## Data resolution (verified by reading node_modules/beads-ui's own
source, not documented upstream)

- `bdui start` (the CLI subcommand) always daemonizes: forks a detached
  background process and returns immediately. Not suitable as a
  container's PID 1.
- The foreground entrypoint is `node server/index.js` (the package's own
  `npm start` script, minus `--debug`). It reads `HOST`/`PORT` from env
  vars (default `127.0.0.1:3000`) and never daemonizes.
- Board-data discovery (`server/db.js`) and the live-reload watcher
  (`server/index.js`'s `watchDb`) both walk up from `process.cwd()`
  looking for a `.beads` dir — neither reads a `BEADS_DIR` env var.
- Every `bd` CLI operation triggered from the UI (`server/bd.js`) shells
  out to the actual `bd` binary and does honor `BEADS_DIR` from the
  server's own environment.
- `server/registry-watcher.js` reads/writes
  `$HOME/.beads/registry.json` — a live cross-workspace discovery cache,
  not durable data. `os.homedir()` resolves via `HOME`.

See the `bdui` service block in the repo root `docker-compose.yml` for
how this drives the container's `WORKDIR`, `BEADS_DIR`, and `HOME`.
