# Artifact Review Server Design Tension Navigation

## Purpose

This document explains how the core design tensions interact during real product decisions for the artifact review server rewrite. The catalogue defines each tension in isolation. This document defines compound effects, duplicate variables, propagation rules, decision order, symptom lookup, and contradiction resolution.

Claims are drawn from `artifact-server-design-tensions.md`, `artifact-server-design-philosophy.md`, and `artifact-server-design-axis-coverage.md` unless marked as a judgement call.

## Decision shortcut

When a design choice feels stuck, do this:

1. Name the review job: inspect, comment, resolve, navigate, or recover.
2. Identify the primary object: artifact, selected annotation or thread, review status, navigation, or metadata.
3. Apply the hard floors: accessibility, draft preservation, focus, recovery, and safety.
4. Protect the artifact: canvas space, viewer responsiveness, and annotation legibility.
5. Make core actions visible, then quiet everything secondary.
6. Put unavoidable complexity where it costs least: rail, drawer, command palette, local inline state, or keyboard shortcut.

## Compounding pairs

These pairs make each other worse when they appear together. Treat them as risk multipliers, not independent checks.

| Tensions | How they compound | App example | Navigation rule |
| --- | --- | --- | --- |
| 2. Information density versus calm + 4. Discoverability versus visual quiet | More visible controls increase density, while dense state makes visible controls harder to notice. | A canvas with unresolved pins, a floating zoom toolbar, add-comment mode, and a right rail can make the artifact feel framed by UI instead of reviewed through UI. | Keep only inspect, comment, resolve, navigate, and recover visible. Move provenance, raw artifact, copy JSON, filters, and diagnostics into rail sections, drawers, menus, or command palette. |
| 3. Expert speed versus newcomer clarity + 11. Safety versus friction | Speed pushes toward one-step actions. Safety pushes toward confirmation. Repeated review makes confirmation fatigue likely. | Resolving ten threads in a batch should not open ten dialogs, but accidental resolve must not feel permanent. | Resolve and reopen are immediate and reversible with undo. Destructive deletion, losing unsaved text, or replacing artifact data uses explicit confirmation naming the object. |
| 5. Consistency versus context optimization + 13. Accessibility versus visual ambition | Layout adaptation can preserve space, but inconsistent DOM order, labels, or focus paths break accessibility. | A phone gallery may collapse the thread rail into a bottom sheet, but thread, pin, resolve, reopen, and selected state must still be the same review object model. | Layout may adapt by artifact type and viewport. Names, states, keyboard contracts, focus restoration, and selection semantics may not drift. |
| 8. Automation versus user control + 9. Immediate feedback versus interruption | Invisible automation weakens trust. Excess feedback from automation steals attention. | Auto-restoring the last zoom and selected thread is useful, but a toast for every restored panel, sort, and viewport would interrupt inspection. | Automate safe restoration silently when it does not hide unresolved work. Show local state for mutations and failures. Reserve toast for undo and failures. |
| 14. Performance versus richness + 13. Accessibility versus visual ambition | Rich overlays and DOM mirrors add value and cost. Accessibility cannot be dropped to save render time. | Annotorious regions, pins, thread-card mirrors, live selection, and gallery thumbnails can overload the browser while panning deep zoom tiles. | Protect pan, zoom, select, type, and resolve first. Lazy-load reports, metadata, history, and non-visible gallery assets after the review shell is usable. Keep thread-list equivalents for annotations. |
| 10. Aesthetic appeal versus usability + 13. Accessibility versus visual ambition | Polished dark UI often tempts low contrast, subtle focus, motion, or color-only states. | A beautiful translucent thread rail can fail if focus rings disappear and resolved or failed comments differ only by color. | Polish may clarify hierarchy, state, and calm only after WCAG AA contrast, focus visibility, non-color state, reduced motion, and keyboard operation are satisfied. |
| 6. Flexibility versus opinionated defaults + 7. Recognition versus recall | Preferences hide complexity until users must remember what they changed. Recognition-heavy settings screens create choice overload. | Persisting a filter that hides resolved or unresolved work can make a reviewer think a gallery is clean when it is only filtered. | Persist preferences only after repeated real workaround evidence. Saved state that can hide work needs visible chips, reset, and deep-link serialization. |
| 1. Simplicity versus capability + 15. Generality versus review-specific primitives | Generic primitives make the UI look simple at first, then push review meaning into props, copy, and local exceptions. | A generic `Card` with comment props cannot consistently express selected thread, pending save, failed reply, resolved history, and pin synchronization. | Build primitives named for review objects, such as `ArtifactViewer`, `AnnotationPin`, `ThreadCard`, `ReviewStatus`, `ViewerToolbar`, and `CommentComposer`. Tokens stay general. |
| 12. Novelty versus familiarity + 3. Expert speed versus newcomer clarity | Novel direct manipulation can be fast after learning, but first use becomes risky if common web paths are missing. | A gesture-only region annotation mode may feel efficient to the designer and impossible to discover for an intermittent reviewer. | Use familiar web patterns for navigation, panels, buttons, comments, forms, focus, and undo. Reserve novelty for viewer manipulation with visible mode, help, and escape paths. |
| 9. Immediate feedback versus interruption + 2. Information density versus calm | Every local status mark solves uncertainty, but many status marks become noise. | Thread cards showing saving, failed, edited, resolved, reopened, filtered, and selected at once can become harder to scan than the artifact. | Status belongs near the object it describes. Combine visual weight: selected and failed are loudest, pending is quiet, resolved is dim or collapsed. |

