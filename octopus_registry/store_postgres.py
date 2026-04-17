"""Postgres-backed registry store."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillSummary,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)
from octopus_sdk.protocols import (
    PROTOCOL_DEFAULT_OPERATOR_REF,
    PROTOCOL_DEFAULT_RETENTION_DAYS,
    PROTOCOL_DEFAULT_RUN_ORG_ID,
    PROTOCOL_DEFAULT_VISIBILITY,
    ProtocolAccessContextRecord,
    ProtocolArtifactObservationRecord,
    builtin_protocol_documents,
    evaluate_protocol_stage_timeout,
    protocol_dispatch_blocked_decision,
    evaluate_protocol_operator_action,
    protocol_dispatch_resolution_failed_decision,
    protocol_dispatch_started_decision,
    evaluate_protocol_task_result,
    ProtocolDefinitionDocumentRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolMutationRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
    ProtocolRunParticipantRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
    ProtocolTransitionRecord,
    ProtocolArtifactRecord,
    canonical_protocol_document,
    default_protocol_document_slug,
    protocol_dispatch_decision,
    protocol_retention_until,
    protocol_stage_internal_context,
    ProtocolStageTaskResultRecord,
    protocol_definition_content_hash,
    protocol_participant_session_key,
    render_protocol_stage_prompt,
    validate_protocol_document,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .routing_skill_service import (
    requested_routed_skills,
)
from .config import RegistryConfig, load_registry_config
from .postgres import get_connection
from .store_dialect import StoreDialect
from .store_shared.agents import (
    enroll as shared_enroll,
    get_agent_runtime_health as shared_get_agent_runtime_health,
    get_agent_status as shared_get_agent_status,
    heartbeat as shared_heartbeat,
    list_agents as shared_list_agents,
    register as shared_register,
    replace_runtime_health_workers as shared_replace_runtime_health_workers,
    resolve_agent_for_token as shared_resolve_agent_for_token,
    resolve_selector as shared_resolve_selector,
    row_to_agent as shared_row_to_agent,
    runtime_worker_rows as shared_runtime_worker_rows,
    search_agents as shared_search_agents,
)
from .store_shared.conversations import (
    add_conversation_action as shared_add_conversation_action,
    add_conversation_message as shared_add_conversation_message,
    create_conversation as shared_create_conversation,
    ensure_conversation_in_tx as shared_ensure_conversation_in_tx,
    insert_event as shared_insert_event,
    list_events as shared_list_events,
    list_messages as shared_list_messages,
    publish_events as shared_publish_events,
    touch_conversation as shared_touch_conversation,
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
    create_delivery as shared_create_delivery,
    create_management_request as shared_create_management_request,
    get_management_result as shared_get_management_result,
    poll as shared_poll,
    report_management_result as shared_report_management_result,
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
    PROTECTED_ROUTED_TASK_STATUSES,
    RoutingSkillDisabledError,
    routed_task_external_conversation_ref,
    validated_routed_task_request,
    hash_agent_token,
    offline_before_iso,
    require_registry_scope,
    utcnow_iso,
)
from octopus_sdk.registry.management import ManagementRequest, ManagementResult
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    AgentRecord,
    AgentStatusRecord,
    ApprovalRecord,
    RoutingSkillRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    ConversationRecord,
    ConversationSearchHitRecord,
    DeliveryPollResult,
    DeliveryRecord,
    EnrollmentResult,
    EventPageRecord,
    HealthSummary,
    MessageRecord,
    MessagePageRecord,
    PublishEventsResult,
    RegistryRecordModel,
    RegistryJsonRecord,
    RegistrySummaryRecord,
    RuntimeHealthDetailRecord,
    TargetSelector,
    TaskRecord,
    UsageSummaryRecord,
)
from octopus_sdk.task_protocol import RoutedTaskSnapshot

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

    def __init__(self, database_url: str, *, config: RegistryConfig | None = None) -> None:
        self.database_url = database_url
        self._config = config or load_registry_config()
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
                        "agent_registry schema not found. Run db-init to create the current schema."
                    )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.meta (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (_REGISTRY_EPOCH_KEY, uuid.uuid4().hex),
                )
            self._ensure_builtin_protocols(conn)
            conn.commit()

    def _ensure_builtin_protocols(self, conn) -> None:
        now = utcnow_iso()
        with _cur(conn) as cur:
            for document in builtin_protocol_documents():
                slug = default_protocol_document_slug(document)
                cur.execute(
                    f"SELECT protocol_id FROM {_SCHEMA}.protocol_definitions WHERE slug = %s",
                    (slug,),
                )
                if cur.fetchone() is not None:
                    continue
                protocol_id = uuid.uuid4().hex
                version_id = uuid.uuid4().hex
                payload = document.model_dump(mode="json")
                content_hash = protocol_definition_content_hash(document)
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_definitions (
                        protocol_id, slug, display_name, description, lifecycle_state,
                        current_version_id, owner_org_id, visibility, created_by, updated_by,
                        draft_definition_json, draft_content_hash, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'published', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        protocol_id,
                        slug,
                        document.display_name or slug,
                        document.description,
                        version_id,
                        PROTOCOL_DEFAULT_RUN_ORG_ID,
                        "registry_template",
                        "bootstrap",
                        "bootstrap",
                        _jsonb(payload),
                        content_hash,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_definition_versions (
                        protocol_definition_version_id, protocol_id, version, definition_json,
                        content_hash, validation_status, published_at, published_by, created_at
                    ) VALUES (%s, %s, 1, %s, %s, 'valid', %s, %s, %s)
                    """,
                    (
                        version_id,
                        protocol_id,
                        _jsonb(payload),
                        content_hash,
                        now,
                        "bootstrap",
                        now,
                    ),
                )

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

    def _token_row(self, conn, token: str) -> dict[str, object] | None:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT * FROM {_SCHEMA}.agents WHERE agent_token = %s",
                (hash_agent_token(token),),
            )
            return cur.fetchone()

    def _create_delivery(self, conn, **kwargs) -> DeliveryRecord:
        return shared_create_delivery(
            conn,
            dialect=_POSTGRES_STORE_DIALECT,
            json_param=_jsonb,
            **kwargs,
        )

    def _insert_event(self, conn, **kwargs) -> EventRecord | None:
        return shared_insert_event(
            conn,
            dialect=_POSTGRES_STORE_DIALECT,
            json_param=_jsonb,
            **kwargs,
        )

    def _ensure_conversation_in_tx(self, conn, **kwargs) -> str:
        return shared_ensure_conversation_in_tx(
            conn,
            dialect=_POSTGRES_STORE_DIALECT,
            **kwargs,
        )

    @staticmethod
    def _require_coordination_scope(agent_row) -> None:
        require_registry_scope(agent_row, {"coordination", "full"})

    def _runtime_worker_rows(self, conn, agent_id: str):
        return shared_runtime_worker_rows(
            conn,
            dialect=_POSTGRES_STORE_DIALECT,
            agent_id=agent_id,
        )

    def resolve_agent_for_token(self, agent_token: str) -> AgentRecord | None:
        with self._connect() as conn:
            return shared_resolve_agent_for_token(
                conn,
                token_row=self._token_row,
                agent_token=agent_token,
            )

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

    def enroll(self, requested_card: AgentCard) -> EnrollmentResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_enroll(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                ensure_unique_slug=self._ensure_unique_slug,
                registry_epoch=self._registry_epoch,
                requested_card=requested_card,
                now=now,
            )

    def assert_agent_scope(self, agent_token: str, required_scopes: set[str]) -> None:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            require_registry_scope(row, required_scopes)

    def register(self, agent_token: str, payload: AgentRegisterRequest) -> AgentRecord:
        with self._connect() as conn, _write_tx(conn):
            return shared_register(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                agent_token=agent_token,
                payload=payload,
            )

    def heartbeat(self, agent_token: str, payload: AgentHeartbeatRequest) -> HealthSummary:
        with self._connect() as conn, _write_tx(conn):
            result = shared_heartbeat(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                replace_runtime_health_workers=lambda inner_conn, **kwargs: shared_replace_runtime_health_workers(
                    inner_conn,
                    dialect=_POSTGRES_STORE_DIALECT,
                    **kwargs,
                ),
                agent_token=agent_token,
                payload=payload,
            )
            self._sweep_protocol_timeouts_in_tx(conn, now=utcnow_iso())
            return result

    def get_routing_skill_override(self, skill_name: str) -> bool | None:
        normalized = skill_name.strip().lower()
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

    def set_routing_skill_override(self, skill_name: str, enabled: bool, set_by: str = "ui") -> None:
        normalized = skill_name.strip().lower()
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

    def list_routing_skills(self) -> list[RoutingSkillRecord]:
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
                        SELECT lower(je.value) AS skill_key, je.value AS skill_name, live_agents.slug
                        FROM live_agents
                        CROSS JOIN LATERAL jsonb_array_elements_text(live_agents.skills_json) AS je(value)
                    )
                    SELECT skill_key, MIN(skill_name) AS skill_name,
                           array_agg(DISTINCT slug ORDER BY slug) AS advertised_by_agents
                    FROM declared
                    GROUP BY skill_key
                    ORDER BY skill_key
                    """,
                    (offline_before_iso(),),
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
            merged[row["skill_key"]] = {
                "skill_name": row["skill_name"],
                "advertised_by_agents": row["advertised_by_agents"] or [],
                "enabled": None,
            }
        for row in override_rows:
            key = row["skill_name"].lower()
            item = merged.setdefault(
                key,
                {
                    "skill_name": row["skill_name"],
                    "advertised_by_agents": [],
                    "enabled": None,
                },
            )
            item["enabled"] = bool(row["enabled"])
        return _records(
            RoutingSkillRecord,
            sorted(merged.values(), key=lambda item: item["skill_name"].lower()),
        )

    def _disabled_routing_skills(self, conn) -> set[str]:
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT skill_name FROM {_SCHEMA}.skills_override WHERE enabled = 0"
            )
            rows = cur.fetchall()
        return {str(row["skill_name"]).lower() for row in rows}

    def search_agents(self, query: AgentDiscoveryQuery) -> list[AgentRecord]:
        with self._connect() as conn:
            return shared_search_agents(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                disabled_skill_names=self._disabled_routing_skills(conn),
                query=query,
            )

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
        delivery_id = uuid.uuid4().hex
        with self._connect() as conn, _write_tx(conn):
            return shared_create_management_request(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                create_delivery=self._create_delivery,
                json_param=_jsonb,
                request=request,
                now=now,
                delivery_id=delivery_id,
            )

    def _resolve_selector(
        self,
        conn,
        selector: TargetSelector,
    ) -> dict[str, object]:
        return shared_resolve_selector(
            conn,
            dialect=_POSTGRES_STORE_DIALECT,
            selector=selector,
        )

    @staticmethod
    def _task_snapshot__row(row: dict[str, object]) -> RoutedTaskSnapshot:
        return RoutedTaskSnapshot(
            status=str(row["status"] or "queued"),
            queued_at=str(row["created_at"] or ""),
        )

    def _create_routed_task_in_tx(
        self,
        conn,
        request: dict[str, object],
        *,
        now: str,
    ) -> dict[str, object]:
        validated_request = validated_routed_task_request(request)
        disabled_skills = self._disabled_routing_skills(conn)
        request_payload = validated_request.model_dump(mode="json")
        request_payload["external_conversation_ref"] = (
            str(request_payload.get("external_conversation_ref", "") or "").strip()
            or routed_task_external_conversation_ref(validated_request.routed_task_id)
        )
        for skill_name in requested_routed_skills(request_payload):
            if skill_name.lower() in disabled_skills:
                raise RoutingSkillDisabledError(skill_name)
        recipient_conversation_id = self._ensure_conversation_in_tx(
            conn,
            target_agent_id=validated_request.target_agent_id,
            title=validated_request.title,
            conversation_type="task_thread",
            origin_channel="registry",
            external_conversation_ref=(
                str(validated_request.external_conversation_ref or "").strip()
                or routed_task_external_conversation_ref(validated_request.routed_task_id)
            ),
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
        mirrored_event_id = f"routed-task:{validated_request.routed_task_id}:queued"
        mirrored_content = str(validated_request.title or validated_request.routed_task_id)
        mirrored_metadata = {
            "routed_task_id": validated_request.routed_task_id,
            "status": "queued",
        }
        inserted_event = self._insert_event(
            conn,
            event_id=mirrored_event_id,
            conversation_id=validated_request.parent_conversation_id,
            agent_id=validated_request.target_agent_id,
            kind="task.status",
            actor="",
            content=mirrored_content,
            metadata=mirrored_metadata,
            created_at=now,
        )
        if inserted_event is not None:
            shared_touch_conversation(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                conversation_id=validated_request.parent_conversation_id,
                updated_at=now,
            )
        recipient_event = self._insert_event(
            conn,
            event_id=f"{mirrored_event_id}:recipient",
            conversation_id=recipient_conversation_id,
            agent_id=validated_request.target_agent_id,
            kind="task.status",
            actor="",
            content=mirrored_content,
            metadata=mirrored_metadata,
            created_at=now,
        )
        if recipient_event is not None:
            shared_touch_conversation(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                conversation_id=recipient_conversation_id,
                updated_at=now,
            )
        return {
            "request": validated_request,
            "delivery": delivery,
            "event": inserted_event,
            "recipient_conversation_id": recipient_conversation_id,
            "recipient_event": recipient_event,
        }

    @staticmethod
    def _protocol_record_from_row(row: Mapping[str, object]) -> ProtocolDefinitionRecord:
        return _record(
            ProtocolDefinitionRecord,
            {
                "protocol_id": row["protocol_id"],
                "slug": row["slug"],
                "display_name": row["display_name"],
                "description": row["description"],
                "lifecycle_state": row["lifecycle_state"],
                "current_version_id": row["current_version_id"],
                "owner_org_id": row.get("owner_org_id", PROTOCOL_DEFAULT_RUN_ORG_ID),
                "visibility": row.get("visibility", PROTOCOL_DEFAULT_VISIBILITY),
                "created_by": row.get("created_by", ""),
                "updated_by": row.get("updated_by", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    @staticmethod
    def _protocol_version_from_row(row: Mapping[str, object]) -> ProtocolDefinitionVersionRecord:
        return _record(
            ProtocolDefinitionVersionRecord,
            {
                "protocol_definition_version_id": row["protocol_definition_version_id"],
                "protocol_id": row["protocol_id"],
                "version": row["version"],
                "definition_json": row["definition_json"],
                "content_hash": row["content_hash"],
                "validation_status": row["validation_status"],
                "published_at": row["published_at"],
                "published_by": row.get("published_by", ""),
                "created_at": row["created_at"],
            },
        )

    @staticmethod
    def _protocol_run_from_row(row: Mapping[str, object]) -> ProtocolRunRecord:
        return _record(
            ProtocolRunRecord,
            {
                "protocol_run_id": row["protocol_run_id"],
                "protocol_id": row["protocol_id"],
                "protocol_definition_version_id": row["protocol_definition_version_id"],
                "entry_agent_id": row["entry_agent_id"],
                "entry_authority_ref": row["entry_authority_ref"],
                "root_conversation_id": row["root_conversation_id"],
                "origin_channel": row["origin_channel"],
                "workspace_ref": row["workspace_ref"],
                "repo_ref": row["repo_ref"],
                "branch_ref": row["branch_ref"],
                "problem_statement": row["problem_statement"],
                "constraints_json": row["constraints_json"],
                "status": row["status"],
                "current_stage_execution_id": row["current_stage_execution_id"],
                "current_stage_key": row["current_stage_key"],
                "termination_summary": row["termination_summary"],
                "blocked_code": row.get("blocked_code", ""),
                "blocked_detail": row.get("blocked_detail", ""),
                "run_org_id": row.get("run_org_id", PROTOCOL_DEFAULT_RUN_ORG_ID),
                "started_by": row.get("started_by", ""),
                "version": row.get("version", 1),
                "retention_until": row.get("retention_until", ""),
                "last_transition_at": row.get("last_transition_at", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            },
        )

    @staticmethod
    def _protocol_run_participant_from_row(row: Mapping[str, object]) -> ProtocolRunParticipantRecord:
        return _record(
            ProtocolRunParticipantRecord,
            {
                "protocol_run_participant_id": row["protocol_run_participant_id"],
                "protocol_run_id": row["protocol_run_id"],
                "participant_key": row["participant_key"],
                "display_name": row["display_name"],
                "required_skills": row["required_skills_json"],
                "target_selector": row["target_selector_json"],
                "resolved_agent_id": row["resolved_agent_id"],
                "resolved_authority_ref": row["resolved_authority_ref"],
                "session_key": row["session_key"],
                "state": row["state"],
                "resolution_outcome": row.get("resolution_outcome", "queued"),
                "resolution_reason": row.get("resolution_reason", ""),
                "selector_snapshot_json": row.get("selector_snapshot_json", {}),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    @staticmethod
    def _protocol_stage_execution_from_row(row: Mapping[str, object]) -> ProtocolStageExecutionRecord:
        return _record(
            ProtocolStageExecutionRecord,
            {
                "protocol_stage_execution_id": row["protocol_stage_execution_id"],
                "protocol_run_id": row["protocol_run_id"],
                "stage_key": row["stage_key"],
                "participant_key": row["participant_key"],
                "attempt": row["attempt"],
                "loop_iteration": row["loop_iteration"],
                "status": row["status"],
                "decision": row["decision"],
                "decision_summary": row["decision_summary"],
                "input_snapshot_json": row["input_snapshot_json"],
                "routed_task_id": row["routed_task_id"],
                "failure_code": row["failure_code"],
                "failure_detail": row["failure_detail"],
                "timeout_at": row.get("timeout_at", ""),
                "lease_owner": row.get("lease_owner", ""),
                "lease_expires_at": row.get("lease_expires_at", ""),
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
            },
        )

    @staticmethod
    def _protocol_artifact_from_row(row: Mapping[str, object]) -> ProtocolArtifactRecord:
        return _record(
            ProtocolArtifactRecord,
            {
                "protocol_artifact_id": row["protocol_artifact_id"],
                "protocol_run_id": row["protocol_run_id"],
                "artifact_key": row["artifact_key"],
                "artifact_kind": row["artifact_kind"],
                "location": row["location"],
                "workspace_path": row["workspace_path"],
                "content_hash": row["content_hash"],
                "size_bytes": row.get("size_bytes", 0),
                "exists": row.get("exists", False),
                "modified_at": row.get("modified_at", ""),
                "observed_at": row.get("observed_at", ""),
                "verification_state": row.get("verification_state", "declared"),
                "produced_by_stage_execution_id": row["produced_by_stage_execution_id"],
                "state": row["state"],
                "supersedes_protocol_artifact_id": row["supersedes_protocol_artifact_id"],
                "created_at": row["created_at"],
            },
        )

    @staticmethod
    def _protocol_transition_from_row(row: Mapping[str, object]) -> ProtocolTransitionRecord:
        return _record(
            ProtocolTransitionRecord,
            {
                "protocol_transition_id": row["protocol_transition_id"],
                "protocol_run_id": row["protocol_run_id"],
                "from_stage_execution_id": row["from_stage_execution_id"],
                "to_stage_execution_id": row["to_stage_execution_id"],
                "transition_kind": row["transition_kind"],
                "decision": row["decision"],
                "reason": row["reason"],
                "error_code": row.get("error_code", ""),
                "metadata_json": row.get("metadata_json", {}),
                "actor_type": row["actor_type"],
                "actor_ref": row["actor_ref"],
                "created_at": row["created_at"],
            },
        )

    def _protocol_row(self, conn, protocol_id: str) -> dict[str, object] | None:
        return _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.protocol_definitions WHERE protocol_id = %s",
            (protocol_id,),
        )

    def _protocol_row_for_slug(self, conn, slug: str) -> dict[str, object] | None:
        return _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.protocol_definitions WHERE slug = %s",
            (slug,),
        )

    def _protocol_version_row(self, conn, version_id: str) -> dict[str, object] | None:
        return _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.protocol_definition_versions WHERE protocol_definition_version_id = %s",
            (version_id,),
        )

    def _latest_protocol_version_row(self, conn, protocol_id: str) -> dict[str, object] | None:
        return _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_definition_versions
            WHERE protocol_id = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (protocol_id,),
        )

    @staticmethod
    def _access_actor_ref(access: ProtocolAccessContextRecord | None) -> str:
        return str((access.actor_ref if access is not None else "") or PROTOCOL_DEFAULT_OPERATOR_REF)

    @staticmethod
    def _access_org_id(access: ProtocolAccessContextRecord | None) -> str:
        return str((access.org_id if access is not None else "") or PROTOCOL_DEFAULT_RUN_ORG_ID)

    @staticmethod
    def _access_has_role(access: ProtocolAccessContextRecord | None, role: str) -> bool:
        return bool(access is not None and access.has_role(role))

    @staticmethod
    def _access_primary_role(access: ProtocolAccessContextRecord | None) -> str:
        for role in ("admin", "publisher", "author", "auditor", "operator"):
            if access is not None and access.has_role(role):
                return role
        return "service"

    def _protocol_visible_to_access(
        self,
        row: Mapping[str, object],
        *,
        access: ProtocolAccessContextRecord,
        include_drafts: bool,
    ) -> bool:
        lifecycle_state = str(row.get("lifecycle_state", "") or "")
        if lifecycle_state != "published" and not include_drafts:
            return False
        if self._access_has_role(access, "admin"):
            return True
        owner_org_id = str(row.get("owner_org_id", "") or "")
        visibility = str(row.get("visibility", "") or PROTOCOL_DEFAULT_VISIBILITY)
        if visibility == "registry_template" and not self._config.protocol_registry_templates_enabled:
            visibility = "org_shared"
        current_org_id = self._access_org_id(access)
        if owner_org_id and owner_org_id != current_org_id and visibility != "registry_template":
            return False
        if visibility == "registry_template":
            return True
        return not owner_org_id or owner_org_id == current_org_id

    def _protocol_visibility_status(
        self,
        row: Mapping[str, object] | None,
        *,
        access: ProtocolAccessContextRecord,
        include_drafts: bool,
    ) -> Literal["missing", "visible", "not_visible"]:
        if row is None:
            return "missing"
        if self._protocol_visible_to_access(row, access=access, include_drafts=include_drafts):
            return "visible"
        return "not_visible"

    def _assert_protocol_visible(
        self,
        row: Mapping[str, object] | None,
        *,
        access: ProtocolAccessContextRecord,
        include_drafts: bool,
    ) -> dict[str, object] | None:
        if row is None:
            return None
        if self._protocol_visible_to_access(row, access=access, include_drafts=include_drafts):
            return dict(row)
        return None

    def _assert_protocol_run_visible(
        self,
        row: Mapping[str, object] | None,
        *,
        access: ProtocolAccessContextRecord,
    ) -> dict[str, object] | None:
        if row is None:
            return None
        if self._access_has_role(access, "admin"):
            return dict(row)
        run_org_id = str(row.get("run_org_id", "") or "")
        if run_org_id and run_org_id != self._access_org_id(access):
            return None
        return dict(row)

    def _protocol_stage_executions_for_run(self, conn, run_id: str) -> list[ProtocolStageExecutionRecord]:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_stage_executions
            WHERE protocol_run_id = %s
            ORDER BY started_at ASC, protocol_stage_execution_id ASC
            """,
            (run_id,),
        )
        return [self._protocol_stage_execution_from_row(row) for row in rows]

    def _protocol_run_artifacts_history(self, conn, run_id: str) -> list[ProtocolArtifactRecord]:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, artifact_key ASC
            """,
            (run_id,),
        )
        return [self._protocol_artifact_from_row(row) for row in rows]

    def _protocol_run_transitions_history(self, conn, run_id: str) -> list[ProtocolTransitionRecord]:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_transitions
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, protocol_transition_id DESC
            """,
            (run_id,),
        )
        return [self._protocol_transition_from_row(row) for row in rows]

    def _protocol_run_detail_in_tx(
        self,
        conn,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolRunDetailRecord | None:
        run_row = self._assert_protocol_run_visible(
            _POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {_SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_id,),
            ),
            access=access,
        )
        if run_row is None:
            return None
        definition_row = self._assert_protocol_visible(
            self._protocol_row(conn, str(run_row["protocol_id"] or "")),
            access=access,
            include_drafts=True,
        )
        version_row = self._protocol_version_row(conn, str(run_row["protocol_definition_version_id"] or ""))
        if definition_row is None or version_row is None:
            return None
        participant_rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_run_participants
            WHERE protocol_run_id = %s
            ORDER BY participant_key ASC
            """,
            (run_id,),
        )
        stage_rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_stage_executions
            WHERE protocol_run_id = %s
            ORDER BY started_at DESC, protocol_stage_execution_id DESC
            """,
            (run_id,),
        )
        artifact_rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, artifact_key ASC
            """,
            (run_id,),
        )
        transition_rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_transitions
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, protocol_transition_id DESC
            """,
            (run_id,),
        )
        return ProtocolRunDetailRecord(
            run=self._protocol_run_from_row(run_row),
            definition=self._protocol_record_from_row(definition_row),
            version=self._protocol_version_from_row(version_row),
            participants=[self._protocol_run_participant_from_row(row) for row in participant_rows],
            stage_executions=[self._protocol_stage_execution_from_row(row) for row in stage_rows],
            artifacts=[self._protocol_artifact_from_row(row) for row in artifact_rows],
            transitions=[self._protocol_transition_from_row(row) for row in transition_rows],
        )

    def _record_protocol_compliance_event(
        self,
        conn,
        *,
        protocol_run_id: str,
        protocol_definition_version_id: str,
        event_kind: str,
        actor_ref: str,
        actor_role: str,
        summary: str,
        metadata: Mapping[str, object],
        now: str,
    ) -> None:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_compliance_events (
                    protocol_compliance_event_id, protocol_run_id, protocol_definition_version_id,
                    event_kind, actor_ref, actor_role, summary, metadata_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4().hex,
                    protocol_run_id,
                    protocol_definition_version_id,
                    event_kind,
                    actor_ref,
                    actor_role,
                    summary,
                    _jsonb(dict(metadata)),
                    now,
                ),
            )

    def _request_hash(self, payload: Mapping[str, object]) -> str:
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _protocol_idempotency_row(
        self,
        conn,
        *,
        scope_kind: str,
        scope_ref: str,
        action_name: str,
        idempotency_key: str,
    ) -> dict[str, object] | None:
        if not str(idempotency_key or "").strip():
            return None
        return _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_idempotency
            WHERE scope_kind = %s
              AND scope_ref = %s
              AND action_name = %s
              AND idempotency_key = %s
            """,
            (scope_kind, scope_ref, action_name, idempotency_key),
        )

    def _store_protocol_idempotency(
        self,
        conn,
        *,
        scope_kind: str,
        scope_ref: str,
        action_name: str,
        idempotency_key: str,
        request_hash: str,
        response_json: Mapping[str, object],
        now: str,
    ) -> None:
        if not str(idempotency_key or "").strip():
            return
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_idempotency (
                    protocol_idempotency_id, scope_kind, scope_ref, action_name,
                    idempotency_key, request_hash, response_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (scope_kind, scope_ref, action_name, idempotency_key)
                DO NOTHING
                """,
                (
                    uuid.uuid4().hex,
                    scope_kind,
                    scope_ref,
                    action_name,
                    idempotency_key,
                    request_hash,
                    _jsonb(dict(response_json)),
                    now,
                ),
            )

    def _draft_protocol_document(self, row: Mapping[str, object]) -> ProtocolDefinitionDocumentRecord:
        return canonical_protocol_document(row.get("draft_definition_json") or {})

    def _protocol_document_for_run(self, conn, run_row: Mapping[str, object]) -> ProtocolDefinitionDocumentRecord:
        version_row = self._protocol_version_row(conn, str(run_row["protocol_definition_version_id"] or ""))
        if version_row is None:
            raise KeyError(f"Unknown protocol definition version for run {run_row['protocol_run_id']}")
        return canonical_protocol_document(version_row["definition_json"])

    def _protocol_artifacts_for_run(self, conn, run_id: str) -> list[ProtocolArtifactRecord]:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {_SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
            ORDER BY artifact_key, created_at DESC
            """,
            (run_id,),
        )
        newest: dict[str, ProtocolArtifactRecord] = {}
        for row in rows:
            artifact = self._protocol_artifact_from_row(row)
            newest.setdefault(artifact.artifact_key, artifact)
        return list(newest.values())

    def _latest_protocol_review_feedback(
        self,
        conn,
        *,
        run_id: str,
        current_stage_key: str,
    ) -> str:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT pse.stage_key, rt.result_json
            FROM {_SCHEMA}.protocol_stage_executions pse
            JOIN {_SCHEMA}.routed_tasks rt
              ON rt.routed_task_id = pse.routed_task_id
            WHERE pse.protocol_run_id = %s
              AND pse.status = 'completed'
              AND pse.stage_key <> %s
            ORDER BY pse.completed_at DESC, pse.started_at DESC
            LIMIT 5
            """,
            (run_id, current_stage_key),
        )
        for row in rows:
            result_json = row.get("result_json")
            if not isinstance(result_json, dict):
                continue
            full_text = str(result_json.get("full_text", "") or "").strip()
            if full_text and "PROTOCOL_DECISION" in full_text:
                return full_text
        return ""

    def _insert_protocol_transition(
        self,
        conn,
        *,
        run_id: str,
        from_stage_execution_id: str,
        to_stage_execution_id: str,
        transition_kind: str,
        decision: str,
        reason: str,
        error_code: str,
        metadata: Mapping[str, object],
        actor_type: str,
        actor_ref: str,
        now: str,
    ) -> None:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_transitions (
                    protocol_transition_id, protocol_run_id, from_stage_execution_id,
                    to_stage_execution_id, transition_kind, decision, reason,
                    error_code, metadata_json, actor_type, actor_ref, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4().hex,
                    run_id,
                    from_stage_execution_id,
                    to_stage_execution_id,
                    transition_kind,
                    decision,
                    reason,
                    error_code,
                    _jsonb(dict(metadata)),
                    actor_type,
                    actor_ref,
                    now,
                ),
            )

    def _create_protocol_stage_execution_in_tx(
        self,
        conn,
        *,
        run_row: Mapping[str, object],
        stage_key: str,
        participant_key: str,
        input_snapshot: dict[str, object],
        timeout_at: str,
        now: str,
    ) -> dict[str, object]:
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {_SCHEMA}.protocol_stage_executions
                WHERE protocol_run_id = %s AND stage_key = %s
                """,
                (run_row["protocol_run_id"], stage_key),
            )
            count_row = cur.fetchone() or {"count": 0}
            attempt = int(count_row["count"] or 0) + 1
            execution_id = uuid.uuid4().hex
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.protocol_stage_executions (
                    protocol_stage_execution_id, protocol_run_id, stage_key, participant_key,
                    attempt, loop_iteration, status, decision, decision_summary,
                    input_snapshot_json, routed_task_id, failure_code, failure_detail,
                    timeout_at, lease_owner, lease_expires_at, started_at, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 'queued', '', '', %s, '', '', '', %s, '', '', '', '')
                RETURNING *
                """,
                (
                    execution_id,
                    run_row["protocol_run_id"],
                    stage_key,
                    participant_key,
                    attempt,
                    attempt,
                    _jsonb(input_snapshot),
                    timeout_at,
                ),
            )
            inserted = cur.fetchone()
        if inserted is None:
            raise RuntimeError("Failed to create protocol stage execution")
        return dict(inserted)

    def _dispatch_protocol_stage_in_tx(
        self,
        conn,
        *,
        run_row: Mapping[str, object],
        stage_execution_row: Mapping[str, object],
        now: str,
    ) -> dict[str, object]:
        run = self._protocol_run_from_row(run_row)
        stage_execution = self._protocol_stage_execution_from_row(stage_execution_row)
        document = self._protocol_document_for_run(conn, run_row)
        stage = document.stage(str(stage_execution_row["stage_key"] or ""))
        participant = document.participant(stage.participant_key)
        artifacts = self._protocol_artifacts_for_run(conn, run.protocol_run_id)
        stage_executions = self._protocol_stage_executions_for_run(conn, run.protocol_run_id)
        dispatch = protocol_dispatch_decision(
            document=document,
            run=run,
            stage=stage,
            stage_executions=stage_executions,
            now=now,
            lease_owner=str(stage_execution_row["protocol_stage_execution_id"] or ""),
            lease_ttl_seconds=900,
        )
        if not dispatch.ok:
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=protocol_dispatch_blocked_decision(
                    run=run,
                    stage_execution=stage_execution,
                    error_code=dispatch.error_code,
                    error_detail=dispatch.error_detail,
                ),
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row["protocol_stage_execution_id"] or ""),
                now=now,
            )
            return {}
        previous_feedback = self._latest_protocol_review_feedback(
            conn,
            run_id=run.protocol_run_id,
            current_stage_key=stage.stage_key,
        )
        if participant.selector is not None:
            selector = participant.selector
        elif participant.required_skills:
            selector = TargetSelector(
                kind="skill",
                value=participant.required_skills[0],
                preferred_agent_id=run.entry_agent_id,
            )
        else:
            selector = TargetSelector(kind="agent", value=run.entry_agent_id)
        try:
            resolved_target = self._resolve_selector(conn, selector)
        except Exception as exc:
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=protocol_dispatch_resolution_failed_decision(
                    run=run,
                    stage_execution=stage_execution,
                    selector=selector,
                    error_detail=str(exc),
                ),
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row["protocol_stage_execution_id"] or ""),
                now=now,
            )
            return {}
        session_key = protocol_participant_session_key(run.protocol_run_id, participant.participant_key)
        instructions = render_protocol_stage_prompt(
            document=document,
            run=run,
            stage=stage,
            artifacts=artifacts,
            previous_feedback=previous_feedback,
        )
        routed_task_id = f"protocol-stage:{stage_execution_row['protocol_stage_execution_id']}"
        context_payload = {
            "protocol_run_id": run.protocol_run_id,
            "protocol_stage_execution_id": stage_execution_row["protocol_stage_execution_id"],
            "protocol_definition_version_id": run.protocol_definition_version_id,
            "participant_key": participant.participant_key,
            "stage_key": stage.stage_key,
            "artifact_manifest": [item.model_dump(mode="json") for item in artifacts],
        }
        internal_context = protocol_stage_internal_context(
            document=document,
            run=run,
            stage_execution_id=str(stage_execution_row["protocol_stage_execution_id"] or ""),
            stage=stage,
        )
        request = {
            "routed_task_id": routed_task_id,
            "parent_conversation_id": run.root_conversation_id,
            "origin_transport_ref": str(run.root_conversation_id or ""),
            "authorized_actor_key": "",
            "external_conversation_ref": routed_task_external_conversation_ref(routed_task_id),
            "origin_agent_id": run.entry_agent_id,
            "target_agent_id": resolved_target["agent_id"],
            "title": stage.display_name or stage.stage_key,
            "instructions": instructions,
            "context": context_payload,
            "internal_context": internal_context,
            "constraints": run.constraints_json.as_dict(),
            "requested_skills": participant.required_skills,
            "session_key_override": session_key,
            "project_id_override": run.workspace_ref,
            "file_policy_override": "edit" if stage.write_capable else "",
            "priority": "normal",
            "created_at": now,
        }
        try:
            return self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=protocol_dispatch_started_decision(
                    run=run,
                    stage_execution=stage_execution,
                    routed_task_id=routed_task_id,
                    timeout_at=dispatch.timeout_at,
                    lease_owner=dispatch.lease_owner,
                    lease_expires_at=dispatch.lease_expires_at,
                    selector=selector,
                    resolved_agent_id=str(resolved_target["agent_id"] or ""),
                    resolved_authority_ref=str(resolved_target.get("authority_ref", "") or ""),
                    now=now,
                ),
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row["protocol_stage_execution_id"] or ""),
                now=now,
                routed_task_request=request,
            ) or {}
        except RoutingSkillDisabledError as exc:
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=protocol_dispatch_blocked_decision(
                    run=run,
                    stage_execution=stage_execution,
                    error_code="ROUTING_SKILL_DISABLED",
                    error_detail=str(exc),
                ),
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row["protocol_stage_execution_id"] or ""),
                now=now,
            )
            return {}

    def _upsert_protocol_stage_artifacts_in_tx(
        self,
        conn,
        *,
        run_row: Mapping[str, object],
        stage_execution_row: Mapping[str, object],
        observations: Sequence[ProtocolArtifactObservationRecord],
        now: str,
    ) -> None:
        current_artifacts = {item.artifact_key: item for item in self._protocol_artifacts_for_run(conn, str(run_row["protocol_run_id"] or ""))}
        for observation in observations:
            previous = current_artifacts.get(observation.artifact_key)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_artifacts (
                        protocol_artifact_id, protocol_run_id, artifact_key, artifact_kind,
                        location, workspace_path, content_hash, size_bytes, exists,
                        modified_at, observed_at, verification_state,
                        produced_by_stage_execution_id, state, supersedes_protocol_artifact_id, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_row["protocol_run_id"],
                        observation.artifact_key,
                        observation.artifact_kind,
                        observation.path,
                        observation.path,
                        observation.content_hash,
                        int(observation.size_bytes or 0),
                        bool(observation.exists),
                        observation.modified_at,
                        observation.observed_at or now,
                        observation.verification_state,
                        stage_execution_row["protocol_stage_execution_id"],
                        "available" if observation.exists else "missing",
                        previous.protocol_artifact_id if previous is not None else "",
                        now,
                    ),
                )

    def _protocol_stage_task_result_from_task_row(self, task_row: Mapping[str, object]) -> ProtocolStageTaskResultRecord:
        result_json = task_row.get("result_json")
        if not isinstance(result_json, dict):
            result_json = {}
        observations: list[ProtocolArtifactObservationRecord] = []
        for raw in result_json.get("artifacts", ()) or ():
            try:
                observations.append(ProtocolArtifactObservationRecord.model_validate(raw))
            except Exception:
                continue
        return ProtocolStageTaskResultRecord(
            routed_task_id=str(task_row.get("routed_task_id", "") or ""),
            status=str(task_row.get("status", "") or ""),
            summary=str(result_json.get("summary", "") or ""),
            full_text=str(result_json.get("full_text", "") or ""),
            artifacts=observations,
            completed_at=str(result_json.get("completed_at", "") or utcnow_iso()),
        )

    def _apply_protocol_engine_decision_in_tx(
        self,
        conn,
        *,
        run_row: Mapping[str, object],
        stage_execution_row: Mapping[str, object],
        engine,
        actor_type: str,
        actor_ref: str,
        now: str,
        routed_task_request: Mapping[str, object] | None = None,
    ) -> dict[str, object] | None:
        created_routed_task: dict[str, object] | None = None
        routed_task_id = str(stage_execution_row.get("routed_task_id", "") or "")
        if routed_task_request is not None:
            created_routed_task = self._create_routed_task_in_tx(conn, dict(routed_task_request), now=now)
            request_record = created_routed_task.get("request")
            routed_task_id = str(getattr(request_record, "routed_task_id", "") or routed_task_id)
        completion_timestamp = now if engine.stage_status in {"completed", "failed", "blocked", "cancelled"} else ""
        started_at = str(engine.started_at or stage_execution_row.get("started_at", "") or "")
        timeout_at = str(engine.timeout_at or "")
        lease_owner = str(engine.lease_owner or "")
        lease_expires_at = str(engine.lease_expires_at or "")
        with _cur(conn) as cur:
            if str(engine.participant_key or "").strip():
                participant_selector_snapshot = engine.participant_selector_snapshot.as_dict()
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.protocol_run_participants
                    SET resolved_agent_id = CASE WHEN %s <> '' THEN %s ELSE resolved_agent_id END,
                        resolved_authority_ref = CASE WHEN %s <> '' THEN %s ELSE resolved_authority_ref END,
                        state = CASE WHEN %s <> '' THEN %s ELSE state END,
                        resolution_outcome = CASE WHEN %s <> '' THEN %s ELSE resolution_outcome END,
                        resolution_reason = CASE WHEN %s <> '' THEN %s ELSE resolution_reason END,
                        selector_snapshot_json = CASE WHEN %s::jsonb <> '{{}}'::jsonb THEN %s ELSE selector_snapshot_json END,
                        updated_at = %s
                    WHERE protocol_run_id = %s AND participant_key = %s
                    """,
                    (
                        str(engine.participant_resolved_agent_id or ""),
                        str(engine.participant_resolved_agent_id or ""),
                        str(engine.participant_resolved_authority_ref or ""),
                        str(engine.participant_resolved_authority_ref or ""),
                        str(engine.participant_state or ""),
                        str(engine.participant_state or ""),
                        str(engine.participant_resolution_outcome or ""),
                        str(engine.participant_resolution_outcome or ""),
                        str(engine.participant_resolution_reason or ""),
                        str(engine.participant_resolution_reason or ""),
                        _jsonb(participant_selector_snapshot),
                        _jsonb(participant_selector_snapshot),
                        now,
                        run_row["protocol_run_id"],
                        str(engine.participant_key or ""),
                    ),
                )
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.protocol_stage_executions
                SET status = %s,
                    decision = %s,
                    decision_summary = %s,
                    failure_code = %s,
                    failure_detail = %s,
                    routed_task_id = %s,
                    timeout_at = %s,
                    lease_owner = %s,
                    lease_expires_at = %s,
                    started_at = %s,
                    completed_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (
                    engine.stage_status,
                    engine.decision,
                    engine.summary,
                    engine.failure_code,
                    engine.failure_detail,
                    routed_task_id,
                    timeout_at,
                    lease_owner,
                    lease_expires_at,
                    started_at,
                    completion_timestamp,
                    stage_execution_row["protocol_stage_execution_id"],
                ),
            )
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.protocol_runs
                SET status = %s,
                    termination_summary = %s,
                    blocked_code = %s,
                    blocked_detail = %s,
                    current_stage_execution_id = %s,
                    current_stage_key = %s,
                    retention_until = %s,
                    version = COALESCE(version, 1) + 1,
                    last_transition_at = %s,
                    updated_at = %s,
                    completed_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled') THEN %s ELSE completed_at END
                WHERE protocol_run_id = %s
                """,
                (
                    engine.run_status,
                    engine.summary if engine.terminal_status else "",
                    engine.run_blocked_code,
                    engine.run_blocked_detail,
                    stage_execution_row["protocol_stage_execution_id"],
                    stage_execution_row["stage_key"],
                    engine.retention_until or protocol_retention_until(now, days=PROTOCOL_DEFAULT_RETENTION_DAYS),
                    now,
                    now,
                    engine.run_status,
                    now,
                    run_row["protocol_run_id"],
                ),
            )
        if engine.artifact_observations:
            self._upsert_protocol_stage_artifacts_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                observations=engine.artifact_observations,
                now=now,
            )
        next_execution_id = ""
        if engine.create_next_execution and engine.next_stage_key:
            next_stage = self._protocol_document_for_run(conn, run_row).stage(engine.next_stage_key)
            next_execution_row = self._create_protocol_stage_execution_in_tx(
                conn,
                run_row=run_row,
                stage_key=next_stage.stage_key,
                participant_key=next_stage.participant_key,
                input_snapshot=engine.input_snapshot.as_dict(),
                timeout_at="",
                now=now,
            )
            next_execution_id = str(next_execution_row["protocol_stage_execution_id"] or "")
        self._insert_protocol_transition(
            conn,
            run_id=str(run_row["protocol_run_id"]),
            from_stage_execution_id=str(stage_execution_row["protocol_stage_execution_id"]),
            to_stage_execution_id=next_execution_id,
            transition_kind=engine.transition_kind,
            decision=engine.decision,
            reason=engine.transition_reason,
            error_code=engine.transition_error_code,
            metadata=engine.transition_metadata.as_dict(),
            actor_type=actor_type,
            actor_ref=actor_ref,
            now=now,
        )
        if next_execution_id:
            refreshed_run_row = _POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {_SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_row["protocol_run_id"],),
            )
            refreshed_stage_row = _POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {_SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
                (next_execution_id,),
            )
            if refreshed_run_row is not None and refreshed_stage_row is not None:
                self._dispatch_protocol_stage_in_tx(
                    conn,
                    run_row=refreshed_run_row,
                    stage_execution_row=refreshed_stage_row,
                    now=now,
                )
        return created_routed_task

    def _advance_protocol_run_for_task_in_tx(
        self,
        conn,
        *,
        routed_task_id: str,
        now: str,
    ) -> None:
        stage_execution_row = _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.protocol_stage_executions WHERE routed_task_id = %s",
            (routed_task_id,),
        )
        if stage_execution_row is None:
            return
        if str(stage_execution_row.get("status", "") or "") in {"completed", "failed", "blocked", "cancelled"}:
            return
        run_row = _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
            (stage_execution_row["protocol_run_id"],),
        )
        task_row = _POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s",
            (routed_task_id,),
        )
        if run_row is None or task_row is None:
            return
        document = self._protocol_document_for_run(conn, run_row)
        stage_execution = self._protocol_stage_execution_from_row(stage_execution_row)
        engine = evaluate_protocol_task_result(
            document=document,
            run=self._protocol_run_from_row(run_row),
            stage_execution=stage_execution,
            stage_executions=self._protocol_stage_executions_for_run(conn, str(run_row["protocol_run_id"] or "")),
            result=self._protocol_stage_task_result_from_task_row(task_row),
        )
        self._apply_protocol_engine_decision_in_tx(
            conn,
            run_row=run_row,
            stage_execution_row=stage_execution_row,
            engine=engine,
            actor_type="protocol_engine",
            actor_ref=routed_task_id,
            now=now,
        )

    def _sweep_protocol_timeouts_in_tx(self, conn, *, now: str) -> None:
        rows = _POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT pse.protocol_stage_execution_id, pse.protocol_run_id
            FROM {_SCHEMA}.protocol_stage_executions pse
            JOIN {_SCHEMA}.protocol_runs pr
              ON pr.protocol_run_id = pse.protocol_run_id
            WHERE pse.status = 'running'
              AND coalesce(pse.timeout_at, '') <> ''
              AND pse.timeout_at::timestamptz <= %s::timestamptz
              AND pr.status = 'running'
            ORDER BY pse.timeout_at ASC, pse.protocol_stage_execution_id ASC
            """,
            (now,),
        )
        for row in rows:
            stage_execution_id = str(row.get("protocol_stage_execution_id", "") or "")
            run_id = str(row.get("protocol_run_id", "") or "")
            if not stage_execution_id or not run_id:
                continue
            stage_execution_row = _POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {_SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
                (stage_execution_id,),
            )
            run_row = _POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {_SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_id,),
            )
            if stage_execution_row is None or run_row is None:
                continue
            document = self._protocol_document_for_run(conn, run_row)
            engine = evaluate_protocol_stage_timeout(
                document=document,
                run=self._protocol_run_from_row(run_row),
                stage_execution=self._protocol_stage_execution_from_row(stage_execution_row),
                now=now,
            )
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=engine,
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row.get("protocol_stage_execution_id", "") or ""),
                now=now,
            )

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
            result = shared_poll(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_row=row,
                cursor=cursor,
                limit=limit,
                now=now,
                registry_epoch=self._registry_epoch(conn),
                task_snapshot_row=self._task_snapshot__row,
            )
            self._sweep_protocol_timeouts_in_tx(conn, now=now)
            return result

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
                require_coordination_scope=self._require_coordination_scope,
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
            result = shared_update_routed_task_result(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                require_coordination_scope=self._require_coordination_scope,
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
            self._advance_protocol_run_for_task_in_tx(
                conn,
                routed_task_id=routed_task_id,
                now=now,
            )
            return result

    def report_management_result(
        self,
        agent_token: str,
        request_id: str,
        payload: ManagementResult,
    ) -> ManagementResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_report_management_result(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                token_row=self._token_row,
                json_param=_jsonb,
                agent_token=agent_token,
                request_id=request_id,
                payload=payload,
                now=now,
            )

    def get_management_result(self, request_id: str) -> ManagementResult | None:
        with self._connect() as conn:
            return shared_get_management_result(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                request_id=request_id,
            )

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
                row_to_agent=shared_row_to_agent,
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
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_create_conversation(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                target_agent_id=target_agent_id,
                title=title,
                origin_channel=origin_channel,
                external_conversation_ref=external_conversation_ref,
                now=now,
            )

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

    def list_protocols(
        self,
        *,
        access: ProtocolAccessContextRecord,
        cursor: int = 0,
        limit: int = 50,
        lifecycle_state: str = "",
        slug: str = "",
        created_after: str = "",
    ) -> list[ProtocolDefinitionRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if lifecycle_state:
            params.append(lifecycle_state)
            clauses.append("lifecycle_state = %s")
        if slug:
            params.append(slug)
            clauses.append("slug = %s")
        if created_after:
            try:
                created_after_iso = datetime.fromisoformat(created_after).isoformat()
            except ValueError as exc:
                raise ValueError("created_after must be ISO-8601 text") from exc
            params.append(created_after_iso)
            clauses.append("created_at >= %s")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        include_drafts = any(
            self._access_has_role(access, role)
            for role in ("author", "publisher", "admin")
        )
        with self._connect() as conn:
            rows = _POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {_SCHEMA}.protocol_definitions
                {where_sql}
                ORDER BY updated_at DESC, display_name ASC, slug ASC
                """,
                tuple(params),
            )
        visible = [
            self._protocol_record_from_row(row)
            for row in rows
            if self._protocol_visible_to_access(row, access=access, include_drafts=include_drafts)
        ]
        return visible[cursor:cursor + limit]

    def get_protocol_template(
        self,
        slug: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionDocumentRecord:
        with self._connect() as conn:
            row = self._protocol_row_for_slug(conn, slug)
            visibility = self._protocol_visibility_status(
                row,
                access=access,
                include_drafts=False,
            )
            if visibility == "not_visible":
                raise PermissionError(slug)
            if visibility != "visible" or row is None:
                raise KeyError(slug)
            version_row = None
            current_version_id = str(row.get("current_version_id", "") or "")
            if current_version_id:
                version_row = self._protocol_version_row(conn, current_version_id)
            if version_row is None:
                version_row = self._latest_protocol_version_row(conn, str(row.get("protocol_id", "") or ""))
            if version_row is None:
                raise KeyError(slug)
            return canonical_protocol_document(version_row.get("definition_json") or {})

    def get_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        include_drafts = any(
            self._access_has_role(access, role)
            for role in ("author", "publisher", "admin")
        )
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(
                row,
                access=access,
                include_drafts=include_drafts,
            )
            if visibility == "missing" or row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            if visibility == "not_visible":
                return ProtocolMutationRecord(ok=False, status="not_visible", message="Protocol is not visible to this actor.")
            raw_definition = row.get("draft_definition_json") or {}
            validation = validate_protocol_document(row.get("draft_definition_json") or {})
            version_row = None
            current_version_id = str(row.get("current_version_id", "") or "")
            if current_version_id:
                version_row = self._protocol_version_row(conn, current_version_id)
            if version_row is None:
                version_row = self._latest_protocol_version_row(conn, protocol_id)
            return ProtocolMutationRecord(
                ok=True,
                status="loaded",
                message="Protocol loaded.",
                protocol=self._protocol_record_from_row(row),
                draft_definition_json=RegistryJsonRecord.model_validate(raw_definition),
                draft_document=validation.normalized_document if validation.ok else None,
                version=self._protocol_version_from_row(version_row) if version_row is not None else None,
                validation=validation,
            )

    def get_protocol_version(
        self,
        protocol_id: str,
        version_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionVersionRecord:
        include_drafts = any(
            self._access_has_role(access, role)
            for role in ("author", "publisher", "admin")
        )
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(
                row,
                access=access,
                include_drafts=include_drafts,
            )
            if visibility == "missing" or row is None:
                raise KeyError(protocol_id)
            if visibility == "not_visible":
                raise PermissionError(protocol_id)
            version_row = self._protocol_version_row(conn, version_id)
            if version_row is None or str(version_row.get("protocol_id", "") or "") != protocol_id:
                raise KeyError(version_id)
            return self._protocol_version_from_row(version_row)

    def save_protocol_draft(
        self,
        *,
        access: ProtocolAccessContextRecord,
        protocol_id: str,
        slug: str,
        display_name: str,
        description: str,
        definition_json: RegistryJsonRecord,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol draft writes require author access.")
        protocol_key = str(protocol_id or uuid.uuid4().hex).strip()
        raw_definition = definition_json.as_dict()
        validation = validate_protocol_document(raw_definition)
        document = validation.normalized_document
        raw_hash = protocol_definition_content_hash(document) if document is not None else hashlib.sha256(
            json.dumps(raw_definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        normalized_slug = str(
            slug or (default_protocol_document_slug(document) if document is not None else "")
        ).strip() or f"protocol-{protocol_key[:8]}"
        normalized_name = str(display_name or (document.display_name if document is not None else "") or normalized_slug).strip()
        normalized_description = str(description or (document.description if document is not None else "") or "").strip()
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            existing_slug_row = self._protocol_row_for_slug(conn, normalized_slug)
            if existing_slug_row is not None and str(existing_slug_row.get("protocol_id", "") or "") != protocol_key:
                return ProtocolMutationRecord(
                    ok=False,
                    status="duplicate_slug",
                    message=f"Protocol slug {normalized_slug!r} is already in use.",
                )
            existing_row = self._protocol_row(conn, protocol_key)
            if existing_row is not None and self._assert_protocol_visible(existing_row, access=access, include_drafts=True) is None:
                return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol not visible to this actor.")
            owner_org_id = str(
                (existing_row.get("owner_org_id", "") if existing_row is not None else "") or self._access_org_id(access)
            )
            visibility = str(
                (existing_row.get("visibility", "") if existing_row is not None else "") or PROTOCOL_DEFAULT_VISIBILITY
            )
            created_by = str(
                (existing_row.get("created_by", "") if existing_row is not None else "") or self._access_actor_ref(access)
            )
            lifecycle_state = str((existing_row.get("lifecycle_state", "") if existing_row is not None else "") or "draft")
            current_version_id = str((existing_row.get("current_version_id", "") if existing_row is not None else "") or "")
            created_at = str((existing_row.get("created_at", "") if existing_row is not None else "") or now)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_definitions (
                        protocol_id, slug, display_name, description, lifecycle_state,
                        current_version_id, owner_org_id, visibility, created_by, updated_by,
                        draft_definition_json, draft_content_hash,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (protocol_id) DO UPDATE SET
                        slug = EXCLUDED.slug,
                        display_name = EXCLUDED.display_name,
                        description = EXCLUDED.description,
                        owner_org_id = EXCLUDED.owner_org_id,
                        visibility = EXCLUDED.visibility,
                        updated_by = EXCLUDED.updated_by,
                        lifecycle_state = EXCLUDED.lifecycle_state,
                        current_version_id = EXCLUDED.current_version_id,
                        draft_definition_json = EXCLUDED.draft_definition_json,
                        draft_content_hash = EXCLUDED.draft_content_hash,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        protocol_key,
                        normalized_slug,
                        normalized_name,
                        normalized_description,
                        lifecycle_state,
                        current_version_id,
                        owner_org_id,
                        visibility,
                        created_by,
                        self._access_actor_ref(access),
                        _jsonb(raw_definition),
                        raw_hash,
                        created_at,
                        now,
                    ),
                )
        result = self.get_protocol(protocol_key, access=access)
        return ProtocolMutationRecord(
            ok=True,
            status="saved",
            message="Protocol draft saved.",
            protocol=result.protocol,
            draft_definition_json=result.draft_definition_json,
            draft_document=result.draft_document,
            version=result.version,
            validation=result.validation,
        )

    def validate_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        result = self.get_protocol(protocol_id, access=access)
        if not result.ok or result.validation is None:
            return result
        return ProtocolMutationRecord(
            ok=result.validation.ok,
            status="validated" if result.validation.ok else "invalid",
            message="Protocol validated." if result.validation.ok else "Protocol validation failed.",
            protocol=result.protocol,
            draft_definition_json=result.draft_definition_json,
            draft_document=result.draft_document,
            version=result.version,
            validation=result.validation,
        )

    def publish_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol publish requires publisher access.")
        loaded = self.get_protocol(protocol_id, access=access)
        if not loaded.ok or loaded.validation is None or loaded.draft_document is None:
            return loaded
        if not loaded.validation.ok:
            return ProtocolMutationRecord(
                ok=False,
                status="invalid",
                message="Protocol draft must validate before publish.",
                protocol=loaded.protocol,
                draft_definition_json=loaded.draft_definition_json,
                draft_document=loaded.draft_document,
                version=loaded.version,
                validation=loaded.validation,
            )
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._protocol_row(conn, protocol_id)
            if row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            with _cur(conn) as cur:
                cur.execute(
                    f"SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM {_SCHEMA}.protocol_definition_versions WHERE protocol_id = %s",
                    (protocol_id,),
                )
                next_version = int((cur.fetchone() or {"next_version": 1})["next_version"] or 1)
                version_id = uuid.uuid4().hex
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_definition_versions (
                        protocol_definition_version_id, protocol_id, version, definition_json,
                        content_hash, validation_status, published_at, published_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, 'valid', %s, %s, %s)
                    """,
                    (
                        version_id,
                        protocol_id,
                        next_version,
                        _jsonb(loaded.draft_document.model_dump(mode="json")),
                        loaded.validation.content_hash,
                        now,
                        self._access_actor_ref(access),
                        now,
                    ),
                )
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.protocol_definitions
                    SET lifecycle_state = 'published',
                        current_version_id = %s,
                        updated_by = %s,
                        updated_at = %s
                    WHERE protocol_id = %s
                    """,
                    (version_id, self._access_actor_ref(access), now, protocol_id),
                )
        result = self.get_protocol(protocol_id, access=access)
        return ProtocolMutationRecord(
            ok=result.ok,
            status="published" if result.ok else result.status,
            message="Protocol published." if result.ok else result.message,
            protocol=result.protocol,
            draft_definition_json=result.draft_definition_json,
            draft_document=result.draft_document,
            version=result.version,
            validation=result.validation,
        )

    def archive_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol archive requires publisher access.")
        loaded = self.get_protocol(protocol_id, access=access)
        if not loaded.ok:
            return loaded
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            row = self._protocol_row(conn, protocol_id)
            if row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.protocol_definitions
                    SET lifecycle_state = 'archived',
                        updated_by = %s,
                        updated_at = %s
                    WHERE protocol_id = %s
                    """,
                    (self._access_actor_ref(access), now, protocol_id),
                )
        result = self.get_protocol(protocol_id, access=access)
        return ProtocolMutationRecord(
            ok=result.ok,
            status="archived" if result.ok else result.status,
            message="Protocol archived." if result.ok else result.message,
            protocol=result.protocol,
            draft_definition_json=result.draft_definition_json,
            draft_document=result.draft_document,
            version=result.version,
            validation=result.validation,
        )

    def list_protocol_runs(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        status: str = "",
        protocol_id: str = "",
    ) -> list[ProtocolRunRecord]:
        params: list[object] = []
        clauses: list[str] = []
        if status:
            params.append(status)
            clauses.append("status = %s")
        if protocol_id:
            params.append(protocol_id)
            clauses.append("protocol_id = %s")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = _POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {_SCHEMA}.protocol_runs
                {where}
                ORDER BY updated_at DESC, created_at DESC
                """,
                tuple(params),
            )
        visible = [
            self._protocol_run_from_row(row)
            for row in rows
            if self._assert_protocol_run_visible(row, access=access) is not None
        ]
        return visible[cursor:cursor + limit]

    def create_protocol_run(
        self,
        payload: ProtocolRunCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
        idempotency_key: str = "",
    ) -> ProtocolRunMutationRecord:
        request = (
            payload
            if isinstance(payload, ProtocolRunCreateRecord)
            else ProtocolRunCreateRecord.model_validate(payload)
        )
        request_hash = self._request_hash(
            {
                "payload": request.model_dump(mode="json"),
                "actor_ref": self._access_actor_ref(access),
                "org_id": self._access_org_id(access),
            }
        )
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            existing_idempotency = self._protocol_idempotency_row(
                conn,
                scope_kind="protocol_runs",
                scope_ref=str(request.protocol_definition_version_id or request.protocol_id or ""),
                action_name="create",
                idempotency_key=idempotency_key,
            )
            if existing_idempotency is not None:
                existing_hash = str(existing_idempotency.get("request_hash", "") or "")
                if existing_hash and existing_hash != request_hash:
                    return ProtocolRunMutationRecord(
                        ok=False,
                        status="idempotency_conflict",
                        message="Idempotency key was already used for a different protocol run request.",
                    )
                return ProtocolRunMutationRecord.model_validate(existing_idempotency.get("response_json", {}))
            protocol_row = None
            version_row = None
            if request.protocol_definition_version_id:
                version_row = self._protocol_version_row(conn, request.protocol_definition_version_id)
                if version_row is None:
                    return ProtocolRunMutationRecord(ok=False, status="not_found", message="Protocol version not found.")
                protocol_row = self._protocol_row(conn, str(version_row["protocol_id"] or ""))
            else:
                protocol_row = self._protocol_row(conn, request.protocol_id)
                if protocol_row is None:
                    return ProtocolRunMutationRecord(ok=False, status="not_found", message="Protocol not found.")
                current_version_id = str(protocol_row.get("current_version_id", "") or "")
                if current_version_id:
                    version_row = self._protocol_version_row(conn, current_version_id)
                if version_row is None:
                    version_row = self._latest_protocol_version_row(conn, request.protocol_id)
            visibility = self._protocol_visibility_status(protocol_row, access=access, include_drafts=False)
            if visibility == "missing" or version_row is None:
                return ProtocolRunMutationRecord(ok=False, status="not_found", message="Published protocol version required.")
            if visibility == "not_visible":
                return ProtocolRunMutationRecord(ok=False, status="not_visible", message="Protocol is not visible to this actor.")
            if str(protocol_row.get("lifecycle_state", "") or "") != "published":
                return ProtocolRunMutationRecord(ok=False, status="invalid", message="Only published protocols can start runs.")
            document = canonical_protocol_document(version_row["definition_json"])
            run_id = uuid.uuid4().hex
            root_conversation_id = str(request.root_conversation_id or "").strip()
            if not root_conversation_id:
                created = shared_create_conversation(
                    conn,
                    dialect=_POSTGRES_STORE_DIALECT,
                    target_agent_id=request.entry_agent_id,
                    title=document.display_name or document.slug or "Protocol run",
                    origin_channel="registry",
                    external_conversation_ref=f"protocol-run:{run_id}",
                    now=now,
                )
                root_conversation_id = str(created.conversation_id or "")
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.protocol_runs (
                        protocol_run_id, protocol_id, protocol_definition_version_id,
                        entry_agent_id, entry_authority_ref, root_conversation_id,
                        origin_channel, workspace_ref, repo_ref, branch_ref,
                        problem_statement, constraints_json, status,
                        current_stage_execution_id, current_stage_key, termination_summary,
                        blocked_code, blocked_detail, run_org_id, started_by, version,
                        retention_until, last_transition_at, created_at, updated_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', '', '', '', '', '', %s, %s, 1, %s, '', %s, %s, '')
                    RETURNING *
                    """,
                    (
                        run_id,
                        protocol_row["protocol_id"],
                        version_row["protocol_definition_version_id"],
                        request.entry_agent_id,
                        request.entry_authority_ref,
                        root_conversation_id,
                        request.origin_channel,
                        request.workspace_ref,
                        request.repo_ref,
                        request.branch_ref,
                        request.problem_statement,
                        _jsonb(
                            request.constraints_json.as_dict()
                            if isinstance(request.constraints_json, RegistryJsonRecord)
                            else dict(request.constraints_json or {})
                        ),
                        self._access_org_id(access),
                        self._access_actor_ref(access),
                        protocol_retention_until(now, days=PROTOCOL_DEFAULT_RETENTION_DAYS),
                        now,
                        now,
                    ),
                )
                run_row = cur.fetchone()
                if run_row is None:
                    raise RuntimeError("Failed to create protocol run")
                for participant in document.participants:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.protocol_run_participants (
                            protocol_run_participant_id, protocol_run_id, participant_key,
                            display_name, required_skills_json, target_selector_json,
                            resolved_agent_id, resolved_authority_ref, session_key, state,
                            resolution_outcome, resolution_reason, selector_snapshot_json,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, '', '', %s, 'queued', 'queued', '', %s, %s, %s)
                        """,
                        (
                            uuid.uuid4().hex,
                            run_id,
                            participant.participant_key,
                            participant.display_name or participant.participant_key,
                            _jsonb(participant.required_skills),
                            _jsonb(participant.selector.model_dump(mode="json") if participant.selector is not None else {}),
                            protocol_participant_session_key(run_id, participant.participant_key),
                            _jsonb(participant.selector.model_dump(mode="json") if participant.selector is not None else {}),
                            now,
                            now,
                        ),
                    )
                for artifact in document.artifacts:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.protocol_artifacts (
                            protocol_artifact_id, protocol_run_id, artifact_key, artifact_kind,
                            location, workspace_path, content_hash, size_bytes, exists,
                            modified_at, observed_at, verification_state,
                            produced_by_stage_execution_id, state, supersedes_protocol_artifact_id, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, '', 0, false, '', '', 'declared', '', 'declared', '', %s)
                        """,
                        (
                            uuid.uuid4().hex,
                            run_id,
                            artifact.artifact_key,
                            artifact.kind,
                            artifact.path,
                            artifact.path,
                            now,
                        ),
                    )
            first_stage = document.stage(document.first_stage_key)
            execution_row = self._create_protocol_stage_execution_in_tx(
                conn,
                run_row=run_row,
                stage_key=first_stage.stage_key,
                participant_key=first_stage.participant_key,
                input_snapshot={
                    "problem_statement": request.problem_statement,
                    "workspace_ref": request.workspace_ref,
                },
                timeout_at="",
                now=now,
            )
            self._dispatch_protocol_stage_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=execution_row,
                now=now,
            )
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise RuntimeError("Failed to load protocol run detail after creation")
            result = ProtocolRunMutationRecord(
                ok=True,
                status="created",
                message="Protocol run created.",
                run=detail.run,
                stage_execution=detail.stage_executions[0] if detail.stage_executions else None,
            )
            self._store_protocol_idempotency(
                conn,
                scope_kind="protocol_runs",
                scope_ref=str(request.protocol_definition_version_id or request.protocol_id or ""),
                action_name="create",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_json=_json_ready(result.model_dump(mode="json")),
                now=now,
            )
            return result

    def get_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunDetailRecord:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail

    def get_protocol_run_participants(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolRunParticipantRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.participants

    def get_protocol_run_artifacts(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolArtifactRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.artifacts

    def get_protocol_run_timeline(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTransitionRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.transitions

    def export_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolRunExportRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "auditor", "admin")):
            raise PermissionError("Protocol export requires operator or auditor access.")
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return ProtocolRunExportRecord(
                run=detail.run,
                definition=detail.definition,
                version=detail.version,
                definition_document=canonical_protocol_document(detail.version.definition_json),
                participants=detail.participants,
                stage_executions=detail.stage_executions,
                artifacts=detail.artifacts,
                transitions=detail.transitions,
            )

    def act_on_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        action: str,
        reason: str,
        idempotency_key: str = "",
        expected_version: int | None = None,
    ) -> ProtocolRunMutationRecord:
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "send-back":
            normalized_action = "send_back"
        if normalized_action not in {"cancel", "retry", "accept", "send_back"}:
            return ProtocolRunMutationRecord(ok=False, status="invalid_action", message=f"Unsupported protocol action {action!r}.")
        if not any(self._access_has_role(access, role) for role in ("operator", "admin")):
            return ProtocolRunMutationRecord(ok=False, status="forbidden", message="Protocol run intervention requires operator access.")
        request_hash = self._request_hash(
            {
                "run_id": run_id,
                "action": normalized_action,
                "reason": reason,
                "expected_version": expected_version or 0,
                "actor_ref": self._access_actor_ref(access),
            }
        )
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            existing_idempotency = self._protocol_idempotency_row(
                conn,
                scope_kind="protocol_run",
                scope_ref=run_id,
                action_name=normalized_action,
                idempotency_key=idempotency_key,
            )
            if existing_idempotency is not None:
                existing_hash = str(existing_idempotency.get("request_hash", "") or "")
                if existing_hash and existing_hash != request_hash:
                    return ProtocolRunMutationRecord(
                        ok=False,
                        status="idempotency_conflict",
                        message="Idempotency key was already used for a different protocol action.",
                    )
                return ProtocolRunMutationRecord.model_validate(existing_idempotency.get("response_json", {}))
            run_row = self._assert_protocol_run_visible(
                _POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"SELECT * FROM {_SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                    (run_id,),
                ),
                access=access,
            )
            if run_row is None:
                return ProtocolRunMutationRecord(ok=False, status="not_found", message="Protocol run not found.")
            current_version = int(run_row.get("version", 1) or 1)
            if expected_version is not None and current_version != int(expected_version):
                return ProtocolRunMutationRecord(
                    ok=False,
                    status="conflict",
                    message=f"Protocol run version conflict: expected {expected_version}, found {current_version}.",
                )
            current_stage_execution_id = str(run_row.get("current_stage_execution_id", "") or "")
            stage_execution_row = None
            if current_stage_execution_id:
                stage_execution_row = _POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"SELECT * FROM {_SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
                    (current_stage_execution_id,),
                )
            if stage_execution_row is None:
                stage_execution_row = _POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"""
                    SELECT *
                    FROM {_SCHEMA}.protocol_stage_executions
                    WHERE protocol_run_id = %s
                    ORDER BY started_at DESC, protocol_stage_execution_id DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
            if stage_execution_row is None:
                return ProtocolRunMutationRecord(ok=False, status="invalid", message="Protocol run has no active stage execution.")
            document = self._protocol_document_for_run(conn, run_row)
            engine = evaluate_protocol_operator_action(
                document=document,
                run=self._protocol_run_from_row(run_row),
                stage_execution=self._protocol_stage_execution_from_row(stage_execution_row),
                stage_executions=self._protocol_stage_executions_for_run(conn, run_id),
                action=normalized_action,
                reason=reason,
                now=now,
            )
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=engine,
                actor_type="operator",
                actor_ref=self._access_actor_ref(access),
                now=now,
            )
            refreshed = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if refreshed is None:
                raise RuntimeError("Failed to load protocol run detail after operator action")
            self._record_protocol_compliance_event(
                conn,
                protocol_run_id=run_id,
                protocol_definition_version_id=refreshed.run.protocol_definition_version_id,
                event_kind=f"operator_{normalized_action}",
                actor_ref=self._access_actor_ref(access),
                actor_role=self._access_primary_role(access),
                summary=str(reason or normalized_action).strip() or normalized_action,
                metadata={
                    "expected_version": expected_version,
                    "result_status": refreshed.run.status,
                    "current_stage_key": refreshed.run.current_stage_key,
                },
                now=now,
            )
            result = ProtocolRunMutationRecord(
                ok=True,
                status="updated",
                message="Protocol run updated.",
                run=refreshed.run,
                stage_execution=refreshed.stage_executions[0] if refreshed.stage_executions else None,
            )
            self._store_protocol_idempotency(
                conn,
                scope_kind="protocol_run",
                scope_ref=run_id,
                action_name=normalized_action,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_json=_json_ready(result.model_dump(mode="json")),
                now=now,
            )
            return result

    def add_conversation_message(self, conversation_id: str, text: str) -> MessageRecord:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_add_conversation_message(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                create_delivery=self._create_delivery,
                json_param=_jsonb,
                conversation_id=conversation_id,
                text=text,
                now=now,
            )

    def add_conversation_action(
        self,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            return shared_add_conversation_action(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                create_delivery=self._create_delivery,
                create_routed_task_in_tx=self._create_routed_task_in_tx,
                resolve_selector=self._resolve_selector,
                json_param=_jsonb,
                conversation_id=conversation_id,
                envelope=envelope,
                now=now,
            )

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
            return shared_publish_events(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                json_param=_jsonb,
                agent_id=agent_id,
                conversation_id=conversation_id,
                events=events,
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
        with self._connect() as conn:
            return shared_list_events(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                conversation_id=conversation_id,
                kind=kind,
                before_seq=before_seq,
                after_seq=after_seq,
                limit=limit,
            )

    def list_messages(self, conversation_id: str, *, cursor: int = 0, limit: int = 50) -> MessagePageRecord:
        with self._connect() as conn:
            return shared_list_messages(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                conversation_id=conversation_id,
                cursor=cursor,
                limit=limit,
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
                row_to_agent=shared_row_to_agent,
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
