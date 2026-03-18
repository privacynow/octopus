"""Telegram surface handlers for conversation control and settings workflows."""

from __future__ import annotations

import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from app import user_messages as _msg
from app.credential_flow import foreign_setup_message
from app.inbound_use_case_factory import (
    get_conversation_control_use_cases,
    get_conversation_settings_use_cases,
)


def _th():
    import app.telegram_handlers as th

    return th


async def cmd_new(event, update: Update, context) -> None:
    del context
    th = _th()
    chat_id = event.chat_id
    cfg = th._cfg()
    prov = th._prov()
    async with th._chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        old_session = th._load(chat_id)
        outcome = get_conversation_control_use_cases().reset_session(
            old_session,
            user_id=th._actor_key(event.user.id),
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            approval_mode_default=cfg.approval_mode,
            default_role=cfg.role,
            default_skills=cfg.default_skills,
        )
        if outcome.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(old_session.awaiting_skill_setup),
            )
            return
        if outcome.replacement_session is None:
            return
        th._save(chat_id, outcome.replacement_session)
        if outcome.cleanup_scripts:
            th.get_provider_guidance_service().cleanup_codex_scripts(
                cfg.data_dir, th._conversation_key(chat_id)
            )
    await update.effective_message.reply_text(outcome.message)


async def cancel_chat_operation(
    chat_id: int | str,
    message,
    *,
    actor_user_id: int | str = "",
    allow_admin_override: bool = False,
    update_id: int | None = None,
) -> None:
    th = _th()
    fast_outcome = request_cancel_fast_path(
        chat_id,
        actor_key=th._actor_key(actor_user_id),
        cancel_request_event_id=th._event_key(update_id) if update_id is not None else "",
        allow_override=allow_admin_override,
    )
    if fast_outcome is not None:
        await message.reply_text(fast_outcome.message)
        return

    async with th._chat_lock(chat_id, message=message, update_id=update_id):
        session = th._load(chat_id)
        outcome = get_conversation_control_use_cases().cancel_conversation(
            session,
            data_dir=th._cfg().data_dir,
            conversation_key=th._conversation_key(chat_id),
            actor_key=th._actor_key(actor_user_id),
            cancel_request_event_id=th._event_key(update_id) if update_id is not None else "",
            allow_override=allow_admin_override,
        )
        if outcome.mutated:
            th._save(chat_id, session)
    await message.reply_text(outcome.message)


def request_cancel_fast_path(
    chat_id: int | str,
    *,
    actor_key: str,
    cancel_request_event_id: str = "",
    allow_override: bool = False,
):
    th = _th()
    session = th._load(chat_id)
    outcome = get_conversation_control_use_cases().cancel_conversation(
        session,
        data_dir=th._cfg().data_dir,
        conversation_key=th._conversation_key(chat_id),
        actor_key=actor_key,
        live_cancel_event=th._LIVE_CANCEL.get(chat_id),
        cancel_request_event_id=cancel_request_event_id,
        allow_override=allow_override,
    )
    if outcome.status in {"live_cancel_requested", "queued_cancelled"}:
        return outcome
    return None


async def cmd_cancel(event, update: Update, context) -> None:
    del context
    th = _th()
    if await th._public_guard(event, update):
        return
    await cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        actor_user_id=event.user.id,
        allow_admin_override=th.is_admin(event.user),
        update_id=update.update_id,
    )


async def cmd_approval(event, update: Update, context) -> None:
    del context
    th = _th()
    chat_id = event.chat_id
    arg = (event.args[0].lower() if event.args else "status")
    if arg not in {"on", "off", "status"}:
        await update.effective_message.reply_text(_msg.approval_usage())
        return
    async with th._chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = th._load(chat_id)
        if arg == "status":
            mode = session.approval_mode
            source = th._approval_mode_source(session)
            await update.effective_message.reply_text(
                f"Approval mode is <b>{mode}</b> ({source}).",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([th._settings_approval_buttons(mode)]),
            )
            return
        outcome = get_conversation_settings_use_cases().set_approval_mode(session, arg)
        if outcome.mutated:
            th._save(chat_id, session)
    await update.effective_message.reply_text(outcome.message)


async def cmd_compact(event, update: Update, context) -> None:
    del context
    th = _th()
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = th._load(chat_id)
        current = session.compact_mode if session.compact_mode is not None else th._cfg().compact_mode
        state = "on" if current else "off"
        await update.effective_message.reply_text(
            f"Compact mode is <b>{state}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([th._settings_compact_buttons(current)]),
        )
        return

    mode = args[0].lower()
    if mode not in {"on", "off"}:
        await update.effective_message.reply_text("Usage: /compact on|off")
        return

    async with th._chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = th._load(chat_id)
        outcome = get_conversation_settings_use_cases().set_compact_mode(session, mode == "on")
        if outcome.mutated:
            th._save(chat_id, session)
    await update.effective_message.reply_text(outcome.message, parse_mode=ParseMode.HTML)


