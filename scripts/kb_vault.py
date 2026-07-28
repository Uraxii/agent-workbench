"""Vault layout, input validation and note writing.

The vault is Obsidian-compatible markdown and this service is the only
thing that opens it:

    <kb_home>/<project>/{decisions,notes,research,sources}/*.md   source
    <kb_home>/index/kb.db                                         derived

Every value that reaches the filesystem passes through the validators in
this module first. The service binds loopback with no authentication, so
these are the trust boundary: a project name is a strict pattern, a note
path must resolve inside the vault, and frontmatter scalars may not carry
the newlines that would let a title forge extra frontmatter fields.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from kb_config import load_sibling

__all__ = [
    "NOTE_DIRS",
    "VAULT_OWN_DIRS",
    "assert_inside_vault",
    "TYPE_TO_DIR",
    "note_dir_for_type",
    "project_dir",
    "project_init",
    "render_note",
    "resolve_vault_path",
    "validate_project",
    "validate_scalar",
    "validate_type",
    "vault_init",
    "vault_status",
    "write_note",
]

NOTE_DIRS = ("decisions", "notes", "research", "sources")
TYPE_TO_DIR = {
    "decision": "decisions",
    "note": "notes",
    "research": "research",
    "source": "sources",
}
DEFAULT_NOTE_TYPE = "note"

# Dirs directly under kb_home that are the vault's own, never a project.
VAULT_OWN_DIRS = frozenset({"index", ".obsidian"})

# A project name becomes a directory name directly under the vault root,
# so it is an allowlist, not a denylist: leading alphanumeric, then
# alphanumerics and . _ - only. Rejects "..", absolute paths, separators,
# NUL, unicode lookalikes and dotfiles in one pattern.
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Frontmatter is line-oriented, so a scalar carrying a newline could forge
# extra fields (or terminate the block early) inside a rendered note.
FORBIDDEN_SCALAR_CHARS = ("\n", "\r", "\x00")
MAX_SCALAR_CHARS = 200


def validate_project(value: object) -> str:
    """Return ``value`` as a safe project directory name, or raise.

    Raises:
        ValueError: not a string, empty, failing PROJECT_RE, containing
            "..", or naming one of the vault's own dirs.
    """
    if not isinstance(value, str) or not PROJECT_RE.fullmatch(value):
        raise ValueError(
            f"invalid project name {value!r}: expected "
            f"{PROJECT_RE.pattern} (1-64 chars)"
        )
    if ".." in value or value in VAULT_OWN_DIRS:
        raise ValueError(f"reserved project name {value!r}")
    return value


def validate_scalar(value: object, field: str, *, required: bool = False) -> str:
    """Return ``value`` as a frontmatter-safe single-line string, or raise.

    Raises:
        ValueError: not a string, longer than MAX_SCALAR_CHARS, carrying a
            newline / carriage return / NUL, or empty when required.
    """
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if required and not value.strip():
        raise ValueError(f"{field} is required")
    if len(value) > MAX_SCALAR_CHARS:
        raise ValueError(f"{field} exceeds {MAX_SCALAR_CHARS} characters")
    if any(char in value for char in FORBIDDEN_SCALAR_CHARS):
        raise ValueError(f"{field} may not contain newlines or NUL")
    return value


def validate_type(value: object) -> str:
    """Return a known note type, defaulting when absent; else raise."""
    note_type = str(value or DEFAULT_NOTE_TYPE)
    if note_type not in TYPE_TO_DIR:
        raise ValueError(
            f"unknown type {note_type!r}, expected one of {sorted(TYPE_TO_DIR)}"
        )
    return note_type


def resolve_vault_path(kb_home: Path, value: object) -> Path:
    """Resolve a caller-supplied note path inside the vault, or raise.

    Accepts a vault-relative path or an absolute path; either way the
    resolved result must stay under ``kb_home`` and end in ``.md``. This
    is what stops ``../../etc/passwd``, a symlink out of the vault, and
    ``/etc/shadow`` alike.

    Raises:
        ValueError: the path escapes the vault or is not a markdown file.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("note path must be a non-empty string")
    root = kb_home.resolve()
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"note path {value!r} resolves outside the vault")
    if candidate.suffix != ".md":
        raise ValueError(f"note path {value!r} is not a .md file")
    return candidate


