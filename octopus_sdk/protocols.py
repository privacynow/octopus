"""Shared protocol definition, lifecycle, and engine models."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel, TargetSelector, utcnow_iso

ProtocolLifecycleState = Literal["draft", "published", "archived"]
ProtocolVisibility = Literal["org_private", "org_shared", "registry_template"]
ProtocolRunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked"]
ProtocolStageKind = Literal["work", "review", "acceptance"]
ProtocolStageExecutionStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked"]
ProtocolArtifactKind = Literal["workspace_file", "control_plane_text"]
ProtocolResolutionOutcome = Literal["queued", "ok", "error"]
ProtocolArtifactVerificationState = Literal["declared", "available", "verified", "missing", "waived"]
ProtocolOperatorAction = Literal["cancel", "retry", "accept", "send_back"]

PROTOCOL_SCHEMA_VERSION = 1
PROTOCOL_MIN_SCHEMA_VERSION = 1
PROTOCOL_WAIVER_MODE = "forbid"
PROTOCOL_DEFAULT_RETENTION_DAYS = 90
PROTOCOL_DEFAULT_RUN_ORG_ID = "local"
PROTOCOL_DEFAULT_OPERATOR_REF = "operator-session"
PROTOCOL_DEFAULT_VISIBILITY: ProtocolVisibility = "org_private"
PROTOCOL_SUPPORTED_RUN_STATUSES: tuple[ProtocolRunStatus, ...] = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "blocked",
)
PROTOCOL_SUPPORTED_STAGE_STATUSES: tuple[ProtocolStageExecutionStatus, ...] = PROTOCOL_SUPPORTED_RUN_STATUSES

_TERMINAL_STAGE_TARGETS = frozenset({"__complete__", "__failed__", "__cancelled__"})
_DECISION_RE = re.compile(r"(?im)^\s*PROTOCOL_DECISION:\s*([a-z0-9_-]+)\s*$")
_SUMMARY_RE = re.compile(r"(?im)^\s*PROTOCOL_SUMMARY:\s*(.+?)\s*$")


def _normalize_key(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


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
    required_skills: list[str] = Field(default_factory=list)
    selector: TargetSelector | None = None
    instructions: str = ""

    @field_validator("participant_key", mode="before")
    @classmethod
    def _participant_key(cls, value: object) -> str:
        return _normalize_key(value, field_name="participant_key")

    @field_validator("required_skills", mode="before")
    @classmethod
    def _required_skills(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _normalize_slug_list(part.strip() for part in value.split(","))
        return _normalize_slug_list(value)


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
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    normalized_document: ProtocolDefinitionDocumentRecord | None = None
    content_hash: str = ""


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
    created_at: str = ""
    updated_at: str = ""


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


class ProtocolRunRecord(RegistryRecordModel):
    protocol_run_id: str = ""
    protocol_id: str = ""
    protocol_definition_version_id: str = ""
    entry_agent_id: str = ""
    entry_authority_ref: str = ""
    root_conversation_id: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    repo_ref: str = ""
    branch_ref: str = ""
    problem_statement: str = ""
    constraints_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    status: ProtocolRunStatus = "queued"
    current_stage_execution_id: str = ""
    current_stage_key: str = ""
    termination_summary: str = ""
    blocked_code: str = ""
    blocked_detail: str = ""
    run_org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID
    started_by: str = ""
    version: int = 1
    retention_until: str = ""
    last_transition_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""


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


class ProtocolRunCreateRecord(RegistryRecordModel):
    protocol_id: str = ""
    protocol_definition_version_id: str = ""
    entry_agent_id: str = ""
    entry_authority_ref: str = ""
    root_conversation_id: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    repo_ref: str = ""
    branch_ref: str = ""
    problem_statement: str = ""
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
    artifacts: list[ProtocolArtifactRecord] = Field(default_factory=list)
    transitions: list[ProtocolTransitionRecord] = Field(default_factory=list)


class ProtocolRunExportRecord(RegistryRecordModel):
    run: ProtocolRunRecord
    definition: ProtocolDefinitionRecord
    version: ProtocolDefinitionVersionRecord
    definition_document: ProtocolDefinitionDocumentRecord
    participants: list[ProtocolRunParticipantRecord] = Field(default_factory=list)
    stage_executions: list[ProtocolStageExecutionRecord] = Field(default_factory=list)
    artifacts: list[ProtocolArtifactRecord] = Field(default_factory=list)
    transitions: list[ProtocolTransitionRecord] = Field(default_factory=list)


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
    repeat_current_stage: bool = False
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
    participant_selector_snapshot: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    transition_metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


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


def migrate_protocol_document_data(value: object) -> dict[str, object]:
    raw = dict(value) if isinstance(value, dict) else (
        value.model_dump(mode="json")
        if hasattr(value, "model_dump")
        else {}
    )
    if not raw:
        return {}
    migrated = json.loads(json.dumps(raw))
    raw_schema_version = migrated.get("schema_version", PROTOCOL_SCHEMA_VERSION)
    try:
        schema_version = int(raw_schema_version or PROTOCOL_SCHEMA_VERSION)
    except (TypeError, ValueError) as exc:
        raise ValueError("protocol definition schema_version must be an integer") from exc
    if schema_version < PROTOCOL_MIN_SCHEMA_VERSION:
        schema_version = PROTOCOL_MIN_SCHEMA_VERSION
    if schema_version > PROTOCOL_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported protocol schema_version {schema_version}; expected at most {PROTOCOL_SCHEMA_VERSION}"
        )
    migrated["schema_version"] = PROTOCOL_SCHEMA_VERSION
    migrated.setdefault("metadata", {})
    migrated.setdefault("participants", [])
    migrated.setdefault("artifacts", [])
    migrated.setdefault("stages", [])
    migrated.setdefault("policies", {})
    for artifact in migrated.get("artifacts", []) or []:
        if isinstance(artifact, dict):
            artifact.setdefault("verify", True)
    for stage in migrated.get("stages", []) or []:
        if isinstance(stage, dict):
            stage.setdefault("strict_completion", False)
            stage.setdefault("require_output_verification", None)
            stage.setdefault("timeout_seconds", 0)
    policies = migrated.get("policies")
    if isinstance(policies, dict):
        policies.setdefault("single_active_writer", True)
        policies.setdefault("max_review_rounds", 5)
    return migrated


def canonical_protocol_document(value: object) -> ProtocolDefinitionDocumentRecord:
    if isinstance(value, ProtocolDefinitionDocumentRecord):
        return value
    return ProtocolDefinitionDocumentRecord.model_validate(migrate_protocol_document_data(value))


def protocol_definition_content_hash(document: ProtocolDefinitionDocumentRecord) -> str:
    payload = json.dumps(document.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_protocol_document(value: object) -> ProtocolValidationResultRecord:
    try:
        document = canonical_protocol_document(value)
    except Exception as exc:
        return ProtocolValidationResultRecord(ok=False, errors=[str(exc)])
    return ProtocolValidationResultRecord(
        ok=True,
        errors=[],
        normalized_document=document,
        content_hash=protocol_definition_content_hash(document),
    )


def protocol_participant_session_key(run_id: str, participant_key: str) -> str:
    return f"protocol:{str(run_id or '').strip()}:participant:{str(participant_key or '').strip()}"


def protocol_stage_instruction_contract(stage: ProtocolStageDefinitionRecord) -> str:
    if stage.stage_kind == "work":
        if stage.strict_completion:
            return (
                "Complete the work for this stage, update the required artifacts in the workspace, "
                "and end your final response with explicit protocol control lines:\n"
                "PROTOCOL_DECISION: completed\n"
                "PROTOCOL_SUMMARY: one short sentence describing the completed work"
            )
        return (
            "Complete the work for this stage, update the required artifacts in the workspace, "
            "and end your final response with a short `PROTOCOL_SUMMARY:` line."
        )
    allowed = ", ".join(stage.allowed_decisions())
    return (
        "You must end your final response with explicit protocol control lines:\n"
        f"PROTOCOL_DECISION: one of [{allowed}]\n"
        "PROTOCOL_SUMMARY: one short sentence explaining the decision\n"
        "Keep the rest of the response as the detailed review or acceptance rationale."
    )


def render_protocol_stage_prompt(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage: ProtocolStageDefinitionRecord,
    artifacts: list[ProtocolArtifactRecord],
    previous_feedback: str = "",
) -> str:
    participant = document.participant(stage.participant_key)
    artifact_lines: list[str] = []
    artifact_by_key = {item.artifact_key: item for item in artifacts}
    for artifact_key in dict.fromkeys([*stage.inputs, *stage.outputs]):
        definition = document.artifact(artifact_key)
        artifact = artifact_by_key.get(artifact_key)
        location = str(artifact.workspace_path or artifact.location or definition.path or "").strip()
        detail = f"{artifact_key}: {location}" if location else artifact_key
        artifact_lines.append(f"- {detail}")
    lines = [
        f"Protocol: {document.display_name or document.slug}",
        f"Run id: {run.protocol_run_id}",
        f"Stage: {stage.stage_key}",
        f"Participant: {participant.display_name or participant.participant_key}",
        f"Problem statement:\n{run.problem_statement.strip()}",
    ]
    if run.workspace_ref:
        lines.append(f"Workspace/project: {run.workspace_ref}")
    if artifact_lines:
        lines.append("Artifacts for this stage:\n" + "\n".join(artifact_lines))
    if participant.instructions:
        lines.append("Participant guidance:\n" + participant.instructions.strip())
    if stage.instructions:
        lines.append("Stage instructions:\n" + stage.instructions.strip())
    if previous_feedback.strip():
        lines.append("Feedback from the previous review stage:\n" + previous_feedback.strip())
    lines.append(protocol_stage_instruction_contract(stage))
    return "\n\n".join(part for part in lines if part.strip())


def parse_protocol_stage_decision(
    *,
    stage: ProtocolStageDefinitionRecord,
    full_text: str,
    summary_fallback: str = "",
) -> ProtocolStageDecisionRecord:
    text = str(full_text or "").strip()
    decision_match = _DECISION_RE.search(text)
    summary_match = _SUMMARY_RE.search(text)
    allowed = set(stage.allowed_decisions())
    if stage.stage_kind == "work":
        require_explicit_decision = len(allowed) > 1
        if decision_match is not None:
            decision = str(decision_match.group(1) or "").strip().lower()
        elif require_explicit_decision:
            raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_DECISION")
        else:
            decision = "completed"
        if decision not in allowed:
            raise ValueError(
                f"Stage {stage.stage_key} returned unsupported decision {decision!r}; expected one of {sorted(allowed)}"
            )
        if stage.strict_completion and summary_match is None:
            raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_SUMMARY")
        summary = (
            str(summary_match.group(1) or "").strip()
            if summary_match is not None
            else summary_fallback or _first_nonempty_line(text) or "Stage completed."
        )
        return ProtocolStageDecisionRecord(decision=decision, summary=summary)
    if decision_match is None:
        raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_DECISION")
    decision = str(decision_match.group(1) or "").strip().lower()
    if decision not in allowed:
        raise ValueError(
            f"Stage {stage.stage_key} returned unsupported decision {decision!r}; expected one of {sorted(allowed)}"
        )
    if summary_match is None:
        raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_SUMMARY")
    summary = str(summary_match.group(1) or "").strip()
    return ProtocolStageDecisionRecord(decision=decision, summary=summary)


def stage_target_for_decision(stage: ProtocolStageDefinitionRecord, decision: str) -> str:
    normalized = str(decision or "").strip().lower()
    if stage.stage_kind == "work" and not stage.transitions.as_dict():
        return ""
    target = stage.transition_target(normalized)
    if not target and stage.stage_kind == "work" and normalized == "completed":
        return ""
    return target


def is_protocol_terminal_target(target: str) -> bool:
    return str(target or "").strip() in _TERMINAL_STAGE_TARGETS


def default_protocol_document_slug(document: ProtocolDefinitionDocumentRecord) -> str:
    slug = document.slug
    if slug:
        return slug
    display = document.display_name.lower().strip().replace(" ", "-")
    return display or "protocol"


def protocol_stage_runtime_contract(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution_id: str,
    stage: ProtocolStageDefinitionRecord,
) -> ProtocolStageRuntimeContractRecord:
    outputs = [
        ProtocolStageArtifactContractRecord(
            artifact_key=artifact.artifact_key,
            artifact_kind=artifact.kind,
            path=artifact.path,
            verify=artifact.verify if stage.require_output_verification is not False else False,
        )
        for artifact in (document.artifact(artifact_key) for artifact_key in stage.outputs)
    ]
    require_verification = bool(
        stage.require_output_verification
        if stage.require_output_verification is not None
        else any(item.verify for item in outputs)
    )
    return ProtocolStageRuntimeContractRecord(
        protocol_run_id=run.protocol_run_id,
        protocol_definition_version_id=run.protocol_definition_version_id,
        protocol_stage_execution_id=stage_execution_id,
        participant_key=stage.participant_key,
        stage_key=stage.stage_key,
        stage_kind=stage.stage_kind,
        strict_completion=stage.strict_completion,
        require_output_verification=require_verification,
        output_artifacts=outputs,
    )


def protocol_stage_internal_context(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution_id: str,
    stage: ProtocolStageDefinitionRecord,
) -> dict[str, object]:
    contract = protocol_stage_runtime_contract(
        document=document,
        run=run,
        stage_execution_id=stage_execution_id,
        stage=stage,
    )
    return {
        "protocol_stage_contract": contract.model_dump(mode="json"),
    }


def protocol_dispatch_decision(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage: ProtocolStageDefinitionRecord,
    stage_executions: Sequence[ProtocolStageExecutionRecord],
    now: str,
    lease_owner: str,
    lease_ttl_seconds: int,
) -> ProtocolDispatchDecisionRecord:
    timeout_at = ""
    if stage.timeout_seconds > 0:
        timeout_at = _iso_plus_seconds(now, stage.timeout_seconds)
    if not stage.write_capable or not document.policies.single_active_writer:
        return ProtocolDispatchDecisionRecord(
            ok=True,
            timeout_at=timeout_at,
        )
    active_leases = [
        item
        for item in stage_executions
        if item.status == "running"
        and item.lease_owner
        and item.protocol_stage_execution_id != run.current_stage_execution_id
        and not _iso_expired(item.lease_expires_at, reference=now)
    ]
    if active_leases:
        active = active_leases[0]
        return ProtocolDispatchDecisionRecord(
            ok=False,
            error_code="LEASE_HELD",
            error_detail=f"Write lease held by stage execution {active.protocol_stage_execution_id}",
            timeout_at=timeout_at,
        )
    lease_expires_at = _iso_plus_seconds(now, lease_ttl_seconds) if lease_ttl_seconds > 0 else ""
    return ProtocolDispatchDecisionRecord(
        ok=True,
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
        timeout_at=timeout_at,
    )


def protocol_dispatch_blocked_decision(
    *,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    error_code: str,
    error_detail: str,
) -> ProtocolEngineDecisionRecord:
    retention_until = run.retention_until or protocol_retention_until(run.created_at or utcnow_iso())
    return ProtocolEngineDecisionRecord(
        run_status="blocked",
        stage_status="blocked",
        failure_code=str(error_code or "").strip().lower() or "lease_held",
        failure_detail=str(error_detail or "").strip() or "Protocol dispatch blocked.",
        transition_kind="blocked",
        transition_reason=str(error_detail or "").strip() or "Protocol dispatch blocked.",
        transition_error_code=str(error_code or "").strip().upper() or "LEASE_HELD",
        run_blocked_code=str(error_code or "").strip().lower() or "lease_held",
        run_blocked_detail=str(error_detail or "").strip() or "Protocol dispatch blocked.",
        participant_key=stage_execution.participant_key,
        retention_until=retention_until,
    )


def protocol_dispatch_resolution_failed_decision(
    *,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    selector: TargetSelector,
    error_detail: str,
) -> ProtocolEngineDecisionRecord:
    detail = str(error_detail or "").strip() or "Participant resolution failed."
    retention_until = run.retention_until or protocol_retention_until(run.created_at or utcnow_iso())
    return ProtocolEngineDecisionRecord(
        run_status="blocked",
        stage_status="blocked",
        failure_code="participant_resolution_failed",
        failure_detail=detail,
        transition_kind="blocked",
        transition_reason=detail,
        transition_error_code="PARTICIPANT_RESOLUTION_FAILED",
        run_blocked_code="participant_resolution_failed",
        run_blocked_detail=detail,
        participant_key=stage_execution.participant_key,
        participant_state="error",
        participant_resolution_outcome="error",
        participant_resolution_reason=detail,
        participant_selector_snapshot=RegistryJsonRecord.model_validate(selector.model_dump(mode="json")),
        transition_metadata=RegistryJsonRecord.model_validate({"selector": selector.model_dump(mode="json")}),
        retention_until=retention_until,
    )


def protocol_dispatch_started_decision(
    *,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    routed_task_id: str,
    timeout_at: str,
    lease_owner: str,
    lease_expires_at: str,
    selector: TargetSelector,
    resolved_agent_id: str,
    resolved_authority_ref: str,
    now: str,
) -> ProtocolEngineDecisionRecord:
    retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
    return ProtocolEngineDecisionRecord(
        run_status="running",
        stage_status="running",
        transition_kind="dispatch",
        transition_reason=f"Dispatched stage {stage_execution.stage_key}.",
        routed_task_id=str(routed_task_id or "").strip(),
        timeout_at=str(timeout_at or "").strip(),
        lease_owner=str(lease_owner or "").strip(),
        lease_expires_at=str(lease_expires_at or "").strip(),
        started_at=str(now or "").strip(),
        participant_key=stage_execution.participant_key,
        participant_state="running",
        participant_resolution_outcome="ok",
        participant_resolution_reason="",
        participant_resolved_agent_id=str(resolved_agent_id or "").strip(),
        participant_resolved_authority_ref=str(resolved_authority_ref or "").strip(),
        participant_selector_snapshot=RegistryJsonRecord.model_validate(selector.model_dump(mode="json")),
        transition_metadata=RegistryJsonRecord.model_validate(
            {
                "target_agent_id": str(resolved_agent_id or "").strip(),
                "routed_task_id": str(routed_task_id or "").strip(),
                "selector": selector.model_dump(mode="json"),
            }
        ),
        retention_until=retention_until,
    )


def evaluate_protocol_stage_timeout(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    now: str,
) -> ProtocolEngineDecisionRecord:
    stage = document.stage(stage_execution.stage_key)
    detail = f"Stage {stage.stage_key} exceeded timeout."
    retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
    return ProtocolEngineDecisionRecord(
        run_status="failed",
        stage_status="failed",
        failure_code="stage_timeout",
        failure_detail=detail,
        transition_kind="terminal",
        transition_reason=detail,
        transition_error_code="STAGE_TIMEOUT",
        terminal_status="failed",
        participant_key=stage_execution.participant_key,
        retention_until=retention_until,
    )


def evaluate_protocol_task_result(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    stage_executions: Sequence[ProtocolStageExecutionRecord],
    result: ProtocolStageTaskResultRecord,
) -> ProtocolEngineDecisionRecord:
    stage = document.stage(stage_execution.stage_key)
    if stage_execution.timeout_at and _iso_expired(stage_execution.timeout_at, reference=result.completed_at):
        return evaluate_protocol_stage_timeout(
            document=document,
            run=run,
            stage_execution=stage_execution,
            now=result.completed_at,
        )
    retention_until = run.retention_until or protocol_retention_until(run.created_at or result.completed_at)
    if result.status != "completed":
        detail = result.summary or result.status or "Stage failed"
        return ProtocolEngineDecisionRecord(
            run_status="failed",
            stage_status="failed",
            failure_code=result.status or "failed",
            failure_detail=detail,
            transition_kind="terminal",
            transition_reason=detail,
            transition_error_code=result.status.upper() if result.status else "TASK_FAILED",
            terminal_status="failed",
            retention_until=retention_until,
        )
    try:
        decision = parse_protocol_stage_decision(
            stage=stage,
            full_text=result.full_text,
            summary_fallback=result.summary,
        )
    except Exception as exc:
        detail = str(exc)
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status="blocked",
            failure_code="protocol_contract_invalid",
            failure_detail=detail,
            transition_kind="blocked",
            transition_reason=detail,
            transition_error_code="PROTOCOL_CONTRACT_INVALID",
            run_blocked_code="protocol_contract_invalid",
            run_blocked_detail=detail,
            retention_until=retention_until,
        )
    artifact_error = protocol_artifact_contract_error(
        document=document,
        stage=stage,
        observations=result.artifacts,
    )
    if artifact_error:
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status="blocked",
            decision=decision.decision,
            summary=decision.summary,
            failure_code=artifact_error[0],
            failure_detail=artifact_error[1],
            transition_kind="blocked",
            transition_reason=artifact_error[1],
            transition_error_code=artifact_error[0].upper(),
            run_blocked_code=artifact_error[0],
            run_blocked_detail=artifact_error[1],
            artifact_observations=list(result.artifacts),
            retention_until=retention_until,
        )
    if decision.decision == "revise":
        revise_count = 1 + sum(
            1
            for item in stage_executions
            if item.stage_key == stage.stage_key and item.status == "completed" and item.decision == "revise"
        )
        if revise_count > document.policies.max_review_rounds:
            detail = (
                f"Stage {stage.stage_key} exceeded max review rounds "
                f"({revise_count} > {document.policies.max_review_rounds})."
            )
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status="blocked",
                decision=decision.decision,
                summary=decision.summary,
                failure_code="max_review_rounds_exceeded",
                failure_detail=detail,
                transition_kind="blocked",
                transition_reason=detail,
                transition_error_code="MAX_REVIEW_ROUNDS_EXCEEDED",
                run_blocked_code="max_review_rounds_exceeded",
                run_blocked_detail=detail,
                artifact_observations=list(result.artifacts),
                retention_until=retention_until,
            )
    target = stage_target_for_decision(stage, decision.decision)
    if not target:
        detail = f"Stage {stage.stage_key} has no transition for {decision.decision}"
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status="blocked",
            decision=decision.decision,
            summary=decision.summary,
            failure_code="protocol_invalid_transition",
            failure_detail=detail,
            transition_kind="blocked",
            transition_reason=detail,
            transition_error_code="PROTOCOL_INVALID_TRANSITION",
            run_blocked_code="protocol_invalid_transition",
            run_blocked_detail=detail,
            artifact_observations=list(result.artifacts),
            retention_until=retention_until,
        )
    if is_protocol_terminal_target(target):
        terminal_status = {
            "__complete__": "completed",
            "__failed__": "failed",
            "__cancelled__": "cancelled",
        }[target]
        return ProtocolEngineDecisionRecord(
            run_status=terminal_status,
            stage_status="completed",
            decision=decision.decision,
            summary=decision.summary,
            transition_kind="terminal",
            transition_reason=decision.summary,
            terminal_status=terminal_status,
            artifact_observations=list(result.artifacts),
            retention_until=retention_until,
        )
    return ProtocolEngineDecisionRecord(
        run_status="running",
        stage_status="completed",
        decision=decision.decision,
        summary=decision.summary,
        transition_kind="advance",
        transition_reason=decision.summary,
        next_stage_key=target,
        create_next_execution=True,
        artifact_observations=list(result.artifacts),
        input_snapshot=RegistryJsonRecord.model_validate(
            {
                "previous_stage_key": stage.stage_key,
                "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                "decision": decision.decision,
                "decision_summary": decision.summary,
            }
        ),
        retention_until=retention_until,
    )


def evaluate_protocol_operator_action(
    *,
    document: ProtocolDefinitionDocumentRecord,
    run: ProtocolRunRecord,
    stage_execution: ProtocolStageExecutionRecord,
    stage_executions: Sequence[ProtocolStageExecutionRecord],
    action: ProtocolOperatorAction,
    reason: str,
    now: str,
) -> ProtocolEngineDecisionRecord:
    del stage_executions
    stage = document.stage(stage_execution.stage_key)
    summary = str(reason or "").strip() or f"Operator {action.replace('_', ' ')}."
    retention_until = run.retention_until or protocol_retention_until(run.created_at or now)
    if action == "cancel":
        return ProtocolEngineDecisionRecord(
            run_status="cancelled",
            stage_status="cancelled",
            summary=summary,
            transition_kind="terminal",
            transition_reason=summary,
            terminal_status="cancelled",
            retention_until=retention_until,
        )
    if action == "retry":
        if stage_execution.status not in {"blocked", "failed", "cancelled"}:
            detail = f"Stage {stage.stage_key} cannot be retried from status {stage_execution.status}."
            return ProtocolEngineDecisionRecord(
                run_status="blocked",
                stage_status=stage_execution.status,
                failure_code="invalid_retry_state",
                failure_detail=detail,
                transition_kind="blocked",
                transition_reason=detail,
                transition_error_code="INVALID_RETRY_STATE",
                run_blocked_code="invalid_retry_state",
                run_blocked_detail=detail,
                retention_until=retention_until,
            )
        return ProtocolEngineDecisionRecord(
            run_status="running",
            stage_status=stage_execution.status,
            summary=summary,
            transition_kind="retry",
            transition_reason=summary,
            next_stage_key=stage.stage_key,
            create_next_execution=True,
            repeat_current_stage=True,
            input_snapshot=RegistryJsonRecord.model_validate(
                {
                    "previous_stage_key": stage.stage_key,
                    "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                    "decision": "retry",
                    "decision_summary": summary,
                }
            ),
            retention_until=retention_until,
        )
    forced_decision = "accept" if action == "accept" else "revise"
    allowed = set(stage.allowed_decisions())
    if forced_decision not in allowed:
        detail = f"Stage {stage.stage_key} does not allow operator decision {forced_decision!r}."
        return ProtocolEngineDecisionRecord(
            run_status="blocked",
            stage_status=stage_execution.status,
            failure_code="invalid_operator_decision",
            failure_detail=detail,
            transition_kind="blocked",
            transition_reason=detail,
            transition_error_code="INVALID_OPERATOR_DECISION",
            run_blocked_code="invalid_operator_decision",
            run_blocked_detail=detail,
            retention_until=retention_until,
        )
    target = stage_target_for_decision(stage, forced_decision)
    if is_protocol_terminal_target(target):
        terminal_status = {
            "__complete__": "completed",
            "__failed__": "failed",
            "__cancelled__": "cancelled",
        }[target]
        return ProtocolEngineDecisionRecord(
            run_status=terminal_status,
            stage_status="completed",
            decision=forced_decision,
            summary=summary,
            transition_kind="terminal",
            transition_reason=summary,
            terminal_status=terminal_status,
            retention_until=retention_until,
        )
    return ProtocolEngineDecisionRecord(
        run_status="running",
        stage_status="completed",
        decision=forced_decision,
        summary=summary,
        transition_kind="advance",
        transition_reason=summary,
        next_stage_key=target,
        create_next_execution=True,
        input_snapshot=RegistryJsonRecord.model_validate(
            {
                "previous_stage_key": stage.stage_key,
                "previous_stage_execution_id": stage_execution.protocol_stage_execution_id,
                "decision": forced_decision,
                "decision_summary": summary,
            }
        ),
        retention_until=retention_until,
    )


def protocol_artifact_contract_error(
    *,
    document: ProtocolDefinitionDocumentRecord,
    stage: ProtocolStageDefinitionRecord,
    observations: Sequence[ProtocolArtifactObservationRecord],
) -> tuple[str, str] | None:
    if stage.require_output_verification is False:
        return None
    observed_by_key = {item.artifact_key: item for item in observations}
    for artifact_key in stage.outputs:
        artifact = document.artifact(artifact_key)
        verify_required = bool(stage.require_output_verification) if stage.require_output_verification is not None else artifact.verify
        if not verify_required:
            continue
        observed = observed_by_key.get(artifact_key)
        if observed is None or not observed.exists:
            return ("artifact_missing", f"Required artifact {artifact_key} was not produced.")
        if not str(observed.content_hash or "").strip():
            return ("artifact_integrity_failed", f"Required artifact {artifact_key} is missing a content hash.")
    return None


def software_engineering_protocol_document() -> ProtocolDefinitionDocumentRecord:
    return canonical_protocol_document(
        {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "metadata": {
                "slug": "software-engineering",
                "display_name": "Software Engineering",
                "description": "Plan, review, architect, implement, review, and accept a software delivery run.",
            },
            "participants": [
                {"participant_key": "planner", "display_name": "Planner", "required_skills": ["product-definition"]},
                {"participant_key": "plan_reviewer", "display_name": "Plan Reviewer", "required_skills": ["review"]},
                {"participant_key": "architect", "display_name": "Architect", "required_skills": ["architecture"]},
                {
                    "participant_key": "architecture_reviewer",
                    "display_name": "Architecture Reviewer",
                    "required_skills": ["review"],
                },
                {"participant_key": "implementer", "display_name": "Implementer", "required_skills": ["implementation"]},
                {
                    "participant_key": "implementation_reviewer",
                    "display_name": "Implementation Reviewer",
                    "required_skills": ["review"],
                },
                {"participant_key": "acceptance", "display_name": "Acceptance", "required_skills": ["review"]},
            ],
            "artifacts": [
                {
                    "artifact_key": "problem",
                    "kind": "workspace_file",
                    "path": "protocol/problem.md",
                    "description": "Problem statement and fixed constraints.",
                    "verify": True,
                },
                {
                    "artifact_key": "plan",
                    "kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "description": "Requirements, architecture, and implementation guidance.",
                    "verify": True,
                },
                {
                    "artifact_key": "status",
                    "kind": "workspace_file",
                    "path": "protocol/status.md",
                    "description": "Implementation progress and final outcome.",
                    "verify": True,
                },
            ],
            "stages": [
                {
                    "stage_key": "planning",
                    "display_name": "Planning",
                    "participant_key": "planner",
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["problem"],
                    "outputs": ["plan"],
                    "transitions": {"completed": "plan_review"},
                    "instructions": "Analyze the problem, identify requirements and constraints, and update protocol/plan.md.",
                },
                {
                    "stage_key": "plan_review",
                    "display_name": "Plan Review",
                    "participant_key": "plan_reviewer",
                    "stage_kind": "review",
                    "timeout_seconds": 1800,
                    "inputs": ["problem", "plan"],
                    "outputs": [],
                    "transitions": {"accept": "architecture", "revise": "planning", "fail": "__failed__"},
                    "instructions": (
                        "Review protocol/plan.md against the original problem statement and send it back only "
                        "if the plan is incomplete or incorrect."
                    ),
                },
                {
                    "stage_key": "architecture",
                    "display_name": "Architecture",
                    "participant_key": "architect",
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["problem", "plan"],
                    "outputs": ["plan"],
                    "transitions": {"completed": "architecture_review"},
                    "instructions": (
                        "Refine protocol/plan.md with architecture, APIs, data model, reliability, "
                        "security, logging, observability, and reuse guidance."
                    ),
                },
                {
                    "stage_key": "architecture_review",
                    "display_name": "Architecture Review",
                    "participant_key": "architecture_reviewer",
                    "stage_kind": "review",
                    "timeout_seconds": 1800,
                    "inputs": ["problem", "plan"],
                    "outputs": [],
                    "transitions": {"accept": "implementation", "revise": "architecture", "fail": "__failed__"},
                    "instructions": (
                        "Review the architecture sections thoroughly and reject only when the architecture is "
                        "not coherent, safe, or maintainable."
                    ),
                },
                {
                    "stage_key": "implementation",
                    "display_name": "Implementation",
                    "participant_key": "implementer",
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 3600,
                    "inputs": ["problem", "plan", "status"],
                    "outputs": ["status"],
                    "transitions": {"completed": "implementation_review"},
                    "instructions": (
                        "Implement the next coherent slice, update protocol/status.md, and keep the workspace "
                        "aligned with protocol/plan.md."
                    ),
                },
                {
                    "stage_key": "implementation_review",
                    "display_name": "Implementation Review",
                    "participant_key": "implementation_reviewer",
                    "stage_kind": "review",
                    "timeout_seconds": 1800,
                    "inputs": ["problem", "plan", "status"],
                    "outputs": [],
                    "transitions": {"accept": "acceptance", "revise": "implementation", "fail": "__failed__"},
                    "instructions": "Review the cumulative implementation, tests, and adherence to the plan before accepting.",
                },
                {
                    "stage_key": "acceptance",
                    "display_name": "Acceptance",
                    "participant_key": "acceptance",
                    "stage_kind": "acceptance",
                    "timeout_seconds": 1800,
                    "inputs": ["problem", "plan", "status"],
                    "outputs": [],
                    "transitions": {"accept": "__complete__", "revise": "implementation", "fail": "__failed__"},
                    "instructions": "Decide whether the run is done, should return to implementation, or must fail.",
                },
            ],
            "policies": {
                "single_active_writer": True,
                "max_review_rounds": 5,
            },
        }
    )


def builtin_protocol_documents() -> tuple[ProtocolDefinitionDocumentRecord, ...]:
    return (software_engineering_protocol_document(),)


def builtin_protocol_document(slug: str) -> ProtocolDefinitionDocumentRecord:
    normalized = str(slug or "").strip().lower()
    for document in builtin_protocol_documents():
        if default_protocol_document_slug(document) == normalized:
            return document
    raise KeyError(normalized)


def new_protocol_definition(
    *,
    slug: str,
    display_name: str,
    description: str = "",
    document: ProtocolDefinitionDocumentRecord,
    protocol_id: str,
    current_version_id: str = "",
    lifecycle_state: ProtocolLifecycleState = "draft",
    now: str | None = None,
    owner_org_id: str = PROTOCOL_DEFAULT_RUN_ORG_ID,
    visibility: ProtocolVisibility = PROTOCOL_DEFAULT_VISIBILITY,
    created_by: str = "",
    updated_by: str = "",
) -> ProtocolDefinitionRecord:
    ts = now or utcnow_iso()
    del document
    return ProtocolDefinitionRecord(
        protocol_id=protocol_id,
        slug=slug,
        display_name=display_name,
        description=description,
        lifecycle_state=lifecycle_state,
        current_version_id=current_version_id,
        owner_org_id=owner_org_id,
        visibility=visibility,
        created_by=created_by,
        updated_by=updated_by or created_by,
        created_at=ts,
        updated_at=ts,
    )


def _iso_plus_seconds(base: str, seconds: int) -> str:
    if seconds <= 0:
        return ""
    parsed = datetime.fromisoformat(base)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=seconds)).isoformat()


def _iso_expired(value: str, *, reference: str) -> bool:
    if not value:
        return False
    expiry = datetime.fromisoformat(value)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    ref = datetime.fromisoformat(reference)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return expiry <= ref
