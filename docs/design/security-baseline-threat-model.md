# Security baseline and threat model, rebuilt agent-workbench stack

Status: active, 2026-07-27. Applies to every service in the rebuilt stack.

This is the standing security contract for the stack described in
`~/.knowledgebase/agent-workbench/architecture.md`: several services, one
per domain, each with its own container, port and mount, all reached over
HTTP by the CLI. It states what each service exposes, what an attacker can
do with it, the exact response headers every service must send, the exact
input-validation rules every service must apply, and whether authentication
is still deferrable.

## 1. The premise: loopback is not a security boundary

Every service binds `127.0.0.1` and requires no credential. That is not
isolation. On a multi-process desktop, `127.0.0.1` is reachable by:

- any process running as the same user: a shell one-liner, a `postinstall`
  script from an npm install, an editor extension, an agent-spawned
  subprocess, anything in `$PATH` that someone was tricked into running;
- **a web page in the user's browser.** A tab open on any site can run
  `fetch('http://127.0.0.1:9100/put', ...)` against these ports. The
  same-origin policy limits whether that page can *read* the reply. It does
  not stop the request from arriving and taking effect. Every write
  endpoint is therefore exposed to any site the user visits;
- **a rebound DNS name.** An attacker who controls `evil.example` can point
  it at `127.0.0.1` after the page loads. The browser then treats requests
  to `http://evil.example:9100/` as same-origin with the attacker's page:
  no `Origin` header is sent, the same-origin policy is satisfied, and the
  attacker can read replies as well as write. Only the `Host` header
  distinguishes this from a legitimate call.

So "it is only on loopback" is not a mitigation and must not be cited as
one. Binding to loopback removes the remote network attacker. It removes
nobody else.

## 2. What each service exposes

| Service | Port | Data it owns | Worst thing reachable through it |
|---|---|---|---|
| kb (`scripts/kb-svc.py`) | 9100 | `~/.knowledgebase`, the whole personal vault | Read every note; write arbitrary markdown into the vault; make the server fetch an arbitrary URL (`/clip`, `/atomize`); spend money against the configured LLM key when `KB_ENRICH=1` |
| artifact | 9099 | `~/.local/share/artifacts`, staged review artifacts | Serves attacker-authored HTML and SVG **and** its own review UI. Scripted content from the same origin as the UI is full control of the UI |
| bd | 3100 (bdui today) | `~/.beads-hub`, every board in every project | Read and rewrite issue state across all projects |
| n8n | 5678 | workflow definitions and credentials | Third-party, opt-in, profiled off. Out of scope here beyond "do not treat its port as private" |

Three facts follow. The vault is the user's entire private knowledge base,
so kb read access is the highest-value confidentiality target. The artifact
service is the only one that renders attacker-controlled content, so it is
the highest-value integrity target. The bd service holds cross-project
state, so it is the widest blast radius per single request.

## 3. What an attacker can do

**A local process running as the user.** Everything. It can call every
endpoint, and it can also read the files directly, so nothing the services
do can stop it. This is the boundary that authentication does not fix
either (see section 7). It is stated here so that no control below is
oversold as covering it.

**A web page the user has open.** Without the controls in section 4, it can
POST to every write endpoint on every service, silently, from any site.
With them, its cross-origin requests are refused before any handler runs.
This is the attacker the header and origin baseline actually defends
against, and it is the realistic one: the user browses the web all day.

**A malicious artifact.** An artifact is attacker-authored content by
construction: agents generate it, and the content can come from anywhere an
agent read. Served as `text/html` from the same origin as the review UI, its
scripts run with that origin's privileges: they can read every other
artifact through the UI's own API, drive review actions as the user, and
reach every other loopback service listed above. SVG is the same problem
wearing an image extension, because SVG can carry `<script>` and is rendered
as a document when it is navigated to directly.

**A malicious page that kb clips.** `/clip` and `/atomize` make the server
fetch a URL the caller chose. Without a guard that is a server-side request
forgery primitive against every other loopback port and against cloud
metadata. `scripts/kb-clip.py` already enforces http/https only plus a
public-address check re-run on every redirect hop, which closes it. The
residual DNS-rebinding TOCTOU between the check and the connect is
documented in that file and accepted.

