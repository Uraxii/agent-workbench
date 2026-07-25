# Round 6: build the UNIFIED artifact-review app mockup (one shell, three switchable modes)

You are a scoped worker in an isolated git worktree. Do exactly this one task, commit it, stop. Do NOT merge, do NOT remove the worktree, do NOT touch any other file or branch.

## Output discipline (binding)

- Any narration: caveman-ultra terse, technical terms/paths exact, under 4 lines, outcome first, no preamble.
- Deliverable is an HTML file: NORMAL clean human-readable HTML/CSS, comments in normal English. No em-dashes.
- Keep the file under ~800 lines. Dedupe aggressively (declare shared fonts, symbols, tokens, and scripts ONCE).

## Task

Build ONE new file: `spikes/frontend-directions/direction-unified-app.html`

It is a single application shell with a top-bar MODE SWITCHER offering three view modes. The user reviewed four separate direction mockups and chose to unify three of them into one app. You are assembling that unified app by REUSING the layouts from three existing, approved mockups (read all three fully first, they are in your worktree):

- `spikes/frontend-directions/direction-unified-inspector.html`  -> Inspector mode
- `spikes/frontend-directions/direction-compare-bench.html`      -> Compare mode
- `spikes/frontend-directions/direction-feedback-ledger.html`    -> Ledger mode

These three files ALREADY share the exact same OKLCH paper-document token system, the light/dark theme toggle, the same fonts, and overlapping Phosphor symbol sets. Your job is to compose them into one coherent shell, not to redesign them.

## The unified shell

- A shared TOP BAR containing: the app/artifact identity as a quiet caption (not a telemetry readout), a MODE SWITCHER (three controls: `Inspector`, `Compare`, `Ledger`, with the active one visibly selected and a keyboard hint each, e.g. `1` `2` `3`), and the theme toggle (sun/moon, `T`).
- A persistent left WORK QUEUE, shared across all modes (reuse the one from direction-unified-inspector).
- The main area is the mode-specific content:
  - Inspector (DEFAULT landing mode): centered artifact viewer that swaps by artifact type, with a right thread/context rail. Extra data/context lives in the side rails. From direction-unified-inspector.
  - Compare: two side-by-side artifact panes plus a version spine; each thread is tagged with the version it was raised against and its status in the candidate. From direction-compare-bench.
  - Ledger: a cross-artifact feedback ledger of open findings as the hero, with bulk multi-select actions; the artifact shows as context. From direction-feedback-ledger.
- Keep the shared thread model, resolve loop, and keyboard hints consistent across modes. Preserve accessibility: `aria-label`s, `.sr-only`, visible focus outlines, status that survives grayscale (icon + shape + text).

## Static layout for the taste gate (important)

This is a STATIC screenshot mockup. Render all three modes VISIBLE by stacking them as three labeled panels down the page (like the existing mockups stack their sections):

- Panel 1 header: `Mode: Inspector`, then the full Inspector app view.
- Panel 2 header: `Mode: Compare`, then the full Compare app view.
- Panel 3 header: `Mode: Ledger`, then the full Ledger app view.

Each panel is one complete app screen for that mode: the shared top bar (with its own mode-switcher showing THAT mode active) + the shared left work queue + the mode's main area and rails. Use a FIXED panel height via a `--section-height:900px` token (do NOT use `100vh`, it balloons the screenshot). The mode switcher must be a real control (wire it with a small script so it works in a live browser), but the static page shows all three stacked so the reviewer sees every mode at once.

## Theme + tokens (reuse verbatim, identical to the three source files)

Reuse the shared `:root` light token block and the `[data-theme="dark"]` warm-workbench override already present in the three source files, plus the sun/moon theme-toggle script. Do NOT invent new palette variables or new SVG path data; reuse the inlined Phosphor symbols from the source files (dedupe duplicates). Dark theme stays warm-workbench, never cockpit.

## Bans + gate

Read `docs/design/avoiding-ai-generated-ui-tells.md` and pass its checklist in BOTH themes. Bans: no Tailwind slate, no generic AI blue, no uniform large radius, no gradient glow, no glassmorphism, no decorative shadows, no emoji icons, no cockpit vocabulary (meters, scopes, telemetry strips, LED dots, dense readout headers, monospace-everywhere). Metadata reads as a quiet caption. Verify WCAG 4.5:1 for text in both themes. Monospace only for IDs, versions, counts, timestamps, keys, and code.

## Asset rules

- Keep relative asset paths unchanged: `assets/fonts/*.woff2`, `assets/sample-artifact.png`. Those files are untracked and absent from this worktree but exist at render time. Do not change paths, do not fetch or create them, keep the three self-hosted font families.

## When done

- Commit ONLY `spikes/frontend-directions/direction-unified-app.html`. Do NOT merge, do NOT remove the worktree, do NOT stage anything else. Stop after commit.
- Return a 3-line summary: confirm the three modes compose in one shell with a working switcher, the light + warm-workbench dark themes + toggle work, and the anti-slop checklist passed.
