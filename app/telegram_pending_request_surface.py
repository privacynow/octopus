"""Telegram surface handlers for pending-request and recovery workflows."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode

from app import access, user_messages as _msg
from app.inbound_use_case_factory import (
    get_pending_request_use_cases,
    get_recovery_use_cases,
)
from app import work_queue


def _th():
    import app.telegram_handlers as th

    return th


async def approve_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    th = _th()
    session = th._load(chat_id)
    outcome = get_pending_request_use_cases().approve(
        session,
        cfg=th._cfg(),
        provider_name=th._prov().name,
    )
    if outcome.mutated:
        th._save(chat_id, session)
    if outcome.execution_plan is None:
        await message.reply_text(outcome.message)
        return
    await th.execute_request(
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


async def reject_pending(chat_id: int | str, message) -> None:
    th = _th()
    session = th._load(chat_id)
    outcome = get_pending_request_use_cases().reject(session)
    if outcome.mutated:
        th._save(chat_id, session)
    await message.reply_text(outcome.message)


async def retry_skip_pending(chat_id: int | str, message) -> None:
    th = _th()
    session = th._load(chat_id)
    outcome = get_pending_request_use_cases().retry_skip(session)
    if outcome.mutated:
        th._save(chat_id, session)
    await th._edit_or_reply_text(message, outcome.message)


async def retry_allow_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    th = _th()
    session = th._load(chat_id)
    outcome = get_pending_request_use_cases().retry_allow(
        session,
        cfg=th._cfg(),
        provider_name=th._prov().name,
    )
    if outcome.mutated:
        th._save(chat_id, session)
    if outcome.execution_plan is None:
        await th._edit_or_reply_text(message, outcome.message)
        return
    await th.execute_request(
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


async def handle_pending_callback(event, query) -> None:
    th = _th()
    chat_id = event.chat_id

    async with th._chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        if event.data == "approval_approve":
            await query.edit_message_reply_markup(reply_markup=None)
            await approve_pending(chat_id, query.message)
            return

        if event.data == "approval_reject":
            await query.edit_message_reply_markup(reply_markup=None)
            await reject_pending(chat_id, query.message)
            return

        if event.data == "retry_skip":
            await query.edit_message_reply_markup(reply_markup=None)
            await retry_skip_pending(chat_id, query.message)
            return

        if event.data == "retry_allow":
            await query.edit_message_reply_markup(reply_markup=None)
            await retry_allow_pending(chat_id, query.message)


async def handle_recovery_callback(update: Update, context) -> None:
    del context
    query = update.callback_query
    user = access.to_inbound_user(update.effective_user)
    if user is None or not _th().is_allowed(user):
        await query.answer(_msg.trust_not_authorized(), show_alert=True)
        return

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        await query.answer(_msg.recovery_invalid_action())
        return
    action, update_id_str = parts
    try:
        update_id = int(update_id_str)
    except (ValueError, TypeError):
        await query.answer(_msg.recovery_invalid_action())
        return

    await handle_recovery_action(
        update.effective_chat.id,
        action,
        update_id,
        query.message,
        answer_action=query.answer,
    )


async def handle_recovery_action(
    chat_id: int | str,
    action: str,
    update_id: int,
    message,
    *,
    answer_action=None,
    cancel_event: asyncio.Event | None = None,
) -> None:
    th = _th()
    if answer_action is None:
        async def answer_action(text=None, show_alert=False):
            del text, show_alert
            return None

    cfg = th._cfg()
    data_dir = cfg.data_dir
    outcome = get_recovery_use_cases().prepare_action(
        data_dir=data_dir,
        conversation_key=th._conversation_key(chat_id),
        event_id=th._event_key(update_id),
        action=action,
        worker_id=th._boot_id,
        ignore_claimed_item_id=str(getattr(message, "_worker_item_id", "")),
        config=cfg,
    )
    if outcome.toast_message:
        await answer_action(outcome.toast_message, show_alert=outcome.show_alert)
    if outcome.edit_message:
        try:
            await th._edit_or_reply_text(
                message,
                outcome.edit_message,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    if outcome.replay_plan is None:
        return

    prompt, image_paths = th.build_user_prompt(
        outcome.replay_plan.event.text,
        list(outcome.replay_plan.event.attachments),
    )
    try:
        async with th._chat_lock(chat_id, message=message, worker_item={"id": outcome.replay_plan.item_id}):
            session = th._load(chat_id)
            if not getattr(outcome.replay_plan.event, "routed_task_id", "") and session.approval_mode == "on":
                await th.request_approval(
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
                await th.execute_request(
                    chat_id,
                    prompt,
                    image_paths,
                    message,
                    request_user_id=outcome.replay_plan.event.user.id,
                    trust_tier=outcome.replay_plan.trust_tier,
                    cancel_event=cancel_event,
                )
        get_recovery_use_cases().complete_replay(
            data_dir=data_dir,
            item_id=outcome.replay_plan.item_id,
        )
    except work_queue.LeaveClaimed:
        th.log.warning("Replay interrupted for chat %d; item stays claimed for re-recovery", chat_id)
    except Exception:
        th.log.exception("Replay failed for chat %d", chat_id)
        get_recovery_use_cases().fail_replay(
            data_dir=data_dir,
            item_id=outcome.replay_plan.item_id,
        )
        try:
            await th._edit_or_reply_text(
                message,
                _msg.recovery_replay_failed_edit(),
                parse_mode=ParseMode.HTML,
            )
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
) -> bool:
    if event.action == "approve_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await approve_pending(runtime_chat, surface, cancel_event=cancel_event)
        return True
    if event.action == "reject_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await reject_pending(runtime_chat, surface)
        return True
    if event.action == "retry_skip":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_skip_pending(runtime_chat, surface)
        return True
    if event.action == "retry_allow":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_allow_pending(runtime_chat, surface, cancel_event=cancel_event)
        return True
    if event.action in {"recovery_replay", "recovery_discard"}:
        update_id = int(params.get("update_id") or 0)
        if update_id <= 0:
            await surface.reply_text(_msg.recovery_invalid_action())
            return True
        if event.action == "recovery_replay":
            work_queue.complete_work_item(_th()._cfg().data_dir, str(item.get("id", "")))
        await surface.edit_reply_markup(reply_markup=None)
        await handle_recovery_action(
            runtime_chat,
            event.action,
            update_id,
            surface,
            cancel_event=cancel_event,
        )
        return True
    return False
