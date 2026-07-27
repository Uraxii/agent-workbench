# Artifact Server System and Input Surfaces

## Gap 7: Touch and gesture interaction

**Research question:** What can touch users reliably do on phone and tablet, and which desktop review features should intentionally degrade?

Touch support is for review, navigation, point feedback, lightweight replies, resolve, and reopen. It is not a full replacement for desktop precision annotation. OpenSeadragon owns gestures inside the viewer canvas: one-finger pan, pinch to image zoom, double tap to zoom toward the tap point, and toolbar reset to fit. Browser page zoom must not be disabled globally, so the app must not use `user-scalable=no`; only the viewer surface uses `touch-action: none` while the surrounding shell keeps normal browser scroll and zoom behavior.

Pin creation on touch uses a visible `24px` pin with an invisible `44px` by `44px` hit target. In add-point mode, the tap coordinate is the annotation anchor, the pin appears immediately in pending state, and the composer opens in the comments sheet. The composer, not a second tap, confirms the annotation. Existing pins are selected by tapping anywhere inside the `44px` hit target, not by touching the visible `24px` mark.

Tap is the primary semantic. A tap selects, activates a visible control, or places a point comment when point-comment mode is active. Long press is secondary only: after `550ms`, it opens a small action sheet with `Add point comment`, `Add general comment`, and `Cancel` when the target is the canvas. Long press must never be required for core review work, must not resolve a thread, and must cancel if the finger moves more than `8px`.

Region comments are reliable on desktop and tablet, but deliberately reduced on phone. On tablet at `768px` and wider, region creation uses a dedicated `Add region` mode: touch down starts a rectangle, drag sets its bounds, and release opens the composer. Region resize handles are `44px` touch targets with visible `12px` handles. On phone under `768px`, new region creation and geometry editing are hidden; users can still read, select, reply to, resolve, and reopen existing region threads, and can add point or general comments.

Desktop-only features are hover preview, hover-only pin to thread highlighting, pixel-level region resizing below `44px`, minimap navigation, dense rail layouts, and any keyboard shortcut shown without a visible touch control. These features may enhance desktop review, but no essential review state may exist only behind them.

Failure mode if done wrong: touch users either fight browser gestures inside OpenSeadragon, create accidental comments while trying to pan, or cannot select a `24px` pin accurately with a finger.

Rules:

- Do not disable browser zoom globally; never ship `user-scalable=no`.
- Set `touch-action: none` only on the OpenSeadragon viewer surface.
- Use `44px` minimum touch targets for pins, handles, toolbar buttons, sheet controls, and status actions.
- Keep visible pins at `24px`; expand only the invisible hit area.
- Make tap the core action and long press a rediscoverable secondary action.
- Hide phone region creation under `768px`; keep point comments, general comments, replies, resolve, and reopen available.
- Cancel pending touch annotation when movement exceeds `8px` before creation mode commits.
- Show bottom sheets on phone at `60vh`, expandable to `100vh`; comments drawers on tablet use `min(420px, 85vw)`.

## Gap 10: Design testing and verification

**Research question:** What automated and manual checks prove the design system actually meets the documented design rules?

Design correctness is verified with a small CI matrix, not by visual taste review. The required automated stack is Playwright for browser flows and screenshots, axe-core through `@axe-core/playwright` for accessibility rules, Vitest for token and utility tests, and a custom TypeScript contrast test using the WCAG relative luminance formula. Playwright, axe-core, `@axe-core/playwright`, and Vitest are real tools. If Storybook is adopted later, it may host fixtures, but CI must not depend on Storybook for the first build.

Automated checks run on every pull request. Token contrast tests assert every documented text, icon, focus, and status pair meets its target: `4.5:1` for normal text, `3:1` for large text and icons, `3:1` for focus indicators against adjacent colors, and a preferred `7:1` body text target in dark mode. Playwright runs keyboard task flows for gallery open, add point comment, reply, resolve, reopen, filter, return to gallery, and report sandbox viewing. Focus order is checked by pressing `Tab` and `Shift+Tab` through fixed fixtures and asserting the active element sequence.

Reduced motion is automated with Playwright `page.emulateMedia({ reducedMotion: 'reduce' })`. In that mode, transform animations must be absent, continuous animation must be absent, and remaining opacity changes must finish in `80ms` or less. Visual regression uses Playwright `toHaveScreenshot` against deterministic fixtures in Chromium at desktop `1440px` by `900px`, tablet `1024px` by `768px`, and phone `390px` by `844px`.

Manual verification remains required for the parts automation cannot reliably judge: screen-reader smoke tests, real touch testing, visual inspection of image dominance, and high-density comment readability. The manual checklist is short and release-blocking for design changes: VoiceOver on macOS or iOS, NVDA on Windows if available, one real phone or tablet over Tailscale, and one dense gallery with at least `24` artifacts and `40` mixed thread states.

