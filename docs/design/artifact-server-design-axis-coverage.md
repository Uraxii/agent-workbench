# Artifact Review Server Design Axis Coverage Audit

## Scope

This audit identifies the design axes that need explicit positions before the artifact review server rewrite proceeds. A considered position means future implementation can make the decision from documented product reasoning, not personal taste.

## Axis list

### Product model and workflow

| Axis | What a considered position means here |
| --- | --- |
| Product purpose and design principles | Define what the product is for, what it optimizes, what it sacrifices, and how later trade-offs are decided. |
| Scope boundaries and anti-goals | Define which adjacent product shapes are intentionally out of scope, especially dashboards, chat, image editing, project management, and enterprise collaboration. |
| Trust model and no-auth UX | Define how the private tailnet, no-auth, effectively single-reviewer model appears in UI, copy, safety, sharing, and error surfaces. |
| Artifact object model and vocabulary | Define the canonical objects and names: artifact, annotation, thread, reply, resolution, status, version, gallery, report, and export. |
| Artifact types and view modes | Define how single images, galleries, HTML reports, and any future compare view differ while preserving one review model. |
| Information architecture and route model | Define the top-level structure, deep links, page states, rails, drawers, and route restoration behavior. |
| Navigation and wayfinding | Define how reviewers move among home, latest artifact, gallery, selected artifact, selected thread, report sections, and return paths. |
| Gallery browsing model | Define how artifact collections are scanned, sorted, opened, and restored after review. |
| Search, filter, and sort | Define the search surfaces, default filters, filter visibility, sort stability, and how hidden items remain discoverable. |
| Versioning, history, and provenance | Define how artifact versions, generated source metadata, stale annotations, changed artifacts, and resolved history are represented. |
| Review completion and done semantics | Define what `Done`, `Resolved`, unresolved comments, export status, and next-step readiness mean. |
| Compare workflow | Define whether compare exists, when it appears, how synchronized zoom works, and how comments attach to each compared artifact. |
| Onboarding and first-run | Define how a first-time or intermittent reviewer learns the core review loop without training. |
| Personalization and persisted preferences | Define which preferences persist, which are per-artifact or per-session, and how saved state avoids hiding work. |

### Visual system

| Axis | What a considered position means here |
| --- | --- |
| Layout and spatial allocation | Define the app shell, canvas dominance, rail sizes, drawer rules, and the minimum useful canvas share. |
| Responsive breakpoints | Define behavior on desktop, tablet, and phone, including which surfaces collapse first. |
| Density system | Define comfortable and compact density, limits for visible controls, and how density maps to tokens rather than bespoke layouts. |
| Typography | Define typefaces, sizes, line heights, weights, truncation rules, and reading hierarchy. |
| Color and theming | Define dark-first tokens, light-mode derivation, semantic colors, contrast targets, and color-use rules. |
| Iconography | Define the icon style, when labels are required, what icons may stand alone, and how icons remain accessible. |
| Imagery, thumbnails, and artifact previews | Define thumbnail sizing, cropping policy, placeholder behavior, gallery previews, and report previews. |
| Depth, elevation, borders, and shadows | Define how surfaces separate in dark mode, when shadows are used, and how selected or floating elements appear. |
| Motion and transitions | Define duration, easing, reduced-motion behavior, and which spatial changes deserve animation. |
| Visual hierarchy and information hierarchy | Define which layer owns attention at each moment: artifact, review state, app chrome, metadata, or settings. |
| Microcopy, labels, and content voice | Define labels, status wording, empty-state wording, error wording, and domain vocabulary. |
| Data visualization, progress, and status summaries | Define whether counts, progress summaries, meters, timelines, or charts appear, and how they avoid dashboard bloat. |

### Design system and governance

| Axis | What a considered position means here |
| --- | --- |
| Component primitives and token governance | Define primitives, token groups, component states, and the rule that product components must not invent local styling. |
| Design-system documentation and decision records | Define where design decisions, component rules, exceptions, and future revisions are documented and reviewed. |
| Backend/API contract as UX | Define how backend state, mutation failures, conflicts, IDs, timestamps, and export contracts shape the visible UI. |
| Design testing and verification | Define how contrast, keyboard flow, screen-reader behavior, focus states, visual regressions, and token usage are verified. |

### Interaction model

