"""Dated, auditable decision notes.

One decision is one markdown file under
``<kb_home>/<project>/decisions/``, grouped by a stable ``topic`` key.
Recording a new decision for a topic that already has an ``active`` note
flips that prior note to ``revised`` and points the new note's
``revises`` field at it, so the audit chain is the files plus their
frontmatter, never a separate database. Exactly one note per topic is
``active`` at any time.

Frontmatter dialect: decision notes use bare, unquoted scalars
(``title/topic/date/status/revises/tags``), NOT the quoted
``type/title/source/...`` schema ``kb_vault.render_note`` writes. Every
decision note already on disk uses the bare shape and ``kb-index.py``
reads both, so this is byte-for-byte preserved. See ``render_decision``.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kb_vault import (
    VAULT_OWN_DIRS,
    assert_inside_vault,
    validate_project,
    validate_scalar,
)

__all__ = [
    "ACTIVE",
    "REVISED",
    "Decision",
    "audit",
    "build_note_path",
    "compose_body",
    "decisions_dir",
    "find_active_note",
    "find_decision_dirs",
    "find_notes_for_topic",
    "load_decision",
    "parse_frontmatter",
    "parse_tags",
    "record",
    "render_decision",
    "resolve_revises_path",
    "slugify",
]

log = logging.getLogger("kb-svc")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
DECISIONS_DIR_NAME = "decisions"
ACTIVE = "active"
REVISED = "revised"


@dataclass
class Decision:
    """One decision note: its frontmatter plus body text.

    ``decision_date`` is the frontmatter ``date`` field (ISO
    ``YYYY-MM-DD``); it is spelled out because ``date`` collides with
    ``datetime.date``. ``revises`` is the path string of the note this
    one replaced, or ``""`` when the topic is new.
    """

    path: Path
    title: str
    topic: str
    decision_date: str
    status: str
    revises: str
    tags: list[str]
    body: str


# ── frontmatter dialect (bare scalars; LOCKED) ────────────────────────


def slugify(text: str) -> str:
    """Lowercase-hyphenate ``text`` into a filesystem-safe name component.

    Postconditions: the result matches ``[a-z0-9-]+`` with no leading or
    trailing hyphen, and is ``"untitled"`` when nothing survives.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``'---\\nkey: val\\n---\\nbody'`` into ``(fields, body)``.

    Every value stays a raw string, including the bracketed ``tags`` list
    (see ``parse_tags``). Returns ``({}, text)`` when there is no
    frontmatter block, so a hand-written note never raises.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_fields, body = match.groups()
    fields: dict[str, str] = {}
    for line in raw_fields.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body.strip()


def parse_tags(raw: str) -> list[str]:
    """Parse a bare inline tag list: ``'[a, b, c]'`` -> ``['a','b','c']``."""
    stripped = raw.strip().strip("[]")
    if not stripped:
        return []
    return [tag.strip() for tag in stripped.split(",") if tag.strip()]


def load_decision(path: Path) -> Decision:
    """Read one decision note off disk into a ``Decision``.

    Postconditions: missing fields fall back to ``title=path.stem``,
    ``status="active"``, everything else empty.
    """
    fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return Decision(
        path=path,
        title=fields.get("title", path.stem),
        topic=fields.get("topic", ""),
        decision_date=fields.get("date", ""),
        status=fields.get("status", ACTIVE),
        revises=fields.get("revises", ""),
        tags=parse_tags(fields.get("tags", "[]")),
        body=body,
    )


def render_decision(decision: Decision) -> str:
    """Serialize a ``Decision`` back to frontmatter + body markdown.

    LOCKED byte shape -- the notes already in the vault must stay
    round-trippable. Two details that look like bugs and are NOT: an empty
    ``revises`` leaves a trailing space after the colon, and values are
    never quoted or escaped. Both match every note on disk; the newline
    rejection in ``validate_scalar`` is what keeps unquoted safe.
    Postcondition: the returned text ends with exactly one newline.
    """
    tags = ", ".join(decision.tags)
    return (
        "---\n"
        f"title: {decision.title}\n"
        f"topic: {decision.topic}\n"
        f"date: {decision.decision_date}\n"
        f"status: {decision.status}\n"
        f"revises: {decision.revises}\n"
        f"tags: [{tags}]\n"
        "---\n\n"
        f"{decision.body}\n"
    )


