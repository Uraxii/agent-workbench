# Artifact Review Server UI and UX Design Rationale

## Product intent

The artifact review server is a focused review workspace for generated visual artifacts: single images, galleries, and HTML reports. The interface should make the artifact feel like the primary object, keep surrounding chrome quiet, and make feedback fast to leave, read, resolve, and export.

The rewrite should feel like a modern professional tool rather than a file browser with comments. The right reference set is Figma inspect and comments, Linear issue density, GitHub pull request review states, Frame.io review flow, and Sentry triage clarity. Borrow their restraint: clear hierarchy, compact but readable panels, visible state, predictable keyboard access, and strong contrast.

## Cohesive user journey

### 1. Entry: land in the right context

The entry route should answer three questions in the first screen:

1. What artifact am I reviewing?
2. What needs attention?
3. What is already resolved?

Recommended entry layout:

- Header height: `56px` desktop, `48px` tablet and phone.
- Left header: artifact title, type badge, generated timestamp.
- Center header: compact breadcrumb if launched from a gallery or report.
- Right header: review progress, share/copy link, settings menu.
- Main region: image, gallery grid, or report iframe/preview.
- Right panel: comments and annotations, collapsed by default on narrow screens.

Primary action should be contextual:

- No feedback yet: `Add comment`.
- Open threads exist: `Review open threads`.
- All threads resolved: `Mark done` or `Copy feedback JSON`, depending on the workflow contract.

### 2. Browse: scan without losing orientation

For galleries, the user should see enough artifacts to compare outputs while keeping metadata minimal.

Gallery card spec:

- Card width: `220px` minimum, `280px` comfortable, fluid grid with `minmax(220px, 1fr)`.
- Thumbnail ratio: preserve original inside a fixed `4:3` preview well, never crop by default.
- Card metadata: filename or title, status pill, comment count, last activity.
- Hover affordance: subtle outline and `Open` action, not a large overlay.
- Keyboard behavior: arrow keys move focus across cards, Enter opens, Escape returns to gallery.

Status categories:

- `Needs review`: no human decision yet.
- `Open comments`: at least one unresolved thread.
- `Resolved`: all threads resolved.
- `Done`: reviewer completed this artifact.
- `Error`: artifact failed to load or render.

### 3. Zoom and annotate: keep the canvas dominant

For single images, OpenSeadragon should own the visual center. The annotation layer should feel native to the viewer, not like a separate form bolted on.

Desktop viewer layout:

```text
┌──────────────────────────────────────────────────────────────┐
│ top bar: title, artifact switcher, status, actions           │ 56px
├──────────┬───────────────────────────────────────┬───────────┤
│ left rail│ image canvas                           │ comments  │
│ 56px     │ OpenSeadragon + Annotorious            │ 360px     │
│ tools    │                                       │ threads   │
└──────────┴───────────────────────────────────────┴───────────┘
```

Canvas rules:

- Canvas background: `#05070A`, darker than the app shell.
- Viewer padding: `24px` desktop, `16px` tablet, `8px` phone.
- Default zoom: fit whole artifact with 5 percent margin.
- Double click or double tap: zoom into pointer.
- Reset view shortcut: `0`.
- Zoom controls: visible but quiet, grouped in a floating vertical toolbar.
- Minimap: optional for very large artifacts, bottom left, `160px` by `112px`, hidden on phone.

Annotation rules:

- Annotation pins use the accent color only for active or selected state.
- Unselected pins use neutral outlines so the image remains dominant.
- A selected region draws a `2px` accent stroke plus a translucent fill at 12 percent opacity.
- Annotation labels show thread number, not author avatars, to reduce visual noise.
- Creating an annotation opens the comment composer in the side panel, focused and linked to the region.

### 4. Comment and resolve: make review state obvious

Threads should behave like professional review objects, not chat messages. Each thread has location, status, author, timestamp, body, replies, and resolution state.

Thread card anatomy:

1. Header: number, status pill, author, timestamp.
2. Optional location chip: `Region`, `Point`, `General`, or `Report section`.
3. Body: Markdown-lite text, plain by default.
4. Replies: compact stack, separated by hairlines.
5. Actions: Reply, Resolve, Reopen, Copy link.

Thread dimensions:

- Side panel width: `360px` default, `420px` large desktop, resizable to `520px` maximum.
- Thread card padding: `12px` compact, `16px` comfortable.
- Thread gap: `12px`.
- Composer minimum height: `88px`.
- Composer expanded height: `160px`.

