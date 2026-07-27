# Artifact Review Server Design Philosophy

## Purpose of this document

This document defines how design decisions should be made for the artifact review server rewrite. The research document defines what the UI should contain. The references document defines product patterns worth borrowing. This philosophy document defines the decision framework: what the interface is for, what it optimizes, what it sacrifices, and how future implementers should resolve design conflicts.

The central product judgement is this: the artifact is the primary object, and every interface choice must help a reviewer inspect it, attach feedback to it, resolve discussion around it, or move to the next artifact with confidence.

## Product philosophy

The artifact review server is a focused review instrument. It is not a dashboard, file browser, chat app, image editor, issue tracker, or team workspace. It exists to make generated visual artifacts easier to inspect and finish.

The UI optimizes for:

1. **Visual primacy:** the artifact receives the most space, the quietest surrounding chrome, and the strongest spatial continuity.
2. **Review completion:** comments are not loose chat. They are threaded, anchored when possible, and resolvable.
3. **Low-friction feedback:** a trusted private tailnet and effectively single-reviewer model justify fewer permissions, fewer confirmations, and faster optimistic interactions.
4. **Accessible precision:** canvas interactions must be mirrored in keyboard and DOM-accessible thread structures.
5. **Stable mental models:** selecting an annotation, selecting a thread, and viewing artifact status must always describe the same review object.

The UI deliberately sacrifices:

1. **Enterprise collaboration depth:** no roles, invites, assignments, notifications, permissions, or approval matrices unless the trust model changes.
2. **Decorative branding:** color, motion, and illustration are subordinate to artifact inspection.
3. **General-purpose content management:** artifact provenance matters, but the app should not become an asset library or admin dashboard.
4. **Maximum visible controls:** secondary actions belong in drawers, menus, or a command palette when they would compete with the canvas.
5. **Perfect feature symmetry across devices:** phone support should allow viewing and lightweight replying, not full desktop-grade region review.

## Schools of thought and how this product uses them

### Dieter Rams, ten principles for good design

Rams argues that good design is useful, understandable, unobtrusive, honest, long-lasting, thorough, and as little design as possible. This product takes Rams' restraint seriously: every visible element must earn its place by supporting inspection, annotation, resolution, navigation, or recovery from error.

What this product takes:

- Usefulness over novelty. A visible `Resolve thread` action is better than a novel gesture.
- Unobtrusiveness. Panels, borders, and controls should recede so the artifact remains dominant.
- Thoroughness. Empty, loading, failed save, resolved, reopened, and filtered states need real design, not afterthought copy.
- Less but better. Avoid project-management bloat in a tool whose trust model does not need it.

What this product rejects:

- Minimalism as absence. Hiding core review actions would fail first-time reviewers and keyboard users. The app should be quiet, not cryptic.
- Timelessness as visual neutrality only. Generated artifacts may be dense and technical, so the interface needs strong state language even when the chrome is restrained.

### Don Norman, affordances, signifiers, mapping, and feedback

Norman's framework from *The Design of Everyday Things* is the main interaction standard for this app. Canvas tools are powerful only if users can tell what can be done, what mode they are in, what object is selected, and what happened after an action.

What this product takes:

- Affordances and signifiers. Buttons need recognizable shape, label or icon, state, and focus treatment.
- Mapping. Thread cards and annotation pins must select, highlight, and scroll to each other consistently.
- Feedback. Create, save, resolve, reopen, zoom, filter, and load operations must show immediate state within roughly 100 ms when possible.
- Error recovery. Failed saves must preserve draft text and pending geometry.

What this product rejects:

- Reliance on perceived affordance alone for canvas actions. A deep-zoom viewer is not self-explanatory, so visible tools and shortcut help are required.
- Mode ambiguity. If comment mode exists, the UI must make the mode visible and easy to exit.

### Edward Tufte, data-ink and chartjunk

Tufte's data-ink principle and critique of chartjunk apply to review chrome even though the app is not primarily a charting tool. Non-artifact pixels are expensive because they compete with the artifact itself.

