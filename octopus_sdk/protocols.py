"""Shared protocol definition and run models plus stage progression helpers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, field_validator, model_validator

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel, TargetSelector, utcnow_iso

ProtocolLifecycleState = Literal["draft", "published", "archived"]
ProtocolRunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked"]
ProtocolStageKind = Literal["work", "review", "acceptance"]
ProtocolStageExecutionStatus = Literal["queued", "running", "completed", "failed", "cancelled", "blocked"]
ProtocolArtifactKind = Literal["workspace_file", "control_plane_text"]

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

    @field_validator("artifact_key", mode="before")
    @classmethod
    def _artifact_key(cls, value: object) -> str:
        return _normalize_key(value, field_name="artifact_key")

    @model_validator(mode="after")
    def _validate_shape(self) -> "ProtocolArtifactDefinitionRecord":
        if self.kind == "workspace_file" and not str(self.path or "").strip():
            raise ValueError("workspace_file artifacts require a path")
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
            str(key or "").strip()
            for key in self.transitions.as_dict().keys()
            if str(key or "").strip()
        ]
        if keys:
            return tuple(keys)
        if self.stage_kind == "work":
            return ("completed",)
        if self.stage_kind == "review":
            return ("accept", "revise", "fail")
        return ("accept", "revise", "fail")


class ProtocolPoliciesRecord(RegistryRecordModel):
    single_active_writer: bool = True
    max_review_rounds: int = Field(default=5, ge=1)


class ProtocolDefinitionDocumentRecord(RegistryRecordModel):
    metadata: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    participants: list[ProtocolParticipantDefinitionRecord] = Field(default_factory=list)
    artifacts: list[ProtocolArtifactDefinitionRecord] = Field(default_factory=list)
    stages: list[ProtocolStageDefinitionRecord] = Field(default_factory=list)
    policies: ProtocolPoliciesRecord = Field(default_factory=ProtocolPoliciesRecord)

    @model_validator(mode="after")
    def _validate_document(self) -> "ProtocolDefinitionDocumentRecord":
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
                if not str(decision or "").strip():
                    raise ValueError(f"stage {stage.stage_key} contains a blank transition decision")
                target_key = str(target or "").strip()
                if not target_key:
                    raise ValueError(f"stage {stage.stage_key} transition {decision} has no target")
                if target_key not in stage_set and target_key not in _TERMINAL_STAGE_TARGETS:
                    raise ValueError(f"stage {stage.stage_key} transition {decision} references unknown target {target_key}")
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


class ProtocolStageDecisionRecord(RegistryRecordModel):
    decision: str = ""
    summary: str = ""


def canonical_protocol_document(value: object) -> ProtocolDefinitionDocumentRecord:
    if isinstance(value, ProtocolDefinitionDocumentRecord):
        return value
    return ProtocolDefinitionDocumentRecord.model_validate(value)


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
    if stage.stage_kind == "work":
        summary = summary_fallback or _first_nonempty_line(text) or "Stage completed."
        return ProtocolStageDecisionRecord(decision="completed", summary=summary)
    match = _DECISION_RE.search(text)
    if match is None:
        raise ValueError(f"Stage {stage.stage_key} result is missing PROTOCOL_DECISION")
    decision = str(match.group(1) or "").strip().lower()
    allowed = set(stage.allowed_decisions())
    if decision not in allowed:
        raise ValueError(
            f"Stage {stage.stage_key} returned unsupported decision {decision!r}; expected one of {sorted(allowed)}"
        )
    summary_match = _SUMMARY_RE.search(text)
    summary = (
        str(summary_match.group(1) or "").strip()
        if summary_match is not None
        else summary_fallback or _first_nonempty_line(text) or decision
    )
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


def software_engineering_protocol_document() -> ProtocolDefinitionDocumentRecord:
    return canonical_protocol_document(
        {
            "metadata": {
                "slug": "software-engineering",
                "display_name": "Software Engineering",
                "description": "Plan, review, architect, implement, review, and accept a software delivery run.",
            },
            "participants": [
                {"participant_key": "planner", "display_name": "Planner", "required_skills": ["product-definition"]},
                {"participant_key": "plan_reviewer", "display_name": "Plan Reviewer", "required_skills": ["review"]},
                {"participant_key": "architect", "display_name": "Architect", "required_skills": ["architecture"]},
                {"participant_key": "architecture_reviewer", "display_name": "Architecture Reviewer", "required_skills": ["review"]},
                {"participant_key": "implementer", "display_name": "Implementer", "required_skills": ["implementation"]},
                {"participant_key": "implementation_reviewer", "display_name": "Implementation Reviewer", "required_skills": ["review"]},
                {"participant_key": "acceptance", "display_name": "Acceptance", "required_skills": ["review"]},
            ],
            "artifacts": [
                {
                    "artifact_key": "problem",
                    "kind": "workspace_file",
                    "path": "protocol/problem.md",
                    "description": "Problem statement and fixed constraints.",
                },
                {
                    "artifact_key": "plan",
                    "kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "description": "Requirements, architecture, and implementation guidance.",
                },
                {
                    "artifact_key": "status",
                    "kind": "workspace_file",
                    "path": "protocol/status.md",
                    "description": "Implementation progress and final outcome.",
                },
            ],
            "stages": [
                {
                    "stage_key": "planning",
                    "display_name": "Planning",
                    "participant_key": "planner",
                    "stage_kind": "work",
                    "write_capable": True,
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
                    "inputs": ["problem", "plan"],
                    "outputs": [],
                    "transitions": {"accept": "architecture", "revise": "planning", "fail": "__failed__"},
                    "instructions": "Review protocol/plan.md against the original problem statement and send it back only if the plan is incomplete or incorrect.",
                },
                {
                    "stage_key": "architecture",
                    "display_name": "Architecture",
                    "participant_key": "architect",
                    "stage_kind": "work",
                    "write_capable": True,
                    "inputs": ["problem", "plan"],
                    "outputs": ["plan"],
                    "transitions": {"completed": "architecture_review"},
                    "instructions": "Refine protocol/plan.md with architecture, APIs, data model, reliability, security, logging, observability, and reuse guidance.",
                },
                {
                    "stage_key": "architecture_review",
                    "display_name": "Architecture Review",
                    "participant_key": "architecture_reviewer",
                    "stage_kind": "review",
                    "inputs": ["problem", "plan"],
                    "outputs": [],
                    "transitions": {"accept": "implementation", "revise": "architecture", "fail": "__failed__"},
                    "instructions": "Review the architecture sections thoroughly and reject only when the architecture is not coherent, safe, or maintainable.",
                },
                {
                    "stage_key": "implementation",
                    "display_name": "Implementation",
                    "participant_key": "implementer",
                    "stage_kind": "work",
                    "write_capable": True,
                    "inputs": ["problem", "plan", "status"],
                    "outputs": ["status"],
                    "transitions": {"completed": "implementation_review"},
                    "instructions": "Implement the next coherent slice, update protocol/status.md, and keep the workspace aligned with protocol/plan.md.",
                },
                {
                    "stage_key": "implementation_review",
                    "display_name": "Implementation Review",
                    "participant_key": "implementation_reviewer",
                    "stage_kind": "review",
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


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        value = line.strip()
        if value and not value.startswith("PROTOCOL_"):
            return value
    return ""


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
) -> ProtocolDefinitionRecord:
    ts = now or utcnow_iso()
    return ProtocolDefinitionRecord(
        protocol_id=protocol_id,
        slug=slug,
        display_name=display_name,
        description=description,
        lifecycle_state=lifecycle_state,
        current_version_id=current_version_id,
        created_at=ts,
        updated_at=ts,
    )
