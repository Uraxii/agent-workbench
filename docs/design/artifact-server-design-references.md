# Artifact Review Server Design References

## Design target

The rewritten review server should feel like a focused professional review desk: the artifact is the hero, the interface is dark, quiet, and fast, and every control earns its place. The best reference products share a few mechanics worth carrying forward: a large uninterrupted canvas, restrained side panels, direct annotation, resolvable threaded feedback, strong keyboard flow, and status that is visible without turning the app into a project-management system.

## Reference products and borrowable patterns

### Frame.io

**What it does well:** Frame.io is the closest product match: media review, comments, version history, and approval state around a large visual artifact. It keeps playback or image content dominant while comments and metadata sit in a disciplined right rail.

**Pattern to borrow:** Use an image-first review layout with a dark top bar of about 48 to 56 px, a collapsible right feedback rail around 360 to 420 px, and a canvas area that fills all remaining space. Comments should be anchored to artifact coordinates, not just listed globally. The selected pin should synchronize with the active thread in the rail, and selecting a thread should pan or highlight the relevant region on the OpenSeadragon canvas.

**Why it fits:** The server must support images, galleries, and HTML reports with annotation pins and threaded comments. Frame.io's mental model, artifact first, feedback second, maps directly to that workflow.

**Trade-off or failure mode:** Frame.io can feel heavy when project, team, approval, and sharing layers pile up. This rewrite should borrow the review surface, not the collaboration suite. Avoid extra status workflows, permission controls, or account chrome that do not matter on a trusted private tailnet.

### Figma comments

**What it does well:** Figma makes comments feel spatial. Pins live on the canvas, unresolved conversations are visible at a glance, and a comment mode separates feedback from editing or navigation.

**Pattern to borrow:** Add a deliberate annotation mode, toggled by a visible toolbar button and a keyboard shortcut such as `C`. In comment mode, clicking the image creates a draft pin and opens a compact thread composer. Pins should show small numbered or avatar-style bubbles, about 24 to 28 px, with a clear active state. Unresolved pins should use the accent color, resolved pins should become low-contrast outlines or disappear behind a resolved filter.

**Why it fits:** Annotorious already provides region annotation primitives. Figma's interaction model gives a simple layer above it: comment mode, place pin, write, resolve, revisit.

**Trade-off or failure mode:** If pins stay fully visible at every zoom level, dense images become noisy. Pins need zoom-aware scaling, clustering at low zoom, and filters for unresolved, mine, all, and resolved.

### GitHub pull request review threads

**What it does well:** GitHub PR review keeps discussion tied to a specific context, shows resolved state clearly, and collapses completed threads without losing history.

**Pattern to borrow:** Treat every annotation thread as a resolvable conversation with a compact header, timestamp, author label, reply count, and a clear `Resolve conversation` action. Resolved threads should collapse to a one-line row in the sidebar and remain restorable. If the underlying artifact version changes later, mark old threads as attached to a previous version rather than silently moving them.

**Why it fits:** Reviewers need to finish work, not merely leave comments. Resolution status turns feedback into a checklist without requiring a full task system.

**Trade-off or failure mode:** GitHub's review batching and file-change machinery would be overkill here. Do not copy request-changes approvals, reviewer assignment, branch status, or code diff metaphors unless artifact versioning later demands them.

### Linear

**What it does well:** Linear's dark interface is dense, fast, and polished without visual clutter. It uses subtle separators, compact typography, command search, and strong keyboard navigation.

**Pattern to borrow:** Use a dark neutral shell with narrow contrast steps: near-black app background, slightly raised panels, hairline borders, and one restrained accent. A left navigation rail, if needed for gallery or artifact list browsing, should be compact, around 240 to 280 px, collapsible, and dominated by titles and status chips rather than thumbnails. Keyboard navigation should support next artifact, previous artifact, focus comments, resolve, and command palette.

**Why it fits:** A self-hosted review server benefits from Linear's professional density. Reviewers can move quickly through many artifacts while the chrome stays quiet.

**Trade-off or failure mode:** Linear's minimalism depends on learned keyboard behavior. If the rewrite hides too much behind shortcuts, occasional reviewers will miss core actions. Every shortcut needs a visible affordance and command palette discoverability.

### Raycast

**What it does well:** Raycast turns complex action sets into a fast command surface. It uses a concise command list, predictable shortcuts, and lightweight previews instead of permanent buttons everywhere.

**Pattern to borrow:** Add a command palette for reviewer actions: jump to artifact, toggle comments, show unresolved only, copy viewer URL, mark all visible threads read, resolve active thread, open raw artifact, and publish feedback JSON. The palette can use a centered modal around 640 px wide with fuzzy search, grouped actions, shortcut hints, and a visible empty state.

**Why it fits:** The app has many useful actions, but most are secondary. A command palette keeps the canvas clean while still making power workflows fast.

**Trade-off or failure mode:** A command palette cannot replace primary controls. Create comment, resolve, next artifact, zoom, and sidebar toggle still need visible buttons or obvious keyboard hints.

