# Rewrite phase 3b: scaffold the React/TS (Vite) frontend project (container-verified build)

Scoped worker in an isolated git worktree. Create the skeleton, verify it builds INSIDE a container, commit, stop. Do NOT merge, do NOT remove the worktree. Board ticket: agent-workbench-m5a (epic).

## Output discipline
Narration caveman-ultra terse, paths exact, under 4 lines. Code + config NORMAL. No em-dashes.

## Read first
- `docs/design/artifact-server-frontend-architecture.md` (present in worktree) - THE plan. Follow its layout, tokens, and component plan.
- `spikes/frontend-directions/direction-unified-app.html` (present in worktree) - the APPROVED design. Port its token system verbatim.
- `~/.claude/rules/typescript.md` and `~/.claude/rules/code-naming.md` (absolute paths) before writing.

## Toolchain reality (critical)
The host has NO node/npm (immutable OS). You MUST build and verify inside a node CONTAINER via podman:
```
podman run --rm -v "$PWD/apps/artifact-review/frontend":/app:Z -w /app node:22 sh -c "npm install && npm run build"
```
Report the node image used and paste the final vite build success line.

## Task
Create `apps/artifact-review/frontend/` per the architecture doc:
- Vite + React + TypeScript project: `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`.
- Design tokens in ONE CSS file (`src/styles/tokens.css`): port the `:root` light block and the `[data-theme="dark"]` Material-dark block VERBATIM from `direction-unified-app.html`, plus spacing/radius/type scales and the three `@font-face` families pointing at `/fonts/*.woff2` (create `public/fonts/.gitkeep`; the actual woff2 files are added separately, do NOT fetch them).
- The sun/moon theme toggle wired to `data-theme` on the document root (port the script from the mockup into a React component/hook).
- `App.tsx`: the unified shell placeholder - top bar with the three mode-switcher tabs (Inspector / Compare / Ledger) + theme toggle, a left work-queue placeholder, and a main area that switches by mode. Stubs are fine; this is the compiling skeleton. Real mode content comes in later slices.
- Ensure `.gitignore` covers `apps/artifact-review/frontend/node_modules/` and `dist/`.

## Gitignore + commit hygiene
Commit ONLY source + config. NEVER commit `node_modules/` or `dist/`. Use explicit `git add`, never `git add -A`.

## When done
Commit the frontend scaffold in ONE commit. Do NOT merge or clean up. Return 3 lines: node image used, `npm run build` result (VERIFIED or exact error), and confirmation the token blocks match the mockup.
