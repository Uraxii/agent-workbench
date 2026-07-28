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
#     "method": "deterministic", "indexed": 2371, "embedded": 2371}
```

`--project` defaults to `inbox`. Every clip is atomized, indexed and
embedded in the same call; there is no flag to skip any of that, because an
opt-in index is an index that drifts.

## put -- write a note (body on stdin)

```bash
echo "Body text goes here." | $AW kb put gvn "My Note" --type note \
  --source "https://example.com"
# -> {"path": "/home/nicole/.knowledgebase/gvn/notes/my-note.md",
#     "children": [], "method": "already-atomic", "indexed": 2372,
#     "embedded": 2372}
```

`--type` defaults to `note`, `--source` defaults to `""`. Notes and
decisions are already-atomic types (splitting a single note or decision
would manufacture children that contradict what the type means), so
`method` reads `already-atomic` and `children` is empty for them.

## atomize -- ingest a URL or stdin content and split it

```bash
$AW kb atomize --url "https://example.com/article" --project gvn \
  --title "Article title" --type source
# -> {"parent": "/home/nicole/.knowledgebase/gvn/sources/article.md",
#     "path": "/home/nicole/.knowledgebase/gvn/sources/article.md",
#     "children": ["/home/nicole/.knowledgebase/gvn/sources/article--intro.md"],
#     "method": "deterministic", "indexed": 2373, "embedded": 2373}
```

Give `--url` or pipe content on stdin (omit `--url` to read stdin).
`--project` defaults to `inbox`, `--title` to `untitled`, `--type` to
`source`. Splits with a strong model tier when `KB_ENRICH=1` plus a key are
configured (`method: "llm"`), falling back to the deterministic heading
split otherwise (`method: "deterministic"`) -- both are normal outcomes,
never an error.

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

`--project`, `--type` and `--all` (include superseded notes) are all
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
  [--rationale "<why>"] [--refs "<paths/tickets>"] [--tags "a, b"]
# -> {"path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "children": [], "method": "already-atomic", "indexed": 2374,
#     "embedded": 2374, "supersedes": ""}

$AW kb decision audit base-body-slices --project gvn
# -> [{"date": "2026-07-22", "status": "superseded",
#     "title": "Base body is six mesh-deformed slices, not per-feature cuts",
#     "path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22.md",
#     "supersedes": ""},
#     {"date": "2026-07-22", "status": "active",
#     "title": "Base body is six overlap-margin mesh slices ...",
#     "path": "/home/nicole/.knowledgebase/gvn/decisions/base-body-slices__2026-07-22-2.md",
#     "supersedes": ".../base-body-slices__2026-07-22.md"}]
```

`record` requires `--project` (decisions are never "inbox"). If the topic
already has an `active` note, it auto-flips to `status: superseded` and the
new note's `supersedes` field points at it -- exactly one `active` note per
topic at any time, and the audit chain is the files plus their frontmatter,
never a separate database.

`audit` is read-only and scans every project's `decisions/` dir unless
`--project` narrows it (topic keys are unique by convention, so a reader
auditing a topic rarely knows which project holds it). Prints the bare
chain array by default (the service's own `GET /decision/audit` answers
`{"chain": [...]}`; this verb unwraps it); add `--human` for a
one-line-per-note table instead.

Decision notes use a different frontmatter dialect from `kb put`'s notes:
bare, unquoted scalars (`title/topic/date/status/supersedes/tags`), not
`put`'s quoted `type/title/source/...` schema -- see
`scripts/kb_decision.py`'s `render_decision` for the exact byte shape.

## enrich -- fill question/summary frontmatter via the LLM

```bash
$AW kb enrich --project gvn
# -> {"enriched": 3, "notes": ["/home/nicole/.knowledgebase/gvn/notes/foo.md", ...]}

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
`KB_ENRICH=1` plus a key in the real `$HOME/.knowledgebase/kb.env`
(template: `scripts/kb-container/kb.env.example` -- never document or
imply a real secret value there).
