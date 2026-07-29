---
name: agent-workbench
description: Locally deployable agent workbench (knowledgebase vault + bd board hub + bdui web front end + hardened kb-svc/artifact-review containers) driven by ONE pure-Python CLI. Use to run knowledgebase clip/put/query, manage bd boards under the central hub, launch the board web UI, scaffold a repo's agent workspace, or record/audit an architectural or scope decision the moment it's settled ("record decision", "we decided", "log this decision").
---

# agent-workbench

One skill, one executable. Every tool is pure Python
(argparse, stdlib + the two pre-existing lxml/readability deps kb-clip
already used). No bash, no `.sh` shims. The CLI lives BESIDE the hardened
container, never inside its image.

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW <subcommand> [ARGS]
```

## Subcommands

| Subcommand | Purpose |
|---|---|
| `kb` | knowledgebase service client (see modes/kb.md for verbs and detailed walkthrough) |
| `bd` | bd board hub + bdui web front end (see modes/bd.md for verbs and detailed walkthrough) |
| `artifact` | artifact review service client (see modes/artifact.md for verbs and detailed walkthrough) |
| `install` | (un)install this repo's skill into `$HOME/.claude/skills/agent-workbench` |
| `init-workspace` | scaffold docs/kb + workstreams + bd board into a repo |
| `doctor` | prerequisite checks and install diagnostics |

For the full verb list and invocation examples for each subcommand family,
see the corresponding mode doc:
- `modes/kb.md` for kb verbs (clip/put/query/atomize/decision/enrich/embed/etc)
- `modes/bd.md` for bd verbs (init/add/sync/repos/path/status + issue operations + ui status)
- `modes/artifact.md` for artifact verbs (publish/feedback/status + new comment/reply/resolve)

## Verification goes through `scratch`, never the live stack

Probing the live stack (curling `127.0.0.1:9099`/`9100`/`9101`, or any
`kb`/`bd`/`artifact` verb with no `KB_SVC_*`/`BD_SVC_*`/`ARTIFACT_SVC_*`
override) to verify a change is NOT an acceptable verification method. It
permanently mutates the real vault, the real board hub, or the real
artifact store. HTTP-surface verification of kb-svc/bd-svc/artifact-svc
goes through `scripts/scratch.py` instead -- this is repo dev/test
tooling, NOT a CLI verb (the shipped CLI is a pure HTTP client with no
container-runtime access), so it only exists in a repo checkout; a
copy-installed skill has no repo beside it and should not be verifying
services at all:

```bash
scripts/scratch.py <kb|bd|artifact> [--no-build] -- <command...>
```

This brings up ONE throwaway container for that service against a fresh
temp data dir on a random free host port, exports the same
`KB_SVC_HOST`/`KB_SVC_PORT` (etc.) env vars the `kb`/`bd`/`artifact`
clients already read so `<command...>` transparently talks to the scratch
instance, runs it, and tears the container + temp dir down in a `finally`
-- self-cleaning even on failure or Ctrl-C. Exit code is the command's
exit code. There is no separate up/down mode.

Scratch runs its own `localhost/<service>:scratch` image tag, never
`:latest` -- a scratch verification can never silently run whatever the
live stack happens to have pinned, and there's no reason to retag
`:latest` just to get a fresh one. That tag alone does NOT guarantee
freshness: `podman-compose up -d` only builds a missing image, so a
`:scratch` tag left over from an earlier branch would otherwise be
reused forever. Freshness instead comes from scratch building the image
from the working tree by default on EVERY run; pass `--no-build` only
when you already know the tag is current (a no-change rebuild is a
layer-cache hit, seconds, not the multi-minute cost of a cold build).
Every run prints the image actually used to stderr as a tripwire:

```
scratch: kb-svc image localhost/kb-svc:scratch id <sha> created <timestamp>
```

**`scratch` isolates only the ONE service named at invocation.** The
other two services are pointed at a `.invalid` sentinel host, so a call
to them fails immediately with a DNS error naming the cause (e.g.
`bd-svc-not-started-by-this-scratch-run.invalid`) instead of silently
reaching the live stack. Do NOT chain a call to a different service
inside the wrapped command (`scratch.py bd -- ... && $AW kb ...` will
fail loudly, by design), and do not nest `scratch` runs -- there is no
bookkeeping to keep an outer run's service live inside an inner one, so a
nested call re-sentinels it and fails loudly on the `.invalid` DNS error.

**There is therefore no supported way to probe two services in one
`scratch` run.** Run `scratch` once per service. Within a single run you
can chain as many steps as you like against *that* service, e.g.
`-- bash -c 'first && second'`.

Requires a repo checkout (it reuses `docker-compose.yml` +
`docker-compose.scratch.yml` at the repo root) and `podman-compose` on
PATH; fails loudly and non-zero, never falling back to the live stack, if
either is missing. See `modes/kb.md`, `modes/bd.md`, `modes/artifact.md`
for a worked example against each service.

## install / init-workspace

```bash
$AW install --copy
$AW init-workspace [TARGET_DIR] [--prefix PREFIX]
```

`install` puts this repo's skill dir at
`$HOME/.claude/skills/agent-workbench`. `--copy` is the production
install: a real copy pinned to the source commit, stamped into a marker
file the CLI reads back. `--link` is a dev symlink, and it makes the
installed skill track whatever branch that working tree has checked out
-- that's why `--copy` is the default recommendation. `--uninstall`
removes a repo-owned install (symlink or stamped copy).

A `--copy` reinstall produces **exactly** the source tree: a module the
source has since deleted does not survive the upgrade. It only ever
replaces its own installs. If the target is a real directory with no
marker, or is not a directory at all, it refuses, leaves the target
untouched, and **exits 1** -- move the path aside yourself and re-run:

```
$ $AW install --copy
agent-workbench: refusing to overwrite /home/you/.claude/skills/agent-workbench
 -- real dir with no install marker, not this repo's own copy install.
 Move it aside yourself, then re-run install --copy.
