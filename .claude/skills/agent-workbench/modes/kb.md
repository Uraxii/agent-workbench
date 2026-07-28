# agent-workbench: kb mode

Knowledgebase ops:
init/add/path/index/clip/put/query/atomize/status/decision.

The vault lives at `$KB_HOME` (default `~/.knowledgebase`) and the
knowledgebase service is the only thing that opens it. Every verb below is
one HTTP call to that service. There is no filesystem fallback: if the
service is down, the command fails and says which endpoint it tried and
why it failed. Start it with `docker compose up -d kb-svc`.

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW kb clip "<url>" --project <project>
$AW kb put <project> "<title>" --type note --source "<url>"  # body on stdin
$AW kb query "<terms>" --project <project> --type source
$AW kb index
$AW kb status
```

Every ingest is atomized, indexed and embedded in the same call. There is
no flag to skip any of that, because an opt-in index is an index that
drifts.

`kb index` rebuilds the whole derived layer (FTS5 rows and vectors) from
the vault markdown alone. That is the recovery path: the index is never
something to back up, and editing the vault outside the service is
repaired by rerunning it.

Service address: `KB_SVC_HOST` (default `127.0.0.1`) and
`KB_SVC_PORT` (default `9100`).

## decision -- dated, auditable decision notes

```bash
$AW kb decision record --project <project> --topic <stable-kebab-key> \
  --title "<title>" --text "<decision statement>" \
  [--rationale "<why>"] [--refs "<paths/tickets>"] [--tags "a, b"]
$AW kb decision audit <topic> [--project <project>] [--human]
```

`record` requires `--project` (decisions are never "inbox"). If the topic
already has an `active` note, it auto-flips to `status: superseded` and
the new note's `supersedes` field points at it -- exactly one `active`
note per topic at any time, and the audit chain is the files plus their
frontmatter, never a separate database.

`audit` is read-only and scans every project's `decisions/` dir unless
`--project` narrows it (topic keys are unique by convention, so a reader
auditing a topic rarely knows which project holds it). JSON by default;
`--human` prints a one-line-per-note table.

Decision notes use a different frontmatter dialect from `kb put`'s notes:
bare, unquoted scalars (`title/topic/date/status/supersedes/tags`), not
`put`'s quoted `type/title/source/...` schema -- see
`scripts/kb_decision.py`'s `render_decision` for the exact byte shape.

## Retrieval

`kb query` fuses two rankings: the FTS5 keyword search decides which
notes match and applies the project/type/superseded filters, and the
vector search reorders them. With no embedding model configured (the
default) the vector half contributes nothing and search is plain
keyword ranking. Turn it on by setting `KB_EMBED_MODEL` in
`$HOME/.knowledgebase/kb.env`, then rerun `kb index`.

## Optional LLM passes

Both are off by default and degrade rather than fail:

- `kb atomize` splits a URL or stdin document into decontextualized child
  notes using a strong model tier, falling back to the deterministic
  heading split when no key is configured.
- `POST /enrich` fills a note's `question`/`summary` frontmatter fields.
  It has no CLI verb; it is an agent-facing endpoint.

Opt in with `KB_ENRICH=1` plus a key in the real
`$HOME/.knowledgebase/kb.env` (template:
`scripts/kb-container/kb.env.example` -- never document or imply a real
secret value there).
