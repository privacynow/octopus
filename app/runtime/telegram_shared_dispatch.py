"""Telegram shared-mode command and callback dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from app import access
from app import user_messages as _msg
from app.presentation import telegram as telegram_presenters
from app.runtime import composition
from app.workflows.conversation.telegram import (
    TelegramConversationRuntime,
    cancel_chat_operation as conversation_cancel_chat_operation,
    cmd_approval as conversation_cmd_approval,
    cmd_compact as conversation_cmd_compact,
    cmd_model as conversation_cmd_model,
    cmd_policy as conversation_cmd_policy,
    cmd_project as conversation_cmd_project,
    cmd_role as conversation_cmd_role,
)
from app.workflows.delegation.telegram import parse_delegation_callback
from app.runtime.telegram_normalization import normalize_callback, normalize_command
from app.workflows.runtime_skills.telegram import (
    handle_skills_command as runtime_skill_handle_skills_command,
    TelegramRuntimeSkillsRuntime,
    handle_skill_add_callback as runtime_skill_handle_skill_add_callback,
)
from app.runtime.telegram_session_io import actor_key as _actor_key, conversation_key, event_key
from app.channels.telegram.state import TelegramRuntime
from octopus_sdk.inbound_types import InboundAction, InboundEnvelope
from app import work_queue


ChatLock = Callable[..., Any]


def _guidance_flows():
    return composition.workflows()


async def handle_provider_guidance_command(event, update: Update, *, is_admin: bool) -> None:
    args = event.args
    if len(args) < 2:
        rendered = telegram_presenters.guidance_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    sub = args[0].lower()
    provider_name = args[1]

    if sub == "preview":
        preview = _guidance_flows().provider_guidance.preview.preview(
            provider_name,
            role="",
            active_skills=[],
            compact_mode=False,
        )
        rendered = telegram_presenters.provider_guidance_preview_message(provider_name, preview)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "history":
        detail = _guidance_flows().provider_guidance.management.detail(provider_name)
        if detail is None:
            rendered = telegram_presenters.provider_guidance_not_found_message(provider_name)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        rendered = telegram_presenters.provider_guidance_history_message(provider_name, detail)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "edit" and len(args) >= 3:
        result = _guidance_flows().provider_guidance.management.edit_draft(
            provider_name,
            actor_key=str(event.user.id),
            body=" ".join(args[2:]),
        )
        rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "submit":
        result = _guidance_flows().provider_guidance.management.submit(
            provider_name,
            actor_key=str(event.user.id),
        )
        rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub in {"approve", "reject", "publish", "archive"}:
        if not is_admin:
            rendered = telegram_presenters.guidance_admin_only_message(sub)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        action = getattr(_guidance_flows().provider_guidance.management, sub)
        result = action(provider_name, actor_key=str(event.user.id))
        rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    rendered = telegram_presenters.guidance_usage_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


def build_shared_command_handler(
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await shared_command_dispatch(update, context, runtime=runtime, chat_lock=chat_lock, build_conversation_runtime=build_conversation_runtime, build_runtime_skill_runtime=build_runtime_skill_runtime)

    handler.__name__ = "shared_command_dispatch"
    return handler


def build_shared_callback_handler(
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await shared_callback_dispatch(update, context, runtime=runtime, chat_lock=chat_lock, build_runtime_skill_runtime=build_runtime_skill_runtime)

    handler.__name__ = "shared_callback_dispatch"
    return handler


def _callback_message_id(update: Update) -> int | None:
    message = update.effective_message or getattr(update.callback_query, "message", None)
    if message is None:
        return None
    raw = getattr(message, "message_id", None) or getattr(message, "id", None)
    return int(raw) if isinstance(raw, int) else None


def _build_action_envelope(
    *,
    transport: str,
    event_id: str,
    action: InboundAction,
    conversation_ref: str = "",
) -> InboundEnvelope:
    return InboundEnvelope(
        transport=transport,
        event_id=event_id,
        conversation_key=action.conversation_key,
        actor_key=action.user.id,
        received_at=datetime.now(timezone.utc),
        event=action,
        conversation_ref=conversation_ref or action.conversation_ref,
    )


def _telegram_action(event, action: str, *, params: dict[str, Any] | None = None) -> InboundAction:
    return InboundAction(
        event.user,
        event.conversation_key,
        action,
        params={} if params is None else params,
        source="telegram",
        transport="telegram",
    )


def _worker_owned_command_action(event) -> InboundAction | None:
    args = tuple(event.args or ())
    command = (event.command or "").lower()

    if command == "new":
        return _telegram_action(event, "session_new")
    if command == "approval":
        mode = args[0].lower() if args else "status"
        if mode in {"on", "off"}:
            return _telegram_action(event, "set_approval_mode", params={"value": mode})
        return None
    if command == "approve":
        return _telegram_action(event, "approve_pending")
    if command == "reject":
        return _telegram_action(event, "reject_pending")
    if command == "cancel":
        return _telegram_action(event, "cancel_conversation")
    if command == "role":
        if not args:
            return None
        value = "" if args[0].lower() == "clear" else " ".join(args)
        return _telegram_action(event, "set_role", params={"value": value})
    if command == "compact":
        if not args:
            return None
        mode = args[0].lower()
        if mode not in {"on", "off"}:
            return None
        return _telegram_action(event, "set_compact_mode", params={"value": mode == "on"})
    if command == "model":
        if not args:
            return None
        profile = args[0].lower()
        if profile == "status":
            return None
        if profile == "inherit":
            profile = ""
        return _telegram_action(event, "set_model_profile", params={"profile": profile})
    if command == "project":
        if not args:
            return None
        sub = args[0].lower()
        if sub == "use" and len(args) >= 2:
            return _telegram_action(event, "set_project", params={"value": args[1]})
        if sub == "clear":
            return _telegram_action(event, "set_project", params={"value": "clear"})
        return None
    if command == "policy":
        mode = args[0].lower() if args else ""
        if mode in {"inspect", "edit"}:
            value = mode
        elif mode == "inherit":
            value = ""
        else:
            return None
        return _telegram_action(event, "set_file_policy", params={"value": value})
    if command == "skills":
        sub = args[0].lower() if args else ""
        if sub == "add" and len(args) >= 2:
            return _telegram_action(event, "skills_add", params={"name": args[1]})
        if sub == "remove" and len(args) >= 2:
            return _telegram_action(event, "skills_remove", params={"name": args[1]})
        if sub == "setup" and len(args) >= 2:
            return _telegram_action(event, "skills_setup", params={"name": args[1]})
        if sub == "clear":
            return _telegram_action(event, "skills_clear")
        return None
    return None


def _worker_owned_callback_action(update: Update, event) -> InboundAction | None:
    params: dict[str, Any] = {}
    message_id = _callback_message_id(update)
    if message_id is not None:
        params["message_id"] = message_id

    data = event.data or ""
    pending_action = telegram_presenters.parse_pending_callback_data(data)
    if pending_action is not None:
        action, callback_token = pending_action
        if callback_token:
            params["callback_token"] = callback_token
        if action == "approval_approve":
            return _telegram_action(event, "approve_pending", params=params)
        if action == "approval_reject":
            return _telegram_action(event, "reject_pending", params=params)
        if action == "retry_allow":
            return _telegram_action(event, "retry_allow", params=params)
        if action == "retry_skip":
            return _telegram_action(event, "retry_skip", params=params)
    if data.startswith("recovery_"):
        parts = data.split(":", 1)
        if len(parts) != 2:
            return None
        try:
            params["update_id"] = int(parts[1])
        except (TypeError, ValueError):
            return None
        return _telegram_action(event, parts[0], params=params)
    if data.startswith("delegation_"):
        parsed = parse_delegation_callback(data)
        if parsed is None:
            return None
        action, chat_id = parsed
        params["target_conversation_key"] = conversation_key(chat_id)
        return _telegram_action(event, action, params=params)
    if data.startswith("setting_"):
        _, rest = data.split("_", 1)
        if ":" not in rest:
            return None
        setting, value = rest.split(":", 1)
        if setting == "model":
            params["profile"] = "" if value == "inherit" else value
            return _telegram_action(event, "set_model_profile", params=params)
        if setting == "approval":
            params["value"] = value
            return _telegram_action(event, "set_approval_mode", params=params)
        if setting == "compact":
            params["value"] = value == "on"
            return _telegram_action(event, "set_compact_mode", params=params)
        if setting == "policy":
            params["value"] = "" if value == "inherit" else value
            return _telegram_action(event, "set_file_policy", params=params)
        if setting == "project":
            params["value"] = value
            return _telegram_action(event, "set_project", params=params)
        return None
    if data.startswith("skill_add_confirm:"):
        params["name"] = data.split(":", 1)[1]
        return _telegram_action(event, "skills_add", params=params)
    return None


def _is_allowed(runtime: TelegramRuntime, user) -> bool:
    override = work_queue.get_user_access(runtime.config.data_dir, user.id)
    return access.is_allowed_user_with_override(runtime.config, user, override)


async def _public_guard(runtime: TelegramRuntime, event, update: Update) -> bool:
    if access.is_public_user(runtime.config, event.user):
        rendered = telegram_presenters.public_command_not_available_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return True
    return False


def _chat_lock_adapter(runtime: TelegramRuntime, chat_lock: ChatLock):
    return lambda chat_id, **kwargs: chat_lock(runtime, chat_id, **kwargs)


def _action_requires_public_guard(action: str) -> bool:
    return action in {
        "cancel_conversation",
        "set_role",
        "set_project",
        "set_file_policy",
        "skills_add",
        "skills_remove",
        "skills_setup",
        "skills_clear",
    }


async def _shared_cancel_command(
    runtime: TelegramRuntime,
    update: Update,
    event,
    action: InboundAction,
    *,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
) -> None:
    if not await runtime.submitter.record(
        _build_action_envelope(
            transport="telegram",
            event_id=event_key(update.update_id),
            action=action,
        )
    ):
        return
    await conversation_cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        runtime=build_conversation_runtime(_chat_lock_adapter(runtime, chat_lock)),
        actor_key=_actor_key(event.user.id),
        allow_admin_override=access.is_admin_user(runtime.config, event.user),
        update_id=update.update_id,
    )


async def shared_command_dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> None:
    event = normalize_command(update, context)
    if event is None:
        return
    if not _is_allowed(runtime, event.user):
        rendered = telegram_presenters.trust_not_authorized_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    action = _worker_owned_command_action(event)
    if action is None:
        command = (event.command or "").lower()
        if command == "skills":
            await runtime_skill_handle_skills_command(
                event,
                update,
                runtime=build_runtime_skill_runtime(_chat_lock_adapter(runtime, chat_lock)),
            )
            return
        inline_handlers = {"approval": conversation_cmd_approval, "compact": conversation_cmd_compact, "role": conversation_cmd_role, "model": conversation_cmd_model, "project": conversation_cmd_project, "policy": conversation_cmd_policy}
        handler = inline_handlers.get(command)
        if handler is not None:
            await handler(
                event,
                update,
                context,
                runtime=build_conversation_runtime(_chat_lock_adapter(runtime, chat_lock)),
            )
            return
        rendered = telegram_presenters.pending_plain_outcome_message(
            _msg.unknown_command(command),
        )
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    if _action_requires_public_guard(action.action) and await _public_guard(runtime, event, update):
        return

    if action.action == "cancel_conversation":
        await _shared_cancel_command(
            runtime,
            update,
            event,
            action,
            chat_lock=chat_lock,
            build_conversation_runtime=build_conversation_runtime,
        )
        return

    await runtime.submitter.enqueue(
        _build_action_envelope(
            transport="telegram",
            event_id=event_key(update.update_id),
            action=action,
        )
    )


async def shared_callback_dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> None:
    del context
    event = normalize_callback(update)
    query = update.callback_query
    if event is None or query is None:
        return
    if not _is_allowed(runtime, event.user):
        await query.answer(telegram_presenters.trust_not_authorized_message().text, show_alert=True)
        return

    action = _worker_owned_callback_action(update, event)
    if action is None:
        if (event.data or "").startswith("skill_add_"):
            await runtime_skill_handle_skill_add_callback(
                event,
                query,
                runtime=build_runtime_skill_runtime(_chat_lock_adapter(runtime, chat_lock)),
            )
            return
        await query.answer()
        return

    if _action_requires_public_guard(action.action) and access.is_public_user(runtime.config, event.user):
        await query.answer(telegram_presenters.public_command_not_available_message().text, show_alert=True)
        return

    await query.answer()
    await runtime.submitter.enqueue(
        _build_action_envelope(
            transport="telegram",
            event_id=event_key(update.update_id),
            action=action,
        )
    )
