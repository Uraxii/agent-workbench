# artifact-serve container

Container packaging of `artifact-serve.py`.

## Files

- `Containerfile` — builds the image (`python:3.13-slim`, stdlib-only, no
  `pip install`).

## Build and run

The repo-root `docker-compose.yml` builds and runs this service. From the repo
root:

```bash
podman-compose up -d artifact-serve    # or: docker compose up -d artifact-serve
```

See the repo-root README for the fresh-machine install sequence. The systemd
user quadlet that used to live here has been deleted; compose is the only
deploy path.

## Mounts and their security note

> The mount table, the `--userns keep-id` note, and the `Network=host` note
> below describe the retired quadlet deploy. `docker-compose.yml` makes
> different choices (a narrower mount set with no `~` mount, a `user:` line
> instead of `keep-id`, and a published `127.0.0.1:9099:9099` port instead of
> host networking). Reconciling this section with what compose actually does
> belongs to the container workstream, not the portability one; the analysis
> is kept because the reasoning it records is still the reasoning that has to
> be answered.

artifact-serve stages every artifact into `/tmp/claude-artifacts/<project>/`
as a **symlink** pointing at the real file elsewhere on disk (see
`artifact-serve.py push`). A container can only resolve those symlinks if the
real targets are reachable at the identical absolute path inside the
container, so:

| Mount | Path | Mode | Why |
|---|---|---|---|
| staging root | `/tmp/claude-artifacts` | rw | where artifacts get symlinked in; also the pid/port/log bookkeeping files |
| feedback store | `~/.local/share/claude-artifacts` | rw | durable sqlite feedback DB + uploaded review files |
| home directory | `~` | ro | symlink targets live under here (`~/Projects/...`, `~/comfy/...`); mounting the whole home dir is the pragmatic choice over enumerating every project root the symlinks currently point into |

**Security implication**: the `~` ro mount gives the container read access to
everything under the home directory, not just the artifact source trees
currently staged. A compromise of artifact-serve (a bug in its request
handling, or a malicious upload) could read any file under `~`. If that
blast radius is unacceptable, narrow the mount to the specific project roots
the symlinks point into (see `artifact-serve.py status` for the current list)
instead of the whole home directory.

The container also runs `--userns keep-id --user <uid>:<uid>` so files it
writes into the two `rw` mounts come out owned by the real host user, not
container root or a shifted subuid range. SELinux (enforcing on this host)
would otherwise deny the broad `~` mount, or force a slow, invasive
recursive relabel of the whole home directory; the quadlet disables the
SELinux label check for this one container instead
(`SecurityLabelDisable=true`) as the trade-off that goes with the
host-FS-exposed-read-only design above.

## Networking

`artifact-serve.py`'s server hardcodes its bind address to `127.0.0.1` (see
`_serve_forever`). Verified on this host: a server bound only to `127.0.0.1`
inside a container is unreachable through Podman's normal port-publish path
(`PublishPort=`, backed by pasta/slirp4netns), because that path delivers
inbound traffic over the container's NAT-facing interface, not its loopback.
Changing the app's bind address was out of scope for this container work, so
the quadlet uses `Network=host` instead: the container shares the host
network namespace, so the app's own `127.0.0.1:9099` bind **is** the host's
`127.0.0.1:9099`, with no port mapping involved. Net exposure is identical
either way — the app only ever answers on loopback because of its own
hardcoded bind; `Network=host` does not add any new externally reachable
surface, it just makes the existing loopback-only bind reachable at all.

Tailscale stays entirely a **host** concern — it is never run inside the
container. To publish the container over the tailnet, run on the host:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9099
```

The app's own `expose`/`unexpose` verbs still work for this (they just shell
out to the `tailscale` CLI), but only when run directly on the host, not
inside the container image (no tailscale binary is installed there).

## Foreground mode (`run` verb)

artifact-serve's normal `start` verb forks + writes a pidfile (a CLI daemon
model). Containers and systemd want a single foreground process they
supervise directly, so a new `run` verb was added: same server, no fork, no
`setsid`, no pidfile — it blocks in the foreground until SIGTERM/SIGINT,
logging to stdout (captured by `podman logs` / `journalctl --user`). This is
the only code change made to `artifact-serve.py` for containerization.

## Bare-to-container cutover

1. Build the image and install the quadlet (above).
2. Stop the bare instance with its own `stop` verb:
   ```bash
   /path/to/repo/.claude/skills/artifact-serve/scripts/artifact-serve.py stop
   ```
   Note: `stop` also runs `tailscale serve --https=443 off` as part of its
   normal shutdown — re-run the `tailscale serve --bg ...` command above
   once the container is up, to point port 443 back at 9099.
3. `systemctl --user start artifact-serve` (or let the already-running unit
   take over the now-free port).
4. Verify: `curl http://127.0.0.1:9099/`, an artifact URL, and that
   `systemctl --user restart artifact-serve` survives cleanly.
