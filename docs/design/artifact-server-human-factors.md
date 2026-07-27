# Artifact Review Server Human Factors Research

## Purpose

This document explains the human physiology and psychology behind interface decisions for the artifact review server rewrite. The design research document defines what the interface should be. This document explains why those choices reduce perceptual strain, motor effort, cognitive load, and error risk for reviewers who inspect generated images, galleries, and HTML reports.

The core premise is simple: the artifact is the visual task, and the interface is the support system. Controls, comments, status, and feedback should stay close enough to be usable, quiet enough not to compete with the image, and explicit enough that state changes are not missed.

## 1. Vision and perception

### Foveal and peripheral acuity

Human vision is not uniform across the visual field. The fovea, the small central part of the retina, provides high acuity for reading text, inspecting edges, and judging fine details. Peripheral vision is much less precise, but it is highly useful for detecting motion, contrast changes, spatial layout, and attention cues.

For this app, that means the reviewer can inspect only a small part of a render sharply at any moment. If the user is judging a face, a button edge, a glyph, a texture seam, or a rendering artifact in the image, controls placed far away from that point require a gaze shift before they can be read or operated. A right comment panel is reasonable because it gives a stable place for threaded text, but the active pin, selected thread, and nearest canvas controls must be visually linked so the user does not have to reconstruct the relationship from memory.

Peripheral vision can notice a selected thread row, a count badge, or a changed toolbar state, but it cannot reliably read subtle text or distinguish small status color differences. Status placed in the periphery should use shape, position, text labels, and stable location, not only a colored dot.

### Saccades and scan paths

Eyes move through saccades, rapid jumps between fixation points. During a saccade, visual intake is suppressed. The user does not experience the interface as a continuous camera pan, but as a sequence of fixations: artifact detail, pin, side panel thread, toolbar, back to artifact.

A review tool should make the likely scan path short and predictable:

1. Inspect the artifact.
2. Notice or place a pin.
3. Read the matching thread.
4. Act on the thread.
5. Return to the same artifact region.

If pin selection and thread selection are synchronized, the eye can follow a clear visual chain. If the selected thread is not visibly tied to the selected annotation, the user must search twice: once in the image and once in the panel. That increases fatigue and makes comments easier to misapply to the wrong visual region.

### Contrast sensitivity in dark themes

Contrast sensitivity is not the same as mathematical contrast ratio. Human ability to detect detail depends on luminance, spatial frequency, adaptation state, glare, and local contrast. Dark themes reduce emitted light and can be comfortable in dim environments, but they also make some visual problems worse.

Pure white text on pure black can produce halation, especially for users with astigmatism or optical scatter. The bright strokes appear to glow into the surrounding black, making text edges less crisp. A near-black background with slightly softened off-white text usually feels sharper than maximum contrast white on black, even when both technically exceed WCAG contrast requirements.

Dark UI also needs stronger separation between surfaces because shadows are less perceptible. Borders, subtle elevation steps, and controlled luminance differences are more reliable than large black shadows. The canvas can be very dark so the image remains dominant, while panels should be slightly lighter to preserve depth and reduce the sensation of floating text in a void.

### Color vision deficiency

Congenital color vision deficiency affects a material share of the population, commonly cited as up to about 8 percent of males and 0.5 percent of females. Red-green deficiencies are the most common. A review app that uses color alone for open, resolved, failed, selected, or warning states will fail for some users and will also fail in peripheral vision, under glare, or on low quality displays.

Color should be redundant. A resolved thread can use green, but it also needs the word `Resolved`, a changed icon or pill shape, and a collapsed visual treatment. An error can use rose, but it also needs error copy, retry action, and an accessible name. Annotation states should differ by stroke, fill, label, and selection ring, not hue alone.

### Luminance adaptation and long review sessions

The visual system adapts to the average luminance of the environment and screen. In a long dark-room review session, abrupt bright panels, white modals, or full-screen loading flashes can cause discomfort because the eye has adapted to lower luminance. Repeated adaptation shifts are tiring, especially when the user is inspecting subtle generated-image defects.

