"""`kb decision` sub-subcommands -- dated, auditable decision notes.

Port of the standalone `record-decision` skill's ``record_decision.py``
into the agent-workbench CLI, so decisions are recorded by the same tool
that owns the rest of the vault instead of by a separate skill with its
own directory layout and its own forked index.

One decision is one markdown file under
``$KB_HOME/<project>/decisions/``, grouped by a stable ``topic`` key.
Recording a new decision for a topic that already has an ``active`` note
flips that prior note to ``superseded`` and points the new note's
``supersedes`` field at it, so the audit chain is the files plus their
frontmatter, never a separate database. Exactly one note per topic is
``active`` at any time.

Two things are deliberately NOT shared with the rest of the vault:

* Frontmatter dialect. Decision notes use bare, unquoted scalars
  (``title/topic/date/status/supersedes/tags``), NOT the quoted
  ``type/title/source/...`` schema kb-serve.py's ``render_note`` writes.
  Dozens of decision notes already on disk use the bare shape, and
  ``kb-index.py`` reads both, so this port keeps it byte-for-byte rather
  than migrating the corpus. See ``render_decision`` for the exact bytes.
* Write path. ``record`` writes the vault directly. Everything else in
  ``cli/kb.py`` prefers the kb-serve HTTP service when it is up. See the
  ``ponytail:`` note on ``cmd_record``.

Sub-subcommands (registered under `kb` by ``cli.kb``):
    decision record --topic T --title T --text T --project P [...]
    decision audit TOPIC [--project P] [--human]
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cli import siblings
from cli.paths import resolve_kb_home

__all__ = [
    "register",
    "Decision",
    "slugify",
    "parse_frontmatter",
    "parse_tags",
    "load_decision",
    "render_decision",
    "decisions_dir",
    "find_decision_dirs",
    "find_notes_for_topic",
    "find_active_note",
    "resolve_supersedes_path",
    "build_note_path",
    "compose_body",
    "record",
    "audit",
    "cmd_record",
    "cmd_audit",
]

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

# The vault subdir decision notes live in, under $KB_HOME/<project>/.
# Same name kb.py's NOTE_DIRS creates and kb-index.py's TYPE_BY_DIR maps
# to type=decision.
DECISIONS_DIR_NAME = "decisions"

# Vault-level dirs that are not projects, skipped when audit scans every
# project. Mirrors kb-index.find_markdown_files / kb.cmd_status.
NON_PROJECT_DIRS = frozenset({"index", ".obsidian"})

ACTIVE = "active"
SUPERSEDED = "superseded"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `decision` parser and its record/audit verbs to `kb`.

    Args:
        subparsers: the sub-subparsers action created by ``cli.kb.register``
            (NOT the top-level one; `decision` is a verb of `kb`).

    Postcondition: both leaf parsers have ``func`` set to a ``cmd_*``
    handler, matching the dispatch contract in ``cli.main.main``.
    """
    parser = subparsers.add_parser(
        "decision", help="record/audit dated decision notes"
    )
    sub = parser.add_subparsers(dest="decision_command", required=True)

    record_cmd = sub.add_parser("record", help="record a new decision")
    record_cmd.add_argument("--project", required=True)
    record_cmd.add_argument("--topic", required=True)
    record_cmd.add_argument("--title", required=True)
    record_cmd.add_argument("--text", required=True)
    record_cmd.add_argument("--rationale", default="")
    record_cmd.add_argument("--refs", default="")
    record_cmd.add_argument("--tags", default="", help="comma-separated")
    record_cmd.add_argument(
        "--supersedes",
        default=None,
        help="path of the note to supersede; default is the topic's "
             "current active note",
    )
    record_cmd.add_argument("--kb-home", default=None)
    record_cmd.set_defaults(func=cmd_record)

    audit_cmd = sub.add_parser("audit", help="show a topic's decision chain")
    audit_cmd.add_argument("topic")
    audit_cmd.add_argument(
        "--project",
        default=None,
        help="narrow to one project; default scans every project",
    )
    audit_cmd.add_argument(
        "--human", action="store_true", help="table instead of JSON"
    )
    audit_cmd.add_argument("--kb-home", default=None)
    audit_cmd.set_defaults(func=cmd_audit)


