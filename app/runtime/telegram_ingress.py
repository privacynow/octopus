"""Telegram channel normalized event translation and handler dispatch."""

import asyncio
import contextlib
import io
import json
import logging
from dataclasses import replace
from datetime import datetime, timezone

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app import access
from app import user_messages as _msg
from app.presentation import telegram as telegram_presenters
from app.config import BotConfig
from octopus_sdk.identity import (
    parse_actor_key,
    parse_conversation_key,
    telegram_conversation_ref,
    telegram_numeric_id,
)
from octopus_sdk.protocols import ProtocolService
from octopus_sdk.registry.client import RegistryClientError
from octopus_sdk.sessions import (
    SessionState,
    session_to_dict,
)
from octopus_sdk.registry.models import (
    parse_agent_discovery_query,
)
from app.workflows.delegation.telegram import (
    handle_delegation_approve,
    handle_delegation_cancel,
    parse_delegation_callback,
    parse_target_selector,
    propose_delegation_plan,
    submit_direct_assignment,
)
from app.runtime.telegram_execution import (
    allowed_roots,
    build_conversation_runtime,
    build_execution_runtime,
    build_runtime_skill_runtime,
    build_pending_runtime,
    build_user_prompt,
    resolve_context,
    send_formatted_reply,
    send_path_to_chat,
)
from app.runtime import telegram_normalization
from app.runtime import telegram_protocols
from app.runtime import telegram_session_io as telegram_session_io
from app.channels.telegram.state import TelegramRuntime
from app.workflows.runtime_skills.telegram import (
    cmd_clear_credentials as runtime_skill_cmd_clear_credentials,
    handle_skills_command as runtime_skill_handle_skills_command,
    handle_clear_cred_callback as runtime_skill_handle_clear_cred_callback,
    handle_skill_add_callback as runtime_skill_handle_skill_add_callback,
    handle_skill_update_callback as runtime_skill_handle_skill_update_callback,
    maybe_handle_setup_message as runtime_skill_maybe_handle_setup_message,
)
from app.workflows.conversation import telegram as telegram_conversation
from app.runtime.telegram_shared_dispatch import (
    handle_provider_guidance_command as channel_handle_guidance_command,
)
from app.workflows.conversation.telegram import (
    cmd_approval as conversation_cmd_approval,
    cmd_cancel as conversation_cmd_cancel,
    cmd_compact as conversation_cmd_compact,
    cmd_model as conversation_cmd_model,
    cmd_new as conversation_cmd_new,
    cmd_policy as conversation_cmd_policy,
    cmd_project as conversation_cmd_project,
    cmd_role as conversation_cmd_role,
    cmd_settings as conversation_cmd_settings,
)
from app.workflows.pending.telegram import (
    approve_pending as pending_approve_pending,
    handle_pending_callback as pending_handle_callback,
    handle_recovery_action as pending_handle_recovery_action,
    handle_recovery_callback as pending_handle_recovery_callback,
    reject_pending as pending_reject_pending,
)
from app.runtime.work_admission import trust_tier_for_ref
from app.formatting import summarize_text
from octopus_sdk.identity import resolve_event_conversation_ref
from octopus_sdk.inbound_types import InboundUser
from octopus_sdk.inbound_types import (
    InboundEnvelope,
    serialize_inbound,
)
from app.storage import (
    resolve_allowed_path,
    session_exists,
    list_sessions,
)
from app.summarize import export_chat_history, load_raw
from app import work_queue
from octopus_sdk.work_queue import TransportStateCorruption

log = logging.getLogger(__name__)


class ClaimBlocked(Exception):
    """Raised when a worker already owns the claimed item for this chat."""


def _context_runtime(context: ContextTypes.DEFAULT_TYPE | None) -> TelegramRuntime:
    if context is not None:
        runtime = getattr(context, "telegram_runtime", None)
        if isinstance(runtime, TelegramRuntime):
            return runtime
        application = getattr(context, "application", None)
        bot_data = getattr(application, "bot_data", None)
        if isinstance(bot_data, dict):
            runtime = bot_data.get("telegram_runtime")
            if isinstance(runtime, TelegramRuntime):
                return runtime
    raise RuntimeError("Telegram runtime is not attached to the handler context")


def event_trust_tier(*, config, dispatcher, event) -> str:
    return trust_tier_for_ref(
        resolve_event_conversation_ref(config=config, event=event),
        event.user,
        config=config,
        dispatcher=dispatcher,
    )


@contextlib.asynccontextmanager
async def _chat_lock(
    runtime: TelegramRuntime,
    chat_id: int | str,
    *,
    message=None,
    query=None,
    update_id: int | None = None,
    worker_item: dict | None = None,
    supersede_recovery: bool = False,
):
    """Serialize chat work, claim the matching durable item when needed, and yield whether busy feedback was sent."""
    data_dir = runtime.config.data_dir
    conversation_ref_key = telegram_session_io.conversation_key(chat_id)
    if runtime.config.runtime_mode == "shared" and worker_item is not None:
        work_queue.supersede_pending_recovery(data_dir, conversation_ref_key)
        try:
            yield False
        except work_queue.LeaveClaimed:
            raise
    lock = runtime.chat_locks[chat_id]
    sent_feedback = False
    # In-memory lock is the primary contention signal.  The durable check
    # only matters on restart recovery (lock not held but stale work items exist).
    is_busy = lock.locked()
    if is_busy:
        sent_feedback = True
        if message is not None:
            rendered = telegram_presenters.queue_busy_message()
            await message.reply_text(rendered.text, **rendered.kwargs())
        elif query is not None:
            await query.answer(_msg.queue_busy())
    async with lock:
        # Worker path: item already claimed externally; supersede any pending_recovery for this chat.
        if worker_item is not None:
            work_queue.supersede_pending_recovery(data_dir, conversation_ref_key)
            try:
                yield sent_feedback
            except work_queue.LeaveClaimed:
                raise  # let worker_dispatch handle it
            return

        # Live handler path: claim the durable work item.
        try:
            effective_update_id = (
                update_id if update_id is not None else runtime.current_update_id.get()
            )
            if effective_update_id is not None:
                item = work_queue.claim_for_update(
                    data_dir,
                    conversation_ref_key,
                    telegram_session_io.event_key(effective_update_id),
                    runtime.boot_id,
                )
            else:
                item = work_queue.claim_next(data_dir, conversation_ref_key, runtime.boot_id)
        except TransportStateCorruption as e:
            log.exception(
                "Transport state corruption in claim path for conversation %s: %s",
                conversation_ref_key,
                e,
            )
            if message is not None:
                rendered = telegram_presenters.generic_error_try_again_message()
                await message.reply_text(rendered.text, **rendered.kwargs())
            elif query is not None:
                await query.answer(_msg.generic_error_try_again(), show_alert=True)
            return

        # If claim failed and the reason is a concurrent claimed item (worker
        # claimed outside the lock), the handler must not run.  The work item
        # stays queued for worker_loop to pick up after its current item.
        if item is None and effective_update_id is not None:
            if work_queue.has_claimed_for_chat(data_dir, conversation_ref_key):
                raise ClaimBlocked(conversation_ref_key)

        item_id = item.id if item else None
        claimed_update_id = telegram_numeric_id(item.event_id) if item else None
        # Fresh message supersedes any pending_recovery for this chat.
        # Only handle_message passes supersede_recovery=True; commands
        # like /approval and /new must NOT supersede recovery items.
        if item_id and supersede_recovery:
            work_queue.supersede_pending_recovery(data_dir, conversation_ref_key)
        try:
            yield sent_feedback
        except work_queue.LeaveClaimed:
            if item_id:
                log.info("Leaving work item %s claimed for restart recovery", item_id)
                return
            raise
        except Exception:
            # Mark the queued item failed locally, then re-raise so the
            # global Telegram error handler logs and notifies the user.
            if item_id:
                work_queue.fail_work_item(data_dir, item_id, error="handler_exception")
                if claimed_update_id:
                    runtime.pending_work_items.pop(claimed_update_id, None)
            raise
        else:
            if item_id:
                work_queue.complete_work_item(data_dir, item_id)
                if claimed_update_id:
                    runtime.pending_work_items.pop(claimed_update_id, None)


def _chat_lock_adapter(runtime: TelegramRuntime):
    return lambda chat_id, **kwargs: _chat_lock(runtime, chat_id, **kwargs)


def _bound_execution_runtime(runtime: TelegramRuntime):
    return build_execution_runtime(runtime)


