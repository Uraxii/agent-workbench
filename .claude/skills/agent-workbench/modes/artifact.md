# agent-workbench: artifact mode

Use the containerized artifact review service through the agent-workbench CLI.
The CLI is an HTTP client only. It does not start the service, stage files in
the artifact store, manage Tailscale exposure, or fall back to local disk.

## Service

Start and stop the service with the stack tooling:

```bash
podman-compose -f docker-compose.yml up -d artifact-svc
# or: docker-compose -f docker-compose.yml up -d artifact-svc
$HOME/.claude/skills/agent-workbench/agent-workbench artifact status
```

The artifact client talks to:

- `ARTIFACT_SVC_URL`, when set.
- Otherwise `http://$ARTIFACT_SVC_HOST:$ARTIFACT_SVC_PORT`.
- Defaults: `127.0.0.1` and `9099`.

If the service is down or returns bad data, the command exits non-zero and
prints the failed verb, full URL, and underlying error to stderr. There is no
filesystem fallback.

## Never verify against the live stack

Never probe the live artifact-svc (port 9099, the real
`~/.local/share/artifacts`, which holds both the staged tree under
`stage/` and the feedback database) to verify a change works --
that leaves permanent residue in the real artifact store. See `SKILL.md`
for the ephemeral-service verification rule and how to invoke it
(`scripts/ephemeral-service.py artifact -- ...`) from a repo checkout;
`--help` documents the mechanics.

## Publish