Resolve behavior:

- Resolve should require one click, not a modal.
- Reopen should be visible on resolved cards.
- Resolving a selected annotation should dim its pin and move the card to the resolved section.
- Use an undo toast for accidental resolve: `Thread resolved. Undo` for 6 seconds.

### 5. Done: close the loop

The final state should make it clear whether the artifact is ready for the next automation step.

Done state should show:

- Open thread count.
- Resolved thread count.
- Last reviewer activity.
- Feedback export status, if the backend mirrors comments to the board or another consumer.
- A primary action for the next expected workflow: `Copy feedback JSON`, `Open next artifact`, or `Return to gallery`.

Avoid making `Done` depend on every comment being resolved unless that is the workflow contract. In many visual review flows, unresolved comments are the actual deliverable.

## Modern UI and UX principles

### Visual hierarchy

Use a three-layer hierarchy:

1. Artifact layer: image, gallery, or report. This receives the most area and the least decorative chrome.
2. Review layer: annotations, selected thread, composer, status. This receives the accent color.
3. App layer: navigation, settings, metadata. This stays neutral and compact.

Rules:

- Never let the side panel visually compete with the artifact. Its surface should be one step lighter than the app background, not high contrast.
- Use accent color for current task, not for branding everywhere.
- Keep titles short and truncate from the middle for paths or hashes.
- Put status near the object it describes: artifact status in the top bar, thread status inside each thread, upload/publish status in toast or activity area.

### Affordance

Every interactive control should have at least two of these signals:

- Shape: button, chip, rail item, or card.
- Label: visible text for primary actions.
- Icon: supplemental, not the only meaning for critical actions.
- State: hover, active, disabled, selected, focus-visible.

Minimum targets:

- Mouse target: `32px` by `32px` minimum.
- Touch target: `44px` by `44px` minimum.
- Toolbar icon button: `36px` desktop, `44px` touch.
- Focus ring: `2px` outline plus `2px` offset.

### Feedback

The app should respond visibly to every user action within 100 ms, even if the backend operation takes longer.

Examples:

- Creating annotation: pin appears immediately in pending state, then commits or rolls back.
- Saving comment: composer switches to saving state, Submit disabled, text preserved on failure.
- Resolve: card dims immediately, undo toast appears, server error restores prior state.
- Upload or publish: show progress if measurable, otherwise show staged steps.

Toast rules:

- Success toast duration: 4 seconds.
- Undo toast duration: 6 seconds.
- Error toast persists until dismissed or fixed.
- Maximum visible toasts: 3, stack bottom right on desktop, bottom center on phone.

### Progressive disclosure

Keep the first screen simple, then reveal depth when needed.

Default visible controls:

- Pan, zoom in, zoom out, reset view.
- Add comment.
- Toggle comments panel.
- Artifact switcher.

Secondary controls under menus or drawers:

- Raw artifact link.
- Download original.
- Copy feedback JSON.
- Show tile diagnostics.
- Annotation visibility filters.
- Keyboard shortcut list.

Avoid hiding core review actions inside menus. Comment, resolve, and next artifact must be directly reachable.

### Empty, loading, and error states

Empty states should be useful and specific.

- Empty gallery: `No artifacts published yet`, with the expected publish command or source path if available.
- No comments: `No comments yet`, with `Click the image or press C to add one`.
- No open threads: `All threads resolved`, with resolved count.
- Filter empty: `No threads match this filter`, with a clear filter action.

Loading states:

- Shell loads first with skeleton top bar and panel.
- Image tiles load progressively through OpenSeadragon.
- Show a low-detail placeholder if dimensions are known.
- Avoid full-screen spinners except on first boot.

Error states:

- Image load error should preserve navigation and comments if possible.
- HTML report sandbox errors should explain whether script was blocked by policy.
- API save errors should never discard composer text.
- Error copy should include a short recovery action.

### Motion restraint

Motion should clarify spatial relationships, not decorate.

Recommended transitions:

- Panel open and close: 160 ms ease-out.
- Thread selection highlight: 120 ms fade.
- Pin hover scale: 80 ms, max 1.08.
- Toast enter and exit: 140 ms.
- Respect `prefers-reduced-motion: reduce` by removing transforms and keeping only opacity changes under 80 ms.

Avoid animated backgrounds, bouncing icons, large parallax, and continuous pulsing. The artifact content may already be visually dense.

