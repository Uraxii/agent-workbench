# artifact-serve — reference

Detailed verb table, storage layout, security model, feedback subsystem, Tailscale wiring. See [SKILL.md](SKILL.md) for quick start.

## Storage layout

### Staging (throwaway, /tmp/)

```
/tmp/claude-artifacts/
├── .serve.pid               # daemon pid (empty if stopped)
├── .serve.port              # port the daemon listens on
├── .serve.log               # request log + diagnostics
├── index.html               # auto-regenerated tile grid (root listing)
├── <project-a>/
│   ├── <subdir-1>           # symlink → /home/user/repo/mockups
│   └── <subdir-2>           # symlink → /home/user/repo/other
└── <project-b>/
    └── ...
```

- `<project>` **required** on push/clean. No git/cwd auto-detect.
- `<subdir>` defaults to source basename; override w/ `--as`.
- Both names must match `[a-z0-9][a-z0-9_-]*` — lowercase kebab/underscore.
- Entries always symlinks to `--src` (no copy mode). Literal `--src` path preserved (no symlink-chain dereference).
- Wipes on reboot.

### Feedback (durable, ~/.local/share/)

```
~/.local/share/claude-artifacts/
├── feedback.db              # sqlite: artifact_index, comment, upload
└── uploads/
    └── <comment-id>/
        ├── screenshot.png
        └── note.pdf
```

- Survives reboot + `/tmp/` wipe.
- `feedback.db` schema: see [Schema](#schema) below.
- Uploads stored on disk; row in `upload` table points at file via `stored_path`.

## Verbs

| Verb | Flags | Behaviour |
|------|-------|-----------|
| `push` | `--project NAME` (req) `--src PATH` (req) `[--as SUBDIR]` `[--id ARTIFACT_ID]` | Relative symlink at `/tmp/claude-artifacts/<project>/<subdir>/` → `PATH`. Always symlink. `NAME` + `SUBDIR` must match `[a-z0-9][a-z0-9_-]*`. `--id` is opaque (any string); defaults to `<project>/<subdir>`. Records (project, subdir, artifact_id, src_path) in `artifact_index`. Overwrites prior entry. Re-runs index regen. |
| `unpush` | `--project NAME` `--subdir SUBDIR` | Remove entry. No-op if absent. Index regen. Feedback rows untouched. |
| `start` | `[--port N=9099]` `[--expose]` | Boot daemon, write pid + port files, regen index. Idempotent. `--expose` chains to `expose`. |
| `expose` | none | Run `tailscale serve --bg --https=443 http://127.0.0.1:<port>`. Needs daemon running. Errors if `tailscale` not on PATH, daemon offline, or tailnet Serve feature not enabled. |
| `unexpose` | none | Run `tailscale serve --https=443 off`. Idempotent. |
| `status` | none | Print pid, port, local URL, tailnet URL (if exposed), mounted `<project>/<subdir>` list. |
| `stop` | none | Kill daemon, run `unexpose`, clear pid/port files. Staging dirs intact. Feedback DB untouched. |
| `clean` | `--project NAME` (req) | Remove `/tmp/claude-artifacts/<project>/` + entries. Refuses w/o `--project` (no global wipe). Feedback DB untouched. |
| `feedback` | `--artifact ID` (req) | Print JSON dump of comments + upload metadata for one artifact, across all sub-paths. Includes `pushes` (all `(project, subdir, src_path, last_pushed)` rows pointing at this artifact_id) and `comments` (each w/ uploads array). |
| `name` | `[VALUE]` `[--clear]` | Get / set / clear the global default comment-author name. 0 args → print current. 1 arg → upsert. `--clear` → delete row. Stored in `setting` k/v table. Widget pre-fills the name input from `/_/api/settings`; server stamps default when form-author is empty. Max 80 chars. |

## Examples

```bash
# Stage two dirs under one project, both tied to one artifact id
as push --project bhwf --src /home/nikki/Git/bhwf/mockups --id cool-beaming-rivest-cd9eb3
as push --project bhwf --src /home/nikki/Git/bhwf/.pipeline/runs/cool-beaming-rivest-cd9eb3 \
        --as run-report --id cool-beaming-rivest-cd9eb3

# Boot + expose
as start --port 9099 --expose

# Rename the subdir on push
as push --project bhwf --src /tmp/build-output --as latest-build

# Inspect
as status

# Pull feedback for one artifact (agent path)
as feedback --artifact cool-beaming-rivest-cd9eb3

# Tear down
as unexpose
as stop
as clean --project demo
```

## Comments + uploads (article model)

Every `text/html` response from a pushed artifact is rewritten on the fly: server appends a `<section id="artifact-serve-comments">` block before `</body>`. Block holds:

- existing comments for `(artifact_id, sub_path)` in chronological order
- form: optional name, comment textarea, multi-file picker, submit button

On submit, form POSTs `multipart/form-data` to `/_/api/comments`. Server resolves `(artifact_id, sub_path)` from the `url` field, stores comment + uploads, returns JSON 201. Widget re-fetches the comment list in place.

### Keying

- `artifact_id` = whatever the agent passed on `push --id`, fallback `<project>/<subdir>`.
- `sub_path` = URL path under the artifact root, e.g. `families/hud-combat.html`. Empty string for artifact-root pages.
- Different sub-paths of one artifact have separate comment threads. Agent retrieval via `feedback --artifact` returns ALL sub_paths grouped.

### Upload rules

- Max **100 MB per file**. Max **500 MB per request** (sum of fields + files).
- Allowed extensions: `.png .jpg .jpeg .webp .gif .bmp .tif .tiff .pdf .txt .md .log .csv .json .yaml .yml .toml .zip .tar .gz .7z .fig .psd .xcf .sketch .mp4 .webm .mov`
- Hard-blocked: `.exe .dll .sh .bash .zsh .bat .cmd .ps1 .js .mjs .html .htm .xhtml .svg .com` (executable + script-injection risk)
- Filename sanitized: basename only, non-`[A-Za-z0-9._-]` collapsed to `_`, truncated to 200 chars, leading dots stripped.
- Collision: auto-suffix `-1`, `-2`, … against existing files in the comment's upload dir.

## API endpoints

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/_/api/comments?url=<page-url>` | none | `{artifact_id, sub_path, comments: [{id, body, author, created_at, uploads: [{id, filename, size, mime}]}]}` |
| GET | `/_/api/comments?artifact=<id>` | none | as above; sub_path empty unless rows exist |
| POST | `/_/api/comments` | multipart/form-data: `url` OR `artifact`, `body` (req), `author` (opt), `files` (opt, multi) | `{id, artifact_id, sub_path, uploads: [{filename, size, mime}]}` (201) |
| GET | `/_/api/uploads/<id>` | none | upload bytes; `Content-Disposition: inline` for images/PDFs, `attachment` for everything else |
| GET | `/_/api/settings` | none | `{key: value, ...}` — current keys in the `setting` table. Widget reads `author` to pre-fill the name input. |

## Schema

```sql
CREATE TABLE artifact_index (
    project     TEXT NOT NULL,
    subdir      TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    src_path    TEXT NOT NULL,
    last_pushed INTEGER NOT NULL,
    PRIMARY KEY (project, subdir)
);

CREATE TABLE comment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    sub_path    TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    author      TEXT,
    created_at  INTEGER NOT NULL
);