$ echo $?
1
```

`doctor` reports which install shape you have and compares the pinned
commit against the source repo the marker records:

```
[OK]   skill install: pinned at c1b549c5c5af, matches repo HEAD
[WARN] skill install: stale -- installed at deadbeefdead, repo HEAD is now c1b549c5c5af
[WARN] skill install: pinned at deadbeefdead, installed from /gone/repo which no longer exists; staleness could not be checked
```

A check that could not actually compare is always `[WARN]`, never `[OK]`.

`init-workspace` scaffolds `docs/kb/` +
`workstreams/` + a bd board into a target repo. It builds no repo-local
search index: the searchable knowledgebase is the vault under `KB_HOME`,
indexed by the one indexer (`scripts/kb-index.py`) and searched with
`kb query`. Bringing the stack up is not a CLI verb either: see
"Deploy + hardening" below.

## How it differs from the old scripts

**Pure Python, single entrypoint.** The five separate shell scripts
collapse into one executable with subcommands. The `kb` family is now an
HTTP client of the knowledgebase service (which owns the vault outright
-- no CLI code touches it), and `artifact` is the same shape against the
artifact review service; the `bd` family (former `hub`/`board`) and
`init-workspace` are genuine rewrites. kb- and bd-specific audit fixes
are documented in their own mode docs above.

## Deploy + hardening

`docker-compose.yml` at the repo root is the ONE supported way to bring
the stack up. There is no `deploy` subcommand and no systemd quadlet
layer: the CLI never starts, stops, or builds a container.

```bash
podman-compose -f docker-compose.yml up -d               # kb-svc + bd-svc + artifact-svc + bdui
podman-compose --profile n8n -f docker-compose.yml up -d # adds n8n
docker compose -f docker-compose.yml up -d               # same file, docker host
docker-compose -f docker-compose.yml up -d               # standalone binary, docker host
```

The compose file carries the hardening (read-only rootfs, `cap-drop=ALL`,
`no-new-privileges`, seccomp default, digest-pinned base image,
HEALTHCHECK, narrowed mounts, ports bound to 127.0.0.1, the pinned n8n
image digest). n8n sits behind a `profiles: ["n8n"]` entry, so a plain
compose-up matches its intentionally-down state. Hardening rationale and
the env config surface are documented in
`docs/agent-workbench-hardening-plan.md`.

bdui (the bd board web front end) is on by default in compose and
publishes at `http://127.0.0.1:3100`. See `modes/bd.md` for details.

Optional data-root overrides live in
`$HOME/.claude/skills/agent-workbench/agent-workbench.env.example`. NOTE:
`KB_HOME` / `ARTIFACTS_HOME` are NOT functional overrides once the
containers are running (compose binds the paths at container start); only
`BEADS_HUB_DIR` is read directly by the Python code. See the env.example
comments.

artifact-svc's publish endpoint is enabled and loopback-only (127.0.0.1-bound).
It is driven by `artifact publish` and is the only publish path.
See `modes/artifact.md` for the full detail.

## n8n Public API

n8n integration is currently inactive and not driven through this CLI.
See https://github.com/TODO/agent-workbench/issues/TODO for status.
