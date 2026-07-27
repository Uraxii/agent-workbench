# Artifact Review Backend Architecture

## Scope

This document designs the Django backend that replaces the HTTP serving parts of `review-serve.py` while preserving the parity contract in `docs/design/artifact-server-parity-spec.md`.

The first implementation target is server parity. The existing Python `push`, `feedback`, and deployment CLI paths keep working during migration because the Django backend reads and writes the same staging tree and SQLite database.

Non-goals for the first backend slice:

- No new authentication model.
- No Django REST Framework dependency.
- No Django-managed migrations for the existing feedback tables.
- No dynamic deep-zoom tile generation in the parity slice.
- No same-origin HTTP publish route for active content.
- No path that tears down host Tailscale Serve mappings.

## Stack and project layout

### Framework choice

Use plain Django views plus `JsonResponse`, `FileResponse`, `StreamingHttpResponse`, and form parsing. Do not use Django REST Framework for the parity rewrite.

Plain Django fits this server because the route surface is small, explicit, and mostly compatibility glue around an existing SQLite file and staged filesystem. DRF would add serializers, viewsets, authentication defaults, and content negotiation behavior that the current `artifact-serve` skill does not need. Avoiding it keeps dependencies minimal and makes exact status codes, multipart limits, and headers easier to preserve.

### Python and dependencies

The host has `python3` 3.14, so local build, run, and tests do not require a container.

| Dependency | Purpose | Notes |
|---|---|---|
| `Django` | HTTP routing, settings, test client, static helpers | Required. Pin a supported Django version compatible with Python 3.14. |
| `gunicorn` | Local and container WSGI server | Required for production-style serving. |
| `pytest` | Test runner | Test-only. |
| `pytest-django` | Django test integration | Test-only. |

Do not add DRF, Celery, SQLAlchemy, or a second migration tool for the parity slice.

### Directory layout

```text
apps/artifact-review/backend/
  manage.py
  pyproject.toml
  artifact_review_site/
    __init__.py
    asgi.py
    settings.py
    urls.py
    wsgi.py
  artifact_review/
    __init__.py
    apps.py
    artifact_paths.py
    artifact_resolution.py
    board_mirror.py
    feedback_forms.py
    feedback_json.py
    feedback_widget.py
    models.py
    publish_policy.py
    response_headers.py
    ssrf_guard.py
    upload_validation.py
    urls.py
    views_api.py
    views_review.py
    views_static.py
  tests/
    test_api_parity.py
    test_artifact_paths.py
    test_bd_mirror.py
    test_feedback_database.py
    test_publish_policy.py
    test_review_views.py
    test_ssrf_guard.py
    test_static_artifacts.py
```

Names use domain nouns and effects. Avoid vague `Manager`, `Helper`, and broad `Service` names. View modules only map HTTP requests to named behavior. Database row names mirror the existing tables so a cold reader can connect code to the schema.

### Settings

Use environment variables matching the current server:

| Variable | Default | Meaning |
|---|---|---|
| `REVIEW_SERVE_HOST` | `127.0.0.1` | Bind host for local run and gunicorn wrapper. |
| `REVIEW_SERVE_PORT` | `9099` | Bind port for local run and gunicorn wrapper. |
| `REVIEW_SERVE_STAGE_ROOT` | `/tmp/claude-artifacts` | Staged artifact symlink tree. |
| `REVIEW_SERVE_FEEDBACK_ROOT` | `~/.local/share/claude-artifacts` | Durable DB and upload root. |
| `REVIEW_SERVE_SPA_ROOT` | frontend build directory | React SPA bundle root. |
| `REVIEW_SERVE_ASSETS_ROOT` | bundled backend assets directory | Vendored OpenSeadragon, Annotorious, CSS, and images. |
| `REVIEW_SERVE_PUBLISH_ENABLED` | `0` | HTTP publish route disabled unless deliberately enabled. |

