# agent-workbench container hardening plan

Current stack hardening applies to domain services behind HTTP. The host CLI is
a stdlib Python client and does not own service files on disk.

## Shared Rules

- Publish host ports on loopback only.
- Run rootless.
- Use a read-only root filesystem.
- Drop all Linux capabilities.
- Set no-new-privileges.
- Mount only the data roots the service owns.
- Keep service shutdown separate from host Tailscale Serve mappings.

## Knowledgebase

The kb service keeps its existing container hardening shape:

- `KB_HOME=$HOME/.knowledgebase`
- service port `9100`
- loopback host publish
- writable vault mount only

## Artifact Review

The old bare-host artifact service and quadlet are retired. Artifact review
is served by the `apps/artifact-review/` service.

The artifact service owns:

- `/tmp/artifacts`
- `$HOME/.local/share/artifacts`

The artifact CLI does not stage by symlink, start a daemon, expose Tailscale,
or stop the service. It calls:

- `POST /_/api/publish`
- `GET /_/api/threads?artifact=<id>`
- `GET /_/health`
- `GET /_/api/artifacts`

Required artifact container controls:

| Control | Requirement |
|---|---|
| Host bind | Publish only `127.0.0.1:9099:9099`. |
| Root filesystem | Read-only. |
| Capabilities | Drop all. |
| Privilege escalation | Disabled with no-new-privileges. |
| Mounts | `/tmp/artifacts:/tmp/artifacts:rw` and `$HOME/.local/share/artifacts:$HOME/.local/share/artifacts:rw`. |
| Healthcheck | GET `http://127.0.0.1:9099/_/health`. |
| Publish handling | Service validates tar member paths and types before extracting. |

## Tailscale

Host exposure stays explicit:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9099
```

No app, deploy, or CLI stop path should run:

```bash
tailscale serve --https=443 off
```
