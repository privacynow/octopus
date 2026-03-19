"""Telegram runtime-skill channel handlers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.constants import ChatAction

from app import access
from app import user_messages as _msg
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.state import TelegramRuntime
from app.execution_context import ResolvedExecutionContext
from app.identity import (
    telegram_actor_key,
    telegram_conversation_key,
    telegram_event_id,
    telegram_numeric_id,
)
from app.runtime import composition
from app.runtime.session_runtime import (
    load_runtime_session,
    resolve_session_context,
    save_runtime_session,
)
from app.session_state import SessionState
from app.skill_activation_service import get_skill_activation_service
from app import work_queue

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramRuntimeSkillsRuntime:
    """Injected Telegram runtime-skill dependencies.

    This concern owns its workflow logic and receives only the Telegram-specific
    runtime collaborators that do not already have a better owner elsewhere.
    """

    state: TelegramRuntime
    chat_lock: Callable[..., Any]
    validate_credential: Callable[[Any, str], Awaitable[tuple[bool, str]]]
    check_prompt_size_cross_chat: Callable[[Path, str], list[str]]


def _flows():
    return composition.workflows()


def _conversation_key(chat_id: int | str) -> str:
    return telegram_conversation_key(chat_id)


def _actor_key(user_id: int | str) -> str:
    return telegram_actor_key(user_id)


def _event_key(update_id: int | str) -> str:
    return telegram_event_id(update_id)


def _numeric_id(actor_key: str) -> int | None:
    return telegram_numeric_id(actor_key)


def _load(runtime: TelegramRuntimeSkillsRuntime, chat_id: int | str) -> SessionState:
    cfg = runtime.state.config
    provider = runtime.state.provider
    session = load_runtime_session(
        cfg.data_dir,
        _conversation_key(chat_id),
        provider_name=provider.name,
        provider_state_factory=provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    if get_skill_activation_service().normalize(session):
        _save(runtime, chat_id, session)
    return session


def _save(runtime: TelegramRuntimeSkillsRuntime, chat_id: int | str, session: SessionState) -> None:
    save_runtime_session(runtime.state.config.data_dir, _conversation_key(chat_id), session)


def _resolve_context(
    runtime: TelegramRuntimeSkillsRuntime,
    session: SessionState,
    trust_tier: str = "trusted",
) -> ResolvedExecutionContext:
    return resolve_session_context(
        session,
        config=runtime.state.config,
        provider_name=runtime.state.provider.name,
        trust_tier=trust_tier,
    )


def _trust_tier(runtime: TelegramRuntimeSkillsRuntime, user) -> str:
    return access.trust_tier(runtime.state.config, user)


def _is_admin(runtime: TelegramRuntimeSkillsRuntime, user) -> bool:
    return access.is_admin_user(runtime.state.config, user)


def _is_public_user(runtime: TelegramRuntimeSkillsRuntime, user) -> bool:
    return access.is_public_user(runtime.state.config, user)


async def _public_guard(runtime: TelegramRuntimeSkillsRuntime, event, update: Update) -> bool:
    if _is_public_user(runtime, event.user):
        rendered = telegram_presenters.public_command_not_available_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return True
    return False


def _check_prompt_size_cross_chat(
    runtime: TelegramRuntimeSkillsRuntime,
    data_dir: Path,
    skill_name: str,
) -> list[str]:
    return runtime.check_prompt_size_cross_chat(data_dir, skill_name)


async def skills_show(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    catalog = {item.name: item for item in _flows().runtime_skills.catalog.list_skills()}
    session = _load(runtime, event.chat_id)
    resolved = _resolve_context(runtime, session, trust_tier=_trust_tier(runtime, event.user))
    active = _flows().runtime_skills.activation.list_conversation_skills(
        list(resolved.active_skills)
    ).active_skills
    rendered = telegram_presenters.runtime_skill_active_summary_message(
        [catalog.get(name).display_name if catalog.get(name) else name for name in active],
        len(catalog),
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def handle_skills_command(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    args = event.args
    if not args:
        await skills_show(event, update, runtime=runtime)
        return

    sub = args[0].lower()
    subs_with_arg = {
        "add": skills_add,
        "remove": skills_remove,
        "setup": skills_setup,
        "create": skills_create,
        "info": skills_info,
        "install": skills_install,
        "uninstall": skills_uninstall,
        "diff": skills_diff,
        "history": skills_history,
        "submit": skills_submit,
        "approve": skills_approve,
        "reject": skills_reject,
        "publish": skills_publish,
        "archive": skills_archive,
    }
    if sub in subs_with_arg and len(args) >= 2:
        await subs_with_arg[sub](event, update, args[1], runtime=runtime)
        return
    if sub == "list":
        await skills_list(event, update, runtime=runtime)
        return
    if sub == "clear":
        await skills_clear(event, update, runtime=runtime)
        return
    if sub == "search" and len(args) >= 2:
        await skills_search(event, update, " ".join(args[1:]), runtime=runtime)
        return
    if sub == "updates":
        await skills_updates(event, update, runtime=runtime)
        return
    if sub == "update" and len(args) >= 2:
        await skills_update(event, update, args[1], runtime=runtime)
        return
    if sub == "edit" and len(args) >= 3:
        await skills_edit(event, update, args[1], " ".join(args[2:]), runtime=runtime)
        return

    rendered = telegram_presenters.skills_usage_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_list(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    catalog = _flows().runtime_skills.catalog.list_skills()
    session = _load(runtime, event.chat_id)
    resolved = _resolve_context(runtime, session, trust_tier=_trust_tier(runtime, event.user))
    active = set(
        _flows().runtime_skills.activation.list_conversation_skills(
            list(resolved.active_skills)
        ).active_skills
    )
    user_creds = _flows().credentials.management.load_credentials(
        _actor_key(event.user.id)
    )
    status_by_name: dict[str, str] = {}
    for item in sorted(catalog, key=lambda value: value.name):
        name = item.name
        if name in active:
            status_by_name[name] = " [active]"
        else:
            if item.requirement_keys:
                skill_creds = user_creds.get(name, {})
                missing = _flows().runtime_skills.catalog.missing_requirements(name, skill_creds)
                status_by_name[name] = " [needs setup]" if missing else " [ready]"
            else:
                status_by_name[name] = ""
    rendered = telegram_presenters.runtime_skill_catalog_message(catalog, status_by_name)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_add(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        rendered = telegram_presenters.runtime_skill_unknown_message(name)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.begin_activate(
            session,
            user_id=event.user.id,
            skill_name=name,
        )
        if decision.mutated:
            _save(runtime, chat_id, session)
        if decision.status == "foreign_setup":
            rendered = telegram_presenters.runtime_skill_foreign_setup_message(
                decision.foreign_setup or session.awaiting_skill_setup
            )
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.status == "needs_setup" and decision.first_requirement:
            rendered = telegram_presenters.runtime_skill_needs_setup_message(name, decision.first_requirement)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.status == "needs_confirmation":
            rendered = telegram_presenters.skill_add_confirmation(
                name,
                decision.projected_size,
                decision.prompt_size_threshold,
            )
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.status == "not_published":
            rendered = telegram_presenters.runtime_skill_not_published_message(name)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
    rendered = telegram_presenters.runtime_skill_activated_message(name)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_remove(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.deactivate(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            rendered = telegram_presenters.runtime_skill_foreign_setup_message(
                decision.foreign_setup or session.awaiting_skill_setup
            )
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    if decision.status == "removed":
        rendered = telegram_presenters.runtime_skill_deactivated_message(name)
    else:
        rendered = telegram_presenters.runtime_skill_not_active_message(name)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_setup(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        rendered = telegram_presenters.runtime_skill_unknown_message(name)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.begin_setup(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            rendered = telegram_presenters.runtime_skill_foreign_setup_message(
                decision.foreign_setup or session.awaiting_skill_setup
            )
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.status == "no_requirements":
            rendered = telegram_presenters.runtime_skill_no_requirements_message(name)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.status == "not_published":
            rendered = telegram_presenters.runtime_skill_not_published_message(name)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    first_req = decision.first_requirement
    if not first_req:
        rendered = telegram_presenters.runtime_skill_setup_could_not_start_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.runtime_skill_setup_started_message(name, first_req)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_clear(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.clear(session, user_id=event.user.id)
        if decision.status == "foreign_setup":
            rendered = telegram_presenters.runtime_skill_foreign_setup_message(
                decision.foreign_setup or session.awaiting_skill_setup
            )
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    rendered = telegram_presenters.runtime_skill_all_removed_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_create(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    try:
        result = _flows().runtime_skills.authoring.create_draft(
            name,
            owner_actor=str(event.user.id),
        )
        if not result.ok or result.detail is None:
            rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        rendered = telegram_presenters.runtime_skill_create_success_message(name, result.detail.visibility)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
    except ValueError as exc:
        rendered = telegram_presenters.runtime_skill_mutation_message(str(exc))
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_edit(event, update: Update, name: str, body: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.authoring.edit_draft(
        name,
        actor_key=str(event.user.id),
        body=body,
    )
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_history(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    detail = _flows().runtime_skills.authoring.detail(name)
    if detail is None:
        rendered = telegram_presenters.runtime_skill_history_not_found_message(name)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.runtime_skill_history_message(detail)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_submit(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.authoring.submit(name, actor_key=str(event.user.id))
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_approve(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can approve skill drafts.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = _flows().runtime_skills.approval.approve(name, actor_key=str(event.user.id))
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_reject(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can reject skill drafts.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = _flows().runtime_skills.approval.reject(name, actor_key=str(event.user.id))
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_publish(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can publish skill drafts.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = _flows().runtime_skills.authoring.publish(name, actor_key=str(event.user.id))
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_archive(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can archive skill drafts.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = _flows().runtime_skills.authoring.archive(name, actor_key=str(event.user.id))
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_search(event, update: Update, query: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    results = await asyncio.to_thread(
        _flows().runtime_skills.imports.search,
        query,
        registry_url=runtime.state.config.registry_url,
    )
    rendered = telegram_presenters.runtime_skill_search_results_message(query, results)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_info(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.catalog.get_skill(name)
    if not result:
        rendered = telegram_presenters.runtime_skill_info_not_found_message(name)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.runtime_skill_info_message(result)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_install(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can install skills.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    registry_url = runtime.state.config.registry_url
    if not registry_url:
        rendered = telegram_presenters.runtime_skill_mutation_message("No skill registry configured.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    try:
        result = await asyncio.to_thread(
            _flows().runtime_skills.imports.install_from_registry,
            name,
            registry_url,
        )
        msg = result.message
        size_warnings = _check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, name) if result.ok else []
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        rendered = telegram_presenters.runtime_skill_mutation_message(msg)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
    except Exception as exc:
        rendered = telegram_presenters.runtime_skill_install_error_message(str(exc))
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_uninstall(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can uninstall imported skills.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = _flows().runtime_skills.imports.uninstall(name, default_skills=runtime.state.config.default_skills)
    rendered = telegram_presenters.runtime_skill_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_updates(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    updates = await asyncio.to_thread(_flows().runtime_skills.imports.list_updates)
    rendered = telegram_presenters.runtime_skill_updates_message(updates)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_diff(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    diff_text = (await asyncio.to_thread(_flows().runtime_skills.imports.diff, name)).message
    rendered = telegram_presenters.runtime_skill_diff_message(diff_text)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def skills_update(event, update: Update, target: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    imports = _flows().runtime_skills.imports
    if not _is_admin(runtime, event.user):
        rendered = telegram_presenters.runtime_skill_admin_only_message("Only admins can update imported skills.")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if target == "all":
        results = await asyncio.to_thread(imports.update_all)
        all_size_warnings: list[str] = []
        for result in results:
            if result.ok:
                all_size_warnings.extend(_check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, result.name))
        rendered = telegram_presenters.runtime_skill_update_results_message(results, all_size_warnings)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    result = await asyncio.to_thread(imports.update, target)
    msg = result.message
    if result.ok:
        size_warnings = _check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, target)
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
    rendered = telegram_presenters.runtime_skill_mutation_message(msg)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def cmd_clear_credentials(event, update: Update, context, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    user_id = _numeric_id(_actor_key(event.user.id)) or 0
    args = event.args
    skill_name = args[0] if args else None

    stored = list(_flows().credentials.management.list_stored_skills(_actor_key(user_id)))

    if skill_name:
        if skill_name not in stored:
            rendered = telegram_presenters.clear_credentials_missing_message(skill_name)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        affected = [skill_name]
        msg = telegram_presenters.clear_credentials_single_message(skill_name)
        cb_data = f"clear_cred_confirm:{user_id}:{skill_name}"
    else:
        if not stored:
            rendered = telegram_presenters.clear_credentials_none_message()
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        affected = stored
        msg = telegram_presenters.clear_credentials_all_message(affected)
        cb_data = f"clear_cred_confirm_all:{user_id}"

    rendered = telegram_presenters.clear_credentials_confirmation(
        msg,
        confirm_callback=cb_data,
        cancel_callback=f"clear_cred_cancel:{user_id}",
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def _execute_clear_credentials(
    query,
    chat_id: int,
    user_id: int,
    skill_name: str | None,
    *,
    runtime: TelegramRuntimeSkillsRuntime,
) -> None:
    async with runtime.chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = _load(runtime, chat_id)
        outcome = _flows().credentials.management.clear_credentials(
            session,
            actor_key=_actor_key(user_id),
            skill_name=skill_name,
        )
        if outcome.mutated:
            _save(runtime, chat_id, session)

    rendered = telegram_presenters.clear_credentials_result_message(
        outcome.removed_skills,
        outcome.setup_cleared,
        outcome.deactivated_skills,
    )
    await query.edit_message_text(rendered.text, **rendered.kwargs())


async def handle_clear_cred_callback(event, query, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    chat_id = event.chat_id
    clicker_id = _numeric_id(_actor_key(event.user.id)) or 0
    parts = event.data.split(":")
    if len(parts) >= 2:
        try:
            owner_id = int(parts[1])
        except (ValueError, IndexError):
            owner_id = 0
        if owner_id and clicker_id != owner_id:
            await query.answer(_msg.callback_wrong_user(), show_alert=True)
            return

    if parts[0] == "clear_cred_cancel":
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.credential_clear_cancelled_message()
        await query.edit_message_text(rendered.text, **rendered.kwargs())
        return

    if parts[0] == "clear_cred_confirm_all":
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, None, runtime=runtime)
        return

    if parts[0] == "clear_cred_confirm" and len(parts) >= 3:
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, parts[2], runtime=runtime)


async def handle_skill_add_callback(event, query, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    chat_id = event.chat_id

    if event.data == "skill_add_cancel":
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.skill_activation_cancelled_message()
        await query.edit_message_text(rendered.text, **rendered.kwargs())
        return

    if event.data.startswith("skill_add_confirm:"):
        name = event.data.split(":", 1)[1]
        async with runtime.chat_lock(chat_id, query=query) as already_answered:
            if not already_answered:
                await query.answer()
            session = _load(runtime, chat_id)
            if _flows().runtime_skills.activation.confirm_activate(session, name).mutated:
                _save(runtime, chat_id, session)
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.runtime_skill_activated_message(name)
        await query.edit_message_text(rendered.text, **rendered.kwargs())


async def handle_skill_update_callback(event, query, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await query.answer("Only admins can update skills.", show_alert=True)
        return

    await query.answer()

    if event.data == "skill_update_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.runtime_skill_update_cancelled_message()
        await query.edit_message_text(rendered.text, **rendered.kwargs())
        return

    if event.data.startswith("skill_update_confirm:"):
        name = event.data.split(":", 1)[1]
        result = await asyncio.to_thread(
            _flows().runtime_skills.imports.update,
            name,
        )
        msg = result.message
        size_warnings = _check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, name) if result.ok else []
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.runtime_skill_mutation_message(msg)
        await query.edit_message_text(rendered.text, **rendered.kwargs())
        return

    if event.data == "skill_update_all_confirm":
        results = await asyncio.to_thread(
            _flows().runtime_skills.imports.update_all,
        )
        all_size_warnings: list[str] = []
        for result in results:
            if result.ok:
                all_size_warnings.extend(_check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, result.name))
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.runtime_skill_update_results_message(results, all_size_warnings)
        await query.edit_message_text(rendered.text, **rendered.kwargs())


async def maybe_handle_setup_message(
    update: Update,
    msg,
    payload: str,
    *,
    runtime: TelegramRuntimeSkillsRuntime,
) -> bool:
    message = update.effective_message
    chat_id = msg.chat_id
    user_id = msg.user.id
    data_dir = runtime.state.config.data_dir
    session = _load(runtime, chat_id)
    setup = session.awaiting_skill_setup
    if not setup or setup.user_id != _actor_key(user_id):
        return False
    if not work_queue.record_update(
        data_dir,
        _event_key(update.update_id),
        _conversation_key(chat_id),
        _actor_key(user_id),
        "message",
        payload=payload,
    ):
        return True
    async with runtime.chat_lock(chat_id, message=message, update_id=update.update_id, supersede_recovery=True):
        session = _load(runtime, chat_id)
        setup = session.awaiting_skill_setup
        if not setup or setup.user_id != _actor_key(user_id):
            return True
        await message.chat.send_action(ChatAction.TYPING)
        raw_value = (message.text or "").strip()
        if not raw_value:
            rendered = telegram_presenters.runtime_skill_enter_credential_value_message()
            await message.reply_text(rendered.text, **rendered.kwargs())
            return True
        outcome = await _flows().runtime_skills.setup.submit_credential_value(
            session,
            user_id=_actor_key(user_id),
            raw_value=raw_value,
            validator=runtime.validate_credential,
        )
        if outcome.status == "validation_failed":
            try:
                await message.delete()
            except Exception:
                log.warning("Could not delete credential message for user %d", user_id)
            rendered = telegram_presenters.runtime_skill_validation_failed_message(
                outcome.validation_key,
                outcome.validation_error,
            )
            await message.reply_text(rendered.text, **rendered.kwargs())
            return True
        try:
            await message.delete()
        except Exception:
            log.warning("Could not delete credential message for user %d", user_id)
        skill_name = outcome.skill_name or setup.skill
        _save(runtime, chat_id, session)
        if outcome.status == "next_requirement" and outcome.next_requirement:
            rendered = telegram_presenters.runtime_skill_next_requirement_message(outcome.next_requirement)
            await message.reply_text(rendered.text, **rendered.kwargs())
            return True
        rendered = telegram_presenters.runtime_skill_ready_message(skill_name)
        await message.reply_text(rendered.text, **rendered.kwargs())
        return True


class _WorkerSkillEvent:
    def __init__(self, chat_id, user):
        self.chat_id = chat_id
        self.user = user


class _WorkerSkillUpdate:
    def __init__(self, surface):
        self.effective_message = surface


async def handle_worker_skill_action(event, surface, *, runtime: TelegramRuntimeSkillsRuntime) -> bool:
    if _is_public_user(runtime, event.user):
        rendered = telegram_presenters.public_command_not_available_message()
        await surface.reply_text(rendered.text, **rendered.kwargs())
        return True
    proxy_event = _WorkerSkillEvent(chat_id=event.chat_id if hasattr(event, "chat_id") else event.conversation_key, user=event.user)
    proxy_update = _WorkerSkillUpdate(surface)
    action = event.action
    name = str(event.params.get("name", ""))
    if action == "skills_add":
        await skills_add(proxy_event, proxy_update, name, runtime=runtime)
        return True
    if action == "skills_remove":
        await skills_remove(proxy_event, proxy_update, name, runtime=runtime)
        return True
    if action == "skills_setup":
        await skills_setup(proxy_event, proxy_update, name, runtime=runtime)
        return True
    if action == "skills_clear":
        await skills_clear(proxy_event, proxy_update, runtime=runtime)
        return True
    return False