def _dedup_update(
    runtime: TelegramRuntime,
    update: Update,
    kind: str = "unknown",
    payload: str = "{}",
) -> bool:
    """Return True when this update_id was already recorded and claimed."""
    uid = update.update_id
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0
    data_dir = runtime.config.data_dir
    is_new, item_id = work_queue.record_and_enqueue(
        data_dir,
        telegram_session_io.event_key(uid),
        telegram_session_io.conversation_key(chat_id),
        telegram_session_io.actor_key(user_id),
        kind,
        payload=payload,
        worker_id=runtime.boot_id,
    )
    if not is_new:
        log.debug("Skipping duplicate update_id %d", uid)
        return True
    runtime.pending_work_items[uid] = item_id
    return False


def _complete_pending_work_item(
    runtime: TelegramRuntime,
    update_id: int,
    state: str = "done",
    error: str | None = None,
) -> None:
    """Complete the pending work item for an update if _chat_lock hasn't already."""
    item_id = runtime.pending_work_items.pop(update_id, None)
    if item_id:
        try:
            if state == "done":
                work_queue.complete_work_item(runtime.config.data_dir, item_id)
            else:
                work_queue.fail_work_item(runtime.config.data_dir, item_id, error=error or "failed")
        except Exception:
            log.debug("Work item %s already completed", item_id)


def _approval_mode_source(session: SessionState) -> str:
    return "chat override" if session.approval_mode_explicit else "instance default"

def is_allowed(runtime: TelegramRuntime, user) -> bool:
    cfg = runtime.config
    inbound = user if isinstance(user, InboundUser) else telegram_normalization.normalize_user(user)
    if inbound is None:
        return False
    override = work_queue.get_user_access(cfg.data_dir, inbound.id)
    return access.is_allowed_user_with_override(cfg, inbound, override)


def is_admin(runtime: TelegramRuntime, user) -> bool:
    """Check if user is an admin (can import/uninstall/update runtime skills)."""
    inbound = user if isinstance(user, InboundUser) else telegram_normalization.normalize_user(user)
    return access.is_admin_user(runtime.config, inbound)


def is_public_user(runtime: TelegramRuntime, user) -> bool:
    """Check if user is a public (untrusted) user.

    A user is public when allow_open is true AND the user is not in
    any allowed-user set.  Returns False if allow_open is off (the user
    wouldn't have passed is_allowed at all).
    """
    inbound = user if isinstance(user, InboundUser) else telegram_normalization.normalize_user(user)
    return access.is_public_user(runtime.config, inbound)


async def _public_guard(runtime: TelegramRuntime, event, update: Update) -> bool:
    """Return True (and send denial) if the user is public. Use at top of restricted commands."""
    if is_public_user(runtime, event.user):
        rendered = telegram_presenters.public_command_not_available_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return True
    return False


def _protocol_access(runtime: TelegramRuntime):
    registry_access = telegram_protocols.registry_client_for_runtime(runtime)
    if registry_access is None:
        return None
    client, agent_id, registry_url = registry_access
    return (client, agent_id, registry_url, ProtocolService(client))


def _protocol_artifact_links(runtime: TelegramRuntime, registry_url: str, run_id: str, artifact) -> dict[str, str]:
    artifact_key = str(getattr(artifact, "artifact_key", "") or "").strip()
    if not artifact_key:
        return {}
    return {
        "preview": telegram_protocols.protocol_artifact_url(
            runtime,
            run_id,
            artifact_key,
            registry_url=registry_url,
            preview=True,
        ) if telegram_protocols.protocol_artifact_previewable(artifact) else "",
        "open": telegram_protocols.protocol_artifact_url(
            runtime,
            run_id,
            artifact_key,
            registry_url=registry_url,
            download=False,
        ),
        "browse": telegram_protocols.protocol_artifact_url(
            runtime,
            run_id,
            artifact_key,
            registry_url=registry_url,
            browse=True,
        ) if telegram_protocols.protocol_artifact_is_package(artifact) else "",
        "runtime": telegram_protocols.protocol_artifact_runtime_url(
            runtime,
            run_id,
            artifact_key,
            registry_url=registry_url,
        ) if telegram_protocols.protocol_artifact_is_package(artifact) else "",
        "download": telegram_protocols.protocol_artifact_url(
            runtime,
            run_id,
            artifact_key,
            registry_url=registry_url,
            download=True,
        ),
    }


async def _send_protocol_status(
    runtime: TelegramRuntime,
    event,
    message,
    protocol_service: ProtocolService,
    registry_url: str,
    run_ref: str,
) -> None:
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to load the protocol run. {exc}")
        return
    except KeyError:
        await message.reply_text("Run not found. Use /protocol recent, then choose a run.")
        return
    run_id = detail.run.protocol_run_id
    session = telegram_session_io.load(runtime, event.chat_id)
    rendered = telegram_presenters.protocol_run_status_message(
        detail,
        deep_link=telegram_protocols.protocol_run_url(runtime, run_id, registry_url=registry_url),
        watching=telegram_protocols.is_protocol_run_watched(session, run_id),
    )
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _send_protocol_artifacts(
    runtime: TelegramRuntime,
    message,
    protocol_service: ProtocolService,
    registry_url: str,
    run_ref: str,
) -> None:
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to load the protocol run. {exc}")
        return
    except KeyError:
        await message.reply_text("Run not found. Use /protocol recent, then choose a run.")
        return
    run_id = detail.run.protocol_run_id
    artifact_links = {
        str(item.artifact_key or ""): _protocol_artifact_links(runtime, registry_url, run_id, item)
        for item in (detail.artifacts or [])
        if item.exists and str(item.artifact_key or "").strip()
    }
    rendered = telegram_presenters.protocol_run_artifacts_message(
        detail,
        deep_link=telegram_protocols.protocol_run_url(runtime, run_id, registry_url=registry_url),
        artifact_links=artifact_links,
    )
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _send_protocol_artifact_preview(
    runtime: TelegramRuntime,
    message,
    protocol_service: ProtocolService,
    registry_url: str,
    run_ref: str,
    artifact_ref: str,
    *,
    open_only: bool = False,
) -> None:
    if not artifact_ref:
        await _send_protocol_artifacts(runtime, message, protocol_service, registry_url, run_ref or "latest")
        return
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
        artifact = telegram_protocols.resolve_protocol_artifact_ref(detail, artifact_ref)
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to load the protocol run. {exc}")
        return
    except KeyError:
        await message.reply_text("Run or artifact not found. Use /protocol recent and choose an artifact.")
        return
    run_id = detail.run.protocol_run_id
    artifact_key = str(getattr(artifact, "artifact_key", "") or "").strip()
    if not bool(getattr(artifact, "exists", False)):
        await message.reply_text(f"Artifact {artifact_key} has not been produced yet.")
        return
    links = _protocol_artifact_links(runtime, registry_url, run_id, artifact)
    open_link = links.get("open", "")
    open_label = "Open"
    if telegram_protocols.protocol_artifact_is_package(artifact):
        open_label = "Open app"
    if open_only:
        preview_link = ""
    else:
        preview_link = links.get("preview", "")
    rendered = telegram_presenters.protocol_artifact_preview_message(
        run_id=run_id,
        artifact_label=telegram_protocols.protocol_artifact_human_label(artifact),
        preview_link=preview_link,
        open_link=open_link,
        runtime_link=links.get("runtime", ""),
        download_link=links.get("download", ""),
        artifact_ref=str(artifact_ref or ""),
        open_label=open_label,
    )
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _send_protocol_artifact_download(
    message,
    protocol_service: ProtocolService,
    run_ref: str,
    artifact_ref: str,
) -> None:
    if not artifact_ref:
        await message.reply_text("Choose an artifact first.")
        return
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
        artifact = telegram_protocols.resolve_protocol_artifact_ref(detail, artifact_ref)
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to load the protocol run. {exc}")
        return
    except KeyError:
        await message.reply_text("Run or artifact not found. Use /protocol recent and choose an artifact.")
        return
    run_id = detail.run.protocol_run_id
    resolved_artifact_key = str(getattr(artifact, "artifact_key", "") or "").strip()
    if not bool(getattr(artifact, "exists", False)):
        await message.reply_text(f"Artifact {resolved_artifact_key} has not been produced yet.")
        return
    try:
        content = await protocol_service.get_run_artifact_content(
            run_id,
            resolved_artifact_key,
            download=True,
        )
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to download the artifact. {exc}")
        return
    if not content:
        await message.reply_text(f"Artifact {artifact_ref} is empty or unavailable.")
        return
    filename = telegram_protocols.protocol_artifact_download_filename(artifact)
    doc = io.BytesIO(content)
    doc.name = filename
    await message.reply_document(
        document=doc,
        caption=f"Protocol artifact: {telegram_protocols.protocol_artifact_human_label(artifact)}",
    )