# ── vault layout ──────────────────────────────────────────────────────


def decisions_dir(kb_home: Path, project: str) -> Path:
    """Return ``<kb_home>/<project>/decisions`` (not created here)."""
    return kb_home / project / DECISIONS_DIR_NAME


def find_decision_dirs(kb_home: Path, project: str | None) -> list[Path]:
    """Decision dirs to scan: one project's, or every project's.

    Returns sorted existing ``<project>/decisions`` dirs. The vault's own
    dirs and projects with no decisions dir are skipped, so an
    un-initialized vault yields ``[]`` rather than raising.
    """
    if project is not None:
        one_dir = decisions_dir(kb_home, validate_project(project))
        assert_inside_vault(kb_home, one_dir)
        return [one_dir] if one_dir.exists() else []
    if not kb_home.exists():
        return []
    root = kb_home.resolve()
    dirs = []
    for entry in sorted(kb_home.iterdir()):
        if not entry.is_dir() or entry.name in VAULT_OWN_DIRS:
            continue
        project_decisions_dir = entry / DECISIONS_DIR_NAME
        if not project_decisions_dir.exists():
            continue
        # Resolving the WHOLE path, not just the project dir, is what
        # matters: is_dir() follows symlinks, so either a symlinked
        # project or a symlinked decisions dir inside a real project
        # would otherwise let an audit read notes outside the vault.
        if not project_decisions_dir.resolve().is_relative_to(root):
            log.warning(
                "skipping %s, it resolves outside %s",
                project_decisions_dir, root,
            )
            continue
        dirs.append(project_decisions_dir)
    return dirs


def build_note_path(decisions_dir_path: Path, topic_slug: str, today: str) -> Path:
    """Pick the destination filename, suffixing on a same-day collision.

    Returns ``<dir>/<topic_slug>__<today>.md``, or ``...__<today>-2.md``,
    ``-3``, ... for the first free name when that already exists.
    """
    base = decisions_dir_path / f"{topic_slug}__{today}.md"
    if not base.exists():
        return base
    n = 2
    while (candidate := decisions_dir_path / f"{topic_slug}__{today}-{n}.md").exists():
        n += 1
    return candidate


# ── revision chain ────────────────────────────────────────────────────


def find_notes_for_topic(
    decision_dirs: Sequence[Path], topic: str,
) -> list[Decision]:
    """Every decision note recorded under ``topic``, any status.

    Returns unsorted matches. ``audit()`` orders them by walking the
    ``revises`` chain, never by sorting on ``decision_date``.

    A note is only read when it resolves inside the decisions dir it was
    found in: a symlinked *file* would otherwise let an audit read
    markdown from anywhere on the host.
    """
    notes: list[Decision] = []
    for decision_dir in decision_dirs:
        if not decision_dir.exists():
            continue
        root = decision_dir.resolve()
        for path in decision_dir.glob("*.md"):
            if not path.resolve().is_relative_to(root):
                log.warning("skipping %s, it resolves outside %s", path, root)
                continue
            notes.append(load_decision(path))
    return [note for note in notes if note.topic == topic]


def find_active_note(
    decision_dirs: Sequence[Path], topic: str,
) -> Decision | None:
    """The topic's current active note, or ``None`` if the topic is new."""
    for note in find_notes_for_topic(decision_dirs, topic):
        if note.status == ACTIVE:
            return note
    return None


