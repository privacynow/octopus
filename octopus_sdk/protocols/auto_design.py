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

ProtocolAutoDesignMode = Literal["create", "revise", "explain"]
ProtocolAutoDesignSurface = Literal["registry", "telegram", "api"]
ProtocolAutoDesignStatus = Literal["draft", "ready", "blocked", "applied", "published", "running", "failed"]
ProtocolAutoDesignSeverity = Literal["info", "warning", "error"]


def _slugify(value: str, *, fallback: str = "auto-protocol") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        text = fallback
    if len(text) > 64:
        text = text[:64].rstrip("-") or fallback
    return text


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


def _normalized_words(*values: object) -> str:
    return " ".join(str(value or "").lower() for value in values if str(value or "").strip())


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
    capabilities: list[str] = Field(default_factory=list)
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
    analysis: ProtocolAutoDesignAnalysisRecord = Field(default_factory=ProtocolAutoDesignAnalysisRecord)
    plan: ProtocolAutoDesignPlanRecord = Field(default_factory=ProtocolAutoDesignPlanRecord)
    draft_definition_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    run_profile: ProtocolAutoDesignRunProfileRecord = Field(default_factory=ProtocolAutoDesignRunProfileRecord)
    validation: ProtocolValidationResultRecord = Field(default_factory=ProtocolValidationResultRecord)
    warnings: list[ProtocolAutoDesignWarningRecord] = Field(default_factory=list)
    unresolved_decisions: list[ProtocolAutoDesignWarningRecord] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
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


def _analysis_capabilities(text: str) -> list[str]:
    """Infer workflow capabilities without selecting a closed use-case template."""
    capabilities = ["requirements planning", "implementation", "verification", "acceptance evidence"]
    signals = [
        (
            "domain grounding",
            ("accurate", "factual", "research", "source", "sources", "evidence", "audit", "regulated", "compliance"),
        ),
        (
            "experience design",
            ("user", "human", "usable", "readable", "intuitive", "beautiful", "polished", "responsive", "controls"),
        ),
        (
            "supporting asset planning",
            ("asset", "assets", "visual", "image", "images", "audio", "sound", "content", "background", "graphic"),
        ),
        (
            "data and input modeling",
            ("data", "dataset", "records", "metrics", "analysis", "reporting", "loading"),
        ),
        (
            "safety and risk review",
            ("safe", "safety", "secure", "security", "risk", "threat", "abuse", "privacy"),
        ),
    ]
    for capability, tokens in signals:
        if _has_any(text, tokens) and capability not in capabilities:
            capabilities.append(capability)
    return capabilities


def _focus_label(requirement_text: str) -> str:
    title = _title_from_requirement(requirement_text)
    if title == "Auto Protocol":
        return "Requirement-specific workflow"
    return title


