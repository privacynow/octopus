"""Postgres-backed registry store."""

from __future__ import annotations

import json
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agents.types import TimelineEvent
from app.capability_service import (
    declared_capabilities,
    query_capabilities,
    requested_routed_capabilities,
)
from app.db.postgres import get_connection
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    conversation_status_for_event,
    decode_json_field,
    effective_connectivity_state,
    runtime_health_detail,
    runtime_health_generated_at,
    runtime_health_summary,
    utcnow_iso,
)

_SCHEMA = "agent_registry"


@contextmanager
def _cur(conn):
    cur = conn.cursor(row_factory=dict_row)
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def _write_tx(conn):
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value)


class RegistryPostgresStore(AbstractRegistryStore):
    """Postgres-backed implementation of the registry store contract."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._verify_schema()

    def _connect(self):
        return get_connection(self.database_url)

    def _verify_schema(self) -> None:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute("SELECT to_regclass(%s) AS table_name", (f"{_SCHEMA}.agents",))
                row = cur.fetchone()
                if row is None or row["table_name"] is None:
                    raise RuntimeError(
                        "agent_registry schema not found. Run DB bootstrap or DB update to apply 0004_registry.sql."
                    )

    def _offline_before(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    def _token_row(self, conn, token: str) -> dict[str, Any] | None:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT * FROM {_SCHEMA}.agents WHERE agent_token = %s",
                (token,),
            )
            return cur.fetchone()

    def _ensure_unique_slug(self, conn, requested: str) -> str:
        slug = requested
        suffix = 2
        with _cur(conn) as cur:
            while True:
                cur.execute(
                    f"SELECT 1 FROM {_SCHEMA}.agents WHERE slug = %s",
                    (slug,),
                )
                if cur.fetchone() is None:
                    return slug
                slug = f"{requested}-{suffix}"
                suffix += 1

    def _row_to_agent(self, row: dict[str, Any]) -> dict[str, Any]:
        effective_state = row.get("effective_state") or effective_connectivity_state(
            row["connectivity_state"], row["last_heartbeat_at"]
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
            "surface_capabilities": decode_json_field(row["surface_capabilities_json"], []),
            "version": row["version"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "updated_at": row["updated_at"],
            "runtime_health_summary": runtime_health_summary(row.get("runtime_health_json")),
            "runtime_health_generated_at": runtime_health_generated_at(row.get("runtime_health_json")),
        }

    def _replace_runtime_health_workers(
        self,
        conn,
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
        with _cur(conn) as cur:
            cur.execute(
                f"DELETE FROM {_SCHEMA}.agent_runtime_workers WHERE agent_id = %s",
                (agent_id,),
            )
            for worker in workers:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.agent_runtime_workers (
                        agent_id, worker_id, process_role, started_at, last_seen_at,
                        current_item_id, current_conversation_key, current_kind,
                        items_processed, stale_recoveries_seen, last_error, mirrored_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    def _runtime_worker_rows(self, conn, agent_id: str) -> list[dict[str, Any]]:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT *
                FROM {_SCHEMA}.agent_runtime_workers
                WHERE agent_id = %s
                ORDER BY worker_id ASC
                """,
                (agent_id,),
            )
            rows = cur.fetchall()
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

    def _upsert_timeline_event(
        self,
        conn,
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
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.timeline_events (
                    event_id, conversation_id, routed_task_id, agent_id, kind, title,
                    body, status, progress, metadata_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(event_id) DO UPDATE SET
                    conversation_id = EXCLUDED.conversation_id,
                    routed_task_id = EXCLUDED.routed_task_id,
                    agent_id = EXCLUDED.agent_id,
                    kind = EXCLUDED.kind,
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    status = EXCLUDED.status,
                    progress = EXCLUDED.progress,
                    metadata_json = EXCLUDED.metadata_json,
                    created_at = EXCLUDED.created_at
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
                    _jsonb(metadata),
                    created_at,
                ),
            )

    def _publish_ui_timeline_conn(
        self,
        conn,
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
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT status FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                (conversation_id,),
            )
            conversation = cur.fetchone()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.conversations
                    SET updated_at = %s, status = %s
                    WHERE conversation_id = %s
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
        with self._connect() as conn, _write_tx(conn):
            slug = self._ensure_unique_slug(conn, requested_card.get("slug") or "agent")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.agents (
                        agent_id, agent_token, display_name, slug, role,
                        skills_json, tags_json, description, provider, mode,
                        connectivity_state, current_capacity, max_capacity,
                        surface_capabilities_json, version, created_at, updated_at, last_heartbeat_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        agent_token,
                        requested_card.get("display_name") or slug,
                        slug,
                        requested_card.get("role", ""),
                        _jsonb(declared_capabilities(requested_card)),
                        _jsonb(requested_card.get("tags", [])),
                        requested_card.get("description", ""),
                        requested_card.get("provider", ""),
                        requested_card.get("mode", "registry"),
                        requested_card.get("connectivity_state", "degraded"),
                        int(requested_card.get("current_capacity", 0)),
                        max(1, int(requested_card.get("max_capacity", 1))),
                        _jsonb(requested_card.get("surface_capabilities", [])),
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET display_name = %s, role = %s, skills_json = %s, tags_json = %s,
                        description = %s, provider = %s, mode = %s, connectivity_state = %s,
                        current_capacity = %s, max_capacity = %s, surface_capabilities_json = %s,
                        version = %s, updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_token = %s
                    """,
                    (
                        card.get("display_name", row["display_name"]),
                        card.get("role", row["role"]),
                        _jsonb(declared_capabilities(card)),
                        _jsonb(card.get("tags", [])),
                        card.get("description", row["description"]),
                        card.get("provider", row["provider"]),
                        card.get("mode", row["mode"]),
                        payload.get("connectivity_state", row["connectivity_state"]),
                        int(payload.get("current_capacity", 0)),
                        max(1, int(payload.get("max_capacity", 1))),
                        _jsonb(card.get("surface_capabilities", [])),
                        card.get("version", row["version"]),
                        now,
                        now,
                        agent_token,
                    ),
                )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return self._row_to_agent(row)

    def heartbeat(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            runtime_health_payload = payload.get("runtime_health")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET connectivity_state = %s, current_capacity = %s, max_capacity = %s,
                        updated_at = %s, last_heartbeat_at = %s, runtime_health_json = %s
                    WHERE agent_token = %s
                    """,
                    (
                        payload.get("connectivity_state", row["connectivity_state"]),
                        int(payload.get("current_capacity", row["current_capacity"])),
                        max(1, int(payload.get("max_capacity", row["max_capacity"]))),
                        now,
                        now,
                        (
                            _jsonb(runtime_health_payload)
                            if isinstance(runtime_health_payload, dict)
                            else _jsonb(decode_json_field(row.get("runtime_health_json"), {}))
                        ),
                        agent_token,
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
            return {"agent": self._row_to_agent(row), "server_time": now}

    def publish_timeline(self, agent_token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for event in events:
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        SELECT status, target_agent_id
                        FROM {_SCHEMA}.conversations
                        WHERE conversation_id = %s
                        """,
                        (event["conversation_id"],),
                    )
                    conversation = cur.fetchone()
                if conversation is None:
                    raise PermissionError(f"Unknown conversation: {event['conversation_id']}")
                if conversation["target_agent_id"] != row["agent_id"]:
                    raise PermissionError(
                        f"Conversation does not belong to agent: {event['conversation_id']}"
                    )
                self._upsert_timeline_event(
                    conn,
                    event_id=event["event_id"],
                    conversation_id=event["conversation_id"],
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
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        UPDATE {_SCHEMA}.conversations
                        SET updated_at = %s, status = %s
                        WHERE conversation_id = %s
                        """,
                        (
                            event["created_at"],
                            conversation_status_for_event(event["kind"], conversation["status"]),
                            event["conversation_id"],
                        ),
                    )
        return {"accepted": len(events)}

    def bind_conversation(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.conversations (
                        conversation_id, target_agent_id, title, origin_surface, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'open', %s, %s)
                    ON CONFLICT(conversation_id) DO UPDATE SET
                        target_agent_id = EXCLUDED.target_agent_id,
                        title = EXCLUDED.title,
                        origin_surface = EXCLUDED.origin_surface,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        payload["conversation_id"],
                        row["agent_id"],
                        payload.get("title", ""),
                        payload.get("origin_surface", "telegram"),
                        now,
                        now,
                    ),
                )
        return self.get_conversation(payload["conversation_id"])

    def get_capability_override(self, capability_name: str) -> bool | None:
        normalized = capability_name.strip().lower()
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT enabled FROM {_SCHEMA}.skills_override WHERE lower(skill_name) = %s",
                    (normalized,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return bool(row["enabled"])

    def set_capability_override(self, capability_name: str, enabled: bool, set_by: str = "ui") -> None:
        normalized = capability_name.strip().lower()
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skills_override (skill_name, enabled, set_by, set_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        set_by = EXCLUDED.set_by,
                        set_at = EXCLUDED.set_at
                    """,
                    (normalized, 1 if enabled else 0, set_by, datetime.now(timezone.utc).timestamp()),
                )

    def list_capabilities(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    WITH live_agents AS (
                        SELECT slug, skills_json
                        FROM {_SCHEMA}.agents
                        WHERE CASE
                            WHEN coalesce(last_heartbeat_at, '') != ''
                                 AND last_heartbeat_at::timestamptz < %s::timestamptz
                            THEN 'offline'
                            ELSE connectivity_state
                        END != 'offline'
                    ),
                    declared AS (
                        SELECT lower(je.value) AS capability_key, je.value AS capability_name, live_agents.slug
                        FROM live_agents
                        CROSS JOIN LATERAL jsonb_array_elements_text(live_agents.skills_json) AS je(value)
                    )
                    SELECT capability_key, MIN(capability_name) AS capability_name,
                           array_agg(DISTINCT slug ORDER BY slug) AS declared_by_agents
                    FROM declared
                    GROUP BY capability_key
                    ORDER BY capability_key
                    """,
                    (self._offline_before(),),
                )
                declared_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT skill_name, enabled
                    FROM {_SCHEMA}.skills_override
                    ORDER BY lower(skill_name)
                    """
                )
                override_rows = cur.fetchall()
        merged: dict[str, dict[str, Any]] = {}
        for row in declared_rows:
            merged[row["capability_key"]] = {
                "capability_name": row["capability_name"],
                "declared_by_agents": row["declared_by_agents"] or [],
                "enabled": None,
            }
        for row in override_rows:
            key = row["skill_name"].lower()
            item = merged.setdefault(
                key,
                {
                    "capability_name": row["skill_name"],
                    "declared_by_agents": [],
                    "enabled": None,
                },
            )
            item["enabled"] = bool(row["enabled"])
        return sorted(merged.values(), key=lambda item: item["capability_name"].lower())

    def _disabled_capabilities(self, conn) -> set[str]:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT skill_name FROM {_SCHEMA}.skills_override WHERE enabled = 0"
            )
            rows = cur.fetchall()
        return {str(row["skill_name"]).lower() for row in rows}

    def search_agents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        role = query.get("role", "").strip().lower()
        required_state = query.get("required_state", "connected")
        capabilities = query_capabilities(query)
        tags = {t.lower() for t in query.get("tags", []) if t}
        free_text = query.get("free_text", "").strip()
        exclude = sorted(set(query.get("exclude_agent_ids", [])))
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            capabilities = capabilities - disabled_capabilities
            if (query.get("capabilities") or query.get("skills")) and not capabilities:
                return []
            sql = [
                f"""
                WITH agent_rows AS (
                    SELECT
                        a.*,
                        CASE
                            WHEN coalesce(a.last_heartbeat_at, '') != ''
                                 AND a.last_heartbeat_at::timestamptz < %s::timestamptz
                            THEN 'offline'
                            ELSE a.connectivity_state
                        END AS effective_state
                    FROM {_SCHEMA}.agents a
                )
                SELECT *
                FROM agent_rows
                WHERE 1 = 1
                """
            ]
            params: list[Any] = [self._offline_before()]
            if exclude:
                sql.append(" AND agent_id != ALL(%s)")
                params.append(exclude)
            if required_state:
                sql.append(" AND effective_state = %s")
                params.append(required_state)
            if role:
                sql.append(" AND role ILIKE %s")
                params.append(f"%{role}%")
            for capability in sorted(capabilities):
                sql.append(
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                        WHERE lower(je.value) = %s
                    )
                    """
                )
                params.append(capability)
            for tag in sorted(tags):
                sql.append(
                    """
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.tags_json) AS je(value)
                        WHERE lower(je.value) = %s
                    )
                    """
                )
                params.append(tag)
            if free_text:
                like = f"%{free_text}%"
                skill_clause = """
                    EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                        WHERE je.value ILIKE %s
                    )
                """
                if disabled_skills:
                    skill_clause = f"""
                        EXISTS (
                            SELECT 1
                            FROM jsonb_array_elements_text(agent_rows.skills_json) AS je(value)
                            WHERE je.value ILIKE %s
                              AND lower(je.value) != ALL(%s)
                        )
                    """
                sql.append(
                    f"""
                    AND (
                        display_name ILIKE %s
                        OR role ILIKE %s
                        OR description ILIKE %s
                        OR {skill_clause}
                        OR EXISTS (
                            SELECT 1
                            FROM jsonb_array_elements_text(agent_rows.tags_json) AS je(value)
                            WHERE je.value ILIKE %s
                        )
                    )
                    """
                )
                params.extend([like, like, like, like])
                if disabled_skills:
                    params.append(sorted(disabled_skills))
                params.append(like)
            sql.append(" ORDER BY lower(display_name)")
            with _cur(conn) as cur:
                cur.execute("".join(sql), params)
                rows = cur.fetchall()
        return [self._row_to_agent(row) for row in rows]

    def create_delivery(self, *, target_agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        delivery_id = uuid.uuid4().hex
        with self._connect() as conn, _write_tx(conn):
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
        conn,
        *,
        target_agent_id: str,
        kind: str,
        payload: dict[str, Any],
        now: str,
        delivery_id: str,
    ) -> dict[str, Any]:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.deliveries (
                    delivery_id, target_agent_id, kind, payload_json, state, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, 'queued', %s, %s)
                RETURNING seq
                """,
                (delivery_id, target_agent_id, kind, _jsonb(payload), now, now),
            )
            seq = cur.fetchone()["seq"]
        return {"delivery_id": delivery_id, "seq": seq}

    def create_routed_task(self, request: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            disabled_capabilities = self._disabled_capabilities(conn)
            for capability in requested_routed_capabilities(request):
                if capability.lower() in disabled_capabilities:
                    raise CapabilityDisabledError(capability)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.routed_tasks (
                        routed_task_id, parent_conversation_id, origin_agent_id, target_agent_id,
                        title, request_json, status, summary, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'queued', '', %s, %s)
                    ON CONFLICT(routed_task_id) DO UPDATE SET
                        parent_conversation_id = EXCLUDED.parent_conversation_id,
                        origin_agent_id = EXCLUDED.origin_agent_id,
                        target_agent_id = EXCLUDED.target_agent_id,
                        title = EXCLUDED.title,
                        request_json = EXCLUDED.request_json,
                        status = EXCLUDED.status,
                        summary = EXCLUDED.summary,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        request["routed_task_id"],
                        request["parent_conversation_id"],
                        request["origin_agent_id"],
                        request["target_agent_id"],
                        request["title"],
                        _jsonb(request),
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
        return {"routed_task_id": request["routed_task_id"], "delivery_id": delivery["delivery_id"]}

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT seq, delivery_id, kind, payload_json, state, created_at
                    FROM {_SCHEMA}.deliveries
                    WHERE target_agent_id = %s
                      AND state = 'queued'
                      AND seq > %s
                    ORDER BY seq ASC
                    LIMIT %s
                    """,
                    (row["agent_id"], cursor, limit),
                )
                deliveries = cur.fetchall()
            delivery_ids = [item["delivery_id"] for item in deliveries]
            if delivery_ids:
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        UPDATE {_SCHEMA}.deliveries
                        SET state = 'leased', leased_at = %s, updated_at = %s
                        WHERE delivery_id = ANY(%s)
                        """,
                        (now, now, delivery_ids),
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.deliveries
                    SET state = %s, updated_at = %s, acked_at = %s
                    WHERE delivery_id = ANY(%s)
                      AND target_agent_id = %s
                    """,
                    (
                        next_state,
                        now,
                        now if next_state != "queued" else None,
                        delivery_ids,
                        row["agent_id"],
                    ),
                )
        return {"updated": len(delivery_ids), "classification": classification}

    def update_routed_task_status(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.routed_tasks
                    SET status = %s, summary = %s, updated_at = %s
                    WHERE routed_task_id = %s
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                    (routed_task_id,),
                )
                task = cur.fetchone()
            if task is None:
                raise KeyError(routed_task_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.routed_tasks
                    SET status = %s, summary = %s, result_json = %s, updated_at = %s
                    WHERE routed_task_id = %s
                    """,
                    (
                        payload.get("status", "completed"),
                        payload.get("summary", ""),
                        _jsonb(payload),
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET connectivity_state = 'offline', updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_token = %s
                    """,
                    (now, now, agent_token),
                )
        return {"agent_id": row["agent_id"], "connectivity_state": "offline"}

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(f"SELECT * FROM {_SCHEMA}.agents ORDER BY lower(display_name)")
                rows = cur.fetchall()
        return [self._row_to_agent(row) for row in rows]

    def ui_bootstrap(self) -> dict[str, Any]:
        return {
            "bots": self.list_agents(),
            "conversations": self.list_conversations(),
            "tasks": self.list_tasks(),
        }

    def get_agent_runtime_health(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return runtime_health_detail(
                row.get("runtime_health_json"),
                self._runtime_worker_rows(conn, agent_id),
            )

    def create_conversation(self, *, target_agent_id: str, title: str, message_text: str) -> dict[str, Any]:
        now = utcnow_iso()
        conversation_id = uuid.uuid4().hex
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.conversations (
                        conversation_id, target_agent_id, title, origin_surface, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, 'registry', 'open', %s, %s)
                    """,
                    (conversation_id, target_agent_id, title, now, now),
                )
            self._create_delivery(
                conn,
                target_agent_id=target_agent_id,
                kind="surface_input",
                payload={
                    "conversation_id": conversation_id,
                    "title": title,
                    "text": message_text,
                    "surface": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="Conversation started",
                body=message_text,
                kind="surface_input",
            )
        return self.get_conversation(conversation_id)

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT
                        c.*,
                        a.display_name AS target_name,
                        COUNT(t.event_id) AS timeline_event_count
                    FROM {_SCHEMA}.conversations c
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    LEFT JOIN {_SCHEMA}.timeline_events t ON t.conversation_id = c.conversation_id
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_surface, c.status, c.created_at, c.updated_at, a.display_name
                    ORDER BY c.updated_at DESC
                    """
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT
                        c.*,
                        a.display_name AS target_name,
                        COUNT(t.event_id) AS timeline_event_count
                    FROM {_SCHEMA}.conversations c
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    LEFT JOIN {_SCHEMA}.timeline_events t ON t.conversation_id = c.conversation_id
                    WHERE c.conversation_id = %s
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_surface, c.status, c.created_at, c.updated_at, a.display_name
                    """,
                    (conversation_id,),
                )
                row = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                    FROM {_SCHEMA}.routed_tasks t
                    LEFT JOIN {_SCHEMA}.agents origin ON origin.agent_id = t.origin_agent_id
                    LEFT JOIN {_SCHEMA}.agents target ON target.agent_id = t.target_agent_id
                    WHERE t.parent_conversation_id = %s
                    ORDER BY t.updated_at DESC
                    """,
                    (conversation_id,),
                )
                task_rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM {_SCHEMA}.timeline_events
                    WHERE conversation_id = %s
                    ORDER BY seq ASC
                    """,
                    (conversation_id,),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT conversation_id, metadata_json, created_at
                    FROM {_SCHEMA}.timeline_events
                    WHERE kind = 'usage' AND created_at >= %s
                    ORDER BY created_at
                    """,
                    (since_iso,),
                )
                rows = cur.fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def search_conversations(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    WITH matched AS (
                        SELECT te.conversation_id,
                               te.seq,
                               ts_headline(
                                   'english',
                                   te.body,
                                   plainto_tsquery('english', %s),
                                   'MaxWords=32,MinWords=15,HighlightAll=true,StartSel=<b>,StopSel=</b>'
                               ) AS snippet,
                               ROW_NUMBER() OVER (
                                   PARTITION BY te.conversation_id
                                   ORDER BY te.seq DESC
                               ) AS row_rank
                        FROM {_SCHEMA}.timeline_events te
                        WHERE te.body_tsv @@ plainto_tsquery('english', %s)
                    )
                    SELECT conversation_id, snippet
                    FROM matched
                    WHERE row_rank = 1
                    ORDER BY seq DESC
                    LIMIT %s
                    """,
                    (q, q, limit),
                )
                rows = cur.fetchall()
        return [{"conversation_id": row["conversation_id"], "snippet": row["snippet"]} for row in rows]

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id, title FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="surface_input",
                payload={
                    "conversation_id": conversation_id,
                    "title": conversation["title"],
                    "text": text,
                    "surface": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="User message",
                body=text,
                kind="surface_input",
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def add_conversation_action(
        self, conversation_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        action_payload = payload or {}
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="surface_action",
                payload={
                    "conversation_id": conversation_id,
                    "conversation_ref": conversation_id,
                    "action": action,
                    "payload": action_payload,
                    "surface": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title=f"Action: {action}",
                body=json.dumps(action_payload) if action_payload else "",
                kind="surface_action",
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def cancel_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            now = utcnow_iso()
            self._create_delivery(
                conn,
                target_agent_id=conversation["target_agent_id"],
                kind="control",
                payload={
                    "conversation_id": conversation_id,
                    "action": "cancel",
                    "surface": "registry",
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            self._publish_ui_timeline_conn(
                conn,
                conversation_id=conversation_id,
                title="Cancel requested",
                body="",
                kind="control",
            )
        return {"conversation_id": conversation_id, "accepted": True}

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                    FROM {_SCHEMA}.routed_tasks t
                    LEFT JOIN {_SCHEMA}.agents origin ON origin.agent_id = t.origin_agent_id
                    LEFT JOIN {_SCHEMA}.agents target ON target.agent_id = t.target_agent_id
                    ORDER BY t.updated_at DESC
                    """
                )
                rows = cur.fetchall()
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