Publish a file or directory as a new artifact for review.

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW artifact publish --project NAME --src /path/to/file-or-dir
```

`publish` reads the local file or directory, builds an uncompressed tar in
memory, and posts it to `POST /_/api/publish`.

#### Flags

- `--project NAME` (required): Project identifier (alphanumeric, dots, hyphens, underscores).
- `--src PATH` (required): Local file or directory to publish. A single file is sent as one tar member named after that file. A directory is sent as a tar tree with paths relative to that directory. Symlinks and unsafe paths are not emitted.
- `--as SUBDIR` (optional): Artifact name within the project. Defaults to the basename of `--src`.
- `--id ARTIFACT_ID` (optional): Stable artifact ID for feedback correlation. Default: `<project>/<subdir>`.
- `--force` (optional): Overwrite an existing artifact without prompting. Omit to reject republish attempts with `409 Conflict: artifact_exists`.

#### Response

Successful publish (201):
```json
{
  "artifact_id": "doctest/file.txt",
  "bytes": 8,
  "files": 1,
  "project": "doctest",
  "replaced": false,
  "subdir": "file.txt",
  "url": "/doctest/file.txt/"
}
```

Republish without `--force` (409):
```
artifact publish failed for http://127.0.0.1:9099/_/api/publish: HTTP 409 Conflict: artifact_exists
```

Republish with `--force` (201, `"replaced": true`):
```json
{
  "artifact_id": "doctest/file.txt",
  "bytes": 8,
  "files": 1,
  "project": "doctest",
  "replaced": true,
  "subdir": "file.txt",
  "url": "/doctest/file.txt/"
}
```

## Feedback

Read feedback threads (comments and replies) for an artifact.

```bash
$AW artifact feedback --artifact ID
```

Calls `GET /_/api/threads?artifact=ID` (with optional filters).

#### Flags

- `--artifact ID` (required): Artifact ID to query (e.g., `myproject/mysubdir`).
- `--sub-path PATH` (optional): Filter to a specific sub-path. Takes precedence over default. Example: `--sub-path pages/about`.
- `--all-paths` (optional): Return threads from all sub-paths. Mutually exclusive with `--sub-path`. Default behavior (neither flag): filter to root sub-path only (`sub_path=""`).

#### Response

Successful query with default flags (`sub_path=""`):
```json
{
  "artifact_id": "doctest/file.txt",
  "sub_path": "",
  "threads": [
    {
      "anchor": null,
      "anchor_kind": "page",
      "author": "agent",
      "bd_ticket": null,
      "created_at": 1785255214,
      "created_at_iso": "2026-07-28T16:13:34Z",
      "id": 5,
      "replies": [
        {
          "author": "agent",
          "body": "Example feedback",
          "created_at": 1785255214,
          "created_at_iso": "2026-07-28T16:13:34Z",
          "id": 6,
          "uploads": []
        }
      ],
      "resolved": true,
      "sub_path": ""
    }
  ]
}
```

Unknown artifact (404):
```
artifact feedback failed for http://127.0.0.1:9099/_/api/threads?artifact=nonexistent&sub_path=: HTTP 404 Not Found: unknown_artifact
```

## Comment

Create a feedback thread (initial comment) on an artifact.

```bash
$AW artifact comment --artifact ID --body TEXT
```

Posts to `POST /_/api/threads`.

#### Flags

- `--artifact ID` (required): Artifact ID (e.g., `myproject/mysubdir`).
- `--body TEXT` (required): Comment text.
- `--sub-path PATH` (optional): Sub-path anchor for the thread. Default: empty (root level).
- `--author NAME` (optional): Comment author name.
- `--anchor-kind KIND` (optional): Anchor type (e.g., `page`, `heading`). Default: `page`.

#### Response

```json
{
  "anchor_kind": "page",
  "artifact_id": "doctest/file.txt",
  "reply_id": 6,
  "sub_path": "",
  "thread_id": 5,
  "uploads": []
}
```

## Reply

Add a reply to an existing feedback thread.

```bash
$AW artifact reply --thread N --body TEXT
```

Posts to `POST /_/api/threads/<N>/replies`.

#### Flags

- `--thread N` (required): Thread ID (integer).
- `--body TEXT` (required): Reply text.
- `--author NAME` (optional): Reply author name.

#### Response

```json
{
  "reply_id": 7,
  "thread_id": 5,
  "uploads": []
}
```

## Resolve

Mark a feedback thread as resolved or reopen it.

```bash
$AW artifact resolve --thread N
```

Posts to `POST /_/api/threads/<N>/resolve`.

#### Flags

- `--thread N` (required): Thread ID (integer).
- `--reopen` (optional): Reopen a resolved thread. Default (no flag): mark as resolved.

#### Response

Resolve:
```json
{
  "id": 5,
  "resolved": true
}
```

Reopen:
```json
{
  "id": 5,
  "resolved": false
}
```

## Status

Check service health and list all artifacts.

```bash
$AW artifact status
```

Calls `GET /_/health` and `GET /_/api/artifacts`.

#### Response

```json
{
  "endpoint": "http://127.0.0.1:9099",
  "health": {
    "status": "ok"
  },
  "artifacts": [
    {
      "artifact_id": "doctest/file.txt",
      "entry_count": 1,
      "last_pushed": 1785255411,
      "last_pushed_iso": "2026-07-28T16:16:51Z",
      "project": "doctest",
      "subdir": "file.txt"
    }
  ]
}
```

## Deletion

Deletion is not provided as a CLI verb. To remove an artifact, use filesystem operations
as a human out-of-band process. All artifact storage paths and metadata are listed below.

### Published artifact tree

The published artifact tree is stored at
`$HOME/.local/share/artifacts/stage/{project}/{subdir}`.

Remove with:
```bash
rm -rf "$HOME/.local/share/artifacts/stage/e2e/tree"
```

Note: The artifact_index row and all feedback threads survive the tree deletion. To
fully clean an artifact, perform the following additional steps.

### Clear the artifact index entry

The database is stored at `$HOME/.local/share/artifacts/feedback.db`.

Remove the index row:
```bash
sqlite3 "$HOME/.local/share/artifacts/feedback.db" \
  "DELETE FROM artifact_index WHERE project='e2e' AND subdir='tree';"
```

### Clear feedback threads (optional)

To also remove all feedback threads and replies for that artifact:
```bash
sqlite3 "$HOME/.local/share/artifacts/feedback.db" \
  "DELETE FROM thread WHERE artifact_id='e2e/tree';"
```

### Existing test residue

The following test artifacts are present and may be removed or left as-is:

- `xss/probe` — XSS injection test artifact
- `e2e/single` — Single-file end-to-end test
- `e2e/tree` — Multi-file directory tree test

Use the commands above (substituting your project/subdir) to clean them up.

## Storage Paths

- Published artifacts: `$HOME/.local/share/artifacts/stage`
- Feedback database: `$HOME/.local/share/artifacts/feedback.db`
- Uploaded files: `$HOME/.local/share/artifacts/uploads/`

No old artifact data is migrated.

## Removed Verbs

The old bare-host server and its CLI verbs were retired:

```text
push unpush start stop status expose unexpose clean run feedback name
```

Only the agent-workbench artifact subcommands remain:

```text
publish feedback comment reply resolve status
```
