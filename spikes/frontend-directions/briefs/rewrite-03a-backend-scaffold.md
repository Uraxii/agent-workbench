# Rewrite phase 3a: scaffold the C#/.NET backend project (container-verified build)

Scoped worker in an isolated git worktree. Create the project skeleton, verify it builds INSIDE a container, commit, stop. Do NOT merge, do NOT remove the worktree. Board ticket: agent-workbench-m5a (epic).

## Output discipline
Narration caveman-ultra terse, paths exact, under 4 lines. Code + config NORMAL. No em-dashes.

## Read first
- `docs/design/artifact-server-backend-architecture.md` (present in worktree) - THE plan. Follow its project layout, stack, and config exactly.
- `~/.claude/rules/csharp.md` and `~/.claude/rules/code-naming.md` (absolute paths) before writing.

## Toolchain reality (critical)
The host has NO dotnet SDK (immutable OS). You MUST build and verify inside the official .NET SDK CONTAINER via podman. Use the latest LTS .NET whose SDK image pulls successfully (try `mcr.microsoft.com/dotnet/sdk:10.0`, fall back to `:8.0` LTS if 10 will not pull). Example verify:
```
podman run --rm -v "$PWD/apps/artifact-review/backend":/src:Z -w /src <sdk-image> dotnet build
```
Report the exact .NET version + SDK image you used and paste the final `dotnet build` success line.

## Task
Create `apps/artifact-review/backend/` per the architecture doc:
- Solution + `ArtifactReview.Backend.csproj` (ASP.NET Core Minimal API), target the chosen LTS TFM.
- `Program.cs`: Kestrel bind from `REVIEW_SERVE_HOST` (default `127.0.0.1`) + `REVIEW_SERVE_PORT` (default `9099`); a health route `GET /` returning 200; a static-file serving stub for the SPA (`wwwroot/`).
- The folder structure the doc specifies (endpoints, data, publish policy, etc.) as EMPTY or minimally-stubbed files with TODO markers - do NOT implement endpoints beyond health yet. This is the compiling skeleton only.
- The test project skeleton `ArtifactReview.Backend.Tests.csproj` that builds.
- Add `apps/artifact-review/backend/**/bin/` and `**/obj/` to `.gitignore`.

## Gitignore + commit hygiene
Commit ONLY source + project files. NEVER commit `bin/`, `obj/`, or restored packages. Use explicit `git add` of the scaffold files, never `git add -A`.

## When done
Commit the backend scaffold in ONE commit. Do NOT merge or clean up. Return 3 lines: .NET version + SDK image used, `dotnet build` result (VERIFIED or the exact error), and the health-route path.
