"""Telegram runtime-skill channel handlers."""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode

from app import access
from app import user_messages as _msg
from app.channels.telegram.state import TelegramChannelState
from app.credential_flow import foreign_setup_message, format_credential_prompt
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

    state: TelegramChannelState
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
        await update.effective_message.reply_text(_msg.trust_command_not_available_public())
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
    if active:
        lines = [f"<b>Active skills ({len(active)}):</b>"]
        for name in active:
            meta = catalog.get(name)
            display = meta.display_name if meta else name
            lines.append(f"  {html.escape(display)}")
    else:
        lines = ["<b>No active skills.</b>"]
    lines.append(f"\n{len(catalog)} skill(s) available. Use /skills list to see all.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_list(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    catalog = _flows().runtime_skills.catalog.list_skills()
    if not catalog:
        await update.effective_message.reply_text("No skills available.")
        return
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
    lines = ["<b>Available skills:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        name = item.name
        if name in active:
            status = " [active]"
        else:
            if item.requirement_keys:
                skill_creds = user_creds.get(name, {})
                missing = _flows().runtime_skills.catalog.missing_requirements(name, skill_creds)
                status = " [needs setup]" if missing else " [ready]"
            else:
                status = ""
        if item.has_custom_override:
            custom_tag = " [custom override]"
        elif item.source_kind == "custom":
            custom_tag = " (custom)"
        elif item.source_kind == "imported":
            custom_tag = " (imported)"
        else:
            custom_tag = ""
        desc = f" — {html.escape(item.description)}" if item.description else ""
        lines.append(f"  <code>{html.escape(name)}</code>{desc}{status}{custom_tag}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_add(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
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
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.status == "needs_setup" and decision.first_requirement:
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> needs setup before activation.\n\n"
                f"{format_credential_prompt(decision.first_requirement)}",
                parse_mode=ParseMode.HTML,
            )
            return
        if decision.status == "needs_confirmation":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes", callback_data=f"skill_add_confirm:{name}"),
                InlineKeyboardButton("No", callback_data="skill_add_cancel"),
            ]])
            await update.effective_message.reply_text(
                f"Adding <code>{html.escape(name)}</code> would bring total "
                f"prompt context to ~{decision.projected_size:,} chars "
                f"(threshold: {decision.prompt_size_threshold:,}). "
                f"This may reduce response quality. Continue?",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return
        if decision.status == "not_published":
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> is not published yet.",
                parse_mode=ParseMode.HTML,
            )
            return
    await update.effective_message.reply_text(
        f"Skill <code>{html.escape(name)}</code> activated.",
        parse_mode=ParseMode.HTML,
    )


