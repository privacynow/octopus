"""Telegram channel ingress, progress display, and PTB wiring."""

import asyncio
import contextlib
import contextvars
import dataclasses
import html
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app import access
from app import user_messages as _msg
from app.channels.telegram import presenters as telegram_presenters
from app.config import BotConfig
from app.formatting import extract_send_directives, trim_text
from app.identity import (
    parse_actor_key,
    parse_conversation_key,
    telegram_actor_key,
    telegram_conversation_key,
    telegram_event_id,
    telegram_numeric_id,
)
from app.execution_context import ResolvedExecutionContext
from app.providers.base import Provider
from app.session_state import (
    DelegatedTask,
    PendingDelegation,
    PendingApproval,
    PendingRetry,
    SessionState,
    session_to_dict,
)
from app.agents.bridge import (
    bind_conversation,
    publish_timeline_event,
    registry_client,
    summarize_text,
    telegram_conversation_ref,
)
from app.agents.client import RegistryClientError
from app.agents.delegation import (
    build_delegation_runtime,
    handle_delegation_approve as handle_surface_delegation_approve,
    handle_delegation_cancel as handle_surface_delegation_cancel,
)
from app.agents.state import load_agent_runtime_state
from app.agents.types import AgentDiscoveryQuery, RoutedTaskResult, TimelineEvent
from app.channels.telegram.cancellation import get_cancellation_registry
from app.channels.telegram.normalization import normalize_callback, normalize_command, normalize_message, normalize_user
from app.channels.telegram.state import (
    build_channel_state,
    get_channel_state,
    install_channel_state,
)
from app.channels.telegram.runtime_skills import (
    cmd_clear_credentials as runtime_skill_cmd_clear_credentials,
    handle_clear_cred_callback as runtime_skill_handle_clear_cred_callback,
    handle_skill_add_callback as runtime_skill_handle_skill_add_callback,
    handle_skill_update_callback as runtime_skill_handle_skill_update_callback,
    handle_worker_skill_action as runtime_skill_handle_worker_skill_action,
    maybe_handle_setup_message as runtime_skill_maybe_handle_setup_message,
    TelegramRuntimeSkillsRuntime,
)
from app.channels.telegram.guidance import (
    guidance_approve as channel_guidance_approve,
    guidance_archive as channel_guidance_archive,
    guidance_edit as channel_guidance_edit,
    guidance_history as channel_guidance_history,
    guidance_preview as channel_guidance_preview,
    guidance_publish as channel_guidance_publish,
    guidance_reject as channel_guidance_reject,
    guidance_submit as channel_guidance_submit,
)
from app.channels.telegram.conversation import (
    cancel_chat_operation as conversation_cancel_chat_operation,
    cmd_approval as conversation_cmd_approval,
    cmd_cancel as conversation_cmd_cancel,
    cmd_compact as conversation_cmd_compact,
    cmd_model as conversation_cmd_model,
    cmd_new as conversation_cmd_new,
    cmd_policy as conversation_cmd_policy,
    cmd_project as conversation_cmd_project,
    cmd_role as conversation_cmd_role,
    cmd_settings as conversation_cmd_settings,
    handle_settings_callback as conversation_handle_settings_callback,
    handle_worker_conversation_action as conversation_handle_worker_action,
    TelegramConversationRuntime,
)
from app.channels.telegram.pending import (
    approve_pending as pending_approve_pending,
    handle_pending_callback as pending_handle_callback,
    handle_recovery_action as pending_handle_recovery_action,
    handle_recovery_callback as pending_handle_recovery_callback,
    handle_worker_pending_action as pending_handle_worker_action,
    reject_pending as pending_reject_pending,
    retry_allow_pending as pending_retry_allow_pending,
    retry_skip_pending as pending_retry_skip_pending,
    TelegramPendingRuntime,
)
from app.runtime import composition
from app.runtime.inbound_types import InboundUser
from app.runtime.dispatch import RuntimeDispatchRuntime
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    ExecutionSurfaceContext,
    RequestExecutionOutcome,
)
from app.workflows.execution.requests import (
    check_prompt_size_cross_chat as execution_check_prompt_size_cross_chat,
    execute_request as execution_execute_request,
    prompt_weight as execution_prompt_weight,
    request_approval as execution_request_approval,
)
from app.runtime.inbound_types import (
    InboundAction,
    InboundAttachment,
    InboundEnvelope,
    serialize_inbound,
)
from app.runtime.session_runtime import (
    load_runtime_session,
    resolve_session_context,
    save_runtime_session,
)
from app.runtime.work_admission import (
    admit_fresh_message,
    enqueue_inbound_envelope,
    record_inbound_envelope,
    trust_tier_for_source,
)
from app.credential_validation import validate_credential
from app.skill_activation_service import get_skill_activation_service
from app.storage import (
    chat_upload_dir,
    is_image_path,
    resolve_allowed_path,
    session_exists,
    list_sessions,
)
from app.ratelimit import RateLimiter
from app.summarize import export_chat_history, load_raw, save_raw
from app import work_queue
from app.workflows.recovery.results import TransportStateCorruption
from app.worker import poll_interval_for_runtime
from app.workflows.delegation.coordination import build_delegation_plan, finalize_resumed_delegation

log = logging.getLogger(__name__)