async def cmd_role(event, update: Update, context) -> None:
    del context
    th = _th()
    if await th._public_guard(event, update):
        return
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = th._load(chat_id)
        role = session.role
        if role:
            await update.effective_message.reply_text(
                f"Current role: <code>{html.escape(role)}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.effective_message.reply_text("No role set (using instance default).")
        return

    value = "" if args[0].lower() == "clear" else " ".join(args)
    async with th._chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = th._load(chat_id)
        outcome = get_conversation_settings_use_cases().set_role(
            session,
            value,
            default_role=th._cfg().role,
        )
        if outcome.mutated:
            th._save(chat_id, session)
    await update.effective_message.reply_text(outcome.message, parse_mode=ParseMode.HTML if value else None)


async def cmd_model(event, update: Update, context) -> None:
    del context
    th = _th()
    cfg = th._cfg()
    msg = update.effective_message
    chat_id = event.chat_id
    settings = get_conversation_settings_use_cases()
    trust = th._trust_tier(event.user)
    arg = event.args[0].lower() if event.args else ""

    if arg == "inherit":
        async with th._chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = th._load(chat_id)
            outcome = settings.set_model_profile(
                session,
                "",
                cfg=cfg,
                provider_name=th._prov().name,
                trust_tier=trust,
            )
            if outcome.mutated:
                th._save(chat_id, session)
        await msg.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return

    if not cfg.model_profiles:
        session = th._load(chat_id)
        outcome = settings.set_model_profile(
            session,
            arg if arg and arg != "status" else "fast",
            cfg=cfg,
            provider_name=th._prov().name,
            trust_tier=trust,
        )
        await msg.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return

    session = th._load(chat_id)
    resolved = th._resolve_context(session, trust)
    effective = resolved.effective_model
    available, current = th._settings_model_profile_state(session, cfg, trust, effective or "")

    if arg and arg != "status":
        async with th._chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = th._load(chat_id)
            outcome = settings.set_model_profile(
                session,
                arg,
                cfg=cfg,
                provider_name=th._prov().name,
                trust_tier=trust,
            )
            if outcome.mutated:
                th._save(chat_id, session)
        await msg.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return

    buttons = th._settings_model_buttons(available, current, has_explicit_override=bool(session.model_profile))
    text = (
        f"Model profile: <b>{html.escape(current)}</b>\n"
        f"Effective model: <code>{html.escape(effective or cfg.model or '(default)')}</code>"
    )
    if buttons:
        text += "\n\n" + _msg.model_choose_profile_hint()
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
        return
    await msg.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_project(event, update: Update, context) -> None:
    del context
    th = _th()
    if await th._public_guard(event, update):
        return
    cfg = th._cfg()
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    if not cfg.projects:
        await msg.reply_text(_msg.no_projects_configured())
        return

    if arg == "list":
        session = th._load(event.chat_id)
        current = session.project_id
        lines = ["<b>Available projects:</b>"]
        for proj in cfg.projects:
            marker = " (active)" if proj.name == current else ""
            lines.append(f"  <code>{html.escape(proj.name)}</code> → {html.escape(proj.root_dir)}{marker}")
        await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if arg == "use" and len(event.args) >= 2:
        value = event.args[1]
    elif arg == "clear":
        value = "clear"
    else:
        value = None

    if value is not None:
        async with th._chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = th._load(event.chat_id)
            outcome = get_conversation_settings_use_cases().set_project(
                session,
                value,
                cfg=cfg,
                provider_state_factory=th._prov().new_provider_state,
            )
            if outcome.mutated:
                th._save(event.chat_id, session)
        await msg.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return

    session = th._load(event.chat_id)
    proj = th._resolve_project(session)
    working_dir = proj.root_dir if proj else str(cfg.working_dir)
    project_label = proj.name if proj else "No project"
    lines = [
        f"Project: <b>{html.escape(project_label)}</b>",
        f"Working dir: <code>{html.escape(working_dir)}</code>",
        _msg.project_use_buttons_or_list_hint(),
    ]
    await msg.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(th._settings_project_buttons(cfg, session)),
    )