@dataclass
class Decision:
    """One decision note: its frontmatter plus body text.

    ``decision_date`` is the frontmatter ``date`` field (ISO ``YYYY-MM-DD``);
    it is spelled out here because ``date`` collides with
    ``datetime.date``. ``supersedes`` is the absolute path string of the
    note this one replaced, or ``""`` when the topic is new.
    """

    path: Path
    title: str
    topic: str
    decision_date: str
    status: str
    supersedes: str
    tags: list[str]
    body: str


# ── frontmatter dialect (bare scalars; LOCKED, see module docstring) ───


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

    # ponytail: hand-rolled scalar-only YAML (no pyyaml), same as
    # kb-index.parse_frontmatter. Not shared with it because that one
    # un-quotes values and expects a quoted tag list, which would corrupt
    # this dialect's bare scalars.
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
    """Parse a bare inline tag list: ``'[a, b, c]'`` -> ``['a','b','c']``.

    Postcondition: no empty strings in the result; ``'[]'`` and ``''``
    both give ``[]``.
    """
    stripped = raw.strip().strip("[]")
    if not stripped:
        return []
    return [tag.strip() for tag in stripped.split(",") if tag.strip()]


def load_decision(path: Path) -> Decision:
    """Read one decision note off disk into a ``Decision``.

    Preconditions: ``path`` is a readable UTF-8 markdown file.
    Postconditions: missing fields fall back to
    ``title=path.stem``, ``status="active"``, everything else empty.
    """
    fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    return Decision(
        path=path,
        title=fields.get("title", path.stem),
        topic=fields.get("topic", ""),
        decision_date=fields.get("date", ""),
        status=fields.get("status", ACTIVE),
        supersedes=fields.get("supersedes", ""),
        tags=parse_tags(fields.get("tags", "[]")),
        body=body,
    )


def render_decision(decision: Decision) -> str:
    """Serialize a ``Decision`` back to frontmatter + body markdown.

    LOCKED byte shape -- the notes already in the vault must stay
    round-trippable, so this is byte-identical to
    ``record_decision.render_decision``:

        ---
        title: {title}
        topic: {topic}
        date: {decision_date}
        status: {status}
        supersedes: {supersedes}
        tags: [{", ".join(tags)}]
        ---

        {body}

    Two details that look like bugs and are NOT: an empty ``supersedes``
    leaves a trailing space after the colon (``"supersedes: \\n"``), and
    values are never quoted or escaped. Both match every note on disk.
    Postcondition: the returned text ends with exactly one newline.
    """
    tags = ", ".join(decision.tags)
    return (
        "---\n"
        f"title: {decision.title}\n"
        f"topic: {decision.topic}\n"
        f"date: {decision.decision_date}\n"
        f"status: {decision.status}\n"
        f"supersedes: {decision.supersedes}\n"
        f"tags: [{tags}]\n"
        "---\n\n"
        f"{decision.body}\n"
    )


# ── vault layout ──────────────────────────────────────────────────────


def decisions_dir(kb_home: Path, project: str) -> Path:
    """Return ``$KB_HOME/<project>/decisions`` (not created here)."""
    return kb_home / project / DECISIONS_DIR_NAME


def find_decision_dirs(kb_home: Path, project: str | None) -> list[Path]:
    """Decision dirs to scan: one project's, or every project's.

    Args:
        kb_home: the vault root.
        project: a single project name, or ``None`` to scan them all.

    Returns:
        Sorted existing ``<project>/decisions`` dirs. Non-project vault
        dirs (``index``, ``.obsidian``) and projects with no decisions
        dir are skipped, so an un-initialized vault yields ``[]`` rather
        than raising.
    """
    if project is not None:
        one_dir = decisions_dir(kb_home, project)
        return [one_dir] if one_dir.exists() else []
    if not kb_home.exists():
        return []
    dirs = []
    for entry in sorted(kb_home.iterdir()):
        if not entry.is_dir() or entry.name in NON_PROJECT_DIRS:
            continue
        project_decisions_dir = entry / DECISIONS_DIR_NAME
        if project_decisions_dir.exists():
            dirs.append(project_decisions_dir)
    return dirs


