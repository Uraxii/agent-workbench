"""Tests for scripts/kb_decision.py -- dated, auditable decision notes,
recorded and audited by the knowledgebase service behind
`kb decision record|audit`.

Mirrors tests/test_kb_serve.py's own style: everything runs against
tmp_path vaults, never the real ~/.knowledgebase, and the service
modules are imported with scripts/ on sys.path.

Covers the skeptic-gate fold-in fixes:
* Bug 2 -- audit() orders a topic's chain by walking the `supersedes`
  links, not by sorting on `decision_date` (same-day record+supersede
  is normal and ties under a date-only sort).
* Bug 2 re-review -- the chain walk matches `supersedes` by resolved
  path, not raw string equality, so an aliased/symlinked path or a
  relative `--supersedes` flag still walks correctly, and any fallback
  that still can't fully walk the chain warns on stderr instead of
  silently reverting to the known-wrong date sort.
* render_decision/load_decision's LOCKED byte shape.
* The supersede flip on `record()`.
* build_note_path's same-day collision suffix.
* resolve_supersedes_path never crossing project boundaries.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import kb_decision  # noqa: E402


def _record_args(
    *,
    project: str,
    topic: str,
    title: str,
    text: str,
    rationale: str = "",
    refs: str = "",
    tags: str = "",
    supersedes: str | None = None,
) -> dict[str, object]:
    """A `POST /decision` payload, shaped like the endpoint's own."""
    return {
        "project": project, "topic": topic, "title": title, "text": text,
        "rationale": rationale, "refs": refs, "tags": tags,
        "supersedes": supersedes,
    }


# ── render_decision / load_decision: LOCKED byte shape + round trip ──────


def test_render_decision_matches_locked_byte_shape() -> None:
    decision = kb_decision.Decision(
        path=Path("unused.md"),
        title="My Title",
        topic="my-topic",
        decision_date="2026-07-27",
        status="active",
        supersedes="",
        tags=["a", "b"],
        body="Body text.",
    )
    assert kb_decision.render_decision(decision) == (
        "---\n"
        "title: My Title\n"
        "topic: my-topic\n"
        "date: 2026-07-27\n"
        "status: active\n"
        "supersedes: \n"  # trailing space after an empty supersedes: LOCKED
        "tags: [a, b]\n"
        "---\n\n"
        "Body text.\n"
    )


def test_render_decision_load_decision_round_trip(tmp_path: Path) -> None:
    decision = kb_decision.Decision(
        path=tmp_path / "note.md",
        title="[H3] a title that looks bracketed",
        topic="my-topic",
        decision_date="2026-07-27",
        status="superseded",
        supersedes=str(tmp_path / "prior.md"),
        tags=["alpha", "beta"],
        body="Some body text.\n\n## Rationale\n\nBecause reasons.",
    )
    decision.path.write_text(kb_decision.render_decision(decision), encoding="utf-8")

    loaded = kb_decision.load_decision(decision.path)

    assert loaded == decision


# ── record(): the supersede flip ─────────────────────────────────────────


def test_record_second_decision_supersedes_the_prior_note(tmp_path: Path) -> None:
    first = kb_decision.record(tmp_path, _record_args(
        project="proj", topic="my-topic", title="First", text="first text",
    ))
    second = kb_decision.record(tmp_path, _record_args(
        project="proj", topic="my-topic", title="Second", text="second text",
    ))

    prior_path = Path(first["path"])
    prior = kb_decision.load_decision(prior_path)
    assert prior.status == kb_decision.SUPERSEDED

    new_note = kb_decision.load_decision(Path(second["path"]))
    assert new_note.status == kb_decision.ACTIVE
    assert new_note.supersedes == str(prior_path)
    assert second["supersedes"] == str(prior_path)


# ── build_note_path: same-day collision suffix ───────────────────────────


