# Artifact Server Review Surfaces

This closes the assigned design gaps for the artifact review web app. It only defines review surfaces that affect generated artifacts, annotations, threads, and compare review.

## Gap 1: State and feedback states

Research question: What exact UI state model covers loading, empty, success, saving, pending, failed, offline, stale, conflict, partial tile failure, and report sandbox load across images, galleries, reports, comments, and exports?

Position: Use one explicit state vocabulary across the gallery, canvas, thread rail, and composer. State is shown locally at the smallest surface that can explain the problem, never as a full-screen blocker after the app shell has loaded.

### Timing and loading policy

- `0 to 100 ms`: no indicator. Optimistic UI may update immediately.
- `100 to 150 ms`: reserve space, no spinner.
- `150 to 600 ms`: show skeletons for lists, cards, headers, and side panels. Show OpenSeadragon progressive tile loading in the viewer corner.
- `600 to 5000 ms`: add an inline spinner only inside the affected surface, sized `16px` for controls or `24px` for panels.
- `5000 ms`: add stalled copy, for example `Still loading tiles`, with a retry action if retry is safe.
- `30000 ms`: treat as error for API calls and report iframe load. Tile sources may continue partial loading if at least one tile level is visible.
- Skeletons are used when shape is predictable. Spinners are used only when shape is unknown or an individual mutation is pending.
- Full-screen spinner is allowed only before the app shell renders, for a maximum of `1000 ms`, then it must become a shell skeleton or error page.

### Surface state inventory

| State | Gallery | Canvas | Thread rail | Composer |
| --- | --- | --- | --- | --- |
| Idle | Grid or list is visible with current search, filters, sort, selected card, and counts. | Artifact, OpenSeadragon controls, annotation layer, selected thread highlight, and tile status are visible. | Open and resolved groups are visible according to filter, with selected thread scrolled into view. | Empty focused or unfocused field shows placeholder `Write feedback` and submit disabled until non-empty text exists. |
| Loading | Card skeletons fill the grid using `220px` minimum card width, with top bar count skeletons. | Viewer shell, toolbar, and title stay mounted. Known dimensions show a low-detail placeholder, unknown dimensions show a centered canvas skeleton. | Thread card skeletons appear in the rail, preserving `360px` panel width. | Existing draft stays editable. If submitting, only the submit control shows a `16px` spinner and disabled state. |
| Empty | Shows `No artifacts published yet` with the expected source path or publish command if known. | Shows `No artifact selected` only on routes that can validly have no selection. Otherwise redirects to gallery empty state. | Shows `No comments yet` and `Click the image or press C to add one`. | Shows placeholder and helper text `Cmd+Enter to submit, Enter for newline`. |
| Partial | Shows loaded cards plus bottom row `More artifacts loading` when pagination or thumbnail fetch is incomplete. Failed thumbnails show a neutral placeholder per card. | Shows visible tiles normally, a corner chip `Some tiles failed`, and retry. Missing tiles use checkerboard placeholders, not blank black. | Shows loaded threads and a `Some replies failed to load` inline row with retry at the affected thread. | Draft remains editable. If linked annotation geometry is pending, a chip reads `Annotation not saved yet`. |
| Error | Shows `Artifacts failed to load` with `Retry` and collapsed technical details. Any cached cards remain visible below an error banner. | Shows `Artifact failed to load` inside the canvas with `Retry`, `Open raw artifact`, and details. Comments remain usable if their API loaded. | Shows `Comments failed to load` with `Retry`; canvas and gallery stay usable. | Save failure keeps text and geometry, shows danger border, inline error text, `Retry`, and `Copy text`. |
| Offline | Shows cached cards if present and a top bar chip `Offline`. Actions needing the server are disabled with reasons. | Existing loaded image stays visible. New tile loads may show partial state. A polite banner says `Connection lost. Review visible content only`. | Cached threads stay readable. Resolve, reopen, reply, and new thread submit are disabled. | Draft remains editable and autosaved locally. Submit is disabled with `Reconnect to submit`. |
| Stale | Shows a subtle banner `List updated` with `Refresh` when newer artifact metadata exists. Existing scroll and selection do not move. | Shows `Newer artifact version available` in the top bar. Current view stays pinned until user chooses `Open latest version`. | Threads tied to an older artifact show a `Stale` chip and keep coordinates visible. | Draft linked to stale geometry shows `Review position before submitting` and submit stays enabled only after user confirms the current version. |
| Saving | Batch status or artifact done action shows pending state near the clicked control. Cards update optimistically with a small pending dot. | Pending pin or region appears immediately with dashed `2px` outline and 12 percent fill. | Thread being resolved, reopened, or replied to shows pending row state and disables duplicate action only. | Submit button shows `Saving`, field remains readable, text cannot be edited during the network request, and focus stays in place. |
| Saved | Card status and counts update within `100 ms`; success toast appears only for cross-surface actions such as `Artifact marked done`. | Pending annotation becomes a normal open annotation. Selected state remains. | Reply appears in chronological order. Resolve moves the card to the resolved group and shows undo toast for `6000 ms`. | Composer clears submitted text, keeps focus if the reviewer is still in the same thread, and shows `Saved` for `1200 ms`. |
| Conflict | Card shows `Changed on server` and opens the current server version on selection. | Shows `This artifact changed on the server. Review latest before editing` and blocks new annotation geometry until refreshed. | Affected thread shows server copy above local attempted change, with `Keep server version`, `Copy my text`, and `Retry as new reply`. | Draft is preserved. Submit is blocked until the reviewer chooses `Reload thread` or `Copy text and discard local conflict`. |