## 4. Response-header baseline

Every service sends this exact set on **every** response, including errors
and 404s. Not advice, a required set.

```
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; sandbox
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
Permissions-Policy: camera=(), microphone=(), geolocation=()
Cache-Control: no-store
```

JSON responses additionally carry `Content-Type: application/json;
charset=utf-8`. The explicit charset plus `nosniff` is what stops a JSON
reply being re-interpreted as a document.

No service ever sends `Access-Control-Allow-Origin`. There is no legitimate
cross-origin consumer: the only client is the CLI.

Alongside the headers, every service enforces four request-side rules,
because headers on the reply do not stop a request that has already taken
effect:

1. **Refuse any request carrying an `Origin` header.** No allowlist, no
   exceptions. The CLI never sends one; a browser always does when the
   request is cross-origin.
2. **Refuse any request whose `Host` header is not `127.0.0.1`,
   `localhost`, or `::1`** (port ignored). This is the only defense against
   the DNS-rebinding case, which arrives with no `Origin` header at all.
3. **Refuse any POST whose `Content-Type` is not `application/json`**, with
   415. A JSON content type is not a CORS "simple request", so a
   cross-origin POST must first win a preflight, and a service that answers
   no preflight and sends no CORS headers fails it.
4. **Refuse any request this service cannot frame exactly.** Rules 1-3 all
   read one header and act on its value, so they are only as good as the
   guarantee that the value read is the value that took effect. Four cases
   break that guarantee, and each is refused:
   - a second `Host` header, so the checked value and the value anything in
     front of the service reads can differ
   - an absolute-form request target (`GET http://elsewhere/path`), so
     routing reads one authority while `Host` claims another
   - `Transfer-Encoding`, because a body this service cannot frame would
     otherwise be read as no body at all, silently turning "here is my
     body" into "run the endpoint on its defaults"
   - a duplicate or out-of-range `Content-Length`, for the same reason

   These are what keep the first three rules from being bypassable rather
   than an extra layer on top of them.

### Routes that serve user-supplied content

This applies to the artifact service only; no other service in the stack
returns a document. The rules are stated here because the baseline is
stack-wide and any future content-serving route inherits them.

```
Content-Security-Policy: default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; font-src data:; connect-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; sandbox
X-Content-Type-Options: nosniff
Cross-Origin-Resource-Policy: same-origin
Cache-Control: no-store
```

Plus, for that route specifically:

- **Serve artifact content from a different origin than the review UI.** A
  CSP that neuters an artifact is one header bug away from not neutering
  it, and the whole failure mode is "attacker script shares an origin with
  the reviewer's session". A separate port is a separate origin and costs
  one line of config.
- **Render artifacts only inside a sandboxed iframe**, with the `sandbox`
  attribute and without `allow-same-origin`.
- **SVG is never served inline as `image/svg+xml` on a navigable URL.**
  Serve it with `Content-Disposition: attachment`, or as `text/plain`, or
  render it inside the same sandboxed frame as HTML.
- **Never reflect an artifact's own filename or title into an HTML
  response** without escaping.

## 5. Input-validation baseline