## Color system

### Color theory direction

Use a neutral dark base, one restrained blue accent, and semantic colors reserved for state. Blue is appropriate because it reads as professional, precise, and non-alarming. It also works well for selected annotations without implying success or failure.

Dark mode should not be pure black everywhere. Use a near-black canvas for the artifact, a slightly lighter app background, and elevated surfaces with subtle borders. This preserves depth without glowing panels.

### WCAG targets

Set these targets as implementation rules:

- Body text: WCAG AA, contrast ratio 4.5:1 minimum.
- Large text and icons: 3:1 minimum.
- Critical controls and focus indicators: 3:1 minimum against adjacent colors.
- Preferred body text target in dark mode: 7:1 or better.
- Do not communicate status by color alone. Pair color with label, icon shape, or text.

### Example dark palette

| Token | Hex | Use | Contrast note |
| --- | --- | --- | --- |
| `color.bg.canvas` | `#05070A` | OpenSeadragon canvas surround | Artifact-first near black |
| `color.bg.app` | `#0B0F14` | App background | `#F8FAFC` text is 18.37:1 |
| `color.bg.surface` | `#111827` | Panels, cards | `#CBD5E1` text is 11.95:1 |
| `color.bg.elevated` | `#1E293B` | Popovers, active cards | `#E2E8F0` text is 11.87:1 |
| `color.border.subtle` | `#243244` | Dividers and card borders | Use at 1px, not as text |
| `color.border.strong` | `#334155` | Active separators | Use for selected neutral states |
| `color.text.primary` | `#F8FAFC` | Primary text | 18.37:1 on app bg |
| `color.text.secondary` | `#CBD5E1` | Body and metadata | 11.95:1 on surface |
| `color.text.muted` | `#94A3B8` | Timestamps, hints | 6.92:1 on surface |
| `color.accent` | `#60A5FA` | Primary action, selected annotation | 7.56:1 on app bg |
| `color.accent.soft` | `#1D4ED8` at 18 percent | Selected fills and hovers | Never use as text |
| `color.success` | `#10B981` | Resolved, saved | 7.58:1 on app bg |
| `color.warning` | `#FBBF24` | Needs attention | 11.51:1 on app bg |
| `color.danger` | `#FB7185` | Error, failed save | 7.14:1 on app bg |
| `color.focus` | `#93C5FD` | Focus ring | 10.66:1 against app bg |

### Example light palette

Light mode should be derived, not redesigned. Keep the same accent family and invert elevation logic.

| Token | Hex | Use | Contrast note |
| --- | --- | --- | --- |
| `color.bg.canvas` | `#E2E8F0` | Viewer surround | Neutral, not white |
| `color.bg.app` | `#F8FAFC` | App background | `#0B0F14` text is 18.37:1 |
| `color.bg.surface` | `#FFFFFF` | Panels, cards | Use shadows sparingly |
| `color.bg.elevated` | `#F1F5F9` | Popovers, active rows | Subtle contrast from surface |
| `color.border.subtle` | `#CBD5E1` | Dividers | 1px standard |
| `color.text.primary` | `#0B0F14` | Primary text | 18.37:1 on app bg |
| `color.text.secondary` | `#334155` | Body and metadata | Strong readability |
| `color.text.muted` | `#64748B` | Timestamps, hints | Use only for non-critical text |
| `color.accent` | `#2563EB` | Primary action | 4.94:1 on app bg |
| `color.success` | `#047857` | Resolved, saved | 5.24:1 on app bg |
| `color.warning` | `#B45309` | Needs attention | 4.80:1 on app bg |
| `color.danger` | `#BE123C` | Error, failed save | 6.01:1 on app bg |

### Semantic usage

Status colors should be limited and consistent:

- Accent blue: selected, current, primary action.
- Success green: resolved, saved, complete.
- Warning amber: needs review, unsaved local draft, partial load.
- Danger rose: failed save, load error, blocked publish.
- Neutral slate: inactive, resolved but not selected, metadata.

Never use red for unresolved comments. Unresolved is normal work, not an error. Use amber or neutral plus label.

## Design tokens and frontend primitives

The React app should be built from tokens and primitives, not page-specific CSS. Tokens can live as CSS custom properties with TypeScript constants for layout values that components need.

### Token structure

Recommended token groups:

