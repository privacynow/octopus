"""SQLite implementation of the central agent registry store."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from app.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillFileRecord,
    SkillRevisionRecord,
    skill_precedence,
)

from app.capability_service import (
    query_capabilities,
    requested_routed_capabilities,
)
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    PROTECTED_ROUTED_TASK_STATUSES,
    validated_ack_request,
    validated_agent_card_payload,
    validated_conversation_action,
    validated_conversation_message_text,
    validated_heartbeat_payload,
    validated_register_payload,
    validated_routed_task_request,
    validated_routed_task_result_payload,
    validated_routed_task_status_payload,
    validated_search_query,
    decode_json_field,
    delivery_kinds_for_registry_scope,
    effective_connectivity_state,
    ensure_json,
    hash_agent_token,
    registry_scope_for_agent_row,
    require_registry_scope,
    runtime_health_detail,
    runtime_health_generated_at,
    runtime_health_summary,
    utcnow_iso,
    validated_registry_scope,
)

_SCHEMA_VERSION = 8

_BASE_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    agent_token TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT '',
    registry_scope TEXT NOT NULL DEFAULT 'full',
    skills_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'standalone',
    connectivity_state TEXT NOT NULL DEFAULT 'standalone',
    current_capacity INTEGER NOT NULL DEFAULT 0,
    max_capacity INTEGER NOT NULL DEFAULT 1,
    channel_capabilities_json TEXT NOT NULL DEFAULT '[]',
    version TEXT NOT NULL DEFAULT '',
    runtime_health_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runtime_workers (
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    process_role TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    current_item_id TEXT NOT NULL DEFAULT '',
    current_conversation_key TEXT NOT NULL DEFAULT '',
    current_kind TEXT NOT NULL DEFAULT '',
    items_processed INTEGER NOT NULL DEFAULT 0,
    stale_recoveries_seen INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    mirrored_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, worker_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_workers_seen
    ON agent_runtime_workers (agent_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS deliveries (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id TEXT NOT NULL UNIQUE,
    target_agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    leased_at TEXT,
    acked_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    origin_channel TEXT NOT NULL DEFAULT '',
    external_conversation_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routed_tasks (
    routed_task_id TEXT PRIMARY KEY,
    parent_conversation_id TEXT NOT NULL,
    origin_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    summary TEXT NOT NULL DEFAULT '',
    result_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    routed_task_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    progress INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);
CREATE INDEX IF NOT EXISTS idx_events_conversation ON events(conversation_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(conversation_id, kind, seq);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(content, content=events, content_rowid=seq);

CREATE TRIGGER IF NOT EXISTS ev_ai AFTER INSERT ON events BEGIN
  INSERT INTO events_fts(rowid, content) VALUES (new.seq, new.content);
END;
CREATE TRIGGER IF NOT EXISTS ev_ad AFTER DELETE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.seq, old.content);
END;
CREATE TRIGGER IF NOT EXISTS ev_au AFTER UPDATE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.seq, old.content);
  INSERT INTO events_fts(rowid, content) VALUES (new.seq, new.content);
END;

CREATE TABLE IF NOT EXISTS runtime_skills (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'custom',
    source_uri TEXT NOT NULL DEFAULT '',
    owner_actor TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    archived INTEGER NOT NULL DEFAULT 0,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json TEXT NOT NULL DEFAULT '[]',
    provider_config_json TEXT NOT NULL DEFAULT '{}',
    files_json TEXT NOT NULL DEFAULT '[]',
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skill_revisions (
    revision_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    instruction_body TEXT NOT NULL DEFAULT '',
    requirements_json TEXT NOT NULL DEFAULT '[]',
    provider_config_json TEXT NOT NULL DEFAULT '{}',
    files_json TEXT NOT NULL DEFAULT '[]',
    version_label TEXT NOT NULL DEFAULT '',
    changelog TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skill_approvals (
    record_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS provider_guidance (
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    is_mutable INTEGER NOT NULL DEFAULT 1,
    active_revision_id TEXT NOT NULL DEFAULT '',
    published_revision_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (provider, scope_kind, scope_key)
);

CREATE TABLE IF NOT EXISTS guidance_revisions (
    revision_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'text',
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS guidance_approvals (
    record_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    scope_kind TEXT NOT NULL DEFAULT 'instance',
    scope_key TEXT NOT NULL DEFAULT '',
    revision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
"""
def _execute_sql_script(conn: sqlite3.Connection, script: str) -> None:
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                conn.execute(statement)
            buffer = ""
    statement = buffer.strip()
    if statement:
        conn.execute(statement)


