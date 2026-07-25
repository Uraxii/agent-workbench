Task: edit exactly these files.

Target files:
- /var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/scripts/review-serve.py
- /var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/assets/css/theme.css
- /var/home/nicole/Projects/agent-workbench/spikes/frontend-directions/direction-unified-app.html

Read these first:
- /var/home/nicole/Projects/lodestar/workstreams/artifact-service-ui-brief.md
- /var/home/nicole/dotfiles/docs/design/avoiding-ai-generated-ui-tells.md
- /var/home/nicole/Projects/agent-workbench/spikes/frontend-directions/briefs/v5b-dual-theme-SHARED.md
- /var/home/nicole/Projects/agent-workbench/spikes/frontend-directions/direction-unified-app.html
- /var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/scripts/review-serve.py
- /var/home/nicole/Projects/agent-workbench/.claude/skills/artifact-serve/assets/css/theme.css
- /var/home/nicole/Projects/agent-workbench/spikes/review-app/DESIGN.md

Context you must preserve:
- User chose the unified app shape as the base.
- Current unified mock already has the shell and stacked Inspector / Compare / Ledger panels. Keep that base shape and interactions unless a change is needed for the theme creator or improved integrated feedback model.
- The current colors still read too generic / AI-ish, especially the dark theme. Push both the mock and the live review app toward the quiet-canvas direction: near-monochrome warm neutrals, hairline separators, generous whitespace, one muted clay accent, content-first, no loud gradients, no glossy SaaS look, no cockpit feel.
- Theme work in the mock must stay self-contained in the HTML.
- The current review-serve page-comment widget is injected at the bottom of served HTML pages and feels outdated. Remove the footer-style feedback block and integrate feedback into the app more like established collaboration tools.
- Repo has no HEAD commit. Do not commit. Just edit the files.

What to implement:
1. Restyle the existing unified mock away from generic AI-looking dark/material tokens toward a more authored quiet-canvas / warm-workbench system while preserving the IA.
2. Add a built-in theme creator UI inside the mock so the user can test theme axes live.
3. Theme creator must support:
   - light and dark base modes
   - editing core token groups live
   - at minimum: surface tone, text tone, accent hue/intensity, status hue feel, radius, spacing density, and animation speed / motion factor
   - export preset to JSON
   - import preset from JSON
   - local persistence in browser storage
   - reset to the authored default preset
4. In review-serve, remove the outdated bottom-of-page feedback block that is injected before </body> on served HTML pages.
5. Replace it with a more integrated collaboration-style feedback surface. Keep it minimal and robust. Good shapes: a right-side discussion rail, slide-over thread panel, or compact dock that feels native to the app rather than a footer form. It should preserve page-level thread creation and viewing without reading like an old comment dump.
6. Update owned review pages and shared theme styling as needed so feedback feels consistent across gallery, code, viewer, index, and arbitrary pushed HTML pages.
7. Keep keyboard and focus behavior sane. Keep the existing T theme toggle working.

Constraints:
- Use ponytail minimalism. Shortest working diff. YAGNI.
- Edit only the three target files.
- No new files, no asset path changes, no npm, no dependencies.
- No em-dash characters anywhere.
- Human-facing HTML/CSS/JS should stay clean and readable.
- Preserve accessibility and grayscale-safe status signaling.
- Do not invent fake data that changes the artifact-review story.
- Preserve existing page-level thread data model and API behavior unless a tiny compatibility shim is needed.

Success criteria:
- The mock still reads as the same unified artifact-review app, but visually calmer and more authored.
- The dark themes read warm-workbench, not generic dark SaaS.
- Theme creator opens, edits live CSS variables or derived tokens, persists, exports JSON, imports JSON, and resets.
- review-serve no longer appends a stale footer feedback block to every HTML page.
- Feedback is integrated in-app in a way that feels closer to established collaboration tools.
- The edited files remain self-contained and understandable.

Output back to orchestrator:
- 4 short lines only:
  1) what changed visually in the mock
  2) what the theme creator can do
  3) how review-serve feedback integration changed
  4) any limitation or corner-cut
