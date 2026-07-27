# Artifact Server Data and Trust Surfaces

## Gap 2: Versioning, history, and provenance

**Research question:** How should the UI represent artifact versions, prior-version annotations, changed coordinates, provenance metadata, and resolved history without becoming an asset library?

**Position:** Republishing the same artifact id creates a new immutable version. The newest version becomes the default view, while every comment, pin, region, resolve event, and export remains attached to the version where it was created. Prior-version threads are not carried forward as live annotations, because image pixels, layout, dimensions, and report anchors may have changed. They are marked stale on newer versions and remain fully usable only when viewing their original version.

**UI behavior:**

- The top bar shows `vN` beside the artifact title. Current versions use a neutral badge such as `v4 current`.
- Older versions show a persistent, compact banner below the top bar: `Viewing v3. Current is v4. Comments here may reference old pixels.` The banner includes `Open current version`.
- A version switcher in the metadata drawer lists versions in reverse chronological order with generated time, publisher label, source run id, artifact hash, comment count, open stale count, and done state.
- On the current version, stale prior-version threads appear in a collapsed `Previous version comments` section below current threads. They show version, status, thread number, excerpt, and a `View on vN` action.
- Stale prior-version pins do not appear on the current canvas by default. Selecting a stale thread opens its original version, then selects and centers the original pin or region.
- Resolved prior-version threads stay collapsed by default. Unresolved prior-version threads remain visible in counts as `2 stale open` so replacement does not silently hide unfinished feedback.
- Deep links include both artifact id and version id. A link to an older version opens that exact version with the older-version banner, not the current version.
- The provenance drawer is quiet by default and includes publisher, generated timestamp, source command or run id, input refs, artifact hash, dimensions or report id, storage path, and feedback schema version.

**Data and contract implication:**

- `artifactId` is the stable logical object.
- `artifactVersionId` is immutable and required on every thread, annotation, reply, resolve event, deep link, and export record.
- Annotation coordinates are normalized to the version dimensions or report anchor map that existed at creation time.
- The API exposes current version, full version list, and per-version review state. It also exposes stale open counts on the current artifact summary.
- Version records are append-only. Republishing never mutates an existing version or rewrites existing coordinates.

**Failure mode if done wrong:** Carrying pins forward as if they still point to the same visual evidence will make reviewers trust incorrect coordinates. Hiding old unresolved comments will make republishing look like progress while losing real feedback. Treating history like an asset library will bury the current review task under storage management.

**Rules:**

- Never auto-migrate annotation geometry across versions.
- Always make old-version viewing visually obvious.
- Show stale unresolved work on the current version, but do not render it as current canvas truth.
- Keep history in the metadata drawer and stale thread section, not in a separate library page.
- Export must preserve the version id for every review object.

## Gap 3: Export, raw artifact, and feedback JSON

**Research question:** What is the exact UX contract for `Copy feedback JSON`, raw artifact access, download, export success, export failure, and downstream handoff?

**Position:** Export is a review handoff, not a separate reporting product. The reviewer can take away four things: the raw artifact, feedback JSON, a shareable deep link, and a short human summary. All four are generated from the same server-side review state so the UI and agent-facing JSON cannot drift.

**UI behavior:**

- Primary completion area shows `Copy feedback JSON` when the artifact has review state worth handing back, especially after comments or `Mark artifact done`.
- Secondary actions live in the top bar `Actions` menu and command palette: `Copy feedback JSON`, `Download feedback JSON`, `Copy review summary`, `Copy link to current view`, `Open raw artifact`, and `Download raw artifact`.
- The canvas toolbar never carries export controls. It remains for viewing and annotation.
- The metadata drawer has a `Raw artifact` row with `Open`, `Download`, file size, MIME type, and hash.
- `Copy link to current view` includes artifact id, version id, selected thread id when present, and viewport state when useful. It never changes the selected filter for the recipient unless the filter is encoded.
- Export success uses a short toast: `Feedback JSON copied`. Download success relies on browser download affordance.
- Clipboard failure leaves the JSON in a modal text area with `Select all` and `Download instead`.
- Export failure is persistent and local to the action: `Could not generate feedback JSON. Retry`. If stale state caused it, the action becomes `Refresh and retry`.
- Batch export is deferred. Gallery-level `Copy feedback JSON` should not ship until the backend can guarantee deterministic ordering and per-artifact version coverage.

**Data and contract implication:**

