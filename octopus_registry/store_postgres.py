"""Postgres-backed registry store."""

from __future__ import annotations

import logging
import secrets
import uuid
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
    ProtocolAuthoringOptionsRecord,
    ProtocolAccessContextRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
    ProtocolArtifactRecord,
    ProtocolArtifactRuntimeEventRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolDefinitionDiffRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolDraftCreateRecord,
    ProtocolIssueRecord,
    ProtocolMaintenanceResultRecord,
    ProtocolMutationRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
    ProtocolRunParticipantRecord,
    ProtocolRunRecord,
    ProtocolScenarioRecord,
    ProtocolTemplateSummaryRecord,
    ProtocolTextDocumentRecord,
    ProtocolTransitionRecord,
)
from octopus_sdk.protocols.engine import DEFAULT_PROTOCOL_RUN_ENGINE, ProtocolRunEngine
from .postgres_store_support import POSTGRES_STORE_DIALECT, SCHEMA, cur, jsonb, write_tx
from .protocol_store import ProtocolPostgresAdapter
from .routing_skill_service import (
    requested_routed_skills,
)
from .config import RegistryConfig, load_registry_config
from .postgres import get_connection
from .store_dialect import StoreDialect
from .store_shared.agents import (
    agent_exists as shared_agent_exists,
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
    selector_candidates as shared_selector_candidates,
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

_SCHEMA = SCHEMA
log = logging.getLogger(__name__)
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


_POSTGRES_STORE_DIALECT = POSTGRES_STORE_DIALECT
_cur = cur
_write_tx = write_tx
_jsonb = jsonb


class RegistryPostgresStore(AbstractRegistryStore):
    """Postgres-backed implementation of the registry store contract."""

    def __init__(self, database_url: str, *, config: RegistryConfig | None = None) -> None:
        self.database_url = database_url
        self._config = config or load_registry_config()
        self._protocol_engine: ProtocolRunEngine = DEFAULT_PROTOCOL_RUN_ENGINE
        self._protocol_store = ProtocolPostgresAdapter(
            database_url=database_url,
            config=self._config,
            protocol_engine=self._protocol_engine,
            create_routed_task_in_tx=self._create_routed_task_in_tx,
            resolve_selector_in_tx=self._resolve_selector,
        )
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
            return shared_heartbeat(
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
        task_context = request_payload.get("context", {})
        task_source_kind = (
            "protocol_stage"
            if isinstance(task_context, dict) and str(task_context.get("protocol_run_id", "") or "").strip()
            else "delegation"
        )
        task_hidden = task_source_kind in {"protocol_stage", "rehearsal", "test"}
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
            source_kind=task_source_kind,
            hidden_from_default_views=task_hidden,
            now=now,
        )
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.routed_tasks (
                    routed_task_id, parent_conversation_id, origin_agent_id, target_agent_id,
                    source_kind, hidden_from_default_views, title, request_json, status, summary, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', '', %s, %s)
                ON CONFLICT(routed_task_id) DO UPDATE SET
                    parent_conversation_id = EXCLUDED.parent_conversation_id,
                    origin_agent_id = EXCLUDED.origin_agent_id,
                    target_agent_id = EXCLUDED.target_agent_id,
                    source_kind = EXCLUDED.source_kind,
                    hidden_from_default_views = EXCLUDED.hidden_from_default_views,
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
                    task_source_kind,
                    task_hidden,
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
            result = shared_update_routed_task_status(
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
            status_value = str(getattr(payload, "status", "") or "")
            if status_value == "running":
                self._protocol_store.renew_protocol_stage_lease_in_tx(
                    conn,
                    routed_task_id=routed_task_id,
                    now=now,
                )
            return result

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
        include_soft_deleted: bool = False,
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
                include_soft_deleted=include_soft_deleted,
            )

    def update_agent_trust_tier(self, agent_id: str, trust_tier: str) -> AgentRecord:
        normalized_id = str(agent_id or "").strip()
        normalized_tier = str(trust_tier or "").strip().lower()
        if not normalized_id:
            raise ValueError("agent_id must not be blank")
        if normalized_tier not in {"community", "trusted", "verified", "restricted"}:
            raise ValueError("trust_tier must be community|trusted|verified|restricted")
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET trust_tier = %s, updated_at = %s
                    WHERE agent_id = %s AND soft_deleted_at = ''
                    RETURNING *
                    """,
                    (normalized_tier, now, normalized_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"agent not found: {normalized_id}")
            return shared_row_to_agent(row)

    def update_agent_capacity(
        self,
        agent_id: str,
        *,
        current_capacity: int | None = None,
        max_capacity: int | None = None,
    ) -> AgentRecord:
        normalized_id = str(agent_id or "").strip()
        if not normalized_id:
            raise ValueError("agent_id must not be blank")
        if current_capacity is None and max_capacity is None:
            raise ValueError("at least one of current_capacity or max_capacity must be provided")
        if current_capacity is not None and current_capacity < 0:
            raise ValueError("current_capacity must be >= 0")
        if max_capacity is not None and max_capacity < 1:
            raise ValueError("max_capacity must be >= 1")
        now = utcnow_iso()
        set_parts: list[str] = []
        params: list[object] = []
        if current_capacity is not None:
            set_parts.append("current_capacity = %s")
            params.append(int(current_capacity))
        if max_capacity is not None:
            set_parts.append("max_capacity = %s")
            params.append(int(max_capacity))
        set_parts.append("updated_at = %s")
        params.append(now)
        params.append(normalized_id)
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET {', '.join(set_parts)}
                    WHERE agent_id = %s AND soft_deleted_at = ''
                    RETURNING *
                    """,
                    tuple(params),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"agent not found: {normalized_id}")
            return shared_row_to_agent(row)

    def rotate_agent_token(self, agent_id: str) -> tuple[AgentRecord, str]:
        normalized_id = str(agent_id or "").strip()
        if not normalized_id:
            raise ValueError("agent_id must not be blank")
        new_token = secrets.token_urlsafe(32)
        new_token_hash = hash_agent_token(new_token)
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET agent_token = %s, updated_at = %s
                    WHERE agent_id = %s AND soft_deleted_at = ''
                    RETURNING *
                    """,
                    (new_token_hash, now, normalized_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"agent not found: {normalized_id}")
            return shared_row_to_agent(row), new_token

    def preview_selector_resolution(
        self,
        selector,
        *,
        exclude_agent_ids: tuple[str, ...] = (),
    ) -> list[dict[str, object]]:
        """Return every candidate row that a selector matches, without ambiguity errors."""
        exclude = {str(agent_id or "").strip() for agent_id in exclude_agent_ids if str(agent_id or "").strip()}
        with self._connect() as conn:
            candidates = shared_selector_candidates(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                selector=selector,
            )
        return [row for row in candidates if str(row.get("agent_id") or "").strip() not in exclude]

    def soft_delete_agent(self, agent_id: str) -> AgentRecord:
        normalized_id = str(agent_id or "").strip()
        if not normalized_id:
            raise ValueError("agent_id must not be blank")
        now = utcnow_iso()
        with self._connect() as conn, _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.agents
                    SET soft_deleted_at = %s, connectivity_state = 'disconnected',
                        updated_at = %s, last_heartbeat_at = %s
                    WHERE agent_id = %s
                    RETURNING *
                    """,
                    (now, now, now, normalized_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise LookupError(f"agent not found: {normalized_id}")
            return shared_row_to_agent(row)

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
            return shared_agent_exists(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
            )

    def create_conversation(
        self,
        *,
        target_agent_id: str,
        title: str,
        origin_channel: str = "registry",
        external_conversation_ref: str = "",
        source_kind: str = "human",
        hidden_from_default_views: bool = False,
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
                source_kind=source_kind,
                hidden_from_default_views=hidden_from_default_views,
                now=now,
            )

    def list_conversations(self, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 25, q: str = "", status: str = "", conversation_type: str = "", include_generated: bool = True) -> list[ConversationRecord]:
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
                    include_generated=include_generated,
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
                include_generated=include_generated,
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

    def cleanup_workspace_data(self) -> dict[str, object]:
        tables = (
            "deliveries",
            "management_requests",
            "events",
            "routed_tasks",
            "protocol_compliance_events",
            "protocol_idempotency",
            "protocol_transitions",
            "protocol_artifacts",
            "protocol_stage_executions",
            "protocol_run_participants",
            "protocol_runs",
            "protocol_scenarios",
            "protocol_definition_versions",
            "protocol_definitions",
            "conversations",
        )
        with self._connect() as conn, _write_tx(conn):
            counts: dict[str, int] = {}
            with _cur(conn) as cur:
                for table in tables:
                    cur.execute(f"SELECT COUNT(*) AS count FROM {_SCHEMA}.{table}")
                    row = cur.fetchone() or {}
                    counts[table] = int(row.get("count") or 0)
                table_sql = ", ".join(f"{_SCHEMA}.{table}" for table in tables)
                cur.execute(f"TRUNCATE TABLE {table_sql} RESTART IDENTITY CASCADE")
            return {
                "cleaned": True,
                "tables": counts,
                "preserved": ["agents", "runtime_skills", "skills_override", "provider_guidance", "catalog content"],
            }

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

    def _advance_protocol_run_for_task_in_tx(
        self,
        conn,
        *,
        routed_task_id: str,
        now: str,
    ) -> None:
        self._protocol_store.advance_run_for_task_in_tx(
            conn,
            routed_task_id=routed_task_id,
            now=now,
        )

    def run_protocol_maintenance(self, *, now: str = "") -> ProtocolMaintenanceResultRecord:
        return self._protocol_store.run_protocol_maintenance(now=now)

    def list_protocols(
        self,
        *,
        access: ProtocolAccessContextRecord,
        cursor: int = 0,
        limit: int = 50,
        lifecycle_state: str = "",
        slug: str = "",
        created_after: str = "",
        include_drafts: bool | None = None,
    ) -> list[ProtocolDefinitionRecord]:
        return self._protocol_store.list_protocols(
            access=access,
            lifecycle_state=lifecycle_state,
            slug=slug,
            limit=limit,
            cursor=cursor,
            created_after=created_after,
            include_drafts=include_drafts,
        )

    def get_protocol_template(
        self,
        slug: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionDocumentRecord:
        return self._protocol_store.get_protocol_template(slug, access=access)

    def list_protocol_templates(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTemplateSummaryRecord]:
        return self._protocol_store.list_protocol_templates(access=access)

    def get_protocol_authoring_options(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAuthoringOptionsRecord:
        return self._protocol_store.get_protocol_authoring_options(access=access)

    def get_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        return self._protocol_store.get_protocol(protocol_id, access=access)

    def get_protocol_version(
        self,
        protocol_id: str,
        version_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolDefinitionVersionRecord:
        return self._protocol_store.get_protocol_version(protocol_id, version_id, access=access)

    def parse_protocol_document_text(
        self,
        *,
        access: ProtocolAccessContextRecord,
        definition_text: str,
        format: str = "json",
        validation_mode: str = "strict",
    ) -> ProtocolTextDocumentRecord:
        return self._protocol_store.parse_protocol_document_text(
            access=access,
            definition_text=definition_text,
            format=format,
            validation_mode=validation_mode,
        )

    def export_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolTextDocumentRecord:
        return self._protocol_store.export_protocol_draft(
            protocol_id,
            access=access,
            format=format,
        )

    def diff_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolDefinitionDiffRecord:
        return self._protocol_store.diff_protocol_draft(
            protocol_id,
            access=access,
            format=format,
        )

    def create_protocol_auto_design_session(
        self,
        payload: ProtocolAutoDesignRequestRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        return self._protocol_store.create_protocol_auto_design_session(payload, access=access)

    def get_protocol_auto_design_session(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        return self._protocol_store.get_protocol_auto_design_session(session_id, access=access)

    def update_protocol_auto_design_session(
        self,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
        event_kind: str = "updated",
    ) -> ProtocolAutoDesignSessionRecord:
        return self._protocol_store.update_protocol_auto_design_session(session, access=access, event_kind=event_kind)

    def list_protocol_auto_design_session_events(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ):
        return self._protocol_store.list_protocol_auto_design_session_events(session_id, access=access)

    def save_protocol_draft(
        self,
        *,
        access: ProtocolAccessContextRecord,
        protocol_id: str,
        slug: str,
        display_name: str,
        description: str,
        definition_json: RegistryJsonRecord,
        authoring_surface: str = "",
        expected_revision: int | None = None,
    ) -> ProtocolMutationRecord:
        return self._protocol_store.save_protocol_draft(
            access=access,
            protocol_id=protocol_id,
            slug=slug,
            display_name=display_name,
            description=description,
            definition_json=definition_json,
            authoring_surface=authoring_surface,
            expected_revision=expected_revision,
        )

    def create_protocol_draft(
        self,
        payload: ProtocolDraftCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        return self._protocol_store.create_protocol_draft(payload, access=access)

    def delete_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        return self._protocol_store.delete_protocol(protocol_id, access=access)

    def validate_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        return self._protocol_store.validate_protocol(protocol_id, access=access)

    def publish_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        return self._protocol_store.publish_protocol(protocol_id, access=access)

    def publish_protocol_template(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        slug: str = "",
        display_name: str = "",
        description: str = "",
    ) -> ProtocolMutationRecord:
        return self._protocol_store.publish_protocol_template(
            protocol_id,
            access=access,
            slug=slug,
            display_name=display_name,
            description=description,
        )

    def archive_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        return self._protocol_store.archive_protocol(protocol_id, access=access)

    def list_protocol_runs(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        root_conversation_id: str = "",
        origin_channel: str = "",
        include_generated: bool = True,
    ) -> list[ProtocolRunRecord]:
        return self._protocol_store.list_protocol_runs(
            access=access,
            limit=limit,
            cursor=cursor,
            status=status,
            protocol_id=protocol_id,
            entry_agent_id=entry_agent_id,
            root_conversation_id=root_conversation_id,
            origin_channel=origin_channel,
            include_generated=include_generated,
        )

    def list_protocol_issues(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        issue_kind: str = "",
        protocol_run_id: str = "",
        protocol_id: str = "",
    ) -> list[ProtocolIssueRecord]:
        return self._protocol_store.list_protocol_issues(
            access=access,
            limit=limit,
            cursor=cursor,
            issue_kind=issue_kind,
            protocol_run_id=protocol_run_id,
            protocol_id=protocol_id,
        )

    def create_protocol_run(
        self,
        payload: ProtocolRunCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
        idempotency_key: str = "",
    ) -> ProtocolRunMutationRecord:
        return self._protocol_store.create_protocol_run(
            payload,
            access=access,
            idempotency_key=idempotency_key,
        )

    def get_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunDetailRecord:
        return self._protocol_store.get_protocol_run(run_id, access=access)

    def get_protocol_run_participants(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolRunParticipantRecord]:
        return self._protocol_store.get_protocol_run_participants(run_id, access=access)

    def get_protocol_run_artifacts(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolArtifactRecord]:
        return self._protocol_store.get_protocol_run_artifacts(run_id, access=access)

    def get_protocol_run_timeline(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTransitionRecord]:
        return self._protocol_store.get_protocol_run_timeline(run_id, access=access)

    def get_protocol_artifact_runtime(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord | None:
        return self._protocol_store.get_protocol_artifact_runtime(run_id, artifact_key, access=access)

    def save_protocol_artifact_runtime(
        self,
        runtime: ProtocolArtifactRuntimeInstanceRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord:
        return self._protocol_store.save_protocol_artifact_runtime(runtime, access=access)

    def append_protocol_artifact_runtime_event(
        self,
        event: ProtocolArtifactRuntimeEventRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeEventRecord:
        return self._protocol_store.append_protocol_artifact_runtime_event(event, access=access)

    def list_protocol_artifact_runtime_events(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 50,
    ) -> list[ProtocolArtifactRuntimeEventRecord]:
        return self._protocol_store.list_protocol_artifact_runtime_events(
            run_id,
            artifact_key,
            access=access,
            limit=limit,
        )

    def export_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolRunExportRecord:
        return self._protocol_store.export_protocol_run(run_id, access=access)

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
        return self._protocol_store.act_on_protocol_run(
            run_id,
            access=access,
            action=action,
            reason=reason,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
        )

    def list_protocol_scenarios(
        self,
        *,
        protocol_id: str = "",
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolScenarioRecord]:
        return self._protocol_store.list_protocol_scenarios(
            protocol_id=protocol_id,
            access=access,
        )

    def create_protocol_scenario(
        self,
        *,
        payload: Mapping[str, object],
        access: ProtocolAccessContextRecord,
    ) -> ProtocolScenarioRecord:
        return self._protocol_store.create_protocol_scenario(payload=payload, access=access)

    def delete_protocol_scenario(
        self,
        *,
        scenario_id: str,
        access: ProtocolAccessContextRecord,
    ) -> bool:
        return self._protocol_store.delete_protocol_scenario(
            scenario_id=scenario_id,
            access=access,
        )

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
        protocol_run_id: str = "",
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
        completed_since_iso: str = "",
        include_generated: bool = True,
    ) -> list[TaskRecord]:
        with self._connect() as conn:
            return shared_list_tasks(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                for_agent_id=for_agent_id,
                parent_conversation_id=parent_conversation_id,
                protocol_run_id=protocol_run_id,
                cursor=cursor,
                limit=limit,
                status=status,
                completed_since_iso=completed_since_iso,
                include_generated=include_generated,
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

    def list_agent_conversations(self, agent_id: str, *, for_agent_id: str | None = None, cursor: int = 0, limit: int = 50, conversation_type: str = "", include_generated: bool = True) -> list[ConversationRecord]:
        with self._connect() as conn:
            return shared_list_agent_conversations(
                conn,
                dialect=_POSTGRES_STORE_DIALECT,
                agent_id=agent_id,
                for_agent_id=for_agent_id,
                cursor=cursor,
                limit=limit,
                conversation_type=conversation_type,
                include_generated=include_generated,
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
