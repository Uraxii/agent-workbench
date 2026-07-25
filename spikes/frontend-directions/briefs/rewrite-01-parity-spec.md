# Rewrite phase 1: write the PARITY SPEC for the artifact review server (ground truth)

Scoped worker in an isolated git worktree. Produce ONE document, commit it, stop. Do NOT merge, do NOT remove the worktree, do NOT touch other files. Board ticket: agent-workbench-5u0.

## Output discipline (binding)

- Narration: caveman-ultra terse, technical terms/paths exact, under 4 lines, outcome first, no preamble. No em-dashes anywhere.
- The deliverable is a Markdown doc: write NORMAL, clear, human-readable English. Use tables for endpoint/schema enumerations.
- Keep the doc under ~700 lines. Be comprehensive but compact (tables over prose).

## Why

We are doing a full rewrite: replace the current Python `review-serve.py` with a C#/.NET backend + a React/TS frontend, preserving 100% functional parity and the security/hardening bar. Before any code, we need ONE authoritative spec that captures the EXACT current contract so the rewrite can match it. This doc is that ground truth. Everything downstream (backend architecture, frontend API client, tests) reads it.

## Read these first (all present in your worktree unless noted)

- `.claude/skills/artifact-serve/scripts/review-serve.py`  -> THE server. Read it fully. This is the primary source.
- `~/.claude/skills/artifact-serve/SKILL.md` and `~/.claude/skills/artifact-serve/REFERENCE.md`  -> the consumer contract (publish + feedback CLI). NOTE: these live under `~/.claude/`, outside the repo worktree; read them from that absolute path.
- Locate and read the container/quadlet + compose definitions for the deployed service (search the repo, e.g. under `scripts/`, `.claude/skills/agent-workbench/`, and `docker-compose.yml`). Document the hardening exactly.
- Locate and read the bd-board mirror test (search for `test_review_serve_bd_mirror` or `bd` mirroring in the server) and document the mirror behavior.

## Deliverable: `docs/design/artifact-server-parity-spec.md`

Capture, exactly as they exist today (cite file + line ranges where useful):

1. **HTTP API surface.** One table row per route: method, path (including the `/_/api/...` and `/_/review` and reserved `/_/` namespace), query params, request body shape, response body shape (JSON keys + types), status codes, and side effects. Cover at least: comments, threads (create/reply/resolve), settings, uploads, publish (note it is HELD under ticket agent-workbench-wxh and WHY), static artifact serving, the deep-zoom/image routes, the code/text viewer route, the `/_/review` gallery|image|code dispatch, and the health route (`GET /` -> 200).
2. **Artifact resolution + staging.** How `artifact_id` maps to a staged path, the `/tmp/claude-artifacts/<project>/<subdir>` layout, the symlink staging mechanism, and the push footguns (self-referencing symlink destruction; sources outside container mounts serve 404).
3. **Database schema.** Every table (artifact_index, comment, thread, and any others), columns, types, indexes, and the DB file location (`~/.local/share/claude-artifacts/feedback.db`). How threads/comments/annotations/resolved-state persist. The bd-board mirror behavior (what mirrors, when, to which board).
4. **Viewer tech contract.** How OpenSeadragon (deep zoom) and Annotorious (region pins) are wired today, what the frontend expects from the server (tile sources, annotation storage shape), threaded resolvable comments model.
5. **artifact-serve skill contract.** The exact `push` inputs/outputs and the `feedback --artifact <id>` JSON shape the skill depends on. The new backend MUST keep these working (publish -> stable viewer URL; feedback returns JSON). Quote the expected shapes.
6. **Security + hardening bar (non-negotiable, hard-won).** Container: read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, base image pinned by digest, healthcheck, mounts NARROWED to only the artifact dirs (`/tmp/claude-artifacts` + `~/.local/share/claude-artifacts`, NO `$HOME`-wide mount), bind `127.0.0.1:9099`. The host `tailscale serve --https=443` in front, and the live-service footgun: never add a path that tears down host tailscale. The publish stored-XSS hole (agent-workbench-wxh): same-origin active content (user HTML/SVG/JS) on the no-auth UI; list the three acceptable mitigations (sandbox CSP disabling script on the raw artifact route, OR separate origin/port for raw artifacts, OR restrict to non-active types). The SSRF pattern for any server-side fetch (reject loopback/private/link-local/metadata 169.254.169.254/CGNAT 100.64.0.0/10 on initial URL and every redirect hop; reference `scripts/kb-clip.py` closed fix `h5u`). Trust model: no-auth on trusted tailnet.
7. **Parity checklist.** A final bullet list the rewrite can check off: every behavior that must still work end to end (publish -> viewer URL -> annotate -> comment -> resolve -> feedback JSON).

Do NOT design the new system here. This doc DESCRIBES what exists. Architecture comes next.

## When done

- Commit ONLY `docs/design/artifact-server-parity-spec.md`. Do NOT merge, do NOT remove the worktree, do NOT stage anything else. Stop after commit.
- Return a 3-line summary: doc path, number of endpoints documented, and any contract ambiguity you could not resolve from the source.