- The UI renders review state from a canonical DTO, for example `ReviewState`.
- Feedback JSON is produced by the server from the same canonical DTO, not reconstructed ad hoc from React component state.
- The feedback JSON includes `feedbackSchemaVersion`, `artifactId`, `artifactVersionId`, `artifactVersionNumber`, artifact title, artifact hash, provenance, generated timestamp, done state, export timestamp, and ordered threads.
- Each thread in JSON includes the same fields the UI shows: thread id, number, status, stale flag, version id, location type, normalized coordinates or report anchor, body, replies, timestamps, edited markers if present, resolved state, and deep link.
- Filters never change export content. Export includes all persisted review objects for the selected artifact version plus stale prior-version references required to explain open stale work.
- `Copy review summary` is generated from the same DTO and includes counts, open thread excerpts, stale open count, and the artifact deep link.
- JSON schema version is visible in the export popover as `Feedback JSON v1` so agents can validate compatibility.

**Failure mode if done wrong:** If the UI shows one set of comments while exported JSON contains another, agents will act on invisible or outdated feedback. If export controls sit on the canvas, they compete with review actions. If raw artifact links are hidden, reviewers will use browser workarounds and lose provenance.

**Rules:**

- One canonical server DTO feeds UI, summary, and feedback JSON.
- Export all persisted review state, not only the current filter.
- Keep export actions in completion, Actions, metadata, and command palette surfaces, not on the viewer toolbar.
- Always include artifact version and feedback schema version.
- Clipboard failure must provide a non-clipboard recovery path.

## Gap 8: Trust model and no-auth UX

**Research question:** How should the trusted-tailnet, no-auth model be visible enough to prevent wrong assumptions without adding account chrome?

**Position:** The interface should be honest that there is no sign-in, but it should not make security the product. Trust copy lives at sharing, raw content, export, and destructive surfaces. The app must never imply user accounts, permissions, or identity-backed ownership that do not exist.

**UI behavior:**

- The share popover states: `Anyone on the tailnet with this link can view and comment. No sign-in is required.`
- The metadata drawer has a compact `Access` row: `Private tailnet, no sign-in` with details in a popover.
- First-run and empty states do not mention auth. Review flow should stay artifact-first.
- No lock icons, shield icons, owner avatars, role labels, permission menus, `Only you`, `Private to you`, or `Signed in as` copy appear anywhere.
- Raw HTML report access uses precise content copy: `Raw report may run active content. Open only if you trust this artifact source.` This is about active content, not account security.
- Save and resolve errors never say `permission denied` unless the backend actually rejects the action for non-identity reasons such as read-only storage. Preferred copy is action-specific, for example `Could not resolve thread. Retry`.
- Comment metadata may show a simple configured author label if the publisher supplies one, but it is display text only and never a permission boundary.

**Design consequence:** No destructive action may rely on identity. A resolve action is a reversible review state change, not proof that a specific authenticated reviewer approved something. Delete should not be part of the normal reviewer UI. If delete exists for cleanup, it must be confirm-gated, tombstoned, reversible where storage allows, and available by artifact or thread state rather than by ownership. Reopen must be available for any resolved thread because there is no trusted identity model for `who may reopen`.

**Data and contract implication:**

- Comment and event records may carry `authorLabel`, `clientLabel`, or `publisherLabel`, but no authorization decisions depend on those fields.
- The API must not expose role concepts the UI cannot honestly enforce.
- Audit history should record state changes with timestamps and optional labels for debugging, not for permission claims.
- Delete endpoints, if implemented, require confirmation tokens or explicit irreversible flags, not user identity checks.

**Failure mode if done wrong:** Fake account chrome will train reviewers to believe comments are private or permissioned when they are not. Identity-based delete or resolve behavior will create a safety illusion that fails the moment another tailnet user opens the link. Alarmist banners will steal attention from the artifact and make the deliberate tailnet model look like an error.

**Rules:**

- Say `Private tailnet, no sign-in`, not `secure`, `locked`, or `only you`.
- Put trust copy where sharing, raw content, export, or deletion happens.
- Do not add auth as the answer to this design problem.
- Do not use identity as a safety mechanism.
- Prefer reversible state changes and tombstones over permission theatre.

## Gap 9: Backend and API contract as UX

**Research question:** Which backend state and mutation guarantees must the frontend design depend on, and how are violations shown?

**Position:** The API must behave like part of the interface. The frontend can be fast and calm only if the C#/.NET backend guarantees stable ids, idempotent writes, canonical errors, ordered reads, version-aware conflicts, and retry-safe mutation recovery.

**UI behavior:**

- Comments and resolves update optimistically within 100 ms, then settle when the server returns the canonical object.
- Pending objects show inline `Saving` state and cannot be resolved until committed.
- A network drop mid-comment preserves composer text, pending annotation geometry, and the idempotency key. The UI shows `Not saved. Reconnect to retry` with `Retry` and `Copy text`.
- If the server saved the comment but the response was lost, retrying with the same idempotency key returns the saved comment instead of creating a duplicate.
- Conflict copy is specific: `This thread changed on the server. Review the latest version before saving.` The UI refreshes the thread and keeps the user's draft separately.
- Pagination never changes the apparent order while the reviewer is reading. Newly arrived items appear after refresh or in a small `New activity` prompt, not by jumping the list.
- Errors attach to the object being acted on: composer, thread card, export popover, or artifact shell. Global toasts are backup, not the main error surface.