| Axis | What a considered position means here |
| --- | --- |
| Pointer interaction and target sizing | Define click, hover, drag, target sizes, pointer travel, and safe placement for frequent controls. |
| Keyboard interaction and shortcuts | Define keyboard reachability, shortcut set, focus-sensitive behavior, help, and browser shortcut avoidance. |
| Touch and gesture interaction | Define phone and tablet gestures, touch hit areas, bottom sheets, imprecision tolerance, and what mobile intentionally does not support. |
| Deep zoom, pan, and tile interaction | Define OpenSeadragon behavior, fit, reset, zoom toward pointer, tile loading feedback, and viewport state retention. |
| Annotation creation and editing model | Define point versus region creation, modes, draft geometry, editing handles, cancel paths, and save behavior. |
| Selection model and thread synchronization | Define the one selected review target, thread to pin sync, pin to thread sync, scrolling, centering, and filtered selection. |
| Focus management and landmarks | Define semantic landmarks, initial focus, focus restoration, drawer traps, focus rings, and `Escape` order. |
| Forms, composer, text entry, and validation | Define comment composer behavior, Markdown-lite scope, submit rules, failed validation, draft persistence, and discard behavior. |
| Command palette and secondary action access | Define which actions live in visible controls, menus, drawers, popovers, shortcuts, or command palette. |

### State, safety, and feedback

| Axis | What a considered position means here |
| --- | --- |
| State and feedback states | Define loading, empty, success, saving, pending, failed, offline, stale, conflict, filtered, and recovered states. |
| Notifications, toasts, and alerts | Define toast placement, duration, persistence, maximum count, alert severity, and which notifications are intentionally absent. |
| Error recovery and undo | Define recovery paths for failed saves, failed loads, rollback, draft preservation, and reversible state changes. |
| Destructive action safety | Define which actions need undo, confirmation, disabled states, separation, or stronger copy. |

### Comment and annotation UX

| Axis | What a considered position means here |
| --- | --- |
| Threaded comment structure | Define thread anatomy, replies, metadata, location chips, chronology, edited markers, and collapse behavior. |
| Resolution and reopen UX | Define resolve, reopen, undo, collapsed resolved history, and how resolution affects pins and progress. |
| Annotation visual states and pin density | Define pin size, hit area, color, active state, hover state, clustering, resolved visibility, and region-outline rules. |
| Author identity and single-reviewer authorship | Define whether author labels, initials, `Mine`, timestamps, and edited markers matter in an effectively one-reviewer tool. |
| Export, raw artifact, and feedback JSON | Define how feedback leaves the app, how raw artifacts open, how copy/export status is shown, and what success means. |
| HTML report sandbox and security UX | Define how report previews, disabled scripts, raw active content, same-origin risk, and security chips behave. |

### Accessibility, internationalization, and portability

| Axis | What a considered position means here |
| --- | --- |
| Visual accessibility | Define contrast, non-color state indicators, focus visibility, dark-theme physiology, and color-vision deficiency support. |
| Motor accessibility | Define target sizes, pointer travel, drag alternatives, keyboard equivalents, and mobile imprecision handling. |
| Cognitive accessibility | Define choice limits, visible state, progressive disclosure, memory aids, predictable sorting, and reduced ambiguity. |
| Screen reader and non-visual accessibility | Define DOM mirrors for annotations, accessible names, live regions, normalized coordinates, and realistic non-visual scope. |
| Internationalization and text expansion | Define whether localization is supported, how labels expand, how timestamps and numbers format, and how right-to-left text would behave if required. |
| Print and offline portability | Define whether any review surface, artifact, report, or feedback output must work as print, saved page, PDF, or offline handoff. |

### Performance as design

| Axis | What a considered position means here |
| --- | --- |
| Performance and perceived latency | Define response thresholds, optimistic updates, skeletons, tile loading, throttling, preload scope, and what must never block the review loop. |

## Coverage table

