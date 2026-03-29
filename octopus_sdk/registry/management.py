"""Typed registry management protocol for connected bots."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel, utcnow_iso
from octopus_sdk.skill_types import SkillRequirement
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
    RuntimeSkillMutationOutcome,
    RuntimeSkillSearchResults,
)

ManagementCapability = Literal[
    "skill_catalog",
    "skill_lifecycle",
    "provider_guidance",
    "conversation_skills",
]

ManagementOperation = Literal[
    "list_catalog_skills",
    "search_catalog_skills",
    "catalog_skill_detail",
    "catalog_skill_lifecycle_detail",
    "edit_catalog_skill_draft",
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
    "preview_provider_guidance",
    "provider_guidance_detail",
    "edit_provider_guidance_draft",
    "submit_provider_guidance",
    "approve_provider_guidance",
    "reject_provider_guidance",
    "publish_provider_guidance",
    "archive_provider_guidance",
]

ManagementErrorCode = Literal[
    "agent_not_connected",
    "capability_not_available",
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


class RuntimeSkillCatalogItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    source_kind: str = ""
    has_custom_override: bool = False
    requires_credentials: bool = False
    requirement_keys: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""


class RuntimeSkillSearchCatalogItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    source_kind: str = ""
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""


class RegistryRuntimeSkillSearchHitRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
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
    source_kind: str = ""
    has_custom_override: bool = False
    providers: list[str] = Field(default_factory=list)
    requirement_keys: list[str] = Field(default_factory=list)
    can_activate: bool = False
    can_update: bool = False
    can_uninstall: bool = False
    lifecycle_status: str = ""


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
    visibility: str = ""
    body: str = ""
    lifecycle_status: str = ""
    active_revision_id: str = ""
    published_revision_id: str = ""
    runtime_available: bool = False
    revisions: list[RuntimeSkillLifecycleRevisionRecord] = Field(default_factory=list)
    approvals: list[RuntimeSkillLifecycleApprovalRecord] = Field(default_factory=list)


class RuntimeSkillLifecycleMutationRecord(RegistryRecordModel):
    status: str = ""
    ok: bool = False
    message: str = ""
    detail: RuntimeSkillLifecycleDetailRecord | None = None


class RuntimeSkillMutationOutcomeRecord(RegistryRecordModel):
    name: str = ""
    ok: bool = False
    message: str = ""
    prompt_size_warnings: list[str] = Field(default_factory=list)


class ConversationSkillItemRecord(RegistryRecordModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    source_kind: str = ""
    has_custom_override: bool = False


class ConversationSkillListingRecord(RegistryRecordModel):
    active_skills: list[str] = Field(default_factory=list)
    active_skill_details: list[ConversationSkillItemRecord] = Field(default_factory=list)


class ConversationSkillMutationOutcomeRecord(RegistryRecordModel):
    status: str = ""
    first_requirement: SkillRequirementRecord | None = None
    projected_size: int = 0
    prompt_size_threshold: int = 0
    foreign_setup_user: str = ""


class ProviderGuidancePreviewRecord(RegistryRecordModel):
    provider: str = ""
    effective_guidance: str = ""
    system_prompt: str = ""
    capability_summary: str = ""
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
    body: str = ""
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


def runtime_skill_catalog_item_record(item: RuntimeSkillCatalogItem) -> RuntimeSkillCatalogItemRecord:
    return RuntimeSkillCatalogItemRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        source_kind=item.source_kind,
        has_custom_override=item.has_custom_override,
        requires_credentials=bool(item.requirement_keys),
        requirement_keys=list(item.requirement_keys),
        providers=list(item.providers),
        can_activate=item.can_activate,
        can_update=item.can_update,
        can_uninstall=item.can_uninstall,
        lifecycle_status=item.lifecycle_status,
    )


def runtime_skill_search_catalog_item_record(
    item: RuntimeSkillCatalogItem,
) -> RuntimeSkillSearchCatalogItemRecord:
    return RuntimeSkillSearchCatalogItemRecord(
        name=item.name,
        display_name=item.display_name,
        description=item.description,
        source_kind=item.source_kind,
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
        source_kind=detail.source_kind,
        has_custom_override=detail.has_custom_override,
        providers=list(detail.providers),
        requirement_keys=list(detail.requirement_keys),
        can_activate=detail.can_activate,
        can_update=detail.can_update,
        can_uninstall=detail.can_uninstall,
        lifecycle_status=detail.lifecycle_status,
    )


def runtime_skill_lifecycle_detail_record(
    detail: RuntimeSkillLifecycleDetail,
) -> RuntimeSkillLifecycleDetailRecord:
    return RuntimeSkillLifecycleDetailRecord(
        name=detail.name,
        display_name=detail.display_name,
        description=detail.description,
        visibility=detail.visibility,
        body=detail.body,
        lifecycle_status=detail.lifecycle_status,
        active_revision_id=detail.active_revision_id,
        published_revision_id=detail.published_revision_id,
        runtime_available=detail.runtime_available,
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
        source_kind=item.source_kind,
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


def provider_guidance_preview_record(
    preview: ProviderGuidancePreview,
) -> ProviderGuidancePreviewRecord:
    return ProviderGuidancePreviewRecord(
        provider=preview.provider,
        effective_guidance=preview.effective_guidance,
        system_prompt=preview.system_prompt,
        capability_summary=preview.capability_summary,
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
        body=detail.body,
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
    body: str
    description: str = ""
    changelog: str = ""


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


class PreviewProviderGuidanceRequest(RegistryRecordModel):
    operation: Literal["preview_provider_guidance"] = "preview_provider_guidance"
    provider_name: str
    role: str = ""
    active_skills: list[str] = Field(default_factory=list)
    compact_mode: bool = False


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


ManagementRequestPayload = Annotated[
    ListCatalogSkillsRequest
    | SearchCatalogSkillsRequest
    | CatalogSkillDetailRequest
    | CatalogSkillLifecycleDetailRequest
    | EditCatalogSkillDraftRequest
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
    | PreviewProviderGuidanceRequest
    | ProviderGuidanceDetailRequest
    | EditProviderGuidanceDraftRequest
    | SubmitProviderGuidanceRequest
    | ApproveProviderGuidanceRequest
    | RejectProviderGuidanceRequest
    | PublishProviderGuidanceRequest
    | ArchiveProviderGuidanceRequest,
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


class ActivateConversationSkillResult(RegistryRecordModel):
    operation: Literal["activate_conversation_skill"] = "activate_conversation_skill"
    result: ConversationSkillMutationOutcomeRecord


class DeactivateConversationSkillResult(RegistryRecordModel):
    operation: Literal["deactivate_conversation_skill"] = "deactivate_conversation_skill"
    result: ConversationSkillMutationOutcomeRecord


class ClearConversationSkillsResult(RegistryRecordModel):
    operation: Literal["clear_conversation_skills"] = "clear_conversation_skills"
    result: ConversationSkillMutationOutcomeRecord


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


ManagementResultPayload = Annotated[
    ListCatalogSkillsResult
    | SearchCatalogSkillsResult
    | CatalogSkillDetailResult
    | CatalogSkillLifecycleDetailResult
    | EditCatalogSkillDraftResult
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
    | PreviewProviderGuidanceResult
    | ProviderGuidanceDetailResult
    | EditProviderGuidanceDraftResult
    | SubmitProviderGuidanceResult
    | ApproveProviderGuidanceResult
    | RejectProviderGuidanceResult
    | PublishProviderGuidanceResult
    | ArchiveProviderGuidanceResult,
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


MANAGEMENT_OPERATION_CAPABILITIES: dict[ManagementOperation, ManagementCapability] = {
    "list_catalog_skills": "skill_catalog",
    "search_catalog_skills": "skill_catalog",
    "catalog_skill_detail": "skill_catalog",
    "install_catalog_skill": "skill_catalog",
    "uninstall_catalog_skill": "skill_catalog",
    "update_catalog_skill": "skill_catalog",
    "diff_catalog_skill": "skill_catalog",
    "catalog_skill_lifecycle_detail": "skill_lifecycle",
    "edit_catalog_skill_draft": "skill_lifecycle",
    "submit_catalog_skill": "skill_lifecycle",
    "approve_catalog_skill": "skill_lifecycle",
    "reject_catalog_skill": "skill_lifecycle",
    "publish_catalog_skill": "skill_lifecycle",
    "archive_catalog_skill": "skill_lifecycle",
    "preview_provider_guidance": "provider_guidance",
    "provider_guidance_detail": "provider_guidance",
    "edit_provider_guidance_draft": "provider_guidance",
    "submit_provider_guidance": "provider_guidance",
    "approve_provider_guidance": "provider_guidance",
    "reject_provider_guidance": "provider_guidance",
    "publish_provider_guidance": "provider_guidance",
    "archive_provider_guidance": "provider_guidance",
    "conversation_skill_state": "conversation_skills",
    "activate_conversation_skill": "conversation_skills",
    "deactivate_conversation_skill": "conversation_skills",
    "clear_conversation_skills": "conversation_skills",
}


def required_management_capability(operation: ManagementOperation | str) -> ManagementCapability:
    return MANAGEMENT_OPERATION_CAPABILITIES[str(operation)]  # type: ignore[index]


def management_capability_supported(
    capabilities: list[str] | tuple[str, ...] | set[str],
    operation: ManagementOperation | str,
) -> bool:
    return required_management_capability(operation) in set(capabilities)
