"""Postgres-backed registry store."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from contextlib import contextmanager
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Literal

from octopus_sdk.content_models import (
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

from .capability_service import (
    query_capabilities,
    requested_routed_capabilities,
)
from .postgres import get_connection
from .exact_aliases import matches_exact_alias
from .store_base import (
    AbstractRegistryStore,
    stable_routed_task_id,
    CapabilityDisabledError,
    PROTECTED_ROUTED_TASK_STATUSES,
    delegation_event,
    direct_assignment_message_text,
    routed_task_created_event,
    routed_task_external_conversation_ref,
    validated_action_payload,
    validated_ack_request,
    validated_agent_card_payload,
    validated_conversation_action,
    validated_conversation_message_text,
    validated_heartbeat_payload,
    validated_management_request,
    validated_management_result,
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
from octopus_sdk.registry.management import (
    ManagementRequest,
    ManagementResult,
    required_management_capability,
)
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentRecord,
    AgentStatusRecord,
    ApprovalRecord,
    CapabilityRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    ConversationRecord,
    ConversationSearchHitRecord,
    DeliveryPollResult,
    DeliveryRecord,
    DelegationTaskDraft,
    DirectAssignActionPayload,
    EnrollmentResult,
    EventRecord,
    EventPageRecord,
    HealthSummary,
    MessageRecord,
    MessagePageRecord,
    PublishEventsResult,
    RegistryRecordModel,
    RegistryJsonRecord,
    RegistrySummaryRecord,
    RuntimeHealthPayload,
    RuntimeHealthDetailRecord,
    RuntimeWorkerRecord,
    TargetSelector,
    TaskRecord,
    UsageSummaryRecord,
)
from octopus_sdk.task_protocol import (
    RoutedTaskSnapshot,
    TaskTransitionRequest,
    apply_task_transition,
)

_SCHEMA = "agent_registry"
_REGISTRY_EPOCH_KEY = "registry_epoch"


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, RegistryJsonRecord):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, RegistryRecordModel):
        return _json_ready(value.model_dump(mode="json"))
    if hasattr(value, "model_dump"):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _record(model_cls, payload):
    return model_cls.model_validate(_json_ready(payload))


def _records(model_cls, rows):
    return [_record(model_cls, row) for row in rows]


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


def _jsonb(value: object) -> Jsonb:
    return Jsonb(_json_ready(value))


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
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.meta (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (_REGISTRY_EPOCH_KEY, uuid.uuid4().hex),
                )
            conn.commit()

    def _registry_epoch(self, conn) -> str:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT value FROM {_SCHEMA}.meta WHERE key = %s",
                (_REGISTRY_EPOCH_KEY,),
            )
            row = cur.fetchone()
            epoch = str((row or {}).get("value", "") or "").strip()
            if epoch:
                return epoch
            epoch = uuid.uuid4().hex
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.meta (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (_REGISTRY_EPOCH_KEY, epoch),
            )
            return epoch

    def _offline_before(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    def _token_row(self, conn, token: str) -> dict[str, object] | None:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT * FROM {_SCHEMA}.agents WHERE agent_token = %s",
                (hash_agent_token(token),),
            )
            return cur.fetchone()

    def resolve_agent_for_token(self, agent_token: str) -> AgentRecord | None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            return self._row_to_agent(row) if row else None

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

    def _row_to_agent(self, row: dict[str, object]) -> AgentRecord:
        effective_state = row.get("effective_state") or effective_connectivity_state(
            row["connectivity_state"], row["last_heartbeat_at"]
        )
        return _record(AgentRecord, {
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
            "management_capabilities": decode_json_field(row.get("management_capabilities_json"), []),
            "version": row["version"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "updated_at": row["updated_at"],
            "runtime_health_summary": runtime_health_summary(row.get("runtime_health_json")),
            "runtime_health_generated_at": runtime_health_generated_at(row.get("runtime_health_json")),
        })

    def _replace_runtime_health_workers(
        self,
        conn,
        *,
        agent_id: str,
        runtime_health_payload: RuntimeHealthPayload,
        mirrored_at: str,
    ) -> None:
        workers: list[RuntimeWorkerRecord] = []
        snapshot = runtime_health_payload.snapshot
        if snapshot is not None:
            raw_workers = snapshot.get("workers") or []
            if isinstance(raw_workers, list):
                for worker in raw_workers:
                    try:
                        workers.append(RuntimeWorkerRecord.model_validate(worker))
                    except Exception:
                        continue
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
                        worker.worker_id,
                        worker.process_role,
                        worker.started_at,
                        worker.last_seen_at,
                        worker.current_item_id,
                        worker.current_conversation_key,
                        worker.current_kind,
                        worker.items_processed,
                        worker.stale_recoveries_seen,
                        worker.last_error,
                        mirrored_at,
                    ),
                )

    def _runtime_worker_rows(self, conn, agent_id: str) -> list[dict[str, object]]:
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


    def enroll(self, requested_card: AgentCard) -> EnrollmentResult:
        now = utcnow_iso()
        requested_payload = (
            requested_card.model_dump(mode="json")
            if hasattr(requested_card, "model_dump")
            else requested_card
        )
        card = validated_agent_card_payload(requested_payload, require_registry_scope=True)
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
                    return _record(EnrollmentResult, {
                        "agent_id": existing["agent_id"],
                        "slug": existing["slug"],
                        "agent_token": agent_token,
                        "poll_cursor": "0",
                        "registry_epoch": self._registry_epoch(conn),
                    })

        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn, _write_tx(conn):
            slug = self._ensure_unique_slug(conn, card.get("slug") or "agent")
            registry_epoch = self._registry_epoch(conn)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.agents (
                        agent_id, agent_token, display_name, slug, role, registry_scope,
                        skills_json, tags_json, description, provider, mode,
                        connectivity_state, current_capacity, max_capacity,
                        channel_capabilities_json, management_capabilities_json, version, bot_key,
                        created_at, updated_at, last_heartbeat_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        _jsonb(card.get("management_capabilities", [])),
                        card.get("version", ""),
                        bot_key,
                        now,
                        now,
                        now,
                    ),
                )
        return _record(EnrollmentResult, {
            "agent_id": agent_id,
            "slug": slug,
            "agent_token": agent_token,
            "poll_cursor": "0",
            "registry_epoch": registry_epoch,
        })

    def assert_agent_scope(self, agent_token: str, required_scopes: set[str]) -> None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, required_scopes)

    def register(self, agent_token: str, payload: AgentRegisterRequest) -> AgentRecord:
        now = utcnow_iso()
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            register_payload = validated_register_payload(
                payload.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
                if hasattr(payload, "model_dump")
                else payload
            )
            card = register_payload.agent_card
            requested_bot_key = str(card.bot_key or "").strip()
            current_bot_key = str(row["bot_key"] or "").strip()
            if requested_bot_key and requested_bot_key != current_bot_key:
                raise ValueError("bot_key must match the enrolled agent identity")
            current_skills = decode_json_field(row.get("skills_json"), [])
            current_tags = decode_json_field(row.get("tags_json"), [])
            current_channel_capabilities = decode_json_field(
                row.get("channel_capabilities_json"),
                [],
            )
            current_management_capabilities = decode_json_field(
                row.get("management_capabilities_json"),
                [],
            )
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET display_name = %s, role = %s, registry_scope = %s, skills_json = %s, tags_json = %s,
                        description = %s, provider = %s, mode = %s, connectivity_state = %s,
                        current_capacity = %s, max_capacity = %s, channel_capabilities_json = %s,
                        management_capabilities_json = %s,
                        version = %s, updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_token = %s
                    """,
                    (
                        card.display_name or row["display_name"],
                        card.role or row["role"],
                        card.registry_scope or row["registry_scope"],
                        _jsonb(card.capabilities or current_skills),
                        _jsonb(card.tags or current_tags),
                        card.description or row["description"],
                        card.provider or row["provider"],
                        card.mode or row["mode"],
                        register_payload.connectivity_state or row["connectivity_state"],
                        row["current_capacity"] if register_payload.current_capacity is None else register_payload.current_capacity,
                        row["max_capacity"] if register_payload.max_capacity is None else register_payload.max_capacity,
                        _jsonb(card.channel_capabilities or current_channel_capabilities),
                        _jsonb(card.management_capabilities or current_management_capabilities),
                        card.version or row["version"],
                        now,
                        now,
                        agent_token_hash,
                    ),
                )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return self._row_to_agent(row)

    def heartbeat(self, agent_token: str, payload: AgentHeartbeatRequest) -> HealthSummary:
        now = utcnow_iso()
        agent_token_hash = hash_agent_token(agent_token)
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            heartbeat_payload = validated_heartbeat_payload(
                payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
            )
            previous_effective_state = effective_connectivity_state(
                row["connectivity_state"],
                row["last_heartbeat_at"],
            )
            runtime_health_payload = heartbeat_payload.runtime_health
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET connectivity_state = %s, current_capacity = %s, max_capacity = %s,
                        updated_at = %s, last_heartbeat_at = %s, runtime_health_json = %s
                    WHERE agent_token = %s
                    """,
                    (
                        heartbeat_payload.connectivity_state or row["connectivity_state"],
                        row["current_capacity"] if heartbeat_payload.current_capacity is None else heartbeat_payload.current_capacity,
                        row["max_capacity"] if heartbeat_payload.max_capacity is None else heartbeat_payload.max_capacity,
                        now,
                        now,
                        (
                            _jsonb(runtime_health_payload)
                            if runtime_health_payload is not None
                            else _jsonb(decode_json_field(row.get("runtime_health_json"), {}))
                        ),
                        agent_token_hash,
                    ),
                )
            if runtime_health_payload is not None:
                self._replace_runtime_health_workers(
                    conn,
                    agent_id=row["agent_id"],
                    runtime_health_payload=runtime_health_payload,
                    mirrored_at=now,
                )
            row = self._token_row(conn, agent_token)
            assert row is not None
            current_agent = self._row_to_agent(row)
            return _record(HealthSummary, {
                "agent": current_agent,
                "collections_changed": previous_effective_state != current_agent["connectivity_state"],
                "server_time": now,
            })

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

    def list_capabilities(self) -> list[CapabilityRecord]:
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
        merged: dict[str, dict[str, object]] = {}
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
        return _records(
            CapabilityRecord,
            sorted(merged.values(), key=lambda item: item["capability_name"].lower()),
        )

    def _disabled_capabilities(self, conn) -> set[str]:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT skill_name FROM {_SCHEMA}.skills_override WHERE enabled = 0"
            )
            rows = cur.fetchall()
        return {str(row["skill_name"]).lower() for row in rows}

    def search_agents(self, query: AgentDiscoveryQuery) -> list[AgentRecord]:
        validated_query = validated_search_query(
            query.model_dump(mode="json") if hasattr(query, "model_dump") else query
        )
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
            params: list[object] = [self._offline_before()]
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

    def create_delivery(
        self,
        *,
        target_agent_id: str,
        kind: str,
        payload: RegistryRecordModel,
    ) -> DeliveryRecord:
        now = utcnow_iso()
        delivery_id = uuid.uuid4().hex
        delivery_payload = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else payload
        )
        with self._connect() as conn, _write_tx(conn):
            return self._create_delivery(
                conn,
                target_agent_id=target_agent_id,
                kind=kind,
                payload=delivery_payload,
                now=now,
                delivery_id=delivery_id,
            )

    def create_management_request(self, request: ManagementRequest) -> ManagementRequest:
        now = utcnow_iso()
        validated_request = validated_management_request(
            request.model_dump(mode="json") if hasattr(request, "model_dump") else request
        )
        delivery_id = uuid.uuid4().hex
        capability = required_management_capability(validated_request.operation)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.management_requests (
                        request_id, target_agent_id, operation, capability, payload_json,
                        status, delivery_id, result_json, error_code, error_detail, created_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, 'queued', %s, NULL, '', '', %s, '')
                    ON CONFLICT (request_id) DO UPDATE SET
                        target_agent_id = EXCLUDED.target_agent_id,
                        operation = EXCLUDED.operation,
                        capability = EXCLUDED.capability,
                        payload_json = EXCLUDED.payload_json,
                        status = 'queued',
                        delivery_id = EXCLUDED.delivery_id,
                        result_json = NULL,
                        error_code = '',
                        error_detail = '',
                        created_at = EXCLUDED.created_at,
                        completed_at = ''
                    """,
                    (
                        validated_request.request_id,
                        validated_request.agent_id,
                        validated_request.operation,
                        capability,
                        _jsonb(validated_request.model_dump(mode="json")),
                        delivery_id,
                        now,
                    ),
                )
            self._create_delivery(
                conn,
                target_agent_id=validated_request.agent_id,
                kind="management_request",
                payload=validated_request.model_dump(mode="json"),
                now=now,
                delivery_id=delivery_id,
            )
        return validated_request

    def _create_delivery(
        self,
        conn,
        *,
        target_agent_id: str,
        kind: str,
        payload: dict[str, object],
        now: str,
        delivery_id: str,
    ) -> DeliveryRecord:
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
        return _record(DeliveryRecord, {"delivery_id": delivery_id, "seq": seq})

    def _selector_candidates(
        self,
        conn,
        selector: TargetSelector,
    ) -> list[dict[str, object]]:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                WITH agent_rows AS (
                    SELECT
                        a.*,
                        CASE
                            WHEN a.last_heartbeat_at != '' AND a.last_heartbeat_at < %s THEN 'offline'
                            ELSE a.connectivity_state
                        END AS effective_state
                    FROM {_SCHEMA}.agents a
                )
                SELECT *
                FROM agent_rows
                WHERE effective_state = 'connected'
                ORDER BY lower(display_name), agent_id
                """,
                (self._offline_before(),),
            )
            rows = cur.fetchall()
        value = selector.value.strip().lower()
        matches: list[dict[str, object]] = []
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
                caps = {
                    str(item).strip().lower()
                    for item in decode_json_field(row["skills_json"], [])
                    if item
                }
                if value in caps:
                    matches.append(row)
            elif selector.kind == "role":
                role = str(row["role"] or "").strip().lower()
                if role == value or value in role:
                    matches.append(row)
        return matches

    def _resolve_selector(
        self,
        conn,
        selector: TargetSelector,
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
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
        conn,
        *,
        event_id: str,
        conversation_id: str,
        agent_id: str,
        kind: str,
        actor: str,
        content: str,
        metadata: dict[str, object],
        created_at: str,
    ) -> dict[str, object] | None:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(event_id) DO NOTHING
                RETURNING seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at
                """,
                (
                    event_id,
                    conversation_id,
                    agent_id,
                    kind,
                    actor,
                    content,
                    _jsonb(metadata),
                    created_at,
                ),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _record(EventRecord, {
            "seq": row["seq"],
            "event_id": row["event_id"],
            "conversation_id": row["conversation_id"],
            "agent_id": row["agent_id"],
            "kind": row["kind"],
            "actor": row["actor"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"],
            "created_at": row["created_at"],
        })

    @staticmethod
    def _task_row_to_summary(row: dict[str, object]) -> TaskRecord:
        request_payload = decode_json_field(row["request_json"], {})
        return _record(TaskRecord, {
            "routed_task_id": row["routed_task_id"],
            "parent_conversation_id": row["parent_conversation_id"],
            "origin_transport_ref": str(request_payload.get("origin_transport_ref", "") or ""),
            "origin_agent_id": row["origin_agent_id"],
            "target_agent_id": row["target_agent_id"],
            "title": row["title"],
            "status": row["status"],
            "summary": row["summary"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    @staticmethod
    def _task_snapshot__row(row: dict[str, object]) -> RoutedTaskSnapshot:
        return RoutedTaskSnapshot(
            status=str(row["status"] or "queued"),
            queued_at=str(row["created_at"] or ""),
        )

    def _ensure_conversation_in_tx(
        self,
        conn,
        *,
        target_agent_id: str,
        title: str,
        conversation_type: str = "conversation",
        origin_channel: str,
        external_conversation_ref: str,
        now: str,
    ) -> str:
        if not origin_channel or not origin_channel.strip():
            raise ValueError("origin_channel must not be empty")
        if not external_conversation_ref or not external_conversation_ref.strip():
            raise ValueError("external_conversation_ref must not be empty")
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT bot_key FROM {_SCHEMA}.agents WHERE agent_id = %s",
                (target_agent_id,),
            )
            agent_row = cur.fetchone()
            bot_key = str(agent_row["bot_key"] or "").strip() if agent_row is not None else ""
            if not bot_key:
                raise ValueError(f"Unknown agent or missing bot_key: {target_agent_id}")
            canonical = f"{bot_key}:{origin_channel}:{external_conversation_ref}"
            conversation_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.conversations (
                    conversation_id, target_agent_id, title, conversation_type, origin_channel,
                    external_conversation_ref, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s)
                ON CONFLICT(target_agent_id, origin_channel, external_conversation_ref) DO UPDATE SET
                    title = EXCLUDED.title,
                    updated_at = EXCLUDED.updated_at
                RETURNING conversation_id
                """,
                (
                    conversation_id,
                    target_agent_id,
                    title,
                    conversation_type,
                    origin_channel,
                    external_conversation_ref,
                    now,
                    now,
                ),
            )
            return str(cur.fetchone()["conversation_id"])

    def _ensure_routed_task_recipient_conversation_in_tx(
        self,
        conn,
        request: RoutedTaskRequest,
        *,
        now: str,
    ) -> str:
        external_conversation_ref = str(request.external_conversation_ref or "").strip()
        if not external_conversation_ref:
            external_conversation_ref = routed_task_external_conversation_ref(request.routed_task_id)
        return self._ensure_conversation_in_tx(
            conn,
            target_agent_id=request.target_agent_id,
            title=request.title,
            conversation_type="task_thread",
            origin_channel="registry",
            external_conversation_ref=external_conversation_ref,
            now=now,
        )

    def _create_routed_task_in_tx(
        self,
        conn,
        request: dict[str, object],
        *,
        now: str,
    ) -> dict[str, object]:
        validated_request = validated_routed_task_request(request)
        disabled_capabilities = self._disabled_capabilities(conn)
        request_payload = validated_request.model_dump(mode="json")
        request_payload["external_conversation_ref"] = (
            str(request_payload.get("external_conversation_ref", "") or "").strip()
            or routed_task_external_conversation_ref(validated_request.routed_task_id)
        )
        for capability in requested_routed_capabilities(request_payload):
            if capability.lower() in disabled_capabilities:
                raise CapabilityDisabledError(capability)
        recipient_conversation_id = self._ensure_routed_task_recipient_conversation_in_tx(
            conn,
            validated_request,
            now=now,
        )
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
                    validated_request.routed_task_id,
                    validated_request.parent_conversation_id,
                    validated_request.origin_agent_id,
                    validated_request.target_agent_id,
                    validated_request.title,
                    _jsonb(request_payload),
                    now,
                    now,
                ),
            )
        delivery = self._create_delivery(
            conn,
            target_agent_id=validated_request.target_agent_id,
            kind="routed_task",
            payload=request_payload,
            now=now,
            delivery_id=uuid.uuid4().hex,
        )
        mirrored_event = routed_task_created_event(validated_request)
        inserted_event = self._insert_event(
            conn,
            event_id=mirrored_event.event_id,
            conversation_id=mirrored_event.conversation_id,
            agent_id=validated_request.target_agent_id,
            kind=mirrored_event.kind,
            actor="",
            content=mirrored_event.content,
            metadata=mirrored_event.metadata,
            created_at=mirrored_event.created_at,
        )
        if inserted_event is not None:
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                    (mirrored_event.created_at, mirrored_event.conversation_id),
                )
        recipient_event = self._insert_event(
            conn,
            event_id=f"{mirrored_event.event_id}:recipient",
            conversation_id=recipient_conversation_id,
            agent_id=validated_request.target_agent_id,
            kind=mirrored_event.kind,
            actor="",
            content=mirrored_event.content,
            metadata=mirrored_event.metadata,
            created_at=mirrored_event.created_at,
        )
        if recipient_event is not None:
            with _cur(conn) as cur:
                cur.execute(
                    f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                    (mirrored_event.created_at, recipient_conversation_id),
                )
        return {
            "request": validated_request,
            "delivery": delivery,
            "event": inserted_event,
        }

    def create_routed_task(self, request: RegistryRecordModel) -> TaskRecord:
        now = utcnow_iso()
        validated_request = validated_routed_task_request(
            request.model_dump(mode="json") if hasattr(request, "model_dump") else request
        )
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT conversation_id FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (validated_request.parent_conversation_id,),
                )
                conversation_row = cur.fetchone()
            if conversation_row is None:
                raise KeyError(validated_request.parent_conversation_id)
            created = self._create_routed_task_in_tx(
                conn,
                validated_request.model_dump(mode="json"),
                now=now,
            )
            delivery = created["delivery"]
            inserted_event = created.get("event")
            inserted_events = [inserted_event] if isinstance(inserted_event, EventRecord) else []
        return _record(TaskRecord, {
            "routed_task_id": validated_request.routed_task_id,
            "delivery_id": delivery.delivery_id,
            "events_written": bool(inserted_events),
            "inserted_events": inserted_events,
            "parent_conversation_id": validated_request.parent_conversation_id,
            "origin_agent_id": validated_request.origin_agent_id,
            "target_agent_id": validated_request.target_agent_id,
        })

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> DeliveryPollResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            registry_epoch = self._registry_epoch(conn)
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
                          AND state IN ('queued', 'leased')
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
                          AND state IN ('queued', 'leased')
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
                for item in deliveries:
                    if item["kind"] != "routed_task":
                        continue
                    payload = decode_json_field(item["payload_json"], {})
                    routed_task_id = str(payload.get("routed_task_id") or "").strip()
                    if not routed_task_id:
                        continue
                    with _cur(conn) as cur:
                        cur.execute(
                            f"SELECT * FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                            (routed_task_id,),
                        )
                        task_row = cur.fetchone()
                    if task_row is None:
                        continue
                    decision = apply_task_transition(
                        self._task_snapshot__row(task_row),
                        TaskTransitionRequest(
                            transition="lease",
                            actor_role="system",
                            transition_id=item["delivery_id"],
                            occurred_at=now,
                        ),
                    )
                    if decision.ok and not decision.duplicate and decision.new_state != task_row["status"]:
                        with _cur(conn) as cur:
                            cur.execute(
                                f"UPDATE {_SCHEMA}.routed_tasks SET status = %s, updated_at = %s WHERE routed_task_id = %s",
                                (decision.new_state, now, routed_task_id),
                            )
        items = [
            _record(DeliveryRecord, {
                "cursor": str(item["seq"]),
                "delivery_id": item["delivery_id"],
                "kind": item["kind"],
                "payload": decode_json_field(item["payload_json"], {}),
                "state": "leased" if item["delivery_id"] in delivery_ids else item["state"],
                "created_at": item["created_at"],
            })
            for item in deliveries
        ]
        next_cursor = str(max([cursor] + [int(item["cursor"]) for item in items]))
        return _record(
            DeliveryPollResult,
            {
                "deliveries": items,
                "next_cursor": next_cursor,
                "registry_epoch": registry_epoch,
            },
        )

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> AckResult:
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
                    SET state = %s, updated_at = %s, acked_at = %s, leased_at = NULL
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
        return _record(
            AckResult,
            {"updated": len(validated_ids), "classification": validated_classification},
        )

    def update_routed_task_status(
        self,
        agent_token: str,
        routed_task_id: str,
        payload: RegistryRecordModel,
    ) -> TaskRecord:
        now = utcnow_iso()
        payload_data = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
        if isinstance(payload_data, dict):
            payload_task_id = str(payload_data.pop("routed_task_id", "") or "")
            if payload_task_id and payload_task_id != routed_task_id:
                raise ValueError("routed_task_id must match the requested task")
            payload_data = {"routed_task_id": routed_task_id, **payload_data}
        validated_payload = validated_routed_task_status_payload(
            payload_data
        )
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
                task_row = cur.fetchone()
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
                self._task_snapshot__row(task_row),
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
            inserted_events: list[EventRecord] = []
            primary_event_id = f"task-transition:{routed_task_id}:{validated_payload['transition_id']}"
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT 1 FROM {_SCHEMA}.events WHERE event_id = %s",
                    (primary_event_id,),
                )
                duplicate = cur.fetchone() is not None
            if not duplicate:
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.routed_tasks SET status = %s, summary = %s, updated_at = %s WHERE routed_task_id = %s",
                        (decision.new_state, validated_payload["summary"], occurred_at, routed_task_id),
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
                task_request = decode_json_field(task_row["request_json"], {})
                recipient_conversation_id = self._ensure_conversation_in_tx(
                    conn,
                    target_agent_id=str(task_row["target_agent_id"] or ""),
                    title=str(task_row["title"] or routed_task_id),
                    conversation_type="task_thread",
                    origin_channel="registry",
                    external_conversation_ref=str(task_request.get("external_conversation_ref", "") or ""),
                    now=occurred_at,
                )
                recipient_event = self._insert_event(
                    conn,
                    event_id=f"{primary_event_id}:recipient",
                    conversation_id=recipient_conversation_id,
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
                if recipient_event is not None:
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (occurred_at, recipient_conversation_id),
                        )
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
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (inserted_events[-1]["created_at"], task_row["parent_conversation_id"]),
                        )
            return _record(TaskRecord, {
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "duplicate": duplicate,
                "events_written": bool(inserted_events),
                "inserted_events": inserted_events,
                "parent_conversation_id": task_row["parent_conversation_id"],
                "origin_agent_id": task_row["origin_agent_id"],
                "target_agent_id": task_row["target_agent_id"],
            })

    def update_routed_task_result(
        self,
        agent_token: str,
        routed_task_id: str,
        payload: RegistryRecordModel,
    ) -> TaskRecord:
        now = utcnow_iso()
        usage_fields = {"prompt_tokens", "completion_tokens", "cost_usd"}
        if hasattr(payload, "model_fields_set"):
            include_usage_fields = bool(
                set(getattr(payload, "model_fields_set", set())) & usage_fields
            )
        elif isinstance(payload, Mapping):
            include_usage_fields = bool(set(payload) & usage_fields)
        else:
            include_usage_fields = False
        payload_data = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
        if isinstance(payload_data, dict):
            payload_task_id = str(payload_data.pop("routed_task_id", "") or "")
            if payload_task_id and payload_task_id != routed_task_id:
                raise ValueError("routed_task_id must match the requested task")
            payload_data = {"routed_task_id": routed_task_id, **payload_data}
        validated_payload = validated_routed_task_result_payload(
            payload_data
        )
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
            task_request = decode_json_field(task["request_json"], {})
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
                self._task_snapshot__row(task),
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
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT 1 FROM {_SCHEMA}.events WHERE event_id = %s",
                    (primary_event_id,),
                )
                duplicate = cur.fetchone() is not None
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT external_conversation_ref FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
                    (task["parent_conversation_id"],),
                )
                parent_conversation = cur.fetchone()
            inserted_events: list[EventRecord] = []
            if not duplicate:
                persisted_result = validated_payload.model_dump(mode="json", exclude_none=True)
                persisted_result["completed_at"] = completed_at
                persisted_result["status"] = decision.new_state
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        UPDATE {_SCHEMA}.routed_tasks
                        SET status = %s, summary = %s, result_json = %s, updated_at = %s
                        WHERE routed_task_id = %s
                        """,
                        (
                            decision.new_state,
                            validated_payload["summary"],
                            _jsonb(persisted_result),
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
                        "parent_transport_ref": str(task_request.get("origin_transport_ref", "") or ""),
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
                event_metadata = {
                    "routed_task_id": routed_task_id,
                    "status": decision.new_state,
                    "transition_id": validated_payload.transition_id,
                }
                if include_usage_fields:
                    event_metadata["prompt_tokens"] = int(validated_payload.prompt_tokens or 0)
                    event_metadata["completion_tokens"] = int(validated_payload.completion_tokens or 0)
                    event_metadata["cost_usd"] = float(validated_payload.cost_usd or 0.0)
                if validated_payload.provider:
                    event_metadata["provider"] = validated_payload.provider
                mirrored_event = self._insert_event(
                    conn,
                    event_id=primary_event_id,
                    conversation_id=str(task["parent_conversation_id"] or ""),
                    agent_id=str(row["agent_id"] or ""),
                    kind="task.status",
                    actor="",
                    content=str(
                        validated_payload.summary
                        or validated_payload.full_text
                        or decision.new_state
                    ),
                    metadata=event_metadata,
                    created_at=completed_at,
                )
                if mirrored_event is not None:
                    inserted_events.append(mirrored_event)
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (completed_at, task["parent_conversation_id"]),
                        )
                recipient_conversation_id = self._ensure_conversation_in_tx(
                    conn,
                    target_agent_id=str(task["target_agent_id"] or ""),
                    title=str(task["title"] or routed_task_id),
                    conversation_type="task_thread",
                    origin_channel="registry",
                    external_conversation_ref=str(task_request.get("external_conversation_ref", "") or ""),
                    now=completed_at,
                )
                recipient_event = self._insert_event(
                    conn,
                    event_id=f"{primary_event_id}:recipient",
                    conversation_id=recipient_conversation_id,
                    agent_id=str(row["agent_id"] or ""),
                    kind="task.status",
                    actor="",
                    content=str(
                        validated_payload.summary
                        or validated_payload.full_text
                        or decision.new_state
                    ),
                    metadata={
                        "routed_task_id": routed_task_id,
                        "status": decision.new_state,
                        "transition_id": validated_payload.transition_id,
                    },
                    created_at=completed_at,
                )
                if recipient_event is not None:
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (completed_at, recipient_conversation_id),
                        )
            return _record(TaskRecord, {
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "duplicate": duplicate,
                "events_written": bool(inserted_events),
                "inserted_events": inserted_events,
                "parent_conversation_id": task["parent_conversation_id"],
                "origin_transport_ref": str(task_request.get("origin_transport_ref", "") or ""),
                "origin_agent_id": task["origin_agent_id"],
                "target_agent_id": task["target_agent_id"],
            })

    def report_management_result(
        self,
        agent_token: str,
        request_id: str,
        payload: ManagementResult,
    ) -> ManagementResult:
        now = utcnow_iso()
        validated_result = validated_management_result(
            payload.model_dump(mode="json", by_alias=True) if hasattr(payload, "model_dump") else payload
        )
        if validated_result.request_id != request_id:
            raise ValueError("request_id must match the requested management result")
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.management_requests WHERE request_id = %s",
                    (request_id,),
                )
                request_row = cur.fetchone()
            if request_row is None:
                raise KeyError(request_id)
            if str(request_row["target_agent_id"] or "") != str(row["agent_id"] or ""):
                raise PermissionError("Management request does not belong to this agent")
            completed_at = validated_result.completed_at or now
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.management_requests
                    SET status = %s, result_json = %s, error_code = %s, error_detail = %s, completed_at = %s
                    WHERE request_id = %s
                    """,
                    (
                        "completed" if validated_result.success else "failed",
                        _jsonb(validated_result.model_dump(mode="json", by_alias=True)),
                        validated_result.error_code,
                        validated_result.error_detail,
                        completed_at,
                        request_id,
                    ),
                )
        return validated_result

    def get_management_result(self, request_id: str) -> ManagementResult | None:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT result_json FROM {_SCHEMA}.management_requests WHERE request_id = %s",
                    (request_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            payload = decode_json_field(row.get("result_json"), None)
            if not payload:
                return None
            return validated_management_result(payload)

    def deregister(self, agent_token: str) -> AgentRecord:
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
        return _record(
            AgentRecord,
            {"agent_id": row["agent_id"], "connectivity_state": "offline"},
        )

    def list_agents(
        self,
        *,
        for_agent_id: str | None = None,
        cursor: int = 0,
        limit: int = 25,
        q: str = "",
        connectivity_state: str = "",
    ) -> list[AgentRecord]:
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

    def get_agent_runtime_health(self, agent_id: str) -> RuntimeHealthDetailRecord | None:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT * FROM {_SCHEMA}.agents WHERE agent_id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
            if row is None:
                return None
            detail = runtime_health_detail(
                row.get("runtime_health_json"),
                self._runtime_worker_rows(conn, agent_id),
            )
            return _record(RuntimeHealthDetailRecord, detail) if detail is not None else None

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
    ) -> ConversationRecord:
        if not origin_channel or not origin_channel.strip():
            raise ValueError("origin_channel must not be empty")
        if not external_conversation_ref or not external_conversation_ref.strip():
            raise ValueError("external_conversation_ref must not be empty")
        now = utcnow_iso()

        with self._connect() as conn, _write_tx(conn):
            actual_id = self._ensure_conversation_in_tx(
                conn,
                target_agent_id=target_agent_id,
                title=title,
                conversation_type="conversation",
                origin_channel=origin_channel,
                external_conversation_ref=external_conversation_ref,
                now=now,
            )
        return self.get_conversation(actual_id)

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "", conversation_type: str = "") -> list[ConversationRecord]:
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
                    params: list[object] = list(hit_ids)
                    if for_agent_id is not None:
                        where_clauses.append("c.target_agent_id = %s")
                        params.append(for_agent_id)
                    if status:
                        where_clauses.append("c.status = %s")
                        params.append(status)
                    if conversation_type:
                        where_clauses.append("c.conversation_type = %s")
                        params.append(conversation_type)
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
                        GROUP BY c.conversation_id, c.target_agent_id, c.title, c.conversation_type, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
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
                    params_list: list[object] = []
                    where_clauses_list: list[str] = []
                    if for_agent_id is not None:
                        where_clauses_list.append("c.target_agent_id = %s")
                        params_list.append(for_agent_id)
                    if status:
                        where_clauses_list.append("c.status = %s")
                        params_list.append(status)
                    if conversation_type:
                        where_clauses_list.append("c.conversation_type = %s")
                        params_list.append(conversation_type)
                    if where_clauses_list:
                        sql += " WHERE " + " AND ".join(where_clauses_list)
                    sql += """
                        GROUP BY c.conversation_id, c.target_agent_id, c.title, c.conversation_type, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
                        ORDER BY c.updated_at DESC
                        LIMIT %s OFFSET %s
                    """
                    params_list.extend([fetch_limit, cursor])
                    cur.execute(sql, params_list)
                    rows = cur.fetchall()
        return _records(ConversationRecord, [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "conversation_type": row["conversation_type"] or "conversation",
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "origin_channel": row["origin_channel"],
                "external_conversation_ref": row["external_conversation_ref"],
                "event_count": int(row["event_count"] or 0),
            }
            for row in rows
        ])

    def get_conversation(self, conversation_id: str) -> ConversationRecord:
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
                    GROUP BY c.conversation_id, c.target_agent_id, c.title, c.conversation_type, c.origin_channel, c.external_conversation_ref, c.status, c.created_at, c.updated_at, a.display_name
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
        return _record(ConversationRecord, {
            "conversation_id": row["conversation_id"],
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "target_name": row["target_name"] or "",
            "title": row["title"],
            "conversation_type": row["conversation_type"] or "conversation",
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "origin_channel": row["origin_channel"],
            "external_conversation_ref": row["external_conversation_ref"],
            "event_count": int(row["event_count"] or 0),
            "linked_routed_tasks": tasks,
        })

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[UsageSummaryRecord]:
        with self._connect() as conn:
            with _cur(conn) as cur:
                if until_iso:
                    cur.execute(
                        f"""
                        SELECT e.conversation_id, e.metadata_json, e.created_at, c.title
                        FROM {_SCHEMA}.events e
                        LEFT JOIN {_SCHEMA}.conversations c ON c.conversation_id = e.conversation_id
                        WHERE (
                            e.kind = 'provider.response'
                            OR (e.kind = 'task.status' AND e.metadata_json ? 'prompt_tokens')
                        ) AND e.created_at >= %s AND e.created_at <= %s
                        ORDER BY e.created_at
                        """,
                        (since_iso, until_iso),
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT e.conversation_id, e.metadata_json, e.created_at, c.title
                        FROM {_SCHEMA}.events e
                        LEFT JOIN {_SCHEMA}.conversations c ON c.conversation_id = e.conversation_id
                        WHERE (
                            e.kind = 'provider.response'
                            OR (e.kind = 'task.status' AND e.metadata_json ? 'prompt_tokens')
                        ) AND e.created_at >= %s
                        ORDER BY e.created_at
                        """,
                        (since_iso,),
                    )
                rows = cur.fetchall()
        return _records(UsageSummaryRecord, [
            {
                "conversation_id": row["conversation_id"],
                "title": row["title"] or "",
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ])

    def get_summary(self, *, now_iso: str) -> RegistrySummaryRecord:
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
        return _record(RegistrySummaryRecord, {
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
        })

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[ApprovalRecord]:
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
                params: list[object] = []
                if for_agent_id is not None:
                    sql += " AND c.target_agent_id = %s"
                    params.append(for_agent_id)
                sql += " ORDER BY e.created_at DESC LIMIT %s OFFSET %s"
                params.extend([fetch_limit, cursor])
                cur.execute(sql, params)
                rows = cur.fetchall()
        return _records(ApprovalRecord, [
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
        ])

    def search_conversations(self, q: str, limit: int = 20) -> list[ConversationSearchHitRecord]:
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
        return _records(
            ConversationSearchHitRecord,
            [{"conversation_id": row["conversation_id"], "snippet": row["snippet"]} for row in rows],
        )

    def add_conversation_message(self, conversation_id: str, text: str) -> MessageRecord:
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
                inserted_event = _record(EventRecord, {
                    "seq": evt_row["seq"],
                    "event_id": evt_row["event_id"],
                    "conversation_id": evt_row["conversation_id"],
                    "agent_id": evt_row["agent_id"],
                    "kind": evt_row["kind"],
                    "actor": evt_row["actor"],
                    "content": evt_row["content"],
                    "metadata": json.loads(evt_row["metadata_json"]) if isinstance(evt_row["metadata_json"], str) else evt_row["metadata_json"],
                    "created_at": evt_row["created_at"],
                })
        return _record(
            MessageRecord,
            {"conversation_id": conversation_id, "accepted": True, "event": inserted_event},
        )

    def add_conversation_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        validated_envelope = validated_conversation_action(envelope)
        action_payload = validated_action_payload(validated_envelope)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT target_agent_id, origin_channel, external_conversation_ref, title FROM {_SCHEMA}.conversations WHERE conversation_id = %s",
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
            bot_key = str(agent_row["bot_key"] or "").strip() if agent_row is not None else ""
            if not bot_key:
                raise ValueError(
                    f"Unknown agent or missing bot_key: {conversation['target_agent_id']}"
                )
            now = utcnow_iso()
            inserted_event = None
            routed_tasks: list[dict[str, object]] = []
            duplicate = False

            def _event__row(event_id: str) -> EventRecord | None:
                with _cur(conn) as cur:
                    cur.execute(
                        f"SELECT seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at FROM {_SCHEMA}.events WHERE event_id = %s",
                        (event_id,),
                    )
                    row = cur.fetchone()
                if row is None:
                    return None
                return _record(EventRecord, {
                    "seq": row["seq"],
                    "event_id": row["event_id"],
                    "conversation_id": row["conversation_id"],
                    "agent_id": row["agent_id"],
                    "kind": row["kind"],
                    "actor": row["actor"],
                    "content": row["content"],
                    "metadata": json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"],
                    "created_at": row["created_at"],
                })

            if validated_envelope.action in {"approve", "reject", "retry_allow", "retry_skip", "recovery_discard", "recovery_replay", "cancel_conversation"}:
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
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s, status = %s WHERE conversation_id = %s",
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
                            "decision": (
                                "rejected"
                                if validated_envelope.action in {"reject", "retry_skip", "recovery_discard"}
                                else "approved"
                            ),
                        },
                        created_at=now,
                    )
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (now, conversation_id),
                        )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event__row(validated_envelope.action_id)
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    event=inserted_event,
                )

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
                    origin_transport_ref=str(proposal.origin_transport_ref or ""),
                    authorized_actor_key=str(proposal.authorized_actor_key or ""),
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
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (now, conversation_id),
                    )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event__row(delegation_evt["event_id"])
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=validated_envelope.action_id,
                    event=inserted_event,
                )

            if validated_envelope.action == "approve_delegation":
                proposal_id = action_payload.proposal_id
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        SELECT * FROM {_SCHEMA}.events
                        WHERE conversation_id = %s
                          AND kind = %s
                          AND metadata_json->>'proposal_id' = %s
                        ORDER BY seq DESC
                        LIMIT 1
                        """,
                        (conversation_id, "delegation.proposed", proposal_id),
                    )
                    proposal_row = cur.fetchone()
                if proposal_row is None:
                    raise ValueError(f"Unknown delegation proposal: {proposal_id}")
                proposal_metadata = decode_json_field(proposal_row["metadata_json"], {})
                proposal_origin_transport_ref = str(
                    proposal_metadata.get("origin_transport_ref", "") or ""
                )
                proposal_authorized_actor_key = str(
                    proposal_metadata.get("authorized_actor_key", "") or ""
                )
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
                        "origin_transport_ref": (
                            proposal_origin_transport_ref
                            or str(conversation["external_conversation_ref"] or "")
                        ),
                        "authorized_actor_key": proposal_authorized_actor_key,
                        "external_conversation_ref": routed_task_external_conversation_ref(
                            stable_routed_task_id(conversation_id, validated_envelope.action_id, index)
                        ),
                        "origin_agent_id": conversation["target_agent_id"],
                        "target_agent_id": resolved_target["agent_id"],
                        "title": draft.title,
                        "instructions": draft.instructions,
                        "context": dict(draft.context),
                        "requested_capabilities": list(draft.requested_capabilities),
                        "priority": draft.priority,
                        "created_at": now,
                    }
                    self._create_routed_task_in_tx(conn, request, now=now)
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
                    origin_transport_ref=proposal_origin_transport_ref,
                    authorized_actor_key=proposal_authorized_actor_key,
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
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (now, conversation_id),
                    )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event__row(f"delegation.submitted:{validated_envelope.action_id}")
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=proposal_id,
                    routed_tasks=routed_tasks,
                    event=inserted_event,
                )

            if validated_envelope.action == "direct_assign":
                assignment = action_payload
                operator_message = direct_assignment_message_text(assignment)
                routed_task_id = stable_routed_task_id(conversation_id, validated_envelope.action_id, 0)
                resolved_target = self._resolve_selector(conn, assignment.selector)
                inserted_events: list[EventRecord] = []
                message_event = self._insert_event(
                    conn,
                    event_id=f"message.user:{validated_envelope.action_id}",
                    conversation_id=conversation_id,
                    agent_id="",
                    kind="message.user",
                    actor="operator",
                    content=operator_message,
                    metadata={
                        "source_action": "direct_assign",
                        "selector_kind": assignment.selector.kind,
                        "selector_value": assignment.selector.value,
                        "routed_task_id": routed_task_id,
                    },
                    created_at=now,
                )
                if message_event is not None:
                    inserted_events.append(message_event)
                request = {
                    "routed_task_id": routed_task_id,
                    "parent_conversation_id": conversation_id,
                    "origin_transport_ref": (
                        str(assignment.origin_transport_ref or "")
                        or str(conversation["external_conversation_ref"] or "")
                    ),
                    "authorized_actor_key": str(assignment.authorized_actor_key or ""),
                    "external_conversation_ref": routed_task_external_conversation_ref(routed_task_id),
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
                if created.get("event") is not None:
                    inserted_events.append(created["event"])
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
                    origin_transport_ref=str(assignment.origin_transport_ref or ""),
                    authorized_actor_key=str(assignment.authorized_actor_key or ""),
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
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (now, conversation_id),
                    )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event__row(f"delegation.submitted:{validated_envelope.action_id}")
                elif inserted_event is not None:
                    inserted_events.append(inserted_event)
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    proposal_id=validated_envelope.action_id,
                    routed_tasks=routed_tasks,
                    inserted_events=inserted_events,
                    event=inserted_event,
                )

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
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                            (now, conversation_id),
                        )
                    duplicate = inserted_event is None
                    if inserted_event is None:
                        inserted_event = _event__row(validated_envelope.action_id)
                    return CoordinationActionResult(
                        conversation_id=conversation_id,
                        action_id=validated_envelope.action_id,
                        action=validated_envelope.action,
                        accepted=True,
                        duplicate=duplicate,
                        proposal_id=action_payload.proposal_id,
                        event=inserted_event,
                    )

                with _cur(conn) as cur:
                    cur.execute(
                        f"SELECT * FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s AND parent_conversation_id = %s",
                        (action_payload.routed_task_id, conversation_id),
                    )
                    task_row = cur.fetchone()
                if task_row is None:
                    raise ValueError(f"Unknown task {action_payload.routed_task_id} for conversation {conversation_id}")
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
                    decision = apply_task_transition(
                        self._task_snapshot__row(task_row),
                        TaskTransitionRequest(
                            transition="cancel",
                            actor_role="operator",
                            transition_id=validated_envelope.action_id,
                            occurred_at=now,
                        ),
                    )
                    if not decision.ok:
                        raise ValueError(decision.reason or f"Task {action_payload.routed_task_id} cannot be cancelled")
                    with _cur(conn) as cur:
                        cur.execute(
                            f"UPDATE {_SCHEMA}.routed_tasks SET status = %s, summary = %s, updated_at = %s WHERE routed_task_id = %s",
                            ("cancelled", "Cancelled by operator.", now, action_payload.routed_task_id),
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
                            "routed_task_id": action_payload.routed_task_id,
                            "status": "cancelled",
                            "transition_id": validated_envelope.action_id,
                        },
                        created_at=now,
                    )
                    routed_tasks.append({
                        "routed_task_id": action_payload.routed_task_id,
                        "target_agent_id": str(task_row["target_agent_id"] or ""),
                        "authority_ref": "",
                        "title": str(task_row["title"] or ""),
                        "status": "cancelled",
                    })
                with _cur(conn) as cur:
                    cur.execute(
                        f"UPDATE {_SCHEMA}.conversations SET updated_at = %s WHERE conversation_id = %s",
                        (now, conversation_id),
                    )
                duplicate = inserted_event is None
                if inserted_event is None:
                    inserted_event = _event__row(validated_envelope.action_id)
                return CoordinationActionResult(
                    conversation_id=conversation_id,
                    action_id=validated_envelope.action_id,
                    action=validated_envelope.action,
                    accepted=True,
                    duplicate=duplicate,
                    routed_tasks=routed_tasks,
                    event=inserted_event,
                )

            raise ValueError(f"Unsupported action: {validated_envelope.action}")

    def list_tasks(
        self,
        *,
        for_agent_id: str | None = None,
        parent_conversation_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
    ) -> list[TaskRecord]:
        fetch_limit = limit + 1
        with self._connect() as conn:
            with _cur(conn) as cur:
                sql = f"""
                    SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                    FROM {_SCHEMA}.routed_tasks t
                    LEFT JOIN {_SCHEMA}.agents origin ON origin.agent_id = t.origin_agent_id
                    LEFT JOIN {_SCHEMA}.agents target ON target.agent_id = t.target_agent_id
                """
                params: list[object] = []
                where_clauses: list[str] = []
                if for_agent_id is not None:
                    where_clauses.append("(t.origin_agent_id = %s OR t.target_agent_id = %s)")
                    params.extend([for_agent_id, for_agent_id])
                if parent_conversation_id:
                    where_clauses.append("t.parent_conversation_id = %s")
                    params.append(parent_conversation_id)
                if status:
                    where_clauses.append("t.status = %s")
                    params.append(status)
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)
                sql += " ORDER BY t.updated_at DESC LIMIT %s OFFSET %s"
                params.extend([fetch_limit, cursor])
                cur.execute(sql, params)
                rows = cur.fetchall()
        return _records(TaskRecord, [
            {
                "routed_task_id": row["routed_task_id"],
                "parent_conversation_id": row["parent_conversation_id"],
                "origin_transport_ref": decode_json_field(row["request_json"], {}).get("origin_transport_ref", ""),
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
        ])

    def get_task(self, routed_task_id: str) -> TaskRecord:
        with self._connect() as conn:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                    FROM {_SCHEMA}.routed_tasks t
                    LEFT JOIN {_SCHEMA}.agents origin ON origin.agent_id = t.origin_agent_id
                    LEFT JOIN {_SCHEMA}.agents target ON target.agent_id = t.target_agent_id
                    WHERE t.routed_task_id = %s
                    """,
                    (routed_task_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(routed_task_id)
        return _record(TaskRecord, {
            "routed_task_id": row["routed_task_id"],
            "parent_conversation_id": row["parent_conversation_id"],
            "origin_transport_ref": decode_json_field(row["request_json"], {}).get("origin_transport_ref", ""),
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
        })

    def publish_events(
        self,
        agent_token: str,
        conversation_id: str,
        events: list[RegistryRecordModel],
    ) -> PublishEventsResult:
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
            inserted_events: list[EventRecord] = []
            for event_model in events:
                event = (
                    event_model.model_dump(mode="json")
                    if hasattr(event_model, "model_dump")
                    else event_model
                )
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
                            inserted_events.append(_record(EventRecord, {
                                "seq": ev_row["seq"],
                                "event_id": ev_row["event_id"],
                                "conversation_id": ev_row["conversation_id"],
                                "agent_id": ev_row["agent_id"],
                                "kind": ev_row["kind"],
                                "actor": ev_row["actor"],
                                "content": ev_row["content"],
                                "metadata": meta if isinstance(meta, dict) else json.loads(meta) if meta else {},
                                "created_at": str(ev_row["created_at"]),
                            }))
                    else:
                        skipped += 1
        return _record(
            PublishEventsResult,
            {
                "inserted": inserted,
                "skipped": skipped,
                "inserted_ids": list(inserted_ids),
                "inserted_events": inserted_events,
            },
        )

    def list_events(
        self,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        if before_seq and after_seq:
            raise ValueError("before_seq and after_seq cannot both be set")
        kinds = [item.strip() for item in kind.split(",") if item.strip()]
        clauses = ["conversation_id = %s"]
        params: list[object] = [conversation_id]
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
        return _record(
            EventPageRecord,
            {
                "events": _records(EventRecord, events_list),
                "has_more_before": has_more_before,
                "next_before_seq": events_list[0]["seq"] if has_more_before and events_list else None,
                "next_after_seq": events_list[-1]["seq"] if events_list else None,
            },
        )

    def list_messages(self, conversation_id: str, *, cursor: int = 0, limit: int = 50) -> MessagePageRecord:
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
        return _record(
            MessagePageRecord,
            {"events": _records(EventRecord, events_list), "next_cursor": next_cursor},
        )

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50, conversation_type: str = "") -> list[ConversationRecord]:
        fetch_limit = limit + 1
        effective_agent_id = for_agent_id if for_agent_id is not None else agent_id
        with self._connect() as conn:
            with _cur(conn) as cur:
                sql = f"""
                    SELECT c.*, a.display_name AS target_name
                    FROM {_SCHEMA}.conversations c
                    LEFT JOIN {_SCHEMA}.agents a ON a.agent_id = c.target_agent_id
                    WHERE c.target_agent_id = %s
                """
                params: list[object] = [effective_agent_id]
                if conversation_type:
                    sql += " AND c.conversation_type = %s"
                    params.append(conversation_type)
                sql += """
                    ORDER BY c.updated_at DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([fetch_limit, cursor])
                cur.execute(sql, params)
                rows = cur.fetchall()
        return _records(ConversationRecord, [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_name": row["target_name"] or "",
                "title": row["title"],
                "conversation_type": row["conversation_type"] or "conversation",
                "origin_channel": row["origin_channel"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ])

    def get_agent_status(self, agent_id: str) -> AgentStatusRecord | None:
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
        return AgentStatusRecord(
            **agent.model_dump(mode="json"),
            workers=workers,
            active_conversations=active_conversations,
            recent_errors=recent_errors,
        )

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[UsageSummaryRecord]:
        with self._connect() as conn:
            sql = (
                f"SELECT e.*, c.title AS conversation_title "
                f"FROM {_SCHEMA}.events e "
                f"LEFT JOIN {_SCHEMA}.conversations c ON c.conversation_id = e.conversation_id "
                f"WHERE (e.kind = 'provider.response' OR (e.kind = 'task.status' AND e.metadata_json ? 'prompt_tokens'))"
            )
            params: list[object] = []
            if agent_id:
                sql += " AND e.agent_id = %s"
                params.append(agent_id)
            if conversation_id:
                sql += " AND e.conversation_id = %s"
                params.append(conversation_id)
            if since:
                sql += " AND e.created_at >= %s"
                params.append(since)
            if until:
                sql += " AND e.created_at <= %s"
                params.append(until)
            sql += " ORDER BY e.created_at"
            with _cur(conn) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return _records(UsageSummaryRecord, [
            {
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "title": row["conversation_title"] or "",
                "agent_id": row["agent_id"],
                "metadata": decode_json_field(row["metadata_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ])

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
    def _parse_json(raw: object, default: object) -> object:
        if raw is None:
            return default
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    @staticmethod
    def _stable_json(value: object) -> str:
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

    def _skill_row_to_track(self, row: dict[str, object]) -> RuntimeSkillTrackRecord:
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

    def _skill_rows_for_slug(self, slug: str, *, runtime_only: bool) -> list[dict[str, object]]:
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
