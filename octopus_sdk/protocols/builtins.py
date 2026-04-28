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
                {"participant_key": "planner", "display_name": "Planner"},
                {"participant_key": "plan_reviewer", "display_name": "Plan Reviewer"},
                {"participant_key": "architect", "display_name": "Architect"},
                {"participant_key": "architecture_reviewer", "display_name": "Architecture Reviewer"},
                {"participant_key": "implementer", "display_name": "Implementer"},
                {"participant_key": "implementation_reviewer", "display_name": "Implementation Reviewer"},
                {"participant_key": "acceptance", "display_name": "Acceptance"},
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
                    "selector": {"kind": "skill", "value": "product-definition"},
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
                    "selector": {"kind": "skill", "value": "review"},
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
                    "selector": {"kind": "skill", "value": "architecture"},
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
                    "selector": {"kind": "skill", "value": "review"},
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
                    "selector": {"kind": "skill", "value": "implementation"},
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
                    "selector": {"kind": "skill", "value": "review"},
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
                    "selector": {"kind": "skill", "value": "review"},
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
                {"participant_key": "author", "display_name": "Author"},
                {"participant_key": "reviewer", "display_name": "Reviewer"},
                {"participant_key": "approver", "display_name": "Approver"},
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
                    "selector": {"kind": "skill", "value": "writing"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": [],
                    "outputs": ["document"],
                    "transitions": {"completed": "review_document"},
                    "instructions": "Draft or revise the document so it is ready for review.",
                },
                {
                    "stage_key": "review_document",
                    "display_name": "Review Document",
                    "participant_key": "reviewer",
                    "selector": {"kind": "skill", "value": "review"},
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
                    "selector": {"kind": "skill", "value": "approval"},
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


def manufacturing_local_analytics_protocol_document() -> ProtocolDefinitionDocumentRecord:
    return canonical_protocol_document(
        {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "metadata": {
                "slug": "manufacturing-local-analytics",
                "display_name": "Manufacturing Local Analytics",
                "description": (
                    "Build and validate local manufacturing analytics scripts while keeping raw CSV rows "
                    "inside the workspace."
                ),
            },
            "participants": [
                {"participant_key": "contract_author", "display_name": "Contract Author"},
                {"participant_key": "script_author", "display_name": "Script Author"},
                {"participant_key": "local_runner", "display_name": "Local Runner"},
                {"participant_key": "validator", "display_name": "Validator"},
                {"participant_key": "reviewer", "display_name": "Reviewer"},
            ],
            "artifacts": [
                {
                    "artifact_key": "input_contract",
                    "kind": "workspace_file",
                    "path": "protocol/input_contract.json",
                    "description": "Local table contract, join keys, and privacy boundary.",
                    "verify": True,
                },
                {
                    "artifact_key": "profile_script",
                    "kind": "workspace_file",
                    "path": "scripts/profile_manufacturing_data.py",
                    "description": "Local profiler that emits schema, counts, missing values, and aggregate summaries.",
                    "verify": True,
                },
                {
                    "artifact_key": "profile_summary",
                    "kind": "workspace_file",
                    "path": "reports/profile_summary.md",
                    "description": "Model-safe profile summary with no raw CSV rows.",
                    "verify": True,
                },
                {
                    "artifact_key": "model_visible_context",
                    "kind": "workspace_file",
                    "path": "reports/model_visible_context.md",
                    "description": "Controlled context that can be shared with the assistant.",
                    "verify": True,
                },
                {
                    "artifact_key": "analysis_script",
                    "kind": "workspace_file",
                    "path": "scripts/analyze_manufacturing_quality.py",
                    "description": "Local analyzer that joins the CSVs and writes repeatable findings.",
                    "verify": True,
                },
                {
                    "artifact_key": "quality_flags",
                    "kind": "workspace_file",
                    "path": "reports/quality_flags.csv",
                    "description": "Panel-level high-risk flags generated locally.",
                    "verify": True,
                },
                {
                    "artifact_key": "defect_summary",
                    "kind": "workspace_file",
                    "path": "reports/defect_summary.csv",
                    "description": "Aggregate quality summary by shift, line, and dominant vendor.",
                    "verify": True,
                },
                {
                    "artifact_key": "findings_report",
                    "kind": "workspace_file",
                    "path": "reports/manufacturing_findings.md",
                    "description": "Human-readable findings and recommendations.",
                    "verify": True,
                },
                {
                    "artifact_key": "heatmap",
                    "kind": "workspace_file",
                    "path": "reports/defect_heatmap.html",
                    "description": "Renderable local defect risk heatmap.",
                    "verify": True,
                },
                {
                    "artifact_key": "run_manifest",
                    "kind": "workspace_file",
                    "path": "reports/run_manifest.json",
                    "description": "Demo manifest with generated files, validation status, and privacy notes.",
                    "verify": True,
                },
            ],
            "stages": [
                {
                    "stage_key": "define_input_contract",
                    "display_name": "Define Input Contract",
                    "participant_key": "contract_author",
                    "selector": {"kind": "skill", "value": "manufacturing-local-analytics"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": [],
                    "outputs": ["input_contract"],
                    "transitions": {"completed": "generate_profile_script"},
                    "instructions": (
                        "Define the expected local CSV files, join keys, privacy boundary, and output contract. "
                        "Do not ask for raw rows; use only schema, counts, and aggregates as model-visible context."
                    ),
                },
                {
                    "stage_key": "generate_profile_script",
                    "display_name": "Generate Profile Script",
                    "participant_key": "script_author",
                    "selector": {"kind": "skill", "value": "manufacturing-local-analytics"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["input_contract"],
                    "outputs": ["profile_script"],
                    "transitions": {"completed": "run_profile_locally"},
                    "instructions": (
                        "Create the local profiling script. It must inspect files on disk and write only "
                        "schema, counts, missing values, relationship checks, and aggregates."
                    ),
                },
                {
                    "stage_key": "run_profile_locally",
                    "display_name": "Run Profile Locally",
                    "participant_key": "local_runner",
                    "selector": {"kind": "skill", "value": "manufacturing-local-analytics"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["input_contract", "profile_script"],
                    "outputs": ["profile_summary", "model_visible_context"],
                    "transitions": {"completed": "generate_analysis_script"},
                    "instructions": (
                        "Run the profile script against the local CSVs and attach only controlled summaries. "
                        "Raw CSV rows must remain in the workspace."
                    ),
                },
                {
                    "stage_key": "generate_analysis_script",
                    "display_name": "Generate Analysis Script",
                    "participant_key": "script_author",
                    "selector": {"kind": "skill", "value": "manufacturing-local-analytics"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["input_contract", "model_visible_context"],
                    "outputs": ["analysis_script"],
                    "transitions": {"completed": "run_analysis_locally"},
                    "instructions": (
                        "Generate or revise the local analysis script using the controlled profile. The script "
                        "must join the CSVs locally and produce repeatable reports."
                    ),
                },
                {
                    "stage_key": "run_analysis_locally",
                    "display_name": "Run Analysis Locally",
                    "participant_key": "local_runner",
                    "selector": {"kind": "skill", "value": "manufacturing-local-analytics"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["input_contract", "analysis_script"],
                    "outputs": ["quality_flags", "defect_summary", "findings_report", "heatmap"],
                    "transitions": {"completed": "validate_outputs"},
                    "instructions": (
                        "Run the analysis script locally. Attach generated reports, flags, summaries, and heatmap "
                        "as artifacts; do not paste raw source rows into the response."
                    ),
                },
                {
                    "stage_key": "validate_outputs",
                    "display_name": "Validate Outputs",
                    "participant_key": "validator",
                    "selector": {"kind": "skill", "value": "testing"},
                    "stage_kind": "work",
                    "write_capable": True,
                    "strict_completion": True,
                    "require_output_verification": True,
                    "timeout_seconds": 1800,
                    "inputs": ["quality_flags", "defect_summary", "findings_report", "heatmap"],
                    "outputs": ["run_manifest"],
                    "transitions": {"completed": "review_report"},
                    "instructions": (
                        "Validate that all required artifacts exist, the known fixture findings are present, and "
                        "the model-visible artifacts do not contain raw CSV rows."
                    ),
                },
                {
                    "stage_key": "review_report",
                    "display_name": "Review Report",
                    "participant_key": "reviewer",
                    "selector": {"kind": "skill", "value": "code-review"},
                    "stage_kind": "acceptance",
                    "timeout_seconds": 1800,
                    "inputs": ["run_manifest", "findings_report", "quality_flags", "defect_summary"],
                    "outputs": [],
                    "transitions": {"accept": "__complete__", "revise": "run_analysis_locally", "fail": "__failed__"},
                    "instructions": (
                        "Approve the report when the local artifacts are complete, repeatable, and safe to share. "
                        "Send it back if outputs are missing or the privacy boundary is violated."
                    ),
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
        manufacturing_local_analytics_protocol_document(),
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
    "manufacturing_local_analytics_protocol_document",
    "builtin_protocol_documents",
    "builtin_protocol_template_summaries",
    "builtin_protocol_document",
    "new_protocol_definition",
]
