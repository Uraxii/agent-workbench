# Artifact Review Server Interaction Cost and Density Rules

## Purpose

This document extends the artifact review server design rationale and reference analysis with an interaction-cost model. The goal is not to make every action take the fewest possible clicks. The goal is to make real review tasks finish quickly, with low mental effort, while keeping the artifact visually dominant.

The product context matters: this is a private tailnet tool, normally used by one reviewer moving through generated artifacts quickly. The app should prefer direct, reversible actions over ceremony. It should not import enterprise review workflows, account chrome, permission prompts, or project-management surfaces unless those needs become real.

## Interaction cost model

### What costs the reviewer

Interaction cost is the total mental and physical effort required to complete a goal. For this app, the main costs are:

| Cost | What it means in this product | Design implication |
| --- | --- | --- |
| Pointer travel | Moving between canvas, toolbar, comments panel, gallery cards, and menus | Put frequent actions near the object they affect. Keep comment creation on the canvas and thread actions inside the thread. |
| Clicks and presses | Mouse clicks, button presses, keypresses, double clicks, and confirmation actions | Remove unnecessary commits and confirmations, but keep explicit actions for destructive or ambiguous operations. |
| Mode switches | Moving between pan, zoom, comment, region draw, keyboard focus, gallery, and details views | Keep modes visible, temporary, and easy to exit. Avoid hidden modes. |
| Context switches | Leaving the image to inspect metadata, find the right thread, compare another artifact, or return to the list | Preserve spatial state with side panels, drawers, deep links, and back navigation that restores scroll and zoom. |
| Waiting | Tile load, comment save, resolve mutation, artifact list refresh, report sandbox load | Show feedback within 100 ms, use optimistic updates for safe mutations, and never block the whole screen unless the app shell itself cannot load. |
| Scrolling | Moving through long galleries, long comment lists, or dense reports | Keep active items pinned or scrolled into view. Collapse resolved history. Preserve gallery scroll on return. |
| Reading | Parsing labels, status chips, metadata, thread headers, and empty states | Use precise labels and small stable status vocabularies. Do not make users read prose to know the next action. |
| Remembering | Holding artifact position, selected thread, unresolved count, filter state, shortcut names, or comparison target in memory | Redisplay state near the task. Use breadcrumbs, selected states, visible counts, and restored deep links. |
| Deciding | Choosing between similar actions, filters, panels, statuses, or comment targets | Limit primary choices. Prefer sensible defaults, stable sort, and one obvious next action. |

### Why raw click count misleads

Raw click count is attractive because it is easy to count, but it is a weak proxy for review speed.

A one-click action can be expensive if the user must search for the target, remember the current mode, read a menu, or recover from a mistaken click. A three-step action can be cheap if each step is obvious, spatially local, and reversible. For example, `click pin`, `type reply`, `press Cmd+Enter` is three inputs, but it is low cost because the target is visible, the text field is focused, and the submit shortcut is predictable. By contrast, `click overflow`, `scan menu`, `click Resolve`, `confirm` may have fewer physical movements than a panel workflow on paper, but it has higher reading, deciding, and mode cost.

Use click count as a diagnostic, not as the target metric.

### What to measure instead

Measure review performance with task-level metrics:

1. Time to task completion: from first intent to visible completed state.
2. Decisions per task: how many meaningful choices the reviewer must make.
3. Eye travel: how often the reviewer must move attention away from the artifact or active thread.
4. Pointer travel: distance between the object of interest and the next control.
5. Working-memory items: how many facts the reviewer must hold without display support.
6. Recovery cost: how many steps it takes to undo or recover from a common mistake.
7. Wait exposure: time spent without useful feedback or without the ability to continue independent work.

For this product, a task is successful when it feels fast and unambiguous, not merely when it has a low click count.

### Literature anchors

This document uses four HCI ideas as calibration:

- Nielsen Norman Group defines interaction cost as the effort users spend to achieve goals. That effort includes mental work, not just physical input.
- GOMS and the Keystroke-Level Model estimate expert task time from low-level operators. Use it as a calibration tool: a point action is not free, a hand move is not free, and mental preparation can dominate a nominally simple task.
- Hick-Hyman law predicts that choice reaction time grows as the number and uncertainty of choices grow. In product terms, ten equally visible actions are not neutral. They increase decision time.
- Fitts's law predicts that pointing time depends on target size and distance. In product terms, large nearby targets for frequent actions are faster than small distant toolbar icons.