def test_build_note_path_suffixes_on_same_day_collision(tmp_path: Path) -> None:
    today = "2026-07-27"

    first = kb_decision.build_note_path(tmp_path, "topic-x", today)
    assert first == tmp_path / "topic-x__2026-07-27.md"
    first.write_text("x", encoding="utf-8")

    second = kb_decision.build_note_path(tmp_path, "topic-x", today)
    assert second == tmp_path / "topic-x__2026-07-27-2.md"
    second.write_text("x", encoding="utf-8")

    third = kb_decision.build_note_path(tmp_path, "topic-x", today)
    assert third == tmp_path / "topic-x__2026-07-27-3.md"


# ── resolve_supersedes_path: never crosses project boundaries ───────────


def test_resolve_supersedes_path_ignores_another_projects_same_named_topic(
    tmp_path: Path,
) -> None:
    dir_a = tmp_path / "proj-a" / "decisions"
    dir_b = tmp_path / "proj-b" / "decisions"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    kb_decision.record(tmp_path, _record_args(
        project="proj-a", topic="shared-topic", title="A1", text="a1 text",
    ))

    # Project B has no note at all for this topic yet; scoping the lookup
    # to dir_b alone must find nothing, even though project A's note for
    # the identical topic string exists right next door.
    supersedes_in_b = kb_decision.resolve_supersedes_path(None, [dir_b], "shared-topic")
    assert supersedes_in_b is None

    supersedes_in_a = kb_decision.resolve_supersedes_path(None, [dir_a], "shared-topic")
    assert supersedes_in_a is not None
    assert supersedes_in_a.parent == dir_a


def test_record_in_one_project_never_touches_another_projects_note(
    tmp_path: Path,
) -> None:
    kb_decision.record(tmp_path, _record_args(
        project="proj-a", topic="shared-topic", title="A1", text="a1 text",
    ))
    kb_decision.record(tmp_path, _record_args(
        project="proj-b", topic="shared-topic", title="B1", text="b1 text",
    ))

    a_note = kb_decision.load_decision(
        next(kb_decision.decisions_dir(tmp_path, "proj-a").glob("*.md"))
    )
    b_note = kb_decision.load_decision(
        next(kb_decision.decisions_dir(tmp_path, "proj-b").glob("*.md"))
    )
    # Recording project B's decision must not flip project A's note,
    # despite the identical topic key.
    assert a_note.status == kb_decision.ACTIVE
    assert b_note.status == kb_decision.ACTIVE


# ── audit(): supersedes-chain ordering fix (Bug 2) ───────────────────────


def test_audit_single_note_topic_returns_that_note(tmp_path: Path) -> None:
    kb_decision.record(tmp_path, _record_args(
        project="proj", topic="solo-topic", title="Solo", text="solo text",
    ))
    decision_dir = kb_decision.decisions_dir(tmp_path, "proj")

    chain = kb_decision.audit([decision_dir], "solo-topic")

    assert [n.title for n in chain] == ["Solo"]


def test_audit_orders_same_day_chain_oldest_first_despite_reversed_glob_order(
    tmp_path: Path,
) -> None:
    """Base + same-day supersede is the normal case this fix targets: both
    notes share a decision_date, so a naive date sort ties and falls back
    to whatever order Path.glob happens to return -- not guaranteed
    chronological. Patching find_notes_for_topic to hand audit() the
    notes in the wrong (newest-first) order proves the ordering comes
    from walking the supersedes chain, not from the input order or any
    filename tiebreak."""
    kb_decision.record(tmp_path, _record_args(
        project="proj", topic="same-day-topic", title="Base", text="base text",
    ))
    kb_decision.record(tmp_path, _record_args(
        project="proj", topic="same-day-topic", title="Supersede", text="new text",
    ))
    decision_dir = kb_decision.decisions_dir(tmp_path, "proj")
    notes = kb_decision.find_notes_for_topic([decision_dir], "same-day-topic")
    assert len(notes) == 2
    assert notes[0].decision_date == notes[1].decision_date  # genuinely same-day

    wrong_order = sorted(notes, key=lambda n: n.status != kb_decision.ACTIVE)  # active/newest first

    with patch.object(kb_decision, "find_notes_for_topic", return_value=wrong_order):
        chain = kb_decision.audit([decision_dir], "same-day-topic")

    assert [n.title for n in chain] == ["Base", "Supersede"]
    assert chain[0].status == kb_decision.SUPERSEDED
    assert chain[1].status == kb_decision.ACTIVE


