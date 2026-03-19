"""Telegram shared-mode command and callback dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from app import access
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.conversation import (
    TelegramConversationRuntime,
    cancel_chat_operation as conversation_cancel_chat_operation,
    cmd_approval as conversation_cmd_approval,
    cmd_compact as conversation_cmd_compact,
    cmd_model as conversation_cmd_model,
    cmd_policy as conversation_cmd_policy,
    cmd_project as conversation_cmd_project,
    cmd_role as conversation_cmd_role,
)
from app.channels.telegram.delegation_channel import parse_delegation_callback
from app.channels.telegram.normalization import normalize_callback, normalize_command
from app.channels.telegram.runtime_skills import (
    TelegramRuntimeSkillsRuntime,
    handle_skill_add_callback as runtime_skill_handle_skill_add_callback,
)
from app.channels.telegram.session_io import conversation_key, event_key
from app.channels.telegram.state import TelegramRuntime
from app.runtime.inbound_types import InboundAction, InboundEnvelope
from app.runtime.work_admission import enqueue_inbound_envelope, record_inbound_envelope
from app import work_queue


ChatLock = Callable[..., Any]


def build_shared_command_handler(
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await shared_command_dispatch(
            update,
            context,
            runtime=runtime,
            chat_lock=chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

    handler.__name__ = "shared_command_dispatch"
    return handler


def build_shared_callback_handler(
    *,
    runtime: TelegramRuntime,
    chat_lock: ChatLock,
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await shared_callback_dispatch(
            update,
            context,
            runtime=runtime,
            chat_lock=chat_lock,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

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


def _worker_owned_command_action(event) -> InboundAction | None:
    args = tuple(event.args or ())
    command = (event.command or "").lower()

    if command == "new":
        return InboundAction(event.user, event.conversation_key, "session_new")
    if command == "approval":
        mode = args[0].lower() if args else "status"
        if mode in {"on", "off"}:
            return InboundAction(
                event.user,
                event.conversation_key,
                "set_approval_mode",
                params={"value": mode},
            )
        return None
    if command == "approve":
        return InboundAction(event.user, event.conversation_key, "approve_pending")
    if command == "reject":
        return InboundAction(event.user, event.conversation_key, "reject_pending")
    if command == "cancel":
        return InboundAction(event.user, event.conversation_key, "cancel_conversation")
    if command == "role":
        if not args:
            return None
        value = "" if args[0].lower() == "clear" else " ".join(args)
        return InboundAction(
            event.user,
            event.conversation_key,
            "set_role",
            params={"value": value},
        )
    if command == "compact":
        if not args:
            return None
        mode = args[0].lower()
        if mode not in {"on", "off"}:
            return None
        return InboundAction(
            event.user,
            event.conversation_key,
            "set_compact_mode",
            params={"value": mode == "on"},
        )
    if command == "model":
        if not args:
            return None
        profile = args[0].lower()
        if profile == "status":
            return None
        if profile == "inherit":
            profile = ""
        return InboundAction(
            event.user,
            event.conversation_key,
            "set_model_profile",
            params={"profile": profile},
        )
    if command == "project":
        if not args:
            return None
        sub = args[0].lower()
        if sub == "use" and len(args) >= 2:
            return InboundAction(
                event.user,
                event.conversation_key,
                "set_project",
                params={"value": args[1]},
            )
        if sub == "clear":
            return InboundAction(
                event.user,
                event.conversation_key,
                "set_project",
                params={"value": "clear"},
            )
        return None
    if command == "policy":
        mode = args[0].lower() if args else ""
        if mode in {"inspect", "edit"}:
            value = mode
        elif mode == "inherit":
            value = ""
        else:
            return None
        return InboundAction(
            event.user,
            event.conversation_key,
            "set_file_policy",
            params={"value": value},
        )
    if command == "skills":
        sub = args[0].lower() if args else ""
        if sub == "add" and len(args) >= 2:
            return InboundAction(
                event.user,
                event.conversation_key,
                "skills_add",
                params={"name": args[1]},
            )
        if sub == "remove" and len(args) >= 2:
            return InboundAction(
                event.user,
                event.conversation_key,
                "skills_remove",
                params={"name": args[1]},
            )
        if sub == "setup" and len(args) >= 2:
            return InboundAction(
                event.user,
                event.conversation_key,
                "skills_setup",
                params={"name": args[1]},
            )
        if sub == "clear":
            return InboundAction(event.user, event.conversation_key, "skills_clear")
        return None
    return None


def _worker_owned_callback_action(update: Update, event) -> InboundAction | None:
    params: dict[str, Any] = {}
    message_id = _callback_message_id(update)
    if message_id is not None:
        params["message_id"] = message_id

    data = event.data or ""
    if data == "approval_approve":
        return InboundAction(event.user, event.conversation_key, "approve_pending", params=params)
    if data == "approval_reject":
        return InboundAction(event.user, event.conversation_key, "reject_pending", params=params)
    if data == "retry_allow":
        return InboundAction(event.user, event.conversation_key, "retry_allow", params=params)
    if data == "retry_skip":
        return InboundAction(event.user, event.conversation_key, "retry_skip", params=params)
    if data.startswith("recovery_"):
        parts = data.split(":", 1)
        if len(parts) != 2:
            return None
        try:
            params["update_id"] = int(parts[1])
        except (TypeError, ValueError):
            return None
        return InboundAction(event.user, event.conversation_key, parts[0], params=params)
    if data.startswith("delegation_"):
        parsed = parse_delegation_callback(data)
        if parsed is None:
            return None
        action, chat_id = parsed
        params["target_conversation_key"] = conversation_key(chat_id)
        return InboundAction(event.user, event.conversation_key, action, params=params)
    if data.startswith("setting_"):
        _, rest = data.split("_", 1)
        if ":" not in rest:
            return None
        setting, value = rest.split(":", 1)
        if setting == "model":
            params["profile"] = "" if value == "inherit" else value
            return InboundAction(event.user, event.conversation_key, "set_model_profile", params=params)
        if setting == "approval":
            params["value"] = value
            return InboundAction(event.user, event.conversation_key, "set_approval_mode", params=params)
        if setting == "compact":
            params["value"] = value == "on"
            return InboundAction(event.user, event.conversation_key, "set_compact_mode", params=params)
        if setting == "policy":
            params["value"] = "" if value == "inherit" else value
            return InboundAction(event.user, event.conversation_key, "set_file_policy", params=params)
        if setting == "project":
            params["value"] = value
            return InboundAction(event.user, event.conversation_key, "set_project", params=params)
        return None
    if data.startswith("skill_add_confirm:"):
        params["name"] = data.split(":", 1)[1]
        return InboundAction(event.user, event.conversation_key, "skills_add", params=params)
    return None


def _is_allowed(runtime: TelegramRuntime, user) -> bool:
    override = work_queue.get_user_access(runtime.config.data_dir, user.id)
    return access.is_allowed_user_with_override(runtime.config, user, override)


def _is_admin(runtime: TelegramRuntime, user) -> bool:
    return access.is_admin_user(runtime.config, user)


def _is_public_user(runtime: TelegramRuntime, user) -> bool:
    return access.is_public_user(runtime.config, user)


async def _public_guard(runtime: TelegramRuntime, event, update: Update) -> bool:
    if _is_public_user(runtime, event.user):
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


async def _enqueue_shared_action(
    runtime: TelegramRuntime,
    update: Update,
    action: InboundAction,
) -> tuple[bool, str | None]:
    envelope = _build_action_envelope(
        transport="telegram",
        event_id=event_key(update.update_id),
        action=action,
    )
    return enqueue_inbound_envelope(runtime.config.data_dir, envelope)


def _shared_action_envelope(update: Update, action: InboundAction) -> InboundEnvelope:
    return _build_action_envelope(
        transport="telegram",
        event_id=event_key(update.update_id),
        action=action,
    )


def _record_shared_action(
    runtime: TelegramRuntime,
    update: Update,
    action: InboundAction,
) -> tuple[bool, InboundEnvelope]:
    envelope = _shared_action_envelope(update, action)
    return record_inbound_envelope(runtime.config.data_dir, envelope), envelope


async def _shared_cancel_command(
    runtime: TelegramRuntime,
    update: Update,
    event,
    action: InboundAction,
    *,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
) -> None:
    is_new, envelope = _record_shared_action(runtime, update, action)
    if not is_new:
        return
    del envelope
    await conversation_cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        runtime=build_conversation_runtime(_chat_lock_adapter(runtime, chat_lock)),
        actor_user_id=event.user.id,
        allow_admin_override=_is_admin(runtime, event.user),
        update_id=update.update_id,
    )


async def _shared_skills_inline_handler(
    runtime: TelegramRuntime,
    event,
    update: Update,
    *,
    chat_lock: ChatLock,
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> None:
    from app.channels.telegram.runtime_skills import (
        skills_add,
        skills_approve,
        skills_archive,
        skills_clear,
        skills_create,
        skills_diff,
        skills_edit,
        skills_history,
        skills_info,
        skills_install,
        skills_list,
        skills_publish,
        skills_reject,
        skills_remove,
        skills_search,
        skills_setup,
        skills_show,
        skills_submit,
        skills_uninstall,
        skills_update,
        skills_updates,
    )

    args = event.args
    skills_runtime = build_runtime_skill_runtime(_chat_lock_adapter(runtime, chat_lock))
    if not args:
        await skills_show(event, update, runtime=skills_runtime)
        return

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
    sub = args[0].lower()
    if sub in subs_with_arg and len(args) >= 2:
        await subs_with_arg[sub](event, update, args[1], runtime=skills_runtime)
        return
    if sub == "list":
        await skills_list(event, update, runtime=skills_runtime)
        return
    if sub == "clear":
        await skills_clear(event, update, runtime=skills_runtime)
        return
    if sub == "search" and len(args) >= 2:
        await skills_search(event, update, " ".join(args[1:]), runtime=skills_runtime)
        return
    if sub == "updates":
        await skills_updates(event, update, runtime=skills_runtime)
        return
    if sub == "update" and len(args) >= 2:
        await skills_update(event, update, args[1], runtime=skills_runtime)
        return
    if sub == "edit" and len(args) >= 3:
        await skills_edit(event, update, args[1], " ".join(args[2:]), runtime=skills_runtime)
        return

    rendered = telegram_presenters.skills_usage_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def _shared_inline_command_handler(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_lock: ChatLock,
    build_conversation_runtime: Callable[[ChatLock], TelegramConversationRuntime],
    build_runtime_skill_runtime: Callable[[ChatLock], TelegramRuntimeSkillsRuntime],
) -> bool:
    command = (event.command or "").lower()
    conversation_runtime = build_conversation_runtime(_chat_lock_adapter(runtime, chat_lock))
    if command == "approval":
        await conversation_cmd_approval(event, update, context, runtime=conversation_runtime)
        return True
    if command == "skills":
        await _shared_skills_inline_handler(
            runtime,
            event,
            update,
            chat_lock=chat_lock,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )
        return True
    if command == "compact":
        await conversation_cmd_compact(event, update, context, runtime=conversation_runtime)
        return True
    if command == "role":
        await conversation_cmd_role(event, update, context, runtime=conversation_runtime)
        return True
    if command == "model":
        await conversation_cmd_model(event, update, context, runtime=conversation_runtime)
        return True
    if command == "project":
        await conversation_cmd_project(event, update, context, runtime=conversation_runtime)
        return True
    if command == "policy":
        await conversation_cmd_policy(event, update, context, runtime=conversation_runtime)
        return True
    return False


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
        handled = await _shared_inline_command_handler(
            runtime,
            event,
            update,
            context,
            chat_lock=chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )
        if handled:
            return
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

    await _enqueue_shared_action(runtime, update, action)


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

    if _action_requires_public_guard(action.action) and _is_public_user(runtime, event.user):
        await query.answer(telegram_presenters.public_command_not_available_message().text, show_alert=True)
        return

    await query.answer()
    await _enqueue_shared_action(runtime, update, action)
