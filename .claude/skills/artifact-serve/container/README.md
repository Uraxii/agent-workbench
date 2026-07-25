# review-serve container

Rootless-podman packaging of `review-serve.py` for durable, boot-surviving
deployment via a systemd user quadlet.

## Files

- `Containerfile` — builds the image (`python:3.13-slim`, stdlib-only, no
  `pip install`).
- `review-serve.container` — the quadlet unit. Tracked copy; the install
  target is `~/.config/containers/systemd/review-serve.container` (see
  Install below).

## Build

```bash
cd /path/to/repo/.claude/skills/artifact-serve
podman build -t localhost/review-serve:latest -f container/Containerfile .
```

## Install the quadlet

```bash
mkdir -p ~/.config/containers/systemd
cp /path/to/repo/.claude/skills/artifact-serve/container/review-serve.container \
   ~/.config/containers/systemd/review-serve.container
systemctl --user daemon-reload
systemctl --user start review-serve
```

The unit carries `WantedBy=default.target`, so quadlet auto-wires it into
`default.target.wants` on every `daemon-reload`/boot — no separate
`systemctl enable` needed. It also needs `loginctl enable-linger $USER` (a
one-time, already-done step on this host) so the user's systemd instance
keeps running, and the container with it, without an active login session.

Re-run the `cp` + `daemon-reload` after any edit to the tracked quadlet file;
the `~/.config/containers/systemd/` copy is the live one, not a symlink to
the repo.

## Mounts and their security note

review-serve stages every artifact into `/tmp/claude-artifacts/<project>/`
as a **symlink** pointing at the real file elsewhere on disk (see
`review-serve.py push`). A container can only resolve those symlinks if the
real targets are reachable at the identical absolute path inside the
container, so:

| Mount | Path | Mode | Why |
|---|---|---|---|
| staging root | `/tmp/claude-artifacts` | rw | where artifacts get symlinked in; also the pid/port/log bookkeeping files |
| feedback store | `~/.local/share/claude-artifacts` | rw | durable sqlite feedback DB + uploaded review files |
| home directory | `~` | ro | symlink targets live under here (`~/Projects/...`, `~/comfy/...`); mounting the whole home dir is the pragmatic choice over enumerating every project root the symlinks currently point into |

**Security implication**: the `~` ro mount gives the container read access to
everything under the home directory, not just the artifact source trees
currently staged. A compromise of review-serve (a bug in its request
handling, or a malicious upload) could read any file under `~`. If that
blast radius is unacceptable, narrow the mount to the specific project roots
the symlinks point into (see `review-serve.py status` for the current list)
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

`review-serve.py`'s server hardcodes its bind address to `127.0.0.1` (see
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

review-serve's normal `start` verb forks + writes a pidfile (a CLI daemon
model). Containers and systemd want a single foreground process they
supervise directly, so a new `run` verb was added: same server, no fork, no
`setsid`, no pidfile — it blocks in the foreground until SIGTERM/SIGINT,
logging to stdout (captured by `podman logs` / `journalctl --user`). This is
the only code change made to `review-serve.py` for containerization.

## Bare-to-container cutover

1. Build the image and install the quadlet (above).
2. Stop the bare instance with its own `stop` verb:
   ```bash
   /path/to/repo/.claude/skills/artifact-serve/scripts/review-serve.py stop
   ```
   Note: `stop` also runs `tailscale serve --https=443 off` as part of its
   normal shutdown — re-run the `tailscale serve --bg ...` command above
   once the container is up, to point port 443 back at 9099.
3. `systemctl --user start review-serve` (or let the already-running unit
   take over the now-free port).
4. Verify: `curl http://127.0.0.1:9099/`, an artifact URL, and that
   `systemctl --user restart review-serve` survives cleanly.