What this product takes:

- Maximize useful pixels. Canvas, annotations, thread text, and necessary status count as useful review information.
- Remove non-informative decoration. Saturated panels, decorative cards, heavy shadows, and animated flourishes are suspect by default.
- Prefer direct labeling and local context. Put status near the object it describes: artifact status in the top bar, thread status inside the card, selected annotation state on the pin and region.

What this product rejects:

- Pure data-ink austerity. Reviewers also need orientation, safety, and accessibility. Borders, focus rings, empty-state guidance, and status chips are not chartjunk when they prevent mistakes.

### Jakob Nielsen, 10 usability heuristics

Nielsen's heuristics are the product's usability checklist. They are especially relevant because the app is likely used intermittently by reviewers who should not need training.

What this product takes:

- Visibility of system status. Loading, saving, failed, resolved, reopened, filtered, and done states must be visible.
- Match between system and real world. Use review language: `thread`, `comment`, `resolve`, `reopen`, `artifact`, `open raw artifact`, and `copy feedback JSON`.
- User control and freedom. `Esc`, undo for resolve, draft preservation, and reversible filters matter.
- Consistency and standards. One selected review target, one status vocabulary, one panel model.
- Recognition rather than recall. Core actions need visible controls, not shortcuts only.

What this product rejects:

- Generic heuristic compliance detached from the workflow. For example, more visibility is not automatically better if showing every pin creates noise that makes the artifact harder to inspect.

### Gestalt grouping principles

Gestalt principles explain how reviewers perceive relationships between pins, regions, thread cards, metadata, and panels. The product uses proximity, similarity, enclosure, continuity, and common fate to make review state legible.

What this product takes:

- Proximity. Thread actions belong inside the thread card. Artifact actions belong near artifact status.
- Similarity. Open, selected, pending, failed, resolved, and reopened states must use consistent visual treatments across pins and cards.
- Enclosure. Panels and cards group related review objects without heavy decoration.
- Continuity. Selecting a thread should pan or highlight the corresponding annotation without disorienting page changes.
- Common fate. Hovering or selecting a pin and its card together shows they are one object.

What this product rejects:

- Decorative grouping. Grouping exists to clarify task relationships, not to create ornamental sections.
- Over-grouping. Too many nested surfaces make the app feel like an admin console.

### Apple Human Interface Guidelines

Apple's guidance is useful for clarity, direct manipulation, forgiving interaction, focus management, and platform expectations. The app should feel polished and predictable, even though it is a web tool rather than a native app.

What this product takes:

- Clarity. Text, hierarchy, target size, and state should be obvious in dark mode.
- Deference to content. The artifact is content, so controls defer to it.
- Direct manipulation. Pan, zoom, select, and annotate should feel immediate.
- Forgiveness. Reversible resolve, draft persistence, and non-destructive filters are required.

What this product rejects:

- Native-platform mimicry. The app should not copy macOS controls or mobile sheet behavior when web conventions are clearer.
- Aesthetic polish over workflow proof. The first build should validate inspect, comment, resolve, and navigate before polishing secondary motion.

### Material Design

Material Design is useful as a systematic component and token discipline: surfaces, elevation, motion, accessibility, and reusable components. It should influence structure, not make the app look like a generic Material app.

What this product takes:

- Design tokens for color, spacing, type, radius, border, shadow, and motion.
- Components with defined states, sizes, density, and accessibility behavior.
- Motion that explains spatial change, especially drawers, panels, selected rows, and popovers.
- Theming discipline, with dark mode first and light mode derived rather than reinvented.

What this product rejects:

- Bright, brand-heavy surfaces. The artifact server needs quieter chrome than many dashboard templates.
- Component library defaults as design decisions. OpenSeadragon, Annotorious, and any UI package must be mapped into the app's review-specific design system.

### W3C WCAG

WCAG is not a visual style, but it is a binding design constraint for this product. Canvas annotation is inherently hard for some assistive technologies, so every spatial object needs an accessible parallel in the thread list.

What this product takes:

- WCAG AA contrast as the minimum for text and meaningful UI components.
- Keyboard access for core review tasks.
- Visible focus indicators.
- Non-color indicators for state.
- Reduced motion support.
- Text alternatives or DOM equivalents for visual annotation state.

What this product rejects:

- Treating canvas accessibility as optional because the primary artifact is visual. The artifact may be visual, but review state, comments, controls, and workflow must remain accessible.

## Decision procedure

Before making any design choice, run this procedure in order. If the choice is small, record the answers briefly in the issue, PR, or design note. If the choice changes layout, workflow, accessibility behavior, terminology, data model, or long-term product direction, record it as a design decision with rationale.

### Step 1: Name the review job

State the user job in one sentence:

- What is the reviewer trying to inspect, decide, write, resolve, or recover from?
- Is the object an artifact, annotation, thread, reply, status, gallery item, report, or system error?

If the answer is not tied to review work, the feature is suspect.

### Step 2: Identify the primary object

Choose one primary object for the moment. The valid hierarchy is:

1. Artifact content.
2. Selected annotation or thread.
3. Review status and progress.
4. Navigation.
5. Metadata and settings.

A design that gives two objects equal priority must justify why the reviewer needs both at the same time.

### Step 3: Gather required evidence

Use the strongest available evidence, in this order:

1. Existing product requirements and trust model.
2. Existing design research and reference docs.
3. Accessibility requirements from WCAG and keyboard behavior.
4. Actual artifact examples, including dense images, sparse images, galleries, and HTML reports.
5. Implementation constraints from OpenSeadragon, Annotorious, React, and backend APIs.
6. Reviewer behavior from observed use, issue comments, or support notes.
7. Product judgement, clearly labelled when evidence is incomplete.

Do not decide from personal preference alone.

### Step 4: Test against the design principles

Ask these questions in order:

1. Does this keep the artifact visually dominant?
2. Does this make review state more finishable?
3. Does this preserve spatial mapping between artifact, annotation, and thread?
4. Does this provide clear affordance, feedback, and recovery?
5. Does this meet keyboard, focus, contrast, and non-color accessibility requirements?
6. Does this reduce cognitive load for the next reviewer action?
7. Does this reuse tokens and primitives rather than inventing a local pattern?
8. Does this avoid collaboration, dashboard, or decoration bloat?

A design that fails questions 1, 3, or 5 needs redesign unless there is an explicit product decision explaining why.

### Step 5: Resolve conflicts with the weighting rule

When principles conflict, use this order of precedence:

1. **Safety and accessibility:** never trade away keyboard access, contrast, focus, draft preservation, or clear error recovery for visual quiet.
2. **Artifact primacy:** when safe and accessible, preserve the artifact's space and legibility over panels, metadata, and decorative polish.
3. **Review completion:** prefer choices that make open, resolved, failed, and done states easier to act on.
4. **Spatial continuity:** avoid route changes, modal stacks, or reflows that break the relationship between image and comment.
5. **First-time clarity:** visible affordance beats hidden speed for core actions.
6. **Power-user speed:** shortcuts and command palette improve repeated work, but cannot be the only path.
7. **Aesthetic restraint:** quietness is valuable only after the above needs are met.

### Step 6: Choose the smallest coherent pattern

Prefer a reusable pattern that can support future cases without becoming generic. Good choices usually map to an existing primitive: `Panel`, `ThreadCard`, `StatusPill`, `ViewerToolbar`, `Drawer`, `Popover`, `CommandPalette`, or `EmptyState`.

If the choice requires a new primitive, define:

- The user job it serves.
- Its states.
- Its keyboard behavior.
- Its accessibility behavior.
- Its token usage.
- Where it must not be used.

### Step 7: Record the outcome

Record the decision where future implementers will find it:

- Small component choice: PR description or issue comment.
- Layout or interaction rule: this philosophy document or the design research document.
- Architecture or scope decision: a dated design decision note in the project's decision log.
- Accessibility exception: issue plus follow-up ticket, with the temporary mitigation and risk.