async def _send_protocol_export(message, protocol_service: ProtocolService, run_ref: str) -> None:
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
        run_id = detail.run.protocol_run_id
        exported = await protocol_service.export_run(run_id)
    except AttributeError:
        run_id = str(run_ref or "latest").strip()
        try:
            exported = await protocol_service.export_run(run_id)
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to export the protocol run. {exc}")
            return
    except RegistryClientError as exc:
        await message.reply_text(f"Failed to export the protocol run. {exc}")
        return
    except KeyError:
        await message.reply_text("Run not found. Use /protocol recent, then choose a run.")
        return
    payload = exported.model_dump(mode="json")
    doc = io.BytesIO(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
    doc.name = f"protocol_run_{run_id}.json"
    await message.reply_document(
        document=doc,
        caption=f"Protocol run export: {telegram_protocols.protocol_run_short_id(run_id)}",
    )


async def _send_auto_protocol_session(message, session, runtime: TelegramRuntime, registry_url: str, *, view: str = "summary") -> None:
    protocol_id = str(getattr(session, "target_protocol_id", "") or "")
    rendered = telegram_presenters.protocol_auto_session_message(
        session,
        registry_link=telegram_protocols.protocol_editor_url(runtime, protocol_id, registry_url=registry_url) if protocol_id else "",
        view=view,
    )
    await message.reply_text(rendered.text, **rendered.kwargs())


async def _set_protocol_watch(
    runtime: TelegramRuntime,
    event,
    message,
    protocol_service: ProtocolService,
    registry_url: str,
    run_ref: str,
    *,
    watching: bool,
) -> None:
    if watching:
        try:
            detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to load the protocol run. {exc}")
            return
        except KeyError:
            await message.reply_text("Run not found. Use /protocol recent, then choose a run.")
            return
        telegram_protocols.persist_protocol_run_watch(
            runtime,
            chat_id=event.chat_id,
            run_id=detail.run.protocol_run_id,
            protocol_id=detail.run.protocol_id,
            protocol_slug=str(getattr(detail.definition, "slug", "") or ""),
            version=int(detail.run.version or 0),
            status=str(detail.run.status or ""),
            stage_key=str(detail.run.current_stage_key or ""),
            registry_url=registry_url,
            last_notified_at=datetime.now(timezone.utc).isoformat(),
        )
        rendered = telegram_presenters.protocol_watch_changed_message(
            run_id=detail.run.protocol_run_id,
            watching=True,
            deep_link=telegram_protocols.protocol_run_url(runtime, detail.run.protocol_run_id, registry_url=registry_url),
        )
        await message.reply_text(rendered.text, **rendered.kwargs())
        return
    try:
        detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
        run_id = detail.run.protocol_run_id
    except Exception:
        run_id = str(run_ref or "latest").strip()
    telegram_protocols.discard_protocol_run_watch(runtime, chat_id=event.chat_id, run_id=run_id)
    rendered = telegram_presenters.protocol_watch_changed_message(
        run_id=run_id,
        watching=False,
        deep_link=telegram_protocols.protocol_run_url(runtime, run_id, registry_url=registry_url),
    )
    await message.reply_text(rendered.text, **rendered.kwargs())


def _command_handler(fn=None, *, show_not_allowed_message: bool = False):
    """Decorator: normalize → dedup → is_allowed gate → call fn(runtime, event, update, context)."""
    import functools

    def decorate(command_fn):
        @functools.wraps(command_fn)
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
            *,
            runtime: TelegramRuntime | None = None,
        ) -> None:
            runtime = runtime or _context_runtime(context)
            event = telegram_normalization.normalize_command(update, context)
            payload = serialize_inbound(event) if event else "{}"
            if _dedup_update(runtime, update, kind="command", payload=payload):
                return
            uid = update.update_id
            if event is None or not is_allowed(runtime, event.user):
                if show_not_allowed_message and event is not None:
                    rendered = telegram_presenters.trust_not_authorized_message()
                    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
                _complete_pending_work_item(runtime, uid)
                return
            token = runtime.current_update_id.set(uid)
            try:
                await command_fn(runtime, event, update, context)
            except ClaimBlocked:
                # Worker owns this chat — item stays queued for worker_loop.
                runtime.pending_work_items.pop(uid, None)
                return
            except Exception:
                # The decorator marks transport state failed here; the
                # exception still bubbles to the global error handler for the
                # generic user-facing Telegram error message.
                _complete_pending_work_item(runtime, uid, state="failed")
                raise
            else:
                _complete_pending_work_item(runtime, uid)
            finally:
                runtime.current_update_id.reset(token)

        return wrapper

    if fn is not None:
        return decorate(fn)
    return decorate


def _callback_handler(fn):
    """Decorator: normalize → dedup → gate → call fn(runtime, event, query)."""
    import functools

    @functools.wraps(fn)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        runtime: TelegramRuntime | None = None,
    ) -> None:
        runtime = runtime or _context_runtime(context)
        event = telegram_normalization.normalize_callback(update)
        payload = serialize_inbound(event) if event else "{}"
        if _dedup_update(runtime, update, kind="callback", payload=payload):
            return
        uid = update.update_id
        if event is None:
            _complete_pending_work_item(runtime, uid)
            return
        query = update.callback_query
        if not is_allowed(runtime, event.user):
            await query.answer(telegram_presenters.trust_not_authorized_message().text, show_alert=True)
            _complete_pending_work_item(runtime, uid)
            return
        token = runtime.current_update_id.set(uid)
        try:
            await fn(runtime, event, query)
        except ClaimBlocked:
            runtime.pending_work_items.pop(uid, None)
            try:
                await query.answer(_msg.queue_busy())
            except Exception:
                log.debug("Could not send queue-busy callback answer", exc_info=True)
            return
        except Exception:
            _complete_pending_work_item(runtime, uid, state="failed")
            raise
        else:
            _complete_pending_work_item(runtime, uid)
        finally:
            runtime.current_update_id.reset(token)

    return wrapper

def _settings_model_profile_state(
    runtime: TelegramRuntime,
    session: SessionState,
    cfg: BotConfig,
    trust_tier: str,
    effective_model: str,
) -> tuple[list[str], str]:
    state = runtime.services.workflows.conversation.settings.model_profile_state(
        session,
        cfg,
        trust_tier,
        effective_model,
    )
    return (list(state.available_profiles), state.current_profile)
