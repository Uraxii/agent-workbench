# agent-workbench: kb mode

Knowledgebase ops:
init/add/path/index/clip/put/query/atomize/status/decision/enrich.

The vault lives at `$KB_HOME` (default `~/.knowledgebase`) and the
knowledgebase service is the only thing that opens it. Every verb below is
one HTTP call to that service. There is no filesystem fallback: if the
service is down, the command fails and says which endpoint it tried and
why it failed. Start it with `docker compose up -d kb-svc`.

Service address: `KB_SVC_HOST` (default `127.0.0.1`) and
`KB_SVC_PORT` (default `9100`).

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
```

## Verifying against a scratch instance (not the live stack)

Never probe the live kb-svc (port 9100, the real `~/.knowledgebase`) to
verify a change works -- that leaves permanent residue in the real vault.
Use `scratch`, which brings up a throwaway kb-svc against a fresh temp
data dir, runs the wrapped command, and tears both down when it returns:

```bash
$AW scratch kb -- $AW kb status
# -> agent-workbench scratch: kb-svc up at 127.0.0.1:<random port>
# -> {"kb_home": "/tmp/aw-scratch-XXXXXXXX", "initialized": true, "projects": []}
```

Same response shape as a live `kb status`, except `kb_home` points at the
scratch dir instead of the real vault. `scratch kb` isolates ONLY kb-svc:
a `bd`/`artifact` call made inside the wrapped command still fails loudly
(sentinel `.invalid` host), never reaches the live stack. See `SKILL.md`
for the full `scratch` contract (any `kb` verb works the same way inside
it, and nesting `scratch kb -- scratch bd -- ...` covers two services).

When a request makes at least one model call, the response includes a `usage`
key with `calls` (HTTP calls made), token counts (summed across calls),
`generation_ids` (provider ids in call order, for billing reconciliation),
and `models` (unique and sorted; a list because `clip`/`put`/`atomize` spend
via `KB_ATOMIZE_MODEL` while `enrich` spends via `KB_LLM_MODEL`). The key's
absence means the request was free. Verbs that can carry `usage`: `clip`,
`put`, `atomize`, `enrich`. Not `decision record` (always already-atomic),
nor `index`, `query`, `status`, `init`, `add`, `path`. This enables cost
estimation: run `kb enrich` once, divide `total_tokens` by `enriched`, and
multiply by notes remaining.

## init -- create the vault

```bash
$AW kb init
# -> {"kb_home": "/home/nicole/.knowledgebase", "initialized": true}
```

Idempotent: safe to call again, just re-asserts the vault's own dirs exist.

## add -- create a project's note dirs

```bash
$AW kb add gvn
# -> {"project": "gvn", "path": "/home/nicole/.knowledgebase/gvn"}
```

Also idempotent, and implied by `clip`/`put`/`atomize`, which create the
project on first write -- call `add` directly only to pre-create an empty
project.

## path -- print a project's vault path

```bash
$AW kb path gvn
# -> /home/nicole/.knowledgebase/gvn
```

Prints the bare path only (the service's `GET /project` actually answers
`{"project", "path", "exists"}`; this verb prints just the path field).

## index -- rebuild the derived layer

```bash
$AW kb index
# -> {"indexed": 2370, "embedded": 2370, "db": "/home/nicole/.knowledgebase/index/kb.db"}
```

Rebuilds the whole derived layer (FTS5 rows and vectors) from the vault
markdown alone. That is the recovery path: the index is never something to
back up, and editing the vault outside the service is repaired by
rerunning this.

## clip -- capture a web source

```bash
$AW kb clip "https://example.com/article" --project gvn
# -> {"path": "/home/nicole/.knowledgebase/gvn/sources/article.md",
#     "children": ["/home/nicole/.knowledgebase/gvn/sources/article--intro.md"],
#     "method": "llm", "indexed": 2371, "embedded": 2371,
#     "usage": {"calls": 1, "prompt_tokens": 284, "completion_tokens": 293,
#               "total_tokens": 577,
#               "generation_ids": ["gen-1785253583-u4apBDVzZObTHrRoRNcg"],
#               "models": ["deepseek/deepseek-chat"]}}
```

`--project` defaults to `inbox`. Every clip writes type `source`, which is
splittable; with `KB_ENRICH=1` plus a resolvable key, the clip makes a model
call and the response includes a `usage` key. Atomizing, indexing and
embedding always happen in the same call and cannot be skipped; the model
tier is controlled by `KB_ENRICH`.

## put -- write a note (body on stdin)

```bash
echo "Body text goes here." | $AW kb put gvn "My Note" --type note \
  --source "https://example.com"
