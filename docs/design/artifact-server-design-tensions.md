# Artifact Review Server Core Design Tensions

This catalogue names tensions that are inherent to UI and UX design. They cannot be removed by taste, tooling, or a better component library. They can only be navigated with explicit product rules, evidence, and tests.

The product context is a self-hosted artifact review server: generated visual artifacts, OpenSeadragon deep zoom, Annotorious region annotations, threaded resolvable comments, React and TypeScript, trusted private tailnet, normally one reviewer moving through batches. The artifact is the hero.

## 1. Simplicity versus capability

- **Tension**: Simple surface versus capable review instrument.
- **Why inherent**: Tesler's law applies: complexity is conserved, it moves rather than vanishing. If the UI hides annotation modes, resolution state, comparison, failures, and metadata, that complexity moves into memory, documentation, support, or mistakes.
- **Failure at each extreme**: Under-capability looks like Apple Preview for a review workflow, pleasant viewing but weak threaded resolution. Over-capability looks like Jira, every artifact trapped inside workflow machinery.
- **Drift signals**: Too simple: users ask where comments, filters, raw artifact links, or done state went. Too capable: reviewers spend more time managing status, menus, and metadata than inspecting the artifact.
- **Stance here**: Keep the default screen to inspect, comment, resolve, navigate, and recover. Any new capability must attach to one of those verbs and pass a one-sentence job test before it gets visible chrome.
- **New or deepened**: New.

## 2. Information density versus legibility and calm

- **Tension**: Dense review state versus calm artifact inspection.
- **Why inherent**: Reviewers need many facts at once, including unresolved counts, selected thread, save state, filters, and artifact provenance, but the same facts compete with visual inspection.
- **Failure at each extreme**: Too sparse looks like a lightbox gallery that hides status until click-through. Too dense looks like an analytics dashboard where every card, chip, and table fights the canvas.
- **Drift signals**: Too sparse: repeated panel opening, tooltip hunting, and memory of hidden counts. Too dense: eye travel rises, annotations blend into chrome, and screenshots no longer show the artifact as dominant.
- **Stance here**: Put density in the right rail and gallery cards, not around the canvas. The normal desktop review view fails if the artifact gets under 60 percent of horizontal space or if metadata is louder than unresolved review state.
- **New or deepened**: Deepened from `Information density versus breathing room`.

## 3. Speed for experts versus clarity for newcomers

- **Tension**: Fast repeated operation versus obvious first use.
- **Why inherent**: Expert speed depends on shortcuts, muscle memory, and reduced confirmation, while newcomer clarity depends on visible labels, feedback, and forgiving paths.
- **Failure at each extreme**: Expert-only failure looks like Vim-style modal power with no discoverable controls. Newcomer-only failure looks like wizard flows that make every repeated review pay the learning toll forever.
- **Drift signals**: Too expert: first-time reviewers cannot add a comment, resolve a thread, or escape a mode. Too novice: batch review feels like a form, with repeated clicks for actions that should be one keypress.
- **Stance here**: Core actions must have visible controls and documented shortcuts. Add comment, resolve, reopen, next, previous, fit, reset, and help must be discoverable without memory, while repeated navigation and thread actions must be reachable by keyboard.
- **New or deepened**: Deepened from `Power-user speed versus first-time clarity`.

## 4. Discoverability versus visual quiet

- **Tension**: Visible affordances versus quiet chrome.
- **Why inherent**: A reviewer cannot use invisible controls, but every visible control consumes attention that should belong to the artifact.
- **Failure at each extreme**: Too hidden looks like gesture-only mobile galleries where power exists but cannot be found. Too visible looks like ribbon toolbars that expose every command all the time.
- **Drift signals**: Too hidden: users hover-sweep, open overflow menus, or rely on remembered shortcuts. Too loud: toolbars expand, labels duplicate state, and the canvas feels framed by controls.
- **Stance here**: Keep a small visible toolbelt for core review actions, plus a command palette and menus for secondary actions. If a control is needed to inspect, comment, resolve, navigate, or recover, it cannot live only in an overflow menu.
- **New or deepened**: Deepened from `Discoverability versus visual quiet`.