`settings.py` sets `DATABASES['default']['ENGINE'] = 'django.db.backends.sqlite3'` and `DATABASES['default']['NAME']` to `~/.local/share/claude-artifacts/feedback.db` after expanding `~`. It does not point at an app-local development database.

## API contract

The Django backend must match the current HTTP contract exactly unless a row says otherwise. JSON keys remain snake_case.

| Method | Route | Django view | Request shape | Response shape | Status codes | Parity notes |
|---|---|---|---|---|---|---|
| GET | `/` | `root_index` | none | Root index HTML from `/tmp/claude-artifacts/index.html`, or SPA shell when the React entrypoint owns root after migration | 200, normal 404 | Keep this as the health route. If SPA owns `/`, it must still show the staged project grid behavior. |
| GET | `/_/assets/<path:rel>` | `vendored_asset` | route `rel` | Asset bytes | 200, 404 | Resolve under `REVIEW_SERVE_ASSETS_ROOT`; reject traversal after full path resolution. |
| GET | `/_/api/settings` | `api_settings` | none | `{key: value}` from `setting` | 200, 500 `{error}` | Ensures schema exists, matching current route behavior. |
| GET | `/_/api/uploads/<int:id>` | `api_upload` | route `id` | Upload bytes | 200, 404, 410, 500 | Preserve `Content-Type`, `Content-Length`, `X-Content-Type-Options: nosniff`, and disposition rules. |
| GET | `/_/api/threads` | `api_threads` | query `artifact` plus optional `sub_path`, or `url` | `{artifact_id, sub_path, threads}` | 200, 404, 500 | Resolve by artifact or static URL. `sub_path` defaults to empty. |
| POST | `/_/api/threads` | `api_create_thread` | multipart form: target, `anchor_kind`, optional `anchor_data`, `body`, optional `author`, optional `files` | `{thread_id, reply_id, artifact_id, sub_path, anchor_kind, uploads}` | 201, 400, 411, 413, 500 | Requires `Content-Length`; creates thread, opening reply, uploads, optional bd ticket. |
| POST | `/_/api/threads/<int:id>/replies` | `api_create_reply` | multipart form: `body`, optional `author`, optional `files` | `{reply_id, thread_id, uploads}` | 201, 400, 404, 411, 413, 500 | Requires existing thread; best-effort bd comment if mirrored. |
| POST | `/_/api/threads/<int:id>/resolve` | `api_resolve_thread` | optional JSON body | `{id, resolved}` | 200, 400, 404, 411, 413 | Empty body toggles. `{resolved: value}` coerces with Python truthiness. |
| GET | `/_/api/comments` | `api_comments` | query `artifact` plus optional `sub_path`, or `url` | `{artifact_id, sub_path, comments}` | 200, 404, 500 | Legacy flattened page-anchor shim only. |
| POST | `/_/api/comments` | `api_create_comment` | legacy multipart form | `{id, thread_id, artifact_id, sub_path}` | 201, 400, 411, 413, 500 | Creates page-level thread and opening reply. Mirrors like `api_create_thread`. |
| GET | `/_/review` | `review_page` | query `artifact`, optional `view`, `src`, `path` | HTML review page | 200, 400, 404 | No view renders gallery. `view=image` renders simple-image OpenSeadragon. `view=code` renders escaped line viewer. |
| GET | `/_/tiles/<artifact>/<path:src>/<path:tile>` | `deep_zoom_tile` | reserved future route | tile bytes | 404 or 501 in parity slice | No dynamic DZI exists today. If implemented later, it must use staged-root guards and SSRF guard for any remote fetch. This addition would require a lockstep `artifact-serve` skill doc change. |
| POST | `/_/api/publish` | `api_publish` | disabled by default | disabled by default | 404 or 501 while disabled | Not current parity. If enabled, it is restricted to non-active types and forces a lockstep skill-doc update. |
| GET | `/_/app/assets/<path:rel>` | `spa_asset` | route `rel` | React bundle asset bytes | 200, 404 | Vite `base: '/_/app/'`. Placing hashed JS/CSS under the reserved `/_/` namespace means a pushed project literally named `assets` can never collide with the SPA's own asset paths. Resolve under `REVIEW_SERVE_SPA_ROOT`; traversal guard. |
| GET | `/<project>/<subdir>/<path:rel>` | `static_artifact` | static URL path | raw bytes, rewritten HTML, or generated directory gallery | 200, 301, 404, normal static statuses | Serve staged files. HTML gets feedback widget and sandbox CSP. |
| GET | `/<project>/<subdir>/` | `static_artifact` | directory URL | static index or generated gallery | 200, normal static statuses | Lists direct child dirs, images, code files, and raw fallback links. |
| GET | `/` and any unmatched non-reserved, non-artifact top-level route | `spa_index` | route path | React `index.html` (the unified app shell) | 200, 404 | Registered LAST, after `/_/api`, `/_/assets`, `/_/app`, `/_/review`, `/_/tiles`, and the `/<project>/<subdir>/...` artifact routes. `GET /` serving the SPA shell satisfies both the parity health-route contract (200) and the container healthcheck; the SPA replaces the old static tile-grid root page with its own API-driven view. The SPA should avoid its own single-segment top-level client routes beyond `/` (use query params or hash routing for mode/view state) so it never has to compete with a real two-segment pushed-artifact path. Do not mask bad reserved API paths under `/_/*`. |