1. **Names are one path segment.** Any request field that becomes a
   directory or file name (`project`, board name, artifact id) must match
   `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` in full. A leading alphanumeric
   character is what makes `.`, `..`, and dotfiles unspellable; the absent
   `/` and `\` are what make `a/b` and `/etc` unspellable. Reject with 400,
   naming the field.
2. **Containment is re-checked after the join.** Build the path, then
   `resolve()` it and require `is_relative_to(root.resolve())`. The name
   pattern should make this unreachable; it stays because a loosened
   pattern, a symlink inside the root, or a new call site would otherwise
   turn straight into a write outside the root.
3. **Free text is never a path component.** Titles and other prose reach
   the filesystem only through `slugify()`, never raw.
4. **No user input reaches a shell.** Subprocesses take an argv list and
   never `shell=True`. The single existing `shell=True` call,
   `resolve_api_key` in `scripts/kb-svc.py`, runs `KB_LLM_API_KEY_CMD`,
   an operator-set value from `kb.env` or the container environment. It is
   never populated from a request, and no request field may ever be routed
   into it.
5. **SQL is parameterized.** `scripts/kb-index.py` `build_query` already
   binds the project and type filters; keep it that way.
6. **Outbound fetches keep the SSRF guard.** Any endpoint that fetches a
   caller-supplied URL goes through `kb-clip.py`'s `check_url_scheme` plus
   `check_destination_is_public`, including on every redirect hop.
7. **Secrets are never logged or echoed.** Already true of
   `resolve_api_key`; it holds for any new secret handling.

## 6. What is implemented, and where

Implemented in this workstream, in `scripts/kb-svc.py`:

- the section 4 header set on every response, stamped in `end_headers` so
  that the stdlib's own `send_error` replies (the 501 for an unimplemented
  method, for instance) carry it too, not only the JSON replies;
- the `Origin` and `Host` request rules, in `_reject_browser_origin`,
  applied to both `do_GET` and `do_POST`;
- the JSON content-type rule on `do_POST`;
- the section 5 name rule and the containment re-check together in
  `_require_project`, applied to `project` at all three entry points
  (`kb_put`, `kb_clip_and_atomize`, `kb_ingest_and_atomize`). Both checks
  run before any write, including the ones `kb_clip_and_atomize` delegates
  to `kb-clip.py`, which builds its own path from the project name.
  `_write_note_file` re-checks through `contained_path` for the type
  subdirectory it adds.

Covered by tests in `tests/test_kb_serve.py`.

Reported, not implemented, because it belongs to another workstream:

- **Artifact service.** All of section 4's user-content rules: the separate
  origin, the sandboxed iframe, the SVG handling, and the content CSP. This
  is the highest-severity item in this document and it is not fixed by
  anything done here.
- **bd service.** Today the board port is `bdui`, a prebuilt third-party
  app that the architecture says is not ours to rewrite. It has no headers
  and no origin guard, so any web page can drive the board. When the bd
  endpoints service is built, section 4 and section 5 apply to it
  unchanged. Until then, the honest statement is that port 3100 is
  unprotected.


## 7. Is authentication still deferrable?

**Yes. Authentication is optional and off by default.** See `~/.knowledgebase/agent-workbench/decisions/security-baseline__2026-07-28.md`, which revises the prior note treating a bearer-token layer as no-longer-deferrable. The bearer-token design was never implemented, and the user has ruled it out as a requirement: "make auth optional." The reasoning in section 3 applies: a process running as the user can read the token file exactly as easily as it can read `~/.knowledgebase`. For a personal, single-user project, a token layer that only defends against browser-origin attackers and other users on a shared machine was judged not worth building.

Section 4's controls close the drive-by browser case and remain the standing mitigation. If future use or threat model changes make an authentication layer desirable, the minimal design below describes what adding one would look like:

### Minimal recommendation (optional, not implemented)

A single shared bearer token, per install:

- generate once, on first deploy: `secrets.token_urlsafe(32)`, written to
  `~/.config/agent-workbench/token` with mode `0600`;
- pass it to each container as an environment variable, alongside the mount
  it already gets;
- every service compares `Authorization: Bearer <token>` with
  `hmac.compare_digest` and answers 401 otherwise, exempting only
  `/health`, so container health checks stay unauthenticated and carry no
  data;
- the CLI reads the same file and sets the header on every call. One place,
  because the CLI is the only client.

### Cost

Roughly 15 lines per service, 10 in the CLI's HTTP helper, plus token
generation in the deploy path and a README line about what to do when the
file is missing. The awkward part is the artifact review UI: a browser
cannot read the token file, so it needs the token delivered as a
`HttpOnly; SameSite=Strict` session cookie set by a small login route, or
the UI's own origin must be treated as pre-authenticated. That decision
belongs to the artifact workstream.

### What it does not buy

Nothing against section 3's first attacker. A process running as the user
can read `~/.config/agent-workbench/token` exactly as easily as it can read
`~/.knowledgebase`. The token defends against browser-origin attackers,
against other users on a shared machine, and against casual local port
scanning. It is not a sandbox, and claiming otherwise would be the same
mistake as claiming loopback is one.
