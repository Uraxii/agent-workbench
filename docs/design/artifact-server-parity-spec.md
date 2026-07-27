# Artifact review server parity specification

This is the ground truth for rewriting the current artifact review server from `review-serve.py` to a C#/.NET backend and React/TypeScript frontend. It describes existing behavior only. It does not design the replacement.

Primary sources:

| Source | Relevant lines |
|---|---|
| `.claude/skills/artifact-serve/scripts/review-serve.py` | 52-153 constants, 219-284 schema, 522-604 artifact resolution, 707-779 anchor validation, 846-1133 store and feedback JSON, 1139-1280 bd mirror, 2334-2896 HTTP routes, 3078-3483 CLI verbs |
| `~/.claude/skills/artifact-serve/SKILL.md` | 18-29 viewer URL rule, 31-69 deploy and Tailscale warning, 71-93 push and feedback contract, 95-103 storage and security notes |
| `~/.claude/skills/artifact-serve/REFERENCE.md` | 5-42 storage, 43-57 verbs, 84-116 legacy comments API, 117-152 legacy schema, 154-180 behavior and caveats |
| `.claude/skills/artifact-serve/container/Containerfile` | 1 base image digest, 14-15 healthcheck, 17 entrypoint |
| `.claude/skills/artifact-serve/container/review-serve.container` | 19-21 bind and publish port, 23-37 narrow mounts, 39-49 hardening |
| `docker-compose.yml` | 71-106 portable compose review-serve service |
| `.claude/skills/agent-workbench/cli/deploy.py` | 188-227 build, install, start, healthcheck, 258-268 safe down behavior |
| `tests/test_review_serve_bd_mirror.py` | 20-51 bd board resolution and missing CLI behavior |
| `tests/test_review_serve_http.py` | 36-260 HTTP behavior coverage |
| `tests/test_review_serve_core.py` | 23-248 schema, anchors, store, feedback, path safety |
| Board ticket `agent-workbench-wxh` | held publish endpoint and stored-XSS finding |
| Board ticket `agent-workbench-h5u` | closed SSRF guard pattern |

## 1. HTTP API surface

### 1.1 Reserved namespace

`/_/` is reserved for the review app. `NAME_RE` requires project and subdir names to start with `[a-z0-9]`, so a pushed project cannot be named `_` and cannot collide with `/_/...` routes. Unknown `/_/...` paths fall through to static serving under `/tmp/claude-artifacts/_/...` and normally 404.

### 1.2 Endpoint table

