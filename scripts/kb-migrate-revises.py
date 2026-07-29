#!/usr/bin/env python3
"""One-shot vault migration: rename the frontmatter ``supersedes`` key to
``revises`` and the ``status: superseded`` value to ``status: revised``.

Pairs with commit 47f542e ("Rename decision-chain vocabulary: supersede
-> revise"), which renamed the code side. This script catches up any
vault notes written before that commit. Run once, then discard: repeat
runs against an already-migrated vault are harmless no-ops since neither
old marker will be found.

Only lines inside the YAML frontmatter block (between the first ``---``
line and the next ``---`` line) are touched. Body text, including prose
that happens to say "supersedes" or "SUPERSEDES", is left byte-identical.

Usage:
    kb-migrate-revises.py [vault_root] [--dry-run]

``vault_root`` defaults to ``~/.knowledgebase``. ``--dry-run`` reports
counts and changes nothing.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

FRONTMATTER_MARKER = "---"
OLD_KEY = "supersedes:"
NEW_KEY = "revises:"
OLD_STATUS = "status: superseded"
NEW_STATUS = "status: revised"


def migrate_file(path: Path, dry_run: bool) -> bool:
    """Rewrite ``path``'s frontmatter in place. Returns True if changed."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != FRONTMATTER_MARKER:
        return False
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == FRONTMATTER_MARKER:
            end = i
            break
    if end is None:
        return False

    changed = False
    for i in range(1, end):
        line = lines[i]
        newline = "\n" if line.endswith("\n") else ""
        body = line[: len(line) - len(newline)] if newline else line
        if body.startswith(OLD_KEY):
            lines[i] = NEW_KEY + body[len(OLD_KEY):] + newline
            changed = True
        elif body == OLD_STATUS:
            lines[i] = NEW_STATUS + newline
            changed = True

    if changed and not dry_run:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def main() -> int:
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in flags
    root = Path(positional[0]) if positional else Path.home() / ".knowledgebase"

    per_project: Counter[str] = Counter()
    for md_path in sorted(root.rglob("*.md")):
        if migrate_file(md_path, dry_run):
            rel = md_path.relative_to(root)
            project = rel.parts[0] if len(rel.parts) > 1 else "(root)"
            per_project[project] += 1

    label = "would migrate" if dry_run else "migrated"
    for project, count in sorted(per_project.items()):
        print(f"{project}: {count} {label}")
    print(f"total: {sum(per_project.values())} {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
