# Artifact Review Container

This directory builds the `localhost/artifact-review:latest` image used by the
`artifact-svc` compose service. The image contains the Django backend, a
production React/Vite SPA bundle served by Django, and gunicorn.

Build the runtime image:

```sh
podman build -f Containerfile -t localhost/artifact-review:latest .
```

Run backend tests inside the image build:

```sh
podman build --target test -f Containerfile .
```

Run the service directly:

```sh
podman run --rm -p 127.0.0.1:9099:9099 \
  -e ARTIFACT_SVC_HOST=0.0.0.0 \
  -e ARTIFACT_SVC_PORT=9099 \
  -e ARTIFACT_SVC_ALLOWED_HOSTS=127.0.0.1,localhost \
  -v /tmp/artifacts:/tmp/artifacts:rw \
  -v "$HOME/.local/share/artifacts:$HOME/.local/share/artifacts:rw" \
  --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges:true \
  localhost/artifact-review:latest
```

Environment variables:

- `ARTIFACT_SVC_HOST`: host setting read by Django. Compose sets `0.0.0.0`.
- `ARTIFACT_SVC_PORT`: gunicorn and healthcheck port. Defaults to `9099`.
- `ARTIFACT_SVC_ALLOWED_HOSTS`: comma-separated Django allowed hosts.
- `ARTIFACT_SVC_STAGE_ROOT`: published artifact root. Defaults to `/tmp/artifacts`.
- `ARTIFACT_SVC_FEEDBACK_ROOT`: sqlite feedback and upload root. Defaults to `~/.local/share/artifacts`.
- `ARTIFACT_SVC_SPA_ROOT`: built SPA root. Defaults to `backend/spa` inside the app.
- `ARTIFACT_SVC_ASSETS_ROOT`: backend asset root.
- `ARTIFACT_SVC_PUBLISH_ENABLED`: set `0` to disable HTTP publishing.
- `DJANGO_DEBUG`: baked as `0` in the image.
- `DJANGO_SECRET_KEY`: optional. If unset, Django generates an ephemeral key at startup.

## Running one-off commands against the image

The runtime image uses an exec-form entrypoint that runs gunicorn directly. To
override this and run a different command, use `--entrypoint`:

```sh
podman run --rm --entrypoint python3 localhost/artifact-review:latest -c 'print("hello")'
```

## Running backend tests

Backend tests are deliberately absent from the production runtime image (pytest
is installed only in the `test` build target). Run tests during the image build:

```sh
podman build --target test -f Containerfile .
```