Dark-mode-first is justified for this workflow, but it must be stable. The app should avoid sudden white surfaces, large high-contrast flashes, and full-screen spinners. Loading and error feedback should appear inside the existing dark shell. HTML reports that are bright by nature should be framed with neutral margins and should not force the surrounding app chrome to switch luminance.

### Implications for this app

- Keep the artifact in the foveal path: selected pin, selected thread, and composer must visibly synchronize.
- Place primary viewer controls near the canvas, not only in distant menus.
- Keep side-panel status readable without depending on peripheral color discrimination.
- Use off-white text on near-black surfaces, not pure white on pure black as the default.
- Target WCAG 2.2 contrast of at least 4.5:1 for normal text, 3:1 for large text, icons, controls, and focus indicators, with 7:1 preferred for dark-mode body text.
- Avoid large white flashes during loading, errors, report opening, or theme changes.
- Never communicate status by color alone. Pair color with text, shape, icon, or position.
- Use subtle borders and luminance steps for dark surfaces because shadows are weak in dark UI.

## 2. Motor control

### Fitts's law

Fitts's law models the time needed to move to a target. A common Shannon formulation is:

```text
MT = a + b log2(D / W + 1)
```

Where:

- `MT` is movement time.
- `a` is the start and stop time constant for the device and user.
- `b` is the slope, or cost per bit of movement difficulty.
- `D` is the distance from the pointer's starting position to the target.
- `W` is the target width along the axis of movement.
- `log2(D / W + 1)` is the index of difficulty. Farther targets increase difficulty. Wider targets reduce difficulty.

The implication is direct: small, distant controls are slow and error-prone. Large, nearby controls are fast and reliable. A reviewer who repeatedly moves between canvas, toolbar, and comment panel pays this cost many times per session.

### Target size and distance

Toolbar buttons used repeatedly should be larger than rare metadata controls. A 32 by 32 px mouse target can be acceptable for dense desktop chrome, but a 36 by 36 px toolbar button is easier to acquire repeatedly. Touch targets should be at least 44 by 44 px. WCAG 2.2 also defines a 24 by 24 CSS px minimum target size for many pointer targets, with exceptions, but that minimum should not be treated as the comfort target for primary actions.

Distance matters as much as size. A `Resolve thread` control inside the selected thread is easier than a global resolve button in the top bar because the pointer is already near the text being read. Zoom controls near the canvas are easier than zoom controls in a far header. The most frequent actions should be near where the pointer naturally is after the previous action.

### Edges and corners

Screen edges and corners behave like very large targets because the pointer cannot overshoot past the display boundary. In Fitts's law terms, they have effectively infinite depth in one or two directions. This makes edge-attached targets useful for high-frequency global controls, such as a collapsible side panel rail, bottom toolbar on touch, or top bar navigation.

Floating controls lose this edge benefit. They can be visually elegant, but their targets must compensate with size, spacing, and predictable placement. If a floating toolbar auto-hides, it should reappear in the same place and with a forgiving hover or focus zone.

### Why a 24 px pin differs from a 44 px touch target

A visible annotation pin around 24 to 28 px can be appropriate because it must not cover the artifact. It is a visual marker first and a direct manipulation handle second. A touch target, however, must account for finger size, occlusion, hand tremor, and imprecise contact. The visible pin can remain 24 px while the invisible hit area is larger, for example 40 to 44 px. This preserves visual density without making the interaction physically difficult.

For mouse use, the pin can be visually compact but should still have a forgiving hit area, especially at low zoom or in dense pin clusters. For touch, the app should avoid requiring precise region editing unless the handles are large and the view is zoomed in.

### Drag versus click cost

Dragging is more expensive than clicking. It requires continuous motor control, visual monitoring, and error correction. Dragging also conflicts with OpenSeadragon pan gestures. Region annotation should be available, but point comments should be the fastest path because they require one click or tap, then text entry.

When drag is necessary, the app should provide visible handles, a cancel path, and an editable draft state. Users should not lose a comment draft because a drag started on the wrong mode or because a pan gesture was interpreted as an annotation gesture.

### Pointer travel across a wide screen

On a wide monitor, the distance from a left toolbar to a right comment panel can be hundreds or thousands of pixels. Repeated travel across that distance is slow, interrupts visual review, and increases the chance of landing on the wrong target.

