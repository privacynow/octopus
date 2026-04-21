"""Dedicated Postgres adapter for protocol definitions, runs, and orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal

from octopus_sdk.protocols import (
    PROTOCOL_ARTIFACT_KIND_OPTIONS,
    PROTOCOL_AUTHORING_SECTION_OPTIONS,
    PROTOCOL_DEFAULT_OPERATOR_REF,
    PROTOCOL_DEFAULT_RETENTION_DAYS,
    PROTOCOL_DEFAULT_RUN_ORG_ID,
    PROTOCOL_SELECTOR_KIND_OPTIONS,
    PROTOCOL_STAGE_KIND_OPTIONS,
    PROTOCOL_DEFAULT_VISIBILITY,
    REHEARSAL_AUTHORITY_REF,
    ProtocolAuthoringManifestRecord,
    ProtocolAccessContextRecord,
    ProtocolArtifactObservationRecord,
    ProtocolArtifactRecord,
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
    ProtocolStageExecutionRecord,
    ProtocolStageTaskResultRecord,
    ProtocolTemplateSummaryRecord,
    ProtocolTextDocumentRecord,
    ProtocolTransitionRecord,
    RegistryJsonRecord,
    TargetSelector,
    builtin_protocol_template_summaries,
    canonical_protocol_document,
    normalize_protocol_document_format,
    protocol_current_review_state,
    protocol_definition_content_hash,
    protocol_document_from_text,
    protocol_document_to_text,
    protocol_document_unified_diff,
    protocol_participant_session_key,
    protocol_retention_until,
    protocol_review_edge_counts,
    validate_protocol_document,
)
from octopus_sdk.protocols.documents import draft_protocol_document_data
from octopus_sdk.protocols.builtins import builtin_protocol_document
from octopus_sdk.protocols.engine import ProtocolRunEngine
from octopus_sdk.registry.models import normalized_requested_skills, utcnow_iso

from .config import RegistryConfig
from .postgres import get_connection
from .postgres_store_support import POSTGRES_STORE_DIALECT, SCHEMA, cur, jsonb, write_tx
from .protocol_runtime import evaluate_protocol_dispatch
from .store_base import RoutingSkillDisabledError
from .store_shared.common import json_ready, record
from .store_shared.agents import agent_exists as shared_agent_exists
from .store_shared.conversations import create_conversation as shared_create_conversation

log = logging.getLogger(__name__)


def _participant_assignment_projection(
    document: ProtocolDefinitionDocumentRecord,
    participant_key: str,
) -> tuple[TargetSelector | None, list[str]]:
    selectors = []
    for stage in document.stages:
        if str(stage.participant_key or "").strip() == str(participant_key or "").strip():
            if stage.selector is not None:
                selectors.append(stage.selector.model_dump(mode="json"))
    if not selectors:
        return None, []
    first = selectors[0]
    if any(item != first for item in selectors[1:]):
        return None, []
    selector = TargetSelector.model_validate(first)
    return selector, normalized_requested_skills(selector=selector)


class ProtocolPostgresAdapter:
    """Protocol-specific Postgres adapter used by the registry store."""

    def __init__(
        self,
        *,
        database_url: str,
        config: RegistryConfig,
        protocol_engine: ProtocolRunEngine,
        create_routed_task_in_tx: Callable[..., dict[str, object]],
        resolve_selector_in_tx: Callable[[object, TargetSelector], dict[str, object]],
    ) -> None:
        self._database_url = database_url
        self._config = config
        self._protocol_engine = protocol_engine
        self._create_routed_task_in_tx = create_routed_task_in_tx
        self._resolve_selector_in_tx = resolve_selector_in_tx

    def _connect(self):
        return get_connection(self._database_url)

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

    @staticmethod
    def _protocol_record_from_row(row: Mapping[str, object]) -> ProtocolDefinitionRecord:
        return record(
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
                "draft_revision": int(row.get("draft_revision", 0) or 0),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    @staticmethod
    def _protocol_version_from_row(row: Mapping[str, object]) -> ProtocolDefinitionVersionRecord:
        return record(
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
        return record(
            ProtocolRunRecord,
            {
                "protocol_run_id": row["protocol_run_id"],
                "protocol_id": row["protocol_id"],
                "protocol_definition_version_id": row["protocol_definition_version_id"],
                "entry_agent_id": row["entry_agent_id"],
                "entry_authority_ref": row["entry_authority_ref"],
                "is_rehearsal": bool(row.get("is_rehearsal", False)),
                "root_conversation_id": row["root_conversation_id"],
                "root_external_conversation_ref": row.get("root_external_conversation_ref", ""),
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
                "current_review_rounds": row.get("current_review_rounds", 0),
                "max_review_rounds": row.get("max_review_rounds", 0),
                "current_review_edge_key": row.get("current_review_edge_key", ""),
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
        return record(
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
        return record(
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
        return record(
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
        return record(
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
        return POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_definitions WHERE protocol_id = %s",
            (protocol_id,),
        )

    def _protocol_row_for_slug(self, conn, slug: str) -> dict[str, object] | None:
        return POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_definitions WHERE slug = %s",
            (slug,),
        )

    def _protocol_version_row(self, conn, version_id: str) -> dict[str, object] | None:
        return POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_definition_versions WHERE protocol_definition_version_id = %s",
            (version_id,),
        )

    def _latest_protocol_version_row(self, conn, protocol_id: str) -> dict[str, object] | None:
        return POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_definition_versions
            WHERE protocol_id = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (protocol_id,),
        )

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

    def _unique_protocol_slug(self, conn, base_slug: str, *, protocol_id: str = "") -> str:
        normalized = str(base_slug or "").strip().lower() or f"protocol-{uuid.uuid4().hex[:8]}"
        candidate = normalized
        suffix = 1
        while True:
            row = self._protocol_row_for_slug(conn, candidate)
            if row is None or str(row.get("protocol_id", "") or "") == str(protocol_id or ""):
                return candidate
            suffix += 1
            candidate = f"{normalized}-{suffix}"

    @staticmethod
    def _blank_protocol_document(
        *,
        slug: str,
        display_name: str,
        description: str,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "metadata": {
                "slug": str(slug or "").strip(),
                "display_name": str(display_name or "").strip(),
                "description": str(description or "").strip(),
            },
            "participants": [],
            "artifacts": [],
            "stages": [],
            "policies": {
                "single_active_writer": True,
                "max_review_rounds": 5,
            },
        }

    @staticmethod
    def _with_protocol_metadata(
        document: Mapping[str, object] | None,
        *,
        slug: str,
        display_name: str,
        description: str,
    ) -> dict[str, object]:
        payload = dict(document or {})
        metadata = dict(payload.get("metadata") or {})
        metadata["slug"] = str(slug or "").strip()
        metadata["display_name"] = str(display_name or "").strip()
        metadata["description"] = str(description or "").strip()
        payload["metadata"] = metadata
        return payload

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

    def _protocol_run_visibility_status(
        self,
        row: Mapping[str, object] | None,
        *,
        access: ProtocolAccessContextRecord,
    ) -> Literal["missing", "visible", "not_visible"]:
        if row is None:
            return "missing"
        if self._assert_protocol_run_visible(row, access=access) is not None:
            return "visible"
        return "not_visible"

    def _protocol_stage_executions_for_run(self, conn, run_id: str) -> list[ProtocolStageExecutionRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_stage_executions
            WHERE protocol_run_id = %s
            ORDER BY started_at ASC, protocol_stage_execution_id ASC
            """,
            (run_id,),
        )
        return [self._protocol_stage_execution_from_row(row) for row in rows]

    def _protocol_run_artifacts_history(self, conn, run_id: str) -> list[ProtocolArtifactRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, artifact_key ASC
            """,
            (run_id,),
        )
        return [self._protocol_artifact_from_row(row) for row in rows]

    def _protocol_run_transitions_history(self, conn, run_id: str) -> list[ProtocolTransitionRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_transitions
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, protocol_transition_id DESC
            """,
            (run_id,),
        )
        return [self._protocol_transition_from_row(row) for row in rows]

    def _decorate_protocol_run_row_with_review_state(
        self,
        conn,
        run_row: Mapping[str, object],
        *,
        transitions: Sequence[ProtocolTransitionRecord] | None = None,
        document: ProtocolDefinitionDocumentRecord | None = None,
    ) -> dict[str, object]:
        payload = dict(run_row)
        transition_records = list(
            transitions or self._protocol_run_transitions_history(conn, str(run_row.get("protocol_run_id", "") or ""))
        )
        document_record = document
        if document_record is None:
            version_row = self._protocol_version_row(conn, str(run_row.get("protocol_definition_version_id", "") or ""))
            if version_row is not None:
                document_record = canonical_protocol_document(version_row["definition_json"])
        max_review_rounds = document_record.policies.max_review_rounds if document_record is not None else 0
        current_review_rounds, max_rounds, current_review_edge_key = protocol_current_review_state(
            transition_records,
            max_review_rounds=max_review_rounds,
        )
        payload["current_review_rounds"] = current_review_rounds
        payload["max_review_rounds"] = max_rounds
        payload["current_review_edge_key"] = current_review_edge_key
        return payload

    def _protocol_run_detail_in_tx(
        self,
        conn,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolRunDetailRecord | None:
        raw_run_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
            (run_id,),
        )
        run_visibility = self._protocol_run_visibility_status(raw_run_row, access=access)
        if run_visibility == "missing":
            return None
        if run_visibility == "not_visible":
            raise PermissionError("Protocol run is not visible to this actor.")
        run_row = dict(raw_run_row or {})
        if str(run_row.get("root_conversation_id", "") or "").strip():
            conversation_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT external_conversation_ref FROM {SCHEMA}.conversations WHERE conversation_id = %s",
                (str(run_row.get("root_conversation_id", "") or ""),),
            )
            if conversation_row is not None:
                run_row["root_external_conversation_ref"] = str(conversation_row.get("external_conversation_ref", "") or "")
        raw_definition_row = self._protocol_row(conn, str(run_row["protocol_id"] or ""))
        definition_visibility = self._protocol_visibility_status(
            raw_definition_row,
            access=access,
            include_drafts=True,
        )
        if definition_visibility == "missing":
            return None
        if definition_visibility == "not_visible":
            raise PermissionError("Protocol is not visible to this actor.")
        definition_row = dict(raw_definition_row or {})
        version_row = self._protocol_version_row(conn, str(run_row["protocol_definition_version_id"] or ""))
        if definition_row is None or version_row is None:
            return None
        participant_rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_run_participants
            WHERE protocol_run_id = %s
            ORDER BY participant_key ASC
            """,
            (run_id,),
        )
        stage_rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_stage_executions
            WHERE protocol_run_id = %s
            ORDER BY started_at DESC, protocol_stage_execution_id DESC
            """,
            (run_id,),
        )
        artifact_rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, artifact_key ASC
            """,
            (run_id,),
        )
        transition_rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_transitions
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, protocol_transition_id DESC
            """,
            (run_id,),
        )
        document = canonical_protocol_document(version_row["definition_json"])
        transition_records = [self._protocol_transition_from_row(row) for row in transition_rows]
        run_row = self._decorate_protocol_run_row_with_review_state(
            conn,
            run_row,
            transitions=transition_records,
            document=document,
        )
        return ProtocolRunDetailRecord(
            run=self._protocol_run_from_row(run_row),
            definition=self._protocol_record_from_row(definition_row),
            version=self._protocol_version_from_row(version_row),
            participants=[self._protocol_run_participant_from_row(row) for row in participant_rows],
            stage_executions=[self._protocol_stage_execution_from_row(row) for row in stage_rows],
            artifacts=[self._protocol_artifact_from_row(row) for row in artifact_rows],
            transitions=transition_records,
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
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_compliance_events (
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
                    jsonb(dict(metadata)),
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
        return POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_idempotency
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
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_idempotency (
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
                    jsonb(dict(response_json)),
                    now,
                ),
            )

    def _draft_protocol_document(self, row: Mapping[str, object]) -> ProtocolDefinitionDocumentRecord | None:
        return self._strict_protocol_document(row.get("draft_definition_json") or {})

    @staticmethod
    def _strict_protocol_document(value: object) -> ProtocolDefinitionDocumentRecord | None:
        validation = validate_protocol_document(value, mode="strict")
        return validation.normalized_document if validation.ok else None

    def _protocol_document_for_run(self, conn, run_row: Mapping[str, object]) -> ProtocolDefinitionDocumentRecord:
        version_row = self._protocol_version_row(conn, str(run_row["protocol_definition_version_id"] or ""))
        if version_row is None:
            raise KeyError(f"Unknown protocol definition version for run {run_row['protocol_run_id']}")
        return canonical_protocol_document(version_row["definition_json"])

    def _protocol_artifacts_for_run(self, conn, run_id: str) -> list[ProtocolArtifactRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifacts
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
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT pse.stage_key, rt.result_json
            FROM {SCHEMA}.protocol_stage_executions pse
            JOIN {SCHEMA}.routed_tasks rt
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
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_transitions (
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
                    jsonb(dict(metadata)),
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
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM {SCHEMA}.protocol_stage_executions
                WHERE protocol_run_id = %s AND stage_key = %s
                """,
                (run_row["protocol_run_id"], stage_key),
            )
            count_row = db_cur.fetchone() or {"count": 0}
            attempt = int(count_row["count"] or 0) + 1
            execution_id = uuid.uuid4().hex
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_stage_executions (
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
                    jsonb(input_snapshot),
                    timeout_at,
                ),
            )
            inserted = db_cur.fetchone()
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
        artifacts = self._protocol_artifacts_for_run(conn, run.protocol_run_id)
        stage_executions = self._protocol_stage_executions_for_run(conn, run.protocol_run_id)
        previous_feedback = self._latest_protocol_review_feedback(
            conn,
            run_id=run.protocol_run_id,
            current_stage_key=str(stage_execution_row["stage_key"] or ""),
        )
        engine = evaluate_protocol_dispatch(
            protocol_engine=self._protocol_engine,
            document=document,
            run=run,
            stage_execution=stage_execution,
            stage_executions=stage_executions,
            artifacts=artifacts,
            previous_feedback=previous_feedback,
            now=now,
            resolve_selector=lambda selector: self._resolve_selector_in_tx(conn, selector),
        )
        try:
            return self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=engine,
                actor_type="protocol_engine",
                actor_ref=str(stage_execution_row["protocol_stage_execution_id"] or ""),
                now=now,
            ) or {}
        except RoutingSkillDisabledError as exc:
            self._apply_protocol_engine_decision_in_tx(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=self._protocol_engine.dispatch_blocked(
                    run=run,
                    stage_execution=stage_execution,
                    error_code="ROUTING_SKILL_DISABLED",
                    error_detail=f"Routing skill disabled: {exc}",
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
        current_artifacts = {
            item.artifact_key: item for item in self._protocol_artifacts_for_run(conn, str(run_row["protocol_run_id"] or ""))
        }
        for observation in observations:
            previous = current_artifacts.get(observation.artifact_key)
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_artifacts (
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

    def renew_protocol_stage_lease_in_tx(
        self,
        conn,
        *,
        routed_task_id: str,
        now: str,
        lease_ttl_seconds: int = 900,
    ) -> None:
        stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE routed_task_id = %s",
            (routed_task_id,),
        )
        if stage_execution_row is None:
            return
        if str(stage_execution_row.get("status", "") or "") != "running":
            return
        run_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
            (stage_execution_row["protocol_run_id"],),
        )
        if run_row is None:
            return
        document = self._protocol_document_for_run(conn, run_row)
        stage = document.stage(str(stage_execution_row.get("stage_key", "") or ""))
        if not stage.write_capable or not document.policies.single_active_writer:
            return
        parsed_now = datetime.fromisoformat(now)
        if parsed_now.tzinfo is None:
            parsed_now = parsed_now.replace(tzinfo=timezone.utc)
        renewed_until = (
            parsed_now + timedelta(seconds=max(int(lease_ttl_seconds or 0), 0))
        ).isoformat()
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                UPDATE {SCHEMA}.protocol_stage_executions
                SET lease_expires_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (
                    renewed_until,
                    stage_execution_row["protocol_stage_execution_id"],
                ),
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
    ) -> dict[str, object] | None:
        created_routed_task: dict[str, object] | None = None
        routed_task_id = str(stage_execution_row.get("routed_task_id", "") or "")
        next_execution_id = ""
        next_stage_key = ""
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
            next_stage_key = str(next_stage.stage_key or "")
        if engine.routed_task_request is not None:
            created_routed_task = self._create_routed_task_in_tx(
                conn,
                engine.routed_task_request.model_dump(mode="json"),
                now=now,
            )
            request_record = created_routed_task.get("request")
            routed_task_id = str(getattr(request_record, "routed_task_id", "") or routed_task_id)
        completion_timestamp = now if engine.stage_status in {"completed", "failed", "blocked", "cancelled"} else ""
        started_at = str(engine.started_at or stage_execution_row.get("started_at", "") or "")
        timeout_at = str(engine.timeout_at or "")
        lease_owner = str(engine.lease_owner or "")
        lease_expires_at = str(engine.lease_expires_at or "")
        with cur(conn) as db_cur:
            if str(engine.participant_key or "").strip():
                selector_snapshot = engine.selector_snapshot.as_dict()
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_run_participants
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
                        jsonb(selector_snapshot),
                        jsonb(selector_snapshot),
                        now,
                        run_row["protocol_run_id"],
                        str(engine.participant_key or ""),
                    ),
                )
            db_cur.execute(
                f"""
                UPDATE {SCHEMA}.protocol_stage_executions
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
            db_cur.execute(
                f"""
                UPDATE {SCHEMA}.protocol_runs
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
                    next_execution_id or stage_execution_row["protocol_stage_execution_id"],
                    next_stage_key or stage_execution_row["stage_key"],
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
        log.info(
            "protocol transition applied run_id=%s stage_execution_id=%s transition=%s run_status=%s stage_status=%s error_code=%s next_stage=%s",
            str(run_row["protocol_run_id"] or ""),
            str(stage_execution_row["protocol_stage_execution_id"] or ""),
            str(engine.transition_kind or ""),
            str(engine.run_status or ""),
            str(engine.stage_status or ""),
            str(engine.transition_error_code or ""),
            str(engine.next_stage_key or ""),
        )
        if next_execution_id:
            refreshed_run_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_row["protocol_run_id"],),
            )
            refreshed_stage_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
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

    def advance_run_for_task_in_tx(
        self,
        conn,
        *,
        routed_task_id: str,
        now: str,
    ) -> None:
        stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE routed_task_id = %s",
            (routed_task_id,),
        )
        if stage_execution_row is None:
            return
        if str(stage_execution_row.get("status", "") or "") in {"completed", "failed", "blocked", "cancelled"}:
            return
        run_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
            (stage_execution_row["protocol_run_id"],),
        )
        task_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.routed_tasks WHERE routed_task_id = %s",
            (routed_task_id,),
        )
        if run_row is None or task_row is None:
            return
        document = self._protocol_document_for_run(conn, run_row)
        stage_execution = self._protocol_stage_execution_from_row(stage_execution_row)
        engine = self._protocol_engine.evaluate_task_result(
            document=document,
            run=self._protocol_run_from_row(run_row),
            stage_execution=stage_execution,
            stage_executions=self._protocol_stage_executions_for_run(conn, str(run_row["protocol_run_id"] or "")),
            result=self._protocol_stage_task_result_from_task_row(task_row),
            review_edge_counts=protocol_review_edge_counts(
                self._protocol_run_transitions_history(conn, str(run_row["protocol_run_id"] or ""))
            ),
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

    def _sweep_protocol_timeouts_in_tx(self, conn, *, now: str) -> ProtocolMaintenanceResultRecord:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT pse.protocol_stage_execution_id, pse.protocol_run_id
            FROM {SCHEMA}.protocol_stage_executions pse
            JOIN {SCHEMA}.protocol_runs pr
              ON pr.protocol_run_id = pse.protocol_run_id
            WHERE pse.status = 'running'
              AND coalesce(pse.timeout_at, '') <> ''
              AND pse.timeout_at::timestamptz <= %s::timestamptz
              AND pr.status = 'running'
            ORDER BY pse.timeout_at ASC, pse.protocol_stage_execution_id ASC
            """,
            (now,),
        )
        affected_run_ids: list[str] = []
        for row in rows:
            stage_execution_id = str(row.get("protocol_stage_execution_id", "") or "")
            run_id = str(row.get("protocol_run_id", "") or "")
            if not stage_execution_id or not run_id:
                continue
            stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
                (stage_execution_id,),
            )
            run_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_id,),
            )
            if stage_execution_row is None or run_row is None:
                continue
            document = self._protocol_document_for_run(conn, run_row)
            engine = self._protocol_engine.evaluate_stage_timeout(
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
            affected_run_ids.append(run_id)
        return ProtocolMaintenanceResultRecord(
            swept_count=len(affected_run_ids),
            affected_run_ids=sorted(set(item for item in affected_run_ids if item)),
        )

    def run_protocol_maintenance(self, *, now: str = "") -> ProtocolMaintenanceResultRecord:
        maintenance_now = str(now or utcnow_iso())
        with self._connect() as conn, write_tx(conn):
            result = self._sweep_protocol_timeouts_in_tx(conn, now=maintenance_now)
            if result.swept_count:
                log.info("protocol maintenance swept_timeouts=%s at=%s", result.swept_count, maintenance_now)
            return result

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
        builtin_slugs = {
            str(item.slug or "").strip()
            for item in builtin_protocol_template_summaries()
            if str(item.slug or "").strip()
        }
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
        if include_drafts is None:
            include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_definitions
                {where_sql}
                ORDER BY updated_at DESC, display_name ASC, slug ASC
                """,
                tuple(params),
            )
        visible = [
            self._protocol_record_from_row(row)
            for row in rows
            if self._protocol_visible_to_access(row, access=access, include_drafts=include_drafts)
            and str(row.get("visibility", "") or "") != "registry_template"
            and str(row.get("slug", "") or "").strip() not in builtin_slugs
        ]
        return visible[cursor : cursor + limit]

    def get_protocol_template(self, slug: str, *, access: ProtocolAccessContextRecord) -> ProtocolDefinitionDocumentRecord:
        del access
        if not self._config.protocol_registry_templates_enabled:
            raise KeyError(slug)
        return builtin_protocol_document(slug)

    def list_protocol_templates(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTemplateSummaryRecord]:
        if not self._config.protocol_registry_templates_enabled:
            return []
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return []
        return list(builtin_protocol_template_summaries())

    def get_protocol_authoring_manifest(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAuthoringManifestRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            raise PermissionError("Protocol authoring requires author access.")
        return ProtocolAuthoringManifestRecord(
            templates=self.list_protocol_templates(access=access),
            sections=list(PROTOCOL_AUTHORING_SECTION_OPTIONS),
            stage_kind_options=list(PROTOCOL_STAGE_KIND_OPTIONS),
            artifact_kind_options=list(PROTOCOL_ARTIFACT_KIND_OPTIONS),
            selector_kind_options=list(PROTOCOL_SELECTOR_KIND_OPTIONS),
        )

    def get_protocol(self, protocol_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolMutationRecord:
        include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=include_drafts)
            if visibility == "missing" or row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            if visibility == "not_visible":
                return ProtocolMutationRecord(
                    ok=False,
                    status="not_visible",
                    message="Protocol is not visible to this actor.",
                )
            raw_definition = row.get("draft_definition_json") or {}
            validation = validate_protocol_document(raw_definition, mode="draft")
            strict_document = self._strict_protocol_document(raw_definition)
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
                draft_document=strict_document,
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
        include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=include_drafts)
            if visibility == "missing" or row is None:
                raise KeyError(protocol_id)
            if visibility == "not_visible":
                raise PermissionError(protocol_id)
            version_row = self._protocol_version_row(conn, version_id)
            if version_row is None or str(version_row.get("protocol_id", "") or "") != protocol_id:
                raise KeyError(version_id)
            return self._protocol_version_from_row(version_row)

    def parse_protocol_document_text(
        self,
        *,
        access: ProtocolAccessContextRecord,
        definition_text: str,
        format: str = "json",
        validation_mode: str = "strict",
    ) -> ProtocolTextDocumentRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            raise PermissionError("Protocol draft writes require author access.")
        normalized_format = normalize_protocol_document_format(format)
        mode = "draft" if str(validation_mode or "").strip().lower() == "draft" else "strict"
        document = protocol_document_from_text(definition_text, format=normalized_format, mode=mode)
        validation = validate_protocol_document(document, mode=mode)
        return ProtocolTextDocumentRecord(
            format=normalized_format,
            text=protocol_document_to_text(document, format=normalized_format, mode=mode),
            document=document,
            validation=validation,
        )

    def export_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolTextDocumentRecord:
        include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        normalized_format = normalize_protocol_document_format(format)
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=include_drafts)
            if visibility == "missing" or row is None:
                raise KeyError(protocol_id)
            if visibility == "not_visible":
                raise PermissionError("Protocol is not visible to this actor.")
            document = row.get("draft_definition_json") or {}
            return ProtocolTextDocumentRecord(
                format=normalized_format,
                text=protocol_document_to_text(document, format=normalized_format, mode="draft"),
                document=document,
                validation=validate_protocol_document(document, mode="draft"),
            )

    def diff_protocol_draft(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        format: str = "json",
    ) -> ProtocolDefinitionDiffRecord:
        include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        normalized_format = normalize_protocol_document_format(format)
        with self._connect() as conn:
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=include_drafts)
            if visibility == "missing" or row is None:
                raise KeyError(protocol_id)
            if visibility == "not_visible":
                raise PermissionError("Protocol is not visible to this actor.")
            version_row = None
            current_version_id = str(row.get("current_version_id", "") or "")
            if current_version_id:
                version_row = self._protocol_version_row(conn, current_version_id)
            if version_row is None:
                version_row = self._latest_protocol_version_row(conn, protocol_id)
            if version_row is None:
                raise KeyError(protocol_id)
            published_document = version_row.get("definition_json") or {}
            return ProtocolDefinitionDiffRecord(
                protocol_id=str(protocol_id or ""),
                protocol_definition_version_id=str(version_row.get("protocol_definition_version_id", "") or ""),
                diff=protocol_document_unified_diff(
                    row.get("draft_definition_json") or {},
                    published_document,
                    left_label="draft",
                    right_label=f"published:v{int(version_row.get('version', 0) or 0)}",
                    format=normalized_format,
                    mode="draft",
                ),
                left_label="draft",
                right_label=f"published:v{int(version_row.get('version', 0) or 0)}",
            )

    def save_protocol_draft(
        self,
        *,
        access: ProtocolAccessContextRecord,
        protocol_id: str,
        slug: str,
        display_name: str,
        description: str,
        definition_json: RegistryJsonRecord,
        expected_revision: int | None = None,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol draft writes require author access.")
        protocol_key = str(protocol_id or uuid.uuid4().hex).strip()
        raw_definition = draft_protocol_document_data(definition_json.as_dict())
        now = utcnow_iso()
        with self._connect() as conn, write_tx(conn):
            existing_row = self._protocol_row(conn, protocol_key)
            if existing_row is not None and expected_revision is not None:
                current_revision = int(existing_row.get("draft_revision", 0) or 0)
                if current_revision != expected_revision:
                    current_raw_definition = existing_row.get("draft_definition_json") or {}
                    current_validation = validate_protocol_document(current_raw_definition, mode="draft")
                    current_document = self._strict_protocol_document(current_raw_definition)
                    return ProtocolMutationRecord(
                        ok=False,
                        status="conflict",
                        message=f"Protocol draft revision conflict: expected {expected_revision}, found {current_revision}.",
                        protocol=self._protocol_record_from_row(existing_row),
                        draft_definition_json=RegistryJsonRecord.model_validate(current_raw_definition),
                        draft_document=current_document,
                        validation=current_validation,
                    )
            current_metadata = dict(raw_definition.get("metadata") or {})
            normalized_slug = str(
                slug
                or current_metadata.get("slug", "")
                or (existing_row.get("slug", "") if existing_row is not None else "")
            ).strip() or f"draft-{protocol_key[:8]}"
            normalized_name = str(
                display_name
                or current_metadata.get("display_name", "")
                or (existing_row.get("display_name", "") if existing_row is not None else "")
                or ""
            ).strip()
            normalized_description = str(
                description
                or current_metadata.get("description", "")
                or (existing_row.get("description", "") if existing_row is not None else "")
                or ""
            ).strip()
            raw_definition = self._with_protocol_metadata(
                raw_definition,
                slug=slug,
                display_name=display_name,
                description=description,
            )
            raw_definition = draft_protocol_document_data(raw_definition)
            validation = validate_protocol_document(raw_definition, mode="draft")
            strict_document = self._strict_protocol_document(raw_definition)
            raw_hash = protocol_definition_content_hash(strict_document) if strict_document is not None else hashlib.sha256(
                json.dumps(raw_definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            existing_slug_row = self._protocol_row_for_slug(conn, normalized_slug)
            if existing_slug_row is not None and str(existing_slug_row.get("protocol_id", "") or "") != protocol_key:
                return ProtocolMutationRecord(
                    ok=False,
                    status="duplicate_slug",
                    message=f"Protocol slug {normalized_slug!r} already exists.",
                )
            if existing_row is None:
                with cur(conn) as db_cur:
                    db_cur.execute(
                        f"""
                        INSERT INTO {SCHEMA}.protocol_definitions (
                            protocol_id, slug, display_name, description, lifecycle_state, current_version_id,
                            owner_org_id, visibility, created_by, updated_by, draft_revision,
                            draft_definition_json, draft_content_hash, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, 'draft', '', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            protocol_key,
                            normalized_slug,
                            normalized_name,
                            normalized_description,
                            self._access_org_id(access),
                            PROTOCOL_DEFAULT_VISIBILITY,
                            self._access_actor_ref(access),
                            self._access_actor_ref(access),
                            1,
                            jsonb(raw_definition),
                            raw_hash,
                            now,
                            now,
                        ),
                    )
                    row = db_cur.fetchone()
            else:
                with cur(conn) as db_cur:
                    db_cur.execute(
                        f"""
                        UPDATE {SCHEMA}.protocol_definitions
                        SET slug = %s,
                            display_name = %s,
                            description = %s,
                            updated_by = %s,
                            draft_definition_json = %s,
                            draft_content_hash = %s,
                            draft_revision = COALESCE(draft_revision, 0) + 1,
                            updated_at = %s
                        WHERE protocol_id = %s
                        RETURNING *
                        """,
                        (
                            normalized_slug,
                            normalized_name,
                            normalized_description,
                            self._access_actor_ref(access),
                            jsonb(raw_definition),
                            raw_hash,
                            now,
                            protocol_key,
                        ),
                    )
                    row = db_cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to save protocol draft")
            return ProtocolMutationRecord(
                ok=True,
                status="saved",
                message="Protocol draft saved.",
                protocol=self._protocol_record_from_row(row),
                draft_definition_json=RegistryJsonRecord.model_validate(raw_definition),
                draft_document=strict_document,
                validation=validation,
            )

    def create_protocol_draft(
        self,
        payload: ProtocolDraftCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol draft writes require author access.")
        source_kind = str(payload.source_kind or "blank").strip()
        with self._connect() as conn:
            if source_kind == "template":
                try:
                    template = self.get_protocol_template(payload.template_slug, access=access)
                except PermissionError:
                    return ProtocolMutationRecord(ok=False, status="not_visible", message="Protocol template is not visible to this actor.")
                except KeyError:
                    return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol template not found.")
                base_slug = template.slug or "protocol"
                unique_slug = self._unique_protocol_slug(conn, f"{base_slug}-draft")
                display_name = str(payload.display_name or f"{template.display_name} Draft").strip()
                description = str(payload.description or template.description or "").strip()
                definition_json = self._with_protocol_metadata(
                    template.model_dump(mode="json"),
                    slug=str(payload.slug or unique_slug).strip(),
                    display_name=display_name,
                    description=description,
                )
                return self.save_protocol_draft(
                    access=access,
                    protocol_id="",
                    slug=str(payload.slug or unique_slug).strip(),
                    display_name=display_name,
                    description=description,
                    definition_json=RegistryJsonRecord.model_validate(definition_json),
                )
            if source_kind == "protocol":
                loaded = self.get_protocol(str(payload.source_protocol_id or "").strip(), access=access)
                if not loaded.ok:
                    return loaded
                source_document = loaded.draft_document.model_dump(mode="json") if loaded.draft_document is not None else loaded.draft_definition_json.as_dict()
                source_metadata = dict(source_document.get("metadata") or {})
                base_slug = str(source_metadata.get("slug", "") or loaded.protocol.slug or "protocol").strip()
                unique_slug = self._unique_protocol_slug(conn, f"{base_slug}-draft")
                source_display_name = str(source_metadata.get("display_name", "") or loaded.protocol.display_name or base_slug).strip()
                source_description = str(source_metadata.get("description", "") or loaded.protocol.description or "").strip()
                display_name = str(payload.display_name or f"{source_display_name} Draft").strip()
                description = str(payload.description or source_description or "").strip()
                definition_json = self._with_protocol_metadata(
                    source_document,
                    slug=str(payload.slug or unique_slug).strip(),
                    display_name=display_name,
                    description=description,
                )
                return self.save_protocol_draft(
                    access=access,
                    protocol_id="",
                    slug=str(payload.slug or unique_slug).strip(),
                    display_name=display_name,
                    description=description,
                    definition_json=RegistryJsonRecord.model_validate(definition_json),
                )
            display_name = str(payload.display_name or "").strip()
            description = str(payload.description or "").strip()
            blank_document = self._blank_protocol_document(
                slug=str(payload.slug or "").strip(),
                display_name=display_name,
                description=description,
            )
            return self.save_protocol_draft(
                access=access,
                protocol_id="",
                slug=str(payload.slug or "").strip(),
                display_name=display_name,
                description=description,
                definition_json=RegistryJsonRecord.model_validate(blank_document),
            )

    def delete_protocol(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol draft delete requires author access.")
        with self._connect() as conn, write_tx(conn):
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=True)
            if visibility == "missing" or row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            if visibility == "not_visible":
                return ProtocolMutationRecord(ok=False, status="not_visible", message="Protocol is not visible to this actor.")
            if str(row.get("current_version_id", "") or "").strip():
                return ProtocolMutationRecord(ok=False, status="invalid_action", message="Published protocols must be archived instead of deleted.")
            if str(row.get("lifecycle_state", "") or "").strip() != "draft":
                return ProtocolMutationRecord(ok=False, status="invalid_action", message="Only unpublished draft protocols can be discarded.")
            run_count_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT COUNT(*) AS run_count FROM {SCHEMA}.protocol_runs WHERE protocol_id = %s",
                (protocol_id,),
            ) or {"run_count": 0}
            if int(run_count_row.get("run_count", 0) or 0) > 0:
                return ProtocolMutationRecord(ok=False, status="invalid_action", message="Protocols with existing runs cannot be discarded.")
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"DELETE FROM {SCHEMA}.protocol_definitions WHERE protocol_id = %s RETURNING *",
                    (protocol_id,),
                )
                deleted_row = db_cur.fetchone()
        if deleted_row is None:
            raise RuntimeError("Failed to delete protocol draft")
        return ProtocolMutationRecord(
            ok=True,
            status="deleted",
            message="Protocol draft discarded.",
            protocol=self._protocol_record_from_row(deleted_row),
            draft_definition_json=RegistryJsonRecord.model_validate(deleted_row.get("draft_definition_json") or {}),
            draft_document=None,
            version=None,
            validation=validate_protocol_document(deleted_row.get("draft_definition_json") or {}, mode="draft"),
        )

    def validate_protocol(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        loaded = self.get_protocol(protocol_id, access=access)
        if not loaded.ok or loaded.protocol is None:
            return loaded
        strict_validation = validate_protocol_document(loaded.draft_definition_json.as_dict(), mode="strict")
        return ProtocolMutationRecord(
            ok=True,
            status="validated" if strict_validation.ok else "invalid",
            message="Protocol validated." if strict_validation.ok else "Protocol is invalid.",
            protocol=loaded.protocol,
            draft_definition_json=loaded.draft_definition_json,
            draft_document=strict_validation.normalized_document if strict_validation.ok else None,
            version=loaded.version,
            validation=strict_validation,
        )

    def publish_protocol(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol publish requires publisher access.")
        loaded = self.get_protocol(protocol_id, access=access)
        if not loaded.ok or loaded.protocol is None:
            return loaded
        strict_validation = validate_protocol_document(loaded.draft_definition_json.as_dict(), mode="strict")
        if not strict_validation.ok or strict_validation.normalized_document is None:
            return ProtocolMutationRecord(
                ok=False,
                status="invalid",
                message="Protocol draft is invalid.",
                protocol=loaded.protocol,
                draft_definition_json=loaded.draft_definition_json,
                draft_document=None,
                version=loaded.version,
                validation=strict_validation,
            )
        strict_document = strict_validation.normalized_document
        now = utcnow_iso()
        version: ProtocolDefinitionVersionRecord | None = None
        with self._connect() as conn, write_tx(conn):
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM {SCHEMA}.protocol_definition_versions WHERE protocol_id = %s",
                    (protocol_id,),
                )
                next_version_row = db_cur.fetchone() or {"next_version": 1}
                next_version = int(next_version_row.get("next_version", 1) or 1)
                version_id = uuid.uuid4().hex
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_definition_versions (
                        protocol_definition_version_id, protocol_id, version, definition_json,
                        content_hash, validation_status, published_at, published_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, 'valid', %s, %s, %s)
                    """,
                    (
                        version_id,
                        protocol_id,
                        next_version,
                        jsonb(strict_document.model_dump(mode="json")),
                        protocol_definition_content_hash(strict_document),
                        now,
                        self._access_actor_ref(access),
                        now,
                    ),
                )
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_definitions
                    SET current_version_id = %s,
                        lifecycle_state = 'published',
                        updated_by = %s,
                        updated_at = %s
                    WHERE protocol_id = %s
                    RETURNING *
                    """,
                    (
                        version_id,
                        self._access_actor_ref(access),
                        now,
                        protocol_id,
                    ),
                )
                row = db_cur.fetchone()
                version = record(
                    ProtocolDefinitionVersionRecord,
                    {
                        "protocol_definition_version_id": version_id,
                        "protocol_id": protocol_id,
                        "version": next_version,
                        "definition_json": strict_document.model_dump(mode="json"),
                        "content_hash": protocol_definition_content_hash(strict_document),
                        "validation_status": "valid",
                        "published_at": now,
                        "published_by": self._access_actor_ref(access),
                        "created_at": now,
                    },
                )
        if row is None:
            raise RuntimeError("Failed to publish protocol")
        return ProtocolMutationRecord(
            ok=True,
            status="published",
            message="Protocol published.",
            protocol=self._protocol_record_from_row(row),
            draft_definition_json=RegistryJsonRecord.model_validate(row.get("draft_definition_json") or {}),
            draft_document=strict_document,
            version=version,
            validation=strict_validation,
        )

    def archive_protocol(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol archive requires publisher access.")
        now = utcnow_iso()
        with self._connect() as conn, write_tx(conn):
            row = self._protocol_row(conn, protocol_id)
            visibility = self._protocol_visibility_status(row, access=access, include_drafts=True)
            if visibility == "missing" or row is None:
                return ProtocolMutationRecord(ok=False, status="not_found", message="Protocol not found.")
            if visibility == "not_visible":
                return ProtocolMutationRecord(ok=False, status="not_visible", message="Protocol is not visible to this actor.")
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_definitions
                    SET lifecycle_state = 'archived', updated_by = %s, updated_at = %s
                    WHERE protocol_id = %s
                    RETURNING *
                    """,
                    (self._access_actor_ref(access), now, protocol_id),
                )
                updated_row = db_cur.fetchone()
        if updated_row is None:
            raise RuntimeError("Failed to archive protocol")
        return ProtocolMutationRecord(
            ok=True,
            status="archived",
            message="Protocol archived.",
            protocol=self._protocol_record_from_row(updated_row),
            draft_definition_json=RegistryJsonRecord.model_validate(updated_row.get("draft_definition_json") or {}),
            draft_document=self._draft_protocol_document(updated_row),
            version=None,
            validation=validate_protocol_document(updated_row.get("draft_definition_json") or {}, mode="draft"),
        )

    def list_protocol_runs(
        self,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 25,
        cursor: int = 0,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        origin_channel: str = "",
    ) -> list[ProtocolRunRecord]:
        params: list[object] = []
        clauses: list[str] = []
        if status:
            params.append(status)
            clauses.append("pr.status = %s")
        if protocol_id:
            params.append(protocol_id)
            clauses.append("pr.protocol_id = %s")
        if entry_agent_id:
            params.append(entry_agent_id)
            clauses.append("pr.entry_agent_id = %s")
        if origin_channel:
            params.append(origin_channel)
            clauses.append("pr.origin_channel = %s")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT pr.*, coalesce(c.external_conversation_ref, '') AS root_external_conversation_ref
                FROM {SCHEMA}.protocol_runs pr
                LEFT JOIN {SCHEMA}.conversations c
                  ON c.conversation_id = pr.root_conversation_id
                {where}
                ORDER BY pr.updated_at DESC, pr.created_at DESC
                """,
                tuple(params),
            )
            visible: list[ProtocolRunRecord] = []
            for row in rows:
                if self._assert_protocol_run_visible(row, access=access) is None:
                    continue
                visible.append(self._protocol_run_from_row(self._decorate_protocol_run_row_with_review_state(conn, row)))
        return visible[cursor : cursor + limit]

    def _protocol_issues_for_row(
        self,
        row: Mapping[str, object],
        *,
        now: str,
    ) -> list[ProtocolIssueRecord]:
        issues: list[ProtocolIssueRecord] = []
        run_status = str(row.get("run_status", "") or row.get("status", "") or "")
        stage_status = str(row.get("stage_status", "") or "")
        blocked_code = str(row.get("blocked_code", "") or "")
        blocked_detail = str(row.get("blocked_detail", "") or "")
        failure_code = str(row.get("failure_code", "") or "")
        failure_detail = str(row.get("failure_detail", "") or "")
        lease_expires_at = str(row.get("lease_expires_at", "") or "")
        timeout_at = str(row.get("timeout_at", "") or "")
        run_id = str(row.get("protocol_run_id", "") or "")
        protocol_id = str(row.get("protocol_id", "") or "")
        display_name = str(row.get("protocol_display_name", "") or row.get("display_name", "") or "")
        stage_execution_id = str(row.get("protocol_stage_execution_id", "") or "")
        stage_key = str(row.get("stage_key", "") or "")
        participant_key = str(row.get("participant_key", "") or "")
        updated_at = str(row.get("run_updated_at", "") or row.get("updated_at", "") or "")
        if run_status == "blocked":
            issues.append(
                ProtocolIssueRecord(
                    issue_kind="blocked_run",
                    protocol_run_id=run_id,
                    protocol_id=protocol_id,
                    protocol_display_name=display_name,
                    stage_execution_id=stage_execution_id,
                    stage_key=stage_key,
                    participant_key=participant_key,
                    run_status=run_status,
                    stage_status=stage_status or "blocked",
                    issue_code=blocked_code or failure_code or "blocked",
                    issue_detail=blocked_detail or failure_detail or "Protocol run is blocked.",
                    lease_expires_at=lease_expires_at,
                    timeout_at=timeout_at,
                    updated_at=updated_at,
                )
            )
        if blocked_code == "protocol_contract_invalid" or failure_code == "protocol_contract_invalid":
            issues.append(
                ProtocolIssueRecord(
                    issue_kind="invalid_contract",
                    protocol_run_id=run_id,
                    protocol_id=protocol_id,
                    protocol_display_name=display_name,
                    stage_execution_id=stage_execution_id,
                    stage_key=stage_key,
                    participant_key=participant_key,
                    run_status=run_status,
                    stage_status=stage_status or "blocked",
                    issue_code="protocol_contract_invalid",
                    issue_detail=blocked_detail or failure_detail or "Protocol result contract is invalid.",
                    lease_expires_at=lease_expires_at,
                    timeout_at=timeout_at,
                    updated_at=updated_at,
                )
            )
        if stage_status == "running" and lease_expires_at:
            try:
                if datetime.fromisoformat(lease_expires_at) <= datetime.fromisoformat(now):
                    issues.append(
                        ProtocolIssueRecord(
                            issue_kind="stuck_lease",
                            protocol_run_id=run_id,
                            protocol_id=protocol_id,
                            protocol_display_name=display_name,
                            stage_execution_id=stage_execution_id,
                            stage_key=stage_key,
                            participant_key=participant_key,
                            run_status=run_status or "running",
                            stage_status=stage_status,
                            issue_code="lease_expired",
                            issue_detail=f"Write lease expired at {lease_expires_at}.",
                            lease_expires_at=lease_expires_at,
                            timeout_at=timeout_at,
                            updated_at=updated_at,
                        )
                    )
            except ValueError:
                pass
        if stage_status == "running" and timeout_at:
            try:
                if datetime.fromisoformat(timeout_at) <= datetime.fromisoformat(now):
                    issues.append(
                        ProtocolIssueRecord(
                            issue_kind="expired_timeout",
                            protocol_run_id=run_id,
                            protocol_id=protocol_id,
                            protocol_display_name=display_name,
                            stage_execution_id=stage_execution_id,
                            stage_key=stage_key,
                            participant_key=participant_key,
                            run_status=run_status or "running",
                            stage_status=stage_status,
                            issue_code="stage_timeout_pending_sweep",
                            issue_detail=f"Stage timeout elapsed at {timeout_at}.",
                            lease_expires_at=lease_expires_at,
                            timeout_at=timeout_at,
                            updated_at=updated_at,
                        )
                    )
            except ValueError:
                pass
        return issues

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
        normalized_kind = str(issue_kind or "").strip().lower()
        normalized_run_id = str(protocol_run_id or "").strip()
        normalized_protocol_id = str(protocol_id or "").strip()
        now = utcnow_iso()
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT
                    pr.protocol_run_id,
                    pr.protocol_id,
                    pr.run_org_id,
                    pr.status AS run_status,
                    pr.blocked_code,
                    pr.blocked_detail,
                    pr.updated_at AS run_updated_at,
                    pd.display_name AS protocol_display_name,
                    pse.protocol_stage_execution_id,
                    pse.stage_key,
                    pse.participant_key,
                    pse.status AS stage_status,
                    pse.failure_code,
                    pse.failure_detail,
                    pse.lease_expires_at,
                    pse.timeout_at
                FROM {SCHEMA}.protocol_runs pr
                LEFT JOIN {SCHEMA}.protocol_stage_executions pse
                  ON pse.protocol_stage_execution_id = pr.current_stage_execution_id
                LEFT JOIN {SCHEMA}.protocol_definitions pd
                  ON pd.protocol_id = pr.protocol_id
                ORDER BY pr.updated_at DESC, pr.protocol_run_id DESC
                """,
            )
            issues: list[ProtocolIssueRecord] = []
            for row in rows:
                run_row = {
                    "protocol_run_id": row.get("protocol_run_id", ""),
                    "protocol_id": row.get("protocol_id", ""),
                    "status": row.get("run_status", ""),
                    "run_org_id": row.get("run_org_id", ""),
                }
                if self._assert_protocol_run_visible(run_row, access=access) is None:
                    continue
                for issue in self._protocol_issues_for_row(row, now=now):
                    if normalized_kind and issue.issue_kind != normalized_kind:
                        continue
                    if normalized_run_id and issue.protocol_run_id != normalized_run_id:
                        continue
                    if normalized_protocol_id and issue.protocol_id != normalized_protocol_id:
                        continue
                    issues.append(issue)
        return issues[cursor : cursor + limit]

    def create_protocol_run(
        self,
        payload: ProtocolRunCreateRecord,
        *,
        access: ProtocolAccessContextRecord,
        idempotency_key: str = "",
    ) -> ProtocolRunMutationRecord:
        request = payload if isinstance(payload, ProtocolRunCreateRecord) else ProtocolRunCreateRecord.model_validate(payload)
        entry_agent_id = str(request.entry_agent_id or "").strip()
        if not entry_agent_id:
            return ProtocolRunMutationRecord(
                ok=False,
                status="invalid",
                message="entry_agent_id is required to start a protocol run.",
            )
        authority_ref = str(request.entry_authority_ref or "").strip()
        if request.is_rehearsal:
            authority_ref = REHEARSAL_AUTHORITY_REF
        elif authority_ref == REHEARSAL_AUTHORITY_REF:
            return ProtocolRunMutationRecord(
                ok=False,
                status="invalid",
                message="entry_authority_ref 'rehearsal' is reserved; set is_rehearsal=true instead.",
            )
        request = request.model_copy(
            update={
                "entry_agent_id": entry_agent_id,
                "entry_authority_ref": authority_ref,
            }
        )
        request_hash = self._request_hash(
            {
                "payload": request.model_dump(mode="json"),
                "actor_ref": self._access_actor_ref(access),
                "org_id": self._access_org_id(access),
            }
        )
        now = utcnow_iso()
        with self._connect() as conn, write_tx(conn):
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
            lifecycle_state = str(protocol_row.get("lifecycle_state", "") or "")
            if lifecycle_state != "published" and not request.is_rehearsal:
                return ProtocolRunMutationRecord(ok=False, status="invalid", message="Only published protocols can start runs.")
            if lifecycle_state == "archived":
                return ProtocolRunMutationRecord(ok=False, status="invalid", message="Archived protocols cannot start runs.")
            if not shared_agent_exists(
                conn,
                dialect=POSTGRES_STORE_DIALECT,
                agent_id=request.entry_agent_id,
            ):
                return ProtocolRunMutationRecord(
                    ok=False,
                    status="invalid",
                    message=f"entry_agent_id does not reference a known managed bot: {request.entry_agent_id}",
                )
            document = canonical_protocol_document(version_row["definition_json"])
            run_id = uuid.uuid4().hex
            root_conversation_id = str(request.root_conversation_id or "").strip()
            if not root_conversation_id:
                created = shared_create_conversation(
                    conn,
                    dialect=POSTGRES_STORE_DIALECT,
                    target_agent_id=request.entry_agent_id,
                    title=document.display_name or document.slug or "Protocol run",
                    origin_channel="registry",
                    external_conversation_ref=f"protocol-run:{run_id}",
                    now=now,
                )
                root_conversation_id = str(created.conversation_id or "")
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_runs (
                        protocol_run_id, protocol_id, protocol_definition_version_id,
                        entry_agent_id, entry_authority_ref, is_rehearsal, root_conversation_id,
                        origin_channel, workspace_ref, repo_ref, branch_ref,
                        problem_statement, constraints_json, status,
                        current_stage_execution_id, current_stage_key, termination_summary,
                        blocked_code, blocked_detail, run_org_id, started_by, version,
                        retention_until, last_transition_at, created_at, updated_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', '', '', '', '', '', %s, %s, 1, %s, '', %s, %s, '')
                    RETURNING *
                    """,
                    (
                        run_id,
                        protocol_row["protocol_id"],
                        version_row["protocol_definition_version_id"],
                        request.entry_agent_id,
                        request.entry_authority_ref,
                        bool(request.is_rehearsal),
                        root_conversation_id,
                        request.origin_channel,
                        request.workspace_ref,
                        request.repo_ref,
                        request.branch_ref,
                        request.problem_statement,
                        jsonb(
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
                run_row = db_cur.fetchone()
                if run_row is None:
                    raise RuntimeError("Failed to create protocol run")
                for participant in document.participants:
                    participant_selector, required_skills = _participant_assignment_projection(document, participant.participant_key)
                    db_cur.execute(
                        f"""
                        INSERT INTO {SCHEMA}.protocol_run_participants (
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
                            jsonb(required_skills),
                            jsonb(participant_selector.model_dump(mode="json") if participant_selector is not None else {}),
                            protocol_participant_session_key(run_id, participant.participant_key),
                            jsonb({}),
                            now,
                            now,
                        ),
                    )
                for artifact in document.artifacts:
                    db_cur.execute(
                        f"""
                        INSERT INTO {SCHEMA}.protocol_artifacts (
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
                response_json=json_ready(result.model_dump(mode="json")),
                now=now,
            )
            return result

    def get_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunDetailRecord:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail

    def get_protocol_run_participants(self, run_id: str, *, access: ProtocolAccessContextRecord) -> list[ProtocolRunParticipantRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.participants

    def get_protocol_run_artifacts(self, run_id: str, *, access: ProtocolAccessContextRecord) -> list[ProtocolArtifactRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.artifacts

    def get_protocol_run_timeline(self, run_id: str, *, access: ProtocolAccessContextRecord) -> list[ProtocolTransitionRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.transitions

    def export_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunExportRecord:
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
        with self._connect() as conn, write_tx(conn):
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
            raw_run_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_id,),
            )
            run_visibility = self._protocol_run_visibility_status(raw_run_row, access=access)
            if run_visibility == "missing":
                return ProtocolRunMutationRecord(ok=False, status="not_found", message="Protocol run not found.")
            if run_visibility == "not_visible":
                return ProtocolRunMutationRecord(ok=False, status="not_visible", message="Protocol run is not visible to this actor.")
            run_row = dict(raw_run_row or {})
            current_version = int(run_row.get("version", 1) or 1)
            if expected_version is not None and current_version != int(expected_version):
                return ProtocolRunMutationRecord(
                    ok=False,
                    status="concurrent_modification",
                    message=f"Protocol run version conflict: expected {expected_version}, found {current_version}.",
                )
            current_stage_execution_id = str(run_row.get("current_stage_execution_id", "") or "")
            stage_execution_row = None
            if current_stage_execution_id:
                stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
                    (current_stage_execution_id,),
                )
            if stage_execution_row is None:
                stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"""
                    SELECT *
                    FROM {SCHEMA}.protocol_stage_executions
                    WHERE protocol_run_id = %s
                    ORDER BY started_at DESC, protocol_stage_execution_id DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
            if stage_execution_row is None:
                return ProtocolRunMutationRecord(ok=False, status="invalid", message="Protocol run has no active stage execution.")
            document = self._protocol_document_for_run(conn, run_row)
            engine = self._protocol_engine.evaluate_operator_action(
                document=document,
                run=self._protocol_run_from_row(run_row),
                stage_execution=self._protocol_stage_execution_from_row(stage_execution_row),
                stage_executions=self._protocol_stage_executions_for_run(conn, run_id),
                action=normalized_action,
                reason=reason,
                now=now,
                review_edge_counts=protocol_review_edge_counts(self._protocol_run_transitions_history(conn, run_id)),
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
                response_json=json_ready(result.model_dump(mode="json")),
                now=now,
            )
            return result

    @staticmethod
    def _protocol_scenario_from_row(row: Mapping[str, object]) -> ProtocolScenarioRecord:
        return record(
            ProtocolScenarioRecord,
            {
                "protocol_scenario_id": row["protocol_scenario_id"],
                "protocol_id": row.get("protocol_id", ""),
                "stage_key": row.get("stage_key", ""),
                "participant_key": row.get("participant_key", ""),
                "display_name": row.get("display_name", ""),
                "decision": row.get("decision", ""),
                "decision_summary": row.get("decision_summary", ""),
                "response_text": row.get("response_text", ""),
                "run_org_id": row.get("run_org_id", PROTOCOL_DEFAULT_RUN_ORG_ID),
                "created_by": row.get("created_by", ""),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    def list_protocol_scenarios(
        self,
        *,
        protocol_id: str = "",
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolScenarioRecord]:
        org_id = self._access_org_id(access)
        with self._connect() as conn:
            with cur(conn) as db_cur:
                if protocol_id:
                    db_cur.execute(
                        f"""
                        SELECT * FROM {SCHEMA}.protocol_scenarios
                        WHERE run_org_id = %s AND protocol_id = %s
                        ORDER BY updated_at DESC
                        """,
                        (org_id, str(protocol_id).strip()),
                    )
                else:
                    db_cur.execute(
                        f"""
                        SELECT * FROM {SCHEMA}.protocol_scenarios
                        WHERE run_org_id = %s
                        ORDER BY updated_at DESC
                        """,
                        (org_id,),
                    )
                rows = db_cur.fetchall() or []
        return [self._protocol_scenario_from_row(row) for row in rows]

    def create_protocol_scenario(
        self,
        *,
        payload: Mapping[str, object],
        access: ProtocolAccessContextRecord,
    ) -> ProtocolScenarioRecord:
        candidate = ProtocolScenarioRecord.model_validate(dict(payload or {}))
        protocol_id = str(candidate.protocol_id or "").strip()
        if not protocol_id:
            raise ValueError("protocol_id is required to create a scenario.")
        display_name = str(candidate.display_name or "").strip() or "Untitled scenario"
        decision = str(candidate.decision or "").strip().lower()
        decision_summary = str(candidate.decision_summary or "").strip()
        response_text = str(candidate.response_text or "")
        now = utcnow_iso()
        scenario_id = uuid.uuid4().hex
        org_id = self._access_org_id(access)
        actor_ref = self._access_actor_ref(access)
        with self._connect() as conn, write_tx(conn):
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_scenarios (
                        protocol_scenario_id, protocol_id, stage_key, participant_key,
                        display_name, decision, decision_summary, response_text, run_org_id, created_by,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        scenario_id,
                        protocol_id,
                        str(candidate.stage_key or "").strip(),
                        str(candidate.participant_key or "").strip(),
                        display_name,
                        decision,
                        decision_summary,
                        response_text,
                        org_id,
                        actor_ref,
                        now,
                        now,
                    ),
                )
                row = db_cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to create protocol scenario.")
        return self._protocol_scenario_from_row(row)

    def delete_protocol_scenario(
        self,
        *,
        scenario_id: str,
        access: ProtocolAccessContextRecord,
    ) -> bool:
        token = str(scenario_id or "").strip()
        if not token:
            return False
        org_id = self._access_org_id(access)
        with self._connect() as conn, write_tx(conn):
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    DELETE FROM {SCHEMA}.protocol_scenarios
                    WHERE protocol_scenario_id = %s AND run_org_id = %s
                    """,
                    (token, org_id),
                )
                return bool(db_cur.rowcount or 0)