```css
:root {
  --space-0: 0;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.25rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-10: 2.5rem;
  --space-12: 3rem;

  --radius-1: 0.375rem;
  --radius-2: 0.5rem;
  --radius-3: 0.75rem;
  --radius-pill: 999px;

  --border-width: 1px;
  --focus-width: 2px;

  --font-sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
}
```

### Spacing scale

Use a 4px base scale with common spacing names:

| Token | Value | Use |
| --- | --- | --- |
| `space.1` | `4px` | Tight icon gaps, hairline offsets |
| `space.2` | `8px` | Button icon gap, compact row gap |
| `space.3` | `12px` | Card inner gap, thread gap |
| `space.4` | `16px` | Standard padding |
| `space.5` | `20px` | Panel sections |
| `space.6` | `24px` | Viewer padding desktop |
| `space.8` | `32px` | Empty state spacing |
| `space.10` | `40px` | Page gutters on large screens |
| `space.12` | `48px` | Major layout separation |

Do not introduce arbitrary values unless they map to a component dimension, such as `56px` header height or `360px` comment panel width.

### Type scale

Recommended type scale:

| Token | Size | Line height | Weight | Use |
| --- | --- | --- | --- | --- |
| `text.xs` | `12px` | `16px` | 500 | Labels, timestamps |
| `text.sm` | `14px` | `20px` | 400 | Body, controls |
| `text.md` | `16px` | `24px` | 400 | Composer text, empty states |
| `text.lg` | `18px` | `28px` | 600 | Panel headings |
| `text.xl` | `20px` | `28px` | 650 | Artifact title |
| `text.2xl` | `24px` | `32px` | 700 | Rare page heading |

Most of the app should use `14px` and `16px`. Large display type is unnecessary because the artifact, not the heading, is the focal point.

### Elevation and borders

Use borders more than shadows in dark mode.

| Token | Value | Use |
| --- | --- | --- |
| `shadow.panel` | `0 16px 40px rgb(0 0 0 / 0.30)` | Floating drawers and modals |
| `shadow.popover` | `0 12px 28px rgb(0 0 0 / 0.35)` | Menus and tooltips |
| `border.subtle` | `1px solid #243244` | Cards, panels |
| `border.selected` | `1px solid #60A5FA` | Selected card or thread |
| `ring.focus` | `0 0 0 2px #0B0F14, 0 0 0 4px #93C5FD` | Focus-visible controls |

### Component primitives

Build the system from these primitives.

#### AppShell

Responsibilities:

- Owns top bar, main split layout, responsive panel behavior.
- Provides skip link target and landmark structure.
- Handles global shortcuts and command palette entry.

Dimensions:

- Header: `56px` desktop, `48px` tablet and phone.
- Left rail: `56px` desktop, collapses to bottom bar on phone.
- Right panel: `360px` default, `420px` wide, `min(100vw, 420px)` overlay on phone.

#### TopBar

Use for global context, not dense controls.

Contents:

- Artifact title and type.
- Breadcrumb or gallery position, for example `7 of 24`.
- Save or sync state.
- Comment filter summary.
- Actions menu.

#### ViewerToolbar

Floating toolbar over the canvas, vertical on desktop, horizontal on phone.

Controls:

- Pan/select mode.
- Add point comment.
- Add region comment.
- Zoom in.
- Zoom out.
- Reset view.
- Toggle annotations.

Button states:

- Default: transparent surface with border.
- Hover: elevated surface.
- Active: accent border and accent-tinted background.
- Disabled: 45 percent opacity, no hover transform.

#### Button

Variants:

- Primary: accent background, dark text only if contrast is high enough, otherwise white text.
- Secondary: neutral surface with border.
- Ghost: transparent, for toolbar and row actions.
- Danger: danger text or border, filled only for destructive confirmation.

Sizes:

- Small: `28px` height, `12px` horizontal padding, metadata actions only.
- Medium: `36px` height, `14px` horizontal padding, default.
- Large: `44px` height, `16px` horizontal padding, touch and primary calls to action.

#### Input and Composer

Inputs should share one visual language.

- Background: `color.bg.app` inside panels, `color.bg.surface` in modals.
- Border: subtle by default, focus ring on keyboard focus.
- Error: danger border plus error text below.
- Composer supports Markdown-lite hints only if implemented, otherwise do not imply formatting.
- Preserve draft text per artifact and selected annotation until submitted or discarded.

#### Panel

Use panels for comments, artifact metadata, filters, and settings.