## 5. Consistency versus context-specific optimisation

- **Tension**: Stable mental model versus optimized local behavior.
- **Why inherent**: Jakob's law says users expect this site to work like other sites they know, and they also expect each artifact type to respect its own constraints. A single layout cannot fit single images, galleries, HTML reports, desktop, and phone equally well.
- **Failure at each extreme**: Rigid consistency looks like a generic Material admin template applied to deep-zoom review. Excessive local optimization looks like Photoshop panels, GitHub comments, and slideshow controls stitched together with no shared model.
- **Drift signals**: Too rigid: image, gallery, and report views waste space or bury their primary action. Too local: `selected`, `resolved`, `open`, and `done` mean different things in different places.
- **Stance here**: Keep names, states, keyboard contracts, and selection semantics consistent. Let layout, panel persistence, and viewer controls adapt by artifact type and viewport only when the same review object model remains intact.
- **New or deepened**: Deepened from `Consistency versus context-specific optimization`.

## 6. Flexibility versus opinionated defaults

- **Tension**: User configurability versus guided review flow.
- **Why inherent**: More choices support more workflows but also create choice overload, slower decisions, and more states to remember.
- **Failure at each extreme**: Too opinionated looks like Linear's focused issue flow forced onto visual review when comparison or raw files matter. Too flexible looks like Jira configuration where the workflow becomes the work.
- **Drift signals**: Too opinionated: users need external notes, manual URL edits, or repeated filter changes to complete normal review. Too flexible: settings grow, defaults stop predicting the next task, and users ask which mode is correct.
- **Stance here**: Default to `Needs review`, unresolved comments visible, latest activity sort, and canvas-first layout. Add preferences only after the same workaround appears in real review tasks at least three times.
- **New or deepened**: New.

## 7. Recognition versus recall

- **Tension**: Visible memory aids versus remembered commands and state.
- **Why inherent**: Recognition lowers cognitive load by showing options and status, while recall enables compact expert operation but depends on memory and recent practice.
- **Failure at each extreme**: Recall-heavy failure looks like command-line flags for routine review actions. Recognition-heavy failure looks like Microsoft Office ribbon overload, where everything is visible and nothing is calm.
- **Drift signals**: Too much recall: users forget shortcuts, modes, filters, or which pin maps to which thread. Too much recognition: labels, badges, and helper text crowd out the artifact.
- **Stance here**: Show current mode, selected thread, unresolved count, save state, and shortcut help entry. Do not show full shortcut lists, advanced filters, or export affordances until requested.
- **New or deepened**: New.

## 8. Automation versus user control and trust

- **Tension**: Helpful automation versus controllable review judgment.
- **Why inherent**: Automation reduces work when it is right, but the irony of automation is that as systems handle routine work, humans are left supervising rarer, harder exceptions with less practice and less context.
- **Failure at each extreme**: Too little automation looks like manually refreshing, re-sorting, and re-counting every artifact. Too much automation looks like Gmail auto-categorization hiding important mail, or autopilot-style systems that surprise the operator at handoff.
- **Drift signals**: Too manual: reviewers repeat mechanical navigation and status updates. Too automatic: comments jump, artifacts mark done unexpectedly, filters change without explanation, or users stop trusting counts.
- **Stance here**: Automate loading, sorting, optimistic safe saves, and restoration of view state. Never auto-resolve comments, auto-mark artifacts done, or silently hide unresolved work.
- **New or deepened**: New.

## 9. Immediate feedback versus interruption

- **Tension**: Fast visible response versus attention theft.
- **Why inherent**: Users need confirmation that an action worked, failed, or is pending, but every toast, spinner, badge, and motion competes with the current inspection task.
- **Failure at each extreme**: Too little feedback looks like a save button that gives no pending or failed state. Too much feedback looks like Slack-style notification storms during focused work.
- **Drift signals**: Too quiet: duplicate submissions, refreshes, and uncertainty about save or resolve. Too interruptive: stacked toasts, layout shifts, focus steals, and animation around the canvas.
- **Stance here**: Mutations show local state within about 100 ms when possible. Use inline status for comments and threads, reserve toast for undo and failures, and never move focus for a successful background save.
- **New or deepened**: New.

