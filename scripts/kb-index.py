#!/usr/bin/env python3
"""kb-index.py -- global recency-weighted FTS5 index over the personal
knowledgebase vault (see scripts/kb.sh).

The vault at KB_HOME holds one SOURCE tree per project
(KB_HOME/<project>/{decisions,notes,research,sources}/*.md) and one
DERIVED index shared across all of them (KB_HOME/index/kb.db). This
script builds that index and queries it. Stdlib only: sqlite3's bundled
FTS5 does full-text search, no external search engine.

Usage:
    scripts/kb-index.py [--kb-home DIR] build
    scripts/kb-index.py [--kb-home DIR] query "<terms>" [--project P]
                        [--type T] [--all]

Defaults: kb-home = --kb-home, else KB_HOME env, else ~/.knowledgebase.
build is also the default when no subcommand is given.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
TAG_LIST_RE = re.compile(r'"([^"]*)"')

# A note's containing subdir names the type when frontmatter omits it
# (plural directory -> singular note type).
TYPE_BY_DIR = {
    "decisions": "decision",
    "notes": "note",
    "research": "research",
    "sources": "source",
}

# Recency blend: bm25(kb) is negative, more negative = better match, so
# relevance = -bm25 flips it to higher-is-better. day_ordinal / 1e6 turns
# today's toordinal() (~739000) into a small ~0.74 bonus: enough to break
# a near-tie between two notes matching a query about equally well, in
# favor of the newer one, without letting mere recency outrank a genuinely
# stronger match elsewhere.
# ponytail: a flat constant divisor, not a normalized-per-corpus scale;
# revisit if the corpus grows enough for bm25 spreads to dwarf ~0.7.
RECENCY_DIVISOR = 1_000_000.0


@dataclass
class NoteRow:
    """One indexed knowledgebase note, ready for FTS5 insertion."""

    path: str
    project: str
    type: str
    title: str
    source: str
    date: str
    status: str
    tags: str
    body: str


def unquote(value: str) -> str:
    """Undo yaml_quote(): strip a wrapping '"..."' and its escapes."""
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Split '---\\nkey: val\\n---\\nbody' into (fields, body).

    # ponytail: hand-rolled scalar-only YAML (no pyyaml), matching the
    # LOCKED note schema written by kb-clip.py. tags is the one list
    # field and is bracket-parsed inline; anything fancier belongs to a
    # real YAML lib, which this project intentionally avoids.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_fields, body = match.groups()
    fields: dict[str, str | list[str]] = {}
    for line in raw_fields.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        fields[key] = TAG_LIST_RE.findall(value) if value.startswith("[") else unquote(value)
    return fields, body.strip()


def derive_project(path: Path, kb_home: Path) -> str:
    """Project name is the first path component under KB_HOME."""
    return path.relative_to(kb_home).parts[0]


def derive_type(fields: dict[str, str | list[str]], path: Path) -> str:
    """Frontmatter `type` wins; else map the containing subdir's name."""
    raw_type = fields.get("type")
    if isinstance(raw_type, str) and raw_type:
        return raw_type
    return TYPE_BY_DIR.get(path.parent.name, path.parent.name)


def load_note(path: Path, kb_home: Path) -> NoteRow:
    """Read one vault note off disk into the row shape the index stores."""
    fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    tags = fields.get("tags", [])
    return NoteRow(
        path=str(path),
        project=derive_project(path, kb_home),
        type=derive_type(fields, path),
        title=fields.get("title") or path.stem,
        source=fields.get("source", ""),
        date=fields.get("published") or fields.get("fetched", ""),
        status=fields.get("status", "active"),
        tags=" ".join(tags) if isinstance(tags, list) else "",
        body=body,
    )


def find_markdown_files(kb_home: Path) -> list[Path]:
    """All notes across every project dir, skipping the vault's own dirs."""
    files: list[Path] = []
    for project_dir in sorted(kb_home.iterdir()):
        if not project_dir.is_dir() or project_dir.name in {"index", ".obsidian"}:
            continue
        files.extend(project_dir.rglob("*.md"))
    return files