Use these models pragmatically. They are not exact predictions for every reviewer, device, or image, but they prevent the design from treating all clicks as equal.

### KLM timing calibration

When estimating expert desktop flows, use these common Keystroke-Level Model operators as rough calibration, not as product guarantees:

| Operator | Meaning | Common timing |
| --- | --- | --- |
| `K` | Keystroke or mouse button press | About 0.20 s for a skilled typist, slower for average users |
| `P` | Point with a mouse | About 1.10 s average |
| `H` | Home hands between keyboard and pointing device | About 0.40 s |
| `M` | Mental preparation | About 1.35 s |
| `R` | System response | Measured per system |
| `D` | Drawing | Specialized, depends on geometry |

The important lesson is that removing a click is often less valuable than removing a mental preparation, a hand move, a long pointer trip, or a wait.

## Task budgets

### Step definition

For this document, a step is one intentional user action:

- Click: one mouse or touch activation.
- Keypress: one shortcut or submit key combination. Text entry counts as `type comment`, not one step per character.
- Drag: one continuous pan, zoom, or region draw gesture.
- Hover: one intentional reveal action, counted when the hover is required to discover or use a control.
- Wait: counted when the user cannot continue the task until the system responds.

Reading visible state is not counted as a step, but it is still cost. If a flow depends on reading dense labels or remembering hidden state, the budget is considered failed even if the step count passes.

### Budget table

| Reviewer task | Target budget | Intended interaction sequence | Notes |
| --- | ---: | --- | --- |
| Open the latest artifact | 1 step from app home, 0 steps from latest deep link | Click `Latest artifact`, or open saved latest URL. | Home should default focus to latest item. The latest artifact route should restore the last viewer state only if the URL includes it. |
| Scan a gallery and pick one | 1 to 2 steps after visual scan | Click artifact card. Optional: click `Needs review` filter first if not already default. | Default sort puts items needing attention first. Card click opens detail view, not a modal. |
| Zoom to a detail | 1 to 2 steps | Double click target detail, or scroll wheel over target, or press `+` then drag pan if needed. | OpenSeadragon should zoom toward pointer. Toolbar zoom is fallback, not primary. |
| Drop a pin and comment | 3 steps | Press `C`, click image point or drag region, type comment and press `Cmd+Enter`. | If the toolbar button is used instead of `C`, budget becomes 4. Composer opens focused in the comments panel. |
| Reply to a thread | 2 steps | Click thread or pin, type reply and press `Cmd+Enter`. | If thread is already selected, budget is 1 text action. Reply box appears inline, not in a modal. |
| Resolve a thread | 1 step when active, 2 steps when not active | Press `R`, or click thread then click `Resolve thread`. | No confirm. Use undo toast. Destructive deletion would require confirmation, but resolve is reversible. |
| Mark the whole artifact reviewed | 1 to 2 steps | Click `Mark artifact done`, or press command palette shortcut then Enter on `Mark artifact done`. | Keep disabled with clear reason if required fields are missing. Do not require all comments resolved unless workflow contract says so. |
| Get back to the list | 1 step | Press `G` or click breadcrumb/gallery back control. | Gallery scroll, filter, and selected card restore. Browser Back should do the same. |
| Compare two artifacts | 2 to 4 steps | Select first artifact, click `Compare`, click second artifact, then drag splitter or press `Swap` if needed. | If comparing adjacent artifacts, `Compare previous` and `Compare next` should make this 1 step from detail view. |

### Task details

#### Open the latest artifact

Target: 1 step from app home.

Sequence:

1. Click `Latest artifact`.

Rules:

- If the reviewer opens the root URL, show the latest reviewable artifact as the primary card or primary button.
- If the reviewer opens a deep link, do not redirect to the latest artifact.
- If no artifacts exist, show a compact empty state with the expected publish path or command.

Failure mode to avoid: a dashboard that requires sorting by date, opening a collection, then selecting the top item.

#### Scan a gallery and pick one