## Disguised duplicates

Some catalogue tensions are separate because they help audits, but they share the same underlying variable during surface design.

| Catalogue tensions | Duplicate judgement | Single underlying variable | How to use this |
| --- | --- | --- | --- |
| 3. Expert speed versus newcomer clarity + 7. Recognition versus recall | Judgement call: these collapse into one tension for core review-loop actions. | Where task knowledge lives: visible in the interface, discoverable through help, or remembered by the reviewer. | For add comment, resolve, reopen, next, previous, fit, reset, and help, require visible or command-palette-discoverable paths plus keyboard speed. Do not debate them separately. |
| 4. Discoverability versus visual quiet + 10. Aesthetic appeal versus usability | Partial duplicate. | Attention spent on interface rather than artifact. | Treat both as an attention-budget problem after accessibility and function are met. A beautiful hidden control and an ugly loud control fail for opposite reasons. |
| 1. Simplicity versus capability + 15. Generality versus fitness for purpose | Partial duplicate. | Where conserved complexity is stored: product workflow, component contracts, or user memory. | Prefer review-specific primitives when generic simplicity would force many local exceptions or unclear names. |
| 2. Information density versus calm + 4. Discoverability versus visual quiet | Not duplicates, but easy to confuse. | Density is how many facts are present. Discoverability is whether an action can be found. | A dense rail can be acceptable if the canvas stays calm. A quiet toolbar can fail if core actions disappear. |
| 5. Consistency versus context optimization + 12. Novelty versus familiarity | Not duplicates. | Consistency concerns this product's internal model. Familiarity concerns learned conventions from other products. | A report view may use a familiar document pattern while still preserving this product's annotation and thread model. |

## Constraint propagation

Each chain shows how one stance forecloses another option and where the cost must move.

1. The stance that core actions must be visible implies you may no longer put `Resolve thread` only in an overflow menu, so `ThreadCard` must absorb the cost through a clear action row, keyboard shortcut, and quiet visual treatment.
2. The stance that the artifact should keep at least 60 percent of desktop width implies you may no longer keep metadata, history, filters, and comments open as peer rails, so drawers, progressive disclosure, and compact status pills must absorb the cost.
3. The stance that every annotation needs a thread-list equivalent implies you may no longer build canvas-only review objects, so the thread rail must absorb accessible names, state, selection, actions, and coordinate references.
4. The stance that automation must never auto-resolve comments, auto-mark artifacts done, or silently hide unresolved work implies you may no longer use cleanup automation to reduce visible workload, so `ReviewStatus`, filters, and gallery cards must absorb unresolved counts and done semantics.
5. The stance that reversible actions use undo rather than confirmation implies you may no longer use confirmation dialogs for routine resolve and reopen, so local state, undo toast, and draft preservation must absorb safety.
6. The stance that viewer responsiveness comes first implies you may no longer eager-load report frames, history, provenance, and offscreen gallery assets before the shell is usable, so skeletons, lazy loading, and per-object pending states must absorb completeness.
7. The stance that preferences are added only after repeated real workaround evidence implies you may no longer solve uncertainty by adding early settings, so opinionated defaults, visible reset, and command palette access must absorb variation.
8. The stance that object names, state language, keyboard contracts, and selection semantics stay consistent implies you may no longer let image, gallery, and report views invent separate meanings for `selected`, `resolved`, `open`, or `done`, so layout adapters must absorb artifact-specific differences.
9. The stance that polish only clarifies hierarchy and state implies you may no longer use decorative gradients, motion, translucency, or brand color if they compete with pins, focus, or contrast, so typography, spacing, borders, and semantic tokens must absorb visual quality.
10. The stance that no-auth trusted-tailnet simplicity is intentional implies you may no longer add roles, invites, sharing controls, or approval states, so copy around private links, raw content, export, and sandboxing must absorb trust clarity.

