"""Postgres-backed registry store."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.capability_service import (
    query_capabilities,
    requested_routed_capabilities,
)
from app.db.postgres import get_connection
from app.registry_service.store_base import (
    AbstractRegistryStore,
    CapabilityDisabledError,
    PROTECTED_ROUTED_TASK_STATUSES,
    routed_task_created_event,
    routed_task_progress_event,
    routed_task_result_event,
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
    hash_agent_token,
    registry_scope_for_agent_row,
    require_registry_scope,
    runtime_health_detail,
    runtime_health_generated_at,
    runtime_health_summary,
    utcnow_iso,
    validated_registry_scope,
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
                (hash_agent_token(token),),
            )
            return cur.fetchone()

    def resolve_agent_for_token(self, agent_token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            return dict(row) if row else None

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
            "registry_scope": row.get("registry_scope", "full"),
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


    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        card = validated_agent_card_payload(requested_card, require_registry_scope=True)
        bot_key = str(card.get("bot_key", "") or "").strip()
        if not bot_key:
            raise ValueError("bot_key requires non-empty text")

        # If bot_key is provided, check for existing enrollment (idempotent re-enroll)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT agent_id, slug FROM {_SCHEMA}.agents WHERE bot_key = %s",
                    (bot_key,),
                )
                existing = cur.fetchone()
                if existing:
                    agent_token = secrets.token_urlsafe(32)
                    agent_token_hash = hash_agent_token(agent_token)
                    cur.execute(
                        f"UPDATE {_SCHEMA}.agents SET agent_token = %s, updated_at = %s WHERE bot_key = %s",
                        (agent_token_hash, now, bot_key),
                    )
                    return {
                        "agent_id": existing["agent_id"],
                        "slug": existing["slug"],
                        "agent_token": agent_token,
                        "poll_cursor": "0",
                    }

        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn, _write_tx(conn):
            slug = self._ensure_unique_slug(conn, card.get("slug") or "agent")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.agents (
                        agent_id, agent_token, display_name, slug, role, registry_scope,
                        skills_json, tags_json, description, provider, mode,
                        connectivity_state, current_capacity, max_capacity,
                        channel_capabilities_json, version, bot_key,
                        created_at, updated_at, last_heartbeat_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        agent_token_hash,
                        card.get("display_name") or slug,
                        slug,
                        card.get("role", ""),
                        validated_registry_scope(card.get("registry_scope")),
                        _jsonb(card.get("capabilities", [])),
                        _jsonb(card.get("tags", [])),
                        card.get("description", ""),
                        card.get("provider", ""),
                        card.get("mode", "registry"),
                        card.get("connectivity_state", "degraded"),
                        card.get("current_capacity", 0),
                        card.get("max_capacity", 1),
                        _jsonb(card.get("channel_capabilities", [])),
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            requested_bot_key = str(card.get("bot_key", "") or "").strip()
            current_bot_key = str(row["bot_key"] or "").strip()
            if requested_bot_key and requested_bot_key != current_bot_key:
                raise ValueError("bot_key must match the enrolled agent identity")
            current_skills = decode_json_field(row.get("skills_json"), [])
            current_tags = decode_json_field(row.get("tags_json"), [])
            current_channel_capabilities = decode_json_field(
                row.get("channel_capabilities_json"),
                [],
            )
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET display_name = %s, role = %s, registry_scope = %s, skills_json = %s, tags_json = %s,
                        description = %s, provider = %s, mode = %s, connectivity_state = %s,
                        current_capacity = %s, max_capacity = %s, channel_capabilities_json = %s,
                        version = %s, updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_token = %s
                    """,
                    (
                        card.get("display_name", row["display_name"]),
                        card.get("role", row["role"]),
                        card.get("registry_scope", row["registry_scope"]),
                        _jsonb(card.get("capabilities", current_skills)),
                        _jsonb(card.get("tags", current_tags)),
                        card.get("description", row["description"]),
                        card.get("provider", row["provider"]),
                        card.get("mode", row["mode"]),
                        register_payload.get("connectivity_state", row["connectivity_state"]),
                        register_payload.get("current_capacity", row["current_capacity"]),
                        register_payload.get("max_capacity", row["max_capacity"]),
                        _jsonb(card.get("channel_capabilities", current_channel_capabilities)),
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            runtime_health_payload = heartbeat_payload.get("runtime_health")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET connectivity_state = %s, current_capacity = %s, max_capacity = %s,
                        updated_at = %s, last_heartbeat_at = %s, runtime_health_json = %s
                    WHERE agent_token = %s
                    """,
                    (
                        heartbeat_payload.get("connectivity_state", row["connectivity_state"]),
                        heartbeat_payload.get("current_capacity", row["current_capacity"]),
                        heartbeat_payload.get("max_capacity", row["max_capacity"]),
                        now,
                        now,
                        (
                            _jsonb(runtime_health_payload)
                            if isinstance(runtime_health_payload, dict)
                            else _jsonb(decode_json_field(row.get("runtime_health_json"), {}))
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
            return {"agent": self._row_to_agent(row), "server_time": now}

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
        validated_query = validated_search_query(query)
        role = validated_query.get("role", "").strip().lower()
        required_state = validated_query.get("required_state", "connected")
        capabilities = query_capabilities(validated_query)
        tags = {t.lower() for t in validated_query.get("tags", []) if t}
        free_text = validated_query.get("free_text", "").strip()
        exclude = sorted(set(validated_query.get("exclude_agent_ids", [])))
        with self._connect() as conn:
            disabled_capabilities = self._disabled_capabilities(conn)
            capabilities = capabilities - disabled_capabilities
            if (validated_query.get("capabilities") or validated_query.get("skills")) and not capabilities:
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
                if disabled_capabilities:
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
                if disabled_capabilities:
                    params.append(sorted(disabled_capabilities))
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
        validated_request = validated_routed_task_request(request)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT conversation_id FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (validated_request["parent_conversation_id"],),
                )
                conversation_row = cur.fetchone()
            if conversation_row is None:
                raise KeyError(validated_request["parent_conversation_id"])
            disabled_capabilities = self._disabled_capabilities(conn)
            for capability in requested_routed_capabilities(validated_request):
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
                        validated_request["routed_task_id"],
                        validated_request["parent_conversation_id"],
                        validated_request["origin_agent_id"],
                        validated_request["target_agent_id"],
                        validated_request["title"],
                        _jsonb(validated_request),
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        mirrored_event["event_id"],
                        mirrored_event["conversation_id"],
                        validated_request["target_agent_id"],
                        mirrored_event["kind"],
                        "",
                        mirrored_event["content"],
                        _jsonb(mirrored_event["metadata"]),
                        mirrored_event["created_at"],
                    ),
                )
                inserted = cur.rowcount > 0
            inserted_events: list[dict[str, Any]] = []
            if inserted:
                with _cur(conn) as cur:
                    cur.execute(
                        f"SELECT seq FROM {_SCHEMA}.events WHERE event_id = %s",
                        (mirrored_event["event_id"],),
                    )
                    seq_row = cur.fetchone()
                inserted_events.append({
                    "seq": int(seq_row["seq"]) if seq_row is not None else 0,
                    "event_id": mirrored_event["event_id"],
                    "conversation_id": mirrored_event["conversation_id"],
                    "agent_id": validated_request["target_agent_id"],
                    "kind": mirrored_event["kind"],
                    "actor": "",
                    "content": mirrored_event["content"],
                    "metadata": mirrored_event["metadata"],
                    "created_at": mirrored_event["created_at"],
                })
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (mirrored_event["created_at"], mirrored_event["conversation_id"]),
                    )
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
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            allowed_kinds = delivery_kinds_for_registry_scope(
                registry_scope_for_agent_row(row)
            )
            with _cur(conn) as cur:
                if allowed_kinds is None:
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
                else:
                    cur.execute(
                        f"""
                        SELECT seq, delivery_id, kind, payload_json, state, created_at
                        FROM {_SCHEMA}.deliveries
                        WHERE target_agent_id = %s
                          AND state = 'queued'
                          AND seq > %s
                          AND kind = ANY(%s)
                        ORDER BY seq ASC
                        LIMIT %s
                        """,
                        (row["agent_id"], cursor, list(allowed_kinds), limit),
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
        validated_ids, validated_classification = validated_ack_request(
            delivery_ids=delivery_ids,
            classification=classification,
        )
        next_state = {
            "accepted": "acked",
            "rejected": "dead_letter",
            "retry_later": "queued",
        }[validated_classification]
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
                        validated_ids,
                        row["agent_id"],
                    ),
                )
        return {"updated": len(validated_ids), "classification": validated_classification}

    def update_routed_task_status(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        validated_payload = validated_routed_task_status_payload(payload)
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, {"coordination", "full"})
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.routed_tasks
                    SET status = %s, summary = %s, updated_at = %s
                    WHERE routed_task_id = %s
                      AND status != ALL(%s)
                    """,
                    (
                        validated_payload["status"],
                        validated_payload["summary"],
                        now,
                        routed_task_id,
                        list(PROTECTED_ROUTED_TASK_STATUSES),
                    ),
                )
                updated = cur.rowcount
            events_written = False
            inserted_events: list[dict[str, Any]] = []
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT parent_conversation_id, origin_agent_id, target_agent_id FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                    (routed_task_id,),
                )
                task_row = cur.fetchone()
            if updated > 0:
                source_events = list(validated_payload["timeline_events"])
                if not source_events and task_row is not None:
                    source_events = [
                        routed_task_progress_event(
                            routed_task_id=routed_task_id,
                            parent_conversation_id=task_row["parent_conversation_id"],
                            payload=validated_payload,
                        )
                    ]
                for event in source_events:
                    event_metadata = {"status": validated_payload["status"]}
                    if event.get("progress") is not None:
                        event_metadata["progress"] = event["progress"]
                    event_content = str(event.get("body", "") or event.get("title", "") or "")
                    with _cur(conn) as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(event_id) DO NOTHING
                            """,
                            (
                                event["event_id"],
                                event["conversation_id"],
                                row["agent_id"],
                                "task.status",
                                "",
                                event_content,
                                _jsonb(event_metadata),
                                event["created_at"],
                            ),
                        )
                        if cur.rowcount > 0:
                            cur.execute(
                                f"SELECT seq FROM {_SCHEMA}.events WHERE event_id = %s",
                                (event["event_id"],),
                            )
                            seq_row = cur.fetchone()
                            events_written = True
                            inserted_events.append({
                                "seq": int(seq_row["seq"]) if seq_row is not None else 0,
                                "event_id": event["event_id"],
                                "conversation_id": event["conversation_id"],
                                "agent_id": row["agent_id"],
                                "kind": "task.status",
                                "actor": "",
                                "content": event_content,
                                "metadata": event_metadata,
                                "created_at": event["created_at"],
                            })
                if events_written and task_row is not None:
                    mirrored_updated_at = inserted_events[-1]["created_at"] if inserted_events else now
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (mirrored_updated_at, task_row["parent_conversation_id"]),
                        )
            result = {"routed_task_id": routed_task_id, "status": validated_payload["status"], "events_written": events_written, "inserted_events": inserted_events}
            if task_row:
                result["parent_conversation_id"] = task_row["parent_conversation_id"]
                result["origin_agent_id"] = task_row["origin_agent_id"]
                result["target_agent_id"] = task_row["target_agent_id"]
        return result

    def update_routed_task_result(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        validated_payload = validated_routed_task_result_payload(payload)
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, {"coordination", "full"})
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
                    f"SELECT external_conversation_ref FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (task["parent_conversation_id"],),
                )
                parent_conversation = cur.fetchone()
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.routed_tasks
                    SET status = %s, summary = %s, result_json = %s, updated_at = %s
                    WHERE routed_task_id = %s
                    """,
                    (
                        validated_payload["status"],
                        validated_payload["summary"],
                        _jsonb(validated_payload),
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
                    "parent_external_conversation_ref": (
                        str(parent_conversation["external_conversation_ref"] or "")
                        if parent_conversation is not None
                        else ""
                    ),
                    "result": validated_payload,
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
            mirrored_event = routed_task_result_event(
                routed_task_id=routed_task_id,
                parent_conversation_id=task["parent_conversation_id"],
                payload=validated_payload,
            )
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO NOTHING
                    """,
                    (
                        mirrored_event["event_id"],
                        mirrored_event["conversation_id"],
                        row["agent_id"],
                        mirrored_event["kind"],
                        "",
                        mirrored_event["content"],
                        _jsonb(mirrored_event["metadata"]),
                        mirrored_event["created_at"],
                    ),
                )
                inserted = cur.rowcount > 0
            inserted_events: list[dict[str, Any]] = []
            if inserted:
                with _cur(conn) as cur:
                    cur.execute(
                        f"SELECT seq FROM {_SCHEMA}.events WHERE event_id = %s",
                        (mirrored_event["event_id"],),
                    )
                    seq_row = cur.fetchone()
                inserted_events.append({
                    "seq": int(seq_row["seq"]) if seq_row is not None else 0,
                    "event_id": mirrored_event["event_id"],
                    "conversation_id": mirrored_event["conversation_id"],
                    "agent_id": row["agent_id"],
                    "kind": mirrored_event["kind"],
                    "actor": "",
                    "content": mirrored_event["content"],
                    "metadata": mirrored_event["metadata"],
                    "created_at": mirrored_event["created_at"],
                })
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (mirrored_event["created_at"], mirrored_event["conversation_id"]),
                    )
        return {
            "routed_task_id": routed_task_id,
            "status": validated_payload["status"],
            "events_written": bool(inserted_events),
            "inserted_events": inserted_events,
            "parent_conversation_id": task["parent_conversation_id"],
            "origin_agent_id": task["origin_agent_id"],
            "target_agent_id": task["target_agent_id"],
        }

    def deregister(self, agent_token: str) -> dict[str, Any]:
        now = utcnow_iso()
        agent_token_hash = hash_agent_token(agent_token)
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
            with _cur(conn) as cur:
                if q or connectivity_state:
                    cur.execute(f"SELECT * FROM {_SCHEMA}.agents ORDER BY lower(display_name)")
                    rows = cur.fetchall()
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
                    cur.execute(
                        f"SELECT * FROM {_SCHEMA}.agents WHERE agent_id = %s ORDER BY lower(display_name) LIMIT %s OFFSET %s",
                        (for_agent_id, fetch_limit, cursor),
                    )
                else:
                    cur.execute(
                        f"SELECT * FROM {_SCHEMA}.agents ORDER BY lower(display_name) LIMIT %s OFFSET %s",
                        (fetch_limit, cursor),
                    )
                rows = cur.fetchall()
        return [self._row_to_agent(row) for row in rows]

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

    def agent_exists(self, agent_id: str) -> bool:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT 1 FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                return cur.fetchone() is not None

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

        with self._connect() as conn, _write_tx(conn):
            # Look up bot_key for the target agent to compute deterministic conversation_id
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT bot_key FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (target_agent_id,),
                )
                agent_row = cur.fetchone()
                bot_key = ""
                if agent_row is not None:
                    bot_key = str(agent_row["bot_key"] or "").strip()
                if not bot_key:
                    raise ValueError(f"Unknown agent or missing bot_key: {target_agent_id}")
                canonical = f"{bot_key}:{origin_channel}:{external_conversation_ref}"
                conversation_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]

                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.conversations (
                        conversation_id, target_agent_id, title, origin_channel,
                        external_conversation_ref, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, 'open', %s, %s)
                    ON CONFLICT(target_agent_id, origin_channel, external_conversation_ref) DO UPDATE SET
                        title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at
                    RETURNING conversation_id
                    """,
                    (conversation_id, target_agent_id, title, origin_channel, external_conversation_ref, now, now),
                )
                actual_id = cur.fetchone()["conversation_id"]
        return self.get_conversation(actual_id)

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "") -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        # When a search query is provided (>= 3 chars), use FTS-based search
        if q and len(q) >= 3:
            search_hits = self.search_conversations(q, limit=fetch_limit + cursor)
            hit_ids = [h["conversation_id"] for h in search_hits]
            if not hit_ids:
                return []
            with self._connect() as conn:
                with _cur(conn) as cur:
                    placeholders = ",".join(["%s"] * len(hit_ids))
                    where_clauses = [f"c.conversation_id IN ({placeholders})"]
                    params: list[Any] = list(hit_ids)
                    if for_agent_id is not None:
                        where_clauses.append("c.target_agent_id = %s")
                        params.append(for_agent_id)
                    if status:
                        where_clauses.append("c.status = %s")
                        params.append(status)
                    where_sql = " WHERE " + " AND ".join(where_clauses)
                    sql = f"""
                        SELECT
                            c.*,
                            a.display_name AS target_name,
                            COUNT(e.event_id) AS event_count
                        FROM {_SCHEMA}.conversations c
                        LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                        LEFT JOIN {_SCHEMA}.events e ON e.conversation_id = c.conversation_id
                        {where_sql}
                        GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
                        ORDER BY c.updated_at DESC
                        LIMIT %s OFFSET %s
                    """
                    params.extend([fetch_limit, cursor])
                    cur.execute(sql, params)
                    rows = cur.fetchall()
        else:
            with self._connect() as conn:
                with _cur(conn) as cur:
                    sql = f"""
                        SELECT
                            c.*,
                            a.display_name AS target_name,
                            COUNT(e.event_id) AS event_count
                        FROM {_SCHEMA}.conversations c
                        LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                        LEFT JOIN {_SCHEMA}.events e ON e.conversation_id = c.conversation_id
                    """
                    params_list: list[Any] = []
                    where_clauses_list: list[str] = []
                    if for_agent_id is not None:
                        where_clauses_list.append("c.target_agent_id = %s")
                        params_list.append(for_agent_id)
                    if status:
                        where_clauses_list.append("c.status = %s")
                        params_list.append(status)
                    if where_clauses_list:
                        sql += " WHERE " + " AND ".join(where_clauses_list)
                    sql += """
                        GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
                        ORDER BY c.updated_at DESC
                        LIMIT %s OFFSET %s
                    """
                    params_list.extend([fetch_limit, cursor])
                    cur.execute(sql, params_list)
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
                "origin_channel": row["origin_channel"],
                "external_conversation_ref": row["external_conversation_ref"],
                "event_count": int(row["event_count"] or 0),
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
                        COUNT(e.event_id) AS event_count
                    FROM {_SCHEMA}.conversations c
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    LEFT JOIN {_SCHEMA}.events e ON e.conversation_id = c.conversation_id
                    WHERE c.conversation_id = %s
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
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
            "origin_channel": row["origin_channel"],
            "external_conversation_ref": row["external_conversation_ref"],
            "event_count": int(row["event_count"] or 0),
            "linked_routed_tasks": tasks,
        }

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                if until_iso:
                    cur.execute(
                        f"""
                        SELECT conversation_id, metadata_json, created_at
                        FROM {_SCHEMA}.events
                        WHERE kind = 'provider.response' AND created_at >= %s AND created_at <= %s
                        ORDER BY created_at
                        """,
                        (since_iso, until_iso),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT conversation_id, metadata_json, created_at
                        FROM {_SCHEMA}.events
                        WHERE kind = 'provider.response' AND created_at >= %s
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

    def get_summary(self, *, now_iso: str) -> dict[str, Any]:
        window_start = (
            datetime.fromisoformat(now_iso) - timedelta(hours=24)
        ).isoformat()
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT connectivity_state, last_heartbeat_at FROM {_SCHEMA}.agents"
                )
                agent_rows = cur.fetchall()
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN status IN ('open', 'running', 'cancelling') THEN 1 ELSE 0 END) AS active
                    FROM {_SCHEMA}.conversations
                    """
                )
                conversation_totals = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM {_SCHEMA}.conversations c
                    WHERE EXISTS (
                        SELECT 1
                        FROM {_SCHEMA}.events e
                        WHERE e.conversation_id = c.conversation_id
                          AND e.kind = 'approval.requested'
                          AND e.seq = (
                              SELECT MAX(e2.seq)
                              FROM {_SCHEMA}.events e2
                              WHERE e2.conversation_id = c.conversation_id
                                AND e2.kind IN ('approval.requested', 'approval.decided')
                          )
                    )
                    """
                )
                pending_approvals_row = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,
                        SUM(CASE WHEN status IN ('queued', 'leased', 'submitted') THEN 1 ELSE 0 END) AS pending,
                        SUM(CASE WHEN status = 'failed' AND updated_at >= %s THEN 1 ELSE 0 END) AS failed_24h
                    FROM {_SCHEMA}.routed_tasks
                    """,
                    (window_start,),
                )
                task_totals = cur.fetchone()
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
            with _cur(conn) as cur:
                sql = f"""
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
                    FROM {_SCHEMA}.events e
                    JOIN {_SCHEMA}.conversations c ON c.conversation_id = e.conversation_id
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    WHERE e.kind = 'approval.requested'
                      AND e.seq = (
                          SELECT MAX(e2.seq)
                          FROM {_SCHEMA}.events e2
                          WHERE e2.conversation_id = e.conversation_id
                            AND e2.kind IN ('approval.requested', 'approval.decided')
                      )
                """
                params: list[Any] = []
                if for_agent_id is not None:
                    sql += " AND c.target_agent_id = %s"
                    params.append(for_agent_id)
                sql += " ORDER BY e.created_at DESC LIMIT %s OFFSET %s"
                params.extend([fetch_limit, cursor])
                cur.execute(sql, params)
                rows = cur.fetchall()
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
                **(json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else (row["metadata_json"] or {})),
            }
            for row in rows
        ]

    def search_conversations(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    WITH matched AS (
                        SELECT ev.conversation_id,
                               ev.seq,
                               ts_headline(
                                   'english',
                                   ev.content,
                                   plainto_tsquery('english', %s),
                                   'MaxWords=32,MinWords=15,HighlightAll=true,StartSel=<b>,StopSel=</b>'
                               ) AS snippet,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ev.conversation_id
                                   ORDER BY ev.seq DESC
                               ) AS row_rank
                        FROM {_SCHEMA}.events ev
                        WHERE to_tsvector('english', ev.content) @@ plainto_tsquery('english', %s)
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
        validated_text = validated_conversation_message_text(text)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id, title, origin_channel, external_conversation_ref FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT bot_key FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (conversation["target_agent_id"],),
                )
                agent_row = cur.fetchone()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO NOTHING
                    RETURNING seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at""",
                    (event_id, conversation_id, "", "message.user", "operator", validated_text, _jsonb({}), now),
                )
                evt_row = cur.fetchone()
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                    (now, conversation_id),
                )
            inserted_event = None
            if evt_row:
                inserted_event = {
                    "seq": evt_row["seq"],
                    "event_id": evt_row["event_id"],
                    "conversation_id": evt_row["conversation_id"],
                    "agent_id": evt_row["agent_id"],
                    "kind": evt_row["kind"],
                    "actor": evt_row["actor"],
                    "content": evt_row["content"],
                    "metadata": json.loads(evt_row["metadata_json"]) if isinstance(evt_row["metadata_json"], str) else evt_row["metadata_json"],
                    "created_at": evt_row["created_at"],
                }
        return {"conversation_id": conversation_id, "accepted": True, "event": inserted_event}

    def add_conversation_action(
        self, conversation_id: str, action: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        validated_action, action_payload = validated_conversation_action(action, payload)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id, origin_channel, external_conversation_ref FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT bot_key FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (conversation["target_agent_id"],),
                )
                agent_row = cur.fetchone()
            bot_key = ""
            if agent_row is not None:
                bot_key = str(agent_row["bot_key"] or "").strip()
            if not bot_key:
                raise ValueError(
                    f"Unknown agent or missing bot_key: {conversation['target_agent_id']}"
                )
            now = utcnow_iso()
            event_id_for_action = uuid.uuid4().hex
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
                    "bot_key": bot_key,
                    "origin_channel": conversation["origin_channel"],
                    "external_conversation_ref": conversation["external_conversation_ref"],
                    "stable_event_id": event_id_for_action,
                    "stable_created_at": now,
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
                decision = "rejected" if validated_action.startswith("reject") else "approved"
                event_metadata = {
                    "action": validated_action,
                    "decided_by": "operator",
                    "decision": decision,
                }
                event_content = json.dumps(action_payload) if action_payload else ""
            event_id = event_id_for_action
            with _cur(conn) as cur:
                cur.execute(
                    f"""INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(event_id) DO NOTHING
                    RETURNING seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at""",
                    (event_id, conversation_id, "", event_kind, "operator", event_content, _jsonb(event_metadata), now),
                )
                evt_row = cur.fetchone()
            if is_cancel:
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s, status = %s WHERE conversation_id = %s",
                        (now, "cancelling", conversation_id),
                    )
            else:
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (now, conversation_id),
                    )
            inserted_event = None
            if evt_row:
                inserted_event = {
                    "seq": evt_row["seq"],
                    "event_id": evt_row["event_id"],
                    "conversation_id": evt_row["conversation_id"],
                    "agent_id": evt_row["agent_id"],
                    "kind": evt_row["kind"],
                    "actor": evt_row["actor"],
                    "content": evt_row["content"],
                    "metadata": json.loads(evt_row["metadata_json"]) if isinstance(evt_row["metadata_json"], str) else evt_row["metadata_json"],
                    "created_at": evt_row["created_at"],
                }
        return {"conversation_id": conversation_id, "accepted": True, "event": inserted_event}

    def list_tasks(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, status: str = "") -> list[dict[str, Any]]:
        fetch_limit = limit + 1
        with self._connect() as conn:
            with _cur(conn) as cur:
                sql = f"""
                    SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                    FROM {_SCHEMA}.routed_tasks t
                    LEFT JOIN {_SCHEMA}.agents origin ON origin.agent_id = t.origin_agent_id
                    LEFT JOIN {_SCHEMA}.agents target ON target.agent_id = t.target_agent_id
                """
                params: list[Any] = []
                where_clauses: list[str] = []
                if for_agent_id is not None:
                    where_clauses.append("(t.origin_agent_id = %s OR t.target_agent_id = %s)")
                    params.extend([for_agent_id, for_agent_id])
                if status:
                    where_clauses.append("t.status = %s")
                    params.append(status)
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)
                sql += " ORDER BY t.updated_at DESC LIMIT %s OFFSET %s"
                params.extend([fetch_limit, cursor])
                cur.execute(sql, params)
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

    def publish_events(self, agent_token: str, conversation_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            agent_id = row["agent_id"]
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conversation = cur.fetchone()
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
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(event_id) DO NOTHING
                        """,
                        (
                            event_id,
                            conversation_id,
                            agent_id,
                            kind,
                            str(event.get("actor", "") or ""),
                            str(event.get("content", "") or ""),
                            _jsonb(event.get("metadata", {})),
                            created_at,
                        ),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                        inserted_ids.add(event_id)
                        cur.execute(
                            f"SELECT seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at FROM {_SCHEMA}.events WHERE event_id = %s",
                            (event_id,),
                        )
                        ev_row = cur.fetchone()
                        if ev_row:
                            meta = ev_row["metadata_json"]
                            inserted_events.append({
                                "seq": ev_row["seq"],
                                "event_id": ev_row["event_id"],
                                "conversation_id": ev_row["conversation_id"],
                                "agent_id": ev_row["agent_id"],
                                "kind": ev_row["kind"],
                                "actor": ev_row["actor"],
                                "content": ev_row["content"],
                                "metadata": meta if isinstance(meta, dict) else json.loads(meta) if meta else {},
                                "created_at": str(ev_row["created_at"]),
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
        clauses = ["conversation_id = %s"]
        params: list[Any] = [conversation_id]
        if kinds:
            placeholders = ", ".join(["%s"] * len(kinds))
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        if before_seq:
            clauses.append("seq < %s")
            params.append(before_seq)
            order_sql = "ORDER BY seq DESC"
        elif after_seq:
            clauses.append("seq > %s")
            params.append(after_seq)
            order_sql = "ORDER BY seq ASC"
        else:
            order_sql = "ORDER BY seq DESC"
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM {_SCHEMA}.events
                    WHERE {' AND '.join(clauses)}
                    {order_sql}
                    LIMIT %s
                    """,
                    (*params, limit + 1),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT * FROM {_SCHEMA}.events
                    WHERE conversation_id = %s AND kind IN ('message.user', 'message.bot') AND seq > %s
                    ORDER BY seq ASC
                    LIMIT %s
                    """,
                    (conversation_id, cursor, limit),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT c.*, a.display_name AS target_name
                    FROM {_SCHEMA}.conversations c
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    WHERE c.target_agent_id = %s
                    ORDER BY c.updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (effective_agent_id, fetch_limit, cursor),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            agent = self._row_to_agent(row)
            workers = self._runtime_worker_rows(conn, agent_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS cnt FROM {_SCHEMA}.conversations
                    WHERE target_agent_id = %s AND status IN ('open', 'running')
                    """,
                    (agent_id,),
                )
                active_count_row = cur.fetchone()
                active_conversations = int(active_count_row["cnt"]) if active_count_row else 0
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS cnt FROM {_SCHEMA}.events
                    WHERE agent_id = %s AND kind = 'error'
                      AND created_at::timestamptz >= (now() - interval '1 hour')
                    """,
                    (agent_id,),
                )
                error_count_row = cur.fetchone()
                recent_errors = int(error_count_row["cnt"]) if error_count_row else 0
        agent["workers"] = workers
        agent["active_conversations"] = active_conversations
        agent["recent_errors"] = recent_errors
        return agent

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            sql = f"SELECT * FROM {_SCHEMA}.events WHERE kind = 'provider.response'"
            params: list[Any] = []
            if agent_id:
                sql += " AND agent_id = %s"
                params.append(agent_id)
            if conversation_id:
                sql += " AND conversation_id = %s"
                params.append(conversation_id)
            if since:
                sql += " AND created_at >= %s"
                params.append(since)
            if until:
                sql += " AND created_at <= %s"
                params.append(until)
            sql += " ORDER BY created_at"
            with _cur(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conv = cur.fetchone()
            if conv is None:
                raise KeyError(conversation_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.events WHERE conversation_id = %s ORDER BY seq ASC",
                    (conversation_id,),
                )
                rows = cur.fetchall()
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"DELETE FROM {_SCHEMA}.events WHERE created_at < %s",
                    (cutoff,),
                )
                count = cur.rowcount
        return count

    # ------------------------------------------------------------------
    # Skill / guidance persistence (registry-owned content store)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (list, dict)):
            return raw
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
        files_json = self._stable_json(
            [
                {
                    "relative_path": f.relative_path,
                    "content_text": f.content_text,
                    "content_type": f.content_type,
                    "executable": f.executable,
                }
                for f in record.revision.files
            ]
        )
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT published_revision_id FROM {_SCHEMA}.runtime_skills WHERE slug = %s",
                    (record.slug,),
                )
                existing = cur.fetchone()
                published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.runtime_skills (
                        slug, display_name, description, source_kind, source_uri, owner_actor,
                        visibility, is_mutable, archived, instruction_body, requirements_json,
                        provider_config_json, files_json, active_revision_id, published_revision_id,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(slug) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        source_kind = EXCLUDED.source_kind,
                        source_uri = EXCLUDED.source_uri,
                        owner_actor = EXCLUDED.owner_actor,
                        visibility = EXCLUDED.visibility,
                        is_mutable = EXCLUDED.is_mutable,
                        archived = EXCLUDED.archived,
                        instruction_body = EXCLUDED.instruction_body,
                        requirements_json = EXCLUDED.requirements_json,
                        provider_config_json = EXCLUDED.provider_config_json,
                        files_json = EXCLUDED.files_json,
                        active_revision_id = EXCLUDED.active_revision_id,
                        published_revision_id = EXCLUDED.published_revision_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        record.slug,
                        record.display_name,
                        record.description,
                        record.source_kind,
                        record.source_uri,
                        record.owner_actor,
                        record.visibility,
                        record.is_mutable,
                        record.archived,
                        record.revision.instruction_body,
                        self._stable_json(record.revision.requirements),
                        self._stable_json(record.revision.provider_config),
                        files_json,
                        revision_id,
                        published_revision_id,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_revisions (
                        revision_id, slug, instruction_body, requirements_json,
                        provider_config_json, files_json, version_label, changelog,
                        status, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(revision_id) DO UPDATE SET
                        instruction_body = EXCLUDED.instruction_body,
                        requirements_json = EXCLUDED.requirements_json,
                        provider_config_json = EXCLUDED.provider_config_json,
                        files_json = EXCLUDED.files_json,
                        version_label = EXCLUDED.version_label,
                        changelog = EXCLUDED.changelog,
                        status = EXCLUDED.status,
                        created_by = EXCLUDED.created_by,
                        created_at = EXCLUDED.created_at
                    """,
                    (
                        revision_id,
                        record.slug,
                        record.revision.instruction_body,
                        self._stable_json(record.revision.requirements),
                        self._stable_json(record.revision.provider_config),
                        files_json,
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(f"DELETE FROM {_SCHEMA}.skill_revisions WHERE slug = %s", (slug,))
                cur.execute(f"DELETE FROM {_SCHEMA}.skill_approvals WHERE slug = %s", (slug,))
                cur.execute(f"DELETE FROM {_SCHEMA}.runtime_skills WHERE slug = %s", (slug,))
                return cur.rowcount > 0

    def _skill_row_to_track(self, row: dict[str, Any]) -> RuntimeSkillTrackRecord:
        files_data = self._parse_json(row.get("files_json", "[]"), [])
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
        revision = SkillRevisionRecord(
            instruction_body=row.get("instruction_body", ""),
            requirements=self._parse_json(row.get("requirements_json", "[]"), []),
            provider_config=self._parse_json(row.get("provider_config_json", "{}"), {}),
            files=files,
            version_label=row.get("version_label", ""),
            changelog=row.get("changelog", ""),
            created_by=row.get("created_by", ""),
            created_at=row.get("created_at", ""),
            revision_id=row.get("revision_id", row.get("active_revision_id", "")),
            status=row.get("status", "published"),
        )
        return RuntimeSkillTrackRecord(
            slug=row["slug"],
            display_name=row.get("display_name", ""),
            description=row.get("description", ""),
            source_kind=row.get("source_kind", "custom"),
            revision=revision,
            source_uri=row.get("source_uri", ""),
            owner_actor=row.get("owner_actor", ""),
            visibility=row.get("visibility", "private"),
            is_mutable=bool(row.get("is_mutable", True)),
            archived=bool(row.get("archived", False)),
            active_revision_id=row.get("active_revision_id", ""),
            published_revision_id=row.get("published_revision_id", ""),
        )

    def _skill_rows_for_slug(self, slug: str, *, runtime_only: bool) -> list[dict[str, Any]]:
        revision_ref = (
            "CASE WHEN s.published_revision_id != '' THEN s.published_revision_id ELSE s.active_revision_id END"
            if runtime_only else "s.active_revision_id"
        )
        extra_where = "AND s.published_revision_id != ''" if runtime_only else ""
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT
                        s.slug, s.display_name, s.description, s.source_kind,
                        s.source_uri, s.owner_actor, s.visibility, s.is_mutable,
                        s.archived, s.active_revision_id, s.published_revision_id,
                        rev.revision_id, rev.instruction_body, rev.requirements_json,
                        rev.provider_config_json, rev.files_json, rev.version_label,
                        rev.changelog, rev.status, rev.created_by, rev.created_at
                    FROM {_SCHEMA}.runtime_skills s
                    JOIN {_SCHEMA}.skill_revisions rev ON rev.revision_id = {revision_ref}
                    WHERE s.slug = %s
                    {extra_where}
                    """,
                    (slug,),
                )
                return cur.fetchall()

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
            with _cur(conn) as cur:
                cur.execute(f"SELECT slug FROM {_SCHEMA}.runtime_skills ORDER BY lower(slug)")
                slugs = cur.fetchall()
        resolver = self.resolve_runtime_skill if runtime_only else self.resolve_skill
        summaries: list[RuntimeSkillSummary] = []
        for row in slugs:
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT revision_id, instruction_body, requirements_json, provider_config_json,
                           files_json, version_label, changelog, status, created_by, created_at
                    FROM {_SCHEMA}.skill_revisions
                    WHERE slug = %s
                    ORDER BY created_at DESC, revision_id DESC
                    """,
                    (slug,),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT record_id, revision_id, action, actor, note, created_at
                    FROM {_SCHEMA}.skill_approvals
                    WHERE slug = %s
                    ORDER BY created_at DESC, record_id DESC
                    """,
                    (slug,),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT action
                    FROM {_SCHEMA}.skill_approvals
                    WHERE slug = %s AND revision_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    LIMIT 1
                    """,
                    (slug, revision_id),
                )
                row = cur.fetchone()
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.skill_approvals (
                        record_id, slug, revision_id, action, actor, note, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.skill_revisions SET status = %s WHERE slug = %s AND revision_id = %s",
                    (status, slug, revision_id),
                )

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.runtime_skills SET published_revision_id = %s, updated_at = %s WHERE slug = %s",
                    (revision_id, utcnow_iso(), slug),
                )

    def clear_published_skill_revision(self, slug: str) -> None:
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.runtime_skills SET published_revision_id = '', updated_at = %s WHERE slug = %s",
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                if set_status is not None:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.skill_revisions SET status = %s WHERE slug = %s AND revision_id = %s",
                        (set_status, slug, revision_id),
                    )
                if published_pointer == "set_active":
                    cur.execute(
                        f"UPDATE {_SCHEMA}.runtime_skills SET published_revision_id = %s, updated_at = %s WHERE slug = %s",
                        (revision_id, now, slug),
                    )
                elif published_pointer == "clear":
                    cur.execute(
                        f"UPDATE {_SCHEMA}.runtime_skills SET published_revision_id = '', updated_at = %s WHERE slug = %s",
                        (now, slug),
                    )
                if approval_action is not None:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.skill_approvals (
                            record_id, slug, revision_id, action, actor, note, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT published_revision_id FROM {_SCHEMA}.provider_guidance WHERE provider = %s AND scope_kind = %s AND scope_key = %s",
                    (record.provider, record.scope_kind, record.scope_key),
                )
                existing = cur.fetchone()
                published_revision_id = revision_id if publish else (existing["published_revision_id"] if existing else "")
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.provider_guidance (
                        provider, scope_kind, scope_key, content, format, is_mutable,
                        active_revision_id, published_revision_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(provider, scope_kind, scope_key) DO UPDATE SET
                        content = EXCLUDED.content,
                        format = EXCLUDED.format,
                        is_mutable = EXCLUDED.is_mutable,
                        active_revision_id = EXCLUDED.active_revision_id,
                        published_revision_id = EXCLUDED.published_revision_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        record.provider,
                        record.scope_kind,
                        record.scope_key,
                        record.revision.content,
                        record.revision.format,
                        record.is_mutable,
                        revision_id,
                        published_revision_id,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.guidance_revisions (
                        revision_id, provider, scope_kind, scope_key, content, format,
                        status, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(revision_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        format = EXCLUDED.format,
                        status = EXCLUDED.status,
                        created_by = EXCLUDED.created_by,
                        created_at = EXCLUDED.created_at
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT
                        g.provider, g.scope_kind, g.scope_key, g.is_mutable,
                        g.active_revision_id, g.published_revision_id,
                        rev.content, rev.format, rev.created_by, rev.created_at,
                        rev.status, rev.revision_id
                    FROM {_SCHEMA}.provider_guidance g
                    JOIN {_SCHEMA}.guidance_revisions rev ON rev.revision_id = g.active_revision_id
                    WHERE g.provider = %s AND g.scope_kind = %s AND g.scope_key = %s
                    """,
                    (provider, scope_kind, scope_key),
                )
                row = cur.fetchone()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT
                        g.provider, g.scope_kind, g.scope_key, g.is_mutable,
                        g.active_revision_id, g.published_revision_id,
                        rev.content, rev.format, rev.created_by, rev.created_at,
                        rev.status, rev.revision_id
                    FROM {_SCHEMA}.provider_guidance g
                    JOIN {_SCHEMA}.guidance_revisions rev ON rev.revision_id = g.published_revision_id
                    WHERE g.provider = %s AND g.scope_kind = %s AND g.scope_key = %s AND g.published_revision_id != ''
                    """,
                    (provider, scope_kind, scope_key),
                )
                row = cur.fetchone()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT revision_id, content, format, created_by, created_at, status
                    FROM {_SCHEMA}.guidance_revisions
                    WHERE provider = %s AND scope_kind = %s AND scope_key = %s
                    ORDER BY created_at DESC, revision_id DESC
                    """,
                    (provider, scope_kind, scope_key),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT record_id, revision_id, action, actor, note, created_at
                    FROM {_SCHEMA}.guidance_approvals
                    WHERE provider = %s AND scope_kind = %s AND scope_key = %s
                    ORDER BY created_at DESC, record_id DESC
                    """,
                    (provider, scope_kind, scope_key),
                )
                rows = cur.fetchall()
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
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT action
                    FROM {_SCHEMA}.guidance_approvals
                    WHERE provider = %s AND scope_kind = %s AND scope_key = %s AND revision_id = %s
                    ORDER BY created_at DESC, record_id DESC
                    LIMIT 1
                    """,
                    (provider, scope_kind, scope_key, revision_id),
                )
                row = cur.fetchone()
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.guidance_approvals (
                        record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.guidance_revisions SET status = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s AND revision_id = %s",
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.provider_guidance SET published_revision_id = %s, updated_at = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s",
                    (revision_id, utcnow_iso(), provider, scope_kind, scope_key),
                )

    def clear_published_provider_guidance_revision(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.provider_guidance SET published_revision_id = '', updated_at = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s",
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
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                if set_status is not None:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.guidance_revisions SET status = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s AND revision_id = %s",
                        (set_status, provider, scope_kind, scope_key, revision_id),
                    )
                if published_pointer == "set_active":
                    cur.execute(
                        f"UPDATE {_SCHEMA}.provider_guidance SET published_revision_id = %s, updated_at = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s",
                        (revision_id, now, provider, scope_kind, scope_key),
                    )
                elif published_pointer == "clear":
                    cur.execute(
                        f"UPDATE {_SCHEMA}.provider_guidance SET published_revision_id = '', updated_at = %s WHERE provider = %s AND scope_kind = %s AND scope_key = %s",
                        (now, provider, scope_kind, scope_key),
                    )
                if approval_action is not None:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.guidance_approvals (
                            record_id, provider, scope_kind, scope_key, revision_id, action, actor, note, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
