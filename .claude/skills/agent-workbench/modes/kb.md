# agent-workbench: kb mode

Knowledgebase ops:
init/add/path/index/clip/put/query/atomize/status/decision/enrich/embed.

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

## Never verify against the live stack

Never probe the live kb-svc (port 9100, the real `~/.knowledgebase`) to
verify a change works -- that leaves permanent residue in the real vault.
See `SKILL.md` for the ephemeral-service verification rule and how to
invoke it (`scripts/ephemeral-service.py kb -- ...`) from a repo
checkout; `--help` documents the mechanics.

When a request makes at least one model call, the response includes a `usage`
key with `calls` (HTTP calls made), token counts (summed across calls),
`generation_ids` (provider ids in call order, for billing reconciliation),
and `models` (unique and sorted; a list because `clip`/`put`/`atomize` spend
via `KB_ATOMIZE_MODEL`, `enrich` spends via `KB_LLM_MODEL`, and `embed`
spends via `KB_EMBED_MODEL`). The key's absence means the request was free.
Verbs that can carry `usage`: `clip`, `put`, `atomize`, `enrich`,
`embed`. Not `decision record` (always already-atomic), nor `index`,
`query`, `status`, `init`, `add`, `path`. This enables cost estimation: run
`kb enrich` once, divide `total_tokens` by `enriched`, and multiply by
notes remaining.

## init -- create the vault

```bash
$AW kb init
# -> {"kb_home": "$HOME/.knowledgebase", "initialized": true}
```

Idempotent: safe to call again, just re-asserts the vault's own dirs exist.

## add -- create a project's note dirs

```bash
$AW kb add gvn
# -> {"project": "gvn", "path": "$HOME/.knowledgebase/gvn"}
```

Also idempotent, and implied by `clip`/`put`/`atomize`, which create the
project on first write -- call `add` directly only to pre-create an empty
project.

## path -- print a project's vault path

```bash
$AW kb path gvn
# -> $HOME/.knowledgebase/gvn
```

Prints the bare path only (the service's `GET /project` actually answers
`{"project", "path", "exists"}`; this verb prints just the path field).

## index -- rebuild the derived layer

```bash
$AW kb index
# -> {"indexed": 2370, "embedded": 0, "db": "$HOME/.knowledgebase/index/kb.db"}
```

Rebuilds the FTS5 index whole from the vault markdown, then incrementally
embeds only stale vectors and prunes vectors for notes that no longer
exist. That is the recovery path: the index is never something to back
up, and editing the vault outside the service is repaired by rerunning
this.

`embedded`, on every verb below that carries it, counts vectors WRITTEN
BY THAT CALL, not the vault's total vector count -- on a warm database
(nothing stale, as above) it reads `0` even though the vault has 2370
vectors already. `GET /health`'s `vector_count` is where the running
total lives.

## clip -- capture a web source

```bash
$AW kb clip "https://example.com/article" --project gvn
# -> {"path": "$HOME/.knowledgebase/gvn/sources/article.md",
#     "children": ["$HOME/.knowledgebase/gvn/sources/article--intro.md"],
#     "method": "llm", "indexed": 2371, "embedded": 2,
#     "usage": {"calls": 1, "prompt_tokens": 284, "completion_tokens": 293,
#               "total_tokens": 577,
#               "generation_ids": ["gen-1785253583-u4apBDVzZObTHrRoRNcg"],
#               "models": ["deepseek/deepseek-chat"]}}
```

`--project` defaults to `inbox`. Every clip writes type `source`, which is
splittable; with `KB_ENRICH=1` plus a resolvable key, the clip makes a model
call and the response includes a `usage` key. Atomizing, indexing and
embedding always happen in the same call and cannot be skipped; embedding
is scoped to the clipped note plus its children (here 1 parent + 1 child =
`"embedded": 2`), never the whole vault. The model tier is controlled by
`KB_ENRICH`. If the embedding backend fails, the response still carries
`indexed`/`embedded` for the write that already landed, plus an
`embed_error` string naming what went wrong -- the write itself never
fails because embedding degraded.

## put -- write a note (body on stdin)

