"""Telegram pending-request and recovery channel handlers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram import Update

from app import access
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.normalization import normalize_user
from app.channels.telegram.state import TelegramRuntime
from app.identity import telegram_conversation_key, telegram_event_id
from app.runtime import composition
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from app.session_state import SessionState
from app.skill_activation_service import get_skill_activation_service
from app import work_queue

log = logging.getLogger(__name__)

@dataclass(frozen=True)
class TelegramPendingRuntime:
    """Injected Telegram pending/recovery dependencies."""

    state: TelegramRuntime
    chat_lock: Callable[..., Any]
    edit_or_reply_text: Callable[..., Awaitable[None]]
    execute_request: Callable[..., Awaitable[None]]
    request_approval: Callable[..., Awaitable[None]]
    build_user_prompt: Callable[..., tuple[str, list[str]]]


def _flows():
    return composition.workflows()


def _conversation_key(chat_id: int | str) -> str:
    return telegram_conversation_key(chat_id)


def _event_key(update_id: int | str) -> str:
    return telegram_event_id(update_id)


def _load(runtime: TelegramPendingRuntime, chat_id: int | str) -> SessionState:
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


def _save(runtime: TelegramPendingRuntime, chat_id: int | str, session: SessionState) -> None:
    save_runtime_session(runtime.state.config.data_dir, _conversation_key(chat_id), session)


def _is_allowed(runtime: TelegramPendingRuntime, user) -> bool:
    override = work_queue.get_user_access(runtime.state.config.data_dir, user.id)
    return access.is_allowed_user_with_override(runtime.state.config, user, override)


async def approve_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramPendingRuntime,
) -> None:
    session = _load(runtime, chat_id)
    outcome = _flows().pending.requests.approve(
        session,
        cfg=runtime.state.config,
        provider_name=runtime.state.provider.name,
    )
    if outcome.mutated:
        _save(runtime, chat_id, session)
    if outcome.execution_plan is None:
        rendered = telegram_presenters.pending_plain_outcome_message(outcome.message)
        await message.reply_text(rendered.text, **rendered.kwargs())
        return
    await runtime.execute_request(
        chat_id,
        outcome.execution_plan.prompt,
        list(outcome.execution_plan.image_paths),
        message,
        extra_dirs=list(outcome.execution_plan.extra_dirs) or None,
        request_user_id=outcome.execution_plan.request_user_id,
        skip_permissions=True,
        trust_tier=outcome.execution_plan.trust_tier,
        cancel_event=cancel_event,
    )


async def reject_pending(chat_id: int | str, message, *, runtime: TelegramPendingRuntime) -> None:
    session = _load(runtime, chat_id)
    outcome = _flows().pending.requests.reject(session)
    if outcome.mutated:
        _save(runtime, chat_id, session)
    rendered = telegram_presenters.pending_plain_outcome_message(outcome.message)
    await message.reply_text(rendered.text, **rendered.kwargs())


async def retry_skip_pending(chat_id: int | str, message, *, runtime: TelegramPendingRuntime) -> None:
    session = _load(runtime, chat_id)
    outcome = _flows().pending.requests.retry_skip(session)
    if outcome.mutated:
        _save(runtime, chat_id, session)
    rendered = telegram_presenters.pending_plain_outcome_message(outcome.message)
    await runtime.edit_or_reply_text(message, rendered.text, **rendered.kwargs())


async def retry_allow_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramPendingRuntime,
) -> None:
    session = _load(runtime, chat_id)
    outcome = _flows().pending.requests.retry_allow(
        session,
        cfg=runtime.state.config,
        provider_name=runtime.state.provider.name,
    )
    if outcome.mutated:
        _save(runtime, chat_id, session)
    if outcome.execution_plan is None:
        rendered = telegram_presenters.pending_plain_outcome_message(outcome.message)
        await runtime.edit_or_reply_text(message, rendered.text, **rendered.kwargs())
        return
    await runtime.execute_request(
        chat_id,
        outcome.execution_plan.prompt,
        list(outcome.execution_plan.image_paths),
        message,
        extra_dirs=list(outcome.execution_plan.extra_dirs) or None,
        request_user_id=outcome.execution_plan.request_user_id,
        skip_permissions=True,
        trust_tier=outcome.execution_plan.trust_tier,
        cancel_event=cancel_event,
    )


async def handle_pending_callback(event, query, *, runtime: TelegramPendingRuntime) -> None:
    chat_id = event.chat_id

    async with runtime.chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        if event.data == "approval_approve":
            await query.edit_message_reply_markup(reply_markup=None)
            await approve_pending(chat_id, query.message, runtime=runtime)
            return

        if event.data == "approval_reject":
            await query.edit_message_reply_markup(reply_markup=None)
            await reject_pending(chat_id, query.message, runtime=runtime)
            return

        if event.data == "retry_skip":
            await query.edit_message_reply_markup(reply_markup=None)
            await retry_skip_pending(chat_id, query.message, runtime=runtime)
            return

        if event.data == "retry_allow":
            await query.edit_message_reply_markup(reply_markup=None)
            await retry_allow_pending(chat_id, query.message, runtime=runtime)


async def handle_recovery_callback(update: Update, context, *, runtime: TelegramPendingRuntime) -> None:
    del context
    query = update.callback_query
    user = normalize_user(update.effective_user)
    if user is None or not _is_allowed(runtime, user):
        rendered = telegram_presenters.trust_not_authorized_message()
        await query.answer(rendered.text, show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        rendered = telegram_presenters.recovery_invalid_action_message()
        await query.answer(rendered.text)
        return
    action, update_id_str = parts
    try:
        update_id = int(update_id_str)
    except (ValueError, TypeError):
        rendered = telegram_presenters.recovery_invalid_action_message()
        await query.answer(rendered.text)
        return

    await handle_recovery_action(
        update.effective_chat.id,
        action,
        update_id,
        query.message,
        answer_action=query.answer,
        runtime=runtime,
    )


async def handle_recovery_action(
    chat_id: int | str,
    action: str,
    update_id: int,
    message,
    *,
    answer_action=None,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramPendingRuntime,
) -> None:
    if answer_action is None:
        async def answer_action(text=None, show_alert=False):
            del text, show_alert
            return None

    cfg = runtime.state.config
    data_dir = cfg.data_dir
    outcome = _flows().recovery.replay.prepare_action(
        data_dir=data_dir,
        conversation_key=_conversation_key(chat_id),
        event_id=_event_key(update_id),
        action=action,
        worker_id=runtime.state.boot_id,
        ignore_claimed_item_id=str(getattr(message, "_worker_item_id", "")),
        config=cfg,
    )
    if outcome.toast_message:
        await answer_action(outcome.toast_message, show_alert=outcome.show_alert)
    if outcome.edit_message:
        try:
            rendered = telegram_presenters.pending_html_outcome_message(outcome.edit_message)
            await runtime.edit_or_reply_text(message, rendered.text, **rendered.kwargs())
        except Exception:
            pass
    if outcome.replay_plan is None:
        return

    prompt, image_paths = runtime.build_user_prompt(
        outcome.replay_plan.event.text,
        list(outcome.replay_plan.event.attachments),
    )
    try:
        async with runtime.chat_lock(chat_id, message=message, worker_item={"id": outcome.replay_plan.item_id}):
            session = _load(runtime, chat_id)
            if not getattr(outcome.replay_plan.event, "routed_task_id", "") and session.approval_mode == "on":
                await runtime.request_approval(
                    chat_id,
                    prompt,
                    image_paths,
                    list(outcome.replay_plan.event.attachments),
                    message,
                    request_user_id=outcome.replay_plan.event.user.id,
                    trust_tier=outcome.replay_plan.trust_tier,
                    cancel_event=cancel_event,
                )
            else:
                await runtime.execute_request(
                    chat_id,
                    prompt,
                    image_paths,
                    message,
                    request_user_id=outcome.replay_plan.event.user.id,
                    trust_tier=outcome.replay_plan.trust_tier,
                    cancel_event=cancel_event,
                )
        _flows().recovery.replay.complete_replay(
            data_dir=data_dir,
            item_id=outcome.replay_plan.item_id,
        )
    except work_queue.LeaveClaimed:
        log.warning("Replay interrupted for chat %d; item stays claimed for re-recovery", chat_id)
    except Exception:
        log.exception("Replay failed for chat %d", chat_id)
        _flows().recovery.replay.fail_replay(
            data_dir=data_dir,
            item_id=outcome.replay_plan.item_id,
        )
        try:
            rendered = telegram_presenters.recovery_failed_edit_message()
            await runtime.edit_or_reply_text(message, rendered.text, **rendered.kwargs())
        except Exception:
            pass


async def handle_worker_pending_action(
    event,
    item: dict[str, object],
    params: dict[str, object],
    surface,
    *,
    runtime_chat: int | str,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramPendingRuntime,
) -> bool:
    if event.action == "approve_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await approve_pending(runtime_chat, surface, cancel_event=cancel_event, runtime=runtime)
        return True
    if event.action == "reject_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await reject_pending(runtime_chat, surface, runtime=runtime)
        return True
    if event.action == "retry_skip":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_skip_pending(runtime_chat, surface, runtime=runtime)
        return True
    if event.action == "retry_allow":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_allow_pending(runtime_chat, surface, cancel_event=cancel_event, runtime=runtime)
        return True
    if event.action in {"recovery_replay", "recovery_discard"}:
        update_id = int(params.get("update_id") or 0)
        if update_id <= 0:
            rendered = telegram_presenters.recovery_invalid_action_message()
            await surface.reply_text(rendered.text, **rendered.kwargs())
            return True
        if event.action == "recovery_replay":
            work_queue.complete_work_item(runtime.state.config.data_dir, str(item.get("id", "")))
        await surface.edit_reply_markup(reply_markup=None)
        await handle_recovery_action(
            runtime_chat,
            event.action,
            update_id,
            surface,
            cancel_event=cancel_event,
            runtime=runtime,
        )
        return True
    return False
