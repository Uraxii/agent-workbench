# CLAUDE

Agent-facing notes for this repo. `CONTRIBUTING.md` carries the test commands
and the load-bearing architecture constraints; they are not repeated here.

## Rebuild AND redeploy after changing source

A change to source that ships in a container image is not done until the image
is rebuilt *and* the container is recreated:

```bash
podman-compose build <svc>
podman-compose up -d --force-recreate <svc>
```

`--force-recreate` is not optional. Plain `up -d` restarts a merely *stopped*
container on its OLD image, and because every service pins the mutable
`:latest` tag, `podman ps` keeps printing the expected tag name while the
container runs stale code. This has already caused one incident: a migrated
data store served by a pre-migration image.

Verify by image ID, never by tag name:

```bash
podman inspect agent-workbench_<svc>_1 --format '{{.Image}}'
podman image inspect localhost/<image>:latest --format '{{.Id}}'
```

The two must match. Note the service name and the image name are not always
the same: `artifact-svc` builds `localhost/artifact-review:latest`.

Before rebuilding, tag the current image so rollback is a retag rather than a
rebuild from an older commit:

```bash
podman tag localhost/<image>:latest localhost/<image>:pre-<change>
```

## Reinstall the skill after changing it

Changes under `.claude/skills/agent-workbench/` do not reach the installed copy
on their own:

```bash
.claude/skills/agent-workbench/agent-workbench install --copy
```

Then confirm with `doctor`, which reports `pinned at <repo HEAD>` when the
installed copy is current and warns when it has drifted.