### Vercel dashboard

**What it does well:** Vercel presents technical artifacts with crisp status, calm dark surfaces, and strong empty, loading, and error states. It makes deployment results scannable without overwhelming the content.

**Pattern to borrow:** Use clear artifact cards for gallery mode: preview thumbnail, title, type badge, comment count, unresolved count, last updated time, and status. Cards should sit on a dark surface with a subtle border and hover elevation. The active artifact should open into the canvas view, not a modal, so the reviewer has a stable deep-linkable URL.

**Why it fits:** The server serves single images, galleries, and HTML reports. Vercel's card-to-detail rhythm gives a clean path from artifact index to focused review.

**Trade-off or failure mode:** Dashboard cards can become decorative tiles with poor information density. For large artifact sets, provide compact list mode and search, not only a pretty grid.

### Sentry

**What it does well:** Sentry organizes dense diagnostic context around a single issue: title, evidence, event details, tags, timeline, and resolve controls. It balances urgency with traceability.

**Pattern to borrow:** For each artifact, show a slim metadata strip or details drawer with source path, generator run, dimensions, file type, published time, and direct artifact URL. Keep it secondary to comments, but make it available without leaving the review surface. Use status chips for unresolved comments, resolved comments, and artifact type.

**Why it fits:** Generated artifacts often need provenance. Reviewers may need to know which run, prompt, page, or source produced the artifact before leaving useful feedback.

**Trade-off or failure mode:** Sentry's alert and ownership features are not needed for a single-reviewer tailnet tool. Avoid noisy severity, assignment, teams, and notification settings unless a real workflow needs them.

### Stripe dashboard

**What it does well:** Stripe makes dense business data feel controlled through tables, drawers, consistent spacing, and restrained interaction states. Its details views are polished and predictable.

**Pattern to borrow:** Use right-side drawers for secondary artifact metadata, settings, and raw JSON instead of full-page detours. Drawers should be about 420 to 520 px, slide over the right edge, trap focus while open, and close on `Esc`. Tables or lists should use sticky headers, clear row hover, visible selected state, and concise filters.

**Why it fits:** Review tools need occasional data inspection, but the main task remains visual review. Drawers let the user inspect without losing canvas context.

**Trade-off or failure mode:** Stripe's enterprise-grade table density can feel cold and form-heavy. Do not turn a visual review tool into an admin dashboard. Keep tables for artifact lists and logs only.

### Framer

**What it does well:** Framer uses a dark canvas, floating toolbars, and inspectors that recede until needed. It treats the work surface as the main object.

**Pattern to borrow:** Use a floating canvas toolbar for zoom, fit, actual size, pan, annotation mode, and sidebar toggle. Place it near the bottom center or top center of the image viewport, with icon buttons around 36 to 40 px and a translucent dark background. Hide labels by default, reveal them in tooltips, and keep the toolbar out of the artifact's focal area when possible.

**Why it fits:** OpenSeadragon needs direct manipulation controls, but permanent side chrome would fight the image. A floating toolbar makes the canvas feel like a professional review surface.

**Trade-off or failure mode:** Floating controls can cover important image content. They need drag or reposition behavior, auto-hide on idle, or a user setting if overlap becomes annoying.

### Notion

**What it does well:** Notion's comments, breadcrumbs, and lightweight page structure make context easy without dense navigation. It keeps writing and review flows approachable.

**Pattern to borrow:** Use a simple breadcrumb and title zone: collection name, artifact name, optional version, and a compact status summary. Comment composers should feel like lightweight writing surfaces with markdown shortcuts, attachment-free by default, and clear submit and cancel actions. Empty states should be friendly but concise, such as `No comments yet` plus a one-line shortcut hint.

**Why it fits:** The server is no-auth and likely used by a small set of trusted reviewers. Notion's low-friction writing model suits quick feedback better than formal issue forms.

**Trade-off or failure mode:** Notion can blur structure when everything becomes a page or block. This app needs a stricter model: artifact, annotation, thread, reply, resolution.

### Arc

**What it does well:** Arc makes navigation feel spatial with a quiet sidebar, clear active item, and useful hover-revealed controls. It favors focus over tab clutter.

**Pattern to borrow:** For galleries, use a collapsible left rail that can show artifact groups and current selection. Thumbnails can be small, around 48 to 64 px square, with text labels and unresolved-count badges. Secondary actions, copy URL, open raw, mark viewed, should appear on hover or in a row menu, not as permanent buttons.

**Why it fits:** Reviewers often need to move through a sequence of artifacts while keeping the current image dominant. Arc's sidebar logic supports that without overwhelming the canvas.

**Trade-off or failure mode:** Hover-only controls are weak on touch and less discoverable. Critical actions need keyboard and menu access, and hover affordances should not be the only path.

### Notion Calendar

**What it does well:** Notion Calendar uses a clean dark interface, a fast command-like event flow, and a right details panel that updates without disorienting the user.

