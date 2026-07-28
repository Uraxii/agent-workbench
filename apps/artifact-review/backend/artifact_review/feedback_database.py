"""Schema creation for the feedback database."""

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
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    mime        TEXT,
    size        INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_upload_reply ON upload(reply_id);
"""


def enable_sqlite_foreign_keys(sender: object, connection: object, **kwargs: object) -> None:
    """Enable SQLite foreign keys on every Django connection."""
    del sender, kwargs
    if getattr(connection, "vendor", None) == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_keys = ON")


def ensure_feedback_schema(using: str = "default") -> None:
    """Create the v2 feedback schema from scratch if needed."""
    settings.ARTIFACT_SVC_FEEDBACK_ROOT.mkdir(parents=True, exist_ok=True)
    (settings.ARTIFACT_SVC_FEEDBACK_ROOT / "uploads").mkdir(parents=True, exist_ok=True)

    django_connection = connections[using]
    django_connection.ensure_connection()
    native_connection = django_connection.connection
    if not isinstance(native_connection, sqlite3.Connection):
        raise TypeError("feedback database must use sqlite3")

    native_connection.executescript(SCHEMA_DDL)
    native_connection.execute(
        "INSERT INTO setting (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    native_connection.commit()


connection_created.connect(enable_sqlite_foreign_keys, dispatch_uid="artifact_review_sqlite_foreign_keys")

__all__ = [
    "SCHEMA_DDL",
    "SCHEMA_VERSION",
    "enable_sqlite_foreign_keys",
    "ensure_feedback_schema",
]
