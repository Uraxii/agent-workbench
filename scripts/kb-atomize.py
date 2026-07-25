#!/usr/bin/env python3
"""kb-atomize.py -- deterministic atomic-note splitter for the personal
knowledgebase vault (see scripts/kb.sh).

Long `source`/`research` notes get split by markdown H2/H3 headings into
one child note per section, each inheriting the parent note's frontmatter
plus a `parent` ref back to it (and keeping the parent's source url in
`## Refs`). Already-atomic notes are left untouched: decisions/notes, or
a source/research note whose body is short and headingless. Deterministic,
zero model calls.

Usage:
    scripts/kb-atomize.py NOTE_PATH [--kb-home DIR]

Defaults: --kb-home = KB_HOME env, else ~/.knowledgebase.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

__all__ = ["kb_atomize", "render_child_note", "split_sections", "build_parser", "main"]

SCRIPT_DIR = Path(__file__).resolve().parent

# Below this size, or with no H2/H3 headings, a note is already atomic
# enough on its own; splitting it would just create noise.
ATOMIZE_MIN_CHARS = 1500
ATOMIC_TYPES = frozenset({"decision", "note"})
# Matches a line of exactly 2 or 3 '#' followed by a space, i.e. H2/H3 only
# (kb-clip.py's html_to_markdown always emits "## text" / "### text").
HEADING_RE = re.compile(r"^(#{2,3})[ \t]+(.+?)\s*$", re.MULTILINE)

# Extra frontmatter field this script adds on top of the LOCKED vault
# schema, pointing a child note back at the source it was split from.
PARENT_FIELD = "parent"

# Every vault note ends with a "## Refs" footer (the LOCKED schema, see
# kb-clip.py's render_note and kb-serve.py's own render_note). That's
# structural boilerplate, not content, so it never becomes its own child.
REFS_HEADING = "refs"


def _load_sibling(name: str) -> types.ModuleType:
    """Import a hyphenated sibling script by path (see kb-serve.py's
    identical helper -- duplicated here rather than shared, since each
    script must stay independently runnable as its own CLI)."""
    path = SCRIPT_DIR / f"{name}.py"
    module_name = name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {path}")
    module = importlib.util.module_from_spec(spec)
    # See kb-serve.py's identical helper: dataclasses needs the module
    # registered in sys.modules before exec_module runs its decorators.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


kb_index = _load_sibling("kb-index")
kb_clip = _load_sibling("kb-clip")


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split body text on H2/H3 headings into (heading_text, section_body).

    Content before the first heading is dropped: the parent note still
    carries the full text, so a lead-in paragraph doesn't need its own
    atomic child (ponytail: simplest rule that matches "one note per
    section" without inventing a synthetic "intro" section name).
    """
    matches = list(HEADING_RE.finditer(body))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        if heading.lower() == REFS_HEADING:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_body = body[match.end():end].strip()
        if section_body:
            sections.append((heading, section_body))
    return sections


def render_child_note(
    parent_fields: dict[str, object], parent_path: Path, heading: str, body: str,
) -> str:
    """Serialize one atomized child note: parent frontmatter + parent ref."""
    tags = parent_fields.get("tags", [])
    frontmatter = {
        "type": parent_fields.get("type", "source"),
        "title": heading,
        "source": parent_fields.get("source", ""),
        "author": parent_fields.get("author", ""),
        "site": parent_fields.get("site", ""),
        "published": parent_fields.get("published", ""),
        "fetched": parent_fields.get("fetched", ""),
        "description": parent_fields.get("description", ""),
        "tags": kb_clip.yaml_list(tags if isinstance(tags, list) else []),
        "project": parent_fields.get("project", ""),
        "status": "active",
        "question": "",
        "summary": "",
    }
    lines = ["---"]
    for key in kb_clip.FRONTMATTER_FIELDS:
        value = frontmatter[key]
        rendered = value if key == "tags" else kb_clip.yaml_quote(str(value))
        lines.append(f"{key}: {rendered}")
    lines.append(f"{PARENT_FIELD}: {kb_clip.yaml_quote(str(parent_path))}")
    lines.extend(["---", "", body, "", "## Refs", ""])
    source = parent_fields.get("source", "")
    if source:
        lines.append(f"- {source}")
    lines.append(f"- parent note: {parent_path}")
    return "\n".join(lines) + "\n"


def kb_atomize(note_path: Path, kb_home: Path) -> list[Path]:
    """Split note_path into atomic child notes; returns their paths.

    No-op (empty list) for already-atomic notes: decisions/notes, or a
    source/research note whose body is short and headingless. Deterministic,
    no model calls. Children are written as siblings of note_path.
    """
    text = note_path.read_text(encoding="utf-8")
    fields, body = kb_index.parse_frontmatter(text)
    note_type = kb_index.derive_type(fields, note_path)
    if note_type in ATOMIC_TYPES or len(body) < ATOMIZE_MIN_CHARS:
        return []

    sections = split_sections(body)
    if len(sections) < 2:
        return []

    fields.setdefault("project", kb_index.derive_project(note_path, kb_home))
    children: list[Path] = []
    for heading, section_body in sections:
        slug = f"{note_path.stem}--{kb_clip.slugify(heading)}"
        child_path = kb_clip.build_note_path(note_path.parent, slug)
        child_path.write_text(
            render_child_note(fields, note_path, heading, section_body), encoding="utf-8",
        )
        children.append(child_path)
    return children


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("note_path", type=Path)
    parser.add_argument("--kb-home", default=None)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    kb_home = kb_index.resolve_kb_home(args.kb_home)
    children = kb_atomize(args.note_path.resolve(), kb_home)
    print(json.dumps({"parent": str(args.note_path), "children": [str(p) for p in children]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