Target: 1 to 2 steps after scan.

Sequence:

1. Optional click: `Needs review` filter, only if the current filter is different.
2. Click the target artifact card.

Rules:

- The default gallery view sorts `Needs review`, then `Open comments`, then recent activity.
- Each card exposes title, thumbnail, status, unresolved count, and last activity.
- The entire card opens the artifact.
- Secondary actions use hover or overflow, but opening never depends on hover.

Failure mode to avoid: making the user open a preview modal, then click again to enter the real review page.

#### Zoom to a detail

Target: 1 to 2 steps.

Sequence options:

1. Double click the detail to zoom toward the pointer.
2. Scroll wheel or trackpad zoom over the detail.
3. Press `+`, then drag pan if the detail is not centered.

Rules:

- Double click zooms into pointer, not image center.
- Press `F` to fit and `0` to reset.
- Toolbar zoom buttons exist for discoverability and accessibility, but are not the fastest path.
- The viewer should not lose selected annotation or panel state during zoom.

Failure mode to avoid: a zoom slider far from the canvas that forces eye travel and pointer travel for every inspection.

#### Drop a pin and comment

Target: 3 steps with keyboard, 4 steps with toolbar.

Keyboard sequence:

1. Press `C` to enter comment mode.
2. Click image point or drag a region.
3. Type comment and press `Cmd+Enter`.

Toolbar sequence:

1. Click `Add comment` or `Add region comment` in the viewer toolbar.
2. Click image point or drag a region.
3. Type comment.
4. Click `Submit`.

Rules:

- Mode indicator must be visible while comment mode is active.
- `Esc` cancels draft geometry before leaving the page or closing the panel.
- Draft text and geometry persist through accidental panel close.
- The pending pin appears immediately.
- Save errors preserve text and geometry.

Failure mode to avoid: click image, open dialog, choose comment type, fill form, click save, wait, then see whether pin appeared.

#### Reply to a thread

Target: 2 steps from visible thread or pin.

Sequence:

1. Click thread card or annotation pin.
2. Type reply and press `Cmd+Enter`.

Rules:

- Selecting a thread reveals an inline reply composer focused at the bottom of that thread.
- If the thread is already active, the first step is skipped.
- A failed reply stays in place with retry and copy text controls.
- Reply should not move the thread unpredictably in sort order.

Failure mode to avoid: a separate reply dialog that hides the image context.

#### Resolve a thread

Target: 1 step if active, 2 steps if not active.

Sequence:

1. Press `R` when a thread is active.

Alternative sequence:

1. Click the thread or pin.
2. Click `Resolve thread`.

Rules:

- Resolving is reversible and uses undo toast, so it does not need confirmation.
- `Resolve thread` stays inside the thread card, not in a distant global toolbar.
- Resolved pins dim or hide depending on filter.
- Resolved cards collapse after resolution, but keep a one-line history row.

Failure mode to avoid: asking for confirmation on every resolve. That trains reviewers to click through dialogs and slows batch review.

#### Mark the whole artifact reviewed

Target: 1 to 2 steps.

Sequence:

1. Click `Mark artifact done`.

Alternative command sequence:

1. Press `Cmd+K`.
2. Type enough to select `Mark artifact done`, then press Enter.

Rules:

- `Mark artifact done` is an artifact-level action, distinct from `Resolve thread`.
- If backend export is part of done, show `Mark artifact done and publish feedback JSON` as the precise action.
- If done is blocked, disable the action and show one sentence explaining why.
- Completion state should update immediately, with rollback on server failure.

Failure mode to avoid: requiring all open comments to be resolved when unresolved comments are the intended review deliverable.

#### Get back to the list

Target: 1 step.

Sequence:

1. Press `G`, click breadcrumb, or use browser Back.

Rules:

- Return restores gallery scroll, filters, and selected card.
- The selected card should be visible and highlighted after return.
- If the user entered through a direct artifact link with no gallery context, `G` goes to the relevant collection or latest list.

Failure mode to avoid: returning to the top of a large gallery after every artifact.

#### Compare two artifacts

Target: 2 to 4 steps for arbitrary compare, 1 step for adjacent compare.

Arbitrary sequence:

