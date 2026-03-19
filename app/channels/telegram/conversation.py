"""Telegram conversation channel handlers."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram import Update

from app import access
from app.channels.telegram.cancellation import TelegramCancellationRegistry
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.state import TelegramRuntime
from app.execution_context import ResolvedExecutionContext
from app.identity import (
    telegram_actor_key,
    telegram_conversation_key,
    telegram_event_id,
)
from app.provider_guidance_service import get_provider_guidance_service
from app.runtime import composition
from app.runtime.session_runtime import (
    load_runtime_session,
    resolve_session_context,
    save_runtime_session,
)
from app.session_state import SessionState
from app.skill_activation_service import get_skill_activation_service


@dataclass(frozen=True)
class TelegramConversationRuntime:
    """Injected Telegram conversation dependencies.

    The conversation channel owner owns its workflow logic directly and receives only
    the Telegram-specific runtime collaborators it genuinely needs.
    """

    state: TelegramRuntime
    cancellations: TelegramCancellationRegistry
    chat_lock: Callable[..., Any]
    edit_or_reply_text: Callable[..., Awaitable[None]]


def _flows():
    return composition.workflows()


def _conversation_key(chat_id: int | str) -> str:
    return telegram_conversation_key(chat_id)


def _actor_key(user_id: int | str) -> str:
    return telegram_actor_key(user_id)


def _event_key(update_id: int | str) -> str:
    return telegram_event_id(update_id)


def _approval_mode_source(session: SessionState) -> str:
    return "chat override" if session.approval_mode_explicit else "instance default"


def _load(runtime: TelegramConversationRuntime, chat_id: int | str) -> SessionState:
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


def _save(runtime: TelegramConversationRuntime, chat_id: int | str, session: SessionState) -> None:
    save_runtime_session(runtime.state.config.data_dir, _conversation_key(chat_id), session)


def _is_admin(runtime: TelegramConversationRuntime, user) -> bool:
    return access.is_admin_user(runtime.state.config, user)


def _is_public_user(runtime: TelegramConversationRuntime, user) -> bool:
    return access.is_public_user(runtime.state.config, user)


def _trust_tier(runtime: TelegramConversationRuntime, user) -> str:
    return access.trust_tier(runtime.state.config, user)


async def _public_guard(runtime: TelegramConversationRuntime, event, update: Update) -> bool:
    if _is_public_user(runtime, event.user):
        rendered = telegram_presenters.public_command_not_available_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return True
    return False


def _resolve_project(runtime: TelegramConversationRuntime, session: SessionState):
    project_id = session.project_id
    if not project_id:
        return None
    for proj in runtime.state.config.projects:
        if proj.name == project_id:
            return proj
    return None


def _resolve_context(
    runtime: TelegramConversationRuntime,
    session: SessionState,
    trust_tier: str = "trusted",
) -> ResolvedExecutionContext:
    return resolve_session_context(
        session,
        config=runtime.state.config,
        provider_name=runtime.state.provider.name,
        trust_tier=trust_tier,
    )


def _settings_model_profile_state(
    runtime: TelegramConversationRuntime,
    session: SessionState,
    trust_tier: str,
    effective_model: str,
) -> tuple[list[str], str]:
    state = _flows().conversation.settings.model_profile_state(
        session,
        runtime.state.config,
        trust_tier,
        effective_model,
    )
    return (list(state.available_profiles), state.current_profile)


async def cmd_new(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    chat_id = event.chat_id
    cfg = runtime.state.config
    provider = runtime.state.provider
    async with runtime.chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        old_session = _load(runtime, chat_id)
        outcome = _flows().conversation.control.reset_session(
            old_session,
            user_id=_actor_key(event.user.id),
            provider_name=provider.name,
            provider_state_factory=provider.new_provider_state,
            approval_mode_default=cfg.approval_mode,
            default_role=cfg.role,
            default_skills=cfg.default_skills,
        )
        if outcome.status == "foreign_setup":
            rendered = telegram_presenters.conversation_foreign_setup_message(old_session.awaiting_skill_setup)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        if outcome.replacement_session is None:
            return
        _save(runtime, chat_id, outcome.replacement_session)
        if outcome.cleanup_scripts:
            get_provider_guidance_service().cleanup_codex_scripts(
                cfg.data_dir,
                _conversation_key(chat_id),
            )
    rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def cancel_chat_operation(
    chat_id: int | str,
    message,
    *,
    runtime: TelegramConversationRuntime,
    actor_user_id: int | str = "",
    allow_admin_override: bool = False,
    update_id: int | None = None,
) -> None:
    fast_outcome = request_cancel_fast_path(
        chat_id,
        runtime=runtime,
        actor_key=_actor_key(actor_user_id),
        cancel_request_event_id=_event_key(update_id) if update_id is not None else "",
        allow_override=allow_admin_override,
    )
    if fast_outcome is not None:
        rendered = telegram_presenters.conversation_plain_outcome_message(fast_outcome.message)
        await message.reply_text(rendered.text, **rendered.kwargs())
        return

    async with runtime.chat_lock(chat_id, message=message, update_id=update_id):
        session = _load(runtime, chat_id)
        outcome = _flows().conversation.control.cancel_conversation(
            session,
            data_dir=runtime.state.config.data_dir,
            conversation_key=_conversation_key(chat_id),
            actor_key=_actor_key(actor_user_id),
            cancel_request_event_id=_event_key(update_id) if update_id is not None else "",
            allow_override=allow_admin_override,
        )
        if outcome.mutated:
            _save(runtime, chat_id, session)
    rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
    await message.reply_text(rendered.text, **rendered.kwargs())


def request_cancel_fast_path(
    chat_id: int | str,
    *,
    runtime: TelegramConversationRuntime,
    actor_key: str,
    cancel_request_event_id: str = "",
    allow_override: bool = False,
):
    session = _load(runtime, chat_id)
    outcome = _flows().conversation.control.cancel_conversation(
        session,
        data_dir=runtime.state.config.data_dir,
        conversation_key=_conversation_key(chat_id),
        actor_key=actor_key,
        live_cancel_event=runtime.cancellations.get(chat_id),
        cancel_request_event_id=cancel_request_event_id,
        allow_override=allow_override,
    )
    if outcome.status in {"live_cancel_requested", "queued_cancelled"}:
        return outcome
    return None


async def cmd_cancel(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    await cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        runtime=runtime,
        actor_user_id=event.user.id,
        allow_admin_override=_is_admin(runtime, event.user),
        update_id=update.update_id,
    )


async def cmd_approval(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    chat_id = event.chat_id
    arg = (event.args[0].lower() if event.args else "status")
    if arg not in {"on", "off", "status"}:
        rendered = telegram_presenters.conversation_approval_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    async with runtime.chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(runtime, chat_id)
        if arg == "status":
            mode = session.approval_mode
            source = _approval_mode_source(session)
            rendered = telegram_presenters.approval_mode_status(mode, source)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        outcome = _flows().conversation.settings.set_approval_mode(session, arg)
        if outcome.mutated:
            _save(runtime, chat_id, session)
    rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def cmd_compact(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(runtime, chat_id)
        current = (
            session.compact_mode
            if session.compact_mode is not None
            else runtime.state.config.compact_mode
        )
        rendered = telegram_presenters.compact_mode_status(current)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    mode = args[0].lower()
    if mode not in {"on", "off"}:
        rendered = telegram_presenters.conversation_compact_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    async with runtime.chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(runtime, chat_id)
        outcome = _flows().conversation.settings.set_compact_mode(session, mode == "on")
        if outcome.mutated:
            _save(runtime, chat_id, session)
    rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def cmd_role(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(runtime, chat_id)
        role = session.role
        if role:
            rendered = telegram_presenters.conversation_role_current_message(role)
        else:
            rendered = telegram_presenters.conversation_role_default_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    value = "" if args[0].lower() == "clear" else " ".join(args)
    async with runtime.chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(runtime, chat_id)
        outcome = _flows().conversation.settings.set_role(
            session,
            value,
            default_role=runtime.state.config.role,
        )
        if outcome.mutated:
            _save(runtime, chat_id, session)
    rendered = (
        telegram_presenters.conversation_html_outcome_message(outcome.message)
        if value
        else telegram_presenters.conversation_plain_outcome_message(outcome.message)
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def cmd_model(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    cfg = runtime.state.config
    msg = update.effective_message
    chat_id = event.chat_id
    settings = _flows().conversation.settings
    trust = _trust_tier(runtime, event.user)
    arg = event.args[0].lower() if event.args else ""

    if arg == "inherit":
        async with runtime.chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = _load(runtime, chat_id)
            outcome = settings.set_model_profile(
                session,
                "",
                cfg=cfg,
                provider_name=runtime.state.provider.name,
                trust_tier=trust,
            )
            if outcome.mutated:
                _save(runtime, chat_id, session)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    if not cfg.model_profiles:
        session = _load(runtime, chat_id)
        outcome = settings.set_model_profile(
            session,
            arg if arg and arg != "status" else "fast",
            cfg=cfg,
            provider_name=runtime.state.provider.name,
            trust_tier=trust,
        )
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    session = _load(runtime, chat_id)
    resolved = _resolve_context(runtime, session, trust)
    effective = resolved.effective_model
    available, current = _settings_model_profile_state(runtime, session, trust, effective or "")

    if arg and arg != "status":
        async with runtime.chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = _load(runtime, chat_id)
            outcome = settings.set_model_profile(
                session,
                arg,
                cfg=cfg,
                provider_name=runtime.state.provider.name,
                trust_tier=trust,
            )
            if outcome.mutated:
                _save(runtime, chat_id, session)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    rendered = telegram_presenters.model_profile_status(
        available,
        current,
        effective or cfg.model or "(default)",
        has_explicit_override=bool(session.model_profile),
    )
    await msg.reply_text(rendered.text, **rendered.kwargs())


async def cmd_project(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    cfg = runtime.state.config
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    if not cfg.projects:
        rendered = telegram_presenters.no_projects_configured_message()
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    if arg == "list":
        session = _load(runtime, event.chat_id)
        current = session.project_id
        rendered = telegram_presenters.conversation_projects_list_message(cfg.projects, current)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    if arg == "use" and len(event.args) >= 2:
        value = event.args[1]
    elif arg == "clear":
        value = "clear"
    else:
        value = None

    if value is not None:
        async with runtime.chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(runtime, event.chat_id)
            outcome = _flows().conversation.settings.set_project(
                session,
                value,
                cfg=cfg,
                provider_state_factory=runtime.state.provider.new_provider_state,
            )
            if outcome.mutated:
                _save(runtime, event.chat_id, session)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    session = _load(runtime, event.chat_id)
    proj = _resolve_project(runtime, session)
    working_dir = str(proj.root_dir) if proj else str(cfg.working_dir)
    project_label = proj.name if proj else "No project"
    rendered = telegram_presenters.project_status(
        [proj.name for proj in cfg.projects],
        proj.name if proj else None,
        working_dir,
    )
    await msg.reply_text(rendered.text, **rendered.kwargs())


async def cmd_settings(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    cfg = runtime.state.config
    msg = update.effective_message
    session = _load(runtime, event.chat_id)
    trust = _trust_tier(runtime, event.user)
    resolved = _resolve_context(runtime, session, trust_tier=trust)

    project_display = resolved.project_id or "No project"
    if trust == "public":
        project_display = "No project"
    working_dir = resolved.working_dir
    policy = resolved.file_policy or "edit"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    effective_model = resolved.effective_model
    model_available, model_display = _settings_model_profile_state(
        runtime,
        session,
        trust,
        effective_model or "",
    )
    approval = session.approval_mode
    rendered = telegram_presenters.settings_overview(
        project_display=project_display,
        working_dir=working_dir,
        policy=policy,
        compact=compact,
        approval=approval,
        model_display=model_display,
        effective_model=effective_model or "",
        trust_public=(trust == "public"),
        project_names=[proj.name for proj in cfg.projects],
        current_project=session.project_id,
        model_available=model_available,
        has_model_override=bool(session.model_profile),
        has_policy_override=bool(session.file_policy),
    )
    await msg.reply_text(rendered.text, **rendered.kwargs())


async def cmd_policy(event, update: Update, context, *, runtime: TelegramConversationRuntime) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    value = None
    if arg == "inherit":
        value = ""
    elif arg in {"inspect", "edit"}:
        value = arg

    if value is not None:
        async with runtime.chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(runtime, event.chat_id)
            outcome = _flows().conversation.settings.set_file_policy(
                session,
                value,
                cfg=runtime.state.config,
                provider_name=runtime.state.provider.name,
                trust_tier=_trust_tier(runtime, event.user),
                provider_state_factory=runtime.state.provider.new_provider_state,
            )
            if outcome.mutated:
                _save(runtime, event.chat_id, session)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    if arg in {"", "status"}:
        session = _load(runtime, event.chat_id)
        resolved = _resolve_context(runtime, session, _trust_tier(runtime, event.user))
        policy = resolved.file_policy or "edit"
        rendered = telegram_presenters.policy_status(
            policy,
            has_explicit_override=bool(session.file_policy),
        )
        await msg.reply_text(rendered.text, **rendered.kwargs())
        return

    rendered = telegram_presenters.conversation_policy_usage_message()
    await msg.reply_text(rendered.text, **rendered.kwargs())


async def handle_settings_callback(
    event,
    query,
    *,
    runtime: TelegramConversationRuntime,
) -> None:
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

    async with runtime.chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = _load(runtime, chat_id)
        settings = _flows().conversation.settings

        if setting == "model":
            outcome = settings.set_model_profile(
                session,
                "" if value == "inherit" else value,
                cfg=runtime.state.config,
                provider_name=runtime.state.provider.name,
                trust_tier=_trust_tier(runtime, event.user),
            )
            if outcome.mutated:
                _save(runtime, chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
            await query.edit_message_text(rendered.text, **rendered.kwargs())
            return

        if setting == "approval":
            if value not in {"on", "off"}:
                return
            outcome = settings.set_approval_mode(session, value)
            if outcome.mutated:
                _save(runtime, chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
            await query.edit_message_text(rendered.text, **rendered.kwargs())
            return

        if setting == "compact":
            outcome = settings.set_compact_mode(session, value == "on")
            if outcome.mutated:
                _save(runtime, chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
            await query.edit_message_text(rendered.text, **rendered.kwargs())
            return

        if setting == "policy":
            if _is_public_user(runtime, event.user):
                rendered = telegram_presenters.trust_file_policy_public_message()
                await query.edit_message_text(rendered.text, **rendered.kwargs())
                return
            outcome = settings.set_file_policy(
                session,
                "" if value == "inherit" else value,
                cfg=runtime.state.config,
                provider_name=runtime.state.provider.name,
                trust_tier=_trust_tier(runtime, event.user),
                provider_state_factory=runtime.state.provider.new_provider_state,
            )
            if outcome.status == "invalid":
                return
            if outcome.mutated:
                _save(runtime, chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
            await query.edit_message_text(rendered.text, **rendered.kwargs())
            return

        if setting == "project":
            if _is_public_user(runtime, event.user):
                rendered = telegram_presenters.trust_project_public_message()
                await query.edit_message_text(rendered.text, **rendered.kwargs())
                return
            if not runtime.state.config.projects:
                rendered = telegram_presenters.no_projects_configured_message()
                await query.edit_message_text(rendered.text, **rendered.kwargs())
                return
            outcome = settings.set_project(
                session,
                value,
                cfg=runtime.state.config,
                provider_state_factory=runtime.state.provider.new_provider_state,
            )
            if outcome.mutated:
                _save(runtime, chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
            await query.edit_message_text(rendered.text, **rendered.kwargs())


async def handle_worker_conversation_action(
    event,
    item: dict[str, Any],
    channel_message,
    *,
    runtime: TelegramConversationRuntime,
    runtime_chat: int | str,
    source: str,
    trust: str,
) -> bool:
    action = event.action
    params = dict(event.params)
    settings = _flows().conversation.settings

    if action == "session_new":
        cfg = runtime.state.config
        provider = runtime.state.provider
        old_session = _load(runtime, runtime_chat)
        outcome = _flows().conversation.control.reset_session(
            old_session,
            user_id=_actor_key(event.user.id),
            provider_name=provider.name,
            provider_state_factory=provider.new_provider_state,
            approval_mode_default=cfg.approval_mode,
            default_role=cfg.role,
            default_skills=cfg.default_skills,
        )
        if outcome.status == "foreign_setup":
            rendered = telegram_presenters.conversation_foreign_setup_message(old_session.awaiting_skill_setup)
            await channel_message.reply_text(rendered.text, **rendered.kwargs())
            return True
        if outcome.replacement_session is None:
            return True
        _save(runtime, runtime_chat, outcome.replacement_session)
        if outcome.cleanup_scripts:
            get_provider_guidance_service().cleanup_codex_scripts(
                cfg.data_dir,
                _conversation_key(runtime_chat),
            )
        rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
        await channel_message.reply_text(rendered.text, **rendered.kwargs())
        return True

    if action == "cancel_conversation":
        live_outcome = request_cancel_fast_path(
            runtime_chat,
            runtime=runtime,
            actor_key=_actor_key(event.user.id),
            cancel_request_event_id=str(item.get("event_id", "")),
            allow_override=(source != "telegram" or _is_admin(runtime, event.user)),
        )
        if live_outcome is not None:
            rendered = telegram_presenters.conversation_plain_outcome_message(live_outcome.message)
            await channel_message.reply_text(rendered.text, **rendered.kwargs())
            return True
        session = _load(runtime, runtime_chat)
        outcome = _flows().conversation.control.cancel_conversation(
            session,
            data_dir=runtime.state.config.data_dir,
            conversation_key=_conversation_key(runtime_chat),
            actor_key=_actor_key(event.user.id),
            cancel_request_event_id=str(item.get("event_id", "")),
            allow_override=(source != "telegram" or _is_admin(runtime, event.user)),
        )
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
        await channel_message.reply_text(rendered.text, **rendered.kwargs())
        return True

    if action == "set_approval_mode":
        value = str(params.get("value", "")).lower()
        session = _load(runtime, runtime_chat)
        outcome = settings.set_approval_mode(session, value)
        if outcome.status == "invalid":
            return True
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        await channel_message.edit_reply_markup(reply_markup=None)
        rendered = telegram_presenters.conversation_plain_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
        return True

    if action == "set_compact_mode":
        session = _load(runtime, runtime_chat)
        outcome = settings.set_compact_mode(session, bool(params.get("value", False)))
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        await channel_message.edit_reply_markup(reply_markup=None)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
        return True

    if action == "set_role":
        if _is_public_user(runtime, event.user):
            rendered = telegram_presenters.public_command_not_available_message()
            await channel_message.reply_text(rendered.text, **rendered.kwargs())
            return True
        session = _load(runtime, runtime_chat)
        outcome = settings.set_role(
            session,
            str(params.get("value", "")),
            default_role=runtime.state.config.role,
        )
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await channel_message.reply_text(rendered.text, **rendered.kwargs())
        return True

    if action == "set_model_profile":
        session = _load(runtime, runtime_chat)
        outcome = settings.set_model_profile(
            session,
            str(params.get("profile", "")),
            cfg=runtime.state.config,
            provider_name=runtime.state.provider.name,
            trust_tier=trust,
        )
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        await channel_message.edit_reply_markup(reply_markup=None)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
        return True

    if action == "set_project":
        if _is_public_user(runtime, event.user):
            rendered = telegram_presenters.trust_project_public_message()
            await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
            return True
        if not runtime.state.config.projects:
            rendered = telegram_presenters.no_projects_configured_message()
            await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
            return True
        session = _load(runtime, runtime_chat)
        outcome = settings.set_project(
            session,
            str(params.get("value", "")),
            cfg=runtime.state.config,
            provider_state_factory=runtime.state.provider.new_provider_state,
        )
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        await channel_message.edit_reply_markup(reply_markup=None)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
        return True

    if action == "set_file_policy":
        if _is_public_user(runtime, event.user):
            rendered = telegram_presenters.trust_file_policy_public_message()
            await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
            return True
        session = _load(runtime, runtime_chat)
        outcome = settings.set_file_policy(
            session,
            str(params.get("value", "")),
            cfg=runtime.state.config,
            provider_name=runtime.state.provider.name,
            trust_tier=trust,
            provider_state_factory=runtime.state.provider.new_provider_state,
        )
        if outcome.status == "invalid":
            return True
        if outcome.mutated:
            _save(runtime, runtime_chat, session)
        await channel_message.edit_reply_markup(reply_markup=None)
        rendered = telegram_presenters.conversation_html_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(channel_message, rendered.text, **rendered.kwargs())
        return True

    return False