This app should avoid workflows that require left edge, right edge, and top edge actions in quick sequence. Common action chains should stay local: select annotation on canvas, type in side panel, resolve in the thread, then advance to next unresolved thread with a nearby control or shortcut.

### Implications for this app

- Use 36 by 36 px desktop toolbar buttons for frequent viewer controls.
- Use 44 by 44 px minimum targets for touch controls and primary mobile actions.
- Treat WCAG 2.2 24 by 24 CSS px as a floor for non-primary pointer targets, not as the main ergonomic target.
- Keep visible pins around 24 to 28 px, but give them invisible hit areas of about 40 to 44 px.
- Put thread actions inside the ThreadCard, not only in global chrome.
- Use edges for stable rails, drawers, and mobile bottom controls where possible.
- Prefer click or tap for point comments. Use drag only for deliberate region creation and editing.
- Avoid forcing repeated pointer travel across the full width of a large monitor.

## 3. Cognition and memory

### Hick-Hyman law

Hick-Hyman law describes how choice reaction time increases as the amount of information in the stimulus set increases. A common simplified form is:

```text
RT = a + b log2(n + 1)
```

Where:

- `RT` is reaction time.
- `a` is baseline reaction time.
- `b` is the increase per bit of choice information.
- `n` is the number of equally probable choices.

Real interfaces are more complex than equal-probability lab choices, but the design lesson holds: more visible choices slow action selection, especially when labels are similar or grouping is unclear.

For this app, the toolbar should not expose every possible artifact action. Core review actions should be visible: pan or select, add comment, zoom, reset, comments, next unresolved. Secondary actions such as raw artifact URL, copy feedback JSON, tile diagnostics, and annotation filters belong in menus or a command palette. This is progressive disclosure, not minimalism for its own sake.

### Chunking and working memory

Miller's 1956 paper is historically important for the phrase seven plus or minus two, but modern working-memory research is more conservative. Cowan's work argues that the focus of attention is often closer to about four chunks, with practical UI guidance commonly treating 3 to 5 items as a safer limit.

A reviewer should not have to remember many independent states: which artifact, which pin, which thread, which filter, whether the comment saved, whether the artifact is done, and where the next unresolved item is. The interface should externalize these states. Group related controls into small chunks, such as viewer tools, annotation tools, thread filters, and artifact actions. Avoid one long toolbar with 10 similar icons.

### Intrinsic versus extraneous cognitive load

Intrinsic load is the unavoidable complexity of the user's real task: judging visual artifacts, comparing render quality, and writing useful feedback. Extraneous load is caused by the interface: ambiguous labels, hidden state, unexpected sorting, mode confusion, lost drafts, and unrelated metadata.

The design should protect the user's limited cognitive capacity for the artifact itself. Stable layout, direct labels, persistent status, and reversible actions reduce extraneous load. The app should not make the reviewer remember whether resolved comments are hidden, whether a draft is saved, or what a color dot means.

### Recognition over recall

Recognition is easier than recall. A visible `Add comment` button, selected annotation ring, `Resolved` label, and shortcut hint require less memory than expecting users to remember that `C` starts comment mode or that a muted pin means resolved.

Keyboard shortcuts are still valuable for repeated review, but every shortcut should have a visible counterpart or be discoverable through `?` or a command palette. Occasional reviewers should succeed by recognition. Expert reviewers should become faster through recall.

### Change blindness

Change blindness is the failure to notice visual changes, especially when attention is elsewhere or when the change coincides with a disruption. In this app, silent state changes are easy to miss: a pin changes from pending to saved, a thread moves to resolved, a filter hides a comment, or an optimistic update rolls back after a save failure.

State changes should be anchored near the object that changed and reinforced through motion, text, or both. A resolved thread should dim and move predictably, but not vanish immediately. A toast should offer undo. A failed save should mark the composer and preserve text. Filters that hide content should show a count so users know content exists outside the current view.

### Response thresholds and the Doherty threshold

Human perception has useful timing thresholds for interface feedback:

- Around 100 ms feels instantaneous.
- Around 1 second keeps the user's flow of thought mostly intact.
- Around 10 seconds risks losing attention unless progress and next steps are clear.