## 10. Aesthetic appeal versus usability

- **Tension**: Beautiful interface versus usable review tool.
- **Why inherent**: The aesthetic-usability effect means attractive designs are often perceived as easier to use, but beauty cannot substitute for affordance, contrast, mapping, recovery, or speed.
- **Failure at each extreme**: Too utilitarian looks like unstyled internal admin pages that users distrust and avoid. Too aesthetic looks like portfolio sites where motion, translucency, and oversized visuals slow the actual task.
- **Drift signals**: Too plain: users miss hierarchy, status, and confidence cues. Too polished: gradients, shadows, animation, and brand color compete with annotation color and artifact detail.
- **Stance here**: Use visual polish only to clarify hierarchy, state, and calm. A decorative treatment fails if it reduces contrast, hides focus, slows interaction, or makes annotation status less distinct in dark mode.
- **New or deepened**: Deepened from `Aesthetic minimalism versus functional completeness`.

## 11. Safety versus friction

- **Tension**: Preventing harm versus keeping flow fast.
- **Why inherent**: Safety mechanisms add steps, reading, and delay, but removing them shifts cost to recovery after destructive or ambiguous actions.
- **Failure at each extreme**: Too little safety looks like permanent delete with no undo. Too much safety looks like Windows User Account Control prompts for low-risk routine actions.
- **Drift signals**: Too unsafe: lost drafts, accidental resolves with no recovery, and fear of clicking. Too frictional: confirmations for reversible actions, blocked batch flow, and ignored dialogs.
- **Stance here**: Reversible actions use undo, not confirmation. Destructive deletion, losing unsaved text, or replacing artifact data requires explicit confirmation with the object named.
- **New or deepened**: New.

## 12. Novelty versus familiarity

- **Tension**: Distinct product fit versus learned web conventions.
- **Why inherent**: Novel interactions can fit a specialized workflow, but familiar patterns carry users' existing expectations and reduce training.
- **Failure at each extreme**: Too familiar looks like a generic CRUD dashboard for image review. Too novel looks like gesture-driven experimental canvases where users cannot predict outcomes.
- **Drift signals**: Too familiar: the app feels like file management rather than review. Too novel: users hesitate before basic actions, ask what icons mean, or cannot use browser Back predictably.
- **Stance here**: Use familiar web patterns for navigation, panels, buttons, comments, forms, focus, and undo. Reserve novelty for direct artifact manipulation where OpenSeadragon and Annotorious provide clear viewer value.
- **New or deepened**: New.

## 13. Accessibility versus visual ambition

- **Tension**: Inclusive operability versus ambitious visual canvas.
- **Why inherent**: This is a false tension for text contrast, focus, keyboard access, reduced motion, and non-color state because accessible choices usually improve clarity for everyone. It is real for spatial annotation of visual artifacts, where some meaning is inherently visual and must be mirrored through DOM structure, text, and keyboard paths.
- **Failure at each extreme**: Accessibility-as-afterthought looks like canvas-only pins with no keyboard or screen reader path. Accessibility-as-flattening looks like banning visual region interaction entirely and losing the core review job.
- **Drift signals**: False-tension drift: teams treat low contrast or missing focus as aesthetic necessity. Real-tension drift: thread list and canvas annotations diverge, or keyboard users cannot create, select, resolve, and reopen review objects.
- **Stance here**: WCAG AA is the floor for chrome, text, focus, target state, and motion. Every annotation must have a thread-list equivalent with accessible name, state, selection, and actions, even if fine-grained visual inspection remains inherently visual.
- **New or deepened**: New.

## 14. Performance versus richness