CHAT_LOCKS: dict[int | str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _run_result_was_interrupted(returncode: int) -> bool:
    """Return True for subprocess exits caused by a signal.

    Any negative return code means the child was killed by a signal:
    SIGTERM (-15) from systemd stop, SIGKILL (-9) from forced kill,
    SIGINT (-2) from Ctrl+C, etc.  These should be replayed after
    restart instead of being surfaced as provider errors.
    """
    return returncode < 0


# Maximum chars of raw error text to show if summarization fails.
_ERROR_DISPLAY_LIMIT = 1500

_ERROR_SUMMARY_PROMPT = """\
Summarize the following provider error for a Telegram chat user.

Rules:
- Keep it under 400 characters.
- Preserve: error type, root cause, actionable next step if obvious.
- Drop: full stack traces, repeated lines, internal paths.
- If the error is empty or uninformative, say so.
- Output plain text, no markdown headers.

Error (rc={rc}):
{text}
"""


async def _format_provider_error(raw_text: str, returncode: int) -> str:
    """Format a provider error for Telegram display.

    Tries to summarize long errors via the provider CLI.  If the provider
    is down or fails, falls back to a truncated version.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return f"Provider exited with code {returncode} (no output)."

    # Short errors don't need summarization
    if len(raw_text) <= _ERROR_DISPLAY_LIMIT:
        return html.escape(raw_text)

    # Try to summarize via a lightweight provider call
    proc = None
    try:
        from app.summarize import _clean_env
        prompt = _ERROR_SUMMARY_PROMPT.format(rc=returncode, text=raw_text[:4000])
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--model", "claude-haiku-4-5-20251001",
            "--output-format", "text",
            "--", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        if proc.returncode == 0:
            summary = stdout.decode("utf-8", errors="replace").strip()
            if summary:
                return html.escape(summary)
    except Exception:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

    # Fallback: truncate intelligently — show beginning and end
    head = raw_text[:800]
    tail = raw_text[-400:]
    truncated = f"{head}\n\n[…truncated…]\n\n{tail}"
    return html.escape(truncated)


class ClaimBlocked(Exception):
    """Raised by _chat_lock when a worker already holds a claimed item for this chat.

    The handler must not run — its work item stays queued and will be
    picked up by the worker_loop after the current item completes.
    """


@contextlib.asynccontextmanager
async def _chat_lock(chat_id: int | str, *, message=None, query=None, update_id: int | None = None,
                     worker_item: dict | None = None, supersede_recovery: bool = False):
    """Acquire the per-chat lock with visible queued feedback.

    If the lock is already held (another request is in-flight), send a
    visible acknowledgment before blocking.  Only handlers that actually
    serialize on the lock should use this — lightweight read-only commands
    like /session should use the lock directly or not at all.

    When ``update_id`` is provided, claim the specific work item for that
    update rather than the oldest queued item.  This prevents a stale
    recovered item from being silently marked done when a fresh update
    acquires the lock first.

    When ``worker_item`` is provided (worker_dispatch path), the item was
    already claimed externally by ``claim_next_any``.  The lock is acquired
    for in-memory serialization but no claiming or completion is done —
    worker_loop owns the item lifecycle.

    Raises ``ClaimBlocked`` if ``claim_for_update`` returns None because
    another item for this chat is already claimed (worker/live-handler
    race).  The caller must bail out without running the handler body.

    Yields ``True`` if queued feedback was sent (callback answer slot
    consumed), ``False`` otherwise.  Callback handlers should skip their
    own ``query.answer()`` when the yielded value is ``True``.
    """
    data_dir = _state().config.data_dir
    conversation_key = _conversation_key(chat_id)
    if _state().config.runtime_mode == "shared" and worker_item is not None:
        work_queue.supersede_pending_recovery(data_dir, conversation_key)
        try:
            yield False
        except work_queue.LeaveClaimed:
            raise
        return

    lock = CHAT_LOCKS[chat_id]
    sent_feedback = False
    # In-memory lock is the primary contention signal.  The durable check
    # only matters on restart recovery (lock not held but stale work items exist).
    is_busy = lock.locked()
    if is_busy:
        sent_feedback = True
        if message is not None:
            await message.reply_text(
                f"<i>{_msg.queue_busy()}</i>",
                parse_mode=ParseMode.HTML)
        elif query is not None:
            await query.answer(_msg.queue_busy())
    async with lock:
        # Worker path: item already claimed externally; supersede any pending_recovery for this chat.
        if worker_item is not None:
            work_queue.supersede_pending_recovery(data_dir, conversation_key)
            try:
                yield sent_feedback
            except work_queue.LeaveClaimed:
                raise  # let worker_dispatch handle it
            return

        # Live handler path: claim the durable work item.
        try:
            effective_update_id = update_id if update_id is not None else _current_update_id.get()
            if effective_update_id is not None:
                item = work_queue.claim_for_update(
                    data_dir,
                    conversation_key,
                    _event_key(effective_update_id),
                    _state().boot_id,
                )
            else:
                item = work_queue.claim_next(data_dir, conversation_key, _state().boot_id)
        except TransportStateCorruption as e:
            log.exception(
                "Transport state corruption in claim path for conversation %s: %s",
                conversation_key,
                e,
            )
            if message is not None:
                await message.reply_text(
                    f"<i>{_msg.generic_error_try_again()}</i>",
                    parse_mode=ParseMode.HTML,
                )
            elif query is not None:
                await query.answer(_msg.generic_error_try_again(), show_alert=True)
            return

        # If claim failed and the reason is a concurrent claimed item (worker
        # claimed outside the lock), the handler must not run.  The work item
        # stays queued for worker_loop to pick up after its current item.
        if item is None and effective_update_id is not None:
            if work_queue.has_claimed_for_chat(data_dir, conversation_key):
                raise ClaimBlocked(conversation_key)

        item_id = item["id"] if item else None
        claimed_update_id = telegram_numeric_id(item["event_id"]) if item else None
        # Fresh message supersedes any pending_recovery for this chat.
        # Only handle_message passes supersede_recovery=True; commands
        # like /approval and /new must NOT supersede recovery items.
        if item_id and supersede_recovery:
            work_queue.supersede_pending_recovery(data_dir, conversation_key)
        try:
            yield sent_feedback
        except work_queue.LeaveClaimed:
            if item_id:
                log.info("Leaving work item %s claimed for restart recovery", item_id)
                return
            raise
        except Exception:
            # Mark as failed on unhandled exception
            if item_id:
                work_queue.fail_work_item(data_dir, item_id, error="handler_exception")
                if claimed_update_id:
                    _pending_work_items.pop(claimed_update_id, None)
            raise
        else:
            if item_id:
                work_queue.complete_work_item(data_dir, item_id)
                if claimed_update_id:
                    _pending_work_items.pop(claimed_update_id, None)


# Current update_id for the active handler — set by decorators so _chat_lock
# can claim the correct work item even in callback handlers that don't pass
# update_id explicitly.
_current_update_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_current_update_id", default=None,
)

# Tracks work item ID per update_id so each handler can complete its own item.
# Keyed by update_id (not chat_id) to prevent same-chat overlap corruption.
_pending_work_items: dict[int, str] = {}  # update_id -> work_item_id


def _state():
    return get_channel_state()


def _conversation_runtime() -> TelegramConversationRuntime:
    return TelegramConversationRuntime(
        state=_state(),
        cancellations=get_cancellation_registry(),
        chat_lock=_chat_lock,
        edit_or_reply_text=_edit_or_reply_text,
    )


def _runtime_skill_runtime() -> TelegramRuntimeSkillsRuntime:
    return TelegramRuntimeSkillsRuntime(
        state=_state(),
        chat_lock=_chat_lock,
        validate_credential=validate_credential,
        check_prompt_size_cross_chat=_check_prompt_size_cross_chat,
    )


def _pending_runtime() -> TelegramPendingRuntime:
    return TelegramPendingRuntime(
        state=_state(),
        chat_lock=_chat_lock,
        edit_or_reply_text=_edit_or_reply_text,
        execute_request=execute_request,
        request_approval=request_approval,
        build_user_prompt=build_user_prompt,
    )


def _dispatch_runtime() -> RuntimeDispatchRuntime:
    return RuntimeDispatchRuntime(
        config=_state().config,
        provider=_state().provider,
        boot_id=_state().boot_id,
        cancellations=get_cancellation_registry(),
        progress_factory=TelegramProgress,
        keep_typing=keep_typing,
        heartbeat=_heartbeat,
        format_provider_error=_format_provider_error,
        run_result_was_interrupted=_run_result_was_interrupted,
    )


def _execution_surface_context(message, chat_id: int | str) -> ExecutionSurfaceContext:
    conversation_ref = ""
    routed_task_id = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "channel_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
        routed_task_id = getattr(message, "routed_task_id", "")
    elif _state().config.agent_mode == "registry" and isinstance(chat_id, int):
        conversation_ref = telegram_conversation_ref(_state().config, _telegram_chat_id(chat_id))
    channel_name = getattr(getattr(message, "capabilities", None), "channel_name", "telegram")
    if conversation_ref and channel_name != "registry":
        async def timeline_callback(html_text: str, force: bool = False) -> None:
            await _progress_timeline_callback(
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )

        return ExecutionSurfaceContext(
            conversation_ref=conversation_ref,
            routed_task_id=routed_task_id,
            timeline_callback=timeline_callback,
        )
    return ExecutionSurfaceContext(
        conversation_ref=conversation_ref,
        routed_task_id=routed_task_id,
        timeline_callback=None,
    )


async def _show_foreign_setup(message, foreign_setup) -> None:
    rendered = telegram_presenters.conversation_foreign_setup_message(foreign_setup)
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _show_setup_prompt(message, missing_skill: str, first_requirement: dict[str, object]) -> None:
    rendered = telegram_presenters.ingress_setup_prompt_message(missing_skill, first_requirement)
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _send_retry_prompt(message, denials: tuple[dict[str, Any], ...]) -> None:
    rendered = telegram_presenters.retry_prompt(denials)
    await message.chat.send_message(rendered.text, **rendered.kwargs())


async def _send_approval_prompt(message) -> None:
    rendered = telegram_presenters.approval_prompt()
    await message.chat.send_message(rendered.text, **rendered.kwargs())


def _execution_runtime() -> ExecutionRuntime:
    return ExecutionRuntime(
        dispatch=_dispatch_runtime(),
        build_surface_context=_execution_surface_context,
        show_foreign_setup=_show_foreign_setup,
        show_setup_prompt=_show_setup_prompt,
        send_retry_prompt=_send_retry_prompt,
        send_approval_prompt=_send_approval_prompt,
        send_formatted_reply=send_formatted_reply,
        send_directed_artifacts=send_directed_artifacts,
        send_compact_reply=_send_compact_reply,
        propose_delegation_plan=_propose_delegation_plan,
    )


def _delegation_runtime():
    state = _state()
    return build_delegation_runtime(
        config=state.config,
        provider_name=state.provider.name,
        provider_state_factory=state.provider.new_provider_state,
    )


def _dedup_update(update: Update, kind: str = "unknown", payload: str = "{}") -> bool:
    """Return True if this update_id was already processed (duplicate).

    Atomically records the update AND enqueues a work item in a single
    SQLite transaction.  The item is created as ``claimed`` (owned by
    the inline handler via the current boot id so the background worker cannot
    steal it before the handler finishes.
    """
    uid = update.update_id
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    state = _state()
    data_dir = state.config.data_dir
    is_new, item_id = work_queue.record_and_enqueue(
        data_dir,
        _event_key(uid),
        _conversation_key(chat_id),
        _actor_key(user_id),
        kind,
        payload=payload,
        worker_id=state.boot_id,
    )
    if not is_new:
        log.debug("Skipping duplicate update_id %d", uid)
        return True
    _pending_work_items[uid] = item_id
    return False


def _complete_pending_work_item(update_id: int, state: str = "done", error: str | None = None) -> None:
    """Complete the pending work item for an update if _chat_lock hasn't already."""
    item_id = _pending_work_items.pop(update_id, None)
    if item_id:
        try:
            if state == "done":
                work_queue.complete_work_item(_state().config.data_dir, item_id)
            else:
                work_queue.fail_work_item(_state().config.data_dir, item_id, error=error or "failed")
        except Exception:
            log.debug("Work item %s already completed", item_id)


def _conversation_key(chat_id: int | str) -> str:
    return parse_conversation_key(chat_id)


def _actor_key(user_id: int | str) -> str:
    if isinstance(user_id, str):
        return parse_actor_key(user_id)
    return telegram_actor_key(user_id)


def _event_key(update_id: int | str) -> str:
    if isinstance(update_id, str):
        return update_id if ":" in update_id or not update_id.isdigit() else telegram_event_id(update_id)
    return telegram_event_id(update_id)


def _telegram_chat_id(chat_id: int | str) -> int:
    if isinstance(chat_id, int):
        return chat_id
    numeric = telegram_numeric_id(chat_id)
    if numeric is None:
        raise RuntimeError(f"Telegram API requires a Telegram conversation key, got {chat_id!r}")
    return numeric


def _approval_mode_source(session: SessionState) -> str:
    return "chat override" if session.approval_mode_explicit else "instance default"


def _callback_message_id(update: Update) -> int | None:
    query = update.callback_query
    if query is None or query.message is None:
        return None
    return getattr(query.message, "message_id", None)


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
        parsed = _parse_delegation_callback(data)
        if parsed is None:
            return None
        action, chat_id = parsed
        params["target_conversation_key"] = _conversation_key(chat_id)
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


# -- Data classes ----------------------------------------------------------

# Attachment is now InboundAttachment from app.channels.telegram.normalization.
# Alias kept for internal signature compatibility.
Attachment = InboundAttachment


# -- TelegramProgress (rate-limited HTML editor) ---------------------------

class TelegramProgress:
    def __init__(self, message, config: BotConfig, *, timeline_callback=None) -> None:
        self.message = message
        self.last_text = ""
        self.last_update = 0.0
        self._interval = config.stream_update_interval_seconds
        self._content_delivered = False
        self._timeline_callback = timeline_callback

    async def update(self, html_text: str, *, force: bool = False) -> None:
        html_text = trim_text(html_text, 3500)
        if not html_text or html_text == self.last_text:
            return
        now = time.monotonic()
        # After content_started is set, the first real (non-forced) update
        # must bypass rate limiting so the user sees reply text instead of a
        # stale tool/heartbeat message.
        cs = getattr(self, "content_started", None)
        if not force and not self._content_delivered and cs and cs.is_set():
            force = True
        if not force and now - self.last_update < self._interval:
            return
        try:
            await self.message.edit_text(html_text, parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.debug("progress update failed: %s", exc)
                return
        self.last_text = html_text
        self.last_update = now
        if cs and cs.is_set():
            self._content_delivered = True
        if self._timeline_callback is not None:
            try:
                await self._timeline_callback(html_text, force=force)
            except Exception as exc:
                log.debug("registry timeline callback failed: %s", exc)


async def _progress_timeline_callback(conversation_ref: str, routed_task_id: str, html_text: str, *, force: bool = False) -> None:
    del force
    await publish_timeline_event(
        _state().config,
        conversation_ref=conversation_ref,
        kind="progress",
        title="Progress",
        body=html_text,
        metadata={"routed_task_id": routed_task_id} if routed_task_id else {},
    )


def _maybe_fire_webhook(cfg: BotConfig, chat_id: int, conversation_ref: str, outcome: RequestExecutionOutcome | None) -> None:
    """Schedule a non-blocking completion webhook for terminal outcomes."""
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


# -- Auth ------------------------------------------------------------------

def is_allowed(user) -> bool:
    cfg = _state().config
    inbound = user if isinstance(user, InboundUser) else normalize_user(user)
    if inbound is None:
        return False
    override = work_queue.get_user_access(cfg.data_dir, inbound.id)
    return access.is_allowed_user_with_override(cfg, inbound, override)


def is_admin(user) -> bool:
    """Check if user is an admin (can import/uninstall/update runtime skills)."""
    inbound = user if isinstance(user, InboundUser) else normalize_user(user)
    return access.is_admin_user(_state().config, inbound)


def is_public_user(user) -> bool:
    """Check if user is a public (untrusted) user.

    A user is public when allow_open is true AND the user is not in
    any allowed-user set.  Returns False if allow_open is off (the user
    wouldn't have passed is_allowed at all).
    """
    inbound = user if isinstance(user, InboundUser) else normalize_user(user)
    return access.is_public_user(_state().config, inbound)


def _trust_tier(user) -> str:
    """Resolve the trust tier for a user: 'trusted' or 'public'."""
    inbound = user if isinstance(user, InboundUser) else normalize_user(user)
    return access.trust_tier(_state().config, inbound)


async def _public_guard(event, update: Update) -> bool:
    """Return True (and send denial) if the user is public. Use at top of restricted commands."""
    if is_public_user(event.user):
        await update.effective_message.reply_text(_msg.trust_command_not_available_public())
        return True
    return False


def _command_handler(fn):
    """Decorator: normalize → dedup (with payload) → is_allowed gate → call fn(event, update, context)."""
    import functools
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        event = normalize_command(update, context)
        payload = serialize_inbound(event) if event else "{}"
        if _dedup_update(update, kind="command", payload=payload):
            return
        uid = update.update_id
        if event is None or not is_allowed(event.user):
            _complete_pending_work_item(uid)
            return
        token = _current_update_id.set(uid)
        try:
            await fn(event, update, context)
        except ClaimBlocked:
            # Worker owns this chat — item stays queued for worker_loop.
            _pending_work_items.pop(uid, None)
            return
        except Exception:
            _complete_pending_work_item(uid, state="failed")
            raise
        else:
            _complete_pending_work_item(uid)
        finally:
            _current_update_id.reset(token)
    return wrapper


def _callback_handler(fn):
    """Decorator: normalize → dedup (with payload) → is_allowed gate → call fn(event, query).

    Does NOT call query.answer() — handlers control their own answer semantics
    (some need alerts, some need silent acks, some answer conditionally).
    """
    import functools
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        event = normalize_callback(update)
        payload = serialize_inbound(event) if event else "{}"
        if _dedup_update(update, kind="callback", payload=payload):
            return
        uid = update.update_id
        if event is None:
            _complete_pending_work_item(uid)
            return
        query = update.callback_query
        if not is_allowed(event.user):
            await query.answer(_msg.trust_not_authorized(), show_alert=True)
            _complete_pending_work_item(uid)
            return
        token = _current_update_id.set(uid)
        try:
            await fn(event, query)
        except ClaimBlocked:
            _pending_work_items.pop(uid, None)
            try:
                await query.answer(_msg.queue_busy())
            except Exception:
                pass
            return
        except Exception:
            _complete_pending_work_item(uid, state="failed")
            raise
        else:
            _complete_pending_work_item(uid)
        finally:
            _current_update_id.reset(token)
    return wrapper


def _check_prompt_size_cross_chat(data_dir: Path, skill_name: str) -> list[str]:
    """Telegram-side helper for prompt-size impact warnings."""
    return execution_check_prompt_size_cross_chat(
        data_dir,
        skill_name,
        runtime=_execution_runtime(),
    )


# -- Project helpers -------------------------------------------------------

def _resolve_project(session: SessionState):
    """Return ProjectBinding for the session's bound project, or None."""
    project_id = session.project_id
    if not project_id:
        return None
    for proj in _state().config.projects:
        if proj.name == project_id:
            return proj
    return None


def _resolve_context(session: SessionState, trust_tier: str = "trusted") -> ResolvedExecutionContext:
    """Build the single authoritative execution identity from session + config."""
    return resolve_session_context(
        session,
        config=_state().config,
        provider_name=_state().provider.name,
        trust_tier=trust_tier,
    )


def _settings_model_profile_state(
    session: SessionState,
    cfg: BotConfig,
    trust_tier: str,
    effective_model: str,
) -> tuple[list[str], str]:
    state = composition.workflows().conversation.settings.model_profile_state(
        session,
        cfg,
        trust_tier,
        effective_model,
    )
    return (list(state.available_profiles), state.current_profile)


# -- Helpers ---------------------------------------------------------------

def _allowed_roots(chat_id: int | str, resolved: ResolvedExecutionContext | None = None) -> list[Path]:
    """Return path roots this chat is allowed to access.

    Uses the resolved execution context for working_dir and extra_dirs,
    so public users get public roots and project-bound chats get project roots.
    Falls back to config defaults only when no resolved context is available.
    """
    cfg = _state().config
    if resolved:
        roots: list[Path] = [Path(resolved.working_dir)]
        roots.extend(Path(d) for d in resolved.base_extra_dirs)
    else:
        roots = [cfg.working_dir]
        roots.extend(cfg.extra_dirs)
    roots.append(chat_upload_dir(cfg.data_dir, _conversation_key(chat_id)))
    return [r.resolve() for r in roots]


def build_user_prompt(text: str, attachments: list[InboundAttachment]) -> tuple[str, list[str]]:
    prompt = text.strip() or "Inspect the attached files or images and help with them."
    image_paths: list[str] = []
    if attachments:
        lines = []
        for a in attachments:
            kind = "image" if a.is_image else "file"
            lines.append(f"- {a.path} ({kind}, original name: {a.original_name})")
            if a.is_image:
                image_paths.append(str(a.path))
        prompt = f"{prompt}\n\nAttached local files:\n" + "\n".join(lines)
    return prompt, image_paths



async def send_formatted_reply(message, text: str) -> None:
    for rendered in telegram_presenters.formatted_reply_messages(text):
        try:
            await message.reply_text(rendered.text, **rendered.kwargs())
        except BadRequest:
            await message.reply_text(telegram_presenters.formatted_reply_fallback_text(rendered.text))


async def _edit_or_reply_text(message, text: str, **kwargs) -> None:
    if getattr(message, "_target_message_id", None) is not None and hasattr(message, "edit_text"):
        await message.edit_text(text, **kwargs)
        return
    caps = getattr(message, "capabilities", None)
    if getattr(caps, "channel_name", "") == "telegram":
        await message.reply_text(text, **kwargs)
        return
    if hasattr(message, "edit_text"):
        await message.edit_text(text, **kwargs)
        return
    await message.reply_text(text, **kwargs)

async def _send_compact_reply(message, text: str, chat_id: int, slot: int) -> None:
    blockquote_rendered = telegram_presenters.compact_reply_blockquote_message(text)
    if blockquote_rendered is not None:
        try:
            await message.reply_text(blockquote_rendered.text, **blockquote_rendered.kwargs())
            return
        except BadRequest:
            pass
    if "\n" in text:
        try:
            rendered = telegram_presenters.compact_reply_button_message(text, chat_id, slot)
            await message.reply_text(rendered.text, **rendered.kwargs())
            return
        except BadRequest:
            pass
    await send_formatted_reply(message, text)


async def send_path_to_chat(message, path: Path, *, force_image: bool | None = None) -> None:
    should_image = force_image if force_image is not None else is_image_path(path)
    with path.open("rb") as f:
        if should_image:
            await message.reply_photo(photo=f)
        else:
            await message.reply_document(document=f)


async def send_directed_artifacts(
    chat_id: int, message, directives: list[tuple[str, str]],
    resolved_ctx: ResolvedExecutionContext | None = None,
) -> None:
    for dtype, raw_path in directives:
        allowed_path = resolve_allowed_path(raw_path, _allowed_roots(chat_id, resolved_ctx))
        if not allowed_path:
            rendered = telegram_presenters.cannot_send_path_message(raw_path)
            await message.reply_text(rendered.text, **rendered.kwargs())
            continue
        await send_path_to_chat(message, allowed_path, force_image=(dtype == "IMAGE"))


def _delegation_keyboard(chat_id: int):
    return telegram_presenters.delegation_reply_markup(chat_id)


class _DelegationCallbackEditableHandle:
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del text, kwargs
        return None

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs
        return None


class _DelegationCallbackSurface:
    def __init__(self, query) -> None:
        self._query = query

    async def send_text(self, text: str, **kwargs: Any) -> _DelegationCallbackEditableHandle:
        await self._query.edit_message_text(text, **kwargs)
        return _DelegationCallbackEditableHandle()


async def _publish_delegation_proposed_event(message, delegation: PendingDelegation) -> None:
    body = "\n".join(
        [
            "Delegation plan:",
            *[
                f"{index}. {task.title or task.routed_task_id} -> {task.target_agent_id or 'unassigned'}"
                for index, task in enumerate(delegation.tasks, start=1)
            ],
        ]
    )
    event = TimelineEvent(
        event_id=f"delegation-proposed:{delegation.conversation_ref}:{int(delegation.created_at * 1000)}",
        conversation_id=delegation.conversation_ref,
        kind="delegation_proposed",
        title="Delegation plan proposed",
        body=body,
        status=delegation.status,
    )
    publisher = getattr(message, "publish_timeline", None)
    if callable(publisher):
        await publisher(event)
        return
    await publish_timeline_event(
        _state().config,
        conversation_ref=delegation.conversation_ref,
        kind=event.kind,
        title=event.title,
        body=event.body,
        status=event.status,
        event_id=event.event_id,
    )


async def _propose_delegation_plan(
    chat_id: int,
    message,
    session: SessionState,
    *,
    conversation_ref: str,
    result,
) -> RequestExecutionOutcome:
    title = result.delegation_title.strip() or summarize_text(result.text) or "Delegation plan"
    delegation = build_delegation_plan(
        conversation_ref,
        title,
        result.delegation_resume_instruction,
        list(result.delegation_tasks),
    )
    session.pending_delegation = delegation
    _save(chat_id, session)
    await _publish_delegation_proposed_event(message, delegation)

    send_plan = getattr(message, "send_text", None) or getattr(message, "reply_text")
    rendered = telegram_presenters.delegation_plan_message(delegation)
    await send_plan(
        rendered.text,
        parse_mode=rendered.parse_mode,
        reply_markup=_delegation_keyboard(chat_id),
    )
    return RequestExecutionOutcome(status="delegation_proposed")


async def keep_typing(chat) -> None:
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(_state().config.typing_interval_seconds)
    except asyncio.CancelledError:
        pass


# Heartbeat cadence: first beat at 5s, then every 10s.
_HEARTBEAT_FIRST = 5.0
_HEARTBEAT_SUBSEQUENT = 10.0


async def _heartbeat(progress, content_started: asyncio.Event) -> None:
    """Show elapsed time on the progress message while idle.

    Stops firing once *content_started* is set (meaning the provider has
    begun streaming real reply text).  Only fires after a period of visible
    silence — if the provider recently pushed a tool/command status update,
    the heartbeat waits until that update goes stale before overwriting it.
    Uses the same background-task lifecycle pattern as keep_typing().
    """
    try:
        start = time.monotonic()
        await asyncio.sleep(_HEARTBEAT_FIRST)
        while not content_started.is_set():
            # Check if a recent progress update was made — don't overwrite it
            last = getattr(progress, "last_update", 0.0)
            since_last = time.monotonic() - last if last else _HEARTBEAT_FIRST
            if since_last < _HEARTBEAT_SUBSEQUENT:
                # Recent update exists; wait for the remaining silence period
                await asyncio.sleep(_HEARTBEAT_SUBSEQUENT - since_last)
                continue
            elapsed = int(time.monotonic() - start)
            await progress.update(_msg.progress_still_working(elapsed), force=True)
            await asyncio.sleep(_HEARTBEAT_SUBSEQUENT)
    except asyncio.CancelledError:
        pass


def _load(chat_id: int) -> SessionState:
    cfg = _state().config
    session = load_runtime_session(
        cfg.data_dir,
        _conversation_key(chat_id),
        provider_name=_state().provider.name,
        provider_state_factory=_state().provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    # Self-heal: prune active skills that no longer resolve through the content catalog.
    if get_skill_activation_service().normalize(session):
        _save(chat_id, session)
    return session


def _save(chat_id: int, session: SessionState) -> None:
    save_runtime_session(_state().config.data_dir, _conversation_key(chat_id), session)


# -- Core execution --------------------------------------------------------

async def execute_request(
    chat_id: int | str,
    prompt: str,
    image_paths: list[str],
    message,
    extra_dirs: list[str] | None = None,
    request_user_id: int | str = "",
    skip_permissions: bool = False,
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
) -> RequestExecutionOutcome:
    return await execution_execute_request(
        chat_id,
        prompt,
        image_paths,
        message,
        extra_dirs=extra_dirs,
        request_user_id=request_user_id,
        skip_permissions=skip_permissions,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
        runtime=_execution_runtime(),
    )


async def request_approval(
    chat_id: int | str,
    prompt: str,
    image_paths: list[str],
    attachments: list[Attachment],
    message,
    request_user_id: int | str = "",
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
) -> None:
    await execution_request_approval(
        chat_id,
        prompt,
        image_paths,
        attachments,
        message,
        request_user_id=request_user_id,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
        runtime=_execution_runtime(),
    )


async def approve_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    await pending_approve_pending(
        chat_id,
        message,
        cancel_event=cancel_event,
        runtime=_pending_runtime(),
    )


async def reject_pending(chat_id: int, message) -> None:
    await pending_reject_pending(chat_id, message, runtime=_pending_runtime())


async def retry_skip_pending(chat_id: int, message) -> None:
    await pending_retry_skip_pending(chat_id, message, runtime=_pending_runtime())


async def retry_allow_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    await pending_retry_allow_pending(
        chat_id,
        message,
        cancel_event=cancel_event,
        runtime=_pending_runtime(),
    )


def _parse_delegation_callback(data: str) -> tuple[str, int] | None:
    parts = (data or "").split(":", 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


async def _handle_delegation_approve(chat_id: int, query) -> None:
    conversation_ref = telegram_conversation_ref(_state().config, chat_id)
    await handle_surface_delegation_approve(
        chat_id,
        conversation_ref,
        _DelegationCallbackSurface(query),
        runtime=_delegation_runtime(),
        retry_markup=_delegation_keyboard(chat_id),
    )


async def _handle_delegation_cancel(chat_id: int, query) -> None:
    conversation_ref = telegram_conversation_ref(_state().config, chat_id)
    await handle_surface_delegation_cancel(
        chat_id,
        conversation_ref,
        _DelegationCallbackSurface(query),
        runtime=_delegation_runtime(),
    )


# -- Command handlers ------------------------------------------------------

def _help_command_lines(user) -> list[str]:
    """Build the main help command list for the given user (trust- and admin-aware).

    Public users do not see /project or /policy (blocked by _public_guard in handlers).
    Non-admin users do not see /admin sessions.
    """
    lines = [
        "/new — start a fresh conversation",
        "/skills — browse and activate skills (e.g. <code>/skills list</code>)",
        "/guidance — inspect and manage provider guidance",
        "/role &lt;text&gt; — set the AI's persona (e.g. <code>/role Python expert</code>)",
        "/approval on|off — show a plan before executing, or run immediately",
        "/approve / /reject — act on a pending plan",
        "/cancel — cancel a running task, credential setup, or a pending request",
        "/clear_credentials — remove your stored credentials",
        "/send &lt;path&gt; — retrieve a file from the server",
        "/compact on|off — toggle short/full answers",
    ]
    if _state().config.model_profiles:
        lines.append("/model — switch model profile (fast/balanced/best)")
    if _state().config.agent_mode == "registry":
        lines.append("/discover — find available specialist bots by role, skill, or tag")
    if not is_public_user(user):
        lines.append("/policy inspect|edit — set file access policy")
    lines.extend([
        "/settings — view and change chat settings",
    ])
    if not is_public_user(user) and _state().config.projects:
        lines.append("/project — show or change project binding")
    lines.extend([
        "/session — show current session info",
        "/id — show your Telegram user ID",
        "/doctor — run full app health check (DB, config, Telegram)",
        "/export — download recent conversation history",
    ])
    if is_admin(user):
        lines.append("/admin sessions — session overview (admin only)")
    return lines


def _build_main_help(user) -> str:
    """Build the full main help text for the given user (trust- and admin-aware)."""
    cfg = _state().config
    provider = _state().provider.name.capitalize()
    instance = cfg.instance
    header = (
        "<b>Agent Bot</b> (instance: <code>{instance}</code>, provider: {provider})\n\n"
        "Send a message, photo, or document and the AI will respond.\n\n"
        "<b>Commands:</b>\n"
    ).format(instance=instance, provider=provider)
    command_block = "\n".join(_help_command_lines(user)) + "\n\n"
    # Intentional set of controls (trust-aware: no /project for public).
    control_parts = ["/settings", "/session"]
    if cfg.model_profiles:
        control_parts.append("/model")
    if not is_public_user(user) and cfg.projects:
        control_parts.append("/project")
    controls_line = "Chat options: " + " · ".join(control_parts) + "."
    recovery_line = "Interrupted? Use Run again or Skip on the status message."
    footer = controls_line + "\n" + recovery_line + "\n\nType /help skills, /help approval, or /help credentials for details."
    return header + command_block + footer

HELP_SKILLS = (
    "<b>Skills</b>\n\n"
    "Skills add domain knowledge and tools to the AI.\n\n"
    "/skills list — see all available skills with status\n"
    "/skills add &lt;name&gt; — activate a skill (prompts for credentials if needed)\n"
    "/skills remove &lt;name&gt; — deactivate a skill\n"
    "/skills setup &lt;name&gt; — re-enter credentials for a skill\n"
    "/skills info &lt;name&gt; — view skill details\n"
    "/skills search &lt;query&gt; — search the skill store\n"
    "/skills clear — deactivate all skills\n"
    "/skills create &lt;name&gt; — create a custom draft skill\n"
    "/skills edit &lt;name&gt; &lt;body&gt; — replace the current draft body\n"
    "/skills history &lt;name&gt; — show revision and approval history\n"
    "/skills submit &lt;name&gt; — submit the draft for review\n"
    "/skills approve|reject|publish|archive &lt;name&gt; — lifecycle admin actions\n\n"
    "/guidance preview &lt;provider&gt; — show effective provider guidance\n"
    "/guidance edit|history|submit|approve|reject|publish|archive &lt;provider&gt; — provider guidance lifecycle"
)

HELP_APPROVAL = (
    "<b>Approval Mode</b>\n\n"
    "When approval mode is on, the AI shows a plan before executing. "
    "You review and approve or reject it.\n\n"
    "If a request needs approval, retry, or recovery (e.g. interrupted or blocked), "
    "use the in-chat buttons on the status message — Run again or Skip — no separate command needed.\n\n"
    "/approval on — require approval before execution\n"
    "/approval off — execute immediately\n"
    "/approval status — check current setting\n"
    "/approve — approve the pending plan\n"
    "/reject — reject the pending plan\n"
    "/cancel — cancel a pending request"
)

HELP_CREDENTIALS = (
    "<b>Credentials</b>\n\n"
    "Some skills need API tokens or keys. When you activate such a skill, "
    "the bot asks for each credential in a private message and encrypts it.\n\n"
    "/skills setup &lt;name&gt; — re-enter credentials for a skill\n"
    "/clear_credentials — remove all your stored credentials\n"
    "/clear_credentials &lt;skill&gt; — remove credentials for one skill\n\n"
    "Your credential messages are deleted after capture for safety."
)

_HELP_TOPICS = {
    "skills": HELP_SKILLS,
    "approval": HELP_APPROVAL,
    "credentials": HELP_CREDENTIALS,
}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — always show main help (ignores deep-link payloads)."""
    event = normalize_command(update, context)
    payload = serialize_inbound(event) if event else "{}"
    if _dedup_update(update, kind="command", payload=payload):
        return
    uid = update.update_id
    if event is None or not is_allowed(event.user):
        await update.effective_message.reply_text(_msg.trust_not_authorized())
        _complete_pending_work_item(uid)
        return
    text = _build_main_help(event.user)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
    _complete_pending_work_item(uid)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help [topic] — main help or topic-specific detail."""
    event = normalize_command(update, context)
    payload = serialize_inbound(event) if event else "{}"
    if _dedup_update(update, kind="command", payload=payload):
        return
    uid = update.update_id
    if event is None or not is_allowed(event.user):
        await update.effective_message.reply_text(_msg.trust_not_authorized())
        _complete_pending_work_item(uid)
        return
    args = event.args

    if args:
        topic = args[0].lower()
        topic_text = _HELP_TOPICS.get(topic)
        if topic_text:
            await update.effective_message.reply_text(topic_text, parse_mode=ParseMode.HTML)
            _complete_pending_work_item(uid)
            return
        await update.effective_message.reply_text(
            "Unknown help topic. Try: /help skills, /help approval, or /help credentials."
        )
        _complete_pending_work_item(uid)
        return

    text = _build_main_help(event.user)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
    _complete_pending_work_item(uid)


@_command_handler
async def cmd_new(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_new(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_session(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _load(event.chat_id)
    cfg = _state().config
    trust = _trust_tier(event.user)
    resolved = _resolve_context(session, trust_tier=trust)
    pstate = session.provider_state

    # Show provider-relevant session ID
    if _state().provider.name == "claude":
        sid = pstate.get("session_id", "[none]")
        active = pstate.get("started", False)
        session_line = f"Session: <code>{html.escape(sid[:12])}\u2026</code>\nActive: <code>{active}</code>"
    else:
        tid = pstate.get("thread_id") or "[none yet]"
        session_line = f"Thread: <code>{html.escape(str(tid))}</code>"

    pending = "yes" if session.has_pending else "no"
    role_display = resolved.role or "(default)"
    skills_display = ", ".join(resolved.active_skills) if resolved.active_skills else "(none)"
    approval_mode = session.approval_mode
    approval_source = _approval_mode_source(session)

    # Resolve effective working directory for display
    if resolved.project_id:
        wd_display = f"{resolved.working_dir} (project: {resolved.project_id})"
    else:
        wd_display = resolved.working_dir

    file_policy = resolved.file_policy or "edit"
    _, model_profile = _settings_model_profile_state(
        session, cfg, trust, resolved.effective_model or ""
    )
    model_id = resolved.effective_model or cfg.model or "(default)"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    compact_display = "on" if compact else "off"

    # Prompt weight estimate (chars of system prompt)
    prompt_weight_count = execution_prompt_weight(resolved.role, resolved.active_skills)
    prompt_weight = f"~{prompt_weight_count} chars" if prompt_weight_count else "minimal"

    body = (
        f"Provider: <code>{html.escape(_state().provider.name)}</code>\n"
        f"Instance: <code>{html.escape(cfg.instance)}</code>\n"
        f"Working dir: <code>{html.escape(wd_display)}</code>\n"
        f"File policy: <code>{html.escape(file_policy)}</code>\n"
        f"Model: <code>{html.escape(model_profile)}</code> ({html.escape(model_id)})\n"
        f"Compact: <code>{compact_display}</code>\n"
        f"Prompt weight: <code>{html.escape(prompt_weight)}</code>\n"
        f"{session_line}\n"
        f"Approval mode: <code>{approval_mode}</code> ({approval_source})\n"
        f"Role: <code>{html.escape(role_display)}</code>\n"
        f"Skills: <code>{html.escape(skills_display)}</code>\n"
        f"Pending: <code>{pending}</code>"
    )
    if trust == "public":
        body += "\n\n" + _msg.trust_settings_managed_public()
    cfg = _state().config
    session_cmds = ["/settings"]
    if trust != "public" and cfg.projects:
        session_cmds.append("/project")
    if cfg.model_profiles:
        session_cmds.append("/model")
    if session_cmds:
        if len(session_cmds) == 1:
            cmd_str = session_cmds[0]
        elif len(session_cmds) == 2:
            cmd_str = session_cmds[0] + " or " + session_cmds[1]
        else:
            cmd_str = ", ".join(session_cmds[:-1]) + ", or " + session_cmds[-1]
        body += "\n\n" + "Use " + cmd_str + " to change chat settings."
    await update.effective_message.reply_text(body, parse_mode=ParseMode.HTML)


@_command_handler
async def cmd_approval(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_approval(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_approve(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _chat_lock(event.chat_id, message=update.effective_message, update_id=update.update_id):
        await approve_pending(event.chat_id, update.effective_message)


@_command_handler
async def cmd_reject(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _chat_lock(event.chat_id, message=update.effective_message, update_id=update.update_id):
        await reject_pending(event.chat_id, update.effective_message)


@_command_handler
async def cmd_send(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    if not event.args:
        await update.effective_message.reply_text("Usage: /send <path>")
        return
    raw_path = " ".join(event.args)
    session = _load(event.chat_id)
    resolved_ctx = _resolve_context(session, trust_tier=_trust_tier(event.user))
    resolved = resolve_allowed_path(raw_path, _allowed_roots(event.chat_id, resolved_ctx))
    if not resolved:
        await update.effective_message.reply_text("Path is missing or outside allowed roots.")
        return
    await send_path_to_chat(update.effective_message, resolved)


@_command_handler
async def cmd_id(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = event.user.username or "[none]"
    await update.effective_message.reply_text(
        f"Your user ID: <code>{event.user.id}</code>\n"
        f"Your username: <code>{html.escape(username)}</code>",
        parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_doctor(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import sqlite3
    from app.runtime_health import (
        SessionHealthContext,
        collect_runtime_health_report,
        format_runtime_health_for_doctor,
    )
    try:
        session = _load(event.chat_id)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, RuntimeError):
        session = None
    cfg = _state().config
    session_context = None
    if session is not None:
        resolved = _resolve_context(session, trust_tier=_trust_tier(event.user))
        session_context = SessionHealthContext(
            session=session_to_dict(session),
            user_id=_actor_key(event.user.id),
            resolved_active_skills=tuple(resolved.active_skills),
        )
    report = await collect_runtime_health_report(
        cfg,
        _state().provider,
        caller_is_bot=True,
        session_context=session_context,
    )
    parts: list[str] = []
    for line in format_runtime_health_for_doctor(report):
        if line.startswith("INFO: "):
            parts.append(f"\u2139\ufe0f {html.escape(line[6:])}")
        elif line.startswith("FAIL: "):
            parts.append(f"\u274c {html.escape(line[6:])}")
        elif line.startswith("WARN: "):
            parts.append(f"\u26a0\ufe0f {html.escape(line[6:])}")
        else:
            parts.append(html.escape(line))
    # Prompt weight from resolved execution context (respects trust tier)
    if session is not None:
        resolved = _resolve_context(session, trust_tier=_trust_tier(event.user))
        prompt_weight_count = execution_prompt_weight(resolved.role, resolved.active_skills)
        if prompt_weight_count:
            parts.append(f"Prompt weight: ~{prompt_weight_count} chars")
    if parts:
        await update.effective_message.reply_text(
            "\n".join(parts), parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("\u2705 All checks passed.")


def _discover_usage() -> str:
    return (
        "Usage: /discover <query> [role:<role>] [capability:<capability>] [tag:<tag>] [state:<connected|degraded|standalone|offline>]\n"
        "Example: <code>/discover role:developer capability:python tag:backend schema review</code>"
    )


def _parse_discovery_query(
    args: tuple[str, ...],
    *,
    exclude_agent_id: str = "",
) -> tuple[AgentDiscoveryQuery | None, str | None]:
    role = ""
    capabilities: list[str] = []
    tags: list[str] = []
    required_state = "connected"
    free_text_parts: list[str] = []
    for token in args:
        key = ""
        value = ""
        if ":" in token:
            key, value = token.split(":", 1)
        elif "=" in token:
            key, value = token.split("=", 1)
        else:
            free_text_parts.append(token)
            continue
        key = key.strip().lower()
        value = value.strip()
        if not value:
            free_text_parts.append(token)
            continue
        if key == "role":
            role = value
        elif key in {"capability", "capabilities", "skill", "skills"}:
            capabilities.extend(part.strip() for part in value.split(",") if part.strip())
        elif key in {"tag", "tags"}:
            tags.extend(part.strip() for part in value.split(",") if part.strip())
        elif key == "state":
            required_state = value.lower()
        else:
            free_text_parts.append(token)
    if required_state not in {"connected", "degraded", "standalone", "offline"}:
        return None, _discover_usage()
    if not role and not capabilities and not tags and not free_text_parts:
        return None, _discover_usage()
    return (
        AgentDiscoveryQuery(
            role=role,
            capabilities=tuple(capabilities),
            tags=tuple(tags),
            free_text=" ".join(free_text_parts).strip(),
            exclude_agent_ids=(exclude_agent_id,) if exclude_agent_id else (),
            required_state=required_state,
        ),
        None,
    )


def _format_discovery_results(agents: list[dict[str, Any]]) -> str:
    if not agents:
        return "No matching agents found."
    lines = ["<b>Matching agents</b>"]
    for agent in agents[:8]:
        display_name = html.escape(
            agent.get("display_name") or agent.get("slug") or agent.get("agent_id") or "Unnamed agent"
        )
        role = html.escape(agent.get("role") or "(unspecified)")
        state = html.escape(agent.get("connectivity_state") or "unknown")
        current_capacity = int(agent.get("current_capacity", 0) or 0)
        max_capacity = int(agent.get("max_capacity", 1) or 1)
        lines.append(f"\n<b>{display_name}</b> — <code>{role}</code>")
        lines.append(
            f"State: <code>{state}</code> · Capacity: <code>{current_capacity}/{max_capacity}</code>"
        )
        capabilities = [str(capability) for capability in agent.get("capabilities", agent.get("skills", [])) if capability]
        if capabilities:
            lines.append(f"Capabilities: <code>{html.escape(', '.join(capabilities))}</code>")
        tags = [str(tag) for tag in agent.get("tags", []) if tag]
        if tags:
            lines.append(f"Tags: <code>{html.escape(', '.join(tags))}</code>")
        description = str(agent.get("description", "") or "").strip()
        if description:
            lines.append(html.escape(description))
    if len(agents) > 8:
        lines.append(f"\nShowing first {8} of {len(agents)} matches.")
    return "\n".join(lines)


@_command_handler
async def cmd_discover(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    cfg = _state().config
    if cfg.agent_mode == "standalone":
        await update.effective_message.reply_text(
            "Agent discovery is unavailable in standalone mode.",
        )
        return
    state = load_agent_runtime_state(cfg.data_dir)
    if state.connectivity_state != "connected":
        detail = f" Last registry error: {state.last_error}" if state.last_error else ""
        await update.effective_message.reply_text(
            "Agent discovery is unavailable because registry connectivity is degraded." + detail
        )
        return
    query, error = _parse_discovery_query(event.args, exclude_agent_id=state.agent_id)
    if error is not None or query is None:
        await update.effective_message.reply_text(error or _discover_usage(), parse_mode=ParseMode.HTML)
        return
    client = registry_client(cfg)
    if client is None:
        await update.effective_message.reply_text(
            "Agent discovery is unavailable because this bot has not finished registry enrollment."
        )
        return
    try:
        agents = await client.search(query)
    except RegistryClientError as exc:
        await update.effective_message.reply_text(
            f"Agent discovery failed: {html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.effective_message.reply_text(
        _format_discovery_results(agents),
        parse_mode=ParseMode.HTML,
    )



@_command_handler
async def cmd_export(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _state().config

    history = export_chat_history(cfg.data_dir, _conversation_key(chat_id))
    if not history:
        await update.effective_message.reply_text(_msg.no_conversation_to_export())
        return

    # Add session metadata header — use resolved context for user-visible data
    session = _load(chat_id)
    trust = _trust_tier(update.effective_user)
    resolved = _resolve_context(session, trust_tier=trust)
    skills = resolved.active_skills
    header_lines = [
        f"Chat ID: {chat_id}",
        f"Provider: {session.provider}",
        f"Approval mode: {session.approval_mode}",
        f"Active skills: {', '.join(skills) if skills else 'none'}",
        f"Created: {(session.created_at or 'unknown')[:19]}",
        "",
        "Note: This export contains up to 50 recent turns — only successful",
        "model responses and approval plans. Denied, timed-out, or failed",
        "requests, command replies, and older history are not captured.",
        "",
        "=" * 40,
        "",
    ]
    full_text = "\n".join(header_lines) + history

    # Send as document
    import io
    doc = io.BytesIO(full_text.encode("utf-8"))
    doc.name = f"chat_{chat_id}_export.txt"
    await update.effective_message.reply_document(document=doc)


@_command_handler
async def cmd_admin(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(event.user):
        await update.effective_message.reply_text(_msg.admin_required())
        return

    args = event.args
    sub = args[0].lower() if args else ""

    if sub != "sessions":
        await update.effective_message.reply_text(
            "Usage: /admin sessions [conversation_key]")
        return

    cfg = _state().config
    sessions = list_sessions(cfg.data_dir)

    if not sessions:
        await update.effective_message.reply_text(_msg.no_sessions_found())
        return

    # Filter stale active_skills that no longer resolve
    for s in sessions:
        s["active_skills"] = composition.workflows().runtime_skills.catalog.filter_resolvable(
            s["active_skills"]
        )

    # Detail view for a specific conversation
    if len(args) >= 2:
        target_key = parse_conversation_key(args[1])
        if not target_key:
            await update.effective_message.reply_text("Invalid conversation key.")
            return
        match = next((s for s in sessions if s["conversation_key"] == target_key), None)
        if not match:
            await update.effective_message.reply_text(
                f"No session found for conversation {target_key}.")
            return
        skills = match["active_skills"]
        skill_list = ", ".join(skills) if skills else "none"
        lines = [
            f"<b>Session {html.escape(target_key)}</b>",
            f"Provider: {html.escape(match['provider'])}",
            f"Approval: {html.escape(match['approval_mode'])}",
            f"Skills ({len(skills)}): {html.escape(skill_list)}",
            f"Pending request: {'yes' if match['has_pending'] else 'no'}",
            f"Credential setup: {'in progress' if match['has_setup'] else 'no'}",
            f"Created: {html.escape(match['created_at'][:19])}",
            f"Updated: {html.escape(match['updated_at'][:19])}",
        ]
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML)
        return

    # Summary view
    total = len(sessions)
    pending = sum(1 for s in sessions if s["has_pending"])
    setup = sum(1 for s in sessions if s["has_setup"])
    skill_counts: dict[str, int] = {}
    for s in sessions:
        for sk in s["active_skills"]:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

    lines = [f"<b>Sessions: {total}</b>"]
    if pending:
        lines.append(f"Pending approval: {pending}")
    if setup:
        lines.append(f"Credential setup: {setup}")
    if skill_counts:
        top = sorted(skill_counts.items(), key=lambda x: -x[1])[:5]
        lines.append("")
        lines.append("<b>Top skills:</b>")
        for sk, count in top:
            lines.append(f"  {html.escape(sk)}: {count}")
    lines.append("")
    lines.append(f"Most recent: {html.escape(sessions[0]['conversation_key'])}")
    if sessions[0]["updated_at"]:
        lines.append(f"  updated {sessions[0]['updated_at'][:19]}")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML)


@_command_handler
async def cmd_skills(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    from app.channels.telegram.runtime_skills import (
        skills_show, skills_list, skills_add, skills_remove,
        skills_setup, skills_clear, skills_create, skills_search,
        skills_info, skills_install, skills_uninstall, skills_updates,
        skills_diff, skills_update, skills_edit, skills_history,
        skills_submit, skills_approve, skills_reject, skills_publish,
        skills_archive,
    )
    args = event.args
    runtime = _runtime_skill_runtime()
    if not args:
        await skills_show(event, update, runtime=runtime)
        return

    sub = args[0].lower()
    _SUBS_WITH_ARG = {
        "add": skills_add, "remove": skills_remove, "setup": skills_setup,
        "create": skills_create, "info": skills_info, "install": skills_install,
        "uninstall": skills_uninstall, "diff": skills_diff,
        "history": skills_history, "submit": skills_submit, "approve": skills_approve,
        "reject": skills_reject, "publish": skills_publish, "archive": skills_archive,
    }
    if sub in _SUBS_WITH_ARG and len(args) >= 2:
        await _SUBS_WITH_ARG[sub](event, update, args[1], runtime=runtime)
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

    await update.effective_message.reply_text(
        "Usage: /skills [list|add|remove|setup|create|edit|history|submit|approve|reject|publish|archive|clear|search|info|install|uninstall|updates|update|diff]"
    )


@_command_handler
async def cmd_guidance(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    args = event.args
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /guidance [preview|edit|history|submit|approve|reject|publish|archive] <provider> [body]"
        )
        return
    sub = args[0].lower()
    provider_name = args[1]
    if sub == "preview":
        await channel_guidance_preview(event, update, provider_name)
        return
    if sub == "history":
        await channel_guidance_history(event, update, provider_name)
        return
    if sub == "edit" and len(args) >= 3:
        await channel_guidance_edit(event, update, provider_name, " ".join(args[2:]))
        return
    if sub == "submit":
        await channel_guidance_submit(event, update, provider_name)
        return
    if sub == "approve":
        if not is_admin(event.user):
            await update.effective_message.reply_text("Only admins can approve provider guidance.")
            return
        await channel_guidance_approve(event, update, provider_name)
        return
    if sub == "reject":
        if not is_admin(event.user):
            await update.effective_message.reply_text("Only admins can reject provider guidance.")
            return
        await channel_guidance_reject(event, update, provider_name)
        return
    if sub == "publish":
        if not is_admin(event.user):
            await update.effective_message.reply_text("Only admins can publish provider guidance.")
            return
        await channel_guidance_publish(event, update, provider_name)
        return
    if sub == "archive":
        if not is_admin(event.user):
            await update.effective_message.reply_text("Only admins can archive provider guidance.")
            return
        await channel_guidance_archive(event, update, provider_name)
        return
    await update.effective_message.reply_text(
        "Usage: /guidance [preview|edit|history|submit|approve|reject|publish|archive] <provider> [body]"
    )


@_command_handler
async def cmd_cancel(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_cancel(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_clear_credentials(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await runtime_skill_cmd_clear_credentials(
        event,
        update,
        context,
        runtime=_runtime_skill_runtime(),
    )


@_callback_handler
async def handle_clear_cred_callback(event, query) -> None:
    await runtime_skill_handle_clear_cred_callback(
        event,
        query,
        runtime=_runtime_skill_runtime(),
    )


@_command_handler
async def cmd_compact(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_compact(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_raw(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _state().config
    args = event.args

    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            rendered = telegram_presenters.raw_usage_message()
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return

    raw_text = load_raw(cfg.data_dir, _conversation_key(chat_id), n)
    if raw_text is None:
        rendered = telegram_presenters.raw_missing_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    await send_formatted_reply(update.effective_message, raw_text)


@_command_handler
async def cmd_role(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_role(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_model(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_model(event, update, context, runtime=_conversation_runtime())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Normalize input, enqueue provider work for the worker, or handle credential setup inline.

    Provider execution runs only in the worker; handlers return quickly so /cancel
    can be delivered without PTB concurrency. At most one fresh (queued or claimed) item
    per chat: admission is serialized at the store; when the chat already has one we
    reply busy and do not enqueue a second run.
    """
    uid = update.update_id
    user = normalize_user(update.effective_user)
    if user is None or not is_allowed(user):
        return

    rate_limiter = _state().rate_limiter
    if rate_limiter and rate_limiter.enabled and not (_state().config.admin_users_explicit and is_admin(user)):
        allowed, retry_after = rate_limiter.check(user.id)
        if not allowed:
            await update.effective_message.reply_text(
                f"Rate limit reached. Please wait {retry_after} seconds.")
            return

    msg = await normalize_message(update, context, _state().config.data_dir)
    if msg is None:
        return

    message = update.effective_message
    chat_id = msg.chat_id
    user_id = user.id
    prompt, image_paths = build_user_prompt(msg.text, list(msg.attachments))
    payload = serialize_inbound(msg)

    cfg = _state().config
    needs_welcome = not session_exists(cfg.data_dir, _conversation_key(chat_id))

    data_dir = cfg.data_dir
    if await runtime_skill_maybe_handle_setup_message(
        update,
        msg,
        payload,
        runtime=_runtime_skill_runtime(),
    ):
        return

    envelope = InboundEnvelope(
        transport="telegram",
        event_id=_event_key(uid),
        conversation_key=_conversation_key(chat_id),
        actor_key=_actor_key(user_id),
        received_at=datetime.now(timezone.utc),
        event=msg,
    )
    status, item_id = admit_fresh_message(data_dir, envelope)
    if status == "duplicate":
        return
    if status == "admitted" and needs_welcome:
        rendered = telegram_presenters.welcome_message(
            approval_mode=cfg.approval_mode,
            compact_mode=cfg.compact_mode,
        )
        await message.chat.send_message(rendered.text, **rendered.kwargs())
    if status == "queued":
        await message.reply_text(
            f"<i>{_msg.queue_accepted()}</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    if status not in {"admitted", "queued"} or item_id is None:
        return

    # Enqueued for worker; return so /cancel can be processed without blocking.
    return


@_callback_handler
async def handle_callback(event, query) -> None:
    await pending_handle_callback(event, query, runtime=_pending_runtime())


@_callback_handler
async def handle_delegation_callback(event, query) -> None:
    parsed = _parse_delegation_callback(event.data)
    if parsed is None:
        return
    action, chat_id = parsed

    async with _chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        if action == "delegation_approve":
            await _handle_delegation_approve(chat_id, query)
            return
        if action == "delegation_cancel":
            await _handle_delegation_cancel(chat_id, query)


# -- Recovery replay/discard callback handler --------------------------------


async def handle_recovery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await pending_handle_recovery_callback(update, context, runtime=_pending_runtime())


async def handle_recovery_action(
    chat_id: int | str,
    action: str,
    update_id: int,
    message,
    *,
    answer_action=None,
    cancel_event: asyncio.Event | None = None,
) -> None:
    await pending_handle_recovery_action(
        chat_id,
        action,
        update_id,
        message,
        answer_action=answer_action,
        cancel_event=cancel_event,
        runtime=_pending_runtime(),
    )


# -- Expand/collapse callback handler --------------------------------------


def _parse_expand_collapse_data(data: str) -> tuple[int, int] | None:
    """Parse 'expand:{chat_id}:{slot}' or 'collapse:{chat_id}:{slot}' callback data."""
    parts = data.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


@_callback_handler
async def handle_expand_callback(event, query) -> None:
    """Handle 'Show full answer' button presses."""
    await query.answer()
    parsed = _parse_expand_collapse_data(event.data)
    if parsed is None:
        return
    target_chat, slot = parsed

    from app.summarize import load_raw_by_slot
    cfg = _state().config
    raw_text = load_raw_by_slot(cfg.data_dir, _conversation_key(target_chat), slot)
    if raw_text is None:
        await query.edit_message_reply_markup(reply_markup=None)
        rendered = telegram_presenters.missing_collapsed_response_message()
        await query.message.edit_text(
            rendered.text,
            **rendered.kwargs(),
        )
        return

    rendered = telegram_presenters.expanded_response_message(raw_text, target_chat, slot)
    if rendered is not None:
        try:
            await query.message.edit_text(rendered.text, **rendered.kwargs())
            return
        except BadRequest:
            pass
    # Too long to edit — send as new messages, remove button
    await query.edit_message_reply_markup(reply_markup=None)
    for rendered in telegram_presenters.formatted_reply_messages(raw_text):
        try:
            await query.message.chat.send_message(rendered.text, **rendered.kwargs())
        except BadRequest:
            await query.message.chat.send_message(
                telegram_presenters.formatted_reply_fallback_text(rendered.text)
            )


@_callback_handler
async def handle_collapse_callback(event, query) -> None:
    """Handle 'Collapse' button presses — re-render compact view."""
    await query.answer()
    parsed = _parse_expand_collapse_data(event.data)
    if parsed is None:
        return
    target_chat, slot = parsed

    from app.summarize import load_raw_by_slot
    cfg = _state().config
    raw_text = load_raw_by_slot(cfg.data_dir, _conversation_key(target_chat), slot)
    if raw_text is None:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    rendered = telegram_presenters.compact_reply_button_message(raw_text, target_chat, slot)
    try:
        await query.message.edit_text(
            rendered.text,
            **rendered.kwargs(),
        )
    except BadRequest:
        await query.edit_message_reply_markup(reply_markup=None)


# -- Settings callback handler ---------------------------------------------


@_callback_handler
async def handle_settings_callback(event, query) -> None:
    await conversation_handle_settings_callback(event, query, runtime=_conversation_runtime())


# -- Application builder ---------------------------------------------------


@_callback_handler
async def handle_skill_add_callback(event, query) -> None:
    await runtime_skill_handle_skill_add_callback(
        event,
        query,
        runtime=_runtime_skill_runtime(),
    )


@_callback_handler
async def handle_skill_update_callback(event, query) -> None:
    await runtime_skill_handle_skill_update_callback(
        event,
        query,
        runtime=_runtime_skill_runtime(),
    )

@_command_handler
async def cmd_project(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_project(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_settings(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_settings(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_policy(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_policy(event, update, context, runtime=_conversation_runtime())


@_command_handler
async def cmd_allowuser(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: add a user to the allowed list. Usage: /allowuser <actor_key|user_id> [reason]."""
    del context
    if not is_admin(event.user):
        await update.effective_message.reply_text("This command requires admin access.")
        return
    if not event.args:
        await update.effective_message.reply_text("Usage: /allowuser <actor_key|user_id> [reason]")
        return
    actor_key = parse_actor_key(event.args[0])
    if not actor_key:
        await update.effective_message.reply_text("Usage: /allowuser <actor_key|user_id> [reason]")
        return
    reason = " ".join(event.args[1:])
    granted_by = _actor_key(event.user.id if event.user else 0)
    cfg = _state().config
    work_queue.set_user_access(cfg.data_dir, actor_key, "allowed", reason, granted_by)
    await update.effective_message.reply_text(f"Actor {actor_key} added to allowed list.")


@_command_handler
async def cmd_blockuser(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: block a user. Usage: /blockuser <actor_key|user_id> [reason]."""
    del context
    if not is_admin(event.user):
        await update.effective_message.reply_text("This command requires admin access.")
        return
    if not event.args:
        await update.effective_message.reply_text("Usage: /blockuser <actor_key|user_id> [reason]")
        return
    actor_key = parse_actor_key(event.args[0])
    if not actor_key:
        await update.effective_message.reply_text("Usage: /blockuser <actor_key|user_id> [reason]")
        return
    reason = " ".join(event.args[1:])
    granted_by = _actor_key(event.user.id if event.user else 0)
    cfg = _state().config
    work_queue.set_user_access(cfg.data_dir, actor_key, "blocked", reason, granted_by)
    await update.effective_message.reply_text(f"Actor {actor_key} blocked.")


@_command_handler
async def cmd_listaccess(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: list all configured DB-backed access overrides."""
    del context
    if not is_admin(event.user):
        await update.effective_message.reply_text("This command requires admin access.")
        return
    cfg = _state().config
    rows = work_queue.list_user_access(cfg.data_dir)
    if not rows:
        await update.effective_message.reply_text("No access overrides set.")
        return
    lines = ["<b>Access overrides</b>"]
    for row in rows:
        status = "✅ allowed" if row["access"] == "allowed" else "🚫 blocked"
        reason = f" — {html.escape(row['reason'])}" if row["reason"] else ""
        lines.append(f"• <code>{row['actor_key']}</code> {status}{reason}")
    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )

async def _poll_cancel_requested(item_id: str, cancel_event: asyncio.Event) -> None:
    interval = poll_interval_for_runtime(_state().config.runtime_mode)
    while not cancel_event.is_set():
        if work_queue.is_cancel_requested(_state().config.data_dir, item_id):
            cancel_event.set()
            return
        await asyncio.sleep(interval)


async def _run_with_cancel_watch(
    item: dict[str, Any],
    runner,
):
    if _state().config.runtime_mode != "shared":
        return await runner(None)
    cancel_event = asyncio.Event()
    watcher = asyncio.create_task(
        _poll_cancel_requested(item["id"], cancel_event),
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


def _build_action_surface(
    event: InboundAction,
    *,
    item: dict[str, Any],
):
    bot_instance = _state().bot_instance
    source = getattr(event, "source", "telegram")
    conversation_key = str(item.get("conversation_key") or event.conversation_key)
    chat_id = telegram_numeric_id(conversation_key) if source == "telegram" else None
    if source == "telegram" and (chat_id is None or bot_instance is None):
        raise RuntimeError(
            f"Telegram action item {item.get('id')} missing bot or chat_id for {conversation_key!r}"
        )
    runtime_chat = chat_id if chat_id is not None else conversation_key
    conversation_ref = event.conversation_ref or (
        telegram_conversation_ref(_state().config, chat_id)
        if source == "telegram" and chat_id is not None
        else conversation_key
    )
    surface = composition.create_channel_egress(
        conversation_ref,
        config=_state().config,
        bot=bot_instance,
        conversation_key=conversation_key,
        source=source,
        target_message_id=_action_target_message_id(event),
        output_log=getattr(bot_instance, "_output_log", None) if bot_instance is not None else None,
    )
    setattr(surface, "_worker_item_id", str(item.get("id", "")))
    return surface, runtime_chat, chat_id, conversation_ref, source


async def _execute_worker_action(
    event: InboundAction,
    item: dict[str, Any],
    *,
    cancel_event: asyncio.Event | None,
) -> None:
    surface, runtime_chat, chat_id, conversation_ref, source = _build_action_surface(event, item=item)
    trust = trust_tier_for_source(source, event.user, config=_state().config)
    action = event.action
    params = dict(event.params)

    if await conversation_handle_worker_action(
        event,
        item,
        surface,
        runtime=_conversation_runtime(),
        runtime_chat=runtime_chat,
        source=source,
        trust=trust,
    ):
        return

    if await pending_handle_worker_action(
        event,
        item,
        params,
        surface,
        runtime_chat=runtime_chat,
        cancel_event=cancel_event,
        runtime=_pending_runtime(),
    ):
        return

    if action == "delegation_approve":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_surface_delegation_approve(
            target_runtime,
            conversation_ref,
            surface,
            runtime=_delegation_runtime(),
        )
        return

    if action == "delegation_cancel":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_surface_delegation_cancel(
            target_runtime,
            conversation_ref,
            surface,
            runtime=_delegation_runtime(),
        )
        return

    if action in {"skills_add", "skills_remove", "skills_setup", "skills_clear"}:
        worker_event = dataclasses.replace(event, conversation_key=_conversation_key(runtime_chat))
        if await runtime_skill_handle_worker_skill_action(
            worker_event,
            surface,
            runtime=_runtime_skill_runtime(),
        ):
            return
        return

    log.warning("Worker dispatch: unknown semantic action %s for item %s", action, item.get("id"))


async def worker_dispatch(kind: str, event, item: dict) -> None:
    """Dispatch a deserialized inbound event from the worker loop.

    Items with dispatch_mode 'recovery' get a recovery notice and move to
    pending_recovery. Fresh message items (dispatch_mode 'fresh') are executed
    here: execute_request or request_approval; they register the live-cancel registry so
    /cancel works.
    """
    from app.runtime.inbound_types import InboundAction, InboundCallback, InboundCommand, InboundMessage

    bot = _state().bot_instance
    cfg = _state().config
    data_dir = cfg.data_dir

    if isinstance(event, InboundMessage):
        source = getattr(event, "source", "telegram")
        conversation_key = str(item.get("conversation_key") or getattr(event, "conversation_key", ""))
        chat_id = telegram_numeric_id(conversation_key) if source == "telegram" else None
        runtime_chat = chat_id if chat_id is not None else conversation_key
        if source == "telegram" and (chat_id is None or bot is None):
            log.warning(
                "Worker dispatch: telegram item %s missing chat/bot (conversation_key=%s)",
                item.get("id"),
                conversation_key,
            )
            return
        conversation_ref = event.conversation_ref or (
            telegram_conversation_ref(_state().config, chat_id)
            if source == "telegram" and chat_id is not None
            else conversation_key
        )
        routed_task_id = getattr(event, "routed_task_id", "")
        title = summarize_text(event.text) or "Conversation"
        bot_msg = composition.create_channel_egress(
            conversation_ref,
            config=_state().config,
            bot=bot,
            conversation_key=conversation_key,
            source=source,
            routed_task_id=routed_task_id,
            output_log=getattr(bot, "_output_log", None),
        )

        # Recovered item: send notice and move to pending_recovery.
        if item.get("dispatch_mode") == "recovery":
            if source == "telegram" and not is_allowed(event.user):
                work_queue.fail_work_item(data_dir, item["id"], error="not_allowed")
                return
            update_id = telegram_numeric_id(str(item.get("event_id") or "")) or 0
            original_text = event.text or ""
            preview = html.escape(original_text[:200] + ("\u2026" if len(original_text) > 200 else ""))
            await bot_msg.bind(title=title, config=_state().config)
            await bot_msg.send_recovery_notice(
                preview=preview,
                prompt=_msg.recovery_notice_prompt(),
                run_again_label=_msg.recovery_button_run_again(),
                skip_label=_msg.recovery_button_skip(),
                update_id=update_id,
            )
            work_queue.mark_pending_recovery(data_dir, item["id"])
            raise work_queue.PendingRecovery(item["id"])

        # Fresh message: run provider (execute_request/request_approval register the live-cancel registry).
        if source == "telegram" and not is_allowed(event.user):
            work_queue.fail_work_item(data_dir, item["id"], error="not_allowed")
            return
        prompt, image_paths = build_user_prompt(event.text, list(event.attachments))
        user_id = event.user.id
        trust = trust_tier_for_source(source, event.user, config=_state().config)
        await bot_msg.bind(title=title, config=_state().config)
        await bot_msg.on_message_received(event.text)
        try:
            async with _chat_lock(runtime_chat, worker_item=item):
                session = _load(runtime_chat)
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
                            bot_msg,
                            request_user_id=user_id,
                            trust_tier=trust,
                            cancel_event=cancel_event,
                        )
                    else:
                        outcome = await execute_request(
                            runtime_chat,
                            prompt,
                            image_paths,
                            bot_msg,
                            request_user_id=user_id,
                            trust_tier=trust,
                            cancel_event=cancel_event,
                        )

                await _run_with_cancel_watch(item, _run_message)
        except work_queue.LeaveClaimed:
            raise
        if outcome is not None:
            await bot_msg.on_outcome(outcome)
            if getattr(event, "skip_approval", False) and source == "registry":
                session_after = _load(runtime_chat)
                finalized = finalize_resumed_delegation(
                    session_after.pending_delegation,
                    conversation_ref=conversation_ref,
                )
                if finalized.status == "cleared_after_resume":
                    session_after.pending_delegation = None
                    _save(runtime_chat, session_after)
        if routed_task_id:
            client = registry_client(_state().config)
            if client is not None and outcome is not None:
                full_text = outcome.reply_text or html.unescape(getattr(bot_msg, "last_status_text", ""))
                result_status = "completed" if outcome.status in {"completed", "completed_with_denials"} else outcome.status
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
                    conversation_key=conversation_key,
                    work_item_id=item["id"],
                    provider=cfg.provider_name,
                    prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens,
                    cost_usd=outcome.cost_usd,
                )
            except Exception:
                log.warning(
                    "Failed to record usage for conversation %s",
                    conversation_key,
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
                item,
                lambda cancel_event: _execute_worker_action(event, item, cancel_event=cancel_event),
            )
        except work_queue.LeaveClaimed:
            raise
        return

    if isinstance(event, (InboundCommand, InboundCallback)):
        conversation_key = str(item.get("conversation_key", ""))
        chat_id = telegram_numeric_id(conversation_key)
        log.info(
            "Worker recovered orphaned %s for conversation %s (event %s)",
            kind,
            conversation_key,
            item.get("event_id"),
        )
        if chat_id is None or bot is None:
            return
        try:
            detail = f"/{event.command}" if isinstance(event, InboundCommand) else "a button action"
            await bot.send_message(
                chat_id,
                _msg.recovery_orphaned_command(detail),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    log.warning("Worker dispatch: unknown event type for item %s", item.get("id"))


def _shared_inline_command_handler(command: str):
    return {
        "approval": cmd_approval,
        "skills": cmd_skills,
        "guidance": cmd_guidance,
        "compact": cmd_compact,
        "role": cmd_role,
        "model": cmd_model,
        "project": cmd_project,
        "policy": cmd_policy,
    }.get(command)


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


async def _enqueue_shared_action(update: Update, action: InboundAction) -> tuple[bool, str | None]:
    envelope = _build_action_envelope(
        transport="telegram",
        event_id=_event_key(update.update_id),
        action=action,
    )
    return enqueue_inbound_envelope(_state().config.data_dir, envelope)


def _shared_action_envelope(update: Update, action: InboundAction) -> InboundEnvelope:
    return _build_action_envelope(
        transport="telegram",
        event_id=_event_key(update.update_id),
        action=action,
    )


def _record_shared_action(update: Update, action: InboundAction) -> tuple[bool, InboundEnvelope]:
    envelope = _shared_action_envelope(update, action)
    return record_inbound_envelope(_state().config.data_dir, envelope), envelope


async def _shared_cancel_command(update: Update, event, action: InboundAction) -> None:
    is_new, envelope = _record_shared_action(update, action)
    if not is_new:
        return
    del envelope
    await conversation_cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        runtime=_conversation_runtime(),
        actor_user_id=event.user.id,
        allow_admin_override=is_admin(event.user),
        update_id=update.update_id,
    )


async def _shared_command_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    event = normalize_command(update, context)
    if event is None:
        return
    if not is_allowed(event.user):
        await update.effective_message.reply_text(_msg.trust_not_authorized())
        return

    action = _worker_owned_command_action(event)
    if action is None:
        handler = _shared_inline_command_handler(event.command)
        if handler is not None:
            await handler(update, context)
        return

    if _action_requires_public_guard(action.action) and await _public_guard(event, update):
        return

    if action.action == "cancel_conversation":
        await _shared_cancel_command(update, event, action)
        return

    await _enqueue_shared_action(update, action)


async def _shared_callback_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    event = normalize_callback(update)
    query = update.callback_query
    if event is None or query is None:
        return
    if not is_allowed(event.user):
        await query.answer(_msg.trust_not_authorized(), show_alert=True)
        return

    action = _worker_owned_callback_action(update, event)
    if action is None:
        if (event.data or "").startswith("skill_add_"):
            await handle_skill_add_callback(update, None)  # type: ignore[arg-type]
            return
        await query.answer()
        return

    if _action_requires_public_guard(action.action) and is_public_user(event.user):
        await query.answer(_msg.trust_command_not_available_public(), show_alert=True)
        return

    await query.answer()
    await _enqueue_shared_action(update, action)


def build_application(config: BotConfig, provider: Provider) -> Application:
    from app.content_store import init_content_store_for_config
    from app.credential_store import init_credential_store_for_config

    init_content_store_for_config(config)
    init_credential_store_for_config(config)
    state = build_channel_state(config, provider)
    if config.allow_open and config.rate_limit_per_minute == 0 and config.rate_limit_per_hour == 0:
        log.info("Public mode: applying default rate limits (5/min, 30/hr)")
    install_channel_state(state)

    # Sequential update processing; live runs are worker-owned so /cancel is delivered promptly.
    builder = Application.builder().token(config.telegram_token)
    if config.telegram_api_base_url:
        builder = builder.base_url(config.telegram_api_base_url)
    if config.telegram_file_api_base_url:
        builder = builder.base_file_url(config.telegram_file_api_base_url)
    app = builder.build()
    state.bot_instance = app.bot
    app.bot_data["telegram_boot_id"] = state.boot_id
    if config.runtime_mode == "shared":
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("session", cmd_session))
        app.add_handler(CommandHandler("clear_credentials", cmd_clear_credentials))
        app.add_handler(CommandHandler("raw", cmd_raw))
        app.add_handler(CommandHandler("send", cmd_send))
        app.add_handler(CommandHandler("id", cmd_id))
        app.add_handler(CommandHandler("doctor", cmd_doctor))
        app.add_handler(CommandHandler("discover", cmd_discover))
        app.add_handler(CommandHandler("settings", cmd_settings))
        app.add_handler(CommandHandler("allowuser", cmd_allowuser))
        app.add_handler(CommandHandler("blockuser", cmd_blockuser))
        app.add_handler(CommandHandler("listaccess", cmd_listaccess))
        app.add_handler(CommandHandler("export", cmd_export))
        app.add_handler(CommandHandler("admin", cmd_admin))
        for command in (
            "new",
            "approval",
            "approve",
            "reject",
            "skills",
            "cancel",
            "role",
            "compact",
            "project",
            "policy",
            "model",
        ):
            app.add_handler(CommandHandler(command, _shared_command_dispatch))
        app.add_handler(CallbackQueryHandler(_shared_callback_dispatch, pattern=r"^(retry_|approval_)"))
        app.add_handler(CallbackQueryHandler(_shared_callback_dispatch, pattern=r"^delegation_"))
        app.add_handler(CallbackQueryHandler(_shared_callback_dispatch, pattern=r"^recovery_"))
        app.add_handler(CallbackQueryHandler(_shared_callback_dispatch, pattern=r"^setting_"))
        app.add_handler(CallbackQueryHandler(handle_expand_callback, pattern=r"^expand:"))
        app.add_handler(CallbackQueryHandler(handle_collapse_callback, pattern=r"^collapse:"))
        app.add_handler(CallbackQueryHandler(_shared_callback_dispatch, pattern=r"^skill_add_"))
        app.add_handler(CallbackQueryHandler(handle_skill_update_callback, pattern=r"^skill_update_"))
        app.add_handler(CallbackQueryHandler(handle_clear_cred_callback, pattern=r"^clear_cred_"))
    else:
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("new", cmd_new))
        app.add_handler(CommandHandler("session", cmd_session))
        app.add_handler(CommandHandler("approval", cmd_approval))
        app.add_handler(CommandHandler("approve", cmd_approve))
        app.add_handler(CommandHandler("reject", cmd_reject))
        app.add_handler(CommandHandler("skills", cmd_skills))
        app.add_handler(CommandHandler("guidance", cmd_guidance))
        app.add_handler(CommandHandler("cancel", cmd_cancel))
        app.add_handler(CommandHandler("clear_credentials", cmd_clear_credentials))
        app.add_handler(CommandHandler("role", cmd_role))
        app.add_handler(CommandHandler("compact", cmd_compact))
        app.add_handler(CommandHandler("raw", cmd_raw))
        app.add_handler(CommandHandler("send", cmd_send))
        app.add_handler(CommandHandler("id", cmd_id))
        app.add_handler(CommandHandler("doctor", cmd_doctor))
        app.add_handler(CommandHandler("discover", cmd_discover))
        app.add_handler(CommandHandler("settings", cmd_settings))
        app.add_handler(CommandHandler("project", cmd_project))
        app.add_handler(CommandHandler("policy", cmd_policy))
        app.add_handler(CommandHandler("model", cmd_model))
        app.add_handler(CommandHandler("allowuser", cmd_allowuser))
        app.add_handler(CommandHandler("blockuser", cmd_blockuser))
        app.add_handler(CommandHandler("listaccess", cmd_listaccess))
        app.add_handler(CommandHandler("export", cmd_export))
        app.add_handler(CommandHandler("admin", cmd_admin))
        app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(retry_|approval_)"))
        app.add_handler(CallbackQueryHandler(handle_delegation_callback, pattern=r"^delegation_"))
        app.add_handler(CallbackQueryHandler(handle_recovery_callback, pattern=r"^recovery_"))
        app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern=r"^setting_"))
        app.add_handler(CallbackQueryHandler(handle_expand_callback, pattern=r"^expand:"))
        app.add_handler(CallbackQueryHandler(handle_collapse_callback, pattern=r"^collapse:"))
        app.add_handler(CallbackQueryHandler(handle_skill_add_callback, pattern=r"^skill_add_"))
        app.add_handler(CallbackQueryHandler(handle_skill_update_callback, pattern=r"^skill_update_"))
        app.add_handler(CallbackQueryHandler(handle_clear_cred_callback, pattern=r"^clear_cred_"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
            handle_message,
        )
    )
    app.add_error_handler(_global_error_handler)
    return app


async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch unhandled exceptions so the user always gets feedback."""
    error = context.error

    # Stale callback queries are harmless — Telegram's 30-second answer
    # window expired while the bot was busy.  Suppress the noise.
    if isinstance(error, BadRequest) and "query is too old" in str(error).lower():
        log.debug("Stale callback query (ignored): %s", error)
        return

    log.exception("Unhandled exception in handler", exc_info=error)

    # Try to notify the user
    if update and isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                _msg.generic_error_try_again(),
            )
        except Exception:
            pass