### DTO shapes

Use dictionaries or dataclasses rendered through `JsonResponse`. Preserve these keys:

```text
ThreadListResponse: artifact_id, sub_path, threads[]
Thread: id, sub_path, anchor_kind, anchor, resolved, author, created_at, created_at_iso, bd_ticket, replies[]
Reply: id, body, author, created_at, created_at_iso, uploads[]
Upload: id, filename, stored_path, mime, size, created_at, created_at_iso
LegacyComment: id, thread_id, sub_path, body, author, created_at, created_at_iso, resolved, uploads[]
```

`JsonResponse` must set `safe=False` only for array top-level values. Current parity responses are object top-level values.

### Request validation

Keep the current limits:

| Input | Rule |
|---|---|
| Request body | `Content-Length` required, integer, non-negative, max 500 MB. |
| Comment body | Required after `.strip()`, max 20,000 chars, stored stripped. |
| Author | Optional after `.strip()`. If absent, use `setting.author` when present. |
| Upload file | Max 100 MB each. |
| Upload name | Basename only, replace non `[A-Za-z0-9._-]` with `_`, strip leading dots, cap 200 chars, collision suffix `-1`, `-2`. |
| Upload allowlist | `.png .jpg .jpeg .webp .gif .bmp .tif .tiff .pdf .txt .md .log .csv .json .yaml .yml .toml .zip .tar .gz .7z .fig .psd .xcf .sketch .mp4 .webm .mov`. |
| Upload blocklist | `.exe .dll .sh .bash .zsh .bat .cmd .ps1 .js .mjs .html .htm .xhtml .svg .com`. |
| Anchor JSON | Max 8 KiB, JSON object only for non-page anchors. |
| Page anchor | `anchor_data` absent or blank. |
| Image anchor | `FragmentSelector` only, value matches `xywh=(pixel:|percent:)?n,n,n,n`; reject `SvgSelector`. |
| Code anchor | `line` integer >= 1; optional `end_line` integer >= `line`; reject booleans. |

Set Django upload limits to support parity, but enforce route-specific checks in view code so tests can verify the exact 411, 413, and 400 behavior. Stream files through Django upload handlers rather than reading entire uploads into memory.

## Data layer

### Storage locations

Use the same paths as `review-serve.py`:

| Resource | Path |
|---|---|
| Stage root | `/tmp/claude-artifacts` |
| Root index | `/tmp/claude-artifacts/index.html` |
| Server pid | `/tmp/claude-artifacts/.serve.pid` |
| Server port | `/tmp/claude-artifacts/.serve.port` |
| Server log | `/tmp/claude-artifacts/.serve.log` |
| Feedback DB | `~/.local/share/claude-artifacts/feedback.db` |
| Upload files | `~/.local/share/claude-artifacts/uploads/<reply-id>/<filename>` |

The backend must not move the database or restage artifacts. Existing Python `push` and `feedback` commands continue to work because they read and write these same locations.

### Django database configuration

`settings.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(FEEDBACK_ROOT / "feedback.db"),
        "OPTIONS": {"timeout": 10},
    }
}
```

On every connection, enable foreign keys with Django's SQLite connection hook or a small connection wrapper:

```sql
PRAGMA foreign_keys = ON;
```

Django migrations must not create, drop, or alter the existing feedback tables. The app either has no migrations for these models, or the initial migration is marked as not used for this database. Existing schema creation and v1 to v2 migration logic belongs in an explicit `ensure_feedback_schema()` function called at startup and before `GET /_/api/settings`, matching the current Python behavior.

### Unmanaged models

Use `managed = False` on every model. Use explicit `db_table`, column names, primary keys, and indexes documented in tests. Example shape:

| Model | Existing table | Required mapping |
|---|---|---|
| `ArtifactIndex` | `artifact_index` | `project`, `subdir`, `artifact_id`, `src_path`, `last_pushed`; composite primary key is represented by `unique_together = (('project', 'subdir'),)`. |
| `Setting` | `setting` | `key` primary key, `value`. |
| `Thread` | `thread` | `id`, `artifact_id`, `sub_path`, `anchor_kind`, `anchor_data`, `resolved`, `author`, `created_at`, `bd_ticket`. |
| `Reply` | `reply` | `id`, `thread_id`, `body`, `author`, `created_at`. |
| `Upload` | `upload` | `id`, `reply_id`, `comment_id`, `filename`, `stored_path`, `mime`, `size`, `created_at`. |
| `LegacyComment` | `comment` | `id`, `artifact_id`, `sub_path`, `body`, `author`, `created_at`. |

Do not rely on Django model validation for parity. Views and form helpers perform the exact current validation. The ORM can be used for simple reads and writes, but schema migration and legacy v1 conversion should use explicit SQL inside `transaction.atomic()` because it must match the current table rebuild behavior.

### Existing indexes

The explicit schema function creates or preserves:

```text
idx_index_artifact on artifact_index(artifact_id)
idx_comment_artifact_path on comment(artifact_id, sub_path)
idx_thread_artifact_path on thread(artifact_id, sub_path)
idx_reply_thread on reply(thread_id)
idx_upload_reply on upload(reply_id)
idx_upload_comment on upload(comment_id)
```

### Migration behavior

Preserve the current idempotent migration:

1. Create missing v2 tables and indexes.
2. If `setting.schema_version` is absent or less than `2`, rebuild legacy `upload` when it lacks `reply_id`.
3. Copy each legacy `comment` row into one page-level `thread` and one opening `reply` in comment id order.
4. Remap uploads for the legacy comment to the new reply.
5. Set `setting.schema_version` to `2`.
6. Commit all migration work in one transaction.

Tests must run this migration against a real temporary SQLite file with seeded v1 data.

### bd-board mirror behavior

Keep the mirror behavior exactly. It is best effort and never fails an HTTP write.