### Transitions

- Initial route: `loading` to `idle`, `empty`, `partial`, or `error`.
- Network loss: any non-terminal state to `offline`; reconnect returns to `stale` if server versions changed, otherwise previous state.
- Mutations: `idle` to `saving` to `saved`, `error`, or `conflict`.
- Optimistic resolve: rail moves thread immediately to resolved pending state; failure rolls it back to open with the original selection restored.
- Tile failures: canvas moves from `loading` to `partial` if at least one useful level is visible, otherwise to `error`.
- Report iframe: `loading` to `idle` when the sandboxed frame fires load, `partial` when static HTML loads but resources fail, `error` after `30000 ms` or sandbox denial. The security chip `Scripts disabled` is not an error.
- Export job: `idle` to `saving` to `saved` or `error`; exported JSON version and timestamp appear only after `saved`.
- Settings save: local preferences such as density and panel width update immediately, persist in local storage, and roll back only if server-backed settings later exist and reject.

### Keyboard path

- `Tab` reaches the top bar status chip, gallery search, active card, canvas toolbar, thread rail, and composer in DOM order.
- `Escape` clears error popovers first, then closes menus, then cancels annotation creation, then returns focus to the invoking control.
- `R`, `Shift R`, `C`, `[`, `]`, `F`, `0`, `+`, `-`, `G`, and `?` keep working in idle, partial, stale, and saved states when focus is not inside text entry.
- Disabled actions remain focusable only when they carry essential explanation through `aria-describedby`; otherwise they are skipped.

### Accessibility consequence

Every state must have text, not just color. Loading uses `aria-busy` on the affected region. Mutation results use `aria-live="polite"`; destructive or blocking errors use `aria-live="assertive"`. Skeletons are hidden from screen readers. The current state is exposed through labels such as `Gallery, offline, 24 cached artifacts`.

### Failure mode if done wrong

The reviewer will move on while the UI silently failed to save, or will assume a draft, stale coordinate, or partial tile view is final feedback. Full-screen blocking states would also make one failed surface stop independent review work.

### Rules

- Show state where the state belongs, not globally, unless the shell cannot load.
- Never discard composer text, pending geometry, or conflict text automatically.
- Use skeletons for predictable content after `150 ms`; use inline spinners only for unknown or mutation state after `600 ms`.
- Preserve independent work during gallery, tile, thread, report, and export failures.
- Treat `Scripts disabled` as normal report state, not an error.
- Roll back optimistic mutations visibly and restore focus to the affected object.

## Gap 4: Search, filter, and sort

Research question: What search, filter, and sort model lets reviewers find artifacts, threads, report sections, unresolved work, and previous feedback without hiding important state?