1. Click `Compare` on the current artifact.
2. Click the second artifact in the picker.
3. Optional drag splitter.
4. Optional click `Sync pan and zoom` if not already default for same dimensions.

Adjacent sequence:

1. Click `Compare previous` or `Compare next`.

Rules:

- Compare view is a page state with a URL, not a modal.
- Same-size images default to synchronized pan and zoom.
- Different-size images show sync off by default with a visible toggle.
- Comment state remains attached to each artifact and does not merge.

Failure mode to avoid: opening two browser tabs and forcing the reviewer to align zoom manually.

## Techniques for removing steps

### Sensible defaults

Use when the user's likely next action is clear.

Good uses:

- Gallery defaults to items needing attention first.
- Thread filter defaults to `Open`.
- Image opens fit to screen with 5 percent margin.
- Comment composer focuses after pin placement.
- Same-size compare defaults to synchronized pan and zoom.

Cost:

- Defaults can hide other states if the current filter is not obvious.
- Defaults can surprise users if they change based on hidden history.

Failure mode:

- A default becomes a hidden decision. For example, defaulting to hide resolved pins is fine only if the filter state is visible and easy to change.

Wrong when:

- The action is destructive.
- The reviewer must make a real judgment.
- The system is guessing from weak signals.
- The default changes silently between sessions without visible state.

### Direct manipulation instead of dialogs

Use when the action targets a visible object.

Good uses:

- Click or drag on image to place an annotation.
- Drag region handles to adjust a region.
- Drag compare splitter.
- Click pin to select thread.

Cost:

- Direct manipulation can create accidental edits.
- Canvas gestures compete with pan and zoom gestures.

Failure mode:

- Hidden canvas mode: the same click sometimes pans, sometimes selects, sometimes creates a comment.

Wrong when:

- The consequence is destructive or hard to undo.
- The target is not visually stable.
- Precision is too high for the device, especially touch region drawing.

### Inline editing

Use when editing belongs to the visible object.

Good uses:

- Reply inside the selected thread.
- Edit a draft comment in place.
- Rename local artifact title only if titles are editable.

Cost:

- Inline fields can make cards taller and increase panel density.
- Multiple open editors create mode confusion.

Failure mode:

- Several editable fields stay open, and the reviewer cannot tell which changes are saved.

Wrong when:

- The edit spans multiple objects.
- The action needs a large preview or validation summary.
- The screen is too narrow to edit safely inline.

### Optimistic updates

Use when failure is rare, the action is reversible, and the local state is easy to roll back.

Good uses:

- Resolve or reopen thread.
- Submit reply on trusted tailnet.
- Mark artifact done.
- Toggle thread filter or annotation visibility.

Cost:

- Requires clear pending and rollback states.
- Can conflict with another session, even if that is rare.

Failure mode:

- The UI says resolved, the server rejects the mutation, and the reviewer moves on without noticing.

Wrong when:

- The action is destructive.
- The server performs validation the client cannot predict.
- A failed action would cause lost text or lost geometry.

### Keyboard shortcuts and command palette

Use shortcuts for repeated expert actions and command palette for secondary actions that should not occupy permanent chrome.

Good uses:

- `C` for comment mode.
- `R` for resolve active thread.
- `[` and `]` for previous and next thread.
- `G` for gallery.
- `Cmd+K` for command palette.
- `?` for shortcut help.

Cost:

- Shortcuts require learning.
- They can conflict with browser or assistive technology behavior.

Failure mode:

- Core actions exist only as shortcuts, so occasional reviewers miss them.

Wrong when:

- The shortcut hijacks browser defaults such as `Cmd+L`, `Cmd+R`, or `Ctrl+F`.
- The action has no visible equivalent.
- Focus is inside a text field and the shortcut would eat text input.

### Hover-reveal

Use hover to reduce permanent visual noise for secondary actions.

Good uses:

- Gallery card overflow actions.
- Thread row copy link.
- Toolbar labels as tooltips.
- Pin region outline on hover.

Cost:

- Hover costs discovery.
- Hover does not work on touch.
- Hover can cause flicker if target boundaries are small.

Failure mode:

- A critical action is invisible until hover, and the reviewer never finds it.

Wrong when:

- The action is primary.
- The app must support touch for that task.
- The control affects safety, destructive behavior, or review completion.

### Auto-save instead of explicit save

Use for drafts and low-risk local preferences.

Good uses:

- Preserve unsent composer text per artifact.
- Preserve panel width, density, theme, and last filter.
- Preserve compare splitter position.

Cost:

- Users need to know whether a draft is private, submitted, or synced.
- Auto-save can make it unclear when the official feedback was sent.

Failure mode:

- The reviewer thinks a draft comment was submitted because text persisted.

Wrong when:

- The action publishes feedback to another system.
- The user expects a deliberate commit.
- The saved state affects other reviewers or automation.

Rule: drafts auto-save, submitted feedback uses explicit submit or `Cmd+Enter`.

### Deep links that restore state

Use when preserving context reduces memory and navigation cost.

Good uses:

- Link to artifact with selected thread.
- Link to artifact with viewport and zoom.
- Link to compare view.
- Link to report section if stable IDs exist.

Cost:

- URLs can become long.
- Restored view can be disorienting if the artifact changed.

Failure mode:

- A deep link silently opens stale coordinates on a new artifact version.

Wrong when:

- The state is private draft text.
- The state is unstable or tied to transient layout dimensions.
- Restoring state hides important new comments or errors.

### Batch actions

Use when the reviewer is applying the same low-risk action to many items.

Good uses:

- Mark selected artifacts viewed.
- Hide resolved threads in current artifact.
- Copy feedback JSON for a batch.
- Open next unresolved artifact.

Cost:

- Batch selection adds mode and status complexity.
- Mistakes have larger blast radius.

Failure mode:

- Selection state remains active and later actions apply to more items than expected.

Wrong when:

- The action is destructive.
- Each item requires judgment.
- The selection count is not visible near the action.

### Predictive or last-used state

Use only when it reduces repeated setup without hiding the current state.

Good uses:

- Remember last thread filter.
- Remember comments panel width.
- Remember density preference.
- Reuse last compare sync preference for same dimension class.

Cost:

- Prediction can make the UI feel inconsistent across sessions.
- Last-used state can conflict with task defaults.

Failure mode:

- The app opens filtered to `Resolved`, and the reviewer thinks no open comments exist.

Wrong when:

- The state changes what work appears incomplete.
- The current state is not visibly labeled.
- The prediction is based on too little history.

## Managing information density

### Progressive disclosure done properly

Progressive disclosure is not hiding. It is sequencing.

Good progressive disclosure keeps the next likely action visible, defers less likely actions to a nearby surface, and preserves enough state that the user does not have to remember what was deferred. In this app, the first screen should show artifact identity, artifact status, canvas, comments state, and the primary next action. It should defer raw metadata, export details, advanced filters, diagnostics, and settings.

Hiding removes information without a visible path back. Deferring keeps a visible scent: count, chip, label, disclosure button, drawer title, or command palette entry.

Examples:

- Good: show `3 open` in the top bar, with the comments panel one click away.
- Bad: hide all comments until the reviewer opens an unlabeled icon.
- Good: show `Scripts disabled` chip with details in a popover.
- Bad: bury report sandbox behavior in settings.

### Spatial density versus temporal density

Spatial density is how much is visible at once. Temporal density is how many steps, waits, and transitions happen over time.

Reducing spatial density can increase temporal density. For example, hiding every thread action in menus creates a cleaner panel, but each resolve now requires menu open, scan, click, and possibly close. Reducing temporal density can increase spatial density. For example, showing every action on every card makes actions faster but turns the panel into noise.

The design should trade between them by task frequency:

- Frequent and local: visible near the object.
- Frequent and global: visible in stable chrome or shortcut help.
- Infrequent but important: command palette plus menu.
- Dangerous: visible only when relevant, with explicit confirmation.
- Diagnostic: drawer or details surface, never permanent canvas chrome.

### Persistent panel versus popover

Use a persistent panel when the user must read, compare, or act repeatedly while keeping context.

Persistent panel fits:

- Thread list.
- Selected thread replies.
- Composer.
- Artifact list on wide screens.
- Compare controls when comparing.

Use a popover when the interaction is short, local, and dismissible.