def test_audit_falls_back_to_date_sort_when_no_unreferenced_root(
    tmp_path: Path,
) -> None:
    """Not-yet-possible-but-be-safe case: corrupted data where every note
    claims to supersede another (no root to start the walk from). Must
    degrade to a stable decision_date sort, never raise."""
    decision_dir = tmp_path / "decisions"
    decision_dir.mkdir()
    note_a = kb_decision.Decision(
        path=decision_dir / "a.md", title="A", topic="corrupt-topic",
        decision_date="2026-07-01", status=kb_decision.SUPERSEDED,
        supersedes=str(decision_dir / "b.md"), tags=[], body="a",
    )
    note_b = kb_decision.Decision(
        path=decision_dir / "b.md", title="B", topic="corrupt-topic",
        decision_date="2026-07-02", status=kb_decision.ACTIVE,
        supersedes=str(decision_dir / "a.md"), tags=[], body="b",
    )
    note_a.path.write_text(kb_decision.render_decision(note_a), encoding="utf-8")
    note_b.path.write_text(kb_decision.render_decision(note_b), encoding="utf-8")

    chain = kb_decision.audit([decision_dir], "corrupt-topic")

    assert [n.title for n in chain] == ["A", "B"]  # ascending decision_date fallback


# ── audit(): chain-walk resolved-path match (skeptic-gate re-review) ────


def test_audit_chain_walk_matches_supersedes_through_an_aliased_path(
    tmp_path: Path,
) -> None:
    """Reproduces the re-review repro without needing this machine's own
    /home -> /var/home symlink: a tmp_path directory standing in for the
    real vault, plus a second symlinked directory standing in for the
    alias, so `supersedes` and `path` name the same file through two
    genuinely different raw strings. Also stands in for the relative
    `--supersedes` flag case, since a relative path has exactly the same
    "differs as a string, same file once resolved" shape.

    Before the fix this raw-string mismatch made the chain walk think
    note_b's link dangled, silently falling back to the date sort --
    right by luck here (dates already ascend) but wrong in general, and
    indistinguishable from a correct result either way.
    """
    real_dir = tmp_path / "vault" / "decisions"
    real_dir.mkdir(parents=True)
    alias_root = tmp_path / "vault-alias"
    alias_root.symlink_to(tmp_path / "vault")

    note_a = kb_decision.Decision(
        path=real_dir / "a.md", title="A", topic="alias-topic",
        decision_date="2026-07-01", status=kb_decision.SUPERSEDED,
        supersedes="", tags=[], body="a",
    )
    aliased_supersedes = str(alias_root / "decisions" / "a.md")
    note_b = kb_decision.Decision(
        path=real_dir / "b.md", title="B", topic="alias-topic",
        decision_date="2026-07-02", status=kb_decision.ACTIVE,
        supersedes=aliased_supersedes, tags=[], body="b",
    )
    note_a.path.write_text(kb_decision.render_decision(note_a), encoding="utf-8")
    note_b.path.write_text(kb_decision.render_decision(note_b), encoding="utf-8")

    assert aliased_supersedes != str(note_a.path)  # raw strings genuinely differ

    chain = kb_decision.audit([real_dir], "alias-topic")

    assert [n.title for n in chain] == ["A", "B"]