def resolve_revises_path(
    revises_arg: str | None,
    decision_dirs: Sequence[Path],
    topic: str,
) -> Path | None:
    """Pick the note being revised.

    An explicit path wins; otherwise the topic's current active note;
    otherwise ``None`` (a brand-new topic). An explicit path is resolved
    and REQUIRED to land inside the recording project's own decisions dir
    -- it names a file this service is about to rewrite, so it may not
    point anywhere else in (or out of) the vault.

    ``decision_dirs`` here is the RECORDING project's dir only, never
    every project's: a cross-project topic-name collision must not
    silently flip another project's note to revised.

    Raises:
        ValueError: an explicit path outside the project's decisions dir,
            naming a file that does not exist, or pointing at a note
            belonging to a different topic.
    """
    if revises_arg:
        candidate = Path(revises_arg).resolve()
        allowed = [d.resolve() for d in decision_dirs]
        if candidate.parent not in allowed or candidate.suffix != ".md":
            raise ValueError(
                f"revises {revises_arg!r} is not a decision note of "
                "this project"
            )
        if not candidate.is_file():
            raise ValueError(f"revises {revises_arg!r} does not exist")
        target_note = load_decision(candidate)
        if target_note.topic != topic:
            raise ValueError(
                f"revises {revises_arg!r} belongs to topic "
                f"{target_note.topic!r}, expected {topic!r}"
            )
        return candidate
    active = find_active_note(decision_dirs, topic)
    return active.path if active else None


# ── record / audit cores ──────────────────────────────────────────────


def compose_body(text: str, rationale: str, refs: str) -> str:
    """Assemble the note body from the decision, its rationale and refs.

    Sections are ``## Rationale`` and ``## Refs``, each omitted when its
    argument is empty. Postcondition: every part is stripped.
    """
    body_parts = [text.strip()]
    if rationale:
        body_parts.append(f"## Rationale\n\n{rationale.strip()}")
    if refs:
        body_parts.append(f"## Refs\n\n{refs.strip()}")
    return "\n\n".join(body_parts)


def _parse_tag_field(raw: object) -> list[str]:
    """Accept either a list of tags or a comma-separated string."""
    if isinstance(raw, list):
        values = [str(tag) for tag in raw]
    else:
        values = str(raw or "").split(",")
    return [
        validate_scalar(tag.strip(), "tag")
        for tag in values
        if tag.strip()
    ]


def record(kb_home: Path, payload: Mapping[str, object]) -> dict[str, str]:
    """Write a new active decision note, revising the topic's prior one.

    Args:
        kb_home: the vault root.
        payload: ``project``, ``topic``, ``title``, ``text`` (all
            required), plus optional ``rationale``, ``refs``, ``tags``,
            ``revises``.

    Returns:
        ``{"path": <new note>, "revises": <prior note or "">}``.

    Side effects, in order: creates the project's decisions dir; rewrites
    the revised note with ``status: revised``; writes the new note
    with ``status: active`` and today's date. Postcondition: the topic has
    exactly one active note.

    Raises:
        ValueError: any field failing validation (see kb_vault).
    """
    project = validate_project(payload.get("project"))
    topic = validate_scalar(payload.get("topic"), "topic", required=True)
    title = validate_scalar(payload.get("title"), "title", required=True)
    text = str(payload.get("text") or "")
    if not text.strip():
        raise ValueError("text is required")

    project_decisions_dir = decisions_dir(kb_home, project)
    assert_inside_vault(kb_home, project_decisions_dir)
    project_decisions_dir.mkdir(parents=True, exist_ok=True)
    assert_inside_vault(kb_home, project_decisions_dir)
    today = date.today().isoformat()
    note_path = build_note_path(project_decisions_dir, slugify(topic), today)
    assert_inside_vault(kb_home, note_path)

    revises_raw = payload.get("revises")
    revises_path = resolve_revises_path(
        str(revises_raw) if revises_raw else None,
        [project_decisions_dir],
        topic,
    )
    if revises_path is not None:
        prior = load_decision(revises_path)
        prior.status = REVISED
        prior.path.write_text(render_decision(prior), encoding="utf-8")

    new_note = Decision(
        path=note_path,
        title=title,
        topic=topic,
        decision_date=today,
        status=ACTIVE,
        revises=str(revises_path) if revises_path else "",
        tags=_parse_tag_field(payload.get("tags")),
        body=compose_body(
            text,
            str(payload.get("rationale") or ""),
            str(payload.get("refs") or ""),
        ),
    )
    note_path.write_text(render_decision(new_note), encoding="utf-8")
    return {"path": str(note_path), "revises": new_note.revises}


