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
    SkillRevisionRecord,
)

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .capability_service import (
    query_capabilities,
    requested_routed_capabilities,
)
from .postgres import get_connection
from .exact_aliases import matches_exact_alias
from .store_dialect import StoreDialect
from .store_shared.agents import (
    get_agent_runtime_health as shared_get_agent_runtime_health,
    get_agent_status as shared_get_agent_status,
    list_agents as shared_list_agents,
)
from .store_shared.conversations import (
    get_conversation as shared_get_conversation,
    list_agent_conversations as shared_list_agent_conversations,
    list_conversations as shared_list_conversations,
)
from .store_shared.content import (
    append_provider_guidance_approval as shared_append_provider_guidance_approval,
    append_skill_approval as shared_append_skill_approval,
    apply_provider_guidance_lifecycle_transition as shared_apply_provider_guidance_lifecycle_transition,
    apply_skill_lifecycle_transition as shared_apply_skill_lifecycle_transition,
    clear_published_provider_guidance_revision as shared_clear_published_provider_guidance_revision,
    clear_published_skill_revision as shared_clear_published_skill_revision,
    delete_skill_track as shared_delete_skill_track,
    get_latest_provider_guidance_approval_action as shared_get_latest_provider_guidance_approval_action,
    get_latest_skill_approval_action as shared_get_latest_skill_approval_action,
    get_provider_guidance as shared_get_provider_guidance,
    list_provider_guidance_approvals as shared_list_provider_guidance_approvals,
    list_provider_guidance_revisions as shared_list_provider_guidance_revisions,
    list_runtime_skill_summaries as shared_list_runtime_skill_summaries,
    list_skill_approvals as shared_list_skill_approvals,
    list_skill_revisions as shared_list_skill_revisions,
    list_skill_summaries as shared_list_skill_summaries,
    list_skill_tracks as shared_list_skill_tracks,
    replace_provider_guidance as shared_replace_provider_guidance,
    replace_skill_track as shared_replace_skill_track,
    resolve_provider_guidance as shared_resolve_provider_guidance,
    resolve_runtime_skill as shared_resolve_runtime_skill,
    resolve_skill as shared_resolve_skill,
    set_provider_guidance_revision_status as shared_set_provider_guidance_revision_status,
    set_published_provider_guidance_revision as shared_set_published_provider_guidance_revision,
    set_published_skill_revision as shared_set_published_skill_revision,
    set_skill_revision_status as shared_set_skill_revision_status,
    upsert_provider_guidance_draft as shared_upsert_provider_guidance_draft,
    upsert_skill_draft as shared_upsert_skill_draft,
)
from .store_shared.delivery import (
    ack as shared_ack,
    poll as shared_poll,
)
from .store_shared.summary import (
    get_summary as shared_get_summary,
    get_usage as shared_get_usage,
    get_usage_summary as shared_get_usage_summary,
    list_approvals as shared_list_approvals,
)
from .store_shared.routed_tasks import (
    create_routed_task as shared_create_routed_task,
    update_routed_task_result as shared_update_routed_task_result,
    update_routed_task_status as shared_update_routed_task_status,
)
from .store_shared.tasks import (
    get_task as shared_get_task,
    list_tasks as shared_list_tasks,
)
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
    validated_agent_card_payload,
    validated_conversation_action,
    validated_conversation_message_text,
    validated_heartbeat_payload,
    validated_management_request,
    validated_management_result,
    validated_register_payload,
    validated_routed_task_request,
    validated_search_query,
    decode_json_field,
    canonical_registry_connectivity_state,
    effective_connectivity_state,
    hash_agent_token,
    offline_before_iso,
    require_registry_scope,
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


class _PostgresStoreDialect(StoreDialect):
    def placeholder(self, index: int) -> str:
        return "%s"

    def qualify(self, table: str) -> str:
        return f"{_SCHEMA}.{table}"

    def json_text(self, json_expr: str, key: str) -> str:
        return f"{json_expr}->>'{key}'"

    def usage_token_predicate(self, metadata_expr: str) -> str:
        return f"{metadata_expr} ? 'prompt_tokens'"

    def execute(self, conn, sql: str, params=()):
        with _cur(conn) as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def fetchone(self, conn, sql: str, params=()):
        with _cur(conn) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else dict(row)

    def fetchall(self, conn, sql: str, params=()):
        with _cur(conn) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(row) for row in rows]