The record must include:

1. Decision.
2. Alternatives considered.
3. Evidence used.
4. Principles applied.
5. Known risks.
6. Review date or trigger for revisiting.

## Worked example: should the comment rail be always visible or collapsible?

### Step 1: Review job

The reviewer needs to inspect the artifact, see open feedback, select a thread, jump to its annotation, and resolve or reply.

### Step 2: Primary object

The primary object is the artifact. The selected thread is secondary but often needed during review.

### Step 3: Evidence

- Existing research recommends a right comments panel around `360px` to `420px` on desktop.
- OpenSeadragon needs enough space for pan and zoom inspection.
- Thread resolution is core to finishing review.
- Narrow screens cannot keep both canvas and rail visible without harming the artifact.
- WCAG and keyboard requirements require the thread list to remain reachable even when hidden.

### Step 4: Principle test

An always-visible rail improves review state visibility, but can reduce artifact space. A fully hidden rail preserves the canvas, but weakens discoverability and makes comments feel detached.

### Step 5: Conflict resolution

Artifact primacy wins over permanent chrome, but review completion requires a visible path to comments.

### Decision

Use an always-visible right comment rail by default on desktop when the artifact still receives at least 60 percent of horizontal space. Collapse or overlay the rail when keeping it open would reduce the artifact below that threshold. Keep a persistent comment toggle with open-count and unresolved-count badges whenever the rail is collapsed.

### Consequences

- Desktop reviewers see comments immediately.
- Tablet and phone reviewers get canvas-first viewing.
- The comment toggle becomes a required visible control, not a hidden menu item.
- Thread and pin selection must still synchronize when the rail opens or closes.

## Core tensions and product stances

### Information density versus breathing room

Stance: favor useful density inside review panels, and breathing room around the artifact.

Rule: the canvas gets spatial calm, panels get compact structure. Thread cards may use dense metadata, but the viewer surround should avoid busy decorations, dense toolbars, and unnecessary text.

Reasoning: review work requires both close visual inspection and fast thread scanning. Treating the whole app as spacious wastes panel utility. Treating the whole app as dense damages artifact inspection.

### Discoverability versus visual quiet

Stance: core actions must be visible, secondary actions may be quiet.

Rule: add comment, toggle comments, resolve, reopen, next or previous artifact, zoom, reset, and shortcut help need visible entry points. Raw artifact, copy JSON, filters, diagnostics, and advanced settings can live in menus, drawers, or command palette.

Reasoning: Rams-style restraint is useful only after Norman-style affordance is satisfied. A quiet interface that hides commenting or resolving fails the product.

### Power-user speed versus first-time clarity

Stance: first-time clarity wins for core actions, power-user speed wins for repeated secondary actions.

Rule: every shortcut must have a visible or command-palette-discoverable equivalent. No core action may exist only as a shortcut. Repeated navigation, filtering, and export actions should be fast from the keyboard.

Reasoning: reviewers may use the tool intermittently. Hidden speed paths help experts, but they cannot be the only path through a review.

### Consistency versus context-specific optimization

Stance: keep conceptual models consistent, adapt layout behavior to context.

Rule: `Artifact`, `Annotation`, `Thread`, `Reply`, and `Resolution` mean the same thing across image, gallery, and report views. Layout may change by screen size and artifact type, but state language and interaction outcomes should not.

Reasoning: consistency supports learning and implementation quality. Context-specific layout is still necessary because images, galleries, and HTML reports impose different viewing constraints.

### Aesthetic minimalism versus functional completeness

Stance: functional completeness wins, then minimalism edits the presentation.

Rule: if a visible element prevents lost work, blocked review, inaccessible state, or ambiguous selection, it stays. Once function is covered, reduce color, weight, animation, and duplication.

Reasoning: this product is a workbench. It should feel calm, but not at the cost of resolution, recovery, or accessibility.

## Anti-goals

The rewrite should not become:

1. **A project-management system:** assignments, priorities, milestones, sprints, and notification rules are out of scope unless the workflow changes.
2. **A team collaboration suite:** authentication, roles, invites, and sharing controls contradict the current trusted-tailnet model.
3. **A decorative portfolio gallery:** beautiful cards are secondary to review status, comments, and navigation.
4. **An image editor:** annotations are for review feedback, not pixel editing or design production.
5. **A chat app:** comments are threaded review objects with resolution state, not an endless conversation stream.
6. **An admin dashboard:** metadata exists to support review, not to dominate the artifact.
7. **A component-library showcase:** primitives serve the artifact review workflow, not the reverse.

## Failure modes and early warning signs

### Failure mode: the artifact stops being the hero

Warning signs:

- The top bar, rails, or cards visually dominate the first screen.
- The canvas receives less than 60 percent of desktop width in normal review mode.
- Metadata is visible more often than comments.
- Decorative colors compete with annotation state.

### Failure mode: comments become detached from the image

Warning signs:

- Selecting a thread does not highlight or center its annotation.
- Selecting a pin does not reveal its thread.
- Resolved pins remain as visually loud as open pins.
- Filters hide annotations without making the thread-list state clear.

### Failure mode: review state is not finishable

Warning signs:

- Open, resolved, failed, pending, reopened, and done states are visually inconsistent.
- Resolve requires a modal or feels destructive without undo.
- Done state is ambiguous or depends on hidden backend rules.
- Comment counts update only after refresh.

### Failure mode: minimalism becomes mystery

Warning signs:

- First-time reviewers cannot find add comment, resolve, or next artifact.
- Shortcuts are required for normal use.
- Toolbar icons have no labels, tooltips, or help entry.
- Empty states are blank or decorative instead of instructional.

### Failure mode: accessibility is bolted on late

Warning signs:

- Annotation pins have no accessible names.
- Threads do not mirror annotation location.
- Focus disappears inside the viewer, drawer, or toolbar.
- Color alone communicates selected, failed, or resolved state.
- Reduced-motion behavior is not defined.

### Failure mode: implementation invents local design exceptions

Warning signs:

- Components use one-off colors, spacing, shadows, or typography.
- Annotorious default styles leak into production without token mapping.
- Similar states look different in gallery cards, thread cards, and pins.
- A new primitive is added without states, keyboard behavior, or usage limits.

### Failure mode: trusted-tailnet simplicity is lost

Warning signs:

- Screens appear for accounts, roles, permissions, sharing, or invitations.
- Error copy assumes hostile or multi-tenant users.
- Single-reviewer workflows require multi-reviewer ceremony.
- Export or feedback JSON is hidden behind collaboration concepts.

## Sources

- Dieter Rams, "Ten principles for good design," commonly dated 1970s, published by Vitsœ as "The power of good design." Verified URL: https://www.vitsoe.com/us/about/good-design
- Don Norman, *The Design of Everyday Things: Revised and Expanded Edition*, 2013. Verified author page URL: https://jnd.org/the-design-of-everyday-things-revised-and-expanded-edition/
- Edward R. Tufte, *The Visual Display of Quantitative Information*, 1983, second edition 2001. Verified official books page URL: http://www.edwardtufte.com/books/
- Jakob Nielsen, "10 Usability Heuristics for User Interface Design," Nielsen Norman Group, 1994, last reviewed 2024. Verified URL: https://www.nngroup.com/articles/ten-usability-heuristics/
- Max Wertheimer, "Laws of Organization in Perceptual Forms," 1923, English version in *A Source Book of Gestalt Psychology*, 1938. Verified hosted text URL: https://psychclassics.yorku.ca/Wertheimer/Forms/forms
- Apple, *Human Interface Guidelines*. Verified URL, page date not shown: https://developer.apple.com/design/human-interface-guidelines/
- Google, *Material Design 3 Foundations*. Verified URL, page date not shown: https://m3.material.io/foundations
- World Wide Web Consortium, *Web Content Accessibility Guidelines (WCAG) 2.2*, W3C Recommendation, 12 December 2024. Verified URL: https://www.w3.org/TR/WCAG22/
