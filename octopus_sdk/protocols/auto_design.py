"""SDK-owned Auto Protocol authoring and revision helpers.

The implementation in this module deliberately produces normal protocol
documents. Registry and Telegram surfaces can render the summaries differently,
but generation, revision, validation, apply, publish, and run all converge on
the canonical protocol model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, field_validator

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel

from .documents import draft_protocol_document_data, validate_protocol_document
from .models import (
    PROTOCOL_SCHEMA_VERSION,
    ProtocolDefinitionDocumentRecord,
    ProtocolMutationRecord,
    ProtocolRunCreateRecord,
    ProtocolRunMutationRecord,
    ProtocolValidationResultRecord,
)

ProtocolAutoDesignMode = Literal["create", "revise"]
ProtocolAutoDesignSurface = Literal["registry", "telegram", "api"]
ProtocolAutoDesignStatus = Literal["draft", "ready", "blocked", "applied", "published", "running", "failed"]
ProtocolAutoDesignSeverity = Literal["info", "warning", "error"]

_AUTO_STAGE_BUDGET_SMALL_MAX = 7
_AUTO_STAGE_BUDGET_STANDARD_MAX = 12
_AUTO_STAGE_BUDGET_COMPLEX_MAX = 16
_AUTO_STAGE_HARD_CAP = 18
_AUTO_STANDARD_WORK_PACKAGE_BUDGET = 6
_AUTO_REVIEW_ROUND_MAX = 6
_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS = 1800
_AUTO_RUN_OBJECTIVE_MAX_CHARS = 1000
_AUTO_REVISION_HISTORY_MAX = 20
_AUTO_RUNTIME_OPEN_BEHAVIORS = {"runtime", "app", "service", "api", "playable"}
_AUTO_RUNTIME_WORDS = {
    "app",
    "application",
    "api",
    "backend",
    "browser",
    "dashboard",
    "frontend",
    "game",
    "html",
    "interface",
    "playable",
    "portal",
    "service",
    "server",
    "spa",
    "ui",
    "web",
    "website",
}
_AUTO_RUNTIME_PHRASES = (
    "api service",
    "back end",
    "browser based",
    "browser-runnable",
    "front end",
    "health endpoint",
    "operator console",
    "operator ui",
    "public api",
    "running system",
    "runnable artifact",
    "runnable product",
    "start command",
    "user interface",
    "user-facing api",
    "user-facing ui",
    "web app",
    "web application",
    "web browser",
)

AUTO_PROTOCOL_RUNTIME_MANIFEST_GUIDANCE = (
    "Runtime manifest contract: runnable primary artifacts must place octopus-runtime.json at the artifact package root "
    "and it must validate as ProtocolArtifactRuntimeManifestRecord. Use runtime_kind exactly one of static, node, python, "
    "java, binary, or process. For a Java/Maven service use runtime_kind 'java', not a descriptive phrase. For process-backed "
    "runtimes include start_command, ui_path, health_path, api_base_path, smoke_test steps, and endpoints as an array of objects. "
    "The package must be built and smoke-tested before final acceptance; start_command is only for launching the already prepared "
    "runtime and must not run dependency installation, build, test, package, or developer server commands such as mvn spring-boot:run. "
    "Each endpoint object uses label, path, endpoint_kind, method, and description; endpoint_kind must be one of ui, api, health, "
    "docs, or other, and every process-backed runtime must include at least one endpoint with endpoint_kind 'docs'. "
    "Example for Java: {\"runtime_kind\":\"java\",\"start_command\":\"java -jar target/risk-engine.jar\",\"ui_path\":\"/\","
    "\"health_path\":\"/health\",\"api_base_path\":\"/api\",\"endpoints\":[{\"label\":\"Operator UI\",\"path\":\"/\","
    "\"endpoint_kind\":\"ui\",\"method\":\"GET\",\"description\":\"Service-backed operator console\"},{\"label\":\"Health\","
    "\"path\":\"/health\",\"endpoint_kind\":\"health\",\"method\":\"GET\",\"description\":\"Runtime readiness\"},"
    "{\"label\":\"API docs\",\"path\":\"/api/docs\",\"endpoint_kind\":\"docs\",\"method\":\"GET\","
    "\"description\":\"Human-readable API documentation\"}],\"smoke_test\":[\"GET /health\",\"GET /\",\"GET /api/docs\"]}."
)


def _slugify(value: str, *, fallback: str = "auto-protocol") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = fallback
    if len(text) > 64:
        text = text[:64].rstrip("-") or fallback
    return text


def _snake(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _title_from_requirement(text: str) -> str:
    source = str(text or "").strip()
    if not source:
        return "Auto Protocol"
    first = re.split(r"[\n.!?]+", source, maxsplit=1)[0].strip()
    first = re.sub(r"\s+", " ", first)
    if len(first) > 80:
        first = first[:80].rsplit(" ", 1)[0].strip()
    return first[:1].upper() + first[1:] if first else "Auto Protocol"


def _sentence(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return ""
    return value if value[-1] in ".!?" else f"{value}."


_AUTO_CONTEXT_LABELS = (
    "current stage",
    "existing objective",
    "existing artifacts",
    "existing protocol objective",
    "original objective",
    "primary artifact expected path",
    "primary artifact",
    "protocol id",
    "protocol name",
    "requested improvement",
    "revision request",
    "run id",
    "run objective",
    "run status",
    "source objective",
    "user improvement request",
)
_AUTO_REVISION_LABELS = {"requested improvement", "revision request", "user improvement request"}
_AUTO_SOURCE_LABELS = {"existing objective", "existing protocol objective", "original objective", "run objective", "source objective"}
_AUTO_CONTEXT_NOISE_PREFIXES = {
    "bring the revised protocol up to the current octopus standard",
    "existing artifacts",
    "improve the existing protocol that produced this run",
    "use the prior run as context",
}
_AUTO_GENERIC_REQUIREMENTS = {
    "auto protocol",
    "auto-generated requirement-specific protocol",
    "create requested outcome",
    "create the requested outcome",
    "create the requested outcome.",
    "revise the selected protocol",
    "run the generated workflow",
}


def _text_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _bounded_text(value: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped or text[:max_chars].strip()


def _auto_context_lines(value: object) -> list[str]:
    text = str(value or "").replace("\r", "\n").strip()
    if not text:
        return []
    label_pattern = "|".join(re.escape(label) for label in sorted(_AUTO_CONTEXT_LABELS, key=len, reverse=True))
    text = re.sub(rf"(?i)(?<!^)\b({label_pattern})\s*:", r"\n\1:", text)
    return [re.sub(r"^\s*[-*]\s*", "", line).strip() for line in text.splitlines()]


def _labeled_auto_context_values(value: object, labels: set[str]) -> list[str]:
    values: list[str] = []
    for line in _auto_context_lines(value):
        if ":" not in line:
            continue
        raw_label, payload = line.split(":", 1)
        label = _text_key(raw_label)
        if label in labels and payload.strip():
            values.append(payload.strip())
    return values


def _dedupe_text_items(values: Sequence[object], *, max_items: int = 20, max_chars: int = 1000) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_auto_protocol_context_text(value, max_chars=max_chars)
        key = _text_key(text)
        if not text or key in seen or key in _AUTO_GENERIC_REQUIREMENTS:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= max_items:
            break
    return items


def _compact_auto_protocol_context_text(value: object, *, max_chars: int = _AUTO_REQUIREMENT_CONTEXT_MAX_CHARS) -> str:
    pieces: list[str] = []
    seen: set[str] = set()
    for line in _auto_context_lines(value):
        if not line:
            continue
        if ":" in line:
            raw_label, payload = line.split(":", 1)
            label = _text_key(raw_label)
            if label in _AUTO_REVISION_LABELS or label in _AUTO_CONTEXT_LABELS:
                continue
            line = payload.strip() if label in _AUTO_SOURCE_LABELS else line
        key = _text_key(line)
        if not key or key in _AUTO_GENERIC_REQUIREMENTS:
            continue
        if any(key.startswith(prefix) for prefix in _AUTO_CONTEXT_NOISE_PREFIXES):
            continue
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", line):
            text = re.sub(r"\s+", " ", chunk).strip()
            chunk_key = _text_key(text)
            if not text or chunk_key in seen or chunk_key in _AUTO_GENERIC_REQUIREMENTS:
                continue
            if any(chunk_key.startswith(prefix) for prefix in _AUTO_CONTEXT_NOISE_PREFIXES):
                continue
            seen.add(chunk_key)
            pieces.append(text)
    return _bounded_text(" ".join(pieces), max_chars=max_chars)


def _source_requirement_from_auto_metadata(metadata: Mapping[str, object], auto_meta: Mapping[str, object]) -> str:
    source_labeled_values: list[str] = []
    for value in [auto_meta.get("requirement"), metadata.get("description")]:
        source_labeled_values.extend(_labeled_auto_context_values(value, _AUTO_SOURCE_LABELS))
    candidates = [
        *source_labeled_values,
        auto_meta.get("requirement"),
        metadata.get("description"),
        metadata.get("display_name") or metadata.get("slug"),
    ]
    base_candidates = [
        re.sub(
            r"(?i)[,;]?\s+(with this requested improvement:|including the requested improvement to)\s+.*$",
            "",
            _compact_auto_protocol_context_text(candidate, max_chars=_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS),
        ).strip()
        for candidate in candidates
    ]
    for candidate in _dedupe_text_items(base_candidates, max_items=1, max_chars=_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS):
        return candidate
    return ""


def _revision_request_from_text(value: object) -> str:
    labeled = _labeled_auto_context_values(value, _AUTO_REVISION_LABELS)
    if labeled:
        values = _dedupe_text_items(labeled, max_items=1, max_chars=_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS)
        if values:
            return values[0]
    return _compact_auto_protocol_context_text(value, max_chars=_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS)


def _model_requirement_summary(model_response: ProtocolAutoDesignModelResponseRecord | None) -> str:
    if model_response is None:
        return ""
    summary = _compact_auto_protocol_context_text(
        model_response.requirement_summary,
        max_chars=_AUTO_RUN_OBJECTIVE_MAX_CHARS,
    )
    return "" if _text_key(summary) in _AUTO_GENERIC_REQUIREMENTS else summary


def _revision_planner_requirement(source_requirement: str, change_request: str) -> str:
    parts = []
    if source_requirement:
        parts.append(f"Existing protocol objective: {source_requirement}")
    if change_request:
        parts.append(f"Requested improvement: {change_request}")
    return "\n".join(parts) or change_request or source_requirement or "Revise the selected protocol."


def _revision_run_objective(
    source_requirement: str,
    change_request: str,
    model_response: ProtocolAutoDesignModelResponseRecord | None,
) -> str:
    summary = _model_requirement_summary(model_response)
    if summary:
        return _sentence(_bounded_text(summary, max_chars=_AUTO_RUN_OBJECTIVE_MAX_CHARS))
    if source_requirement and change_request:
        change_fragment = change_request[:1].lower() + change_request[1:] if change_request else ""
        return _sentence(_bounded_text(
            f"{source_requirement.rstrip('.!?')}, including the requested improvement to {change_fragment}",
            max_chars=_AUTO_RUN_OBJECTIVE_MAX_CHARS,
        ))
    return _sentence(_bounded_text(change_request or source_requirement, max_chars=_AUTO_RUN_OBJECTIVE_MAX_CHARS))


def _run_objective_sentence(value: object) -> str:
    return _sentence(_compact_auto_protocol_context_text(value, max_chars=_AUTO_RUN_OBJECTIVE_MAX_CHARS))


def _run_profile_with_problem_statement(
    profile: ProtocolAutoDesignRunProfileRecord,
    problem_statement: str,
) -> ProtocolAutoDesignRunProfileRecord:
    objective = _run_objective_sentence(problem_statement) or profile.problem_statement
    fields: list[dict[str, object]] = []
    found = False
    for field in profile.run_inputs:
        item = dict(field)
        if str(item.get("key") or "").strip() == "problem_statement":
            item["default_value"] = objective
            item["required"] = True
            found = True
        fields.append(item)
    if not found:
        fields.insert(0, {
            "key": "problem_statement",
            "label": "Run objective",
            "kind": "textarea",
            "required": True,
            "default_value": objective,
            "help": "The run-specific outcome this protocol should accomplish.",
        })
    return profile.model_copy(update={
        "problem_statement": objective,
        "run_inputs": fields,
    })


def _normalized_words(*values: object) -> str:
    return " ".join(str(value or "").lower() for value in values if str(value or "").strip())


def auto_protocol_runtime_expected_from_text(*values: object) -> bool:
    """Return whether an Auto Protocol outcome should be exposed as a runtime."""
    text = _normalized_words(*values)
    if not text:
        return False
    if "octopus-runtime.json" in text or "runtime manifest" in text:
        return True
    if any(phrase in text for phrase in _AUTO_RUNTIME_PHRASES):
        return True
    words = {
        token
        for token in re.split(r"[^a-z0-9]+", text)
        if token
    }
    if words & _AUTO_RUNTIME_WORDS:
        return True
    if "engine" in words and words & {"api", "backend", "service", "server", "ui", "web"}:
        return True
    return False


def _dict(value: object) -> dict[str, object]:
    if isinstance(value, RegistryJsonRecord):
        return value.as_dict()
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _agent_label(agent: Mapping[str, object]) -> str:
    return str(
        agent.get("display_name")
        or agent.get("slug")
        or agent.get("agent_id")
        or ""
    ).strip()


def _agent_skills(agent: Mapping[str, object]) -> set[str]:
    raw = agent.get("routing_skills", agent.get("skills_json", []))
    return {
        str(item or "").strip().lower()
        for item in _list(raw)
        if str(item or "").strip()
    }


def _selector_for_role(
    role_key: str,
    role_label: str,
    available_agents: Sequence[Mapping[str, object]],
    available_skills: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], str]:
    normalized_role = _slugify(f"{role_key} {role_label}", fallback=role_key)
    skill_names = {
        str(item.get("skill_name") or item.get("name") or item.get("slug") or "").strip().lower()
        for item in available_skills
        if str(item.get("skill_name") or item.get("name") or item.get("slug") or "").strip()
    }
    role_tokens = {
        token for token in re.split(r"[^a-z0-9]+", normalized_role)
        if token and token not in {"agent", "reviewer", "specialist", "developer"}
    }
    for agent in available_agents:
        agent_id = str(agent.get("agent_id") or "").strip()
        if not agent_id:
            continue
        label = _agent_label(agent).lower()
        skills = _agent_skills(agent)
        if role_tokens and (role_tokens & skills or any(token in label for token in role_tokens)):
            return {"kind": "agent", "value": agent_id}, f"Matched {_agent_label(agent)} to {role_label}."
    for skill in sorted(skill_names):
        skill_tokens = set(re.split(r"[^a-z0-9]+", skill))
        if role_tokens & skill_tokens:
            return {"kind": "skill", "value": skill}, f"Matched routing skill {skill} to {role_label}."
    first_agent = next((agent for agent in available_agents if str(agent.get("agent_id") or "").strip()), None)
    if first_agent is not None:
        return {"kind": "agent", "value": str(first_agent.get("agent_id") or "").strip()}, (
            f"No specific match for {role_label}; assigned the first connected agent."
        )
    return {"kind": "skill", "value": normalized_role}, (
        f"No connected agent was available for {role_label}; left a skill-based assignment intent."
    )


class ProtocolAutoDesignWarningRecord(RegistryRecordModel):
    code: str = ""
    message: str = ""
    severity: ProtocolAutoDesignSeverity = "warning"
    section: str = ""
    action: str = ""


class ProtocolAutoDesignRolePlanRecord(RegistryRecordModel):
    role_key: str = ""
    display_name: str = ""
    responsibility: str = ""
    selector: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    assignment_note: str = ""


class ProtocolAutoDesignArtifactPlanRecord(RegistryRecordModel):
    artifact_key: str = ""
    display_name: str = ""
    description: str = ""
    path: str = ""


class ProtocolAutoDesignPrimaryArtifactRecord(RegistryRecordModel):
    artifact_key: str = ""
    display_name: str = ""
    produced_by_stage_key: str = ""
    artifact_kind: str = "workspace_file"
    expected_path: str = ""
    open_behavior: str = "browse"
    evidence_requirements: list[str] = Field(default_factory=list)
    supporting_artifact_keys: list[str] = Field(default_factory=list)


class ProtocolAutoDesignReviewPolicyRecord(RegistryRecordModel):
    stance: str = "adversarial"
    max_review_rounds: int = 3
    stage_hard_cap: int = _AUTO_STAGE_HARD_CAP
    stage_budget_label: str = "standard"
    stage_count_rationale: str = ""


class ProtocolAutoDesignWorkPackageRecord(RegistryRecordModel):
    package_key: str = ""
    display_name: str = ""
    rationale: str = ""
    role_key: str = ""
    role_display_name: str = ""
    role_responsibility: str = ""
    required_skills: list[str] = Field(default_factory=list)
    purpose: str = ""
    quality_bar: str = ""
    artifact_key: str = ""
    artifact_display_name: str = ""
    artifact_description: str = ""
    artifact_path: str = ""
    dependencies: list[str] = Field(default_factory=list)
    review_role_key: str = ""
    review_display_name: str = ""
    review_responsibility: str = ""
    review_artifact_key: str = ""
    review_artifact_display_name: str = ""
    review_artifact_description: str = ""
    review_artifact_path: str = ""
    review_rubric: str = ""


class ProtocolAutoDesignStagePlanRecord(RegistryRecordModel):
    stage_key: str = ""
    display_name: str = ""
    stage_kind: str = "work"
    role_key: str = ""
    purpose: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    review_of_stage_key: str = ""


class ProtocolAutoDesignRunProfileRecord(RegistryRecordModel):
    problem_statement: str = ""
    context: str = ""
    constraints: str = ""
    acceptance_criteria: str = ""
    workspace_ref: str = ""
    run_inputs: list[dict[str, object]] = Field(default_factory=list)


class ProtocolAutoDesignAnalysisRecord(RegistryRecordModel):
    domain: str = "general"
    complexity: str = "standard"
    goal: str = ""
    focus: str = ""
    requirement_terms: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    work_packages: list[ProtocolAutoDesignWorkPackageRecord] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)


class ProtocolAutoDesignPlanRecord(RegistryRecordModel):
    protocol_name: str = ""
    protocol_slug: str = ""
    description: str = ""
    roles: list[ProtocolAutoDesignRolePlanRecord] = Field(default_factory=list)
    artifacts: list[ProtocolAutoDesignArtifactPlanRecord] = Field(default_factory=list)
    stages: list[ProtocolAutoDesignStagePlanRecord] = Field(default_factory=list)
    run_profile: ProtocolAutoDesignRunProfileRecord = Field(default_factory=ProtocolAutoDesignRunProfileRecord)
    primary_artifact: ProtocolAutoDesignPrimaryArtifactRecord = Field(default_factory=ProtocolAutoDesignPrimaryArtifactRecord)
    review_policy: ProtocolAutoDesignReviewPolicyRecord = Field(default_factory=ProtocolAutoDesignReviewPolicyRecord)


class ProtocolAutoDesignModelRequestRecord(RegistryRecordModel):
    mode: ProtocolAutoDesignMode = "create"
    requirement_text: str = ""
    constraints_text: str = ""
    source_document: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    available_agents: list[RegistryJsonRecord] = Field(default_factory=list)
    available_skills: list[RegistryJsonRecord] = Field(default_factory=list)
    workspace_ref: str = ""
    actor_ref: str = ""
    chat_ref: str = ""

    @field_validator("available_agents", "available_skills", mode="before")
    @classmethod
    def _json_list(cls, value: object) -> list[RegistryJsonRecord]:
        return [RegistryJsonRecord.model_validate(_dict(item)) for item in _list(value)]


class ProtocolAutoDesignModelResponseRecord(RegistryRecordModel):
    requirement_summary: str = ""
    domain: str = "requirement-specific"
    risk_assessment: str = ""
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    work_packages: list[ProtocolAutoDesignWorkPackageRecord] = Field(default_factory=list)
    roles: list[ProtocolAutoDesignRolePlanRecord] = Field(default_factory=list)
    artifacts: list[ProtocolAutoDesignArtifactPlanRecord] = Field(default_factory=list)
    primary_artifact: ProtocolAutoDesignPrimaryArtifactRecord = Field(default_factory=ProtocolAutoDesignPrimaryArtifactRecord)
    review_policy: ProtocolAutoDesignReviewPolicyRecord = Field(default_factory=ProtocolAutoDesignReviewPolicyRecord)
    run_inputs: list[dict[str, object]] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    warnings: list[ProtocolAutoDesignWarningRecord] = Field(default_factory=list)
    planner_ref: str = ""

    @field_validator("warnings", mode="before")
    @classmethod
    def _warning_list(cls, value: object) -> list[object]:
        normalized: list[object] = []
        for index, item in enumerate(_list(value)):
            if isinstance(item, str):
                message = item.strip()
                if message:
                    normalized.append({
                        "code": f"planner.warning_{index + 1}",
                        "message": message,
                        "severity": "warning",
                        "section": "planner",
                        "action": "review_generated_protocol",
                    })
                continue
            normalized.append(item)
        return normalized


class ProtocolAutoDesignEventSummaryRecord(RegistryRecordModel):
    event_kind: str = ""
    session_status: str = ""
    target_protocol_id: str = ""
    source_protocol_id: str = ""
    run_id: str = ""
    warning_codes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    unresolved_count: int = 0
    stage_count: int = 0
    package_count: int = 0
    primary_artifact_key: str = ""
    change_summary: list[str] = Field(default_factory=list)
    actor_ref: str = ""
    created_at: str = ""


class ProtocolAutoDesignChangeSummaryRecord(RegistryRecordModel):
    summary: str = ""
    changed_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProtocolAutoDesignRequestRecord(RegistryRecordModel):
    mode: ProtocolAutoDesignMode = "create"
    surface: ProtocolAutoDesignSurface = "api"
    requirement_text: str = ""
    constraints_text: str = ""
    target_protocol_id: str = ""
    target_version_id: str = ""
    target_draft_revision: int = 0
    source_document: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    available_agents: list[RegistryJsonRecord] = Field(default_factory=list)
    available_skills: list[RegistryJsonRecord] = Field(default_factory=list)
    workspace_ref: str = ""
    preferred_design_agent_id: str = ""
    actor_ref: str = ""
    chat_ref: str = ""
    idempotency_key: str = ""
    model_response: ProtocolAutoDesignModelResponseRecord | None = None

    @field_validator("available_agents", "available_skills", mode="before")
    @classmethod
    def _json_list(cls, value: object) -> list[RegistryJsonRecord]:
        return [RegistryJsonRecord.model_validate(_dict(item)) for item in _list(value)]


class ProtocolAutoDesignSessionRecord(RegistryRecordModel):
    session_id: str = ""
    status: ProtocolAutoDesignStatus = "draft"
    mode: ProtocolAutoDesignMode = "create"
    surface: ProtocolAutoDesignSurface = "api"
    actor_ref: str = ""
    chat_ref: str = ""
    source_protocol_id: str = ""
    source_version_id: str = ""
    source_draft_revision: int = 0
    target_protocol_id: str = ""
    target_draft_revision: int = 0
    requirement_text: str = ""
    constraints_text: str = ""
    model_response: ProtocolAutoDesignModelResponseRecord | None = None
    analysis: ProtocolAutoDesignAnalysisRecord = Field(default_factory=ProtocolAutoDesignAnalysisRecord)
    plan: ProtocolAutoDesignPlanRecord = Field(default_factory=ProtocolAutoDesignPlanRecord)
    draft_definition_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    run_profile: ProtocolAutoDesignRunProfileRecord = Field(default_factory=ProtocolAutoDesignRunProfileRecord)
    validation: ProtocolValidationResultRecord = Field(default_factory=ProtocolValidationResultRecord)
    warnings: list[ProtocolAutoDesignWarningRecord] = Field(default_factory=list)
    unresolved_decisions: list[ProtocolAutoDesignWarningRecord] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
    event_summary: ProtocolAutoDesignEventSummaryRecord = Field(default_factory=ProtocolAutoDesignEventSummaryRecord)
    applied_protocol: ProtocolMutationRecord | None = None
    run_result: ProtocolRunMutationRecord | None = None
    created_at: str = ""
    updated_at: str = ""


class ProtocolAutoDesignRenderCardRecord(RegistryRecordModel):
    title: str = ""
    body: str = ""
    facts: list[dict[str, str]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


_REQUIREMENT_STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "another",
    "around",
    "because",
    "before",
    "being",
    "between",
    "build",
    "create",
    "could",
    "deliver",
    "design",
    "does",
    "done",
    "each",
    "from",
    "give",
    "have",
    "into",
    "make",
    "more",
    "most",
    "need",
    "needs",
    "only",
    "other",
    "outcome",
    "over",
    "perhaps",
    "proper",
    "prototype",
    "really",
    "should",
    "some",
    "start",
    "that",
    "their",
    "there",
    "these",
    "thing",
    "this",
    "through",
    "using",
    "want",
    "where",
    "which",
    "while",
    "with",
    "work",
    "works",
    "would",
}


def _requirement_terms(*values: object, limit: int = 18) -> list[str]:
    text = _normalized_words(*values)
    seen: set[str] = set()
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text):
        normalized = token.strip("-")
        if len(normalized) < 4 or normalized in _REQUIREMENT_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= limit:
            break
    return terms


def _requirement_phrases(text: str, *, limit: int = 6) -> list[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if not cleaned:
        return []
    parts = [
        part.strip(" .;:-")
        for part in re.split(r"[\n.;]+|\s+-\s+", cleaned)
        if part.strip(" .;:-")
    ]
    phrases: list[str] = []
    for part in parts:
        if len(part) > 140:
            part = part[:140].rsplit(" ", 1)[0].strip()
        if part and part not in phrases:
            phrases.append(part)
        if len(phrases) >= limit:
            break
    return phrases


def _has_any(text: str, tokens: Sequence[str]) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", text) for token in tokens)


def _analysis_skills(text: str) -> list[str]:
    """Infer workflow skills without selecting a closed use-case template."""
    skills = ["requirements planning", "implementation", "verification", "acceptance evidence"]
    signals: list[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]]] = [
        (
            "technical architecture",
            (
                "architecture",
                "library",
                "libraries",
                "framework",
                "runtime",
                "integration",
                "api",
                "web",
                "deploy",
            ),
            (
                ("architecture", "runtime", "integration", "api"),
                ("library", "libraries", "framework", "deploy", "web"),
            ),
        ),
        (
            "domain grounding",
            (
                "accurate",
                "factual",
                "research",
                "source",
                "sources",
                "evidence",
                "audit",
                "regulated",
                "compliance",
                "history",
                "historical",
                "legal",
                "medical",
                "financial",
            ),
            (
                ("accurate", "factual", "research", "sources", "evidence", "audit"),
                ("regulated", "compliance", "legal", "medical", "financial", "historical"),
            ),
        ),
        (
            "experience design",
            (
                "user",
                "users",
                "human",
                "usable",
                "readable",
                "intuitive",
                "beautiful",
                "polished",
                "responsive",
                "controls",
                "guide",
                "guided",
                "guidance",
                "interaction",
                "interactive",
                "workflow",
                "dashboard",
                "dashboards",
                "explanation",
                "explanations",
                "ux",
                "ui",
            ),
            (
                ("user", "users", "human", "usable", "readable", "intuitive", "polished"),
                ("responsive", "controls", "interaction", "interactive", "dashboard", "ux", "ui"),
            ),
        ),
        (
            "supporting asset planning",
            (
                "asset",
                "assets",
                "visual",
                "image",
                "images",
                "audio",
                "sound",
                "content",
                "background",
                "graphic",
                "animation",
                "animated",
                "chart",
                "charts",
                "graph",
                "graphs",
            ),
            (
                ("asset", "assets", "visual", "image", "images", "audio", "sound", "graphic"),
                ("background", "animation", "animated", "chart", "charts", "graph", "graphs"),
            ),
        ),
        (
            "data and input modeling",
            ("data", "dataset", "records", "metrics", "analysis", "reporting", "loading", "dimensions", "drill"),
            (
                ("dataset", "records", "metrics", "reporting", "loading", "drill"),
                ("data", "analysis", "dimensions"),
            ),
        ),
        (
            "safety and risk review",
            ("safe", "safety", "secure", "security", "risk", "threat", "abuse", "privacy"),
            (
                ("safe", "safety", "secure", "security", "risk", "threat", "abuse", "privacy"),
            ),
        ),
    ]
    for skill, tokens, groups in signals:
        group_hits = sum(1 for group in groups if _has_any(text, group))
        single_strong_hit = bool(tokens) and _has_any(text, tokens) and len(str(text or "")) > 260
        if (group_hits >= 1 and (len(groups) == 1 or group_hits >= 2 or single_strong_hit)) and skill not in skills:
            skills.append(skill)
    return skills


def _is_complex_requirement(text: str, skills: Sequence[str], coverage_terms: Sequence[str]) -> bool:
    non_baseline = {
        skill
        for skill in skills
        if skill not in {"requirements planning", "implementation", "verification", "acceptance evidence"}
    }
    return len(non_baseline) >= 2 or len(str(text or "")) > 420 or len(coverage_terms) >= 10


def _production_dimensions(
    text: str,
    skills: Sequence[str],
    coverage_terms: Sequence[str],
) -> list[str]:
    """Infer reusable production slices from required capabilities, not domains."""
    normalized = _normalized_words(text, *coverage_terms)
    inferred = set(skills)
    dimensions: list[str] = []

    def add(dimension: str) -> None:
        if dimension not in dimensions:
            dimensions.append(dimension)

    if _is_complex_requirement(normalized, skills, coverage_terms) or "technical architecture" in inferred:
        add("production_foundation")
    if "data and input modeling" in inferred:
        add("data_behavior_layer")
    if "experience design" in inferred and _has_any(
        normalized,
        (
            "interactive",
            "interaction",
            "controls",
            "workflow",
            "navigation",
            "drill",
            "explore",
            "playable",
            "simulate",
            "motion",
            "animation",
            "animated",
        ),
    ):
        add("interaction_layer")
    if "supporting asset planning" in inferred and _has_any(
        normalized,
        (
            "visual",
            "visuals",
            "graphic",
            "graphics",
            "image",
            "images",
            "background",
            "backgrounds",
            "animation",
            "animated",
            "chart",
            "charts",
            "graph",
            "graphs",
            "sound",
            "audio",
        ),
    ):
        add("visual_media_layer")
    if _has_any(
        normalized,
        (
            "multiple",
            "varied",
            "varying",
            "variation",
            "variations",
            "scenario",
            "scenarios",
            "examples",
            "segments",
            "dimensions",
            "levels",
            "characters",
            "modes",
            "states",
        ),
    ):
        add("content_variation_layer")
    if "domain grounding" in inferred:
        add("domain_content_layer")
    return dimensions


def _work_package(
    package_key: str,
    display_name: str,
    role_key: str,
    role_display_name: str,
    role_responsibility: str,
    purpose: str,
    quality_bar: str,
    artifact_key: str,
    artifact_display_name: str,
    artifact_description: str,
    *,
    dependencies: Sequence[str] = (),
    review_role_key: str = "",
    review_display_name: str = "",
    review_responsibility: str = "",
    review_rubric: str = "",
    artifact_path: str = "",
    review_artifact_key: str = "",
    review_artifact_display_name: str = "",
    review_artifact_description: str = "",
    review_artifact_path: str = "",
    rationale: str = "",
    required_skills: Sequence[str] = (),
) -> ProtocolAutoDesignWorkPackageRecord:
    review_key = review_role_key or f"{package_key}_reviewer"
    review_label = review_display_name or f"{display_name} Reviewer"
    review_artifact = review_artifact_key or f"{artifact_key}_review"
    return ProtocolAutoDesignWorkPackageRecord(
        package_key=package_key,
        display_name=display_name,
        rationale=rationale or f"{display_name} is required to satisfy and verify the requested outcome.",
        role_key=role_key,
        role_display_name=role_display_name,
        role_responsibility=role_responsibility,
        required_skills=list(required_skills),
        purpose=purpose,
        quality_bar=quality_bar,
        artifact_key=artifact_key,
        artifact_display_name=artifact_display_name,
        artifact_description=artifact_description,
        artifact_path=artifact_path or _auto_artifact_path(artifact_key),
        dependencies=list(dependencies),
        review_role_key=review_key,
        review_display_name=review_label,
        review_responsibility=(
            review_responsibility
            or f"Critically inspect {artifact_display_name}, compare it to the requirement and rubric, and send it back when quality or evidence is weak."
        ),
        review_artifact_key=review_artifact,
        review_artifact_display_name=review_artifact_display_name or f"{artifact_display_name} Review",
        review_artifact_description=(
            review_artifact_description
            or f"Critical review notes, decision rationale, gaps, and revision requests for {artifact_display_name}."
        ),
        review_artifact_path=review_artifact_path or _auto_artifact_path(review_artifact),
        review_rubric=(
            review_rubric
            or f"Inspect {artifact_display_name} against the original requirement, this stage rubric, and downstream usefulness. Choose revise when any material gap remains."
        ),
    )


_AUTO_RUN_ARTIFACT_ROOT = "protocol/auto/{protocol_run_id}"


def _auto_artifact_path(name: str, *, extension: str = ".md") -> str:
    return f"{_AUTO_RUN_ARTIFACT_ROOT}/{_slugify(name)}{extension}"


def _infer_work_packages(
    requirement_text: str,
    constraints_text: str,
    skills: Sequence[str],
    coverage_terms: Sequence[str],
) -> list[ProtocolAutoDesignWorkPackageRecord]:
    """Create a requirement decomposition from workflow primitives, not use-case templates."""
    request_scope = _sentence(requirement_text) or "Create the requested outcome."
    terms = ", ".join(list(coverage_terms)[:14]) or "the explicit user requirement"
    full_text = _normalized_words(requirement_text, constraints_text)
    inferred = set(skills)
    packages: list[ProtocolAutoDesignWorkPackageRecord] = [
        _work_package(
            "requirements",
            "Requirement Coverage",
            "planner",
            "Workflow Planner",
            "Turn the user request into explicit scope, assumptions, dependencies, acceptance criteria, and work-package coverage.",
            (
                f"Create a requirements coverage plan for: {request_scope} "
                f"Explicitly map these requirement terms to artifacts, stages, and acceptance criteria: {terms}."
            ),
            "Every material request is either covered by a stage/artifact, recorded as an assumption, or called out as a gap.",
            "requirements_plan",
            "Requirements Coverage Plan",
            "Goal, constraints, assumptions, work packages, deliverables, acceptance criteria, and coverage terms.",
            review_role_key="requirements_reviewer",
            review_display_name="Requirement Coverage Reviewer",
            review_rubric=(
                "Reject shallow planning. Verify that every material user request is mapped to a concrete work package, artifact, acceptance criterion, or explicit assumption. "
                "Choose revise if scope is vague, quality bars are missing, or downstream stages cannot act on the plan."
            ),
        ),
    ]
    dependency_artifacts = ["requirements_plan"]

    def add(package: ProtocolAutoDesignWorkPackageRecord) -> None:
        packages.append(package)
        dependency_artifacts.append(package.artifact_key)

    if "technical architecture" in inferred:
        add(_work_package(
            "technical_approach",
            "Technical Approach",
            "technical_architect",
            "Technical Architect",
            "Choose the implementation approach, platform assumptions, libraries, test path, and delivery boundaries.",
            (
                f"Define the technical approach needed to satisfy: {terms}. "
                "Name the implementation path, constraints, likely tools or libraries, test strategy, and delivery risks."
            ),
            "The approach is concrete enough for the implementer to build and for verification to test without guessing.",
            "technical_approach",
            "Technical Approach",
            "Architecture, tool choices, runtime assumptions, implementation boundaries, and test strategy.",
            dependencies=list(dependency_artifacts),
            review_role_key="technical_approach_reviewer",
            review_display_name="Technical Approach Reviewer",
            review_rubric=(
                "Review whether the approach is practical, testable, and aligned with the requested platform and constraints. "
                "Choose revise if tool choices, runtime assumptions, or verification paths are missing or weak."
            ),
        ))
    if "data and input modeling" in inferred:
        add(_work_package(
            "input_model",
            "Input Model",
            "input_modeler",
            "Input Modeler",
            "Define required inputs, data shape, loading path, validation rules, examples, and assumptions.",
            f"Define the inputs needed to produce the requested outcome while preserving requirement coverage for: {terms}.",
            "Inputs are understandable, sufficient, validated, and usable by downstream implementation and verification stages.",
            "input_model",
            "Input Model",
            "Inputs, data shapes, loading path, validation rules, examples, and assumptions needed by the outcome.",
            dependencies=list(dependency_artifacts),
            review_role_key="input_model_reviewer",
            review_display_name="Input Model Reviewer",
            review_rubric=(
                "Review whether inputs are complete, understandable, realistic, and testable. "
                "Choose revise if downstream stages would need to infer data shape, source expectations, or validation rules."
            ),
        ))
    if "domain grounding" in inferred:
        add(_work_package(
            "domain_grounding",
            "Domain Grounding",
            "domain_researcher",
            "Domain Researcher",
            "Ground factual, regulated, historical, scientific, or customer-domain assumptions before production work depends on them.",
            f"Record factual, domain, source, and boundary assumptions required by the request. Explicitly address: {terms}.",
            "Claims and assumptions are explicit, sourced where possible, bounded, and safe for later stages to use.",
            "domain_grounding",
            "Domain Grounding Notes",
            "Factual grounding, sources, assumptions, uncertainty, and disputed or sensitive claims.",
            dependencies=list(dependency_artifacts),
            review_role_key="domain_grounding_reviewer",
            review_display_name="Domain Grounding Reviewer",
            review_rubric=(
                "Critically review factual claims, source quality, uncertainty, and boundary conditions. "
                "Choose revise if important claims are unsupported, overconfident, or unsafe for downstream use."
            ),
        ))
    if "experience design" in inferred:
        add(_work_package(
            "experience_design",
            "Experience Design",
            "experience_designer",
            "Experience Designer",
            "Design the human-facing flow, interaction model, readability, responsive behavior, and polish criteria.",
            f"Design the human-facing experience and quality bar for the requested outcome while preserving: {terms}.",
            "The design is usable, readable, progressive, responsive where relevant, and specific enough to guide implementation.",
            "experience_design",
            "Experience Design",
            "Human-facing flow, interaction model, responsiveness, polish criteria, and inspection notes.",
            dependencies=list(dependency_artifacts),
            review_role_key="experience_design_reviewer",
            review_display_name="Experience Design Reviewer",
            review_rubric=(
                "Inspect usability, visual hierarchy, clarity, progressive flow, responsiveness, and fit to the intended user. "
                "Choose revise if the design is generic, confusing, low-polish, or missing acceptance criteria."
            ),
        ))
    if "supporting asset planning" in inferred:
        add(_work_package(
            "supporting_assets",
            "Supporting Assets and Content",
            "asset_planner",
            "Supporting Asset Planner",
            "Specify supporting media, content, generated assets, source material, or non-code inputs required by the outcome.",
            f"Plan the supporting assets, content, media, or generated inputs needed by the final outcome. Preserve coverage for: {terms}.",
            "Assets and content are concrete enough to produce or source, and their quality expectations are clear.",
            "supporting_assets",
            "Supporting Asset Plan",
            "Required supporting media, content, generated assets, source files, or input material.",
            dependencies=list(dependency_artifacts),
            review_role_key="supporting_assets_reviewer",
            review_display_name="Supporting Assets Reviewer",
            review_rubric=(
                "Review whether required assets, content, ownership, fidelity, and acceptance criteria are concrete. "
                "Choose revise if final production would have to improvise important media or content decisions."
            ),
        ))
    if "safety and risk review" in inferred:
        add(_work_package(
            "risk_assessment",
            "Risk Assessment",
            "risk_analyst",
            "Risk Analyst",
            "Identify safety, security, privacy, operational, abuse, or compliance risks before final production.",
            f"Assess risks and mitigations implied by the requested outcome and constraints. Explicitly address: {terms}.",
            "Material risks, mitigations, and residual risks are explicit enough for reviewers and final evidence.",
            "risk_review",
            "Risk Review",
            "Safety, security, privacy, operational, compliance, or abuse-risk review evidence.",
            dependencies=list(dependency_artifacts),
            review_role_key="risk_assessment_reviewer",
            review_display_name="Risk Assessment Reviewer",
            review_rubric=(
                "Review whether risks are concrete, mitigations are practical, and residual risks are explicit. "
                "Choose revise if any material safety, security, privacy, operational, or abuse risk is hand-waved."
            ),
        ))

    production_dependencies = list(dependency_artifacts)
    for dimension in _production_dimensions(full_text, skills, coverage_terms):
        if dimension == "production_foundation":
            add(_work_package(
                "production_foundation",
                "Production Foundation",
                "production_foundation_builder",
                "Production Foundation Builder",
                "Build the reusable foundation, runtime skeleton, core model, and inspection harness needed before final assembly.",
                (
                    f"Create a working foundation for the requested outcome that downstream production stages can build on. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The foundation is concrete and executable or inspectable, with clear files, state model, extension points, and evidence. "
                    "It must not be a placeholder description when the request calls for a working outcome."
                ),
                "production_foundation",
                "Production Foundation",
                "Reusable foundation, scaffold, core model, runtime assumptions, and inspection harness for the final outcome.",
                artifact_path=_auto_artifact_path("production-foundation", extension=""),
                dependencies=production_dependencies,
                review_role_key="production_foundation_reviewer",
                review_display_name="Production Foundation Reviewer",
                review_rubric=(
                    "Inspect whether the foundation is concrete enough to carry the full requested outcome. "
                    "Choose revise if it is placeholder-only, cannot be executed or inspected, lacks an extension path, or ignores accepted upstream constraints."
                ),
            ))
        elif dimension == "data_behavior_layer":
            add(_work_package(
                "data_behavior_layer",
                "Data and Behavior Layer",
                "data_behavior_builder",
                "Data and Behavior Builder",
                "Build the data, state, rules, calculations, transformations, or behavioral model required by the outcome.",
                (
                    f"Implement the data, state, rules, calculations, transformations, or behavior layer implied by the request. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The layer is realistic enough to support human inspection, includes representative examples or fixtures, "
                    "and exposes clear behavior for the final integrated outcome."
                ),
                "data_behavior_layer",
                "Data and Behavior Layer",
                "Implemented data/state/rules/calculation layer, representative examples, validation notes, and handoff evidence.",
                artifact_path=_auto_artifact_path("data-behavior-layer", extension=""),
                dependencies=list(dependency_artifacts),
                review_role_key="data_behavior_reviewer",
                review_display_name="Data and Behavior Reviewer",
                review_rubric=(
                    "Inspect whether the data and behavior layer is realistic, internally coherent, and sufficient for downstream user-facing work. "
                    "Choose revise if examples are toy-thin, calculations or rules are opaque, or important states and edge cases are missing."
                ),
            ))
        elif dimension == "interaction_layer":
            add(_work_package(
                "interaction_layer",
                "Interaction Layer",
                "interaction_builder",
                "Interaction Builder",
                "Build the controls, flows, state transitions, feedback, accessibility behavior, and responsive interaction layer required by the outcome.",
                (
                    f"Implement the interaction layer implied by the accepted experience design. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The interaction layer is usable by a human without hidden knowledge, has meaningful feedback and state changes, "
                    "and includes responsive or progressive behavior when relevant."
                ),
                "interaction_layer",
                "Interaction Layer",
                "Controls, flows, state transitions, responsive behavior, accessibility notes, and interaction evidence.",
                artifact_path=_auto_artifact_path("interaction-layer", extension=""),
                dependencies=list(dependency_artifacts),
                review_role_key="interaction_reviewer",
                review_display_name="Interaction Reviewer",
                review_rubric=(
                    "Inspect the controls, flows, state changes, feedback, accessibility, and responsive behavior. "
                    "Choose revise if interaction is shallow, confusing, static where the request implies action, or dependent on undocumented user knowledge."
                ),
            ))
        elif dimension == "visual_media_layer":
            add(_work_package(
                "visual_media_layer",
                "Visual and Media Layer",
                "visual_media_builder",
                "Visual and Media Builder",
                "Produce the visual, motion, audio, charting, or media layer required by the outcome.",
                (
                    f"Create concrete visual, motion, audio, charting, or media assets and integration notes for the requested outcome. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The media layer is specific, polished relative to the requested bar, varied when the request asks for variety, "
                    "and avoids generic placeholders when visible quality matters."
                ),
                "visual_media_layer",
                "Visual and Media Layer",
                "Concrete visual/media assets, styling system, motion/audio notes, charting approach, and fidelity evidence.",
                artifact_path=_auto_artifact_path("visual-media-layer", extension=""),
                dependencies=list(dependency_artifacts),
                review_role_key="visual_media_reviewer",
                review_display_name="Visual and Media Reviewer",
                review_rubric=(
                    "Inspect fidelity, variety, visual hierarchy, motion/media behavior, and fit to the intended user. "
                    "Choose revise if visible outputs are generic, placeholder-like, sparse, inconsistent, or below the stated quality bar."
                ),
            ))
        elif dimension == "content_variation_layer":
            add(_work_package(
                "content_variation_layer",
                "Content and Variation Layer",
                "content_variation_builder",
                "Content and Variation Builder",
                "Produce representative scenarios, examples, states, modes, variants, or content sets needed to make the outcome feel complete.",
                (
                    f"Create representative content, scenarios, examples, states, modes, or variants for the requested outcome. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The content layer demonstrates meaningful breadth and depth instead of a single thin path, "
                    "and downstream implementation can integrate it without inventing missing material."
                ),
                "content_variation_layer",
                "Content and Variation Layer",
                "Representative scenarios, examples, modes, states, variants, or content sets with integration notes.",
                artifact_path=_auto_artifact_path("content-variation-layer", extension=""),
                dependencies=list(dependency_artifacts),
                review_role_key="content_variation_reviewer",
                review_display_name="Content and Variation Reviewer",
                review_rubric=(
                    "Inspect breadth, depth, realism, consistency, and usefulness of the content or scenarios. "
                    "Choose revise if there is only one shallow path, missing variation, unsupported claims, or weak downstream handoff."
                ),
            ))
        elif dimension == "domain_content_layer":
            add(_work_package(
                "domain_content_layer",
                "Grounded Content Application",
                "grounded_content_builder",
                "Grounded Content Builder",
                "Apply accepted domain grounding to the concrete content, interactions, labels, claims, examples, or explanations in the outcome.",
                (
                    f"Turn accepted domain grounding into concrete content and usage boundaries for the final outcome. "
                    f"Preserve these requirement terms: {terms}."
                ),
                (
                    "The domain content is traceable to accepted grounding, avoids overclaiming, and is concrete enough to appear in the final deliverable."
                ),
                "domain_content_layer",
                "Grounded Content Application",
                "Concrete domain-informed content, labels, claims, examples, uncertainty notes, and integration guidance.",
                artifact_path=_auto_artifact_path("domain-content-layer", extension=""),
                dependencies=list(dependency_artifacts),
                review_role_key="domain_content_reviewer",
                review_display_name="Grounded Content Reviewer",
                review_rubric=(
                    "Inspect whether concrete content faithfully applies accepted domain grounding and uncertainty boundaries. "
                    "Choose revise if claims are unsupported, too generic, overconfident, or disconnected from the final user experience."
                ),
            ))

    packages.append(_work_package(
        "implementation",
        "Integrated Outcome",
        "integrator",
        "Outcome Integrator",
        "Integrate accepted upstream production layers into the requested final outcome.",
        (
            f"Produce the final integrated outcome from the accepted plan, reviews, and production-layer artifacts. "
            f"The result must visibly satisfy the requirement coverage terms: {terms}. "
            "Do not discard upstream production work; reconcile it into one usable deliverable. "
            "For runnable outcomes, make the package run-ready before completion and make the main user action visibly display its result."
        ),
        (
            "The deliverable is usable by the intended human, implements the accepted plan, integrates accepted production layers, "
            "and leaves clear inspection evidence. Runnable deliverables are not complete until they are built, smoke-tested, "
            "launchable through a cheap start command, and show clear user-facing outcomes from their core actions. "
            "Placeholder-level outcomes are not acceptable when the request asks for polish, variety, or commercial quality."
        ),
        "produced_outcome",
        "Produced Outcome",
        "The primary deliverable requested by the user.",
        artifact_path=_auto_artifact_path("output", extension=""),
        dependencies=list(dependency_artifacts),
        review_role_key="outcome_acceptance_reviewer",
        review_display_name="Outcome Acceptance Reviewer",
        review_rubric=(
            "Inspect the produced outcome directly, exercise it where practical, compare it to the accepted plan and upstream artifacts, "
            "and choose revise if the outcome is low-detail, not usable, untested by inspection, hides core action results, "
            "requires build/install work at user start, or falls below the stated quality bar."
        ),
        rationale="The primary outcome package owns the artifact the user actually asked Octopus to produce.",
        required_skills=("implementation", "verification", "acceptance evidence"),
    ))
    return _consolidate_work_packages(packages, terms=terms)


def _consolidate_work_packages(
    packages: Sequence[ProtocolAutoDesignWorkPackageRecord],
    *,
    terms: str,
) -> list[ProtocolAutoDesignWorkPackageRecord]:
    """Fit package shape into the stage budget by merging adjacent supporting slices."""
    ordered = [package for package in packages if package.package_key != "verification"]
    requirements = next((package for package in ordered if package.package_key == "requirements"), None)
    implementation = next((package for package in ordered if package.package_key == "implementation"), None)
    optional = [
        package for package in ordered
        if package.package_key not in {"requirements", "implementation"}
    ]
    if requirements is None:
        requirements = _work_package(
            "requirements",
            "Requirement Coverage",
            "planner",
            "Workflow Planner",
            "Turn the request into explicit scope and acceptance criteria.",
            "Create a requirements coverage plan.",
            "The plan is actionable and complete enough for downstream work.",
            "requirements_plan",
            "Requirements Coverage Plan",
            "Goal, constraints, assumptions, work packages, deliverables, acceptance criteria, and coverage terms.",
        )
    if implementation is None:
        implementation = _work_package(
            "implementation",
            "Integrated Outcome",
            "integrator",
            "Outcome Integrator",
            "Produce the primary requested outcome.",
            "Produce the primary requested outcome.",
            "The outcome is usable and inspectable.",
            "produced_outcome",
            "Produced Outcome",
            "The primary deliverable requested by the user.",
            artifact_path=_auto_artifact_path("output", extension=""),
        )

    if len(optional) <= _AUTO_STANDARD_WORK_PACKAGE_BUDGET:
        return [requirements, *optional, implementation]

    kept = optional[: max(0, _AUTO_STANDARD_WORK_PACKAGE_BUDGET - 1)]
    overflow = optional[len(kept):]
    overflow_names = ", ".join(package.display_name for package in overflow)
    dependencies = list(dict.fromkeys(
        [
            *(artifact for package in kept for artifact in [package.artifact_key, package.review_artifact_key] if artifact),
            *(dependency for package in overflow for dependency in package.dependencies if dependency),
        ]
    ))
    consolidated = _work_package(
        "integrated_delivery_scope",
        "Integrated Delivery Scope",
        "delivery_architect",
        "Delivery Architect",
        "Consolidate remaining production concerns into one scoped delivery plan so the protocol stays runnable and reviewable.",
        (
            f"Consolidate these concerns into one delivery package without creating shallow separate stages: {overflow_names}. "
            f"Preserve these requirement terms: {terms}."
        ),
        (
            "The delivery scope is concrete, traceable to the omitted fine-grained concerns, and explicit about what is in the first delivery tranche "
            "versus what belongs in backlog or a follow-up protocol."
        ),
        "integrated_delivery_scope",
        "Integrated Delivery Scope",
        "Consolidated plan, acceptance notes, backlog, and handoff guidance for remaining production concerns.",
        dependencies=dependencies,
        review_role_key="integrated_delivery_scope_reviewer",
        review_display_name="Integrated Delivery Scope Reviewer",
        review_rubric=(
            "Review whether consolidation preserved the important requirements without creating a bloated protocol. "
            "Choose revise if the scope hides important work, loses traceability, or leaves the outcome implementer guessing."
        ),
        rationale=(
            "Multiple supporting slices were consolidated because separate stages would exceed the stage budget and burn tokens without improving the user outcome."
        ),
        required_skills=list(dict.fromkeys(
            skill for package in overflow for skill in [*package.required_skills, package.display_name.lower()]
            if str(skill or "").strip()
        )),
    )
    implementation_dependencies = [
        artifact
        for package in [requirements, *kept, consolidated]
        for artifact in (package.artifact_key, package.review_artifact_key)
        if artifact
    ]
    implementation = implementation.model_copy(update={
        "dependencies": list(dict.fromkeys(implementation_dependencies)),
    })
    return [requirements, *kept, consolidated, implementation]


def _normalize_model_work_packages(
    packages: Sequence[ProtocolAutoDesignWorkPackageRecord],
    *,
    requirement_text: str,
    constraints_text: str,
    terms: Sequence[str],
) -> list[ProtocolAutoDesignWorkPackageRecord]:
    model_packages = [package for package in packages if str(package.display_name or package.package_key or "").strip()]
    if not model_packages:
        return []
    terms_text = ", ".join(list(terms)[:14]) or "the explicit user requirement"
    dependency_artifacts: list[str] = ["requirements_plan"]
    normalized: list[ProtocolAutoDesignWorkPackageRecord] = []

    def normalized_package(package: ProtocolAutoDesignWorkPackageRecord, package_key: str) -> ProtocolAutoDesignWorkPackageRecord:
        display = str(package.display_name or package_key.replace("_", " ").title()).strip()
        role_key = _slugify(package.role_key or package.role_display_name or display, fallback=f"{package_key}_owner").replace("-", "_")
        artifact_key = _slugify(package.artifact_key or display, fallback=f"{package_key}_artifact").replace("-", "_")
        if package_key == "implementation":
            artifact_key = "produced_outcome"
        review_role_key = _slugify(
            package.review_role_key or package.review_display_name or f"{display} Reviewer",
            fallback=f"{package_key}_reviewer",
        ).replace("-", "_")
        dependency_candidates = [] if package_key == "requirements" else [
            *(dependency for dependency in package.dependencies if str(dependency or "").strip()),
            *dependency_artifacts,
        ]
        return package.model_copy(update={
            "package_key": package_key,
            "display_name": display,
            "rationale": package.rationale or f"{display} is required by the planner's semantic decomposition.",
            "role_key": role_key,
            "role_display_name": package.role_display_name or display,
            "role_responsibility": (
                package.role_responsibility
                or f"Own {display.lower()} for the requested outcome and produce actionable handoff evidence."
            ),
            "required_skills": list(dict.fromkeys(
                str(item or "").strip().lower()
                for item in package.required_skills
                if str(item or "").strip()
            )),
            "purpose": (
                package.purpose
                or f"Produce {display.lower()} that preserves these requirement terms: {terms_text}."
            ),
            "quality_bar": (
                package.quality_bar
                or "The artifact is concrete, inspectable, evidence-backed, and specific enough for downstream work."
            ),
            "artifact_key": artifact_key,
            "artifact_display_name": package.artifact_display_name or display,
            "artifact_description": (
                package.artifact_description
                or f"Planner-requested artifact for {display.lower()}."
            ),
            "artifact_path": package.artifact_path or _auto_artifact_path(
                "output" if package_key == "implementation" else artifact_key,
                extension="" if package_key == "implementation" else ".md",
            ),
            "dependencies": list(dict.fromkeys(dependency_candidates)),
            "review_role_key": review_role_key,
            "review_display_name": package.review_display_name or f"{display} Reviewer",
            "review_responsibility": (
                package.review_responsibility
                or f"Adversarially inspect {display.lower()} against the requirement and upstream artifacts."
            ),
            "review_artifact_key": (
                package.review_artifact_key
                or f"{artifact_key}_review"
            ),
            "review_artifact_display_name": package.review_artifact_display_name or f"{display} Review",
            "review_artifact_description": (
                package.review_artifact_description
                or f"Critical review decision and revision requests for {display.lower()}."
            ),
            "review_artifact_path": package.review_artifact_path or _auto_artifact_path(f"{artifact_key}-review"),
            "review_rubric": (
                package.review_rubric
                or f"Inspect {display.lower()} directly, compare it to the original requirement and accepted upstream artifacts, and choose revise for material gaps."
            ),
        })

    has_requirements = any(
        _slugify(package.package_key or package.display_name, fallback="") in {"requirements", "planning", "requirement-coverage"}
        for package in model_packages
    )
    if not has_requirements:
        normalized.append(_work_package(
            "requirements",
            "Requirement Coverage",
            "planner",
            "Workflow Planner",
            "Turn the user request into explicit scope, assumptions, dependencies, acceptance criteria, and work-package coverage.",
            f"Create a requirements coverage plan and map these terms: {terms_text}.",
            "Every material request is either covered, recorded as an assumption, or called out as a gap.",
            "requirements_plan",
            "Requirements Coverage Plan",
            "Goal, constraints, assumptions, work packages, deliverables, acceptance criteria, and coverage terms.",
        ))
    seen_package_keys = {package.package_key for package in normalized}
    for package in model_packages:
        raw_key = _slugify(package.package_key or package.display_name, fallback="work_package").replace("-", "_")
        if raw_key in {"requirements", "planning", "requirement_coverage"}:
            package_key = "requirements"
        elif raw_key in {"implementation", "outcome", "primary_outcome", "integrated_outcome", "delivery"}:
            package_key = "implementation"
        else:
            package_key = raw_key
        if package_key == "requirements" and any(item.package_key == "requirements" for item in normalized):
            continue
        if package_key == "implementation":
            continue
        if package_key in seen_package_keys:
            suffix = 2
            candidate = f"{package_key}_{suffix}"
            while candidate in seen_package_keys:
                suffix += 1
                candidate = f"{package_key}_{suffix}"
            package_key = candidate
        seen_package_keys.add(package_key)
        item = normalized_package(package, package_key)
        normalized.append(item)
        dependency_artifacts.extend([item.artifact_key, item.review_artifact_key])
    outcome_package = next(
        (
            package for package in model_packages
            if _slugify(package.package_key or package.display_name, fallback="").replace("-", "_")
            in {"implementation", "outcome", "primary_outcome", "integrated_outcome", "delivery"}
        ),
        ProtocolAutoDesignWorkPackageRecord(
            display_name="Integrated Outcome",
            purpose=(
                f"Produce the final integrated outcome for: {_sentence(requirement_text) or terms_text}. "
                f"Respect constraints: {_sentence(constraints_text)}"
            ),
        ),
    )
    normalized.append(normalized_package(outcome_package, "implementation"))
    return normalized


def _dedupe_work_package_review_roles(
    packages: Sequence[ProtocolAutoDesignWorkPackageRecord],
) -> list[ProtocolAutoDesignWorkPackageRecord]:
    """Planner output may reuse a reviewer label; protocols need isolated review roles."""
    used_role_keys: set[str] = set()
    used_artifact_keys: set[str] = set()
    normalized: list[ProtocolAutoDesignWorkPackageRecord] = []
    for package in packages:
        if package.package_key == "implementation":
            normalized.append(package)
            continue
        fallback_role = _slugify(
            f"{package.package_key}_reviewer",
            fallback=f"{package.package_key}_reviewer",
        ).replace("-", "_")
        role_key = _slugify(
            package.review_role_key or package.review_display_name or fallback_role,
            fallback=fallback_role,
        ).replace("-", "_")
        if not role_key or role_key in used_role_keys:
            role_key = fallback_role
        suffix = 2
        base_role_key = role_key
        while role_key in used_role_keys:
            role_key = f"{base_role_key}_{suffix}"
            suffix += 1
        used_role_keys.add(role_key)

        fallback_artifact = _slugify(
            package.review_artifact_key or f"{package.artifact_key}_review",
            fallback=f"{package.package_key}_review",
        ).replace("-", "_")
        artifact_key = fallback_artifact
        if not artifact_key or artifact_key in used_artifact_keys:
            artifact_key = _slugify(
                f"{package.package_key}_review",
                fallback=f"{package.package_key}_review",
            ).replace("-", "_")
        suffix = 2
        base_artifact_key = artifact_key
        while artifact_key in used_artifact_keys:
            artifact_key = f"{base_artifact_key}_{suffix}"
            suffix += 1
        used_artifact_keys.add(artifact_key)

        normalized.append(package.model_copy(update={
            "review_role_key": role_key,
            "review_display_name": package.review_display_name or f"{package.display_name} Reviewer",
            "review_artifact_key": artifact_key,
            "review_artifact_path": _auto_artifact_path(artifact_key),
        }))
    return normalized


def _focus_label(requirement_text: str) -> str:
    title = _title_from_requirement(requirement_text)
    if title == "Auto Protocol":
        return "Requirement-specific workflow"
    return title


def _analyze_requirement(requirement_text: str, constraints_text: str) -> ProtocolAutoDesignAnalysisRecord:
    text = _normalized_words(requirement_text, constraints_text)
    terms = _requirement_terms(requirement_text, constraints_text)
    skills = _analysis_skills(text)
    work_packages = _dedupe_work_package_review_roles(
        _infer_work_packages(requirement_text, constraints_text, skills, terms)
    )
    deliverables = _requirement_phrases(requirement_text)
    complexity_signals = sum(1 for skill in skills if skill not in {"requirements planning", "implementation", "verification", "acceptance evidence"})
    complexity = "high" if complexity_signals >= 2 or len(text) > 700 or len(deliverables) >= 4 or len(work_packages) >= 6 else "standard"
    goal = _sentence(requirement_text) or "Create the requested outcome."
    assumptions = [
        "The generated protocol should be reviewed before publish.",
        "Stage instructions should carry the work contract so launch text can stay simple.",
        "The workflow is composed from requirement decomposition and reusable protocol primitives, not a closed use-case template.",
        "Every generated work package with an output artifact should have a direct critical review or final outcome acceptance gate.",
    ]
    risks = [
        "Assignments may need local agent mapping before publish/run.",
        "A requirement-specific workflow can still miss intent if the user leaves critical constraints implicit.",
    ]
    if "domain grounding" in skills:
        risks.append("Factual or domain-sensitive claims need explicit grounding and review evidence.")
    if "experience design" in skills:
        risks.append("Human-facing outcomes need usability and polish review, not only functional completion.")
    if "safety and risk review" in skills:
        risks.append("Risk-sensitive outcomes need explicit safety or security review before acceptance.")

    required_roles: list[str] = []
    for package in work_packages:
        for label in (package.role_display_name, package.review_display_name):
            normalized = label.lower().strip()
            if normalized and normalized not in required_roles:
                required_roles.append(normalized)
    required_roles.append("outcome acceptance reviewer")

    expected_artifacts: list[str] = []
    for package in work_packages:
        labels = (package.artifact_display_name,) if package.package_key == "implementation" else (
            package.artifact_display_name,
            package.review_artifact_display_name,
        )
        for label in labels:
            normalized = label.lower().strip()
            if normalized and normalized not in expected_artifacts:
                expected_artifacts.append(normalized)
    expected_artifacts.append("release evidence")

    return ProtocolAutoDesignAnalysisRecord(
        domain="requirement-specific",
        complexity=complexity,
        goal=goal,
        focus=_focus_label(requirement_text),
        requirement_terms=terms,
        skills=skills,
        work_packages=work_packages,
        deliverables=deliverables,
        assumptions=assumptions,
        risks=risks,
        required_roles=required_roles,
        expected_artifacts=expected_artifacts,
    )


def _analysis_from_model_response(
    request: ProtocolAutoDesignRequestRecord,
    model_response: ProtocolAutoDesignModelResponseRecord,
) -> ProtocolAutoDesignAnalysisRecord:
    requirement_text = str(request.requirement_text or "").strip()
    constraints_text = str(request.constraints_text or "").strip()
    terms = _requirement_terms(requirement_text, constraints_text)
    normalized_model_packages = _normalize_model_work_packages(
        model_response.work_packages,
        requirement_text=requirement_text,
        constraints_text=constraints_text,
        terms=terms,
    )
    packages = _dedupe_work_package_review_roles(
        _consolidate_work_packages(
            normalized_model_packages or _infer_work_packages(
                requirement_text,
                constraints_text,
                _analysis_skills(_normalized_words(requirement_text, constraints_text)),
                terms,
            ),
            terms=", ".join(terms[:14]) or "the explicit user requirement",
        )
    )
    skill_names: list[str] = []
    for package in packages:
        for skill in package.required_skills:
            value = str(skill or "").strip().lower()
            if value and value not in skill_names:
                skill_names.append(value)
    for value in _analysis_skills(_normalized_words(requirement_text, constraints_text)):
        if value not in {"requirements planning", "implementation", "verification", "acceptance evidence"}:
            continue
        if value not in skill_names:
            skill_names.append(value)
    required_roles: list[str] = []
    for package in packages:
        for label in (package.role_display_name, package.review_display_name):
            normalized = label.lower().strip()
            if normalized and normalized not in required_roles:
                required_roles.append(normalized)
    if "outcome acceptance reviewer" not in required_roles:
        required_roles.append("outcome acceptance reviewer")
    expected_artifacts: list[str] = []
    for package in packages:
        for label in (package.artifact_display_name, package.review_artifact_display_name):
            normalized = label.lower().strip()
            if normalized and normalized not in expected_artifacts and package.package_key != "implementation":
                expected_artifacts.append(normalized)
        if package.package_key == "implementation" and package.artifact_display_name.lower() not in expected_artifacts:
            expected_artifacts.append(package.artifact_display_name.lower())
    if "release evidence" not in expected_artifacts:
        expected_artifacts.append("release evidence")
    complexity = "high" if len(packages) >= 6 or len(requirement_text) > 700 else "standard"
    return ProtocolAutoDesignAnalysisRecord(
        domain=model_response.domain or "requirement-specific",
        complexity=complexity,
        goal=_sentence(model_response.requirement_summary) or _sentence(requirement_text) or "Create the requested outcome.",
        focus=_focus_label(model_response.requirement_summary or requirement_text),
        requirement_terms=terms,
        skills=skill_names,
        work_packages=packages,
        deliverables=_requirement_phrases(requirement_text),
        assumptions=[
            item for item in model_response.assumptions
            if str(item or "").strip()
        ],
        risks=[
            item for item in [model_response.risk_assessment, *model_response.open_questions]
            if str(item or "").strip()
        ],
        required_roles=required_roles,
        expected_artifacts=expected_artifacts,
    )


def _role(
    role_key: str,
    display_name: str,
    responsibility: str,
    agents: Sequence[Mapping[str, object]],
    skills: Sequence[Mapping[str, object]],
) -> ProtocolAutoDesignRolePlanRecord:
    selector, note = _selector_for_role(role_key, display_name, agents, skills)
    return ProtocolAutoDesignRolePlanRecord(
        role_key=role_key,
        display_name=display_name,
        responsibility=responsibility,
        selector=RegistryJsonRecord.model_validate(selector),
        assignment_note=note,
    )


def _artifact(key: str, name: str, description: str, path: str) -> ProtocolAutoDesignArtifactPlanRecord:
    return ProtocolAutoDesignArtifactPlanRecord(
        artifact_key=key,
        display_name=name,
        description=description,
        path=path,
    )


def _stage(
    key: str,
    name: str,
    kind: str,
    role_key: str,
    purpose: str,
    *,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = (),
    review_of: str = "",
) -> ProtocolAutoDesignStagePlanRecord:
    return ProtocolAutoDesignStagePlanRecord(
        stage_key=key,
        display_name=name,
        stage_kind=kind,
        role_key=role_key,
        purpose=purpose,
        inputs=list(inputs),
        outputs=list(outputs),
        review_of_stage_key=review_of,
    )


def _review_round_limit(policy: ProtocolAutoDesignReviewPolicyRecord | None = None) -> int:
    raw = int((policy.max_review_rounds if policy is not None else 3) or 0)
    if raw <= 0:
        raw = 3
    return min(raw, _AUTO_REVIEW_ROUND_MAX)


def _base_run_profile(requirement: str, constraints: str, workspace_ref: str) -> ProtocolAutoDesignRunProfileRecord:
    objective = _run_objective_sentence(requirement)
    return ProtocolAutoDesignRunProfileRecord(
        problem_statement=objective or "Run the generated workflow.",
        context="Use the protocol stages as the work contract. Add only run-specific facts here.",
        constraints=_sentence(constraints),
        acceptance_criteria=(
            "Complete every stage, produce declared artifacts, record critical review decisions, "
            "revise work when reviewers identify material gaps, and finish with inspection-ready evidence."
        ),
        workspace_ref=str(workspace_ref or "").strip(),
        run_inputs=[
            {
                "key": "problem_statement",
                "label": "Run objective",
                "kind": "textarea",
                "required": True,
                "default_value": objective,
                "help": "The run-specific outcome this protocol should accomplish.",
            },
            {
                "key": "constraints",
                "label": "Constraints",
                "kind": "textarea",
                "required": False,
                "default_value": _sentence(constraints),
                "help": "Runtime constraints, inputs, or boundaries that matter for this run.",
            },
        ],
    )


def _canonical_run_inputs(
    run_inputs: Sequence[Mapping[str, object]] | None,
    *,
    fallback_requirement: str,
    fallback_constraints: str,
) -> list[dict[str, object]]:
    fields: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in run_inputs or []:
        if not isinstance(raw, Mapping):
            continue
        field = dict(raw)
        raw_key = _snake(str(field.get("key") or ""))
        if not raw_key:
            continue
        key = "problem_statement" if raw_key == "goal" else raw_key
        if key in seen:
            continue
        field["key"] = key
        if key == "problem_statement":
            field.setdefault("label", "Run objective")
            field.setdefault("kind", "textarea")
            field["required"] = True
            field.setdefault("default_value", _sentence(fallback_requirement))
            field.setdefault("help", "The run-specific outcome this protocol should accomplish.")
        fields.append(field)
        seen.add(key)
    if "problem_statement" not in seen:
        fields.insert(
            0,
            {
                "key": "problem_statement",
                "label": "Run objective",
                "kind": "textarea",
                "required": True,
                "default_value": _sentence(fallback_requirement),
                "help": "The run-specific outcome this protocol should accomplish.",
            },
        )
        seen.add("problem_statement")
    if "constraints" not in seen and _sentence(fallback_constraints):
        fields.append(
            {
                "key": "constraints",
                "label": "Constraints",
                "kind": "textarea",
                "required": False,
                "default_value": _sentence(fallback_constraints),
                "help": "Runtime constraints, inputs, or boundaries that matter for this run.",
            }
        )
    return fields


def _build_plan(
    request: ProtocolAutoDesignRequestRecord,
    analysis: ProtocolAutoDesignAnalysisRecord,
) -> ProtocolAutoDesignPlanRecord:
    requirement = str(request.requirement_text or "").strip()
    constraints = str(request.constraints_text or "").strip()
    title = _title_from_requirement(requirement)
    slug = _slugify(title)
    description = _sentence(requirement) or "Auto-generated requirement-specific protocol."
    agents = [item.as_dict() for item in request.available_agents]
    skills = [item.as_dict() for item in request.available_skills]
    model_response = request.model_response
    run_profile = _base_run_profile(requirement, constraints, request.workspace_ref)
    if model_response is not None and model_response.run_inputs:
        run_profile = run_profile.model_copy(update={
            "run_inputs": _canonical_run_inputs(
                model_response.run_inputs,
                fallback_requirement=requirement,
                fallback_constraints=constraints,
            )
        })
    if model_response is not None and model_response.acceptance_criteria:
        run_profile = run_profile.model_copy(update={
            "acceptance_criteria": " ".join(
                _sentence(item) for item in model_response.acceptance_criteria if str(item or "").strip()
            ).strip() or run_profile.acceptance_criteria,
        })
    work_packages = list(analysis.work_packages) or _infer_work_packages(
        requirement,
        constraints,
        analysis.skills,
        analysis.requirement_terms,
    )
    implementation_package = next((package for package in work_packages if package.package_key == "implementation"), None)
    proposed_primary = model_response.primary_artifact if model_response is not None else None
    proposed_open_behavior = str((proposed_primary.open_behavior if proposed_primary is not None else "") or "").strip().lower()
    runtime_expected = (
        proposed_open_behavior in _AUTO_RUNTIME_OPEN_BEHAVIORS
        or auto_protocol_runtime_expected_from_text(
            proposed_open_behavior,
            requirement,
            constraints,
            analysis.goal,
            analysis.focus,
            *(analysis.deliverables or []),
            *((implementation_package.required_skills if implementation_package is not None else []) or []),
            implementation_package.display_name if implementation_package is not None else "",
            implementation_package.purpose if implementation_package is not None else "",
            implementation_package.quality_bar if implementation_package is not None else "",
            implementation_package.artifact_description if implementation_package is not None else "",
            model_response.requirement_summary if model_response is not None else "",
            model_response.domain if model_response is not None else "",
        )
    )

    roles_by_key: dict[str, ProtocolAutoDesignRolePlanRecord] = {}

    def ensure_role(role_key: str, display_name: str, responsibility: str) -> None:
        if role_key not in roles_by_key:
            roles_by_key[role_key] = _role(role_key, display_name, responsibility, agents, skills)

    for package in work_packages:
        ensure_role(package.role_key, package.role_display_name, package.role_responsibility)
        if package.package_key != "implementation":
            ensure_role(
                package.review_role_key,
                package.review_display_name,
                (
                    package.review_responsibility
                    + " Be independent and critical; choose revise when evidence, usability, completeness, or quality is below the stated bar."
                ),
            )
    ensure_role(
        "outcome_acceptance_reviewer",
        "Outcome Acceptance Reviewer",
        "Adversarially inspect or exercise the primary artifact against the original requirement, accepted upstream artifacts, and release evidence before accepting the run.",
    )
    roles = list(roles_by_key.values())

    artifact_by_key: dict[str, ProtocolAutoDesignArtifactPlanRecord] = {}

    def ensure_artifact(key: str, name: str, description_text: str, path: str) -> None:
        if key and key not in artifact_by_key:
            artifact_by_key[key] = _artifact(key, name, description_text, path)

    for package in work_packages:
        ensure_artifact(package.artifact_key, package.artifact_display_name, package.artifact_description, package.artifact_path)
        if package.package_key != "implementation":
            ensure_artifact(
                package.review_artifact_key,
                package.review_artifact_display_name,
                package.review_artifact_description,
                package.review_artifact_path,
            )
    ensure_artifact(
        "release_evidence",
        "Release Evidence",
        "Final summary of artifacts, accepted reviews, revision loops, remaining risks, and exact inspection steps.",
        _auto_artifact_path("release-evidence"),
    )
    artifacts = list(artifact_by_key.values())

    stage_key_by_package = {
        "requirements": "plan_requirements",
        "technical_approach": "define_technical_approach",
        "input_model": "model_inputs",
        "domain_grounding": "establish_domain_grounding",
        "experience_design": "design_experience",
        "supporting_assets": "plan_supporting_assets",
        "risk_assessment": "assess_risk",
        "production_foundation": "build_production_foundation",
        "data_behavior_layer": "build_data_behavior_layer",
        "interaction_layer": "build_interaction_layer",
        "visual_media_layer": "build_visual_media_layer",
        "content_variation_layer": "build_content_variation_layer",
        "domain_content_layer": "apply_grounded_content",
        "implementation": "produce_outcome",
    }
    review_key_by_package = {
        "requirements": "review_requirements",
        "technical_approach": "review_technical_approach",
        "input_model": "review_inputs",
        "domain_grounding": "review_domain_grounding",
        "experience_design": "review_experience",
        "supporting_assets": "review_supporting_assets",
        "risk_assessment": "review_risk",
        "production_foundation": "review_production_foundation",
        "data_behavior_layer": "review_data_behavior_layer",
        "interaction_layer": "review_interaction_layer",
        "visual_media_layer": "review_visual_media_layer",
        "content_variation_layer": "review_content_variation_layer",
        "domain_content_layer": "review_grounded_content",
        "implementation": "review_outcome",
    }
    work_display_by_package = {
        "requirements": "Map requirement and acceptance criteria",
        "technical_approach": "Define technical approach",
        "input_model": "Model required inputs",
        "domain_grounding": "Establish domain grounding",
        "experience_design": "Design user-facing experience",
        "supporting_assets": "Plan supporting assets and content",
        "risk_assessment": "Assess risk and safety",
        "production_foundation": "Build production foundation",
        "data_behavior_layer": "Build data and behavior layer",
        "interaction_layer": "Build interaction layer",
        "visual_media_layer": "Build visual and media layer",
        "content_variation_layer": "Build content and variation layer",
        "domain_content_layer": "Apply grounded content",
        "implementation": "Integrate requested outcome",
    }
    review_display_by_package = {
        "requirements": "Review requirement coverage",
        "technical_approach": "Review technical approach",
        "input_model": "Review input model",
        "domain_grounding": "Review domain grounding",
        "experience_design": "Review experience design",
        "supporting_assets": "Review supporting asset plan",
        "risk_assessment": "Review risk assessment",
        "production_foundation": "Review production foundation",
        "data_behavior_layer": "Review data and behavior layer",
        "interaction_layer": "Review interaction layer",
        "visual_media_layer": "Review visual and media layer",
        "content_variation_layer": "Review content and variation layer",
        "domain_content_layer": "Review grounded content application",
        "implementation": "Review produced outcome",
    }

    stages: list[ProtocolAutoDesignStagePlanRecord] = []
    available_artifacts: list[str] = []
    for package in work_packages:
        work_key = stage_key_by_package.get(package.package_key, _slugify(package.package_key, fallback="work_stage").replace("-", "_"))
        review_key = review_key_by_package.get(package.package_key, f"review_{work_key}")
        work_inputs = list(dict.fromkeys([*package.dependencies, *available_artifacts]))
        work_purpose = "\n".join([
            package.purpose.strip(),
            f"Quality bar: {package.quality_bar.strip()}",
            "Keep this stage focused on its owned artifact and avoid doing later-stage work early.",
            (
                "This protocol expects a runnable primary artifact. Package it as a user-facing product: include a coherent UI/API, "
                "tests or smoke steps, a root octopus-runtime.json manifest, and enough start/health/smoke metadata for Octopus to start it, proxy it, and let users try it. "
                "Build and smoke-test the package during this stage so the manifest start_command launches a prepared artifact quickly instead of installing dependencies, compiling, testing, or packaging on user start. "
                "Any user-triggered action in the UI must surface a clear result/outcome in the app itself, not require log inspection or raw JSON archaeology. "
                f"{AUTO_PROTOCOL_RUNTIME_MANIFEST_GUIDANCE}"
                if package.package_key == "implementation" and runtime_expected
                else ""
            ),
            (
                "If this outcome unexpectedly becomes interactive or API-backed, include octopus-runtime.json at the package root so Octopus can start it, proxy it, and let users try it."
                if package.package_key == "implementation" and not runtime_expected
                else ""
            ),
        ]).strip()
        stages.append(_stage(
            work_key,
            work_display_by_package.get(package.package_key, package.display_name),
            "work",
            package.role_key,
            work_purpose,
            inputs=work_inputs,
            outputs=[package.artifact_key],
        ))
        if package.package_key == "implementation":
            available_artifacts = list(dict.fromkeys([*available_artifacts, package.artifact_key]))
            continue
        review_inputs = list(dict.fromkeys([*work_inputs, package.artifact_key]))
        review_purpose = "\n".join([
            f"Critically review {package.artifact_display_name}.",
            package.review_rubric.strip(),
            f"Quality bar under review: {package.quality_bar.strip()}",
            "Inspect the artifact content, compare it to the original requirement and upstream artifacts, identify stronger approaches where useful, and choose revise for any material gap.",
            "Do not accept merely because the stage produced something; accept only when the artifact is specific, usable, evidence-backed, and ready for downstream work.",
            "Use a fail-first review posture: list the evidence you inspected, name any missing evidence, and choose revise when the current artifact has unresolved material gaps, weak fidelity, shallow coverage, unsupported claims, untested required behavior, or downstream-critical uncertainty.",
            "If your rationale says something important is missing, risky, unproven, placeholder-like, or below the stated quality bar, PROTOCOL_DECISION must be revise unless the problem cannot be corrected by another attempt, in which case choose fail.",
            "End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
        ]).strip()
        stages.append(_stage(
            review_key,
            review_display_by_package.get(package.package_key, f"Review {package.display_name}"),
            "review",
            package.review_role_key,
            review_purpose,
            inputs=review_inputs,
            outputs=[package.review_artifact_key],
            review_of=work_key,
        ))
        available_artifacts = list(dict.fromkeys([*available_artifacts, package.artifact_key, package.review_artifact_key]))

    stages.append(_stage(
        "final_evidence",
        "Accept primary outcome and release evidence",
        "acceptance",
        "outcome_acceptance_reviewer",
        (
            (
                "Adversarially exercise the runnable primary produced outcome against the original requirement, accepted upstream artifacts, and quality bars. "
                "The produced outcome must include octopus-runtime.json at the package root. "
                f"{AUTO_PROTOCOL_RUNTIME_MANIFEST_GUIDANCE} "
                "Start or open the Octopus-managed runtime, exercise the UI/API through the Registry URL, "
                "and record runtime evidence before accepting. Do not accept based on direct localhost or container-only smoke checks when the Registry-managed runtime cannot parse, start, route, or fetch the app. "
                "Do not accept if the runtime start command performs build, dependency installation, packaging, tests, or developer-mode bootstrapping; the implementation stage must prepare the package first and the start command must only launch it. "
                "For UI/API systems, run at least one core user action and verify the result is visible and understandable in the app itself. "
                "Choose revise if the manifest is missing or invalid, the runtime cannot start, health fails, the UI/API cannot be exercised, "
                "the primary artifact is hard to find, low-detail, not usable, missing required behavior, hides the result of core actions, unsupported by evidence, or below the stated quality bar. "
            )
            if runtime_expected
            else (
                "Adversarially inspect or exercise the primary produced outcome against the original requirement, accepted upstream artifacts, and quality bars. "
                "If the primary artifact declares octopus-runtime.json, it must follow the Octopus runtime manifest contract, then start or open the Octopus-managed runtime, exercise the UI/API, and record runtime evidence before accepting. "
                "If the runtime start command performs build, dependency installation, packaging, tests, or developer-mode bootstrapping, choose revise. "
                "For UI/API systems, run at least one core user action and verify the result is visible and understandable in the app itself. "
                "Choose revise if the primary artifact is hard to find, low-detail, not usable, missing required behavior, hides the result of core actions, unsupported by evidence, has an invalid runtime manifest, or falls below the stated quality bar. "
            )
        )
        + (
            "Record final release evidence: what was inspected, what worked, what remains risky, exact user-facing inspection steps, and the visible outcome/result from at least one exercised core action when applicable. "
            "Choose accept only when the primary artifact is ready for a human user to inspect. End with PROTOCOL_DECISION: accept, revise, or fail and PROTOCOL_SUMMARY."
        ),
        inputs=[artifact.artifact_key for artifact in artifacts if artifact.artifact_key != "release_evidence"],
        outputs=["release_evidence"],
        review_of="produce_outcome",
    ))

    stage_count = len(stages)
    if stage_count <= _AUTO_STAGE_BUDGET_SMALL_MAX:
        budget_label = "small"
    elif stage_count <= _AUTO_STAGE_BUDGET_STANDARD_MAX:
        budget_label = "standard"
    elif stage_count <= _AUTO_STAGE_BUDGET_COMPLEX_MAX:
        budget_label = "complex"
    else:
        budget_label = "over_cap"
    primary_artifact = ProtocolAutoDesignPrimaryArtifactRecord(
        artifact_key="produced_outcome",
        display_name="Produced Outcome",
        produced_by_stage_key="produce_outcome",
        artifact_kind="workspace_file",
        expected_path=_auto_artifact_path("output", extension=""),
        open_behavior="runtime" if runtime_expected else "browse",
        evidence_requirements=[
            "Primary artifact exists and is inspectable.",
            "Final acceptance records what was exercised or inspected.",
            "Release evidence links the artifact to the original requirement.",
            *(
                [
                    "A root octopus-runtime.json manifest exists for the primary artifact.",
                    "The Octopus-managed runtime starts, passes health, and is exercised through Registry routing.",
                    "The runtime start command launches a prebuilt/prepared package and does not install, build, package, or test on user start.",
                    "A core user action visibly surfaces its result in the runtime UI/API.",
                ]
                if runtime_expected
                else []
            ),
        ],
        supporting_artifact_keys=[
            artifact.artifact_key
            for artifact in artifacts
            if artifact.artifact_key not in {"produced_outcome", "release_evidence"}
        ],
    )
    proposed_policy = model_response.review_policy if model_response is not None else None
    review_policy = ProtocolAutoDesignReviewPolicyRecord(
        stance="adversarial",
        max_review_rounds=_review_round_limit(proposed_policy),
        stage_hard_cap=_AUTO_STAGE_HARD_CAP,
        stage_budget_label=budget_label,
        stage_count_rationale=(
            f"{stage_count} stages: {len(work_packages)} work packages compiled with direct reviews for upstream artifacts and one final outcome acceptance."
        ),
    )

    return ProtocolAutoDesignPlanRecord(
        protocol_name=title,
        protocol_slug=slug,
        description=description,
        roles=roles,
        artifacts=artifacts,
        stages=stages,
        run_profile=run_profile,
        primary_artifact=primary_artifact,
        review_policy=review_policy,
    )


def compile_auto_protocol_plan(
    plan: ProtocolAutoDesignPlanRecord,
    *,
    requirement_text: str = "",
    constraints_text: str = "",
) -> dict[str, object]:
    role_by_key = {role.role_key: role for role in plan.roles}
    stages: list[dict[str, object]] = []
    for index, stage in enumerate(plan.stages):
        transitions: dict[str, str] = {}
        next_key = plan.stages[index + 1].stage_key if index + 1 < len(plan.stages) else "__complete__"
        if stage.stage_kind == "review":
            transitions = {
                "accept": next_key,
                "revise": stage.review_of_stage_key or (plan.stages[index - 1].stage_key if index > 0 else next_key),
                "fail": "__failed__",
            }
        elif stage.stage_kind == "acceptance":
            transitions = {
                "accept": "__complete__",
                "revise": stage.review_of_stage_key or (plan.stages[index - 1].stage_key if index > 0 else next_key),
                "fail": "__failed__",
            }
        else:
            transitions = {"completed": next_key}
        role = role_by_key.get(stage.role_key)
        selector = role.selector.as_dict() if role is not None else {"kind": "skill", "value": stage.role_key or "auto-protocol"}
        if stage.stage_kind == "work":
            decision_instruction = (
                "This is a work stage. The only valid protocol decision is completed; "
                "do not end with accept, revise, or fail."
            )
        else:
            decision_instruction = (
                "This is a review or acceptance stage. Make the decision explicit and end with "
                "PROTOCOL_DECISION and PROTOCOL_SUMMARY."
            )
        instructions = "\n".join([
            stage.purpose.strip(),
            "",
            "Use the protocol run context, declared inputs, and artifact contract. Produce or update declared outputs only where this stage owns them.",
            "Do not leave foreground servers, watchers, or other long-running commands active. If a temporary local server is needed, stop it before final response.",
            decision_instruction,
        ]).strip()
        stages.append({
            "stage_key": stage.stage_key,
            "display_name": stage.display_name,
            "participant_key": stage.role_key,
            "selector": selector,
            "stage_kind": stage.stage_kind,
            "instructions": instructions,
            "inputs": list(stage.inputs),
            "outputs": list(stage.outputs),
            "transitions": transitions,
            "write_capable": bool(stage.outputs),
            "max_rounds": 0,
            "strict_completion": stage.stage_kind in {"review", "acceptance"},
            "require_output_verification": True if stage.outputs else None,
            "timeout_seconds": 0,
        })
    metadata: dict[str, object] = {
        "slug": plan.protocol_slug,
        "display_name": plan.protocol_name,
        "description": plan.description,
        "auto_protocol": {
            "generated": True,
            "requirement": str(requirement_text or "").strip(),
            "constraints": str(constraints_text or "").strip(),
            "primary_artifact_key": plan.primary_artifact.artifact_key,
            "primary_artifact": plan.primary_artifact.model_dump(mode="json"),
            "stage_count": len(plan.stages),
            "stage_hard_cap": plan.review_policy.stage_hard_cap or _AUTO_STAGE_HARD_CAP,
            "stage_budget_label": plan.review_policy.stage_budget_label,
            "stage_count_rationale": plan.review_policy.stage_count_rationale,
            "review_policy": plan.review_policy.model_dump(mode="json"),
        },
        "run_inputs": plan.run_profile.run_inputs,
    }
    return draft_protocol_document_data({
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "metadata": metadata,
        "participants": [
            {
                "participant_key": role.role_key,
                "display_name": role.display_name,
                "instructions": role.responsibility,
            }
            for role in plan.roles
        ],
        "artifacts": [
            {
                "artifact_key": artifact.artifact_key,
                "display_name": artifact.display_name,
                "description": artifact.description,
                "kind": "workspace_file",
                "path": artifact.path,
                "verify": True,
            }
            for artifact in plan.artifacts
        ],
        "stages": stages,
        "policies": {
            "single_active_writer": True,
            "max_review_rounds": _review_round_limit(plan.review_policy),
        },
    })


def _first_connected_agent_selector(request: ProtocolAutoDesignRequestRecord) -> dict[str, object]:
    for item in request.available_agents:
        agent = item.as_dict()
        agent_id = str(agent.get("agent_id") or "").strip()
        if agent_id:
            return {"kind": "agent", "value": agent_id}
    return {"kind": "skill", "value": "auto-protocol"}


def _repair_protocol_document(
    document: dict[str, object],
    request: ProtocolAutoDesignRequestRecord,
    validation: ProtocolValidationResultRecord,
) -> tuple[dict[str, object], list[str]]:
    repaired = draft_protocol_document_data(document)
    notes: list[str] = []
    metadata = dict(repaired.get("metadata") or {})
    participants = [dict(item) for item in repaired.get("participants", []) if isinstance(item, Mapping)]
    artifacts = [dict(item) for item in repaired.get("artifacts", []) if isinstance(item, Mapping)]
    stages = [dict(item) for item in repaired.get("stages", []) if isinstance(item, Mapping)]

    def note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    def unique_key(raw: str, existing: set[str], fallback: str) -> str:
        base = _slugify(raw, fallback=fallback).replace("-", "_")
        candidate = base
        index = 2
        while not candidate or candidate in existing:
            candidate = f"{base}_{index}"
            index += 1
        existing.add(candidate)
        return candidate

    participant_keys = {
        str(item.get("participant_key", "") or "").strip()
        for item in participants
        if str(item.get("participant_key", "") or "").strip()
    }
    artifact_keys = {
        str(item.get("artifact_key", "") or "").strip()
        for item in artifacts
        if str(item.get("artifact_key", "") or "").strip()
    }
    stage_keys = {
        str(item.get("stage_key", "") or "").strip()
        for item in stages
        if str(item.get("stage_key", "") or "").strip()
    }

    if any(issue.code == "metadata.slug_required" for issue in validation.issues):
        title = str(metadata.get("display_name") or request.requirement_text or "Auto Protocol")
        metadata["slug"] = _slugify(title)
        note("Repaired missing protocol slug.")

    if any(issue.code == "participants.required" for issue in validation.issues):
        participants.append({
            "participant_key": "auto_protocol_worker",
            "display_name": "Auto Protocol Worker",
            "instructions": "Own generated protocol work when no specific participant was declared.",
        })
        participant_keys.add("auto_protocol_worker")
        note("Added a fallback participant.")

    if any(issue.code == "stages.required" for issue in validation.issues):
        if "auto_protocol_worker" not in participant_keys:
            participants.append({
                "participant_key": "auto_protocol_worker",
                "display_name": "Auto Protocol Worker",
                "instructions": "Plan, produce, review, and summarize the requested outcome.",
            })
            participant_keys.add("auto_protocol_worker")
        if "auto_protocol_output" not in artifact_keys:
            artifacts.append({
                "artifact_key": "auto_protocol_output",
                "display_name": "Auto Protocol Output",
                "description": "Primary generated work product.",
                "kind": "workspace_file",
                "path": _auto_artifact_path("output"),
                "verify": True,
            })
            artifact_keys.add("auto_protocol_output")
        stages.append({
            "stage_key": "produce_output",
            "display_name": "Produce output",
            "participant_key": "auto_protocol_worker",
            "selector": _first_connected_agent_selector(request),
            "stage_kind": "work",
            "instructions": "Produce the requested output and record enough evidence for review.",
            "inputs": [],
            "outputs": ["auto_protocol_output"],
            "transitions": {"completed": "__complete__"},
            "write_capable": True,
            "max_rounds": 0,
            "strict_completion": False,
            "require_output_verification": True,
            "timeout_seconds": 0,
        })
        stage_keys.add("produce_output")
        note("Added a fallback work stage.")

    participant_keys = set()
    for index, participant in enumerate(participants):
        raw_key = str(participant.get("participant_key", "") or "").strip()
        if not raw_key or raw_key in participant_keys:
            participant["participant_key"] = unique_key(raw_key or participant.get("display_name", ""), participant_keys, f"participant_{index + 1}")
            note("Repaired participant keys.")
        else:
            participant_keys.add(raw_key)

    artifact_keys = set()
    for index, artifact in enumerate(artifacts):
        raw_key = str(artifact.get("artifact_key", "") or "").strip()
        if not raw_key or raw_key in artifact_keys:
            artifact["artifact_key"] = unique_key(raw_key or artifact.get("display_name", ""), artifact_keys, f"artifact_{index + 1}")
            note("Repaired artifact keys.")
        else:
            artifact_keys.add(raw_key)
        if str(artifact.get("kind", "") or "").strip() == "workspace_file" and not str(artifact.get("path", "") or "").strip():
            artifact["path"] = _auto_artifact_path(str(artifact.get("artifact_key") or f"artifact-{index + 1}"))
            note("Repaired missing artifact paths.")

    stage_keys = set()
    for index, stage in enumerate(stages):
        raw_key = str(stage.get("stage_key", "") or "").strip()
        if not raw_key or raw_key in stage_keys:
            stage["stage_key"] = unique_key(raw_key or stage.get("display_name", ""), stage_keys, f"stage_{index + 1}")
            note("Repaired stage keys.")
        else:
            stage_keys.add(raw_key)

    fallback_participant = next(iter(participant_keys), "auto_protocol_worker")
    if not participant_keys:
        participants.append({
            "participant_key": fallback_participant,
            "display_name": "Auto Protocol Worker",
            "instructions": "Own generated protocol work when no specific participant was declared.",
        })
        participant_keys.add(fallback_participant)
        note("Added a fallback participant.")

    for index, stage in enumerate(stages):
        participant_key = str(stage.get("participant_key", "") or "").strip()
        if not participant_key or participant_key not in participant_keys:
            stage["participant_key"] = fallback_participant
            note("Repaired missing stage participants.")
        selector = stage.get("selector")
        selector_map = dict(selector) if isinstance(selector, Mapping) else {}
        selector_kind = str(selector_map.get("kind", "") or "").strip()
        selector_value = str(selector_map.get("value", "") or "").strip()
        if selector_kind not in {"agent", "skill", "role", "capability"} or not selector_value:
            stage["selector"] = _first_connected_agent_selector(request)
            note("Repaired missing stage assignment rules.")
        for field in ("inputs", "outputs"):
            repaired_refs: list[str] = []
            for raw_ref in _list(stage.get(field)):
                artifact_key = str(raw_ref or "").strip()
                if not artifact_key:
                    continue
                if artifact_key not in artifact_keys:
                    artifacts.append({
                        "artifact_key": artifact_key,
                        "display_name": artifact_key.replace("_", " ").replace("-", " ").title(),
                        "description": "Auto-added artifact required by a generated stage.",
                        "kind": "workspace_file",
                        "path": _auto_artifact_path(artifact_key),
                        "verify": True,
                    })
                    artifact_keys.add(artifact_key)
                    note("Repaired missing artifact declarations.")
                repaired_refs.append(artifact_key)
            stage[field] = repaired_refs
        transitions = dict(stage.get("transitions") or {})
        next_key = str(stages[index + 1].get("stage_key") or "") if index + 1 < len(stages) else "__complete__"
        stage_kind = str(stage.get("stage_kind", "") or "work").strip() or "work"
        if stage_kind != "work" and not transitions:
            transitions = {"accept": next_key, "fail": "__failed__"}
            if stage_kind == "review":
                transitions["revise"] = str(stages[index - 1].get("stage_key") or next_key) if index > 0 else next_key
            note("Repaired missing review transitions.")
        fixed_transitions: dict[str, str] = {}
        for decision, target in transitions.items():
            decision_key = str(decision or "").strip().lower() or "completed"
            target_key = str(target or "").strip()
            if not target_key or (target_key not in stage_keys and target_key not in {"__complete__", "__failed__", "__cancelled__"}):
                target_key = next_key
                note("Repaired invalid transition targets.")
            fixed_transitions[decision_key] = target_key
        if not fixed_transitions:
            fixed_transitions = {"completed": next_key}
        stage["transitions"] = fixed_transitions

    repaired["metadata"] = metadata
    repaired["participants"] = participants
    repaired["artifacts"] = artifacts
    repaired["stages"] = stages
    return draft_protocol_document_data(repaired), notes


def _validate_and_repair_protocol_document(
    document: dict[str, object],
    request: ProtocolAutoDesignRequestRecord,
    *,
    max_attempts: int = 2,
) -> tuple[dict[str, object], ProtocolValidationResultRecord, list[str]]:
    current = draft_protocol_document_data(document)
    repair_notes: list[str] = []
    validation = validate_protocol_document(current, mode="strict")
    attempts = 0
    while not validation.ok and attempts < max_attempts:
        current, notes = _repair_protocol_document(current, request, validation)
        repair_notes.extend(note for note in notes if note not in repair_notes)
        validation = validate_protocol_document(current, mode="strict")
        attempts += 1
    return current, validation, repair_notes


def _plan_coverage_text(plan: ProtocolAutoDesignPlanRecord) -> str:
    parts: list[str] = [
        plan.protocol_name,
        plan.description,
        plan.run_profile.problem_statement,
        plan.run_profile.context,
        plan.run_profile.constraints,
        plan.run_profile.acceptance_criteria,
    ]
    for role in plan.roles:
        parts.extend([role.display_name, role.responsibility])
    for artifact in plan.artifacts:
        parts.extend([artifact.display_name, artifact.description, artifact.path])
    for stage in plan.stages:
        parts.extend([
            stage.display_name,
            stage.stage_kind,
            stage.role_key,
            stage.purpose,
            *stage.inputs,
            *stage.outputs,
            stage.review_of_stage_key,
        ])
    return _normalized_words(*parts)


def _semantic_warnings_for_session(
    analysis: ProtocolAutoDesignAnalysisRecord,
    plan: ProtocolAutoDesignPlanRecord,
) -> tuple[list[ProtocolAutoDesignWarningRecord], list[ProtocolAutoDesignWarningRecord]]:
    warnings: list[ProtocolAutoDesignWarningRecord] = []
    unresolved: list[ProtocolAutoDesignWarningRecord] = []
    coverage_text = _plan_coverage_text(plan)
    terms = [term for term in analysis.requirement_terms if len(term) >= 4]
    missing = [term for term in terms if term not in coverage_text]
    if terms and len(missing) > max(1, len(terms) // 5):
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.coverage_incomplete",
            message=(
                "The generated protocol does not explicitly cover enough of the user's requirement. "
                f"Missing coverage: {', '.join(missing[:8])}."
            ),
            severity="error",
            section="semantic_coverage",
            action="repair_generated_protocol",
        ))

    stage_kinds = {stage.stage_kind for stage in plan.stages}
    if "review" not in stage_kinds:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.review_missing",
            message="The generated protocol has no review stage. Add at least one review gate before publish or run.",
            severity="error",
            section="semantic_coverage",
            action="repair_generated_protocol",
        ))
    if "acceptance" not in stage_kinds:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.acceptance_missing",
            message="The generated protocol has no acceptance stage. Add final evidence before publish or run.",
            severity="error",
            section="semantic_coverage",
            action="repair_generated_protocol",
        ))
    if len(plan.stages) > _AUTO_STAGE_HARD_CAP:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.stage_budget_exceeded",
            message=(
                f"The generated protocol has {len(plan.stages)} stages, above the hard cap of {_AUTO_STAGE_HARD_CAP}. "
                "Consolidate work packages or narrow the requested outcome before publishing."
            ),
            severity="error",
            section="semantic_coverage",
            action="repair_generated_protocol",
        ))

    stage_by_key = {stage.stage_key: stage for stage in plan.stages}
    artifact_keys = {artifact.artifact_key for artifact in plan.artifacts if artifact.artifact_key}
    primary = plan.primary_artifact
    if not primary.artifact_key or primary.artifact_key not in artifact_keys:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.primary_artifact_missing",
            message="The generated protocol does not declare an inspectable primary artifact.",
            severity="error",
            section="primary_artifact",
            action="repair_generated_protocol",
        ))
    primary_stage = stage_by_key.get(primary.produced_by_stage_key or "")
    if primary_stage is None or primary.artifact_key not in primary_stage.outputs:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.primary_artifact_stage_invalid",
            message="The primary artifact is not produced by the declared primary outcome stage.",
            severity="error",
            section="primary_artifact",
            action="repair_generated_protocol",
        ))
    elif len(plan.stages) >= 2 and plan.stages[-2].stage_key != primary_stage.stage_key:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.primary_artifact_not_second_last",
            message="The primary artifact stage must be immediately before final outcome acceptance.",
            severity="error",
            section="primary_artifact",
            action="repair_generated_protocol",
        ))
    if plan.stages:
        final_stage = plan.stages[-1]
        if final_stage.stage_kind != "acceptance" or final_stage.review_of_stage_key != primary.produced_by_stage_key:
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code="semantic.final_acceptance_invalid",
                message="The final stage must adversarially accept or send back the primary produced outcome.",
                severity="error",
                section="primary_artifact",
                action="repair_generated_protocol",
            ))

    skill_stage_requirements = {
        "technical architecture": ("technical", "architecture", "foundation"),
        "domain grounding": ("domain", "grounded"),
        "experience design": ("experience", "interaction", "visual", "ux"),
        "supporting asset planning": ("supporting", "asset", "visual", "media", "content"),
        "data and input modeling": ("input", "data", "behavior"),
        "safety and risk review": ("risk", "safety", "security"),
    }
    stage_text = _normalized_words(*(stage.stage_key for stage in plan.stages), *(stage.display_name for stage in plan.stages))
    for skill, required_tokens in skill_stage_requirements.items():
        if skill in analysis.skills and not any(token in stage_text for token in required_tokens):
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code="semantic.skill_missing",
                message=f"The generated protocol inferred {skill} but did not create a visible stage for it.",
                severity="error",
                section="semantic_coverage",
                action="repair_generated_protocol",
            ))

    reviewed_work_stage_keys = {
        stage.review_of_stage_key
        for stage in plan.stages
        if stage.stage_kind in {"review", "acceptance"} and str(stage.review_of_stage_key or "").strip()
    }
    for stage in plan.stages:
        if stage.stage_kind != "work" or not stage.outputs:
            continue
        if stage.stage_key not in reviewed_work_stage_keys:
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code="semantic.work_review_missing",
                message=(
                    f"The generated work stage '{stage.display_name or stage.stage_key}' produces artifacts "
                    "but has no direct critical review stage."
                ),
                severity="error",
                section="semantic_coverage",
                action="repair_generated_protocol",
            ))

    review_role_usage: dict[str, int] = {}
    for stage in plan.stages:
        if stage.stage_kind == "review":
            review_role_usage[stage.role_key] = review_role_usage.get(stage.role_key, 0) + 1
    reused_review_roles = sorted(role_key for role_key, count in review_role_usage.items() if count > 1)
    if reused_review_roles:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="semantic.review_context_not_isolated",
            message=(
                "Generated review stages reuse participant keys, which can reduce independent review context: "
                f"{', '.join(reused_review_roles[:6])}."
            ),
            severity="error",
            section="semantic_coverage",
            action="repair_generated_protocol",
        ))

    if not unresolved:
        warnings.append(ProtocolAutoDesignWarningRecord(
            code="semantic.coverage_ready",
            message="Requirement coverage passed: work packages, artifacts, isolated reviews, primary artifact, and final acceptance reference the material request.",
            severity="info",
            section="semantic_coverage",
            action="review_generated_protocol",
        ))
    return warnings, unresolved


def _warnings_for_session(
    request: ProtocolAutoDesignRequestRecord,
    validation: ProtocolValidationResultRecord,
) -> tuple[list[ProtocolAutoDesignWarningRecord], list[ProtocolAutoDesignWarningRecord]]:
    warnings: list[ProtocolAutoDesignWarningRecord] = []
    unresolved: list[ProtocolAutoDesignWarningRecord] = []
    if not request.available_agents:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="assignments.no_connected_agents",
            message="No connected agents were available while generating this protocol. Resolve stage assignments before publish or run.",
            severity="warning",
            section="assignments",
            action="choose_stage_agents",
        ))
    for issue in validation.issues:
        if str(issue.code or "").startswith("stage.selector_"):
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code=issue.code,
                message=issue.message,
                severity="error" if issue.blocking else "warning",
                section="assignments",
                action="choose_stage_agents",
            ))
        elif issue.blocking:
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code=issue.code,
                message=issue.message,
                severity="error",
                section=issue.section,
                action="repair_generated_protocol",
            ))
    if validation.ok:
        warnings.append(ProtocolAutoDesignWarningRecord(
            code="review.before_publish",
            message="Review the generated stages, artifacts, and assignments before publishing.",
            severity="info",
            section="review",
            action="review_generated_protocol",
        ))
    return warnings, unresolved


def _planner_warnings_for_session(
    model_response: ProtocolAutoDesignModelResponseRecord | None,
) -> tuple[list[ProtocolAutoDesignWarningRecord], list[ProtocolAutoDesignWarningRecord]]:
    warnings: list[ProtocolAutoDesignWarningRecord] = []
    unresolved: list[ProtocolAutoDesignWarningRecord] = []
    if model_response is None:
        return warnings, unresolved
    for index, warning in enumerate(model_response.warnings):
        if isinstance(warning, str):
            message = warning.strip()
            if not message:
                continue
            normalized = ProtocolAutoDesignWarningRecord(
                code=f"planner.warning_{index + 1}",
                message=message,
                severity="warning",
                section="planner",
                action="review_generated_protocol",
            )
        else:
            normalized = warning
        if not normalized.code:
            normalized = normalized.model_copy(update={"code": "planner.warning"})
        if not normalized.message:
            continue
        if normalized.severity == "error":
            unresolved.append(normalized)
        else:
            warnings.append(normalized)
    return warnings, unresolved


def _dedupe_auto_protocol_warnings(
    warnings: Sequence[ProtocolAutoDesignWarningRecord],
) -> list[ProtocolAutoDesignWarningRecord]:
    deduped: list[ProtocolAutoDesignWarningRecord] = []
    seen: set[tuple[str, str, str, str]] = set()
    for warning in warnings:
        item = ProtocolAutoDesignWarningRecord.model_validate(warning)
        key = (
            str(item.code or "").strip(),
            str(item.message or "").strip(),
            str(item.severity or "").strip(),
            str(item.section or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def auto_protocol_event_summary(
    session: ProtocolAutoDesignSessionRecord,
    *,
    event_kind: str = "",
    created_at: str = "",
) -> ProtocolAutoDesignEventSummaryRecord:
    run_id = ""
    if session.run_result is not None:
        run_id = str(session.run_result.run.protocol_run_id if session.run_result.run is not None else "")
    return ProtocolAutoDesignEventSummaryRecord(
        event_kind=str(event_kind or "").strip(),
        session_status=str(session.status or ""),
        target_protocol_id=str(session.target_protocol_id or ""),
        source_protocol_id=str(session.source_protocol_id or ""),
        run_id=run_id,
        warning_codes=[
            str(item.code or "").strip()
            for item in session.warnings
            if str(item.code or "").strip()
        ],
        blocker_codes=[
            str(item.code or "").strip()
            for item in session.unresolved_decisions
            if str(item.code or "").strip()
        ],
        unresolved_count=len(session.unresolved_decisions),
        stage_count=len(session.plan.stages),
        package_count=len(session.analysis.work_packages),
        primary_artifact_key=str(session.plan.primary_artifact.artifact_key or ""),
        change_summary=list(session.change_summary or [])[:10],
        actor_ref=str(session.actor_ref or ""),
        created_at=str(created_at or session.updated_at or session.created_at or ""),
    )


def generate_auto_protocol_session(
    request: ProtocolAutoDesignRequestRecord,
    *,
    session_id: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> ProtocolAutoDesignSessionRecord:
    if request.model_response is not None:
        analysis = _analysis_from_model_response(request, request.model_response)
    else:
        analysis = _analyze_requirement(request.requirement_text, request.constraints_text)
    plan = _build_plan(request, analysis)
    draft = compile_auto_protocol_plan(
        plan,
        requirement_text=request.requirement_text,
        constraints_text=request.constraints_text,
    )
    draft, validation, repair_notes = _validate_and_repair_protocol_document(draft, request)
    warnings, unresolved = _warnings_for_session(request, validation)
    semantic_warnings, semantic_unresolved = _semantic_warnings_for_session(analysis, plan)
    planner_warnings, planner_unresolved = _planner_warnings_for_session(request.model_response)
    warnings.extend(semantic_warnings)
    warnings.extend(planner_warnings)
    unresolved.extend(semantic_unresolved)
    unresolved.extend(planner_unresolved)
    if request.model_response is None:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="planner.model_response_missing",
            message=(
                "Auto Protocol generation requires provider-backed semantic planning. "
                "No structured planner response was available for this session."
            ),
            severity="error",
            section="planner",
            action="retry_generation",
        ))
    elif not request.model_response.work_packages:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="planner.work_packages_missing",
            message="The semantic planner did not return work packages. Revise the request or retry generation.",
            severity="error",
            section="planner",
            action="retry_generation",
        ))
    elif request.model_response.open_questions:
        unresolved.append(ProtocolAutoDesignWarningRecord(
            code="planner.open_questions",
            message=(
                "The planner reported open questions that block a commercially reliable protocol: "
                + "; ".join(str(item or "").strip() for item in request.model_response.open_questions[:4] if str(item or "").strip())
            ),
            severity="error",
            section="planner",
            action="revise_requirement",
        ))
    status: ProtocolAutoDesignStatus = "ready" if validation.ok and not unresolved else ("blocked" if validation.ok else "failed")
    session = ProtocolAutoDesignSessionRecord(
        session_id=session_id,
        status=status,
        mode=request.mode,
        surface=request.surface,
        actor_ref=request.actor_ref,
        chat_ref=request.chat_ref,
        source_protocol_id=request.target_protocol_id,
        source_version_id=request.target_version_id,
        source_draft_revision=request.target_draft_revision,
        target_protocol_id=request.target_protocol_id,
        target_draft_revision=request.target_draft_revision,
        requirement_text=request.requirement_text,
        constraints_text=request.constraints_text,
        model_response=request.model_response,
        analysis=analysis,
        plan=plan,
        draft_definition_json=RegistryJsonRecord.model_validate(draft),
        run_profile=plan.run_profile,
        validation=validation,
        warnings=warnings,
        unresolved_decisions=unresolved,
        change_summary=[
            f"Generated a requirement-specific protocol with {len(plan.stages)} stages.",
            f"Declared {len(plan.artifacts)} artifacts and {len(plan.roles)} participant roles.",
            "Included review/revision gates and final evidence.",
            *repair_notes,
        ],
        created_at=created_at,
        updated_at=updated_at,
    )
    return session.model_copy(update={
        "event_summary": auto_protocol_event_summary(session, event_kind="generated", created_at=updated_at or created_at),
    })


def revise_auto_protocol_session(
    request: ProtocolAutoDesignRequestRecord,
    *,
    session_id: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> ProtocolAutoDesignSessionRecord:
    source = request.source_document.as_dict()
    if not source:
        return generate_auto_protocol_session(request, session_id=session_id, created_at=created_at, updated_at=updated_at)
    draft = draft_protocol_document_data(source)
    metadata = dict(draft.get("metadata") or {})
    auto_meta = dict(metadata.get("auto_protocol") or {})
    change_request = _revision_request_from_text(request.requirement_text)
    previous_requirement = _source_requirement_from_auto_metadata(metadata, auto_meta)
    combined_requirement = _revision_planner_requirement(previous_requirement, change_request)
    canonical_requirement = _revision_run_objective(previous_requirement, change_request, request.model_response)

    existing_revisions = [str(item or "").strip() for item in _list(auto_meta.get("revision_requests")) if str(item or "").strip()]
    revisions = _dedupe_text_items(
        [
            *existing_revisions,
            *_labeled_auto_context_values(auto_meta.get("requirement"), _AUTO_REVISION_LABELS),
            *_labeled_auto_context_values(request.requirement_text, _AUTO_REVISION_LABELS),
            change_request,
        ],
        max_items=_AUTO_REVISION_HISTORY_MAX,
        max_chars=_AUTO_REQUIREMENT_CONTEXT_MAX_CHARS,
    )
    regenerate_request = request.model_copy(update={
        "mode": "revise",
        "requirement_text": combined_requirement,
        "source_document": RegistryJsonRecord.model_validate(draft),
    })
    session = generate_auto_protocol_session(
        regenerate_request,
        session_id=session_id,
        created_at=created_at,
        updated_at=updated_at,
    )
    regenerated_draft = session.draft_definition_json.as_dict()
    regenerated_metadata = dict(regenerated_draft.get("metadata") or {})
    if metadata.get("slug"):
        regenerated_metadata["slug"] = str(metadata.get("slug") or "")
    if metadata.get("display_name"):
        regenerated_metadata["display_name"] = str(metadata.get("display_name") or "")
    source_description = _compact_auto_protocol_context_text(metadata.get("description"), max_chars=420)
    if source_description:
        regenerated_metadata["description"] = source_description
    elif canonical_requirement:
        regenerated_metadata["description"] = _sentence(canonical_requirement)
    regenerated_auto_meta = dict(regenerated_metadata.get("auto_protocol") or {})
    regenerated_auto_meta.update({
        "generated": True,
        "requirement": canonical_requirement,
        "revision_of_protocol_id": str(request.target_protocol_id or ""),
        "revision_of_version_id": str(request.target_version_id or ""),
        "revision_requests": revisions[-_AUTO_REVISION_HISTORY_MAX:],
    })
    regenerated_metadata["auto_protocol"] = regenerated_auto_meta
    compact_profile = _run_profile_with_problem_statement(session.run_profile, canonical_requirement)
    regenerated_metadata["run_inputs"] = compact_profile.run_inputs
    regenerated_draft["metadata"] = regenerated_metadata
    regenerated_draft, validation, repair_notes = _validate_and_repair_protocol_document(regenerated_draft, regenerate_request)
    warnings, unresolved = _warnings_for_session(regenerate_request, validation)
    semantic_warnings, semantic_unresolved = _semantic_warnings_for_session(session.analysis, session.plan)
    warnings = _dedupe_auto_protocol_warnings([
        *session.warnings,
        *warnings,
        *semantic_warnings,
    ])
    unresolved = _dedupe_auto_protocol_warnings([
        *session.unresolved_decisions,
        *unresolved,
        *semantic_unresolved,
    ])
    status: ProtocolAutoDesignStatus = "ready" if validation.ok and not unresolved else ("blocked" if validation.ok else "failed")
    compact_plan = session.plan.model_copy(update={
        "protocol_name": str(regenerated_metadata.get("display_name") or "").strip()
            or _title_from_requirement(canonical_requirement),
        "protocol_slug": str(regenerated_metadata.get("slug") or "").strip()
            or _slugify(canonical_requirement),
        "description": _sentence(canonical_requirement) or session.plan.description,
        "run_profile": compact_profile,
    })
    revised_session = session.model_copy(update={
        "status": status,
        "mode": "revise",
        "source_protocol_id": request.target_protocol_id,
        "source_version_id": request.target_version_id,
        "source_draft_revision": request.target_draft_revision,
        "target_protocol_id": request.target_protocol_id,
        "target_draft_revision": request.target_draft_revision,
        "requirement_text": request.requirement_text,
        "constraints_text": request.constraints_text,
        "plan": compact_plan,
        "run_profile": compact_profile,
        "draft_definition_json": RegistryJsonRecord.model_validate(regenerated_draft),
        "validation": validation,
        "warnings": warnings,
        "unresolved_decisions": unresolved,
        "change_summary": [
            "Regenerated the selected protocol through the canonical requirement-specific compiler.",
            "Preserved the target protocol identity for apply, publish, and run.",
            *repair_notes,
        ],
    })
    return revised_session.model_copy(update={
        "event_summary": auto_protocol_event_summary(
            revised_session,
            event_kind="revised",
            created_at=updated_at or created_at,
        ),
    })


def auto_protocol_render_cards(session: ProtocolAutoDesignSessionRecord) -> list[ProtocolAutoDesignRenderCardRecord]:
    plan = session.plan
    validation = session.validation
    review_count = sum(1 for stage in plan.stages if stage.stage_kind == "review")
    cards = [
        ProtocolAutoDesignRenderCardRecord(
            title=plan.protocol_name or "Generated protocol",
            body=session.analysis.goal or plan.description,
            facts=[
                {"label": "Focus", "value": session.analysis.focus or session.analysis.domain},
                {"label": "Skills", "value": ", ".join(session.analysis.skills[:4])},
                {"label": "Work packages", "value": str(len(session.analysis.work_packages))},
                {"label": "Reviews", "value": str(review_count)},
                {"label": "Stages", "value": str(len(plan.stages))},
                {"label": "Artifacts", "value": str(len(plan.artifacts))},
                {"label": "Validation", "value": "ready" if validation.ok else "needs attention"},
            ],
            actions=["stages", "artifacts", "warnings", "apply"],
        )
    ]
    for index, stage in enumerate(plan.stages, start=1):
        cards.append(ProtocolAutoDesignRenderCardRecord(
            title=f"Stage {index}: {stage.display_name}",
            body=stage.purpose,
            facts=[
                {"label": "Kind", "value": stage.stage_kind},
                {"label": "Role", "value": stage.role_key},
                {"label": "Outputs", "value": ", ".join(stage.outputs) if stage.outputs else "none"},
            ],
            actions=["back", "next", "modify"],
        ))
    if session.warnings or session.unresolved_decisions:
        cards.append(ProtocolAutoDesignRenderCardRecord(
            title="Warnings",
            body="\n".join(item.message for item in [*session.unresolved_decisions, *session.warnings]),
            facts=[],
            actions=["modify", "open_registry"],
        ))
    return cards


def protocol_run_create_from_auto_session(
    session: ProtocolAutoDesignSessionRecord,
    *,
    protocol_id: str,
    entry_agent_id: str,
    root_conversation_id: str = "",
    origin_channel: str = "",
) -> ProtocolRunCreateRecord:
    profile = session.run_profile
    constraints = {
        "context": profile.context,
        "constraints": profile.constraints,
        "acceptance_criteria": profile.acceptance_criteria,
    }
    return ProtocolRunCreateRecord(
        protocol_id=protocol_id,
        entry_agent_id=entry_agent_id,
        root_conversation_id=root_conversation_id,
        origin_channel=origin_channel,
        workspace_ref=profile.workspace_ref,
        problem_statement=profile.problem_statement or session.requirement_text,
        constraints_json=RegistryJsonRecord.model_validate({
            key: value for key, value in constraints.items() if str(value or "").strip()
        }),
    )


__all__ = [
    "ProtocolAutoDesignMode",
    "ProtocolAutoDesignSurface",
    "ProtocolAutoDesignStatus",
    "ProtocolAutoDesignSeverity",
    "ProtocolAutoDesignWarningRecord",
    "ProtocolAutoDesignRolePlanRecord",
    "ProtocolAutoDesignArtifactPlanRecord",
    "ProtocolAutoDesignPrimaryArtifactRecord",
    "ProtocolAutoDesignReviewPolicyRecord",
    "ProtocolAutoDesignWorkPackageRecord",
    "ProtocolAutoDesignStagePlanRecord",
    "ProtocolAutoDesignRunProfileRecord",
    "ProtocolAutoDesignAnalysisRecord",
    "ProtocolAutoDesignPlanRecord",
    "ProtocolAutoDesignModelRequestRecord",
    "ProtocolAutoDesignModelResponseRecord",
    "ProtocolAutoDesignEventSummaryRecord",
    "ProtocolAutoDesignChangeSummaryRecord",
    "ProtocolAutoDesignRequestRecord",
    "ProtocolAutoDesignSessionRecord",
    "ProtocolAutoDesignRenderCardRecord",
    "auto_protocol_runtime_expected_from_text",
    "auto_protocol_event_summary",
    "compile_auto_protocol_plan",
    "generate_auto_protocol_session",
    "revise_auto_protocol_session",
    "auto_protocol_render_cards",
    "protocol_run_create_from_auto_session",
]
