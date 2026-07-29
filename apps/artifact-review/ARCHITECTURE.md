# Architecture

The current contract of the shipped `apps/artifact-review/` service: publish
flow, storage roots, and sandbox policy.

The artifact review app is now the containerized `apps/artifact-review/`
service. The old bare-host implementation, vendored assets, quadlet, and
direct script verbs are retired.

## Current Contract

The host CLI is a stdlib HTTP client:

- `agent-workbench artifact publish`
- `agent-workbench artifact feedback`
- `agent-workbench artifact status`

Service lifecycle belongs to compose or deploy tooling.

## Publish Flow

`publish` reads a local file or directory, creates an uncompressed tar in
memory, and sends it to:

```text
POST /_/api/publish
```

The CLI never writes into the artifact store. The service extracts safe
regular files and directories under:

```text
/tmp/artifacts
```

Durable feedback and uploads live under:

```text
$HOME/.local/share/artifacts
```

## Review Flow

Reviewer surfaces stay under `/_/review` and call the service APIs for
threads, replies, resolve state, uploads, settings, and artifact lists. The
service owns all filesystem access and must validate paths before reading or
writing.

## Safety

The service rejects unsafe tar paths and non-regular archive members. Raw
artifact routes must keep the active-content sandbox policy so uploaded HTML
or SVG cannot script the no-auth review origin.