Popover fits:

- Sort choice.
- Filter choice.
- Copy link menu.
- Small metadata summary.
- Keyboard shortcut hint from a toolbar button.

A popover is wrong for a thread conversation, because reading and replying require stable space. A persistent panel is wrong for one-off copy actions, because it steals canvas width.

### Keeping the artifact dominant

The artifact is the hero. The interface must prove that in pixels and contrast.

Rules:

- Desktop review mode keeps at least 60 percent of horizontal space for the canvas at 1280 px and wider.
- If side surfaces would push the canvas below 60 percent, collapse the left rail first, then overlay the right panel.
- The canvas background is the darkest layer. Panels are raised but quiet.
- Accent color appears on selected task state, not as decoration.
- Annotation pins stay compact. Region outlines appear on hover, active selection, or edit, not all the time.
- Resolved annotations are hidden or muted by default, with a visible filter state.

### Thread state without visual overload

The reviewer needs thread state visible without turning the canvas into confetti.

Rules:

- Show unresolved pins by default.
- Hide or mute resolved pins by default.
- Cluster pins at low zoom when pins overlap.
- Show full region geometry only for active, hovered, or editing states.
- Mirror every annotation in the comments panel for accessibility and scanning.
- Selecting a pin selects the thread. Selecting a thread centers or highlights the pin.
- Use thread numbers instead of avatars on pins to reduce visual variety.

### Concrete density limits

Use these limits as design constraints:

| Surface | Limit |
| --- | --- |
| Global primary actions in top bar | 1 primary, plus at most 2 secondary visible actions |
| Viewer toolbar actions | 7 visible controls maximum before grouping |
| Thread card visible actions | 2 visible actions maximum, usually `Reply` and `Resolve thread` or `Reopen thread` |
| Gallery card visible metadata | Title, type, status, unresolved count, last activity maximum |
| Gallery card visible actions | Whole-card open plus 1 hover action or overflow menu |
| Simultaneous open panels | 1 persistent side panel plus 1 transient popover maximum |
| Visible toast count | 3 maximum |
| Top bar status chips | 3 maximum |
| Filter chips in one row | 5 maximum, then move extra filters into `More filters` |
| Thread groups before subgrouping | 3 groups maximum: `Open`, `Resolved`, `Failed` |
| Thread cards before virtualized list | 50 cards |
| Resolved replies shown by default | 1 latest reply plus count, expand on demand |
| Metadata rows visible by default | 5 rows, then `Show details` |
| Command palette primary results | 7 visible results before scroll |

Collapse rules:

- Collapse resolved threads by default once there is at least 1 open thread.
- Collapse artifact metadata after 5 rows.
- Collapse long comment bodies after 12 lines, but never while editing.
- Collapse the left gallery rail before collapsing comments on desktop.
- Collapse comments into an overlay drawer when canvas width would fall below 60 percent.
- Do not collapse the active thread, active composer, failed save state, or selected annotation state.

## Resolution: rule set for fewer steps and lower density

This product reconciles fewer steps with lower density through task-weighted visibility. Screen space is earned by frequency, locality, consequence, and need for continuous context.

### Permanent screen space

A feature earns permanent screen space only if all of these are true:

1. It is used in most review sessions.
2. It affects the current artifact or active thread.
3. The reviewer benefits from seeing its state continuously.
4. Hiding it would add memory cost or repeated navigation cost.
5. It does not reduce the canvas below the space rule.

Permanent examples:

- Artifact title and status.
- Open thread count.
- Comments panel on desktop.
- Add comment control.
- Zoom, fit, and reset controls.
- Active thread state.

### Revealed surface

A feature belongs in a revealed surface if any of these are true:

1. It is useful but not needed continuously.
2. It supports the current task but is not the primary next action.
3. It would add visual noise if always visible.
4. It needs a small amount of reading or choice.

Revealed examples:

- Filters.
- Sort options.
- Copy link.
- Raw artifact link.
- Metadata details.
- Annotation visibility choices.
- Keyboard shortcut help.

Preferred surfaces:

- Inline expansion for content attached to one object.
- Popover for short local choices.
- Drawer for secondary inspection that needs reading.
- Command palette for broad secondary actions.