def _run_migration_step(conn: sqlite3.Connection, version: int, migration) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        migration(conn)
        conn.execute(
            """
            INSERT INTO meta (key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(version),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class RegistrySQLiteStore(AbstractRegistryStore):
    """SQLite-backed registry store used by the FastAPI registry service."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_BASE_SCHEMA_SQL)
            self._run_migrations(conn)

    def _current_schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Unsupported registry SQLite schema") from exc

    def _set_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            """
            INSERT INTO meta (key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(version),),
        )

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        _execute_sql_script(
            conn,
            """
            CREATE TABLE IF NOT EXISTS skills_override (
                skill_name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                set_by TEXT NOT NULL DEFAULT 'ui',
                set_at REAL NOT NULL
            );
            """,
        )

    def _migrate_v2_timeline_fts(self, conn: sqlite3.Connection) -> None:
        _execute_sql_script(
            conn,
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS timeline_fts
            USING fts5(body, content=timeline_events, content_rowid=seq);

            CREATE TRIGGER IF NOT EXISTS tl_ai AFTER INSERT ON timeline_events BEGIN
              INSERT INTO timeline_fts(rowid, body) VALUES (new.seq, new.body);
            END;
            CREATE TRIGGER IF NOT EXISTS tl_ad AFTER DELETE ON timeline_events BEGIN
              INSERT INTO timeline_fts(timeline_fts, rowid, body) VALUES ('delete', old.seq, old.body);
            END;
            CREATE TRIGGER IF NOT EXISTS tl_au AFTER UPDATE ON timeline_events BEGIN
              INSERT INTO timeline_fts(timeline_fts, rowid, body) VALUES ('delete', old.seq, old.body);
              INSERT INTO timeline_fts(rowid, body) VALUES (new.seq, new.body);
            END;
            """,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO timeline_fts(rowid, body)
            SELECT seq, body FROM timeline_events
            WHERE body IS NOT NULL AND body != ''
            """
        )

    def _migrate_v3_runtime_health(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "runtime_health_json" not in columns:
            conn.execute(
                "ALTER TABLE agents ADD COLUMN runtime_health_json TEXT NOT NULL DEFAULT '{}'"
            )
        _execute_sql_script(
            conn,
            """
            CREATE TABLE IF NOT EXISTS agent_runtime_workers (
                agent_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                process_role TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT NOT NULL DEFAULT '',
                current_item_id TEXT NOT NULL DEFAULT '',
                current_conversation_key TEXT NOT NULL DEFAULT '',
                current_kind TEXT NOT NULL DEFAULT '',
                items_processed INTEGER NOT NULL DEFAULT 0,
                stale_recoveries_seen INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                mirrored_at TEXT NOT NULL,
                PRIMARY KEY (agent_id, worker_id)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_runtime_workers_seen
                ON agent_runtime_workers (agent_id, last_seen_at DESC);
            """,
        )

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }

    def _migrate_v4_channel_vocabulary(self, conn: sqlite3.Connection) -> None:
        agent_columns = self._table_columns(conn, "agents")
        if (
            "surface_capabilities_json" in agent_columns
            and "channel_capabilities_json" not in agent_columns
        ):
            conn.execute(
                """
                ALTER TABLE agents
                RENAME COLUMN surface_capabilities_json TO channel_capabilities_json
                """
            )

        conversation_columns = self._table_columns(conn, "conversations")
        if "origin_surface" in conversation_columns and "origin_channel" not in conversation_columns:
            conn.execute(
                """
                ALTER TABLE conversations
                RENAME COLUMN origin_surface TO origin_channel
                """
            )

        conn.execute(
            "UPDATE deliveries SET kind = 'channel_input' WHERE kind = 'surface_input'"
        )
        conn.execute(
            "UPDATE deliveries SET kind = 'channel_action' WHERE kind = 'surface_action'"
        )

    def _migrate_v5_agent_token_hashing(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT agent_id, agent_token FROM agents").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE agents SET agent_token = ? WHERE agent_id = ?",
                (hash_agent_token(str(row["agent_token"])), row["agent_id"]),
            )

    def _migrate_v6_registry_scope(self, conn: sqlite3.Connection) -> None:
        columns = self._table_columns(conn, "agents")
        if "registry_scope" not in columns:
            conn.execute(
                "ALTER TABLE agents ADD COLUMN registry_scope TEXT NOT NULL DEFAULT 'full'"
            )
        conn.execute(
            "UPDATE agents SET registry_scope = 'full' WHERE coalesce(registry_scope, '') = ''"
        )

    def _migrate_v7_events_table(self, conn: sqlite3.Connection) -> None:
        # Drop old FTS triggers
        conn.execute("DROP TRIGGER IF EXISTS tl_ai")
        conn.execute("DROP TRIGGER IF EXISTS tl_ad")
        conn.execute("DROP TRIGGER IF EXISTS tl_au")
        # Drop and recreate FTS virtual table (clean state since we truncate)
        conn.execute("DROP TABLE IF EXISTS timeline_fts")
        # Truncate timeline_events (keep table for legacy code still referencing it)
        conn.execute("DELETE FROM timeline_events")
        # Recreate FTS and triggers for legacy timeline search
        _execute_sql_script(
            conn,
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS timeline_fts
            USING fts5(body, content=timeline_events, content_rowid=seq);

            CREATE TRIGGER IF NOT EXISTS tl_ai AFTER INSERT ON timeline_events BEGIN
              INSERT INTO timeline_fts(rowid, body) VALUES (new.seq, new.body);
            END;
            CREATE TRIGGER IF NOT EXISTS tl_ad AFTER DELETE ON timeline_events BEGIN
              INSERT INTO timeline_fts(timeline_fts, rowid, body) VALUES ('delete', old.seq, old.body);
            END;
            CREATE TRIGGER IF NOT EXISTS tl_au AFTER UPDATE ON timeline_events BEGIN
              INSERT INTO timeline_fts(timeline_fts, rowid, body) VALUES ('delete', old.seq, old.body);
              INSERT INTO timeline_fts(rowid, body) VALUES (new.seq, new.body);
            END;
            """,
        )
        # Truncate conversations
        conn.execute("DELETE FROM conversations")
        # Add new columns to conversations
        conversation_columns = self._table_columns(conn, "conversations")
        if "origin_channel" not in conversation_columns:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN origin_channel TEXT NOT NULL DEFAULT ''"
            )
        if "external_conversation_ref" not in conversation_columns:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN external_conversation_ref TEXT NOT NULL DEFAULT ''"
            )
        # Create unique index on conversations
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
            ON conversations(target_agent_id, origin_channel, external_conversation_ref)
            """
        )
        # Create events table
        _execute_sql_script(
            conn,
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_events_conversation ON events(conversation_id, seq);
            CREATE INDEX IF NOT EXISTS idx_events_kind ON events(conversation_id, kind, seq);

            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(content, content=events, content_rowid=seq);

            CREATE TRIGGER IF NOT EXISTS ev_ai AFTER INSERT ON events BEGIN
              INSERT INTO events_fts(rowid, content) VALUES (new.seq, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS ev_ad AFTER DELETE ON events BEGIN
              INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.seq, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS ev_au AFTER UPDATE ON events BEGIN
              INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.seq, old.content);
              INSERT INTO events_fts(rowid, content) VALUES (new.seq, new.content);
            END;
            """,
        )

    def _migrate_v8_content_tables(self, conn: sqlite3.Connection) -> None:
        _execute_sql_script(
            conn,
            """
            CREATE TABLE IF NOT EXISTS runtime_skills (
                slug TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL DEFAULT 'custom',
                source_uri TEXT NOT NULL DEFAULT '',
                owner_actor TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'private',
                is_mutable INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,
                instruction_body TEXT NOT NULL DEFAULT '',
                requirements_json TEXT NOT NULL DEFAULT '[]',
                provider_config_json TEXT NOT NULL DEFAULT '{}',
                files_json TEXT NOT NULL DEFAULT '[]',
                active_revision_id TEXT NOT NULL DEFAULT '',
                published_revision_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS skill_revisions (
                revision_id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                instruction_body TEXT NOT NULL DEFAULT '',
                requirements_json TEXT NOT NULL DEFAULT '[]',
                provider_config_json TEXT NOT NULL DEFAULT '{}',
                files_json TEXT NOT NULL DEFAULT '[]',
                version_label TEXT NOT NULL DEFAULT '',
                changelog TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS skill_approvals (
                record_id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS provider_guidance (
                provider TEXT NOT NULL,
                scope_kind TEXT NOT NULL DEFAULT 'instance',
                scope_key TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT 'text',
                is_mutable INTEGER NOT NULL DEFAULT 1,
                active_revision_id TEXT NOT NULL DEFAULT '',
                published_revision_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (provider, scope_kind, scope_key)
            );

            CREATE TABLE IF NOT EXISTS guidance_revisions (
                revision_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                scope_kind TEXT NOT NULL DEFAULT 'instance',
                scope_key TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT 'text',
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS guidance_approvals (
                record_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                scope_kind TEXT NOT NULL DEFAULT 'instance',
                scope_key TEXT NOT NULL DEFAULT '',
                revision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            );
            """,
        )

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        current = self._current_schema_version(conn)
        if current > _SCHEMA_VERSION:
            raise RuntimeError(
                f"Registry DB schema version {current} is newer than supported version {_SCHEMA_VERSION}. Upgrade the registry."
            )
        if current < 1:
            _run_migration_step(conn, 1, self._migrate_v1)
            current = 1
        if current < 2:
            _run_migration_step(conn, 2, self._migrate_v2_timeline_fts)
            current = 2
        if current < 3:
            _run_migration_step(conn, 3, self._migrate_v3_runtime_health)
            current = 3
        if current < 4:
            _run_migration_step(conn, 4, self._migrate_v4_channel_vocabulary)
            current = 4
        if current < 5:
            _run_migration_step(conn, 5, self._migrate_v5_agent_token_hashing)
            current = 5
        if current < 6:
            _run_migration_step(conn, 6, self._migrate_v6_registry_scope)
            current = 6
        if current < 7:
            # v7 is destructive: drops timeline_events, truncates conversations.
            # Require explicit opt-in in non-interactive environments.
            if not os.environ.get("REGISTRY_ALLOW_DESTRUCTIVE_MIGRATION"):
                import sys
                if not sys.stdin.isatty():
                    raise RuntimeError(
                        "Destructive schema migration required (v7: events table replaces timeline_events). "
                        "Set REGISTRY_ALLOW_DESTRUCTIVE_MIGRATION=1 to proceed. "
                        "Back up .deploy/registry/ first."
                    )
                else:
                    log.warning(
                        "Registry schema upgrade will reset event history. "
                        "Timeline data from before this version will not be preserved."
                    )
            _run_migration_step(conn, 7, self._migrate_v7_events_table)
            current = 7
        if current < 8:
            _run_migration_step(conn, 8, self._migrate_v8_content_tables)

    def _ensure_unique_slug(self, conn: sqlite3.Connection, requested: str) -> str:
        slug = requested
        suffix = 2
        while conn.execute("SELECT 1 FROM agents WHERE slug = ?", (slug,)).fetchone():
            slug = f"{requested}-{suffix}"
            suffix += 1
        return slug

    def _row_to_agent(self, row: sqlite3.Row) -> dict[str, Any]:
        row_keys = row.keys()
        effective_state = (
            row["effective_state"]
            if "effective_state" in row_keys
            else effective_connectivity_state(row["connectivity_state"], row["last_heartbeat_at"])
        )
        return {
            "agent_id": row["agent_id"],
            "display_name": row["display_name"],
            "slug": row["slug"],
            "role": row["role"],
            "registry_scope": row["registry_scope"] if "registry_scope" in row_keys else "full",
            "capabilities": decode_json_field(row["skills_json"], []),
            "tags": decode_json_field(row["tags_json"], []),
            "description": row["description"],
            "provider": row["provider"],
            "mode": row["mode"],
            "connectivity_state": effective_state,
            "current_capacity": row["current_capacity"],
            "max_capacity": row["max_capacity"],
            "channel_capabilities": decode_json_field(row["channel_capabilities_json"], []),
            "version": row["version"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "updated_at": row["updated_at"],
            "runtime_health_summary": runtime_health_summary(row["runtime_health_json"]),
            "runtime_health_generated_at": runtime_health_generated_at(row["runtime_health_json"]),
        }

    def _replace_runtime_health_workers(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str,
        runtime_health_payload: dict[str, Any],
        mirrored_at: str,
    ) -> None:
        workers = []
        snapshot = runtime_health_payload.get("snapshot")
        if isinstance(snapshot, dict):
            raw_workers = snapshot.get("workers") or []
            if isinstance(raw_workers, list):
                workers = [worker for worker in raw_workers if isinstance(worker, dict)]
        conn.execute("DELETE FROM agent_runtime_workers WHERE agent_id = ?", (agent_id,))
        for worker in workers:
            conn.execute(
                """
                INSERT INTO agent_runtime_workers (
                    agent_id, worker_id, process_role, started_at, last_seen_at,
                    current_item_id, current_conversation_key, current_kind,
                    items_processed, stale_recoveries_seen, last_error, mirrored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    str(worker.get("worker_id", "")),
                    str(worker.get("process_role", "")),
                    str(worker.get("started_at", "")),
                    str(worker.get("last_seen_at", "")),
                    str(worker.get("current_item_id", "")),
                    str(worker.get("current_conversation_key", "")),
                    str(worker.get("current_kind", "")),
                    int(worker.get("items_processed", 0) or 0),
                    int(worker.get("stale_recoveries_seen", 0) or 0),
                    str(worker.get("last_error", "")),
                    mirrored_at,
                ),
            )

    def _runtime_worker_rows(self, conn: sqlite3.Connection, agent_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM agent_runtime_workers WHERE agent_id = ? ORDER BY worker_id ASC",
            (agent_id,),
        ).fetchall()
        return [
            {
                "worker_id": row["worker_id"],
                "process_role": row["process_role"],
                "started_at": row["started_at"],
                "last_seen_at": row["last_seen_at"],
                "current_item_id": row["current_item_id"],
                "current_conversation_key": row["current_conversation_key"],
                "current_kind": row["current_kind"],
                "items_processed": row["items_processed"],
                "stale_recoveries_seen": row["stale_recoveries_seen"],
                "last_error": row["last_error"],
                "mirrored_at": row["mirrored_at"],
            }
            for row in rows
        ]

    def _token_row(self, conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM agents WHERE agent_token = ?",
            (hash_agent_token(token),),
        ).fetchone()

    def resolve_agent_for_token(self, agent_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                return None
            return dict(row)

    def _offline_before(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        agent_token_hash = hash_agent_token(agent_token)
        card = validated_agent_card_payload(requested_card, require_registry_scope=True)
        with self._connect() as conn:
            slug = self._ensure_unique_slug(conn, card.get("slug") or "agent")
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, agent_token, display_name, slug, role, registry_scope,
                    skills_json, tags_json, description, provider, mode,
                    connectivity_state, current_capacity, max_capacity,
                    channel_capabilities_json, version, created_at, updated_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    agent_token_hash,
                    card.get("display_name") or slug,
                    slug,
                    card.get("role", ""),
                    validated_registry_scope(card.get("registry_scope")),
                    ensure_json(card.get("capabilities", [])),
                    ensure_json(card.get("tags", [])),
                    card.get("description", ""),
                    card.get("provider", ""),
                    card.get("mode", "registry"),
                    card.get("connectivity_state", "degraded"),
                    card.get("current_capacity", 0),
                    card.get("max_capacity", 1),
                    ensure_json(card.get("channel_capabilities", [])),
                    card.get("version", ""),
                    now,
                    now,
                    now,
                ),
            )
        return {
            "agent_id": agent_id,
            "slug": slug,
            "agent_token": agent_token,
            "poll_cursor": "0",
        }

    def assert_agent_scope(self, agent_token: str, required_scopes: set[str]) -> None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, required_scopes)

    def register(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        register_payload = validated_register_payload(payload)
        card = register_payload["agent_card"]
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            current_skills = decode_json_field(row["skills_json"], [])
            current_tags = decode_json_field(row["tags_json"], [])
            current_channel_capabilities = decode_json_field(row["channel_capabilities_json"], [])
            conn.execute(
                """
                UPDATE agents
                SET display_name = ?, role = ?, registry_scope = ?, skills_json = ?, tags_json = ?,
                    description = ?, provider = ?, mode = ?, connectivity_state = ?,
                    current_capacity = ?, max_capacity = ?, channel_capabilities_json = ?,
                    version = ?, updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (
                    card.get("display_name", row["display_name"]),
                    card.get("role", row["role"]),
                    card.get("registry_scope", row["registry_scope"]),
                    ensure_json(card.get("capabilities", current_skills)),
                    ensure_json(card.get("tags", current_tags)),
                    card.get("description", row["description"]),
                    card.get("provider", row["provider"]),
                    card.get("mode", row["mode"]),
                    register_payload.get("connectivity_state", row["connectivity_state"]),
                    register_payload.get("current_capacity", row["current_capacity"]),
                    register_payload.get("max_capacity", row["max_capacity"]),
                    ensure_json(card.get("channel_capabilities", current_channel_capabilities)),
                    card.get("version", row["version"]),
                    now,
                    now,
                    agent_token_hash,
                ),
            )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return self._row_to_agent(row)

    def heartbeat(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        agent_token_hash = hash_agent_token(agent_token)
        heartbeat_payload = validated_heartbeat_payload(payload)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            runtime_health_payload = heartbeat_payload.get("runtime_health")
            conn.execute(
                """
                UPDATE agents
                SET connectivity_state = ?, current_capacity = ?, max_capacity = ?,
                    updated_at = ?, last_heartbeat_at = ?,
                    runtime_health_json = ?
                WHERE agent_token = ?
                """,
                (
                    heartbeat_payload.get("connectivity_state", row["connectivity_state"]),
                    heartbeat_payload.get("current_capacity", row["current_capacity"]),
                    heartbeat_payload.get("max_capacity", row["max_capacity"]),
                    now,
                    now,
                    (
                        ensure_json(runtime_health_payload)
                        if isinstance(runtime_health_payload, dict)
                        else row["runtime_health_json"]
                    ),
                    agent_token_hash,
                ),
            )
            if isinstance(runtime_health_payload, dict):
                self._replace_runtime_health_workers(
                    conn,
                    agent_id=row["agent_id"],
                    runtime_health_payload=runtime_health_payload,
                    mirrored_at=now,
                )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return {
                "agent": self._row_to_agent(row),
                "server_time": now,
            }

    def get_capability_override(self, capability_name: str) -> bool | None:
        normalized = capability_name.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT enabled FROM skills_override WHERE lower(skill_name) = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return bool(row["enabled"])

    def set_capability_override(self, capability_name: str, enabled: bool, set_by: str = "ui") -> None:
        normalized = capability_name.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills_override (skill_name, enabled, set_by, set_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(skill_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    set_by = excluded.set_by,
                    set_at = excluded.set_at
                """,
                (normalized, 1 if enabled else 0, set_by, time.time()),
            )
            conn.commit()

    def list_capabilities(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            offline_before = self._offline_before()
            declared_rows = conn.execute(
                """
                WITH live_agents AS (
                    SELECT slug, skills_json
                    FROM agents
                    WHERE CASE
                        WHEN last_heartbeat_at != '' AND last_heartbeat_at < ? THEN 'offline'
                        ELSE connectivity_state
                    END != 'offline'
                ),
                declared AS (
                    SELECT lower(je.value) AS capability_key, je.value AS capability_name, live_agents.slug
                    FROM live_agents
                    JOIN json_each(live_agents.skills_json) AS je
                )
                SELECT capability_key, MIN(capability_name) AS capability_name, GROUP_CONCAT(DISTINCT slug) AS declared_by_agents
                FROM declared
                GROUP BY capability_key
                ORDER BY capability_key
                """
                ,
                (offline_before,),
            ).fetchall()
            override_rows = conn.execute(
                """
                SELECT skill_name, enabled
                FROM skills_override
                ORDER BY lower(skill_name)
                """
            ).fetchall()

        merged: dict[str, dict[str, Any]] = {}
        for row in declared_rows:
            capability_name = row["capability_name"]
            item = merged.setdefault(
                row["capability_key"],
                {
                    "capability_name": capability_name,
                    "declared_by_agents": sorted(
                        str(row["declared_by_agents"]).split(",")
                        if row["declared_by_agents"]
                        else []
                    ),
                    "enabled": None,
                },
            )
        for row in override_rows:
            capability_name = row["skill_name"]
            key = capability_name.lower()
            item = merged.setdefault(
                key,
                {
                    "capability_name": capability_name,
                    "declared_by_agents": [],
                    "enabled": None,
                },
            )
            item["enabled"] = bool(row["enabled"])
        return sorted(merged.values(), key=lambda item: item["capability_name"].lower())

    def _disabled_capabilities(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            "SELECT skill_name FROM skills_override WHERE enabled = 0"
        ).fetchall()
        return {str(row["skill_name"]).lower() for row in rows}

    def search_agents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        validated_query = validated_search_query(query)
        role = validated_query.get("role", "").strip().lower()
        required_state = validated_query.get("required_state", "connected")
        capabilities = query_capabilities(validated_query)
        tags = {s.lower() for s in validated_query.get("tags", []) if s}
        free_text = validated_query.get("free_text", "").strip().lower()
        exclude = sorted(set(validated_query.get("exclude_agent_ids", [])))
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            capabilities = capabilities - disabled_capabilities
            if (validated_query.get("capabilities") or validated_query.get("skills")) and not capabilities:
                return []
            sql = [
                """
                WITH agent_rows AS (
                    SELECT
                        a.*,
                        CASE
                            WHEN a.last_heartbeat_at != '' AND a.last_heartbeat_at < ? THEN 'offline'
                            ELSE a.connectivity_state
                        END AS effective_state
                    FROM agents a
                )
                SELECT *
                FROM agent_rows
                WHERE 1 = 1
                """
            ]
            params: list[Any] = [self._offline_before()]
            if exclude:
                sql.append(f" AND agent_id NOT IN ({','.join('?' for _ in exclude)})")
                params.extend(exclude)
            if required_state:
                sql.append(" AND effective_state = ?")
                params.append(required_state)
            if role:
                sql.append(" AND lower(role) LIKE ?")
                params.append(f"%{role}%")
            for capability in sorted(capabilities):
                sql.append(
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM json_each(agent_rows.skills_json) AS je
                        WHERE lower(je.value) = ?
                    )
                    """
                )
                params.append(capability)
            for tag in sorted(tags):
                sql.append(
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM json_each(agent_rows.tags_json) AS je
                        WHERE lower(je.value) = ?
                    )
                    """
                )
                params.append(tag)
            if free_text:
                like = f"%{free_text}%"
                skill_clause = """
                    EXISTS (
                        SELECT 1
                        FROM json_each(agent_rows.skills_json) AS je
                        WHERE lower(je.value) LIKE ?
                    )
                """
                if disabled_capabilities:
                    skill_clause = f"""
                        EXISTS (
                            SELECT 1
                            FROM json_each(agent_rows.skills_json) AS je
                            WHERE lower(je.value) LIKE ?
                              AND lower(je.value) NOT IN ({','.join('?' for _ in disabled_capabilities)})
                        )
                    """
                sql.append(
                    f"""
                    AND (
                        lower(display_name) LIKE ?
                        OR lower(role) LIKE ?
                        OR lower(description) LIKE ?
                        OR {skill_clause}
                        OR EXISTS (
                            SELECT 1
                            FROM json_each(agent_rows.tags_json) AS je
                            WHERE lower(je.value) LIKE ?
                        )
                    )
                    """
                )
                params.extend([like, like, like, like])
                if disabled_capabilities:
                    params.extend(sorted(disabled_capabilities))
                params.append(like)
            sql.append(" ORDER BY lower(display_name)")
            rows = conn.execute("".join(sql), params).fetchall()
        return [self._row_to_agent(row) for row in rows]

    def create_delivery(self, *, target_agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        delivery_id = uuid.uuid4().hex
        with self._connect() as conn:
            return self._create_delivery(
                conn,
                target_agent_id=target_agent_id,
                kind=kind,
                payload=payload,
                now=now,
                delivery_id=delivery_id,
            )

    def _create_delivery(
        self,
        conn: sqlite3.Connection,
        *,
        target_agent_id: str,
        kind: str,
        payload: dict[str, Any],
        now: str,
        delivery_id: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO deliveries (delivery_id, target_agent_id, kind, payload_json, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            (delivery_id, target_agent_id, kind, ensure_json(payload), now, now),
        )
        seq = conn.execute(
            "SELECT seq FROM deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()["seq"]
        return {
            "delivery_id": delivery_id,
            "seq": seq,
        }

    def create_routed_task(self, request: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        validated_request = validated_routed_task_request(request)
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            for capability in requested_routed_capabilities(validated_request):
                if capability.lower() in disabled_capabilities:
                    raise CapabilityDisabledError(capability)
            conn.execute(
                """
                INSERT INTO routed_tasks (
                    routed_task_id, parent_conversation_id, origin_agent_id, target_agent_id,
                    title, request_json, status, summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)
                ON CONFLICT(routed_task_id) DO UPDATE SET
                    parent_conversation_id = excluded.parent_conversation_id,
                    origin_agent_id = excluded.origin_agent_id,
                    target_agent_id = excluded.target_agent_id,
                    title = excluded.title,
                    request_json = excluded.request_json,
                    status = excluded.status,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (
                    validated_request["routed_task_id"],
                    validated_request["parent_conversation_id"],
                    validated_request["origin_agent_id"],
                    validated_request["target_agent_id"],
                    validated_request["title"],
                    ensure_json(validated_request),
                    now,
                    now,
                ),
            )
            delivery = self._create_delivery(
                conn,
                target_agent_id=validated_request["target_agent_id"],
                kind="routed_task",
                payload=validated_request,
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
        return {
            "routed_task_id": validated_request["routed_task_id"],
            "delivery_id": delivery["delivery_id"],
        }

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            allowed_kinds = delivery_kinds_for_registry_scope(
                registry_scope_for_agent_row(row)
            )
            if allowed_kinds is None:
                deliveries = conn.execute(
                    """
                    SELECT seq, delivery_id, kind, payload_json, state, created_at
                    FROM deliveries
                    WHERE target_agent_id = ?
                      AND state = 'queued'
                      AND seq > ?
                    ORDER BY seq ASC
                    LIMIT ?
                    """,
                    (row["agent_id"], cursor, limit),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in allowed_kinds)
                deliveries = conn.execute(
                    f"""
                    SELECT seq, delivery_id, kind, payload_json, state, created_at
                    FROM deliveries
                    WHERE target_agent_id = ?
                      AND state = 'queued'
                      AND seq > ?
                      AND kind IN ({placeholders})
                    ORDER BY seq ASC
                    LIMIT ?
                    """,
                    (row["agent_id"], cursor, *allowed_kinds, limit),
                ).fetchall()
            delivery_ids = [item["delivery_id"] for item in deliveries]
            if delivery_ids:
                placeholders = ",".join("?" for _ in delivery_ids)
                conn.execute(
                    f"""
                    UPDATE deliveries
                    SET state = 'leased', leased_at = ?, updated_at = ?
                    WHERE delivery_id IN ({placeholders})
                    """,
                    (now, now, *delivery_ids),
                )
        items = [
            {
                "cursor": str(item["seq"]),
                "delivery_id": item["delivery_id"],
                "kind": item["kind"],
                "payload": decode_json_field(item["payload_json"], {}),
                "state": "leased" if item["delivery_id"] in delivery_ids else item["state"],
                "created_at": item["created_at"],
            }
            for item in deliveries
        ]
        next_cursor = str(max([cursor] + [int(item["cursor"]) for item in items]))
        return {"deliveries": items, "next_cursor": next_cursor}

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> dict[str, Any]:
        now = utcnow_iso()
        validated_ids, validated_classification = validated_ack_request(
            delivery_ids=delivery_ids,
            classification=classification,
        )
        next_state = {
            "accepted": "acked",
            "rejected": "dead_letter",
            "retry_later": "queued",
        }[validated_classification]
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for delivery_id in validated_ids:
                conn.execute(
                    """
                    UPDATE deliveries
                    SET state = ?, updated_at = ?, acked_at = ?
                    WHERE delivery_id = ?
                      AND target_agent_id = ?
                    """,
                    (
                        next_state,
                        now,
                        now if next_state != "queued" else None,
                        delivery_id,
                        row["agent_id"],
                    ),
                )
        return {"updated": len(validated_ids), "classification": validated_classification}

    def update_routed_task_status(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        protected_status_placeholders = ", ".join("?" for _ in PROTECTED_ROUTED_TASK_STATUSES)
        validated_payload = validated_routed_task_status_payload(payload)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, {"coordination", "full"})
            cursor = conn.execute(
                f"""
                UPDATE routed_tasks
                SET status = ?, summary = ?, updated_at = ?
                WHERE routed_task_id = ?
                  AND status NOT IN ({protected_status_placeholders})
                """,
                (
                    validated_payload["status"],
                    validated_payload["summary"],
                    now,
                    routed_task_id,
                    *PROTECTED_ROUTED_TASK_STATUSES,
                ),
            )
            if cursor.rowcount > 0:
                for event in validated_payload["timeline_events"]:
                    event_metadata = {"status": validated_payload["status"], "routed_task_id": routed_task_id}
                    if event.get("title"):
                        event_metadata["title"] = event["title"]
                    if event.get("progress") is not None:
                        event_metadata["progress"] = event["progress"]
                    conn.execute(
                        """
                        INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(event_id) DO NOTHING
                        """,
                        (
                            event["event_id"],
                            event["conversation_id"],
                            row["agent_id"],
                            "task.status",
                            "",
                            event.get("body", ""),
                            ensure_json(event_metadata),
                            event["created_at"],
                        ),
                    )
            # Return enough context for WebSocket broadcast
            task_row = conn.execute(
                "SELECT parent_conversation_id, origin_agent_id, target_agent_id FROM routed_tasks WHERE routed_task_id = ?",
                (routed_task_id,),
            ).fetchone()
            result = {"routed_task_id": routed_task_id, "status": validated_payload["status"]}
            if task_row:
                result["parent_conversation_id"] = task_row["parent_conversation_id"]
                result["origin_agent_id"] = task_row["origin_agent_id"]
                result["target_agent_id"] = task_row["target_agent_id"]
        return result

    def update_routed_task_result(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        validated_payload = validated_routed_task_result_payload(payload)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, {"coordination", "full"})
            task = conn.execute(
                "SELECT * FROM routed_tasks WHERE routed_task_id = ?",
                (routed_task_id,),
            ).fetchone()
            if task is None:
                raise KeyError(routed_task_id)
            conn.execute(
                """
                UPDATE routed_tasks
                SET status = ?, summary = ?, result_json = ?, updated_at = ?
                WHERE routed_task_id = ?
                """,
                (
                    validated_payload["status"],
                    validated_payload["summary"],
                    ensure_json(validated_payload),
                    now,
                    routed_task_id,
                ),
            )
            self._create_delivery(
                conn,
                target_agent_id=task["origin_agent_id"],
                kind="routed_result",
                payload={
                    "routed_task_id": routed_task_id,
                    "parent_conversation_id": task["parent_conversation_id"],
                    "result": validated_payload,
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
        return {"routed_task_id": routed_task_id, "status": validated_payload["status"]}

    def deregister(self, agent_token: str) -> dict[str, Any]:
        now = utcnow_iso()
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE agents
                SET connectivity_state = 'offline', updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (now, now, agent_token_hash),
            )
            return {"agent_id": row["agent_id"], "connectivity_state": "offline"}

    def list_agents(self, *, for_agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if for_agent_id is not None:
                rows = conn.execute(
                    "SELECT * FROM agents WHERE agent_id = ? ORDER BY lower(display_name)",
                    (for_agent_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM agents ORDER BY lower(display_name)").fetchall()
        return [self._row_to_agent(row) for row in rows]

    def get_agent_runtime_health(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None
            return runtime_health_detail(
                row["runtime_health_json"],
                self._runtime_worker_rows(conn, agent_id),
            )

    def create_conversation(
        self,
        *,
        target_agent_id: str,
        title: str,
        origin_channel: str = "registry",
        external_conversation_ref: str = "",
    ) -> dict[str, Any]:
        now = utcnow_iso()
        conversation_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, target_agent_id, title, origin_channel,
                    external_conversation_ref, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(target_agent_id, origin_channel, external_conversation_ref) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (conversation_id, target_agent_id, title, origin_channel, external_conversation_ref, now, now),
            )
            # Resolve actual conversation_id (may be existing row)
            row = conn.execute(
                """
                SELECT conversation_id FROM conversations
                WHERE target_agent_id = ? AND origin_channel = ? AND external_conversation_ref = ?
                """,
                (target_agent_id, origin_channel, external_conversation_ref),
            ).fetchone()
            actual_id = row["conversation_id"] if row else conversation_id
        return self.get_conversation(actual_id)

    def list_conversations(self, *, for_agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            sql = """
                SELECT
                    c.*,
                    a.display_name AS target_name,
                    COUNT(e.event_id) AS event_count
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                LEFT JOIN events e ON e.conversation_id = c.conversation_id
            """
            params: list[Any] = []
            if for_agent_id is not None:
                sql += " WHERE c.target_agent_id = ?"
                params.append(for_agent_id)
            sql += """
                GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.status, c.created_at, c.updated_at, a.display_name
                ORDER BY c.updated_at DESC
            """
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "timeline_event_count": int(row["event_count"] or 0),
            }
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    c.*,
                    a.display_name AS target_name,
                    COUNT(e.event_id) AS event_count
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                LEFT JOIN events e ON e.conversation_id = c.conversation_id
                WHERE c.conversation_id = ?
                GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.status, c.created_at, c.updated_at, a.display_name
                """,
                (conversation_id,),
            ).fetchone()
            task_rows = conn.execute(
                """
                SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                FROM routed_tasks t
                LEFT JOIN agents origin ON origin.agent_id = t.origin_agent_id
                LEFT JOIN agents target ON target.agent_id = t.target_agent_id
                WHERE t.parent_conversation_id = ?
                ORDER BY t.updated_at DESC
                """,
                (conversation_id,),
            ).fetchall()
        if row is None:
            raise KeyError(conversation_id)
        tasks = [
            {
                "routed_task_id": task["routed_task_id"],
                "parent_conversation_id": task["parent_conversation_id"],
                "origin_agent_id": task["origin_agent_id"],
                "origin_display_name": task["origin_name"] or "",
                "target_agent_id": task["target_agent_id"],
                "target_display_name": task["target_name"] or "",
                "title": task["title"],
                "status": task["status"],
                "summary": task["summary"],
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
            }
            for task in task_rows
        ]
        return {
            "conversation_id": row["conversation_id"],
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "timeline_event_count": int(row["event_count"] or 0),
            "linked_routed_tasks": tasks,
        }

    def get_usage_summary(self, since_iso: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT conversation_id, metadata_json, created_at
                FROM events
                WHERE kind = 'usage' AND created_at >= ?
                ORDER BY created_at
                """,
                (since_iso,),
            ).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def search_conversations(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT ev.conversation_id,
                           snippet(events_fts, 0, '<b>', '</b>', '…', 32) AS snippet,
                           ev.seq
                    FROM events_fts
                    JOIN events ev ON ev.seq = events_fts.rowid
                    WHERE events_fts MATCH ?
                      AND ev.seq = (
                          SELECT MAX(ev2.seq)
                          FROM events ev2
                          WHERE ev2.conversation_id = ev.conversation_id
                            AND ev2.seq IN (
                                SELECT rowid
                                FROM events_fts
                                WHERE events_fts MATCH ?
                            )
                      )
                    ORDER BY ev.seq DESC
                    LIMIT ?
                    """,
                    (q, q, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"conversation_id": row["conversation_id"], "snippet": row["snippet"]} for row in rows]

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        validated_text = validated_conversation_message_text(text)
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT target_agent_id, title FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="channel_input",
                payload={
                    "conversation_id": conversation_id,
                    "title": conversation["title"],
                    "text": validated_text,
                    "channel": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            conn.execute(
                """INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""",
                (uuid.uuid4().hex, conversation_id, "", "message.user", "operator", validated_text, "{}", now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def add_conversation_action(self, conversation_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        validated_action, action_payload = validated_conversation_action(action, payload)
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT target_agent_id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="channel_action",
                payload={
                    "conversation_id": conversation_id,
                    "conversation_ref": conversation_id,
                    "action": validated_action,
                    "payload": action_payload,
                    "channel": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            is_cancel = validated_action == "cancel_conversation"
            if is_cancel:
                event_kind = "task.status"
                event_metadata = {"status": "cancelling"}
                event_content = ""
            else:
                event_kind = "approval.decided"
                event_metadata = {"action": validated_action, "decided_by": "operator"}
                event_content = json.dumps(action_payload) if action_payload else ""
            conn.execute(
                """INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""",
                (uuid.uuid4().hex, conversation_id, "", event_kind, "operator", event_content, ensure_json(event_metadata), now),
            )
            update_fields = "updated_at = ?"
            update_params: list[Any] = [now]
            if is_cancel:
                update_fields += ", status = ?"
                update_params.append("cancelling")
            update_params.append(conversation_id)
            conn.execute(
                f"UPDATE conversations SET {update_fields} WHERE conversation_id = ?",
                update_params,
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                FROM routed_tasks t
                LEFT JOIN agents origin ON origin.agent_id = t.origin_agent_id
                LEFT JOIN agents target ON target.agent_id = t.target_agent_id
                ORDER BY t.updated_at DESC
                """
            ).fetchall()
        return [
            {
                "routed_task_id": row["routed_task_id"],
                "parent_conversation_id": row["parent_conversation_id"],
                "origin_agent_id": row["origin_agent_id"],
                "origin_display_name": row["origin_name"] or "",
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "status": row["status"],
                "summary": row["summary"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def publish_events(self, agent_token: str, conversation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            agent_id = row["agent_id"]
            conversation = conn.execute(
                "SELECT target_agent_id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise PermissionError(f"Unknown conversation: {conversation_id}")
            if conversation["target_agent_id"] != agent_id:
                raise PermissionError(f"Conversation does not belong to agent: {conversation_id}")
            inserted = 0
            skipped = 0
            for event in events:
                serialized = json.dumps(event)
                if len(serialized) >= 256 * 1024:
                    raise ValueError("Event exceeds 256KB size limit")
                event_id = str(event.get("event_id", "") or "")
                if not event_id.strip():
                    raise ValueError("event_id is required")
                kind = str(event.get("kind", "") or "")
                if not kind.strip():
                    raise ValueError("kind is required")
                created_at = str(event.get("created_at", "") or "") or utcnow_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        event_id,
                        conversation_id,
                        agent_id,
                        kind,
                        str(event.get("actor", "") or ""),
                        str(event.get("content", "") or ""),
                        ensure_json(event.get("metadata", {})),
                        created_at,
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
        return {"inserted": inserted, "skipped": skipped}

    def list_events(self, conversation_id: str, *, kind: str = "", cursor: int = 0, limit: int = 50) -> dict[str, Any]:
        with self._connect() as conn:
            if kind:
                rows = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE conversation_id = ? AND kind = ? AND seq > ?
                    ORDER BY seq ASC
                    LIMIT ?
                    """,
                    (conversation_id, kind, cursor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE conversation_id = ? AND seq > ?
                    ORDER BY seq ASC
                    LIMIT ?
                    """,
                    (conversation_id, cursor, limit),
                ).fetchall()
        events_list = [
            {
                "seq": row["seq"],
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "agent_id": row["agent_id"],
                "kind": row["kind"],
                "actor": row["actor"],
                "content": row["content"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        next_cursor = events_list[-1]["seq"] if events_list else 0
        return {"events": events_list, "next_cursor": next_cursor}

    def list_messages(self, conversation_id: str, *, cursor: int = 0, limit: int = 50) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE conversation_id = ? AND kind IN ('message.user', 'message.bot') AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (conversation_id, cursor, limit),
            ).fetchall()
        events_list = [
            {
                "seq": row["seq"],
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "agent_id": row["agent_id"],
                "kind": row["kind"],
                "actor": row["actor"],
                "content": row["content"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        next_cursor = events_list[-1]["seq"] if events_list else 0
        return {"events": events_list, "next_cursor": next_cursor}

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        effective_agent_id = for_agent_id if for_agent_id is not None else agent_id
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, a.display_name AS target_name
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                WHERE c.target_agent_id = ?
                ORDER BY c.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (effective_agent_id, limit, cursor),
            ).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "origin_channel": row["origin_channel"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_agent_status(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None
            agent = self._row_to_agent(row)
            workers = self._runtime_worker_rows(conn, agent_id)
            active_count_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM conversations
                WHERE target_agent_id = ? AND status IN ('open', 'running')
                """,
                (agent_id,),
            ).fetchone()
            active_conversations = int(active_count_row["cnt"]) if active_count_row else 0
            error_count_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM events
                WHERE agent_id = ? AND kind = 'error'
                  AND created_at >= datetime('now', '-1 hour')
                """,
                (agent_id,),
            ).fetchone()
            recent_errors = int(error_count_row["cnt"]) if error_count_row else 0
        agent["workers"] = workers
        agent["active_conversations"] = active_conversations
        agent["recent_errors"] = recent_errors
        return agent

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            sql = "SELECT * FROM events WHERE kind = 'usage'"
            params: list[Any] = []
            if agent_id:
                sql += " AND agent_id = ?"
                params.append(agent_id)
            if conversation_id:
                sql += " AND conversation_id = ?"
                params.append(conversation_id)
            if since:
                sql += " AND created_at >= ?"
                params.append(since)
            if until:
                sql += " AND created_at <= ?"
                params.append(until)
            sql += " ORDER BY created_at"
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "agent_id": row["agent_id"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def export_conversation(self, conversation_id: str) -> str:
        with self._connect() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conv is None:
                raise KeyError(conversation_id)
            rows = conn.execute(
                "SELECT * FROM events WHERE conversation_id = ? ORDER BY seq ASC",
                (conversation_id,),
            ).fetchall()
        lines = [f"# Conversation: {conv['title'] or conversation_id}", ""]
        for row in rows:
            actor = row["actor"] or row["agent_id"] or "system"
            lines.append(f"## [{row['created_at']}] {actor} ({row['kind']})")
            lines.append("")
            if row["content"]:
                lines.append(row["content"])
                lines.append("")
        return "\n".join(lines)

    def purge_old_events(self, older_than_days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM events WHERE created_at < ?",
                (cutoff,),
            )
            count = cursor.rowcount
        return count

    # ------------------------------------------------------------------
    # Skill / guidance persistence (registry-owned content store)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(raw: str, default: Any) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    @staticmethod
    def _stable_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True)

    def _skill_revision_id(self, record: RuntimeSkillTrackRecord) -> str:
        return record.revision.revision_id or f"{record.slug}|{record.revision.digest}"

    def _guidance_revision_id(self, record: ProviderGuidanceTrackRecord) -> str:
        key = f"{record.provider}|{record.scope_kind}|{record.scope_key}"
        return record.revision.revision_id or f"{key}|{record.revision.digest}"

    def _upsert_registry_skill(
        self,
        record: RuntimeSkillTrackRecord,
        *,
        status: str,
        publish: bool,
    ) -> None:
        now = utcnow_iso()
        revision_id = self._skill_revision_id(record)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT published_revision_id FROM runtime_skills WHERE slug = ?",
                (record.slug,),
            ).fetchone()
            published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
            conn.execute(
                """
                INSERT INTO runtime_skills (
                    slug, display_name, description, source_kind, source_uri, owner_actor,
                    visibility, is_mutable, archived, instruction_body, requirements_json,
                    provider_config_json, files_json, active_revision_id, published_revision_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    display_name = excluded.display_name,
                    description = excluded.description,
                    source_kind = excluded.source_kind,
                    source_uri = excluded.source_uri,
                    owner_actor = excluded.owner_actor,
                    visibility = excluded.visibility,
                    is_mutable = excluded.is_mutable,
                    archived = excluded.archived,
                    instruction_body = excluded.instruction_body,
                    requirements_json = excluded.requirements_json,
                    provider_config_json = excluded.provider_config_json,
                    files_json = excluded.files_json,
                    active_revision_id = excluded.active_revision_id,
                    published_revision_id = excluded.published_revision_id,
                    updated_at = excluded.updated_at
                """,
                (
                    record.slug,
                    record.display_name,
                    record.description,
                    record.source_kind,
                    record.source_uri,
                    record.owner_actor,
                    record.visibility,
                    1 if record.is_mutable else 0,
                    1 if record.archived else 0,
                    record.revision.instruction_body,
                    self._stable_json(record.revision.requirements),
                    self._stable_json(record.revision.provider_config),
                    self._stable_json(
                        [
                            {
                                "relative_path": f.relative_path,
                                "content_text": f.content_text,
                                "content_type": f.content_type,
                                "executable": f.executable,
                            }
                            for f in record.revision.files
                        ]
                    ),
                    revision_id,
                    published_revision_id,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO skill_revisions (
                    revision_id, slug, instruction_body, requirements_json,
                    provider_config_json, files_json, version_label, changelog,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    record.slug,
                    record.revision.instruction_body,
                    self._stable_json(record.revision.requirements),
                    self._stable_json(record.revision.provider_config),
                    self._stable_json(
                        [
                            {
                                "relative_path": f.relative_path,
                                "content_text": f.content_text,
                                "content_type": f.content_type,
                                "executable": f.executable,
                            }
                            for f in record.revision.files
                        ]
                    ),
                    record.revision.version_label,
                    record.revision.changelog,
                    status,
                    record.revision.created_by,
                    record.revision.created_at or now,
                ),
            )

    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        self._upsert_registry_skill(record, status="published", publish=True)

    def delete_skill_track(
        self,
        slug: str,
        *,
        source_kind: str,
        source_uri: str = "",
        owner_actor: str = "",
    ) -> bool:
        with self._connect() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM skill_revisions WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM skill_approvals WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM runtime_skills WHERE slug = ?", (slug,))
            return conn.total_changes > before

    def _skill_row_to_track(self, row: sqlite3.Row) -> RuntimeSkillTrackRecord:
        files_data = self._parse_json(row["files_json"], [])
        files = tuple(
            SkillFileRecord(
                relative_path=f.get("relative_path", ""),
                content_text=f.get("content_text", ""),
                content_type=f.get("content_type", "text/plain"),
                executable=bool(f.get("executable", False)),
            )
            for f in files_data
            if isinstance(f, dict)
        )
        # Determine the revision status from skill_revisions if available
        revision_status = row["status"] if "status" in row.keys() else "published"
        revision = SkillRevisionRecord(
            instruction_body=row["instruction_body"],
            requirements=self._parse_json(row["requirements_json"], []),
            provider_config=self._parse_json(row["provider_config_json"], {}),
            files=files,
            version_label=row["version_label"] if "version_label" in row.keys() else "",
            changelog=row["changelog"] if "changelog" in row.keys() else "",
            created_by=row["created_by"] if "created_by" in row.keys() else "",
            created_at=row["created_at"] if "created_at" in row.keys() else "",
            revision_id=row["revision_id"] if "revision_id" in row.keys() else row["active_revision_id"],
            status=revision_status,
        )
        return RuntimeSkillTrackRecord(
            slug=row["slug"],
            display_name=row["display_name"],
            description=row["description"],
            source_kind=row["source_kind"],
            revision=revision,
            source_uri=row["source_uri"],
            owner_actor=row["owner_actor"],
            visibility=row["visibility"],
            is_mutable=bool(row["is_mutable"]),
            archived=bool(row["archived"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
        )

    def _skill_rows_for_slug(self, slug: str, *, runtime_only: bool) -> list[sqlite3.Row]:
        revision_ref = (
            "CASE WHEN s.published_revision_id != '' THEN s.published_revision_id ELSE s.active_revision_id END"
            if runtime_only else "s.active_revision_id"
        )
        extra_where = "AND s.published_revision_id != ''" if runtime_only else ""
        with self._connect() as conn:
            return conn.execute(
                f"""
                SELECT
                    s.slug, s.display_name, s.description, s.source_kind,
                    s.source_uri, s.owner_actor, s.visibility, s.is_mutable,
                    s.archived, s.active_revision_id, s.published_revision_id,
                    rev.revision_id, rev.instruction_body, rev.requirements_json,
                    rev.provider_config_json, rev.files_json, rev.version_label,
                    rev.changelog, rev.status, rev.created_by, rev.created_at
                FROM runtime_skills s
                JOIN skill_revisions rev ON rev.revision_id = {revision_ref}
                WHERE s.slug = ?
                {extra_where}
                """,
                (slug,),
            ).fetchall()

    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        records = [self._skill_row_to_track(row) for row in self._skill_rows_for_slug(slug, runtime_only=False)]
        return sorted(records, key=lambda r: skill_precedence(r.source_kind), reverse=True)

    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        tracks = self.list_skill_tracks(slug)
        return tracks[0] if tracks else None

    def resolve_runtime_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        records = [self._skill_row_to_track(row) for row in self._skill_rows_for_slug(slug, runtime_only=True)]
        records = sorted(records, key=lambda r: skill_precedence(r.source_kind), reverse=True)
        return records[0] if records else None

    def _skill_summaries(self, *, runtime_only: bool) -> list[RuntimeSkillSummary]:
        with self._connect() as conn:
            rows = conn.execute("SELECT slug FROM runtime_skills ORDER BY lower(slug)").fetchall()
        resolver = self.resolve_runtime_skill if runtime_only else self.resolve_skill
        summaries: list[RuntimeSkillSummary] = []
        for row in rows:
            record = resolver(row["slug"])
            if record is None:
                continue
            summaries.append(
                RuntimeSkillSummary(
                    slug=record.slug,
                    display_name=record.display_name,
                    description=record.description,
                    source_kind=record.source_kind,
                    source_uri=record.source_uri,
                    visibility=record.visibility,
                    is_mutable=record.is_mutable,
                    digest=record.revision.digest,
                    status=record.revision.status,
                    runtime_available=bool(record.published_revision_id) or not record.is_mutable,
                    has_unpublished_changes=bool(record.published_revision_id)
                    and record.published_revision_id != record.active_revision_id,
                )
            )
        return summaries

    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        return self._skill_summaries(runtime_only=False)

    def list_runtime_skill_summaries(self) -> list[RuntimeSkillSummary]:
        return self._skill_summaries(runtime_only=True)

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        self._upsert_registry_skill(record, status="draft", publish=False)

    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT revision_id, instruction_body, requirements_json, provider_config_json,
                       files_json, version_label, changelog, status, created_by, created_at
                FROM skill_revisions
                WHERE slug = ?
                ORDER BY created_at DESC, revision_id DESC
                """,
                (slug,),
            ).fetchall()
        return [
            SkillRevisionRecord(
                instruction_body=row["instruction_body"],
                requirements=self._parse_json(row["requirements_json"], []),
                provider_config=self._parse_json(row["provider_config_json"], {}),
                files=tuple(
                    SkillFileRecord(
                        relative_path=f.get("relative_path", ""),
                        content_text=f.get("content_text", ""),
                        content_type=f.get("content_type", "text/plain"),
                        executable=bool(f.get("executable", False)),
                    )
                    for f in self._parse_json(row["files_json"], [])
                    if isinstance(f, dict)
                ),
                version_label=row["version_label"],
                changelog=row["changelog"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revision_id=row["revision_id"],
                status=row["status"],
            )
            for row in rows
        ]

    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id, revision_id, action, actor, note, created_at
                FROM skill_approvals
                WHERE slug = ?
                ORDER BY created_at DESC, record_id DESC
                """,
                (slug,),
            ).fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_latest_skill_approval_action(self, slug: str, revision_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT action
                FROM skill_approvals
                WHERE slug = ? AND revision_id = ?
                ORDER BY created_at DESC, record_id DESC
                LIMIT 1
                """,
                (slug, revision_id),
            ).fetchone()
        return str(row["action"]) if row is not None else ""

    def append_skill_approval(
        self,
        slug: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
    ) -> LifecycleApprovalRecord:
        now = utcnow_iso()
        record_id = f"{slug}|{revision_id}|{action}|{now}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_approvals (
                    record_id, slug, revision_id, action, actor, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, slug, revision_id, action, actor, note, now),
            )
        return LifecycleApprovalRecord(
            record_id=record_id,
            revision_id=revision_id,
            action=action,
            actor=actor,
            note=note,
            created_at=now,
        )

    def set_skill_revision_status(self, slug: str, revision_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE skill_revisions SET status = ? WHERE slug = ? AND revision_id = ?",
                (status, slug, revision_id),
            )

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runtime_skills SET published_revision_id = ?, updated_at = ? WHERE slug = ?",
                (revision_id, utcnow_iso(), slug),
            )

    def clear_published_skill_revision(self, slug: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE runtime_skills SET published_revision_id = '', updated_at = ? WHERE slug = ?",
                (utcnow_iso(), slug),
            )

    def apply_skill_lifecycle_transition(
        self,
        slug: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
    ) -> LifecycleApprovalRecord | None:
        record: LifecycleApprovalRecord | None = None
        now = utcnow_iso()
        record_id = (
            f"{slug}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else ""
        )
        with self._connect() as conn:
            if set_status is not None:
                conn.execute(
                    "UPDATE skill_revisions SET status = ? WHERE slug = ? AND revision_id = ?",
                    (set_status, slug, revision_id),
                )
            if published_pointer == "set_active":
                conn.execute(
                    "UPDATE runtime_skills SET published_revision_id = ?, updated_at = ? WHERE slug = ?",
                    (revision_id, now, slug),
                )
            elif published_pointer == "clear":
                conn.execute(
                    "UPDATE runtime_skills SET published_revision_id = '', updated_at = ? WHERE slug = ?",
                    (now, slug),
                )
            if approval_action is not None:
                conn.execute(
                    """
                    INSERT INTO skill_approvals (
                        record_id, slug, revision_id, action, actor, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, slug, revision_id, approval_action, actor, note, now),
                )
                record = LifecycleApprovalRecord(
                    record_id=record_id,
                    revision_id=revision_id,
                    action=approval_action,
                    actor=actor,
                    note=note,
                    created_at=now,
                )
        return record

    # --- Provider guidance ---

    def _upsert_registry_guidance(
        self,
        record: ProviderGuidanceTrackRecord,
        *,
        status: str,
        publish: bool,
    ) -> None:
        now = utcnow_iso()
        revision_id = self._guidance_revision_id(record)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT published_revision_id FROM provider_guidance WHERE provider = ? AND scope_kind = ? AND scope_key = ?",
                (record.provider, record.scope_kind, record.scope_key),
            ).fetchone()
            published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
            conn.execute(
                """
                INSERT INTO provider_guidance (
                    provider, scope_kind, scope_key, content, format, is_mutable,
                    active_revision_id, published_revision_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, scope_kind, scope_key) DO UPDATE SET
                    content = excluded.content,
                    format = excluded.format,
                    is_mutable = excluded.is_mutable,
                    active_revision_id = excluded.active_revision_id,
                    published_revision_id = excluded.published_revision_id,
                    updated_at = excluded.updated_at
                """,
                (
                    record.provider,
                    record.scope_kind,
                    record.scope_key,
                    record.revision.content,
                    record.revision.format,
                    1 if record.is_mutable else 0,
                    revision_id,
                    published_revision_id,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO guidance_revisions (
                    revision_id, provider, scope_kind, scope_key, content, format,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    record.provider,
                    record.scope_kind,
                    record.scope_key,
                    record.revision.content,
                    record.revision.format,
                    status,
                    record.revision.created_by,
                    record.revision.created_at or now,
                ),
            )

    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        self._upsert_registry_guidance(record, status="published", publish=True)

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        self._upsert_registry_guidance(record, status="draft", publish=False)

    def get_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    g.provider, g.scope_kind, g.scope_key, g.is_mutable,
                    g.active_revision_id, g.published_revision_id,
                    rev.content, rev.format, rev.created_by, rev.created_at,
                    rev.status, rev.revision_id
                FROM provider_guidance g
                JOIN guidance_revisions rev ON rev.revision_id = g.active_revision_id
                WHERE g.provider = ? AND g.scope_kind = ? AND g.scope_key = ?
                """,
                (provider, scope_kind, scope_key),
            ).fetchone()
        if row is None:
            return None
        return ProviderGuidanceTrackRecord(
            provider=row["provider"],
            scope_kind=row["scope_kind"],
            scope_key=row["scope_key"],
            is_mutable=bool(row["is_mutable"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revision_id=row["revision_id"],
                status=row["status"],
            ),
        )

    def _runtime_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str,
        scope_key: str,
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    g.provider, g.scope_kind, g.scope_key, g.is_mutable,
                    g.active_revision_id, g.published_revision_id,
                    rev.content, rev.format, rev.created_by, rev.created_at,
                    rev.status, rev.revision_id
                FROM provider_guidance g
                JOIN guidance_revisions rev ON rev.revision_id = g.published_revision_id
                WHERE g.provider = ? AND g.scope_kind = ? AND g.scope_key = ? AND g.published_revision_id != ''
                """,
                (provider, scope_kind, scope_key),
            ).fetchone()
        if row is None:
            return None
        return ProviderGuidanceTrackRecord(
            provider=row["provider"],
            scope_kind=row["scope_kind"],
            scope_key=row["scope_key"],
            is_mutable=bool(row["is_mutable"]),
            active_revision_id=row["active_revision_id"],
            published_revision_id=row["published_revision_id"],
            revision=ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revision_id=row["revision_id"],
                status=row["status"],
            ),
        )

    def resolve_provider_guidance(
        self,
        provider: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        if instance_key:
            match = self._runtime_provider_guidance(provider, scope_kind="instance", scope_key=instance_key)
            if match is not None:
                return match
        return self._runtime_provider_guidance(provider, scope_kind="system", scope_key="")

    def list_provider_guidance_revisions(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT revision_id, content, format, created_by, created_at, status
                FROM guidance_revisions
                WHERE provider = ? AND scope_kind = ? AND scope_key = ?
                ORDER BY created_at DESC, revision_id DESC
                """,
                (provider, scope_kind, scope_key),
            ).fetchall()
        return [
            ProviderGuidanceRevisionRecord(
                content=row["content"],
                format=row["format"],
                created_by=row["created_by"],
                created_at=row["created_at"],
                revision_id=row["revision_id"],
                status=row["status"],
            )
            for row in rows
        ]

    def list_provider_guidance_approvals(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT record_id, revision_id, action, actor, note, created_at
                FROM guidance_approvals
                WHERE provider = ? AND scope_kind = ? AND scope_key = ?
                ORDER BY created_at DESC, record_id DESC
                """,
                (provider, scope_kind, scope_key),
            ).fetchall()
        return [
            LifecycleApprovalRecord(
                record_id=row["record_id"],
                revision_id=row["revision_id"],
                action=row["action"],
                actor=row["actor"],
                note=row["note"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_latest_provider_guidance_approval_action(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT action
                FROM guidance_approvals
                WHERE provider = ? AND scope_kind = ? AND scope_key = ? AND revision_id = ?
                ORDER BY created_at DESC, record_id DESC
                LIMIT 1
                """,
                (provider, scope_kind, scope_key, revision_id),
            ).fetchone()
        return str(row["action"]) if row is not None else ""

    def append_provider_guidance_approval(
        self,
        provider: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord:
        now = utcnow_iso()
        record_id = f"{provider}|{scope_kind}|{scope_key}|{revision_id}|{action}|{now}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO guidance_approvals (
                    record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, now),
            )
        return LifecycleApprovalRecord(
            record_id=record_id,
            revision_id=revision_id,
            action=action,
            actor=actor,
            note=note,
            created_at=now,
        )

    def set_provider_guidance_revision_status(
        self,
        provider: str,
        revision_id: str,
        status: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE guidance_revisions SET status = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ? AND revision_id = ?",
                (status, provider, scope_kind, scope_key, revision_id),
            )

    def set_published_provider_guidance_revision(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE provider_guidance SET published_revision_id = ?, updated_at = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ?",
                (revision_id, utcnow_iso(), provider, scope_kind, scope_key),
            )

    def clear_published_provider_guidance_revision(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE provider_guidance SET published_revision_id = '', updated_at = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ?",
                (utcnow_iso(), provider, scope_kind, scope_key),
            )

    def apply_provider_guidance_lifecycle_transition(
        self,
        provider: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: Literal["unchanged", "set_active", "clear"] = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> LifecycleApprovalRecord | None:
        record: LifecycleApprovalRecord | None = None
        now = utcnow_iso()
        record_id = (
            f"{provider}|{scope_kind}|{scope_key}|{revision_id}|{approval_action}|{now}"
            if approval_action is not None else ""
        )
        with self._connect() as conn:
            if set_status is not None:
                conn.execute(
                    "UPDATE guidance_revisions SET status = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ? AND revision_id = ?",
                    (set_status, provider, scope_kind, scope_key, revision_id),
                )
            if published_pointer == "set_active":
                conn.execute(
                    "UPDATE provider_guidance SET published_revision_id = ?, updated_at = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ?",
                    (revision_id, now, provider, scope_kind, scope_key),
                )
            elif published_pointer == "clear":
                conn.execute(
                    "UPDATE provider_guidance SET published_revision_id = '', updated_at = ? WHERE provider = ? AND scope_kind = ? AND scope_key = ?",
                    (now, provider, scope_kind, scope_key),
                )
            if approval_action is not None:
                conn.execute(
                    """
                    INSERT INTO guidance_approvals (
                        record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record_id, provider, scope_kind, scope_key, revision_id, approval_action, actor, note, now),
                )
                record = LifecycleApprovalRecord(
                    record_id=record_id,
                    revision_id=revision_id,
                    action=approval_action,
                    actor=actor,
                    note=note,
                    created_at=now,
                )
        return record
