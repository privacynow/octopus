"""Telegram command handlers, message handler, progress display, and app wiring."""

import asyncio
import contextlib
import contextvars
import dataclasses
import html
import logging
import os
import platform
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from app.approvals import (
    build_preflight_prompt,
    format_denials_html,
)
from app.config import BotConfig
from app.formatting import extract_send_directives, md_to_telegram_html, split_html, trim_text
from app.identity import (
    parse_actor_key,
    parse_conversation_key,
    telegram_actor_key,
    telegram_conversation_key,
    telegram_event_id,
    telegram_numeric_id,
)
from app.execution_context import ResolvedExecutionContext, resolve_execution_context
from app.providers.base import Provider
from app.request_flow import (
    check_credential_satisfaction,
    classify_pending_validation,
    extra_dirs_from_denials,
    foreign_setup_message,
    foreign_skill_setup,
    format_credential_prompt,
    pending_expired,
    validate_pending,
)
from app.workflows.pending_request import (
    PendingRequestDisposition,
    PendingRequestWorkflowModel,
    run_pending_request_event,
)
from app.session_state import (
    DelegatedTask,
    PendingDelegation,
    PendingApproval,
    PendingRetry,
    SessionState,
    session_from_dict,
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
    handle_delegation_approve as handle_surface_delegation_approve,
    handle_delegation_cancel as handle_surface_delegation_cancel,
)
from app.agents.orchestration import build_delegation_plan
from app.agents.state import load_agent_runtime_state
from app.agents.types import AgentDiscoveryQuery, RoutedTaskResult, TimelineEvent
from app.transports import factory
from app.transports.admission import (
    admit_fresh_message,
    enqueue_inbound_envelope,
    record_inbound_envelope,
)
from app.transports.types import InboundEnvelope
from app.skills import (
    build_run_context, build_preflight_context,
    get_provider_config_digest, get_skill_digests,
    get_skill_requirements,
    save_user_credential, delete_user_credentials, list_user_credential_skills,
    derive_encryption_key,
    build_credential_env,
    validate_credential,
    stage_codex_scripts, cleanup_codex_scripts,
    SkillRequirement,
)
from app.storage import (
    chat_upload_dir,
    default_session,
    is_image_path,
    load_session,
    resolve_allowed_path,
    save_session,
    session_exists,
    list_sessions,
)
from app.ratelimit import RateLimiter
from app.summarize import export_chat_history, load_raw, save_raw
from app import work_queue
from app.workflows.results import TransportStateCorruption
from app.transport import (
    InboundAction,
    InboundAttachment,
    normalize_callback,
    normalize_command,
    normalize_message,
    normalize_user,
    serialize_inbound,
)
from app.worker import poll_interval_for_runtime

log = logging.getLogger(__name__)

CHAT_LOCKS: dict[int | str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Worker-owned live execution: chat_id -> cancel Event for the active provider run.
# Populated by worker_dispatch when it starts execute_request/request_approval;
# /cancel sets the event so the running provider can exit. Busy/admission gating
# is done at the store (record_and_admit_message), not via this registry.
_LIVE_CANCEL: dict[int | str, asyncio.Event] = {}


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
    data_dir = _cfg().data_dir
    conversation_key = _conversation_key(chat_id)
    if _cfg().runtime_mode == "shared" and worker_item is not None:
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
                    _boot_id,
                )
            else:
                item = work_queue.claim_next(data_dir, conversation_key, _boot_id)
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

# These get set by build_application()
_config: BotConfig | None = None
_provider: Provider | None = None
_boot_id: str = ""  # unique per process; detects restart to clear stale threads
_rate_limiter: RateLimiter | None = None
# Tracks work item ID per update_id so each handler can complete its own item.
# Keyed by update_id (not chat_id) to prevent same-chat overlap corruption.
_pending_work_items: dict[int, str] = {}  # update_id -> work_item_id


def _make_boot_id() -> str:
    return f"{platform.node()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _dedup_update(update: Update, kind: str = "unknown", payload: str = "{}") -> bool:
    """Return True if this update_id was already processed (duplicate).

    Atomically records the update AND enqueues a work item in a single
    SQLite transaction.  The item is created as ``claimed`` (owned by
    the inline handler via ``_boot_id``) so the background worker cannot
    steal it before the handler finishes.
    """
    uid = update.update_id
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    data_dir = _cfg().data_dir
    is_new, item_id = work_queue.record_and_enqueue(
        data_dir,
        _event_key(uid),
        _conversation_key(chat_id),
        _actor_key(user_id),
        kind,
        payload=payload,
        worker_id=_boot_id,
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
                work_queue.complete_work_item(_cfg().data_dir, item_id)
            else:
                work_queue.fail_work_item(_cfg().data_dir, item_id, error=error or "failed")
        except Exception:
            log.debug("Work item %s already completed", item_id)


def _cfg() -> BotConfig:
    assert _config is not None
    return _config


def _prov() -> Provider:
    assert _provider is not None
    return _provider


def _encryption_key() -> bytes:
    return derive_encryption_key(_cfg().telegram_token)


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

# Attachment is now InboundAttachment from app.transport.
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


@dataclasses.dataclass(frozen=True)
class RequestExecutionOutcome:
    status: str
    reply_text: str = ""
    error_text: str = ""
    denials: tuple[dict[str, Any], ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


async def _progress_timeline_callback(conversation_ref: str, routed_task_id: str, html_text: str, *, force: bool = False) -> None:
    del force
    await publish_timeline_event(
        _cfg(),
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
    cfg = _cfg()
    inbound = access.to_inbound_user(user)
    if inbound is None:
        return False
    override = work_queue.get_user_access(cfg.data_dir, inbound.id)
    return access.is_allowed_user_with_override(cfg, inbound, override)


def is_admin(user) -> bool:
    """Check if user is an admin (can install/uninstall/update store skills)."""
    return access.is_admin_user(_cfg(), user)


def is_public_user(user) -> bool:
    """Check if user is a public (untrusted) user.

    A user is public when allow_open is true AND the user is not in
    any allowed-user set.  Returns False if allow_open is off (the user
    wouldn't have passed is_allowed at all).
    """
    return access.is_public_user(_cfg(), user)


def _trust_tier(user) -> str:
    """Resolve the trust tier for a user: 'trusted' or 'public'."""
    return access.trust_tier(_cfg(), user)


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
    """Check prompt size in all chats where skill_name is active."""
    from app.doctor import check_prompt_size_cross_chat
    cfg = _cfg()
    return check_prompt_size_cross_chat(
        data_dir, skill_name, cfg.provider_name,
        _prov().new_provider_state, cfg.approval_mode,
    )


# -- Project helpers -------------------------------------------------------

def _resolve_project(session: SessionState):
    """Return ProjectBinding for the session's bound project, or None."""
    project_id = session.project_id
    if not project_id:
        return None
    for proj in _cfg().projects:
        if proj.name == project_id:
            return proj
    return None


def _resolve_context(session: SessionState, trust_tier: str = "trusted") -> ResolvedExecutionContext:
    """Build the single authoritative execution identity from session + config."""
    return resolve_execution_context(session, _cfg(), _prov().name, trust_tier=trust_tier)


def _settings_model_profile_state(
    session: SessionState,
    cfg: BotConfig,
    trust_tier: str,
    effective_model: str,
) -> tuple[list[str], str]:
    """Return (available profile names sorted, current profile name for display/checkmark).

    For public users, current is derived from effective_model over public profiles only,
    so text and keyboard selection stay consistent when saved/default is restricted.
    """
    if trust_tier == "public" and cfg.public_model_profiles and cfg.model_profiles:
        available = sorted(cfg.public_model_profiles & cfg.model_profiles.keys())
        current = "(default)"
        for p in available:
            if cfg.model_profiles.get(p) == effective_model:
                current = p
                break
        return (available, current)
    available = sorted(cfg.model_profiles.keys()) if cfg.model_profiles else []
    if not available:
        # No profiles configured — don't display a phantom profile name
        return ([], "(default)")
    # Resolution: session > project > global default (mirrors resolve_effective_model)
    project_profile = ""
    if session.project_id:
        for proj in cfg.projects:
            if proj.name == session.project_id:
                project_profile = proj.model_profile
                break
    current = session.model_profile or project_profile or cfg.default_model_profile or "(default)"
    return (available, current)


def _settings_model_buttons(available: list[str], current: str, has_explicit_override: bool = False) -> list[InlineKeyboardButton]:
    """One row of model profile buttons, with optional Inherit button."""
    buttons = [
        InlineKeyboardButton(
            f"\u2705 {p}" if p == current else p,
            callback_data=f"setting_model:{p}",
        )
        for p in available
    ]
    if has_explicit_override:
        buttons.append(InlineKeyboardButton("Inherit", callback_data="setting_model:inherit"))
    return buttons


def _settings_project_buttons(
    cfg: BotConfig, session: SessionState
) -> list[list[InlineKeyboardButton]]:
    """Project rows: one row of project names, optional clear row. For trusted users only."""
    rows: list[list[InlineKeyboardButton]] = []
    if not cfg.projects:
        return rows
    row = []
    for proj in cfg.projects:
        label = f"\u2705 {proj.name}" if proj.name == session.project_id else proj.name
        row.append(InlineKeyboardButton(label, callback_data=f"setting_project:{proj.name}"))
    if row:
        rows.append(row)
    if session.project_id:
        rows.append([InlineKeyboardButton("Clear project", callback_data="setting_project:clear")])
    return rows


def _settings_policy_buttons(policy: str, has_explicit_override: bool = False) -> list[InlineKeyboardButton]:
    """One row of file policy buttons, with optional Inherit button."""
    buttons = [
        InlineKeyboardButton(
            "\u2705 Read only" if policy == "inspect" else "Read only",
            callback_data="setting_policy:inspect",
        ),
        InlineKeyboardButton(
            "\u2705 Read & write" if policy == "edit" else "Read & write",
            callback_data="setting_policy:edit",
        ),
    ]
    if has_explicit_override:
        buttons.append(InlineKeyboardButton("Inherit", callback_data="setting_policy:inherit"))
    return buttons


def _settings_compact_buttons(compact: bool) -> list[InlineKeyboardButton]:
    """One row of compact mode buttons."""
    return [
        InlineKeyboardButton(
            "\u2705 Short answers" if compact else "Short answers",
            callback_data="setting_compact:on",
        ),
        InlineKeyboardButton(
            "\u2705 Full answers" if not compact else "Full answers",
            callback_data="setting_compact:off",
        ),
    ]


def _settings_approval_buttons(approval: str) -> list[InlineKeyboardButton]:
    """One row of approval mode buttons."""
    return [
        InlineKeyboardButton(
            "\u2705 Review first" if approval == "on" else "Review first",
            callback_data="setting_approval:on",
        ),
        InlineKeyboardButton(
            "\u2705 Run immediately" if approval == "off" else "Run immediately",
            callback_data="setting_approval:off",
        ),
    ]


# -- Setting mutators (single authority per family for command + callback) ----

def _apply_model_change(chat_id: int, session: SessionState, value: str) -> None:
    """Set session model_profile and persist. Caller sends reply."""
    session.model_profile = value
    _save(chat_id, session)


def _apply_model_selection(
    chat_id: int,
    session: SessionState,
    profile: str,
    cfg: BotConfig,
    trust_tier: str,
) -> tuple[bool, str]:
    """Validate model profile for this context, apply if allowed, return (ok, message).

    Single authority for both cmd_model and handle_settings_callback model branch.
    Caller sends the returned message (reply or edit_text).
    """
    resolved = _resolve_context(session, trust_tier=trust_tier)
    effective = resolved.effective_model or ""
    available_list, _ = _settings_model_profile_state(session, cfg, trust_tier, effective)
    available = set(available_list)
    if profile not in available:
        return (False, _msg.trust_model_profile_not_available(profile, list(available_list)))
    _apply_model_change(chat_id, session, profile)
    return (True, _msg.trust_model_profile_set(profile, cfg.model_profiles[profile]))


def _apply_project_change(
    chat_id: int, session: SessionState, value: str
) -> tuple[bool, str]:
    """Apply project change (clear or set). Returns (success, message). Caller sends message."""
    cfg = _cfg()
    if value == "clear":
        if not session.project_id:
            return (False, _msg.trust_no_project_active())
        session.project_id = ""
        session.provider_state = _prov().new_provider_state()
        session.clear_pending()
        _save(chat_id, session)
        return (True, _msg.trust_project_cleared(str(cfg.working_dir)))
    # value is project name
    found = any(proj.name == value for proj in cfg.projects)
    if not found:
        return (False, _msg.trust_unknown_project(value))
    if session.project_id == value:
        return (False, _msg.trust_already_using_project(value))
    session.project_id = value
    session.provider_state = _prov().new_provider_state()
    session.clear_pending()
    _save(chat_id, session)
    proj = next(p for p in cfg.projects if p.name == value)
    return (True, _msg.trust_switched_project(
        value, str(proj.root_dir),
        file_policy=proj.file_policy, model_profile=proj.model_profile,
    ))


def _apply_policy_change(chat_id: int, session: SessionState, value: str) -> None:
    """Set file_policy, reset provider_state and pending, persist. Caller sends reply."""
    session.file_policy = value
    session.provider_state = _prov().new_provider_state()
    session.clear_pending()
    _save(chat_id, session)


def _apply_approval_change(chat_id: int, session: SessionState, value: str) -> None:
    """Set approval_mode and approval_mode_explicit, persist. Caller sends reply."""
    session.approval_mode = value
    session.approval_mode_explicit = True
    _save(chat_id, session)


def _apply_compact_change(chat_id: int, session: SessionState, value: bool) -> None:
    """Set compact_mode and persist. Caller sends reply."""
    session.compact_mode = value
    _save(chat_id, session)


# -- Helpers ---------------------------------------------------------------

def _allowed_roots(chat_id: int | str, resolved: ResolvedExecutionContext | None = None) -> list[Path]:
    """Return path roots this chat is allowed to access.

    Uses the resolved execution context for working_dir and extra_dirs,
    so public users get public roots and project-bound chats get project roots.
    Falls back to config defaults only when no resolved context is available.
    """
    cfg = _cfg()
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
    formatted = md_to_telegram_html(text) if text else "<i>[empty]</i>"
    for chunk in split_html(formatted, 4096):
        try:
            await message.reply_text(
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        except BadRequest:
            # Strip HTML tags so the fallback doesn't show raw markup
            plain = re.sub(r"<[^>]+>", "", chunk)
            await message.reply_text(plain[:4096])


async def _edit_or_reply_text(message, text: str, **kwargs) -> None:
    if getattr(message, "_target_message_id", None) is not None and hasattr(message, "edit_text"):
        await message.edit_text(text, **kwargs)
        return
    caps = getattr(message, "capabilities", None)
    if getattr(caps, "surface_name", "") == "telegram":
        await message.reply_text(text, **kwargs)
        return
    if hasattr(message, "edit_text"):
        await message.edit_text(text, **kwargs)
        return
    await message.reply_text(text, **kwargs)


def _extract_summary(text: str, max_lines: int = 4) -> tuple[str, str]:
    """Split text into a short summary (first few lines) and the rest."""
    lines = text.split("\n")
    # Take up to max_lines non-empty lines as summary
    summary_lines = []
    rest_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            summary_lines.append(line)
        if len(summary_lines) >= max_lines:
            rest_start = i + 1
            break
    else:
        rest_start = len(lines)

    summary = "\n".join(lines[:rest_start])
    rest = "\n".join(lines[rest_start:]).strip()
    return summary, rest


async def _send_compact_reply(message, text: str, chat_id: int, slot: int) -> None:
    """Send a compact response using expandable blockquote or expand button."""
    summary, detail = _extract_summary(text)
    formatted_summary = md_to_telegram_html(summary) if summary else ""

    if detail:
        # Use expandable blockquote for the detail
        formatted_detail = md_to_telegram_html(detail)
        compact_html = (
            f"{formatted_summary}\n\n"
            f"<blockquote expandable>{formatted_detail}</blockquote>"
        )

        # If the combined text fits in a single message, send with expandable blockquote
        if len(compact_html) <= 4000:
            try:
                await message.reply_text(
                    compact_html, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return
            except BadRequest:
                pass  # Fall through to button approach

        # Too long for blockquote — send summary with "Show full" button
        button_text = f"{formatted_summary}\n\n<i>Response truncated</i>"
        try:
            await message.reply_text(
                button_text[:4000], parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "Show full answer",
                        callback_data=f"expand:{chat_id}:{slot}",
                    ),
                ]]),
            )
            return
        except BadRequest:
            pass

    # Fallback: send as regular formatted reply
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
            await message.reply_text(f"[Cannot send: {raw_path}]")
            continue
        await send_path_to_chat(message, allowed_path, force_image=(dtype == "IMAGE"))


def _delegation_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\u25b6\ufe0f Approve delegation", callback_data=f"delegation_approve:{chat_id}"),
        InlineKeyboardButton("\u2716 Cancel", callback_data=f"delegation_cancel:{chat_id}"),
    ]])