def assert_inside_vault(kb_home: Path, path: Path) -> Path:
    """Return ``path`` if it resolves inside the vault, else raise.

    A valid project name is not enough on its own: if ``<kb_home>/proj``
    is a SYMLINK to somewhere else, every write below it lands outside
    the vault even though the name passed ``validate_project``. Resolving
    before the write is what closes that.

    Raises:
        ValueError: the resolved path is not the vault root or under it.
    """
    root = kb_home.resolve()
    resolved = path.resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"{path} resolves outside the vault")
    return path


def project_dir(kb_home: Path, project: str) -> Path:
    """``<kb_home>/<project>``, validated by name AND by resolved path."""
    return assert_inside_vault(kb_home, kb_home / validate_project(project))


def note_dir_for_type(kb_home: Path, project: str, note_type: str) -> Path:
    """``<kb_home>/<project>/<type dir>``, created if missing."""
    notes_dir = project_dir(kb_home, project) / TYPE_TO_DIR[validate_type(note_type)]
    assert_inside_vault(kb_home, notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    return assert_inside_vault(kb_home, notes_dir)


def vault_init(kb_home: Path) -> dict[str, object]:
    """Create the vault's own dirs (idempotent)."""
    for name in sorted(VAULT_OWN_DIRS):
        (kb_home / name).mkdir(parents=True, exist_ok=True)
    return {"kb_home": str(kb_home), "initialized": True}


def project_init(kb_home: Path, project: object) -> dict[str, object]:
    """Create a project's four note dirs under the vault (idempotent)."""
    name = validate_project(project)
    root = project_dir(kb_home, name)
    vault_init(kb_home)
    for note_dir in NOTE_DIRS:
        assert_inside_vault(kb_home, root / note_dir)
        (root / note_dir).mkdir(parents=True, exist_ok=True)
    return {"project": name, "path": str(root)}


def vault_status(kb_home: Path) -> dict[str, object]:
    """Report the vault root, whether it is initialized, and its projects."""
    initialized = (kb_home / ".obsidian").is_dir()
    projects: list[str] = []
    if initialized:
        projects = sorted(
            entry.name
            for entry in kb_home.iterdir()
            if entry.is_dir() and entry.name not in VAULT_OWN_DIRS
        )
    return {
        "kb_home": str(kb_home),
        "initialized": initialized,
        "projects": projects,
    }


def render_note(
    note_type: str, title: str, source: str, project: str, body: str,
) -> str:
    """Serialize one put note: LOCKED frontmatter + body + Refs footer.

    Same frontmatter shape as kb-clip.py's captured source notes (reusing
    its field list and quoting helpers), generic to any note type.
    """
    kb_clip = load_sibling("kb-clip")
    frontmatter = {
        "type": note_type, "title": title, "source": source, "author": "",
        "site": "", "published": "", "fetched": date.today().isoformat(),
        "description": "", "tags": kb_clip.yaml_list([]), "project": project,
        "status": "active", "question": "", "summary": "",
    }
    lines = ["---"]
    for key in kb_clip.FRONTMATTER_FIELDS:
        value = frontmatter[key]
        rendered = value if key == "tags" else kb_clip.yaml_quote(str(value))
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", body, "", "## Refs", ""])
    if source:
        lines.append(f"- {source}")
    return "\n".join(lines) + "\n"


def write_note(
    kb_home: Path,
    project: str,
    note_type: str,
    title: str,
    source: str,
    content: str,
) -> Path:
    """Validate, render and write one note; returns the created path."""
    project = validate_project(project)
    note_type = validate_type(note_type)
    if note_type == "decision":
        raise ValueError(
            "type 'decision' is not supported; use 'kb decision record' instead"
        )
    title = validate_scalar(title, "title") or "untitled"
    source = validate_scalar(source, "source")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content is required")

    kb_clip = load_sibling("kb-clip")
    notes_dir = note_dir_for_type(kb_home, project, note_type)
    note_path = kb_clip.build_note_path(notes_dir, kb_clip.slugify(title))
    assert_inside_vault(kb_home, note_path)
    note_path.write_text(
        render_note(note_type, title, source, project, content),
        encoding="utf-8",
    )
    return note_path
