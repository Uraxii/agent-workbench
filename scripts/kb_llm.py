"""Optional model-backed passes: enrichment and LLM atomization.

Both are opt-in operator config (``KB_ENRICH=1`` plus a resolvable API
key) and both degrade instead of failing: with no key, ``kb_enrich`` is a
clean no-op and ``kb_atomize_via_llm`` falls back to the deterministic
heading splitter in kb-atomize.py.

That fallback is what keeps the "no ingest path skips atomization"
invariant true without making the model a dependency: atomization always
happens, the model only changes how good the split is.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from kb_config import KbServeConfig, load_sibling

__all__ = [
    "apply_enrichment",
    "find_unenriched_notes",
    "fold_call_records",
    "kb_atomize_via_llm",
    "kb_enrich",
    "request_atomize_split",
    "request_enrichment",
]

log = logging.getLogger("kb-svc")

LLM_TIMEOUT_SEC = 30.0
# Atomizing needs the whole document to find its section boundaries, hence
# a much bigger cap than enrich's 4000 (which only needs a gist).
ATOMIZE_PROMPT_CHAR_LIMIT = 12000
ENRICH_PROMPT_CHAR_LIMIT = 4000
# ponytail: bounds one /enrich call's model spend to a fixed batch; call
# /enrich again to keep going rather than adding pagination.
ENRICH_BATCH_LIMIT = 20

# Bounds the frontmatter block a rewrite touches: "---\n...\n---\n", so
# question/summary get patched in place without disturbing the body.
FRONTMATTER_BOUNDS_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)

MODEL_FAILURES = (
    OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError,
    KeyError, IndexError, ValueError,
)


def _chat_completion_json(
    config: KbServeConfig, model: str, prompt: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """One chat-completions POST expecting a JSON object back.

    Returns (parsed_content, call_record) where call_record is
    {"id": str, "model": str, "prompt_tokens": int,
     "completion_tokens": int, "total_tokens": int}.
    Raises on any network or parse failure; callers decide how to degrade.
    """
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{config.llm_base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SEC) as response:
        data = json.loads(response.read())
    parsed = json.loads(data["choices"][0]["message"]["content"])
    usage = data.get("usage", {})
    call_record = {
        "id": data.get("id", ""),
        "model": data.get("model", ""),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
    return parsed, call_record


def fold_call_records(records: list[dict[str, object]]) -> dict[str, object]:
    """Fold a list of call records into an aggregated usage block.

    Returns {"calls": int, "prompt_tokens": int, "completion_tokens": int,
             "total_tokens": int, "generation_ids": [str, ...],
             "models": [str, ...]}.
    generation_ids are in call order with empty strings dropped; models are unique and sorted.
    """
    generation_ids: list[str] = []
    models_list: list[str] = []
    total_prompt = 0
    total_completion = 0
    total_tokens = 0

    for record in records:
        call_id = record.get("id", "")
        if call_id:
            generation_ids.append(call_id)
        model = record.get("model", "")
        if model and model not in models_list:
            models_list.append(model)
        total_prompt += record.get("prompt_tokens", 0)
        total_completion += record.get("completion_tokens", 0)
        total_tokens += record.get("total_tokens", 0)

    return {
        "calls": len(records),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "generation_ids": generation_ids,
        "models": sorted(models_list),
    }


# ── enrichment: fill question/summary ─────────────────────────────────


def find_unenriched_notes(
    kb_home: Path, project: str | None, note_filter: str | None,
) -> list[Path]:
    """Notes with an empty question or summary, capped at the batch limit.

    ``note_filter`` targets exactly that path, checked against kb_home;
    an absolute or ``..``-escaping value that lands outside kb_home is
    treated as "no matching note" (empty list) and never read. The
    returned path is the UNRESOLVED ``kb_home / note_filter`` form, not
    the resolved candidate used only for the containment check: this is
    the same unresolved shape ``kb-index.find_markdown_files`` returns
    for the vault-scan case below, so both cases produce exactly one path
    shape per note. A symlinked project dir would otherwise make the two
    cases disagree, embedding the same note under two different vector
    keys (see kb_embed.py's ``sync_vectors``).
    """
    kb_index = load_sibling("kb-index")
    if note_filter:
        candidate = (kb_home / note_filter).resolve()
        if not candidate.is_relative_to(kb_home.resolve()) or not candidate.is_file():
            return []
        return [kb_home / note_filter]
    unenriched: list[Path] = []
    for path in kb_index.find_markdown_files(kb_home):
        if project and kb_index.derive_project(path, kb_home) != project:
            continue
        fields, _ = kb_index.parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fields.get("question") or not fields.get("summary"):
            unenriched.append(path)
        if len(unenriched) >= ENRICH_BATCH_LIMIT:
            break
    return unenriched


def request_enrichment(
    config: KbServeConfig, title: str, body: str,
) -> tuple[dict[str, str], dict[str, object]]:
    """One chat-completions call asking for ``{question, summary}`` JSON."""
    prompt = (
        "Given this knowledgebase note, respond with ONLY a JSON object "
        '{"question": "...", "summary": "..."}. question = the question '
        "someone would search to find this note. summary = a 2-3 sentence "
        f"summary of its content.\n\nTitle: {title}\n\n"
        f"{body[:ENRICH_PROMPT_CHAR_LIMIT]}"
    )
    parsed, call_record = _chat_completion_json(config, config.llm_model, prompt)
    enrichment = {
        "question": str(parsed.get("question", "")),
        "summary": str(parsed.get("summary", "")),
    }
    return enrichment, call_record


def apply_enrichment(note_path: Path, question: str, summary: str) -> None:
    """Rewrite only the question/summary frontmatter lines in place.

    Every other line, including the body, is left byte-for-byte untouched.
    """
    kb_clip = load_sibling("kb-clip")
    text = note_path.read_text(encoding="utf-8")
    match = FRONTMATTER_BOUNDS_RE.match(text)
    if not match:
        return
    head, raw_fields, tail = match.groups()
    raw_fields = re.sub(
        r"^question:.*$", f"question: {kb_clip.yaml_quote(question)}",
        raw_fields, count=1, flags=re.MULTILINE,
    )
    raw_fields = re.sub(
        r"^summary:.*$", f"summary: {kb_clip.yaml_quote(summary)}",
        raw_fields, count=1, flags=re.MULTILINE,
    )
    note_path.write_text(
        head + raw_fields + tail + text[match.end():], encoding="utf-8",
    )


def kb_enrich(
    config: KbServeConfig, payload: Mapping[str, object],
) -> dict[str, object]:
    """Fill question/summary on unenriched notes via the configured LLM.

    Clean no-op (zero network calls) if KB_ENRICH=0 or no API key
    resolved -- the caller always gets a result with a clear ``message``,
    never a crash. Reindexing is the caller's job.
    """
    if not config.enrich_enabled:
        return {"enriched": 0, "message": "KB_ENRICH is 0; enrichment disabled"}
    if not config.llm_api_key:
        return {
            "enriched": 0,
            "message": "KB_ENRICH=1 but no API key resolved "
                       "(checked KB_LLM_API_KEY_CMD, KB_LLM_API_KEY)",
        }

    kb_index = load_sibling("kb-index")
    project = payload.get("project")
    note_filter = payload.get("note")
    notes = find_unenriched_notes(
        config.kb_home,
        str(project) if project else None,
        str(note_filter) if note_filter else None,
    )
    enriched: list[str] = []
    call_records: list[dict[str, object]] = []
    for note_path in notes:
        try:
            fields, body = kb_index.parse_frontmatter(
                note_path.read_text(encoding="utf-8")
            )
            result, call_record = request_enrichment(
                config, str(fields.get("title", note_path.stem)), body,
            )
            call_records.append(call_record)
        except MODEL_FAILURES as exc:
            log.warning("enrichment failed for %s: %s", note_path, exc)
            continue
        apply_enrichment(note_path, result["question"], result["summary"])
        enriched.append(str(note_path))
    response = {"enriched": len(enriched), "notes": enriched}
    if call_records:
        response["usage"] = fold_call_records(call_records)
    return response


# ── LLM-tier atomize (deterministic fallback) ─────────────────────────


def _hard_cut_chunks(text: str, limit: int) -> list[str]:
    return [text[index:index + limit] for index in range(0, len(text), limit)]


def _paragraph_chunks(section: str, limit: int) -> list[str]:
    paragraphs = section.split("\n\n")
    chunks: list[str] = []
    current = ""
    for index, paragraph in enumerate(paragraphs):
        suffix = "\n\n" if index < len(paragraphs) - 1 else ""
        unit = f"{paragraph}{suffix}"
        if len(unit) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_cut_chunks(unit, limit))
        elif current and len(current) + len(unit) > limit:
            chunks.append(current)
            current = unit
        else:
            current += unit
    if current:
        chunks.append(current)
    return chunks


def _heading_sections(body: str) -> list[str]:
    headings = list(re.finditer(r"(?m)^#", body))
    if not headings:
        return [body]
    sections: list[str] = []
    if headings[0].start() > 0:
        sections.append(body[:headings[0].start()])
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        sections.append(body[heading.start():end])
    return [section for section in sections if section]


def _atomize_prompt_body_chunks(body: str) -> list[str]:
    if len(body) <= ATOMIZE_PROMPT_CHAR_LIMIT:
        return [body]
    chunks: list[str] = []
    current = ""
    for section in _heading_sections(body):
        if len(section) > ATOMIZE_PROMPT_CHAR_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_paragraph_chunks(section, ATOMIZE_PROMPT_CHAR_LIMIT))
        elif current and len(current) + len(section) > ATOMIZE_PROMPT_CHAR_LIMIT:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)
    return chunks


def _parse_atomize_notes(parsed: Mapping[str, object]) -> list[dict[str, str]]:
    notes = parsed["notes"]
    if not isinstance(notes, list):
        raise KeyError("'notes' in atomize response is not a list")
    return [
        {"title": str(item.get("title", "")), "body": str(item.get("body", ""))}
        for item in notes if isinstance(item, dict)
    ]


def request_atomize_split(
    config: KbServeConfig, title: str, body: str,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Ask the atomize tier to split a document into self-contained notes.

    Response shape: ``(notes, call_records)`` where notes is
    ``[{"title", "body"}, ...]`` and call_records is a list of
    call_record dicts, one per chunk. Raises on any network or parse
    failure (including a missing/malformed ``notes`` list);
    ``kb_atomize_via_llm`` decides how to degrade.
    """
    notes: list[dict[str, str]] = []
    call_records: list[dict[str, object]] = []
    for chunk in _atomize_prompt_body_chunks(body):
        prompt = (
            "Split the following knowledgebase note into distinct, "
            "self-contained atomic notes. Respond with ONLY a JSON object "
            '{"notes": [{"title": "...", "body": "..."}, ...]}.\n\n'
            f"Title: {title}\n\n{chunk}"
        )
        parsed, call_record = _chat_completion_json(
            config, config.atomize_model, prompt
        )
        call_records.append(call_record)
        notes.extend(_parse_atomize_notes(parsed))
    return notes, call_records


def _write_llm_child_note(
    note_path: Path, fields: dict[str, object], item: dict[str, str],
) -> Path:
    """Write one LLM-proposed child note as a sibling of ``note_path``."""
    kb_clip = load_sibling("kb-clip")
    kb_atomize_script = load_sibling("kb-atomize")
    slug = f"{note_path.stem}--{kb_clip.slugify(item['title'])}"
    child_path = kb_clip.build_note_path(note_path.parent, slug)
    child_path.write_text(
        kb_atomize_script.render_child_note(
            fields, note_path, item["title"], item["body"],
        ),
        encoding="utf-8",
    )
    return child_path


def kb_atomize_via_llm(
    config: KbServeConfig, note_path: Path, kb_home: Path,
) -> tuple[list[Path], str, list[dict[str, object]]]:
    """Split ``note_path`` into atomic children, model tier or not.

    Falls back to the deterministic heading splitter when the model is
    disabled, no key resolved, or the call fails. Returns
    ``(children, method, call_records)`` where method is ``"llm"``,
    ``"deterministic"`` or ``"already-atomic"``. ``call_records`` is empty
    for "already-atomic" and "deterministic", and contains one record per
    LLM call for "llm".

    Which note types are already atomic is the deterministic splitter's
    rule (kb-atomize.py's ATOMIC_TYPES), and the model tier honours it
    rather than deciding for itself: a decision or a note IS one idea by
    construction, so splitting it would manufacture children that
    contradict the type's meaning. Enabling the model must change how
    well a splittable note is split, never which notes get split.
    """
    kb_index = load_sibling("kb-index")
    kb_atomize_script = load_sibling("kb-atomize")
    fields, body = kb_index.parse_frontmatter(
        note_path.read_text(encoding="utf-8")
    )
    if kb_index.derive_type(fields, note_path) in kb_atomize_script.ATOMIC_TYPES:
        return [], "already-atomic", []
    if config.enrich_enabled and config.llm_api_key:
        try:
            notes, call_records = request_atomize_split(
                config, str(fields.get("title", note_path.stem)), body,
            )
        except MODEL_FAILURES as exc:
            log.warning("LLM atomize failed for %s: %s", note_path, exc)
        else:
            children = [
                _write_llm_child_note(note_path, fields, item) for item in notes
            ]
            return children, "llm", call_records

    return kb_atomize_script.kb_atomize(note_path, kb_home), "deterministic", []
