"""Protocol models, constants, and shared record types."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import PurePosixPath
import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator
import yaml

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel, RoutedTaskRequest, TargetSelector, TaskRecord, utcnow_iso

ProtocolLifecycleState = Literal["draft", "published", "archived"]
ProtocolVisibility = Literal["org_private", "org_shared", "registry_template"]
ProtocolRunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked", "archived", "deleted"]
ProtocolStageKind = Literal["work", "review", "acceptance"]
ProtocolStageExecutionStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked"]
ProtocolArtifactKind = Literal["workspace_file", "control_plane_text"]
ProtocolArtifactRuntimeKind = Literal["static", "node", "python", "java", "binary", "process"]
ProtocolArtifactRuntimeStatus = Literal[
    "not_configured",
    "starting",
    "running",
    "stopping",
    "stopped",
    "failed",
    "archived",
    "deleted",
]
ProtocolArtifactRuntimeEventKind = Literal[
    "detected",
    "start_requested",
    "started",
    "health_checked",
    "fetch",
    "stop_requested",
    "stopped",
    "archived",
    "deleted",
    "failed",
    "journey_requested",
    "journey_completed",
    "journey_failed",
]
ProtocolRuntimeCapabilityAction = Literal[
    "runtime:start",
    "runtime:stop",
    "runtime:read",
    "runtime:fetch",
    "runtime:event",
    "journey:read",
    "journey:result",
    "journey:run",
]
ProtocolEvidenceTrustTier = Literal["tier_1", "tier_2", "tier_3"]
ProtocolEvidenceStatus = Literal["passed", "failed", "skipped", "stale", "uncorroborated", "blocked"]
ProtocolResolutionOutcome = Literal["queued", "ok", "error"]
ProtocolArtifactVerificationState = Literal["declared", "available", "verified", "missing", "waived"]
ProtocolArtifactRetentionState = Literal["active", "archived", "expired", "deleted", "unavailable"]
ProtocolArtifactSnapshotKind = Literal["file", "directory", "text", "external"]
ProtocolOperatorAction = Literal["cancel", "retry", "accept", "send_back", "interrupt"]
PROTOCOL_GENERATED_SERIOUS_WORK_TIMEOUT_SECONDS = 14_400
PROTOCOL_GENERATED_SERIOUS_REVIEW_TIMEOUT_SECONDS = 10_800
PROTOCOL_GENERATED_SERIOUS_ACCEPTANCE_TIMEOUT_SECONDS = 10_800
ProtocolIssueKind = Literal[
    "blocked_run",
    "invalid_contract",
    "runtime_evidence_required",
    "operator_interrupted",
    "acceptance_contract_invalid",
    "stuck_lease",
    "expired_timeout",
]
ProtocolDocumentTextFormat = Literal["json", "yaml"]
ProtocolRunForkMode = Literal["rerun_selected", "continue_after"]
ProtocolDraftSourceKind = Literal["blank", "template", "protocol"]
ProtocolValidationMode = Literal["strict", "draft"]
ProtocolAuthoringSurface = Literal["standard", "operator"]
ProtocolRunInputKind = Literal["text", "textarea", "select"]

PROTOCOL_SCHEMA_VERSION = 1
PROTOCOL_MIN_SCHEMA_VERSION = 1
PROTOCOL_LEGACY_SCHEMA_VERSION = 0
PROTOCOL_WAIVER_MODE = "forbid"
PROTOCOL_DEFAULT_RETENTION_DAYS = 90
PROTOCOL_DEFAULT_RUN_ORG_ID = "local"
PROTOCOL_DEFAULT_OPERATOR_REF = "operator-session"
PROTOCOL_DEFAULT_VISIBILITY: ProtocolVisibility = "org_private"

REHEARSAL_AUTHORITY_REF = "rehearsal"
"""Canonical authority ref for rehearsal runs.