def build_index(kb_home: Path, db_path: Path) -> int:
    """Rebuild kb.db from scratch (drop + recreate is trivially idempotent)."""
    notes = [load_note(path, kb_home) for path in find_markdown_files(kb_home)]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    with con:
        con.execute("DROP TABLE IF EXISTS kb")
        con.execute(
            "CREATE VIRTUAL TABLE kb USING fts5("
            "path, project, type, title, source, date, status, tags, body)"
        )
        con.executemany(
            "INSERT INTO kb (path, project, type, title, source, date, "
            "status, tags, body) VALUES (:path, :project, :type, :title, "
            ":source, :date, :status, :tags, :body)",
            [vars(note) for note in notes],
        )
    con.close()
    print(json.dumps({"indexed": len(notes), "db": str(db_path)}))
    return len(notes)


def day_ordinal(date_str: str) -> int:
    """ISO date -> ordinal day number, 0 for missing/unparseable dates."""
    try:
        return date.fromisoformat(date_str).toordinal()
    except ValueError:
        return 0


def fts5_match_expr(query: str) -> str:
    """Turn free-text user input into a safe, AND-ed FTS5 MATCH expression.

    FTS5's query syntax gives meaning to punctuation (":", "-", quotes,
    "*"), so a raw phrase like "mesh-deformed" is parsed as a column
    filter and errors out. Quoting each word token neutralizes that.
    """
    tokens = re.findall(r"\w+", query)
    return " ".join(f'"{t}"' for t in tokens)


def build_query(
    query: str, project: str | None, note_type: str | None
) -> tuple[str, list[str]]:
    """Build the parameterized SQL for a search, project/type as optional
    exact-match filters alongside the FTS5 MATCH."""
    sql = (
        "SELECT path, project, type, title, source, date, status, tags, "
        "snippet(kb, 8, '[', ']', '...', 12) AS snippet, "
        "bm25(kb) AS bm25_rank FROM kb WHERE kb MATCH ?"
    )
    params: list[str] = [fts5_match_expr(query)]
    if project:
        sql += " AND project = ?"
        params.append(project)
    if note_type:
        sql += " AND type = ?"
        params.append(note_type)
    return sql, params


def score_rows(rows: list[sqlite3.Row], include_superseded: bool) -> list[dict]:
    """Blend each row's bm25 relevance with a recency bonus, drop
    superseded notes unless asked for, and rank highest-score first."""
    results = []
    for row in rows:
        if not include_superseded and row["status"] == "superseded":
            continue
        relevance = -row["bm25_rank"]
        recency_bonus = day_ordinal(row["date"]) / RECENCY_DIVISOR
        results.append(
            {
                "path": row["path"],
                "project": row["project"],
                "type": row["type"],
                "title": row["title"],
                "date": row["date"],
                "status": row["status"],
                "snippet": row["snippet"],
                "score": relevance + recency_bonus,
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def query_index(
    db_path: Path,
    query: str,
    project: str | None,
    note_type: str | None,
    include_superseded: bool,
) -> list[dict]:
    """Search kb.db, ranked by bm25 relevance blended with recency."""
    sql, params = build_query(query, project, note_type)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, params).fetchall()
    con.close()
    return score_rows(rows, include_superseded)


def resolve_kb_home(cli_value: str | None) -> Path:
    """--kb-home > KB_HOME env > ~/.knowledgebase."""
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("KB_HOME")
    return Path(env) if env else Path.home() / ".knowledgebase"


def build_parser() -> argparse.ArgumentParser:
    """Construct the build/query CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kb-home", default=None,
        help="override the vault root (else KB_HOME env, else ~/.knowledgebase)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("build", help="rebuild index/kb.db from every project")

    query_cmd = sub.add_parser("query", help="full-text search the index")
    query_cmd.add_argument("q")
    query_cmd.add_argument("--project", default=None)
    query_cmd.add_argument("--type", default=None)
    query_cmd.add_argument(
        "--all", action="store_true", help="include superseded notes",
    )

    return parser


def main(argv: list[str]) -> int:
    """CLI entry point: dispatch to build (default) or query."""
    args = build_parser().parse_args(argv)
    kb_home = resolve_kb_home(args.kb_home)
    db_path = kb_home / "index" / "kb.db"

    if args.command == "query":
        results = query_index(db_path, args.q, args.project, args.type, args.all)
        print(json.dumps(results, indent=2))
    else:
        build_index(kb_home, db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
