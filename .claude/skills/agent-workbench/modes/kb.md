# agent-workbench: kb mode

Knowledgebase vault ops: init/add/path/index/clip/put/query/atomize/status.
Replaces `scripts/kb.sh`.

```bash
AW=$HOME/.claude/skills/agent-workbench/agent-workbench
$AW kb clip "<url>" --project <project>
$AW kb put <project> "<title>" --type note --source "<url>"  # body on stdin
$AW kb query "<terms>" --project <project> --type source
$AW kb index
$AW kb status
```

`clip` / `put` / `query` prefer the running kb-serve HTTP service (so the
call also atomizes + reindexes) and fall back to an in-process kb-serve.py
call when the service is down. Same behavior kb.sh had.

`kb` honors `KB_SERVE_HOST` (not only `KB_SERVE_PORT`) and surfaces the
HTTP error body on failure instead of swallowing it.

The clip path preserves kb-clip.py's http/https scheme allowlist verbatim
(it delegates to the same `check_url_scheme`), so `file://` and other
schemes stay rejected with zero new code.

## kb-serve LLM endpoints (agent-facing)

Two optional, LLM-backed endpoints exist on the running kb-serve service
(see `scripts/kb-serve.py`'s module docstring for exact behavior):

- `POST /enrich` -- fills in a note's `question`/`summary` frontmatter
  fields via the configured LLM. Gated by `KB_ENRICH` (must be `1`;
  default `0` is a clean no-op, zero network calls) plus a resolvable API
  key (`KB_LLM_API_KEY`, or preferably `KB_LLM_API_KEY_CMD`, a vault CLI
  command whose stdout is the key -- see
  `scripts/kb-container/kb.env.example` for the exact modes/format).
- `POST /atomize` -- LLM-assisted atomize/split of a URL or raw document
  content into decontextualized child notes, using a "strong" model tier
  (bigger than enrich's, since atomize needs real
  decontextualization/section-splitting, not just a gist). If
  `KB_ENRICH`/the key isn't configured, it falls back to the deterministic
  heading-based split (no model call) -- never fails, just degrades.

Both are off/degraded by default; opt in via `KB_ENRICH=1` plus a
configured key in the real `$HOME/.knowledgebase/kb.env` (see
`scripts/kb-container/kb.env.example` for the template -- never document
or imply a real secret value there).