| Method | Path | Query params | Request body | Response | Status codes | Side effects |
|---|---|---|---|---|---|---|
| GET | `/` | none | none | Root index HTML. Contains `review-serve` and a tile grid of staged projects. | 200 when `index.html` exists after `regenerate_index`; normal static 404 otherwise. Tests treat this as the health route because no `/health` route exists. | None. |
| GET | `/_/assets/<rel>` | none | none | Vendored static asset bytes from `ASSETS_ROOT`: OpenSeadragon, Annotorious, CSS, images. `Content-Type` from extension. | 200, 404. | None. Traversal guarded by `resolve()` plus `is_relative_to(ASSETS_ROOT)`. |
| GET | `/_/api/settings` | none | none | JSON object of every row in `setting`: `{ "schema_version": "2", "author": "...", "bd_mirror": "1" }` when present. | 200, 500 `{error}`. | Opens DB, creates or migrates schema if needed. |
| GET | `/_/api/uploads/<id>` | path integer id | none | Raw upload bytes. Headers: `Content-Type`, `Content-Length`, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline` for image/png, image/jpeg, image/webp, image/gif, image/bmp, application/pdf, text/plain, else `attachment`. | 200, 404 for bad or absent id, 410 when DB row exists but file missing, 500 for DB error. | None. |
| GET | `/_/api/threads` | Either `artifact=<id>&sub_path=<path>` or `url=<page-url>`. `sub_path` defaults to empty. | none | `{ "artifact_id": string, "sub_path": string, "threads": Thread[] }`. Thread shape below. | 200, 404 `{error:"could not resolve artifact"}`, 500 `{error:"db: ..."}`. | None. |
| POST | `/_/api/threads` | none | `multipart/form-data`: `artifact` plus optional `sub_path`, or `url`; `anchor_kind` default `page`; optional `anchor_data`; required `body`; optional `author`; optional multi file field `files`. | 201 `{ "thread_id": number, "reply_id": number, "artifact_id": string, "sub_path": string, "anchor_kind": string, "uploads": Upload[] }`. | 201, 400 for non-multipart, bad multipart, no target, missing or long body, invalid anchor, disallowed upload; 411 missing or invalid `Content-Length`; 413 oversized request or file; 500 create failure. | Inserts one `thread`, one opening `reply`, optional `upload` rows and files. If bd mirror enabled, best-effort creates a bd ticket and stores `bd_ticket`. |
| POST | `/_/api/threads/<id>/replies` | path integer thread id | `multipart/form-data`: required `body`; optional `author`; optional multi file field `files`. | 201 `{ "reply_id": number, "thread_id": number, "uploads": Upload[] }`. | 201, 400, 404 for missing thread, 411, 413, 500. | Inserts `reply`, optional uploads. If the thread has `bd_ticket`, best-effort appends a bd comment. |
| POST | `/_/api/threads/<id>/resolve` | path integer thread id | JSON body optional. Empty body toggles. `{ "resolved": true|false }` sets explicit state. Any truthy or falsy value is coerced with `bool(...)`. | 200 `{ "id": number, "resolved": boolean }`. | 200, 400 for invalid JSON, 404 for missing thread, 411, 413. | Updates `thread.resolved`. If mirrored, best-effort `bd close` when true, `bd reopen` when false. |
| GET | `/_/api/comments` | Either `artifact=<id>&sub_path=<path>` or `url=<page-url>`. | none | Legacy flattened page-comment shim: `{ "artifact_id": string, "sub_path": string, "comments": Comment[] }`. Only page-anchor threads are included. | 200, 404, 500. | None. |
| POST | `/_/api/comments` | none | Legacy multipart shim: `artifact` plus optional `sub_path`, or `url`; required `body`; optional `author`; optional `files`. Always creates a page anchor. | 201 `{ "id": reply_id, "thread_id": thread_id, "artifact_id": string, "sub_path": string }`. | 201, 400, 411, 413, 500. | Creates a page-level thread and opening reply. Mirrors like `POST /_/api/threads`. |
| GET | `/_/review` | Required `artifact=<id>`. Optional `view=image|code`, `src=<rel>`, `path=<rel-dir>`. | none | HTML review page. No `view`: gallery. `view=image`: OpenSeadragon plus Annotorious image viewer. `view=code`: per-line text/code viewer. | 200, 400 `artifact required`, 404 when `view` is image or code and `src` cannot be resolved under the staged root. | None. |
| GET | `/<project>/<subdir>/<rel>` | static URL path | none | Static artifact bytes from `/tmp/claude-artifacts`. `text/html` responses are rewritten to inject the page feedback widget before `</body>` and omit `Content-Length`. Other files stream normally. | Standard `SimpleHTTPRequestHandler` statuses, usually 200, 301 for directory redirect, 404. | None. HTML injection adds client-side calls to settings, threads, uploads. |
| GET | `/<project>/<subdir>/<dir>/` | static URL path to directory without `index.html` | none | Themed directory gallery HTML. Direct child dirs link to their own directory URL. Image files link to `/_/review?...&view=image`. Code extensions link to `/_/review?...&view=code`. Other files link raw. | 200. Static handler statuses when an `index.html` exists or path not a directory. | None. |
| POST | `/_/api/publish` | held, not deployed | held | Held under `agent-workbench-wxh`. It is not present in the current deployed `review-serve.py` route table. | Not part of current parity surface. | Do not implement as a same-origin raw active-content write endpoint without mitigation. See security section. |

### 1.3 JSON schemas

Thread:

```json
{
  "id": 123,
  "sub_path": "relative/path.png",
  "anchor_kind": "page | image_region | code_line",
  "anchor": null,
  "resolved": false,
  "author": "name or null",
  "created_at": 1720000000,
  "created_at_iso": "2024-07-03T09:46:40Z",
  "bd_ticket": "agent-workbench-abc or null",
  "replies": []
}
```

For `image_region`, `anchor` is:

```json
{
  "selector": {
    "type": "FragmentSelector",
    "value": "xywh=pixel:1,2,3,4",
    "conformsTo": "optional string"
  }
}
```

For `code_line`, `anchor` is:

```json
{ "line": 5, "end_line": 8 }
```

Reply:

```json
{
  "id": 456,
  "body": "comment text",
  "author": "name or null",
  "created_at": 1720000000,
  "created_at_iso": "2024-07-03T09:46:40Z",
  "uploads": []
}
```

Upload:

```json
{
  "id": 789,
  "filename": "safe-name.png",
  "stored_path": "~/.local/share/claude-artifacts/uploads/<reply-id>/safe-name.png",
  "mime": "image/png or null",
  "size": 12345,
  "created_at": 1720000000,
  "created_at_iso": "2024-07-03T09:46:40Z"
}
```

Legacy Comment:

```json
{
  "id": 456,
  "thread_id": 123,
  "sub_path": "relative/path.html",
  "body": "comment text",
  "author": "name or null",
  "created_at": 1720000000,
  "created_at_iso": "2024-07-03T09:46:40Z",
  "resolved": false,
  "uploads": []
}
```

### 1.4 Request limits and validation

| Item | Current rule |
|---|---|
| Request body | `Content-Length` required, integer, non-negative, max 500 MB. |
| Comment body | Required after `.strip()`, max 20,000 chars. Stored stripped. |
| Author | Optional after `.strip()`. If absent, server uses setting `author` when present. CLI `name` caps to 80 chars, but HTTP author has no explicit length cap. |
| Upload size | Max 100 MB per file. |
| Upload filename | Basename only, non `[A-Za-z0-9._-]` chars become `_`, leading dots stripped, max 200 chars, collision suffix `-1`, `-2`, etc. |
| Upload allowlist | `.png .jpg .jpeg .webp .gif .bmp .tif .tiff .pdf .txt .md .log .csv .json .yaml .yml .toml .zip .tar .gz .7z .fig .psd .xcf .sketch .mp4 .webm .mov` |
| Upload blocklist | `.exe .dll .sh .bash .zsh .bat .cmd .ps1 .js .mjs .html .htm .xhtml .svg .com` |
| Anchor JSON | Max 8 KiB, JSON object for non-page anchors. Unknown extra keys are dropped. |
| `page` anchor | `anchor_data` must be absent or blank. |
| `image_region` anchor | Must contain selector object with `type: "FragmentSelector"` and `value` matching `xywh=(pixel:|percent:)?n,n,n,n`. `SvgSelector` and all other selector types rejected. |
| `code_line` anchor | `line` integer >= 1. Optional `end_line` integer >= `line`. Booleans rejected. |

## 2. Artifact resolution and staging

### 2.1 Names and IDs

| Value | Rule |
|---|---|
| Project | Required for CLI push and clean. Must match `^[a-z0-9][a-z0-9_-]*$`. |
| Subdir | Defaults to source basename, or `--as`. Same regex. |
| Artifact ID | Defaults to `<project>/<subdir>`. `--id` must be one or two path segments, each matching the same regex. This is stricter than the older reference doc. |

### 2.2 Staging layout

```text
/tmp/claude-artifacts/
  .serve.pid
  .serve.port
  .serve.log
  index.html
  <project>/
    <subdir>  symlink to the pushed source