| Axis | Status | Existing coverage | Note |
| --- | --- | --- | --- |
| Product purpose and design principles | COVERED | `artifact-server-design-philosophy.md`, `## Product philosophy`; `artifact-server-design-philosophy.md`, `## Decision procedure`; `artifact-server-design-research.md`, `## Product intent` | The documents define the artifact-first purpose, trade-off order, and decision procedure. |
| Scope boundaries and anti-goals | COVERED | `artifact-server-design-philosophy.md`, `## Anti-goals`; `artifact-server-design-references.md`, `## Anti-patterns to avoid`; `artifact-server-interaction-cost.md`, `## Purpose` | Strong anti-goals prevent collaboration, dashboard, admin, image-editor, and project-management drift. |
| Trust model and no-auth UX | THIN | `artifact-server-design-philosophy.md`, `## Product philosophy`; `artifact-server-design-research.md`, `### Report view`; `artifact-server-design-references.md`, `## Anti-patterns to avoid` | No-auth and trusted tailnet are used to remove roles and ceremony, but the UX surface for trust, private sharing, copy, privacy language, and tailnet assumptions is not fully specified. |
| Artifact object model and vocabulary | COVERED | `artifact-server-design-philosophy.md`, `### Step 1: Name the review job`; `artifact-server-design-philosophy.md`, `### Consistency versus context-specific optimization`; `artifact-server-design-research.md`, `### Copy and labels` | The core nouns and labels are named and distinguished. |
| Artifact types and view modes | COVERED | `artifact-server-design-research.md`, `## Cohesive user journey`; `artifact-server-design-research.md`, `### Report view`; `artifact-server-design-research.md`, `## Concrete page recipes` | Single image, gallery, and HTML report views have concrete recipes and shared rules. |
| Information architecture and route model | COVERED | `artifact-server-design-research.md`, `### Suggested React structure`; `artifact-server-design-references.md`, `### Canvas-first shell`; `artifact-server-interaction-cost.md`, `### Deep links that restore state` | The documents cover shell zones, routes, drawers, deep links, and route restoration. |
| Navigation and wayfinding | COVERED | `artifact-server-design-research.md`, `### 1. Entry: land in the right context`; `artifact-server-interaction-cost.md`, `#### Get back to the list`; `artifact-server-design-references.md`, `### Arc` | Entry, gallery return, breadcrumbs, active item, and sidebar navigation are specified. |
| Gallery browsing model | COVERED | `artifact-server-design-research.md`, `### 2. Browse: scan without losing orientation`; `artifact-server-design-research.md`, `### Gallery review page`; `artifact-server-interaction-cost.md`, `#### Scan a gallery and pick one` | Gallery cards, keyboard behavior, sort intent, and return preservation are covered. |
| Search, filter, and sort | THIN | `artifact-server-design-research.md`, `### Filters and sorting`; `artifact-server-design-references.md`, `### Raycast`; `artifact-server-interaction-cost.md`, `### Persistent panel versus popover` | Thread filters and stable sort are covered, but artifact search, gallery-scale filtering, report-section search, and filter state across deep links remain underspecified. |
| Versioning, history, and provenance | THIN | `artifact-server-design-references.md`, `### GitHub pull request review threads`; `artifact-server-design-references.md`, `### Sentry`; `artifact-server-interaction-cost.md`, `### Deep links that restore state` | Provenance fields and previous-version thread handling are mentioned, but there is no full model for artifact versions, stale coordinates, history, or changed reports. |
| Review completion and done semantics | COVERED | `artifact-server-design-research.md`, `### 5. Done: close the loop`; `artifact-server-interaction-cost.md`, `#### Mark the whole artifact reviewed`; `artifact-server-design-philosophy.md`, `### Failure mode: review state is not finishable` | The distinction between thread resolution, artifact done, and feedback deliverable is explicit. |
| Compare workflow | THIN | `artifact-server-interaction-cost.md`, `#### Compare two artifacts`; `artifact-server-interaction-cost.md`, `### Direct manipulation instead of dialogs` | Compare has task budgets and sync rules, but no visual layout, responsive behavior, accessibility model, or entry criteria. |
| Onboarding and first-run | THIN | `artifact-server-design-research.md`, `### Empty, loading, and error states`; `artifact-server-design-references.md`, `### Notion`; `artifact-server-design-philosophy.md`, `### Failure mode: minimalism becomes mystery` | Empty states and shortcut help are covered, but first-run guidance and intermittent-user reorientation are not designed as a journey. |
| Personalization and persisted preferences | THIN | `artifact-server-interaction-cost.md`, `### Auto-save instead of explicit save`; `artifact-server-interaction-cost.md`, `### Predictive or last-used state`; `artifact-server-design-research.md`, `### Contrast and theming tests` | Density, theme, filters, panel width, and compare settings are mentioned, but persistence scope and safety rules are incomplete. |
| Layout and spatial allocation | COVERED | `artifact-server-design-research.md`, `### 3. Zoom and annotate: keep the canvas dominant`; `artifact-server-design-references.md`, `### Canvas-first shell`; `artifact-server-interaction-cost.md`, `### Keeping the artifact dominant` | Strong coverage exists for the three-zone layout, rail widths, and 60 percent canvas rule. |
| Responsive breakpoints | COVERED | `artifact-server-design-research.md`, `## Screen real estate strategy`; `artifact-server-design-references.md`, `### Canvas-first shell`; `artifact-server-design-philosophy.md`, `### Decision` | Desktop, tablet, and phone behavior is specified with collapse rules. |
| Density system | COVERED | `artifact-server-interaction-cost.md`, `## Managing information density`; `artifact-server-interaction-cost.md`, `### Concrete density limits`; `artifact-server-design-research.md`, `### Density and breathing room` | Density levels, visible-control limits, collapse rules, and token-multiplier guidance are clear. |
| Typography | COVERED | `artifact-server-design-research.md`, `### Type scale`; `artifact-server-design-references.md`, `### Visual language` | Typeface, sizes, line heights, weights, and use cases are specified. |
| Color and theming | COVERED | `artifact-server-design-research.md`, `## Color system`; `artifact-server-human-factors.md`, `### Contrast sensitivity in dark themes`; `artifact-server-design-philosophy.md`, `### W3C WCAG` | Dark and light palettes, contrast targets, semantic usage, and physiological rationale are covered. |
| Iconography | THIN | `artifact-server-design-research.md`, `### Affordance`; `artifact-server-design-research.md`, `#### Button`; `artifact-server-design-references.md`, `### Framer` | Icons are constrained as supplemental and target-sized, but icon style, set, semantics, and accessible naming standards are not defined. |
| Imagery, thumbnails, and artifact previews | COVERED | `artifact-server-design-research.md`, `### 2. Browse: scan without losing orientation`; `artifact-server-design-research.md`, `#### GalleryCard`; `artifact-server-design-references.md`, `### Vercel dashboard` | Thumbnail ratios, metadata, cards, and preview behavior are covered. |
| Depth, elevation, borders, and shadows | COVERED | `artifact-server-design-research.md`, `### Elevation and borders`; `artifact-server-human-factors.md`, `### Contrast sensitivity in dark themes`; `artifact-server-design-references.md`, `### Visual language` | The documents define dark-mode separation through borders, luminance steps, and limited shadows. |
| Motion and transitions | COVERED | `artifact-server-design-research.md`, `### Motion restraint`; `artifact-server-human-factors.md`, `### Motion sensitivity and vestibular triggers`; `artifact-server-design-references.md`, `### Notion Calendar` | Durations, restraint, reduced motion, and forbidden motion patterns are covered. |
| Visual hierarchy and information hierarchy | COVERED | `artifact-server-design-research.md`, `### Visual hierarchy`; `artifact-server-design-philosophy.md`, `### Step 2: Identify the primary object`; `artifact-server-design-philosophy.md`, `### Failure mode: the artifact stops being the hero` | The artifact, review layer, and app layer are explicitly ranked. |
| Microcopy, labels, and content voice | COVERED | `artifact-server-design-research.md`, `### Copy and labels`; `artifact-server-design-research.md`, `### Empty, loading, and error states`; `artifact-server-design-philosophy.md`, `### Jakob Nielsen, 10 usability heuristics` | Precise domain labels and several empty, error, and security copy examples are defined. |
| Data visualization, progress, and status summaries | THIN | `artifact-server-design-research.md`, `### 5. Done: close the loop`; `artifact-server-design-research.md`, `#### StatusPill`; `artifact-server-design-references.md`, `### Vercel dashboard` | Counts and status pills are covered, but there is no explicit stance on progress meters, activity timelines, charts, or dashboard-like summaries. |
| Component primitives and token governance | COVERED | `artifact-server-design-research.md`, `## Design tokens and frontend primitives`; `artifact-server-design-research.md`, `### Design-token adoption path`; `artifact-server-design-philosophy.md`, `### Material Design` | Token groups, primitives, component states, and adoption path are specific enough to guide implementation. |
| Design-system documentation and decision records | THIN | `artifact-server-design-philosophy.md`, `### Step 7: Record the outcome`; `artifact-server-design-philosophy.md`, `### Failure mode: implementation invents local design exceptions` | Decision recording is covered, but component documentation structure, ownership, change review, and examples are not. |
| Backend/API contract as UX | THIN | `artifact-server-design-research.md`, `### State boundaries`; `artifact-server-design-research.md`, `### Data loading`; `artifact-server-design-research.md`, `### 5. Done: close the loop` | The state categories are named, but API error shapes, optimistic mutation contracts, IDs, timestamps, export status, and conflict handling need UX-level specification. |
| Design testing and verification | THIN | `artifact-server-design-research.md`, `### Contrast and theming tests`; `artifact-server-design-research.md`, `## Design success criteria`; `artifact-server-design-philosophy.md`, `### Step 3: Gather required evidence` | Contrast, focus, screen-reader smoke tests, and success criteria are listed, but visual regression, keyboard task tests, density tests, and annotation-state verification are not fully defined. |
| Pointer interaction and target sizing | COVERED | `artifact-server-human-factors.md`, `## 2. Motor control`; `artifact-server-design-research.md`, `### Affordance`; `artifact-server-interaction-cost.md`, `### What costs the reviewer` | Fitts's law, target sizes, pointer travel, pin hit areas, and target placement are well covered. |
| Keyboard interaction and shortcuts | COVERED | `artifact-server-design-research.md`, `### Keyboard shortcuts`; `artifact-server-design-references.md`, `### Keyboard flow`; `artifact-server-interaction-cost.md`, `### Keyboard shortcuts and command palette` | The shortcut set, visible help, browser shortcut avoidance, and core keyboard flows are covered, with noted inconsistency below. |
| Touch and gesture interaction | THIN | `artifact-server-design-research.md`, `### Phone, under 768px`; `artifact-server-human-factors.md`, `### Why a 24 px pin differs from a 44 px touch target`; `artifact-server-interaction-cost.md`, `### Direct manipulation instead of dialogs` | Touch target sizes and phone constraints exist, but touch-specific region creation, gestures, drawer conflicts, and tablet workflows remain thin. |
| Deep zoom, pan, and tile interaction | COVERED | `artifact-server-design-research.md`, `### Canvas rules`; `artifact-server-design-research.md`, `### OpenSeadragon tile performance`; `artifact-server-interaction-cost.md`, `#### Zoom to a detail` | OpenSeadragon fit, zoom, reset, pointer zoom, tile loading, and performance constraints are covered. |
| Annotation creation and editing model | COVERED | `artifact-server-design-research.md`, `### Annotation rules`; `artifact-server-interaction-cost.md`, `#### Drop a pin and comment`; `artifact-server-human-factors.md`, `### Drag versus click cost` | Point and region creation, mode visibility, pending geometry, cancellation, save failure, and draft preservation are covered. |
| Selection model and thread synchronization | COVERED | `artifact-server-design-research.md`, `### Selection model`; `artifact-server-design-references.md`, `### Comment pins and threads`; `artifact-server-design-philosophy.md`, `### Gestalt grouping principles` | One selected target and bidirectional pin-thread synchronization are strongly covered. |
| Focus management and landmarks | COVERED | `artifact-server-design-research.md`, `### Landmarks and focus`; `artifact-server-design-research.md`, `#### AppShell`; `artifact-server-design-philosophy.md`, `### W3C WCAG` | Landmarks, initial focus, drawer focus, focus restoration, and focus rings are specified. |
| Forms, composer, text entry, and validation | THIN | `artifact-server-design-research.md`, `#### Input and Composer`; `artifact-server-design-research.md`, `#### ThreadCard`; `artifact-server-interaction-cost.md`, `### Auto-save instead of explicit save` | Composer behavior is covered, but validation rules, Markdown-lite scope, editing submitted comments, discard confirmation, and failed validation copy are thin. |
| Command palette and secondary action access | COVERED | `artifact-server-design-references.md`, `### Raycast`; `artifact-server-interaction-cost.md`, `### Keyboard-only or command-first path`; `artifact-server-design-research.md`, `### Progressive disclosure` | The palette role, examples, visibility rules, and constraints are clear. |
| State and feedback states | THIN | `artifact-server-design-research.md`, `### Feedback`; `artifact-server-design-research.md`, `### Empty, loading, and error states`; `artifact-server-human-factors.md`, `### Response thresholds and the Doherty threshold` | Loading, empty, error, save, resolve, and success are covered, but offline, stale, conflict, reconnect, partial tile failure, and long-running report states are incomplete. |
| Notifications, toasts, and alerts | COVERED | `artifact-server-design-research.md`, `### Feedback`; `artifact-server-human-factors.md`, `### Banner blindness`; `artifact-server-interaction-cost.md`, `### Concrete density limits` | Toast durations, placement, persistence, limits, and banner restraint are covered. |
| Error recovery and undo | COVERED | `artifact-server-design-research.md`, `### Feedback`; `artifact-server-human-factors.md`, `### Prevent, not just report, destructive or lossy actions`; `artifact-server-design-philosophy.md`, `### Don Norman, affordances, signifiers, mapping, and feedback` | Draft preservation, rollback, undo toast, retry, and local error placement are well covered. |
| Destructive action safety | COVERED | `artifact-server-human-factors.md`, `### Speed-accuracy trade-off`; `artifact-server-interaction-cost.md`, `### Modal or confirmation path`; `artifact-server-design-research.md`, `#### Dialog and Popover` | The documents define reversible versus destructive actions and when confirmation is required. |
| Threaded comment structure | COVERED | `artifact-server-design-research.md`, `### 4. Comment and resolve: make review state obvious`; `artifact-server-design-references.md`, `### GitHub pull request review threads`; `artifact-server-design-research.md`, `#### ThreadCard` | Thread anatomy, replies, metadata, location chip, actions, states, and dimensions are defined. |
| Resolution and reopen UX | COVERED | `artifact-server-design-research.md`, `### 4. Comment and resolve: make review state obvious`; `artifact-server-interaction-cost.md`, `#### Resolve a thread`; `artifact-server-design-philosophy.md`, `### Failure mode: review state is not finishable` | Resolve, reopen, undo, dimming, collapsed history, and finishability are covered. |
| Annotation visual states and pin density | COVERED | `artifact-server-design-references.md`, `### Comment pins and threads`; `artifact-server-interaction-cost.md`, `### Thread state without visual overload`; `artifact-server-human-factors.md`, `### Why a 24 px pin differs from a 44 px touch target` | Pin size, hit area, clustering, resolved hiding, hover geometry, and sync states are covered, with a color inconsistency noted below. |
| Author identity and single-reviewer authorship | THIN | `artifact-server-design-research.md`, `### 4. Comment and resolve: make review state obvious`; `artifact-server-design-references.md`, `### GitHub Projects and Issues`; `artifact-server-design-research.md`, `### Filters and sorting` | Author, initials, `Mine`, timestamps, and edited markers are mentioned, but their role in a no-auth single-reviewer app is not decided. |
| Export, raw artifact, and feedback JSON | THIN | `artifact-server-design-research.md`, `### 5. Done: close the loop`; `artifact-server-design-research.md`, `### Copy and labels`; `artifact-server-interaction-cost.md`, `### Keyboard-only or command-first path` | Copy feedback JSON and raw artifact are named, but export contract, status, failure recovery, batch export, and privacy implications are thin. |
| HTML report sandbox and security UX | COVERED | `artifact-server-design-research.md`, `### Report view`; `artifact-server-design-research.md`, `### HTML report page`; `artifact-server-human-factors.md`, `### Banner blindness` | Sandbox copy, scripts-disabled chip, raw active content risk, and report comments are covered. |
| Visual accessibility | COVERED | `artifact-server-design-research.md`, `### WCAG targets`; `artifact-server-human-factors.md`, `## 1. Vision and perception`; `artifact-server-design-philosophy.md`, `### W3C WCAG` | Contrast, color redundancy, dark-theme physiology, and non-color state indicators are covered. |
| Motor accessibility | COVERED | `artifact-server-human-factors.md`, `## 2. Motor control`; `artifact-server-design-research.md`, `### Affordance`; `artifact-server-design-research.md`, `### Phone, under 768px` | Target sizes, drag cost, keyboard alternatives, and touch imprecision are covered. |
| Cognitive accessibility | COVERED | `artifact-server-human-factors.md`, `## 3. Cognition and memory`; `artifact-server-interaction-cost.md`, `## Interaction cost model`; `artifact-server-design-philosophy.md`, `### Jakob Nielsen, 10 usability heuristics` | Choice limits, visible state, recognition over recall, and cognitive-load reduction are covered. |
| Screen reader and non-visual accessibility | COVERED | `artifact-server-design-research.md`, `### Annotation accessibility`; `artifact-server-human-factors.md`, `### Screen-reader users and spatial pins`; `artifact-server-design-philosophy.md`, `### W3C WCAG` | DOM thread mirrors, accessible names, live regions, coordinates, and realistic scope are covered. |
| Internationalization and text expansion | MISSING | None | No document covers localization policy, text expansion, date and number formats, bidirectionality, or whether the app intentionally stays English-only. |
| Print and offline portability | MISSING | None | No document covers print styles, PDF output, saved-page behavior, offline review packets, or whether these are explicitly out of scope. |
| Performance and perceived latency | COVERED | `artifact-server-design-research.md`, `## Performance and deep-zoom behavior`; `artifact-server-human-factors.md`, `### Response thresholds and the Doherty threshold`; `artifact-server-interaction-cost.md`, `### What costs the reviewer` | Tile loading, throttling, optimistic updates, skeletons, lazy thumbnails, and response thresholds are covered. |