# -> {"path": "/home/nicole/.knowledgebase/gvn/notes/my-note.md",
#     "children": [], "method": "already-atomic", "indexed": 2372,
#     "embedded": 2372}
```

`--type` defaults to `note`, `--source` defaults to `""`. `--type decision`
is not supported; use `kb decision record` instead. With `KB_ENRICH=1` plus
a resolvable key, a splittable type (like `source`) makes a model call and
the response includes a `usage` key; already-atomic types (`note`) never do.
Notes are already-atomic (splitting a single note would manufacture children
that contradict what the type means), so `method` reads `already-atomic` and
`children` is empty for them. Repeated titles do not overwrite; the service
appends `-2`, `-3` to the path, producing duplicate notes with both indexed.

## atomize -- ingest a URL or stdin content and split it

```bash
$AW kb atomize --url "https://example.com/article" --project gvn \
  --title "Article title" --type source
# -> {"parent": "/home/nicole/.knowledgebase/gvn/sources/article.md",
#     "path": "/home/nicole/.knowledgebase/gvn/sources/article.md",
#     "children": ["/home/nicole/.knowledgebase/gvn/sources/article--intro.md"],
#     "method": "llm", "indexed": 2373, "embedded": 2373,
#     "usage": {"calls": 1, "prompt_tokens": 284, "completion_tokens": 293,
#               "total_tokens": 577,
#               "generation_ids": ["gen-1785253583-u4apBDVzZObTHrRoRNcg"],
#               "models": ["deepseek/deepseek-chat"]}}
```

Give `--url` or pipe content on stdin (omit `--url` to read stdin).
`--project` defaults to `inbox`, `--title` to `untitled`, `--type` to
`source`. `--type decision` is not supported; use `kb decision record`
instead. Splittable types with `KB_ENRICH=1` plus a key configured make a
model call with `method: "llm"` and include a `usage` key; deterministic
splits have `method: "deterministic"` and no `usage` key -- both are normal
outcomes, never an error.

## query -- hybrid keyword + vector search

```bash
$AW kb query "information architecture" --project agent-workbench
# -> {"results": [{"path": "/home/nicole/.knowledgebase/agent-workbench/research/....md",
#     "project": "agent-workbench", "type": "research",
#     "title": "Information Architecture and Route Model Axis",
#     "date": "2026-07-24", "status": "active",
#     "snippet": "Define the top-level structure, deep links, ...",
#     "score": 0.0313}]}
```

`--project`, `--type` and `--all` (include revised notes) are all
optional filters. The FTS5 keyword half decides which notes match and
applies the filters; the vector half only reorders them. With no embedding
model configured the vector half contributes nothing and search is plain
keyword ranking. Turn it on by setting `KB_EMBED_MODEL` in
`$HOME/.knowledgebase/kb.env`, then rerun `kb index`.

## status -- vault root and projects

```bash
$AW kb status
# -> {"kb_home": "/home/nicole/.knowledgebase", "initialized": true,
#     "projects": ["agent-workbench", "gvn", "lodestar"]}
```

## decision record / audit -- dated, auditable decision notes

```bash
$AW kb decision record --project gvn --topic base-body-slices \
  --title "<title>" --text "<decision statement>" \
  [--rationale "<why>"] [--refs "<paths/tickets>"] [--tags "a, b"] \
  [--revises "<path>"]
