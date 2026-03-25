"""SQLite implementation of the central agent registry store."""

from __future__ import annotations

import hashlib
import json
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
from app.exact_aliases import matches_exact_alias
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    PROTECTED_ROUTED_TASK_STATUSES,
    delegation_event,
    routed_task_created_event,
    routed_task_progress_event,
    routed_task_result_event,
    stable_routed_task_id,
    validated_action_payload,
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
from octopus_sdk.registry.models import (
    CoordinationActionEnvelope,
    CoordinationActionResult,
    DelegationTaskDraft,
    DirectAssignActionPayload,
    TargetSelector,
)
from octopus_sdk.task_protocol import (
    RoutedTaskSnapshot,
    TaskTransitionRequest,
    apply_task_transition,
)

_SCHEMA_VERSION = 1

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
    bot_key TEXT NOT NULL DEFAULT '',
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_external
    ON conversations(target_agent_id, origin_channel, external_conversation_ref);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_bot_key
    ON agents(bot_key) WHERE bot_key != '';

CREATE TABLE IF NOT EXISTS skills_override (
    skill_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    set_by TEXT NOT NULL DEFAULT 'ui',
    set_at REAL NOT NULL
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
            _execute_sql_script(conn, _BASE_SCHEMA_SQL)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
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
        card = validated_agent_card_payload(requested_card, require_registry_scope=True)
        bot_key = str(card.get("bot_key", "") or "").strip()
        if not bot_key:
            raise ValueError("bot_key requires non-empty text")

        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn:
            # Idempotent re-enrollment: if bot_key already exists, refresh token and return existing row
            if bot_key:
                existing = conn.execute(
                    "SELECT agent_id, slug FROM agents WHERE bot_key = ?",
                    (bot_key,),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE agents SET agent_token = ?, updated_at = ? WHERE bot_key = ?",
                        (agent_token_hash, now, bot_key),
                    )
                    return {
                        "agent_id": existing["agent_id"],
                        "slug": existing["slug"],
                        "agent_token": agent_token,
                        "poll_cursor": "0",
                    }

            slug = self._ensure_unique_slug(conn, card.get("slug") or "agent")
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, agent_token, display_name, slug, role, registry_scope,
                    skills_json, tags_json, description, provider, mode,
                    connectivity_state, current_capacity, max_capacity,
                    channel_capabilities_json, version, bot_key,
                    created_at, updated_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    bot_key,
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
            requested_bot_key = str(card.get("bot_key", "") or "").strip()
            current_bot_key = str(row["bot_key"] or "").strip()
            if requested_bot_key and requested_bot_key != current_bot_key:
                raise ValueError("bot_key must match the enrolled agent identity")
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
            previous_effective_state = effective_connectivity_state(
                row["connectivity_state"],
                row["last_heartbeat_at"],
            )
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
            current_agent = self._row_to_agent(row)
            return {
                "agent": current_agent,
                "collections_changed": previous_effective_state != current_agent["connectivity_state"],
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

    def _selector_candidates(
        self,
        conn: sqlite3.Connection,
        selector: TargetSelector,
    ) -> list[sqlite3.Row]:
        rows = conn.execute(
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
            WHERE effective_state = 'connected'
            ORDER BY lower(display_name), agent_id
            """,
            (self._offline_before(),),
        ).fetchall()
        value = selector.value.strip().lower()
        matches: list[sqlite3.Row] = []
        for row in rows:
            if selector.kind == "agent":
                slug = str(row["slug"] or "").strip().lower()
                agent_id = str(row["agent_id"] or "").strip().lower()
                display_name = str(row["display_name"] or "")
                if matches_exact_alias(
                    value,
                    identifier=agent_id,
                    slug=slug,
                    display_name=display_name,
                ):
                    matches.append(row)
            elif selector.kind == "capability":
                caps = {str(item).strip().lower() for item in decode_json_field(row["skills_json"], []) if item}
                if value in caps:
                    matches.append(row)
            elif selector.kind == "role":
                role = str(row["role"] or "").strip().lower()
                if role == value or value in role:
                    matches.append(row)
        return matches

    def _resolve_selector(
        self,
        conn: sqlite3.Connection,
        selector: TargetSelector,
    ) -> sqlite3.Row:
        matches = self._selector_candidates(conn, selector)
        preferred = selector.preferred_agent_id.strip()
        if preferred:
            preferred_matches = [
                row for row in matches if str(row["agent_id"] or "").strip() == preferred
            ]
            if not preferred_matches:
                raise ValueError(
                    f"Selector {selector.kind}:{selector.value} does not resolve to preferred agent {preferred}"
                )
            return preferred_matches[0]
        if not matches:
            raise ValueError(f"No connected agent matches {selector.kind}:{selector.value}")
        if len(matches) > 1:
            labels = ", ".join(
                str(row["slug"] or row["agent_id"] or "").strip()
                for row in matches[:5]
            )
            raise ValueError(
                f"Selector {selector.kind}:{selector.value} is ambiguous across {len(matches)} agents: {labels}"
            )
        return matches[0]

    def _delegation_task_metadata(
        self,
        task: DelegationTaskDraft,
        *,
        status: str,
        target_agent_id: str = "",
        routed_task_id: str = "",
    ) -> dict[str, Any]:
        return {
            "draft_id": task.draft_id,
            "title": task.title,
            "target": target_agent_id or task.selector.preferred_agent_id or task.selector.value,
            "status": status,
            "routed_task_id": routed_task_id,
            "selector_kind": task.selector.kind,
            "selector_value": task.selector.value,
            "instructions": task.instructions,
            "priority": task.priority,
            "requested_capabilities": list(task.requested_capabilities),
            "context": dict(task.context),
        }

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: str,
        conversation_id: str,
        agent_id: str,
        kind: str,
        actor: str,
        content: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any] | None:
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
                actor,
                content,
                ensure_json(metadata),
                created_at,
            ),
        )
        if cursor.rowcount <= 0:
            return None
        seq_row = conn.execute(
            "SELECT seq FROM events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return {
            "seq": int(seq_row["seq"]) if seq_row is not None else 0,
            "event_id": event_id,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "kind": kind,
            "actor": actor,
            "content": content,
            "metadata": metadata,
            "created_at": created_at,
        }

    def _task_row_to_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "routed_task_id": row["routed_task_id"],
            "parent_conversation_id": row["parent_conversation_id"],
            "origin_agent_id": row["origin_agent_id"],
            "target_agent_id": row["target_agent_id"],
            "title": row["title"],
            "status": row["status"],
            "summary": row["summary"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _task_snapshot_from_row(row: sqlite3.Row) -> RoutedTaskSnapshot:
        return RoutedTaskSnapshot(
            status=str(row["status"] or "queued"),
            queued_at=str(row["created_at"] or ""),
            leased_at="",
            started_at="",
            completed_at="",
            failed_at="",
            cancelled_at="",
        )

    def _create_routed_task_in_tx(
        self,
        conn: sqlite3.Connection,
        request: dict[str, Any],
        *,
        now: str,
    ) -> dict[str, Any]:
        validated_request = validated_routed_task_request(request)
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
        mirrored_event = routed_task_created_event(validated_request)
        inserted_event = self._insert_event(
            conn,
            event_id=mirrored_event["event_id"],
            conversation_id=mirrored_event["conversation_id"],
            agent_id=validated_request["target_agent_id"],
            kind=mirrored_event["kind"],
            actor="",
            content=mirrored_event["content"],
            metadata=mirrored_event["metadata"],
            created_at=mirrored_event["created_at"],
        )
        if inserted_event is not None:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (mirrored_event["created_at"], mirrored_event["conversation_id"]),
            )
        return {
            "request": validated_request,
            "delivery": delivery,
            "event": inserted_event,
        }

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
            validated_request = validated_routed_task_request(request)
            conversation_row = conn.execute(
                "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
                (validated_request["parent_conversation_id"],),
            ).fetchone()
            if conversation_row is None:
                raise KeyError(validated_request["parent_conversation_id"])
            created = self._create_routed_task_in_tx(
                conn,
                validated_request,
                now=now,
            )
            delivery = created["delivery"]
            inserted_events = [created["event"]] if created.get("event") is not None else []
        return {
            "routed_task_id": validated_request["routed_task_id"],
            "delivery_id": delivery["delivery_id"],
            "events_written": bool(inserted_events),
            "inserted_events": inserted_events,
            "parent_conversation_id": validated_request["parent_conversation_id"],
            "origin_agent_id": validated_request["origin_agent_id"],
            "target_agent_id": validated_request["target_agent_id"],
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
                for item in deliveries:
                    if item["kind"] != "routed_task":
                        continue
                    payload = decode_json_field(item["payload_json"], {})
                    routed_task_id = str(payload.get("routed_task_id") or "").strip()
                    if not routed_task_id:
                        continue
                    task_row = conn.execute(
                        "SELECT * FROM routed_tasks WHERE routed_task_id = ?",
                        (routed_task_id,),
                    ).fetchone()
                    if task_row is None:
                        continue
                    decision = apply_task_transition(
                        self._task_snapshot_from_row(task_row),
                        TaskTransitionRequest(
                            transition="lease",
                            actor_role="system",
                            transition_id=item["delivery_id"],
                            occurred_at=now,
                        ),
                    )
                    if decision.ok and not decision.duplicate and decision.new_state != task_row["status"]:
                        conn.execute(
                            "UPDATE routed_tasks SET status = ?, updated_at = ? WHERE routed_task_id = ?",
                            (decision.new_state, now, routed_task_id),
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
        validated_payload = validated_routed_task_status_payload(payload)
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, {"coordination", "full"})
            task_row = conn.execute(
                "SELECT * FROM routed_tasks WHERE routed_task_id = ?",
                (routed_task_id,),
            ).fetchone()
            if task_row is None:
                raise KeyError(routed_task_id)
            if str(task_row["target_agent_id"] or "") != str(row["agent_id"] or ""):
                raise PermissionError("Routed task does not belong to this agent")
            occurred_at = now
            requested_status = validated_payload["status"]
            if requested_status == "running":
                transition = "progress" if str(task_row["status"] or "") == "running" else "start"
            elif requested_status == "failed":
                transition = "fail"
            elif requested_status == "timed_out":
                transition = "time_out"
            elif requested_status == "cancelled":
                transition = "cancel"
            elif requested_status == "leased":
                transition = "lease"
            else:
                raise ValueError(f"Unsupported routed task status: {requested_status}")

            decision = apply_task_transition(
                self._task_snapshot_from_row(task_row),
                TaskTransitionRequest(
                    transition=transition,
                    actor_role="target_bot",
                    transition_id=validated_payload["transition_id"],
                    occurred_at=occurred_at,
                    progress=validated_payload.get("progress"),
                ),
            )
            if not decision.ok:
                raise ValueError(decision.reason or f"Task {routed_task_id} cannot transition to {requested_status}")

            duplicate = False
            inserted_events: list[dict[str, Any]] = []
            primary_event_id = f"task-transition:{routed_task_id}:{validated_payload['transition_id']}"
            if conn.execute(
                "SELECT 1 FROM events WHERE event_id = ?",
                (primary_event_id,),
            ).fetchone():
                duplicate = True
            else:
                conn.execute(
                    "UPDATE routed_tasks SET status = ?, summary = ?, updated_at = ? WHERE routed_task_id = ?",
                    (
                        decision.new_state,
                        validated_payload["summary"],
                        occurred_at,
                        routed_task_id,
                    ),
                )
                primary_event = self._insert_event(
                    conn,
                    event_id=primary_event_id,
                    conversation_id=str(task_row["parent_conversation_id"] or ""),
                    agent_id=str(row["agent_id"] or ""),
                    kind="task.status",
                    actor="",
                    content=str(validated_payload.get("summary") or decision.new_state),
                    metadata={
                        "routed_task_id": routed_task_id,
                        "status": decision.new_state,
                        "transition_id": validated_payload["transition_id"],
                        **(
                            {"progress": validated_payload["progress"]}
                            if validated_payload.get("progress") is not None
                            else {}
                        ),
                    },
                    created_at=occurred_at,
                )
                if primary_event is not None:
                    inserted_events.append(primary_event)
                for event in validated_payload["timeline_events"]:
                    event_metadata = {
                        "routed_task_id": routed_task_id,
                        "status": decision.new_state,
                        "transition_id": validated_payload["transition_id"],
                        **dict(event.get("metadata") or {}),
                    }
                    if event.get("progress") is not None:
                        event_metadata["progress"] = event["progress"]
                    inserted_event = self._insert_event(
                        conn,
                        event_id=str(event["event_id"]),
                        conversation_id=str(event["conversation_id"]),
                        agent_id=str(row["agent_id"] or ""),
                        kind="task.status",
                        actor="",
                        content=str(event.get("body", "") or event.get("title", "") or ""),
                        metadata=event_metadata,
                        created_at=str(event["created_at"]),
                    )
                    if inserted_event is not None:
                        inserted_events.append(inserted_event)
                if inserted_events:
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                        (inserted_events[-1]["created_at"], task_row["parent_conversation_id"]),
                    )
            return {
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "duplicate": duplicate,
                "events_written": bool(inserted_events),
                "inserted_events": inserted_events,
                "parent_conversation_id": task_row["parent_conversation_id"],
                "origin_agent_id": task_row["origin_agent_id"],
                "target_agent_id": task_row["target_agent_id"],
            }

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
            if str(task["target_agent_id"] or "") != str(row["agent_id"] or ""):
                raise PermissionError("Routed task does not belong to this agent")
            requested_status = validated_payload["status"]
            if requested_status == "completed":
                transition = "complete"
            elif requested_status == "failed":
                transition = "fail"
            elif requested_status == "timed_out":
                transition = "time_out"
            else:
                raise ValueError(f"Unsupported routed task result status: {requested_status}")
            completed_at = now
            decision = apply_task_transition(
                self._task_snapshot_from_row(task),
                TaskTransitionRequest(
                    transition=transition,
                    actor_role="target_bot",
                    transition_id=validated_payload["transition_id"],
                    occurred_at=completed_at,
                ),
            )
            if not decision.ok:
                raise ValueError(decision.reason or f"Task {routed_task_id} cannot transition to {requested_status}")
            primary_event_id = f"task-result:{routed_task_id}:{validated_payload['transition_id']}"
            duplicate = conn.execute(
                "SELECT 1 FROM events WHERE event_id = ?",
                (primary_event_id,),
            ).fetchone() is not None
            parent_conversation = conn.execute(
                "SELECT external_conversation_ref FROM conversations WHERE conversation_id = ?",
                (task["parent_conversation_id"],),
            ).fetchone()
            inserted_events: list[dict[str, Any]] = []
            if not duplicate:
                persisted_result = dict(validated_payload)
                persisted_result["completed_at"] = completed_at
                persisted_result["status"] = decision.new_state
                conn.execute(
                    """
                    UPDATE routed_tasks
                    SET status = ?, summary = ?, result_json = ?, updated_at = ?
                    WHERE routed_task_id = ?
                    """,
                    (
                        decision.new_state,
                        validated_payload["summary"],
                        ensure_json(persisted_result),
                        completed_at,
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
                        "parent_external_conversation_ref": (
                            str(parent_conversation["external_conversation_ref"] or "")
                            if parent_conversation is not None
                            else ""
                        ),
                        "result": persisted_result,
                    },
                    now=completed_at,
                    delivery_id=uuid.uuid4().hex,
                )
                mirrored_event = self._insert_event(
                    conn,
                    event_id=primary_event_id,
                    conversation_id=str(task["parent_conversation_id"] or ""),
                    agent_id=str(row["agent_id"] or ""),
                    kind="task.status",
                    actor="",
                    content=str(
                        validated_payload.get("summary")
                        or validated_payload.get("full_text")
                        or decision.new_state
                    ),
                    metadata={
                        "routed_task_id": routed_task_id,
                        "status": decision.new_state,
                        "transition_id": validated_payload["transition_id"],
                    },
                    created_at=completed_at,
                )
                if mirrored_event is not None:
                    inserted_events.append(mirrored_event)
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                        (completed_at, task["parent_conversation_id"]),
                    )
            return {
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "duplicate": duplicate,
                "events_written": bool(inserted_events),
                "inserted_events": inserted_events,
                "parent_conversation_id": task["parent_conversation_id"],
                "origin_agent_id": task["origin_agent_id"],
                "target_agent_id": task["target_agent_id"],
            }

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

    def list_agents(
        self,
        *,
        for_agent_id: str | None = None,
        cursor: int = 0,
        limit: int = 25,
        q: str = "",
        connectivity_state: str = "",
    ) -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        with self._connect() as conn:
            if q or connectivity_state:
                rows = conn.execute("SELECT * FROM agents ORDER BY lower(display_name)").fetchall()
                agents = [self._row_to_agent(row) for row in rows]
                if for_agent_id is not None:
                    agents = [agent for agent in agents if agent["agent_id"] == for_agent_id]
                q_lower = q.strip().lower()
                if q_lower:
                    agents = [
                        agent for agent in agents
                        if q_lower in (agent["display_name"] or "").lower()
                        or q_lower in (agent["slug"] or "").lower()
                        or q_lower in (agent["role"] or "").lower()
                        or q_lower in (agent["provider"] or "").lower()
                    ]
                if connectivity_state:
                    agents = [
                        agent for agent in agents
                        if (agent["connectivity_state"] or "") == connectivity_state
                    ]
                return agents[cursor: cursor + fetch_limit]
            if for_agent_id is not None:
                rows = conn.execute(
                    "SELECT * FROM agents WHERE agent_id = ? ORDER BY lower(display_name) LIMIT ? OFFSET ?",
                    (for_agent_id, fetch_limit, cursor),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agents ORDER BY lower(display_name) LIMIT ? OFFSET ?",
                    (fetch_limit, cursor),
                ).fetchall()
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

    def agent_exists(self, agent_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return row is not None

    def create_conversation(
        self,
        *,
        target_agent_id: str,
        title: str,
        origin_channel: str = "registry",
        external_conversation_ref: str = "",
    ) -> dict[str, Any]:
        if not origin_channel or not origin_channel.strip():
            raise ValueError("origin_channel must not be empty")
        if not external_conversation_ref or not external_conversation_ref.strip():
            raise ValueError("external_conversation_ref must not be empty")
        now = utcnow_iso()

        # Look up bot_key for the target agent to compute deterministic conversation_id
        with self._connect() as conn:
            agent_row = conn.execute(
                "SELECT bot_key FROM agents WHERE agent_id = ?",
                (target_agent_id,),
            ).fetchone()
            bot_key = ""
            if agent_row is not None:
                bot_key = str(agent_row["bot_key"] or "").strip()
            if not bot_key:
                raise ValueError(f"Unknown agent or missing bot_key: {target_agent_id}")
            canonical = f"{bot_key}:{origin_channel}:{external_conversation_ref}"
            conversation_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]

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

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "") -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        # When a search query is provided (>= 3 chars), use FTS-based search
        if q and len(q) >= 3:
            search_hits = self.search_conversations(q, limit=fetch_limit + cursor)
            hit_ids = [h["conversation_id"] for h in search_hits]
            if not hit_ids:
                return []
            # Now fetch full conversation rows for those IDs
            with self._connect() as conn:
                placeholders = ",".join("?" * len(hit_ids))
                where_clauses = [f"c.conversation_id IN ({placeholders})"]
                params: list[Any] = list(hit_ids)
                if for_agent_id is not None:
                    where_clauses.append("c.target_agent_id = ?")
                    params.append(for_agent_id)
                if status:
                    where_clauses.append("c.status = ?")
                    params.append(status)
                where_sql = " WHERE " + " AND ".join(where_clauses)
                sql = f"""
                    SELECT
                        c.*,
                        a.display_name AS target_name,
                        COUNT(e.event_id) AS event_count
                    FROM conversations c
                    LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                    LEFT JOIN events e ON e.conversation_id = c.conversation_id
                    {where_sql}
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
                    ORDER BY c.updated_at DESC
                    LIMIT ? OFFSET ?
                """
                params.extend([fetch_limit, cursor])
                rows = conn.execute(sql, params).fetchall()
        else:
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
                params_list: list[Any] = []
                where_clauses_list: list[str] = []
                if for_agent_id is not None:
                    where_clauses_list.append("c.target_agent_id = ?")
                    params_list.append(for_agent_id)
                if status:
                    where_clauses_list.append("c.status = ?")
                    params_list.append(status)
                if where_clauses_list:
                    sql += " WHERE " + " AND ".join(where_clauses_list)
                sql += """
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
                    ORDER BY c.updated_at DESC
                    LIMIT ? OFFSET ?
                """
                params_list.extend([fetch_limit, cursor])
                rows = conn.execute(sql, params_list).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "origin_channel": row["origin_channel"],
                "external_conversation_ref": row["external_conversation_ref"],
                "event_count": int(row["event_count"] or 0),
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
                GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
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
            "origin_channel": row["origin_channel"],
            "external_conversation_ref": row["external_conversation_ref"],
            "event_count": int(row["event_count"] or 0),
            "linked_routed_tasks": tasks,
        }

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            if until_iso:
                rows = conn.execute(
                    """
                    SELECT conversation_id, metadata_json, created_at
                    FROM events
                    WHERE kind = 'provider.response' AND created_at >= ? AND created_at <= ?
                    ORDER BY created_at
                    """,
                    (since_iso, until_iso),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT conversation_id, metadata_json, created_at
                    FROM events
                    WHERE kind = 'provider.response' AND created_at >= ?
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

    def get_summary(self, *, now_iso: str) -> dict[str, Any]:
        window_start = (
            datetime.fromisoformat(now_iso) - timedelta(hours=24)
        ).isoformat()
        with self._connect() as conn:
            agent_rows = conn.execute(
                "SELECT connectivity_state, last_heartbeat_at FROM agents"
            ).fetchall()
            conversation_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('open', 'running', 'cancelling') THEN 1 ELSE 0 END) AS active
                FROM conversations
                """
            ).fetchone()
            pending_approvals_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM conversations c
                WHERE EXISTS (
                    SELECT 1
                    FROM events e
                    WHERE e.conversation_id = c.conversation_id
                      AND e.kind = 'approval.requested'
                      AND e.seq = (
                          SELECT MAX(e2.seq)
                          FROM events e2
                          WHERE e2.conversation_id = c.conversation_id
                            AND e2.kind IN ('approval.requested', 'approval.decided')
                      )
                )
                """
            ).fetchone()
            task_totals = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                    SUM(CASE WHEN status IN ('queued', 'leased', 'submitted') THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'failed' AND updated_at >= ? THEN 1 ELSE 0 END) AS failed_24h
                FROM routed_tasks
                """,
                (window_start,),
            ).fetchone()
        connected = 0
        degraded = 0
        disconnected = 0
        for row in agent_rows:
            state = effective_connectivity_state(row["connectivity_state"], row["last_heartbeat_at"])
            if state == "connected":
                connected += 1
            elif state == "degraded":
                degraded += 1
            else:
                disconnected += 1
        usage_rows = self.get_usage_summary(window_start, until_iso=now_iso)
        usage_total = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
        }
        for row in usage_rows:
            metadata = row.get("metadata") or {}
            usage_total["prompt_tokens"] += int(metadata.get("prompt_tokens") or 0)
            usage_total["completion_tokens"] += int(metadata.get("completion_tokens") or 0)
            usage_total["cost_usd"] += float(metadata.get("cost_usd") or 0.0)
        return {
            "generated_at": now_iso,
            "agents": {
                "total": len(agent_rows),
                "connected": connected,
                "degraded": degraded,
                "disconnected": disconnected,
            },
            "conversations": {
                "total": int(conversation_totals["total"] or 0),
                "active": int(conversation_totals["active"] or 0),
                "pending_approvals": int(pending_approvals_row["cnt"] or 0),
            },
            "tasks": {
                "running": int(task_totals["running"] or 0),
                "pending": int(task_totals["pending"] or 0),
                "failed_24h": int(task_totals["failed_24h"] or 0),
            },
            "usage_24h": usage_total,
        }

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        with self._connect() as conn:
            sql = """
                SELECT
                    e.event_id,
                    e.conversation_id,
                    e.actor,
                    e.content,
                    e.metadata_json,
                    e.created_at,
                    c.title,
                    c.status AS conversation_status,
                    c.updated_at AS conversation_updated_at,
                    c.target_agent_id,
                    a.display_name AS target_name
                FROM events e
                JOIN conversations c ON c.conversation_id = e.conversation_id
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                WHERE e.kind = 'approval.requested'
                  AND e.seq = (
                      SELECT MAX(e2.seq)
                      FROM events e2
                      WHERE e2.conversation_id = e.conversation_id
                        AND e2.kind IN ('approval.requested', 'approval.decided')
                  )
            """
            params: list[Any] = []
            if for_agent_id is not None:
                sql += " AND c.target_agent_id = ?"
                params.append(for_agent_id)
            sql += """
                ORDER BY e.created_at DESC
                LIMIT ? OFFSET ?
            """
            params.extend([fetch_limit, cursor])
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "request_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "conversation_title": row["title"],
                "conversation_status": row["conversation_status"],
                "conversation_updated_at": row["conversation_updated_at"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "actor": row["actor"],
                "content": row["content"],
                "created_at": row["created_at"],
                **decode_json_field(row["metadata_json"], {}),
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
                "SELECT target_agent_id, title, origin_channel, external_conversation_ref FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            agent_row = conn.execute(
                "SELECT bot_key FROM agents WHERE agent_id = ?",
                (conversation["target_agent_id"],),
            ).fetchone()
            bot_key = ""
            if agent_row is not None:
                bot_key = str(agent_row["bot_key"] or "").strip()
            if not bot_key:
                raise ValueError(
                    f"Unknown agent or missing bot_key: {conversation['target_agent_id']}"
                )
            now = utcnow_iso()
            event_id = uuid.uuid4().hex
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="channel_input",
                payload={
                    "conversation_id": conversation_id,
                    "title": conversation["title"],
                    "text": validated_text,
                    "channel": "registry",
                    "bot_key": bot_key,
                    "origin_channel": conversation["origin_channel"],
                    "external_conversation_ref": conversation["external_conversation_ref"],
                    "stable_event_id": event_id,
                    "stable_created_at": now,
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            conn.execute(
                """INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING""",
                (event_id, conversation_id, "", "message.user", "operator", validated_text, "{}", now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (now, conversation_id),
            )
            inserted_event_row = conn.execute(
                "SELECT * FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
            inserted_event = None
            if inserted_event_row:
                inserted_event = {
                    "seq": inserted_event_row["seq"],
                    "event_id": inserted_event_row["event_id"],
                    "conversation_id": inserted_event_row["conversation_id"],
                    "agent_id": inserted_event_row["agent_id"],
                    "kind": inserted_event_row["kind"],
                    "actor": inserted_event_row["actor"],
                    "content": inserted_event_row["content"],
                    "metadata": decode_json_field(inserted_event_row["metadata_json"], {}),
                    "created_at": inserted_event_row["created_at"],
                }
        return {"conversation_id": conversation_id, "accepted": True, "event": inserted_event}

    def add_conversation_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope | dict[str, Any],
    ) -> dict[str, Any]:
        validated_envelope = validated_conversation_action(envelope)
        action_payload = validated_action_payload(validated_envelope)
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT target_agent_id, origin_channel, external_conversation_ref, title FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            inserted_event = None
            routed_tasks: list[dict[str, Any]] = []
            duplicate = False

            def _event_from_row(event_id: str) -> dict[str, Any] | None:
                row = conn.execute(
                    "SELECT * FROM events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if row is None:
                    return None
                return {
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

            if validated_envelope.action in {"approve", "reject", "retry_allow", "retry_skip", "recovery_discard", "recovery_replay", "cancel_conversation"}:
                agent_row = conn.execute(
                    "SELECT bot_key FROM agents WHERE agent_id = ?",
                    (conversation["target_agent_id"],),
                ).fetchone()
                bot_key = str(agent_row["bot_key"] or "").strip() if agent_row is not None else ""
                if not bot_key:
                    raise ValueError(
                        f"Unknown agent or missing bot_key: {conversation['target_agent_id']}"
                    )
                self._create_delivery(
                    conn,
                    target_agent_id=conversation["target_agent_id"],
                    kind="channel_action",
                    payload={
                        "conversation_id": conversation_id,
                        "conversation_ref": conversation_id,
                        "action": validated_envelope.action,
                        "payload": {} if action_payload is None else action_payload.model_dump(exclude_unset=True),
                        "channel": "registry",
                        "bot_key": bot_key,
                        "origin_channel": conversation["origin_channel"],
                        "external_conversation_ref": conversation["external_conversation_ref"],
                        "stable_event_id": validated_envelope.action_id,
                        "stable_created_at": now,
                    },
                    now=now,
                    delivery_id=uuid.uuid4().hex,
                )
                if validated_envelope.action == "cancel_conversation":
                    inserted_event = self._insert_event(
                        conn,
                        event_id=validated_envelope.action_id,
                        conversation_id=conversation_id,
                        agent_id="",
                        kind="task.status",
                        actor="operator",
                        content="",
                        metadata={"routed_task_id": "", "status": "cancelling"},
                        created_at=now,
                    )
                    conn.execute(
                        "UPDATE conversations SET updated_at = ?, status = ? WHERE conversation_id = ?",
                        (now, "cancelling", conversation_id),
                    )
                else:
                    inserted_event = self._insert_event(
                        conn,
                        event_id=validated_envelope.action_id,
                        conversation_id=conversation_id,
                        agent_id="",
                        kind="approval.decided",
                        actor="operator",
                        content=json.dumps(action_payload.model_dump(exclude_unset=True)),
                        metadata={
                            "action": validated_envelope.action,
                            "decided_by": "operator",
                            "decision": "rejected" if validated_envelope.action in {"reject", "retry_skip", "recovery_discard"} else "approved",
                        },
                        created_at=now,
                    )
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                        (now, conversation_id),
                    )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event_from_row(validated_envelope.action_id)
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    event=inserted_event,
                ).model_dump()

            if validated_envelope.action == "delegate_tasks":
                proposal = action_payload
                task_entries = [
                    self._delegation_task_metadata(task, status="proposed")
                    for task in proposal.tasks
                ]
                delegation_evt = delegation_event(
                    kind="delegation.proposed",
                    proposal_id=validated_envelope.action_id,
                    conversation_id=conversation_id,
                    tasks=task_entries,
                    created_at=now,
                    content=proposal.title or "Delegation proposal",
                )
                inserted_event = self._insert_event(
                    conn,
                    event_id=delegation_evt["event_id"],
                    conversation_id=conversation_id,
                    agent_id="",
                    kind=delegation_evt["kind"],
                    actor="operator",
                    content=delegation_evt["content"],
                    metadata=delegation_evt["metadata"],
                    created_at=delegation_evt["created_at"],
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (now, conversation_id),
                )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event_from_row(delegation_evt["event_id"])
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=validated_envelope.action_id,
                    event=inserted_event,
                ).model_dump()

            if validated_envelope.action == "approve_delegation":
                proposal_id = action_payload.proposal_id
                proposal_row = conn.execute(
                    "SELECT * FROM events WHERE conversation_id = ? AND kind = ? AND json_extract(metadata_json, '$.proposal_id') = ? ORDER BY seq DESC LIMIT 1",
                    (conversation_id, "delegation.proposed", proposal_id),
                ).fetchone()
                if proposal_row is None:
                    raise ValueError(f"Unknown delegation proposal: {proposal_id}")
                proposal_metadata = decode_json_field(proposal_row["metadata_json"], {})
                task_entries = list(proposal_metadata.get("tasks", []))
                if not task_entries:
                    raise ValueError(f"Delegation proposal {proposal_id} has no tasks")
                for index, entry in enumerate(task_entries):
                    draft = DelegationTaskDraft.model_validate(
                        {
                            "draft_id": entry.get("draft_id", f"draft-{index + 1}"),
                            "selector": {
                                "kind": entry.get("selector_kind", "agent"),
                                "value": entry.get("selector_value", entry.get("target", "")),
                                "preferred_agent_id": entry.get("target", ""),
                            },
                            "title": entry.get("title", ""),
                            "instructions": entry.get("instructions", ""),
                            "priority": entry.get("priority", "normal"),
                            "requested_capabilities": entry.get("requested_capabilities", []),
                            "context": entry.get("context", {}),
                        }
                    )
                    resolved_target = self._resolve_selector(conn, draft.selector)
                    request = {
                        "routed_task_id": stable_routed_task_id(conversation_id, validated_envelope.action_id, index),
                        "parent_conversation_id": conversation_id,
                        "origin_agent_id": conversation["target_agent_id"],
                        "target_agent_id": resolved_target["agent_id"],
                        "title": draft.title,
                        "instructions": draft.instructions,
                        "context": dict(draft.context),
                        "requested_capabilities": list(draft.requested_capabilities),
                        "priority": draft.priority,
                        "created_at": now,
                    }
                    created = self._create_routed_task_in_tx(conn, request, now=now)
                    routed_tasks.append({
                        "routed_task_id": request["routed_task_id"],
                        "target_agent_id": resolved_target["agent_id"],
                        "authority_ref": "",
                        "title": draft.title,
                        "status": "queued",
                    })
                submitted_event = delegation_event(
                    kind="delegation.submitted",
                    proposal_id=proposal_id,
                    conversation_id=conversation_id,
                    tasks=[
                        {
                            **entry,
                            "status": "submitted",
                            "routed_task_id": routed_tasks[index]["routed_task_id"],
                            "target": routed_tasks[index]["target_agent_id"],
                        }
                        for index, entry in enumerate(task_entries)
                    ],
                    created_at=now,
                    content="Delegated work submitted",
                )
                inserted_event = self._insert_event(
                    conn,
                    event_id=f"delegation.submitted:{validated_envelope.action_id}",
                    conversation_id=conversation_id,
                    agent_id="",
                    kind=submitted_event["kind"],
                    actor="operator",
                    content=submitted_event["content"],
                    metadata=submitted_event["metadata"],
                    created_at=submitted_event["created_at"],
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (now, conversation_id),
                )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event_from_row(f"delegation.submitted:{validated_envelope.action_id}")
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=proposal_id,
                    routed_tasks=routed_tasks,
                    event=inserted_event,
                ).model_dump()

            if validated_envelope.action == "direct_assign":
                assignment = action_payload
                resolved_target = self._resolve_selector(conn, assignment.selector)
                request = {
                    "routed_task_id": stable_routed_task_id(conversation_id, validated_envelope.action_id, 0),
                    "parent_conversation_id": conversation_id,
                    "origin_agent_id": conversation["target_agent_id"],
                    "target_agent_id": resolved_target["agent_id"],
                    "title": assignment.title,
                    "instructions": assignment.instructions,
                    "context": dict(assignment.context),
                    "requested_capabilities": list(assignment.requested_capabilities),
                    "priority": assignment.priority,
                    "created_at": now,
                }
                created = self._create_routed_task_in_tx(conn, request, now=now)
                routed_tasks.append({
                    "routed_task_id": request["routed_task_id"],
                    "target_agent_id": resolved_target["agent_id"],
                    "authority_ref": "",
                    "title": assignment.title,
                    "status": "queued",
                })
                submitted_event = delegation_event(
                    kind="delegation.submitted",
                    proposal_id=validated_envelope.action_id,
                    conversation_id=conversation_id,
                    tasks=[
                        {
                            "draft_id": validated_envelope.action_id,
                            "title": assignment.title,
                            "target": resolved_target["agent_id"],
                            "status": "submitted",
                            "routed_task_id": request["routed_task_id"],
                            "selector_kind": assignment.selector.kind,
                            "selector_value": assignment.selector.value,
                            "instructions": assignment.instructions,
                            "priority": assignment.priority,
                            "requested_capabilities": list(assignment.requested_capabilities),
                            "context": dict(assignment.context),
                        }
                    ],
                    created_at=now,
                    content="Direct assignment submitted",
                )
                inserted_event = self._insert_event(
                    conn,
                    event_id=f"delegation.submitted:{validated_envelope.action_id}",
                    conversation_id=conversation_id,
                    agent_id="",
                    kind=submitted_event["kind"],
                    actor="operator",
                    content=submitted_event["content"],
                    metadata=submitted_event["metadata"],
                    created_at=submitted_event["created_at"],
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (now, conversation_id),
                )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event_from_row(f"delegation.submitted:{validated_envelope.action_id}")
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=validated_envelope.action_id,
                    routed_tasks=routed_tasks,
                    event=inserted_event,
                ).model_dump()

            if validated_envelope.action in {"cancel_task", "retry_task", "cancel_delegation"}:
                if validated_envelope.action == "cancel_delegation":
                    inserted_event = self._insert_event(
                        conn,
                        event_id=validated_envelope.action_id,
                        conversation_id=conversation_id,
                        agent_id="",
                        kind="approval.decided",
                        actor="operator",
                        content="",
                        metadata={
                            "action": validated_envelope.action,
                            "decided_by": "operator",
                            "decision": "rejected",
                        },
                        created_at=now,
                    )
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                        (now, conversation_id),
                    )
                    duplicate = inserted_event is None
                    if inserted_event is None:
                        inserted_event = _event_from_row(validated_envelope.action_id)
                    return CoordinationActionResult(
                        conversation_id=conversation_id,
                        action_id=validated_envelope.action_id,
                        action=validated_envelope.action,
                        accepted=True,
                        duplicate=duplicate,
                        proposal_id=action_payload.proposal_id,
                        event=inserted_event,
                    ).model_dump()

                routed_task_id = action_payload.routed_task_id
                task_row = conn.execute(
                    "SELECT * FROM routed_tasks WHERE routed_task_id = ? AND parent_conversation_id = ?",
                    (routed_task_id, conversation_id),
                ).fetchone()
                if task_row is None:
                    raise ValueError(f"Unknown task {routed_task_id} for conversation {conversation_id}")
                if validated_envelope.action == "retry_task":
                    request = decode_json_field(task_row["request_json"], {})
                    request["routed_task_id"] = stable_routed_task_id(conversation_id, validated_envelope.action_id, 0)
                    request["created_at"] = now
                    request["parent_conversation_id"] = conversation_id
                    created = self._create_routed_task_in_tx(conn, request, now=now)
                    routed_tasks.append({
                        "routed_task_id": request["routed_task_id"],
                        "target_agent_id": request["target_agent_id"],
                        "authority_ref": "",
                        "title": request["title"],
                        "status": "queued",
                    })
                    inserted_event = created.get("event")
                else:
                    snapshot = RoutedTaskSnapshot(
                        status=str(task_row["status"] or "queued"),
                    )
                    decision = apply_task_transition(
                        snapshot,
                        TaskTransitionRequest(
                            transition="cancel",
                            actor_role="operator",
                            transition_id=validated_envelope.action_id,
                            occurred_at=now,
                        ),
                    )
                    if not decision.ok:
                        raise ValueError(decision.reason or f"Task {routed_task_id} cannot be cancelled")
                    conn.execute(
                        "UPDATE routed_tasks SET status = ?, summary = ?, updated_at = ? WHERE routed_task_id = ?",
                        ("cancelled", "Cancelled by operator.", now, routed_task_id),
                    )
                    inserted_event = self._insert_event(
                        conn,
                        event_id=validated_envelope.action_id,
                        conversation_id=conversation_id,
                        agent_id="",
                        kind="task.status",
                        actor="operator",
                        content="Cancelled by operator.",
                        metadata={
                            "routed_task_id": routed_task_id,
                            "status": "cancelled",
                            "transition_id": validated_envelope.action_id,
                        },
                        created_at=now,
                    )
                    routed_tasks.append({
                        "routed_task_id": routed_task_id,
                        "target_agent_id": str(task_row["target_agent_id"] or ""),
                        "authority_ref": "",
                        "title": str(task_row["title"] or ""),
                        "status": "cancelled",
                    })
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (now, conversation_id),
                )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event_from_row(validated_envelope.action_id)
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    routed_tasks=routed_tasks,
                    event=inserted_event,
                ).model_dump()

            raise ValueError(f"Unsupported action: {validated_envelope.action}")

    def list_tasks(
        self,
        *,
        for_agent_id: str | None = None,
        parent_conversation_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
    ) -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        with self._connect() as conn:
            sql = """
                SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                FROM routed_tasks t
                LEFT JOIN agents origin ON origin.agent_id = t.origin_agent_id
                LEFT JOIN agents target ON target.agent_id = t.target_agent_id
            """
            params: list[Any] = []
            where_clauses: list[str] = []
            if for_agent_id is not None:
                where_clauses.append("(t.origin_agent_id = ? OR t.target_agent_id = ?)")
                params.extend([for_agent_id, for_agent_id])
            if parent_conversation_id:
                where_clauses.append("t.parent_conversation_id = ?")
                params.append(parent_conversation_id)
            if status:
                where_clauses.append("t.status = ?")
                params.append(status)
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            sql += " ORDER BY t.updated_at DESC LIMIT ? OFFSET ?"
            params.extend([fetch_limit, cursor])
            rows = conn.execute(sql, params).fetchall()
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
                "instructions": decode_json_field(row["request_json"], {}).get("instructions", ""),
                "result_summary": decode_json_field(row["result_json"], {}).get("summary", ""),
                "result_text": decode_json_field(row["result_json"], {}).get("full_text", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_task(self, routed_task_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                FROM routed_tasks t
                LEFT JOIN agents origin ON origin.agent_id = t.origin_agent_id
                LEFT JOIN agents target ON target.agent_id = t.target_agent_id
                WHERE t.routed_task_id = ?
                """,
                (routed_task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(routed_task_id)
        return {
            "routed_task_id": row["routed_task_id"],
            "parent_conversation_id": row["parent_conversation_id"],
            "origin_agent_id": row["origin_agent_id"],
            "origin_display_name": row["origin_name"] or "",
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "title": row["title"],
            "status": row["status"],
            "summary": row["summary"],
            "request": decode_json_field(row["request_json"], {}),
            "result": decode_json_field(row["result_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

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
            inserted_ids: set[str] = set()
            inserted_events: list[dict[str, Any]] = []
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
                    inserted_ids.add(event_id)
                    row = conn.execute(
                        "SELECT seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at FROM events WHERE event_id = ?",
                        (event_id,),
                    ).fetchone()
                    if row:
                        inserted_events.append({
                            "seq": row["seq"],
                            "event_id": row["event_id"],
                            "conversation_id": row["conversation_id"],
                            "agent_id": row["agent_id"],
                            "kind": row["kind"],
                            "actor": row["actor"],
                            "content": row["content"],
                            "metadata": decode_json_field(row["metadata_json"], {}),
                            "created_at": row["created_at"],
                        })
                else:
                    skipped += 1
        return {"inserted": inserted, "skipped": skipped, "inserted_ids": list(inserted_ids), "inserted_events": inserted_events}

    def list_events(
        self,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        if before_seq and after_seq:
            raise ValueError("before_seq and after_seq cannot both be set")
        kinds = [item.strip() for item in kind.split(",") if item.strip()]
        where_clauses = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            where_clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        if before_seq:
            where_clauses.append("seq < ?")
            params.append(before_seq)
            order_sql = "ORDER BY seq DESC"
        elif after_seq:
            where_clauses.append("seq > ?")
            params.append(after_seq)
            order_sql = "ORDER BY seq ASC"
        else:
            order_sql = "ORDER BY seq DESC"
        query = f"""
            SELECT * FROM events
            WHERE {' AND '.join(where_clauses)}
            {order_sql}
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, (*params, limit + 1)).fetchall()
        has_more_before = False
        if before_seq or not after_seq:
            has_more_before = len(rows) > limit
            if has_more_before:
                rows = rows[:limit]
            rows = list(reversed(rows))
        else:
            if len(rows) > limit:
                rows = rows[:limit]
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
        return {
            "events": events_list,
            "has_more_before": has_more_before,
            "next_before_seq": events_list[0]["seq"] if has_more_before and events_list else None,
            "next_after_seq": events_list[-1]["seq"] if events_list else None,
        }

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
        fetch_limit = limit + 1
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
                (effective_agent_id, fetch_limit, cursor),
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
            sql = "SELECT * FROM events WHERE kind = 'provider.response'"
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