def _revises_targets(revises: str, path: Path) -> bool:
    """True when a note's raw ``revises`` string names ``path``.

    Compares resolved paths, not raw strings, so the chain walk survives
    path aliasing (a bind-mounted ``/home`` vs ``/var/home`` alias) or a
    relative link. An empty ``revises`` (a topic's root note) never
    matches: ``Path("").resolve()`` is the cwd, which must not match.
    """
    if not revises:
        return False
    return Path(revises).resolve() == path.resolve()


def _same_day_suffix(note: Decision) -> int:
    """The collision counter ``build_note_path`` gave this note's name.

    ``<topic>__<date>.md`` is ``1``; ``...-2.md`` parses to ``2``. Lets
    the audit fallback sort same-day notes in recording order instead of
    ASCII filename order, where ``"...-2.md"`` sorts before the
    un-suffixed ``"....md"`` -- backwards. The regex is anchored on the
    note's own ``decision_date`` because the date itself ends in two
    digits, which a date-blind pattern misreads as a suffix.
    """
    pattern = re.compile(rf"__{re.escape(note.decision_date)}(?:-(\d+))?\.md$")
    match = pattern.search(note.path.name)
    if match and match.group(1):
        return int(match.group(1))
    return 1


def _fallback_chain_order(
    notes: list[Decision], topic: str, reason: str,
) -> list[Decision]:
    """Degrade to a best-effort order and say so, loudly, in the log.

    Used when the ``revises`` chain walk cannot account for every note
    (no single root, or a broken link) -- the exact condition the chain
    walk exists to avoid, so a caller trusting this order silently would
    be back to the original ordering bug.
    """
    log.warning(
        "kb decision audit: topic %r: %s; chain walk could not be "
        "completed, falling back to a date+suffix sort (order is NOT "
        "chain-verified)", topic, reason,
    )
    return sorted(notes, key=lambda n: (n.decision_date, _same_day_suffix(n)))


def audit(decision_dirs: Sequence[Path], topic: str) -> list[Decision]:
    """The topic's full revision chain, oldest decision first.

    Ordering walks the ``revises`` links instead of sorting on
    ``decision_date``: recording a decision and correcting it same-day is
    normal, so two notes can tie on date and a date sort can silently
    print the chain backwards.

    The walk starts at the one note with an empty ``revises``, then
    repeatedly follows whichever note points its ``revises`` at the
    current one, matched by resolved path. Falls back to a best-effort
    sort, with a warning naming the topic, when that walk cannot account
    for every note found. Postcondition: an unknown topic gives ``[]``.
    """
    notes = find_notes_for_topic(decision_dirs, topic)
    if not notes:
        return []
    roots = [note for note in notes if not note.revises]
    if len(roots) != 1:
        reason = (
            "no note has an empty revises (no root to start from)"
            if not roots
            else f"{len(roots)} notes have an empty revises (ambiguous root)"
        )
        return _fallback_chain_order(notes, topic, reason)

    chain = [roots[0]]
    seen = {str(roots[0].path)}
    while (
        next_note := next(
            (n for n in notes if _revises_targets(n.revises, chain[-1].path)),
            None,
        )
    ) is not None and str(next_note.path) not in seen:
        chain.append(next_note)
        seen.add(str(next_note.path))

    if len(chain) != len(notes):
        reason = (
            f"chain walk only reached {len(chain)} of {len(notes)} notes "
            "(a broken or dangling revises link)"
        )
        return _fallback_chain_order(notes, topic, reason)
    return chain