CREATE TABLE upload (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id  INTEGER NOT NULL REFERENCES comment(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT,
    size        INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE TABLE setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

## Server behaviour

- Single stdlib `http.server.SimpleHTTPRequestHandler` subclass.
- Bind: `127.0.0.1:<port>` only. Tailscale daemon proxies inbound; no OS firewall hole needed.
- `socketserver.TCPServer` subclass w/ `allow_reuse_address = True`.
- Daemonization: `os.fork()`. Parent writes pid file + exits 0. Child closes stdin/stdout/stderr, redirects diagnostics to `.serve.log`.
- Idempotent `start`: read pid file → `os.kill(pid, 0)` liveness check → alive on same port → print URL, exit 0.
- Auto-regen `index.html` at server root. Rebuilt on `start`, `push`, `unpush`. Plain HTML, inline `<style>`, dark theme, no JS. One tile per `<project>/<subdir>`: project, subdir, symlink target (via `os.readlink`), entry mtime, file count.
- HTML injection: `send_head` reads body, splices feedback block before `</body>`, returns mutated BytesIO. `Content-Length` suppressed on `text/html` responses (server sends via HTTP/1.0 close-framing).
- Multipart parsing: stdlib-only (Python 3.13 dropped `cgi`). Hand-rolled boundary-split parser in `parse_multipart_form()`. Loads entire request body in memory — request cap 500 MB.

## Path resolution

- URL traversal blocked by stdlib `SimpleHTTPRequestHandler.translate_path` URL normalization (`..` segments collapsed before filesystem access).
- Symlink **targets** NOT sandboxed. Push of `/home/user/repo/mockups` makes entire `/home/user/repo/mockups/...` subtree reachable. Intentional — you pushed it.
- Daemon root: `/tmp/claude-artifacts/`. URLs cannot reach files outside that tree unless via pushed symlink target.

## Security caveats (full)

1. **Tailscale exposure is tailnet-wide.** `expose` publishes served root to every tailnet device over HTTPS. Persists until `unexpose` or `tailscaled` restart. Anyone w/ tailnet key reads every pushed artifact **and can post comments + uploads**.
2. **No symlink-target sandbox.** Pushing parent dir of secrets exposes secrets. Push narrowly.
3. **`/tmp/` wipes on reboot.** All `.serve.pid`, `.serve.port`, staged dirs vanish. Feedback DB at `~/.local/share/` survives.
4. **No auth, no access control.** Single-user assumption. Shared NixOS box → gate exposure behind `unexpose` between sessions. Anyone on tailnet can POST comments anonymously.
5. **Log retention.** `.serve.log` records every request path. Wipes w/ `/tmp/` on reboot. Inspect: `tail -f /tmp/claude-artifacts/.serve.log`.
6. **Upload disk usage unbounded.** Feedback uploads accumulate at `~/.local/share/claude-artifacts/uploads/`. No auto-cleanup. Remove per-comment dirs manually or wipe entire `uploads/` when reviewing is done.
7. **No CSRF guard on POST.** Browser on the tailnet can be tricked into POSTing comments. Low risk on a single-user tailnet; consider before exposing to a multi-user tailnet.

## Exit codes

- `0` — success / no-op
- `1` — caller error (bad flags, missing `--project`, source path absent, bad name regex)
- `2` — server error (port bound by other process, fork failed, tailscale call failed)

## Setup

One-time, after first stow / clone:

```bash
chmod +x ~/.claude/skills/artifact-serve/scripts/artifact-serve.py
```

(`Write` tool authoring this skill can't set execute bit. Script also runs via explicit `python3 <path>`.)

For Tailscale HTTPS exposure (one-time, requires sudo):

```nix
# /etc/nixos/configuration.nix
services.tailscale = {
  enable = true;
  openFirewall = true;
  permitCertUid = "<your-user>";   # grants HTTPS cert provisioning
};
```

```bash
sudo nixos-rebuild switch
sudo tailscale up --operator=$USER --ssh   # grants IPN bus access
# enable Serve feature once on https://login.tailscale.com/admin/serve
```

After that, `as expose` works as user.