async def cmd_settings(event, update: Update, context) -> None:
    del context
    th = _th()
    cfg = th._cfg()
    msg = update.effective_message
    session = th._load(event.chat_id)
    trust = th._trust_tier(event.user)
    resolved = th._resolve_context(session, trust_tier=trust)

    project_display = resolved.project_id or "No project"
    if trust == "public":
        project_display = "No project"
    working_dir = resolved.working_dir
    policy = resolved.file_policy or "edit"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    compact_label = "on" if compact else "off"
    effective_model = resolved.effective_model
    model_available, model_display = th._settings_model_profile_state(
        session, cfg, trust, effective_model or ""
    )
    approval = session.approval_mode

    lines = [
        "<b>Chat settings</b>",
        f"Project: <code>{html.escape(project_display)}</code> → <code>{html.escape(working_dir)}</code>",
        f"Model profile: <code>{html.escape(model_display)}</code>",
        f"File policy: <code>{html.escape(policy)}</code>",
        f"Compact mode: <b>{compact_label}</b>",
        f"Approval mode: <b>{approval}</b>",
        _msg.settings_use_buttons_hint(),
    ]
    if effective_model:
        lines.insert(3, f"Effective model: <code>{html.escape(effective_model)}</code>")
    if trust == "public":
        lines.append(_msg.trust_settings_managed_public())

    keyboard: list[list[Any]] = []
    if trust != "public":
        keyboard.extend(th._settings_project_buttons(cfg, session))
        keyboard.append(th._settings_policy_buttons(policy, has_explicit_override=bool(session.file_policy)))
    if model_available:
        keyboard.append(th._settings_model_buttons(model_available, model_display, has_explicit_override=bool(session.model_profile)))
    elif session.model_profile:
        keyboard.append([InlineKeyboardButton("Clear model override", callback_data="setting_model:inherit")])
    keyboard.append(th._settings_compact_buttons(compact))
    keyboard.append(th._settings_approval_buttons(approval))

    await msg.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_policy(event, update: Update, context) -> None:
    del context
    th = _th()
    if await th._public_guard(event, update):
        return
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    value = None
    if arg == "inherit":
        value = ""
    elif arg in {"inspect", "edit"}:
        value = arg

    if value is not None:
        async with th._chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = th._load(event.chat_id)
            outcome = get_conversation_settings_use_cases().set_file_policy(
                session,
                value,
                cfg=th._cfg(),
                provider_name=th._prov().name,
                trust_tier=th._trust_tier(event.user),
                provider_state_factory=th._prov().new_provider_state,
            )
            if outcome.mutated:
                th._save(event.chat_id, session)
        await msg.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return

    if arg in {"", "status"}:
        session = th._load(event.chat_id)
        resolved = th._resolve_context(session, th._trust_tier(event.user))
        policy = resolved.file_policy or "edit"
        await msg.reply_text(
            f"File policy: <b>{html.escape(policy)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [th._settings_policy_buttons(policy, has_explicit_override=bool(session.file_policy))]
            ),
        )
        return

    await msg.reply_text(_msg.policy_usage())


async def handle_settings_callback(event, query) -> None:
    th = _th()
    chat_id = event.chat_id
    data = event.data

    if not data.startswith("setting_"):
        await query.answer()
        return
    _, rest = data.split("_", 1)
    if ":" not in rest:
        await query.answer()
        return
    setting, value = rest.split(":", 1)

    async with th._chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = th._load(chat_id)
        settings = get_conversation_settings_use_cases()

        if setting == "model":
            outcome = settings.set_model_profile(
                session,
                "" if value == "inherit" else value,
                cfg=th._cfg(),
                provider_name=th._prov().name,
                trust_tier=th._trust_tier(event.user),
            )
            if outcome.mutated:
                th._save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(outcome.message, parse_mode=ParseMode.HTML)
            return

        if setting == "approval":
            if value not in {"on", "off"}:
                return
            outcome = settings.set_approval_mode(session, value)
            if outcome.mutated:
                th._save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(outcome.message)
            return

        if setting == "compact":
            outcome = settings.set_compact_mode(session, value == "on")
            if outcome.mutated:
                th._save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(outcome.message, parse_mode=ParseMode.HTML)
            return

        if setting == "policy":
            if th.is_public_user(event.user):
                await query.edit_message_text(_msg.trust_file_policy_public())
                return
            outcome = settings.set_file_policy(
                session,
                "" if value == "inherit" else value,
                cfg=th._cfg(),
                provider_name=th._prov().name,
                trust_tier=th._trust_tier(event.user),
                provider_state_factory=th._prov().new_provider_state,
            )
            if outcome.status == "invalid":
                return
            if outcome.mutated:
                th._save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(outcome.message, parse_mode=ParseMode.HTML)
            return

        if setting == "project":
            if th.is_public_user(event.user):
                await query.edit_message_text(_msg.trust_project_public())
                return
            if not th._cfg().projects:
                await query.edit_message_text(_msg.no_projects_configured())
                return
            outcome = settings.set_project(
                session,
                value,
                cfg=th._cfg(),
                provider_state_factory=th._prov().new_provider_state,
            )
            if outcome.mutated:
                th._save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(outcome.message, parse_mode=ParseMode.HTML)