| Trigger | Django action | Failure behavior |
|---|---|---|
| Create thread | If `setting.bd_mirror == "1"`, find the artifact project, run `agent-workbench hub path <project>`, then run `bd create <title>` with `BEADS_DIR` set to that path. Store the first whitespace token of stdout in `thread.bd_ticket`. | Swallow missing CLI, timeout, non-zero exit, parse failure, DB update failure, and unknown project. Return HTTP success without a ticket. |
| Add reply | If `thread.bd_ticket` exists, run `bd comment <ticket> <reply body>` in the same board. | Best effort warning only. |
| Resolve or reopen | If `thread.bd_ticket` exists, run `bd close <ticket>` when resolved, else `bd reopen <ticket>`. | Best effort warning only. |

Use `subprocess.run([...], shell=False, timeout=<short>)` with an explicit environment. Never invoke a shell. Do not assume `agent-workbench` or `bd` exists in the container.

## Static and artifact serving

### Route ordering

Register routes in this order:

1. `/_/api/*`
2. `/_/assets/*`
3. `/_/app/*` (SPA hashed assets)
4. `/_/review`
5. `/_/tiles/*`
6. Static artifact routes under `/<project>/<subdir>/...`
7. `/` and React SPA catch-all for every remaining non-reserved, non-artifact route

The reserved `/_/` namespace remains safe because project and subdir names must match `^[a-z0-9][a-z0-9_-]*$`.

### React SPA bundle

The Django backend serves the React build from `REVIEW_SERVE_SPA_ROOT`. Decided prefix: Vite `base: '/_/app/'`, so every hashed asset URL the bundle emits lives under the reserved `/_/` namespace and can never collide with a pushed project directory (`NAME_RE` forbids a leading `_`).

| Request | Behavior |
|---|---|
| `/_/app/assets/<rel>` | Resolve under `REVIEW_SERVE_SPA_ROOT`; return asset bytes with MIME type and traversal guard. |
| `GET /` | Return the SPA `index.html` (the unified app shell). This is also the health-route target. |
| Any other unmatched top-level path that is not `/_/api`, `/_/assets`, `/_/app`, `/_/review`, `/_/tiles`, and does not resolve as a two-segment `/<project>/<subdir>/...` artifact path | Return the SPA `index.html` so client-side view state (mode, query params, hash) can render. Registered last in urls.py. |
| Reserved backend path | Never fall through to the SPA. Bad `/_/api`, `/_/assets`, `/_/app`, `/_/review`, and `/_/tiles` paths return backend 404 or 405. |

This prefix is now fixed by decision `artifact-server-spa-mount` (`~/.knowledgebase/agent-workbench/decisions/`); do not change it without recording a superseding decision and updating both the frontend `vite.config.ts` `base` and this table in the same commit.

### Artifact-id resolution

For static URL resolution:

1. Split the URL path.
2. Require at least two segments.
3. Validate `project` and `subdir` with the parity name regex.
4. Look up `(project, subdir)` in `artifact_index`.
5. If found, use stored `artifact_id`; otherwise use `<project>/<subdir>`.
6. Join remaining segments with `/` as `sub_path`.

For review pages, resolve the artifact location by `artifact_id`. `src` and `path` are relative paths under the staged artifact root. The final file path must be resolved and verified under the staged root before reading.

### Staging path mapping

The server serves from the existing symlink tree:

```text
/tmp/claude-artifacts/<project>/<subdir> -> pushed source directory
```

The server does not create or rewrite those symlinks in the backend parity slice. The existing push CLI keeps responsibility for staging and for updating `artifact_index`.

Preserve these current footguns unless a later CLI migration deliberately fixes them with tests:

- Push can destroy a self-referencing staging symlink target.
- Symlink targets outside the container mounts serve 404 from the container.
- Reachable files under pushed symlink targets are reachable.
- `/tmp` staging wipes on reboot.

### Raw artifact responses

For raw static artifact responses:

| File type | Behavior |
|---|---|
| `text/html` | Inject the feedback widget before `</body>`, or append it if no closing body exists. Omit `Content-Length` after rewriting. Add the sandbox CSP described below. |
| `image/svg+xml` | Serve only from CLI-pushed artifacts. Add the sandbox CSP described below. Do not execute scripts. |
| Other files | Stream normally after path validation. Add `X-Content-Type-Options: nosniff`. |