The Doherty threshold is commonly cited around 400 ms: systems that respond under this threshold can support more fluid human-computer interaction and better productivity. The exact value is not a universal law, but it is a useful design target for repeated review actions.

This app should provide visible feedback within 100 ms for local interactions, even if the network operation takes longer. Optimistic pins, disabled submit buttons, pending thread states, and preserved drafts are not polish. They keep the user's cognitive loop intact.

### Implications for this app

- Keep primary toolbars to about 3 to 5 visible groups, not one long strip of unrelated actions.
- Show only core review actions by default. Move secondary actions to menus or a command palette.
- Give every shortcut a visible control or help entry.
- Preserve and show state rather than making users remember it.
- Show local feedback within 100 ms for clicks, submits, resolves, and mode changes.
- Keep routine operations under 1 second when possible. If slower, show inline pending state.
- For work over 10 seconds, show progress, staged status, or a clear recovery path.
- Do not silently hide, move, or resolve comments without a visible count, label, or undo path.

## 4. Attention and error

### Inattentional blindness

Inattentional blindness occurs when users fail to notice unexpected events while focused on another task. Reviewers inspecting subtle artifacts may miss a new warning badge, a changed status chip, or a toast far from the focal region. This is especially likely when the artifact is visually dense.

Critical feedback should appear at the locus of attention. If a comment save fails, the composer should show the failure, not only a toast. If a selected thread has an off-screen pin, the thread should include a `Center annotation` action. If an annotation is hidden by a filter, the canvas should not look as if the comment disappeared without explanation.

### Banner blindness

Users learn to ignore regions that look like promotional banners, decorative cards, or repetitive status strips. A review UI with loud top banners or colorful persistent notices risks training reviewers to ignore the very area that later carries important information.

Warnings and status should be specific, compact, and close to the object they describe. The app should not use persistent generic banners for routine success messages. Error and security states for HTML reports should appear as precise chips or inline notices, with details available on demand.

### Speed-accuracy trade-off

When people move quickly, errors increase. Review sessions often encourage speed: scan image, drop pin, type comment, resolve, move on. The interface should make frequent safe actions fast and risky actions slower.

Resolving a thread can be one click because it is reversible through undo and reopen. Deleting a thread, discarding a draft, removing an annotation, or marking an artifact done with unresolved comments is riskier. Those actions should require clearer affordance, confirmation, or an undo buffer.

### Slips versus mistakes

A slip is an execution error: the user intended the right action but clicked the wrong control, hit the wrong key, or dropped a pin in the wrong place. A mistake is a planning or understanding error: the user misunderstood what `Done` means, thought a filter changed only the panel when it also hid pins, or believed a draft was saved when it was not.

Prevent slips through target size, spacing, undo, visible focus, and avoiding destructive controls next to frequent controls. Prevent mistakes through clear labels, stable terminology, previews, and state explanations. `Resolve thread` and `Mark artifact done` should remain distinct because they operate at different levels.

### Prevent, not just report, destructive or lossy actions

Error reporting is not enough. The app should design away common losses:

- Preserve comment drafts until explicit discard or successful save.
- Keep pending annotations visible until saved or canceled.
- Provide undo for resolve and reopen.
- Require confirmation or a safe undo for destructive deletes.
- Avoid mode ambiguity between pan, select, and annotate.
- Prevent navigation away from an unsaved draft unless autosave or recovery exists.

### Implications for this app

- Put errors next to the failed object: composer, ThreadCard, pin, or report frame.
- Use toasts as reinforcement, not as the only error channel.
- Keep routine success messages quiet and avoid persistent banner-like noise.
- Make reversible actions fast. Make destructive or lossy actions slower, confirmed, or undoable.
- Separate destructive actions from frequent actions by position and visual treatment.
- Use labels that name the object and effect, such as `Resolve thread`, `Reopen thread`, and `Discard draft`.
- Keep undo toast duration around 6 seconds for resolve and similar reversible state changes.
- Preserve draft text on save failure, navigation interruption, and temporary disconnect.

## 5. Accessibility as physiology, not compliance

### Motion sensitivity and vestibular triggers

