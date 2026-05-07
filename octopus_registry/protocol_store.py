"""Dedicated Postgres adapter for protocol definitions, runs, and orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal

from octopus_sdk.protocols import (
    PROTOCOL_ARTIFACT_KIND_OPTIONS,
    PROTOCOL_AUTHORING_SECTION_OPTIONS,
    PROTOCOL_AUTHORING_SURFACE_OPTIONS,
    PROTOCOL_DEFAULT_OPERATOR_REF,
    PROTOCOL_DEFAULT_RETENTION_DAYS,
    PROTOCOL_DEFAULT_RUN_ORG_ID,
    PROTOCOL_SELECTOR_KIND_OPTIONS,
    PROTOCOL_STAGE_KIND_OPTIONS,
    PROTOCOL_DEFAULT_VISIBILITY,
    REHEARSAL_AUTHORITY_REF,
    ProtocolAuthoringOptionsRecord,
    ProtocolAccessContextRecord,
    ProtocolAutoDesignEventSummaryRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
    ProtocolArtifactObservationRecord,
    ProtocolArtifactRecord,
    ProtocolArtifactSnapshotRecord,
    ProtocolArtifactRuntimeEventRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
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
    protocol_review_edge_key,
    runtime_manifest_run_ready_blockers,
    stage_target_for_decision,
    auto_protocol_event_summary,
    auto_protocol_runtime_expected_from_text,
    generate_auto_protocol_session,
    revise_auto_protocol_session,
    validate_protocol_document,
)
from octopus_sdk.protocols.documents import draft_protocol_document_data
from octopus_sdk.protocols.engine import ProtocolRunEngine
from octopus_sdk.registry.models import normalized_requested_skills, utcnow_iso

from .artifact_snapshots import artifact_snapshot_storage_path, create_artifact_snapshot
from .config import RegistryConfig, load_registry_config
from .artifact_paths import resolve_protocol_artifact_path
from .postgres import get_connection
from .postgres_store_support import POSTGRES_STORE_DIALECT, SCHEMA, cur, jsonb, write_tx
from .protocol_runtime import evaluate_protocol_dispatch
from .store_base import RoutingSkillDisabledError
from .store_shared.common import json_ready, record
from .store_shared.agents import agent_exists as shared_agent_exists
from .store_shared.conversations import create_conversation as shared_create_conversation
from .store_shared.tasks import tasks_for_routed_ids

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
        for role in ("admin", "publisher", "author", "auditor", "operator", "agent"):
            if access is not None and access.has_role(role):
                return role
        return "service"

    @classmethod
    def _access_can_edit_protocol_internals(cls, access: ProtocolAccessContextRecord | None) -> bool:
        return any(cls._access_has_role(access, role) for role in ("publisher", "admin"))

    @classmethod
    def _normalize_authoring_surface(
        cls,
        value: object,
        *,
        access: ProtocolAccessContextRecord | None,
    ) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return "operator" if cls._access_can_edit_protocol_internals(access) else "standard"
        if normalized not in PROTOCOL_AUTHORING_SURFACE_OPTIONS:
            return "standard"
        if normalized == "operator" and not cls._access_can_edit_protocol_internals(access):
            raise PermissionError("Operator authoring surface requires protocol-internal edit access.")
        return normalized

    @classmethod
    def _validate_standard_surface_document(
        cls,
        definition: Mapping[str, object],
        *,
        existing_definition: Mapping[str, object] | None = None,
    ) -> str | None:
        existing_stage_map = {
            str(item.get("stage_key", "") or ""): item
            for item in (existing_definition or {}).get("stages", [])
            if isinstance(item, Mapping) and str(item.get("stage_key", "") or "").strip()
        }
        for raw_stage in definition.get("stages", []) or []:
            if not isinstance(raw_stage, Mapping):
                continue
            stage_key = str(raw_stage.get("stage_key", "") or "").strip()
            existing_stage = existing_stage_map.get(stage_key, {})
            selector = raw_stage.get("selector")
            selector_kind = str(selector.get("kind", "") or "").strip().lower() if isinstance(selector, Mapping) else ""
            existing_selector = existing_stage.get("selector")
            existing_selector_kind = (
                str(existing_selector.get("kind", "") or "").strip().lower()
                if isinstance(existing_selector, Mapping)
                else ""
            )
            if selector_kind and selector_kind not in {"agent", "skill"}:
                if not existing_stage or selector != existing_selector:
                    return (
                        f"Standard authoring cannot set runtime selector kind {selector_kind!r} "
                        f"for stage {stage_key or 'step'}."
                    )
            elif existing_selector_kind and existing_selector_kind not in {"agent", "skill"} and selector != existing_selector:
                return f"Standard authoring cannot modify the operator-managed assignment on stage {stage_key or 'step'}."
            for field_name in ("max_rounds", "timeout_seconds"):
                incoming = int(raw_stage.get(field_name, 0) or 0)
                existing = int(existing_stage.get(field_name, 0) or 0) if isinstance(existing_stage, Mapping) else 0
                if incoming != existing:
                    if not existing_stage and incoming == 0:
                        continue
                    return f"Standard authoring cannot edit {field_name} on stage {stage_key or 'step'}."
        return None

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
    def _protocol_template_summary_from_document(
        document: ProtocolDefinitionDocumentRecord,
        *,
        featured: bool = False,
    ) -> ProtocolTemplateSummaryRecord:
        metadata = document.metadata.as_dict()
        return ProtocolTemplateSummaryRecord(
            slug=str(metadata.get("slug", "") or "").strip(),
            display_name=str(metadata.get("display_name", "") or metadata.get("slug", "") or "Protocol template").strip(),
            description=str(metadata.get("description", "") or "").strip(),
            featured=featured,
            participant_count=len(document.participants),
            artifact_count=len(document.artifacts),
            stage_count=len(document.stages),
            stage_kind_sequence=[stage.stage_kind for stage in document.stages],
        )

    @staticmethod
    def _protocol_run_from_row(row: Mapping[str, object]) -> ProtocolRunRecord:
        return record(
            ProtocolRunRecord,
            {
                "protocol_run_id": row["protocol_run_id"],
                "protocol_id": row["protocol_id"],
                "protocol_definition_version_id": row["protocol_definition_version_id"],
                "source_kind": row.get("source_kind", "protocol_run") or "protocol_run",
                "hidden_from_default_views": bool(row.get("hidden_from_default_views", False)),
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
    def _protocol_artifact_runtime_from_row(row: Mapping[str, object]) -> ProtocolArtifactRuntimeInstanceRecord:
        manifest_json = row.get("manifest_json") or {}
        manifest = None
        if isinstance(manifest_json, Mapping) and manifest_json:
            try:
                manifest = ProtocolArtifactRuntimeManifestRecord.model_validate(manifest_json)
            except Exception:
                manifest = None
        return record(
            ProtocolArtifactRuntimeInstanceRecord,
            {
                "runtime_instance_id": row["runtime_instance_id"],
                "protocol_run_id": row["protocol_run_id"],
                "artifact_key": row["artifact_key"],
                "agent_id": row.get("agent_id", ""),
                "status": row.get("status", "not_configured"),
                "manifest": manifest,
                "manifest_path": row.get("manifest_path", ""),
                "artifact_path": row.get("artifact_path", ""),
                "runtime_url": row.get("runtime_url", ""),
                "ui_url": row.get("ui_url", ""),
                "api_url": row.get("api_url", ""),
                "health_url": row.get("health_url", ""),
                "internal_url": row.get("internal_url", ""),
                "pid": row.get("pid", 0),
                "port": row.get("port", 0),
                "started_by": row.get("started_by", ""),
                "stopped_by": row.get("stopped_by", ""),
                "failure_code": row.get("failure_code", ""),
                "failure_detail": row.get("failure_detail", ""),
                "log_tail": row.get("log_tail", ""),
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
                "started_at": row.get("started_at", ""),
                "stopped_at": row.get("stopped_at", ""),
                "expires_at": row.get("expires_at", ""),
            },
        )

    @staticmethod
    def _protocol_artifact_snapshot_from_row(row: Mapping[str, object]) -> ProtocolArtifactSnapshotRecord:
        return record(
            ProtocolArtifactSnapshotRecord,
            {
                "artifact_snapshot_id": row["artifact_snapshot_id"],
                "protocol_artifact_id": row.get("protocol_artifact_id", ""),
                "protocol_run_id": row["protocol_run_id"],
                "artifact_key": row["artifact_key"],
                "snapshot_kind": row.get("snapshot_kind", "file"),
                "storage_uri": row.get("storage_uri", ""),
                "content_hash": row.get("content_hash", ""),
                "size_bytes": row.get("size_bytes", 0),
                "manifest_json": row.get("manifest_json") or {},
                "retention_state": row.get("retention_state", "active"),
                "retention_until": row.get("retention_until", ""),
                "created_at": row.get("created_at", ""),
                "created_by": row.get("created_by", ""),
                "deleted_at": row.get("deleted_at", ""),
                "deleted_by": row.get("deleted_by", ""),
            },
        )

    @staticmethod
    def _protocol_artifact_runtime_event_from_row(row: Mapping[str, object]) -> ProtocolArtifactRuntimeEventRecord:
        return record(
            ProtocolArtifactRuntimeEventRecord,
            {
                "runtime_event_id": row["runtime_event_id"],
                "runtime_instance_id": row["runtime_instance_id"],
                "protocol_run_id": row["protocol_run_id"],
                "artifact_key": row["artifact_key"],
                "event_kind": row["event_kind"],
                "actor_ref": row.get("actor_ref", ""),
                "summary": row.get("summary", ""),
                "metadata_json": row.get("metadata_json", {}),
                "created_at": row.get("created_at", ""),
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
            if (
                row is None or str(row.get("protocol_id", "") or "") == str(protocol_id or "")
            ):
                return candidate
            suffix += 1
            candidate = f"{normalized}-{suffix}"

    def _protocol_template_document_from_row(
        self,
        conn,
        row: Mapping[str, object],
    ) -> ProtocolDefinitionDocumentRecord:
        version_row = None
        current_version_id = str(row.get("current_version_id", "") or "").strip()
        if current_version_id:
            version_row = self._protocol_version_row(conn, current_version_id)
        raw_definition = (version_row or {}).get("definition_json") or row.get("draft_definition_json") or {}
        return ProtocolDefinitionDocumentRecord.model_validate(raw_definition)

    def _protocol_template_summary_from_row(
        self,
        conn,
        row: Mapping[str, object],
    ) -> ProtocolTemplateSummaryRecord:
        return self._protocol_template_summary_from_document(
            self._protocol_template_document_from_row(conn, row),
            featured=False,
        )

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
        routed_task_ids = [
            str(row.get("routed_task_id", "") or "").strip()
            for row in stage_rows
            if str(row.get("routed_task_id", "") or "").strip()
        ]
        return ProtocolRunDetailRecord(
            run=self._protocol_run_from_row(run_row),
            definition=self._protocol_record_from_row(definition_row),
            version=self._protocol_version_from_row(version_row),
            participants=[self._protocol_run_participant_from_row(row) for row in participant_rows],
            stage_executions=[self._protocol_stage_execution_from_row(row) for row in stage_rows],
            tasks=tasks_for_routed_ids(
                conn,
                dialect=POSTGRES_STORE_DIALECT,
                routed_task_ids=routed_task_ids,
            ),
            artifacts=self._protocol_artifacts_for_run(conn, run_id),
            artifact_snapshots=self._protocol_artifact_snapshots_for_run(conn, run_id),
            runtime_instances=self._protocol_artifact_runtimes_for_run(conn, run_id),
            runtime_events=self._protocol_artifact_runtime_events_for_run(conn, run_id),
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

    def _protocol_artifact_snapshots_for_run(self, conn, run_id: str) -> list[ProtocolArtifactSnapshotRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifact_snapshots
            WHERE protocol_run_id = %s
              AND retention_state <> 'deleted'
            ORDER BY artifact_key, created_at DESC
            """,
            (run_id,),
        )
        newest: dict[str, ProtocolArtifactSnapshotRecord] = {}
        for row in rows:
            snapshot = self._protocol_artifact_snapshot_from_row(row)
            newest.setdefault(snapshot.artifact_key, snapshot)
        return list(newest.values())

    def _protocol_artifact_snapshot_for_key(
        self,
        conn,
        run_id: str,
        artifact_key: str,
    ) -> ProtocolArtifactSnapshotRecord | None:
        row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifact_snapshots
            WHERE protocol_run_id = %s
              AND artifact_key = %s
              AND retention_state <> 'deleted'
            ORDER BY created_at DESC, artifact_snapshot_id DESC
            LIMIT 1
            """,
            (run_id, artifact_key),
        )
        return self._protocol_artifact_snapshot_from_row(row) if row is not None else None

    def _insert_protocol_artifact_snapshot_in_tx(
        self,
        conn,
        snapshot: ProtocolArtifactSnapshotRecord,
        *,
        actor_ref: str,
        now: str,
    ) -> None:
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_artifact_snapshots (
                    artifact_snapshot_id, protocol_artifact_id, protocol_run_id, artifact_key,
                    snapshot_kind, storage_uri, content_hash, size_bytes, manifest_json,
                    retention_state, retention_until, created_at, created_by, deleted_at, deleted_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_snapshot_id) DO UPDATE SET
                    protocol_artifact_id = EXCLUDED.protocol_artifact_id,
                    storage_uri = EXCLUDED.storage_uri,
                    content_hash = EXCLUDED.content_hash,
                    size_bytes = EXCLUDED.size_bytes,
                    manifest_json = EXCLUDED.manifest_json,
                    retention_state = EXCLUDED.retention_state,
                    retention_until = EXCLUDED.retention_until,
                    deleted_at = EXCLUDED.deleted_at,
                    deleted_by = EXCLUDED.deleted_by
                """,
                (
                    snapshot.artifact_snapshot_id,
                    snapshot.protocol_artifact_id,
                    snapshot.protocol_run_id,
                    snapshot.artifact_key,
                    snapshot.snapshot_kind,
                    snapshot.storage_uri,
                    snapshot.content_hash,
                    snapshot.size_bytes,
                    jsonb(snapshot.manifest_json.as_dict()),
                    snapshot.retention_state or "active",
                    snapshot.retention_until,
                    snapshot.created_at or now,
                    snapshot.created_by or actor_ref,
                    snapshot.deleted_at,
                    snapshot.deleted_by,
                ),
            )
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_transitions (
                    protocol_transition_id, protocol_run_id, transition_kind,
                    decision, reason, metadata_json, actor_type, actor_ref, created_at
                ) VALUES (%s, %s, 'artifact_snapshot', 'snapshotted', %s, %s, 'registry', %s, %s)
                """,
                (
                    uuid.uuid4().hex,
                    snapshot.protocol_run_id,
                    f"Artifact {snapshot.artifact_key} snapshotted.",
                    jsonb({
                        "artifact_key": snapshot.artifact_key,
                        "artifact_snapshot_id": snapshot.artifact_snapshot_id,
                        "content_hash": snapshot.content_hash,
                        "size_bytes": snapshot.size_bytes,
                    }),
                    actor_ref,
                    now,
                ),
            )

    def _protocol_artifact_runtimes_for_run(
        self,
        conn,
        run_id: str,
    ) -> list[ProtocolArtifactRuntimeInstanceRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifact_runtime_instances
            WHERE protocol_run_id = %s
            ORDER BY updated_at DESC, runtime_instance_id ASC
            """,
            (run_id,),
        )
        return [self._protocol_artifact_runtime_from_row(row) for row in rows]

    def _protocol_artifact_runtime_events_for_run(
        self,
        conn,
        run_id: str,
        *,
        limit: int = 200,
    ) -> list[ProtocolArtifactRuntimeEventRecord]:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifact_runtime_events
            WHERE protocol_run_id = %s
            ORDER BY created_at DESC, runtime_event_id DESC
            LIMIT %s
            """,
            (run_id, max(1, min(int(limit or 200), 500))),
        )
        return [self._protocol_artifact_runtime_event_from_row(row) for row in rows]

    @staticmethod
    def _primary_artifact_key(document: ProtocolDefinitionDocumentRecord) -> str:
        metadata = document.metadata.as_dict()
        auto_protocol = metadata.get("auto_protocol") if isinstance(metadata, Mapping) else {}
        if isinstance(auto_protocol, Mapping):
            primary = str(auto_protocol.get("primary_artifact_key", "") or "").strip()
            if primary:
                return primary
            primary_record = auto_protocol.get("primary_artifact")
            if isinstance(primary_record, Mapping):
                primary = str(primary_record.get("artifact_key", "") or "").strip()
                if primary:
                    return primary
        if any(item.artifact_key == "produced_outcome" for item in document.artifacts):
            return "produced_outcome"
        return document.artifacts[-1].artifact_key if document.artifacts else ""

    @staticmethod
    def _artifact_runtime_manifest_state(
        detail: ProtocolRunDetailRecord,
        artifact: ProtocolArtifactRecord,
    ) -> tuple[bool, ProtocolArtifactRuntimeManifestRecord | None, str]:
        resolved = resolve_protocol_artifact_path(detail, artifact)
        if resolved is None:
            return False, None, ""
        root = resolved if resolved.is_dir() else resolved.parent
        manifest_path = root / "octopus-runtime.json"
        if not manifest_path.is_file():
            return False, None, ""
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            return True, ProtocolArtifactRuntimeManifestRecord.model_validate(raw), ""
        except Exception as exc:
            return True, None, str(exc)

    @staticmethod
    def _primary_artifact_expects_runtime(document: ProtocolDefinitionDocumentRecord) -> bool:
        metadata = document.metadata.as_dict()
        auto_protocol = metadata.get("auto_protocol") if isinstance(metadata, Mapping) else {}
        if not isinstance(auto_protocol, Mapping):
            return False
        primary = auto_protocol.get("primary_artifact")
        if isinstance(primary, Mapping):
            open_behavior = str(primary.get("open_behavior", "") or "").strip().lower()
            if open_behavior in {"runtime", "app", "service", "api", "playable"}:
                return True
            evidence = primary.get("evidence_requirements")
            if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
                if auto_protocol_runtime_expected_from_text(*evidence):
                    return True
        return auto_protocol_runtime_expected_from_text(
            auto_protocol.get("requirement", ""),
            auto_protocol.get("constraints", ""),
            auto_protocol.get("description", ""),
        )

    @staticmethod
    def _runtime_manifest_run_ready_blockers(manifest: ProtocolArtifactRuntimeManifestRecord | None) -> list[str]:
        return runtime_manifest_run_ready_blockers(manifest)

    @staticmethod
    def _runtime_fetch_counts_as_core_exercise(
        metadata: Mapping[str, object],
        manifest: ProtocolArtifactRuntimeManifestRecord | None,
    ) -> bool:
        return bool(RegistryPostgresStore._runtime_fetch_core_exercise_key(metadata, manifest))

    @staticmethod
    def _runtime_fetch_core_exercise_key(
        metadata: Mapping[str, object],
        manifest: ProtocolArtifactRuntimeManifestRecord | None,
    ) -> str:
        status_code = int(metadata.get("status_code", 0) or 0)
        if status_code <= 0 or status_code >= 500:
            return ""
        method = str(metadata.get("method", "GET") or "GET").strip().upper()
        path = str(metadata.get("path", "") or "").strip() or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        query = str(metadata.get("query_string", "") or "").strip()
        if query and not query.startswith("?"):
            query = f"?{query}"
        path_without_query = path.split("?", 1)[0].split("#", 1)[0] or "/"
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return f"{method} {path_without_query}{query}"
        manifest = manifest or ProtocolArtifactRuntimeManifestRecord()
        health_path = str(manifest.health_path or "/health").strip() or "/health"
        if not health_path.startswith("/"):
            health_path = f"/{health_path}"
        ui_path = str(manifest.ui_path or "/").strip() or "/"
        if not ui_path.startswith("/"):
            ui_path = f"/{ui_path}"
        if path_without_query == health_path:
            return ""
        if bool(metadata.get("is_api")):
            if path_without_query in {"/", "/docs", "/api-docs", "/openapi.json", health_path}:
                return ""
            return f"{method} {path_without_query}{query}"
        if path_without_query == ui_path or path_without_query == "/":
            return ""
        if re.search(r"\.(?:css|js|mjs|map|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|otf)$", path_without_query, re.I):
            return ""
        return f"{method} {path_without_query}{query}"

    @staticmethod
    def _runtime_client_interaction_key(metadata: Mapping[str, object]) -> str:
        event_type = str(metadata.get("event_type", "") or "").strip().lower()
        tag = str(metadata.get("tag", "") or "").strip().lower()
        text = re.sub(r"\s+", " ", str(metadata.get("text", "") or "").strip().lower())[:80]
        action = re.sub(r"\s+", " ", str(metadata.get("action", "") or "").strip().lower())[:80]
        page_path = str(metadata.get("page_path", "") or "").strip().lower()
        key = "|".join(part for part in [event_type, tag, text or action, page_path] if part)
        return key

    @staticmethod
    def _runtime_manifest_minimum_core_journeys(manifest: ProtocolArtifactRuntimeManifestRecord | None) -> int:
        if manifest is None:
            return 1
        metadata = manifest.metadata.as_dict() if manifest.metadata else {}
        raw = metadata.get("minimum_core_journeys") if isinstance(metadata, Mapping) else None
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            value = 0
        checks = metadata.get("outcome_readiness_checks") if isinstance(metadata, Mapping) else None
        if value <= 0 and isinstance(checks, Sequence) and not isinstance(checks, (str, bytes)):
            value = min(4, max(0, len([item for item in checks if str(item or "").strip()])))
        if value <= 0:
            value = 1 if str(manifest.runtime_kind or "").strip().lower() == "static" else 2
        return max(1, min(6, value))

    @staticmethod
    def _runtime_acceptance_text_has_visible_result_evidence(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        negative_patterns = [
            r"\b(no|not|nothing|never)\s+(visible|shown|displayed|rendered|returned|updated|changed|worked|working|result)",
            r"\b(did not|does not|cannot|could not|failed to|unable to)\s+(show|display|render|return|update)",
            r"\b(did not|does not|cannot|could not|failed to|unable to)\s+(exercise|run|work)\b.{0,100}\b(app|ui|button|control|action|flow|scenario|journey|workflow|result)\b",
            r"\b(button|control|action|flow)\s+(did not|does not|failed to|cannot|could not)\b",
        ]
        if any(re.search(pattern, normalized) for pattern in negative_patterns):
            return False
        action_terms = (
            "clicked",
            "selected",
            "submitted",
            "ran",
            "called",
            "posted",
            "played",
            "exercised",
            "tested",
            "opened",
            "used",
            "triggered",
            "completed",
        )
        result_terms = (
            "visible",
            "displayed",
            "shown",
            "rendered",
            "returned",
            "updated",
            "result",
            "response",
            "decision",
            "score",
            "chart",
            "dashboard",
            "screen",
            "output",
            "evidence",
        )
        return any(term in normalized for term in action_terms) and any(term in normalized for term in result_terms)

    @staticmethod
    def _runtime_acceptance_text_has_outcome_readiness_matrix(text: str, *, minimum_core_journeys: int) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        if not any(term in normalized for term in ("outcome-readiness", "outcome readiness", "readiness matrix", "journey matrix", "scenario matrix", "workflow matrix", "qa matrix")):
            return False
        negative_patterns = (
            r"\bplaceholder\b",
            r"\bskipped\b",
            r"\buntested\b",
            r"\bnot\s+(covered|working|implemented|visible|usable)\b",
            r"\bonly\s+the\s+first\b",
        )
        negative_scan = re.sub(r"\b(?:0|zero|no)\s+skipped\b", "clean skip count", normalized)
        if any(re.search(pattern, negative_scan) for pattern in negative_patterns):
            return False
        pass_count = len(re.findall(r"\b(pass(?:ed)?|verified|succeeded|works|working|ok)\b", normalized))
        return pass_count >= max(1, minimum_core_journeys)

    @staticmethod
    def _runtime_acceptance_text_has_customer_branding_evidence(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        if "octopus" not in normalized or "brand" not in normalized:
            return False
        branding_patterns = (
            r"\b(no|not|without|none|absent|avoids?|removed)\b.{0,100}\boctopus\b.{0,80}\b(brand|branding|title|copy|ui|api|customer-facing)\b",
            r"\boctopus\b.{0,100}\b(no|not|without|none|absent|only internal|internal only|manifest|release evidence|registry)\b",
            r"\bbranding check\b.{0,140}\boctopus\b",
        )
        return any(re.search(pattern, normalized) for pattern in branding_patterns)

    @staticmethod
    def _runtime_document_explicitly_allows_octopus_branding(document: ProtocolDefinitionDocumentRecord) -> bool:
        metadata = document.metadata.as_dict()
        auto_protocol = metadata.get("auto_protocol") if isinstance(metadata, Mapping) else {}
        parts = [
            metadata.get("display_name", ""),
            metadata.get("description", ""),
        ]
        if isinstance(auto_protocol, Mapping):
            parts.extend([
                auto_protocol.get("requirement", ""),
                auto_protocol.get("constraints", ""),
                auto_protocol.get("description", ""),
            ])
        normalized = re.sub(r"\s+", " ", " ".join(str(part or "") for part in parts).lower())
        return bool(re.search(r"\b(use|include|apply|keep|show|brand(?:ed)? as)\s+octopus\s+brand", normalized))

    def _runtime_acceptance_result_text(
        self,
        conn,
        *,
        stage_execution_row: Mapping[str, object],
        engine,
    ) -> str:
        parts = [
            str(getattr(engine, "transition_reason", "") or ""),
        ]
        routed_task_id = str(stage_execution_row.get("routed_task_id", "") or "").strip()
        if routed_task_id:
            task_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT result_json FROM {SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                (routed_task_id,),
            )
            result_json = task_row.get("result_json") if isinstance(task_row, Mapping) else {}
            if isinstance(result_json, Mapping):
                parts.extend([
                    str(result_json.get("summary", "") or ""),
                    str(result_json.get("full_text", "") or ""),
                ])
        parts.extend(self._runtime_acceptance_artifact_text(conn, stage_execution_row=stage_execution_row))
        return "\n".join(part for part in parts if part.strip())

    def _runtime_acceptance_artifact_text(
        self,
        conn,
        *,
        stage_execution_row: Mapping[str, object],
    ) -> list[str]:
        stage_execution_id = str(stage_execution_row.get("protocol_stage_execution_id", "") or "").strip()
        run_id = str(stage_execution_row.get("protocol_run_id", "") or "").strip()
        if not stage_execution_id or not run_id:
            return []
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifacts
            WHERE protocol_run_id = %s
              AND produced_by_stage_execution_id = %s
              AND exists = TRUE
              AND state = 'available'
              AND artifact_kind = 'workspace_file'
              AND size_bytes > 0
              AND size_bytes <= 131072
            ORDER BY observed_at DESC, created_at DESC
            LIMIT 8
            """,
            (run_id, stage_execution_id),
        )
        artifact_store_dir = load_registry_config().artifact_store_dir
        texts: list[str] = []
        for row in rows:
            artifact_key = str(row.get("artifact_key", "") or "").strip()
            path = self._runtime_acceptance_artifact_path(conn, row, artifact_store_dir=artifact_store_dir)
            if path is None or not path.is_file():
                continue
            if path.suffix.lower() not in {"", ".txt", ".md", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                texts.append(f"Artifact {artifact_key}:\n{text[:131072]}")
        return texts

    def _runtime_acceptance_artifact_path(
        self,
        conn,
        artifact_row: Mapping[str, object],
        *,
        artifact_store_dir: str,
    ) -> Path | None:
        artifact_id = str(artifact_row.get("protocol_artifact_id", "") or "").strip()
        if artifact_id:
            snapshot_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_artifact_snapshots
                WHERE protocol_artifact_id = %s
                  AND retention_state <> 'deleted'
                ORDER BY created_at DESC, artifact_snapshot_id DESC
                LIMIT 1
                """,
                (artifact_id,),
            )
            if snapshot_row is not None:
                path = artifact_snapshot_storage_path(
                    artifact_store_dir,
                    self._protocol_artifact_snapshot_from_row(snapshot_row),
                )
                if path is not None and path.exists():
                    return path
        location = str(artifact_row.get("location", "") or "").strip()
        return Path(location).expanduser().resolve() if location else None

    def _runtime_acceptance_evidence_gate(
        self,
        conn,
        *,
        run_row: Mapping[str, object],
        stage_execution_row: Mapping[str, object],
        engine,
    ):
        if str(engine.terminal_status or "") != "completed":
            return engine
        if str(engine.decision or "").strip().lower() != "accept":
            return engine
        run_id = str(run_row.get("protocol_run_id", "") or "").strip()
        document = self._protocol_document_for_run(conn, run_row)
        try:
            stage = document.stage(str(stage_execution_row.get("stage_key", "") or ""))
        except Exception:
            return engine
        if stage.stage_kind != "acceptance":
            return engine

        primary_key = self._primary_artifact_key(document)
        if not primary_key:
            return engine
        detail = self._protocol_run_detail_in_tx(
            conn,
            run_id,
            access=ProtocolAccessContextRecord(actor_ref=PROTOCOL_DEFAULT_OPERATOR_REF, roles=["operator"]),
        )
        if detail is None:
            return engine
        artifact = next((item for item in detail.artifacts if item.artifact_key == primary_key), None)
        if artifact is None:
            return engine
        runtime = next((item for item in detail.runtime_instances if item.artifact_key == primary_key), None)
        manifest_present, file_manifest, manifest_error = self._artifact_runtime_manifest_state(detail, artifact)
        runtime_expected = self._primary_artifact_expects_runtime(document)
        manifest_required = runtime_expected or bool(runtime and runtime.manifest) or manifest_present
        effective_manifest = file_manifest or (runtime.manifest if runtime and runtime.manifest else None)
        if not manifest_required:
            return engine
        if manifest_present and file_manifest is None:
            detail_text = (
                "Final acceptance for this runnable primary artifact requires a valid root octopus-runtime.json manifest before completion. "
                f"Registry could not parse the manifest for artifact '{primary_key}': {manifest_error}. "
                "The acceptance gate is returning the run to the primary outcome stage so the package uses the canonical Octopus runtime manifest schema."
            )
            metadata = engine.transition_metadata.as_dict()
            metadata.update({
                "runtime_evidence_required": True,
                "runtime_manifest_invalid": True,
                "primary_artifact_key": primary_key,
                "missing_runtime_evidence": ["valid root octopus-runtime.json manifest"],
                "runtime_manifest_error": manifest_error,
            })
            return self._runtime_acceptance_revise_or_block_decision(
                conn,
                document=document,
                stage=stage,
                stage_execution_row=stage_execution_row,
                engine=engine,
                detail_text=detail_text,
                failure_code="runtime_manifest_invalid",
                transition_error_code="RUNTIME_MANIFEST_INVALID",
                metadata=metadata,
            )
        if runtime_expected and not manifest_present and not bool(runtime and runtime.manifest):
            detail_text = (
                "Final acceptance for this runnable primary artifact requires a root octopus-runtime.json manifest before completion. "
                "The acceptance gate is returning the run to the primary outcome stage so the package includes runtime metadata, start/health paths, and smoke steps that Octopus can route through the Registry."
            )
            metadata = engine.transition_metadata.as_dict()
            metadata.update({
                "runtime_evidence_required": True,
                "runtime_manifest_required": True,
                "primary_artifact_key": primary_key,
                "missing_runtime_evidence": ["root octopus-runtime.json manifest"],
            })
            return self._runtime_acceptance_revise_or_block_decision(
                conn,
                document=document,
                stage=stage,
                stage_execution_row=stage_execution_row,
                engine=engine,
                detail_text=detail_text,
                failure_code="runtime_manifest_required",
                transition_error_code="RUNTIME_MANIFEST_REQUIRED",
                metadata=metadata,
            )

        run_ready_blockers = self._runtime_manifest_run_ready_blockers(effective_manifest)
        if run_ready_blockers:
            start_command = str(effective_manifest.start_command or "").strip() if effective_manifest else ""
            detail_text = (
                "Final acceptance for this runnable primary artifact requires a run-ready package before completion. "
                "The runtime manifest start_command must only launch an already prepared artifact; it must not install dependencies, build, package, test, or use developer-mode run commands. "
                f"Current start_command for artifact '{primary_key}' is {start_command!r}. "
                "The acceptance gate is returning the run to the primary outcome stage so it builds and smoke-tests the package first, then uses a cheap launch command such as a prebuilt binary or java -jar target/app.jar."
            )
            metadata = engine.transition_metadata.as_dict()
            metadata.update({
                "runtime_evidence_required": True,
                "runtime_manifest_not_run_ready": True,
                "primary_artifact_key": primary_key,
                "runtime_manifest_start_command": start_command,
                "runtime_manifest_blockers": run_ready_blockers,
                "missing_runtime_evidence": ["run-ready runtime start command"],
            })
            return self._runtime_acceptance_revise_or_block_decision(
                conn,
                document=document,
                stage=stage,
                stage_execution_row=stage_execution_row,
                engine=engine,
                detail_text=detail_text,
                failure_code="runtime_manifest_not_run_ready",
                transition_error_code="RUNTIME_MANIFEST_NOT_RUN_READY",
                metadata=metadata,
            )

        events = [item for item in detail.runtime_events if item.artifact_key == primary_key]
        has_started = any(str(item.event_kind or "") == "started" for item in events)
        has_healthy = any(
            str(item.event_kind or "") == "health_checked"
            and bool(item.metadata_json.as_dict().get("ok"))
            for item in events
        )
        client_interaction_keys = {
            self._runtime_client_interaction_key(item.metadata_json.as_dict())
            for item in events
            if str(item.event_kind or "") == "client_interaction"
        }
        client_interaction_keys.discard("")
        core_fetch_keys = {
            self._runtime_fetch_core_exercise_key(item.metadata_json.as_dict(), effective_manifest)
            for item in events
            if str(item.event_kind or "") == "fetch"
        }
        core_fetch_keys.discard("")
        has_client_interaction = bool(client_interaction_keys)
        has_exercised = bool(core_fetch_keys)
        minimum_core_journeys = self._runtime_manifest_minimum_core_journeys(effective_manifest)
        distinct_core_journeys = len(core_fetch_keys | client_interaction_keys)
        evidence_text = self._runtime_acceptance_result_text(
            conn,
            stage_execution_row=stage_execution_row,
            engine=engine,
        )
        has_visible_result_evidence = self._runtime_acceptance_text_has_visible_result_evidence(evidence_text)
        has_outcome_readiness_matrix = self._runtime_acceptance_text_has_outcome_readiness_matrix(
            evidence_text,
            minimum_core_journeys=minimum_core_journeys,
        )
        branding_check_required = not self._runtime_document_explicitly_allows_octopus_branding(document)
        has_customer_branding_evidence = (
            not branding_check_required
            or self._runtime_acceptance_text_has_customer_branding_evidence(evidence_text)
        )
        missing = []
        if not has_started:
            missing.append("runtime start")
        if not has_healthy:
            missing.append("healthy runtime check")
        if not has_client_interaction:
            missing.append("user interaction through Registry routing")
        if not has_exercised:
            missing.append("routed UI/API fetch for a core action")
        if distinct_core_journeys < minimum_core_journeys and not has_outcome_readiness_matrix:
            journey_label = "journey" if minimum_core_journeys == 1 else "journeys"
            missing.append(f"evidence for at least {minimum_core_journeys} representative core {journey_label}")
        if not has_visible_result_evidence:
            missing.append("written evidence of the visible result from an exercised core action")
        if not has_outcome_readiness_matrix:
            missing.append("pass/fail outcome-readiness matrix")
        if not has_customer_branding_evidence:
            missing.append("customer-facing branding check confirming Octopus is not used as the artifact brand")
        if not missing:
            return engine

        detail_text = (
            "Final acceptance for this runnable primary artifact requires runtime and outcome-readiness evidence before completion: "
            + ", ".join(missing)
            + ". Start or open the artifact runtime, run Health, exercise representative UI/API journeys through the Registry URL, record visible outcomes, verify customer-facing branding, then accept again."
        )
        metadata = engine.transition_metadata.as_dict()
        metadata.update({
            "runtime_evidence_required": True,
            "primary_artifact_key": primary_key,
            "missing_runtime_evidence": missing,
            "runtime_core_exercise_count": distinct_core_journeys,
            "runtime_minimum_core_journeys": minimum_core_journeys,
            "runtime_core_fetch_keys": sorted(core_fetch_keys),
            "runtime_client_interaction_keys": sorted(client_interaction_keys),
        })
        return engine.model_copy(update={
            "run_status": "blocked",
            "stage_status": "blocked",
            "failure_code": "runtime_evidence_required",
            "failure_detail": detail_text,
            "transition_kind": "blocked",
            "transition_reason": detail_text,
            "transition_error_code": "RUNTIME_EVIDENCE_REQUIRED",
            "run_blocked_code": "runtime_evidence_required",
            "run_blocked_detail": detail_text,
            "terminal_status": None,
            "create_next_execution": False,
            "next_stage_key": "",
            "transition_metadata": RegistryJsonRecord.model_validate(metadata),
        })

    def _runtime_acceptance_revise_or_block_decision(
        self,
        conn,
        *,
        document: ProtocolDefinitionDocumentRecord,
        stage,
        stage_execution_row: Mapping[str, object],
        engine,
        detail_text: str,
        failure_code: str,
        transition_error_code: str,
        metadata: Mapping[str, object],
    ):
        update_metadata = dict(metadata)
        target = ""
        if "revise" in set(stage.allowed_decisions()):
            target = stage_target_for_decision(stage, "revise")
            try:
                document.stage(target)
            except Exception:
                target = ""
        if target:
            run_id = str(stage_execution_row.get("protocol_run_id", "") or "")
            edge_key = protocol_review_edge_key(stage.stage_key, target)
            revise_count = (
                protocol_review_edge_counts(self._protocol_run_transitions_history(conn, run_id)).get(edge_key, 0)
                + 1
            )
            update_metadata.update({
                "review_edge_key": edge_key,
                "current_review_rounds": revise_count,
                "max_review_rounds": document.policies.max_review_rounds,
                "runtime_gate_auto_revise": True,
            })
            if revise_count <= document.policies.max_review_rounds:
                input_snapshot = {
                    "previous_stage_key": stage.stage_key,
                    "previous_stage_execution_id": str(stage_execution_row.get("protocol_stage_execution_id", "") or ""),
                    "decision": "revise",
                    "decision_summary": detail_text,
                    "runtime_gate_code": failure_code,
                    "primary_artifact_key": str(update_metadata.get("primary_artifact_key", "") or ""),
                }
                start_command = str(update_metadata.get("runtime_manifest_start_command", "") or "")
                if start_command:
                    input_snapshot["runtime_manifest_start_command"] = start_command
                blockers = update_metadata.get("runtime_manifest_blockers", [])
                if blockers:
                    input_snapshot["runtime_manifest_blockers"] = blockers
                return engine.model_copy(update={
                    "run_status": "running",
                    "stage_status": "completed",
                    "decision": "revise",
                    "summary": detail_text,
                    "failure_code": "",
                    "failure_detail": "",
                    "transition_kind": "advance",
                    "transition_reason": detail_text,
                    "transition_error_code": transition_error_code,
                    "next_stage_key": target,
                    "create_next_execution": True,
                    "terminal_status": None,
                    "run_blocked_code": "",
                    "run_blocked_detail": "",
                    "input_snapshot": RegistryJsonRecord.model_validate(input_snapshot),
                    "transition_metadata": RegistryJsonRecord.model_validate(update_metadata),
                })
            detail_text = (
                f"Review edge {edge_key or stage.stage_key} exceeded max review rounds "
                f"({revise_count} > {document.policies.max_review_rounds}) while enforcing runtime readiness. "
                + detail_text
            )
            failure_code = "max_review_rounds_exceeded"
            transition_error_code = "MAX_REVIEW_ROUNDS_EXCEEDED"

        return engine.model_copy(update={
            "run_status": "blocked",
            "stage_status": "blocked",
            "failure_code": failure_code,
            "failure_detail": detail_text,
            "transition_kind": "blocked",
            "transition_reason": detail_text,
            "transition_error_code": transition_error_code,
            "run_blocked_code": failure_code,
            "run_blocked_detail": detail_text,
            "terminal_status": None,
            "create_next_execution": False,
            "next_stage_key": "",
            "transition_metadata": RegistryJsonRecord.model_validate(update_metadata),
        })

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
        working_dir = ""
        routed_task_id = str(stage_execution_row.get("routed_task_id", "") or "").strip()
        if routed_task_id:
            task_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT result_json FROM {SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                (routed_task_id,),
            )
            result_json = task_row.get("result_json") if isinstance(task_row, Mapping) else {}
            if isinstance(result_json, dict):
                working_dir = str(result_json.get("working_dir", "") or "").strip()
        for observation in observations:
            previous = current_artifacts.get(observation.artifact_key)
            location = str(observation.path or "").strip()
            if working_dir and location:
                candidate = Path(location)
                if not candidate.is_absolute():
                    location = str((Path(working_dir) / candidate).resolve())
            artifact_id = uuid.uuid4().hex
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
                        artifact_id,
                        run_row["protocol_run_id"],
                        observation.artifact_key,
                        observation.artifact_kind,
                        location,
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
            if observation.exists and location:
                source_path = Path(location)
                if source_path.exists():
                    try:
                        snapshot = create_artifact_snapshot(
                            artifact_store_dir=load_registry_config().artifact_store_dir,
                            source_path=source_path,
                            protocol_artifact_id=artifact_id,
                            protocol_run_id=str(run_row["protocol_run_id"] or ""),
                            artifact_key=observation.artifact_key,
                            created_by="protocol_engine",
                            retention_until=str(run_row.get("retention_until", "") or ""),
                        )
                        self._insert_protocol_artifact_snapshot_in_tx(
                            conn,
                            snapshot,
                            actor_ref="protocol_engine",
                            now=now,
                        )
                    except Exception as exc:
                        log.warning(
                            "protocol artifact snapshot failed run=%s artifact=%s path=%s error=%s",
                            run_row["protocol_run_id"],
                            observation.artifact_key,
                            location,
                            exc,
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
        engine = self._runtime_acceptance_evidence_gate(
            conn,
            run_row=run_row,
            stage_execution_row=stage_execution_row,
            engine=engine,
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

    def _sweep_protocol_artifact_runtimes_in_tx(self, conn, *, now: str) -> ProtocolMaintenanceResultRecord:
        rows = POSTGRES_STORE_DIALECT.fetchall(
            conn,
            f"""
            SELECT *
            FROM {SCHEMA}.protocol_artifact_runtime_instances
            WHERE status IN ('starting', 'running')
              AND coalesce(expires_at, '') <> ''
              AND expires_at::timestamptz <= %s::timestamptz
            ORDER BY expires_at ASC, runtime_instance_id ASC
            """,
            (now,),
        )
        affected_run_ids: list[str] = []
        for row in rows:
            runtime = self._protocol_artifact_runtime_from_row(row)
            summary = "Runtime exceeded its configured maximum duration and was stopped by maintenance."
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_artifact_runtime_instances
                    SET status = 'stopped',
                        failure_code = 'runtime_expired',
                        failure_detail = %s,
                        updated_at = %s,
                        stopped_at = %s
                    WHERE runtime_instance_id = %s
                    """,
                    (summary, now, now, runtime.runtime_instance_id),
                )
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_artifact_runtime_events (
                        runtime_event_id, runtime_instance_id, protocol_run_id, artifact_key,
                        event_kind, actor_ref, summary, metadata_json, created_at
                    ) VALUES (%s, %s, %s, %s, 'stopped', 'system:protocol-maintenance', %s, %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        runtime.runtime_instance_id,
                        runtime.protocol_run_id,
                        runtime.artifact_key,
                        summary,
                        jsonb({"reason": "runtime_expired"}),
                        now,
                    ),
                )
            affected_run_ids.append(runtime.protocol_run_id)
        return ProtocolMaintenanceResultRecord(
            swept_count=len(affected_run_ids),
            affected_run_ids=sorted(set(item for item in affected_run_ids if item)),
        )

    def run_protocol_maintenance(self, *, now: str = "") -> ProtocolMaintenanceResultRecord:
        maintenance_now = str(now or utcnow_iso())
        with self._connect() as conn, write_tx(conn):
            timeout_result = self._sweep_protocol_timeouts_in_tx(conn, now=maintenance_now)
            runtime_result = self._sweep_protocol_artifact_runtimes_in_tx(conn, now=maintenance_now)
            swept_count = timeout_result.swept_count + runtime_result.swept_count
            affected_run_ids = sorted(set([*timeout_result.affected_run_ids, *runtime_result.affected_run_ids]))
            if swept_count:
                log.info(
                    "protocol maintenance swept_timeouts=%s swept_artifact_runtimes=%s at=%s",
                    timeout_result.swept_count,
                    runtime_result.swept_count,
                    maintenance_now,
                )
            return ProtocolMaintenanceResultRecord(
                swept_count=swept_count,
                affected_run_ids=affected_run_ids,
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
        include_drafts: bool | None = None,
    ) -> list[ProtocolDefinitionRecord]:
        if include_drafts is None:
            include_drafts = any(self._access_has_role(access, role) for role in ("author", "publisher", "admin"))
        clauses: list[str] = []
        params: list[object] = []
        clauses.append("visibility <> 'registry_template'")
        if lifecycle_state:
            params.append(lifecycle_state)
            clauses.append("lifecycle_state = %s")
        elif include_drafts is False:
            clauses.append("lifecycle_state = 'published'")
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
        if not self._access_has_role(access, "admin"):
            params.append(self._access_org_id(access))
            clauses.append("(owner_org_id = %s OR owner_org_id = '')")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_definitions
                {where_sql}
                ORDER BY updated_at DESC, display_name ASC, slug ASC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, max(1, int(limit or 50)), max(0, int(cursor or 0))]),
            )
        visible = [
            self._protocol_record_from_row(row)
            for row in rows
            if self._protocol_visible_to_access(row, access=access, include_drafts=include_drafts)
        ]
        return visible

    def get_protocol_template(self, slug: str, *, access: ProtocolAccessContextRecord) -> ProtocolDefinitionDocumentRecord:
        if not self._config.protocol_registry_templates_enabled:
            raise KeyError(slug)
        normalized_slug = str(slug or "").strip()
        with self._connect() as conn:
            row = self._protocol_row_for_slug(conn, normalized_slug)
            if row is not None and str(row.get("visibility", "") or "") == "registry_template":
                if not self._protocol_visible_to_access(row, access=access, include_drafts=False):
                    raise PermissionError(normalized_slug)
                return self._protocol_template_document_from_row(conn, row)
        raise KeyError(normalized_slug)

    def list_protocol_templates(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolTemplateSummaryRecord]:
        if not self._config.protocol_registry_templates_enabled:
            return []
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return []
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_definitions
                WHERE visibility = 'registry_template'
                ORDER BY updated_at DESC, display_name ASC, slug ASC
                """,
            )
            authored_summaries = [
                self._protocol_template_summary_from_row(conn, row)
                for row in rows
                if self._protocol_visible_to_access(row, access=access, include_drafts=False)
            ]
        return authored_summaries

    def get_protocol_authoring_options(
        self,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAuthoringOptionsRecord:
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            raise PermissionError("Protocol authoring requires author access.")
        return ProtocolAuthoringOptionsRecord(
            sections=list(PROTOCOL_AUTHORING_SECTION_OPTIONS),
            stage_kind_options=list(PROTOCOL_STAGE_KIND_OPTIONS),
            artifact_kind_options=list(PROTOCOL_ARTIFACT_KIND_OPTIONS),
            selector_kind_options=list(PROTOCOL_SELECTOR_KIND_OPTIONS),
            default_surface="standard",
            operator_surface_available=self._access_can_edit_protocol_internals(access),
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

    @staticmethod
    def _auto_design_session_from_row(row: Mapping[str, object]) -> ProtocolAutoDesignSessionRecord:
        session = record(
            ProtocolAutoDesignSessionRecord,
            {
                "session_id": row.get("session_id", ""),
                "status": row.get("status", "draft"),
                "mode": row.get("mode", "create"),
                "surface": row.get("surface", "api"),
                "actor_ref": row.get("actor_ref", ""),
                "chat_ref": row.get("chat_ref", ""),
                "source_protocol_id": row.get("source_protocol_id", ""),
                "source_version_id": row.get("source_version_id", ""),
                "source_draft_revision": int(row.get("source_draft_revision", 0) or 0),
                "target_protocol_id": row.get("target_protocol_id", ""),
                "target_draft_revision": int(row.get("target_draft_revision", 0) or 0),
                "requirement_text": row.get("requirement_text", ""),
                "constraints_text": row.get("constraints_text", ""),
                "model_response": row.get("planner_response_json") or None,
                "analysis": row.get("analysis_json") or {},
                "plan": row.get("plan_json") or {},
                "draft_definition_json": row.get("draft_definition_json") or {},
                "run_profile": row.get("run_profile_json") or {},
                "validation": row.get("validation_json") or {},
                "warnings": row.get("warnings_json") or [],
                "unresolved_decisions": row.get("unresolved_decisions_json") or [],
                "change_summary": row.get("change_summary_json") or [],
                "applied_protocol": row.get("applied_protocol_json") or None,
                "run_result": row.get("run_result_json") or None,
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
            },
        )
        return session.model_copy(update={
            "event_summary": auto_protocol_event_summary(
                session,
                event_kind="loaded",
                created_at=str(row.get("updated_at", "") or ""),
            ),
        })

    @classmethod
    def _auto_design_payload(cls, session: ProtocolAutoDesignSessionRecord) -> dict[str, object]:
        return {
            "session_id": session.session_id,
            "status": session.status,
            "mode": session.mode,
            "surface": session.surface,
            "actor_ref": session.actor_ref,
            "chat_ref": session.chat_ref,
            "source_protocol_id": session.source_protocol_id,
            "source_version_id": session.source_version_id,
            "source_draft_revision": int(session.source_draft_revision or 0),
            "target_protocol_id": session.target_protocol_id,
            "target_draft_revision": int(session.target_draft_revision or 0),
            "requirement_text": session.requirement_text,
            "constraints_text": session.constraints_text,
            "planner_response_json": session.model_response.model_dump(mode="json") if session.model_response is not None else {},
            "analysis_json": session.analysis.model_dump(mode="json"),
            "plan_json": session.plan.model_dump(mode="json"),
            "draft_definition_json": session.draft_definition_json.as_dict(),
            "run_profile_json": session.run_profile.model_dump(mode="json"),
            "validation_json": session.validation.model_dump(mode="json"),
            "warnings_json": [item.model_dump(mode="json") for item in session.warnings],
            "unresolved_decisions_json": [item.model_dump(mode="json") for item in session.unresolved_decisions],
            "change_summary_json": list(session.change_summary or []),
            "applied_protocol_json": session.applied_protocol.model_dump(mode="json") if session.applied_protocol is not None else {},
            "run_result_json": session.run_result.model_dump(mode="json") if session.run_result is not None else {},
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    def _append_auto_design_event_in_tx(
        self,
        conn,
        *,
        session_id: str,
        event_kind: str,
        actor_ref: str,
        payload: Mapping[str, object],
        now: str,
    ) -> None:
        sequence_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM {SCHEMA}.protocol_auto_session_events
            WHERE session_id = %s
            """,
            (session_id,),
        ) or {"next_sequence": 1}
        with cur(conn) as db_cur:
            db_cur.execute(
                f"""
                INSERT INTO {SCHEMA}.protocol_auto_session_events (
                    event_id, session_id, sequence, event_kind, actor_ref, payload_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4().hex,
                    session_id,
                    int(sequence_row.get("next_sequence", 1) or 1),
                    event_kind,
                    actor_ref,
                    jsonb(dict(payload)),
                    now,
                ),
            )

    def update_protocol_auto_design_session(
        self,
        session: ProtocolAutoDesignSessionRecord,
        *,
        access: ProtocolAccessContextRecord,
        event_kind: str = "updated",
    ) -> ProtocolAutoDesignSessionRecord:
        if not any(self._access_has_role(access, role) for role in ("agent", "author", "publisher", "admin")):
            raise PermissionError("Auto Protocol requires agent or author access.")
        now = utcnow_iso()
        session_for_save = session.model_copy(update={"updated_at": now})
        payload = self._auto_design_payload(session_for_save)
        if not str(payload.get("created_at", "") or "").strip():
            payload["created_at"] = now
            session_for_save = session_for_save.model_copy(update={"created_at": now})
        with self._connect() as conn, write_tx(conn):
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_auto_sessions (
                        session_id, status, mode, surface, actor_ref, chat_ref,
                        source_protocol_id, source_version_id, source_draft_revision,
                        target_protocol_id, target_draft_revision, requirement_text, constraints_text,
                        planner_response_json, analysis_json, plan_json, draft_definition_json, run_profile_json, validation_json,
                        warnings_json, unresolved_decisions_json, change_summary_json,
                        applied_protocol_json, run_result_json, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (session_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        mode = EXCLUDED.mode,
                        surface = EXCLUDED.surface,
                        actor_ref = EXCLUDED.actor_ref,
                        chat_ref = EXCLUDED.chat_ref,
                        source_protocol_id = EXCLUDED.source_protocol_id,
                        source_version_id = EXCLUDED.source_version_id,
                        source_draft_revision = EXCLUDED.source_draft_revision,
                        target_protocol_id = EXCLUDED.target_protocol_id,
                        target_draft_revision = EXCLUDED.target_draft_revision,
                        requirement_text = EXCLUDED.requirement_text,
                        constraints_text = EXCLUDED.constraints_text,
                        planner_response_json = EXCLUDED.planner_response_json,
                        analysis_json = EXCLUDED.analysis_json,
                        plan_json = EXCLUDED.plan_json,
                        draft_definition_json = EXCLUDED.draft_definition_json,
                        run_profile_json = EXCLUDED.run_profile_json,
                        validation_json = EXCLUDED.validation_json,
                        warnings_json = EXCLUDED.warnings_json,
                        unresolved_decisions_json = EXCLUDED.unresolved_decisions_json,
                        change_summary_json = EXCLUDED.change_summary_json,
                        applied_protocol_json = EXCLUDED.applied_protocol_json,
                        run_result_json = EXCLUDED.run_result_json,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    (
                        payload["session_id"],
                        payload["status"],
                        payload["mode"],
                        payload["surface"],
                        payload["actor_ref"],
                        payload["chat_ref"],
                        payload["source_protocol_id"],
                        payload["source_version_id"],
                        payload["source_draft_revision"],
                        payload["target_protocol_id"],
                        payload["target_draft_revision"],
                        payload["requirement_text"],
                        payload["constraints_text"],
                        jsonb(payload["planner_response_json"]),
                        jsonb(payload["analysis_json"]),
                        jsonb(payload["plan_json"]),
                        jsonb(payload["draft_definition_json"]),
                        jsonb(payload["run_profile_json"]),
                        jsonb(payload["validation_json"]),
                        jsonb(payload["warnings_json"]),
                        jsonb(payload["unresolved_decisions_json"]),
                        jsonb(payload["change_summary_json"]),
                        jsonb(payload["applied_protocol_json"]),
                        jsonb(payload["run_result_json"]),
                        payload["created_at"],
                        payload["updated_at"],
                    ),
                )
                row = db_cur.fetchone()
            self._append_auto_design_event_in_tx(
                conn,
                session_id=str(payload["session_id"]),
                event_kind=str(event_kind or "updated"),
                actor_ref=self._access_actor_ref(access),
                payload=auto_protocol_event_summary(
                    session_for_save,
                    event_kind=str(event_kind or "updated"),
                    created_at=now,
                ).model_dump(mode="json"),
                now=now,
            )
        if row is None:
            raise RuntimeError("Failed to save Auto Protocol session")
        return self._auto_design_session_from_row(row)

    def get_protocol_auto_design_session(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        if not any(self._access_has_role(access, role) for role in ("agent", "author", "publisher", "admin")):
            raise PermissionError("Auto Protocol requires agent or author access.")
        with self._connect() as conn:
            row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_auto_sessions WHERE session_id = %s",
                (str(session_id or "").strip(),),
            )
        if row is None:
            raise KeyError(session_id)
        return self._auto_design_session_from_row(row)

    def list_protocol_auto_design_session_events(
        self,
        session_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> list[ProtocolAutoDesignEventSummaryRecord]:
        if not any(self._access_has_role(access, role) for role in ("agent", "author", "publisher", "admin")):
            raise PermissionError("Auto Protocol requires agent or author access.")
        session_id = str(session_id or "").strip()
        if not session_id:
            return []
        with self._connect() as conn:
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT event_kind, actor_ref, payload_json, created_at
                FROM {SCHEMA}.protocol_auto_session_events
                WHERE session_id = %s
                ORDER BY sequence ASC
                """,
                (session_id,),
            )
        events: list[ProtocolAutoDesignEventSummaryRecord] = []
        for row in rows:
            payload = row.get("payload_json") if isinstance(row, Mapping) else {}
            payload_map = dict(payload) if isinstance(payload, Mapping) else {}
            payload_map.setdefault("event_kind", row.get("event_kind", ""))
            payload_map.setdefault("actor_ref", row.get("actor_ref", ""))
            payload_map.setdefault("created_at", row.get("created_at", ""))
            events.append(record(ProtocolAutoDesignEventSummaryRecord, payload_map))
        return events

    def create_protocol_auto_design_session(
        self,
        payload: ProtocolAutoDesignRequestRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolAutoDesignSessionRecord:
        if not any(self._access_has_role(access, role) for role in ("agent", "author", "publisher", "admin")):
            raise PermissionError("Auto Protocol requires agent or author access.")
        session_id = uuid.uuid4().hex
        now = utcnow_iso()
        request = payload.model_copy(update={
            "actor_ref": payload.actor_ref or self._access_actor_ref(access),
        })
        if request.mode == "revise":
            session = revise_auto_protocol_session(request, session_id=session_id, created_at=now, updated_at=now)
        else:
            session = generate_auto_protocol_session(request, session_id=session_id, created_at=now, updated_at=now)
        return self.update_protocol_auto_design_session(session, access=access, event_kind="created")

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
        if not any(self._access_has_role(access, role) for role in ("author", "publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol draft writes require author access.")
        try:
            normalized_surface = self._normalize_authoring_surface(authoring_surface, access=access)
        except PermissionError as exc:
            return ProtocolMutationRecord(ok=False, status="forbidden", message=str(exc))
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
            if normalized_surface == "standard":
                restriction = self._validate_standard_surface_document(
                    raw_definition,
                    existing_definition=(existing_row.get("draft_definition_json") or {}) if existing_row is not None else None,
                )
                if restriction:
                    return ProtocolMutationRecord(ok=False, status="forbidden", message=restriction)
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

    def publish_protocol_template(
        self,
        protocol_id: str,
        *,
        access: ProtocolAccessContextRecord,
        slug: str = "",
        display_name: str = "",
        description: str = "",
    ) -> ProtocolMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("publisher", "admin")):
            return ProtocolMutationRecord(ok=False, status="forbidden", message="Protocol template publish requires publisher access.")
        loaded = self.get_protocol(protocol_id, access=access)
        if not loaded.ok or loaded.protocol is None:
            return loaded
        if str(loaded.protocol.visibility or "") == "registry_template":
            return ProtocolMutationRecord(ok=False, status="invalid_action", message="Protocol templates are already reusable.")
        current_version_id = str(loaded.protocol.current_version_id or "").strip()
        if str(loaded.protocol.lifecycle_state or "") != "published" or not current_version_id:
            return ProtocolMutationRecord(
                ok=False,
                status="invalid_action",
                message="Publish the protocol before making a reusable template.",
                protocol=loaded.protocol,
                draft_definition_json=loaded.draft_definition_json,
                draft_document=loaded.draft_document,
                version=loaded.version,
                validation=loaded.validation,
            )

        now = utcnow_iso()
        actor_ref = self._access_actor_ref(access)
        template_row: dict[str, object] | None = None
        template_version: ProtocolDefinitionVersionRecord | None = None
        strict_document: ProtocolDefinitionDocumentRecord | None = None
        strict_validation = None

        with self._connect() as conn, write_tx(conn):
            source_version_row = self._protocol_version_row(conn, current_version_id)
            if source_version_row is None:
                return ProtocolMutationRecord(
                    ok=False,
                    status="not_found",
                    message="Published protocol version not found.",
                    protocol=loaded.protocol,
                    draft_definition_json=loaded.draft_definition_json,
                    draft_document=loaded.draft_document,
                    version=loaded.version,
                    validation=loaded.validation,
                )
            source_document = dict(source_version_row.get("definition_json") or {})
            source_metadata = dict(source_document.get("metadata") or {})
            source_slug = str(source_metadata.get("slug", "") or loaded.protocol.slug or "protocol").strip()
            source_name = str(source_metadata.get("display_name", "") or loaded.protocol.display_name or source_slug).strip()
            source_description = str(source_metadata.get("description", "") or loaded.protocol.description or "").strip()
            template_slug = self._unique_protocol_slug(conn, str(slug or f"{source_slug}-template").strip())
            template_name = str(display_name or f"{source_name} Template").strip()
            template_description = str(description or source_description or "").strip()
            template_document = self._with_protocol_metadata(
                source_document,
                slug=template_slug,
                display_name=template_name,
                description=template_description,
            )
            strict_validation = validate_protocol_document(template_document, mode="strict")
            if not strict_validation.ok or strict_validation.normalized_document is None:
                return ProtocolMutationRecord(
                    ok=False,
                    status="invalid",
                    message="Published protocol version cannot be converted into a valid template.",
                    protocol=loaded.protocol,
                    draft_definition_json=RegistryJsonRecord.model_validate(template_document),
                    draft_document=None,
                    version=loaded.version,
                    validation=strict_validation,
                )
            strict_document = strict_validation.normalized_document
            content_hash = protocol_definition_content_hash(strict_document)
            template_protocol_id = uuid.uuid4().hex
            template_version_id = uuid.uuid4().hex
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_definitions (
                        protocol_id, slug, display_name, description, lifecycle_state, current_version_id,
                        owner_org_id, visibility, created_by, updated_by, draft_revision,
                        draft_definition_json, draft_content_hash, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'published', %s, %s, 'registry_template', %s, %s, 1, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        template_protocol_id,
                        template_slug,
                        template_name,
                        template_description,
                        template_version_id,
                        self._access_org_id(access),
                        actor_ref,
                        actor_ref,
                        jsonb(strict_document.model_dump(mode="json")),
                        content_hash,
                        now,
                        now,
                    ),
                )
                template_row = db_cur.fetchone()
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_definition_versions (
                        protocol_definition_version_id, protocol_id, version, definition_json,
                        content_hash, validation_status, published_at, published_by, created_at
                    ) VALUES (%s, %s, 1, %s, %s, 'valid', %s, %s, %s)
                    """,
                    (
                        template_version_id,
                        template_protocol_id,
                        jsonb(strict_document.model_dump(mode="json")),
                        content_hash,
                        now,
                        actor_ref,
                        now,
                    ),
                )
                template_version = record(
                    ProtocolDefinitionVersionRecord,
                    {
                        "protocol_definition_version_id": template_version_id,
                        "protocol_id": template_protocol_id,
                        "version": 1,
                        "definition_json": strict_document.model_dump(mode="json"),
                        "content_hash": content_hash,
                        "validation_status": "valid",
                        "published_at": now,
                        "published_by": actor_ref,
                        "created_at": now,
                    },
                )

        if template_row is None or strict_document is None:
            raise RuntimeError("Failed to publish protocol template")
        return ProtocolMutationRecord(
            ok=True,
            status="template_published",
            message="Protocol template published.",
            protocol=self._protocol_record_from_row(template_row),
            draft_definition_json=RegistryJsonRecord.model_validate(strict_document.model_dump(mode="json")),
            draft_document=strict_document,
            version=template_version,
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
        root_conversation_id: str = "",
        origin_channel: str = "",
        include_generated: bool = True,
    ) -> list[ProtocolRunRecord]:
        page_limit = max(1, int(limit or 25))
        page_cursor = max(0, int(cursor or 0))
        params: list[object] = []
        clauses: list[str] = []
        if not self._access_has_role(access, "admin"):
            params.append(self._access_org_id(access))
            clauses.append("pr.run_org_id = %s")
        if status:
            params.append(status)
            clauses.append("pr.status = %s")
        else:
            clauses.append("pr.status NOT IN ('archived', 'deleted')")
        if protocol_id:
            params.append(protocol_id)
            clauses.append("pr.protocol_id = %s")
        if entry_agent_id:
            params.append(entry_agent_id)
            clauses.append("pr.entry_agent_id = %s")
        if root_conversation_id:
            params.append(root_conversation_id)
            clauses.append("pr.root_conversation_id = %s")
        if origin_channel:
            params.append(origin_channel)
            clauses.append("pr.origin_channel = %s")
        if not include_generated:
            clauses.append(
                """
                (
                    pr.hidden_from_default_views = FALSE
                    OR (
                        NULLIF(BTRIM(COALESCE(pr.problem_statement, '')), '') IS NOT NULL
                        AND pr.origin_channel IN ('registry', 'telegram')
                    )
                )
                """
            )
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
                LIMIT %s OFFSET %s
                """,
                tuple([*params, page_limit + 1, page_cursor]),
            )
            visible: list[ProtocolRunRecord] = []
            for row in rows:
                if self._assert_protocol_run_visible(row, access=access) is None:
                    continue
                visible.append(self._protocol_run_from_row(self._decorate_protocol_run_row_with_review_state(conn, row)))
        return visible

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
        known_issue_kinds = {"blocked_run", "invalid_contract", "stuck_lease", "expired_timeout"}
        if normalized_kind and normalized_kind not in known_issue_kinds:
            return []
        now = utcnow_iso()
        page_limit = max(1, int(limit or 25))
        page_cursor = max(0, int(cursor or 0))
        clauses: list[str] = []
        params: list[object] = []
        if not self._access_has_role(access, "admin"):
            params.append(self._access_org_id(access))
            clauses.append("pr.run_org_id = %s")
        if normalized_run_id:
            params.append(normalized_run_id)
            clauses.append("pr.protocol_run_id = %s")
        if normalized_protocol_id:
            params.append(normalized_protocol_id)
            clauses.append("pr.protocol_id = %s")
        if normalized_kind == "blocked_run":
            clauses.append("pr.status = 'blocked'")
        elif normalized_kind == "invalid_contract":
            clauses.append("(pr.blocked_code = 'protocol_contract_invalid' OR pse.failure_code = 'protocol_contract_invalid')")
        elif normalized_kind == "stuck_lease":
            params.append(now)
            clauses.append("(pse.status = 'running' AND pse.lease_expires_at <> '' AND pse.lease_expires_at <= %s)")
        elif normalized_kind == "expired_timeout":
            params.append(now)
            clauses.append("(pse.status = 'running' AND pse.timeout_at <> '' AND pse.timeout_at <= %s)")
        else:
            params.extend([now, now])
            clauses.append(
                """(
                    pr.status = 'blocked'
                    OR pr.blocked_code = 'protocol_contract_invalid'
                    OR pse.failure_code = 'protocol_contract_invalid'
                    OR (pse.status = 'running' AND pse.lease_expires_at <> '' AND pse.lease_expires_at <= %s)
                    OR (pse.status = 'running' AND pse.timeout_at <> '' AND pse.timeout_at <= %s)
                )"""
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        candidate_limit = page_cursor + page_limit + 1
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
                {where}
                ORDER BY pr.updated_at DESC, pr.protocol_run_id DESC
                LIMIT %s
                """,
                tuple([*params, candidate_limit]),
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
                    issues.append(issue)
        return issues[page_cursor : page_cursor + page_limit + 1]

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
            source_kind = "rehearsal" if request.is_rehearsal else "protocol_run"
            hidden_from_default_views = bool(request.is_rehearsal)
            root_conversation_id = str(request.root_conversation_id or "").strip()
            if not root_conversation_id:
                created = shared_create_conversation(
                    conn,
                    dialect=POSTGRES_STORE_DIALECT,
                    target_agent_id=request.entry_agent_id,
                    title=document.display_name or document.slug or "Protocol run",
                    origin_channel="registry",
                    external_conversation_ref=f"protocol-run:{run_id}",
                    source_kind=source_kind,
                    hidden_from_default_views=hidden_from_default_views,
                    now=now,
                )
                root_conversation_id = str(created.conversation_id or "")
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_runs (
                        protocol_run_id, protocol_id, protocol_definition_version_id,
                        source_kind, hidden_from_default_views,
                        entry_agent_id, entry_authority_ref, is_rehearsal, root_conversation_id,
                        origin_channel, workspace_ref, repo_ref, branch_ref,
                        problem_statement, constraints_json, status,
                        current_stage_execution_id, current_stage_key, termination_summary,
                        blocked_code, blocked_detail, run_org_id, started_by, version,
                        retention_until, last_transition_at, created_at, updated_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', '', '', '', '', '', %s, %s, 1, %s, '', %s, %s, '')
                    RETURNING *
                    """,
                    (
                        run_id,
                        protocol_row["protocol_id"],
                        version_row["protocol_definition_version_id"],
                        source_kind,
                        hidden_from_default_views,
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

    def get_protocol_artifact_snapshot(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord | None:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return self._protocol_artifact_snapshot_for_key(conn, run_id, artifact_key)

    def save_protocol_artifact_snapshot(
        self,
        snapshot: ProtocolArtifactSnapshotRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin", "agent")):
            raise PermissionError("Protocol artifact snapshot mutation requires operator, admin, or agent access.")
        with self._connect() as conn, write_tx(conn):
            detail = self._protocol_run_detail_in_tx(conn, snapshot.protocol_run_id, access=access)
            if detail is None:
                raise KeyError(snapshot.protocol_run_id)
            artifact = next(
                (item for item in detail.artifacts if item.artifact_key == snapshot.artifact_key),
                None,
            )
            if artifact is None:
                raise KeyError(snapshot.artifact_key)
            now = utcnow_iso()
            snapshot_id = snapshot.artifact_snapshot_id or uuid.uuid4().hex
            created_at = snapshot.created_at or now
            created_by = snapshot.created_by or self._access_actor_ref(access)
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_artifact_snapshots (
                        artifact_snapshot_id, protocol_artifact_id, protocol_run_id, artifact_key,
                        snapshot_kind, storage_uri, content_hash, size_bytes, manifest_json,
                        retention_state, retention_until, created_at, created_by, deleted_at, deleted_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (artifact_snapshot_id) DO UPDATE SET
                        protocol_artifact_id = EXCLUDED.protocol_artifact_id,
                        storage_uri = EXCLUDED.storage_uri,
                        content_hash = EXCLUDED.content_hash,
                        size_bytes = EXCLUDED.size_bytes,
                        manifest_json = EXCLUDED.manifest_json,
                        retention_state = EXCLUDED.retention_state,
                        retention_until = EXCLUDED.retention_until,
                        deleted_at = EXCLUDED.deleted_at,
                        deleted_by = EXCLUDED.deleted_by
                    RETURNING *
                    """,
                    (
                        snapshot_id,
                        snapshot.protocol_artifact_id or artifact.protocol_artifact_id,
                        snapshot.protocol_run_id,
                        snapshot.artifact_key,
                        snapshot.snapshot_kind,
                        snapshot.storage_uri,
                        snapshot.content_hash,
                        snapshot.size_bytes,
                        jsonb(snapshot.manifest_json.as_dict()),
                        snapshot.retention_state or "active",
                        snapshot.retention_until,
                        created_at,
                        created_by,
                        snapshot.deleted_at,
                        snapshot.deleted_by,
                    ),
                )
                row = db_cur.fetchone()
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_transitions (
                        protocol_transition_id, protocol_run_id, transition_kind,
                        decision, reason, metadata_json, actor_type, actor_ref, created_at
                    ) VALUES (%s, %s, 'artifact_snapshot', 'snapshotted', %s, %s, 'registry', %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        snapshot.protocol_run_id,
                        f"Artifact {snapshot.artifact_key} snapshotted.",
                        jsonb({
                            "artifact_key": snapshot.artifact_key,
                            "artifact_snapshot_id": snapshot_id,
                            "content_hash": snapshot.content_hash,
                            "size_bytes": snapshot.size_bytes,
                        }),
                        created_by,
                        now,
                    ),
                )
            if row is None:
                raise RuntimeError("Failed to persist artifact snapshot.")
            return self._protocol_artifact_snapshot_from_row(row)

    def delete_protocol_artifact_snapshot(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactSnapshotRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin")):
            raise PermissionError("Protocol artifact snapshot delete requires operator or admin access.")
        with self._connect() as conn, write_tx(conn):
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            snapshot = self._protocol_artifact_snapshot_for_key(conn, run_id, artifact_key)
            if snapshot is None:
                raise KeyError(artifact_key)
            now = utcnow_iso()
            actor = self._access_actor_ref(access)
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_artifact_snapshots
                    SET retention_state = 'deleted', deleted_at = %s, deleted_by = %s
                    WHERE artifact_snapshot_id = %s
                    RETURNING *
                    """,
                    (now, actor, snapshot.artifact_snapshot_id),
                )
                row = db_cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to delete artifact snapshot.")
            return self._protocol_artifact_snapshot_from_row(row)

    def save_workspace_cleanup_inventory(
        self,
        *,
        inventory_id: str,
        agent_id: str,
        workspace_ref: str = "",
        protocol_run_id: str = "",
        scan_status: str = "completed",
        file_count: int = 0,
        total_bytes: int = 0,
        retained_bytes: int = 0,
        transient_bytes: int = 0,
        unknown_bytes: int = 0,
        summary: Mapping[str, object] | None = None,
        access: ProtocolAccessContextRecord,
    ) -> dict[str, object]:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin")):
            raise PermissionError("Workspace cleanup inventory requires operator access.")
        now = utcnow_iso()
        row_id = str(inventory_id or "").strip() or uuid.uuid4().hex
        payload = dict(summary or {})
        with self._connect() as conn, write_tx(conn):
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.workspace_cleanup_inventory (
                        inventory_id, agent_id, workspace_ref, protocol_run_id, scan_status,
                        file_count, total_bytes, retained_bytes, transient_bytes, unknown_bytes,
                        summary_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (inventory_id) DO UPDATE SET
                        agent_id = EXCLUDED.agent_id,
                        workspace_ref = EXCLUDED.workspace_ref,
                        protocol_run_id = EXCLUDED.protocol_run_id,
                        scan_status = EXCLUDED.scan_status,
                        file_count = EXCLUDED.file_count,
                        total_bytes = EXCLUDED.total_bytes,
                        retained_bytes = EXCLUDED.retained_bytes,
                        transient_bytes = EXCLUDED.transient_bytes,
                        unknown_bytes = EXCLUDED.unknown_bytes,
                        summary_json = EXCLUDED.summary_json
                    RETURNING *
                    """,
                    (
                        row_id,
                        agent_id,
                        workspace_ref,
                        protocol_run_id,
                        scan_status,
                        int(file_count or 0),
                        int(total_bytes or 0),
                        int(retained_bytes or 0),
                        int(transient_bytes or 0),
                        int(unknown_bytes or 0),
                        jsonb(payload),
                        now,
                    ),
                )
                row = db_cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to persist workspace cleanup inventory.")
            return dict(row)

    def get_workspace_cleanup_inventory(
        self,
        inventory_id: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> dict[str, object] | None:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin")):
            raise PermissionError("Workspace cleanup inventory requires operator access.")
        with self._connect() as conn:
            row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.workspace_cleanup_inventory
                WHERE inventory_id = %s
                """,
                (inventory_id,),
            )
            return dict(row) if row is not None else None

    def get_protocol_run_timeline(self, run_id: str, *, access: ProtocolAccessContextRecord) -> list[ProtocolTransitionRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            return detail.transitions

    def get_protocol_artifact_runtime(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord | None:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_artifact_runtime_instances
                WHERE protocol_run_id = %s
                  AND artifact_key = %s
                  AND status <> 'deleted'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (run_id, artifact_key),
            )
            return self._protocol_artifact_runtime_from_row(row) if row is not None else None

    def save_protocol_artifact_runtime(
        self,
        runtime: ProtocolArtifactRuntimeInstanceRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeInstanceRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin", "agent")):
            raise PermissionError("Protocol runtime mutation requires operator, admin, or agent access.")
        with self._connect() as conn, write_tx(conn):
            detail = self._protocol_run_detail_in_tx(conn, runtime.protocol_run_id, access=access)
            if detail is None:
                raise KeyError(runtime.protocol_run_id)
            now = utcnow_iso()
            existing = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"""
                SELECT runtime_instance_id, created_at
                FROM {SCHEMA}.protocol_artifact_runtime_instances
                WHERE runtime_instance_id = %s
                """,
                (runtime.runtime_instance_id,),
            )
            created_at = str(existing.get("created_at", "")) if existing is not None else (runtime.created_at or now)
            manifest_json = runtime.manifest.model_dump(mode="json") if runtime.manifest is not None else {}
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_artifact_runtime_instances (
                        runtime_instance_id, protocol_run_id, artifact_key, agent_id, status,
                        manifest_json, manifest_path, artifact_path, runtime_url, ui_url, api_url,
                        health_url, internal_url, pid, port, started_by, stopped_by,
                        failure_code, failure_detail, log_tail, created_at, updated_at,
                        started_at, stopped_at, expires_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (runtime_instance_id) DO UPDATE SET
                        agent_id = EXCLUDED.agent_id,
                        status = EXCLUDED.status,
                        manifest_json = EXCLUDED.manifest_json,
                        manifest_path = EXCLUDED.manifest_path,
                        artifact_path = EXCLUDED.artifact_path,
                        runtime_url = EXCLUDED.runtime_url,
                        ui_url = EXCLUDED.ui_url,
                        api_url = EXCLUDED.api_url,
                        health_url = EXCLUDED.health_url,
                        internal_url = EXCLUDED.internal_url,
                        pid = EXCLUDED.pid,
                        port = EXCLUDED.port,
                        started_by = EXCLUDED.started_by,
                        stopped_by = EXCLUDED.stopped_by,
                        failure_code = EXCLUDED.failure_code,
                        failure_detail = EXCLUDED.failure_detail,
                        log_tail = EXCLUDED.log_tail,
                        updated_at = EXCLUDED.updated_at,
                        started_at = EXCLUDED.started_at,
                        stopped_at = EXCLUDED.stopped_at,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (
                        runtime.runtime_instance_id,
                        runtime.protocol_run_id,
                        runtime.artifact_key,
                        runtime.agent_id,
                        runtime.status,
                        jsonb(manifest_json),
                        runtime.manifest_path,
                        runtime.artifact_path,
                        runtime.runtime_url,
                        runtime.ui_url,
                        runtime.api_url,
                        runtime.health_url,
                        runtime.internal_url,
                        runtime.pid,
                        runtime.port,
                        runtime.started_by,
                        runtime.stopped_by,
                        runtime.failure_code,
                        runtime.failure_detail,
                        runtime.log_tail,
                        created_at,
                        runtime.updated_at or now,
                        runtime.started_at,
                        runtime.stopped_at,
                        runtime.expires_at,
                    ),
                )
            row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_artifact_runtime_instances WHERE runtime_instance_id = %s",
                (runtime.runtime_instance_id,),
            )
            if row is None:
                raise RuntimeError("Failed to persist artifact runtime.")
            return self._protocol_artifact_runtime_from_row(row)

    def append_protocol_artifact_runtime_event(
        self,
        event: ProtocolArtifactRuntimeEventRecord,
        *,
        access: ProtocolAccessContextRecord,
    ) -> ProtocolArtifactRuntimeEventRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin", "agent", "auditor")):
            raise PermissionError("Protocol runtime event mutation requires protocol access.")
        with self._connect() as conn, write_tx(conn):
            detail = self._protocol_run_detail_in_tx(conn, event.protocol_run_id, access=access)
            if detail is None:
                raise KeyError(event.protocol_run_id)
            runtime_event_id = event.runtime_event_id or uuid.uuid4().hex
            created_at = event.created_at or utcnow_iso()
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_artifact_runtime_events (
                        runtime_event_id, runtime_instance_id, protocol_run_id, artifact_key,
                        event_kind, actor_ref, summary, metadata_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        runtime_event_id,
                        event.runtime_instance_id,
                        event.protocol_run_id,
                        event.artifact_key,
                        event.event_kind,
                        event.actor_ref,
                        event.summary,
                        jsonb(event.metadata_json.as_dict()),
                        created_at,
                    ),
                )
            row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_artifact_runtime_events WHERE runtime_event_id = %s",
                (runtime_event_id,),
            )
            if row is None:
                raise RuntimeError("Failed to persist artifact runtime event.")
            saved = self._protocol_artifact_runtime_event_from_row(row)
            self._maybe_complete_blocked_runtime_acceptance_in_tx(
                conn,
                run_id=event.protocol_run_id,
                actor_ref=event.actor_ref or self._access_actor_ref(access),
                now=created_at,
            )
            return saved

    def _maybe_complete_blocked_runtime_acceptance_in_tx(
        self,
        conn,
        *,
        run_id: str,
        actor_ref: str,
        now: str,
    ) -> None:
        run_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
            (run_id,),
        )
        if run_row is None:
            return
        if str(run_row.get("status", "") or "").strip().lower() != "blocked":
            return
        if str(run_row.get("blocked_code", "") or "").strip().lower() != "runtime_evidence_required":
            return
        stage_execution_id = str(run_row.get("current_stage_execution_id", "") or "").strip()
        if not stage_execution_id:
            return
        stage_execution_row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"SELECT * FROM {SCHEMA}.protocol_stage_executions WHERE protocol_stage_execution_id = %s",
            (stage_execution_id,),
        )
        if stage_execution_row is None:
            return
        if str(stage_execution_row.get("status", "") or "").strip().lower() != "blocked":
            return
        if str(stage_execution_row.get("decision", "") or "").strip().lower() != "accept":
            return
        if str(stage_execution_row.get("failure_code", "") or "").strip().lower() != "runtime_evidence_required":
            return
        try:
            document = self._protocol_document_for_run(conn, run_row)
            stage = document.stage(str(stage_execution_row.get("stage_key", "") or ""))
        except Exception:
            return
        if stage.stage_kind != "acceptance":
            return

        reason = (
            "Registry runtime evidence now satisfies the blocked final acceptance gate: "
            "runtime start, health check, routed UI/API exercise, visible outcome evidence, "
            "outcome-readiness matrix, and customer-facing branding evidence are recorded."
        )
        engine = self._protocol_engine.evaluate_operator_action(
            document=document,
            run=self._protocol_run_from_row(run_row),
            stage_execution=self._protocol_stage_execution_from_row(stage_execution_row),
            stage_executions=self._protocol_stage_executions_for_run(conn, run_id),
            action="accept",
            reason=reason,
            now=now,
            review_edge_counts=protocol_review_edge_counts(self._protocol_run_transitions_history(conn, run_id)),
        )
        engine = self._runtime_acceptance_evidence_gate(
            conn,
            run_row=run_row,
            stage_execution_row=stage_execution_row,
            engine=engine,
        )
        if str(engine.run_status or "") != "completed":
            return
        self._apply_protocol_engine_decision_in_tx(
            conn,
            run_row=run_row,
            stage_execution_row=stage_execution_row,
            engine=engine,
            actor_type="protocol_engine",
            actor_ref=str(actor_ref or "runtime_evidence_gate"),
            now=now,
        )
        self._record_protocol_compliance_event(
            conn,
            protocol_run_id=run_id,
            protocol_definition_version_id=str(run_row.get("protocol_definition_version_id", "") or ""),
            event_kind="runtime_evidence_auto_accept",
            actor_ref=str(actor_ref or "runtime_evidence_gate"),
            actor_role="protocol_engine",
            summary=reason,
            metadata={
                "current_stage_key": str(stage_execution_row.get("stage_key", "") or ""),
                "stage_execution_id": str(stage_execution_row.get("protocol_stage_execution_id", "") or ""),
            },
            now=now,
        )

    def list_protocol_artifact_runtime_events(
        self,
        run_id: str,
        artifact_key: str,
        *,
        access: ProtocolAccessContextRecord,
        limit: int = 50,
    ) -> list[ProtocolArtifactRuntimeEventRecord]:
        with self._connect() as conn:
            detail = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if detail is None:
                raise KeyError(run_id)
            current_runtime = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"""
                SELECT runtime_instance_id
                FROM {SCHEMA}.protocol_artifact_runtime_instances
                WHERE protocol_run_id = %s
                  AND artifact_key = %s
                  AND status <> 'deleted'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (run_id, artifact_key),
            )
            if current_runtime is None:
                return []
            rows = POSTGRES_STORE_DIALECT.fetchall(
                conn,
                f"""
                SELECT *
                FROM {SCHEMA}.protocol_artifact_runtime_events
                WHERE runtime_instance_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (
                    str(current_runtime.get("runtime_instance_id", "") or ""),
                    max(1, min(int(limit or 50), 200)),
                ),
            )
            return [self._protocol_artifact_runtime_event_from_row(row) for row in rows]

    def export_protocol_run(self, run_id: str, *, access: ProtocolAccessContextRecord) -> ProtocolRunExportRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "auditor", "admin", "agent")):
            raise PermissionError("Protocol export requires operator, auditor, or agent access.")
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
                tasks=detail.tasks,
                artifacts=detail.artifacts,
                artifact_snapshots=detail.artifact_snapshots,
                runtime_instances=detail.runtime_instances,
                runtime_events=detail.runtime_events,
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
            engine = self._runtime_acceptance_evidence_gate(
                conn,
                run_row=run_row,
                stage_execution_row=stage_execution_row,
                engine=engine,
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

    def _running_runtime_count_for_run(self, conn, run_id: str) -> int:
        row = POSTGRES_STORE_DIALECT.fetchone(
            conn,
            f"""
            SELECT COUNT(*) AS count
            FROM {SCHEMA}.protocol_artifact_runtime_instances
            WHERE protocol_run_id = %s
              AND status IN ('starting', 'running', 'stopping')
            """,
            (run_id,),
        ) or {"count": 0}
        return int(row.get("count", 0) or 0)

    def _set_protocol_run_lifecycle_status(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        target_status: str,
        reason: str,
    ) -> ProtocolRunMutationRecord:
        if not any(self._access_has_role(access, role) for role in ("operator", "admin")):
            return ProtocolRunMutationRecord(ok=False, status="forbidden", message="Protocol run lifecycle changes require operator access.")
        normalized_status = str(target_status or "").strip().lower()
        if normalized_status not in {"archived", "deleted", "restore"}:
            return ProtocolRunMutationRecord(ok=False, status="invalid_action", message="Unsupported protocol run lifecycle action.")
        now = utcnow_iso()
        actor = self._access_actor_ref(access)
        with self._connect() as conn, write_tx(conn):
            raw_run_row = POSTGRES_STORE_DIALECT.fetchone(
                conn,
                f"SELECT * FROM {SCHEMA}.protocol_runs WHERE protocol_run_id = %s",
                (run_id,),
            )
            visibility = self._protocol_run_visibility_status(raw_run_row, access=access)
            if visibility == "missing":
                return ProtocolRunMutationRecord(ok=False, status="not_found", message="Protocol run not found.")
            if visibility == "not_visible":
                return ProtocolRunMutationRecord(ok=False, status="not_visible", message="Protocol run is not visible to this actor.")
            run_row = dict(raw_run_row or {})
            current_status = str(run_row.get("status", "") or "").strip().lower()
            running_runtimes = self._running_runtime_count_for_run(conn, run_id)
            if normalized_status in {"archived", "deleted"} and running_runtimes:
                return ProtocolRunMutationRecord(
                    ok=False,
                    status="invalid_action",
                    message="Stop artifact runtimes before archiving or deleting this run.",
                )
            active_statuses = {"queued", "running"}
            if normalized_status == "archived":
                if current_status in active_statuses:
                    return ProtocolRunMutationRecord(ok=False, status="invalid_action", message="Cancel or finish the run before archiving it.")
                if current_status == "deleted":
                    return ProtocolRunMutationRecord(ok=False, status="invalid_action", message="Deleted runs cannot be archived.")
                next_status = "archived"
                hidden = True
                summary = str(reason or "Protocol run archived.").strip()
                metadata = {"previous_status": current_status}
            elif normalized_status == "deleted":
                if current_status in active_statuses:
                    return ProtocolRunMutationRecord(ok=False, status="invalid_action", message="Cancel or finish the run before deleting it.")
                next_status = "deleted"
                hidden = True
                summary = str(reason or "Protocol run deleted.").strip()
                metadata = {"previous_status": current_status}
            else:
                if current_status != "archived":
                    return ProtocolRunMutationRecord(ok=False, status="invalid_action", message="Only archived runs can be restored.")
                previous_status = "completed"
                latest_transition = POSTGRES_STORE_DIALECT.fetchone(
                    conn,
                    f"""
                    SELECT metadata_json
                    FROM {SCHEMA}.protocol_transitions
                    WHERE protocol_run_id = %s
                      AND transition_kind = 'run_lifecycle'
                      AND decision = 'archived'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
                metadata_json = latest_transition.get("metadata_json", {}) if latest_transition is not None else {}
                if isinstance(metadata_json, Mapping):
                    candidate = str(metadata_json.get("previous_status", "") or "").strip().lower()
                    if candidate and candidate not in {"archived", "deleted", "queued", "running"}:
                        previous_status = candidate
                next_status = previous_status
                hidden = False
                summary = str(reason or "Protocol run restored.").strip()
                metadata = {"previous_status": current_status, "restored_status": previous_status}
            with cur(conn) as db_cur:
                db_cur.execute(
                    f"""
                    UPDATE {SCHEMA}.protocol_runs
                    SET status = %s,
                        hidden_from_default_views = %s,
                        termination_summary = CASE WHEN %s <> '' THEN %s ELSE termination_summary END,
                        updated_at = %s,
                        version = version + 1
                    WHERE protocol_run_id = %s
                    RETURNING *
                    """,
                    (next_status, hidden, summary, summary, now, run_id),
                )
                updated_row = db_cur.fetchone()
                db_cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.protocol_transitions (
                        protocol_transition_id, protocol_run_id, transition_kind, decision,
                        reason, metadata_json, actor_type, actor_ref, created_at
                    ) VALUES (%s, %s, 'run_lifecycle', %s, %s, %s, 'operator', %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_id,
                        "restored" if normalized_status == "restore" else next_status,
                        summary,
                        jsonb(metadata),
                        actor,
                        now,
                    ),
                )
            if updated_row is None:
                raise RuntimeError("Failed to update protocol run lifecycle.")
            refreshed = self._protocol_run_detail_in_tx(conn, run_id, access=access)
            if refreshed is None:
                raise RuntimeError("Failed to reload protocol run lifecycle.")
            return ProtocolRunMutationRecord(
                ok=True,
                status="updated",
                message=f"Protocol run {('restored' if normalized_status == 'restore' else next_status)}.",
                run=refreshed.run,
                stage_execution=refreshed.stage_executions[0] if refreshed.stage_executions else None,
            )

    def archive_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        return self._set_protocol_run_lifecycle_status(run_id, access=access, target_status="archived", reason=reason)

    def restore_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        return self._set_protocol_run_lifecycle_status(run_id, access=access, target_status="restore", reason=reason)

    def delete_protocol_run(
        self,
        run_id: str,
        *,
        access: ProtocolAccessContextRecord,
        reason: str = "",
    ) -> ProtocolRunMutationRecord:
        return self._set_protocol_run_lifecycle_status(run_id, access=access, target_status="deleted", reason=reason)

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
