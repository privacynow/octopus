"""Shared runtime-surface access for registry skill and guidance APIs.

The registry remains the only public HTTP API, but it should call the same
runtime services in-process rather than forcing the bot through HTTP for
catalog/guidance/session-backed lifecycle work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from app.content_store import init_content_store_for_config, reset_for_test as reset_content_store_for_test
from app.credential_store import (
    init_credential_store_for_config,
    reset_for_test as reset_credential_store_for_test,
)
from app.agents.bridge import conversation_key_for_ref
from app.execution_context import resolve_execution_context
from app.inbound_use_case_factory import (
    get_provider_guidance_use_cases,
    get_runtime_skill_activation_use_cases,
    get_runtime_skill_catalog_use_cases,
    get_runtime_skill_import_use_cases,
)
from app.registry_service.store_base import AbstractRegistryStore
from app import runtime_backend
from app.config import BotConfig, load_config_provider_health
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.workflows.runtime_skills.contracts import PromptWarningContext
from app.session_state import SessionState, session_from_dict, session_to_dict
from app.storage import load_session, save_session

ProviderStateFactory = Callable[[], dict[str, Any]]

_context: "RuntimeSurfaceContext | None" = None


@dataclass(frozen=True)
class RuntimeSurfaceContext:
    config: BotConfig
    provider_state_factory: ProviderStateFactory


@dataclass(frozen=True)
class RuntimeConversationContext:
    context: RuntimeSurfaceContext
    conversation_key: str
    session: SessionState


class RuntimeSurfaceError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def get_runtime_surface_context() -> RuntimeSurfaceContext:
    global _context
    if _context is None:
        config = load_config_provider_health()
        runtime_backend.init(config)
        init_content_store_for_config(config)
        init_credential_store_for_config(config)
        if config.provider_name == "codex":
            provider_state_factory = CodexProvider(config).new_provider_state
        else:
            provider_state_factory = ClaudeProvider(config).new_provider_state
        _context = RuntimeSurfaceContext(
            config=config,
            provider_state_factory=provider_state_factory,
        )
    return _context


def runtime_registry_url() -> str:
    return os.environ.get("BOT_REGISTRY_URL", "").strip()


def prompt_warning_context() -> PromptWarningContext | None:
    try:
        context = get_runtime_surface_context()
    except Exception:
        return None
    return PromptWarningContext(
        data_dir=context.config.data_dir,
        provider_name=context.config.provider_name,
        provider_state_factory=context.provider_state_factory,
        approval_mode=context.config.approval_mode,
    )


def load_runtime_conversation(store: AbstractRegistryStore, conversation_id: str) -> RuntimeConversationContext:
    try:
        store.get_conversation(conversation_id)
    except KeyError as exc:
        raise RuntimeSurfaceError(404, f"Unknown conversation: {conversation_id}") from exc
    context = get_runtime_surface_context()
    conversation_key = conversation_key_for_ref(conversation_id)
    raw = load_session(
        context.config.data_dir,
        conversation_key,
        context.config.provider_name,
        context.provider_state_factory,
        context.config.approval_mode,
        default_skills=context.config.default_skills,
    )
    return RuntimeConversationContext(
        context=context,
        conversation_key=conversation_key,
        session=session_from_dict(raw),
    )


def list_catalog_skills(query: str = "") -> dict[str, Any]:
    return {
        "skills": [
            {
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
            }
            for item in get_runtime_skill_catalog_use_cases().list_skills(query)
        ]
    }


def search_catalog_skills(query: str) -> dict[str, Any]:
    query_text = query.strip()
    if len(query_text) < 2:
        return {"catalog": [], "registry": []}
    results = get_runtime_skill_import_use_cases().search(query_text, registry_url=runtime_registry_url())
    return {
        "catalog": [
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "source_kind": item.source_kind,
                "can_activate": item.can_activate,
                "can_update": item.can_update,
                "can_uninstall": item.can_uninstall,
            }
            for item in results.catalog
        ],
        "registry": [
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "publisher": item.publisher,
                "version": item.version,
                "can_import": item.can_import,
            }
            for item in results.registry
        ],
        "registry_error": results.registry_error,
    }


def catalog_skill_detail(skill_name: str) -> dict[str, Any]:
    detail = get_runtime_skill_catalog_use_cases().get_skill(skill_name)
    if detail is None:
        raise RuntimeSurfaceError(404, f"Unknown skill: {skill_name}")
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
    }


def install_catalog_skill(skill_name: str) -> dict[str, Any]:
    registry_url = runtime_registry_url()
    if not registry_url:
        raise RuntimeSurfaceError(404, "No skill registry configured.")
    result = get_runtime_skill_import_use_cases().install_from_registry(
        skill_name,
        registry_url,
        warning_context=prompt_warning_context(),
    )
    if not result.ok:
        raise RuntimeSurfaceError(404, result.message)
    response: dict[str, Any] = {
        "name": result.name,
        "ok": result.ok,
        "message": result.message,
    }
    if result.prompt_size_warnings:
        response["prompt_size_warnings"] = list(result.prompt_size_warnings)
    return response


def uninstall_catalog_skill(skill_name: str) -> dict[str, Any]:
    try:
        context = get_runtime_surface_context()
        default_skills = context.config.default_skills
    except Exception:
        default_skills = ()
    result = get_runtime_skill_import_use_cases().uninstall(skill_name, default_skills=default_skills)
    if not result.ok:
        raise RuntimeSurfaceError(400, result.message)
    return {"name": result.name, "ok": result.ok, "message": result.message}


def update_catalog_skill(skill_name: str) -> dict[str, Any]:
    result = get_runtime_skill_import_use_cases().update(
        skill_name,
        warning_context=prompt_warning_context(),
    )
    if not result.ok:
        raise RuntimeSurfaceError(400, result.message)
    response: dict[str, Any] = {
        "name": result.name,
        "ok": result.ok,
        "message": result.message,
    }
    if result.prompt_size_warnings:
        response["prompt_size_warnings"] = list(result.prompt_size_warnings)
    return response


def diff_catalog_skill(skill_name: str) -> dict[str, Any]:
    result = get_runtime_skill_import_use_cases().diff(skill_name)
    if not result.ok:
        raise RuntimeSurfaceError(400, result.message)
    return {"name": result.name, "ok": result.ok, "diff": result.message}


def conversation_skill_state(store: AbstractRegistryStore, conversation_id: str) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    resolved = resolve_execution_context(
        loaded.session,
        loaded.context.config,
        loaded.context.config.provider_name,
        trust_tier="trusted",
    )
    listing = get_runtime_skill_activation_use_cases().list_conversation_skills(
        list(resolved.active_skills)
    )
    return {
        "conversation_id": conversation_id,
        "conversation_key": loaded.conversation_key,
        "active_skills": list(listing.active_skills),
        "active_skill_details": [
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "source_kind": item.source_kind,
                "has_custom_override": item.has_custom_override,
            }
            for item in listing.active_skill_details
        ],
    }


def activate_conversation_skill(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
    confirm: bool,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = get_runtime_skill_activation_use_cases().begin_activate(
        loaded.session,
        user_id=actor_key,
        skill_name=skill_name,
        confirm=confirm,
    )
    if decision.status == "unknown":
        raise RuntimeSurfaceError(404, f"Unknown skill: {skill_name}")
    if decision.mutated:
        save_session(loaded.context.config.data_dir, loaded.conversation_key, session_to_dict(loaded.session))
    response: dict[str, Any] = {"status": decision.status}
    if decision.status == "needs_setup" and decision.first_requirement:
        response["first_requirement"] = decision.first_requirement
    if decision.status == "needs_confirmation":
        response["projected_size"] = decision.projected_size
        response["prompt_size_threshold"] = decision.prompt_size_threshold
    if decision.status == "foreign_setup":
        response["foreign_setup_user"] = decision.foreign_setup.user_id if decision.foreign_setup else ""
    return response


def deactivate_conversation_skill(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = get_runtime_skill_activation_use_cases().deactivate(
        loaded.session,
        user_id=actor_key,
        skill_name=skill_name,
    )
    if decision.status == "foreign_setup":
        raise RuntimeSurfaceError(409, "credential_setup_in_progress")
    if decision.mutated:
        save_session(loaded.context.config.data_dir, loaded.conversation_key, session_to_dict(loaded.session))
    return {"status": decision.status}


def clear_conversation_skills(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = get_runtime_skill_activation_use_cases().clear(loaded.session, user_id=actor_key)
    if decision.status == "foreign_setup":
        raise RuntimeSurfaceError(409, "credential_setup_in_progress")
    if decision.mutated:
        save_session(loaded.context.config.data_dir, loaded.conversation_key, session_to_dict(loaded.session))
    return {"status": decision.status}


def preview_provider_guidance(
    provider_name: str,
    *,
    role: str,
    active_skills: list[str],
    compact_mode: bool,
) -> dict[str, Any]:
    try:
        preview = get_provider_guidance_use_cases().preview(
            provider_name,
            role=role,
            active_skills=list(active_skills),
            compact_mode=compact_mode,
        )
    except ValueError as exc:
        raise RuntimeSurfaceError(404, str(exc)) from exc
    return {
        "provider": preview.provider,
        "effective_guidance": preview.effective_guidance,
        "system_prompt": preview.system_prompt,
        "capability_summary": preview.capability_summary,
        "provider_config": preview.provider_config,
        "prompt_weight": preview.prompt_weight,
    }


def reset_for_test() -> None:
    global _context
    _context = None
    runtime_backend.reset_for_test()
    reset_content_store_for_test()
    reset_credential_store_for_test()
