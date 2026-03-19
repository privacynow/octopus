"""Telegram worker dispatch and action execution."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import html
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app import access
from app import user_messages as _msg
from app import work_queue
from app.agents.bridge import (
    publish_timeline_event,
    summarize_text,
    telegram_conversation_ref,
)
from app.agents.delegation import (
    handle_delegation_approve as handle_channel_delegation_approve,
    handle_delegation_cancel as handle_channel_delegation_cancel,
)
from app.agents.types import RoutedTaskResult
from app.channel_egress_factory import create_channel_egress
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.conversation import handle_worker_conversation_action
from app.channels.telegram.execution import (
    build_conversation_runtime,
    build_delegation_channel_runtime,
    build_pending_runtime,
    build_runtime_skill_runtime,
    build_user_prompt,
    execute_request,
    request_approval,
)
from app.channels.telegram.pending import handle_worker_pending_action
from app.channels.telegram.runtime_skills import handle_worker_skill_action
from app.channels.telegram.session_io import (
    conversation_key,
    load as load_session,
    save as save_session,
)
from app.channels.telegram.state import TelegramRuntime
from app.identity import telegram_numeric_id
from app.runtime.inbound_types import (
    InboundAction,
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
)
from app.runtime.work_admission import trust_tier_for_source
from app.workflows.delegation.coordination import finalize_resumed_delegation
from app.workflows.execution.contracts import RequestExecutionOutcome
from app.worker import poll_interval_for_runtime

log = logging.getLogger(__name__)


def _is_allowed(runtime: TelegramRuntime, user: InboundUser) -> bool:
    if not isinstance(user, InboundUser):
        return False
    override = work_queue.get_user_access(runtime.config.data_dir, user.id)
    return access.is_allowed_user_with_override(runtime.config, user, override)


@contextlib.asynccontextmanager
async def _worker_chat_lock(
    runtime: TelegramRuntime,
    chat_id: int | str,
    *,
    message=None,
    query=None,
    update_id: int | None = None,
    worker_item: dict[str, Any],
    supersede_recovery: bool = False,
) -> AsyncIterator[bool]:
    del message, query, update_id, supersede_recovery
    data_dir = runtime.config.data_dir
    conversation_ref_key = conversation_key(chat_id)
    if runtime.config.runtime_mode == "shared":
        work_queue.supersede_pending_recovery(data_dir, conversation_ref_key)
        try:
            yield False
        except work_queue.LeaveClaimed:
            raise
        return

    lock = runtime.chat_locks[chat_id]
    async with lock:
        work_queue.supersede_pending_recovery(data_dir, conversation_ref_key)
        try:
            yield False
        except work_queue.LeaveClaimed:
            raise


def _worker_chat_lock_adapter(runtime: TelegramRuntime):
    return lambda chat_id, **kwargs: _worker_chat_lock(runtime, chat_id, **kwargs)


async def _poll_cancel_requested(
    runtime: TelegramRuntime,
    item_id: str,
    cancel_event: asyncio.Event,
) -> None:
    interval = poll_interval_for_runtime(runtime.config.runtime_mode)
    while not cancel_event.is_set():
        if work_queue.is_cancel_requested(runtime.config.data_dir, item_id):
            cancel_event.set()
            return
        await asyncio.sleep(interval)


async def _run_with_cancel_watch(
    runtime: TelegramRuntime,
    item: dict[str, Any],
    runner,
):
    if runtime.config.runtime_mode != "shared":
        return await runner(None)
    cancel_event = asyncio.Event()
    watcher = asyncio.create_task(
        _poll_cancel_requested(runtime, item["id"], cancel_event),
        name=f"cancel-watch:{item['id']}",
    )
    try:
        return await runner(cancel_event)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def _action_target_message_id(event: InboundAction) -> int | None:
    raw = event.params.get("message_id")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _build_action_channel_egress(
    runtime: TelegramRuntime,
    event: InboundAction,
    *,
    item: dict[str, Any],
):
    bot_instance = runtime.bot_instance
    source = getattr(event, "source", "telegram")
    action_conversation_key = str(item.get("conversation_key") or event.conversation_key)
    chat_id = telegram_numeric_id(action_conversation_key) if source == "telegram" else None
    if source == "telegram" and (chat_id is None or bot_instance is None):
        raise RuntimeError(
            f"Telegram action item {item.get('id')} missing bot or chat_id for {action_conversation_key!r}"
        )
    runtime_chat = chat_id if chat_id is not None else action_conversation_key
    conversation_ref = event.conversation_ref or (
        telegram_conversation_ref(runtime.config, chat_id)
        if source == "telegram" and chat_id is not None
        else action_conversation_key
    )
    channel_egress = create_channel_egress(
        conversation_ref,
        config=runtime.config,
        bot=bot_instance,
        conversation_key=action_conversation_key,
        source=source,
        target_message_id=_action_target_message_id(event),
        output_log=getattr(bot_instance, "_output_log", None) if bot_instance is not None else None,
    )
    setattr(channel_egress, "_worker_item_id", str(item.get("id", "")))
    return channel_egress, runtime_chat, chat_id, conversation_ref, source


async def _execute_worker_action(
    runtime: TelegramRuntime,
    event: InboundAction,
    item: dict[str, Any],
    *,
    cancel_event: asyncio.Event | None,
) -> None:
    channel_egress, runtime_chat, _chat_id, conversation_ref, source = _build_action_channel_egress(
        runtime,
        event,
        item=item,
    )
    trust = trust_tier_for_source(source, event.user, config=runtime.config)
    action = event.action
    params = dict(event.params)

    if await handle_worker_conversation_action(
        event,
        item,
        channel_egress,
        runtime=build_conversation_runtime(runtime, chat_lock=_worker_chat_lock_adapter(runtime)),
        runtime_chat=runtime_chat,
        source=source,
        trust=trust,
    ):
        return

    if await handle_worker_pending_action(
        event,
        item,
        params,
        channel_egress,
        runtime_chat=runtime_chat,
        cancel_event=cancel_event,
        runtime=build_pending_runtime(runtime, chat_lock=_worker_chat_lock_adapter(runtime)),
    ):
        return

    if action == "delegation_approve":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_channel_delegation_approve(
            target_runtime,
            conversation_ref,
            channel_egress,
            runtime=build_delegation_channel_runtime(runtime),
        )
        return

    if action == "delegation_cancel":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_channel_delegation_cancel(
            target_runtime,
            conversation_ref,
            channel_egress,
            runtime=build_delegation_channel_runtime(runtime),
        )
        return

    if action in {"skills_add", "skills_remove", "skills_setup", "skills_clear"}:
        worker_event = dataclasses.replace(event, conversation_key=conversation_key(runtime_chat))
        if await handle_worker_skill_action(
            worker_event,
            channel_egress,
            runtime=build_runtime_skill_runtime(runtime, chat_lock=_worker_chat_lock_adapter(runtime)),
        ):
            return
        return

    log.warning("Worker dispatch: unknown semantic action %s for item %s", action, item.get("id"))


async def worker_dispatch(
    kind: str,
    event,
    item: dict,
    *,
    runtime: TelegramRuntime,
) -> None:
    """Dispatch a deserialized inbound event from the worker loop."""
    bot = runtime.bot_instance
    cfg = runtime.config
    data_dir = cfg.data_dir

    if isinstance(event, InboundMessage):
        source = getattr(event, "source", "telegram")
        message_conversation_key = str(item.get("conversation_key") or getattr(event, "conversation_key", ""))
        chat_id = telegram_numeric_id(message_conversation_key) if source == "telegram" else None
        runtime_chat = chat_id if chat_id is not None else message_conversation_key
        if source == "telegram" and (chat_id is None or bot is None):
            log.warning(
                "Worker dispatch: telegram item %s missing chat/bot (conversation_key=%s)",
                item.get("id"),
                message_conversation_key,
            )
            return
        conversation_ref = event.conversation_ref or (
            telegram_conversation_ref(runtime.config, chat_id)
            if source == "telegram" and chat_id is not None
            else message_conversation_key
        )
        routed_task_id = getattr(event, "routed_task_id", "")
        title = summarize_text(event.text) or "Conversation"
        channel_egress = create_channel_egress(
            conversation_ref,
            config=runtime.config,
            bot=bot,
            conversation_key=message_conversation_key,
            source=source,
            routed_task_id=routed_task_id,
            output_log=getattr(bot, "_output_log", None),
        )

        if item.get("dispatch_mode") == "recovery":
            if source == "telegram" and not _is_allowed(runtime, event.user):
                work_queue.fail_work_item(data_dir, item["id"], error="not_allowed")
                return
            update_id = telegram_numeric_id(str(item.get("event_id") or "")) or 0
            original_text = event.text or ""
            preview = html.escape(original_text[:200] + ("\u2026" if len(original_text) > 200 else ""))
            await channel_egress.bind(title=title, config=runtime.config)
            await channel_egress.send_recovery_notice(
                preview=preview,
                prompt=_msg.recovery_notice_prompt(),
                run_again_label=_msg.recovery_button_run_again(),
                skip_label=_msg.recovery_button_skip(),
                update_id=update_id,
            )
            work_queue.mark_pending_recovery(data_dir, item["id"])
            raise work_queue.PendingRecovery(item["id"])

        if source == "telegram" and not _is_allowed(runtime, event.user):
            work_queue.fail_work_item(data_dir, item["id"], error="not_allowed")
            return
        prompt, image_paths = build_user_prompt(event.text, list(event.attachments))
        user_id = event.user.id
        trust = trust_tier_for_source(source, event.user, config=runtime.config)
        await channel_egress.bind(title=title, config=runtime.config)
        await channel_egress.on_message_received(event.text)
        try:
            async with _worker_chat_lock(runtime, runtime_chat, worker_item=item):
                session = load_session(runtime, runtime_chat)
                outcome = None

                async def _run_message(cancel_event: asyncio.Event | None):
                    nonlocal outcome
                    if (
                        not routed_task_id
                        and not getattr(event, "skip_approval", False)
                        and session.approval_mode == "on"
                    ):
                        await request_approval(
                            runtime_chat,
                            prompt,
                            image_paths,
                            list(event.attachments),
                            channel_egress,
                            request_user_id=user_id,
                            trust_tier=trust,
                            cancel_event=cancel_event,
                            runtime=runtime,
                        )
                    else:
                        outcome = await execute_request(
                            runtime_chat,
                            prompt,
                            image_paths,
                            channel_egress,
                            request_user_id=user_id,
                            trust_tier=trust,
                            cancel_event=cancel_event,
                            runtime=runtime,
                        )

                await _run_with_cancel_watch(runtime, item, _run_message)
        except work_queue.LeaveClaimed:
            raise
        if outcome is not None:
            await channel_egress.on_outcome(outcome)
            if getattr(event, "skip_approval", False) and source == "registry":
                session_after = load_session(runtime, runtime_chat)
                finalized = finalize_resumed_delegation(
                    session_after.pending_delegation,
                    conversation_ref=conversation_ref,
                )
                if finalized.status == "cleared_after_resume":
                    session_after.pending_delegation = None
                    save_session(runtime, runtime_chat, session_after)
        if routed_task_id:
            client = runtime.registry_client_factory(runtime.config)
            if client is not None and outcome is not None:
                full_text = outcome.reply_text or html.unescape(getattr(channel_egress, "last_status_text", ""))
                result_status = (
                    "completed"
                    if outcome.status in {"completed", "completed_with_denials"}
                    else outcome.status
                )
                try:
                    await client.routed_task_result(
                        routed_task_id,
                        RoutedTaskResult(
                            routed_task_id=routed_task_id,
                            status=result_status,
                            summary=summarize_text(full_text or outcome.error_text or result_status),
                            full_text=full_text or outcome.error_text,
                            artifacts=(),
                            follow_up_questions=(),
                        ),
                    )
                except Exception:
                    log.warning(
                        "Failed to report routed task result for %s",
                        routed_task_id,
                        exc_info=True,
                    )
        if outcome is not None and outcome.status in {"completed", "completed_with_denials"}:
            try:
                work_queue.record_usage(
                    data_dir,
                    conversation_key=message_conversation_key,
                    work_item_id=item["id"],
                    provider=cfg.provider_name,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cost_usd=outcome.cost_usd,
                )
            except Exception:
                log.warning(
                    "Failed to record usage for conversation %s",
                    message_conversation_key,
                    exc_info=True,
                )
            if conversation_ref and (
                outcome.prompt_tokens > 0 or outcome.completion_tokens > 0
            ):
                try:
                    await publish_timeline_event(
                        cfg,
                        conversation_ref=conversation_ref,
                        kind="usage",
                        title="Token usage",
                        body="",
                        metadata={
                            "prompt_tokens": outcome.prompt_tokens,
                            "completion_tokens": outcome.completion_tokens,
                            "cost_usd": outcome.cost_usd,
                            "provider": cfg.provider_name,
                        },
                    )
                except Exception:
                    log.debug("Failed to publish usage timeline event", exc_info=True)
        _maybe_fire_webhook(cfg, chat_id or 0, conversation_ref, outcome)
        return

    if isinstance(event, InboundAction):
        try:
            await _run_with_cancel_watch(
                runtime,
                item,
                lambda cancel_event: _execute_worker_action(
                    runtime,
                    event,
                    item,
                    cancel_event=cancel_event,
                ),
            )
        except work_queue.LeaveClaimed:
            raise
        return

    if isinstance(event, (InboundCommand, InboundCallback)):
        conversation_ref_key = str(item.get("conversation_key", ""))
        chat_id = telegram_numeric_id(conversation_ref_key)
        log.info(
            "Worker recovered orphaned %s for conversation %s (event %s)",
            kind,
            conversation_ref_key,
            item.get("event_id"),
        )
        if chat_id is None or bot is None:
            return
        try:
            detail = f"/{event.command}" if isinstance(event, InboundCommand) else "a button action"
            rendered = telegram_presenters.recovery_orphaned_command_message(detail)
            await bot.send_message(chat_id, rendered.text, **rendered.kwargs())
        except Exception:
            pass
        return

    log.warning("Worker dispatch: unknown event type for item %s", item.get("id"))


def _maybe_fire_webhook(
    cfg,
    chat_id: int,
    conversation_ref: str,
    outcome: RequestExecutionOutcome | None,
) -> None:
    if not cfg.completion_webhook_url:
        return
    if outcome is None or outcome.status == "delegation_proposed":
        return
    from app.webhook import fire_completion_webhook

    summary = (outcome.reply_text or outcome.error_text or "")[:200]
    completed_at = datetime.now(timezone.utc).isoformat()
    asyncio.create_task(
        fire_completion_webhook(
            cfg.completion_webhook_url,
            chat_id=chat_id,
            conversation_ref=conversation_ref,
            status=outcome.status,
            summary=summary,
            completed_at=completed_at,
        )
    )
