"""Registry-side management API adapter over the bot management protocol."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
import time

from .management_client import ManagementClientError, RegistryManagementClient
from .store_base import AbstractRegistryStore
from octopus_sdk.identity import conversation_key_for_ref
from octopus_sdk.registry.management import (
    ActivateConversationSkillRequest,
    ActivateConversationSkillResult,
    ArchiveCatalogSkillRequest,
    ArchiveCatalogSkillResult,
    ArchiveProviderGuidanceRequest,
    ArchiveProviderGuidanceResult,
    ApproveCatalogSkillRequest,
    ApproveCatalogSkillResult,
    ApproveProviderGuidanceRequest,
    ApproveProviderGuidanceResult,
    CatalogSkillDetailResult,
    CatalogSkillDetailRequest,
    CatalogSkillLifecycleDetailRequest,
    CatalogSkillLifecycleDetailResult,
    ClearConversationSkillsRequest,
    ConversationSkillStateRequest,
    ConversationSkillStateResult,
    DeactivateConversationSkillRequest,
    DiffCatalogSkillRequest,
    DiffCatalogSkillResult,
    EditCatalogSkillDraftRequest,
    EditCatalogSkillDraftResult,
    EditProviderGuidanceDraftRequest,
    EditProviderGuidanceDraftResult,
    InstallCatalogSkillRequest,
    InstallCatalogSkillResult,
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementResult,
    ManagementResultPayload,
    PreviewProviderGuidanceRequest,
    PreviewProviderGuidanceResult,
    ProviderGuidanceDetailRequest,
    ProviderGuidanceDetailResult,
    PublishCatalogSkillRequest,
    PublishCatalogSkillResult,
    PublishProviderGuidanceRequest,
    PublishProviderGuidanceResult,
    RejectCatalogSkillRequest,
    RejectCatalogSkillResult,
    RejectProviderGuidanceRequest,
    RejectProviderGuidanceResult,
    SearchCatalogSkillsRequest,
    SearchCatalogSkillsResult,
    SubmitCatalogSkillRequest,
    SubmitCatalogSkillResult,
    SubmitProviderGuidanceRequest,
    SubmitProviderGuidanceResult,
    UninstallCatalogSkillRequest,
    UninstallCatalogSkillResult,
    UpdateCatalogSkillRequest,
    UpdateCatalogSkillResult,
)


class RegistryIngressError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class _ManagementReadCacheEntry:
    expires_at: float = 0.0
    value: object | None = None
    error: tuple[int, str] | None = None
    inflight: asyncio.Task[object] | None = None


_MANAGEMENT_READ_CACHE: dict[tuple[str, ...], _ManagementReadCacheEntry] = {}
_MANAGEMENT_CACHE_TTL_SECONDS = 60.0
_MANAGEMENT_SEARCH_CACHE_TTL_SECONDS = 30.0
_MANAGEMENT_ERROR_TTL_SECONDS = 5.0


def _client(store: AbstractRegistryStore) -> RegistryManagementClient:
    return RegistryManagementClient(store)


def _transport_error(result: ManagementResult) -> RegistryIngressError:
    detail = result.error_detail or "Management request failed."
    if result.error_code == "request_timeout":
        return RegistryIngressError(504, detail)
    if result.error_code == "agent_not_connected":
        return RegistryIngressError(503, detail)
    if result.error_code == "capability_not_available":
        return RegistryIngressError(409, detail)
    if detail == "No skill registry configured.":
        return RegistryIngressError(404, detail)
    if detail.startswith("Unknown provider:"):
        return RegistryIngressError(404, "Unknown provider guidance preview target.")
    return RegistryIngressError(400, detail)


def _management_cache_key(*parts: object) -> tuple[str, ...]:
    return tuple(str(part or "") for part in parts)


def _management_cache_value(value: object) -> object:
    return copy.deepcopy(value)


def _invalidate_management_cache(*prefixes: tuple[str, ...]) -> None:
    if not prefixes:
        return
    for key in list(_MANAGEMENT_READ_CACHE):
        if any(key[:len(prefix)] == prefix for prefix in prefixes):
            _MANAGEMENT_READ_CACHE.pop(key, None)


def _invalidate_skill_cache(agent_id: str) -> None:
    _invalidate_management_cache(
        _management_cache_key("skills:list", agent_id),
        _management_cache_key("skills:search", agent_id),
    )


def _invalidate_guidance_cache(agent_id: str, provider_name: str | None = None) -> None:
    if provider_name:
        _invalidate_management_cache(_management_cache_key("guidance", agent_id, provider_name))
        return
    _invalidate_management_cache(_management_cache_key("guidance", agent_id))


async def _cached_read(
    key: tuple[str, ...],
    loader,
    *,
    ttl_seconds: float,
    error_ttl_seconds: float = _MANAGEMENT_ERROR_TTL_SECONDS,
):
    now = time.monotonic()
    entry = _MANAGEMENT_READ_CACHE.get(key)
    if entry and entry.inflight is None and entry.expires_at > now:
        if entry.error is not None:
            raise RegistryIngressError(entry.error[0], entry.error[1])
        return _management_cache_value(entry.value)
    if entry and entry.inflight is not None:
        result = await entry.inflight
        return _management_cache_value(result)

    task = asyncio.create_task(loader())
    pending = _ManagementReadCacheEntry(inflight=task)
    _MANAGEMENT_READ_CACHE[key] = pending
    try:
        value = await task
    except RegistryIngressError as exc:
        if _MANAGEMENT_READ_CACHE.get(key) is pending:
            _MANAGEMENT_READ_CACHE[key] = _ManagementReadCacheEntry(
                expires_at=time.monotonic() + max(0.0, error_ttl_seconds),
                error=(exc.status_code, exc.detail),
            )
        raise
    except Exception:
        if _MANAGEMENT_READ_CACHE.get(key) is pending:
            _MANAGEMENT_READ_CACHE.pop(key, None)
        raise

    if _MANAGEMENT_READ_CACHE.get(key) is pending:
        _MANAGEMENT_READ_CACHE[key] = _ManagementReadCacheEntry(
            expires_at=time.monotonic() + max(0.0, ttl_seconds),
            value=_management_cache_value(value),
        )
    return _management_cache_value(value)


async def _send(
    store: AbstractRegistryStore,
    *,
    agent_id: str,
    payload,
) -> ManagementResultPayload:
    try:
        result = await _client(store).send(agent_id=agent_id, payload=payload)
    except ManagementClientError as exc:
        raise RegistryIngressError(exc.status_code, exc.detail) from exc
    if not result.success or result.payload is None:
        raise _transport_error(result)
    return result.payload


def _raise_for_lifecycle(result) -> None:
    if result.ok:
        return
    if result.status == "missing":
        raise RegistryIngressError(404, result.message)
    raise RegistryIngressError(400, result.message)


def _mutation_payload(result) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": result.status,
        "ok": result.ok,
        "message": result.message,
    }
    if getattr(result, "detail", None) is not None:
        payload["detail"] = result.detail.model_dump(mode="json", by_alias=True)
    return payload


def _conversation_management_key(
    store: AbstractRegistryStore,
    *,
    conversation_id: str,
) -> str:
    conversation = store.get_conversation(conversation_id)
    transport_ref = str(conversation.external_conversation_ref or conversation.conversation_id or "").strip()
    if not transport_ref:
        raise RegistryIngressError(404, f"Unknown conversation: {conversation_id}")
    return conversation_key_for_ref(transport_ref)


def _skill_mutation_payload(result) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": result.name,
        "ok": result.ok,
        "message": result.message,
    }
    if result.prompt_size_warnings:
        payload["prompt_size_warnings"] = list(result.prompt_size_warnings)
    return payload


async def list_catalog_skills(store: AbstractRegistryStore, agent_id: str, query: str = "") -> dict[str, object]:
    query_text = query.strip()

    async def _load() -> dict[str, object]:
        payload = await _send(store, agent_id=agent_id, payload=ListCatalogSkillsRequest(query=query_text))
        assert isinstance(payload, ListCatalogSkillsResult)
        return {"skills": [item.model_dump(mode="json", by_alias=True) for item in payload.items]}

    return await _cached_read(
        _management_cache_key("skills:list", agent_id, query_text),
        _load,
        ttl_seconds=_MANAGEMENT_CACHE_TTL_SECONDS,
    )


async def search_catalog_skills(store: AbstractRegistryStore, agent_id: str, query: str) -> dict[str, object]:
    query_text = query.strip()
    if len(query_text) < 2:
        return {"catalog": [], "registry": []}

    async def _load() -> dict[str, object]:
        payload = await _send(store, agent_id=agent_id, payload=SearchCatalogSkillsRequest(query=query_text))
        assert isinstance(payload, SearchCatalogSkillsResult)
        return payload.results.model_dump(mode="json", by_alias=True)

    return await _cached_read(
        _management_cache_key("skills:search", agent_id, query_text.lower()),
        _load,
        ttl_seconds=_MANAGEMENT_SEARCH_CACHE_TTL_SECONDS,
    )


async def catalog_skill_detail(store: AbstractRegistryStore, agent_id: str, skill_name: str) -> dict[str, object]:
    payload = await _send(store, agent_id=agent_id, payload=CatalogSkillDetailRequest(skill_name=skill_name))
    assert isinstance(payload, CatalogSkillDetailResult)
    if payload.detail is None:
        raise RegistryIngressError(404, f"Unknown skill: {skill_name}")
    return payload.detail.model_dump(mode="json", by_alias=True)


async def catalog_skill_lifecycle_detail(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=CatalogSkillLifecycleDetailRequest(skill_name=skill_name),
    )
    assert isinstance(payload, CatalogSkillLifecycleDetailResult)
    if payload.detail is None:
        raise RegistryIngressError(404, f"Unknown custom skill: {skill_name}")
    return payload.detail.model_dump(mode="json", by_alias=True)


async def edit_catalog_skill_draft(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    body: str,
    description: str | None = None,
    changelog: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=EditCatalogSkillDraftRequest(
            skill_name=skill_name,
            actor_key=actor_key,
            body=body,
            description=description or "",
            changelog=changelog,
        ),
    )
    assert isinstance(payload, EditCatalogSkillDraftResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def submit_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    note: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=SubmitCatalogSkillRequest(skill_name=skill_name, actor_key=actor_key, note=note),
    )
    assert isinstance(payload, SubmitCatalogSkillResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def approve_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    note: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ApproveCatalogSkillRequest(skill_name=skill_name, actor_key=actor_key, note=note),
    )
    assert isinstance(payload, ApproveCatalogSkillResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def reject_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    note: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=RejectCatalogSkillRequest(skill_name=skill_name, actor_key=actor_key, note=note),
    )
    assert isinstance(payload, RejectCatalogSkillResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def publish_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    note: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=PublishCatalogSkillRequest(skill_name=skill_name, actor_key=actor_key, note=note),
    )
    assert isinstance(payload, PublishCatalogSkillResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def archive_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
    *,
    actor_key: str,
    note: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ArchiveCatalogSkillRequest(skill_name=skill_name, actor_key=actor_key, note=note),
    )
    assert isinstance(payload, ArchiveCatalogSkillResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_skill_cache(agent_id)
    return _mutation_payload(payload.result)


async def install_catalog_skill(store: AbstractRegistryStore, agent_id: str, skill_name: str) -> dict[str, object]:
    payload = await _send(store, agent_id=agent_id, payload=InstallCatalogSkillRequest(skill_name=skill_name))
    assert isinstance(payload, InstallCatalogSkillResult)
    if not payload.result.ok:
        raise RegistryIngressError(404, payload.result.message)
    _invalidate_skill_cache(agent_id)
    return _skill_mutation_payload(payload.result)


async def uninstall_catalog_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    skill_name: str,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=UninstallCatalogSkillRequest(skill_name=skill_name),
    )
    assert isinstance(payload, UninstallCatalogSkillResult)
    if not payload.result.ok:
        raise RegistryIngressError(400, payload.result.message)
    _invalidate_skill_cache(agent_id)
    return _skill_mutation_payload(payload.result)


async def update_catalog_skill(store: AbstractRegistryStore, agent_id: str, skill_name: str) -> dict[str, object]:
    payload = await _send(store, agent_id=agent_id, payload=UpdateCatalogSkillRequest(skill_name=skill_name))
    assert isinstance(payload, UpdateCatalogSkillResult)
    if not payload.result.ok:
        raise RegistryIngressError(400, payload.result.message)
    _invalidate_skill_cache(agent_id)
    return _skill_mutation_payload(payload.result)


async def diff_catalog_skill(store: AbstractRegistryStore, agent_id: str, skill_name: str) -> dict[str, object]:
    payload = await _send(store, agent_id=agent_id, payload=DiffCatalogSkillRequest(skill_name=skill_name))
    assert isinstance(payload, DiffCatalogSkillResult)
    if not payload.result.ok:
        raise RegistryIngressError(400, payload.result.message)
    return {"name": payload.result.name, "ok": payload.result.ok, "diff": payload.result.message}


async def conversation_skill_state(
    store: AbstractRegistryStore,
    agent_id: str,
    conversation_id: str,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ConversationSkillStateRequest(
            conversation_id=conversation_id,
            conversation_key=_conversation_management_key(store, conversation_id=conversation_id),
        ),
    )
    assert isinstance(payload, ConversationSkillStateResult)
    return {
        "conversation_id": payload.conversation_id,
        "conversation_key": payload.conversation_key,
        "active_skills": list(payload.listing.active_skills),
        "active_skill_details": [
            item.model_dump(mode="json", by_alias=True)
            for item in payload.listing.active_skill_details
        ],
    }


def _conversation_mutation_payload(result) -> dict[str, object]:
    payload: dict[str, object] = {"status": result.status}
    if result.first_requirement is not None:
        payload["first_requirement"] = result.first_requirement.model_dump(mode="json", by_alias=True)
    if result.projected_size:
        payload["projected_size"] = result.projected_size
    if result.prompt_size_threshold:
        payload["prompt_size_threshold"] = result.prompt_size_threshold
    if result.foreign_setup_user:
        payload["foreign_setup_user"] = result.foreign_setup_user
    return payload


async def activate_conversation_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
    confirm: bool,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ActivateConversationSkillRequest(
            conversation_id=conversation_id,
            conversation_key=_conversation_management_key(store, conversation_id=conversation_id),
            actor_key=actor_key,
            skill_name=skill_name,
            confirm=confirm,
        ),
    )
    result = payload.result
    if result.status == "unknown":
        raise RegistryIngressError(404, f"Unknown skill: {skill_name}")
    return _conversation_mutation_payload(result)


async def deactivate_conversation_skill(
    store: AbstractRegistryStore,
    agent_id: str,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=DeactivateConversationSkillRequest(
            conversation_id=conversation_id,
            conversation_key=_conversation_management_key(store, conversation_id=conversation_id),
            actor_key=actor_key,
            skill_name=skill_name,
        ),
    )
    result = payload.result
    if result.status == "foreign_setup":
        raise RegistryIngressError(409, "credential_setup_in_progress")
    return {"status": result.status}


async def clear_conversation_skills(
    store: AbstractRegistryStore,
    agent_id: str,
    conversation_id: str,
    *,
    actor_key: str,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ClearConversationSkillsRequest(
            conversation_id=conversation_id,
            conversation_key=_conversation_management_key(store, conversation_id=conversation_id),
            actor_key=actor_key,
        ),
    )
    result = payload.result
    if result.status == "foreign_setup":
        raise RegistryIngressError(409, "credential_setup_in_progress")
    return {"status": result.status}


async def preview_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    role: str,
    active_skills: list[str],
    compact_mode: bool,
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=PreviewProviderGuidanceRequest(
            provider_name=provider_name,
            role=role,
            active_skills=list(active_skills),
            compact_mode=compact_mode,
        ),
    )
    assert isinstance(payload, PreviewProviderGuidanceResult)
    return payload.preview.model_dump(mode="json", by_alias=True)


async def provider_guidance_detail(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    async def _load() -> dict[str, object]:
        payload = await _send(
            store,
            agent_id=agent_id,
            payload=ProviderGuidanceDetailRequest(
                provider_name=provider_name,
                scope_kind=scope_kind,
                scope_key=scope_key,
            ),
        )
        assert isinstance(payload, ProviderGuidanceDetailResult)
        if payload.detail is None:
            raise RegistryIngressError(404, f"Unknown provider guidance: {provider_name}")
        return payload.detail.model_dump(mode="json", by_alias=True)

    return await _cached_read(
        _management_cache_key("guidance", agent_id, provider_name, scope_kind, scope_key),
        _load,
        ttl_seconds=_MANAGEMENT_CACHE_TTL_SECONDS,
    )


async def edit_provider_guidance_draft(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    body: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=EditProviderGuidanceDraftRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            body=body,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, EditProviderGuidanceDraftResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


async def submit_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=SubmitProviderGuidanceRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, SubmitProviderGuidanceResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


async def approve_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ApproveProviderGuidanceRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, ApproveProviderGuidanceResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


async def reject_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=RejectProviderGuidanceRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, RejectProviderGuidanceResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


async def publish_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=PublishProviderGuidanceRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, PublishProviderGuidanceResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


async def archive_provider_guidance(
    store: AbstractRegistryStore,
    agent_id: str,
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, object]:
    payload = await _send(
        store,
        agent_id=agent_id,
        payload=ArchiveProviderGuidanceRequest(
            provider_name=provider_name,
            actor_key=actor_key,
            note=note,
            scope_kind=scope_kind,
            scope_key=scope_key,
        ),
    )
    assert isinstance(payload, ArchiveProviderGuidanceResult)
    _raise_for_lifecycle(payload.result)
    _invalidate_guidance_cache(agent_id, provider_name)
    return _mutation_payload(payload.result)


def reset_for_test() -> None:
    _MANAGEMENT_READ_CACHE.clear()