```bash
echo "Body text goes here." | $AW kb put gvn "My Note" --type note \
  --source "https://example.com"
# -> {"path": "$HOME/.knowledgebase/gvn/notes/my-note.md",
#     "children": [], "method": "already-atomic", "indexed": 2372,
#     "embedded": 1}
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
# -> {"parent": "$HOME/.knowledgebase/gvn/sources/article.md",
#     "path": "$HOME/.knowledgebase/gvn/sources/article.md",
#     "children": ["$HOME/.knowledgebase/gvn/sources/article--intro.md"],
#     "method": "llm", "indexed": 2373, "embedded": 2,
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
outcomes, never an error. `embedded` is scoped to this note plus its
children (see `## clip`); an `embed_error` key appears alongside it if the
embedding backend failed, without failing the write.

## query -- hybrid keyword + vector search

```bash
$AW kb query "information architecture" --project agent-workbench
# -> {"results": [{"path": "$HOME/.knowledgebase/agent-workbench/research/....md",
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
# -> {"kb_home": "$HOME/.knowledgebase", "initialized": true,
#     "projects": ["agent-workbench", "gvn", "lodestar"]}
```

## decision record / audit -- dated, auditable decision notes

```bash
$AW kb decision record --project gvn --topic base-body-slices \
  --title "<title>" --text "<decision statement>" \
  [--rationale "<why>"] [--refs "<paths/tickets>"] [--tags "a, b"] \
  [--revises "<path>"]
# -> {"path": "$HOME/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "children": [], "method": "already-atomic", "indexed": 2374,
#     "embedded": 1, "revises": ""}

# revising an existing topic also refreshes the PRIOR note's index row
# and vector in the same request:
# -> {"path": "$HOME/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22-2.md",
#     "children": [], "method": "already-atomic", "indexed": 2375,
#     "embedded": 1,
#     "revises": "$HOME/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "revised_embedded": 1}

$AW kb decision audit base-body-slices --project gvn
# -> [{"date": "2026-07-22", "status": "revised",
#     "title": "Base body is six mesh-deformed slices, not per-feature cuts",
#     "path": "$HOME/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "revises": ""},
#     {"date": "2026-07-22", "status": "active",
#     "title": "Base body is six overlap-margin mesh slices ...",
#     "path": "$HOME/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22-2.md",
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

Whenever a prior note gets revised (auto-detected or via `--revises`),
that note's index row and vector are refreshed in the same request, not
left stale for the next `/embed` or `/reindex` pass. `revised_embedded`
reports how many prior notes were re-embedded (0 or 1; also 0 when the
topic is new, so there is no prior note, or when embeddings are
disabled). Same asymmetry as every other ingest route: a backend
failure here sets `revised_embed_error` and still returns 201, never
loses the write.

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
# -> {"enriched": 3, "notes": ["$HOME/.knowledgebase/gvn/notes/foo.md", ...],
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

## embed -- bounded, resumable vector backfill

```bash
$AW kb embed missing
# -> {"mode": "missing", "dry_run": false,
#     "embeddings": {"enabled": true, "embedded": 96, "pruned": 0,
#                     "remaining": 2284, "chars_sent": 170954,
#                     "usage": {"calls": 3, "prompt_tokens": 42739,
#                               "completion_tokens": 0, "total_tokens": 42739,
#                               "generation_ids": [],
#                               "models": ["text-embedding-3-small"]}},
#     "atomize": {"enabled": false, "processed": null, "remaining": null,
#                 "message": "re-atomizing is out of scope by decision, not unimplemented: it requires deleting a note's prior atomize children first, which the standing no-delete decision forbids. Re-atomizing is a human out-of-band operation; this route covers the vector tier only."},
#     "next": "$HOME/.claude/skills/agent-workbench/agent-workbench kb embed missing"}