### Keyboard-only or command-first path

A feature may be command-first when all of these are true:

1. It is for power users or batch workflows.
2. It is not required to complete a first-time review.
3. It has a visible discoverability path through help, menu, or palette.
4. It does not affect safety without confirmation.

Command-first examples:

- Copy feedback JSON.
- Jump to artifact by fuzzy search.
- Toggle compact density.
- Open raw artifact.
- Show tile diagnostics.

Keyboard-only should be rare. Core review tasks need visible paths.

### Modal or confirmation path

A feature needs a modal or confirmation only when at least one is true:

1. It is destructive.
2. It affects multiple artifacts.
3. It publishes externally in a way that cannot be trivially undone.
4. It changes security posture, such as opening active report content.
5. It has consequences not visible from the current screen.

Resolve does not qualify because it is reversible. Delete would qualify if deletion exists.

### New feature decision test

For any proposed feature, answer these questions in order:

1. What reviewer task does it shorten or clarify?
2. Which cost does it reduce: pointer, click, mode, context, wait, scroll, reading, memory, or decision?
3. Which cost does it add?
4. How often does the task occur in normal review?
5. Does the state need to remain visible while reviewing the artifact?
6. Can undo or recovery make the action safe without confirmation?
7. Would the feature reduce canvas space below the 60 percent rule?
8. Can the same value be delivered by a revealed surface or command palette?

Placement outcome:

- If it is frequent, local, stateful, and safe: permanent screen space.
- If it is frequent but not stateful: visible control near the task object.
- If it is useful but intermittent: revealed surface.
- If it is expert, batch, or rare: command palette and documented shortcut.
- If it is dangerous: explicit surface with confirmation.
- If it cannot identify a reviewer task: do not build it.

### Product-level rule

The app should spend pixels to save memory, not to advertise features. It should spend clicks to prevent harm, not to satisfy process. It should hide decoration, defer diagnostics, reveal secondary choices, and keep the review loop direct: inspect, annotate, discuss, resolve, continue.

## Sources

- Raluca Budiu, "Interaction Cost", Nielsen Norman Group, 2013, last reviewed 2024. https://www.nngroup.com/articles/interaction-cost-definition/
- Kathryn Whitenton, "Minimize Cognitive Load to Maximize Usability", Nielsen Norman Group, 2013. https://www.nngroup.com/articles/minimize-cognitive-load/
- Stuart K. Card, Thomas P. Moran, and Allen Newell, "The Keystroke-Level Model for User Performance Time with Interactive Systems", Communications of the ACM, 23(7), 1980. DOI: https://doi.org/10.1145/358886.358895. Free report copy verified through Carnegie Mellon University Library: https://iiif.library.cmu.edu/file/Newell_box00072_fld05090_doc0005/Newell_box00072_fld05090_doc0005.pdf
- W. E. Hick, "On the Rate of Gain of Information", Quarterly Journal of Experimental Psychology, 4(1), 1952. DOI: https://doi.org/10.1080/17470215208416600. Public copy found at University of Iowa: https://www2.psychology.uiowa.edu/faculty/mordkoff/InfoProc/pdfs/Hick%201952.pdf
- Ray Hyman, "Stimulus Information as a Determinant of Reaction Time", Journal of Experimental Psychology, 45(3), 1953. DOI: https://doi.org/10.1037/h0056940. PubMed record: https://pubmed.ncbi.nlm.nih.gov/13052851/
- Paul M. Fitts, "The Information Capacity of the Human Motor System in Controlling the Amplitude of Movement", Journal of Experimental Psychology, 47(6), 1954. DOI: https://doi.org/10.1037/h0055392. PubMed record: https://pubmed.ncbi.nlm.nih.gov/13174710/
- Ben Shneiderman, Catherine Plaisant, Maxine Cohen, Steven Jacobs, and Niklas Elmqvist, "Designing the User Interface: Strategies for Effective Human-Computer Interaction", sixth edition, Pearson, 2016. Golden rules reference page: https://www.cs.umd.edu/~ben/goldenrules.html
- W3C Web Accessibility Initiative, "Understanding Success Criterion 2.5.8: Target Size (Minimum)", WCAG 2.2, updated 2026. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