## Resolution order for new surfaces

Settle tensions in this order because each step narrows the safe choices for the next one.

1. **Product job and scope:** Decide whether the surface serves inspect, comment, resolve, navigate, or recover. This prevents dashboard, chat, image-editor, and project-management drift before layout work begins.
2. **Primary object:** Choose artifact, selected annotation or thread, review status, navigation, or metadata. This determines what may dominate attention.
3. **Object model and vocabulary:** Fix the nouns and state meanings before arranging UI. `Artifact`, `Annotation`, `Thread`, `Reply`, `Resolution`, `Open`, `Resolved`, `Done`, and `Selected` must not change by surface.
4. **Accessibility and safety floors:** Lock keyboard access, focus, contrast, non-color state, draft preservation, undo, and destructive confirmation. These constraints are not optional polish.
5. **Artifact and performance budget:** Allocate canvas share, rail behavior, viewer toolbar shape, tile loading, and lazy-loading boundaries. This protects the hero object and interaction immediacy.
6. **Core-action discoverability:** Place visible paths for add comment, resolve, reopen, next, previous, zoom, reset, and help. This prevents minimalism from becoming mystery.
7. **State, feedback, and recovery:** Define loading, saving, failed, pending, resolved, reopened, filtered, stale, and done treatments near the object they describe.
8. **Density and progressive disclosure:** Decide what stays visible, what collapses, and what moves to drawer, menu, or command palette. This is safe only after core actions and state are known.
9. **Context optimization:** Adapt layout for single image, gallery, HTML report, desktop, tablet, and phone without changing the model.
10. **Visual polish and token mapping:** Apply color, type, spacing, border, motion, and elevation after the functional structure is proven. One-off styling is not allowed unless recorded as a decision.

## Symptom to tension lookup