def build_note_path(decisions_dir_path: Path, topic_slug: str, today: str) -> Path:
    """Pick the destination filename, suffixing on a same-day collision.

    Returns ``<dir>/<topic_slug>__<today>.md``, or
    ``...__<today>-2.md``, ``-3``, ... for the first free name when that
    already exists.

    # ponytail: same topic + same day is rare (one manual command per
    # decision moment), so a counter suffix beats a timestamp-in-filename
    # scheme nobody asked for.
    """
    base = decisions_dir_path / f"{topic_slug}__{today}.md"
    if not base.exists():
        return base
    n = 2
    while (candidate := decisions_dir_path / f"{topic_slug}__{today}-{n}.md").exists():
        n += 1
    return candidate


# ── supersession chain ────────────────────────────────────────────────


def find_notes_for_topic(
    decision_dirs: Sequence[Path], topic: str
) -> list[Decision]:
    """Every decision note recorded under ``topic``, any status.

    Args:
        decision_dirs: dirs to glob (see ``find_decision_dirs``);
            non-existent entries are skipped.
        topic: exact frontmatter ``topic`` match, no slugging.

    Returns:
        Unsorted matches. Callers that display a chain sort by
        ``decision_date``.
    """
    notes: list[Decision] = []
    for decision_dir in decision_dirs:
        if not decision_dir.exists():
            continue
        notes.extend(load_decision(p) for p in decision_dir.glob("*.md"))
    return [note for note in notes if note.topic == topic]


def find_active_note(
    decision_dirs: Sequence[Path], topic: str
) -> Decision | None:
    """The topic's current active note, or ``None`` if the topic is new.

    Postcondition (invariant this module maintains): at most one note per
    topic has ``status == "active"``, so returning the first match is
    unambiguous.
    """
    for note in find_notes_for_topic(decision_dirs, topic):
        if note.status == ACTIVE:
            return note
    return None


def resolve_supersedes_path(
    supersedes_arg: str | None, decision_dirs: Sequence[Path], topic: str
) -> Path | None:
    """Pick the note being superseded.

    An explicit ``--supersedes`` path wins; otherwise the topic's current
    active note; otherwise ``None`` (a brand-new topic).

    Note that ``decision_dirs`` here is the RECORDING project's dir only,
    never every project's: a cross-project topic-name collision must not
    silently flip another project's note to superseded.
    """
    if supersedes_arg:
        return Path(supersedes_arg)
    active = find_active_note(decision_dirs, topic)
    return active.path if active else None


# ── record / audit cores (no argparse, no stdout) ─────────────────────


def compose_body(text: str, rationale: str, refs: str) -> str:
    """Assemble the note body from the decision, its rationale and refs.

    Sections are ``## Rationale`` and ``## Refs``, each omitted when its
    argument is empty, joined by blank lines. Postcondition: no trailing
    whitespace; every part is stripped.
    """
    body_parts = [text.strip()]
    if rationale:
        body_parts.append(f"## Rationale\n\n{rationale.strip()}")
    if refs:
        body_parts.append(f"## Refs\n\n{refs.strip()}")
    return "\n\n".join(body_parts)


def record(kb_home: Path, args: argparse.Namespace) -> dict[str, str]:
    """Write a new active decision note, superseding the topic's prior one.

    Args:
        kb_home: the vault root.
        args: parsed ``decision record`` args -- project, topic, title,
            text, rationale, refs, tags, supersedes.

    Returns:
        ``{"path": <new note>, "supersedes": <prior note or "">}``.

    Side effects, in order: creates the project's decisions dir; rewrites
    the superseded note with ``status: superseded``; writes the new note
    with ``status: active`` and today's date. Postcondition: the topic has
    exactly one active note.
    """
    project_decisions_dir = decisions_dir(kb_home, args.project)
    project_decisions_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    note_path = build_note_path(project_decisions_dir, slugify(args.topic), today)

    supersedes_path = resolve_supersedes_path(
        args.supersedes, [project_decisions_dir], args.topic
    )
    if supersedes_path is not None:
        prior = load_decision(supersedes_path)
        prior.status = SUPERSEDED
        prior.path.write_text(render_decision(prior), encoding="utf-8")

    new_note = Decision(
        path=note_path,
        title=args.title,
        topic=args.topic,
        decision_date=today,
        status=ACTIVE,
        supersedes=str(supersedes_path) if supersedes_path else "",
        tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        body=compose_body(args.text, args.rationale, args.refs),
    )
    note_path.write_text(render_decision(new_note), encoding="utf-8")
    return {"path": str(note_path), "supersedes": new_note.supersedes}