## Prioritized gap list

### 1. State and feedback states

**Research question:** What exact UI state model covers loading, empty, success, saving, pending, failed, offline, stale, conflict, partial tile failure, and report sandbox load across images, galleries, reports, comments, and exports?

Create a state inventory by object: artifact, tile source, thread, reply, composer, annotation geometry, report frame, export job, and settings. For each state, define visible treatment, copy, recovery action, accessibility announcement, optimistic rollback behavior, and whether the user can continue independent work.

### 2. Versioning, history, and provenance

**Research question:** How should the UI represent artifact versions, prior-version annotations, changed coordinates, provenance metadata, and resolved history without becoming an asset library?

Map the lifecycle of a generated artifact from publish through review, replacement, and export. Define version badges, stale annotation rules, provenance drawer fields, deep-link behavior after version changes, and how much history remains visible by default.

### 3. Export, raw artifact, and feedback JSON

**Research question:** What is the exact UX contract for `Copy feedback JSON`, raw artifact access, download, export success, export failure, and downstream handoff?

Identify who consumes exported feedback and what they need to trust it. Define export labels, command palette entries, success and failure copy, batch behavior, JSON version display, copy-to-clipboard recovery, and whether export status is part of `Done`.

### 4. Search, filter, and sort

**Research question:** What search, filter, and sort model lets reviewers find artifacts, threads, report sections, unresolved work, and previous feedback without hiding important state?