def _format_delegation_plan_message(delegation: PendingDelegation) -> str:
    lines = [
        "<b>Delegation plan</b>",
        "",
        "I'd like to delegate the following to specialist bots:",
        "",
    ]
    for index, task in enumerate(delegation.tasks, start=1):
        lines.extend([
            f"<b>{index}. {html.escape(task.title or task.routed_task_id)}</b>",
            f"\u2192 {html.escape(task.target_agent_id or 'unassigned')}",
            "",
        ])
    lines.append("Approve to send these requests, or cancel to continue without delegation.")
    return "\n".join(lines)


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
        _cfg(),
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
    await send_plan(
        _format_delegation_plan_message(delegation),
        parse_mode=ParseMode.HTML,
        reply_markup=_delegation_keyboard(chat_id),
    )
    return RequestExecutionOutcome(status="delegation_proposed")


async def keep_typing(chat) -> None:
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(_cfg().typing_interval_seconds)
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
    cfg = _cfg()
    raw = load_session(
        cfg.data_dir, _conversation_key(chat_id), _prov().name,
        _prov().new_provider_state, cfg.approval_mode,
        cfg.role, cfg.default_skills,
    )
    session = session_from_dict(raw)
    # Self-heal: prune active skills whose refs/dirs no longer exist
    from app.skills import normalize_active_skills
    normalize_active_skills(session, save_fn=lambda s: _save(chat_id, s))
    return session


def _save(chat_id: int, session: SessionState) -> None:
    save_session(_cfg().data_dir, _conversation_key(chat_id), session_to_dict(session))


# -- Credential helpers ----------------------------------------------------

