"""Schema creation and v1-to-v2 migration for the feedback database."""

from __future__ import annotations

import sqlite3

from django.conf import settings
from django.db import connections
from django.db.backends.signals import connection_created

SCHEMA_VERSION = 2
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS artifact_index (
    project     TEXT NOT NULL,
    subdir      TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    src_path    TEXT NOT NULL,
    last_pushed INTEGER NOT NULL,
    PRIMARY KEY (project, subdir)
);
CREATE INDEX IF NOT EXISTS idx_index_artifact
    ON artifact_index(artifact_id);

CREATE TABLE IF NOT EXISTS comment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    sub_path    TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL,
    author      TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comment_artifact_path
    ON comment(artifact_id, sub_path);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL,
    sub_path    TEXT NOT NULL DEFAULT '',
    anchor_kind TEXT NOT NULL DEFAULT 'page',
    anchor_data TEXT,
    resolved    INTEGER NOT NULL DEFAULT 0,
    author      TEXT,
    created_at  INTEGER NOT NULL,
    bd_ticket   TEXT,
    CHECK (anchor_kind IN ('page', 'image_region', 'code_line')),
    CHECK (resolved IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_thread_artifact_path
    ON thread(artifact_id, sub_path);

CREATE TABLE IF NOT EXISTS reply (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  INTEGER NOT NULL REFERENCES thread(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    author     TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reply_thread ON reply(thread_id);

CREATE TABLE IF NOT EXISTS upload (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reply_id    INTEGER REFERENCES reply(id) ON DELETE CASCADE,
    comment_id  INTEGER,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT,
    size        INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id);
CREATE INDEX IF NOT EXISTS idx_upload_comment ON upload(comment_id);
"""


def enable_sqlite_foreign_keys(sender: object, connection: object, **kwargs: object) -> None:
    """Enable SQLite foreign keys on every Django connection."""
    del sender, kwargs
    if getattr(connection, "vendor", None) == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = ON")


def ensure_feedback_schema(using: str = "default") -> None:
    """Create the v2 feedback schema and run the legacy migration if needed."""
    settings.REVIEW_SERVE_FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True)
    (settings.REVIEW_SERVE_FEEDBACK_ROOT / "uploads").mkdir(parents=True, exist_ok=True)

    django_connection = connections[using]
    django_connection.ensure_connection()
    native_connection = django_connection.connection
    if not isinstance(native_connection, sqlite3.Connection):
        raise TypeError("feedback database must use sqlite3")

    ddl = SCHEMA_DDL
    upload_columns = _table_columns(native_connection, "upload")
    if upload_columns and "reply_id" not in upload_columns:
        ddl = ddl.replace("CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id);", "")
    native_connection.executescript(ddl)
    native_connection.commit()
    migrate_feedback_schema(native_connection)


def migrate_feedback_schema(connection: sqlite3.Connection) -> None:
    """Run the idempotent v1-to-v2 feedback schema migration."""
    row = connection.execute("SELECT value FROM setting WHERE key='schema_version'").fetchone()
    current_schema_version = int(row[0]) if row else 1
    if current_schema_version >= SCHEMA_VERSION:
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        _rebuild_upload_table_if_legacy(connection)
        _backfill_legacy_comments(connection)
        connection.execute(
            "INSERT INTO setting (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
    except sqlite3.Error:
        connection.rollback()
        raise
    else:
        connection.commit()


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _rebuild_upload_table_if_legacy(connection: sqlite3.Connection) -> None:
    upload_columns = _table_columns(connection, "upload")
    if "reply_id" in upload_columns:
        return
    connection.execute(
        "CREATE TABLE upload_new ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "reply_id INTEGER REFERENCES reply(id) ON DELETE CASCADE, "
        "comment_id INTEGER, filename TEXT NOT NULL, "
        "stored_path TEXT NOT NULL, mime TEXT, size INTEGER NOT NULL, "
        "created_at INTEGER NOT NULL)"
    )
    connection.execute(
        "INSERT INTO upload_new "
        "(id, comment_id, filename, stored_path, mime, size, created_at) "
        "SELECT id, comment_id, filename, stored_path, mime, size, created_at "
        "FROM upload"
    )
    connection.execute("DROP TABLE upload")
    connection.execute("ALTER TABLE upload_new RENAME TO upload")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_upload_comment ON upload(comment_id)")


def _backfill_legacy_comments(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id, artifact_id, sub_path, body, author, created_at FROM comment ORDER BY id ASC"
    ).fetchall()
    for comment_id, artifact_id, sub_path, body, author, created_at in rows:
        thread_id = connection.execute(
            "INSERT INTO thread "
            "(artifact_id, sub_path, anchor_kind, anchor_data, resolved, author, created_at) "
            "VALUES (?, ?, 'page', NULL, 0, ?, ?)",
            (artifact_id, sub_path, author, created_at),
        ).lastrowid
        reply_id = connection.execute(
            "INSERT INTO reply (thread_id, body, author, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, body, author, created_at),
        ).lastrowid
        connection.execute("UPDATE upload SET reply_id=? WHERE comment_id=?", (reply_id, comment_id))


connection_created.connect(enable_sqlite_foreign_keys, dispatch_uid="artifact_review_sqlite_foreign_keys")

__all__ = [
    "SCHEMA_DDL",
    "SCHEMA_VERSION",
    "enable_sqlite_foreign_keys",
    "ensure_feedback_schema",
    "migrate_feedback_schema",
]
