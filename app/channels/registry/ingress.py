"""Registry channel ingress for runtime-skill and guidance APIs.

The registry remains the only public HTTP API, but it should call the same
runtime services in-process rather than forcing the bot through HTTP for
catalog/guidance/session-backed lifecycle work.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from app.content_store import init_content_store_for_config, reset_for_test as reset_content_store_for_test
from app.credential_store import (
    init_credential_store_for_config,
    reset_for_test as reset_credential_store_for_test,
)
from app.channels.registry import presenters
from app.identity import conversation_key_for_ref
from app.registry_service.store_base import AbstractRegistryStore
from app import runtime_backend
from app.config import BotConfig, load_config_provider_health
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.runtime import composition
from app.runtime.session_runtime import (
    load_runtime_session,
    resolve_session_context,
    save_runtime_session,
)
from app.workflows.runtime_skills.contracts import PromptWarningContext
from app.session_state import SessionState

ProviderStateFactory = Callable[[], dict[str, Any]]

_context: "RuntimeChannelContext | None" = None
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeChannelContext:
    config: BotConfig
    provider_state_factory: ProviderStateFactory


@dataclass(frozen=True)
class RuntimeConversationContext:
    context: RuntimeChannelContext
    conversation_key: str
    session: SessionState


class RegistryIngressError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def get_runtime_channel_context() -> RuntimeChannelContext:
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
        _context = RuntimeChannelContext(
            config=config,
            provider_state_factory=provider_state_factory,
        )
    return _context


def runtime_registry_url() -> str:
    return os.environ.get("BOT_REGISTRY_URL", "").strip()


def _flows():
    return composition.workflows()


def prompt_warning_context() -> PromptWarningContext | None:
    try:
        context = get_runtime_channel_context()
    except Exception as exc:
        log.warning(
            "Registry runtime context unavailable for prompt warnings: %s",
            exc.__class__.__name__,
        )
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
        raise RegistryIngressError(404, f"Unknown conversation: {conversation_id}") from exc
    context = get_runtime_channel_context()
    conversation_key = conversation_key_for_ref(conversation_id)
    return RuntimeConversationContext(
        context=context,
        conversation_key=conversation_key,
        session=load_runtime_session(
            context.config.data_dir,
            conversation_key,
            provider_name=context.config.provider_name,
            provider_state_factory=context.provider_state_factory,
            approval_mode=context.config.approval_mode,
            default_skills=context.config.default_skills,
        ),
    )


def list_catalog_skills(query: str = "") -> dict[str, Any]:
    return {
        "skills": [presenters.catalog_item(item) for item in _flows().runtime_skills.catalog.list_skills(query)]
    }


def search_catalog_skills(query: str) -> dict[str, Any]:
    query_text = query.strip()
    if len(query_text) < 2:
        return {"catalog": [], "registry": []}
    results = _flows().runtime_skills.imports.search(query_text, registry_url=runtime_registry_url())
    return presenters.search_results(results)


def catalog_skill_detail(skill_name: str) -> dict[str, Any]:
    detail = _flows().runtime_skills.catalog.get_skill(skill_name)
    if detail is None:
        raise RegistryIngressError(404, f"Unknown skill: {skill_name}")
    return presenters.catalog_detail(detail)


def catalog_skill_lifecycle_detail(skill_name: str) -> dict[str, Any]:
    detail = _flows().runtime_skills.authoring.detail(skill_name)
    if detail is None:
        raise RegistryIngressError(404, f"Unknown custom skill: {skill_name}")
    return presenters.runtime_skill_lifecycle_detail(detail)


def _raise_for_lifecycle(result) -> None:
    if result.ok:
        return
    if result.status == "missing":
        raise RegistryIngressError(404, result.message)
    raise RegistryIngressError(400, result.message)


def edit_catalog_skill_draft(
    skill_name: str,
    *,
    actor_key: str,
    body: str,
    description: str | None = None,
    changelog: str = "",
) -> dict[str, Any]:
    if _flows().runtime_skills.authoring.detail(skill_name) is None:
        created = _flows().runtime_skills.authoring.create_draft(skill_name, owner_actor=actor_key)
        _raise_for_lifecycle(created)
    result = _flows().runtime_skills.authoring.edit_draft(
        skill_name,
        actor_key=actor_key,
        body=body,
        description=description,
        changelog=changelog,
    )
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def submit_catalog_skill(skill_name: str, *, actor_key: str, note: str = "") -> dict[str, Any]:
    result = _flows().runtime_skills.authoring.submit(skill_name, actor_key=actor_key, note=note)
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def approve_catalog_skill(skill_name: str, *, actor_key: str, note: str = "") -> dict[str, Any]:
    result = _flows().runtime_skills.approval.approve(skill_name, actor_key=actor_key, note=note)
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def reject_catalog_skill(skill_name: str, *, actor_key: str, note: str = "") -> dict[str, Any]:
    result = _flows().runtime_skills.approval.reject(skill_name, actor_key=actor_key, note=note)
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def publish_catalog_skill(skill_name: str, *, actor_key: str, note: str = "") -> dict[str, Any]:
    result = _flows().runtime_skills.authoring.publish(skill_name, actor_key=actor_key, note=note)
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def archive_catalog_skill(skill_name: str, *, actor_key: str, note: str = "") -> dict[str, Any]:
    result = _flows().runtime_skills.authoring.archive(skill_name, actor_key=actor_key, note=note)
    _raise_for_lifecycle(result)
    return presenters.runtime_skill_lifecycle_mutation(result)


def install_catalog_skill(skill_name: str) -> dict[str, Any]:
    registry_url = runtime_registry_url()
    if not registry_url:
        raise RegistryIngressError(404, "No skill registry configured.")
    result = _flows().runtime_skills.imports.install_from_registry(
        skill_name,
        registry_url,
        warning_context=prompt_warning_context(),
    )
    if not result.ok:
        raise RegistryIngressError(404, result.message)
    return presenters.mutation_result(result)


def uninstall_catalog_skill(skill_name: str) -> dict[str, Any]:
    try:
        context = get_runtime_channel_context()
        default_skills = context.config.default_skills
    except Exception as exc:
        log.warning(
            "Registry runtime context unavailable for uninstall default-skill check: %s",
            exc.__class__.__name__,
        )
        default_skills = ()
    result = _flows().runtime_skills.imports.uninstall(skill_name, default_skills=default_skills)
    if not result.ok:
        raise RegistryIngressError(400, result.message)
    return presenters.mutation_result(result)


def update_catalog_skill(skill_name: str) -> dict[str, Any]:
    result = _flows().runtime_skills.imports.update(
        skill_name,
        warning_context=prompt_warning_context(),
    )
    if not result.ok:
        raise RegistryIngressError(400, result.message)
    return presenters.mutation_result(result)


def diff_catalog_skill(skill_name: str) -> dict[str, Any]:
    result = _flows().runtime_skills.imports.diff(skill_name)
    if not result.ok:
        raise RegistryIngressError(400, result.message)
    return presenters.diff_result(result)


def conversation_skill_state(store: AbstractRegistryStore, conversation_id: str) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    resolved = resolve_session_context(
        loaded.session,
        config=loaded.context.config,
        provider_name=loaded.context.config.provider_name,
        trust_tier="trusted",
    )
    listing = _flows().runtime_skills.activation.list_conversation_skills(
        list(resolved.active_skills)
    )
    return presenters.conversation_skill_state(conversation_id, loaded.conversation_key, listing)


def activate_conversation_skill(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
    confirm: bool,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = _flows().runtime_skills.activation.begin_activate(
        loaded.session,
        user_id=actor_key,
        skill_name=skill_name,
        confirm=confirm,
    )
    if decision.status == "unknown":
        raise RegistryIngressError(404, f"Unknown skill: {skill_name}")
    if decision.mutated:
        save_runtime_session(loaded.context.config.data_dir, loaded.conversation_key, loaded.session)
    return presenters.activation_result(decision)


def deactivate_conversation_skill(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
    skill_name: str,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = _flows().runtime_skills.activation.deactivate(
        loaded.session,
        user_id=actor_key,
        skill_name=skill_name,
    )
    if decision.status == "foreign_setup":
        raise RegistryIngressError(409, "credential_setup_in_progress")
    if decision.mutated:
        save_runtime_session(loaded.context.config.data_dir, loaded.conversation_key, loaded.session)
    return presenters.status_result(decision)


def clear_conversation_skills(
    store: AbstractRegistryStore,
    conversation_id: str,
    *,
    actor_key: str,
) -> dict[str, Any]:
    loaded = load_runtime_conversation(store, conversation_id)
    decision = _flows().runtime_skills.activation.clear(loaded.session, user_id=actor_key)
    if decision.status == "foreign_setup":
        raise RegistryIngressError(409, "credential_setup_in_progress")
    if decision.mutated:
        save_runtime_session(loaded.context.config.data_dir, loaded.conversation_key, loaded.session)
    return presenters.status_result(decision)


def preview_provider_guidance(
    provider_name: str,
    *,
    role: str,
    active_skills: list[str],
    compact_mode: bool,
) -> dict[str, Any]:
    try:
        preview = _flows().provider_guidance.preview.preview(
            provider_name,
            role=role,
            active_skills=list(active_skills),
            compact_mode=compact_mode,
        )
    except ValueError as exc:
        raise RegistryIngressError(404, "Unknown provider guidance preview target.") from exc
    return presenters.provider_guidance_preview(preview)


def provider_guidance_detail(
    provider_name: str,
    *,
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    detail = _flows().provider_guidance.management.detail(
        provider_name,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    if detail is None:
        raise RegistryIngressError(404, f"Unknown provider guidance: {provider_name}")
    return presenters.provider_guidance_lifecycle_detail(detail)


def edit_provider_guidance_draft(
    provider_name: str,
    *,
    actor_key: str,
    body: str,
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.edit_draft(
        provider_name,
        actor_key=actor_key,
        body=body,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def submit_provider_guidance(
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.submit(
        provider_name,
        actor_key=actor_key,
        note=note,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def approve_provider_guidance(
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.approve(
        provider_name,
        actor_key=actor_key,
        note=note,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def reject_provider_guidance(
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.reject(
        provider_name,
        actor_key=actor_key,
        note=note,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def publish_provider_guidance(
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.publish(
        provider_name,
        actor_key=actor_key,
        note=note,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def archive_provider_guidance(
    provider_name: str,
    *,
    actor_key: str,
    note: str = "",
    scope_kind: str = "system",
    scope_key: str = "",
) -> dict[str, Any]:
    result = _flows().provider_guidance.management.archive(
        provider_name,
        actor_key=actor_key,
        note=note,
        scope_kind=scope_kind,
        scope_key=scope_key,
    )
    _raise_for_lifecycle(result)
    return presenters.provider_guidance_lifecycle_mutation(result)


def reset_for_test() -> None:
    global _context
    _context = None
    runtime_backend.reset_for_test()
    reset_content_store_for_test()
    reset_credential_store_for_test()