```

`push` preserves the literal expanded absolute source path with `Path(args.src).expanduser().absolute()`. It does not call `.resolve()`, so it does not dereference intermediate symlinks. The staged entry is always a relative symlink from `/tmp/claude-artifacts/<project>/<subdir>` to the source.

CLI `push` output shape:

```text
symlink /tmp/claude-artifacts/<project>/<subdir> → <relative-target>
artifact_id: <artifact-id>
```

The durable `artifact_index` row is upserted on `(project, subdir)` with `artifact_id`, `src_path`, and `last_pushed`.

### 2.3 URL to artifact resolution

Static URL form is `/<project>/<subdir>/<rest...>`.

Resolution steps:

1. Split the URL path.
2. If fewer than two segments, return no artifact.
3. Validate project and subdir with `NAME_RE`.
4. Look up `(project, subdir)` in `artifact_index`.
5. If found, use stored `artifact_id`; otherwise fallback to `<project>/<subdir>`.
6. `sub_path` is all remaining path segments joined with `/`.

`/_/review` image and code routes resolve with `_artifact_location(artifact_id)` and `staged_source_path(artifact_id, rel)`. The final path is `(root / rel).resolve()` and must be both under the staged root and a file, or the route returns 404.

### 2.4 Staging footguns that parity must preserve or deliberately fix with tests

| Footgun | Current behavior |
|---|---|
| Self-referencing symlink destruction | `push` deletes the destination entry before creating the new symlink. If the source is the destination or inside a staging path being replaced, that source can be destroyed. Operators must not push from the target staging tree to itself. |
| Symlink targets outside container mounts | The container mounts `/tmp/claude-artifacts` and `~/.local/share/claude-artifacts`, not all of `$HOME`. A host-created symlink to a source outside mounted paths exists in `/tmp` but cannot be followed inside the container, so static routes serve 404. |
| Symlink targets not sandboxed | When the target is reachable in the serving process namespace, anything under the pushed target tree is reachable. Push narrowly. |
| `/tmp` volatility | Staging, pid, port, log, and index wipe on reboot. Feedback DB and uploads survive. |

## 3. Database schema and persistence

DB file: `~/.local/share/claude-artifacts/feedback.db`.

Upload files: `~/.local/share/claude-artifacts/uploads/<reply-id>/<filename>`.

`db_connect()` creates the feedback root, opens SQLite with timeout 10 seconds, enables `PRAGMA foreign_keys = ON`, executes idempotent DDL, then runs the v1 to v2 migration. Current `setting['schema_version']` is `"2"`.

### 3.1 Tables

| Table | Column | Type | Constraints and meaning |
|---|---|---|---|
| `artifact_index` | `project` | TEXT | NOT NULL. Primary key part. |
| `artifact_index` | `subdir` | TEXT | NOT NULL. Primary key part. |
| `artifact_index` | `artifact_id` | TEXT | NOT NULL. Current artifact identity for this staged entry. |
| `artifact_index` | `src_path` | TEXT | NOT NULL. Expanded absolute source path from push. |
| `artifact_index` | `last_pushed` | INTEGER | NOT NULL epoch seconds. |
| `comment` | `id` | INTEGER | PRIMARY KEY AUTOINCREMENT. Legacy flat comment row. |
| `comment` | `artifact_id` | TEXT | NOT NULL. |
| `comment` | `sub_path` | TEXT | NOT NULL DEFAULT ''. |
| `comment` | `body` | TEXT | NOT NULL. |
| `comment` | `author` | TEXT | Nullable. |
| `comment` | `created_at` | INTEGER | NOT NULL epoch seconds. |
| `setting` | `key` | TEXT | PRIMARY KEY. Keys observed: `schema_version`, `author`, optional `bd_mirror`. |
| `setting` | `value` | TEXT | NOT NULL. |
| `thread` | `id` | INTEGER | PRIMARY KEY AUTOINCREMENT. |
| `thread` | `artifact_id` | TEXT | NOT NULL. |
| `thread` | `sub_path` | TEXT | NOT NULL DEFAULT ''. |
| `thread` | `anchor_kind` | TEXT | NOT NULL DEFAULT `page`; check in `page`, `image_region`, `code_line`. |
| `thread` | `anchor_data` | TEXT | Nullable compact JSON for non-page anchors. |
| `thread` | `resolved` | INTEGER | NOT NULL DEFAULT 0; check 0 or 1. |
| `thread` | `author` | TEXT | Nullable author of opener. |
| `thread` | `created_at` | INTEGER | NOT NULL epoch seconds. |
| `thread` | `bd_ticket` | TEXT | Nullable mirrored board ticket id. |
| `reply` | `id` | INTEGER | PRIMARY KEY AUTOINCREMENT. |
| `reply` | `thread_id` | INTEGER | NOT NULL REFERENCES `thread(id)` ON DELETE CASCADE. |
| `reply` | `body` | TEXT | NOT NULL. |
| `reply` | `author` | TEXT | Nullable. |
| `reply` | `created_at` | INTEGER | NOT NULL epoch seconds. |
| `upload` | `id` | INTEGER | PRIMARY KEY AUTOINCREMENT. |
| `upload` | `reply_id` | INTEGER | Nullable REFERENCES `reply(id)` ON DELETE CASCADE. |
| `upload` | `comment_id` | INTEGER | Nullable legacy pointer. |
| `upload` | `filename` | TEXT | NOT NULL sanitized filename. |
| `upload` | `stored_path` | TEXT | NOT NULL full stored path. |
| `upload` | `mime` | TEXT | Nullable guessed MIME. |
| `upload` | `size` | INTEGER | NOT NULL bytes. |
| `upload` | `created_at` | INTEGER | NOT NULL epoch seconds. |

### 3.2 Indexes and primary keys

| Name | Definition |
|---|---|
| `sqlite_autoindex_artifact_index_1` | Primary key on `(project, subdir)`. |
| `idx_index_artifact` | `artifact_index(artifact_id)`. |
| `idx_comment_artifact_path` | `comment(artifact_id, sub_path)`. |
| `sqlite_autoindex_setting_1` | Primary key on `setting(key)`. |
| `idx_thread_artifact_path` | `thread(artifact_id, sub_path)`. |
| `idx_reply_thread` | `reply(thread_id)`. |
| `idx_upload_reply` | `upload(reply_id)`. |
| `idx_upload_comment` | `upload(comment_id)`. |

### 3.3 Migration behavior

If `setting['schema_version']` is absent or less than 2:

1. New tables are created if missing.
2. Legacy `upload` is rebuilt if it lacks `reply_id`.
3. Every legacy `comment` row is copied into one page-level `thread` and one opening `reply` in comment id order.
4. Uploads for that comment are remapped to the new reply.
5. `setting['schema_version']` is set to `"2"`.

The migration is one transaction and idempotent after the version stamp.

### 3.4 bd-board mirror behavior

| Trigger | Mirror action | Failure behavior |
|---|---|---|
| Create thread | If `setting['bd_mirror'] == "1"`, `bd` is on `PATH`, the agent-workbench CLI exists, and the pushed artifact's project resolves to a hub board, run `bd create <title>`. Store the first whitespace token of stdout in `thread.bd_ticket`. | Best effort. Any missing tool, unknown project, timeout, non-zero exit, DB error, or parse failure returns no ticket and never fails the HTTP write. |
| Add reply | If `thread.bd_ticket` exists, run `bd comment <bd_ticket> <reply.body>` against the artifact project's board. | Best effort warning only. |
| Resolve or reopen | If `thread.bd_ticket` exists, run `bd close <bd_ticket>` when resolved true, else `bd reopen <bd_ticket>`. | Best effort warning only. |

Board choice: look up the latest `artifact_index.project` for the thread's `artifact_id`, then run `agent-workbench hub path <project>`. The returned path is used as `BEADS_DIR` for all `bd` calls. In the current container image, the agent-workbench CLI is not copied in, so `_bd_beads_dir()` returns `None` and mirror behavior degrades off by contract.

## 4. Viewer technology contract

### 4.1 Shared frontend shell

Server-owned pages use `render_page()`:

- `<!doctype html>` with UTF-8.
- Pre-paint theme script reads localStorage key `review-serve-theme`.
- Shared stylesheet at `/_/assets/css/theme.css`.
- Optional page-specific CSS and scripts.
- Theme toggle cycles `auto`, `light`, `dark`.

Injected raw HTML pages do not own `<head>`, so the feedback widget carries scoped theme CSS and a later theme script. This can briefly flash before syncing to the stored theme.

### 4.2 Gallery contract

`/_/review?artifact=<id>` renders a gallery for the artifact root. `path=<rel-dir>` renders a gallery for a subdirectory. The gallery lists only direct child image files for the explicit review gallery. Static directory browsing lists direct child dirs, image files, recognized code files, and raw fallbacks.

Image extensions treated as viewable: `.png .jpg .jpeg .webp .gif .bmp .tif .tiff`.

Code extensions treated as text viewable: `.py .js .ts .jsx .tsx .json .md .txt .log .csv .yaml .yml .toml .sh .bash .zsh .css .html .htm .xml .c .cpp .h .hpp .go .rs .java .rb .gd .cfg .ini .sql`.

### 4.3 Image viewer contract

`/_/review?artifact=<id>&src=<rel>&view=image` returns HTML that:

- Loads `/_/assets/openseadragon/openseadragon.min.js`.
- Loads `/_/assets/annotorious/annotorious-openseadragon.min.js`.
- Loads `/_/assets/annotorious/annotorious.min.css`.
- Creates OpenSeadragon with `tileSources: { type: 'image', url: IMAGE_URL }` and `showNavigator: true`.
- Uses `prefixUrl: '/_/assets/openseadragon/images/'`.
- Creates Annotorious with `OpenSeadragon.Annotorious(viewer, { drawingEnabled: true })`.
- Fetches `GET /_/api/threads?artifact=<id>&sub_path=<src>`.
- Converts each `image_region` thread to Annotorious annotation `{ id: 'thread-<id>', type: 'Annotation', body: [], target: { selector: t.anchor.selector } }`.
- Calls `anno.setAnnotations(annotations)`.
- Uses Annotorious formatter classes to color resolved and unresolved annotations.
- On new annotation, prompts for text with `window.prompt('comment:')`, posts a multipart `POST /_/api/threads` with `anchor_kind=image_region` and `anchor_data={selector: annotation.target.selector}`, removes the temporary annotation, then reloads threads.

Important: there is no DZI tile generation endpoint. OpenSeadragon runs in simple-image mode against the raw static image URL.

### 4.4 Code viewer contract

`/_/review?artifact=<id>&src=<rel>&view=code` returns HTML that:

- Reads the staged file as UTF-8 with replacement for invalid bytes.
- Escapes every line with `html.escape`.
- Renders one clickable `.code-line` per line with `data-line` and id `L<n>`.
- Fetches `GET /_/api/threads?artifact=<id>&sub_path=<src>`.
- Groups `code_line` threads by `anchor.line`.
- Adds `.has-thread` to lines with threads.
- Clicking a line opens the panel, shows existing thread cards, and posts new line comments with `anchor_kind=code_line` and `anchor_data={line:<n>}`.
- Resolve and reopen use `POST /_/api/threads/<id>/resolve`.

### 4.5 Page-level HTML feedback widget

Every `text/html` static artifact response is rewritten to include `PAGE_COMMENT_WIDGET` before `</body>` or appended if no closing body tag exists. The widget:

- Fetches `GET /_/api/settings` and pre-fills `author` when present.
- Fetches `GET /_/api/threads?url=<window.location.pathname>`.
- Displays only `anchor_kind=page` threads.
- Renders user strings via `textContent`, not raw HTML.
- Posts new comments with `POST /_/api/threads`, multipart fields `url`, `anchor_kind=page`, `body`, optional `author`, optional `files`.
- Shows uploads as links to `/_/api/uploads/<id>`.
- Toggles resolved state with `POST /_/api/threads/<id>/resolve`.

## 5. artifact-serve skill contract

### 5.1 Publish contract used by agents

The skill instructs agents to share viewer URLs, never raw file paths or bare image links.

Image viewer URL:

```text
https://<tailnet-host>/_/review?artifact=<id>&src=<image>&view=image
```

Gallery URL:

```text
https://<tailnet-host>/_/review?artifact=<id>
```

Code viewer URL:

```text
https://<tailnet-host>/_/review?artifact=<id>&src=<file>&view=code
```

CLI publish path:

```bash
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py push --project NAME --src /path/to/dir --id <artifact-id>
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py start
```

CLI verbs that must remain available:

```text
push unpush start run expose unexpose status stop clean feedback name
```

`run` is the foreground container and systemd entry point. `start` is the daemonizing CLI path.

### 5.2 Feedback read-back contract

Agents read feedback with:

```bash
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py feedback --artifact <id>
```

Exit behavior:

| Case | Exit | Output |
|---|---:|---|
| Valid artifact id, even unknown | 0 | JSON to stdout. Unknown artifact returns empty arrays. |
| Blank artifact id after strip | 1 | `error: --artifact required` on stderr. |
| SQLite error | 2 | `error: db: <message>` on stderr. |

JSON shape:

```json
{
  "artifact_id": "project/subdir-or-custom-id",
  "pushes": [
    {
      "project": "project",
      "subdir": "subdir",
      "src_path": "/expanded/source/path",
      "last_pushed": 1720000000,
      "last_pushed_iso": "2024-07-03T09:46:40Z"
    }
  ],
  "threads": [
    {
      "id": 1,
      "sub_path": "image.png",
      "anchor_kind": "image_region",
      "anchor": { "selector": { "type": "FragmentSelector", "value": "xywh=1,2,3,4" } },
      "resolved": false,
      "author": "alice",
      "created_at": 1720000000,
      "created_at_iso": "2024-07-03T09:46:40Z",
      "bd_ticket": null,
      "replies": [
        {
          "id": 1,
          "body": "comment",
          "author": "alice",
          "created_at": 1720000000,
          "created_at_iso": "2024-07-03T09:46:40Z",
          "uploads": []
        }
      ]
    }
  ],
  "comments": [
    {
      "id": 1,
      "thread_id": 1,
      "sub_path": "",
      "body": "page comment",
      "author": "alice",
      "created_at": 1720000000,
      "created_at_iso": "2024-07-03T09:46:40Z",
      "resolved": false,
      "uploads": []
    }
  ]
}
```

`threads` is canonical. `comments` is deprecated compatibility output containing flattened replies from page-anchor threads only.

## 6. Security and hardening bar

### 6.1 Runtime trust model

- No authentication.
- Trusted tailnet model.
- Anyone who can reach the service can read pushed artifacts and write comments, threads, resolve state, and uploads.
- Bind locally on the host and put Tailscale Serve in front when sharing.
- Push narrowly because symlink targets are the access boundary.

### 6.2 Container hardening required for parity

| Control | Current source |
|---|---|
| Base image pinned by digest | `FROM python@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91`. |
| Rootless identity | Quadlet `User=%U`, `Group=%U`, `UserNS=keep-id`; compose uses best-effort `user: "${UID:-1000}:${GID:-1000}"`. |
| Read-only root filesystem | Quadlet `ReadOnly=true`; compose `read_only: true`. |
| Tmpfs | Quadlet `Tmpfs=/tmp`; compose `tmpfs: /tmp`. |
| Drop capabilities | Quadlet `DropCapability=ALL`; compose `cap_drop: [ALL]`. |
| No new privileges | Quadlet `NoNewPrivileges=true`; compose `security_opt: no-new-privileges:true`. |
| Narrow mounts | `/tmp/claude-artifacts:/tmp/claude-artifacts:rw` and `~/.local/share/claude-artifacts:~/.local/share/claude-artifacts:rw`. No `$HOME`-wide mount. |
| Loopback publish | App binds `REVIEW_SERVE_HOST=0.0.0.0` in-container. Podman publishes only `127.0.0.1:9099:9099`. Compose does the same. |
| Healthcheck | Containerfile and compose GET `http://127.0.0.1:${REVIEW_SERVE_PORT:-9099}/`. |
| SELinux note | Quadlet disables label check with `SecurityLabelDisable=true` for the narrow feedback bind. |