**Pattern to borrow:** Use a persistent but lightweight details panel for the currently selected thread or artifact. The panel should update in place rather than opening stacked modals. Inline transitions should be short, around 120 to 180 ms, and should not animate the artifact itself during zoom or pan.

**Why it fits:** Reviewing is a repeated focus-switching task: inspect image, read comment, jump to pin, resolve, move on. Updating side context without page changes keeps the user oriented.

**Trade-off or failure mode:** Calendar metaphors do not fit artifact review. Borrow the details-panel behavior, not calendar grids, scheduling language, or time-block visual metaphors.

### GitHub Projects and Issues

**What it does well:** GitHub's issue sidebar shows metadata and status while keeping the conversation central. Labels, state, and references are compact and readable.

**Pattern to borrow:** Use small semantic pills for artifact type, comment state, and source. Make links copyable and expose stable IDs only when useful. The main thread list should be chronological with clear separators, avatar initials, timestamps, and edited markers.

**Why it fits:** The backend mirrors comments to a `bd` board today, and future tooling may read feedback as JSON. Stable thread state and compact metadata will make human and machine review outputs easier to reconcile.

**Trade-off or failure mode:** GitHub's issue ecosystem assumes many people, permissions, mentions, labels, milestones, and automation. For this rewrite, avoid assignment, subscriptions, project boards, and complex labels.

## Cross-reference layout recommendations

### Canvas-first shell

Use a three-zone layout:

1. Optional left artifact rail: 240 to 280 px expanded, 56 to 72 px collapsed.
2. Center canvas: all remaining width, dark neutral background, OpenSeadragon image centered with fit-to-screen default.
3. Right feedback rail: 360 to 420 px, resizable up to about 520 px, collapsible with a persistent unread or unresolved badge.

The canvas should never be squeezed below usefulness. On smaller screens, collapse the left rail first, then turn the right rail into an overlay drawer.

### Comment pins and threads

Pins should have four clear states: unresolved, active, hovered, resolved. Unresolved uses the accent color and a filled center. Active adds a ring and links to the selected thread. Hover should highlight the associated region and thread row. Resolved should become muted or hidden behind a filter.

Region annotations should preserve the selected geometry, but the default visible marker should remain compact. Full region outlines can appear on hover, active thread, or while editing.

### Keyboard flow

The first useful keyboard layer should be small and visible:

- `C`: enter comment mode.
- `Esc`: exit mode, close drawer, or cancel draft.
- `J` and `K`: next and previous thread or artifact, depending on focus.
- `R`: resolve active thread.
- `/`: focus search.
- `?`: open shortcut help.
- `Cmd/Ctrl+K`: open command palette.

Keyboard focus must be visible, especially in the canvas toolbar, thread list, and modal surfaces.

### Visual language

Use a dark-mode-first palette with restrained contrast: black or near-black app background, raised charcoal panels, one cool accent, and semantic status colors reserved for actual states. Borders should be subtle but visible at WCAG-compliant contrast. Typography should favor a professional sans-serif, with 13 to 14 px dense UI text, 15 to 16 px comment body text, and clear line height for reading.

## Anti-patterns to avoid

- **Team and permission complexity:** No-auth on a trusted private tailnet means login, roles, invites, sharing permissions, and enterprise admin surfaces are wrong by default.
- **Project-management bloat:** Assignment, priority, milestone, sprint, and notification concepts should not appear unless a real workflow requires them later.
- **Chrome competing with the artifact:** Large headers, colorful sidebars, decorative cards, and always-visible metadata can make the image feel secondary.
- **Pin confetti:** Showing every pin and region outline at once can ruin dense visual review. Use filters, clustering, hover outlines, and resolved hiding.
- **Modal stacking:** Deep modal chains break spatial context. Prefer side rails, drawers, popovers, and inline thread editing.
- **Dashboard-first thinking:** Artifact lists matter, but the core workflow is inspect, annotate, discuss, resolve. The detail view should receive most design attention.
- **Hover-only interaction:** Hover affordances are elegant but insufficient. Every important action needs keyboard access and a visible menu path.
- **Over-animated canvas:** Motion should orient the user, not decorate the app. Avoid transitions that fight OpenSeadragon zoom and pan.
- **Exact cloning:** Borrow mechanics, not branding. The app should feel like a coherent artifact review tool, not a collage of Linear, Figma, and Frame.io.

## Prioritized shortlist: adopt these five first

1. **Frame.io's artifact-first review shell:** Start with the large canvas plus right feedback rail. This sets the product's hierarchy correctly from day one.
2. **Figma's spatial comment pins:** Annotation must feel direct, visible, and tied to the image. Comment mode, active pins, and synchronized threads are core to the tool.
3. **GitHub PR-style resolvable threads:** Resolution turns feedback into a finishable review workflow while preserving history.
4. **Linear and Raycast keyboard density:** Fast navigation, command palette, and quiet dark chrome make repeated review sessions efficient without adding visible clutter.
5. **Vercel-style artifact cards and states:** Galleries need a clean entry point with thumbnails, type, unresolved count, and stable status before the user enters the canvas view.