Extend the existing thread-filter model to gallery, report, and global search. Specify defaults, visible filter chips, deep-link serialization, keyboard behavior, empty-filter states, result grouping, and rules for preserving stable spatial order.

### 5. Author identity and single-reviewer authorship

**Research question:** In a no-auth, effectively single-reviewer tool, what identity model should comments, filters, timestamps, edited markers, and `Mine` semantics use?

Decide whether author labels are fixed, inferred, editable, hidden, or derived from local config. Define what happens if a second reviewer appears later, whether `Mine` should ship now, and how identity affects export JSON and accessibility labels.

### 6. Forms, composer, text entry, and validation

**Research question:** What exact composer and text-entry rules prevent lost feedback while keeping comment creation fast?

Define Markdown-lite scope, edit and delete behavior, submit shortcuts, validation errors, maximum lengths, pasted content, draft autosave, discard confirmation, retry, copy-text recovery, and how composer focus behaves across panel close, navigation, and failed save.

### 7. Touch and gesture interaction

**Research question:** What can touch users reliably do on phone and tablet, and which desktop review features should intentionally degrade?

Prototype point comments, region comments, pan, zoom, bottom sheet comments, drawer opening, hit slop, and accidental gesture recovery on touch. Decide if region drawing is desktop-first, how touch users edit annotations, and how hover-only affordances translate.