@_command_handler(show_not_allowed_message=True)
async def cmd_start(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — always show main help (ignores deep-link payloads)."""
    del context
    cfg = runtime.config
    rendered = telegram_presenters.main_help_message(
        instance=cfg.instance,
        provider_name=runtime.provider.name.capitalize(),
        has_model_profiles=bool(cfg.model_profiles),
        agent_mode=cfg.agent_mode,
        is_public=is_public_user(runtime, event.user),
        has_projects=bool(cfg.projects),
        is_admin=is_admin(runtime, event.user),
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler(show_not_allowed_message=True)
async def cmd_help(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help [topic] — main help or topic-specific detail."""
    del context
    args = event.args

    if args:
        topic = args[0].lower()
        rendered = telegram_presenters.help_topic_message(topic)
        if rendered is not None:
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        rendered = telegram_presenters.unknown_help_topic_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    cfg = runtime.config
    rendered = telegram_presenters.main_help_message(
        instance=cfg.instance,
        provider_name=runtime.provider.name.capitalize(),
        has_model_profiles=bool(cfg.model_profiles),
        agent_mode=cfg.agent_mode,
        is_public=is_public_user(runtime, event.user),
        has_projects=bool(cfg.projects),
        is_admin=is_admin(runtime, event.user),
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_new(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await conversation_cmd_new(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_session(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    session = telegram_session_io.load(runtime, event.chat_id)
    cfg = runtime.config
    trust = event_trust_tier(
        config=runtime.config,
        dispatcher=getattr(runtime, "transport_dispatcher", None),
        event=event,
    )
    resolved = resolve_context(runtime, session, trust_tier=trust)
    pstate = session.provider_state

    if runtime.provider.name == "claude":
        sid = pstate.get("session_id", "[none]")
        active = pstate.get("started", False)
        session_label = "Session"
        session_value = sid[:12] + "\u2026"
        session_active = str(active)
    else:
        tid = pstate.get("thread_id") or "[none yet]"
        session_label = "Thread"
        session_value = str(tid)
        session_active = None

    pending = "yes" if session.has_pending else "no"
    role_display = resolved.role or "(default)"
    skills_display = ", ".join(resolved.active_skills) if resolved.active_skills else "(none)"
    approval_mode = session.approval_mode
    approval_source = _approval_mode_source(session)

    if resolved.project_id:
        wd_display = f"{resolved.working_dir} (project: {resolved.project_id})"
    else:
        wd_display = resolved.working_dir

    file_policy = resolved.file_policy or "edit"
    _, model_profile = _settings_model_profile_state(
        runtime, session, cfg, trust, resolved.effective_model or ""
    )
    model_id = resolved.effective_model or cfg.model or "(default)"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    compact_display = "on" if compact else "off"
    # Note: excludes agent discovery context (requires async bus call, not available in /settings).
    # Execution path includes agents via build_run_context; this is a best-effort UI estimate.
    prompt_weight_count = runtime.services.execution_services.guidance.prompt_weight(
        resolved.role,
        resolved.active_skills,
    )
    prompt_weight = f"~{prompt_weight_count} chars" if prompt_weight_count else "minimal"
    session_cmds = ["/settings"]
    if trust != "public" and cfg.projects:
        session_cmds.append("/project")
    if cfg.model_profiles:
        session_cmds.append("/model")
    rendered = telegram_presenters.session_overview_message(
        provider_name=runtime.provider.name,
        instance=cfg.instance,
        working_dir_display=wd_display,
        file_policy=file_policy,
        model_profile=model_profile,
        model_id=model_id,
        compact_display=compact_display,
        prompt_weight=prompt_weight,
        session_label=session_label,
        session_value=session_value,
        session_active=session_active,
        approval_mode=approval_mode,
        approval_source=approval_source,
        role_display=role_display,
        skills_display=skills_display,
        pending=pending,
        trust_public=(trust == "public"),
        session_commands=session_cmds,
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_approval(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_approval(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_approve(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _chat_lock(
        runtime,
        event.chat_id,
        message=update.effective_message,
        update_id=update.update_id,
    ):
        await pending_approve_pending(
            event.chat_id,
            update.effective_message,
            runtime=build_pending_runtime(
                runtime,
                execution_runtime=_bound_execution_runtime(runtime),
            ),
        )


@_command_handler
async def cmd_reject(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with _chat_lock(
        runtime,
        event.chat_id,
        message=update.effective_message,
        update_id=update.update_id,
    ):
        await pending_reject_pending(
            event.chat_id,
            update.effective_message,
            runtime=build_pending_runtime(
                runtime,
                execution_runtime=_bound_execution_runtime(runtime),
            ),
        )


@_command_handler
async def cmd_send(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(runtime, event, update):
        return
    if not event.args:
        rendered = telegram_presenters.send_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    raw_path = " ".join(event.args)
    session = telegram_session_io.load(runtime, event.chat_id)
    resolved_ctx = resolve_context(
        runtime,
        session,
        trust_tier=event_trust_tier(
            config=runtime.config,
            dispatcher=getattr(runtime, "transport_dispatcher", None),
            event=event,
        ),
    )
    resolved = resolve_allowed_path(raw_path, allowed_roots(runtime, event.chat_id, resolved_ctx))
    if not resolved:
        rendered = telegram_presenters.send_path_not_allowed_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    await send_path_to_chat(update.effective_message, resolved)


@_command_handler
async def cmd_id(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = event.user.username or "[none]"
    rendered = telegram_presenters.user_identity_message(event.user.id, username)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_doctor(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    from app.runtime_health import (
        SessionHealthContext,
        collect_runtime_health_report,
        format_runtime_health_for_doctor,
    )
    try:
        session = telegram_session_io.load(runtime, event.chat_id)
    except RuntimeError:
        session = None
    cfg = runtime.config
    session_context = None
    if session is not None:
        resolved = resolve_context(
            runtime,
            session,
            trust_tier=event_trust_tier(
                config=runtime.config,
                dispatcher=getattr(runtime, "transport_dispatcher", None),
                event=event,
            ),
        )
        session_context = SessionHealthContext(
            session=session_to_dict(session),
            actor_key=telegram_session_io.actor_key(event.user.id),
            resolved_active_skills=tuple(resolved.active_skills),
        )
    report = await collect_runtime_health_report(
        cfg,
        runtime.provider,
        caller_is_bot=True,
        session_context=session_context,
    )
    prompt_weight_count = None
    if session is not None:
        resolved = resolve_context(
            runtime,
            session,
            trust_tier=event_trust_tier(
                config=runtime.config,
                dispatcher=getattr(runtime, "transport_dispatcher", None),
                event=event,
            ),
        )
        prompt_weight_count = runtime.services.execution_services.guidance.prompt_weight(
            resolved.role,
            resolved.active_skills,
        ) or None
    rendered = telegram_presenters.doctor_report_message(
        format_runtime_health_for_doctor(report),
        prompt_weight_count,
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_discover(runtime: TelegramRuntime, event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    cfg = runtime.config
    if cfg.agent_mode == "standalone":
        rendered = telegram_presenters.discover_unavailable_standalone_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    participant = runtime.services.registry
    if not participant.health.live_local_agent_ids():
        rendered = telegram_presenters.discover_not_enrolled_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    query = parse_agent_discovery_query(event.args)
    if query is None:
        rendered = telegram_presenters.discover_usage_message()
        await update.effective_message.reply_text(rendered.text, parse_mode=rendered.parse_mode)
        return
    try:
        search = await participant.discovery.search_agents(query=query)
    except Exception:
        rendered = telegram_presenters.discover_failed_message("registry_request_failed")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if search.status == "unavailable":
        rendered = telegram_presenters.discover_degraded_message("registry_unreachable")
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.discover_results_message(search.agents)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_delegate(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    args = tuple(event.args or ())
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /delegate @agent instructions\nYou can also use @skill:skill-name or @role:role."
        )
        return
    selector = parse_target_selector(args[0])
    if selector is None:
        await update.effective_message.reply_text(
            "Usage: /delegate @agent instructions\nYou can also use @skill:skill-name or @role:role."
        )
        return
    instructions = " ".join(part.strip() for part in args[1:] if str(part).strip()).strip()
    if not instructions:
        await update.effective_message.reply_text(
            "Delegation needs instructions after the target selector."
        )
        return
    chat_id = event.chat_id
    title = summarize_text(instructions) or "Direct assignment"
    try:
        result = await submit_direct_assignment(
            runtime,
            telegram_session_io.conversation_key(chat_id),
            update.effective_message,
            conversation_ref=telegram_conversation_ref(runtime.config, chat_id),
            selector=selector,
            title=title,
            instructions=instructions,
            message_text=str(getattr(update.effective_message, "text", "") or ""),
        )
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Delegation unavailable right now. {exc}"
        )
        return
    task_ref = result.routed_tasks[0] if result.routed_tasks else None
    target_label = (
        f"@{selector.value}"
        if selector.kind == "agent"
        else f"@{selector.kind}:{selector.value}"
    )
    if task_ref is None:
        await update.effective_message.reply_text(f"Task sent to {target_label}.")
        return
    await update.effective_message.reply_text(
        f"Task sent to {target_label}. Routed task id: {task_ref.routed_task_id}"
    )


@_command_handler
async def cmd_protocol(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context
    if await _public_guard(runtime, event, update):
        return
    protocol_access = _protocol_access(runtime)
    if protocol_access is None:
        await update.effective_message.reply_text("Protocol control requires a connected registry.")
        return
    client, agent_id, registry_url, protocol_service = protocol_access
    args = tuple(event.args or ())
    sub = str(args[0] or "").strip().lower() if args else ""
    if sub in {"", "help"}:
        rendered = telegram_presenters.protocol_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "list":
        try:
            protocols = await protocol_service.list_launchable()
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to list protocols. {exc}")
            return
        rendered = telegram_presenters.protocol_list_message(protocols)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub in {"recent", "runs"}:
        try:
            runs = await telegram_protocols.recent_protocol_runs(protocol_service, limit=10)
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to list protocol runs. {exc}")
            return
        rendered = telegram_presenters.protocol_recent_runs_message(
            runs,
            run_links={
                str(run.protocol_run_id or ""): telegram_protocols.protocol_run_url(
                    runtime,
                    run.protocol_run_id,
                    registry_url=registry_url,
                )
                for run in runs
                if str(run.protocol_run_id or "").strip()
            },
        )
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "auto":
        auto_action = str(args[1] or "").strip().lower() if len(args) >= 2 else ""
        if auto_action in {"modify", "revise"}:
            if len(args) < 4:
                await update.effective_message.reply_text("Usage: /protocol auto modify latest|<session_id> <change request>")
                return
            try:
                session_id = telegram_protocols.resolve_auto_protocol_session_ref(runtime, event.chat_id, str(args[2] or ""))
            except KeyError:
                await update.effective_message.reply_text("No recent Auto Protocol session. Create one with /protocol auto <requirement>.")
                return
            change_request = " ".join(args[3:]).strip()
            if not change_request:
                await update.effective_message.reply_text("Usage: /protocol auto modify latest|<session_id> <change request>")
                return
            await update.effective_message.reply_text(
                "Updating the Auto Protocol draft. I will post the revised workflow here when planning finishes."
            )
            try:
                auto_session = await client.revise_protocol_auto_design_session(
                    session_id,
                    {
                        "mode": "revise",
                        "surface": "telegram",
                        "requirement_text": change_request,
                        "preferred_design_agent_id": agent_id,
                        "chat_ref": telegram_conversation_ref(runtime.config, event.chat_id),
                    },
                )
            except RegistryClientError as exc:
                await update.effective_message.reply_text(f"Failed to modify the generated protocol. {exc}")
                return
            telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=auto_session.session_id)
            await _send_auto_protocol_session(update.effective_message, auto_session, runtime, registry_url)
            return
        if auto_action in {"status", "show"}:
            try:
                session_id = telegram_protocols.resolve_auto_protocol_session_ref(
                    runtime,
                    event.chat_id,
                    str(args[2] or "latest") if len(args) >= 3 else "latest",
                )
            except KeyError:
                await update.effective_message.reply_text("No recent Auto Protocol session. Create one with /protocol auto <requirement>.")
                return
            try:
                auto_session = await client.get_protocol_auto_design_session(session_id)
            except RegistryClientError as exc:
                await update.effective_message.reply_text(f"Failed to load the generated protocol. {exc}")
                return
            await _send_auto_protocol_session(update.effective_message, auto_session, runtime, registry_url)
            return
        requirement = " ".join(args[1:]).strip()
        if not requirement:
            await update.effective_message.reply_text("Usage: /protocol auto <requirement>")
            return
        session_state = telegram_session_io.load(runtime, event.chat_id)
        await update.effective_message.reply_text(
            "Designing an Auto Protocol workflow. I will post the proposed stages, blockers, and actions here when planning finishes."
        )
        try:
            auto_session = await client.create_protocol_auto_design_session({
                "mode": "create",
                "surface": "telegram",
                "requirement_text": requirement,
                "workspace_ref": str(session_state.project_id or ""),
                "preferred_design_agent_id": agent_id,
                "chat_ref": telegram_conversation_ref(runtime.config, event.chat_id),
            })
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to generate the protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=auto_session.session_id)
        await _send_auto_protocol_session(update.effective_message, auto_session, runtime, registry_url)
        return
    if sub in {"improve-run", "improve_run"}:
        if len(args) < 3:
            await update.effective_message.reply_text("Usage: /protocol improve-run latest|<run id|recent index> <change request>")
            return
        run_ref = str(args[1] or "").strip()
        change_request = " ".join(args[2:]).strip()
        if not run_ref or not change_request:
            await update.effective_message.reply_text("Usage: /protocol improve-run latest|<run id|recent index> <change request>")
            return
        try:
            detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref)
            protocol_id = str(getattr(detail.run, "protocol_id", "") or "").strip()
            if not protocol_id:
                await update.effective_message.reply_text("That run does not have a protocol id to improve.")
                return
            await update.effective_message.reply_text(
                "Designing an improved protocol from that run. I will post the proposed workflow here when planning finishes."
            )
            auto_session = await client.create_protocol_auto_design_session({
                "mode": "revise",
                "surface": "telegram",
                "target_protocol_id": protocol_id,
                "requirement_text": telegram_protocols.protocol_run_improvement_requirement(detail, change_request),
                "constraints_text": telegram_protocols.protocol_run_improvement_constraints(detail),
                "preferred_design_agent_id": agent_id,
                "chat_ref": telegram_conversation_ref(runtime.config, event.chat_id),
            })
        except KeyError:
            await update.effective_message.reply_text(f"Unknown protocol run: {run_ref}")
            return
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to improve the run. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=auto_session.session_id)
        await _send_auto_protocol_session(update.effective_message, auto_session, runtime, registry_url)
        return
    if sub == "improve":
        if len(args) < 3:
            await update.effective_message.reply_text("Usage: /protocol improve <slug> <change request>")
            return
        protocol_ref = str(args[1] or "").strip()
        change_request = " ".join(args[2:]).strip()
        if not protocol_ref or not change_request:
            await update.effective_message.reply_text("Usage: /protocol improve <slug> <change request>")
            return
        try:
            match = await protocol_service.resolve_launchable(protocol_ref)
            auto_session = await client.create_protocol_auto_design_session({
                "mode": "revise",
                "surface": "telegram",
                "target_protocol_id": match.protocol_id,
                "requirement_text": change_request,
                "preferred_design_agent_id": agent_id,
                "chat_ref": telegram_conversation_ref(runtime.config, event.chat_id),
            })
        except KeyError:
            await update.effective_message.reply_text(f"Unknown published protocol: {protocol_ref}")
            return
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to improve the protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=auto_session.session_id)
        await _send_auto_protocol_session(update.effective_message, auto_session, runtime, registry_url)
        return
    if sub == "start":
        slug, launch_inputs = telegram_protocols.parse_protocol_start_args(args[1:])
        if not slug or not str(launch_inputs.get("problem_statement") or "").strip():
            await update.effective_message.reply_text(
                "Usage: /protocol start <slug> <problem statement> [--context <text>] [--constraints <text>] [--workspace <ref>]",
            )
            return
        try:
            match = await protocol_service.resolve_launchable(slug)
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to load protocols. {exc}")
            return
        except KeyError:
            await update.effective_message.reply_text(f"Unknown published protocol: {slug}")
            return
        session = telegram_session_io.load(runtime, event.chat_id)
        if not str(launch_inputs.get("workspace_ref") or "").strip():
            launch_inputs["workspace_ref"] = str(session.project_id or "")
        conversation = await client.create_conversation(
            target_agent_id=agent_id,
            origin_channel="telegram",
            external_conversation_ref=telegram_conversation_ref(runtime.config, event.chat_id),
            title=f"Telegram chat {event.chat_id}",
        )
        try:
            result = await protocol_service.launch_from_inputs(
                match,
                launch_inputs,
                entry_agent_id=agent_id,
                root_conversation_id=conversation.conversation_id,
                origin_channel="telegram",
                origin="telegram",
            )
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to start the protocol run. {exc}")
            return
        except ValueError as exc:
            await update.effective_message.reply_text(f"Failed to start the protocol run. {exc}")
            return
        try:
            protocol_label = str(match.display_name or match.slug or match.protocol_id)
        except Exception:
            protocol_label = str(match.display_name or match.slug or match.protocol_id)
        run = result.run
        if run is None:
            await update.effective_message.reply_text("Protocol run creation failed without a run record.")
            return
        telegram_protocols.persist_protocol_run_watch(
            runtime,
            chat_id=event.chat_id,
            run_id=run.protocol_run_id,
            protocol_id=match.protocol_id,
            protocol_slug=str(match.slug or ""),
            version=int(run.version or 0),
            status=str(run.status or ""),
            stage_key=str(run.current_stage_key or ""),
            registry_url=registry_url,
            last_notified_at=datetime.now(timezone.utc).isoformat(),
        )
        rendered = telegram_presenters.protocol_run_started_message(
            run_id=run.protocol_run_id,
            protocol_label=protocol_label,
            current_stage=str(run.current_stage_key or "queued"),
            deep_link=telegram_protocols.protocol_run_url(runtime, run.protocol_run_id, registry_url=registry_url),
            watching=True,
        )
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub == "status":
        await _send_protocol_status(
            runtime,
            event,
            update.effective_message,
            protocol_service,
            registry_url,
            str(args[1] or "") if len(args) >= 2 else "latest",
        )
        return
    if sub == "artifacts":
        run_ref = str(args[1] or "") if len(args) >= 2 else "latest"
        download_requested = len(args) >= 4 and str(args[2] or "").strip().lower() == "download"
        requested_artifact_key = str(args[3] or "").strip() if download_requested else ""
        if download_requested:
            await _send_protocol_artifact_download(
                update.effective_message,
                protocol_service,
                run_ref,
                requested_artifact_key,
            )
            return
        await _send_protocol_artifacts(runtime, update.effective_message, protocol_service, registry_url, run_ref)
        return
    if sub == "preview":
        await _send_protocol_artifact_preview(
            runtime,
            update.effective_message,
            protocol_service,
            registry_url,
            str(args[1] or "") if len(args) >= 2 else "latest",
            str(args[2] or "") if len(args) >= 3 else "",
        )
        return
    if sub == "export":
        await _send_protocol_export(
            update.effective_message,
            protocol_service,
            str(args[1] or "") if len(args) >= 2 else "latest",
        )
        return
    if sub in {"watch", "unwatch"}:
        if sub == "watch":
            await _set_protocol_watch(
                runtime,
                event,
                update.effective_message,
                protocol_service,
                registry_url,
                str(args[1] or "") if len(args) >= 2 else "latest",
                watching=True,
            )
            return
        await _set_protocol_watch(
            runtime,
            event,
            update.effective_message,
            protocol_service,
            registry_url,
            str(args[1] or "") if len(args) >= 2 else "latest",
            watching=False,
        )
        return
    if sub in {"cancel", "retry", "accept", "send-back"}:
        if len(args) < 2:
            await update.effective_message.reply_text(f"Usage: /protocol {sub} <run> [reason]")
            return
        confirmation = len(args) >= 3 and str(args[2] or "").strip().lower() == "confirm"
        reason_parts = args[3:] if confirmation else args[2:]
        reason = " ".join(str(part).strip() for part in reason_parts if str(part).strip()).strip()
        try:
            detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, str(args[1] or ""))
            run_id = detail.run.protocol_run_id
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to load the protocol run. {exc}")
            return
        except KeyError:
            await update.effective_message.reply_text("Run not found. Use /protocol recent, then repeat the action with a number.")
            return
        if telegram_protocols.protocol_action_requires_confirmation(sub):
            if not reason:
                await update.effective_message.reply_text(f"Usage: /protocol {sub} <run> [reason]")
                return
            if not confirmation:
                rendered = telegram_presenters.protocol_action_confirmation_message(
                    action=sub,
                    run_id=run_id,
                    reason=reason,
                    deep_link=telegram_protocols.protocol_run_url(runtime, run_id, registry_url=registry_url),
                )
                await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
                return
        try:
            result = await protocol_service.act_on_run(
                run_id,
                action=sub,
                reason=reason,
                expected_version=detail.run.version or 1,
            )
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to update the protocol run. {exc}")
            return
        run = result.run
        if run is None:
            await update.effective_message.reply_text("Protocol action completed without a refreshed run payload.")
            return
        if str(run.status or "") in {"completed", "failed", "cancelled"}:
            telegram_protocols.discard_protocol_run_watch(runtime, chat_id=event.chat_id, run_id=run.protocol_run_id)
        else:
            telegram_protocols.persist_protocol_run_watch(
                runtime,
                chat_id=event.chat_id,
                run_id=run.protocol_run_id,
                protocol_id=run.protocol_id,
                protocol_slug=str(getattr(detail.definition, "slug", "") or ""),
                version=int(run.version or 0),
                status=str(run.status or ""),
                stage_key=str(run.current_stage_key or ""),
                registry_url=registry_url,
                last_notified_at=datetime.now(timezone.utc).isoformat(),
            )
        rendered = telegram_presenters.protocol_run_updated_message(
            run_id=run.protocol_run_id,
            status=str(run.status or ""),
            current_stage=str(run.current_stage_key or "n/a"),
            deep_link=telegram_protocols.protocol_run_url(runtime, run.protocol_run_id, registry_url=registry_url),
        )
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if sub in {"archive", "restore", "delete"}:
        if len(args) < 2:
            await update.effective_message.reply_text(f"Usage: /protocol {sub} <run> [reason]")
            return
        confirmation = len(args) >= 3 and str(args[2] or "").strip().lower() == "confirm"
        reason_parts = args[3:] if confirmation else args[2:]
        reason = " ".join(str(part).strip() for part in reason_parts if str(part).strip()).strip()
        if sub == "delete" and not confirmation:
            await update.effective_message.reply_text("Usage: /protocol delete <run> confirm [reason]")
            return
        try:
            detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, str(args[1] or ""))
            run_id = detail.run.protocol_run_id
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to load the protocol run. {exc}")
            return
        except KeyError:
            await update.effective_message.reply_text("Run not found. Use /protocol recent, then repeat the action with a number.")
            return
        try:
            if sub == "archive":
                result = await protocol_service.archive_run(run_id, reason=reason)
            elif sub == "restore":
                result = await protocol_service.restore_run(run_id, reason=reason)
            else:
                result = await protocol_service.delete_run(run_id, reason=reason, confirm="DELETE")
        except RegistryClientError as exc:
            await update.effective_message.reply_text(f"Failed to update the protocol run lifecycle. {exc}")
            return
        run = result.run
        if run is None:
            await update.effective_message.reply_text("Protocol lifecycle action completed without a refreshed run payload.")
            return
        if str(run.status or "") in {"completed", "failed", "cancelled", "archived", "deleted"}:
            telegram_protocols.discard_protocol_run_watch(runtime, chat_id=event.chat_id, run_id=run.protocol_run_id)
        rendered = telegram_presenters.protocol_run_updated_message(
            run_id=run.protocol_run_id,
            status=str(run.status or ""),
            current_stage=str(run.current_stage_key or "n/a"),
            deep_link=telegram_protocols.protocol_run_url(runtime, run.protocol_run_id, registry_url=registry_url),
        )
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.protocol_usage_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_callback_handler
async def handle_protocol_callback(runtime: TelegramRuntime, event, query) -> None:
    if is_public_user(runtime, event.user):
        await query.answer(telegram_presenters.public_command_not_available_message().text, show_alert=True)
        return
    parsed = telegram_presenters.parse_protocol_callback_data(event.data)
    if parsed is None:
        await query.answer("Protocol action unavailable.", show_alert=True)
        return
    action, run_ref, artifact_ref = parsed
    protocol_access = _protocol_access(runtime)
    if protocol_access is None:
        await query.answer("Protocol control requires a connected registry.", show_alert=True)
        return
    client, agent_id, registry_url, protocol_service = protocol_access
    message = query.message
    if message is None:
        await query.answer("Protocol action unavailable.", show_alert=True)
        return
    await query.answer()
    if action in {"auto_summary", "auto_stages", "auto_artifacts", "auto_warnings"}:
        try:
            session = await client.get_protocol_auto_design_session(run_ref)
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to load the generated protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=session.session_id)
        await _send_auto_protocol_session(message, session, runtime, registry_url, view=action.removeprefix("auto_"))
        return
    if action == "auto_apply":
        try:
            session = await client.apply_protocol_auto_design_session(run_ref)
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to apply the generated protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=session.session_id)
        await _send_auto_protocol_session(message, session, runtime, registry_url)
        return
    if action == "auto_publish":
        try:
            session = await client.publish_protocol_auto_design_session(run_ref)
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to publish the generated protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=session.session_id)
        await _send_auto_protocol_session(message, session, runtime, registry_url)
        return
    if action == "auto_run":
        try:
            conversation = await client.create_conversation(
                target_agent_id=agent_id,
                origin_channel="telegram",
                external_conversation_ref=telegram_conversation_ref(runtime.config, event.chat_id),
                title=f"Telegram chat {event.chat_id}",
            )
            session = await client.run_protocol_auto_design_session(
                run_ref,
                {
                    "entry_agent_id": agent_id,
                    "root_conversation_id": conversation.conversation_id,
                    "origin_channel": "telegram",
                },
            )
        except RegistryClientError as exc:
            await message.reply_text(f"Failed to publish and run the generated protocol. {exc}")
            return
        telegram_protocols.persist_auto_protocol_session_ref(runtime, chat_id=event.chat_id, session_id=session.session_id)
        run = getattr(getattr(session, "run_result", None), "run", None)
        if run is not None:
            applied_protocol = getattr(getattr(session, "applied_protocol", None), "protocol", None)
            protocol_label = str(
                getattr(applied_protocol, "display_name", "")
                or getattr(session.plan, "protocol_name", "")
                or "Generated protocol"
            )
            telegram_protocols.persist_protocol_run_watch(
                runtime,
                chat_id=event.chat_id,
                run_id=run.protocol_run_id,
                protocol_id=run.protocol_id,
                protocol_slug="",
                version=int(run.version or 0),
                status=str(run.status or ""),
                stage_key=str(run.current_stage_key or ""),
                registry_url=registry_url,
                last_notified_at=datetime.now(timezone.utc).isoformat(),
            )
            rendered = telegram_presenters.protocol_run_started_message(
                run_id=run.protocol_run_id,
                protocol_label=protocol_label,
                current_stage=run.current_stage_key,
                deep_link=telegram_protocols.protocol_run_url(runtime, run.protocol_run_id, registry_url=registry_url),
                watching=True,
            )
            await message.reply_text(rendered.text, **rendered.kwargs())
            return
        await _send_auto_protocol_session(message, session, runtime, registry_url)
        return
    if action == "status":
        await _send_protocol_status(runtime, event, message, protocol_service, registry_url, run_ref)
        return
    if action == "artifacts":
        await _send_protocol_artifacts(runtime, message, protocol_service, registry_url, run_ref)
        return
    if action == "preview":
        await _send_protocol_artifact_preview(runtime, message, protocol_service, registry_url, run_ref, artifact_ref)
        return
    if action == "open":
        await _send_protocol_artifact_preview(
            runtime,
            message,
            protocol_service,
            registry_url,
            run_ref,
            artifact_ref,
            open_only=True,
        )
        return
    if action == "download":
        await _send_protocol_artifact_download(message, protocol_service, run_ref, artifact_ref)
        return
    if action in {"runtime_start", "runtime_stop", "runtime_status"}:
        if not artifact_ref:
            await message.reply_text("Choose an artifact first.")
            return
        try:
            detail = await telegram_protocols.resolve_protocol_run_ref(protocol_service, run_ref or "latest")
            artifact = telegram_protocols.resolve_protocol_artifact_ref(detail, artifact_ref)
            artifact_key = str(getattr(artifact, "artifact_key", "") or "").strip()
            if action == "runtime_start":
                runtime_result = await protocol_service.start_artifact_runtime(detail.run.protocol_run_id, artifact_key)
                status = str(runtime_result.status or "")
                result_message = runtime_result.message
            elif action == "runtime_stop":
                runtime_result = await protocol_service.stop_artifact_runtime(detail.run.protocol_run_id, artifact_key)
                status = str(runtime_result.status or "")
                result_message = runtime_result.message
            else:
                health = await protocol_service.get_artifact_runtime_health(detail.run.protocol_run_id, artifact_key)
                status = str(health.status or "")
                result_message = health.message
        except RegistryClientError as exc:
            await message.reply_text(f"Artifact app action failed. {exc}")
            return
        except KeyError:
            await message.reply_text("Run or artifact not found. Use /protocol recent and choose an artifact.")
            return
        rendered = telegram_presenters.protocol_artifact_runtime_message(
            run_id=detail.run.protocol_run_id,
            artifact_label=telegram_protocols.protocol_artifact_human_label(artifact),
            status=status,
            message=result_message,
            runtime_link=telegram_protocols.protocol_artifact_runtime_url(
                runtime,
                detail.run.protocol_run_id,
                artifact_key,
                registry_url=registry_url,
            ),
            package_link=telegram_protocols.protocol_artifact_url(
                runtime,
                detail.run.protocol_run_id,
                artifact_key,
                registry_url=registry_url,
                download=True,
            ),
            artifact_ref=str(artifact_ref or ""),
        )
        await message.reply_text(rendered.text, **rendered.kwargs())
        return
    if action == "export":
        await _send_protocol_export(message, protocol_service, run_ref)
        return
    if action == "watch":
        await _set_protocol_watch(
            runtime,
            event,
            message,
            protocol_service,
            registry_url,
            run_ref,
            watching=True,
        )
        return
    if action == "unwatch":
        await _set_protocol_watch(
            runtime,
            event,
            message,
            protocol_service,
            registry_url,
            run_ref,
            watching=False,
        )
        return
    await query.answer("Protocol action unavailable.", show_alert=True)


@_command_handler
async def cmd_export(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat_id = event.chat_id
    cfg = runtime.config

    history = export_chat_history(cfg.data_dir, telegram_session_io.conversation_key(chat_id))
    if not history:
        rendered = telegram_presenters.no_conversation_to_export_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    # Add session metadata header — use resolved context for user-visible data
    session = telegram_session_io.load(runtime, chat_id)
    trust = event_trust_tier(
        config=runtime.config,
        dispatcher=getattr(runtime, "transport_dispatcher", None),
        event=event,
    )
    resolved = resolve_context(runtime, session, trust_tier=trust)
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
async def cmd_admin(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not is_admin(runtime, event.user):
        rendered = telegram_presenters.admin_required_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    args = event.args
    sub = args[0].lower() if args else ""

    if sub != "sessions":
        rendered = telegram_presenters.admin_sessions_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    cfg = runtime.config
    sessions = list_sessions(cfg.data_dir)

    if not sessions:
        rendered = telegram_presenters.no_sessions_found_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    # Filter stale active_skills that no longer resolve
    for s in sessions:
        s["active_skills"] = runtime.services.workflows.runtime_skills.catalog.filter_resolvable(
            s["active_skills"]
        )

    # Detail view for a specific conversation
    if len(args) >= 2:
        target_key = parse_conversation_key(args[1])
        if not target_key:
            rendered = telegram_presenters.admin_invalid_conversation_key_message()
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        match = next((s for s in sessions if s["conversation_key"] == target_key), None)
        if not match:
            rendered = telegram_presenters.admin_session_not_found_message(target_key)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        rendered = telegram_presenters.admin_session_detail_message(target_key, match)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    # Summary view
    total = len(sessions)
    pending = sum(1 for s in sessions if s["has_pending"])
    setup = sum(1 for s in sessions if s["has_setup"])
    skill_counts: dict[str, int] = {}
    for s in sessions:
        for sk in s["active_skills"]:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

    top = sorted(skill_counts.items(), key=lambda value: -value[1])[:5] if skill_counts else []
    rendered = telegram_presenters.admin_sessions_summary_message(
        total=total,
        pending=pending,
        setup=setup,
        top_skills=top,
        most_recent_key=sessions[0]["conversation_key"],
        most_recent_updated_at=sessions[0]["updated_at"],
    )
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_skills(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if await _public_guard(runtime, event, update):
        return
    await runtime_skill_handle_skills_command(
        event,
        update,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


@_command_handler
async def cmd_guidance(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if await _public_guard(runtime, event, update):
        return
    await channel_handle_guidance_command(
        runtime,
        event,
        update,
        is_admin=is_admin(runtime, event.user),
    )


@_command_handler
async def cmd_cancel(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_cancel(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_clear_credentials(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await runtime_skill_cmd_clear_credentials(
        event,
        update,
        context,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


@_callback_handler
async def handle_clear_cred_callback(runtime: TelegramRuntime, event, query) -> None:
    await runtime_skill_handle_clear_cred_callback(
        event,
        query,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


@_command_handler
async def cmd_compact(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_compact(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_raw(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat_id = event.chat_id
    cfg = runtime.config
    args = event.args

    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            rendered = telegram_presenters.raw_usage_message()
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return

    raw_text = load_raw(cfg.data_dir, telegram_session_io.conversation_key(chat_id), n)
    if raw_text is None:
        rendered = telegram_presenters.raw_missing_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return

    await send_formatted_reply(update.effective_message, raw_text)


@_command_handler
async def cmd_role(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_role(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_model(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_model(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: TelegramRuntime | None = None,
) -> None:
    """Normalize input, handle setup inline, or enqueue worker-owned provider execution."""
    runtime = runtime or _context_runtime(context)
    uid = update.update_id
    user = telegram_normalization.normalize_user(update.effective_user)
    if user is None or not is_allowed(runtime, user):
        return

    rate_limiter = runtime.rate_limiter
    if rate_limiter and rate_limiter.enabled and not (
        runtime.config.admin_users_explicit and is_admin(runtime, user)
    ):
        allowed, retry_after = rate_limiter.check(user.id)
        if not allowed:
            rendered = telegram_presenters.rate_limit_message(retry_after)
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return

    try:
        msg = await telegram_normalization.normalize_message(update, context, runtime.config.data_dir)
    except telegram_normalization.TelegramAttachmentTooLarge as exc:
        await update.effective_message.reply_text(str(exc))
        return
    if msg is None:
        return

    message = update.effective_message
    chat_id = msg.chat_id
    user_id = user.id

    cfg = runtime.config
    needs_welcome = not session_exists(cfg.data_dir, telegram_session_io.conversation_key(chat_id))
    if not msg.conversation_ref:
        msg = telegram_normalization.normalize_message_with_conversation_ref(msg, config=cfg, chat_id=chat_id)
    if msg.attachments:
        registry_access = telegram_protocols.registry_client_for_runtime(runtime)
        if registry_access is None:
            await update.effective_message.reply_text(
                "I could not register the attached file with Registry. Check Registry connectivity and try again."
            )
            return
        client, _agent_id, _registry_url = registry_access
        registered_attachments = []
        try:
            for attachment in msg.attachments:
                resource = await client.upload_resource_from_path(
                    attachment.path,
                    source_surface="telegram",
                    source_ref=msg.conversation_ref or msg.conversation_key,
                    target_kind="",
                    target_ref="",
                )
                registered_attachments.append(
                    replace(
                        attachment,
                        resource_id=resource.resource_id,
                        source_surface=resource.source_surface,
                    )
                )
        except RegistryClientError as exc:
            await update.effective_message.reply_text(
                f"I could not register the attached file with Registry: {exc.operator_detail or exc}"
            )
            return
        msg = replace(msg, attachments=tuple(registered_attachments))
    prompt, image_paths = build_user_prompt(msg.text, list(msg.attachments))
    payload = serialize_inbound(msg)

    data_dir = cfg.data_dir
    if await runtime_skill_maybe_handle_setup_message(
        update,
        msg,
        payload,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    ):
        return

    envelope = InboundEnvelope(
        transport="telegram",
        event_id=telegram_session_io.event_key(uid),
        conversation_key=telegram_session_io.conversation_key(chat_id),
        actor_key=telegram_session_io.actor_key(user_id),
        received_at=datetime.now(timezone.utc),
        event=msg,
    )
    submission = await runtime.submitter.admit_message(envelope)
    status, item_id = submission.status, submission.item_id
    if status == "duplicate":
        return
    if status in {"admitted", "queued"}:
        work_queue.supersede_pending_recovery(data_dir, envelope.conversation_key)
    if status == "admitted" and needs_welcome:
        rendered = telegram_presenters.welcome_message(
            approval_mode=cfg.approval_mode,
            compact_mode=cfg.compact_mode,
        )
        await message.chat.send_message(rendered.text, **rendered.kwargs())
    if status == "queued":
        rendered = telegram_presenters.queue_accepted_message()
        await message.reply_text(rendered.text, **rendered.kwargs())
        return
    if status not in {"admitted", "queued"} or item_id is None:
        return

    # Enqueued for worker; return so /cancel can be processed without blocking.
    return


@_callback_handler
async def handle_callback(runtime: TelegramRuntime, event, query) -> None:
    await pending_handle_callback(
        event,
        query,
        runtime=build_pending_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


@_callback_handler
async def handle_delegation_callback(runtime: TelegramRuntime, event, query) -> None:
    parsed = parse_delegation_callback(event.data)
    if parsed is None:
        return
    action, chat_id = parsed

    async with _chat_lock(runtime, chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        if action == "delegation_approve":
            await handle_delegation_approve(
                runtime,
                chat_id,
                query,
            )
            return
        if action == "delegation_cancel":
            await handle_delegation_cancel(
                runtime,
                chat_id,
                query,
            )

async def handle_recovery_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    runtime: TelegramRuntime | None = None,
) -> None:
    runtime = runtime or _context_runtime(context)
    await pending_handle_recovery_callback(
        update,
        context,
        runtime=build_pending_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


async def handle_recovery_action(
    chat_id: int | str,
    action: str,
    update_id: int,
    message,
    *,
    answer_action=None,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramRuntime,
) -> None:
    await pending_handle_recovery_action(
        chat_id,
        action,
        update_id,
        message,
        answer_action=answer_action,
        cancel_event=cancel_event,
        runtime=build_pending_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )

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
async def handle_expand_callback(runtime: TelegramRuntime, event, query) -> None:
    """Handle 'Show full answer' button presses."""
    await query.answer()
    parsed = _parse_expand_collapse_data(event.data)
    if parsed is None:
        return
    target_chat, slot = parsed

    from app.summarize import load_raw_by_slot
    cfg = runtime.config
    raw_text = load_raw_by_slot(cfg.data_dir, telegram_session_io.conversation_key(target_chat), slot)
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
async def handle_collapse_callback(runtime: TelegramRuntime, event, query) -> None:
    """Handle 'Collapse' button presses — re-render compact view."""
    await query.answer()
    parsed = _parse_expand_collapse_data(event.data)
    if parsed is None:
        return
    target_chat, slot = parsed

    from app.summarize import load_raw_by_slot
    cfg = runtime.config
    raw_text = load_raw_by_slot(cfg.data_dir, telegram_session_io.conversation_key(target_chat), slot)
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

@_callback_handler
async def handle_settings_callback(runtime: TelegramRuntime, event, query) -> None:
    await telegram_conversation.handle_settings_callback(
        event,
        query,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )

@_callback_handler
async def handle_skill_add_callback(runtime: TelegramRuntime, event, query) -> None:
    await runtime_skill_handle_skill_add_callback(
        event,
        query,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )


@_callback_handler
async def handle_skill_update_callback(runtime: TelegramRuntime, event, query) -> None:
    await runtime_skill_handle_skill_update_callback(
        event,
        query,
        runtime=build_runtime_skill_runtime(
            runtime,
            chat_lock=_chat_lock_adapter(runtime),
            execution_runtime=_bound_execution_runtime(runtime),
        ),
    )
@_command_handler
async def cmd_project(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_project(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_settings(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_settings(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_policy(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await conversation_cmd_policy(
        event,
        update,
        context,
        runtime=build_conversation_runtime(runtime, chat_lock=_chat_lock_adapter(runtime)),
    )


@_command_handler
async def cmd_allowuser(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Admin: add a user to the allowed list. Usage: /allowuser <actor_key|user_id> [reason]."""
    del context
    if not is_admin(runtime, event.user):
        rendered = telegram_presenters.admin_access_required_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if not event.args:
        rendered = telegram_presenters.allowuser_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    target_actor_key = parse_actor_key(event.args[0])
    if not target_actor_key:
        rendered = telegram_presenters.allowuser_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    reason = " ".join(event.args[1:])
    granted_by = telegram_session_io.actor_key(event.user.id if event.user else 0)
    cfg = runtime.config
    work_queue.set_user_access(cfg.data_dir, target_actor_key, "allowed", reason, granted_by)
    rendered = telegram_presenters.allowuser_success_message(target_actor_key)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_blockuser(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Admin: block a user. Usage: /blockuser <actor_key|user_id> [reason]."""
    del context
    if not is_admin(runtime, event.user):
        rendered = telegram_presenters.admin_access_required_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    if not event.args:
        rendered = telegram_presenters.blockuser_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    target_actor_key = parse_actor_key(event.args[0])
    if not target_actor_key:
        rendered = telegram_presenters.blockuser_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    reason = " ".join(event.args[1:])
    granted_by = telegram_session_io.actor_key(event.user.id if event.user else 0)
    cfg = runtime.config
    work_queue.set_user_access(cfg.data_dir, target_actor_key, "blocked", reason, granted_by)
    rendered = telegram_presenters.blockuser_success_message(target_actor_key)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


@_command_handler
async def cmd_listaccess(
    runtime: TelegramRuntime,
    event,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Admin: list all configured DB-backed access overrides."""
    del context
    if not is_admin(runtime, event.user):
        rendered = telegram_presenters.admin_access_required_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    cfg = runtime.config
    rows = work_queue.list_user_access(cfg.data_dir)
    if not rows:
        rendered = telegram_presenters.listaccess_empty_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.access_overrides_message(rows)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())

async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch unhandled exceptions so the user always gets feedback."""
    error = context.error

    # Stale callback queries are harmless: Telegram's answer window expired.
    if isinstance(error, BadRequest) and "query is too old" in str(error).lower():
        log.debug("Stale callback query (ignored): %s", error)
        return

    log.exception("Unhandled exception in handler", exc_info=error)

    if update and isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                _msg.generic_error_try_again(),
            )
        except Exception as exc:
            log.warning(
                "Could not send generic error message to chat %s: %s",
                update.effective_chat.id,
                exc.__class__.__name__,
            )
