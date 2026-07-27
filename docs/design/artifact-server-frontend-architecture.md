# Artifact Server Frontend Architecture

## Purpose

This document designs the React and TypeScript single page app for the artifact review server rewrite. The SPA is built with Vite, served as static files by the C# backend, and replaces the current separate gallery, image, code, and injected feedback experiences with one unified review shell.

The approved design is `~/Projects/agent-workbench/spikes/frontend-directions/direction-unified-app.html`. The real app must reproduce its product shape: one shell, a top-bar mode switcher, a shared work queue, threaded resolvable comments, and light plus Material-dark themes.

## Goals and constraints

| Area | Decision |
|---|---|
| Runtime | Static React bundle served by the C# backend. |
| Frontend root | `apps/artifact-review/frontend/`. |
| Build tool | Vite with React and TypeScript. |
| Language bar | `strict: true`, no unchecked external data, discriminated unions for UI state. |
| State | Built-in React state, reducer hooks where needed, thin typed API layer. No app-wide state library for phase one. |
| Image viewer | OpenSeadragon in simple-image mode. The parity spec has no DZI tile endpoint. |
| Region pins | `@annotorious/react` over OpenSeadragon, persisted as `image_region` threads. |
| Comments | One canonical thread model across page, image region, report block, code line, compare, and ledger views. |
| Security | The SPA never treats raw artifact HTML as trusted same-origin app UI. Active artifact content stays sandboxed or separated per backend mitigation. |
| Dependencies | Minimal dependencies only when they remove real complexity. |

## Stack and project layout

### Runtime stack

| Layer | Package | Purpose |
|---|---|---|
| Build | `vite` | Dev server, build pipeline, static output. |
| UI | `react`, `react-dom` | Component model. |
| Types | `typescript` | Strict type checking. |
| Viewer | `openseadragon` | Deep zoom style pan and zoom in simple-image mode. |
| Regions | `@annotorious/react` | Region drawing, selection, and annotation adapter. |
| Validation | `zod` | Validate API responses at the boundary. |
| Tests | `vitest`, `@testing-library/react`, `@testing-library/user-event` | Component and API-client tests. |

Do not add routing, query, state, styling, or component libraries until a real need appears. React state plus small local reducers are enough because the app has one active artifact, one mode, and a small set of server-backed collections.

### Directory layout

```text
apps/artifact-review/frontend/
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  src/
    main.tsx
    App.tsx
    api/
      artifactReviewClient.ts
      artifactReviewSchemas.ts
      artifactReviewTypes.ts
      formData.ts
    assets/
      fonts/
        ibm-plex-sans-latin-400-normal.woff2
        ibm-plex-sans-latin-500-normal.woff2
        ibm-plex-sans-latin-600-normal.woff2
        jetbrains-mono-latin-400-normal.woff2
        jetbrains-mono-latin-500-normal.woff2
        jetbrains-mono-latin-600-normal.woff2
        source-serif-4-latin-400-normal.woff2
        source-serif-4-latin-500-normal.woff2
        source-serif-4-latin-600-normal.woff2
    components/
      primitives/
        Button.tsx
        Card.tsx
        KbdHint.tsx
        Panel.tsx
        StatusPill.tsx
      shell/
        ReviewShell.tsx
        TopBar.tsx
        ModeSwitcher.tsx
        ThemeToggle.tsx
        WorkQueue.tsx
      threads/
        ThreadRail.tsx
        ThreadCard.tsx
        ThreadComposer.tsx
        ReplyList.tsx
        UploadList.tsx
      viewer/
        ArtifactViewer.tsx
        ImageViewer.tsx
        GalleryViewer.tsx
        ReportViewer.tsx
        CodeViewer.tsx
        AnchorOverlay.tsx
      modes/
        InspectorMode.tsx
        CompareMode.tsx
        LedgerMode.tsx
        VersionSpine.tsx
        ComparePane.tsx
        FeedbackLedger.tsx
    state/
      reviewState.ts
      threadState.ts
      themeState.ts
    styles/
      tokens.css
      base.css
      components.css
      modes.css
```

### Ownership seams for implementation workers