# -> {"path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "children": [], "method": "already-atomic", "indexed": 2374,
#     "embedded": 2374, "revises": ""}

$AW kb decision audit base-body-slices --project gvn
# -> [{"date": "2026-07-22", "status": "revised",
#     "title": "Base body is six mesh-deformed slices, not per-feature cuts",
#     "path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "revises": ""},
#     {"date": "2026-07-22", "status": "active",
#     "title": "Base body is six overlap-margin mesh slices ...",
#     "path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22-2.md",
#     "revises": ".../base-body-slices__2026-07-22.md"}]
```

`record` requires `--project` (decisions are never "inbox"). If the topic
already has an `active` note, it auto-flips to `status: revised` and the
new note's `revises` field points at it -- exactly one `active` note per
topic at any time, and the audit chain is the files plus their frontmatter,
never a separate database.

`--revises` optionally rewrites an existing decision note IN PLACE,
setting its `status` to `revised`. The target must be a note on the same
topic or the service rejects it. Decision records are always free (already-atomic
type making no model call).

`audit` is read-only and scans every project's `decisions/` dir unless
`--project` narrows it (topic keys are unique by convention, so a reader
auditing a topic rarely knows which project holds it). Prints the bare
chain array by default (the service's own `GET /decision/audit` answers
`{"chain": [...]}`; this verb unwraps it); add `--human` for a
one-line-per-note table instead.

Decision notes use a different frontmatter dialect from `kb put`'s notes.
The decision frontmatter is six bare, unquoted fields in this order:

```
---
title: <title>
topic: <topic>
date: <YYYY-MM-DD>
status: active
revises: <path or empty>
tags: [a, b]
---
```

Values are never quoted or escaped. An empty `revises` leaves a trailing
space after the colon. This is the locked byte shape. By contrast, `kb put`
writes quoted `type/title/source/...` frontmatter.

## enrich -- fill question/summary frontmatter via the LLM

```bash
$AW kb enrich --project gvn
# -> {"enriched": 3, "notes": ["/home/nicole/.knowledgebase/gvn/notes/foo.md", ...],
#     "usage": {"calls": 4, "prompt_tokens": 891, "completion_tokens": 325,
#               "total_tokens": 1216,
#               "generation_ids": ["gen-1785253601-bd4xKoLL1axNWEBasA4w", "..."],
#               "models": ["openai/gpt-4o-mini"]}}

$AW kb enrich
# -> {"enriched": 0, "message": "KB_ENRICH is 0; enrichment disabled"}
```

`--project` and `--note` are both optional filters; `--note` targets
exactly one note, given as a path relative to the vault root. With neither
flag it scans every project. Capped at 20 notes per call -- call it again
to keep going rather than reaching for a `--limit` flag that does not
exist.

Off by default and degrades rather than fails: with `KB_ENRICH=0` (the
default) or no LLM key resolved, the result reads `{"enriched": 0,
"message": "..."}` explaining why, never an error. Opt in with
`KB_ENRICH=1` plus a key configured at deploy time in kb.env (the real
file is `$HOME/.knowledgebase/kb.env`; the repo ships an example template).
Never document or imply a real secret value in deploy configuration.

## deletion -- out-of-band human operation

There is deliberately NO delete verb and NO delete route. Deletion is a
human out-of-band operation.

To remove a note:
1. Remove the markdown file under
   `$HOME/.knowledgebase/<project>/<dir>/<note>.md` (the note's `path` is in
   every response that created it).
2. Then rebuild the derived layer with `$AW kb index`.

Removing the markdown WITHOUT rerunning `kb index` leaves a stale index: the
note stays visible to `kb query` even though the file is gone.