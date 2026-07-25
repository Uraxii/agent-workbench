# Round 5 probe: re-skin `content-first` artifact review mockup into a LIGHT paper-document feel

You are a scoped worker in an isolated git worktree. Do exactly this one task, commit it, stop. Do NOT merge, do NOT remove the worktree, do NOT touch any other file or branch. The orchestrator reviews your diff and integrates.

## Output discipline (binding, all agents)

- Any narration you emit: caveman-ultra terse (clipped grammar, no filler, technical terms/paths/commands exact). Under 4 lines. Lead with outcome. No preamble, no recap.
- The DELIVERABLE is an HTML file: write it as NORMAL, clean, human-readable HTML/CSS. Comments in normal English. No em-dashes anywhere.
- Keep the file under ~800 lines (it is currently ~97 dense lines; stay compact).

## What this is

Self-hosted artifact review app. A reviewer opens an artifact (image, gallery, HTML report, or code/text), drops threaded resolvable comments anchored to a region/item/block/line, and works a queue. This mockup is ONE of four approved information architectures. It is a static single-file HTML mockup for a human taste gate, not production code.

## The ONE file to rewrite (in place)

`spikes/frontend-directions/direction-content-first.html`

Read it fully first. It is a complete, well-built dark mockup: real inlined Phosphor SVG symbols, real self-hosted fonts, an OKLCH palette. Your job is a VISUAL RE-SKIN only. Preserve the information architecture and every behavior/state it shows. Rewrite the same file in place.

## Preserve EXACTLY (the approved `content-first` IA)

1. Content is dominant; chrome is minimal.
2. The work queue is a SUMMONED OVERLAY (`.queue`) floating over content, never a permanent pane.
3. Threads anchor INLINE to the content they discuss: region pin + thread card on the image, side-thread in the margin of report blocks, line-thread under code lines.
4. An always-visible thread index lives in the bottom action strip.
5. A persistent COMPACT action strip at the bottom carries actions + keyboard hints (`kbd`).
6. FOUR stacked sections prove type-agnosticism and must all remain, in order: (1) single image with region pins, (2) gallery with per-item state, (3) HTML report with block-anchored margin threads, (4) code/text with line-anchored threads. Same queue, same thread model, same resolve loop, same keyboard hints across all four; only the viewer swaps.
7. Keep all accessibility: `aria-label`s, `.sr-only`, visible focus outlines, and status that survives grayscale (icon + shape + text label, never color alone).
8. Keep the legend/footer, updated to describe the new palette and its provenance.

## The NEW feel: LIGHT paper-document (this is the whole point)

Every prior round was dark and read as a "space ship dashboard / cockpit". Kill that entirely. Target:

- LIGHT paper document. Warm near-white paper surfaces, dark warm ink text. This is a light theme, a deliberate departure from every prior dark round.
- Reading-first, calm. The artifact and its comments should read like a marked-up paper document / manuscript with marginalia, not telemetry.
- Low chroma throughout. Generous margins. Near-zero chrome.
- One restrained editorial accent (think a proof-mark ink), low chroma, with stated provenance.
- Serif (Source Serif 4) for reading copy and thread prose. IBM Plex Sans for interface chrome. JetBrains Mono ONLY for IDs, versions, counts, timestamps, keys, and code. Monospace is NOT the body font.

### Remove the cockpit vocabulary (why prior rounds failed)

- No telemetry-strip headers, no meters, no scopes, no LED indicators, no dense readout header. The `.facts` header row must become a QUIET document caption line (e.g. a soft single line of small metadata), not a dashboard readout.
- No glow, no gradients, no glassmorphism, no decorative shadows, no blur, no marketing hero.
- No monospace-everywhere. No neon-on-black.

## Hard ban list (BINDING) + anti-slop gate

Read `docs/design/avoiding-ai-generated-ui-tells.md` and run its pass/fail checklist against your result. Also read `docs/design/artifact-server-design-philosophy.md` (the decision procedure) if you need to break a tie.

Bans: no Tailwind slate ramp, no `#60A5FA` (or any generic AI blue as accent), no single uniform large border-radius, no gradient glow, no glassmorphism, no decorative shadows, no emoji icons.

Color method: build a warm paper OKLCH neutral ramp derived from a REAL named source (state which in the legend, e.g. archival paper / editorial proof marks). One accent with stated provenance. Semantic states (open / resolved / draft) as low-chroma editorial ink marks, each paired with icon + text so they read in grayscale. Verify WCAG: body/reading text at least 4.5:1 against paper, UI text at least 4.5:1. Never hand-pick arbitrary hexes; keep it OKLCH.

## Layout fix (do this, it matters for the screenshot)

The current file uses `min-height:100vh` on `.section` and `height:calc(100vh - 132px)` on the viewer. Replace the 100vh usage with a FIXED section height around 880-920px, and update the viewer/report/code-view/gallery inner heights to fill that fixed height (e.g. `calc(900px - 132px)`). Reason: the taste gate screenshots the full page at a tall window; `100vh` makes each section balloon to the window height and creates huge dead space. Keep `body{min-width:1440px}` and the 1440px section width.

## Icon + asset rules

- REUSE the Phosphor `<symbol>` SVGs already inlined in the file. Do NOT invent new SVG path data. If you genuinely need an icon not already present, prefer reusing an existing symbol instead; do not fabricate paths.
- Keep the relative asset paths unchanged: `assets/fonts/*.woff2` and `assets/sample-artifact.png`. Those files are untracked and absent from this worktree but exist at render time. Do not change the paths, do not try to fetch or create the assets.
- Keep the same three self-hosted font families already declared.

## When done

- Commit ONLY `spikes/frontend-directions/direction-content-first.html` with a clear message (e.g. `Re-skin content-first mockup: light paper-document feel (round 5 probe)`).
- Do NOT merge. Do NOT remove the worktree. Do NOT stage or commit anything else. Stop after the commit.
- Return a 3-line summary: what feel you built, the palette source you named, and confirmation the anti-slop checklist passed.
