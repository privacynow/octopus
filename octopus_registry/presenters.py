"""Registry-channel presenters for HTTP response payloads."""

from __future__ import annotations

from typing import Any

from octopus_sdk.workflows.provider_guidance import ProviderGuidancePreview
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleMutation,
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


def catalog_item(item: RuntimeSkillCatalogItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "display_name": item.display_name,
        "description": item.description,
        "source_kind": item.source_kind,
        "has_custom_override": item.has_custom_override,
        "requires_credentials": bool(item.requirement_keys),
        "requirement_keys": list(item.requirement_keys),
        "providers": list(item.providers),
        "can_activate": item.can_activate,
        "can_update": item.can_update,
        "can_uninstall": item.can_uninstall,
        "lifecycle_status": item.lifecycle_status,
    }


def search_catalog_item(item: RuntimeSkillCatalogItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "display_name": item.display_name,
        "description": item.description,
        "source_kind": item.source_kind,
        "can_activate": item.can_activate,
        "can_update": item.can_update,
        "can_uninstall": item.can_uninstall,
        "lifecycle_status": item.lifecycle_status,
    }


def registry_search_hit(item: RegistryRuntimeSkillSearchHit) -> dict[str, Any]:
    return {
        "name": item.name,
        "display_name": item.display_name,
        "description": item.description,
        "publisher": item.publisher,
        "version": item.version,
        "can_import": item.can_import,
    }


def search_results(results: RuntimeSkillSearchResults) -> dict[str, Any]:
    return {
        "catalog": [search_catalog_item(item) for item in results.catalog],
        "registry": [registry_search_hit(item) for item in results.registry],
        "registry_error": results.registry_error,
    }


def catalog_detail(detail: RuntimeSkillDetail) -> dict[str, Any]:
    return {
        "name": detail.name,
        "display_name": detail.display_name,
        "description": detail.description,
        "body": detail.body,
        "source_kind": detail.source_kind,
        "has_custom_override": detail.has_custom_override,
        "providers": list(detail.providers),
        "requirement_keys": list(detail.requirement_keys),
        "can_activate": detail.can_activate,
        "can_update": detail.can_update,
        "can_uninstall": detail.can_uninstall,
        "lifecycle_status": detail.lifecycle_status,
    }


def mutation_result(result: RuntimeSkillMutationOutcome) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": result.name,
        "ok": result.ok,
        "message": result.message,
    }
    if result.prompt_size_warnings:
        payload["prompt_size_warnings"] = list(result.prompt_size_warnings)
    return payload


def diff_result(result: RuntimeSkillMutationOutcome) -> dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "diff": result.message,
    }


def conversation_skill_item(item: ConversationSkillItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "display_name": item.display_name,
        "description": item.description,
        "source_kind": item.source_kind,
        "has_custom_override": item.has_custom_override,
    }


def conversation_skill_state(
    conversation_id: str,
    conversation_key: str,
    listing: ConversationSkillListing,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "conversation_key": conversation_key,
        "active_skills": list(listing.active_skills),
        "active_skill_details": [conversation_skill_item(item) for item in listing.active_skill_details],
    }


def activation_result(decision: ConversationSkillMutationOutcome) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": decision.status}
    if decision.status == "needs_setup" and decision.first_requirement:
        payload["first_requirement"] = decision.first_requirement
    if decision.status == "needs_confirmation":
        payload["projected_size"] = decision.projected_size
        payload["prompt_size_threshold"] = decision.prompt_size_threshold
    if decision.status == "foreign_setup":
        payload["foreign_setup_user"] = decision.foreign_setup.actor_key if decision.foreign_setup else ""
    return payload


def status_result(decision: ConversationSkillMutationOutcome) -> dict[str, Any]:
    return {"status": decision.status}


def provider_guidance_preview(preview: ProviderGuidancePreview) -> dict[str, Any]:
    return {
        "provider": preview.provider,
        "effective_guidance": preview.effective_guidance,
        "system_prompt": preview.system_prompt,
        "capability_summary": preview.capability_summary,
        "provider_config": preview.provider_config,
        "prompt_weight": preview.prompt_weight,
    }


def runtime_skill_lifecycle_detail(detail: RuntimeSkillLifecycleDetail) -> dict[str, Any]:
    return {
        "name": detail.name,
        "display_name": detail.display_name,
        "description": detail.description,
        "visibility": detail.visibility,
        "body": detail.body,
        "lifecycle_status": detail.lifecycle_status,
        "active_revision_id": detail.active_revision_id,
        "published_revision_id": detail.published_revision_id,
        "runtime_available": detail.runtime_available,
        "revisions": [
            {
                "revision_id": item.revision_id,
                "version_label": item.version_label,
                "status": item.status,
                "changelog": item.changelog,
                "created_by": item.created_by,
                "created_at": item.created_at,
                "is_published": item.is_published,
            }
            for item in detail.revisions
        ],
        "approvals": [
            {
                "revision_id": item.revision_id,
                "action": item.action,
                "actor": item.actor,
                "note": item.note,
                "created_at": item.created_at,
            }
            for item in detail.approvals
        ],
    }


def runtime_skill_lifecycle_mutation(result: RuntimeSkillLifecycleMutation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "ok": result.ok,
        "message": result.message,
    }
    if result.detail is not None:
        payload["detail"] = runtime_skill_lifecycle_detail(result.detail)
    return payload


def provider_guidance_lifecycle_detail(detail: ProviderGuidanceLifecycleDetail) -> dict[str, Any]:
    return {
        "provider": detail.provider,
        "scope_kind": detail.scope_kind,
        "scope_key": detail.scope_key,
        "body": detail.body,
        "lifecycle_status": detail.lifecycle_status,
        "active_revision_id": detail.active_revision_id,
        "published_revision_id": detail.published_revision_id,
        "runtime_available": detail.runtime_available,
        "revisions": [
            {
                "revision_id": item.revision_id,
                "status": item.status,
                "created_by": item.created_by,
                "created_at": item.created_at,
                "is_published": item.is_published,
            }
            for item in detail.revisions
        ],
        "approvals": [
            {
                "revision_id": item.revision_id,
                "action": item.action,
                "actor": item.actor,
                "note": item.note,
                "created_at": item.created_at,
            }
            for item in detail.approvals
        ],
    }


def provider_guidance_lifecycle_mutation(result: ProviderGuidanceLifecycleMutation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "ok": result.ok,
        "message": result.message,
    }
    if result.detail is not None:
        payload["detail"] = provider_guidance_lifecycle_detail(result.detail)
    return payload
