# agent-workbench: artifact mode

Use the containerized artifact review service through the agent-workbench CLI.
The CLI is an HTTP client only. It does not start the service, stage files in
the artifact store, manage Tailscale exposure, or fall back to local disk.

## Service

Start and stop the service with the stack tooling:

```bash
docker-compose up artifact-review
$HOME/.claude/skills/agent-workbench/agent-workbench deploy status
```

The artifact client talks to:

- `ARTIFACT_SVC_URL`, when set.
- Otherwise `http://$ARTIFACT_SVC_HOST:$ARTIFACT_SVC_PORT`.
- Defaults: `127.0.0.1` and `9099`.

If the service is down or returns bad data, the command exits non-zero and
prints the failed verb, full URL, and underlying error to stderr. There is no
filesystem fallback.

## Publish

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW artifact publish --project NAME --src /path/to/file-or-dir --id <artifact-id>
```

`publish` reads the local file or directory, builds an uncompressed tar in
memory, and posts it to:

```text
POST /_/api/publish
```

Multipart fields:

- `project`
- `as`
- `artifact_id`, when `--id` is supplied
- `archive`, the tar file part

A single file is sent as one tar member named after that file. A directory is
sent as a tar tree with paths relative to that directory. Symlinks and unsafe
paths are not emitted. The service owns all artifact-store writes.

The command prints the service JSON response to stdout.

## Feedback

```bash
$AW artifact feedback --artifact <artifact-id>
```

The CLI calls:

```text
GET /_/api/threads?artifact=<artifact-id>
```

The JSON body is printed unchanged to stdout.

## Status

```bash
$AW artifact status
```

The CLI calls:

```text
GET /_/health
GET /_/api/artifacts
```

It prints JSON containing the endpoint, service health, and current artifact
list.

## Storage Paths

The service owns these paths:

- `/tmp/artifacts`
- `$HOME/.local/share/artifacts`

No old artifact data is migrated.

## Removed Verbs

The old bare-host server and its CLI verbs were retired:

```text
push unpush start stop status expose unexpose clean run feedback name
```

Only the agent-workbench artifact subcommands remain:

```text
publish feedback status
```