Position: Provide one compact search and filter strip above the surface being searched, plus command palette jump for power use. Defaults prioritize unresolved work, but every filtered view must show counts for hidden states and a one-action clear path.

### Concrete UI behavior

- Gallery search lives in the gallery top bar, left of filter chips, width `280px` desktop, `100%` row width on phone.
- Thread search lives at the top of the thread rail, below the rail header, width `100%`.
- Report search uses the same top bar field when the report route is active and searches stable section titles, anchors, visible text excerpts, and comments.
- Global jump lives in `Cmd+K`: artifacts by title or filename, threads by text, report sections by heading, and commands such as `Open next unresolved`.
- Search debounce is `150 ms` for local indexed data and `300 ms` for server queries. Results update without moving keyboard focus.
- Search query persists in the URL for shareable routes as `q=`. Filter and sort persist in the URL as `filter=` and `sort=` when not default. Last-used gallery filter also persists in local storage, but only if the visible URL or chip shows it.

### Searchable fields

- Artifacts: title, filename, type, status, generated timestamp, source label, version label, unresolved count, and error text.
- Threads: body text, replies, thread number, status, location chip, author label, timestamp, edited marker, and stale marker.
- Report sections: heading text, stable anchor id, visible excerpt up to `240` characters, linked thread text, and sandbox error text.
- Feedback history: resolved thread body, replies, edited marker, resolver label, and resolved timestamp.
- Not searchable: raw image pixels, hidden report script output, unsubmitted private drafts, local-only viewer coordinates, and raw exported JSON blobs.

### Filters

- Gallery chips, default visible row: `Needs review`, `Open comments`, `Done`, `Errors`, `All`.
- Gallery `More filters`: artifact type `Image`, `Gallery`, `Report`; `Stale`; `Has draft`; `Export failed`.
- Thread chips, default visible row: `Open`, `Resolved`, `All`, `General`, `Region`.
- Thread `More filters`: `Stale`, `Failed save`, `Agent comments`, `Edited`.
- Report filters: `Sections with comments`, `Sections with open comments`, `Sections with errors`, `All sections`.
- Unresolved state is always represented as `Open`, never only by color or count.

### Sort

- Gallery default sort: `Needs review`, then `Open comments`, then `Errors`, then newest generated timestamp, with stable filename order inside ties.
- Thread default sort: open first, selected thread pinned within view, then creation order. Replies remain chronological oldest to newest.
- Report default sort: document order. Sections with open comments can be filtered, but not re-sorted away from document order.
- Search result sort: exact title or filename match first, then open thread matches, then recency. Result groups stay separate: `Artifacts`, `Threads`, `Report sections`, `Commands`.
- Sorting must not change after each reply. Counts update, but row order stays stable until the user changes route, filter, or sort.

### Empty-result treatment

- Empty search: `No results for "query"` with `Clear search` and still-visible counts for open, resolved, errors, and total.
- Empty filter: `No open threads match this filter` with `Show all threads`.
- Empty gallery filter: `No artifacts match these filters` with `Clear filters` and a compact summary such as `12 artifacts hidden`.
- Empty report filter: `No report sections with open comments` with `Show all sections`.
- Empty states never remove the search field, filter chips, or current count summary.

### Keyboard path

- `Tab` enters search, filter chips, sort menu, result list, and clear action in that order.
- `Enter` on a selected search result opens it. `Escape` clears the search field if focused, then closes the result popover.
- Arrow keys move inside result lists and chip groups. `Home` and `End` move to first and last chip in the focused chip group.
- `Cmd+K` opens global jump without hijacking `Ctrl+F` or browser find.

### Accessibility consequence

Search and filter controls need explicit labels, result counts, and active filter names. The result list uses `role="listbox"` only while the search field owns focus, otherwise normal links are better. Count changes are polite live announcements, for example `5 threads shown, 17 hidden`.

### Failure mode if done wrong

The reviewer will think work is complete because a saved filter hid open comments, or will lose spatial context because sorting changes after every mutation.

### Rules

- Default to unresolved work, but always show hidden counts and clear controls.
- Persist non-default search state in the URL, not only local memory.
- Do not search private drafts or raw image pixels.
- Keep report sections in document order.
- Keep thread order stable during replies and resolves.
- Never make `Mine` a filter in the first build.