- **Tension**: Fast interaction versus rich inspection and context.
- **Why inherent**: Deep zoom, thumbnails, galleries, HTML reports, annotation overlays, and threaded comments add value by loading, rendering, and synchronizing more state.
- **Failure at each extreme**: Too lean looks like static image links with no review state. Too rich looks like heavy Figma files or dashboard apps that feel powerful only after loading everything.
- **Drift signals**: Too lean: reviewers open external tools, lose comment context, or cannot compare. Too rich: slow initial load, janky pan and zoom, delayed comment save, and overlays that lag behind tiles.
- **Stance here**: Protect viewer responsiveness first: pan, zoom, select, type, and resolve must remain immediate. Lazy-load reports, metadata, history, and non-visible gallery assets after the review shell is usable.
- **New or deepened**: New.

## 15. Generality versus fitness for purpose in a component and token system

- **Tension**: Reusable design system versus review-specific primitives.
- **Why inherent**: Components and tokens need general rules to stay coherent, but over-general primitives lose the domain semantics that make artifact review fast and testable.
- **Failure at each extreme**: Too generic looks like Bootstrap cards and buttons with review meaning bolted on through copy. Too specific looks like one-off pin, thread, and toolbar variants that cannot share state, tokens, or accessibility behavior.
- **Drift signals**: Too generic: components require many props to become useful, and names do not reveal review purpose. Too specific: colors, spacing, focus, loading, and error states fork across gallery cards, thread cards, pins, and panels.
- **Stance here**: Build primitives named for review objects: `ArtifactViewer`, `AnnotationPin`, `ThreadCard`, `ReviewStatus`, `ViewerToolbar`, and `CommentComposer`. Tokens remain general for color, spacing, type, radius, motion, and elevation, but component contracts encode review semantics.
- **New or deepened**: New.

## Sources

- Alphonse Chapanis, Robert Garner, and Clifford Morgan, *Applied Experimental Psychology: Human Factors in Engineering Design*, 1949. URL not verified in this session.
- Larry Tesler, "Complexity Conservation," collected by the Interaction Design Foundation, page date not shown. URL: https://www.interaction-design.org/literature/book/the-glossary-of-human-computer-interaction/complexity-conservation
- Jon Yablonski, "Tesler's Law," *Laws of UX*, page date not shown. URL: https://lawsofux.com/teslers-law/
- Jakob Nielsen, "10 Usability Heuristics for User Interface Design," Nielsen Norman Group, 1994, last reviewed 2024. URL: https://www.nngroup.com/articles/ten-usability-heuristics/
- Jon Yablonski, "Jakob's Law," *Laws of UX*, page date not shown. URL: https://lawsofux.com/jakobs-law/
- William Edmund Hick, "On the Rate of Gain of Information," *Quarterly Journal of Experimental Psychology*, 1952. DOI URL: https://doi.org/10.1080/17470215208416600
- Barry Schwartz, *The Paradox of Choice: Why More Is Less*, 2004. URL not verified in this session.
- Jakob Nielsen, "Recognition Rather Than Recall in User Interfaces," Nielsen Norman Group, 1994, updated 2024. URL: https://www.nngroup.com/articles/recognition-and-recall/
- Lisanne Bainbridge, "Ironies of Automation," *Automatica*, 1983. DOI URL: https://doi.org/10.1016/0005-1098(83)90046-8
- Jakob Nielsen, "Response Times: The 3 Important Limits," Nielsen Norman Group, 1993. URL: https://www.nngroup.com/articles/response-times-3-important-limits/
- Masaaki Kurosu and Kaori Kashimura, "Apparent Usability vs. Inherent Usability," CHI 1995 Conference Companion, 1995. DOI URL: https://doi.org/10.1145/223355.223680
- Jon Yablonski, "Aesthetic-Usability Effect," *Laws of UX*, page date not shown. URL: https://lawsofux.com/aesthetic-usability-effect/
- Don Norman, *The Design of Everyday Things: Revised and Expanded Edition*, 2013. Author page URL: https://jnd.org/the-design-of-everyday-things-revised-and-expanded-edition/
- World Wide Web Consortium, *Web Content Accessibility Guidelines (WCAG) 2.2*, W3C Recommendation, 12 December 2024. URL: https://www.w3.org/TR/WCAG22/
- Google, *Material Design 3 Foundations*, page date not shown. URL: https://m3.material.io/foundations