### 8. Trust model and no-auth UX

**Research question:** How should the trusted-tailnet, no-auth model be visible enough to prevent wrong assumptions without adding account chrome?

Define copy for private links, raw artifact access, report sandboxing, error states, and export actions. Decide whether the UI ever says `Private tailnet`, how it warns about opening raw active content, and how it avoids implying multi-user permissions that do not exist.

### 9. Backend/API contract as UX

**Research question:** Which backend state and mutation guarantees must the frontend design depend on, and how are violations shown?

Define visible semantics for IDs, timestamps, ordering, save failure, conflict, reconnect, stale data, export status, and optimistic rollback. Align copy and interaction rules with the actual C#/.NET API response shapes before component implementation hard-codes assumptions.

### 10. Design testing and verification

**Research question:** What automated and manual checks prove the design system actually meets the documented design rules?

Build a verification matrix for token contrast, focus rings, keyboard task flows, screen-reader smoke tests, reduced motion, visual regression for component states, annotation sync, and density limits. Define required fixtures for dark mode, light mode, high-density comments, large images, failed saves, and sandboxed reports.

### 11. Onboarding and first-run

**Research question:** How does an intermittent reviewer learn `inspect, annotate, discuss, resolve, continue` in under one minute without a tutorial becoming permanent chrome?