## Gap 5: Author identity and single-reviewer authorship

Research question: In a no-auth, effectively single-reviewer tool, what identity model should comments, filters, timestamps, edited markers, and `Mine` semantics use?

Position: Ship a typed authorship model without account chrome. Human review comments display as `You`; automated comments display as named agents. There is no first-build `Mine` filter and no user-facing identity configuration.

### Concrete UI behavior

- Human comments show `You` in the header, timestamp, and edited marker when applicable.
- Agent comments show `Agent: <name>` with a small neutral `Agent` chip, never an avatar. The chip is `20px` high and uses neutral color plus text.
- System-generated import or export notes show `System` and are visually quieter than comments. They cannot be replied to unless the backend promotes them to threads.
- Thread pins continue to show thread number, not author initials.
- Timestamps use relative time under `24` hours, then absolute local date and time, for example `Jul 24, 2026, 14:32`.
- Edited comments show `edited` beside the timestamp. Hover or focus reveals exact edit timestamp.
- If a second human appears because another browser posts with the same no-auth endpoint, the UI still shows both as `You` unless the backend provides a distinct `author.id`. That is acceptable for the trust model and should trigger a later multi-reviewer design, not account UI now.

### Storage model

Store authors as typed metadata, not display strings:

```json
{
  "kind": "human",
  "id": "local-reviewer",
  "displayName": "Reviewer"
}
```

Agent comments use:

```json
{
  "kind": "agent",
  "id": "agent:<stable-name>",
  "displayName": "<stable-name>"
}
```

System notes use `kind: "system"`. Export JSON must include `kind`, `id`, and `displayName` so downstream automation can distinguish human judgment from automated suggestions.

### Configuration position

- No user-facing profile, initials, color picker, avatar, or `Mine` setting in the first build.
- Optional server configuration may set the human export display name, default `Reviewer`, but the UI still renders the active local human as `You`.
- Agent names are supplied by the posting client or backend job and must be stable ASCII labels up to `64` characters.
- Revisit identity only when two or more named humans need simultaneous review, accountability, or permission boundaries.

### Keyboard path

- Author chips are not in the normal tab order unless they expose a popover with details.
- `Tab` reaches thread actions, not decorative identity labels.
- Screen reader text includes author kind, for example `Thread 4, unresolved, by agent render-critic, created today at 14:32`.

### Accessibility consequence

Distinguishing human, agent, and system authors by text prevents color-only or avatar-only identity. Avoiding initials on pins reduces noise and helps screen-reader parity because the thread number is the stable cross-reference.

### Failure mode if done wrong

The UI may imply collaboration and permissions that do not exist, or automated comments may be mistaken for the reviewer’s own final judgment.

### Rules

- Render the local human as `You`.
- Render agents as `Agent: <name>` with a textual chip.
- Do not ship `Mine` filter in the first build.
- Do not put avatars or initials on annotation pins.
- Store author kind, id, and display name in export JSON.
- Do not add account settings until multi-human review is real.

## Gap 6: Forms, composer, text entry, and validation

Research question: What exact composer and text-entry rules prevent lost feedback while keeping comment creation fast?

Position: Use one inline composer for new threads and replies. It supports Markdown-lite text, autosaves private drafts locally, submits explicitly with `Cmd+Enter` or button, and never accepts image attachments in the first build.

### Concrete UI behavior

- Composer minimum height is `88px`, normal height `144px`, maximum auto-expanded height `240px`, then internal scroll.
- Width is the rail width minus `32px` padding on desktop, or full sheet width minus `32px` on phone.
- Placeholder: `Write feedback`.
- Helper row: `Cmd+Enter to submit, Enter for newline`.
- Button row: `Submit` primary, `Discard draft` ghost only when draft text or unsaved geometry exists.
- Autosave starts after first non-empty change, debounced `500 ms`, to local storage or IndexedDB by `artifactId`, `threadId` or pending annotation id, and artifact version.
- Draft indicator appears within `100 ms` after local save as `Draft saved locally`, then fades after `1200 ms`.
- Submitted comments are server state. Drafts are private local state and never exported.