Motion sensitivity is a physiological response, not a preference for less polish. Large parallax shifts, zooming backgrounds, bouncing controls, and unexpected spatial movement can trigger discomfort, nausea, dizziness, or disorientation for some users. A deep-zoom image viewer already involves pan and zoom motion, so the surrounding UI should be restrained.

The app must respect `prefers-reduced-motion: reduce`. In reduced motion mode, remove nonessential transforms, large slides, parallax, pulsing, and animated zoom transitions outside direct viewer manipulation. Keep opacity fades short and functional, ideally under 80 ms when needed to avoid abrupt disappearance.

### Photosensitivity limits

Flashing content can trigger seizures in photosensitive users. WCAG 2.2 includes a three-flashes-or-below-threshold criterion. This app has no reason to use flashing status indicators. Loading, saving, failed, selected, and unresolved states should use static shape, text, and modest color. Do not use blinking pins, pulsing error rings, or rapid skeleton shimmer.

Generated artifacts themselves may contain flashing or high-contrast patterns if the server later supports video or animated content. The review shell should not add more risk. If animated artifacts are supported later, playback controls and reduced-motion handling become part of the artifact viewer requirements.

### Keyboard-only users and the annotation canvas

A canvas-centered app can easily exclude keyboard-only users unless the spatial model is mirrored in DOM controls. The annotation layer should not be the only way to reach comments. Every annotation needs a corresponding ThreadCard in DOM order, a stable thread number, a status label, and keyboard navigation.

Keyboard users need to move through annotations and threads with predictable commands, such as previous and next annotation, focus selected thread, center selected annotation, resolve selected thread, reopen selected thread, and return to gallery. Focus should never disappear into the OpenSeadragon canvas without a visible ring and escape path.

### Screen-reader users and spatial pins

A screen reader cannot directly inspect an image pin in the same way a sighted user can. It can read alternative text, thread content, status, author, timestamp, and normalized coordinates. It can support navigation among comments and allow replies or resolution. It cannot independently verify that a pin is on the right visual defect unless the artifact has meaningful textual description or another human described the region.

For non-visual users, spatial pins should be represented as structured metadata, not only as canvas objects. A region can be announced as `Thread 4, unresolved region comment, x 42 percent, y 31 percent, width 18 percent, height 12 percent`. A point can be announced as normalized x and y coordinates. The app can offer `Center annotation` for low-vision keyboard users, but screen-reader users need the thread list as the primary interface.

The honest accessibility goal is not to pretend that visual artifact review is fully equivalent without vision. The goal is to make all non-visual parts accessible, to expose spatial annotations as structured data, and to support collaboration where a non-visual user can read, reply, resolve, audit, or export feedback even if they cannot judge the underlying visual defect alone.

### Implications for this app

- Respect `prefers-reduced-motion: reduce` and remove nonessential transforms.
- Keep reduced-motion opacity changes under about 80 ms.
- Do not use blinking or pulsing pins, badges, skeletons, or error indicators.
- Keep any flashing below WCAG 2.2 thresholds, and preferably avoid flashing entirely.
- Provide keyboard navigation for previous and next thread or annotation.
- Mirror every canvas annotation as a ThreadCard in the DOM.
- Give pins accessible names tied to thread number, status, and type.
- Announce selection changes through a polite live region.
- Represent spatial locations with normalized coordinates and region dimensions.
- Make non-visual workflows explicit: read comments, reply, resolve, reopen, inspect metadata, copy links, and export feedback are accessible, while independent visual defect judgment may require human-provided description.

## Sources

