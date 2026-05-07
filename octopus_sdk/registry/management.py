"""Typed registry management protocol for connected bots."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from octopus_sdk.content_models import SkillFileRecord as DomainSkillFileRecord
from octopus_sdk.providers import ProviderConfigRecord, coerce_provider_config
from octopus_sdk.protocols.auto_design import (
    ProtocolAutoDesignModelRequestRecord,
    ProtocolAutoDesignModelResponseRecord,
)
from octopus_sdk.protocols.models import (
    ProtocolArtifactRuntimeActionResultRecord,
    ProtocolArtifactRuntimeHealthRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
)
from octopus_sdk.registry.models import ExecutionStateRecord, RegistryJsonRecord, RegistryRecordModel, utcnow_iso
from octopus_sdk.skill_types import SkillRequirement
from octopus_sdk.workflows.conversation import (
    ConversationResetOutcome,
    SettingMutationOutcome,
)
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleMutation,
    ProviderGuidancePreview,
)
from octopus_sdk.workflows.skills import (
    ConversationSkillItem,
    ConversationSkillListing,
    ConversationSkillMutationOutcome,
    RegistryRuntimeSkillSearchHit,
    RuntimeSkillCatalogItem,
    RuntimeSkillDetail,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillLifecycleMutation,
    RuntimeSkillPackageArtifact,
    RuntimeSkillValidationProblem,
    RuntimeSkillMutationOutcome,
    RuntimeSkillSearchResults,
    RuntimeSkillSetupAdvanceOutcome,
)

ManagementOperation = Literal[
    "list_catalog_skills",
    "search_catalog_skills",
    "catalog_skill_detail",
    "catalog_skill_lifecycle_detail",
    "edit_catalog_skill_draft",
    "export_catalog_skill_package",
    "import_catalog_skill_package",
    "submit_catalog_skill",
    "approve_catalog_skill",
    "reject_catalog_skill",
    "publish_catalog_skill",
    "archive_catalog_skill",
    "install_catalog_skill",
    "uninstall_catalog_skill",
    "update_catalog_skill",
    "diff_catalog_skill",
    "conversation_skill_state",
    "activate_conversation_skill",
    "deactivate_conversation_skill",
    "clear_conversation_skills",
    "submit_conversation_skill_credential",
    "conversation_settings_state",
    "set_conversation_setting",
    "reset_conversation",
    "reset_execution_fault",
    "preview_provider_guidance",
    "provider_guidance_detail",
    "edit_provider_guidance_draft",
    "submit_provider_guidance",
    "approve_provider_guidance",
    "reject_provider_guidance",
    "publish_provider_guidance",
    "archive_provider_guidance",
    "design_auto_protocol",
    "start_artifact_runtime",
    "stop_artifact_runtime",
    "artifact_runtime_health",
    "artifact_runtime_logs",
    "artifact_runtime_fetch",
    "workspace_usage",
    "workspace_cleanup",
]

ALL_MANAGEMENT_OPERATIONS: tuple[ManagementOperation, ...] = (
    "list_catalog_skills",
    "search_catalog_skills",
    "catalog_skill_detail",
    "catalog_skill_lifecycle_detail",
    "edit_catalog_skill_draft",
    "export_catalog_skill_package",
    "import_catalog_skill_package",
    "submit_catalog_skill",
    "approve_catalog_skill",
    "reject_catalog_skill",
    "publish_catalog_skill",
    "archive_catalog_skill",
    "install_catalog_skill",
    "uninstall_catalog_skill",
    "update_catalog_skill",
    "diff_catalog_skill",
    "conversation_skill_state",
    "activate_conversation_skill",
    "deactivate_conversation_skill",
    "clear_conversation_skills",
    "submit_conversation_skill_credential",
    "conversation_settings_state",
    "set_conversation_setting",
    "reset_conversation",
    "reset_execution_fault",
    "preview_provider_guidance",
    "provider_guidance_detail",
    "edit_provider_guidance_draft",
    "submit_provider_guidance",
    "approve_provider_guidance",
    "reject_provider_guidance",
    "publish_provider_guidance",
    "archive_provider_guidance",
    "design_auto_protocol",
    "start_artifact_runtime",
    "stop_artifact_runtime",
    "artifact_runtime_health",
    "artifact_runtime_logs",
    "artifact_runtime_fetch",
    "workspace_usage",
    "workspace_cleanup",
)

ManagementErrorCode = Literal[
    "agent_not_connected",
    "admin_operation_not_implemented",
    "admin_operation_unavailable",
    "admin_interface_not_implemented",
    "request_timeout",
    "request_failed",
    "request_invalid",
]


class SkillRequirementRecord(RegistryRecordModel):
    key: str = ""
    prompt: str = ""
    help_url: str = ""
    validation: RegistryJsonRecord | None = Field(
        default=None,
        validation_alias="validate",
        serialization_alias="validate",
    )


class SkillFileRecord(RegistryRecordModel):
    relative_path: str = ""
    content_text: str = ""
    content_type: str = "text/plain"
    executable: bool = False
    digest: str = ""


class RuntimeSkillValidationProblemRecord(RegistryRecordModel):
    code: str = ""
    message: str = ""
    field_path: str = ""
    severity: str = "error"


class RuntimeSkillCatalogItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    skill_kind: str = "prompt"
    source_kind: str = ""
    source_label: str = ""
    has_custom_override: bool = False
    requires_credentials: bool = False
    requirement_keys: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""
    runtime_available: bool = True
    default_for_new_conversations: bool = False
    visibility: str = "shared"
    is_mutable: bool = False
    has_unpublished_changes: bool = False


class RuntimeSkillSearchCatalogItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    source_kind: str = ""
    source_label: str = ""
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""


class RegistryRuntimeSkillSearchHitRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    source_label: str = "Store"
    publisher: str = ""
    version: str = ""
    can_import: bool = False


class RuntimeSkillSearchResultsRecord(RegistryRecordModel):
    catalog: list[RuntimeSkillSearchCatalogItemRecord] = Field(default_factory=list)
    registry: list[RegistryRuntimeSkillSearchHitRecord] = Field(default_factory=list)
    registry_error: str = ""


class RuntimeSkillDetailRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    body: str = ""
    skill_kind: str = "prompt"
    source_kind: str = ""
    source_label: str = ""
    has_custom_override: bool = False
    providers: list[str] = Field(default_factory=list)
    requirement_keys: list[str] = Field(default_factory=list)
    requires_credentials: bool = False
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""
    runtime_available: bool = True
    default_for_new_conversations: bool = False
    visibility: str = "shared"
    is_mutable: bool = False
    has_unpublished_changes: bool = False
    requirements: list[SkillRequirementRecord] = Field(default_factory=list)
    provider_config: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    files: list[SkillFileRecord] = Field(default_factory=list)
    validation_problems: list[RuntimeSkillValidationProblemRecord] = Field(default_factory=list)
    publish_ready: bool = False


class RuntimeSkillLifecycleRevisionRecord(RegistryRecordModel):
    revision_id: str = ""
    version_label: str = ""
    status: str = ""
    changelog: str = ""
    created_by: str = ""
    created_at: str = ""
    is_published: bool = False


class RuntimeSkillLifecycleApprovalRecord(RegistryRecordModel):
    revision_id: str = ""
    action: str = ""
    actor: str = ""
    note: str = ""
    created_at: str = ""


class RuntimeSkillLifecycleDetailRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    skill_kind: str = "prompt"
    source_label: str = ""
    visibility: str = ""
    body: str = ""
    lifecycle_status: str = ""
    active_revision_id: str = ""
    published_revision_id: str = ""
    runtime_available: bool = False
    publish_ready: bool = False
    requirements: list[SkillRequirementRecord] = Field(default_factory=list)
    provider_config: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    files: list[SkillFileRecord] = Field(default_factory=list)
    validation_problems: list[RuntimeSkillValidationProblemRecord] = Field(default_factory=list)
    revisions: list[RuntimeSkillLifecycleRevisionRecord] = Field(default_factory=list)
    approvals: list[RuntimeSkillLifecycleApprovalRecord] = Field(default_factory=list)


class RuntimeSkillLifecycleMutationRecord(RegistryRecordModel):
    status: str = ""
    ok: bool = False
    message: str = ""
    detail: RuntimeSkillLifecycleDetailRecord | None = None


class RuntimeSkillPackageArtifactRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    file_name: str = ""
    content_type: str = "application/json"
    document_text: str = ""
    format: str = "json"
    revision_scope: str = "draft"
    revision_id: str = ""


class RuntimeSkillMutationOutcomeRecord(RegistryRecordModel):
    name: str = ""
    ok: bool = False
    message: str = ""
    prompt_size_warnings: list[str] = Field(default_factory=list)


class ConversationSkillItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    skill_kind: str = "prompt"
    source_kind: str = ""
    source_label: str = ""
    providers: list[str] = Field(default_factory=list)
    requirement_keys: list[str] = Field(default_factory=list)
    requires_credentials: bool = False
    has_custom_override: bool = False


class ConversationSkillListingRecord(RegistryRecordModel):
    active_skills: list[str] = Field(default_factory=list)
    active_skill_details: list[ConversationSkillItemRecord] = Field(default_factory=list)


class ConversationSkillSetupPromptRecord(RegistryRecordModel):
    skill_name: str = ""
    actor_key: str = ""
    requirement: SkillRequirementRecord | None = None


class ConversationSkillMutationOutcomeRecord(RegistryRecordModel):
    status: str = ""
    first_requirement: SkillRequirementRecord | None = None
    projected_size: int = 0
    prompt_size_threshold: int = 0
    foreign_setup_user: str = ""


class ConversationSkillSetupAdvanceOutcomeRecord(RegistryRecordModel):
    status: str = ""
    validation_key: str = ""
    validation_error: str = ""
    next_requirement: SkillRequirementRecord | None = None
    skill_name: str = ""


class ConversationSettingsStateRecord(RegistryRecordModel):
    conversation_id: str = ""
    conversation_key: str = ""
    role: str = ""
    default_role: str = ""
    approval_mode: str = ""
    approval_mode_explicit: bool = False
    compact_mode: bool | None = None
    effective_compact_mode: bool = False
    model_profile: str = ""
    current_profile: str = ""
    effective_model: str = ""
    available_model_profiles: list[str] = Field(default_factory=list)
    file_policy: str = ""
    effective_file_policy: str = ""
    project_id: str = ""
    available_projects: list[str] = Field(default_factory=list)


class ConversationSettingMutationRecord(RegistryRecordModel):
    setting: str = ""
    status: str = ""
    mutated: bool = False
    message: str = ""
    effective_policy: str = ""
    effective_model: str = ""
    current_profile: str = ""
    compact_enabled: bool | None = None


class ConversationResetOutcomeRecord(RegistryRecordModel):
    status: str = ""
    message: str = ""


class ProviderGuidancePreviewRecord(RegistryRecordModel):
    provider: str = ""
    published_guidance: str = ""
    preview_guidance: str = ""
    preview_source: str = ""
    composed_prompt: str = ""
    active_skill_tools_summary: str = ""
    provider_config: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    prompt_weight: int = 0


class ProviderGuidanceLifecycleRevisionRecord(RegistryRecordModel):
    revision_id: str = ""
    status: str = ""
    created_by: str = ""
    created_at: str = ""
    is_published: bool = False


class ProviderGuidanceLifecycleApprovalRecord(RegistryRecordModel):
    revision_id: str = ""
    action: str = ""
    actor: str = ""
    note: str = ""
    created_at: str = ""


class ProviderGuidanceLifecycleDetailRecord(RegistryRecordModel):
    provider: str = ""
    scope_kind: str = ""
    scope_key: str = ""
    draft_body: str = ""
    published_body: str = ""
    lifecycle_status: str = ""
    active_revision_id: str = ""
    published_revision_id: str = ""
    runtime_available: bool = False
    revisions: list[ProviderGuidanceLifecycleRevisionRecord] = Field(default_factory=list)
    approvals: list[ProviderGuidanceLifecycleApprovalRecord] = Field(default_factory=list)


class ProviderGuidanceLifecycleMutationRecord(RegistryRecordModel):
    status: str = ""
    ok: bool = False
    message: str = ""
    detail: ProviderGuidanceLifecycleDetailRecord | None = None


def skill_requirement_record(requirement: SkillRequirement) -> SkillRequirementRecord:
    validate = requirement.validate.to_dict() if requirement.validate is not None else None
    return SkillRequirementRecord(
        key=requirement.key,
        prompt=requirement.prompt,
        help_url=requirement.help_url or "",
        validate=RegistryJsonRecord(validate or {}) if validate is not None else None,
    )


def skill_requirement(value: SkillRequirementRecord | SkillRequirement) -> SkillRequirement:
    if isinstance(value, SkillRequirement):
        return value
    validate = value.validation.as_dict() if value.validation is not None else None
    return SkillRequirement(
        key=value.key,
        prompt=value.prompt,
        help_url=value.help_url or None,
        validate=validate,
    )


def skill_file_record(file_record) -> SkillFileRecord:
    return SkillFileRecord(
        relative_path=file_record.relative_path,
        content_text=file_record.content_text,
        content_type=file_record.content_type,
        executable=file_record.executable,
        digest=file_record.digest,
    )


def skill_file(value: SkillFileRecord | DomainSkillFileRecord) -> DomainSkillFileRecord:
    if isinstance(value, DomainSkillFileRecord):
        return value
    return DomainSkillFileRecord(
        relative_path=value.relative_path,
        content_text=value.content_text,
        content_type=value.content_type,
        executable=value.executable,
    )


def provider_config(value: RegistryJsonRecord | ProviderConfigRecord | None) -> ProviderConfigRecord:
    if value is None:
        return ProviderConfigRecord()
    if isinstance(value, ProviderConfigRecord):
        return value
    return coerce_provider_config(value.as_dict())


def runtime_skill_validation_problem_record(
    problem: RuntimeSkillValidationProblem,
) -> RuntimeSkillValidationProblemRecord:
    return RuntimeSkillValidationProblemRecord(
        code=problem.code,
        message=problem.message,
        field_path=problem.field_path,
        severity=problem.severity,
    )


def runtime_skill_catalog_item_record(item: RuntimeSkillCatalogItem) -> RuntimeSkillCatalogItemRecord:
    return RuntimeSkillCatalogItemRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        skill_kind=item.skill_kind,
        source_kind=item.source_kind,
        source_label=item.source_label,
        has_custom_override=item.has_custom_override,
        requires_credentials=bool(item.requirement_keys),
        requirement_keys=list(item.requirement_keys),
        providers=list(item.providers),
        can_activate=item.can_activate,
        can_update=item.can_update,
        can_uninstall=item.can_uninstall,
        lifecycle_status=item.lifecycle_status,
        runtime_available=item.runtime_available,
        default_for_new_conversations=item.default_for_new_conversations,
        visibility=item.visibility,
        is_mutable=item.is_mutable,
        has_unpublished_changes=item.has_unpublished_changes,
    )


def runtime_skill_search_catalog_item_record(
    item: RuntimeSkillCatalogItem,
) -> RuntimeSkillSearchCatalogItemRecord:
    return RuntimeSkillSearchCatalogItemRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        source_kind=item.source_kind,
        source_label=item.source_label,
        can_activate=item.can_activate,
        can_update=item.can_update,
        can_uninstall=item.can_uninstall,
        lifecycle_status=item.lifecycle_status,
    )


def registry_runtime_skill_search_hit_record(
    item: RegistryRuntimeSkillSearchHit,
) -> RegistryRuntimeSkillSearchHitRecord:
    return RegistryRuntimeSkillSearchHitRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        source_label=item.source_label,
        publisher=item.publisher,
        version=item.version,
        can_import=item.can_import,
    )


def runtime_skill_search_results_record(
    results: RuntimeSkillSearchResults,
) -> RuntimeSkillSearchResultsRecord:
    return RuntimeSkillSearchResultsRecord(
        catalog=[runtime_skill_search_catalog_item_record(item) for item in results.catalog],
        registry=[registry_runtime_skill_search_hit_record(item) for item in results.registry],
        registry_error=results.registry_error,
    )


def runtime_skill_detail_record(detail: RuntimeSkillDetail) -> RuntimeSkillDetailRecord:
    return RuntimeSkillDetailRecord(
        name=detail.name,
        display_name=detail.display_name,
        description=detail.description,
        body=detail.body,
        skill_kind=detail.skill_kind,
        source_kind=detail.source_kind,
        source_label=detail.source_label,
        has_custom_override=detail.has_custom_override,
        providers=list(detail.providers),
        requirement_keys=list(detail.requirement_keys),
        requires_credentials=detail.requires_credentials,
        can_activate=detail.can_activate,
        can_update=detail.can_update,
        can_uninstall=detail.can_uninstall,
        lifecycle_status=detail.lifecycle_status,
        runtime_available=detail.runtime_available,
        default_for_new_conversations=detail.default_for_new_conversations,
        visibility=detail.visibility,
        is_mutable=detail.is_mutable,
        has_unpublished_changes=detail.has_unpublished_changes,
        requirements=[skill_requirement_record(item) for item in detail.requirements],
        provider_config=RegistryJsonRecord(detail.provider_config.to_dict()),
        files=[skill_file_record(item) for item in detail.files],
        validation_problems=[
            runtime_skill_validation_problem_record(item)
            for item in detail.validation_problems
        ],
        publish_ready=detail.publish_ready,
    )


def runtime_skill_lifecycle_detail_record(
    detail: RuntimeSkillLifecycleDetail,
) -> RuntimeSkillLifecycleDetailRecord:
    return RuntimeSkillLifecycleDetailRecord(
        name=detail.name,
        display_name=detail.display_name,
        description=detail.description,
        skill_kind=detail.skill_kind,
        source_label=detail.source_label,
        visibility=detail.visibility,
        body=detail.body,
        lifecycle_status=detail.lifecycle_status,
        active_revision_id=detail.active_revision_id,
        published_revision_id=detail.published_revision_id,
        runtime_available=detail.runtime_available,
        publish_ready=detail.publish_ready,
        requirements=[skill_requirement_record(item) for item in detail.requirements],
        provider_config=RegistryJsonRecord(detail.provider_config.to_dict()),
        files=[skill_file_record(item) for item in detail.files],
        validation_problems=[
            runtime_skill_validation_problem_record(item)
            for item in detail.validation_problems
        ],
        revisions=[
            RuntimeSkillLifecycleRevisionRecord(
                revision_id=item.revision_id,
                version_label=item.version_label,
                status=item.status,
                changelog=item.changelog,
                created_by=item.created_by,
                created_at=item.created_at,
                is_published=item.is_published,
            )
            for item in detail.revisions
        ],
        approvals=[
            RuntimeSkillLifecycleApprovalRecord(
                revision_id=item.revision_id,
                action=item.action,
                actor=item.actor,
                note=item.note,
                created_at=item.created_at,
            )
            for item in detail.approvals
        ],
    )


def runtime_skill_package_artifact_record(
    artifact: RuntimeSkillPackageArtifact,
) -> RuntimeSkillPackageArtifactRecord:
    return RuntimeSkillPackageArtifactRecord(
        name=artifact.name,
        display_name=artifact.display_name,
        file_name=artifact.file_name,
        content_type=artifact.content_type,
        document_text=artifact.content_text,
        format=artifact.format,
        revision_scope=artifact.revision_scope,
        revision_id=artifact.revision_id,
    )


def runtime_skill_lifecycle_mutation_record(
    mutation: RuntimeSkillLifecycleMutation,
) -> RuntimeSkillLifecycleMutationRecord:
    return RuntimeSkillLifecycleMutationRecord(
        status=mutation.status,
        ok=mutation.ok,
        message=mutation.message,
        detail=(
            runtime_skill_lifecycle_detail_record(mutation.detail)
            if mutation.detail is not None
            else None
        ),
    )


def runtime_skill_mutation_outcome_record(
    result: RuntimeSkillMutationOutcome,
) -> RuntimeSkillMutationOutcomeRecord:
    return RuntimeSkillMutationOutcomeRecord(
        name=result.name,
        ok=result.ok,
        message=result.message,
        prompt_size_warnings=list(result.prompt_size_warnings),
    )


def conversation_skill_item_record(item: ConversationSkillItem) -> ConversationSkillItemRecord:
    return ConversationSkillItemRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        skill_kind=item.skill_kind,
        source_kind=item.source_kind,
        source_label=item.source_label,
        providers=list(item.providers),
        requirement_keys=list(item.requirement_keys),
        requires_credentials=item.requires_credentials,
        has_custom_override=item.has_custom_override,
    )


def conversation_skill_listing_record(
    listing: ConversationSkillListing,
) -> ConversationSkillListingRecord:
    return ConversationSkillListingRecord(
        active_skills=list(listing.active_skills),
        active_skill_details=[
            conversation_skill_item_record(item) for item in listing.active_skill_details
        ],
    )


def conversation_skill_mutation_outcome_record(
    outcome: ConversationSkillMutationOutcome,
) -> ConversationSkillMutationOutcomeRecord:
    return ConversationSkillMutationOutcomeRecord(
        status=outcome.status,
        first_requirement=(
            skill_requirement_record(outcome.first_requirement)
            if outcome.first_requirement is not None
            else None
        ),
        projected_size=outcome.projected_size,
        prompt_size_threshold=outcome.prompt_size_threshold,
        foreign_setup_user=(
            outcome.foreign_setup.actor_key if outcome.foreign_setup is not None else ""
        ),
    )


def conversation_skill_setup_advance_outcome_record(
    outcome: RuntimeSkillSetupAdvanceOutcome,
) -> ConversationSkillSetupAdvanceOutcomeRecord:
    return ConversationSkillSetupAdvanceOutcomeRecord(
        status=outcome.status,
        validation_key=outcome.validation_key,
        validation_error=outcome.validation_error,
        next_requirement=(
            skill_requirement_record(outcome.next_requirement)
            if outcome.next_requirement is not None
            else None
        ),
        skill_name=outcome.skill_name,
    )


def conversation_setting_mutation_record(
    setting: str,
    outcome: SettingMutationOutcome,
) -> ConversationSettingMutationRecord:
    return ConversationSettingMutationRecord(
        setting=setting,
        status=outcome.status,
        mutated=outcome.mutated,
        message=outcome.message,
        effective_policy=outcome.effective_policy,
        effective_model=outcome.effective_model,
        current_profile=outcome.current_profile,
        compact_enabled=outcome.compact_enabled,
    )


def conversation_reset_outcome_record(
    outcome: ConversationResetOutcome,
) -> ConversationResetOutcomeRecord:
    return ConversationResetOutcomeRecord(
        status=outcome.status,
        message=outcome.message,
    )


def provider_guidance_preview_record(
    preview: ProviderGuidancePreview,
) -> ProviderGuidancePreviewRecord:
    return ProviderGuidancePreviewRecord(
        provider=preview.provider,
        published_guidance=preview.published_guidance,
        preview_guidance=preview.preview_guidance,
        preview_source=preview.preview_source,
        composed_prompt=preview.composed_prompt,
        active_skill_tools_summary=preview.active_skill_tools_summary,
        provider_config=RegistryJsonRecord(preview.provider_config.to_dict()),
        prompt_weight=preview.prompt_weight,
    )


def provider_guidance_lifecycle_detail_record(
    detail: ProviderGuidanceLifecycleDetail,
) -> ProviderGuidanceLifecycleDetailRecord:
    return ProviderGuidanceLifecycleDetailRecord(
        provider=detail.provider,
        scope_kind=detail.scope_kind,
        scope_key=detail.scope_key,
        draft_body=detail.draft_body,
        published_body=detail.published_body,
        lifecycle_status=detail.lifecycle_status,
        active_revision_id=detail.active_revision_id,
        published_revision_id=detail.published_revision_id,
        runtime_available=detail.runtime_available,
        revisions=[
            ProviderGuidanceLifecycleRevisionRecord(
                revision_id=item.revision_id,
                status=item.status,
                created_by=item.created_by,
                created_at=item.created_at,
                is_published=item.is_published,
            )
            for item in detail.revisions
        ],
        approvals=[
            ProviderGuidanceLifecycleApprovalRecord(
                revision_id=item.revision_id,
                action=item.action,
                actor=item.actor,
                note=item.note,
                created_at=item.created_at,
            )
            for item in detail.approvals
        ],
    )


def provider_guidance_lifecycle_mutation_record(
    mutation: ProviderGuidanceLifecycleMutation,
) -> ProviderGuidanceLifecycleMutationRecord:
    return ProviderGuidanceLifecycleMutationRecord(
        status=mutation.status,
        ok=mutation.ok,
        message=mutation.message,
        detail=(
            provider_guidance_lifecycle_detail_record(mutation.detail)
            if mutation.detail is not None
            else None
        ),
    )


class ListCatalogSkillsRequest(RegistryRecordModel):
    operation: Literal["list_catalog_skills"] = "list_catalog_skills"
    query: str = ""


class SearchCatalogSkillsRequest(RegistryRecordModel):
    operation: Literal["search_catalog_skills"] = "search_catalog_skills"
    query: str = ""


class CatalogSkillDetailRequest(RegistryRecordModel):
    operation: Literal["catalog_skill_detail"] = "catalog_skill_detail"
    skill_name: str


class CatalogSkillLifecycleDetailRequest(RegistryRecordModel):
    operation: Literal["catalog_skill_lifecycle_detail"] = "catalog_skill_lifecycle_detail"
    skill_name: str


class EditCatalogSkillDraftRequest(RegistryRecordModel):
    operation: Literal["edit_catalog_skill_draft"] = "edit_catalog_skill_draft"
    skill_name: str
    actor_key: str
    body: str | None = None
    display_name: str | None = None
    description: str | None = None
    skill_kind: str | None = None
    requirements: list[SkillRequirementRecord] | None = None
    provider_config: RegistryJsonRecord | None = None
    files: list[SkillFileRecord] | None = None
    changelog: str = ""


class ExportCatalogSkillPackageRequest(RegistryRecordModel):
    operation: Literal["export_catalog_skill_package"] = "export_catalog_skill_package"
    skill_name: str
    revision_scope: Literal["draft", "published"] = "draft"
    format: Literal["json", "yaml"] = "json"


class ImportCatalogSkillPackageRequest(RegistryRecordModel):
    operation: Literal["import_catalog_skill_package"] = "import_catalog_skill_package"
    actor_key: str
    target_skill_name: str = ""
    file_name: str = ""
    document_text: str
    format: Literal["json", "yaml"] = "json"


class SubmitCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["submit_catalog_skill"] = "submit_catalog_skill"
    skill_name: str
    actor_key: str
    note: str = ""


class ApproveCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["approve_catalog_skill"] = "approve_catalog_skill"
    skill_name: str
    actor_key: str
    note: str = ""


class RejectCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["reject_catalog_skill"] = "reject_catalog_skill"
    skill_name: str
    actor_key: str
    note: str = ""


class PublishCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["publish_catalog_skill"] = "publish_catalog_skill"
    skill_name: str
    actor_key: str
    note: str = ""


class ArchiveCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["archive_catalog_skill"] = "archive_catalog_skill"
    skill_name: str
    actor_key: str
    note: str = ""


class InstallCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["install_catalog_skill"] = "install_catalog_skill"
    skill_name: str


class UninstallCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["uninstall_catalog_skill"] = "uninstall_catalog_skill"
    skill_name: str


class UpdateCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["update_catalog_skill"] = "update_catalog_skill"
    skill_name: str


class DiffCatalogSkillRequest(RegistryRecordModel):
    operation: Literal["diff_catalog_skill"] = "diff_catalog_skill"
    skill_name: str


class ConversationSkillStateRequest(RegistryRecordModel):
    operation: Literal["conversation_skill_state"] = "conversation_skill_state"
    conversation_id: str
    conversation_key: str


class ActivateConversationSkillRequest(RegistryRecordModel):
    operation: Literal["activate_conversation_skill"] = "activate_conversation_skill"
    conversation_id: str
    conversation_key: str
    actor_key: str
    skill_name: str
    confirm: bool = False


class DeactivateConversationSkillRequest(RegistryRecordModel):
    operation: Literal["deactivate_conversation_skill"] = "deactivate_conversation_skill"
    conversation_id: str
    conversation_key: str
    actor_key: str
    skill_name: str


class ClearConversationSkillsRequest(RegistryRecordModel):
    operation: Literal["clear_conversation_skills"] = "clear_conversation_skills"
    conversation_id: str
    conversation_key: str
    actor_key: str


class SubmitConversationSkillCredentialRequest(RegistryRecordModel):
    operation: Literal["submit_conversation_skill_credential"] = "submit_conversation_skill_credential"
    conversation_id: str
    conversation_key: str
    actor_key: str
    skill_name: str
    value: str


class ConversationSettingsStateRequest(RegistryRecordModel):
    operation: Literal["conversation_settings_state"] = "conversation_settings_state"
    conversation_id: str
    conversation_key: str


class SetConversationSettingRequest(RegistryRecordModel):
    operation: Literal["set_conversation_setting"] = "set_conversation_setting"
    conversation_id: str
    conversation_key: str
    actor_key: str
    setting: Literal["approval_mode", "compact_mode", "role", "model_profile", "project", "file_policy"]
    value: str = ""


class ResetConversationRequest(RegistryRecordModel):
    operation: Literal["reset_conversation"] = "reset_conversation"
    conversation_id: str
    conversation_key: str
    actor_key: str


class ResetExecutionFaultRequest(RegistryRecordModel):
    operation: Literal["reset_execution_fault"] = "reset_execution_fault"
    actor_key: str


class PreviewProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["preview_provider_guidance"] = "preview_provider_guidance"
    provider_name: str
    role: str = ""
    active_skills: list[str] = Field(default_factory=list)
    compact_mode: bool = False
    use_draft: bool = False
    body_override: str = ""


class ProviderGuidanceDetailRequest(RegistryRecordModel):
    operation: Literal["provider_guidance_detail"] = "provider_guidance_detail"
    provider_name: str
    scope_kind: str = "system"
    scope_key: str = ""


class EditProviderGuidanceDraftRequest(RegistryRecordModel):
    operation: Literal["edit_provider_guidance_draft"] = "edit_provider_guidance_draft"
    provider_name: str
    actor_key: str
    body: str
    scope_kind: str = "system"
    scope_key: str = ""


class SubmitProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["submit_provider_guidance"] = "submit_provider_guidance"
    provider_name: str
    actor_key: str
    note: str = ""
    scope_kind: str = "system"
    scope_key: str = ""


class ApproveProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["approve_provider_guidance"] = "approve_provider_guidance"
    provider_name: str
    actor_key: str
    note: str = ""
    scope_kind: str = "system"
    scope_key: str = ""


class RejectProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["reject_provider_guidance"] = "reject_provider_guidance"
    provider_name: str
    actor_key: str
    note: str = ""
    scope_kind: str = "system"
    scope_key: str = ""


class PublishProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["publish_provider_guidance"] = "publish_provider_guidance"
    provider_name: str
    actor_key: str
    note: str = ""
    scope_kind: str = "system"
    scope_key: str = ""


class ArchiveProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["archive_provider_guidance"] = "archive_provider_guidance"
    provider_name: str
    actor_key: str
    note: str = ""
    scope_kind: str = "system"
    scope_key: str = ""


class DesignAutoProtocolRequest(RegistryRecordModel):
    operation: Literal["design_auto_protocol"] = "design_auto_protocol"
    request: ProtocolAutoDesignModelRequestRecord


class StartArtifactRuntimeRequest(RegistryRecordModel):
    operation: Literal["start_artifact_runtime"] = "start_artifact_runtime"
    runtime_instance_id: str
    protocol_run_id: str
    artifact_key: str
    artifact_path: str
    manifest_path: str = ""
    manifest: ProtocolArtifactRuntimeManifestRecord
    actor_ref: str = ""


class StopArtifactRuntimeRequest(RegistryRecordModel):
    operation: Literal["stop_artifact_runtime"] = "stop_artifact_runtime"
    runtime_instance_id: str
    protocol_run_id: str
    artifact_key: str
    actor_ref: str = ""


class ArtifactRuntimeHealthRequest(RegistryRecordModel):
    operation: Literal["artifact_runtime_health"] = "artifact_runtime_health"
    runtime_instance_id: str
    protocol_run_id: str
    artifact_key: str


class ArtifactRuntimeLogsRequest(RegistryRecordModel):
    operation: Literal["artifact_runtime_logs"] = "artifact_runtime_logs"
    runtime_instance_id: str
    protocol_run_id: str
    artifact_key: str
    max_bytes: int = Field(default=12000, ge=1000, le=120000)


class ArtifactRuntimeFetchRequest(RegistryRecordModel):
    operation: Literal["artifact_runtime_fetch"] = "artifact_runtime_fetch"
    runtime_instance_id: str
    protocol_run_id: str
    artifact_key: str
    method: str = "GET"
    path: str = "/"
    query_string: str = ""
    headers: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    body_base64: str = ""


class WorkspaceCleanupEntryRecord(RegistryRecordModel):
    path: str = ""
    category: str = "unknown"
    size_bytes: int = 0
    file_count: int = 0
    safe_to_delete: bool = False
    reason: str = ""


class WorkspaceCleanupPlanRecord(RegistryRecordModel):
    inventory_id: str = ""
    agent_id: str = ""
    workspace_ref: str = ""
    protocol_run_id: str = ""
    categories: list[str] = Field(default_factory=list)
    entries: list[WorkspaceCleanupEntryRecord] = Field(default_factory=list)
    total_bytes: int = 0
    retained_bytes: int = 0
    transient_bytes: int = 0
    unknown_bytes: int = 0
    deletable_bytes: int = 0
    file_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)


class WorkspaceUsageRequest(RegistryRecordModel):
    operation: Literal["workspace_usage"] = "workspace_usage"
    workspace_ref: str = ""
    protocol_run_id: str = ""
    categories: list[str] = Field(default_factory=list)
    older_than: str = ""
    include_archived: bool = False
    include_failed: bool = True
    max_entries: int = Field(default=250, ge=1, le=1000)


class WorkspaceCleanupRequest(RegistryRecordModel):
    operation: Literal["workspace_cleanup"] = "workspace_cleanup"
    plan: WorkspaceCleanupPlanRecord
    confirm: str = ""


ManagementRequestPayload = Annotated[
    ListCatalogSkillsRequest
    | SearchCatalogSkillsRequest
    | CatalogSkillDetailRequest
    | CatalogSkillLifecycleDetailRequest
    | EditCatalogSkillDraftRequest
    | ExportCatalogSkillPackageRequest
    | ImportCatalogSkillPackageRequest
    | SubmitCatalogSkillRequest
    | ApproveCatalogSkillRequest
    | RejectCatalogSkillRequest
    | PublishCatalogSkillRequest
    | ArchiveCatalogSkillRequest
    | InstallCatalogSkillRequest
    | UninstallCatalogSkillRequest
    | UpdateCatalogSkillRequest
    | DiffCatalogSkillRequest
    | ConversationSkillStateRequest
    | ActivateConversationSkillRequest
    | DeactivateConversationSkillRequest
    | ClearConversationSkillsRequest
    | SubmitConversationSkillCredentialRequest
    | ConversationSettingsStateRequest
    | SetConversationSettingRequest
    | ResetConversationRequest
    | ResetExecutionFaultRequest
    | PreviewProviderGuidanceRequest
    | ProviderGuidanceDetailRequest
    | EditProviderGuidanceDraftRequest
    | SubmitProviderGuidanceRequest
    | ApproveProviderGuidanceRequest
    | RejectProviderGuidanceRequest
    | PublishProviderGuidanceRequest
    | ArchiveProviderGuidanceRequest
    | DesignAutoProtocolRequest
    | StartArtifactRuntimeRequest
    | StopArtifactRuntimeRequest
    | ArtifactRuntimeHealthRequest
    | ArtifactRuntimeLogsRequest
    | ArtifactRuntimeFetchRequest
    | WorkspaceUsageRequest
    | WorkspaceCleanupRequest,
    Field(discriminator="operation"),
]


class ListCatalogSkillsResult(RegistryRecordModel):
    operation: Literal["list_catalog_skills"] = "list_catalog_skills"
    items: tuple[RuntimeSkillCatalogItemRecord, ...] = ()


class SearchCatalogSkillsResult(RegistryRecordModel):
    operation: Literal["search_catalog_skills"] = "search_catalog_skills"
    results: RuntimeSkillSearchResultsRecord


class CatalogSkillDetailResult(RegistryRecordModel):
    operation: Literal["catalog_skill_detail"] = "catalog_skill_detail"
    detail: RuntimeSkillDetailRecord | None = None


class CatalogSkillLifecycleDetailResult(RegistryRecordModel):
    operation: Literal["catalog_skill_lifecycle_detail"] = "catalog_skill_lifecycle_detail"
    detail: RuntimeSkillLifecycleDetailRecord | None = None


class EditCatalogSkillDraftResult(RegistryRecordModel):
    operation: Literal["edit_catalog_skill_draft"] = "edit_catalog_skill_draft"
    result: RuntimeSkillLifecycleMutationRecord


class ExportCatalogSkillPackageResult(RegistryRecordModel):
    operation: Literal["export_catalog_skill_package"] = "export_catalog_skill_package"
    artifact: RuntimeSkillPackageArtifactRecord | None = None


class ImportCatalogSkillPackageResult(RegistryRecordModel):
    operation: Literal["import_catalog_skill_package"] = "import_catalog_skill_package"
    result: RuntimeSkillLifecycleMutationRecord


class SubmitCatalogSkillResult(RegistryRecordModel):
    operation: Literal["submit_catalog_skill"] = "submit_catalog_skill"
    result: RuntimeSkillLifecycleMutationRecord


class ApproveCatalogSkillResult(RegistryRecordModel):
    operation: Literal["approve_catalog_skill"] = "approve_catalog_skill"
    result: RuntimeSkillLifecycleMutationRecord


class RejectCatalogSkillResult(RegistryRecordModel):
    operation: Literal["reject_catalog_skill"] = "reject_catalog_skill"
    result: RuntimeSkillLifecycleMutationRecord


class PublishCatalogSkillResult(RegistryRecordModel):
    operation: Literal["publish_catalog_skill"] = "publish_catalog_skill"
    result: RuntimeSkillLifecycleMutationRecord


class ArchiveCatalogSkillResult(RegistryRecordModel):
    operation: Literal["archive_catalog_skill"] = "archive_catalog_skill"
    result: RuntimeSkillLifecycleMutationRecord


class InstallCatalogSkillResult(RegistryRecordModel):
    operation: Literal["install_catalog_skill"] = "install_catalog_skill"
    result: RuntimeSkillMutationOutcomeRecord


class UninstallCatalogSkillResult(RegistryRecordModel):
    operation: Literal["uninstall_catalog_skill"] = "uninstall_catalog_skill"
    result: RuntimeSkillMutationOutcomeRecord


class UpdateCatalogSkillResult(RegistryRecordModel):
    operation: Literal["update_catalog_skill"] = "update_catalog_skill"
    result: RuntimeSkillMutationOutcomeRecord


class DiffCatalogSkillResult(RegistryRecordModel):
    operation: Literal["diff_catalog_skill"] = "diff_catalog_skill"
    result: RuntimeSkillMutationOutcomeRecord


class ConversationSkillStateResult(RegistryRecordModel):
    operation: Literal["conversation_skill_state"] = "conversation_skill_state"
    conversation_id: str
    conversation_key: str
    listing: ConversationSkillListingRecord
    pending_setup: ConversationSkillSetupPromptRecord | None = None


class ActivateConversationSkillResult(RegistryRecordModel):
    operation: Literal["activate_conversation_skill"] = "activate_conversation_skill"
    result: ConversationSkillMutationOutcomeRecord


class DeactivateConversationSkillResult(RegistryRecordModel):
    operation: Literal["deactivate_conversation_skill"] = "deactivate_conversation_skill"
    result: ConversationSkillMutationOutcomeRecord


class ClearConversationSkillsResult(RegistryRecordModel):
    operation: Literal["clear_conversation_skills"] = "clear_conversation_skills"
    result: ConversationSkillMutationOutcomeRecord


class SubmitConversationSkillCredentialResult(RegistryRecordModel):
    operation: Literal["submit_conversation_skill_credential"] = "submit_conversation_skill_credential"
    result: ConversationSkillSetupAdvanceOutcomeRecord


class ConversationSettingsStateResult(RegistryRecordModel):
    operation: Literal["conversation_settings_state"] = "conversation_settings_state"
    state: ConversationSettingsStateRecord


class SetConversationSettingResult(RegistryRecordModel):
    operation: Literal["set_conversation_setting"] = "set_conversation_setting"
    result: ConversationSettingMutationRecord
    state: ConversationSettingsStateRecord


class ResetConversationResult(RegistryRecordModel):
    operation: Literal["reset_conversation"] = "reset_conversation"
    result: ConversationResetOutcomeRecord
    state: ConversationSettingsStateRecord


class ResetExecutionFaultResult(RegistryRecordModel):
    operation: Literal["reset_execution_fault"] = "reset_execution_fault"
    state: ExecutionStateRecord


class PreviewProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["preview_provider_guidance"] = "preview_provider_guidance"
    preview: ProviderGuidancePreviewRecord


class ProviderGuidanceDetailResult(RegistryRecordModel):
    operation: Literal["provider_guidance_detail"] = "provider_guidance_detail"
    detail: ProviderGuidanceLifecycleDetailRecord | None = None


class EditProviderGuidanceDraftResult(RegistryRecordModel):
    operation: Literal["edit_provider_guidance_draft"] = "edit_provider_guidance_draft"
    result: ProviderGuidanceLifecycleMutationRecord


class SubmitProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["submit_provider_guidance"] = "submit_provider_guidance"
    result: ProviderGuidanceLifecycleMutationRecord


class ApproveProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["approve_provider_guidance"] = "approve_provider_guidance"
    result: ProviderGuidanceLifecycleMutationRecord


class RejectProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["reject_provider_guidance"] = "reject_provider_guidance"
    result: ProviderGuidanceLifecycleMutationRecord


class PublishProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["publish_provider_guidance"] = "publish_provider_guidance"
    result: ProviderGuidanceLifecycleMutationRecord


class ArchiveProviderGuidanceResult(RegistryRecordModel):
    operation: Literal["archive_provider_guidance"] = "archive_provider_guidance"
    result: ProviderGuidanceLifecycleMutationRecord


class DesignAutoProtocolResult(RegistryRecordModel):
    operation: Literal["design_auto_protocol"] = "design_auto_protocol"
    response: ProtocolAutoDesignModelResponseRecord


class StartArtifactRuntimeResult(RegistryRecordModel):
    operation: Literal["start_artifact_runtime"] = "start_artifact_runtime"
    result: ProtocolArtifactRuntimeActionResultRecord


class StopArtifactRuntimeResult(RegistryRecordModel):
    operation: Literal["stop_artifact_runtime"] = "stop_artifact_runtime"
    result: ProtocolArtifactRuntimeActionResultRecord


class ArtifactRuntimeHealthResult(RegistryRecordModel):
    operation: Literal["artifact_runtime_health"] = "artifact_runtime_health"
    health: ProtocolArtifactRuntimeHealthRecord


class ArtifactRuntimeLogsResult(RegistryRecordModel):
    operation: Literal["artifact_runtime_logs"] = "artifact_runtime_logs"
    runtime: ProtocolArtifactRuntimeInstanceRecord
    log_tail: str = ""


class ArtifactRuntimeFetchResult(RegistryRecordModel):
    operation: Literal["artifact_runtime_fetch"] = "artifact_runtime_fetch"
    runtime: ProtocolArtifactRuntimeInstanceRecord | None = None
    status_code: int = 0
    headers: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)
    body_base64: str = ""


class WorkspaceUsageResult(RegistryRecordModel):
    operation: Literal["workspace_usage"] = "workspace_usage"
    plan: WorkspaceCleanupPlanRecord


class WorkspaceCleanupResult(RegistryRecordModel):
    operation: Literal["workspace_cleanup"] = "workspace_cleanup"
    plan: WorkspaceCleanupPlanRecord
    removed_paths: list[str] = Field(default_factory=list)
    removed_bytes: int = 0
    failures: list[str] = Field(default_factory=list)


ManagementResultPayload = Annotated[
    ListCatalogSkillsResult
    | SearchCatalogSkillsResult
    | CatalogSkillDetailResult
    | CatalogSkillLifecycleDetailResult
    | EditCatalogSkillDraftResult
    | ExportCatalogSkillPackageResult
    | ImportCatalogSkillPackageResult
    | SubmitCatalogSkillResult
    | ApproveCatalogSkillResult
    | RejectCatalogSkillResult
    | PublishCatalogSkillResult
    | ArchiveCatalogSkillResult
    | InstallCatalogSkillResult
    | UninstallCatalogSkillResult
    | UpdateCatalogSkillResult
    | DiffCatalogSkillResult
    | ConversationSkillStateResult
    | ActivateConversationSkillResult
    | DeactivateConversationSkillResult
    | ClearConversationSkillsResult
    | SubmitConversationSkillCredentialResult
    | ConversationSettingsStateResult
    | SetConversationSettingResult
    | ResetConversationResult
    | ResetExecutionFaultResult
    | PreviewProviderGuidanceResult
    | ProviderGuidanceDetailResult
    | EditProviderGuidanceDraftResult
    | SubmitProviderGuidanceResult
    | ApproveProviderGuidanceResult
    | RejectProviderGuidanceResult
    | PublishProviderGuidanceResult
    | ArchiveProviderGuidanceResult
    | DesignAutoProtocolResult
    | StartArtifactRuntimeResult
    | StopArtifactRuntimeResult
    | ArtifactRuntimeHealthResult
    | ArtifactRuntimeLogsResult
    | ArtifactRuntimeFetchResult
    | WorkspaceUsageResult
    | WorkspaceCleanupResult,
    Field(discriminator="operation"),
]


class ManagementRequest(RegistryRecordModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    agent_id: str
    payload: ManagementRequestPayload
    created_at: str = Field(default_factory=utcnow_iso)
    timeout_seconds: int = 30

    @property
    def operation(self) -> str:
        return str(self.payload.operation)


class ManagementResult(RegistryRecordModel):
    request_id: str
    agent_id: str
    success: bool
    payload: ManagementResultPayload | None = None
    error_code: ManagementErrorCode | str = ""
    error_detail: str = ""
    completed_at: str = Field(default_factory=utcnow_iso)

    @property
    def operation(self) -> str:
        if self.payload is not None:
            return str(self.payload.operation)
        return ""

def management_operation_supported(
    supported_admin_operations: list[str] | tuple[str, ...] | set[str],
    operation: ManagementOperation | str,
) -> bool:
    return str(operation) in set(supported_admin_operations)