| Slice | Files | Responsibility |
|---|---|---|
| Shell | `components/shell/*`, `styles/base.css` | Top bar, mode switcher, queue, keyboard shortcuts, root layout. |
| Design tokens | `styles/tokens.css`, `src/assets/fonts/*` | Exact token port, font loading, theme toggle wiring. |
| Threads | `components/threads/*`, `state/threadState.ts` | Canonical thread rail, composer, replies, resolve behavior, uploads. |
| Viewer | `components/viewer/*` | Image, gallery, report, and code anchors sharing one thread model. |
| API client | `api/*` | Typed fetch client and runtime validation for all parity endpoints. |
| Modes | `components/modes/*` | Inspector, Compare, Ledger compositions from the approved mockup. |

## Design-token system

Tokens live in one CSS file: `src/styles/tokens.css`. Components consume variables only. Do not create one-off colors, spacing, radii, shadows, or font stacks in component styles.

### Font faces

The mockup self-hosts three font families and three weights each. The app must ship the same families from `src/assets/fonts/` and let Vite fingerprint them.

```css
@font-face{font-family:"Plex Local";src:url("../assets/fonts/ibm-plex-sans-latin-400-normal.woff2") format("woff2");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"Plex Local";src:url("../assets/fonts/ibm-plex-sans-latin-500-normal.woff2") format("woff2");font-weight:500;font-style:normal;font-display:swap}
@font-face{font-family:"Plex Local";src:url("../assets/fonts/ibm-plex-sans-latin-600-normal.woff2") format("woff2");font-weight:600;font-style:normal;font-display:swap}
@font-face{font-family:"JetBrains Local";src:url("../assets/fonts/jetbrains-mono-latin-400-normal.woff2") format("woff2");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"JetBrains Local";src:url("../assets/fonts/jetbrains-mono-latin-500-normal.woff2") format("woff2");font-weight:500;font-style:normal;font-display:swap}
@font-face{font-family:"JetBrains Local";src:url("../assets/fonts/jetbrains-mono-latin-600-normal.woff2") format("woff2");font-weight:600;font-style:normal;font-display:swap}
@font-face{font-family:"Source Serif Local";src:url("../assets/fonts/source-serif-4-latin-400-normal.woff2") format("woff2");font-weight:400;font-style:normal;font-display:swap}
@font-face{font-family:"Source Serif Local";src:url("../assets/fonts/source-serif-4-latin-500-normal.woff2") format("woff2");font-weight:500;font-style:normal;font-display:swap}
@font-face{font-family:"Source Serif Local";src:url("../assets/fonts/source-serif-4-latin-600-normal.woff2") format("woff2");font-weight:600;font-style:normal;font-display:swap}
```

### Light tokens

Port the approved `:root` block verbatim, with only font URL paths changed in the font-face declarations above.

```css
:root{
  --paper-0:oklch(98% .012 78); --paper-1:oklch(95% .014 78); --paper-2:oklch(91% .018 78); --paper-3:oklch(86% .020 78); --paper-4:oklch(76% .024 78);
  --ink-0:oklch(17% .028 64); --ink-1:oklch(27% .026 64); --ink-2:oklch(39% .024 64); --ink-3:oklch(52% .021 64);
  --accent:oklch(43% .078 34); --accent-soft:oklch(93% .035 34); --accent-rule:oklch(56% .065 34);
  --open:oklch(39% .090 38); --open-soft:oklch(94% .032 38);
  --resolved:oklch(36% .060 145); --resolved-soft:oklch(94% .030 145);
  --draft:oklch(42% .052 88); --draft-soft:oklch(95% .028 88);
  --focus:oklch(45% .090 42);
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --r1:2px; --r2:4px; --r3:7px;
  --section-height:900px; --viewer-height:calc(var(--section-height) - 132px);
  --sans:"Plex Local"; --mono:"JetBrains Local"; --serif:"Source Serif Local";
}
```

### Dark tokens

Port the approved Material-dark block verbatim. The dark palette is neutral elevated grey, not blue-black.