def audit(decision_dirs: Sequence[Path], topic: str) -> list[Decision]:
    """The topic's full supersession chain, oldest decision first.

    Ordering walks the ``supersedes`` links instead of sorting on
    ``decision_date``: recording a decision and correcting it same-day is
    normal, so two notes can tie on date, and which one ``Path.glob``
    happened to return first is unspecified -- a date sort (with or
    without a filename tiebreak; ``"...-2.md"`` sorts before
    ``"....md"``) can silently print the chain backwards.

    The walk starts at the one note with an empty ``supersedes`` (the
    topic's original -- nothing preceded it), then repeatedly follows
    whichever note points its ``supersedes`` at the current one. Falls
    back to a stable ``decision_date`` sort when that walk can't fully
    account for every note found -- no single root, or a broken/dangling
    link -- which should not happen but must degrade instead of raising.

    Postcondition: an unknown topic gives ``[]``.
    """
    notes = find_notes_for_topic(decision_dirs, topic)
    if not notes:
        return []
    roots = [note for note in notes if not note.supersedes]
    if len(roots) != 1:
        return sorted(notes, key=lambda n: n.decision_date)

    chain = [roots[0]]
    seen = {str(roots[0].path)}
    while (
        next_note := next(
            (n for n in notes if n.supersedes == str(chain[-1].path)), None
        )
    ) is not None and str(next_note.path) not in seen:
        chain.append(next_note)
        seen.add(str(next_note.path))

    if len(chain) != len(notes):
        return sorted(notes, key=lambda n: n.decision_date)
    return chain


# ── command handlers ──────────────────────────────────────────────────


def cmd_record(args: argparse.Namespace) -> int:
    """Record a decision, reindex the vault, print the result as JSON.

    Reindexing keeps a just-recorded decision immediately findable by
    ``kb query``, the same guarantee ``kb put`` gives. Like `kb put`'s
    in-process path, kb-index's own ``{"indexed": N, "db": ...}`` line
    lands on stdout BEFORE this command's result object.

    # ponytail: writes the vault filesystem directly instead of going
    # through kb-serve, so it breaks the "containers are the only I/O
    # path to kb" rule (decision topic
    # agent-workbench-service-layer-boundary). Lifting this to a kb-serve
    # POST /decision endpoint belongs to the service-layer epic
    # (agent-workbench-vno), not here.
    """
    kb_home = resolve_kb_home(args.kb_home)
    result = record(kb_home, args)
    siblings.load_kb_serve().build_index(kb_home)
    print(json.dumps(result))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Print a topic's decision chain: JSON by default, table with --human.

    Read-only. Scans every project's decisions dir unless ``--project``
    narrows it, because topic keys are globally unique by convention and
    a reader auditing a topic rarely knows which project holds it.

    JSON rows carry ``date``, ``status``, ``title``, ``path``,
    ``supersedes``. The ``--human`` line is verbatim from the standalone
    skill: ``"{date}  {status:12} {title}  (supersedes: {path or '-'})"``.
    """
    dirs = find_decision_dirs(resolve_kb_home(args.kb_home), args.project)
    notes = audit(dirs, args.topic)
    if args.human:
        for note in notes:
            print(
                f"{note.decision_date}  {note.status:12} {note.title}"
                f"  (supersedes: {note.supersedes or '-'})"
            )
        return 0
    chain = [
        {
            "date": note.decision_date,
            "status": note.status,
            "title": note.title,
            "path": str(note.path),
            "supersedes": note.supersedes,
        }
        for note in notes
    ]
    print(json.dumps(chain, indent=2))
    return 0