Panel sections:

- Header: title, count, close or collapse.
- Filter row: segmented controls or chips.
- Content: scroll area.
- Footer: composer or primary action.

Scroll behavior:

- Thread list scrolls independently from canvas.
- Top bar remains fixed.
- Composer can pin to the bottom of the comments panel.

#### ThreadCard

ThreadCard is the core review primitive.

States:

- Open.
- Selected.
- Pending save.
- Failed save.
- Resolved.
- Reopened.

Visual treatment:

- Open: neutral card border with status pill.
- Selected: accent border, subtle accent background tint.
- Pending: warning icon plus disabled resolve.
- Failed: danger border and inline retry action.
- Resolved: lower contrast, success pill, hidden replies collapsed by default after enough history.

#### AnnotationOverlay

This is the bridge between Annotorious and the design system.

Rules:

- Do not use default library styling without mapping it to tokens.
- Pins and regions must expose accessible names tied to their thread numbers.
- Selected annotation synchronizes with selected ThreadCard.
- Hovering a ThreadCard highlights the annotation. Hovering an annotation highlights the ThreadCard.
- Hidden annotations should still be represented in the thread list.

#### GalleryCard

GalleryCard should support fast scanning.

Contents:

- Thumbnail preview.
- Artifact title or filename.
- Type badge.
- Status pill.
- Comment count.
- Last activity.

Interaction:

- Entire card opens artifact.
- Secondary actions live in a small overflow menu.
- Focus-visible outline wraps the whole card.

#### StatusPill

StatusPill combines color, shape, and label.

Examples:

- `Needs review`: amber dot, neutral pill.
- `Open comments`: blue dot, neutral pill.
- `Resolved`: green dot, neutral pill.
- `Error`: rose dot, danger text.

Do not use filled saturated pills everywhere. Filled color blocks add noise in dense panels.

#### EmptyState

EmptyState should be compact and action-oriented.

Structure:

- Short title.
- One sentence of guidance.
- Optional primary action.
- Optional technical details collapsed under `Details`.

#### Dialog and Popover

Use modals sparingly. Most review actions should happen inline.

Modal uses:

- Confirm irreversible delete if delete exists.
- Show keyboard shortcuts.
- Advanced settings.

Popover uses:

- Sort and filter controls.
- Copy link menu.
- Artifact metadata summary.

## Screen real estate strategy

### Desktop, 1280px and wider

Default layout:

- Top bar: full width.
- Left rail: `56px`.
- Right comments panel: `360px`.
- Canvas: remaining width.

At `1440px` and wider:

- Allow comments panel to expand to `420px`.
- Keep canvas centered with max useful padding.
- Optional metadata drawer can open over the comments panel, not beside it.

The artifact should receive at least 60 percent of horizontal space in normal review mode. If side panels would reduce that below 60 percent, panels should overlay or collapse.

### Tablet, 768px to 1279px

Recommended behavior:

- Top bar stays visible.
- Left rail becomes a compact top-left tool cluster or bottom toolbar.
- Comments panel becomes a slide-over drawer, default closed when viewing image.
- A persistent comment count button opens the drawer.
- Annotation creation opens the drawer automatically.

Panel width:

- `min(420px, 85vw)`.

### Phone, under 768px

Phone support should prioritize viewing and lightweight replies, not full power use.

Recommended behavior:

- Canvas first.
- Bottom toolbar with core actions: comments, add, zoom, reset.
- Comments open as a bottom sheet at 60 percent height, expandable to full height.
- Annotation drawing can be simplified to point comments if region drawing is too cramped.
- Gallery grid becomes one column or two compact columns depending on width.
- Metadata is hidden behind a sheet.

Touch requirements:

- 44px minimum target.
- Avoid hover-only affordances.
- Long press should not be required for core actions.
- Pin selection should tolerate touch imprecision with a larger invisible hit area.

### Density and breathing room

The app needs two density levels:

- Comfortable: default for first build, more breathing room, `16px` panel padding.
- Compact: useful for heavy review sessions, `12px` panel padding and tighter thread cards.

Do not create separate bespoke layouts. Density should be a token multiplier applied to spacing and component size.

### Report view

HTML reports can be visually noisy and may carry security constraints. Treat report viewing as a sibling to image viewing.

Layout:

- Report preview in the canvas region.
- Comments panel still works for general and section comments.
- Report toolbar includes zoom, open raw sandboxed artifact, copy link, and security status.
- If scripts are blocked, show a small security chip: `Scripts disabled` with details in a popover.

Security UX:

- Do not display scary warnings for expected sandbox behavior.
- Use precise copy: `This report is shown with scripts disabled for reviewer safety`.
- Raw active content should never share the same trusted origin without mitigation.

## Accessibility requirements

### Landmarks and focus

Use semantic landmarks:

- `header` for TopBar.
- `main` for viewer or gallery.
- `aside` for comments panel.
- `nav` for artifact navigation if a gallery exists.

Focus rules:

- Initial focus after page load: artifact title or main heading, not the canvas.
- Opening comments drawer: focus moves to drawer heading.
- Creating annotation: focus moves to composer.
- Saving comment: focus returns to the created thread card.
- Closing drawer: focus returns to the control that opened it.
- Escape closes menus, popovers, drawers, then exits annotation creation mode in that order.

### Annotation accessibility

Canvas annotations are difficult for assistive tech, so mirror them in accessible UI.

Required behavior:

- Every annotation has a corresponding ThreadCard in DOM order.
- ThreadCard includes location text, for example `Region annotation at x 42 percent, y 31 percent, width 18 percent, height 12 percent`.
- Pin buttons have accessible names, for example `Thread 4, unresolved region comment`.
- Keyboard users can select next and previous annotation with `[` and `]`.
- The selected annotation is announced through an `aria-live="polite"` region.
- Color is never the only indicator of selected or resolved state.

### Keyboard shortcuts

Keep shortcuts small and visible in a help dialog.

Recommended set:

| Shortcut | Action |
| --- | --- |
| `C` | Add general comment or enter comment mode |
| `R` | Resolve selected thread |
| `Shift R` | Reopen selected resolved thread |
| `[` | Previous thread or annotation |
| `]` | Next thread or annotation |
| `F` | Fit artifact to screen |
| `0` | Reset zoom |
| `+` | Zoom in |
| `-` | Zoom out |
| `G` | Return to gallery |
| `?` | Show keyboard shortcuts |
| `Escape` | Close current overlay or cancel current mode |

Do not hijack browser shortcuts such as `Cmd L`, `Cmd R`, or `Ctrl F`.

### Contrast and theming tests

Add automated checks where practical:

- Unit test token contrast pairs used for text.
- Storybook or component preview visual checks for focus rings.
- Manual screen reader smoke test for create, reply, resolve, and reopen.
- `prefers-color-scheme` support plus explicit saved theme.
- `prefers-reduced-motion` support.

## Performance and deep-zoom behavior

### OpenSeadragon tile performance

The viewer should feel instant even for huge generated images.

Recommendations:

- Keep OpenSeadragon instance stable across thread panel changes.
- Memoize tile source construction.
- Do not re-render the React tree around the viewer on every pan or zoom event.
- Store high-frequency viewport state outside React or throttle updates to 100 ms.
- Use tile loading indicators only in the viewer corner, not full-screen spinners.
- Preload adjacent gallery artifact metadata, not all deep-zoom tiles.
- For galleries, lazy-load thumbnails with `loading="lazy"` and `IntersectionObserver`.

### Annotation performance

- Render only visible annotation overlays if the library allows it.
- Debounce annotation position updates during drawing.
- Use stable thread IDs as React keys.
- Avoid expensive Markdown rendering while typing. Render preview only on demand or after debounce.
- Batch comment count updates when many artifacts load.

### Data loading

Use a simple state model:

- Artifact metadata query.
- Thread list query.
- Comment mutation queue.
- Settings query.

Optimistic updates are appropriate for comments and resolves because the trusted tailnet model makes conflicts rare. Still handle conflicts with clear copy: `This thread changed on the server. Review the latest version before saving`.

## Interaction details

### Selection model

There should be one selected review target at a time:

- Selected artifact in gallery.
- Selected annotation in viewer.
- Selected thread in panel.

Selection sync rules:

- Clicking an annotation selects its thread and scrolls it into view.
- Clicking a thread selects and centers its annotation if it has one.
- Navigating with `[` and `]` advances through visible threads.
- Filtering threads hides non-matching annotations or dims them, depending on filter mode.

### Filters and sorting

Default thread filter: `Open`.

Available filters:

- Open.
- Resolved.
- Mine, if author identity exists.
- All.
- General comments.
- Region comments.

Default sort:

