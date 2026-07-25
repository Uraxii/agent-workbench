# Rewrite phase 2b: React/TS (Vite) frontend architecture doc

Scoped worker in an isolated git worktree. Produce ONE doc, commit, stop. Do NOT merge, do NOT remove the worktree, do NOT touch other files. Board ticket: agent-workbench-g6n.

## Output discipline

- Narration: caveman-ultra terse, paths exact, under 4 lines, no preamble. No em-dashes.
- Deliverable is a Markdown doc: NORMAL clear English, tables where useful. Under ~650 lines.

## Read first

- `docs/design/artifact-server-parity-spec.md` (server contract the frontend calls, present in your worktree).
- `spikes/frontend-directions/direction-unified-app.html` (THE APPROVED DESIGN, present in your worktree). The real app must reproduce this: one shell, top-bar mode switcher (Inspector / Compare / Ledger), shared work queue, threaded resolvable comments, light + Material dark themes with a toggle. Extract its exact design tokens.
- `~/.claude/rules/typescript.md` and `~/.claude/rules/code-naming.md` (absolute paths) BEFORE proposing names/structure.

## Deliverable: `docs/design/artifact-server-frontend-architecture.md`

Design the React + TypeScript (Vite) SPA, served as a static bundle by the C# backend. Cover:

1. **Stack + layout.** Vite + React + TypeScript. Project directory `apps/artifact-review/frontend/`. Folder structure, key deps (OpenSeadragon for deep zoom; `@annotorious/react` for region pins; keep deps minimal, YAGNI). State approach: prefer built-in React state + a thin API layer over a heavy state library unless justified.
2. **Design-token system.** Port the OKLCH token system from the approved mockup VERBATIM: the `:root` light block and the `[data-theme="dark"]` Material-dark block (neutral elevated greys), spacing/radius/type scales, the three self-hosted fonts (IBM Plex Sans / Source Serif 4 / JetBrains Mono), and the sun/moon theme toggle wired to `data-theme` on the root. Tokens live in ONE place (CSS variables), consumed everywhere. NOT one-off styles.
3. **Component tree.** The unified shell: top bar (identity caption + mode switcher tabs Inspector/Compare/Ledger with keyboard hints + theme toggle), persistent left work queue, and the mode-specific main area. Enumerate reusable primitives (button, kbd hint, panel, card, comment thread, composer, status pill, queue row, gallery tile, version spine row) so the UI reads as ONE system. Map each of the three modes to its component composition per the mockup.
4. **Viewer integration.** How OpenSeadragon mounts for single image (deep zoom) + galleries, how `@annotorious/react` overlays region pins and syncs annotations to the backend, and how report (HTML block anchors) and code/text (line anchors) viewers share the SAME thread + resolve model. Handle the publish-safety constraint from the backend (raw active content is sandboxed/separated); the SPA must respect it.
5. **API client.** A typed client matching every parity endpoint (threads create/reply/resolve, comments, settings, uploads, artifact/tile fetch, feedback). Request/response TypeScript types derived from the parity spec. Loading/empty/error states.
6. **User journey.** Entry -> browse queue -> open artifact -> zoom/annotate -> comment/resolve -> switch modes -> done. Keep chrome recessive, artifact the hero. Accessibility (WCAG contrast in both themes, focus outlines, aria labels, status surviving grayscale) carried from the mockup.
7. **Build seam.** Vite build output path and how the backend serves it; dev proxy to the backend API.

Design only; no implementation code. Provide enough that implementation workers can each take a slice (e.g. shell, each mode, viewer, api-client).

## When done

Commit ONLY `docs/design/artifact-server-frontend-architecture.md`. Do NOT merge or clean up. Return 3-line summary: doc path, component/primitive count, any open risk.