```css
[data-theme="dark"]{
  --paper-0:oklch(27% .006 60); --paper-1:oklch(23% .005 60); --paper-2:oklch(19% .004 60); --paper-3:oklch(36% .008 60); --paper-4:oklch(46% .010 60);
  --ink-0:oklch(94% .004 60); --ink-1:oklch(84% .005 60); --ink-2:oklch(70% .006 60); --ink-3:oklch(58% .007 60);
  --accent:oklch(72% .13 32); --accent-soft:oklch(34% .07 32); --accent-rule:oklch(66% .13 32);
  --open:oklch(75% .13 36); --open-soft:oklch(33% .07 36);
  --resolved:oklch(80% .13 152); --resolved-soft:oklch(33% .06 152);
  --draft:oklch(82% .11 92); --draft-soft:oklch(34% .06 92);
  --focus:oklch(80% .13 50);
}
```

### Token usage rules

| Token group | Use |
|---|---|
| `--paper-*` | App surface, panels, raised cards, borders, viewer stage. |
| `--ink-*` | Text hierarchy, metadata, subdued labels. |
| `--accent*` | Current mode, selected object, primary action, active tab. |
| `--open*` | Open unresolved thread state. |
| `--resolved*` | Resolved or approved state. |
| `--draft*` | Draft, in-review, held, needs-reply state. |
| `--focus` | Focus rings only. |
| `--s*` | Spacing. |
| `--r*` | Radius. |
| `--sans`, `--mono`, `--serif` | UI text, machine labels, review prose. |

### Theme toggle

The app root is `document.documentElement`. Theme state is stored in `localStorage` key `review-serve-theme` for parity with the current server pages. The toggle cycles light and dark with a sun or moon icon and keyboard shortcut `T`. It sets `data-theme="dark"` on the root for dark mode and removes it for light mode. The pre-paint script in `index.html` applies the stored value before React mounts to avoid flash.

## Component tree

### Root shell

```text
App
  ReviewShell
    TopBar
      IdentityCaption
      ModeSwitcher
      ThemeToggle
    WorkQueue
    InspectorMode | CompareMode | LedgerMode
```

The shell owns current mode, active artifact, active version pair, active thread, filters, and keyboard shortcuts. Mode content owns only local viewer detail.

### Reusable primitives

| Primitive | Purpose |
|---|---|
| `Button` | Tokenized action button with primary, quiet, and icon variants. |
| `KbdHint` | Mono keyboard hint matching the mockup `<kbd>` style. |
| `Panel` | Bordered shell region for queue, rail, pane, and context surfaces. |
| `Card` | Raised review object, thread, and fact card. |
| `StatusPill` | Status with color and non-color shape cue. |
| `QueueRow` | One artifact in the persistent work queue. |
| `GalleryTile` | One image or artifact tile in gallery contexts. |
| `VersionSpineRow` | One version in Compare mode. |
| `ThreadCard` | Thread header, anchor, replies, resolve state. |
| `ReplyList` | Chronological replies with author, time, uploads. |
| `ThreadComposer` | Body, author, file attach, post, resolve-after-send. |
| `UploadList` | Safe upload links through `/_/api/uploads/<id>`. |
| `AnchorLabel` | Human-readable page, region, block, and line anchor label. |
| `ViewerToolbar` | Shared viewer controls and keyboard hints. |
| `FactGrid` | Compact identifier, type, version, produced facts. |
| `BulkActionBar` | Ledger selected-row actions. |

Primitive count: 16.

### Shell regions

| Region | Width in mockup | Behavior |
|---|---:|---|
| Top bar | Full width, 48 px high | Identity caption, mode tabs, review progress, theme toggle. |
| Work queue | 292 px | Persistent across all modes, filters unresolved artifacts, keeps active selection. |
| Main area | Flexible | Mode-specific artifact hero. |
| Thread rail or context rail | 316 to 420 px | Shows threads or artifact context for current mode. |

### Mode switcher

Tabs are Inspector, Compare, and Ledger. Keyboard shortcuts are `1`, `2`, and `3`. Each tab uses `aria-pressed` and remains a button, not a link, because the shell preserves app state while switching modes.

### Inspector mode composition

```text
InspectorMode
  ViewerToolbar
  ArtifactViewer
    GalleryViewer | ImageViewer | ReportViewer | CodeViewer
  ThreadRail
    ThreadCard[]
    ThreadComposer
```

