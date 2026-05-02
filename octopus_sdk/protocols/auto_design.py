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


class ProtocolAutoDesignWorkPackageRecord(RegistryRecordModel):
    package_key: str = ""
    display_name: str = ""
    role_key: str = ""
    role_display_name: str = ""
    role_responsibility: str = ""
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


def _analysis_skills(text: str) -> list[str]:
    """Infer workflow skills without selecting a closed use-case template."""
    skills = ["requirements planning", "implementation", "verification", "acceptance evidence"]
    signals = [
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
        ),
        (
            "experience design",
            ("user", "human", "usable", "readable", "intuitive", "beautiful", "polished", "responsive", "controls", "ux", "ui"),
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
    for skill, tokens in signals:
        if _has_any(text, tokens) and skill not in skills:
            skills.append(skill)
    return skills


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
) -> ProtocolAutoDesignWorkPackageRecord:
    review_key = review_role_key or f"{package_key}_reviewer"
    review_label = review_display_name or f"{display_name} Reviewer"
    review_artifact = review_artifact_key or f"{artifact_key}_review"
    return ProtocolAutoDesignWorkPackageRecord(
        package_key=package_key,
        display_name=display_name,
        role_key=role_key,
        role_display_name=role_display_name,
        role_responsibility=role_responsibility,
        purpose=purpose,
        quality_bar=quality_bar,
        artifact_key=artifact_key,
        artifact_display_name=artifact_display_name,
        artifact_description=artifact_description,
        artifact_path=artifact_path or f"protocol/auto/{_slugify(artifact_key)}.md",
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
        review_artifact_path=review_artifact_path or f"protocol/auto/{_slugify(review_artifact)}.md",
        review_rubric=(
            review_rubric
            or f"Inspect {artifact_display_name} against the original requirement, this stage rubric, and downstream usefulness. Choose revise when any material gap remains."
        ),
    )


def _infer_work_packages(
    requirement_text: str,
    constraints_text: str,
    skills: Sequence[str],
    coverage_terms: Sequence[str],
) -> list[ProtocolAutoDesignWorkPackageRecord]:
    """Create a requirement decomposition from workflow primitives, not use-case templates."""
    request_scope = _sentence(requirement_text) or "Create the requested outcome."
    terms = ", ".join(list(coverage_terms)[:14]) or "the explicit user requirement"
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

    packages.extend([
        _work_package(
            "implementation",
            "Implementation",
            "implementer",
            "Implementation Owner",
            "Produce the requested outcome from accepted upstream artifacts and quality bars.",
            (
                f"Produce the requested outcome from the accepted plan and supporting artifacts. "
                f"The result must visibly satisfy the requirement coverage terms: {terms}."
            ),
            "The deliverable is usable by the intended human, implements the accepted plan, and leaves clear inspection evidence.",
            "produced_outcome",
            "Produced Outcome",
            "The primary deliverable requested by the user.",
            artifact_path="protocol/auto/output",
            dependencies=list(dependency_artifacts),
            review_role_key="outcome_reviewer",
            review_display_name="Outcome Reviewer",
            review_rubric=(
                "Inspect the produced outcome directly, compare it to the requirements plan and design artifacts, and look for better ways to meet the goal. "
                "Choose revise if the outcome is low-detail, not usable, untested by inspection, or below the stated quality bar."
            ),
        ),
        _work_package(
            "verification",
            "Verification",
            "verifier",
            "Verification Lead",
            "Run focused checks against acceptance criteria, artifact contracts, usability, and requirement coverage.",
            "Run focused checks against the accepted plan, produced outcome, declared artifacts, and quality bars. Record commands, manual checks, defects, gaps, and unresolved risks.",
            "Verification proves the important claims a human would care about and documents any remaining gaps.",
            "verification_report",
            "Verification Report",
            "Checks, results, defects, gaps, and requirement coverage evidence.",
            dependencies=[*dependency_artifacts, "produced_outcome"],
            review_role_key="verification_reviewer",
            review_display_name="Verification Reviewer",
            review_rubric=(
                "Review whether verification actually exercised the important requirements rather than merely describing them. "
                "Choose revise if checks are superficial, missing human inspection, or do not prove the deliverable is usable."
            ),
        ),
    ])
    return packages