def test_audit_falls_back_and_warns_on_dangling_supersedes_link(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A `supersedes` string that resolves to no real note (corrupt data,
    or a note copied in from elsewhere without its target) must still
    degrade to the date-sort fallback rather than raise -- and, unlike
    the pre-fix behaviour, must say so in the log instead of silently
    handing back an order that might be wrong."""
    decision_dir = tmp_path / "decisions"
    decision_dir.mkdir()
    note_a = kb_decision.Decision(
        path=decision_dir / "a.md", title="A", topic="dangling-topic",
        decision_date="2026-07-01", status=kb_decision.SUPERSEDED,
        supersedes="", tags=[], body="a",
    )
    note_b = kb_decision.Decision(
        path=decision_dir / "b.md", title="B", topic="dangling-topic",
        decision_date="2026-07-02", status=kb_decision.ACTIVE,
        supersedes=str(decision_dir / "does-not-exist.md"), tags=[], body="b",
    )
    note_a.path.write_text(kb_decision.render_decision(note_a), encoding="utf-8")
    note_b.path.write_text(kb_decision.render_decision(note_b), encoding="utf-8")

    with caplog.at_level("WARNING"):
        chain = kb_decision.audit([decision_dir], "dangling-topic")

    assert [n.title for n in chain] == ["A", "B"]  # degrades, doesn't raise
    warning = caplog.text
    assert "dangling-topic" in warning
    assert "not chain-verified" in warning.lower()


def test_audit_fallback_orders_same_day_notes_by_recording_suffix(
    tmp_path: Path,
) -> None:
    """Regression guard on the fallback's own suffix parser: a note's
    `decision_date` itself ends in two digits (`...-22.md`), so a
    date-blind `-\\d+\\.md` pattern misreads the UN-suffixed note's date
    tail as a fake large suffix and sorts it last instead of first. Two
    real `build_note_path`-named same-day notes, with a dangling
    supersedes link forcing the fallback, must still land in recording
    order: the plain `__DATE.md` note before its `__DATE-2.md` sibling.
    """
    decision_dir = tmp_path / "decisions"
    decision_dir.mkdir()
    today = "2026-07-22"
    note_a = kb_decision.Decision(
        path=kb_decision.build_note_path(decision_dir, "topic-x", today),
        title="A", topic="topic-x", decision_date=today,
        status=kb_decision.SUPERSEDED, supersedes="", tags=[], body="a",
    )
    note_a.path.write_text(kb_decision.render_decision(note_a), encoding="utf-8")
    note_b = kb_decision.Decision(
        path=kb_decision.build_note_path(decision_dir, "topic-x", today),
        title="B", topic="topic-x", decision_date=today,
        status=kb_decision.ACTIVE,
        supersedes=str(tmp_path / "nowhere.md"), tags=[], body="b",
    )
    note_b.path.write_text(kb_decision.render_decision(note_b), encoding="utf-8")
    assert note_a.path.name == "topic-x__2026-07-22.md"
    assert note_b.path.name == "topic-x__2026-07-22-2.md"

    chain = kb_decision.audit([decision_dir], "topic-x")

    assert [n.title for n in chain] == ["A", "B"]


# ── audit(): the scan stays inside the vault ──────────────────────────


def test_find_decision_dirs_skips_a_symlinked_project(tmp_path: Path) -> None:
    """`entry.is_dir()` follows symlinks, so an audit would otherwise read
    decision notes from outside the vault."""
    vault = tmp_path / "vault"
    (vault / "proj" / "decisions").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "decisions").mkdir(parents=True)
    (vault / "escaped").symlink_to(outside)

    dirs = kb_decision.find_decision_dirs(vault, None)

    assert dirs == [vault / "proj" / "decisions"]


def test_find_decision_dirs_skips_a_symlinked_decisions_dir(
    tmp_path: Path,
) -> None:
    """The project dir can be real and its `decisions` dir a symlink out,
    so the whole path has to resolve inside the vault, not just its head."""
    vault = tmp_path / "vault"
    (vault / "proj").mkdir(parents=True)
    outside = tmp_path / "outside" / "decisions"
    outside.mkdir(parents=True)
    (vault / "proj" / "decisions").symlink_to(outside)

    assert kb_decision.find_decision_dirs(vault, None) == []


def test_find_decision_dirs_rejects_a_named_project_that_escapes(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "proj").mkdir(parents=True)
    outside = tmp_path / "outside" / "decisions"
    outside.mkdir(parents=True)
    (vault / "proj" / "decisions").symlink_to(outside)

    with pytest.raises(ValueError, match="outside the vault"):
        kb_decision.find_decision_dirs(vault, "proj")


def test_find_notes_for_topic_skips_a_symlinked_note(tmp_path: Path) -> None:
    decision_dir = tmp_path / "vault" / "proj" / "decisions"
    decision_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text(
        "---\ntitle: Secret\ntopic: leak-topic\ndate: 2026-07-01\n"
        "status: active\nsupersedes: \ntags: []\n---\n\nsecret body\n",
        encoding="utf-8",
    )
    (decision_dir / "link.md").symlink_to(outside)

    assert kb_decision.find_notes_for_topic([decision_dir], "leak-topic") == []


# ── resolve_supersedes_path: topic matching validation ──────────────────

def test_resolve_supersedes_path_rejects_mismatched_topic(
    tmp_path: Path,
) -> None:
    """When an explicit supersedes path is given, the target note's topic
    must match the topic being recorded. A cross-topic supersession is
    silently prevented."""
    # Create a note on topic "alpha"
    first = kb_decision.record(tmp_path, _record_args(
        project="proj", topic="alpha", title="Alpha Note", text="alpha text",
    ))
    alpha_note_path = Path(first["path"])
    assert alpha_note_path.exists()

    dir_a = alpha_note_path.parent

    # Try to record a decision on topic "beta" with --supersedes pointing
    # at the "alpha" note. This must be rejected.
    with pytest.raises(ValueError, match="belongs to topic"):
        kb_decision.resolve_supersedes_path(
            str(alpha_note_path), [dir_a], "beta",
        )


def test_record_rejects_supersedes_with_mismatched_topic_and_leaves_file_unmodified(
    tmp_path: Path,
) -> None:
    """Recording a decision on topic B with --supersedes pointing at a note
    on topic A must fail and the target note must remain byte-for-byte
    unmodified."""
    dir_a = tmp_path / "proj" / "decisions"
    dir_a.mkdir(parents=True)

    # Create a note on topic "alpha"
    first = kb_decision.record(tmp_path, _record_args(
        project="proj", topic="alpha", title="Alpha Note", text="alpha text",
    ))
    alpha_note_path = Path(first["path"])
    original_content = alpha_note_path.read_text(encoding="utf-8")

    # Try to record a decision on topic "beta" with --supersedes pointing
    # at the "alpha" note. This must fail.
    with pytest.raises(ValueError, match="belongs to topic"):
        kb_decision.record(tmp_path, _record_args(
            project="proj",
            topic="beta",
            title="Beta Note",
            text="beta text",
            supersedes=str(alpha_note_path),
        ))

    # Verify the alpha note is completely unmodified
    current_content = alpha_note_path.read_text(encoding="utf-8")
    assert current_content == original_content
    # And it's still active (not flipped to superseded)
    alpha_note = kb_decision.load_decision(alpha_note_path)
    assert alpha_note.status == kb_decision.ACTIVE


def test_record_with_matching_topic_still_supersedes_successfully(
    tmp_path: Path,
) -> None:
    """Verify the happy path still works: when an explicit supersedes path
    is given pointing at a note on the same topic, supersession happens
    normally (regression guard)."""
    # Create a note on topic "shared-topic"
    first = kb_decision.record(tmp_path, _record_args(
        project="proj", topic="shared-topic", title="First", text="first text",
    ))
    first_path = Path(first["path"])

    # Record a second decision on the same topic, explicitly superseding the first
    second = kb_decision.record(tmp_path, _record_args(
        project="proj",
        topic="shared-topic",
        title="Second",
        text="second text",
        supersedes=str(first_path),
    ))
    second_path = Path(second["path"])

    # Verify the first note is now superseded
    first_note = kb_decision.load_decision(first_path)
    assert first_note.status == kb_decision.SUPERSEDED

    # Verify the second note is active and points to the first
    second_note = kb_decision.load_decision(second_path)
    assert second_note.status == kb_decision.ACTIVE
    assert second_note.supersedes == str(first_path)