| Symptom during design | Tension actually in play | Product stance | First thing to try |
| --- | --- | --- | --- |
| This screen feels busy. | 2. Density versus calm, plus 4. Discoverability versus quiet | Density belongs in the rail and gallery cards, not around the canvas. | Remove non-core chrome from the viewer surround. Keep artifact above the 60 percent desktop width rule. |
| Nobody can find the resolve action. | 4. Discoverability versus quiet, plus 3 and 7 collapsed | Core actions cannot live only in overflow or memory. | Put `Resolve thread` in the thread card action row and expose the shortcut through help or command palette. |
| This needs one more confirmation. | 11. Safety versus friction | Reversible actions use undo. Destructive or lossy actions use confirmation. | Replace the confirmation with immediate action plus undo unless the action deletes, discards unsaved text, or replaces artifact data. |
| Experts complain it is slow to use. | 3. Expert speed versus newcomer clarity | Visible core paths remain, repeated actions get keyboard speed. | Add or tune shortcuts, focus order, and command palette entries without removing visible controls. |
| The mock looks great but testing went badly. | 10. Aesthetic appeal versus usability | Polish cannot substitute for affordance, contrast, mapping, recovery, or speed. | Test labels, focus rings, contrast, state mapping, and task time before adjusting visual style. |
| The artifact no longer feels like the hero. | 2. Density versus calm, 10. Aesthetic appeal versus usability | The artifact gets visual primacy and spatial calm. | Reduce rails, metadata, shadows, saturated color, and persistent panels before reducing review state. |
| Comments feel detached from pins. | 5. Consistency versus context optimization, 13. Accessibility versus visual ambition | Selection semantics and DOM mirrors stay consistent. | Make pin selection reveal the thread, thread selection highlight or center the pin, and both share state labels. |
| The gallery looks like a dashboard. | 1. Simplicity versus capability, 14. Performance versus richness | Capability must attach to inspect, comment, resolve, navigate, or recover. | Replace charts and broad summaries with review status pills, unresolved counts, and next-action labels. |
| Filters make work disappear. | 6. Flexibility versus defaults, 8. Automation versus control | Never silently hide unresolved work. | Add visible filter chips, empty-filter copy, reset, and deep-link serialization. |
| The thread rail feels cramped. | 2. Density versus calm, 15. Generality versus purpose | Useful density belongs in review panels. | Compress metadata, collapse resolved history, and use `ThreadCard` states rather than widening the rail first. |
| The canvas interaction feels mysterious. | 12. Novelty versus familiarity, 4. Discoverability versus quiet | Novelty is reserved for direct viewer value, with visible mode and escape paths. | Add mode label, cursor change, toolbar state, shortcut help, and `Esc` behavior. |
| Pan and zoom feel janky. | 14. Performance versus richness | Pan, zoom, select, type, and resolve must remain immediate. | Defer non-visible gallery assets, report frames, history, provenance, and heavy overlays. |
| Screen reader support seems bolted on. | 13. Accessibility versus visual ambition | Every annotation needs a thread-list equivalent. | Add accessible names, state, actions, normalized coordinates, focus order, and live-region updates to the rail. |
| Open, resolved, failed, and selected states look inconsistent. | 5. Consistency versus context optimization, 15. Token governance | State language and component contracts stay consistent. | Define shared tokens and states for pins, thread cards, gallery cards, and status pills. |
| A designer wants icon-only controls. | 4. Discoverability versus quiet, 7. Recognition versus recall | Core actions need visible entry points, not memory-only paths. | Allow icon-only only when meaning is standard, target size is sufficient, accessible name exists, and help or tooltip is present. |
| A reviewer asks for many preferences. | 6. Flexibility versus opinionated defaults | Preferences need repeated real workaround evidence. | Check whether the request occurred at least three times. If not, improve default, reset, or command palette path. |

## Contradiction resolution

The axis audit lists four contradictions. The following rules now hold.

| Contradiction | Tension stance used to decide | Winner | Rule now in force |
| --- | --- | --- | --- |
| Unresolved pin color conflicts with selected-only accent use. | Tension 2 protects artifact calm. Tension 4 makes core review state discoverable. Tension 10 limits color to usable state hierarchy. Tension 13 requires non-color cues. | Selected-only accent use wins. | Blue accent is for selected, current, and primary action state. Unresolved pins use neutral or amber treatment plus number, shape, label, hit area, rail count, or filter support. Resolved pins become low-contrast outlines, dimmed state, collapsed state, or filter-controlled visibility. |
| Keyboard navigation uses `J` and `K` in one source and `[` and `]` in others. | Tension 3 supports expert speed only when core use remains clear. Tension 5 requires one consistent keyboard contract. Tension 13 requires keyboard operation to be reliable. | `[` and `]` win for previous and next thread or annotation traversal. | `[` means previous thread or annotation. `]` means next thread or annotation. `J` and `K` may exist only as optional focus-scoped list navigation, documented as enhancement, never required for the core review loop. |
| Viewer toolbar placement is unsettled across centered, left-rail, and floating vertical patterns. | Tension 2 protects canvas dominance. Tension 5 allows layout adaptation while preserving one conceptual model. Tension 14 protects viewer responsiveness. | One `ViewerToolbar` primitive wins: floating over the canvas, vertical on desktop, horizontal on phone. | Do not implement competing toolbar primitives. Desktop uses a quiet vertical floating toolbar unless artifact-overlap testing shows a better edge. Phone uses horizontal placement. Exact edge placement is a layout parameter, not a new interaction model. |
| Open comment status color uses blue in one component but semantic usage reserves blue for selected or current state. | Tension 2 reduces chrome competition. Tension 10 rejects decorative or misleading color. Tension 13 requires state beyond color. | Semantic usage wins. | `Open comments` uses neutral or amber treatment plus a clear label unless it is the selected filter or current task state. Blue remains reserved for selected, current, and primary action state. Red is never used for unresolved comments. |

## Operating rule

A design may be quiet only after it is findable, accessible, recoverable, and fast enough for the viewer. A design may be rich only after the artifact remains dominant and responsive. When in doubt, move complexity out of the canvas and into the review-specific primitive that owns it.