The widget renders user strings with DOM `textContent`, never raw HTML. Upload links point at `/_/api/uploads/<id>`.

### Directory gallery

When a static path is a directory and no `index.html` exists, render themed gallery HTML that lists direct children only:

| Child type | Link target |
|---|---|
| Directory | Raw directory URL with trailing slash. |
| Image extension | `/_/review?artifact=<id>&src=<rel>&view=image` |
| Code extension | `/_/review?artifact=<id>&src=<rel>&view=code` |
| Other file | Raw static URL. |

Image and code extension lists must match the parity spec.

### Review pages and tile behavior

`/_/review?artifact=<id>` renders a gallery for the artifact root or the requested `path`.

`view=image` renders OpenSeadragon in simple-image mode:

- Load `/_/assets/openseadragon/openseadragon.min.js`.
- Load `/_/assets/annotorious/annotorious-openseadragon.min.js`.
- Load `/_/assets/annotorious/annotorious.min.css`.
- Use `tileSources: { type: 'image', url: IMAGE_URL }`.
- Use `prefixUrl: '/_/assets/openseadragon/images/'`.
- Fetch and post image-region threads exactly as the parity spec describes.

There is no dynamic DZI endpoint in current parity. The backend reserves `/_/tiles/*` for a later deep-zoom implementation, but it returns 404 or 501 until a ticket adds tile generation and tests. Any future tile route must use the same staged-root path guard as `view=image` and must not fetch remote tiles server-side without `ssrf_guard.py`.

`view=code` renders a UTF-8 text view with replacement for invalid bytes, escaped lines, clickable `data-line` elements, line-thread grouping, and resolve or reopen calls to `POST /_/api/threads/<id>/resolve`.

## Publish safety and response headers

The publish-safety decision is binding: do not expose a same-origin HTTP publish route that can write active browser content, and do not serve CLI-pushed active content without a sandbox on the no-auth review origin.

### HTTP publish policy

`POST /_/api/publish` is disabled by default with `REVIEW_SERVE_PUBLISH_ENABLED=0`. While disabled, the route returns 404 or 501 and has no side effects.

When deliberately enabled, it must use this policy:

| Control | Required behavior |
|---|---|
| Extension allowlist | Match the upload allowlist: `.png .jpg .jpeg .webp .gif .bmp .tif .tiff .pdf .txt .md .log .csv .json .yaml .yml .toml .zip .tar .gz .7z .fig .psd .xcf .sketch .mp4 .webm .mov`. |
| Active extension blocklist | Always reject `.html .htm .xhtml .svg .js .mjs .exe .dll .sh .bash .zsh .bat .cmd .ps1 .com`. |
| MIME rejection | Reject `text/html`, `image/svg+xml`, `application/javascript`, `text/javascript`, `application/ecmascript`, and `text/ecmascript`. Extension checks remain authoritative because MIME can lie. |
| Path safety | Publish only under a staged artifact directory selected by validated project, subdir, artifact id, and relative file path. Resolve the final path and require it to stay under that staged root. |
| Response headers | Published file responses include `X-Content-Type-Options: nosniff`. Content-Disposition follows the upload route rule. |
| Tests | Cover allowed extensions, blocked active extensions, MIME mismatch, traversal, oversized body, and same-origin script planting regression. |

If the `artifact-serve` skill starts using HTTP publish, update the skill docs in lockstep to say HTTP publish is for non-active files only and CLI push remains required for HTML review pages.

### Sandbox CSP for raw artifacts

The raw-artifact serving route must set a restrictive sandbox Content Security Policy for active browser-rendered artifact types, including HTML and SVG:

```text
Content-Security-Policy: sandbox; default-src 'none'; script-src 'none'; object-src 'none'
X-Content-Type-Options: nosniff
```

