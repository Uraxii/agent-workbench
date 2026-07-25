---
name: artifact-serve
description: Publish images, renders, mockups, galleries, or HTML reports to the self-hosted review app (OpenSeadragon deep-zoom + Annotorious region pins + threaded, resolvable comments) and share the VIEWER URL for a human to review, never a raw file link. Use WHENEVER you generate visual output for the user to look at or give feedback on, when you need a human taste gate on renders/mockups, or to serve a report over Tailscale. Bundles the server + how to deploy it (rootless-podman container, or a bare daemon) if none is running. Read reviewer feedback back as JSON via `feedback --artifact <id>`.
---

# artifact-serve (review app)

Serve generated artifacts for review in a browser: high-res deep-zoom images
with click-to-pin region annotations, threaded comments, resolve/unresolve, and
per-line code comments. Stdlib-python daemon, optional Tailscale HTTPS, durable
sqlite feedback the agent reads back. Linear-themed with a light/dark/auto
toggle.

Scripts + container live beside this skill:
`~/.claude/skills/artifact-serve/scripts/review-serve.py` and
`~/.claude/skills/artifact-serve/container/`.

## Golden rule: share the VIEWER url, never a raw link

When you make images/renders/mockups for the user, do NOT paste a raw file path
or a bare `.png` link. Push the artifact, then hand over the **viewer URL** so
they land in the deep-zoom + pin UI:

```
https://<tailnet-host>/_/review?artifact=<id>&src=<image>&view=image
```

The gallery for a whole pushed dir is `/_/review?artifact=<id>` (thumbnails that
open the viewer). Code files use `...&view=code` (per-line comments).

## Step 0: is a server already running?

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9099/    # 200 = up
systemctl --user is-active review-serve                            # container instance?
```

If it answers 200, skip to Publish. If NOT, deploy one (next section).

## Deploy a server (only if none is running)

Preferred: rootless-podman container, durable across reboot (systemd quadlet).
Exact build + install steps are in
`~/.claude/skills/artifact-serve/container/README.md`; short form:

```bash
# build the image + install the quadlet (see container/README.md for the exact context path)
podman build -t review-serve -f ~/.claude/skills/artifact-serve/container/Containerfile ...
cp ~/.claude/skills/artifact-serve/container/review-serve.container ~/.config/containers/systemd/
systemctl --user daemon-reload && systemctl --user start review-serve
```

Bare daemon (no container), fine for a quick one-off:

```bash
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py start [--expose]
```

Expose over Tailscale (host-level; the container path keeps this on the host):

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9099
```

> WARNING: expose publishes over the WHOLE tailnet with read AND write (anyone
> on the tailnet can view and post). Do not push parent dirs of secrets; the
> server follows pushed symlinks. `review-serve.py stop` also runs
> `tailscale serve --https=443 off` as a side effect, tearing down the 443
> mapping; for the container prefer `systemctl --user restart review-serve`.

## Publish

```bash
RS=~/.claude/skills/artifact-serve/scripts/review-serve.py
python3 $RS push --project NAME --src /path/to/dir --id <artifact-id>   # symlinks, never copies
python3 $RS start                                                       # idempotent
# share: http://127.0.0.1:9099/_/review?artifact=<artifact-id>
```

Verbs: `push unpush start run expose unexpose status stop clean feedback name`.
`run` is the container foreground entry point; `name` sets your default comment
author.

## Read reviewer feedback back

```bash
python3 ~/.claude/skills/artifact-serve/scripts/review-serve.py feedback --artifact <id>
```

Returns JSON `{artifact_id, pushes[], threads[], comments[]}`. Each thread
carries its anchor (image-region pin coords / code line / page), `resolved`
state, and nested `replies[]` with any uploads. This is how you consume the
human's pins + comments after they review.

## Notes

- Feedback DB + uploads are durable at `~/.local/share/claude-artifacts/`; the
  staging root `/tmp/claude-artifacts/` wipes on reboot (re-push after).
- Uploads: extension allowlist (img/pdf/text/zip/fig/psd/mp4), size caps;
  `.svg/.html/.js` blocked. Attacker-supplied `SvgSelector` anchors are rejected
  server-side.
- Full API + security detail: [REFERENCE.md](REFERENCE.md). Container specifics:
  [container/README.md](container/README.md).