**UX-driven API requirements:**

- Stable ids: artifact ids, version ids, thread ids, reply ids, annotation ids, export ids, and event ids are stable across reloads and suitable for React keys and deep links.
- Idempotent posts: comment, reply, resolve, reopen, mark done, and export requests accept an `Idempotency-Key` and return the existing result for duplicate keys.
- Canonical error envelope: every non-2xx response returns `{ error: { code, message, retryable, correlationId, fieldErrors, conflict } }`, with absent optional fields allowed.
- Ordered thread reads: thread lists return server-defined order, stable thread numbers, and explicit sort keys. Replies are chronological inside a thread.
- Version-aware writes: every mutation includes `artifactVersionId` and, for edits or resolves, an entity version or ETag. Stale writes return a conflict envelope with the latest object.
- Server timestamps: the server assigns creation, update, resolution, and export timestamps in RFC 3339 UTC. The client may show local optimistic time only until the server responds.
- Cursor pagination: gallery artifacts and long thread lists use opaque cursors with stable sort. Counts for open, resolved, stale open, and done are available without loading every page.
- Mutation response shape: successful mutations return the canonical updated object plus affected counts so the UI does not guess.
- Export status: feedback JSON generation has a clear success or failure state with schema version, artifact version id, generated time, and retryable failure code.
- Health and reconnect: the client can distinguish offline, backend unreachable, artifact missing, version missing, and storage unavailable.

**Failure mode if done wrong:** Without idempotency, a dropped response can create duplicate comments. Without stable ids and ordering, selection, deep links, and screen-reader references break. Without canonical errors, each component invents copy and recovery, making the app feel random under stress.

**Rules:**

- Treat API response shapes as design-system primitives.
- Never let the client infer persisted truth after a mutation.
- Use idempotency for every user-visible write.
- Use one error envelope everywhere.
- Preserve drafts and geometry across network failures.

## Gap 18: Print and offline portability

**Research question:** Are print, PDF, saved-page, offline review packet, or portable feedback outputs in scope, explicitly out of scope, or deferred?

**Position:** Print, PDF, saved-page fidelity, and offline review packets are out of scope for the first rewrite. The portable output is feedback JSON plus raw artifact download and deep links. This is enough for the agent workflow and avoids spending design and engineering effort on a second static review product.

**UI behavior:**

- The app does not include `Print`, `Export PDF`, or `Save offline packet` actions in the first build.
- Browser print is not blocked, but it is not a supported review surface. If styled at all, print CSS should reduce the page to title, artifact metadata, and a plain thread list.
- The supported portability path is explicit: `Download raw artifact`, `Download feedback JSON`, `Copy review summary`, and `Copy link to current view`.
- HTML reports remain online viewer content. Raw report download is allowed, but offline script execution is not framed as a supported review path.
- If a reviewer needs a human-readable record, `Copy review summary` supplies a compact Markdown summary generated from the canonical review DTO.

**Data and contract implication:**

- No first-build schema is needed for PDF layout, static HTML bundles, asset manifests, offline caches, or service-worker synchronization.
- Feedback JSON must carry enough version and provenance data to be portable between the UI and the agent without a printed packet.
- Raw artifact downloads include content type, file name, hash, and version id through headers or sidecar metadata in the JSON.
- Deep links are tailnet links and are not promised to work outside the private network.

**Revisit trigger:** Revisit offline portability only if one of these becomes true: reviews must be archived for humans outside the tailnet, regulatory or customer evidence requires static snapshots, reviewers need to work during known network outages, or automated agents need a self-contained bundle rather than JSON plus raw artifact references. The first acceptable future shape would be a static HTML evidence bundle containing thumbnail or image, metadata, ordered comments, normalized annotation coordinates, and the exact feedback JSON, all tied to artifact version ids.

**Failure mode if done wrong:** Building PDF or offline packets now will add layout, storage, asset rewriting, sandbox, and stale-version complexity before the core review loop is stable. A weak printout can also imply that a static artifact is authoritative when the real source of truth is versioned server state plus feedback JSON.

**Rules:**

- Do not ship print, PDF, saved-page, or offline packet controls in the first build.
- Support portability through raw artifact, feedback JSON, summary, and deep link.
- State that deep links require tailnet access.
- Keep feedback JSON as the machine-readable portable record.
- Revisit only when an external archive, compliance, outage, or bundle requirement appears.