Equivalent stricter headers are acceptable. Do not add `allow-scripts` or `allow-same-origin`.

Implement this with a small response-header function used by `views_static.static_artifact` after MIME detection and before returning the response. A middleware may also enforce the header for artifact responses, but the view-level function is still required so tests can call the view and verify exact headers. API routes and the React SPA do not receive the sandbox header.

## SSRF guard

The parity backend should not fetch arbitrary remote URLs. If any server-side fetch is added later, including publish by URL, import by URL, clipping, preview generation, metadata extraction, or remote tiles, use `ssrf_guard.py` based on the closed `agent-workbench-h5u` pattern from `scripts/kb-clip.py`.

Required behavior:

1. Parse the URL and require `http` or `https`.
2. Resolve the hostname with `socket.getaddrinfo()` before connecting.
3. Reject loopback, private, link-local, multicast, unspecified, reserved, and IPv4-mapped forms of those ranges using `ipaddress`.
4. Explicitly reject cloud metadata `169.254.169.254`.
5. Explicitly reject CGNAT and Tailscale range `100.64.0.0/10`.
6. Disable automatic redirects in the HTTP client.
7. For each redirect, resolve and validate the next URL before following it.
8. Fail closed on DNS errors, parse errors, too many redirects, unsupported schemes, or any validation uncertainty.

Address ranges to reject include at least:

| Family | Ranges |
|---|---|
| IPv4 | `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`, `192.168.0.0/16`, multicast, reserved, and `169.254.169.254/32`. |
| IPv6 | `::/128`, `::1/128`, IPv4-mapped protected addresses, `fc00::/7`, `fe80::/10`, multicast `ff00::/8`, and non-global reserved ranges. |

Tests must include initial URL denial and redirect-hop denial for each protected range.

## Serving, runtime, and hardening

### Local run

From repo root, local development can use Django's server:

```bash
cd apps/artifact-review/backend
REVIEW_SERVE_STAGE_ROOT=/tmp/claude-artifacts \
REVIEW_SERVE_FEEDBACK_ROOT="$HOME/.local/share/claude-artifacts" \
REVIEW_SERVE_HOST=127.0.0.1 \
REVIEW_SERVE_PORT=9099 \
python3 manage.py runserver 127.0.0.1:9099
```

Production-style local run uses gunicorn:

```bash
cd apps/artifact-review/backend
REVIEW_SERVE_HOST=127.0.0.1 \
REVIEW_SERVE_PORT=9099 \
gunicorn artifact_review_site.wsgi:application --bind 127.0.0.1:9099
```

ASGI is available through `artifact_review_site.asgi:application` for future websocket or async needs, but the parity slice should run WSGI through gunicorn.

### Container image

Use a slim Python base pinned by digest. Example shape:

```text
FROM python:3.14-slim@sha256:<pinned-builder-digest> AS build
WORKDIR /src
COPY apps/artifact-review/backend/ ./apps/artifact-review/backend/
RUN python -m venv /venv \
 && /venv/bin/pip install --upgrade pip \
 && /venv/bin/pip install ./apps/artifact-review/backend

FROM python:3.14-slim@sha256:<pinned-runtime-digest>
ENV PATH=/venv/bin:$PATH
ENV REVIEW_SERVE_HOST=0.0.0.0
ENV REVIEW_SERVE_PORT=9099
WORKDIR /app
COPY --from=build /venv /venv
COPY apps/artifact-review/backend/ /app/
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9099/', timeout=2).read()" || exit 1
ENTRYPOINT ["gunicorn", "artifact_review_site.wsgi:application", "--bind", "0.0.0.0:9099"]
```

Before implementation merges, replace placeholder digests with real digests. The digest pin is mandatory.

### Runtime controls

Keep the current hardening controls:

| Control | Required config |
|---|---|
| Host bind | Publish only `127.0.0.1:9099:9099`. |
| App bind in container | `0.0.0.0:9099`. |
| Root filesystem | Read-only. |
| Capabilities | `cap_drop: [ALL]` or Quadlet `DropCapability=ALL`. |
| Privilege escalation | `no-new-privileges:true` or Quadlet `NoNewPrivileges=true`. |
| User | Rootless user, `User=%U`, `Group=%U`, `UserNS=keep-id` for Quadlet, UID and GID mapping for compose. |
| Tmpfs | `/tmp` tmpfs, with `/tmp/claude-artifacts` bind-mounted over the staging path when serving host-staged artifacts. |
| Mounts | Only `/tmp/claude-artifacts:/tmp/claude-artifacts:rw` and `~/.local/share/claude-artifacts:~/.local/share/claude-artifacts:rw`. No `$HOME`-wide mount. |
| Healthcheck | GET `http://127.0.0.1:9099/`. |
| SELinux | Preserve the current narrow bind behavior. If label disabling is needed, scope it to this container only. |

### Tailscale Serve

Host exposure remains outside the app:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9099
```

The backend, container entrypoint, deploy scripts, and shutdown scripts must not call:

```bash
tailscale serve --https=443 off
```

Bundle-owned stop paths should stop only the app container or user service.

## Build and test seams

### Local setup

From repo root:

```bash
cd apps/artifact-review/backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python manage.py check
pytest
```

During migration, stage artifacts with the existing CLI:

```bash
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py push --project NAME --src /path/to/dir --id NAME/subdir
```

Then open:

```text
http://127.0.0.1:9099/_/review?artifact=NAME/subdir
```

### Required tests

Use Django's test client and temporary directories. Do not use the real user feedback DB in tests.

| Test group | Required proof |
|---|---|
| API parity | Every route in the API table returns the same status codes, JSON keys, and headers as the Python tests cover. |
| Publish to viewer to feedback loop | Stage an artifact, open gallery, open image review, create image-region thread, add reply, resolve, then read back through the same feedback JSON shape used by `feedback --artifact`. |
| Page widget loop | Serve a static HTML artifact, verify widget injection and sandbox CSP, create a page thread, upload an allowed file, and read upload bytes. |
| Code viewer loop | Open code view, create a `code_line` thread, verify escaped source and line grouping. |
| Legacy comments | `GET` and `POST /_/api/comments` preserve flattened page-comment compatibility. |
| SQLite schema | Managed Django migrations do not create or alter existing tables; `managed = False` models map all tables and columns. |
| SQLite migration | v1 DB migrates to schema version 2, remaps uploads, and remains idempotent. |
| Upload validation | Allowed and blocked extensions, filename sanitizer, body limits, missing `Content-Length`, and oversized uploads. |
| Artifact paths | Traversal rejection, symlink staging lookup, unknown artifact fallback, and `url` to artifact resolution. |
| bd mirror | With fake `agent-workbench` and `bd` commands, create, comment, close, and reopen calls are attempted and failures do not fail HTTP writes. |
| Publish policy | HTTP publish is disabled by default and rejects active extensions and MIME types when enabled. |
| SSRF guard | Initial URL and redirect hops reject protected address ranges. |
| Container | Healthcheck passes, rootfs is read-only, only narrow mounts are present, and host bind is `127.0.0.1:9099`. |

### Implementation slices

The design supports independent implementation slices:

1. Project skeleton, settings, WSGI, root index route, and healthcheck.
2. Unmanaged models, schema creation, migration, settings, thread, reply, upload, and feedback queries.
3. Multipart validation and upload storage.
4. Static artifact serving, sandbox CSP, HTML injection, directory gallery, and vendored assets.
5. React SPA serving, review gallery, image viewer, and code viewer pages.
6. bd-board mirror.
7. Publish policy scaffold with route disabled by default.
8. Containerfile, compose or Quadlet updates, and integration tests.

Each slice should keep parity tests green before moving to the next slice.