_POSTGRES_STORE_DIALECT = _PostgresStoreDialect()


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
        return offline_before_iso()

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
                        canonical_registry_connectivity_state(card.get("connectivity_state", "degraded")),
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
                        canonical_registry_connectivity_state(
                            register_payload.connectivity_state or row["connectivity_state"]
                        ),
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
                        canonical_registry_connectivity_state(
                            heartbeat_payload.connectivity_state or row["connectivity_state"]
                        ),
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
                            THEN 'disconnected'
                            WHEN connectivity_state = 'offline' THEN 'disconnected'
                            ELSE connectivity_state
                        END != 'disconnected'
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
                            THEN 'disconnected'
                            WHEN a.connectivity_state = 'offline' THEN 'disconnected'
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
                            WHEN a.last_heartbeat_at != '' AND a.last_heartbeat_at < %s THEN 'disconnected'
                            WHEN a.connectivity_state = 'offline' THEN 'disconnected'
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
            "recipient_conversation_id": recipient_conversation_id,
            "recipient_event": recipient_event,
        }

    def create_routed_task(self, request: RegistryRecordModel) -> TaskRecord:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_create_routed_task(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                request=request,
                now=now,
                create_routed_task_in_tx=self._create_routed_task_in_tx,
            )

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> DeliveryPollResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            return shared_poll(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_row=row,
                cursor=cursor,
                limit=limit,
                now=now,
                registry_epoch=self._registry_epoch(conn),
                task_snapshot_row=self._task_snapshot__row,
            )

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> AckResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            return shared_ack(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                target_agent_id=row["agent_id"],
                delivery_ids=delivery_ids,
                classification=classification,
                now=now,
            )

    def update_routed_task_status(
        self,
        agent_token: str,
        routed_task_id: str,
        payload: RegistryRecordModel,
    ) -> TaskRecord:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_update_routed_task_status(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                require_coordination_scope=lambda agent_row: require_registry_scope(agent_row, {"coordination", "full"}),
                task_snapshot_row=self._task_snapshot__row,
                insert_event=self._insert_event,
                ensure_conversation_in_tx=self._ensure_conversation_in_tx,
                agent_token=agent_token,
                routed_task_id=routed_task_id,
                payload=payload,
                now=now,
            )

    def update_routed_task_result(
        self,
        agent_token: str,
        routed_task_id: str,
        payload: RegistryRecordModel,
    ) -> TaskRecord:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_update_routed_task_result(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                require_coordination_scope=lambda agent_row: require_registry_scope(agent_row, {"coordination", "full"}),
                task_snapshot_row=self._task_snapshot__row,
                insert_event=self._insert_event,
                ensure_conversation_in_tx=self._ensure_conversation_in_tx,
                create_delivery=self._create_delivery,
                json_param=_jsonb,
                agent_token=agent_token,
                routed_task_id=routed_task_id,
                payload=payload,
                now=now,
            )

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
                    SET connectivity_state = 'disconnected', updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_token = %s
                    """,
                    (now, now, agent_token_hash),
                )
        return _record(
            AgentRecord,
            {"agent_id": row["agent_id"], "connectivity_state": "disconnected"},
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
        with self._connect() as conn:
            return shared_list_agents(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                row_to_agent=self._row_to_agent,
                for_agent_id=for_agent_id,
                cursor=cursor,
                limit=limit,
                q=q,
                connectivity_state=connectivity_state,
            )

    def get_agent_runtime_health(self, agent_id: str) -> RuntimeHealthDetailRecord | None:
        with self._connect() as conn:
            detail = shared_get_agent_runtime_health(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
                runtime_worker_rows=self._runtime_worker_rows,
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
        if q and len(q) >= 3:
            search_hits = self.search_conversations(q, limit=fetch_limit + cursor)
            hit_ids = [h["conversation_id"] for h in search_hits]
            if not hit_ids:
                return []
            with self._connect() as conn:
                return shared_list_conversations(
                    conn,
                    dialect=_POSTGRES_STORE_DIALECT,
                    for_agent_id=for_agent_id,
                    cursor=cursor,
                    limit=limit,
                    status=status,
                    conversation_type=conversation_type,
                    search_hit_ids=hit_ids,
                )
        with self._connect() as conn:
            return shared_list_conversations(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                for_agent_id=for_agent_id,
                cursor=cursor,
                limit=limit,
                status=status,
                conversation_type=conversation_type,
            )

    def get_conversation(self, conversation_id: str) -> ConversationRecord:
        with self._connect() as conn:
            return shared_get_conversation(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                conversation_id=conversation_id,
            )

    def get_usage_summary(self, since_iso: str, until_iso: str = "") -> list[UsageSummaryRecord]:
        with self._connect() as conn:
            return shared_get_usage_summary(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                since_iso=since_iso,
                until_iso=until_iso,
            )

    def get_summary(self, *, now_iso: str) -> RegistrySummaryRecord:
        with self._connect() as conn:
            return shared_get_summary(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                now_iso=now_iso,
            )

    def list_approvals(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25) -> list[ApprovalRecord]:
        with self._connect() as conn:
            return shared_list_approvals(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                for_agent_id=for_agent_id,
                cursor=cursor,
                limit=limit,
            )

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
        completed_since_iso: str = "",
    ) -> list[TaskRecord]:
        with self._connect() as conn:
            return shared_list_tasks(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                for_agent_id=for_agent_id,
                parent_conversation_id=parent_conversation_id,
                cursor=cursor,
                limit=limit,
                status=status,
                completed_since_iso=completed_since_iso,
            )

    def get_task(self, routed_task_id: str) -> TaskRecord:
        with self._connect() as conn:
            return shared_get_task(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                routed_task_id=routed_task_id,
            )

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
        with self._connect() as conn:
            return shared_list_agent_conversations(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
                for_agent_id=for_agent_id,
                cursor=cursor,
                limit=limit,
                conversation_type=conversation_type,
            )

    def get_agent_status(self, agent_id: str) -> AgentStatusRecord | None:
        with self._connect() as conn:
            return shared_get_agent_status(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
                row_to_agent=self._row_to_agent,
                runtime_worker_rows=self._runtime_worker_rows,
            )

    def get_usage(self, *, agent_id: str = "", conversation_id: str = "", since: str = "", until: str = "") -> list[UsageSummaryRecord]:
        with self._connect() as conn:
            return shared_get_usage(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
                conversation_id=conversation_id,
                since=since,
                until=until,
            )

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

    # ------------------------------------------------------------------
    # Skill / guidance persistence (registry-owned content store)
    # ------------------------------------------------------------------

    def replace_skill_track(self, record: RuntimeSkillTrackRecord) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_replace_skill_track(conn, dialect=_POSTGRES_STORE_DIALECT, track=record)

    def delete_skill_track(
        self,
        slug: str,
        *,
        source_kind: str,
        source_uri: str = "",
        owner_actor: str = "",
    ) -> bool:
        with self._connect() as conn, _write_tx(conn):
            return shared_delete_skill_track(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def list_skill_tracks(self, slug: str) -> list[RuntimeSkillTrackRecord]:
        with self._connect() as conn:
            return shared_list_skill_tracks(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def resolve_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        with self._connect() as conn:
            return shared_resolve_skill(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def resolve_runtime_skill(self, slug: str) -> RuntimeSkillTrackRecord | None:
        with self._connect() as conn:
            return shared_resolve_runtime_skill(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def list_skill_summaries(self) -> list[RuntimeSkillSummary]:
        with self._connect() as conn:
            return shared_list_skill_summaries(conn, dialect=_POSTGRES_STORE_DIALECT)

    def list_runtime_skill_summaries(self) -> list[RuntimeSkillSummary]:
        with self._connect() as conn:
            return shared_list_runtime_skill_summaries(conn, dialect=_POSTGRES_STORE_DIALECT)

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_upsert_skill_draft(conn, dialect=_POSTGRES_STORE_DIALECT, track=record)

    def list_skill_revisions(self, slug: str) -> list[SkillRevisionRecord]:
        with self._connect() as conn:
            return shared_list_skill_revisions(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def list_skill_approvals(self, slug: str) -> list[LifecycleApprovalRecord]:
        with self._connect() as conn:
            return shared_list_skill_approvals(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

    def get_latest_skill_approval_action(self, slug: str, revision_id: str) -> str:
        with self._connect() as conn:
            return shared_get_latest_skill_approval_action(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                slug=slug,
                revision_id=revision_id,
            )

    def append_skill_approval(
        self,
        slug: str,
        revision_id: str,
        *,
        action: str,
        actor: str,
        note: str = "",
    ) -> LifecycleApprovalRecord:
        with self._connect() as conn, _write_tx(conn):
            return shared_append_skill_approval(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                slug=slug,
                revision_id=revision_id,
                action=action,
                actor=actor,
                note=note,
            )

    def set_skill_revision_status(self, slug: str, revision_id: str, status: str) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_set_skill_revision_status(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                slug=slug,
                revision_id=revision_id,
                status=status,
            )

    def set_published_skill_revision(self, slug: str, revision_id: str) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_set_published_skill_revision(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                slug=slug,
                revision_id=revision_id,
            )

    def clear_published_skill_revision(self, slug: str) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_clear_published_skill_revision(conn, dialect=_POSTGRES_STORE_DIALECT, slug=slug)

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
        with self._connect() as conn, _write_tx(conn):
            return shared_apply_skill_lifecycle_transition(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                slug=slug,
                revision_id=revision_id,
                set_status=set_status,
                published_pointer=published_pointer,
                approval_action=approval_action,
                actor=actor,
                note=note,
            )

    def replace_provider_guidance(self, record: ProviderGuidanceTrackRecord) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_replace_provider_guidance(conn, dialect=_POSTGRES_STORE_DIALECT, track=record)

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_upsert_provider_guidance_draft(conn, dialect=_POSTGRES_STORE_DIALECT, track=record)

    def get_provider_guidance(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            return shared_get_provider_guidance(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )

    def resolve_provider_guidance(
        self,
        provider: str,
        *,
        instance_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        with self._connect() as conn:
            return shared_resolve_provider_guidance(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                instance_key=instance_key,
            )

    def list_provider_guidance_revisions(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        with self._connect() as conn:
            return shared_list_provider_guidance_revisions(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )

    def list_provider_guidance_approvals(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        with self._connect() as conn:
            return shared_list_provider_guidance_approvals(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )

    def get_latest_provider_guidance_approval_action(
        self,
        provider: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str:
        with self._connect() as conn:
            return shared_get_latest_provider_guidance_approval_action(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                revision_id=revision_id,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )

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
        with self._connect() as conn, _write_tx(conn):
            return shared_append_provider_guidance_approval(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                revision_id=revision_id,
                action=action,
                actor=actor,
                note=note,
                scope_kind=scope_kind,
                scope_key=scope_key,
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
            shared_set_provider_guidance_revision_status(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                revision_id=revision_id,
                status=status,
                scope_kind=scope_kind,
                scope_key=scope_key,
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
            shared_set_published_provider_guidance_revision(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                revision_id=revision_id,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )

    def clear_published_provider_guidance_revision(
        self,
        provider: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        with self._connect() as conn, _write_tx(conn):
            shared_clear_published_provider_guidance_revision(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                scope_kind=scope_kind,
                scope_key=scope_key,
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
        with self._connect() as conn, _write_tx(conn):
            return shared_apply_provider_guidance_lifecycle_transition(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                provider=provider,
                revision_id=revision_id,
                set_status=set_status,
                published_pointer=published_pointer,
                approval_action=approval_action,
                actor=actor,
                note=note,
                scope_kind=scope_kind,
                scope_key=scope_key,
            )