Inspector is the default mode for one artifact. The artifact is the hero. The right rail follows the selected anchor or shows all threads for the active `sub_path`.

### Compare mode composition

```text
CompareMode
  VersionSpine
    VersionSpineRow[]
  PairSummary
    FactGrid
  ComparePane(reference)
    ArtifactViewer
  ComparePane(candidate)
    ArtifactViewer
  ThreadRail
```

Compare shows a left version spine, two synchronized artifact panes, and a rail filtered to the pair. Threads keep their original anchor but add pair context such as `raised in v021` and `candidate still open`.

### Ledger mode composition

```text
LedgerMode
  FeedbackLedger
    LedgerFilters
    BulkActionBar
    LedgerRow[]
  ArtifactContext
    ArtifactViewer
    ThreadCard[]
    ThreadComposer
```

Ledger is the cross-artifact feedback work surface. Selecting a row opens its artifact context on the right and highlights the source anchor. Bulk actions preserve per-row anchors and call the same resolve or reply APIs as the rail.

## State model

### App state

| State | Owner | Notes |
|---|---|---|
| `mode` | `ReviewShell` | `inspector`, `compare`, or `ledger`. |
| `theme` | `themeState` | Light or dark, persisted to `review-serve-theme`. |
| `queueFilter` | `WorkQueue` with shell callback | Defaults to unresolved only. |
| `activeArtifact` | `ReviewShell` | Artifact id plus sub path and kind. |
| `activeAnchor` | Current viewer | Region, block, line, gallery tile, or page. |
| `threads` | `threadState` | Loaded through API client per artifact and sub path. |
| `uploads` | API data | Rendered as links only, never inline active content. |
| `requestState` | Each data hook | `idle`, `loading`, `ready`, `empty`, or `error`. |

### Thread domain type

The frontend treats `threads` as canonical. Legacy `comments` are read only for compatibility views if needed.

| Anchor kind | Frontend anchor | Backend mapping |
|---|---|---|
| Page | Whole artifact page or raw HTML page | `anchor_kind=page`, no `anchor_data`. |
| Image region | Annotorious FragmentSelector | `anchor_kind=image_region`, `anchor_data.selector.value=xywh=...`. |
| Code line | One line or range | `anchor_kind=code_line`, `anchor_data.line`, optional `end_line`. |
| Report block | Stable block id in rendered safe report view | Store as page thread until backend adds a first-class block anchor. Use `sub_path` and client-side block focus. |
| Gallery tile | File sub path for the tile | Use the tile file as `sub_path`; region or page anchor depends on viewer. |

Report block anchors are a UI layer over the parity model. They must not create a new backend anchor kind until the server contract changes. The implementation can encode block focus in the client URL or local view state, while the persisted thread remains page-level for that report `sub_path`.

## Viewer integration

### Artifact viewer dispatcher

`ArtifactViewer` chooses a concrete viewer from artifact metadata and URL state.

| Artifact kind | Viewer | Thread query |
|---|---|---|
| Image | `ImageViewer` | `GET /_/api/threads?artifact=<id>&sub_path=<src>`. |
| Gallery | `GalleryViewer` | Queue or tile selection decides `sub_path`; gallery root can query empty `sub_path`. |
| Report HTML | `ReportViewer` | Safe rendered report view queries the report `sub_path`. |
| Code or text | `CodeViewer` | `GET /_/api/threads?artifact=<id>&sub_path=<src>`. |
| Raw artifact page | Sandboxed frame or separate-origin link | `GET /_/api/threads?url=<page-url>` only in the feedback widget bridge. |

### OpenSeadragon

OpenSeadragon mounts inside `ImageViewer` after the container element exists. The parity server has no DZI tile generation endpoint, so use simple-image mode:

| OpenSeadragon option | Value |
|---|---|
| `tileSources` | `{ type: 'image', url: rawArtifactUrl }` |
| `showNavigator` | `true` |
| `prefixUrl` | `/_/assets/openseadragon/images/` or Vite asset path when bundled |
| Zoom reset | Fit image to stage, keyboard `Z`. |
| Lifecycle | Create on mount, destroy on unmount, update when `artifactId` or `subPath` changes. |

If a future backend adds DZI or tiled image generation, add a new typed capability flag and keep simple-image mode as the parity default.

