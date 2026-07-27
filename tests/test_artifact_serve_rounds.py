from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ENTRY = (
    REPO_ROOT
    / ".claude"
    / "skills"
    / "artifact-serve"
    / "scripts"
    / "artifact-serve.py"
)


def load_artifact_module() -> ModuleType:
    """Load artifact-serve.py from disk for direct render smoke tests."""
    spec = importlib.util.spec_from_file_location("artifact_serve_test_entry", ARTIFACT_ENTRY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {ARTIFACT_ENTRY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def artifact_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType, Path]:
    """Point artifact-serve globals at temp storage for one test."""
    mod = load_artifact_module()
    impl = mod
    stage_root = tmp_path / "stage"
    feedback_root = tmp_path / "feedback"
    monkeypatch.setattr(impl, "ROOT", stage_root)
    monkeypatch.setattr(impl, "PID_FILE", stage_root / ".serve.pid")
    monkeypatch.setattr(impl, "PORT_FILE", stage_root / ".serve.port")
    monkeypatch.setattr(impl, "LOG_FILE", stage_root / ".serve.log")
    monkeypatch.setattr(impl, "INDEX_FILE", stage_root / "index.html")
    monkeypatch.setattr(impl, "FEEDBACK_ROOT", feedback_root)
    monkeypatch.setattr(impl, "FEEDBACK_DB", feedback_root / "feedback.db")
    monkeypatch.setattr(impl, "UPLOAD_ROOT", feedback_root / "uploads")
    return mod, impl, tmp_path


def make_source_dir(base: Path) -> Path:
    """Create one sample artifact tree with image, code, and page files."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "index.html").write_text("<html><body>demo</body></html>", encoding="utf-8")
    (base / "example.py").write_text("print('demo')\n", encoding="utf-8")
    (base / "image.png").write_bytes(b"not-a-real-png")
    return base


def push_args(src: Path, *, artifact_id: str) -> argparse.Namespace:
    """Build the argparse namespace cmd_push expects."""
    return argparse.Namespace(
        src=str(src),
        project="proj",
        as_name="demo",
        artifact_id=artifact_id,
    )


def test_repush_creates_rounds_and_render_smoke(
    artifact_env: tuple[ModuleType, ModuleType, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated push creates ordered rounds and new threads bind current round."""
    mod, impl, tmp_path = artifact_env
    src = make_source_dir(tmp_path / "artifact-src")
    times = iter([100, 200, 210])
    monkeypatch.setattr(impl.time, "time", lambda: next(times))

    assert impl.cmd_push(push_args(src, artifact_id="proj/demo")) == impl.EXIT_OK
    assert impl.cmd_push(push_args(src, artifact_id="proj/demo")) == impl.EXIT_OK

    rounds = impl.round_history("proj/demo")
    assert [row["round_number"] for row in rounds] == [1, 2]

    anchor = impl.Anchor(kind=impl.ANCHOR_PAGE, data=None)
    thread_id, _reply_id = impl.create_thread(
        "proj/demo", "", anchor, "latest round note", None, []
    )
    created_thread = next(
        thread for thread in impl.list_threads("proj/demo", "") if thread.id == thread_id
    )
    assert created_thread.round_number == 2

    feedback = impl.feedback_dump("proj/demo")
    assert feedback["current_round"]["round_number"] == 2
    assert [row["round_number"] for row in feedback["rounds"]] == [1, 2]

    gallery_html = mod.render_gallery_page("proj/demo", "").decode("utf-8")
    code_html = mod.render_code_page("proj/demo", "example.py").decode("utf-8")
    viewer_html = mod.render_viewer_page("proj/demo", "image.png").decode("utf-8")
    for html in (gallery_html, code_html, viewer_html):
        assert "Round history" in html
        assert "Round 2" in html


def test_migration_infers_rounds_from_legacy_thread_timestamps(
    artifact_env: tuple[ModuleType, ModuleType, Path],
) -> None:
    """Legacy threads split into inferred rounds when timestamps straddle a push."""
    _mod, impl, _tmp_path = artifact_env
    impl.ensure_feedback_root()
    conn = sqlite3.connect(str(impl.FEEDBACK_DB))
    try:
        conn.executescript(
            """
            CREATE TABLE artifact_index (
                project TEXT NOT NULL,
                subdir TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                src_path TEXT NOT NULL,
                last_pushed INTEGER NOT NULL,
                PRIMARY KEY (project, subdir)
            );
            CREATE TABLE setting (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE thread (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_id TEXT NOT NULL,
                sub_path TEXT NOT NULL DEFAULT '',
                anchor_kind TEXT NOT NULL DEFAULT 'page',
                anchor_data TEXT,
                resolved INTEGER NOT NULL DEFAULT 0,
                author TEXT,
                created_at INTEGER NOT NULL,
                bd_ticket TEXT
            );
            CREATE TABLE reply (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                author TEXT,
                created_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO setting (key, value) VALUES ('schema_version', '2')"
        )
        conn.execute(
            "INSERT INTO artifact_index (project, subdir, artifact_id, src_path, last_pushed) "
            "VALUES (?, ?, ?, ?, ?)",
            ("proj", "demo", "proj/demo", "/legacy/src", 200),
        )
        selector = '{"selector":{"type":"FragmentSelector","value":"xywh=pixel:1,1,10,10"}}'
        old_thread = conn.execute(
            "INSERT INTO thread "
            "(artifact_id, sub_path, anchor_kind, anchor_data, resolved, author, created_at, bd_ticket) "
            "VALUES (?, ?, 'image_region', ?, 0, ?, ?, NULL)",
            ("proj/demo", "image.png", selector, "artist", 150),
        ).lastrowid
        new_thread = conn.execute(
            "INSERT INTO thread "
            "(artifact_id, sub_path, anchor_kind, anchor_data, resolved, author, created_at, bd_ticket) "
            "VALUES (?, ?, 'image_region', ?, 0, ?, ?, NULL)",
            ("proj/demo", "image.png", selector, "artist", 250),
        ).lastrowid
        conn.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) VALUES (?, ?, ?, ?)",
            (old_thread, "before push", "artist", 150),
        )
        conn.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) VALUES (?, ?, ?, ?)",
            (new_thread, "after push", "artist", 250),
        )
        conn.commit()
    finally:
        conn.close()

    migrated = impl.db_connect()
    migrated.close()

    rounds = impl.round_history("proj/demo")
    assert [row["round_number"] for row in rounds] == [1, 2]
    assert all(bool(row["inferred"]) for row in rounds)

    threads = impl.list_threads("proj/demo", "image.png")
    assert [thread.round_number for thread in threads] == [1, 2]
    assert all(thread.round_inferred for thread in threads)

    feedback = impl.feedback_dump("proj/demo")
    assert [thread["round_number"] for thread in feedback["threads"]] == [1, 2]