Failure mode if done wrong: the app appears correct in a design document but ships unreadable token pairs, broken tab order, motion that ignores user settings, or annotation states that only work in the happy path.

Rules:

- CI must run Vitest token tests, Playwright task tests, Playwright screenshots, and `@axe-core/playwright` scans.
- Use deterministic fixtures for dark mode, light mode, compact density, high-density comments, failed saves, partial image load, and sandboxed reports.
- Screenshot thresholds must be tight enough to catch layout drift, with animation disabled during capture.
- Focus order tests must cover drawers, popovers, composer open, composer save failure, and Escape restoration.
- Axe checks do not replace manual screen-reader tests.
- Reduced-motion tests must assert behavior, not just CSS presence.
- Touch behavior must be checked on at least one physical touch device before release.
- Any new primitive needs a fixture for default, hover, focus, active, disabled, error, selected, and loading states where applicable.

## Gap 11: Onboarding and first-run

**Research question:** How does an intermittent reviewer learn `inspect, annotate, discuss, resolve, continue` in under one minute without a tutorial becoming permanent chrome?

The product uses no tutorial, no tour, and no coach marks that persist. First-run learning happens through specific empty states, visible primary actions, a shortcut dialog, and one dismissible first-comment hint. This is correct for a trusted, mostly single-reviewer tool because the review loop must feel like opening a focused work surface, not like entering a SaaS onboarding funnel.

With zero artifacts, the first screen shows an empty gallery state: title `No artifacts published yet`, one sentence explaining that generated artifacts will appear here, and a collapsed `Details` section that may show the expected publish path or command if the backend exposes it. No fake sample artifacts are shown, because they would confuse the review state. The primary action is disabled or absent unless the backend can provide a real upload or publish route.

With zero comments on an artifact, desktop opens the comments panel and shows `No comments yet` plus `Click the image or press C to add one`. Tablet and phone keep the artifact first and show a comments button with `0 open`. The first time a reviewer opens any artifact in a browser profile, a small non-modal hint appears near the comments control: `Add a point comment with C or the Add button`. It dismisses after the first submitted comment, after explicit close, or after `20s`, and does not return unless local preferences are reset.

A direct deep link must reorient without ceremony. The top bar shows artifact title, type, status, gallery position if known, and open count. If the linked thread exists, its card is selected and scrolled into view. If the linked thread no longer exists, the app shows an inline recoverable message in the comments panel and keeps the artifact visible.

Failure mode if done wrong: minimalism becomes mystery, so an intermittent reviewer sees a beautiful canvas but does not know where comments, open work, or the next artifact live.

Rules:

- Do not build a multi-step tutorial for the first version.
- Empty states must name the current object and the next useful action.
- First artifact hint appears once per browser profile, lasts at most `20s`, and never blocks the canvas.
- The shortcut dialog is opened by `?` and a visible menu item.
- Deep links must show context in the top bar without requiring a gallery visit first.
- Do not show fake demo content in a real review workspace.
- Rediscovery lives in visible labels, empty-state copy, and the shortcut dialog.
- Hints must not cover pins, the composer, or the selected thread.

## Gap 12: Personalization and persisted preferences

**Research question:** Which UI preferences should persist, where should they persist, and how does the app prevent saved state from hiding work?

Because there is no auth, preferences persist in `localStorage` per browser profile. They do not sync across devices. Server storage is reserved for review data: artifacts, threads, replies, resolution state, artifact done state, export status, and stable IDs. URL state is used only for shareable review context, such as artifact ID, selected thread ID, and explicit filter query when a link is copied.

Persist these preferences in `localStorage`: theme (`system`, `dark`, `light`), density (`comfortable`, `compact`), comments panel or rail open state, comments panel width from `320px` to `520px`, default thread filter, default gallery sort, zoom mode (`fit`, `actual-size`, `last-view`), annotation visibility, and first-run hint dismissal. Persist them with a namespaced key such as `artifactReview.preferences.v1` so resets and migrations are simple.

Do not persist high-risk state that can hide work or confuse links: selected thread, selected annotation, transient hover, pending resolve undo, active composer focus, unsaved annotation geometry, error banners, and per-artifact viewport unless the user explicitly chooses `last-view` zoom mode. Draft comment text may persist locally per artifact and annotation as safety state, but it is not a preference and must show a visible `Draft` marker.

Filters and sort must never hide work silently. If the saved filter excludes unresolved threads, the top bar still shows the total open count, and the panel shows a chip such as `3 open hidden by filter` with a one-click `Show open` action. Gallery sort may persist, but `Errors` and `Open comments` remain visibly counted in the top bar regardless of sort.

Across devices, nothing personal follows the reviewer except server-side review data. A phone may default to system theme and closed comments sheet even if desktop used compact density and an open panel. This is acceptable because the trust model is no-auth and device-local comfort matters more than account-level personalization.