async def _check_credential_satisfaction(
    chat_id: int | str, user_id: int | str, session: SessionState, message,
    resolved: ResolvedExecutionContext | None = None,
) -> dict[str, str] | None:
    """Check credentials for active skills. Returns credential_env if satisfied, None if not.

    Uses resolved.active_skills (not raw session.active_skills) so public users
    with no resolved skills skip credential checks entirely.

    Delegates to request_flow.check_credential_satisfaction for pure logic,
    then handles transport (message sending, session saving).
    """
    active_skills = resolved.active_skills if resolved else session.active_skills
    result = check_credential_satisfaction(
        active_skills, session, _actor_key(user_id), _cfg().data_dir, _encryption_key(),
    )
    if result.satisfied:
        return result.credential_env

    if result.foreign_setup:
        await message.reply_text(foreign_setup_message(result.foreign_setup))
        return None

    # Start credential setup for missing skill
    session.awaiting_skill_setup = result.setup_state
    _save(chat_id, session)
    first_req = result.setup_state.remaining[0]
    await message.reply_text(
        f"Skill <code>{html.escape(result.missing_skill)}</code> needs setup.\n\n"
        f"{format_credential_prompt(first_req)}",
        parse_mode=ParseMode.HTML,
    )
    return None


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
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    # Resolve the authoritative execution identity once
    resolved = _resolve_context(session, trust_tier=trust_tier)

    # Check credential satisfaction using resolved active_skills
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message, resolved=resolved,
    )
    if credential_env is None:
        return

    # Always include the chat-specific upload dir (not the shared uploads tree)
    # plus resolved extra_dirs from execution context and any denial dirs from retries
    upload_dir = str(chat_upload_dir(cfg.data_dir, _conversation_key(chat_id)))
    all_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs) + (extra_dirs or [])

    # Stage Codex scripts before building context so scripts_dir is in extra_dirs
    if prov.name == "codex":
        scripts_dir = stage_codex_scripts(
            cfg.data_dir,
            _conversation_key(chat_id),
            resolved.active_skills,
        )
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    # Build execution context (includes all extra_dirs, including staged scripts)
    context = build_run_context(
        resolved.role, resolved.active_skills, all_extra_dirs,
        provider_name=prov.name,
        credential_env=credential_env, working_dir=resolved.working_dir,
        file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
    )
    context.skip_permissions = skip_permissions

    # Compact mode: add summary-first instruction to system prompt
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and context.system_prompt:
        context.system_prompt += (
            "\n\nIMPORTANT: Structure your response with a 2-4 line summary first, "
            "then provide detailed explanation below. Lead with the answer."
        )
    elif compact:
        context.system_prompt = (
            "Structure your response with a 2-4 line summary first, "
            "then provide detailed explanation below. Lead with the answer."
        )

    # Use the single authoritative context hash
    context_hash = resolved.context_hash

    # Codex thread invalidation: start fresh thread when context drifted or bot restarted.
    if prov.name == "codex":
        stored_hash = session.provider_state.get("context_hash")
        stored_boot = session.provider_state.get("boot_id")
        stale_thread = (
            (stored_hash and stored_hash != context_hash)
            or (stored_boot and stored_boot != _boot_id)
        )
        if stale_thread and session.provider_state.get("thread_id"):
            log.info("Clearing stale codex thread for chat %d (hash_match=%s, boot_match=%s)",
                     chat_id, stored_hash == context_hash, stored_boot == _boot_id)
            session.provider_state["thread_id"] = None
        session.provider_state["context_hash"] = context_hash
        session.provider_state["boot_id"] = _boot_id
        _save(chat_id, session)

    is_resume = bool(session.provider_state.get("thread_id") or session.provider_state.get("started"))
    label = _msg.progress_resuming() if is_resume else _msg.progress_working()
    conversation_ref = ""
    routed_task_id = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "surface_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
        routed_task_id = getattr(message, "routed_task_id", "")
    elif cfg.agent_mode == "registry":
        conversation_ref = telegram_conversation_ref(cfg, chat_id)

    timeline_cb = None
    surface_name = getattr(getattr(message, "capabilities", None), "surface_name", "telegram")
    if conversation_ref and surface_name != "registry":
        timeline_cb = lambda html_text, force=False: _progress_timeline_callback(
            conversation_ref, routed_task_id, html_text, force=force
        )

    status_msg = await message.reply_text(label)
    progress = TelegramProgress(status_msg, cfg, timeline_callback=timeline_cb)
    content_started = asyncio.Event()
    progress.content_started = content_started  # providers set this when real text arrives
    typing_task = asyncio.create_task(keep_typing(message.chat))
    heartbeat_task = asyncio.create_task(_heartbeat(progress, content_started))

    local_cancel_event = cancel_event or asyncio.Event()
    _LIVE_CANCEL[chat_id] = local_cancel_event
    try:
        result = await prov.run(
            session.provider_state,
            prompt,
            image_paths,
            progress,
            context=context,
            cancel=local_cancel_event,
        )
    finally:
        _LIVE_CANCEL.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    if result.cancelled:
        # Persist provider_state_updates so thread/session continuity is not lost.
        session = _load(chat_id)
        session.provider_state.update(result.provider_state_updates)
        _save(chat_id, session)
        await progress.update(_msg.cancel_live_completed(), force=True)
        return RequestExecutionOutcome(status="cancelled")

    if _run_result_was_interrupted(result.returncode):
        log.info("%s interrupted for chat %d (rc=%s); leaving work item claimed",
                 prov.name, chat_id, result.returncode)
        raise work_queue.LeaveClaimed()

    # Re-load session to pick up any changes made while the provider was running
    session = _load(chat_id)
    session.provider_state.update(result.provider_state_updates)

    # Typed resume failure: provider proved the resume target is dead/invalid.
    # Generic errors during a healthy resumed session do NOT trigger a reset.
    if result.resume_failed:
        log.warning("%s resume target invalid (rc=%s) for chat %d — resetting session state",
                     prov.name, result.returncode, chat_id)
        if prov.name == "codex":
            session.provider_state["thread_id"] = None
        else:
            session.provider_state.update(prov.new_provider_state())

    # Codex also clears thread_id on any resume error (existing behavior).
    elif (
        prov.name == "codex"
        and is_resume
        and not result.timed_out
        and result.returncode and result.returncode != 0
    ):
        log.warning("codex resume error (rc=%s) for chat %d — clearing thread_id",
                     result.returncode, chat_id)
        session.provider_state["thread_id"] = None

    _save(chat_id, session)

    if result.timed_out:
        await progress.update(_msg.progress_request_timed_out(cfg.timeout_seconds), force=True)
        return RequestExecutionOutcome(status="timed_out")

    if result.returncode != 0:
        error_text = await _format_provider_error(result.text, result.returncode)
        if result.resume_failed:
            error_text += _msg.progress_session_not_resumed()
        await progress.update(error_text, force=True)
        return RequestExecutionOutcome(status="failed", error_text=error_text)

    # Claude denial/retry flow — show denials BEFORE output so the user
    # understands the result is partial before reading it.
    if result.denials:
        await progress.update(_msg.progress_completed_with_blocked(), force=True)

        session = _load(chat_id)
        session.pending_retry = PendingRetry(
            request_user_id=request_user_id,
            prompt=prompt,
            image_paths=image_paths,
            context_hash=context_hash,
            denials=result.denials,
            trust_tier=trust_tier,
            created_at=time.time(),
        )
        _save(chat_id, session)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("\u2705 " + _msg.retry_button_grant(), callback_data="retry_allow"),
            InlineKeyboardButton("\u274c " + _msg.retry_button_skip(), callback_data="retry_skip"),
        ]])
        await message.chat.send_message(
            f"\u26a0\ufe0f <b>{_msg.retry_permission_prompt()}</b>\n"
            f"{format_denials_html(result.denials)}\n\n"
            f"{_msg.retry_grant_and_retry_question()}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

        cleaned_reply, directives = extract_send_directives(result.text)
        if cleaned_reply.strip():
            await send_formatted_reply(message, cleaned_reply)
            await send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
        return RequestExecutionOutcome(
            status="completed_with_denials",
            reply_text=cleaned_reply,
            denials=tuple(result.denials),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
        )

    if result.delegation_tasks:
        await progress.update("Delegation plan ready.", force=True)
        session = _load(chat_id)
        return await _propose_delegation_plan(
            chat_id,
            message,
            session,
            conversation_ref=conversation_ref or telegram_conversation_ref(cfg, chat_id),
            result=result,
        )

    await progress.update(_msg.progress_completed(), force=True)

    cleaned_reply, directives = extract_send_directives(result.text)

    # Save raw response to ring buffer for /raw retrieval
    from app.summarize import load_raw_by_slot
    slot = save_raw(cfg.data_dir, _conversation_key(chat_id), prompt, cleaned_reply)

    # Compact mode: use expandable blockquote or inline expand for long responses
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and len(cleaned_reply) > 800:
        await _send_compact_reply(message, cleaned_reply, chat_id, slot)
    else:
        await send_formatted_reply(message, cleaned_reply)
    await send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
    return RequestExecutionOutcome(
        status="completed",
        reply_text=cleaned_reply,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
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
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    if session.has_pending:
        await message.reply_text(_msg.approval_already_waiting())
        return

    # Resolve the authoritative execution identity once
    resolved = _resolve_context(session, trust_tier=trust_tier)

    # Check credential satisfaction using resolved active_skills
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message, resolved=resolved,
    )
    if credential_env is None:
        return

    # Build preflight context (include config extra_dirs + upload dir)
    upload_dir = str(chat_upload_dir(cfg.data_dir, _conversation_key(chat_id)))
    preflight_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs)
    preflight_context = build_preflight_context(
        resolved.role, resolved.active_skills, preflight_extra_dirs,
        provider_name=prov.name,
        working_dir=resolved.working_dir, file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
    )

    # Use the single authoritative context hash
    context_hash = resolved.context_hash

    status_msg = await message.reply_text(_msg.approval_preparing())
    conversation_ref = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "surface_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
    elif cfg.agent_mode == "registry":
        conversation_ref = telegram_conversation_ref(cfg, _telegram_chat_id(chat_id))
    timeline_cb = None
    surface_name = getattr(getattr(message, "capabilities", None), "surface_name", "telegram")
    if conversation_ref and surface_name != "registry":
        timeline_cb = lambda html_text, force=False: _progress_timeline_callback(
            conversation_ref, "", html_text, force=force
        )
    progress = TelegramProgress(status_msg, cfg, timeline_callback=timeline_cb)
    content_started = asyncio.Event()
    progress.content_started = content_started
    typing_task = asyncio.create_task(keep_typing(message.chat))
    heartbeat_task = asyncio.create_task(_heartbeat(progress, content_started))

    preflight_prompt = build_preflight_prompt(prompt, prov.name)
    local_cancel_event = cancel_event or asyncio.Event()
    _LIVE_CANCEL[chat_id] = local_cancel_event
    try:
        plan_result = await prov.run_preflight(
            preflight_prompt,
            image_paths,
            progress,
            context=preflight_context,
            cancel=local_cancel_event,
        )
    finally:
        _LIVE_CANCEL.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    if plan_result.cancelled:
        await progress.update(_msg.cancel_live_completed(), force=True)
        return

    if _run_result_was_interrupted(plan_result.returncode):
        log.info("Preflight interrupted for chat %d (rc=%s); leaving work item claimed",
                 chat_id, plan_result.returncode)
        raise work_queue.LeaveClaimed()

    if plan_result.timed_out:
        await progress.update(_msg.approval_timeout(), force=True)
        return

    if plan_result.returncode != 0:
        error_text = await _format_provider_error(plan_result.text, plan_result.returncode)
        await progress.update(f"{_msg.approval_check_failed_prefix()}\n{error_text}", force=True)
        return

    attachment_dicts = [
        {"path": str(a.path), "original_name": a.original_name, "is_image": a.is_image}
        for a in attachments
    ]
    session.pending_approval = PendingApproval(
        request_user_id=request_user_id,
        prompt=prompt,
        image_paths=image_paths,
        attachment_dicts=attachment_dicts,
        context_hash=context_hash,
        trust_tier=trust_tier,
        created_at=time.time(),
    )
    _save(chat_id, session)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 " + _msg.approval_button_approve(), callback_data="approval_approve"),
        InlineKeyboardButton("\u274c " + _msg.approval_button_reject(), callback_data="approval_reject"),
    ]])
    await progress.update(_msg.approval_required(), force=True)
    plan_text = plan_result.text or "[empty plan]"
    save_raw(cfg.data_dir, _conversation_key(chat_id), prompt, plan_text, kind="approval")
    await send_formatted_reply(
        message,
        "**Approval plan:**\n\n" + plan_text,
    )
    await message.chat.send_message(_msg.approval_plan_question(), reply_markup=keyboard)


async def approve_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    session = _load(chat_id)
    pending = session.pending_approval or session.pending_retry
    if not pending:
        await message.reply_text(_msg.approval_no_pending_approve())
        return

    state = "pending_approval" if session.pending_approval else "pending_retry"
    classification = classify_pending_validation(pending, session, _cfg(), _prov().name)
    event = (
        "approve_execute" if classification == "ok"
        else "expire" if classification == "expired"
        else "invalidate_stale"
    )
    model = PendingRequestWorkflowModel(state=state, validation_result=classification)
    result = run_pending_request_event(model, event, validation_result=classification)

    if not result.allowed:
        session.clear_pending()
        _save(chat_id, session)
        error = validate_pending(pending, session, _cfg(), _prov().name)
        await message.reply_text(error or _msg.approval_request_no_longer_valid())
        return

    if result.disposition != PendingRequestDisposition.executed:
        session.clear_pending()
        _save(chat_id, session)
        error = validate_pending(pending, session, _cfg(), _prov().name)
        await message.reply_text(error or _msg.approval_request_no_longer_valid())
        return

    denials = getattr(pending, "denials", None) or []
    denial_dirs = extra_dirs_from_denials(denials) if denials else None
    request_user_id = pending.request_user_id
    trust_tier = getattr(pending, "trust_tier", "trusted")
    session.clear_pending()
    _save(chat_id, session)
    await execute_request(
        chat_id, pending.prompt, pending.image_paths, message,
        extra_dirs=denial_dirs,
        request_user_id=request_user_id,
        skip_permissions=True,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
    )


async def reject_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    if not session.has_pending:
        await message.reply_text(_msg.approval_no_pending_reject())
        return
    state = "pending_approval" if session.pending_approval else "pending_retry"
    model = PendingRequestWorkflowModel(state=state)
    run_pending_request_event(model, "reject")
    session.clear_pending()
    _save(chat_id, session)
    await message.reply_text(_msg.approval_rejected())


