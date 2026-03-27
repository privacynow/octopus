"""Telegram worker dispatch and action execution."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from typing import Any, AsyncIterator

from app import work_queue
from app.agents.state import runtime_registry_agent_id
from app.presentation import telegram as telegram_presenters
from app.workflows.conversation.telegram import handle_worker_conversation_action
from app.runtime.telegram_execution import (
    build_conversation_runtime,
    build_pending_runtime,
    build_runtime_skill_runtime,
    build_transport_identity,
    build_user_prompt,
)
from app.workflows.pending.telegram import handle_worker_pending_action
from app.workflows.runtime_skills.telegram import handle_worker_skill_action
from app.runtime.telegram_session_io import (
    actor_key as _actor_key,
    conversation_key,
    load as load_session,
    save as save_session,
)
from app.channels.telegram.state import TelegramRuntime
from app.formatting import summarize_text
from octopus_sdk.identity import telegram_conversation_ref, telegram_numeric_id
from octopus_sdk.inbound_types import (
    InboundAction,
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
)
from app.runtime.work_admission import admit_worker_message, trust_tier_for_ref
from octopus_sdk.execution import ExecutionRuntime
from octopus_sdk.execution import RequestExecutionOutcome
from app.workflows.execution.finalization import FinalizationContext, finalize_execution
from octopus_sdk.execution import dispatch_message_request, load_approval_mode
from app.runtime.session_runtime import LocalSessionRuntime
from app.worker import poll_interval_for_runtime
from octopus_sdk.workflows.delegation import (
    ParticipantDelegationRuntime,
    approve_participant_delegation,
    cancel_participant_delegation,
    expire_stale_delegations,
)
from octopus_sdk.work_queue import WorkItemRecord

log = logging.getLogger(__name__)


def _routed_task_requires_interactive_failure() -> RequestExecutionOutcome:
    return RequestExecutionOutcome(
        status="failed",
        error_text=(
            "Routed task could not continue because it requires an interactive "
            "setup or approval step."
        ),
    )


async def _noop_async(*args: Any, **kwargs: Any) -> None:
    del args, kwargs


def _item_conversation_key(item: WorkItemRecord) -> str:
    conversation_key_value = item.conversation_key.strip()
    if not conversation_key_value:
        raise RuntimeError(f"worker item missing conversation_key: {item.id}")
    return conversation_key_value


def _normalized_event_text(text: str | None) -> str:
    return "" if text is None else text


def _transport_dispatcher(runtime: TelegramRuntime):
    dispatcher = getattr(runtime, "transport_dispatcher", None)
    if dispatcher is None:
        raise RuntimeError("Telegram runtime is missing a transport dispatcher")
    return dispatcher


def _participant_delegation_runtime(runtime: TelegramRuntime) -> ParticipantDelegationRuntime:
    return ParticipantDelegationRuntime(
        config=runtime.config,
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        coordination=runtime.services.registry.coordination,
        sessions=LocalSessionRuntime(runtime.config),
    )


def _recovery_runtime(runtime: TelegramRuntime):
    return runtime.services.workflows.recovery.replay


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
    item: WorkItemRecord,
    runner,
):
    if runtime.config.runtime_mode != "shared":
        return await runner(None)
    cancel_event = asyncio.Event()
    watcher = asyncio.create_task(
        _poll_cancel_requested(runtime, item.id, cancel_event),
        name=f"cancel-watch:{item.id}",
    )
    try:
        return await runner(cancel_event)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def notify_deserialize_failure(
    item: WorkItemRecord,
    *,
    runtime: TelegramRuntime,
) -> None:
    conversation_key_value = item.conversation_key
    chat_id = telegram_numeric_id(conversation_key_value)
    bot = runtime.bot_instance
    if chat_id is None or bot is None:
        return
    rendered = telegram_presenters.generic_error_try_again_message()
    await bot.send_message(chat_id, rendered.text, **rendered.kwargs())


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
    item: WorkItemRecord,
):
    action_conversation_key = _item_conversation_key(item)
    return _build_channel_egress(
        runtime,
        conversation_key=action_conversation_key,
        source=getattr(event, "source", "telegram"),
        conversation_ref=event.conversation_ref,
        external_conversation_ref=getattr(event, "external_conversation_ref", ""),
        authority_ref=event.authority_ref,
        routed_task_id="",
        target_message_id=_action_target_message_id(event),
        item_id=item.id,
    )


def _build_channel_egress(
    runtime: TelegramRuntime,
    *,
    conversation_key: str,
    source: str,
    conversation_ref: str = "",
    external_conversation_ref: str = "",
    authority_ref: str = "",
    routed_task_id: str = "",
    target_message_id: int | None = None,
    item_id: str = "",
):
    bot_instance = runtime.bot_instance
    dispatcher = _transport_dispatcher(runtime)
    chat_id = telegram_numeric_id(conversation_key)
    runtime_chat = chat_id if chat_id is not None else conversation_key
    resolved_conversation_ref = conversation_ref
    if not resolved_conversation_ref:
        if chat_id is not None:
            resolved_conversation_ref = telegram_conversation_ref(runtime.config, chat_id)
        else:
            resolved_conversation_ref = conversation_key
    channel_egress = dispatcher.create_egress(
        resolved_conversation_ref,
        config=runtime.config,
        bot=bot_instance,
        conversation_key=conversation_key,
        source=source,
        authority_ref=authority_ref,
        routed_task_id=routed_task_id,
        external_id=external_conversation_ref,
        target_message_id=target_message_id,
        output_log=getattr(bot_instance, "_output_log", None) if bot_instance is not None else None,
    )
    setattr(channel_egress, "_worker_item_id", item_id)
    return channel_egress, runtime_chat, chat_id, resolved_conversation_ref, source


async def _execute_worker_action(
    runtime: TelegramRuntime,
    event: InboundAction,
    item: WorkItemRecord,
    *,
    execution_runtime: ExecutionRuntime,
    cancel_event: asyncio.Event | None,
) -> None:
    channel_egress, runtime_chat, _chat_id, conversation_ref, source = _build_action_channel_egress(
        runtime,
        event,
        item=item,
    )
    trust = trust_tier_for_ref(
        conversation_ref,
        event.user,
        config=runtime.config,
        dispatcher=_transport_dispatcher(runtime),
    )
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
        runtime=build_pending_runtime(
            runtime,
            chat_lock=_worker_chat_lock_adapter(runtime),
            execution_runtime=execution_runtime,
        ),
    ):
        return

    action_conversation_key = _item_conversation_key(item)

    if action == "delegation_approve":
        target_key = action_conversation_key
        if params.get("target_conversation_key"):
            target_key = str(params["target_conversation_key"])
        outcome = await approve_participant_delegation(
            _participant_delegation_runtime(runtime),
            target_key,
        )
        await channel_egress.send_text(outcome.message)
        return

    if action == "delegation_cancel":
        target_key = action_conversation_key
        if params.get("target_conversation_key"):
            target_key = str(params["target_conversation_key"])
        outcome = await cancel_participant_delegation(
            _participant_delegation_runtime(runtime),
            target_key,
        )
        await channel_egress.send_text(outcome.message)
        return

    if action in {"skills_add", "skills_remove", "skills_setup", "skills_clear"}:
        worker_event = dataclasses.replace(event, conversation_key=conversation_key(runtime_chat))
        if await handle_worker_skill_action(
            worker_event,
            channel_egress,
            runtime=build_runtime_skill_runtime(
                runtime,
                chat_lock=_worker_chat_lock_adapter(runtime),
                execution_runtime=execution_runtime,
            ),
        ):
            return
        return

    log.warning("Worker dispatch: unknown semantic action %s for item %s", action, item.id)


async def worker_dispatch(
    kind: str,
    event,
    item: WorkItemRecord,
    *,
    runtime: TelegramRuntime,
    execution_runtime: ExecutionRuntime,
) -> None:
    """Dispatch a deserialized inbound event the worker loop.

    Completion ownership:
    - `worker_loop()` marks the item done after normal return this function.
    - `admit_worker_message()` marks rejected items failed at the admission boundary.
    - `dispatch_worker_recovery()` moves claimed recovery items to `pending_recovery`;
      this function then raises `PendingRecovery` so `worker_loop()` does not mark done.
    - execution workflows raise `LeaveClaimed` for interrupted provider runs; the
      caller leaves the item claimed for later recovery.
    - any uncaught exception this function bubbles to `worker_loop()`, which
      marks the item failed.
    """
    bot = runtime.bot_instance
    cfg = runtime.config
    data_dir = cfg.data_dir

    if isinstance(event, InboundMessage):
        source = getattr(event, "source", "telegram")
        message_conversation_key = _item_conversation_key(item)
        routed_task_id = getattr(event, "routed_task_id", "")
        authority_ref = getattr(event, "authority_ref", "")
        is_routed_task = bool(routed_task_id)
        title = summarize_text(event.text)
        if not title:
            title = "Conversation"
        dispatcher = _transport_dispatcher(runtime)
        message_chat_id = telegram_numeric_id(message_conversation_key)
        admission_conversation_ref = event.conversation_ref
        if not admission_conversation_ref:
            if message_chat_id is not None:
                admission_conversation_ref = telegram_conversation_ref(runtime.config, message_chat_id)
            else:
                admission_conversation_ref = message_conversation_key
        channel_egress, runtime_chat, chat_id, conversation_ref, source = _build_channel_egress(
            runtime,
            conversation_key=message_conversation_key,
            source=source,
            conversation_ref=event.conversation_ref,
            external_conversation_ref=getattr(event, "external_conversation_ref", ""),
            authority_ref=authority_ref,
            routed_task_id=routed_task_id,
            item_id=item.id,
        )

        admission = admit_worker_message(
            data_dir=data_dir,
            item_id=item.id,
            conversation_ref=admission_conversation_ref,
            user=event.user,
            config=runtime.config,
            dispatcher=dispatcher,
        )
        if not admission.allowed:
            return

        if item.dispatch_mode == "recovery":
            raw_event_id = item.event_id
            numeric_event_id = telegram_numeric_id(raw_event_id)
            update_id = 0 if numeric_event_id is None else numeric_event_id
            recovery_outcome = await _recovery_runtime(runtime).dispatch_worker_recovery(
                data_dir=data_dir,
                item_id=item.id,
                original_text=_normalized_event_text(event.text),
                update_id=update_id,
                bind_egress=(
                    (lambda: channel_egress.bind(title=title, config=runtime.config))
                    if not is_routed_task
                    else _noop_async
                ),
                send_notice=(
                    (
                        lambda notice: channel_egress.send_recovery_notice(
                            preview=notice.preview,
                            prompt=notice.prompt,
                            run_again_label=notice.run_again_label,
                            skip_label=notice.skip_label,
                            update_id=notice.update_id,
                        )
                    )
                    if not is_routed_task
                    else (lambda notice: _noop_async(notice))
                ),
            )
            if recovery_outcome.status == "pending_recovery":
                raise work_queue.PendingRecovery(item.id)
            raise RuntimeError(
                f"Unexpected recovery outcome: {recovery_outcome.status}"
            )

        prompt, image_paths = build_user_prompt(event.text, list(event.attachments))
        user_id = _actor_key(event.user.id)
        if not is_routed_task:
            await channel_egress.bind(title=title, config=runtime.config)
        try:
            async with _worker_chat_lock(runtime, runtime_chat, worker_item=item):
                outcome = None
                session = load_session(runtime, runtime_chat)
                expiration = expire_stale_delegations(
                    session.pending_delegation,
                    timeout_seconds=runtime.config.delegation_timeout_seconds,
                )
                if expiration.expired:
                    session.pending_delegation = expiration.pending
                    save_session(runtime, runtime_chat, session)
                approval_mode = load_approval_mode(message_conversation_key, runtime=execution_runtime)

                async def _run_message(cancel_event: asyncio.Event | None):
                    nonlocal outcome
                    transport = build_transport_identity(
                        runtime,
                        channel_egress,
                        runtime_chat,
                        actor_key=user_id,
                    )
                    outcome = await dispatch_message_request(
                        transport,
                        prompt,
                        image_paths,
                        list(event.attachments),
                        channel_egress,
                        approval_mode=approval_mode,
                        routed_task_id=routed_task_id,
                        skip_approval=getattr(event, "skip_approval", False),
                        trust_tier=admission.trust_tier,
                        cancel_event=cancel_event,
                        runtime=execution_runtime,
                    )

                await _run_with_cancel_watch(runtime, item, _run_message)
        except work_queue.LeaveClaimed:
            raise
        if is_routed_task and outcome is None:
            outcome = _routed_task_requires_interactive_failure()
        finalization = await finalize_execution(
            outcome,
            context=FinalizationContext(
                config=cfg,
                item_id=item.id,
                conversation_key=message_conversation_key,
                runtime_chat=runtime_chat,
                conversation_ref=conversation_ref,
                chat_id=0 if chat_id is None else chat_id,
                routed_task_id=routed_task_id,
                authority_ref=authority_ref,
                skip_approval=getattr(event, "skip_approval", False),
                last_status_text=getattr(channel_egress, "last_status_text", ""),
                load_session=lambda target_chat: load_session(runtime, target_chat),
                save_session=lambda target_chat, session: save_session(runtime, target_chat, session),
                task_routing=runtime.services.control_plane.task_routing,
                record_usage=work_queue.record_usage,
            ),
        )
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
                    execution_runtime=execution_runtime,
                    cancel_event=cancel_event,
                ),
            )
        except work_queue.LeaveClaimed:
            raise
    if isinstance(event, (InboundCommand, InboundCallback)):
        conversation_ref_key = item.conversation_key
        chat_id = telegram_numeric_id(conversation_ref_key)
        log.info(
            "Worker recovered orphaned %s for conversation %s (event %s)",
            kind,
            conversation_ref_key,
            item.event_id,
        )
        if chat_id is None or bot is None:
            return
        try:
            detail = f"/{event.command}" if isinstance(event, InboundCommand) else "a button action"
            rendered = telegram_presenters.recovery_orphaned_command_message(detail)
            await bot.send_message(chat_id, rendered.text, **rendered.kwargs())
        except Exception:
            log.debug(
                "Could not send orphaned command notice to chat %s",
                chat_id,
                exc_info=True,
            )
        return

    log.warning("Worker dispatch: unknown event type for item %s", item.id)
