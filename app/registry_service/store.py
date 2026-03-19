"""SQLite implementation of the central agent registry store."""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.agents.types import TimelineEvent
from app.capability_service import (
    declared_capabilities,
    query_capabilities,
    requested_routed_capabilities,
)
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    conversation_status_for_event,
    decode_json_field,
    effective_connectivity_state,
    ensure_json,
    hash_agent_token,
    runtime_health_detail,
    runtime_health_generated_at,
    runtime_health_summary,
    utcnow_iso,
)

_SCHEMA_VERSION = 5

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
    origin_channel TEXT NOT NULL DEFAULT 'registry',
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
"""
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
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skills_override (
                skill_name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                set_by TEXT NOT NULL DEFAULT 'ui',
                set_at REAL NOT NULL
            );
            """
        )

    def _migrate_v2_timeline_fts(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
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
            """
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
        conn.executescript(
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
            """
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

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        current = self._current_schema_version(conn)
        if current > _SCHEMA_VERSION:
            raise RuntimeError(
                f"Registry DB schema version {current} is newer than supported version {_SCHEMA_VERSION}. Upgrade the registry."
            )
        if current < 1:
            self._migrate_v1(conn)
            self._set_schema_version(conn, 1)
            conn.commit()
            current = 1
        if current < 2:
            self._migrate_v2_timeline_fts(conn)
            self._set_schema_version(conn, 2)
            conn.commit()
            current = 2
        if current < 3:
            self._migrate_v3_runtime_health(conn)
            self._set_schema_version(conn, 3)
            conn.commit()
            current = 3
        if current < 4:
            self._migrate_v4_channel_vocabulary(conn)
            self._set_schema_version(conn, 4)
            conn.commit()
            current = 4
        if current < 5:
            self._migrate_v5_agent_token_hashing(conn)
            self._set_schema_version(conn, 5)
            conn.commit()

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

    def _offline_before(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    def _upsert_timeline_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        conversation_id: str,
        routed_task_id: str,
        agent_id: str,
        kind: str,
        title: str,
        body: str,
        status: str,
        progress: int | None,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO timeline_events (
                event_id, conversation_id, routed_task_id, agent_id, kind, title,
                body, status, progress, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                conversation_id = excluded.conversation_id,
                routed_task_id = excluded.routed_task_id,
                agent_id = excluded.agent_id,
                kind = excluded.kind,
                title = excluded.title,
                body = excluded.body,
                status = excluded.status,
                progress = excluded.progress,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at
            """,
            (
                event_id,
                conversation_id,
                routed_task_id,
                agent_id,
                kind,
                title,
                body,
                status,
                progress,
                ensure_json(metadata),
                created_at,
            ),
        )

    def _publish_ui_timeline_conn(
        self,
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        title: str,
        body: str,
        kind: str,
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = TimelineEvent(
            event_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            kind=kind,
            title=title,
            body=body,
            status=status,
            progress=progress,
            metadata=metadata or {},
        )
        conversation = conn.execute(
            """
            SELECT status
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
        self._upsert_timeline_event(
            conn,
            event_id=event.event_id,
            conversation_id=event.conversation_id,
            routed_task_id="",
            agent_id="",
            kind=event.kind,
            title=event.title,
            body=event.body,
            status=event.status,
            progress=event.progress,
            metadata=event.metadata,
            created_at=event.created_at,
        )
        if conversation is not None:
            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?, status = ?
                WHERE conversation_id = ?
                """,
                (
                    event.created_at,
                    conversation_status_for_event(kind, conversation["status"]),
                    conversation_id,
                ),
            )

    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn:
            slug = self._ensure_unique_slug(conn, requested_card.get("slug") or "agent")
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, agent_token, display_name, slug, role,
                    skills_json, tags_json, description, provider, mode,
                    connectivity_state, current_capacity, max_capacity,
                    channel_capabilities_json, version, created_at, updated_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    agent_token_hash,
                    requested_card.get("display_name") or slug,
                    slug,
                    requested_card.get("role", ""),
                    ensure_json(declared_capabilities(requested_card)),
                    ensure_json(requested_card.get("tags", [])),
                    requested_card.get("description", ""),
                    requested_card.get("provider", ""),
                    requested_card.get("mode", "registry"),
                    requested_card.get("connectivity_state", "degraded"),
                    int(requested_card.get("current_capacity", 0)),
                    max(1, int(requested_card.get("max_capacity", 1))),
                    ensure_json(requested_card.get("channel_capabilities", [])),
                    requested_card.get("version", ""),
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

    def register(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        card = payload["agent_card"]
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE agents
                SET display_name = ?, role = ?, skills_json = ?, tags_json = ?,
                    description = ?, provider = ?, mode = ?, connectivity_state = ?,
                    current_capacity = ?, max_capacity = ?, channel_capabilities_json = ?,
                    version = ?, updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (
                    card.get("display_name", row["display_name"]),
                    card.get("role", row["role"]),
                    ensure_json(declared_capabilities(card)),
                    ensure_json(card.get("tags", [])),
                    card.get("description", row["description"]),
                    card.get("provider", row["provider"]),
                    card.get("mode", row["mode"]),
                    payload.get("connectivity_state", row["connectivity_state"]),
                    int(payload.get("current_capacity", 0)),
                    max(1, int(payload.get("max_capacity", 1))),
                    ensure_json(card.get("channel_capabilities", [])),
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
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            runtime_health_payload = payload.get("runtime_health")
            conn.execute(
                """
                UPDATE agents
                SET connectivity_state = ?, current_capacity = ?, max_capacity = ?,
                    updated_at = ?, last_heartbeat_at = ?,
                    runtime_health_json = ?
                WHERE agent_token = ?
                """,
                (
                    payload.get("connectivity_state", row["connectivity_state"]),
                    int(payload.get("current_capacity", row["current_capacity"])),
                    max(1, int(payload.get("max_capacity", row["max_capacity"]))),
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

    def publish_timeline(self, agent_token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for event in events:
                conversation_id = event["conversation_id"]
                conversation = conn.execute(
                    """
                    SELECT status, target_agent_id
                    FROM conversations
                    WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if conversation is None:
                    raise PermissionError(f"Unknown conversation: {conversation_id}")
                if conversation["target_agent_id"] != row["agent_id"]:
                    raise PermissionError(f"Conversation does not belong to agent: {conversation_id}")
                self._upsert_timeline_event(
                    conn,
                    event_id=event["event_id"],
                    conversation_id=conversation_id,
                    routed_task_id=event.get("metadata", {}).get("routed_task_id", ""),
                    agent_id=row["agent_id"],
                    kind=event["kind"],
                    title=event["title"],
                    body=event.get("body", ""),
                    status=event.get("status", ""),
                    progress=event.get("progress"),
                    metadata=event.get("metadata", {}),
                    created_at=event["created_at"],
                )
                conn.execute(
                    """
                    UPDATE conversations
                    SET updated_at = ?, status = ?
                    WHERE conversation_id = ?
                    """,
                    (
                        event["created_at"],
                        conversation_status_for_event(event["kind"], conversation["status"]),
                        conversation_id,
                    ),
                )
            return {"accepted": len(events)}

    def bind_conversation(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, target_agent_id, title, origin_channel, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    target_agent_id = excluded.target_agent_id,
                    title = excluded.title,
                    origin_channel = excluded.origin_channel,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["conversation_id"],
                    row["agent_id"],
                    payload.get("title", ""),
                    payload.get("origin_channel", "telegram"),
                    now,
                    now,
                ),
            )
        return self.get_conversation(payload["conversation_id"])

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
        role = query.get("role", "").strip().lower()
        required_state = query.get("required_state", "connected")
        capabilities = query_capabilities(query)
        tags = {s.lower() for s in query.get("tags", []) if s}
        free_text = query.get("free_text", "").strip().lower()
        exclude = sorted(set(query.get("exclude_agent_ids", [])))
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            capabilities = capabilities - disabled_capabilities
            if (query.get("capabilities") or query.get("skills")) and not capabilities:
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
                if disabled_skills:
                    skill_clause = f"""
                        EXISTS (
                            SELECT 1
                            FROM json_each(agent_rows.skills_json) AS je
                            WHERE lower(je.value) LIKE ?
                              AND lower(je.value) NOT IN ({','.join('?' for _ in disabled_skills)})
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
                if disabled_skills:
                    params.extend(sorted(disabled_skills))
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
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            for capability in requested_routed_capabilities(request):
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
                    request["routed_task_id"],
                    request["parent_conversation_id"],
                    request["origin_agent_id"],
                    request["target_agent_id"],
                    request["title"],
                    ensure_json(request),
                    now,
                    now,
                ),
            )
            delivery = self._create_delivery(
                conn,
                target_agent_id=request["target_agent_id"],
                kind="routed_task",
                payload=request,
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
        return {
            "routed_task_id": request["routed_task_id"],
            "delivery_id": delivery["delivery_id"],
        }

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
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
        next_state = {
            "accepted": "acked",
            "rejected": "dead_letter",
            "retry_later": "queued",
        }.get(classification, "queued")
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for delivery_id in delivery_ids:
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
        return {"updated": len(delivery_ids), "classification": classification}

    def update_routed_task_status(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE routed_tasks
                SET status = ?, summary = ?, updated_at = ?
                WHERE routed_task_id = ?
                """,
                (payload.get("status", ""), payload.get("summary", ""), now, routed_task_id),
            )
            for event in payload.get("timeline_events", []):
                self._upsert_timeline_event(
                    conn,
                    event_id=event["event_id"],
                    conversation_id=event["conversation_id"],
                    routed_task_id=routed_task_id,
                    agent_id=row["agent_id"],
                    kind=event["kind"],
                    title=event["title"],
                    body=event.get("body", ""),
                    status=event.get("status", ""),
                    progress=event.get("progress"),
                    metadata=event.get("metadata", {}),
                    created_at=event["created_at"],
                )
        return {"routed_task_id": routed_task_id, "status": payload.get("status", "")}

    def update_routed_task_result(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
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
                    payload.get("status", "completed"),
                    payload.get("summary", ""),
                    ensure_json(payload),
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
                    "result": payload,
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
        return {"routed_task_id": routed_task_id, "status": payload.get("status", "completed")}

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

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY lower(display_name)").fetchall()
        return [self._row_to_agent(row) for row in rows]

    def ui_bootstrap(self) -> dict[str, Any]:
        return {
            "bots": self.list_agents(),
            "conversations": self.list_conversations(),
            "tasks": self.list_tasks(),
        }

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

    def create_conversation(self, *, target_agent_id: str, title: str, message_text: str) -> dict[str, Any]:
        now = utcnow_iso()
        conversation_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, target_agent_id, title, origin_channel, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'registry', 'open', ?, ?)
                """,
                (conversation_id, target_agent_id, title, now, now),
            )
            self._create_delivery(
                conn,
                target_agent_id=target_agent_id,
                kind="channel_input",
                payload={
                    "conversation_id": conversation_id,
                    "title": title,
                    "text": message_text,
                    "channel": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="Conversation started",
                body=message_text,
                kind="channel_input",
            )
        return self.get_conversation(conversation_id)

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.*,
                    a.display_name AS target_name,
                    COUNT(t.event_id) AS timeline_event_count
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                LEFT JOIN timeline_events t ON t.conversation_id = c.conversation_id
                GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.status, c.created_at, c.updated_at, a.display_name
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "timeline_event_count": int(row["timeline_event_count"] or 0),
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
                    COUNT(t.event_id) AS timeline_event_count
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                LEFT JOIN timeline_events t ON t.conversation_id = c.conversation_id
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
            "timeline_event_count": int(row["timeline_event_count"] or 0),
            "linked_routed_tasks": tasks,
        }

    def get_conversation_timeline(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM timeline_events
                WHERE conversation_id = ?
                ORDER BY seq ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "routed_task_id": row["routed_task_id"],
                "agent_id": row["agent_id"],
                "kind": row["kind"],
                "title": row["title"],
                "body": row["body"],
                "status": row["status"],
                "progress": row["progress"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_usage_summary(self, since_iso: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT conversation_id, metadata_json, created_at
                FROM timeline_events
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
                    SELECT te.conversation_id,
                           snippet(timeline_fts, 0, '<b>', '</b>', '…', 32) AS snippet,
                           te.seq
                    FROM timeline_fts
                    JOIN timeline_events te ON te.seq = timeline_fts.rowid
                    WHERE timeline_fts MATCH ?
                      AND te.seq = (
                          SELECT MAX(te2.seq)
                          FROM timeline_events te2
                          WHERE te2.conversation_id = te.conversation_id
                            AND te2.seq IN (
                                SELECT rowid
                                FROM timeline_fts
                                WHERE timeline_fts MATCH ?
                            )
                      )
                    ORDER BY te.seq DESC
                    LIMIT ?
                    """,
                    (q, q, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"conversation_id": row["conversation_id"], "snippet": row["snippet"]} for row in rows]

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
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
                    "text": text,
                    "channel": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="User message",
                body=text,
                kind="channel_input",
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def add_conversation_action(self, conversation_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_payload = payload or {}
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
                    "action": action,
                    "payload": action_payload,
                    "channel": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            is_cancel = action == "cancel_conversation"
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="Cancel requested" if is_cancel else f"Action: {action}",
                body="" if is_cancel else json.dumps(action_payload) if action_payload else "",
                kind="control" if is_cancel else "channel_action",
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