$AW kb embed all --dry-run
# -> {"mode": "all", "dry_run": true,
#     "embeddings": {"enabled": true, "would_embed": 2380, "would_prune": 0,
#                     "chars_to_send": 4241700, "estimated_tokens": 1060425,
#                     "estimated_tokens_basis": "chars_to_send // 4; an estimate, not a billed count",
#                     "batch_limit": 96, "calls_required": 25},
#     "atomize": {"enabled": false, "processed": null, "remaining": null,
#                 "message": "re-atomizing is out of scope by decision, not unimplemented: it requires deleting a note's prior atomize children first, which the standing no-delete decision forbids. Re-atomizing is a human out-of-band operation; this route covers the vector tier only."},
#     "next": "$HOME/.claude/skills/agent-workbench/agent-workbench kb embed all"}
```

Two verbs, both `--dry-run`-able, no `--limit` and no `--project`: `missing`
embeds only notes never embedded or changed since (compares each note's
current content hash against what is stored); `all` marks every note
stale first, then runs the exact same bounded batch `missing` would. Each
real call embeds at most `BACKFILL_BATCH_LIMIT` (96) notes -- 3 backend
requests of `EMBED_BATCH_SIZE` (32) each, at up to `EMBED_TIMEOUT_SEC`
(30s) apiece, so 90s worst case against the CLI's 120s
`REQUEST_TIMEOUT_SEC`, real margin, not a coincidence; `all` is the
answer to "I changed `KB_EMBED_MODEL`" -- it is what makes every note
stale again so the next batches re-embed under the new model.

The `next` field is the whole control plane: keep re-running the printed
command until `next` comes back `null`. Note that `all`'s `next` always
names `kb embed missing`, never `kb embed all` -- `all` resets every hash
on every call, so looping on `all` would never converge. `--dry-run`
performs the identical scan and reports the exact
`chars_to_send`/`estimated_tokens` without making any network call,
resetting any hash, or pruning; its `next` names the same verb you just
dry-ran, so running it for real is one copy-paste away.

With no `KB_EMBED_MODEL`/key configured, embeddings stay off and both
verbs return 200 (never an error) with `embeddings.enabled: false`, every
count at `0`, and a `message` explaining why -- the same degrade-instead-of-fail
shape as `enrich`. A mid-run backend failure is the one place `embed`
differs from every other ingest verb: because embedding IS the operation
here (not a side effect of a write that already safely landed), a failed
batch is reported as a 502 rather than a silent degrade, with whatever
batches already committed kept and counted.

`embed` and `kb index` share one lock: a second call that arrives while
one is already running gets 409 with a `next` naming the exact command it
already has, rather than racing to embed the same stale notes twice.
Re-running `next` is the correct response to a 409, same as any other
value in that field.

The atomize tier of `embed` is permanently out of scope by decision, not
merely unimplemented. Both verbs always return an `atomize` block with
`enabled: false` and a message naming why: re-atomizing a note requires
deleting its prior atomize children first (they carry `kb enrich`-written
question/summary), and the standing no-delete decision for kb notes
forbids that. This route covers the vector tier only; see
`## re-atomizing -- out-of-band human operation` below for the human
procedure.

After upgrading onto this version, backfill the vault with
`kb embed missing` (called repeatedly until `next` is `null`), not
`kb index`: `kb index`/`POST /reindex` stays the unbounded, one-shot
recovery path and will likely exceed the CLI's 120s timeout against a
cold database with thousands of stale vectors.

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

## re-atomizing -- out-of-band human operation

There is deliberately NO CLI verb and NO route to re-atomize a note.
Re-atomizing needs the parent note's prior atomize children deleted
first, and deletion of kb notes is human-only by standing decision (see
`## deletion` above) -- a re-atomize route would sit right on top of that
decision, so it does not exist either.

To re-atomize a parent note:
1. Locate the parent's existing children in the vault: siblings named
   `<parent-stem>--<slug>.md` in the same directory as the parent (e.g.
   `article.md`'s children are `article--intro.md`,
   `article--details.md`, ...).
2. Remove those child markdown files by hand.
3. Re-run the atomizer on the parent:
   `scripts/kb-atomize.py <path-to-parent>.md --kb-home $HOME/.knowledgebase`
   (repo dev tooling, not a CLI verb -- same tier as
   `scripts/ephemeral-service.py`).
4. Rebuild the derived layer with `$AW kb index`.

Skipping step 2 is the trap: `build_note_path` treats every freshly
split child's slug as a collision with the stale one still on disk and
suffixes `-2`/`-3` onto the new filename instead of replacing it, so the
parent ends up with BOTH the stale and the fresh children, duplicated
rather than replaced.

The new children also start with blank `question`/`summary`
frontmatter: whatever `kb enrich` had written onto the old children does
not carry over, since re-atomizing writes new files rather than editing
the old ones. Re-run `kb enrich` afterward to refill it.