async def retry_skip_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    session.clear_pending()
    _save(chat_id, session)
    await _edit_or_reply_text(message, _msg.retry_skip_confirmation())


async def retry_allow_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
) -> None:
    session = _load(chat_id)
    pending = session.pending_retry
    if not pending:
        await _edit_or_reply_text(message, _msg.retry_nothing_pending())
        return

    classification = classify_pending_validation(pending, session, _cfg(), _prov().name)
    event_name = (
        "approve_execute" if classification == "ok"
        else "expire" if classification == "expired"
        else "invalidate_stale"
    )
    model = PendingRequestWorkflowModel(state="pending_retry", validation_result=classification)
    result = run_pending_request_event(model, event_name, validation_result=classification)

    if not result.allowed or result.disposition != PendingRequestDisposition.executed:
        session.clear_pending()
        _save(chat_id, session)
        error = validate_pending(pending, session, _cfg(), _prov().name)
        await _edit_or_reply_text(message, error or _msg.approval_request_no_longer_valid())
        return

    prompt = pending.prompt
    denials = pending.denials or []
    request_user_id = pending.request_user_id
    trust_tier = getattr(pending, "trust_tier", "trusted")
    session.clear_pending()

    denial_dirs = extra_dirs_from_denials(denials)

    if denial_dirs and _prov().name == "codex":
        session.provider_state["thread_id"] = None

    _save(chat_id, session)

    await execute_request(
        chat_id, prompt, pending.image_paths,
        message, denial_dirs,
        request_user_id=request_user_id,
        skip_permissions=True,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
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
    conversation_ref = telegram_conversation_ref(_cfg(), chat_id)
    await handle_surface_delegation_approve(
        chat_id,
        conversation_ref,
        _DelegationCallbackSurface(query),
        retry_markup=_delegation_keyboard(chat_id),
    )


async def _handle_delegation_cancel(chat_id: int, query) -> None:
    conversation_ref = telegram_conversation_ref(_cfg(), chat_id)
    await handle_surface_delegation_cancel(
        chat_id,
        conversation_ref,
        _DelegationCallbackSurface(query),
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
        "/role &lt;text&gt; — set the AI's persona (e.g. <code>/role Python expert</code>)",
        "/approval on|off — show a plan before executing, or run immediately",
        "/approve / /reject — act on a pending plan",
        "/cancel — cancel a running task, credential setup, or a pending request",
        "/clear_credentials — remove your stored credentials",
        "/send &lt;path&gt; — retrieve a file from the server",
        "/compact on|off — toggle short/full answers",
    ]
    if _cfg().model_profiles:
        lines.append("/model — switch model profile (fast/balanced/best)")
    if _cfg().agent_mode == "registry":
        lines.append("/discover — find available specialist bots by role, skill, or tag")
    if not is_public_user(user):
        lines.append("/policy inspect|edit — set file access policy")
    lines.extend([
        "/settings — view and change chat settings",
    ])
    if not is_public_user(user) and _cfg().projects:
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
    cfg = _cfg()
    provider = _prov().name.capitalize()
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
    "/skills clear — deactivate all skills"
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
    chat_id = event.chat_id
    cfg = _cfg()
    prov = _prov()
    async with _chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        old_session = _load(chat_id)
        user_id = event.user.id
        if foreign_skill_setup(old_session, _actor_key(user_id)):
            await update.effective_message.reply_text(
                foreign_setup_message(old_session.awaiting_skill_setup),
            )
            return
        if old_session.approval_mode_explicit:
            approval_mode = old_session.approval_mode
        else:
            approval_mode = cfg.approval_mode
        session = session_from_dict(default_session(prov.name, prov.new_provider_state(), approval_mode, cfg.role, cfg.default_skills))
        if old_session.approval_mode_explicit:
            session.approval_mode_explicit = True
        _save(chat_id, session)
        # Clean up any staged Codex scripts for this chat
        cleanup_codex_scripts(cfg.data_dir, _conversation_key(chat_id))
    await update.effective_message.reply_text(f"Fresh {prov.name} conversation started.")


@_command_handler
async def cmd_session(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _load(event.chat_id)
    cfg = _cfg()
    trust = _trust_tier(event.user)
    resolved = _resolve_context(session, trust_tier=trust)
    pstate = session.provider_state

    # Show provider-relevant session ID
    if _prov().name == "claude":
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
    from app.skills import build_system_prompt
    sys_prompt = build_system_prompt(resolved.role, resolved.active_skills)
    prompt_weight = f"~{len(sys_prompt)} chars" if sys_prompt else "minimal"

    body = (
        f"Provider: <code>{html.escape(_prov().name)}</code>\n"
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
    cfg = _cfg()
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
    chat_id = event.chat_id
    arg = (event.args[0].lower() if event.args else "status")
    if arg not in {"on", "off", "status"}:
        await update.effective_message.reply_text(_msg.approval_usage())
        return
    async with _chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(chat_id)
        if arg == "status":
            mode = session.approval_mode
            source = _approval_mode_source(session)
            await update.effective_message.reply_text(
                f"Approval mode is <b>{mode}</b> ({source}).",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([_settings_approval_buttons(mode)]),
            )
            return
        _apply_approval_change(chat_id, session, arg)
    await update.effective_message.reply_text(
        f"Approval mode set to {arg} for this chat."
    )


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
    from app.doctor import collect_runtime_health, format_doctor_report_lines
    try:
        session = _load(event.chat_id)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, RuntimeError):
        session = None
    cfg = _cfg()
    kwargs: dict[str, Any] = {}
    if session is not None:
        kwargs.update(session=session_to_dict(session), user_id=event.user.id,
                      encryption_key=_encryption_key())
    report = await collect_runtime_health(
        cfg, _prov(), caller_is_bot=True, **kwargs)
    parts: list[str] = []
    for line in format_doctor_report_lines(report):
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
        from app.skills import build_system_prompt
        resolved = _resolve_context(session, trust_tier=_trust_tier(event.user))
        sys_prompt = build_system_prompt(resolved.role, resolved.active_skills)
        if sys_prompt:
            parts.append(f"Prompt weight: ~{len(sys_prompt)} chars")
    if parts:
        await update.effective_message.reply_text(
            "\n".join(parts), parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("\u2705 All checks passed.")


def _discover_usage() -> str:
    return (
        "Usage: /discover <query> [role:<role>] [skill:<skill>] [tag:<tag>] [state:<connected|degraded|standalone|offline>]\n"
        "Example: <code>/discover role:developer skill:python tag:backend schema review</code>"
    )


def _parse_discovery_query(
    args: tuple[str, ...],
    *,
    exclude_agent_id: str = "",
) -> tuple[AgentDiscoveryQuery | None, str | None]:
    role = ""
    skills: list[str] = []
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
        elif key in {"skill", "skills"}:
            skills.extend(part.strip() for part in value.split(",") if part.strip())
        elif key in {"tag", "tags"}:
            tags.extend(part.strip() for part in value.split(",") if part.strip())
        elif key == "state":
            required_state = value.lower()
        else:
            free_text_parts.append(token)
    if required_state not in {"connected", "degraded", "standalone", "offline"}:
        return None, _discover_usage()
    if not role and not skills and not tags and not free_text_parts:
        return None, _discover_usage()
    return (
        AgentDiscoveryQuery(
            role=role,
            skills=tuple(skills),
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
        skills = [str(skill) for skill in agent.get("skills", []) if skill]
        if skills:
            lines.append(f"Skills: <code>{html.escape(', '.join(skills))}</code>")
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
    cfg = _cfg()
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
    cfg = _cfg()

    history = export_chat_history(cfg.data_dir, _conversation_key(chat_id))
    if not history:
        await update.effective_message.reply_text(_msg.no_conversation_to_export())
        return

    # Add session metadata header — use resolved context for user-visible data
    session = _load(chat_id)
    trust = _trust_tier(normalize_user(update.effective_user))
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

    cfg = _cfg()
    sessions = list_sessions(cfg.data_dir)

    if not sessions:
        await update.effective_message.reply_text(_msg.no_sessions_found())
        return

    # Filter stale active_skills that no longer resolve
    from app.skills import filter_resolvable_skills
    for s in sessions:
        s["active_skills"] = filter_resolvable_skills(s["active_skills"])

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
    from app.skill_commands import (
        skills_show, skills_list, skills_add, skills_remove,
        skills_setup, skills_clear, skills_create, skills_search,
        skills_info, skills_install, skills_uninstall, skills_updates,
        skills_diff, skills_update,
    )
    args = event.args
    if not args:
        await skills_show(event, update)
        return

    sub = args[0].lower()
    _SUBS_WITH_ARG = {
        "add": skills_add, "remove": skills_remove, "setup": skills_setup,
        "create": skills_create, "info": skills_info, "install": skills_install,
        "uninstall": skills_uninstall, "diff": skills_diff,
    }
    if sub in _SUBS_WITH_ARG and len(args) >= 2:
        await _SUBS_WITH_ARG[sub](event, update, args[1])
        return
    if sub == "list":
        await skills_list(event, update)
        return
    if sub == "clear":
        await skills_clear(event, update)
        return
    if sub == "search" and len(args) >= 2:
        await skills_search(event, update, " ".join(args[1:]))
        return
    if sub == "updates":
        await skills_updates(event, update)
        return
    if sub == "update" and len(args) >= 2:
        await skills_update(event, update, args[1])
        return

    await update.effective_message.reply_text(
        "Usage: /skills [list|add|remove|setup|create|clear|search|info|install|uninstall|updates|update|diff]"
    )


@_command_handler
async def cmd_cancel(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    await cancel_chat_operation(
        event.chat_id,
        update.effective_message,
        actor_user_id=event.user.id,
        allow_admin_override=is_admin(event.user),
        update_id=update.update_id,
    )


async def cancel_chat_operation(
    chat_id: int | str,
    message,
    *,
    actor_user_id: int | str = "",
    allow_admin_override: bool = False,
    update_id: int | None = None,
) -> None:
    # Worker-owned live run: set cancel event so the running execute_request/request_approval sees it.
    cancel_event = _LIVE_CANCEL.get(chat_id)
    if cancel_event is not None:
        cancel_event.set()
        await message.reply_text(_msg.cancel_live_requested())
        return

    # Admitted but not yet running: cancel queued fresh item so the worker won't run it.
    if work_queue.cancel_queued_fresh_for_chat(_cfg().data_dir, _conversation_key(chat_id)):
        await message.reply_text(_msg.cancel_queued_superseded())
        return

    async with _chat_lock(chat_id, message=message, update_id=update_id):
        session = _load(chat_id)

        setup = session.awaiting_skill_setup
        if setup:
            if setup.user_id == _actor_key(actor_user_id) or allow_admin_override:
                session.awaiting_skill_setup = None
                _save(chat_id, session)
                await message.reply_text(_msg.credential_setup_cancelled())
                return
            else:
                await message.reply_text(
                    _msg.credential_setup_another_user_in_progress(),
                )
                return

        if session.has_pending:
            session.clear_pending()
            _save(chat_id, session)
            await message.reply_text(_msg.cancel_pending_request())
            return

    await message.reply_text(_msg.nothing_to_cancel())


@_command_handler
async def cmd_clear_credentials(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    user_id = telegram_numeric_id(_actor_key(event.user.id)) or 0
    args = event.args
    skill_name = args[0] if args else None

    cfg = _cfg()
    stored = list_user_credential_skills(cfg.data_dir, _actor_key(user_id))

    if skill_name:
        if skill_name not in stored:
            await update.effective_message.reply_text(
                f"No stored credentials for <code>{html.escape(skill_name)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        affected = [skill_name]
        msg = (f"This will remove your credentials for "
               f"<code>{html.escape(skill_name)}</code> and deactivate it "
               f"in this chat. Continue?")
        cb_data = f"clear_cred_confirm:{user_id}:{skill_name}"
    else:
        if not stored:
            await update.effective_message.reply_text("No stored credentials found.")
            return
        affected = stored
        names = html.escape(", ".join(affected))
        msg = (f"This will remove all your stored credentials "
               f"({names}) and deactivate affected skills. Continue?")
        cb_data = f"clear_cred_confirm_all:{user_id}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, clear", callback_data=cb_data),
        InlineKeyboardButton("Cancel", callback_data=f"clear_cred_cancel:{user_id}"),
    ]])
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML,
                                              reply_markup=keyboard)


async def _execute_clear_credentials(
    query, chat_id: int, user_id: int, skill_name: str | None,
) -> None:
    """Shared logic for clearing credentials after confirmation."""
    cfg = _cfg()
    key = _encryption_key()
    removed = delete_user_credentials(cfg.data_dir, _actor_key(user_id), key, skill_name)

    # Clear in-progress setup even if no credentials were saved yet
    setup_cleared = False
    async with _chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = _load(chat_id)
        setup = session.awaiting_skill_setup
        if setup and setup.user_id == _actor_key(user_id):
            if skill_name is None or setup.skill == skill_name:
                session.awaiting_skill_setup = None
                setup_cleared = True

        active = session.active_skills
        deactivated = []
        for name in removed:
            if name in active and get_skill_requirements(name):
                active.remove(name)
                deactivated.append(name)
        if deactivated or setup_cleared:
            _save(chat_id, session)

    parts = []
    if removed:
        parts.append(f"Credentials cleared for: {html.escape(', '.join(removed))}.")
    if setup_cleared:
        parts.append(_msg.credential_setup_cancelled())
    if deactivated:
        parts.append(f"Deactivated in this chat: {html.escape(', '.join(deactivated))}.")
    if not parts:
        parts.append("No credentials to clear (may have already been removed).")
    await query.edit_message_text("\n".join(parts), parse_mode=ParseMode.HTML)


@_callback_handler
async def handle_clear_cred_callback(event, query) -> None:
    chat_id = event.chat_id
    clicker_id = telegram_numeric_id(_actor_key(event.user.id)) or 0

    # All callback data encodes the initiating user: clear_cred_<action>:<uid>[:<skill>]
    # Reject if a different user clicks the button.
    parts = event.data.split(":")
    # parts[0] = "clear_cred_cancel" | "clear_cred_confirm" | "clear_cred_confirm_all"
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
        await _execute_clear_credentials(query, chat_id, clicker_id, None)
        return

    if parts[0] == "clear_cred_confirm" and len(parts) >= 3:
        skill_name = parts[2]
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, skill_name)
        return


@_command_handler
async def cmd_compact(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(chat_id)
        current = session.compact_mode if session.compact_mode is not None else _cfg().compact_mode
        state = "on" if current else "off"
        await update.effective_message.reply_text(
            f"Compact mode is <b>{state}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([_settings_compact_buttons(current)]),
        )
        return

    mode = args[0].lower()
    if mode not in {"on", "off"}:
        await update.effective_message.reply_text("Usage: /compact on|off")
        return

    async with _chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(chat_id)
        _apply_compact_change(chat_id, session, mode == "on")

    label = _msg.settings_compact_on_label() if mode == "on" else _msg.settings_compact_off_label()
    await update.effective_message.reply_text(
        f"Compact mode set to <b>{label}</b>.", parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_raw(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _cfg()
    args = event.args

    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            await update.effective_message.reply_text("Usage: /raw [N] — N is the Nth most recent response (default: 1)")
            return

    raw_text = load_raw(cfg.data_dir, _conversation_key(chat_id), n)
    if raw_text is None:
        await update.effective_message.reply_text("No stored responses found.")
        return

    await send_formatted_reply(update.effective_message, raw_text)


@_command_handler
async def cmd_role(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(chat_id)
        role = session.role
        if role:
            await update.effective_message.reply_text(
                f"Current role: <code>{html.escape(role)}</code>", parse_mode=ParseMode.HTML,
            )
        else:
            await update.effective_message.reply_text("No role set (using instance default).")
        return

    if args[0].lower() == "clear":
        cfg = _cfg()
        async with _chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
            session = _load(chat_id)
            session.role = cfg.role
            _save(chat_id, session)
        await update.effective_message.reply_text("Role reset to instance default.")
        return

    role_text = " ".join(args)
    async with _chat_lock(chat_id, message=update.effective_message, update_id=update.update_id):
        session = _load(chat_id)
        session.role = role_text
        _save(chat_id, session)
    await update.effective_message.reply_text(
        f"Role set to: <code>{html.escape(role_text)}</code>", parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_model(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg()
    msg = update.effective_message
    chat_id = event.chat_id

    arg = event.args[0].lower() if event.args else ""

    # inherit must run even when model_profiles is empty — clears stale overrides
    if arg == "inherit":
        trust = _trust_tier(event.user)
        async with _chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = _load(chat_id)
            if not session.model_profile:
                await msg.reply_text("Model profile is already inherited.", parse_mode=ParseMode.HTML)
                return
            _apply_model_change(chat_id, session, "")
        resolved = _resolve_context(_load(chat_id), trust)
        effective = resolved.effective_model or cfg.model
        _, profile_name = _settings_model_profile_state(_load(chat_id), cfg, trust, effective or "")
        if effective and profile_name != "(default)":
            cleared_text = f"Model profile cleared. Effective: <code>{html.escape(profile_name)}</code> ({html.escape(effective)})"
        elif effective:
            cleared_text = f"Model profile cleared. Using default model."
        else:
            cleared_text = "Model profile cleared. Using default model."
        await msg.reply_text(
            cleared_text,
            parse_mode=ParseMode.HTML,
        )
        return

    if not cfg.model_profiles:
        session = _load(chat_id)
        if session.model_profile:
            await msg.reply_text(
                f"No model profiles configured, but this chat has a stale override "
                f"(<code>{html.escape(session.model_profile)}</code>). "
                "Use /model inherit to clear it.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.reply_text(_msg.trust_no_model_profiles())
        return

    trust = _trust_tier(event.user)
    session = _load(chat_id)
    resolved = _resolve_context(session, trust)
    effective = resolved.effective_model
    available, current = _settings_model_profile_state(session, cfg, trust, effective or "")

    if arg and arg != "status":
        async with _chat_lock(chat_id, message=msg, update_id=update.update_id):
            session = _load(chat_id)
            _ok, text = _apply_model_selection(chat_id, session, arg, cfg, trust)
        await msg.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Show current + inline keyboard (same effective-profile source as /settings)
    buttons = _settings_model_buttons(available, current, has_explicit_override=bool(session.model_profile))
    text = (
        f"Model profile: <b>{html.escape(current)}</b>\n"
        f"Effective model: <code>{html.escape(effective or cfg.model or '(default)')}</code>"
    )
    if buttons:
        text += "\n\n" + _msg.model_choose_profile_hint()
        await msg.reply_text(text, parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup([buttons]))
    else:
        await msg.reply_text(text, parse_mode=ParseMode.HTML)


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

    if _rate_limiter and _rate_limiter.enabled and not (_cfg().admin_users_explicit and is_admin(user)):
        allowed, retry_after = _rate_limiter.check(user.id)
        if not allowed:
            await update.effective_message.reply_text(
                f"Rate limit reached. Please wait {retry_after} seconds.")
            return

    msg = await normalize_message(update, context, _cfg().data_dir)
    if msg is None:
        return

    message = update.effective_message
    chat_id = msg.chat_id
    user_id = user.id
    prompt, image_paths = build_user_prompt(msg.text, list(msg.attachments))
    payload = serialize_inbound(msg)

    cfg = _cfg()
    if not session_exists(cfg.data_dir, _conversation_key(chat_id)):
        welcome = "I'm ready. Send me a message or type /help to see what I can do."
        if cfg.approval_mode == "on":
            welcome += "\nApproval mode is on \u2014 I'll show a plan before acting."
        effective_compact = cfg.compact_mode
        if effective_compact:
            welcome += "\nCompact mode is on \u2014 long answers are summarized. Use /compact off for full answers."
        await message.chat.send_message(welcome)

    data_dir = cfg.data_dir
    session = _load(chat_id)
    setup = session.awaiting_skill_setup
    if setup and setup.user_id == _actor_key(user_id):
        # Credential setup: record update for dedupe only; handle inline. No work item so worker
        # never sees this message as provider work (avoids race and secret-leak path).
        if not work_queue.record_update(
            data_dir,
            _event_key(uid),
            _conversation_key(chat_id),
            _actor_key(user_id),
            "message",
            payload=payload,
        ):
            return  # duplicate update_id
        try:
            async with _chat_lock(chat_id, message=message, update_id=uid, supersede_recovery=True):
                session = _load(chat_id)
                setup = session.awaiting_skill_setup
                if not setup or setup.user_id != _actor_key(user_id):
                    return
                await message.chat.send_action(ChatAction.TYPING)
                req = setup.remaining[0]
                raw_value = (message.text or "").strip()
                if not raw_value:
                    await message.reply_text("Please send the credential value as a text message.")
                    return
                if req.get("validate"):
                    ok, detail = await validate_credential(
                        SkillRequirement(key=req["key"], prompt=req["prompt"],
                                         help_url=req.get("help_url"), validate=req["validate"]),
                        raw_value,
                    )
                    if not ok:
                        try:
                            await message.delete()
                        except Exception:
                            log.warning("Could not delete credential message for user %d", user_id)
                        await message.reply_text(
                            f"Credential validation failed for <code>{html.escape(req['key'])}</code>: "
                            f"{html.escape(detail)}\nPlease try again.",
                            parse_mode=ParseMode.HTML,
                        )
                        return
                save_user_credential(
                    cfg.data_dir, user_id, setup.skill, req["key"], raw_value, _encryption_key(),
                )
                try:
                    await message.delete()
                except Exception:
                    log.warning("Could not delete credential message for user %d", user_id)
                setup.remaining.pop(0)
                if setup.remaining:
                    next_req = setup.remaining[0]
                    _save(chat_id, session)
                    await message.reply_text(
                        format_credential_prompt(next_req),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    skill_name = setup.skill
                    session.awaiting_skill_setup = None
                    if skill_name not in session.active_skills:
                        session.active_skills.append(skill_name)
                    _save(chat_id, session)
                    await message.reply_text(
                        f"Skill <code>{html.escape(skill_name)}</code> is ready.",
                        parse_mode=ParseMode.HTML,
                    )
        except Exception:
            raise
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
    chat_id = event.chat_id

    async with _chat_lock(chat_id, query=query) as already_answered:
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
    """Handle Replay / Discard buttons from post-restart recovery notices.

    This handler bypasses ``_callback_handler`` because:
    - The callback's own update_id should not create a work item.
    - Replay creates a fresh execution with ``_chat_lock`` using the
      recovered item, not the callback's update.
    """
    query = update.callback_query
    user = access.to_inbound_user(update.effective_user)
    if user is None or not is_allowed(user):
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

    chat_id = update.effective_chat.id
    await handle_recovery_action(
        chat_id,
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
    if answer_action is None:
        async def answer_action(text=None, show_alert=False):
            del text, show_alert
            return None

    cfg = _cfg()
    data_dir = cfg.data_dir

    try:
        recovery_item = work_queue.get_pending_recovery_for_update(
            data_dir,
            _conversation_key(chat_id),
            _event_key(update_id),
        )
    except TransportStateCorruption as e:
        log.exception("Transport state corruption in recovery callback for chat %s: %s", chat_id, e)
        await answer_action(_msg.recovery_error_try_again(), show_alert=True)
        return

    if recovery_item is None:
        # Already handled (double-click, superseded, etc.) — idempotent.
        await answer_action(_msg.recovery_already_handled())
        return

    # -- Discard path --
    if action == "recovery_discard":
        try:
            discard_outcome = work_queue.discard_recovery(data_dir, recovery_item["id"])
        except TransportStateCorruption as e:
            log.exception("Transport state corruption on discard for item %s: %s", recovery_item["id"], e)
            await answer_action(_msg.recovery_error_try_again(), show_alert=True)
            return
        if discard_outcome == work_queue.DiscardResult.already_handled:
            await answer_action(_msg.recovery_already_handled())
            return
        if discard_outcome == work_queue.DiscardResult.corruption:
            await answer_action(_msg.recovery_error_discard_try_again())
            return
        await answer_action(_msg.recovery_discarded_confirm())
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_discarded_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # -- Replay path --
    if action != "recovery_replay":
        await answer_action(_msg.recovery_unknown_action())
        return

    await answer_action(_msg.recovery_replaying_toast())

    # Reclaim the item for replay execution.
    try:
        item = work_queue.reclaim_for_replay(
            data_dir,
            recovery_item["id"],
            _boot_id,
            ignore_claimed_item_id=str(getattr(message, "_worker_item_id", "")),
        )
    except TransportStateCorruption as e:
        log.exception("Transport state corruption on reclaim for item %s: %s", recovery_item["id"], e)
        await answer_action(_msg.recovery_error_try_again(), show_alert=True)
        return
    except work_queue.ReclaimBlocked:
        # Another request is in progress — item is still pending_recovery.
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_blocked_replay_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return
    if item is None:
        # Race: already handled between our check and reclaim.
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_already_handled_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Retrieve original payload and deserialize.
    from app.transport import deserialize_inbound, InboundMessage
    payload_str = item.get("payload") or work_queue.get_update_payload(data_dir, _event_key(update_id))
    if not payload_str:
        work_queue.fail_work_item(data_dir, item["id"], error="payload_missing")
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_payload_missing_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    try:
        event = deserialize_inbound("message", payload_str)
    except Exception:
        work_queue.fail_work_item(data_dir, item["id"], error="deserialize_error")
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_replay_failed_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if not isinstance(event, InboundMessage):
        work_queue.fail_work_item(data_dir, item["id"], error="not_message")
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_replay_failed_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Update the notice to show replay is in progress.
    try:
        await _edit_or_reply_text(
            message,
            _msg.recovery_replaying_edit(),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Execute through _chat_lock with worker_item (lock-only, no claiming).
    prompt, image_paths = build_user_prompt(event.text, list(event.attachments))
    trust = factory.trust_tier_for_source(
        getattr(event, "source", "telegram"),
        event.user,
        config=_cfg(),
    )
    try:
        async with _chat_lock(chat_id, message=message, worker_item=item):
            session = _load(chat_id)
            if not getattr(event, "routed_task_id", "") and session.approval_mode == "on":
                await request_approval(
                    chat_id, prompt, image_paths, list(event.attachments),
                    message,
                    request_user_id=event.user.id,
                    trust_tier=trust,
                    cancel_event=cancel_event,
                )
            else:
                await execute_request(
                    chat_id, prompt, image_paths, message,
                    request_user_id=event.user.id,
                    trust_tier=trust,
                    cancel_event=cancel_event,
                )
        work_queue.complete_work_item(data_dir, item["id"])
    except work_queue.LeaveClaimed:
        # Replay interrupted by another restart — item stays claimed.
        # Next boot will recover it and send a new notice.
        log.warning("Replay interrupted for chat %d; item stays claimed for re-recovery", chat_id)
    except Exception:
        log.exception("Replay failed for chat %d", chat_id)
        work_queue.fail_work_item(data_dir, item["id"], error="replay_failed")
        try:
            await _edit_or_reply_text(
                message,
                _msg.recovery_replay_failed_edit(),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


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
    cfg = _cfg()
    raw_text = load_raw_by_slot(cfg.data_dir, _conversation_key(target_chat), slot)
    if raw_text is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.edit_text(
            "<i>Response no longer available (ring buffer rotated). Use /raw to check.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Replace the compact message with the full response
    formatted = md_to_telegram_html(raw_text)
    # If it fits in one message, edit in-place with a Collapse button
    if len(formatted) <= 4000:
        try:
            await query.message.edit_text(
                formatted, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "Collapse",
                        callback_data=f"collapse:{target_chat}:{slot}",
                    ),
                ]]),
            )
            return
        except BadRequest:
            pass
    # Too long to edit — send as new messages, remove button
    await query.edit_message_reply_markup(reply_markup=None)
    for chunk in split_html(formatted, 4096):
        try:
            await query.message.chat.send_message(
                chunk, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except BadRequest:
            plain = re.sub(r"<[^>]+>", "", chunk)
            await query.message.chat.send_message(plain[:4096])


@_callback_handler
async def handle_collapse_callback(event, query) -> None:
    """Handle 'Collapse' button presses — re-render compact view."""
    await query.answer()
    parsed = _parse_expand_collapse_data(event.data)
    if parsed is None:
        return
    target_chat, slot = parsed

    from app.summarize import load_raw_by_slot
    cfg = _cfg()
    raw_text = load_raw_by_slot(cfg.data_dir, _conversation_key(target_chat), slot)
    if raw_text is None:
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # Re-render compact version with "Show full answer" button
    summary, detail = _extract_summary(raw_text)
    formatted_summary = md_to_telegram_html(summary) if summary else ""
    button_text = f"{formatted_summary}\n\n<i>Response truncated</i>" if formatted_summary else "<i>Response truncated</i>"
    try:
        await query.message.edit_text(
            button_text[:4000], parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Show full answer",
                    callback_data=f"expand:{target_chat}:{slot}",
                ),
            ]]),
        )
    except BadRequest:
        await query.edit_message_reply_markup(reply_markup=None)


# -- Settings callback handler ---------------------------------------------


@_callback_handler
async def handle_settings_callback(event, query) -> None:
    """Handle inline-keyboard callbacks for session settings."""
    chat_id = event.chat_id
    data = event.data  # e.g. "setting_model:fast", "setting_approval:on"

    if not data.startswith("setting_"):
        await query.answer()
        return

    _, rest = data.split("_", 1)
    if ":" not in rest:
        await query.answer()
        return
    setting, value = rest.split(":", 1)

    async with _chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = _load(chat_id)

        if setting == "model":
            if value == "inherit":
                if not session.model_profile:
                    await query.edit_message_text("Model profile is already inherited.", parse_mode=ParseMode.HTML)
                    return
                _apply_model_change(chat_id, session, "")
                cfg = _cfg()
                trust = _trust_tier(event.user)
                resolved = _resolve_context(session, trust)
                effective = resolved.effective_model or cfg.model
                _, profile_name = _settings_model_profile_state(session, cfg, trust, effective or "")
                if effective and profile_name != "(default)":
                    cleared_text = f"Model profile cleared. Effective: <code>{html.escape(profile_name)}</code> ({html.escape(effective)})"
                elif effective:
                    cleared_text = f"Model profile cleared. Using default model."
                else:
                    cleared_text = "Model profile cleared. Using default model."
                await query.edit_message_reply_markup(reply_markup=None)
                await query.edit_message_text(cleared_text, parse_mode=ParseMode.HTML)
                return
            cfg = _cfg()
            if not cfg.model_profiles:
                await query.edit_message_text(_msg.trust_no_model_profiles())
                return
            trust = _trust_tier(event.user)
            _ok, text = _apply_model_selection(chat_id, session, value, cfg, trust)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML)

        elif setting == "approval":
            if value not in {"on", "off"}:
                return
            _apply_approval_change(chat_id, session, value)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"Approval mode set to {value} for this chat.")

        elif setting == "compact":
            _apply_compact_change(chat_id, session, value == "on")
            await query.edit_message_reply_markup(reply_markup=None)
            label = _msg.settings_compact_on_label() if value == "on" else _msg.settings_compact_off_label()
            await query.edit_message_text(
                f"Compact mode set to <b>{label}</b>.",
                parse_mode=ParseMode.HTML,
            )

        elif setting == "policy":
            if is_public_user(event.user):
                await query.edit_message_text(_msg.trust_file_policy_public())
                return
            if value == "inherit":
                if not session.file_policy:
                    await query.edit_message_text("File policy is already inherited.", parse_mode=ParseMode.HTML)
                    return
                _apply_policy_change(chat_id, session, "")
                resolved = _resolve_context(session, _trust_tier(event.user))
                effective = resolved.file_policy or "edit"
                await query.edit_message_reply_markup(reply_markup=None)
                await query.edit_message_text(
                    f"File policy cleared. Effective policy: <code>{html.escape(effective)}</code>",
                    parse_mode=ParseMode.HTML,
                )
                return
            if value not in {"inspect", "edit"}:
                return
            _apply_policy_change(chat_id, session, value)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                _msg.trust_file_policy_set(value),
                parse_mode=ParseMode.HTML,
            )

        elif setting == "project":
            if is_public_user(event.user):
                await query.edit_message_text(_msg.trust_project_public())
                return
            if not _cfg().projects:
                await query.edit_message_text(_msg.no_projects_configured())
                return
            ok, reply_text = _apply_project_change(chat_id, session, value)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(reply_text, parse_mode=ParseMode.HTML)


# -- Application builder ---------------------------------------------------


@_callback_handler
async def handle_skill_add_callback(event, query) -> None:
    chat_id = event.chat_id

    if event.data == "skill_add_cancel":
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Skill activation cancelled.")
        return

    if event.data.startswith("skill_add_confirm:"):
        name = event.data.split(":", 1)[1]
        async with _chat_lock(chat_id, query=query) as already_answered:
            if not already_answered:
                await query.answer()
            session = _load(chat_id)
            if name not in session.active_skills:
                session.active_skills.append(name)
                _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"Skill <code>{html.escape(name)}</code> activated.",
                parse_mode=ParseMode.HTML)


@_callback_handler
async def handle_skill_update_callback(event, query) -> None:
    if not is_admin(event.user):
        await query.answer("Only admins can update skills.", show_alert=True)
        return

    await query.answer()

    if event.data == "skill_update_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Update cancelled.")
        return

    if event.data.startswith("skill_update_confirm:"):
        from app.store import update_skill as store_update_skill
        name = event.data.split(":", 1)[1]
        ok, msg = store_update_skill(name)
        if ok:
            cfg = _cfg()
            size_warnings = _check_prompt_size_cross_chat(cfg.data_dir, name)
            if size_warnings:
                msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if event.data == "skill_update_all_confirm":
        from app.store import update_all as store_update_all
        results = store_update_all()
        if not results:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text("No store skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        cfg = _cfg()
        all_size_warnings: list[str] = []
        for name, ok, msg in results:
            status = "\u2714" if ok else "\u2718"
            lines.append(f"  {status} {html.escape(msg)}")
            if ok:
                all_size_warnings.extend(_check_prompt_size_cross_chat(cfg.data_dir, name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for w in all_size_warnings:
                lines.append(f"  {html.escape(w)}")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

@_command_handler
async def cmd_project(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    cfg = _cfg()
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    # No projects configured: early exit for all subcommands
    if not cfg.projects:
        await msg.reply_text(_msg.no_projects_configured())
        return

    if arg == "list":
        session = _load(event.chat_id)
        current = session.project_id
        lines = ["<b>Available projects:</b>"]
        for proj in cfg.projects:
            marker = " (active)" if proj.name == current else ""
            lines.append(f"  <code>{html.escape(proj.name)}</code> \u2192 {html.escape(proj.root_dir)}{marker}")
        await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if arg == "use" and len(event.args) >= 2:
        project_name = event.args[1]
        async with _chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(event.chat_id)
            ok, reply_text = _apply_project_change(event.chat_id, session, project_name)
        await msg.reply_text(reply_text, parse_mode=ParseMode.HTML)
        return

    if arg == "clear":
        async with _chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(event.chat_id)
            ok, reply_text = _apply_project_change(event.chat_id, session, "clear")
        await msg.reply_text(reply_text, parse_mode=ParseMode.HTML)
        return


    # Default: show current project with discoverable inline choices
    session = _load(event.chat_id)
    proj = _resolve_project(session)
    working_dir = proj.root_dir if proj else str(cfg.working_dir)
    project_label = proj.name if proj else "No project"
    lines = [
        f"Project: <b>{html.escape(project_label)}</b>",
        f"Working dir: <code>{html.escape(working_dir)}</code>",
    ]
    buttons = _settings_project_buttons(cfg, session)
    lines.append(_msg.project_use_buttons_or_list_hint())
    text = "\n".join(lines)
    await msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@_command_handler
async def cmd_settings(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Discoverability surface: current chat settings and inline controls (same mutations as commands)."""
    cfg = _cfg()
    msg = update.effective_message
    chat_id = event.chat_id
    session = _load(chat_id)
    trust = _trust_tier(event.user)
    resolved = _resolve_context(session, trust_tier=trust)

    # Display from resolved context only (public-safe: no trusted project/path leak)
    project_display = resolved.project_id or "No project"
    if trust == "public":
        project_display = "No project"
    working_dir = resolved.working_dir
    policy = resolved.file_policy or "edit"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    compact_label = "on" if compact else "off"
    effective_model = resolved.effective_model
    model_available, model_display = _settings_model_profile_state(
        session, cfg, trust, effective_model or ""
    )
    approval = session.approval_mode

    lines = [
        "<b>Chat settings</b>",
        f"Project: <code>{html.escape(project_display)}</code> \u2192 <code>{html.escape(working_dir)}</code>",
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
    text = "\n".join(lines)

    # Inline keyboard: omit project and policy controls for public users
    keyboard: list[list[InlineKeyboardButton]] = []
    if trust != "public":
        keyboard.extend(_settings_project_buttons(cfg, session))
        keyboard.append(_settings_policy_buttons(policy, has_explicit_override=bool(session.file_policy)))
    if model_available:
        keyboard.append(_settings_model_buttons(model_available, model_display, has_explicit_override=bool(session.model_profile)))
    elif session.model_profile:
        # No profiles configured but stale override exists — show inherit-only button
        keyboard.append([InlineKeyboardButton("Clear model override", callback_data="setting_model:inherit")])
    keyboard.append(_settings_compact_buttons(compact))
    keyboard.append(_settings_approval_buttons(approval))

    await msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@_command_handler
async def cmd_policy(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    if arg == "inherit":
        async with _chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(event.chat_id)
            if not session.file_policy:
                await msg.reply_text("File policy is already inherited.", parse_mode=ParseMode.HTML)
                return
            _apply_policy_change(event.chat_id, session, "")
        resolved = _resolve_context(_load(event.chat_id), _trust_tier(event.user))
        effective = resolved.file_policy or "edit"
        await msg.reply_text(
            f"File policy cleared. Effective policy: <code>{html.escape(effective)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg in ("inspect", "edit"):
        async with _chat_lock(event.chat_id, message=msg, update_id=update.update_id):
            session = _load(event.chat_id)
            resolved = _resolve_context(session, _trust_tier(event.user))
            old_policy = resolved.file_policy or "edit"
            if old_policy == arg:
                await msg.reply_text(f"File policy is already <code>{html.escape(arg)}</code>.", parse_mode=ParseMode.HTML)
                return
            _apply_policy_change(event.chat_id, session, arg)
        await msg.reply_text(
            _msg.trust_file_policy_set(arg),
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "" or arg == "status":
        session = _load(event.chat_id)
        resolved = _resolve_context(session, _trust_tier(event.user))
        policy = resolved.file_policy or "edit"
        await msg.reply_text(
            f"File policy: <b>{html.escape(policy)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([_settings_policy_buttons(policy, has_explicit_override=bool(session.file_policy))]),
        )
        return

    await msg.reply_text(_msg.policy_usage())


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
    cfg = _cfg()
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
    cfg = _cfg()
    work_queue.set_user_access(cfg.data_dir, actor_key, "blocked", reason, granted_by)
    await update.effective_message.reply_text(f"Actor {actor_key} blocked.")


@_command_handler
async def cmd_listaccess(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: list all configured DB-backed access overrides."""
    del context
    if not is_admin(event.user):
        await update.effective_message.reply_text("This command requires admin access.")
        return
    cfg = _cfg()
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

_bot_instance = None  # Set by build_application


@dataclasses.dataclass(frozen=True)
class _WorkerSkillEvent:
    chat_id: int | str
    user: Any


class _WorkerSkillUpdate:
    def __init__(self, message: Any) -> None:
        self.effective_message = message


async def _poll_cancel_requested(item_id: str, cancel_event: asyncio.Event) -> None:
    interval = poll_interval_for_runtime(_cfg().runtime_mode)
    while not cancel_event.is_set():
        if work_queue.is_cancel_requested(_cfg().data_dir, item_id):
            cancel_event.set()
            return
        await asyncio.sleep(interval)


async def _run_with_cancel_watch(
    item: dict[str, Any],
    runner,
):
    if _cfg().runtime_mode != "shared":
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
    source = getattr(event, "source", "telegram")
    conversation_key = str(item.get("conversation_key") or event.conversation_key)
    chat_id = telegram_numeric_id(conversation_key) if source == "telegram" else None
    if source == "telegram" and (chat_id is None or _bot_instance is None):
        raise RuntimeError(
            f"Telegram action item {item.get('id')} missing bot or chat_id for {conversation_key!r}"
        )
    runtime_chat = chat_id if chat_id is not None else conversation_key
    conversation_ref = event.conversation_ref or (
        telegram_conversation_ref(_cfg(), chat_id)
        if source == "telegram" and chat_id is not None
        else conversation_key
    )
    surface = factory.create_outbound_surface(
        conversation_ref,
        config=_cfg(),
        bot=_bot_instance,
        conversation_key=conversation_key,
        source=source,
        target_message_id=_action_target_message_id(event),
        output_log=getattr(_bot_instance, "_output_log", None) if _bot_instance is not None else None,
    )
    setattr(surface, "_worker_item_id", str(item.get("id", "")))
    return surface, runtime_chat, chat_id, conversation_ref, source


async def _execute_worker_action(
    event: InboundAction,
    item: dict[str, Any],
    *,
    cancel_event: asyncio.Event | None,
) -> None:
    from app.skill_commands import skills_add, skills_clear, skills_remove, skills_setup

    surface, runtime_chat, chat_id, conversation_ref, source = _build_action_surface(event, item=item)
    trust = factory.trust_tier_for_source(source, event.user, config=_cfg())
    action = event.action
    params = dict(event.params)

    if action == "session_new":
        cfg = _cfg()
        prov = _prov()
        old_session = _load(runtime_chat)
        user_id = event.user.id
        if foreign_skill_setup(old_session, _actor_key(user_id)):
            await surface.reply_text(
                foreign_setup_message(old_session.awaiting_skill_setup),
            )
            return
        approval_mode = old_session.approval_mode if old_session.approval_mode_explicit else cfg.approval_mode
        session = session_from_dict(
            default_session(prov.name, prov.new_provider_state(), approval_mode, cfg.role, cfg.default_skills)
        )
        if old_session.approval_mode_explicit:
            session.approval_mode_explicit = True
        _save(runtime_chat, session)
        cleanup_codex_scripts(cfg.data_dir, _conversation_key(runtime_chat))
        await surface.reply_text(f"Fresh {prov.name} conversation started.")
        return

    if action == "set_approval_mode":
        value = str(params.get("value", "")).lower()
        if value not in {"on", "off"}:
            return
        session = _load(runtime_chat)
        _apply_approval_change(runtime_chat, session, value)
        await surface.edit_reply_markup(reply_markup=None)
        await _edit_or_reply_text(surface, f"Approval mode set to {value} for this chat.")
        return

    if action == "approve_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await approve_pending(runtime_chat, surface, cancel_event=cancel_event)
        return

    if action == "reject_pending":
        await surface.edit_reply_markup(reply_markup=None)
        await reject_pending(runtime_chat, surface)
        return

    if action == "retry_skip":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_skip_pending(runtime_chat, surface)
        return

    if action == "retry_allow":
        await surface.edit_reply_markup(reply_markup=None)
        await retry_allow_pending(runtime_chat, surface, cancel_event=cancel_event)
        return

    if action in {"recovery_replay", "recovery_discard"}:
        update_id = int(params.get("update_id") or 0)
        if update_id <= 0:
            await surface.reply_text(_msg.recovery_invalid_action())
            return
        if action == "recovery_replay":
            work_queue.complete_work_item(_cfg().data_dir, str(item.get("id", "")))
        await surface.edit_reply_markup(reply_markup=None)
        await handle_recovery_action(
            runtime_chat,
            action,
            update_id,
            surface,
            cancel_event=cancel_event,
        )
        return

    if action == "delegation_approve":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_surface_delegation_approve(target_runtime, conversation_ref, surface)
        return

    if action == "delegation_cancel":
        target = params.get("target_conversation_key") or runtime_chat
        target_runtime = target
        if isinstance(target, str):
            numeric = telegram_numeric_id(target)
            if numeric is not None:
                target_runtime = numeric
        await handle_surface_delegation_cancel(target_runtime, conversation_ref, surface)
        return

    if action == "cancel_conversation":
        result = work_queue.request_cancel(
            _cfg().data_dir,
            _conversation_key(runtime_chat),
            _actor_key(event.user.id),
            cancel_request_event_id=str(item.get("event_id", "")),
        )
        if result == work_queue.CancelRequestResult.claimed_cancel_requested:
            await surface.reply_text(_msg.cancel_live_requested())
            return
        if result == work_queue.CancelRequestResult.queued_cancelled:
            await surface.reply_text(_msg.cancel_queued_superseded())
            return
        session = _load(runtime_chat)
        setup = session.awaiting_skill_setup
        allow_admin_override = source != "telegram" or is_admin(event.user)
        if setup:
            if setup.user_id == _actor_key(event.user.id) or allow_admin_override:
                session.awaiting_skill_setup = None
                _save(runtime_chat, session)
                await surface.reply_text(_msg.credential_setup_cancelled())
                return
            await surface.reply_text(_msg.credential_setup_another_user_in_progress())
            return
        if session.has_pending:
            session.clear_pending()
            _save(runtime_chat, session)
            await surface.reply_text(_msg.cancel_pending_request())
            return
        await surface.reply_text(_msg.nothing_to_cancel())
        return

    if action == "set_compact_mode":
        value = bool(params.get("value", False))
        session = _load(runtime_chat)
        _apply_compact_change(runtime_chat, session, value)
        await surface.edit_reply_markup(reply_markup=None)
        label = _msg.settings_compact_on_label() if value else _msg.settings_compact_off_label()
        await _edit_or_reply_text(
            surface,
            f"Compact mode set to <b>{label}</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "set_role":
        if is_public_user(event.user):
            await surface.reply_text(_msg.trust_command_not_available_public())
            return
        value = str(params.get("value", ""))
        session = _load(runtime_chat)
        if not value:
            session.role = _cfg().role
            _save(runtime_chat, session)
            await surface.reply_text("Role reset to instance default.")
            return
        session.role = value
        _save(runtime_chat, session)
        await surface.reply_text(
            f"Role set to: <code>{html.escape(value)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "set_model_profile":
        cfg = _cfg()
        session = _load(runtime_chat)
        profile = str(params.get("profile", ""))
        if profile == "":
            if not session.model_profile:
                await _edit_or_reply_text(surface, "Model profile is already inherited.", parse_mode=ParseMode.HTML)
                return
            _apply_model_change(runtime_chat, session, "")
            resolved = _resolve_context(_load(runtime_chat), trust)
            effective = resolved.effective_model or cfg.model
            _, profile_name = _settings_model_profile_state(_load(runtime_chat), cfg, trust, effective or "")
            if effective and profile_name != "(default)":
                text = (
                    "Model profile cleared. Effective: "
                    f"<code>{html.escape(profile_name)}</code> ({html.escape(effective)})"
                )
            else:
                text = "Model profile cleared. Using default model."
            await surface.edit_reply_markup(reply_markup=None)
            await _edit_or_reply_text(surface, text, parse_mode=ParseMode.HTML)
            return
        if not cfg.model_profiles:
            stale = session.model_profile
            if stale:
                await surface.reply_text(
                    "No model profiles configured, but this chat has a stale override "
                    f"(<code>{html.escape(stale)}</code>). Use /model inherit to clear it.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await surface.reply_text(_msg.trust_no_model_profiles())
            return
        ok, text = _apply_model_selection(runtime_chat, session, profile, cfg, trust)
        await surface.edit_reply_markup(reply_markup=None)
        await _edit_or_reply_text(surface, text, parse_mode=ParseMode.HTML)
        return

    if action == "set_project":
        if is_public_user(event.user):
            await _edit_or_reply_text(surface, _msg.trust_project_public())
            return
        cfg = _cfg()
        if not cfg.projects:
            await _edit_or_reply_text(surface, _msg.no_projects_configured())
            return
        session = _load(runtime_chat)
        _ok, reply_text = _apply_project_change(runtime_chat, session, str(params.get("value", "")))
        await surface.edit_reply_markup(reply_markup=None)
        await _edit_or_reply_text(surface, reply_text, parse_mode=ParseMode.HTML)
        return

    if action == "set_file_policy":
        if is_public_user(event.user):
            await _edit_or_reply_text(surface, _msg.trust_file_policy_public())
            return
        value = str(params.get("value", ""))
        session = _load(runtime_chat)
        if not value:
            if not session.file_policy:
                await _edit_or_reply_text(surface, "File policy is already inherited.", parse_mode=ParseMode.HTML)
                return
            _apply_policy_change(runtime_chat, session, "")
            resolved = _resolve_context(_load(runtime_chat), trust)
            effective = resolved.file_policy or "edit"
            await surface.edit_reply_markup(reply_markup=None)
            await _edit_or_reply_text(
                surface,
                f"File policy cleared. Effective policy: <code>{html.escape(effective)}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        if value not in {"inspect", "edit"}:
            return
        resolved = _resolve_context(session, trust)
        old_policy = resolved.file_policy or "edit"
        if old_policy == value:
            await _edit_or_reply_text(
                surface,
                f"File policy is already <code>{html.escape(value)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        _apply_policy_change(runtime_chat, session, value)
        await surface.edit_reply_markup(reply_markup=None)
        await _edit_or_reply_text(surface, _msg.trust_file_policy_set(value), parse_mode=ParseMode.HTML)
        return

    if action in {"skills_add", "skills_remove", "skills_setup", "skills_clear"}:
        if is_public_user(event.user):
            await surface.reply_text(_msg.trust_command_not_available_public())
            return
        proxy_event = _WorkerSkillEvent(chat_id=runtime_chat, user=event.user)
        proxy_update = _WorkerSkillUpdate(surface)
        name = str(params.get("name", ""))
        if action == "skills_add":
            await skills_add(proxy_event, proxy_update, name)
            return
        if action == "skills_remove":
            await skills_remove(proxy_event, proxy_update, name)
            return
        if action == "skills_setup":
            await skills_setup(proxy_event, proxy_update, name)
            return
        await skills_clear(proxy_event, proxy_update)
        return

    log.warning("Worker dispatch: unknown semantic action %s for item %s", action, item.get("id"))


async def worker_dispatch(kind: str, event, item: dict) -> None:
    """Dispatch a deserialized inbound event from the worker loop.

    Items with dispatch_mode 'recovery' get a recovery notice and move to
    pending_recovery. Fresh message items (dispatch_mode 'fresh') are executed
    here: execute_request or request_approval; they register _LIVE_CANCEL so
    /cancel works.
    """
    from app.transport import InboundAction, InboundCallback, InboundCommand, InboundMessage

    bot = _bot_instance
    cfg = _cfg()
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
            telegram_conversation_ref(_cfg(), chat_id)
            if source == "telegram" and chat_id is not None
            else conversation_key
        )
        routed_task_id = getattr(event, "routed_task_id", "")
        title = summarize_text(event.text) or "Conversation"
        bot_msg = factory.create_outbound_surface(
            conversation_ref,
            config=_cfg(),
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
            await bot_msg.bind(title=title, config=_cfg())
            await bot_msg.send_recovery_notice(
                preview=preview,
                prompt=_msg.recovery_notice_prompt(),
                run_again_label=_msg.recovery_button_run_again(),
                skip_label=_msg.recovery_button_skip(),
                update_id=update_id,
            )
            work_queue.mark_pending_recovery(data_dir, item["id"])
            raise work_queue.PendingRecovery(item["id"])

        # Fresh message: run provider (execute_request/request_approval register _LIVE_CANCEL).
        if source == "telegram" and not is_allowed(event.user):
            work_queue.fail_work_item(data_dir, item["id"], error="not_allowed")
            return
        prompt, image_paths = build_user_prompt(event.text, list(event.attachments))
        user_id = event.user.id
        trust = factory.trust_tier_for_source(source, event.user, config=_cfg())
        await bot_msg.bind(title=title, config=_cfg())
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
                delegation = session_after.pending_delegation
                if (
                    delegation is not None
                    and delegation.conversation_ref == conversation_ref
                    and delegation.status in {"completed", "partial_failed"}
                ):
                    session_after.pending_delegation = None
                    _save(runtime_chat, session_after)
        if routed_task_id:
            client = registry_client(_cfg())
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
    return enqueue_inbound_envelope(_cfg().data_dir, envelope)


def _shared_action_envelope(update: Update, action: InboundAction) -> InboundEnvelope:
    return _build_action_envelope(
        transport="telegram",
        event_id=_event_key(update.update_id),
        action=action,
    )


def _record_shared_action(update: Update, action: InboundAction) -> tuple[bool, InboundEnvelope]:
    envelope = _shared_action_envelope(update, action)
    return record_inbound_envelope(_cfg().data_dir, envelope), envelope


async def _shared_cancel_command(update: Update, event, action: InboundAction) -> None:
    is_new, envelope = _record_shared_action(update, action)
    if not is_new:
        return
    chat_id = event.chat_id
    actor_key = _actor_key(event.user.id)
    message = update.effective_message
    session = _load(chat_id)
    setup = session.awaiting_skill_setup
    if setup:
        if setup.user_id == actor_key or is_admin(event.user):
            async with _chat_lock(chat_id, message=message, update_id=update.update_id):
                session = _load(chat_id)
                if session.awaiting_skill_setup and (
                    session.awaiting_skill_setup.user_id == actor_key or is_admin(event.user)
                ):
                    session.awaiting_skill_setup = None
                    _save(chat_id, session)
                    await message.reply_text(_msg.credential_setup_cancelled())
                    return
            return
        await message.reply_text(_msg.credential_setup_another_user_in_progress())
        return

    result = work_queue.request_cancel(
        _cfg().data_dir,
        _conversation_key(chat_id),
        actor_key,
        cancel_request_event_id=_event_key(update.update_id),
    )
    if result == work_queue.CancelRequestResult.claimed_cancel_requested:
        await message.reply_text(_msg.cancel_live_requested())
        return
    if result == work_queue.CancelRequestResult.queued_cancelled:
        await message.reply_text(_msg.cancel_queued_superseded())
        return

    work_queue.enqueue_work_item(
        _cfg().data_dir,
        envelope.conversation_key,
        envelope.event_id,
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
    global _config, _provider, _boot_id, _rate_limiter, _bot_instance
    _config = config
    _provider = provider
    _boot_id = _make_boot_id()
    # Apply conservative rate-limit defaults for public mode
    per_minute = config.rate_limit_per_minute
    per_hour = config.rate_limit_per_hour
    if config.allow_open and per_minute == 0 and per_hour == 0:
        per_minute = 5
        per_hour = 30
        log.info("Public mode: applying default rate limits (5/min, 30/hr)")
    _rate_limiter = RateLimiter(per_minute=per_minute, per_hour=per_hour)

    # Sequential update processing; live runs are worker-owned so /cancel is delivered promptly.
    app = Application.builder().token(config.telegram_token).build()
    _bot_instance = app.bot
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