async def skills_remove(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.deactivate(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    if decision.status == "removed":
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> deactivated.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> is not active.",
            parse_mode=ParseMode.HTML,
        )


async def skills_setup(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.begin_setup(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.status == "no_requirements":
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> has no credential requirements.",
                parse_mode=ParseMode.HTML,
            )
            return
        if decision.status == "not_published":
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> is not published yet.",
                parse_mode=ParseMode.HTML,
            )
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    first_req = decision.first_requirement
    if not first_req:
        await update.effective_message.reply_text("Setup could not be started.")
        return
    await update.effective_message.reply_text(
        f"Setting up <code>{html.escape(name)}</code>.\n\n"
        f"{format_credential_prompt(first_req)}",
        parse_mode=ParseMode.HTML,
    )


async def skills_clear(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with runtime.chat_lock(chat_id, message=update.effective_message) as _:
        session = _load(runtime, chat_id)
        decision = lifecycle.clear(session, user_id=event.user.id)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.mutated:
            _save(runtime, chat_id, session)
    await update.effective_message.reply_text("All skills removed.")


async def skills_create(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    try:
        result = _flows().runtime_skills.authoring.create_draft(
            name,
            owner_actor=str(event.user.id),
        )
        if not result.ok or result.detail is None:
            await update.effective_message.reply_text(result.message)
            return
        await update.effective_message.reply_text(
            f"Created custom skill <code>{html.escape(name)}</code>\n"
            f"Draft visibility: <code>{html.escape(result.detail.visibility)}</code>\n"
            "Use /skills edit, /skills submit, and /skills history to continue the lifecycle.",
            parse_mode=ParseMode.HTML,
        )
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))


async def skills_edit(event, update: Update, name: str, body: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.authoring.edit_draft(
        name,
        actor_key=str(event.user.id),
        body=body,
    )
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_history(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    detail = _flows().runtime_skills.authoring.detail(name)
    if detail is None:
        await update.effective_message.reply_text(
            f"Custom skill <code>{html.escape(name)}</code> not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines = [
        f"<b>{html.escape(detail.display_name)}</b>",
        f"Status: <code>{html.escape(detail.lifecycle_status)}</code>",
        f"Runtime available: {'yes' if detail.runtime_available else 'no'}",
        f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>",
        "",
        "<b>Revisions</b>",
    ]
    for item in detail.revisions[:8]:
        pub = " [published]" if item.is_published else ""
        lines.append(
            f"  <code>{html.escape(item.revision_id[:12])}</code> — "
            f"{html.escape(item.status)}{pub}"
        )
    if detail.approvals:
        lines.append("")
        lines.append("<b>Approvals</b>")
        for item in detail.approvals[:8]:
            note = f" — {html.escape(item.note)}" if item.note else ""
            lines.append(f"  {html.escape(item.action)} by {html.escape(item.actor)}{note}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_submit(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.authoring.submit(name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_approve(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can approve skill drafts.")
        return
    result = _flows().runtime_skills.approval.approve(name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_reject(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can reject skill drafts.")
        return
    result = _flows().runtime_skills.approval.reject(name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_publish(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can publish skill drafts.")
        return
    result = _flows().runtime_skills.authoring.publish(name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_archive(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can archive skill drafts.")
        return
    result = _flows().runtime_skills.authoring.archive(name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_search(event, update: Update, query: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    results = await asyncio.to_thread(
        _flows().runtime_skills.imports.search,
        query,
        registry_url=runtime.state.config.registry_url,
    )
    lines: list[str] = []
    if results.catalog:
        lines.append(f"<b>Catalog skills matching '{html.escape(query)}':</b>")
        for info in results.catalog:
            desc = f" — {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")
    if results.registry:
        local_names = {item.name for item in results.catalog}
        reg_only = [item for item in results.registry if item.name not in local_names]
        if reg_only:
            lines.append(f"\n<b>Registry skills matching '{html.escape(query)}':</b>")
            for skill in reg_only:
                desc = f" — {html.escape(skill.description)}" if skill.description else ""
                pub = f" (by {html.escape(skill.publisher)})" if skill.publisher else ""
                lines.append(f"  <code>{html.escape(skill.name)}</code>{desc}{pub}")
    if results.registry_error:
        lines.append(f"\n<i>Registry search failed: {html.escape(results.registry_error)}</i>")

    if not lines:
        await update.effective_message.reply_text(
            f"No skills matching '{html.escape(query)}'.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines.append("\nUse /skills info <name> for details, /skills install <name> to import from the registry.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_info(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    result = _flows().runtime_skills.catalog.get_skill(name)
    if not result:
        await update.effective_message.reply_text(
            f"Skill '{html.escape(name)}' not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    parts = [f"<b>{html.escape(result.display_name)}</b>"]
    if result.description:
        parts.append(html.escape(result.description))
    if result.requirement_keys:
        req_keys = ", ".join(result.requirement_keys)
        parts.append(f"Requires: {html.escape(req_keys)}")
    if result.providers:
        parts.append(f"Providers: {', '.join(sorted(result.providers))}")
    parts.append(f"Resolves to: {result.source_kind}")
    preview = result.body
    if len(preview) > 1000:
        cut = preview.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = preview[:cut] + "..."
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def skills_install(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can install skills.")
        return
    registry_url = runtime.state.config.registry_url
    if not registry_url:
        await update.effective_message.reply_text("No skill registry configured.", parse_mode=ParseMode.HTML)
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
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Registry install failed: {html.escape(str(exc)[:300])}",
            parse_mode=ParseMode.HTML,
        )


async def skills_uninstall(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can uninstall imported skills.")
        return
    result = _flows().runtime_skills.imports.uninstall(name, default_skills=runtime.state.config.default_skills)
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_updates(event, update: Update, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    updates = await asyncio.to_thread(_flows().runtime_skills.imports.list_updates)
    if not updates:
        await update.effective_message.reply_text("No imported skills found.")
        return
    lines = ["<b>Imported skill status:</b>"]
    for item in updates:
        label = "update available" if item.status == "update_available" else "up to date"
        override = " [custom override]" if item.has_custom_override else ""
        lines.append(f"  <code>{html.escape(item.name)}</code> — {label}{override}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_diff(event, update: Update, name: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    del runtime
    diff_text = (await asyncio.to_thread(_flows().runtime_skills.imports.diff, name)).message
    if not diff_text.strip():
        diff_text = "No differences."
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n... (truncated)"
    await update.effective_message.reply_text(
        f"<pre>{html.escape(diff_text)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def skills_update(event, update: Update, target: str, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    imports = _flows().runtime_skills.imports
    if not _is_admin(runtime, event.user):
        await update.effective_message.reply_text("Only admins can update imported skills.")
        return
    if target == "all":
        results = await asyncio.to_thread(imports.update_all)
        if not results:
            await update.effective_message.reply_text("No imported skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        all_size_warnings: list[str] = []
        for result in results:
            status = "✔" if result.ok else "✘"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(_check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, result.name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for warning in all_size_warnings:
                lines.append(f"  {html.escape(warning)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    result = await asyncio.to_thread(imports.update, target)
    msg = result.message
    if result.ok:
        size_warnings = _check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, target)
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
    await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)


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
            await update.effective_message.reply_text(
                f"No stored credentials for <code>{html.escape(skill_name)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        affected = [skill_name]
        msg = (
            f"This will remove your credentials for "
            f"<code>{html.escape(skill_name)}</code> and deactivate it "
            f"in this chat. Continue?"
        )
        cb_data = f"clear_cred_confirm:{user_id}:{skill_name}"
    else:
        if not stored:
            await update.effective_message.reply_text("No stored credentials found.")
            return
        affected = stored
        names = html.escape(", ".join(affected))
        msg = (
            f"This will remove all your stored credentials "
            f"({names}) and deactivate affected skills. Continue?"
        )
        cb_data = f"clear_cred_confirm_all:{user_id}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, clear", callback_data=cb_data),
        InlineKeyboardButton("Cancel", callback_data=f"clear_cred_cancel:{user_id}"),
    ]])
    await update.effective_message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


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

    parts = []
    if outcome.removed_skills:
        parts.append(f"Credentials cleared for: {html.escape(', '.join(outcome.removed_skills))}.")
    if outcome.setup_cleared:
        parts.append(_msg.credential_setup_cancelled())
    if outcome.deactivated_skills:
        parts.append(f"Deactivated in this chat: {html.escape(', '.join(outcome.deactivated_skills))}.")
    if not parts:
        parts.append("No credentials to clear (may have already been removed).")
    await query.edit_message_text("\n".join(parts), parse_mode=ParseMode.HTML)


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
        await query.edit_message_text(_msg.credential_clear_cancelled())
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
        await query.edit_message_text("Skill activation cancelled.")
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
        await query.edit_message_text(
            f"Skill <code>{html.escape(name)}</code> activated.",
            parse_mode=ParseMode.HTML,
        )


async def handle_skill_update_callback(event, query, *, runtime: TelegramRuntimeSkillsRuntime) -> None:
    if not _is_admin(runtime, event.user):
        await query.answer("Only admins can update skills.", show_alert=True)
        return

    await query.answer()

    if event.data == "skill_update_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Update cancelled.")
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
        await query.edit_message_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if event.data == "skill_update_all_confirm":
        results = await asyncio.to_thread(
            _flows().runtime_skills.imports.update_all,
        )
        if not results:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text("No imported skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        all_size_warnings: list[str] = []
        for result in results:
            status = "✔" if result.ok else "✘"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(_check_prompt_size_cross_chat(runtime, runtime.state.config.data_dir, result.name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for warning in all_size_warnings:
                lines.append(f"  {html.escape(warning)}")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)


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
            await message.reply_text("Please send the credential value as a text message.")
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
            await message.reply_text(
                f"Credential validation failed for <code>{html.escape(outcome.validation_key)}</code>: "
                f"{html.escape(outcome.validation_error)}\nPlease try again.",
                parse_mode=ParseMode.HTML,
            )
            return True
        try:
            await message.delete()
        except Exception:
            log.warning("Could not delete credential message for user %d", user_id)
        skill_name = outcome.skill_name or setup.skill
        _save(runtime, chat_id, session)
        if outcome.status == "next_requirement" and outcome.next_requirement:
            await message.reply_text(
                format_credential_prompt(outcome.next_requirement),
                parse_mode=ParseMode.HTML,
            )
            return True
        await message.reply_text(
            f"Skill <code>{html.escape(skill_name)}</code> is ready.",
            parse_mode=ParseMode.HTML,
        )
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
        await surface.reply_text(_msg.trust_command_not_available_public())
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