- Fitts, Paul M. "The Information Capacity of the Human Motor System in Controlling the Amplitude of Movement." 1954. Journal of Experimental Psychology, 47(6), 381-391. DOI: https://doi.org/10.1037/h0055392. PubMed: https://pubmed.ncbi.nlm.nih.gov/13174710/
- Hick, W. E. "On the Rate of Gain of Information." 1952. Quarterly Journal of Experimental Psychology, 4(1), 11-26. DOI: https://doi.org/10.1080/17470215208416600. Publisher page: https://journals.sagepub.com/doi/abs/10.1080/17470215208416600
- Hyman, Ray. "Stimulus Information as a Determinant of Reaction Time." 1953. Journal of Experimental Psychology, 45(3), 188-196. DOI: https://doi.org/10.1037/h0056940. PubMed: https://pubmed.ncbi.nlm.nih.gov/13052851/
- Miller, George A. "The Magical Number Seven, Plus or Minus Two: Some Limits on Our Capacity for Processing Information." 1956. Psychological Review, 63(2), 81-97. Full text: https://psychclassics.yorku.ca/Miller/. PubMed: https://pubmed.ncbi.nlm.nih.gov/13310704/
- Cowan, Nelson. "The Magical Number 4 in Short-Term Memory: A Reconsideration of Mental Storage Capacity." 2001. Behavioral and Brain Sciences, 24(1), 87-114. DOI: https://doi.org/10.1017/S0140525X01003922. PubMed: https://pubmed.ncbi.nlm.nih.gov/11515286/
- Nielsen, Jakob. "Response Time Limits: Article by Jakob Nielsen." Nielsen Norman Group. URL verified: https://www.nngroup.com/articles/response-times-3-important-limits/
- Nielsen Norman Group. "Memory Recognition and Recall in User Interfaces." URL verified: https://www.nngroup.com/articles/recognition-and-recall/
- Nielsen Norman Group. "10 Usability Heuristics for User Interface Design." URL verified: https://www.nngroup.com/articles/ten-usability-heuristics/
- Pernice, Kara. "Banner Blindness Revisited: Users Dodge Ads on Mobile and Desktop." 2018. Nielsen Norman Group. URL verified: https://www.nngroup.com/articles/banner-blindness-old-and-new-findings/
- Nielsen Norman Group. "Preventing User Errors: Avoiding Unconscious Slips." URL verified: https://www.nngroup.com/articles/slips/
- Doherty, Walter J., and Ahrvind J. Thadani. "The Economic Value of Rapid Response Time." 1982. IBM Technical Report GE20-0752-0. Primary report URL not verified. Secondary transcription found: https://jlelliotton.blogspot.com/p/the-economic-value-of-rapid-response.html
- Doherty, Walter J., and Richard P. Kelisky. "Managing VM/CMS Systems for User Effectiveness." 1979. IBM Systems Journal, 18(1), 143-163. DOI: https://doi.org/10.1147/SJ.181.0143. DBLP: https://dblp.org/rec/journals/ibmsj/DohertyK79
- Simons, Daniel J., and Christopher F. Chabris. "Gorillas in Our Midst: Sustained Inattentional Blindness for Dynamic Events." 1999. Perception, 28(9), 1059-1074. DOI: https://doi.org/10.1068/p281059. PubMed: https://pubmed.ncbi.nlm.nih.gov/10694957/
- Rensink, Ronald A., J. Kevin O'Regan, and James J. Clark. "To See or Not to See: The Need for Attention to Perceive Changes in Scenes." 1997. Psychological Science, 8(5), 368-373. DOI: https://doi.org/10.1111/j.1467-9280.1997.tb00427.x. Publisher page: https://journals.sagepub.com/doi/10.1111/j.1467-9280.1997.tb00427.x
- Ware, Colin. Information Visualization: Perception for Design, 4th edition. 2020. Morgan Kaufmann. Publisher page verified: https://shop.elsevier.com/books/information-visualization/ware/978-0-12-812875-6
- W3C. Web Content Accessibility Guidelines (WCAG) 2.2. URL verified: https://www.w3.org/TR/WCAG22/. Relevant success criteria include 1.4.3 Contrast (Minimum), 1.4.11 Non-text Contrast, 2.3.1 Three Flashes or Below Threshold, 2.5.4 Motion Actuation, 2.5.5 Target Size (Enhanced), and 2.5.8 Target Size (Minimum).
- Birch, Jennifer. "Worldwide Prevalence of Red-Green Color Deficiency." 2012. Journal of the Optical Society of America A, cited for prevalence context from memory, article URL not verified in this session.
- Simunovic, M. P. "Colour Vision Deficiency." 2010. Eye, 24, 747-755. PubMed URL verified: https://pubmed.ncbi.nlm.nih.gov/19927164/. Publisher page: https://www.nature.com/articles/eye2009251
- American Optometric Association. "Color Vision Deficiency." URL verified: https://www.aoa.org/healthy-eyes/eye-and-vision-conditions/color-vision-deficiency