Failure mode if done wrong: a saved narrow panel, hidden filter, or stale zoom state makes a reviewer miss open work and assume the artifact is done.

Rules:

- Store UI preferences in `localStorage`, not on the server.
- Use server state only for review facts and shared workflow state.
- Do not sync preferences across devices without adding authentication or an explicit device preference export.
- Keep open counts and error counts visible regardless of saved filter or sort.
- Provide `Reset view preferences` in settings; it clears the preference namespace but not drafts or comments.
- Clamp restored panel width to `320px` minimum and `520px` maximum.
- Default zoom mode is `fit`; `last-view` is opt-in and per browser.
- Version stored preferences and ignore unknown keys during migration.

## Gap 14: Data visualization, progress, and status summaries

**Research question:** What progress or status summaries are useful for review completion, and which would turn the app into a dashboard?

The app uses counts, chips, status pills, and one restrained gallery progress meter. It does not use charts, timelines, sparklines, pie charts, heatmaps, or dashboards in the review surface. The artifact is the hero, and progress exists only to answer whether there is work left.

The top bar for an artifact shows compact status: artifact status pill, unresolved thread count chip, resolved count in secondary text when useful, and export state if feedback JSON is part of the workflow. The comments panel header shows the active filter and exact counts, for example `Open 3`, `Resolved 8`, `All 11`. Thread cards carry their own status labels, not just colors.

The gallery has one progress summary above the grid: `7 of 24 reviewed`, `5 with open comments`, `2 errors`. If the gallery has more than one artifact, a thin progress meter may appear under the summary. It is `4px` high, neutral track, semantic filled segments only for `Done`, `Open comments`, and `Error`, and every segment value must also appear as text. On phone, the meter is hidden and the text summary remains.

No activity timeline ships in the first build. Last activity is a timestamp on cards and threads, not a separate visualization. Error count appears as a danger status chip only when count is greater than `0`. Export state appears as text plus status icon: `Not exported`, `Copied`, `Failed`, or `Out of date`.

Failure mode if done wrong: the review server drifts into an analytics dashboard and steals attention from the image while still failing to make the next action clear.

Rules:

- Use text counts first; add the gallery meter only when there are at least `2` artifacts.
- Never use color as the only status indicator.
- Do not add charts, timelines, heatmaps, or aggregate dashboards to the review surface.
- Keep progress meter height at `4px`; it must not become a hero element.
- Show exact counts, not percentages alone.
- Red or danger color is only for errors and failed operations, not ordinary unresolved work.
- Hide the meter on phone; keep the count text.
- Export state belongs near the action that copies or hands off feedback.

## Gap 15: Design-system documentation and decision records

**Research question:** What documentation must accompany primitives, tokens, exceptions, and design decisions so implementation does not invent local patterns?

The design system is documented where implementers work and where reviewers can audit reasoning. Tokens live in the frontend source as `src/design-system/tokens.css` plus a short `src/design-system/README.md`. Each primitive gets a colocated documentation file beside the component, for example `src/design-system/Button.mdx` or `src/design-system/Button.docs.md`. Product-level rationale and cross-component rules stay in `docs/design/`, including this file and the existing design research documents.

Each primitive document must include purpose, anatomy, variants, states, keyboard behavior, pointer and touch behavior, accessibility behavior, token usage, examples, anti-examples, and usage limits. A primitive is not ready if it only has a screenshot. It needs enough text for a new implementer to avoid inventing local spacing, colors, labels, or focus behavior.

Token exceptions require a recorded decision. A new color, spacing value outside the `4px` scale, new component primitive, changed status semantic, changed breakpoint, or changed touch target rule must be captured with date, decision, rationale, alternatives rejected, affected files, and revisit condition. In this repository, the durable record is a decision note created through the existing `record-decision` workflow and linked from the relevant `docs/design/` file. If the implementation repository differs, it must keep the same fields in `docs/design/decisions/` or an ADR directory.

Design docs must rot less by being close to tests. Every primitive doc lists the fixture or Playwright spec that verifies it. Every token table lists its contrast test coverage. Every decision record links to the component, test, or route it changed.

Failure mode if done wrong: local CSS exceptions accumulate, primitives fork silently, and later implementation cannot tell whether a difference is intentional or accidental drift.

Rules:

- Document tokens in `src/design-system/tokens.css` and `src/design-system/README.md`.
- Document each primitive beside its implementation with purpose, anatomy, states, behavior, accessibility, tokens, examples, anti-examples, and usage limits.
- Keep product rationale in `docs/design/`; do not bury product decisions only in component comments.
- Record every new primitive, token exception, semantic status change, breakpoint change, or touch target change as a dated decision.
- Link decisions to affected files and verification fixtures.
- Prefer changing a primitive over adding route-specific CSS.
- Remove or supersede stale examples in the same change that alters a primitive.
- A screenshot without behavior and accessibility notes is not design-system documentation.