### Text rules

- Markdown-lite is allowed: paragraphs, hard line breaks, bullets, numbered lists, blockquotes, inline code, fenced code, and links.
- Raw HTML, images, tables, headings, task lists, and embedded iframes are not supported.
- Links open in a new tab and show the raw URL on hover or focus.
- Rendering sanitizes output and treats unsupported Markdown as plain text.
- No live preview in the first build. A `Preview` toggle may be added later if reviewers need rich formatting.

### Submit and newline keys

- `Enter` inserts a newline.
- `Shift+Enter` inserts a newline.
- `Cmd+Enter` on macOS and `Ctrl+Enter` on Windows or Linux submits.
- The visible `Submit` button is required for discoverability and touch.
- While IME composition is active, submit shortcuts are ignored.
- Global shortcuts are disabled while focus is inside the composer except `Escape` for local cancellation.

### Validation and limits

- Minimum body: `1` non-whitespace character after trimming.
- Maximum comment or reply body: `4000` Unicode scalar values.
- Maximum rendered link URL: `2048` characters.
- Maximum draft count per artifact: `20`; the oldest empty or fully submitted draft is purged first.
- Empty submit error: `Write a comment before submitting`.
- Too long error: `Comment is 421 characters over the 4000 character limit`.
- Stale version warning: `This draft was started on an older artifact version. Review the position before submitting`.
- Validation errors appear below the field, set `aria-invalid="true"`, and keep focus in the composer.

### Paste and attachment behavior

- Pasted plain text is inserted as text.
- Pasted rich text is converted to plain Markdown-lite where safe, otherwise plain text.
- Pasted images are not uploaded. The composer shows `Image paste is not supported. Save the image as an artifact or link to it` and leaves the image out.
- Pasted files are rejected with the same inline message.
- Large pasted text over the limit is inserted up to the limit only after confirmation through an inline `Trim to 4000 characters` action. Without confirmation, the existing draft is unchanged.

### Draft navigation behavior

- Closing the comments panel keeps draft text and pending geometry.
- Navigating to another artifact keeps the draft and shows a `Draft` badge on the source artifact card.
- Returning to an artifact with a draft reopens the comments panel on desktop and shows a `1 draft` chip on tablet and phone.
- Browser Back, gallery return, reload, and tab close do not show a blocking prompt if the draft has been autosaved locally.
- If a submit request is in flight and the user navigates away, show a route-level confirmation: `Comment is submitting. Leave this page?` because that state is not yet recoverable from local draft alone.
- `Discard draft` requires one confirmation only when text or unsaved geometry exists: `Discard local draft?` with `Discard` and `Keep editing`.

### Editing submitted comments

- Editing is inline on the comment, not in a modal.
- Only the body is editable. Author, timestamp, location, and thread id are immutable.
- `Cmd+Enter` saves edits. `Escape` cancels edits and restores the last server body.
- Save failure preserves edited text and offers `Retry`, `Copy text`, and `Cancel edit`.
- Delete comment is not built in the first build. If deletion is later added, it requires confirmation and is not grouped with resolve.

### Keyboard path

- `C` creates a general comment and focuses the composer.
- Point or region annotation creation focuses the composer after geometry is placed.
- `Tab` moves from text area to submit, discard, formatting help, then back to thread actions.
- `Escape` in a new empty composer closes it. `Escape` in a non-empty draft asks for discard confirmation. `Escape` during annotation geometry cancels geometry first and preserves text.

### Accessibility consequence

The composer is a labeled form with helper text, live draft status, explicit validation, and no hidden submit requirement. Autosaved drafts are announced politely. Error messages are associated with the text area. Button labels include target context, for example `Submit reply to thread 4`.

### Failure mode if done wrong

The reviewer will lose feedback during navigation, believe a local draft was submitted, or fail to submit because the newline and submit keys conflict with typing expectations.

### Rules

- Drafts autosave locally; submitted feedback requires explicit submit.
- Preserve text and geometry through close, reload, route changes, failed save, and conflict.
- Use Markdown-lite only, no images or raw HTML.
- Enforce `4000` character body limit and `1` character minimum.
- Do not block navigation for autosaved drafts, only for in-flight submit.
- Keep one active composer per thread or pending annotation.

