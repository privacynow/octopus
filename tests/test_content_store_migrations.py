"""Lifecycle schema migration coverage for the content store backends."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.content_store_postgres import PostgresContentStore
from app.content_store_sqlite import SQLiteContentStore
from app.db.postgres import get_connection

_SQLITE_V1_SCHEMA = """\
CREATE TABLE skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable INTEGER NOT NULL DEFAULT 0,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json TEXT NOT NULL DEFAULT '[]',
    provider_config_json TEXT NOT NULL DEFAULT '{}',
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE skill_files (
    revision_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable INTEGER NOT NULL DEFAULT 0,
    digest TEXT NOT NULL,
    PRIMARY KEY(revision_id, relative_path)
);
CREATE TABLE provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable INTEGER NOT NULL DEFAULT 0,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

_POSTGRES_V1_SCHEMA = """\
CREATE SCHEMA IF NOT EXISTS bot_content;
CREATE TABLE bot_content.skill_namespaces (
    skill_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE bot_content.skill_tracks (
    track_id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES bot_content.skill_namespaces(skill_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'shared',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE bot_content.skill_revisions (
    revision_id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES bot_content.skill_tracks(track_id) ON DELETE CASCADE,
    version_label TEXT NOT NULL DEFAULT '',
    digest TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    changelog TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE bot_content.skill_files (
    revision_id TEXT NOT NULL REFERENCES bot_content.skill_revisions(revision_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'text/plain',
    executable BOOLEAN NOT NULL DEFAULT FALSE,
    digest TEXT NOT NULL,
    PRIMARY KEY(revision_id, relative_path)
);
CREATE TABLE bot_content.provider_guidance_tracks (
    guidance_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'system',
    scope_key TEXT NOT NULL DEFAULT '',
    is_mutable BOOLEAN NOT NULL DEFAULT FALSE,
    active_revision_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE bot_content.provider_guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    guidance_id TEXT NOT NULL REFERENCES bot_content.provider_guidance_tracks(guidance_id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'markdown',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
"""


def test_sqlite_content_store_migrates_v1_schema(tmp_path: Path):
    db_path = tmp_path / "content.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SQLITE_V1_SCHEMA)
    conn.execute(
        "INSERT INTO skill_namespaces VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("skill:debugging", "debugging", "Debugging", "desc", 0, "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO skill_tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("debugging|builtin|catalog/debugging|", "skill:debugging", "builtin", "catalog/debugging", "", "shared", 0, "rev-debug", "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO skill_revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rev-debug", "debugging|builtin|catalog/debugging|", "builtin", "digest-debug", "builtin body", "[]", "{}", "", "seed", "2026-03-17T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO provider_guidance_tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("claude|system|", "claude", "system", "", 0, "guidance-rev", "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO provider_guidance_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("guidance-rev", "claude|system|", "digest-guidance", "guidance body", "markdown", "seed", "2026-03-17T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    store = SQLiteContentStore(db_path)

    skill = store.resolve_runtime_skill("debugging")
    guidance = store.resolve_provider_guidance("claude")

    assert skill is not None
    assert skill.published_revision_id == "rev-debug"
    assert skill.revision.status == "published"
    assert guidance is not None
    assert guidance.published_revision_id == "guidance-rev"
    assert guidance.revision.status == "published"

    check = sqlite3.connect(str(db_path))
    version = check.execute(
        "SELECT value FROM meta WHERE key = 'content_schema_version'"
    ).fetchone()[0]
    skill_cols = {row[1] for row in check.execute("PRAGMA table_info(skill_tracks)").fetchall()}
    guidance_cols = {row[1] for row in check.execute("PRAGMA table_info(provider_guidance_tracks)").fetchall()}
    approval_tables = {
        row[0] for row in check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%approval_records'"
        ).fetchall()
    }
    check.close()

    assert version == "2"
    assert "published_revision_id" in skill_cols
    assert "published_revision_id" in guidance_cols
    assert "skill_approval_records" in approval_tables
    assert "provider_guidance_approval_records" in approval_tables


@pytest.mark.usefixtures("postgres_content_truncated")
def test_postgres_content_store_migrates_v1_schema(postgres_content_truncated):
    with get_connection(postgres_content_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(_POSTGRES_V1_SCHEMA)
            cur.execute(
                """
                INSERT INTO bot_content.skill_namespaces
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                """,
                ("skill:debugging", "debugging", "Debugging", "desc", False, "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
            )
            cur.execute(
                """
                INSERT INTO bot_content.skill_tracks
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                """,
                ("debugging|builtin|catalog/debugging|", "skill:debugging", "builtin", "catalog/debugging", "", "shared", False, "rev-debug", "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
            )
            cur.execute(
                """
                INSERT INTO bot_content.skill_revisions
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::timestamptz)
                """,
                ("rev-debug", "debugging|builtin|catalog/debugging|", "builtin", "digest-debug", "builtin body", "[]", "{}", "", "seed", "2026-03-17T00:00:00+00:00"),
            )
            cur.execute(
                """
                INSERT INTO bot_content.provider_guidance_tracks
                VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                """,
                ("claude|system|", "claude", "system", "", False, "guidance-rev", "2026-03-17T00:00:00+00:00", "2026-03-17T00:00:00+00:00"),
            )
            cur.execute(
                """
                INSERT INTO bot_content.provider_guidance_revisions
                VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz)
                """,
                ("guidance-rev", "claude|system|", "digest-guidance", "guidance body", "markdown", "seed", "2026-03-17T00:00:00+00:00"),
            )
        conn.commit()

    store = PostgresContentStore(postgres_content_truncated)
    skill = store.resolve_runtime_skill("debugging")
    guidance = store.resolve_provider_guidance("claude")

    assert skill is not None
    assert skill.published_revision_id == "rev-debug"
    assert skill.revision.status == "published"
    assert guidance is not None
    assert guidance.published_revision_id == "guidance-rev"
    assert guidance.revision.status == "published"

    with get_connection(postgres_content_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM bot_content.schema_migrations")
            version = cur.fetchone()[0]
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'bot_content' AND table_name = 'skill_tracks'
                """
            )
            skill_cols = {row[0] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'bot_content' AND table_name = 'provider_guidance_tracks'
                """
            )
            guidance_cols = {row[0] for row in cur.fetchall()}
    assert version == 2
    assert "published_revision_id" in skill_cols
    assert "published_revision_id" in guidance_cols