### Annotorious

`@annotorious/react` wraps the OpenSeadragon viewer. The adapter performs three conversions:

| Direction | Conversion |
|---|---|
| Server to viewer | Thread with `anchor_kind=image_region` becomes an Annotorious annotation with id `thread-<id>` and target selector from `thread.anchor.selector`. |
| Viewer to draft | New Annotorious region creates a draft thread composer with `anchor_data={"selector": annotation.target.selector}`. |
| Resolve state to style | Formatter adds open, draft, or resolved classes from token colors and shape cues. |

The frontend must reject unsupported selectors before posting. Only `FragmentSelector` with `xywh` is sent. Never send `SvgSelector`.

### Code and text viewer

`CodeViewer` renders escaped text from the backend or a safe text endpoint. Each row has a stable `line` and optional `end_line`. Clicking a line opens or drafts a `code_line` thread. Lines with open threads use dotted left borders and `--open-soft`; resolved lines use solid borders and `--resolved-soft`.

Invalid bytes are handled by the backend parity behavior. The frontend treats code as text, not HTML.

### Report viewer

`ReportViewer` renders trusted, sanitized report blocks generated by the backend SPA route, not arbitrary raw artifact HTML. Block anchors are focus targets in the SPA. The persisted server thread remains page-level or code-line until the backend contract grows a `block` anchor.

### Raw HTML and publish safety

The backend parity spec holds `POST /_/api/publish` because same-origin active content would be able to script unauthenticated review APIs. The SPA must preserve that boundary:

1. Do not mount React inside raw artifact HTML.
2. Do not fetch raw HTML and inject it with `dangerouslySetInnerHTML`.
3. Show raw active artifacts in a sandboxed iframe without same-origin script privileges, or link to a separate origin or port if the backend provides one.
4. Keep review UI APIs on the app origin and raw active content unable to script that origin.
5. Treat upload links as downloads or safe inline types exactly as the backend headers specify.

## API client

### Client shape

`artifactReviewClient.ts` exposes small functions, not a generated service object. Each function validates JSON with zod before returning typed data. Non-JSON responses return bytes, text, or `Response` as appropriate.

Every request returns a discriminated request state to the UI:

| State | Meaning |
|---|---|
| `idle` | Not requested yet. |
| `loading` | Request in flight. |
| `ready` | Data loaded and non-empty where applicable. |
| `empty` | Request succeeded with no rows. |
| `error` | HTTP, network, validation, or parse failure with a display-safe message. |

### Endpoint coverage

| Function | Method and path | Request | Response type | UI users |
|---|---|---|---|---|
| `getRootIndex()` | `GET /` | None | HTML text or response | Health and optional landing. |
| `getSettings()` | `GET /_/api/settings` | None | `Settings` | Author default, feature flags, theme parity. |
| `getUpload(id)` | `GET /_/api/uploads/<id>` | Upload id | `Response` bytes | Upload links and previews for safe MIME only. |
| `getThreadsByArtifact(input)` | `GET /_/api/threads?artifact=<id>&sub_path=<path>` | Artifact id and sub path | `ThreadList` | Inspector, Compare, Ledger context. |
| `getThreadsByUrl(url)` | `GET /_/api/threads?url=<page-url>` | Static page URL | `ThreadList` | Raw page feedback bridge. |
| `createThread(input)` | `POST /_/api/threads` | Multipart artifact or url, body, author, anchor, files | `CreateThreadResponse` | New page, region, line, and report comments. |
| `createReply(input)` | `POST /_/api/threads/<id>/replies` | Multipart body, author, files | `CreateReplyResponse` | Thread composer replies. |
| `setThreadResolved(id, resolved)` | `POST /_/api/threads/<id>/resolve` | Optional JSON `{ resolved }` | `ResolveThreadResponse` | Resolve and reopen controls. |
| `toggleThreadResolved(id)` | `POST /_/api/threads/<id>/resolve` | Empty body | `ResolveThreadResponse` | Keyboard shortcut `R`. |
| `getComments(input)` | `GET /_/api/comments?...` | Artifact or url | `CommentList` | Legacy compatibility only. |
| `createComment(input)` | `POST /_/api/comments` | Multipart page comment | `CreateCommentResponse` | Legacy compatibility only. |
| `getReviewPageUrl(input)` | `GET /_/review?...` | URL builder only | URL string | Backward-compatible open-in-review links. |
| `getArtifactBytes(url)` | `GET /<project>/<subdir>/<rel>` | Static artifact URL | `Response` | Image source, safe text source, download. |
| `getAssetBytes(rel)` | `GET /_/assets/<rel>` | Asset path | `Response` | OpenSeadragon images only if not bundled. |
| `getFeedback(artifact)` | CLI parity, if exposed through backend later | Artifact id | Feedback JSON | Ledger source only when a JSON endpoint exists. |