def _analyze_requirement(requirement_text: str, constraints_text: str) -> ProtocolAutoDesignAnalysisRecord:
    text = _normalized_words(requirement_text, constraints_text)
    terms = _requirement_terms(requirement_text, constraints_text)
    capabilities = _analysis_capabilities(text)
    deliverables = _requirement_phrases(requirement_text)
    complexity_signals = sum(1 for capability in capabilities if capability not in {"requirements planning", "implementation", "verification", "acceptance evidence"})
    complexity = "high" if complexity_signals >= 2 or len(text) > 700 or len(deliverables) >= 4 else "standard"
    goal = _sentence(requirement_text) or "Create the requested outcome."
    assumptions = [
        "The generated protocol should be reviewed before publish.",
        "Stage instructions should carry the work contract so launch text can stay simple.",
        "The workflow is composed from requirement coverage and reusable protocol primitives, not a closed use-case template.",
    ]
    risks = [
        "Assignments may need local agent mapping before publish/run.",
        "A requirement-specific workflow can still miss intent if the user leaves critical constraints implicit.",
    ]
    if "domain grounding" in capabilities:
        risks.append("Factual or domain-sensitive claims need explicit grounding and review evidence.")
    if "experience design" in capabilities:
        risks.append("Human-facing outcomes need usability and polish review, not only functional completion.")
    if "safety and risk review" in capabilities:
        risks.append("Risk-sensitive outcomes need explicit safety or security review before acceptance.")

    required_roles = ["workflow planner", "coverage reviewer", "implementation owner", "verification lead", "readiness reviewer"]
    if "domain grounding" in capabilities:
        required_roles.insert(2, "domain grounding reviewer")
    if "experience design" in capabilities:
        required_roles.insert(-2, "experience designer")
    if "supporting asset planning" in capabilities:
        required_roles.insert(-2, "supporting asset planner")
    if "data and input modeling" in capabilities:
        required_roles.insert(2, "input modeler")
    if "safety and risk review" in capabilities:
        required_roles.insert(-1, "risk reviewer")

    expected_artifacts = ["requirements coverage plan", "produced outcome", "verification report", "release evidence"]
    if "domain grounding" in capabilities:
        expected_artifacts.insert(1, "domain grounding notes")
    if "experience design" in capabilities:
        expected_artifacts.insert(-2, "experience design")
    if "supporting asset planning" in capabilities:
        expected_artifacts.insert(-2, "supporting asset plan")
    if "data and input modeling" in capabilities:
        expected_artifacts.insert(1, "input model")
    if "safety and risk review" in capabilities:
        expected_artifacts.insert(-1, "risk review")

    return ProtocolAutoDesignAnalysisRecord(
        domain="requirement-specific",
        complexity=complexity,
        goal=goal,
        focus=_focus_label(requirement_text),
        requirement_terms=terms,
        capabilities=capabilities,
        deliverables=deliverables,
        assumptions=assumptions,
        risks=risks,
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


def _base_run_profile(requirement: str, constraints: str, workspace_ref: str) -> ProtocolAutoDesignRunProfileRecord:
    return ProtocolAutoDesignRunProfileRecord(
        problem_statement=_sentence(requirement) or "Run the generated workflow.",
        context="Use the protocol stages as the work contract. Add only run-specific facts here.",
        constraints=_sentence(constraints),
        acceptance_criteria="Complete every stage, produce declared artifacts, record review decisions, and finish with inspection-ready evidence.",
        workspace_ref=str(workspace_ref or "").strip(),
        run_inputs=[
            {
                "key": "goal",
                "label": "Goal",
                "kind": "textarea",
                "required": True,
                "default_value": _sentence(requirement),
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
    run_profile = _base_run_profile(requirement, constraints, request.workspace_ref)
    capabilities = set(analysis.capabilities)
    coverage_terms = ", ".join(analysis.requirement_terms[:14]) or "the explicit user requirement"
    request_scope = _sentence(requirement) or "Create the requested outcome."

    roles = [
        _role("planner", "Workflow Planner", "Turn the user request into an explicit plan, coverage map, assumptions, and acceptance criteria.", agents, skills),
        _role("coverage_reviewer", "Coverage Reviewer", "Verify that the generated workflow covers the user requirement before production starts.", agents, skills),
    ]
    if "data and input modeling" in capabilities:
        roles.append(_role("input_modeler", "Input Modeler", "Define required inputs, data shape, loading path, validation rules, and assumptions.", agents, skills))
    if "domain grounding" in capabilities:
        roles.append(_role("domain_reviewer", "Domain Grounding Reviewer", "Check factual grounding, domain assumptions, sources, and boundary conditions.", agents, skills))
    if "experience design" in capabilities:
        roles.append(_role("experience_designer", "Experience Designer", "Design the human-facing flow, interaction model, readability, and polish criteria.", agents, skills))
    if "supporting asset planning" in capabilities:
        roles.append(_role("asset_planner", "Supporting Asset Planner", "Specify supporting media, content, assets, or other non-code inputs required by the outcome.", agents, skills))
    roles.extend([
        _role("implementer", "Implementation Owner", "Produce the requested outcome from the accepted plan and declared inputs.", agents, skills),
        _role("verifier", "Verification Lead", "Run checks against acceptance criteria, artifacts, and requirement coverage.", agents, skills),
    ])
    if "safety and risk review" in capabilities:
        roles.append(_role("risk_reviewer", "Risk Reviewer", "Review safety, security, operational, privacy, or abuse risks before final acceptance.", agents, skills))
    roles.append(_role("readiness_reviewer", "Readiness Reviewer", "Accept final evidence or send work back with concrete fixes.", agents, skills))

    artifacts = [
        _artifact("requirements_plan", "Requirements Coverage Plan", "Goal, constraints, assumptions, deliverables, acceptance criteria, and coverage terms.", "protocol/auto/requirements-coverage-plan.md"),
    ]
    if "data and input modeling" in capabilities:
        artifacts.append(_artifact("input_model", "Input Model", "Inputs, data shapes, loading path, validation rules, and assumptions needed by the outcome.", "protocol/auto/input-model.md"))
    if "domain grounding" in capabilities:
        artifacts.append(_artifact("domain_grounding", "Domain Grounding Notes", "Factual grounding, sources, assumptions, and disputed or uncertain claims.", "protocol/auto/domain-grounding.md"))
    if "experience design" in capabilities:
        artifacts.append(_artifact("experience_design", "Experience Design", "Human-facing flow, interaction model, responsiveness, polish criteria, and inspection notes.", "protocol/auto/experience-design.md"))
    if "supporting asset planning" in capabilities:
        artifacts.append(_artifact("supporting_assets", "Supporting Asset Plan", "Required supporting media, content, generated assets, source files, or input material.", "protocol/auto/supporting-assets.md"))
    artifacts.extend([
        _artifact("produced_outcome", "Produced Outcome", "The primary deliverable requested by the user.", "protocol/auto/output"),
        _artifact("verification_report", "Verification Report", "Checks, results, defects, gaps, and requirement coverage evidence.", "protocol/auto/verification-report.md"),
    ])
    if "safety and risk review" in capabilities:
        artifacts.append(_artifact("risk_review", "Risk Review", "Safety, security, privacy, operational, or abuse-risk review evidence.", "protocol/auto/risk-review.md"))
    artifacts.append(_artifact("release_evidence", "Release Evidence", "Final summary of artifacts, reviews, remaining risks, and inspection steps.", "protocol/auto/release-evidence.md"))

    stages = [
        _stage(
            "plan_requirements",
            "Map requirement and acceptance criteria",
            "work",
            "planner",
            f"Create a requirements coverage plan for: {request_scope} Explicitly cover these terms or phrases: {coverage_terms}. Capture assumptions, constraints, deliverables, required capabilities, and acceptance criteria.",
            outputs=["requirements_plan"],
        ),
        _stage(
            "review_requirements",
            "Review requirement coverage",
            "review",
            "coverage_reviewer",
            "Accept only if the plan maps every material part of the user request to a stage, artifact, acceptance criterion, or explicit assumption. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
            inputs=["requirements_plan"],
            review_of="plan_requirements",
        ),
    ]

    planning_outputs = ["requirements_plan"]
    if "data and input modeling" in capabilities:
        stages.extend([
            _stage(
                "model_inputs",
                "Model required inputs",
                "work",
                "input_modeler",
                f"Define the inputs needed to produce the requested outcome. Preserve requirement coverage for: {coverage_terms}. Include loading, validation, examples, and assumptions where applicable.",
                inputs=list(planning_outputs),
                outputs=["input_model"],
            ),
            _stage(
                "review_inputs",
                "Review input model",
                "review",
                "coverage_reviewer",
                "Accept only if the input model is understandable, sufficient for the requested outcome, and testable. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
                inputs=["requirements_plan", "input_model"],
                review_of="model_inputs",
            ),
        ])
        planning_outputs.append("input_model")
    if "domain grounding" in capabilities:
        stages.extend([
            _stage(
                "establish_domain_grounding",
                "Establish domain grounding",
                "work",
                "domain_reviewer",
                f"Record the factual, domain, source, and boundary assumptions required by the request. Explicitly address: {coverage_terms}.",
                inputs=list(planning_outputs),
                outputs=["domain_grounding"],
            ),
            _stage(
                "review_domain_grounding",
                "Review domain grounding",
                "review",
                "coverage_reviewer",
                "Accept only if factual and domain-sensitive assumptions are explicit, grounded, and safe to use in later stages. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
                inputs=["requirements_plan", "domain_grounding"],
                review_of="establish_domain_grounding",
            ),
        ])
        planning_outputs.append("domain_grounding")
    if "experience design" in capabilities:
        stages.extend([
            _stage(
                "design_experience",
                "Design user-facing experience",
                "work",
                "experience_designer",
                f"Design the human-facing flow and quality bar for the requested outcome. Make the path intuitive, readable, and inspectable while preserving: {coverage_terms}.",
                inputs=list(planning_outputs),
                outputs=["experience_design"],
            ),
            _stage(
                "review_experience",
                "Review experience design",
                "review",
                "coverage_reviewer",
                "Accept only if the design is usable, clear, responsive where relevant, and tied to the acceptance criteria. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
                inputs=["requirements_plan", "experience_design"],
                review_of="design_experience",
            ),
        ])
        planning_outputs.append("experience_design")
    if "supporting asset planning" in capabilities:
        stages.extend([
            _stage(
                "plan_supporting_assets",
                "Plan supporting assets and content",
                "work",
                "asset_planner",
                f"Specify the supporting assets, content, media, source material, or generated inputs needed by the final outcome. Preserve requirement coverage for: {coverage_terms}.",
                inputs=list(planning_outputs),
                outputs=["supporting_assets"],
            ),
            _stage(
                "review_supporting_assets",
                "Review supporting asset plan",
                "review",
                "coverage_reviewer",
                "Accept only if the supporting asset plan is complete enough to produce and verify the final outcome. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
                inputs=["requirements_plan", "supporting_assets"],
                review_of="plan_supporting_assets",
            ),
        ])
        planning_outputs.append("supporting_assets")

    stages.extend([
        _stage(
            "produce_outcome",
            "Produce requested outcome",
            "work",
            "implementer",
            f"Produce the requested outcome from the accepted plan and supporting artifacts. The output must visibly satisfy the requirement coverage terms: {coverage_terms}.",
            inputs=list(planning_outputs),
            outputs=["produced_outcome"],
        ),
        _stage(
            "verify_outcome",
            "Verify outcome against requirement",
            "work",
            "verifier",
            "Run focused checks against the acceptance criteria, declared artifacts, and coverage plan. Record commands, manual checks, defects, gaps, and unresolved risks.",
            inputs=[*planning_outputs, "produced_outcome"],
            outputs=["verification_report"],
        ),
    ])
    if "safety and risk review" in capabilities:
        stages.append(_stage(
            "review_risk",
            "Review risk and safety",
            "review",
            "risk_reviewer",
            "Accept only if safety, security, privacy, abuse, and operational risks have been considered and any residual risks are explicit. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
            inputs=["requirements_plan", "produced_outcome", "verification_report"],
            outputs=["risk_review"],
            review_of="produce_outcome",
        ))
    stages.extend([
        _stage(
            "review_outcome",
            "Review produced outcome",
            "review",
            "readiness_reviewer",
            "Accept only if the outcome satisfies the requirement coverage plan, verification is meaningful, and the result is usable by the intended human. End with PROTOCOL_DECISION and PROTOCOL_SUMMARY.",
            inputs=["requirements_plan", "produced_outcome", "verification_report"],
            review_of="produce_outcome",
        ),
        _stage(
            "final_evidence",
            "Prepare release evidence",
            "acceptance",
            "readiness_reviewer",
            "Summarize the produced artifacts, accepted reviews, verification evidence, remaining risks, and exact inspection steps. End with PROTOCOL_DECISION: accept or fail and PROTOCOL_SUMMARY.",
            inputs=[artifact.artifact_key for artifact in artifacts if artifact.artifact_key != "release_evidence"],
            outputs=["release_evidence"],
        ),
    ])

    return ProtocolAutoDesignPlanRecord(
        protocol_name=title,
        protocol_slug=slug,
        description=description,
        roles=roles,
        artifacts=artifacts,
        stages=stages,
        run_profile=run_profile,
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
            transitions = {"accept": "__complete__", "fail": "__failed__"}
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
            "max_review_rounds": 5,
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
                "path": "protocol/auto/output.md",
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
            artifact["path"] = f"protocol/auto/{_slugify(str(artifact.get('artifact_key') or f'artifact-{index + 1}'))}.md"
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
                        "path": f"protocol/auto/{_slugify(artifact_key)}.md",
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

    capability_stage_requirements = {
        "domain grounding": "domain",
        "experience design": "experience",
        "supporting asset planning": "supporting",
        "data and input modeling": "input",
        "safety and risk review": "risk",
    }
    stage_text = _normalized_words(*(stage.stage_key for stage in plan.stages), *(stage.display_name for stage in plan.stages))
    for capability, required_text in capability_stage_requirements.items():
        if capability in analysis.capabilities and required_text not in stage_text:
            unresolved.append(ProtocolAutoDesignWarningRecord(
                code="semantic.capability_missing",
                message=f"The generated protocol inferred {capability} but did not create a visible stage for it.",
                severity="error",
                section="semantic_coverage",
                action="repair_generated_protocol",
            ))

    if not unresolved:
        warnings.append(ProtocolAutoDesignWarningRecord(
            code="semantic.coverage_ready",
            message="Requirement coverage passed: stages, artifacts, reviews, and final evidence reference the material request.",
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


def generate_auto_protocol_session(
    request: ProtocolAutoDesignRequestRecord,
    *,
    session_id: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> ProtocolAutoDesignSessionRecord:
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
    warnings.extend(semantic_warnings)
    unresolved.extend(semantic_unresolved)
    status: ProtocolAutoDesignStatus = "ready" if validation.ok and not unresolved else ("blocked" if validation.ok else "failed")
    return ProtocolAutoDesignSessionRecord(
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
    changes = list(auto_meta.get("revision_requests") or [])
    change_request = str(request.requirement_text or "").strip()
    if change_request:
        changes.append(change_request)
    auto_meta["generated"] = bool(auto_meta.get("generated", False))
    auto_meta["revision_requests"] = changes[-20:]
    metadata["auto_protocol"] = auto_meta
    draft["metadata"] = metadata

    lower = change_request.lower()
    inserted: list[str] = []
    stages = [dict(item) for item in draft.get("stages", []) if isinstance(item, Mapping)]
    participants = [dict(item) for item in draft.get("participants", []) if isinstance(item, Mapping)]
    artifacts = [dict(item) for item in draft.get("artifacts", []) if isinstance(item, Mapping)]
    participant_keys = {str(item.get("participant_key", "") or "").strip() for item in participants}
    artifact_keys = {str(item.get("artifact_key", "") or "").strip() for item in artifacts}

    def ensure_participant(key: str, name: str, instructions: str) -> None:
        if key in participant_keys:
            return
        participants.append({"participant_key": key, "display_name": name, "instructions": instructions})
        participant_keys.add(key)

    def ensure_artifact(key: str, name: str, description: str, path: str) -> None:
        if key in artifact_keys:
            return
        artifacts.append({
            "artifact_key": key,
            "display_name": name,
            "description": description,
            "kind": "workspace_file",
            "path": path,
            "verify": True,
        })
        artifact_keys.add(key)

    def insert_review_stage(key: str, name: str, participant: str, artifact_key: str, focus: str) -> None:
        if any(str(item.get("stage_key", "") or "") == key for item in stages):
            return
        selector = {"kind": "skill", "value": _slugify(participant)}
        for item in request.available_agents:
            agent = item.as_dict()
            if str(agent.get("agent_id") or "").strip():
                selector = {"kind": "agent", "value": str(agent.get("agent_id") or "").strip()}
                break
        stage = {
            "stage_key": key,
            "display_name": name,
            "participant_key": participant,
            "selector": selector,
            "stage_kind": "review",
            "instructions": (
                f"Review the protocol output for {focus}. Accept only if the prior work is specific, usable, "
                "and satisfies this concern. End with PROTOCOL_DECISION: accept, revise, or fail and PROTOCOL_SUMMARY."
            ),
            "inputs": [artifact_key] if artifact_key else [],
            "outputs": [],
            "transitions": {"accept": "__complete__", "revise": stages[-1]["stage_key"] if stages else "__failed__", "fail": "__failed__"},
            "write_capable": False,
            "max_rounds": 0,
            "strict_completion": True,
            "require_output_verification": None,
            "timeout_seconds": 0,
        }
        if stages:
            previous = stages[-1]
            previous_transitions = dict(previous.get("transitions") or {})
            for decision, target in list(previous_transitions.items()):
                if str(target or "") == "__complete__":
                    previous_transitions[decision] = key
            previous["transitions"] = previous_transitions or {"completed": key}
        stages.append(stage)
        inserted.append(name)

    if any(token in lower for token in ("security", "safety", "threat", "vulnerability")):
        ensure_participant("security_reviewer", "Security Reviewer", "Review safety, security, abuse, and operational risk.")
        ensure_artifact("security_review", "Security Review", "Security and safety review evidence.", "protocol/auto/security-review.md")
        insert_review_stage("security_review", "Review security and safety", "security_reviewer", "security_review", "security and safety risk")
    if any(token in lower for token in ("ux", "ui", "usable", "readable", "responsive", "beautiful")):
        ensure_participant("ux_reviewer", "UX Reviewer", "Review user experience, readability, visual quality, and responsiveness.")
        ensure_artifact("ux_review", "UX Review", "UX review notes and acceptance evidence.", "protocol/auto/ux-review.md")
        insert_review_stage("ux_review", "Review UX and usability", "ux_reviewer", "ux_review", "human usability, readability, and responsiveness")
    if any(token in lower for token in ("histor", "accuracy", "factual")):
        ensure_participant("domain_reviewer", "Domain Reviewer", "Review factual accuracy, domain fit, and assumptions.")
        ensure_artifact("domain_review", "Domain Review", "Domain and factual review notes.", "protocol/auto/domain-review.md")
        insert_review_stage("domain_review", "Review domain accuracy", "domain_reviewer", "domain_review", "domain accuracy and factual grounding")
    if any(token in lower for token in ("test", "qa", "verify", "playtest")):
        ensure_participant("test_engineer", "Test Engineer", "Verify behavior, evidence, and acceptance criteria.")
        ensure_artifact("test_evidence", "Test Evidence", "Test results and verification evidence.", "protocol/auto/test-evidence.md")
        if not any(str(item.get("stage_key", "") or "") == "test_evidence" for item in stages):
            selector = {"kind": "skill", "value": "testing"}
            for item in request.available_agents:
                agent = item.as_dict()
                if str(agent.get("agent_id") or "").strip():
                    selector = {"kind": "agent", "value": str(agent.get("agent_id") or "").strip()}
                    break
            if stages:
                previous = stages[-1]
                transitions = dict(previous.get("transitions") or {})
                for decision, target in list(transitions.items()):
                    if str(target or "") == "__complete__":
                        transitions[decision] = "test_evidence"
                previous["transitions"] = transitions or {"completed": "test_evidence"}
            stages.append({
                "stage_key": "test_evidence",
                "display_name": "Test and verify output",
                "participant_key": "test_engineer",
                "selector": selector,
                "stage_kind": "work",
                "instructions": "Run focused checks and write test evidence with commands, outcomes, defects, and gaps.",
                "inputs": [],
                "outputs": ["test_evidence"],
                "transitions": {"completed": "__complete__"},
                "write_capable": True,
                "max_rounds": 0,
                "strict_completion": False,
                "require_output_verification": True,
                "timeout_seconds": 0,
            })
            inserted.append("Test and verify output")

    draft["participants"] = participants
    draft["artifacts"] = artifacts
    draft["stages"] = stages
    draft = draft_protocol_document_data(draft)
    draft, validation, repair_notes = _validate_and_repair_protocol_document(draft, request)
    analysis = _analyze_requirement(
        f"{metadata.get('description', '')} {change_request}",
        request.constraints_text,
    )
    plan = ProtocolAutoDesignPlanRecord(
        protocol_name=str(metadata.get("display_name") or metadata.get("slug") or "Revised Protocol"),
        protocol_slug=str(metadata.get("slug") or "revised-protocol"),
        description=str(metadata.get("description") or ""),
        roles=[
            ProtocolAutoDesignRolePlanRecord(
                role_key=str(item.get("participant_key", "") or ""),
                display_name=str(item.get("display_name", "") or ""),
                responsibility=str(item.get("instructions", "") or ""),
            )
            for item in participants
        ],
        artifacts=[
            ProtocolAutoDesignArtifactPlanRecord(
                artifact_key=str(item.get("artifact_key", "") or ""),
                display_name=str(item.get("display_name", "") or ""),
                description=str(item.get("description", "") or ""),
                path=str(item.get("path", "") or ""),
            )
            for item in artifacts
        ],
        stages=[
            ProtocolAutoDesignStagePlanRecord(
                stage_key=str(item.get("stage_key", "") or ""),
                display_name=str(item.get("display_name", "") or ""),
                stage_kind=str(item.get("stage_kind", "") or "work"),
                role_key=str(item.get("participant_key", "") or ""),
                purpose=str(item.get("instructions", "") or "").splitlines()[0] if str(item.get("instructions", "") or "").strip() else "",
                inputs=[str(value or "") for value in _list(item.get("inputs"))],
                outputs=[str(value or "") for value in _list(item.get("outputs"))],
            )
            for item in stages
        ],
        run_profile=_base_run_profile(request.requirement_text, request.constraints_text, request.workspace_ref),
    )
    warnings, unresolved = _warnings_for_session(request, validation)
    semantic_warnings, semantic_unresolved = _semantic_warnings_for_session(analysis, plan)
    warnings.extend(semantic_warnings)
    unresolved.extend(semantic_unresolved)
    status: ProtocolAutoDesignStatus = "ready" if validation.ok and not unresolved else ("blocked" if validation.ok else "failed")
    return ProtocolAutoDesignSessionRecord(
        session_id=session_id,
        status=status,
        mode="revise",
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
        analysis=analysis,
        plan=plan,
        draft_definition_json=RegistryJsonRecord.model_validate(draft),
        run_profile=plan.run_profile,
        validation=validation,
        warnings=warnings,
        unresolved_decisions=unresolved,
        change_summary=[*(inserted or ["Recorded the requested revision in protocol metadata."]), *repair_notes],
        created_at=created_at,
        updated_at=updated_at,
    )


def auto_protocol_render_cards(session: ProtocolAutoDesignSessionRecord) -> list[ProtocolAutoDesignRenderCardRecord]:
    plan = session.plan
    validation = session.validation
    cards = [
        ProtocolAutoDesignRenderCardRecord(
            title=plan.protocol_name or "Generated protocol",
            body=session.analysis.goal or plan.description,
            facts=[
                {"label": "Focus", "value": session.analysis.focus or session.analysis.domain},
                {"label": "Capabilities", "value": ", ".join(session.analysis.capabilities[:4])},
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
    "ProtocolAutoDesignStagePlanRecord",
    "ProtocolAutoDesignRunProfileRecord",
    "ProtocolAutoDesignAnalysisRecord",
    "ProtocolAutoDesignPlanRecord",
    "ProtocolAutoDesignRequestRecord",
    "ProtocolAutoDesignSessionRecord",
    "ProtocolAutoDesignRenderCardRecord",
    "compile_auto_protocol_plan",
    "generate_auto_protocol_session",
    "revise_auto_protocol_session",
    "auto_protocol_render_cards",
    "protocol_run_create_from_auto_session",
]
