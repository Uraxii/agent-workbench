# Rewrite phase 2a (redo for Django): backend architecture doc

Scoped worker in an isolated git worktree. Produce ONE doc (OVERWRITE the existing C# one), commit, stop. Do NOT merge, do NOT remove the worktree. Board ticket: agent-workbench-zua.

## Output discipline
Narration caveman-ultra terse, paths exact, under 4 lines, no preamble. No em-dashes. Doc in NORMAL English, tables where useful, under ~650 lines.

## Context: backend is now DJANGO (Python), not C#/.NET
The user changed the backend stack to Django. Everything else stands: the parity spec, the publish-safety decision, and the React/TS frontend are unchanged. You are REPLACING the C#/.NET backend design with a Django design.

## Read first
- `docs/design/artifact-server-parity-spec.md` (ground-truth contract, present in worktree). Primary input.
- `docs/design/artifact-server-backend-architecture.md` (the OLD C# design you are overwriting; read for the endpoint/DB/hardening intent, then replace with Django).
- `~/.knowledgebase/agent-workbench/decisions/artifact-server-publish-safety__2026-07-25.md` (absolute path) - the publish-safety + sandbox-CSP decision that BINDS this design.
- `~/.claude/rules/python.md` and `~/.claude/rules/code-naming.md` (absolute paths) before writing.

## Deliverable: OVERWRITE `docs/design/artifact-server-backend-architecture.md` with the Django design

Cover:
1. **Stack + layout.** Django. Decide plainly (ponytail: prefer minimal) whether to use plain Django views + JsonResponse or Django REST Framework; justify. Project directory `apps/artifact-review/backend/`. Layout: project package, one app, settings, urls, views, models, wsgi/asgi. Key deps kept minimal. The HOST HAS python3 (3.14) so local build/run/test needs NO container.
2. **API contract.** One table mapping EVERY parity endpoint to its Django URL + view (method, route, request shape, response shape, status codes). Default: match the existing contract EXACTLY so the `artifact-serve` skill keeps working unchanged. Flag any endpoint you propose to add/improve (e.g. the Ledger cross-artifact summary endpoint, ticket agent-workbench-vrf) and the lockstep skill-doc change it forces.
3. **Data layer.** Bind the SAME existing sqlite DB `~/.local/share/claude-artifacts/feedback.db` (configure `DATABASES`), with `managed = False` models + explicit `db_table`/columns mapping the existing schema (artifact_index, comment, thread, ...), so the existing push + feedback CLIs keep working with zero change. Do NOT let Django migrations recreate or alter these tables. Document the bd-board mirror behavior (keep it).
4. **Static + artifact serving.** Serve the React SPA bundle (a catch-all view returning index.html + static assets). Serve staged artifacts + the deep-zoom/tile routes + code/text viewer, with artifact-id resolution + staging path mapping per the parity spec.
5. **Publish safety (BINDING, agent-workbench-wxh + c8x).** HTTP publish restricted to non-active types, disabled by default (`REVIEW_SERVE_PUBLISH_ENABLED=0`), path-traversal validated, `X-Content-Type-Options: nosniff`. SEPARATELY: the raw-artifact serving route MUST send a restrictive sandbox CSP (`sandbox; default-src 'none'; script-src 'none'; object-src 'none'` or equivalent) so CLI-pushed HTML/SVG reports cannot execute script on the no-auth same origin. Specify exact Django middleware/response-header wiring.
6. **SSRF guard.** Any server-side fetch resolves destination + rejects loopback/private/link-local/metadata `169.254.169.254`/CGNAT `100.64.0.0/10` on the initial URL and every redirect hop (reference `scripts/kb-clip.py` fix `h5u`).
7. **Serving/runtime + hardening.** WSGI/ASGI server (gunicorn or uvicorn), bind `127.0.0.1:9099` via `REVIEW_SERVE_HOST`/`REVIEW_SERVE_PORT`. Container: slim python base pinned by digest, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, healthcheck, mounts NARROWED to only `/tmp/claude-artifacts` + `~/.local/share/claude-artifacts` (NO `$HOME`-wide mount). Host `tailscale serve --https=443` stays; NEVER add a path that tears down host tailscale.
8. **Build/test seams.** Local run (`python manage.py runserver` / gunicorn) and tests (Django test client proving the publish->viewer->feedback loop) - all runnable on the host with python3, no container.

Design only; no implementation code. Provide enough that implementation workers can each take a slice.

## When done
OVERWRITE and commit ONLY `docs/design/artifact-server-backend-architecture.md`. Do NOT merge or clean up. Return 3 lines: framework choice (plain Django vs DRF) + why, the publish-safety wiring summary, any open risk.
