"""Builtin protocol definition documents and helpers."""

from __future__ import annotations

from .documents import canonical_protocol_document, default_protocol_document_slug
from .models import *  # noqa: F401,F403

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




__all__ = [
    "software_engineering_protocol_document",
    "builtin_protocol_documents",
    "builtin_protocol_document",
    "new_protocol_definition",
]
