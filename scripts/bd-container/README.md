# bd-svc

`bd-svc` is the local HTTP service that owns the bd board hub under
`$BEADS_HUB_DIR` or `$HOME/.beads-hub`. The host CLI talks to this service;
the service is the only component that runs the `bd` binary.

## Build

```bash
podman build -f scripts/bd-container/Containerfile -t localhost/bd-svc:latest scripts
```

## Run

```bash
podman run --rm \
  -p 127.0.0.1:9101:9101 \
  -e BD_SVC_HOST=0.0.0.0 \
  -e BD_SVC_PORT=9101 \
  -e HOME=/tmp \
  -e BEADS_HUB_DIR="$HOME/.beads-hub" \
  -v "$HOME/.beads-hub:$HOME/.beads-hub:rw" \
  localhost/bd-svc:latest
```

## Environment

- `BD_SVC_HOST`: bind host, default `127.0.0.1`
- `BD_SVC_PORT`: bind port, default `9101`
- `BEADS_HUB_DIR`: board hub root, default `$HOME/.beads-hub`. Set it to the
  HOST path and bind-mount that same path, so absolute board paths stored in
  the aggregator resolve identically inside and outside the container.
- `HOME`: keep this pointed at a writable throwaway dir (`/tmp`, backed by a
  tmpfs) rather than the host home. `bd` wants a writable home for its own
  config and cache, and the container runs with a read-only root filesystem.

## Request shape and validation

Every endpoint is a named operation with typed parameters; there is no verb
that accepts a command string, an argv array, or a flag list. The service
builds the `bd` argument list itself and never uses a shell. Board names,
issue ids and labels must match strict patterns that start with an
alphanumeric, so a value beginning with `-` can never reach `bd`'s flag
parser. Rejected input returns `400`; a failing `bd` returns `502` carrying
its exit code and stderr.

The port is unauthenticated, so requests that look like they came from a web
page are refused with `403`: anything carrying an `Origin` header, anything
whose `Host` is not a loopback literal (the DNS-rebinding shape), and any
`POST` without `Content-Type: application/json` (which is what forces a
cross-origin attempt through a preflight this service never answers).

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | service health and hub status |
| POST | `/hub/init` | initialize the aggregator board |
| POST | `/hub/add` | create and register a board |
| POST | `/hub/sync` | sync registered repos |
| POST | `/hub/repos` | list registered repos |
| POST | `/hub/path` | return a board path |
| POST | `/hub/status` | return hub root, initialized flag, and repos |
| POST | `/issue/list` | list issues |
| POST | `/issue/show` | show an issue |
| POST | `/issue/create` | create an issue |
| POST | `/issue/update` | update an issue |
| POST | `/issue/close` | close an issue |
| POST | `/issue/note` | add an issue note |
| POST | `/issue/link` | link issues |
| POST | `/issue/children` | list child issues |
| POST | `/issue/priority` | set issue priority |
