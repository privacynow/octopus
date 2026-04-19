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
                {"participant_key": "planner", "display_name": "Planner", "selector": {"kind": "skill", "value": "product-definition"}},
                {"participant_key": "plan_reviewer", "display_name": "Plan Reviewer", "selector": {"kind": "skill", "value": "review"}},
                {"participant_key": "architect", "display_name": "Architect", "selector": {"kind": "skill", "value": "architecture"}},
                {
                    "participant_key": "architecture_reviewer",
                    "display_name": "Architecture Reviewer",
                    "selector": {"kind": "skill", "value": "review"},
                },
                {"participant_key": "implementer", "display_name": "Implementer", "selector": {"kind": "skill", "value": "implementation"}},
                {
                    "participant_key": "implementation_reviewer",
                    "display_name": "Implementation Reviewer",
                    "selector": {"kind": "skill", "value": "review"},
                },
                {"participant_key": "acceptance", "display_name": "Acceptance", "selector": {"kind": "skill", "value": "review"}},
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


def document_approval_protocol_document() -> ProtocolDefinitionDocumentRecord:
    return canonical_protocol_document(
        {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "metadata": {
                "slug": "document-approval",
                "display_name": "Document Approval",
                "description": "Draft, review, and approve a document before completion.",
            },
            "participants": [
                {"participant_key": "author", "display_name": "Author", "selector": {"kind": "skill", "value": "writing"}},
                {"participant_key": "reviewer", "display_name": "Reviewer", "selector": {"kind": "skill", "value": "review"}},
                {"participant_key": "approver", "display_name": "Approver", "selector": {"kind": "skill", "value": "approval"}},
            ],
            "artifacts": [
                {
                    "artifact_key": "document",
                    "kind": "workspace_file",
                    "path": "protocol/document.md",
                    "description": "The draft document being prepared for approval.",
                    "verify": True,
                },
            ],
            "stages": [
                {
                    "stage_key": "draft_document",
                    "display_name": "Draft Document",
                    "participant_key": "author",
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["document"],
                    "outputs": ["document"],
                    "transitions": {"completed": "review_document"},
                    "instructions": "Draft or revise the document so it is ready for review.",
                },
                {
                    "stage_key": "review_document",
                    "display_name": "Review Document",
                    "participant_key": "reviewer",
                    "stage_kind": "review",
                    "timeout_seconds": 1800,
                    "inputs": ["document"],
                    "outputs": [],
                    "transitions": {"accept": "approve_document", "revise": "draft_document", "fail": "__failed__"},
                    "instructions": "Review the document for completeness, correctness, and clarity.",
                },
                {
                    "stage_key": "approve_document",
                    "display_name": "Approve Document",
                    "participant_key": "approver",
                    "stage_kind": "acceptance",
                    "timeout_seconds": 1800,
                    "inputs": ["document"],
                    "outputs": [],
                    "transitions": {"accept": "__complete__", "revise": "draft_document", "fail": "__failed__"},
                    "instructions": "Approve the document, send it back for revision, or fail the workflow.",
                },
            ],
            "policies": {
                "single_active_writer": True,
                "max_review_rounds": 3,
            },
        }
    )


def builtin_protocol_documents() -> tuple[ProtocolDefinitionDocumentRecord, ...]:
    return (
        software_engineering_protocol_document(),
        document_approval_protocol_document(),
    )


def builtin_protocol_template_summaries() -> tuple[ProtocolTemplateSummaryRecord, ...]:
    summaries: list[ProtocolTemplateSummaryRecord] = []
    for document in builtin_protocol_documents():
        summaries.append(
            ProtocolTemplateSummaryRecord(
                slug=document.slug,
                display_name=document.display_name,
                description=document.description,
                featured=False,
                participant_count=len(document.participants),
                artifact_count=len(document.artifacts),
                stage_count=len(document.stages),
                stage_kind_sequence=[item.stage_kind for item in document.stages],
            )
        )
    return tuple(summaries)


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
    "document_approval_protocol_document",
    "builtin_protocol_documents",
    "builtin_protocol_template_summaries",
    "builtin_protocol_document",
    "new_protocol_definition",
]