- Open threads first.
- Selected thread pinned within view.
- Then by creation order for stable review.

Avoid changing sort order on every reply. Stability matters more than recency for spatial review.

### Copy and labels

Use precise labels:

- `Resolve thread`, not `Done` inside a thread.
- `Mark artifact done`, not `Resolve` for the artifact.
- `Copy feedback JSON`, not `Export` if the consumer expects JSON.
- `Open raw artifact`, not `View file`.
- `Scripts disabled`, not `Safe mode`, because it explains the actual constraint.

## Implementation-oriented design architecture

### Suggested React structure

```text
src/
  app/
    AppShell.tsx
    routes.tsx
  design-system/
    tokens.css
    Button.tsx
    IconButton.tsx
    Panel.tsx
    StatusPill.tsx
    EmptyState.tsx
    Dialog.tsx
    Popover.tsx
  artifacts/
    ArtifactRoute.tsx
    GalleryRoute.tsx
    ReportRoute.tsx
    ArtifactTopBar.tsx
  viewer/
    DeepZoomViewer.tsx
    AnnotationOverlay.tsx
    ViewerToolbar.tsx
    useViewerShortcuts.ts
  comments/
    CommentsPanel.tsx
    ThreadCard.tsx
    CommentComposer.tsx
    threadStatus.ts
  api/
    client.ts
    artifactQueries.ts
    commentMutations.ts
```

This keeps OpenSeadragon and Annotorious integration isolated from comment rendering, while the design-system primitives remain reusable.

### State boundaries

- Server state: artifacts, settings, threads, comments.
- Viewer state: zoom, pan, selected tool, selected annotation.
- Draft state: unsaved composer text and pending annotation geometry.
- UI state: panel open, density, filters, theme.

Do not store high-frequency zoom state in global app state unless another component truly needs it.

### Design-token adoption path

1. Implement CSS custom property tokens for color, spacing, radius, type, border, shadow, and motion.
2. Build primitives with only token references.
3. Build viewer and comments layout from primitives.
4. Map Annotorious classes to tokens.
5. Add light theme after dark theme is complete.
6. Add density after the base component system is stable.

## Concrete page recipes

### Single image review page

Initial state:

- Top bar shows artifact title, `Image`, `Needs review`, `0 open`.
- Canvas fits image.
- Comments panel open on desktop, closed on tablet and phone.
- Empty comment state explains `Click the image or press C to add one`.

After adding region comment:

- Region shows pending accent outline.
- Composer opens in panel with `Thread 1` header.
- Save failure keeps region and draft in failed state with retry.
- Save success converts pending region to open thread.

After resolving:

- Thread moves to resolved section.
- Pin dims to neutral.
- Toast offers undo.
- Progress summary updates immediately.

### Gallery review page

Initial state:

- Grid sorted by needs attention first.
- Each card shows thumbnail, status, comment count.
- Keyboard focus starts on first `Needs review` card.
- Right side may show a compact activity panel on wide screens.

Batch navigation:

- `N` or a visible `Next unresolved` action opens the next artifact with open comments.
- Returning to gallery preserves scroll and selected card.

### HTML report page

Initial state:

- Report shown in sandboxed preview with scripts disabled unless a safer separate origin is implemented.
- Security chip explains the sandbox policy.
- General comments are available immediately.
- Section comments can attach to anchors if the report exposes stable IDs, otherwise they remain general comments.

## What to build first

First usable slice:

1. Dark tokens and AppShell.
2. Single image route with OpenSeadragon fit, zoom, reset, and tile loading state.
3. Comments panel with open/resolved ThreadCard states.
4. Point annotation creation linked to a thread.
5. Save, reply, resolve, reopen, and error recovery.
6. Gallery grid with status counts.
7. Report route with sandbox status and general comments.

This slice proves the core journey before visual polish expands.

## Design success criteria

The design is successful when:

- A reviewer can understand artifact status within 5 seconds of opening the page.
- The artifact uses most of the screen and remains visually dominant.
- Adding a comment takes one direct action from the viewer.
- Selecting a thread and selecting its annotation always stay synchronized.
- Resolving and reopening are obvious, reversible, and reflected in both panel and overlay.
- Text and controls meet WCAG AA contrast in dark and light themes.
- Keyboard users can browse artifacts, select annotations, comment, resolve, and return to gallery.
- The design system can build new routes without inventing new spacing, colors, or component shapes.