def _focus_label(requirement_text: str) -> str:
    title = _title_from_requirement(requirement_text)
    if title == "Auto Protocol":
        return "Requirement-specific workflow"
    return title


def _analyze_requirement(requirement_text: str, constraints_text: str) -> ProtocolAutoDesignAnalysisRecord:
    text = _normalized_words(requirement_text, constraints_text)
    terms = _requirement_terms(requirement_text, constraints_text)
    skills = _analysis_skills(text)
    work_packages = _infer_work_packages(requirement_text, constraints_text, skills, terms)
    deliverables = _requirement_phrases(requirement_text)
    complexity_signals = sum(1 for skill in skills if skill not in {"requirements planning", "implementation", "verification", "acceptance evidence"})
    complexity = "high" if complexity_signals >= 2 or len(text) > 700 or len(deliverables) >= 4 or len(work_packages) >= 6 else "standard"
    goal = _sentence(requirement_text) or "Create the requested outcome."
    assumptions = [
        "The generated protocol should be reviewed before publish.",
        "Stage instructions should carry the work contract so launch text can stay simple.",
        "The workflow is composed from requirement decomposition and reusable protocol primitives, not a closed use-case template.",
        "Every generated work package with an output artifact should have its own critical review gate.",
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
    required_roles.append("readiness reviewer")

    expected_artifacts: list[str] = []
    for package in work_packages:
        for label in (package.artifact_display_name, package.review_artifact_display_name):
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
        acceptance_criteria=(
            "Complete every stage, produce declared artifacts, record critical review decisions, "
            "revise work when reviewers identify material gaps, and finish with inspection-ready evidence."
        ),
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
    work_packages = list(analysis.work_packages) or _infer_work_packages(
        requirement,
        constraints,
        analysis.skills,
        analysis.requirement_terms,
    )

    roles_by_key: dict[str, ProtocolAutoDesignRolePlanRecord] = {}

    def ensure_role(role_key: str, display_name: str, responsibility: str) -> None:
        if role_key not in roles_by_key:
            roles_by_key[role_key] = _role(role_key, display_name, responsibility, agents, skills)

    for package in work_packages:
        ensure_role(package.role_key, package.role_display_name, package.role_responsibility)
        ensure_role(
            package.review_role_key,
            package.review_display_name,
            (
                package.review_responsibility
                + " Be independent and critical; choose revise when evidence, usability, completeness, or quality is below the stated bar."
            ),
        )
    ensure_role(
        "readiness_reviewer",
        "Readiness Reviewer",
        "Accept final evidence only when the completed workflow, review decisions, artifacts, and inspection steps are coherent and commercially usable.",
    )
    roles = list(roles_by_key.values())

    artifact_by_key: dict[str, ProtocolAutoDesignArtifactPlanRecord] = {}

    def ensure_artifact(key: str, name: str, description_text: str, path: str) -> None:
        if key and key not in artifact_by_key:
            artifact_by_key[key] = _artifact(key, name, description_text, path)

    for package in work_packages:
        ensure_artifact(package.artifact_key, package.artifact_display_name, package.artifact_description, package.artifact_path)
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
        "protocol/auto/release-evidence.md",
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
        "implementation": "produce_outcome",
        "verification": "verify_outcome",
    }
    review_key_by_package = {
        "requirements": "review_requirements",
        "technical_approach": "review_technical_approach",
        "input_model": "review_inputs",
        "domain_grounding": "review_domain_grounding",
        "experience_design": "review_experience",
        "supporting_assets": "review_supporting_assets",
        "risk_assessment": "review_risk",
        "implementation": "review_outcome",
        "verification": "review_verification",
    }
    work_display_by_package = {
        "requirements": "Map requirement and acceptance criteria",
        "technical_approach": "Define technical approach",
        "input_model": "Model required inputs",
        "domain_grounding": "Establish domain grounding",
        "experience_design": "Design user-facing experience",
        "supporting_assets": "Plan supporting assets and content",
        "risk_assessment": "Assess risk and safety",
        "implementation": "Produce requested outcome",
        "verification": "Verify outcome against requirement",
    }
    review_display_by_package = {
        "requirements": "Review requirement coverage",
        "technical_approach": "Review technical approach",
        "input_model": "Review input model",
        "domain_grounding": "Review domain grounding",
        "experience_design": "Review experience design",
        "supporting_assets": "Review supporting asset plan",
        "risk_assessment": "Review risk assessment",
        "implementation": "Review produced outcome",
        "verification": "Review verification evidence",
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
        review_inputs = list(dict.fromkeys([*work_inputs, package.artifact_key]))
        review_purpose = "\n".join([
            f"Critically review {package.artifact_display_name}.",
            package.review_rubric.strip(),
            f"Quality bar under review: {package.quality_bar.strip()}",
            "Inspect the artifact content, compare it to the original requirement and upstream artifacts, identify stronger approaches where useful, and choose revise for any material gap.",
            "Do not accept merely because the stage produced something; accept only when the artifact is specific, usable, evidence-backed, and ready for downstream work.",
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
        "Prepare release evidence",
        "acceptance",
        "readiness_reviewer",
        (
            "Summarize the produced artifacts, accepted reviews, revision loops, verification evidence, remaining risks, and exact inspection steps. "
            "Accept only if the full workflow evidence is coherent and the outcome is ready for a human user to inspect. "
            "End with PROTOCOL_DECISION: accept or fail and PROTOCOL_SUMMARY."
        ),
        inputs=[artifact.artifact_key for artifact in artifacts if artifact.artifact_key != "release_evidence"],
        outputs=["release_evidence"],
    ))

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

    skill_stage_requirements = {
        "technical architecture": "technical",
        "domain grounding": "domain",
        "experience design": "experience",
        "supporting asset planning": "supporting",
        "data and input modeling": "input",
        "safety and risk review": "risk",
    }
    stage_text = _normalized_words(*(stage.stage_key for stage in plan.stages), *(stage.display_name for stage in plan.stages))
    for skill, required_text in skill_stage_requirements.items():
        if skill in analysis.skills and required_text not in stage_text:
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
        if stage.stage_kind == "review" and str(stage.review_of_stage_key or "").strip()
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
            message="Requirement coverage passed: work packages, artifacts, isolated reviews, and final evidence reference the material request.",
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
    change_request = str(request.requirement_text or "").strip()
    previous_requirement = str(auto_meta.get("requirement") or "").strip()
    base_parts = [
        str(metadata.get("display_name") or metadata.get("slug") or "").strip(),
        str(metadata.get("description") or "").strip(),
        previous_requirement,
    ]
    combined_requirement = "\n".join(part for part in base_parts if part)
    if change_request:
        combined_requirement = "\n".join(part for part in [combined_requirement, f"Revision request: {change_request}"] if part)
    if not combined_requirement:
        combined_requirement = change_request or "Revise the selected protocol."

    revisions = [str(item or "").strip() for item in _list(auto_meta.get("revision_requests")) if str(item or "").strip()]
    if change_request:
        revisions.append(change_request)
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
    if metadata.get("description"):
        regenerated_metadata["description"] = str(metadata.get("description") or "")
    regenerated_auto_meta = dict(regenerated_metadata.get("auto_protocol") or {})
    regenerated_auto_meta.update({
        "generated": True,
        "revision_of_protocol_id": str(request.target_protocol_id or ""),
        "revision_of_version_id": str(request.target_version_id or ""),
        "revision_requests": revisions[-20:],
    })
    regenerated_metadata["auto_protocol"] = regenerated_auto_meta
    regenerated_draft["metadata"] = regenerated_metadata
    regenerated_draft, validation, repair_notes = _validate_and_repair_protocol_document(regenerated_draft, regenerate_request)
    warnings, unresolved = _warnings_for_session(regenerate_request, validation)
    semantic_warnings, semantic_unresolved = _semantic_warnings_for_session(session.analysis, session.plan)
    warnings.extend(semantic_warnings)
    unresolved.extend(semantic_unresolved)
    status: ProtocolAutoDesignStatus = "ready" if validation.ok and not unresolved else ("blocked" if validation.ok else "failed")
    return session.model_copy(update={
        "status": status,
        "mode": "revise",
        "source_protocol_id": request.target_protocol_id,
        "source_version_id": request.target_version_id,
        "source_draft_revision": request.target_draft_revision,
        "target_protocol_id": request.target_protocol_id,
        "target_draft_revision": request.target_draft_revision,
        "requirement_text": request.requirement_text,
        "constraints_text": request.constraints_text,
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
    "ProtocolAutoDesignWorkPackageRecord",
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