## Gap 16: Iconography

**Research question:** What icon style and icon-label policy gives the app quiet density without hiding meaning from occasional reviewers or assistive tech?

Use Lucide React as the icon set for the first build. It is outline-based, consistent, tree-shakeable, and already fits a quiet professional tool. Default icon size is `16px` inside text rows and chips, `20px` inside `36px` desktop icon buttons, and `24px` inside `44px` touch buttons. Default stroke width is `2px`, with `stroke-linecap="round"` and `stroke-linejoin="round"`. Filled icons are not used except if a third-party status asset is unavoidable, which should be treated as an exception.

Icons are supplemental for primary actions. `Add comment`, `Resolve thread`, `Reopen`, `Copy feedback JSON`, `Open raw artifact`, `Mark artifact done`, and destructive or recovery actions require visible text labels in their primary placement. Icons may appear without labels only in persistent, repeated toolbars where the control also has an accessible name, a tooltip on hover and focus, and predictable position: zoom in, zoom out, fit, reset, comments panel toggle, annotations toggle, previous, next, close, and overflow menu.

Status iconography must differ by shape, label, and accessible text, not color alone. Error uses an alert triangle or circle-alert icon plus `Error` text. Warning uses a triangle plus label. Resolved uses a check icon plus `Resolved`. Selected uses focus ring, border, and `aria-selected`, not a unique icon. Hidden annotations use an eye-off icon only with visible `Hidden` or `Annotations hidden` text where state matters.

Icon-only controls must be real buttons with `aria-label`, `title` or custom tooltip content, visible focus ring, and `44px` touch target when pointer is coarse. Decorative icons in labeled controls must use `aria-hidden="true"`.

Failure mode if done wrong: occasional reviewers and assistive tech users see a wall of unlabeled glyphs and must learn a private icon language before leaving feedback.

Rules:

- Use Lucide React outline icons for the first build.
- Use `16px`, `20px`, and `24px` icon sizes only unless a component documents an exception.
- Use `2px` stroke width by default.
- Require visible labels for primary, destructive, export, resolve, reopen, and recovery actions.
- Allow icon-only buttons only for repeated viewer controls with stable placement.
- Every icon-only button needs `aria-label`, tooltip on hover and focus, and focus-visible styling.
- Decorative icons inside labeled controls use `aria-hidden="true"`.
- Do not communicate status by color or icon alone; pair with text.

## Gap 17: Internationalization and text expansion

**Research question:** Is the rewrite intentionally English-only, or must it preserve layout and semantics under localization, text expansion, locale formats, and bidirectional text?

The first build is intentionally English-only. This is a product scope decision for a private, single-reviewer tailnet tool, not a statement that the layout may be English-fragile. Localization is revisited if two or more regular reviewers need another language, if the tool becomes shared outside the trusted private environment, or if exported feedback must be consumed by a localized downstream system.

Even while English-only, the UI must be safe under text expansion. Buttons size to content with minimum heights, not fixed English widths. Status pills allow at least `40%` text expansion before truncation. Thread cards and empty states wrap naturally. Top-bar titles truncate from the middle only for filenames, paths, hashes, and artifact IDs. Critical action labels do not truncate below `320px`; instead they move into the overflow menu or bottom sheet.

Use browser locale APIs for dates, times, and numbers even in English. Timestamps use `Intl.DateTimeFormat` with a concise format in the UI and full timestamp in the tooltip or details. Counts use `Intl.NumberFormat`. Keyboard shortcut labels are generated from platform-aware display strings, so `Cmd` and `Ctrl` are not hard-coded into prose.

Right-to-left layout is not supported in the first build, but the layout must not make it impossible later. Use logical CSS properties where cheap, such as `margin-inline`, `padding-inline`, `border-inline`, `inset-inline`, and text alignment tokens. Avoid baking left and right into component names unless they describe physical viewer placement. Annotation coordinates remain normalized image coordinates and do not flip with text direction.

Failure mode if done wrong: the English-only first build becomes permanently unlocalizable because buttons, rails, pills, and status summaries were sized to short English labels.

Rules:

- Ship English-only in the first build.
- Revisit localization when multiple regular reviewers need it, deployment leaves the private tailnet assumption, or downstream feedback requires localized text.
- Do not use fixed-width buttons sized to English labels.
- Allow status pills and chips to grow until layout pressure requires truncation.
- Never truncate critical actions; move them to a menu or sheet instead.
- Use `Intl.DateTimeFormat` and `Intl.NumberFormat` for visible dates, times, and counts.
- Use logical CSS properties for new layout code where practical.
- Keep annotation coordinates independent from text direction.