`POST /_/api/publish` is not implemented in the current parity surface. The client must not include a publish function until the backend ships active-content mitigation and tests.

### Core TypeScript types

Type names should mirror domain nouns and backend payload names:

| Type | Notes |
|---|---|
| `ArtifactId` | String alias for `<project>/<subdir>` or custom artifact id. |
| `AnchorKind` | Union: `page`, `image_region`, `code_line`. |
| `ImageRegionAnchor` | Fragment selector with `xywh` value. |
| `CodeLineAnchor` | Positive `line`, optional `end_line`. |
| `Thread` | Backend thread with parsed `anchor`. |
| `Reply` | Backend reply with uploads. |
| `Upload` | Backend upload metadata. |
| `LegacyComment` | Deprecated flat page-comment shape. |
| `Settings` | String dictionary with known keys `schema_version`, `author`, `bd_mirror`. |
| `ReviewRequestState<T>` | Discriminated UI load state. |
| `ArtifactQueueRow` | UI-derived queue row from artifact index and thread summaries. |
| `LedgerRow` | UI-derived cross-artifact thread row. |

External JSON is `unknown` until zod validates it. Do not use `any`, unchecked casts, or non-null assertions for API data.

### Loading, empty, and error UX

| Area | Loading | Empty | Error |
|---|---|---|---|
| Work queue | Skeleton rows with subdued borders. | Empty panel: `No artifacts need review`. | Inline retry card, queue remains mounted. |
| Viewer | Center spinner and file name. | Empty gallery tile. | Error panel with status and safe message. |
| Thread rail | Rail skeleton cards. | Composer plus `No threads yet`. | Retry card, composer disabled. |
| Ledger | Table skeleton rows. | `No unresolved feedback`. | Error row with retry. |
| Upload | Attachment progress row. | None. | Per-file failure, do not drop comment draft. |

## User journey

1. User opens the app at the backend SPA route.
2. The pre-paint script applies `review-serve-theme`; React mounts the unified shell.
3. `WorkQueue` loads artifacts and thread summaries, defaulting to unresolved items first.
4. User opens an artifact in Inspector.
5. For images, OpenSeadragon shows the image and Annotorious renders region pins. For reports or code, the matching viewer renders block or line anchors.
6. User zooms, selects a region or line, writes a comment, attaches safe files if needed, and posts a thread.
7. The thread appears in the rail, the anchor gets an open visual marker, and the queue open count updates.
8. User replies or resolves. Resolve calls `POST /_/api/threads/<id>/resolve` and updates the same thread object everywhere.
9. User switches to Compare with `2`; the same artifact context appears in paired panes with version history.
10. User switches to Ledger with `3`; all unresolved work becomes table rows, and selecting a row opens its artifact context.
11. User finishes when queue and ledger have no unresolved work.

Chrome stays recessive: low-contrast panel surfaces, compact controls, and persistent context. The artifact stage, selected row, and active thread receive the strongest accent treatment.

## Accessibility

| Requirement | Design response |
|---|---|
| Keyboard access | `1`, `2`, `3` for modes; `T` for theme; `J` and `K` for next and previous; `R` for resolve; `C` for comment; `Z` for fit. All shortcuts are ignored while typing in fields. |
| Focus | Every interactive element uses `:focus-visible` with `--focus`, 2 px outline, and offset. |
| Labels | Icon buttons have `aria-label`; mode switcher uses `aria-label="Mode switcher"`; rows expose artifact names and status. |
| Status without color | Open uses dotted borders, resolved uses solid borders, draft or held uses double borders. Icons and text labels remain visible in grayscale. |
| Contrast | OKLCH token pairs must be checked in both themes against WCAG AA for body text and UI labels. |
| Motion | Smooth scroll from the mockup should honor `prefers-reduced-motion`. |
| Touch targets | Compact controls should keep at least 30 px height from the mockup; primary actions should exceed that where space allows. |
| Screen readers | Thread updates announce through a polite live region after post, reply, or resolve. |