async def handle_worker_conversation_action(
    event,
    item: dict[str, Any],
    surface,
    *,
    runtime_chat: int | str,
    source: str,
    trust: str,
) -> bool:
    th = _th()
    action = event.action
    params = dict(event.params)
    settings = get_conversation_settings_use_cases()

    if action == "session_new":
        cfg = th._cfg()
        prov = th._prov()
        old_session = th._load(runtime_chat)
        outcome = get_conversation_control_use_cases().reset_session(
            old_session,
            user_id=th._actor_key(event.user.id),
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            approval_mode_default=cfg.approval_mode,
            default_role=cfg.role,
            default_skills=cfg.default_skills,
        )
        if outcome.status == "foreign_setup":
            await surface.reply_text(foreign_setup_message(old_session.awaiting_skill_setup))
            return True
        if outcome.replacement_session is None:
            return True
        th._save(runtime_chat, outcome.replacement_session)
        if outcome.cleanup_scripts:
            th.get_provider_guidance_service().cleanup_codex_scripts(
                cfg.data_dir, th._conversation_key(runtime_chat)
            )
        await surface.reply_text(outcome.message)
        return True

    if action == "cancel_conversation":
        live_outcome = request_cancel_fast_path(
            runtime_chat,
            actor_key=th._actor_key(event.user.id),
            cancel_request_event_id=str(item.get("event_id", "")),
            allow_override=(source != "telegram" or th.is_admin(event.user)),
        )
        if live_outcome is not None:
            await surface.reply_text(live_outcome.message)
            return True
        session = th._load(runtime_chat)
        outcome = get_conversation_control_use_cases().cancel_conversation(
            session,
            data_dir=th._cfg().data_dir,
            conversation_key=th._conversation_key(runtime_chat),
            actor_key=th._actor_key(event.user.id),
            cancel_request_event_id=str(item.get("event_id", "")),
            allow_override=(source != "telegram" or th.is_admin(event.user)),
        )
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.reply_text(outcome.message)
        return True

    if action == "set_approval_mode":
        value = str(params.get("value", "")).lower()
        session = th._load(runtime_chat)
        outcome = settings.set_approval_mode(session, value)
        if outcome.status == "invalid":
            return True
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.edit_reply_markup(reply_markup=None)
        await th._edit_or_reply_text(surface, outcome.message)
        return True

    if action == "set_compact_mode":
        session = th._load(runtime_chat)
        outcome = settings.set_compact_mode(session, bool(params.get("value", False)))
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.edit_reply_markup(reply_markup=None)
        await th._edit_or_reply_text(surface, outcome.message, parse_mode=ParseMode.HTML)
        return True

    if action == "set_role":
        if th.is_public_user(event.user):
            await surface.reply_text(_msg.trust_command_not_available_public())
            return True
        session = th._load(runtime_chat)
        outcome = settings.set_role(
            session,
            str(params.get("value", "")),
            default_role=th._cfg().role,
        )
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.reply_text(outcome.message, parse_mode=ParseMode.HTML)
        return True

    if action == "set_model_profile":
        session = th._load(runtime_chat)
        outcome = settings.set_model_profile(
            session,
            str(params.get("profile", "")),
            cfg=th._cfg(),
            provider_name=th._prov().name,
            trust_tier=trust,
        )
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.edit_reply_markup(reply_markup=None)
        await th._edit_or_reply_text(surface, outcome.message, parse_mode=ParseMode.HTML)
        return True

    if action == "set_project":
        if th.is_public_user(event.user):
            await th._edit_or_reply_text(surface, _msg.trust_project_public())
            return True
        if not th._cfg().projects:
            await th._edit_or_reply_text(surface, _msg.no_projects_configured())
            return True
        session = th._load(runtime_chat)
        outcome = settings.set_project(
            session,
            str(params.get("value", "")),
            cfg=th._cfg(),
            provider_state_factory=th._prov().new_provider_state,
        )
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.edit_reply_markup(reply_markup=None)
        await th._edit_or_reply_text(surface, outcome.message, parse_mode=ParseMode.HTML)
        return True

    if action == "set_file_policy":
        if th.is_public_user(event.user):
            await th._edit_or_reply_text(surface, _msg.trust_file_policy_public())
            return True
        session = th._load(runtime_chat)
        outcome = settings.set_file_policy(
            session,
            str(params.get("value", "")),
            cfg=th._cfg(),
            provider_name=th._prov().name,
            trust_tier=trust,
            provider_state_factory=th._prov().new_provider_state,
        )
        if outcome.status == "invalid":
            return True
        if outcome.mutated:
            th._save(runtime_chat, session)
        await surface.edit_reply_markup(reply_markup=None)
        await th._edit_or_reply_text(surface, outcome.message, parse_mode=ParseMode.HTML)
        return True

    return False