A protocol run whose ``entry_authority_ref`` equals this constant is a dry
rehearsal: external egress (webhooks, outbound transports, credentialed
provider calls) is gated at the composition layer, and only agents enrolled
under this authority may be resolved as participants for the run."""
PROTOCOL_SUPPORTED_RUN_STATUSES: tuple[ProtocolRunStatus, ...] = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "blocked",
)
PROTOCOL_SUPPORTED_STAGE_STATUSES: tuple[ProtocolStageExecutionStatus, ...] = PROTOCOL_SUPPORTED_RUN_STATUSES
PROTOCOL_STAGE_KIND_OPTIONS: tuple[ProtocolStageKind, ...] = ("work", "review", "acceptance")
PROTOCOL_ARTIFACT_KIND_OPTIONS: tuple[ProtocolArtifactKind, ...] = ("workspace_file", "control_plane_text")
PROTOCOL_SELECTOR_KIND_OPTIONS: tuple[str, ...] = ("agent", "skill", "role")
PROTOCOL_AUTHORING_SECTION_OPTIONS: tuple[str, ...] = (
    "design",
    "review",
)
PROTOCOL_AUTHORING_SURFACE_OPTIONS: tuple[ProtocolAuthoringSurface, ...] = ("standard", "operator")

_TERMINAL_STAGE_TARGETS = frozenset({"__complete__", "__failed__", "__cancelled__"})
_DECISION_RE = re.compile(r"(?im)^\s*PROTOCOL_DECISION:\s*([a-z0-9_-]+)\s*$")
_SUMMARY_RE = re.compile(r"(?im)^\s*PROTOCOL_SUMMARY:\s*(.+?)\s*$")


def _normalize_key(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


def _validate_relative_workspace_path(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "\\" in text:
        raise ValueError(f"{field_name} must use forward slashes")
    path = PurePosixPath(text)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative to the workspace root")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"{field_name} must not escape the workspace root")
    normalized = path.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_slug_list(raw: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for item in raw or ():
        slug = str(item or "").strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        items.append(slug)
    return items


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        value = line.strip()
        if value and not value.startswith("PROTOCOL_"):
            return value
    return ""


def _coerce_iso(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601 text") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def protocol_retention_until(now: str | None = None, *, days: int = PROTOCOL_DEFAULT_RETENTION_DAYS) -> str:
    base = now or utcnow_iso()
    parsed = datetime.fromisoformat(base)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(days=days)).isoformat()


class ProtocolParticipantDefinitionRecord(RegistryRecordModel):
    participant_key: str = Field(..., min_length=1)
    display_name: str = ""
    instructions: str = ""

    @field_validator("participant_key", mode="before")
    @classmethod
    def _participant_key(cls, value: object) -> str:
        return _normalize_key(value, field_name="participant_key")


class ProtocolArtifactDefinitionRecord(RegistryRecordModel):
    artifact_key: str = Field(..., min_length=1)
    display_name: str = ""
    description: str = ""
    kind: ProtocolArtifactKind = "workspace_file"
    path: str = ""
    verify: bool = True

    @field_validator("artifact_key", mode="before")
    @classmethod
    def _artifact_key(cls, value: object) -> str:
        return _normalize_key(value, field_name="artifact_key")

    @field_validator("path", mode="before")
    @classmethod
    def _path(cls, value: object) -> str:
        return _validate_relative_workspace_path(value, field_name="path")

    @model_validator(mode="after")
    def _validate_shape(self) -> "ProtocolArtifactDefinitionRecord":
        if self.kind == "workspace_file" and not str(self.path or "").strip():
            raise ValueError("workspace_file artifacts require a path")
        if PROTOCOL_WAIVER_MODE == "forbid" and not self.verify:
            raise ValueError("artifact.verify=false is not allowed in this deployment mode")
        return self


class ProtocolStageDefinitionRecord(RegistryRecordModel):
    stage_key: str = Field(..., min_length=1)
    display_name: str = ""
    participant_key: str = Field(..., min_length=1)
    selector: TargetSelector | None = None
    stage_kind: ProtocolStageKind = "work"
    instructions: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    transitions: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    write_capable: bool = False
    max_rounds: int = Field(default=0, ge=0)
    strict_completion: bool = False
    require_output_verification: bool | None = None
    timeout_seconds: int = Field(default=0, ge=0)

    @field_validator("stage_key", "participant_key", mode="before")
    @classmethod
    def _required_keys(cls, value: object, info) -> str:
        return _normalize_key(value, field_name=info.field_name)

    @field_validator("inputs", "outputs", mode="before")
    @classmethod
    def _artifact_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
        else:
            items = [str(item or "").strip() for item in value]
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def transition_target(self, decision: str) -> str:
        raw = self.transitions.get(str(decision or "").strip(), "")
        return str(raw or "").strip()

    def allowed_decisions(self) -> tuple[str, ...]:
        keys = [
            str(key or "").strip().lower()
            for key in self.transitions.as_dict().keys()
            if str(key or "").strip()
        ]
        if keys:
            return tuple(keys)
        if self.stage_kind == "work":
            return ("completed",)
        return ("accept", "revise", "fail")


class ProtocolPoliciesRecord(RegistryRecordModel):
    single_active_writer: bool = True
    max_review_rounds: int = Field(default=5, ge=1)


class ProtocolDefinitionDocumentRecord(RegistryRecordModel):
    schema_version: int = Field(default=PROTOCOL_SCHEMA_VERSION, ge=1)
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    participants: list[ProtocolParticipantDefinitionRecord] = Field(default_factory=list)
    artifacts: list[ProtocolArtifactDefinitionRecord] = Field(default_factory=list)
    stages: list[ProtocolStageDefinitionRecord] = Field(default_factory=list)
    policies: ProtocolPoliciesRecord = Field(default_factory=ProtocolPoliciesRecord)

    @model_validator(mode="after")
    def _validate_document(self) -> "ProtocolDefinitionDocumentRecord":
        if self.schema_version < PROTOCOL_MIN_SCHEMA_VERSION or self.schema_version > PROTOCOL_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported protocol schema_version "
                f"{self.schema_version}; expected between {PROTOCOL_MIN_SCHEMA_VERSION} and {PROTOCOL_SCHEMA_VERSION}"
            )
        participant_keys = [item.participant_key for item in self.participants]
        artifact_keys = [item.artifact_key for item in self.artifacts]
        stage_keys = [item.stage_key for item in self.stages]
        if not self.stages:
            raise ValueError("protocol definition requires at least one stage")
        if len(set(participant_keys)) != len(participant_keys):
            raise ValueError("participant_key values must be unique")
        if len(set(artifact_keys)) != len(artifact_keys):
            raise ValueError("artifact_key values must be unique")
        if len(set(stage_keys)) != len(stage_keys):
            raise ValueError("stage_key values must be unique")
        participant_set = set(participant_keys)
        artifact_set = set(artifact_keys)
        stage_set = set(stage_keys)
        if not str(self.metadata.get("slug", "") or "").strip():
            raise ValueError("protocol definition metadata.slug is required")
        for stage in self.stages:
            if stage.participant_key not in participant_set:
                raise ValueError(f"stage {stage.stage_key} references unknown participant {stage.participant_key}")
            for artifact_key in (*stage.inputs, *stage.outputs):
                if artifact_key not in artifact_set:
                    raise ValueError(f"stage {stage.stage_key} references unknown artifact {artifact_key}")
            transitions = stage.transitions.as_dict()
            if not transitions and stage.stage_kind != "work":
                raise ValueError(f"stage {stage.stage_key} must define transitions")
            if stage.stage_kind == "work" and not transitions:
                continue
            for decision, target in transitions.items():
                decision_key = str(decision or "").strip().lower()
                if not decision_key:
                    raise ValueError(f"stage {stage.stage_key} contains a blank transition decision")
                target_key = str(target or "").strip()
                if not target_key:
                    raise ValueError(f"stage {stage.stage_key} transition {decision} has no target")
                if target_key not in stage_set and target_key not in _TERMINAL_STAGE_TARGETS:
                    raise ValueError(
                        f"stage {stage.stage_key} transition {decision} references unknown target {target_key}"
                    )
        return self

    @property
    def slug(self) -> str:
        return str(self.metadata.get("slug", "") or "").strip()

    @property
    def display_name(self) -> str:
        return str(self.metadata.get("display_name", "") or self.slug or "").strip()

    @property
    def description(self) -> str:
        return str(self.metadata.get("description", "") or "").strip()

    def participant(self, participant_key: str) -> ProtocolParticipantDefinitionRecord:
        key = str(participant_key or "").strip()
        for item in self.participants:
            if item.participant_key == key:
                return item
        raise KeyError(key)

    def artifact(self, artifact_key: str) -> ProtocolArtifactDefinitionRecord:
        key = str(artifact_key or "").strip()
        for item in self.artifacts:
            if item.artifact_key == key:
                return item
        raise KeyError(key)

    def stage(self, stage_key: str) -> ProtocolStageDefinitionRecord:
        key = str(stage_key or "").strip()
        for item in self.stages:
            if item.stage_key == key:
                return item
        raise KeyError(key)

    @property
    def first_stage_key(self) -> str:
        return self.stages[0].stage_key


class ProtocolValidationResultRecord(RegistryRecordModel):
    mode: ProtocolValidationMode = "strict"
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    issues: list["ProtocolValidationIssueRecord"] = Field(default_factory=list)
    next_required_actions: list[str] = Field(default_factory=list)
    normalized_document: ProtocolDefinitionDocumentRecord | None = None
    content_hash: str = ""


class ProtocolValidationIssueRecord(RegistryRecordModel):
    code: str = ""
    message: str = ""
    section: str = ""
    entity_kind: str = ""
    entity_key: str = ""
    path: str = ""
    blocking: bool = True


class ProtocolDefinitionRecord(RegistryRecordModel):
    protocol_id: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""
    lifecycle_state: ProtocolLifecycleState = "draft"
    current_version_id: str = ""
    owner_org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID
    visibility: ProtocolVisibility = PROTOCOL_DEFAULT_VISIBILITY
    created_by: str = ""
    updated_by: str = ""
    draft_revision: int = 0
    created_at: str = ""
    updated_at: str = ""


class ProtocolRunInputFieldRecord(RegistryRecordModel):
    """One launch-time input a protocol surface can ask a user to provide."""

    key: str = Field(..., min_length=1)
    label: str = ""
    help: str = ""
    kind: ProtocolRunInputKind = "textarea"
    required: bool = False
    default_value: str = ""
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, value: object) -> str:
        return _normalize_key(value, field_name="key")

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw = [part.strip() for part in value.split(",")]
        else:
            raw = [str(item or "").strip() for item in value]
        seen: set[str] = set()
        options: list[str] = []
        for item in raw:
            if not item or item in seen:
                continue
            seen.add(item)
            options.append(item)
        return options


class ProtocolRunLaunchFormRecord(RegistryRecordModel):
    """Transport-neutral launch form derived from a published protocol."""

    protocol_id: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""
    fields: list[ProtocolRunInputFieldRecord] = Field(default_factory=list)


class ProtocolDefinitionVersionRecord(RegistryRecordModel):
    protocol_definition_version_id: str = ""
    protocol_id: str = ""
    version: int = 0
    definition_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    content_hash: str = ""
    validation_status: str = ""
    published_at: str = ""
    published_by: str = ""
    created_at: str = ""


class ProtocolTemplateSummaryRecord(RegistryRecordModel):
    slug: str = ""
    display_name: str = ""
    description: str = ""
    featured: bool = False
    participant_count: int = 0
    artifact_count: int = 0
    stage_count: int = 0
    stage_kind_sequence: list[ProtocolStageKind] = Field(default_factory=list)


class ProtocolAuthoringOptionsRecord(RegistryRecordModel):
    sections: list[str] = Field(default_factory=lambda: list(PROTOCOL_AUTHORING_SECTION_OPTIONS))
    stage_kind_options: list[ProtocolStageKind] = Field(default_factory=lambda: list(PROTOCOL_STAGE_KIND_OPTIONS))
    artifact_kind_options: list[ProtocolArtifactKind] = Field(default_factory=lambda: list(PROTOCOL_ARTIFACT_KIND_OPTIONS))
    selector_kind_options: list[str] = Field(default_factory=lambda: list(PROTOCOL_SELECTOR_KIND_OPTIONS))
    default_surface: ProtocolAuthoringSurface = "standard"
    operator_surface_available: bool = False


class ProtocolTemplateCreateRecord(RegistryRecordModel):
    source_protocol_id: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""

    @model_validator(mode="after")
    def _validate_source(self) -> "ProtocolTemplateCreateRecord":
        if not str(self.source_protocol_id or "").strip():
            raise ValueError("source_protocol_id is required when creating a protocol template")
        return self


class ProtocolDraftCreateRecord(RegistryRecordModel):
    source_kind: ProtocolDraftSourceKind = "blank"
    template_slug: str = ""
    source_protocol_id: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""

    @model_validator(mode="after")
    def _validate_source(self) -> "ProtocolDraftCreateRecord":
        if self.source_kind == "template" and not str(self.template_slug or "").strip():
            raise ValueError("template_slug is required when source_kind=template")
        if self.source_kind == "protocol" and not str(self.source_protocol_id or "").strip():
            raise ValueError("source_protocol_id is required when source_kind=protocol")
        return self


class ProtocolRunRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    protocol_id: str = ""
    protocol_definition_version_id: str = ""
    source_kind: str = "protocol_run"
    hidden_from_default_views: bool = False
    entry_agent_id: str = ""
    entry_authority_ref: str = ""
    is_rehearsal: bool = False
    root_conversation_id: str = ""
    root_external_conversation_ref: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    repo_ref: str = ""
    branch_ref: str = ""
    problem_statement: str = ""
    resource_refs: list[str] = Field(default_factory=list)
    constraints_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    status: ProtocolRunStatus = "queued"
    current_stage_execution_id: str = ""
    current_stage_key: str = ""
    termination_summary: str = ""
    blocked_code: str = ""
    blocked_detail: str = ""
    current_review_rounds: int = 0
    max_review_rounds: int = 0
    current_review_edge_key: str = ""
    run_org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID
    started_by: str = ""
    version: int = 1
    retention_until: str = ""
    last_transition_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    parent_protocol_run_id: str = ""
    parent_stage_execution_id: str = ""
    fork_mode: str = ""
    fork_reason: str = ""


class ProtocolRunParticipantRecord(RegistryRecordModel):
    protocol_run_participant_id: str = ""
    protocol_run_id: str = ""
    participant_key: str = ""
    display_name: str = ""
    required_skills: list[str] = Field(default_factory=list)
    target_selector: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    resolved_agent_id: str = ""
    resolved_authority_ref: str = ""
    session_key: str = ""
    state: str = ""
    resolution_outcome: ProtocolResolutionOutcome = "queued"
    resolution_reason: str = ""
    selector_snapshot_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = ""
    updated_at: str = ""


class ProtocolStageExecutionRecord(RegistryRecordModel):
    protocol_stage_execution_id: str = ""
    protocol_run_id: str = ""
    stage_key: str = ""
    participant_key: str = ""
    attempt: int = 1
    loop_iteration: int = 1
    status: ProtocolStageExecutionStatus = "queued"
    decision: str = ""
    decision_summary: str = ""
    input_snapshot_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    routed_task_id: str = ""
    failure_code: str = ""
    failure_detail: str = ""
    timeout_at: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    started_at: str = ""
    completed_at: str = ""


class ProtocolArtifactRecord(RegistryRecordModel):
    protocol_artifact_id: str = ""
    protocol_run_id: str = ""
    artifact_key: str = ""
    artifact_kind: str = ""
    location: str = ""
    workspace_path: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    exists: bool = False
    modified_at: str = ""
    observed_at: str = ""
    verification_state: ProtocolArtifactVerificationState = "declared"
    produced_by_stage_execution_id: str = ""
    state: str = ""
    supersedes_protocol_artifact_id: str = ""
    created_at: str = ""


class ProtocolArtifactSnapshotRecord(RegistryRecordModel):
    artifact_snapshot_id: str = ""
    protocol_artifact_id: str = ""
    protocol_run_id: str = ""
    artifact_key: str = ""
    snapshot_kind: ProtocolArtifactSnapshotKind | str = "file"
    storage_uri: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    manifest_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    retention_state: ProtocolArtifactRetentionState | str = "active"
    retention_until: str = ""
    created_at: str = ""
    created_by: str = ""
    deleted_at: str = ""
    deleted_by: str = ""
    produced_by_stage_execution_id: str = ""


class ProtocolRunForkRequestRecord(RegistryRecordModel):
    stage_execution_id: str = ""
    fork_mode: ProtocolRunForkMode = "rerun_selected"
    fork_reason: str = ""


class ProtocolRunForkResultRecord(RegistryRecordModel):
    ok: bool = False
    status: str = ""
    message: str = ""
    run: ProtocolRunRecord | None = None
    stage_execution: ProtocolStageExecutionRecord | None = None
    missing_snapshots: list[str] = Field(default_factory=list)


class ProtocolArtifactRuntimeEndpointRecord(RegistryRecordModel):
    label: str = ""
    path: str = "/"
    endpoint_kind: Literal["ui", "api", "health", "docs", "other"] = "other"
    method: str = "GET"
    description: str = ""

    @field_validator("path", mode="before")
    @classmethod
    def _runtime_path(cls, value: object) -> str:
        text = str(value or "/").strip() or "/"
        if not text.startswith("/"):
            text = f"/{text}"
        if "\\" in text or ".." in PurePosixPath(text).parts:
            raise ValueError("runtime endpoint paths must not escape the artifact root")
        return text

    @field_validator("method", mode="before")
    @classmethod
    def _method(cls, value: object) -> str:
        text = str(value or "GET").strip().upper()
        return text or "GET"


class ProtocolRuntimeTestHookRecord(RegistryRecordModel):
    hook: str = ""
    selector: str = ""
    kind: Literal["button", "input", "text", "region", "link", "other"] = "other"
    description: str = ""

    @field_validator("hook", "selector", mode="before")
    @classmethod
    def _nonblank(cls, value: object, info) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be blank")
        return text


class ProtocolArtifactRuntimeManifestRecord(RegistryRecordModel):
    runtime_kind: ProtocolArtifactRuntimeKind = "static"
    display_name: str = ""
    description: str = ""
    working_directory: str = ""
    start_command: str = ""
    ui_path: str = "/"
    health_path: str = "/"
    api_base_path: str = "/api"
    port_env: str = "PORT"
    startup_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_runtime_seconds: int = Field(default=3600, ge=60, le=86400)
    endpoints: list[ProtocolArtifactRuntimeEndpointRecord] = Field(default_factory=list)
    smoke_test: list[str] = Field(default_factory=list)
    test_hooks: list[ProtocolRuntimeTestHookRecord] = Field(default_factory=list)
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)

    @field_validator("working_directory", mode="before")
    @classmethod
    def _working_directory(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return _validate_relative_workspace_path(text, field_name="working_directory")

    @field_validator("ui_path", "health_path", "api_base_path", mode="before")
    @classmethod
    def _url_path(cls, value: object) -> str:
        text = str(value or "/").strip() or "/"
        if not text.startswith("/"):
            text = f"/{text}"
        if "\\" in text or ".." in PurePosixPath(text).parts:
            raise ValueError("runtime paths must not escape the artifact root")
        return text

    @field_validator("port_env", mode="before")
    @classmethod
    def _port_env(cls, value: object) -> str:
        text = str(value or "PORT").strip()
        return text or "PORT"

    @field_validator("smoke_test", mode="before")
    @classmethod
    def _smoke_test(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(item or "").strip() for item in value if str(item or "").strip()]

    @model_validator(mode="after")
    def _validate_runtime_contract(self) -> "ProtocolArtifactRuntimeManifestRecord":
        if self.runtime_kind != "static" and not str(self.start_command or "").strip():
            raise ValueError("process-backed runtime artifacts require start_command")
        if self.runtime_kind != "static" and not self.smoke_test:
            raise ValueError("process-backed runtime artifacts require smoke_test steps")
        if self.runtime_kind != "static":
            endpoint_kinds = {str(item.endpoint_kind or "").strip().lower() for item in self.endpoints}
            if "docs" not in endpoint_kinds:
                raise ValueError("process-backed runtime artifacts require a docs endpoint")
        return self


def runtime_manifest_run_ready_blockers(manifest: ProtocolArtifactRuntimeManifestRecord | None) -> list[str]:
    if manifest is None:
        return []
    if str(manifest.runtime_kind or "").strip().lower() == "static":
        return []
    command = str(manifest.start_command or "").strip()
    if not command:
        return ["start_command is missing"]
    normalized = re.sub(r"\s+", " ", command.lower())
    blocker_patterns = [
        (r"(^|[;&|]\s*|\s)(\.\/mvnw|mvn)(\s|$)", "Maven commands build or resolve dependencies at user start"),
        (r"(^|[;&|]\s*|\s)(\.\/gradlew|gradle)(\s|$)", "Gradle commands build or resolve dependencies at user start"),
        (r"(^|[;&|]\s*|\s)(npm|pnpm|yarn)\s+(install|ci|add|build|test|run\s+build|run\s+test)(\s|$)", "Node dependency, build, or test commands must run before acceptance"),
        (r"(^|[;&|]\s*|\s)(pip|pip3|python\s+-m\s+pip|poetry|uv)\s+(install|sync|add)(\s|$)", "Python dependency installation must run before acceptance"),
        (r"(^|[;&|]\s*|\s)(cargo|go|dotnet)\s+(build|test|run)(\s|$)", "Build, test, or developer run commands must not be the user start command"),
        (r"(^|[;&|]\s*|\s)(pytest|tox|nox|make\s+(test|build|package)|cmake|meson|bazel)(\s|$)", "Test or build commands must run before acceptance"),
    ]
    blockers = [message for pattern, message in blocker_patterns if re.search(pattern, normalized)]
    return list(dict.fromkeys(blockers))


class ProtocolArtifactRuntimeInstanceRecord(RegistryRecordModel):
    runtime_instance_id: str = ""
    protocol_run_id: str = ""
    artifact_key: str = ""
    agent_id: str = ""
    status: ProtocolArtifactRuntimeStatus = "not_configured"
    manifest: ProtocolArtifactRuntimeManifestRecord | None = None
    manifest_path: str = ""
    artifact_path: str = ""
    runtime_url: str = ""
    ui_url: str = ""
    api_url: str = ""
    health_url: str = ""
    internal_url: str = ""
    pid: int = 0
    port: int = 0
    started_by: str = ""
    stopped_by: str = ""
    failure_code: str = ""
    failure_detail: str = ""
    log_tail: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    stopped_at: str = ""
    expires_at: str = ""


class ProtocolArtifactRuntimeEventRecord(RegistryRecordModel):
    runtime_event_id: str = ""
    runtime_instance_id: str = ""
    protocol_run_id: str = ""
    artifact_key: str = ""
    event_kind: ProtocolArtifactRuntimeEventKind | str = "detected"
    actor_ref: str = ""
    summary: str = ""
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    created_at: str = ""


class ProtocolRuntimeJourneySpecRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    artifact_key: str = ""
    journey_key: str = ""
    target_url: str = ""
    timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    steps: list[RegistryJsonRecord] = Field(default_factory=list)
    assertions: list[RegistryJsonRecord] = Field(default_factory=list)
    hooks: dict[str, ProtocolRuntimeTestHookRecord] = Field(default_factory=dict)
    allowed_external_origins: list[str] = Field(default_factory=list)
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolRuntimeJourneyResultRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    artifact_key: str = ""
    journey_key: str = ""
    journey_run_id: str = ""
    ok: bool = False
    status: str = ""
    summary: str = ""
    assertions: list[RegistryJsonRecord] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolEvidenceItemRecord(RegistryRecordModel):
    evidence_id: str = ""
    kind: str = ""
    trust_tier: ProtocolEvidenceTrustTier | str = "tier_2"
    requirement_id: str = ""
    status: ProtocolEvidenceStatus | str = "blocked"
    observed_at: str = ""
    artifact_content_hash: str = ""
    runtime_instance_id: str = ""
    source_stage_execution_id: str = ""
    source_artifact_key: str = ""
    command_or_probe: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    observed_result: str = ""
    corroboration_refs: list[str] = Field(default_factory=list)
    failure_detail: str = ""
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)

    @field_validator("trust_tier", mode="before")
    @classmethod
    def _trust_tier(cls, value: object) -> str:
        text = str(value or "tier_2").strip().lower().replace("-", "_").replace(" ", "_")
        if text in {"1", "tier1"}:
            return "tier_1"
        if text in {"2", "tier2"}:
            return "tier_2"
        if text in {"3", "tier3"}:
            return "tier_3"
        return text or "tier_2"


class ProtocolEvidenceManifestRecord(RegistryRecordModel):
    schema_version: int = 1
    artifact_key: str = ""
    artifact_content_hash: str = ""
    source_stage_execution_id: str = ""
    produced_at: str = ""
    evidence_items: list[ProtocolEvidenceItemRecord] = Field(default_factory=list)
    summary: str = ""
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolAcceptanceContractV2SkeletonRecord(RegistryRecordModel):
    schema_version: int = 2
    contract_required: bool = False
    product_class: str = ""
    primary_artifact_key: str = ""
    contract_artifact_key: str = "auto_protocol_contract"
    contract_producer_stage_key: str = "produce_system_verification_contract"
    contract_review_stage_key: str = "review_system_verification_contract"
    product_domain_contract_artifact_key: str = "product_domain_contract"
    producer_manifest_artifact_key: str = "producer_evidence_manifest"
    reviewer_manifest_artifact_key: str = "reviewer_evidence_manifest"
    required_evidence_kinds: list[str] = Field(default_factory=list)
    trust_tiers: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    legacy_v1_journeys: list[RegistryJsonRecord] = Field(default_factory=list)


class ProtocolAutoProtocolContractRecord(RegistryRecordModel):
    schema_version: int = 2
    product_contract: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    domain_contract: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    system_contract: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    verification_contract: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    operator_decisions_required: list[RegistryJsonRecord] = Field(default_factory=list)
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolRuntimeCapabilityTokenRecord(RegistryRecordModel):
    capability_token_id: str = ""
    capability_ref: str = ""
    protocol_run_id: str = ""
    protocol_stage_execution_id: str = ""
    artifact_key: str = ""
    participant_key: str = ""
    target_agent_id: str = ""
    allowed_actions: list[ProtocolRuntimeCapabilityAction | str] = Field(default_factory=list)
    expires_at: str = ""
    revoked_at: str = ""
    exchange_count: int = 0
    max_exchange_count: int = 5
    created_at: str = ""
    updated_at: str = ""
    actor_ref: str = ""


class ProtocolRuntimeCapabilityExchangeRecord(RegistryRecordModel):
    capability_ref: str = ""


class ProtocolRuntimeCapabilityExchangeResultRecord(RegistryRecordModel):
    ok: bool = False
    status: str = ""
    message: str = ""
    bearer_token: str = ""
    token: ProtocolRuntimeCapabilityTokenRecord | None = None


class ProtocolArtifactRuntimeHealthRecord(RegistryRecordModel):
    ok: bool = False
    status: ProtocolArtifactRuntimeStatus | str = "not_configured"
    status_code: int = 0
    message: str = ""
    checked_at: str = ""
    runtime: ProtocolArtifactRuntimeInstanceRecord | None = None


class ProtocolArtifactRuntimeActionResultRecord(RegistryRecordModel):
    ok: bool = False
    status: ProtocolArtifactRuntimeStatus | str = "not_configured"
    message: str = ""
    runtime: ProtocolArtifactRuntimeInstanceRecord | None = None
    event: ProtocolArtifactRuntimeEventRecord | None = None


class ProtocolTransitionRecord(RegistryRecordModel):
    protocol_transition_id: str = ""
    protocol_run_id: str = ""
    from_stage_execution_id: str = ""
    to_stage_execution_id: str = ""
    transition_kind: str = ""
    decision: str = ""
    reason: str = ""
    error_code: str = ""
    metadata_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    actor_type: str = ""
    actor_ref: str = ""
    created_at: str = ""


class ProtocolScenarioRecord(RegistryRecordModel):
    """Canned author response for rehearsal runs, reusable across stages."""

    protocol_scenario_id: str = ""
    protocol_id: str = ""
    stage_key: str = ""
    participant_key: str = ""
    display_name: str = ""
    decision: str = ""
    decision_summary: str = ""
    response_text: str = ""
    run_org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class ProtocolRunCreateRecord(RegistryRecordModel):
    protocol_id: str = ""
    protocol_definition_version_id: str = ""
    entry_agent_id: str = ""
    entry_authority_ref: str = ""
    is_rehearsal: bool = False
    root_conversation_id: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    repo_ref: str = ""
    branch_ref: str = ""
    problem_statement: str = ""
    resource_refs: list[str] = Field(default_factory=list)
    constraints_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolMutationRecord(RegistryRecordModel):
    ok: bool = False
    status: str = ""
    message: str = ""
    protocol: ProtocolDefinitionRecord | None = None
    draft_definition_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    draft_document: ProtocolDefinitionDocumentRecord | None = None
    version: ProtocolDefinitionVersionRecord | None = None
    validation: ProtocolValidationResultRecord | None = None


class ProtocolRunMutationRecord(RegistryRecordModel):
    ok: bool = False
    status: str = ""
    message: str = ""
    run: ProtocolRunRecord | None = None
    stage_execution: ProtocolStageExecutionRecord | None = None


class ProtocolRunDetailRecord(RegistryRecordModel):
    run: ProtocolRunRecord
    definition: ProtocolDefinitionRecord
    version: ProtocolDefinitionVersionRecord
    participants: list[ProtocolRunParticipantRecord] = Field(default_factory=list)
    stage_executions: list[ProtocolStageExecutionRecord] = Field(default_factory=list)
    tasks: list[TaskRecord] = Field(default_factory=list)
    artifacts: list[ProtocolArtifactRecord] = Field(default_factory=list)
    artifact_snapshots: list[ProtocolArtifactSnapshotRecord] = Field(default_factory=list)
    runtime_instances: list[ProtocolArtifactRuntimeInstanceRecord] = Field(default_factory=list)
    runtime_events: list[ProtocolArtifactRuntimeEventRecord] = Field(default_factory=list)
    transitions: list[ProtocolTransitionRecord] = Field(default_factory=list)


class ProtocolRunExportRecord(RegistryRecordModel):
    run: ProtocolRunRecord
    definition: ProtocolDefinitionRecord
    version: ProtocolDefinitionVersionRecord
    definition_document: ProtocolDefinitionDocumentRecord
    participants: list[ProtocolRunParticipantRecord] = Field(default_factory=list)
    stage_executions: list[ProtocolStageExecutionRecord] = Field(default_factory=list)
    tasks: list[TaskRecord] = Field(default_factory=list)
    artifacts: list[ProtocolArtifactRecord] = Field(default_factory=list)
    artifact_snapshots: list[ProtocolArtifactSnapshotRecord] = Field(default_factory=list)
    runtime_instances: list[ProtocolArtifactRuntimeInstanceRecord] = Field(default_factory=list)
    runtime_events: list[ProtocolArtifactRuntimeEventRecord] = Field(default_factory=list)
    transitions: list[ProtocolTransitionRecord] = Field(default_factory=list)


class ProtocolIssueRecord(RegistryRecordModel):
    issue_kind: ProtocolIssueKind
    protocol_run_id: str = ""
    protocol_id: str = ""
    protocol_display_name: str = ""
    stage_execution_id: str = ""
    stage_key: str = ""
    participant_key: str = ""
    run_status: ProtocolRunStatus = "queued"
    stage_status: ProtocolStageExecutionStatus = "queued"
    issue_code: str = ""
    issue_detail: str = ""
    lease_expires_at: str = ""
    timeout_at: str = ""
    task_updated_at: str = ""
    updated_at: str = ""


class ProtocolMaintenanceResultRecord(RegistryRecordModel):
    swept_count: int = 0
    affected_run_ids: list[str] = Field(default_factory=list)
    affected_auto_session_ids: list[str] = Field(default_factory=list)


class ProtocolTextDocumentRecord(RegistryRecordModel):
    format: ProtocolDocumentTextFormat = "json"
    text: str = ""
    document: ProtocolDefinitionDocumentRecord | RegistryJsonRecord | None = None
    validation: ProtocolValidationResultRecord | None = None


class ProtocolPackageSourceAgentRecord(RegistryRecordModel):
    source_agent_key: str = ""
    source_agent_id: str = ""
    slug: str = ""
    display_name: str = ""
    provider: str = ""
    role: str = ""
    advertised_skills: list[str] = Field(default_factory=list)


class ProtocolPackageStageBindingRecord(RegistryRecordModel):
    stage_key: str = ""
    selector: TargetSelector | None = None
    source_agent_key: str = ""
    required_skills: list[str] = Field(default_factory=list)


class ProtocolPackageBindingsRecord(RegistryRecordModel):
    source_agents: list[ProtocolPackageSourceAgentRecord] = Field(default_factory=list)
    stage_bindings: list[ProtocolPackageStageBindingRecord] = Field(default_factory=list)


class ProtocolPackageDocumentRecord(RegistryRecordModel):
    schema_version: int = 1
    kind: str = "octopus.protocol_package"
    protocol: ProtocolDefinitionDocumentRecord
    skills: list[RegistryJsonRecord] = Field(default_factory=list)
    bindings: ProtocolPackageBindingsRecord = Field(default_factory=ProtocolPackageBindingsRecord)
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolPackageIssueRecord(RegistryRecordModel):
    code: str = ""
    message: str = ""
    severity: str = "warning"
    field_path: str = ""
    blocking: bool = False


class ProtocolPackageProtocolPlanRecord(RegistryRecordModel):
    slug: str = ""
    display_name: str = ""
    exists: bool = False
    existing_protocol_id: str = ""
    identical_to_existing: bool = False
    available_policies: list[str] = Field(default_factory=list)
    suggested_copy_slug: str = ""
    suggested_copy_display_name: str = ""


class ProtocolPackageSkillPlanRecord(RegistryRecordModel):
    name: str = ""
    package_hash: str = ""
    status: str = "missing"
    target_agent_id: str = ""
    candidates: list[RegistryJsonRecord] = Field(default_factory=list)
    message: str = ""


class ProtocolPackageStageMappingPlanRecord(RegistryRecordModel):
    stage_key: str = ""
    selector: TargetSelector | None = None
    status: str = "requires_mapping"
    target_agent_id: str = ""
    candidates: list[RegistryJsonRecord] = Field(default_factory=list)
    message: str = ""


class ProtocolPackageImportPlanRecord(RegistryRecordModel):
    ok: bool = False
    format: ProtocolDocumentTextFormat = "json"
    package_hash: str = ""
    protocol: ProtocolPackageProtocolPlanRecord = Field(default_factory=ProtocolPackageProtocolPlanRecord)
    skills: list[ProtocolPackageSkillPlanRecord] = Field(default_factory=list)
    stage_mappings: list[ProtocolPackageStageMappingPlanRecord] = Field(default_factory=list)
    blocking_issues: list[ProtocolPackageIssueRecord] = Field(default_factory=list)
    warnings: list[ProtocolPackageIssueRecord] = Field(default_factory=list)


class ProtocolPackageImportApplyResultRecord(RegistryRecordModel):
    ok: bool = False
    status: str = ""
    message: str = ""
    protocol: ProtocolDefinitionRecord | None = None
    mutation: ProtocolMutationRecord | None = None
    plan: ProtocolPackageImportPlanRecord | None = None
    skill_results: list[RegistryJsonRecord] = Field(default_factory=list)
    mapping_results: list[RegistryJsonRecord] = Field(default_factory=list)


class ProtocolDefinitionDiffRecord(RegistryRecordModel):
    protocol_id: str = ""
    protocol_definition_version_id: str = ""
    diff: str = ""
    left_label: str = ""
    right_label: str = ""


class ProtocolStageDecisionRecord(RegistryRecordModel):
    decision: str = ""
    summary: str = ""


class ProtocolArtifactObservationRecord(RegistryRecordModel):
    artifact_key: str = Field(..., min_length=1)
    artifact_kind: ProtocolArtifactKind = "workspace_file"
    path: str = ""
    exists: bool = False
    size_bytes: int = 0
    content_hash: str = ""
    modified_at: str = ""
    observed_at: str = Field(default_factory=utcnow_iso)
    verification_state: ProtocolArtifactVerificationState = "declared"

    @field_validator("artifact_key", mode="before")
    @classmethod
    def _artifact_key(cls, value: object) -> str:
        return _normalize_key(value, field_name="artifact_key")

    @field_validator("path", mode="before")
    @classmethod
    def _path(cls, value: object) -> str:
        return _validate_relative_workspace_path(value, field_name="path")


class ProtocolStageArtifactContractRecord(RegistryRecordModel):
    artifact_key: str = Field(..., min_length=1)
    artifact_kind: ProtocolArtifactKind = "workspace_file"
    path: str = ""
    verify: bool = True


class ProtocolStageRuntimeContractRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    protocol_definition_version_id: str = ""
    protocol_stage_execution_id: str = ""
    participant_key: str = ""
    stage_key: str = ""
    stage_kind: ProtocolStageKind = "work"
    timeout_seconds: int = Field(default=0, ge=0)
    strict_completion: bool = False
    require_output_verification: bool = False
    output_artifacts: list[ProtocolStageArtifactContractRecord] = Field(default_factory=list)


class ProtocolStageTaskResultRecord(RegistryRecordModel):
    routed_task_id: str = ""
    status: str = ""
    summary: str = ""
    full_text: str = ""
    artifacts: list[ProtocolArtifactObservationRecord] = Field(default_factory=list)
    completed_at: str = Field(default_factory=utcnow_iso)

    @field_validator("completed_at", mode="before")
    @classmethod
    def _completed_at(cls, value: object) -> str:
        return utcnow_iso() if not str(value or "").strip() else str(value)


class ProtocolDispatchDecisionRecord(RegistryRecordModel):
    ok: bool = True
    error_code: str = ""
    error_detail: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    timeout_at: str = ""


class ProtocolParticipantResolutionRecord(RegistryRecordModel):
    selector: TargetSelector
    resolved_agent_id: str = ""
    resolved_authority_ref: str = ""
    outcome: ProtocolResolutionOutcome | str = "queued"
    reason: str = ""

    @property
    def ok(self) -> bool:
        return str(self.outcome or "").strip() == "ok" and bool(str(self.resolved_agent_id or "").strip())


class ProtocolEngineDecisionRecord(RegistryRecordModel):
    run_status: ProtocolRunStatus
    stage_status: ProtocolStageExecutionStatus
    decision: str = ""
    summary: str = ""
    failure_code: str = ""
    failure_detail: str = ""
    transition_kind: str = ""
    transition_reason: str = ""
    transition_error_code: str = ""
    next_stage_key: str = ""
    create_next_execution: bool = False
    terminal_status: ProtocolRunStatus | None = None
    run_blocked_code: str = ""
    run_blocked_detail: str = ""
    artifact_observations: list[ProtocolArtifactObservationRecord] = Field(default_factory=list)
    input_snapshot: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    retention_until: str = ""
    routed_task_id: str = ""
    timeout_at: str = ""
    lease_owner: str = ""
    lease_expires_at: str = ""
    started_at: str = ""
    participant_key: str = ""
    participant_state: str = ""
    participant_resolution_outcome: ProtocolResolutionOutcome | str = ""
    participant_resolution_reason: str = ""
    participant_resolved_agent_id: str = ""
    participant_resolved_authority_ref: str = ""
    selector_snapshot: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    transition_metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    routed_task_request: RoutedTaskRequest | None = None


class ProtocolAccessContextRecord(RegistryRecordModel):
    actor_ref: str = PROTOCOL_DEFAULT_OPERATOR_REF
    org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID
    roles: list[str] = Field(default_factory=list)

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw = (part.strip() for part in value.split(","))
        else:
            raw = (str(item or "").strip() for item in value)
        seen: set[str] = set()
        roles: list[str] = []
        for item in raw:
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            roles.append(key)
        return roles

    def has_role(self, role: str) -> bool:
        return str(role or "").strip().lower() in set(self.roles)




__all__ = [
    name
    for name in globals()
    if name.startswith("Protocol")
    or name in {
        "PROTOCOL_SCHEMA_VERSION",
        "PROTOCOL_MIN_SCHEMA_VERSION",
        "PROTOCOL_LEGACY_SCHEMA_VERSION",
        "PROTOCOL_WAIVER_MODE",
        "PROTOCOL_DEFAULT_RETENTION_DAYS",
        "PROTOCOL_DEFAULT_RUN_ORG_ID",
        "PROTOCOL_DEFAULT_OPERATOR_REF",
        "PROTOCOL_DEFAULT_VISIBILITY",
        "PROTOCOL_GENERATED_SERIOUS_WORK_TIMEOUT_SECONDS",
        "PROTOCOL_GENERATED_SERIOUS_REVIEW_TIMEOUT_SECONDS",
        "PROTOCOL_GENERATED_SERIOUS_ACCEPTANCE_TIMEOUT_SECONDS",
        "REHEARSAL_AUTHORITY_REF",
        "PROTOCOL_SUPPORTED_RUN_STATUSES",
        "PROTOCOL_SUPPORTED_STAGE_STATUSES",
        "PROTOCOL_STAGE_KIND_OPTIONS",
        "PROTOCOL_ARTIFACT_KIND_OPTIONS",
        "PROTOCOL_SELECTOR_KIND_OPTIONS",
        "PROTOCOL_AUTHORING_SECTION_OPTIONS",
        "PROTOCOL_AUTHORING_SURFACE_OPTIONS",
        "RegistryJsonRecord",
        "RegistryRecordModel",
        "RoutedTaskRequest",
        "TargetSelector",
        "utcnow_iso",
        "protocol_retention_until",
        "runtime_manifest_run_ready_blockers",
    }
]