The tracked container README still contains older text about a broad `~` read-only mount and `Network=host`. The current hardening source of truth is the Containerfile, quadlet, compose file, deploy CLI, and tests.

### 6.3 Tailscale Serve

Host-level exposure command:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9099
```

Current CLI `expose` runs that command. Current CLI `stop` also runs `tailscale serve --https=443 off` after killing the daemon. For the container path, prefer `systemctl --user restart review-serve` and host-level Tailscale management.

Live-service footgun: do not add any app, deploy, or shutdown path that tears down host Tailscale Serve mappings unexpectedly. The deploy CLI `down` only stops bundle-owned quadlets and does not call `tailscale serve off`.

### 6.4 Held HTTP publish endpoint, ticket `agent-workbench-wxh`

The current deployed server has no `POST /_/api/publish` route. A functionally complete publish endpoint exists only as held work. It is held because it allowed network writers to store same-origin active content on a no-auth UI.

Problem:

- Comment uploads block `.html`, `.htm`, `.xhtml`, `.svg`, `.js`, `.mjs`.
- Held publish accepted active content and served it raw as same-origin `text/html` or SVG/JS.
- The review UI APIs are same-origin and unauthenticated.
- Any tailnet peer with write reach could plant stored JS and script the review UI, comments, threads, and settings APIs.
- CLI push is not an equivalent baseline because CLI push requires local shell access, while HTTP publish requires only network access.

Acceptable mitigations before any HTTP publish route ships:

1. Sandbox CSP on the raw artifact route, with scripts disabled, plus `nosniff`.
2. Serve raw artifacts from a separate origin or port so active content cannot script the review UI origin.
3. Restrict HTTP publish to non-active types, matching a strict allowlist such as the upload allowlist.

A token write gate may reduce writer access, but it does not replace same-origin active-content isolation.

### 6.5 SSRF guard pattern from ticket `agent-workbench-h5u`

The current review server does not fetch arbitrary remote URLs. If the rewrite adds any server-side fetch, including HTTP publish by URL, import by URL, clipping, preview generation, or metadata fetch, use the closed `h5u` pattern:

- Resolve the initial hostname with `getaddrinfo` before connecting.
- Reject loopback, private, link-local, multicast, unspecified, reserved, and IPv4-mapped forms of those ranges.
- Explicitly reject cloud metadata `169.254.169.254`.
- Explicitly reject Tailscale and CGNAT `100.64.0.0/10`.
- Revalidate every redirect hop before following it.
- Fail closed on DNS, parse, redirect, or validation uncertainty.

### 6.6 Existing content safety controls

| Area | Current control |
|---|---|
| Static asset route | Traversal guarded under `ASSETS_ROOT`. |
| Review `src` route | Traversal guarded under staged root with `resolve()` and `is_relative_to`. |
| Annotorious anchors | `SvgSelector` rejected. Only `FragmentSelector` is accepted. |
| User text rendering | Viewer and widget render comments with `textContent`. Code lines are `html.escape` escaped. |
| Upload downloads | `nosniff`; potentially active uploaded types are blocked. |
| No secret env echo | Regression test verifies an environment secret does not appear in representative pages and API responses. |

## 7. Parity checklist

- [ ] `GET /` returns 200 and root index HTML after server start or index regeneration.
- [ ] CLI `push` stages by relative symlink under `/tmp/claude-artifacts/<project>/<subdir>` and upserts `artifact_index`.
- [ ] CLI `push` preserves literal source path with `.absolute()`, not `.resolve()`.
- [ ] CLI `push` prints `symlink ... → ...` and `artifact_id: ...`.
- [ ] CLI `start` daemonizes, writes pid and port files, is idempotent on same port, refuses conflicting port.
- [ ] CLI `run` stays foreground for container and systemd.
- [ ] CLI `status`, `unpush`, `clean`, `stop`, `expose`, `unexpose`, `name`, and `feedback` keep their current behavior and exit codes.
- [ ] Host bind defaults to `127.0.0.1:9099`; env `REVIEW_SERVE_HOST` and `REVIEW_SERVE_PORT` steer `start` and `run` defaults.
- [ ] Container binds internally to `0.0.0.0:9099` and publishes only `127.0.0.1:9099:9099`.
- [ ] Container keeps read-only rootfs, tmpfs `/tmp`, `cap_drop: ALL`, no-new-privileges, pinned base image digest, healthcheck, and narrow mounts only.
- [ ] Host Tailscale Serve remains `tailscale serve --bg --https=443 http://127.0.0.1:9099`; app shutdown paths do not unexpectedly tear it down.
- [ ] Static artifacts serve from pushed symlink targets when reachable.
- [ ] Static `text/html` artifacts get the page feedback widget injected before `</body>` and suppress `Content-Length`.
- [ ] Directories without `index.html` render the themed directory gallery.
- [ ] `/_/` remains reserved and cannot collide with pushed project names.
- [ ] `/_/assets/<rel>` serves only vendored assets under `ASSETS_ROOT`.
- [ ] `/_/review?artifact=<id>` renders image gallery.
- [ ] `/_/review?artifact=<id>&src=<image>&view=image` renders OpenSeadragon simple-image viewer with Annotorious region pins.
- [ ] `/_/review?artifact=<id>&src=<file>&view=code` renders escaped per-line code viewer and line comments.
- [ ] Image region annotations round-trip as `FragmentSelector` anchors and reject `SvgSelector`.
- [ ] Code anchors validate positive integer `line` and optional `end_line`.
- [ ] `GET /_/api/threads` resolves by `artifact` plus `sub_path` and by static `url`.
- [ ] `POST /_/api/threads` creates a thread plus opening reply plus optional uploads.
- [ ] `POST /_/api/threads/<id>/replies` appends replies plus optional uploads.
- [ ] `POST /_/api/threads/<id>/resolve` toggles on empty body and sets explicit state from JSON.
- [ ] Legacy `/_/api/comments` GET and POST shims keep working for page-level comments.
- [ ] `GET /_/api/uploads/<id>` returns bytes, inline safe MIME types, attachment otherwise, `nosniff`, 410 when missing on disk.
- [ ] `GET /_/api/settings` returns all settings rows.
- [ ] Upload allowlist, blocklist, size caps, request cap, and filename sanitizer match current behavior.
- [ ] SQLite schema, indexes, v1 to v2 migration, and `schema_version=2` behavior match current behavior.
- [ ] `feedback --artifact <id>` returns JSON `{artifact_id, pushes[], threads[], comments[]}` with `threads` canonical and page-thread `comments` compatibility output.
- [ ] Unknown artifact feedback returns empty `pushes`, `threads`, and `comments` arrays with exit 0.
- [ ] Optional bd mirror creates tickets, comments replies, closes/reopens on resolve, chooses board through `agent-workbench hub path <project>`, and never fails the HTTP write.
- [ ] No HTTP publish route ships until `agent-workbench-wxh` active-content mitigation is implemented and tested.
- [ ] Any new server-side URL fetch follows the `agent-workbench-h5u` SSRF deny and redirect validation pattern.