Design first empty states, shortcut help, visible hints, command palette discovery, and a first-comment nudge. Define when hints disappear, how they are rediscovered, and how direct deep links explain context to someone who did not start from the gallery.

### 12. Personalization and persisted preferences

**Research question:** Which UI preferences should persist, where should they persist, and how does the app prevent saved state from hiding work?

Classify preferences into safe local memory, per-artifact URL state, per-session state, and never-persisted state. Cover theme, density, panel width, filter, sort, compare sync, viewport, selected thread, and draft text with clear visibility and reset rules.

### 13. Compare workflow

**Research question:** Should compare be a first-build feature, and if so, what visual, keyboard, accessibility, and comment model does it use?

Turn the interaction-cost sketch into a full page state. Define entry points, adjacent compare, arbitrary compare picker, synchronized pan and zoom, splitter behavior, keyboard navigation, responsive fallback, deep links, and how each artifact's comments remain separate.

### 14. Data visualization, progress, and status summaries

**Research question:** What progress or status summaries are useful for review completion, and which would turn the app into a dashboard?

Inventory possible summaries: open count, resolved count, done count, export status, gallery progress, activity timeline, and error count. Decide which remain status pills or text, which never become charts, and how progress appears in gallery and top bar without stealing artifact focus.

### 15. Design-system documentation and decision records

