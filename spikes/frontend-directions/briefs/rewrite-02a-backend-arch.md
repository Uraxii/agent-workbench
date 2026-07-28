# Rewrite phase 2a: C#/.NET backend architecture doc

Scoped worker in an isolated git worktree. Produce ONE doc, commit, stop. Do NOT merge, do NOT remove the worktree, do NOT touch other files. Board ticket: agent-workbench-7pi.

## Output discipline

- Narration: caveman-ultra terse, paths exact, under 4 lines, no preamble. No em-dashes.
- Deliverable is a Markdown doc: NORMAL clear English, tables where useful. Under ~650 lines.

## Read first

- `docs/design/artifact-server-parity-spec.md` (the ground-truth contract, present in your worktree). This is the primary input.
- `~/.claude/rules/csharp.md` and `~/.claude/rules/code-naming.md` (absolute paths, outside worktree) BEFORE proposing any names or structure.

## Deliverable: `docs/design/artifact-server-backend-architecture.md`

Design the C#/.NET backend that replaces `review-serve.py` with 100% parity. Cover:

1. **Stack + layout.** ASP.NET Core (minimal APIs unless you justify MVC). Project directory `apps/artifact-review/backend/`. Solution/project files, folder structure, key NuGet deps (Microsoft.Data.Sqlite for the existing DB; no heavyweight ORM unless justified). Idiomatic .NET, YAGNI, shortest working structure.
2. **API contract.** One table mapping EVERY parity endpoint to its .NET handler (method, route, request DTO, response DTO, status codes). Default: match the existing contract exactly so the `artifact-svc` skill keeps working unchanged. Flag any endpoint you propose to improve and state the lockstep skill-doc change it forces.
3. **Data layer.** Read/write the sqlite DB (`~/.local/share/artifacts/feedback.db`) and service-owned artifact dirs, so HTTP publish and feedback keep working through the agent-workbench artifact CLI. Document the schema mapping, connection handling, and the bd-board mirror behavior (keep it, or re-decide with justification).
4. **Static + artifact serving.** Serve the React SPA static bundle. Serve staged artifacts and the deep-zoom/tile routes. Artifact-id resolution + staging path mapping per the parity spec.
5. **Publish safety (agent-workbench-wxh) — REQUIRED decision.** The publish path serves user-supplied HTML/SVG/JS same-origin against a no-auth UI = stored XSS. PICK one mitigation and justify it: (a) sandbox CSP that disables script + plugins on the raw artifact route, (b) serve raw artifacts from a separate origin/port, or (c) restrict publish to non-active types. Specify exact headers/config. This is a trust-boundary choice; make it explicit and safe from day one.
6. **SSRF guard.** For ANY server-side fetch, resolve destination and reject loopback/private/link-local/metadata `169.254.169.254`/CGNAT `100.64.0.0/10`, on the initial URL AND every redirect hop. Reference the `scripts/kb-clip.py` fix `h5u` pattern.
7. **Container hardening plan.** Slim, digest-pinned .NET base image; read-only rootfs; `cap_drop: ALL`; `no-new-privileges`; healthcheck; bind `127.0.0.1:9099`; mounts NARROWED to only `/tmp/artifacts` + `~/.local/share/artifacts` (NO `$HOME`-wide mount). Host `tailscale serve --https=443` stays in front; NEVER add a path that tears down host tailscale.
8. **Build/test seams.** How the backend is built, run locally, and tested (API tests proving the publish->viewer->feedback loop).

Design only; do not write implementation code. Provide enough that implementation workers can each take a slice.

## When done

Commit ONLY `docs/design/artifact-server-backend-architecture.md`. Do NOT merge or clean up. Return 3-line summary: doc path, the publish-safety mitigation you chose, any open risk.