## Build seam

### Vite output

Vite builds the frontend from:

```text
apps/artifact-review/frontend/
```

Default output:

```text
apps/artifact-review/frontend/dist/
```

The C# backend build copies that directory into its static web root during publish. The backend serves the SPA assets under a reserved app prefix that cannot collide with pushed artifact names:

```text
/_/app/
```

Recommended mapping:

| Request | Backend behavior |
|---|---|
| `GET /_/app/` | Return SPA `index.html`. |
| `GET /_/app/assets/<file>` | Return Vite fingerprinted assets with long cache headers. |
| `GET /_/app/<spa-route>` | Return SPA `index.html`. |
| `GET /_/api/*` | API routes, never SPA fallback. |
| `GET /_/assets/*` | Legacy vendored assets for parity, or redirect to bundled assets where safe. |
| `GET /<project>/<subdir>/*` | Raw static artifact serving, not SPA fallback. |

The root `/` can continue to serve the root index for parity. It may link to `/_/app/` as the unified review app.

### Dev server proxy

Vite dev server runs from `apps/artifact-review/frontend/` and proxies backend routes:

| Dev path | Proxy target |
|---|---|
| `/_/api/*` | C# backend on `http://127.0.0.1:9099`. |
| `/_/assets/*` | C# backend for parity assets not yet bundled. |
| `/_/review*` | C# backend for backward-compatible pages. |
| `/<project>/<subdir>/*` | C# backend static artifact route. |

The dev app itself is `http://127.0.0.1:<vite-port>/_/app/`. Use same-origin-like paths in the client so production and dev differ only by Vite proxy.

## Implementation slices

| Slice | Deliverable | Success criteria |
|---|---|---|
| Token port | `tokens.css`, font assets, theme state | The app matches mockup light and dark colors, fonts, spacing, radii, and focus rings. |
| Shell | `ReviewShell`, `TopBar`, `WorkQueue` | Mode tabs, keyboard hints, queue, and theme toggle work without viewer dependencies. |
| API client | `api/*` | Every parity endpoint has a typed function, zod validation, and error mapping. |
| Thread system | `ThreadRail`, `ThreadCard`, `ThreadComposer` | Create, reply, resolve, reopen, uploads, and empty/error states work for page threads. |
| Image viewer | `ImageViewer`, `AnchorOverlay` | OpenSeadragon simple image mode and Annotorious region pins round-trip to backend threads. |
| Text viewers | `ReportViewer`, `CodeViewer` | Escaped code lines and safe report blocks share the same thread composer and resolve model. |
| Compare | `CompareMode`, `VersionSpine`, `ComparePane` | Two panes share pair context and thread rail filtering. |
| Ledger | `LedgerMode`, `FeedbackLedger`, `ArtifactContext` | Cross-artifact rows drive context viewer and bulk resolve. |
| Build | Vite config and C# static file mapping | `dist/` is served at `/_/app/` and dev proxy reaches backend APIs. |

## Open risks

| Risk | Mitigation |
|---|---|
| No DZI tile endpoint exists. | Use OpenSeadragon simple-image mode for parity; treat tiles as future backend capability. |
| Report block anchors are not a backend anchor kind. | Persist page-level threads for report `sub_path` and keep block focus client-side until the contract changes. |
| Raw active HTML can script same-origin APIs if embedded unsafely. | Sandbox or separate active artifacts. Never inject raw HTML into React. |
| Ledger needs artifact summaries not listed as a parity JSON endpoint. | Derive from thread queries and artifact index data exposed by the backend; if missing, add a read-only summary endpoint in the backend architecture phase. |
| Theme drift from one-off CSS. | Enforce token-only component styles and review for raw color literals outside `tokens.css`. |