## Gap 13: Compare workflow

Research question: Should compare be a first-build feature, and if so, what visual, keyboard, accessibility, and comment model does it use?

Position: Compare is a first-build feature for image artifacts only. It is a URL-addressable page state with two side-by-side OpenSeadragon viewers, synchronized pan and zoom when dimensions match, and separate comments per artifact. Overlay, swipe, opacity blend, and multi-artifact compare are deliberately not built.

### Concrete UI behavior

- Entry points: `Compare previous`, `Compare next`, gallery card overflow `Compare with current`, and command palette `Compare current with...`.
- Adjacent compare opens in `1` step from an artifact detail view. Arbitrary compare opens in `2 to 4` steps through a picker.
- Route shape: `/artifacts/:leftId/compare/:rightId`, with optional `thread=`, `zoom=`, `x=`, `y=`, and `sync=` parameters.
- Desktop layout at `1280px` and wider: top bar `56px`, two viewers split `50/50`, draggable splitter `12px` hit area with `1px` visible line, comments rail `360px` on the right.
- The comments rail has two tabs: `Left comments` and `Right comments`, each showing only that artifact’s threads. Counts appear in the tab labels.
- Same pixel dimensions default to `Sync on`. Different dimensions default to `Sync off` with visible copy `Different dimensions` beside the toggle.
- With sync on, pan and zoom changes in the active viewer apply to the other viewer within `50 ms`, using normalized coordinates and zoom ratio.
- The active viewer has a `2px` focus ring inside its viewport edge and a label in the top bar, `Editing left` or `Editing right`.
- Comments attach only to the active viewer’s artifact. Creating a new annotation requires the reviewer to focus left or right first.
- The splitter position persists per compare route in local storage, default `50%`, min `35%`, max `65%`.

### Responsive behavior

- Tablet `768px to 1279px`: viewers remain side by side if each can keep at least `360px` width. Comments become an overlay drawer.
- Phone under `768px`: compare opens as stacked viewers with a sticky segment control `Left`, `Right`, `Both`. `Both` is read-only inspection. Comment creation is allowed only in `Left` or `Right` mode.
- If either viewer would fall below `320px`, sync stays available but region drawing is disabled and point comments remain available.

### Keyboard path

- `Cmd+K`, type `Compare previous` or `Compare next`, `Enter` opens adjacent compare.
- `Tab` reaches left viewer, splitter, right viewer, sync toggle, comments tabs, active thread list, and composer.
- Arrow keys on the focused splitter adjust by `2%`; `Shift+Arrow` adjusts by `10%`.
- `S` toggles sync when focus is not in text entry.
- `L` focuses the left viewer and `;` focuses the right viewer when focus is not in text entry.
- `[` and `]` move through threads in the active side only.
- `G` returns to the source gallery and preserves compare route in browser history.

### Accessibility consequence

Each viewer is labeled as `Left artifact` or `Right artifact` with title, dimensions, and sync state. The splitter uses `role="separator"`, `aria-orientation="vertical"`, and `aria-valuenow` as a percentage. Sync changes are announced politely. The comments rail tabs keep left and right threads separate so screen-reader users do not hear a merged thread list with ambiguous coordinates.

### Failure mode if done wrong

If compare merges comments, hides which side is active, or uses overlay-only blending, reviewers will attach feedback to the wrong artifact or miss differences that require independent zoom inspection.

### Deliberately not built

- No opacity overlay, swipe reveal, difference blend, or heatmap in the first build.
- No three-way or N-way compare.
- No compare for HTML reports in the first build.
- No synchronized annotation editing across both artifacts.
- No automatic visual diff detection.
- No persistent second comments rail that reduces the canvas below the `60%` artifact-space rule.

### Rules

- Build compare as a page state, not a modal.
- Use side-by-side OpenSeadragon viewers.
- Default sync on only for same pixel dimensions.
- Keep comments and annotations attached to exactly one artifact side.
- Make the active side visible in the viewport, top bar, rail tab, and screen-reader label.
- Revisit overlay or swipe only after side-by-side compare fails real review tasks on same-size images.