**Research question:** What documentation must accompany primitives, tokens, exceptions, and design decisions so implementation does not invent local patterns?

Define a design-system documentation shape for each primitive: purpose, anatomy, states, keyboard behavior, accessibility behavior, tokens, examples, anti-examples, and usage limits. Link this to the decision procedure and define when a new primitive or token exception requires a recorded design decision.

### 16. Iconography

**Research question:** What icon style and icon-label policy gives the app quiet density without hiding meaning from occasional reviewers or assistive tech?

Choose an icon source or style, stroke weight, size, filled versus outline policy, semantic mapping, tooltip rules, and accessible names. Specify which actions require visible labels, which may use icon-only buttons, and how error, warning, resolved, selected, and hidden states differ beyond color.

### 17. Internationalization and text expansion

**Research question:** Is the rewrite intentionally English-only, or must it preserve layout and semantics under localization, text expansion, locale formats, and bidirectional text?

If English-only, record that as an explicit product decision with revisit triggers. If localization may matter, define string length budgets, truncation, timestamp format, number format, keyboard shortcut display, right-to-left layout constraints, and how long status labels fit in pills and rails.

### 18. Print and offline portability

**Research question:** Are print, PDF, saved-page, offline review packet, or portable feedback outputs in scope, explicitly out of scope, or deferred?

Decide whether reviewers ever need a printable report, static evidence bundle, or offline handoff. If out of scope, record why; if in scope, specify which surfaces print, how annotations and comments are represented, and how exported feedback remains tied to artifact versions.

## Contradictions and inconsistencies

### 1. Unresolved pin color conflicts with selected-only accent use

`artifact-server-design-references.md`, `### Figma comments` says: "Unresolved pins should use the accent color, resolved pins should become low-contrast outlines or disappear behind a resolved filter."

`artifact-server-design-research.md`, `### Annotation rules` says: "Annotation pins use the accent color only for active or selected state." It also says: "Unselected pins use neutral outlines so the image remains dominant."

**Which should win:** The selected-only accent rule should win because it is more specific to this product's artifact-first visual system and better supports the color system rule that accent blue marks current task state. Unresolved pins still need visibility, but that should come from thread numbers, filters, labels, hit areas, and panel counts rather than making every open pin accent-colored.

### 2. Keyboard navigation uses two competing next and previous models

`artifact-server-design-references.md`, `### Keyboard flow` says: "`J` and `K`: next and previous thread or artifact, depending on focus."

`artifact-server-design-research.md`, `### Keyboard shortcuts` says: "`[` | Previous thread or annotation" and "`]` | Next thread or annotation". `artifact-server-interaction-cost.md`, `### Keyboard shortcuts and command palette` repeats "`[` and `]` for previous and next thread."

**Which should win:** `[` and `]` should win for annotation and thread traversal because they are repeated in the more detailed interaction and accessibility sections. `J` and `K` can remain an optional list-navigation enhancement only if documented by focus context and never required for the core review loop.

### 3. Viewer toolbar placement is not settled

`artifact-server-design-references.md`, `### Framer` says: "Place it near the bottom center or top center of the image viewport, with icon buttons around 36 to 40 px and a translucent dark background."

`artifact-server-design-research.md`, `### Canvas rules` says: "Zoom controls: visible but quiet, grouped in a floating vertical toolbar." The desktop diagram in `artifact-server-design-research.md`, `### 3. Zoom and annotate: keep the canvas dominant` shows "left rail" and "56px tools" beside the canvas.

**Which should win:** The implementation should follow `artifact-server-design-research.md`, `#### ViewerToolbar`: "Floating toolbar over the canvas, vertical on desktop, horizontal on phone." The exact edge or center placement can be decided by artifact overlap testing, but the component contract should be one toolbar primitive, not competing left-rail and centered-toolbar patterns.

### 4. Open comment status color is inconsistent

`artifact-server-design-research.md`, `### Semantic usage` says: "Accent blue: selected, current, primary action." It also says: "Never use red for unresolved comments. Unresolved is normal work, not an error. Use amber or neutral plus label."

`artifact-server-design-research.md`, `#### StatusPill` says: "`Open comments`: blue dot, neutral pill."

**Which should win:** The semantic usage rule should win. `Open comments` should use a neutral or amber treatment plus a clear label unless it is the currently selected filter or task state; blue should remain reserved for selected, current, and primary action state.
