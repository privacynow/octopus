"""Telegram-specific protocol control helpers and run follow-up watches."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import quote

from app.agents.state import load_runtime_registry_connection_state
from app.channels.telegram.state import TelegramRuntime
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from app.runtime import telegram_session_io
from app.storage import list_sessions
from octopus_sdk.identity import telegram_numeric_id
from octopus_sdk.registry.client import RegistryClient, RegistryClientError
from octopus_sdk.sessions import ProtocolRunWatch, SessionState

log = logging.getLogger(__name__)

PROTOCOL_NOTIFICATION_INTERVAL_SECONDS = 20.0
PROTOCOL_NOTIFICATION_DEBOUNCE_SECONDS = 60.0


def registry_client_for_runtime(runtime: TelegramRuntime) -> tuple[RegistryClient, str, str] | None:
    for registry in runtime.config.agent_registries:
        state = load_runtime_registry_connection_state(
            runtime.config.data_dir,
            registry.registry_id,
            registry_scope=registry.registry_scope,
        )
        if state.agent_token:
            return (
                RegistryClient(registry.url, agent_token=state.agent_token),
                str(state.agent_id or ""),
                str(registry.url or ""),
            )
    return None


def protocol_run_url(runtime: TelegramRuntime, run_id: str, *, registry_url: str = "") -> str:
    base = str(registry_url or "").strip()
    if not base:
        registry = next(iter(runtime.config.agent_registries), None)
        base = str(getattr(registry, "url", "") or "").strip() if registry is not None else ""
    if not base:
        return ""
    return f"{base.rstrip('/')}/ui/runs?run_id={quote(str(run_id or '').strip())}"


def protocol_artifact_url(
    runtime: TelegramRuntime,
    run_id: str,
    artifact_key: str,
    *,
    registry_url: str = "",
) -> str:
    base = str(registry_url or "").strip()
    if not base:
        registry = next(iter(runtime.config.agent_registries), None)
        base = str(getattr(registry, "url", "") or "").strip() if registry is not None else ""
    if not base:
        return ""
    run_token = quote(str(run_id or "").strip())
    artifact_token = quote(str(artifact_key or "").strip())
    if not run_token or not artifact_token:
        return ""
    return f"{base.rstrip('/')}/v1/protocol-runs/{run_token}/artifacts/{artifact_token}/content"


def protocol_action_requires_confirmation(action: str) -> bool:
    return str(action or "").strip().lower() in {"cancel", "send-back"}


def is_protocol_run_watched(session: SessionState, run_id: str) -> bool:
    token = str(run_id or "").strip()
    return any(item.run_id == token for item in session.protocol_run_watches)


def upsert_protocol_run_watch(
    session: SessionState,
    *,
    run_id: str,
    protocol_id: str = "",
    protocol_slug: str = "",
    version: int = 0,
    status: str = "",
    stage_key: str = "",
    registry_url: str = "",
    last_notified_at: str = "",
) -> bool:
    token = str(run_id or "").strip()
    if not token:
        return False
    normalized_time = str(last_notified_at or "").strip()
    for item in session.protocol_run_watches:
        if item.run_id != token:
            continue
        item.protocol_id = str(protocol_id or item.protocol_id or "")
        item.protocol_slug = str(protocol_slug or item.protocol_slug or "")
        item.last_notified_version = int(version or item.last_notified_version or 0)
        item.last_notified_status = str(status or item.last_notified_status or "")
        item.last_notified_stage_key = str(stage_key or item.last_notified_stage_key or "")
        item.registry_url = str(registry_url or item.registry_url or "")
        if normalized_time:
            item.last_notified_at = normalized_time
        return False
    session.protocol_run_watches.append(
        ProtocolRunWatch(
            run_id=token,
            protocol_id=str(protocol_id or ""),
            protocol_slug=str(protocol_slug or ""),
            last_notified_version=int(version or 0),
            last_notified_status=str(status or ""),
            last_notified_stage_key=str(stage_key or ""),
            last_notified_at=normalized_time,
            registry_url=str(registry_url or ""),
        )
    )
    return True


def remove_protocol_run_watch(session: SessionState, run_id: str) -> bool:
    token = str(run_id or "").strip()
    before = len(session.protocol_run_watches)
    session.protocol_run_watches = [item for item in session.protocol_run_watches if item.run_id != token]
    return len(session.protocol_run_watches) != before


def persist_protocol_run_watch(
    runtime: TelegramRuntime,
    *,
    chat_id: int | str,
    run_id: str,
    protocol_id: str = "",
    protocol_slug: str = "",
    version: int = 0,
    status: str = "",
    stage_key: str = "",
    registry_url: str = "",
    last_notified_at: str = "",
) -> bool:
    conversation_key = telegram_session_io.conversation_key(chat_id)
    session = load_runtime_session(
        runtime.config.data_dir,
        conversation_key,
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )
    created = upsert_protocol_run_watch(
        session,
        run_id=run_id,
        protocol_id=protocol_id,
        protocol_slug=protocol_slug,
        version=version,
        status=status,
        stage_key=stage_key,
        registry_url=registry_url,
        last_notified_at=last_notified_at,
    )
    save_runtime_session(runtime.config.data_dir, conversation_key, session)
    return created


def discard_protocol_run_watch(runtime: TelegramRuntime, *, chat_id: int | str, run_id: str) -> bool:
    conversation_key = telegram_session_io.conversation_key(chat_id)
    session = load_runtime_session(
        runtime.config.data_dir,
        conversation_key,
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
    )
    removed = remove_protocol_run_watch(session, run_id)
    if removed:
        save_runtime_session(runtime.config.data_dir, conversation_key, session)
    return removed


def _conversation_key_to_chat_id(conversation_key: str) -> int | None:
    return telegram_numeric_id(str(conversation_key or "").strip())


def _watch_due(item: ProtocolRunWatch, now: datetime) -> bool:
    if not item.last_notified_at:
        return True
    try:
        last = datetime.fromisoformat(item.last_notified_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - last.astimezone(timezone.utc)).total_seconds() >= PROTOCOL_NOTIFICATION_DEBOUNCE_SECONDS


def _is_terminal(status: str) -> bool:
    return str(status or "").strip() in {"completed", "failed", "cancelled"}


def iter_protocol_run_watches(runtime: TelegramRuntime) -> list[tuple[str, SessionState, ProtocolRunWatch]]:
    watches: list[tuple[str, SessionState, ProtocolRunWatch]] = []
    for record in list_sessions(runtime.config.data_dir):
        conversation_key = str(record.get("conversation_key", "") or "").strip()
        if not conversation_key:
            continue
        session = load_runtime_session(
            runtime.config.data_dir,
            conversation_key,
            provider_name=runtime.provider.name,
            provider_state_factory=runtime.provider.new_provider_state,
            approval_mode=runtime.config.approval_mode,
            default_role=runtime.config.role,
            default_skills=runtime.config.default_skills,
        )
        if not session.protocol_run_watches:
            continue
        for watch in session.protocol_run_watches:
            watches.append((conversation_key, session, watch))
    return watches


async def notify_protocol_run_watches(
    runtime: TelegramRuntime,
    *,
    render_notification,
) -> None:
    registry_access = registry_client_for_runtime(runtime)
    if registry_access is None or runtime.bot_instance is None:
        return
    client, _agent_id, registry_url = registry_access
    now = datetime.now(timezone.utc)
    grouped: dict[str, tuple[SessionState, list[ProtocolRunWatch]]] = {}
    for conversation_key, session, watch in iter_protocol_run_watches(runtime):
        grouped.setdefault(conversation_key, (session, []))[1].append(watch)
    for conversation_key, (session, watches) in grouped.items():
        chat_id = _conversation_key_to_chat_id(conversation_key)
        if chat_id is None:
            continue
        session_changed = False
        for watch in list(watches):
            try:
                detail = await client.get_run(watch.run_id)
            except RegistryClientError as exc:
                if exc.error_code in {"PROTOCOL_NOT_VISIBLE", "PROTOCOL_RUN_NOT_FOUND"}:
                    if remove_protocol_run_watch(session, watch.run_id):
                        session_changed = True
                else:
                    log.warning("Protocol watch refresh failed for %s", watch.run_id, exc_info=True)
                continue
            run = detail.run
            changed = (
                int(run.version or 0) != int(watch.last_notified_version or 0)
                or str(run.status or "") != str(watch.last_notified_status or "")
                or str(run.current_stage_key or "") != str(watch.last_notified_stage_key or "")
            )
            if not changed:
                continue
            terminal = _is_terminal(str(run.status or ""))
            if not terminal and not _watch_due(watch, now):
                continue
            rendered = render_notification(
                detail,
                deep_link=protocol_run_url(runtime, run.protocol_run_id, registry_url=watch.registry_url or registry_url),
            )
            await runtime.bot_instance.send_message(chat_id, rendered.text, **rendered.kwargs())
            watch.protocol_id = str(run.protocol_id or watch.protocol_id or "")
            watch.protocol_slug = str(getattr(detail.definition, "slug", "") or watch.protocol_slug or "")
            watch.last_notified_version = int(run.version or 0)
            watch.last_notified_status = str(run.status or "")
            watch.last_notified_stage_key = str(run.current_stage_key or "")
            watch.last_notified_at = now.isoformat()
            watch.registry_url = str(watch.registry_url or registry_url or "")
            session_changed = True
            if terminal:
                remove_protocol_run_watch(session, watch.run_id)
        if session_changed:
            save_runtime_session(runtime.config.data_dir, conversation_key, session)


async def protocol_watch_loop(
    runtime: TelegramRuntime,
    *,
    stop_event: asyncio.Event,
    render_notification,
) -> None:
    while not stop_event.is_set():
        try:
            await notify_protocol_run_watches(runtime, render_notification=render_notification)
        except Exception:
            log.warning("Telegram protocol watch sweep failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PROTOCOL_NOTIFICATION_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


def watched_protocol_run_ids(session: SessionState) -> list[str]:
    return [item.run_id for item in session.protocol_run_watches]


def protocol_watch_label(session: SessionState, run_id: str) -> str:
    return "watching" if is_protocol_run_watched(session, run_id) else "not watching"


def protocol_registry_urls(runtime: TelegramRuntime) -> Iterable[str]:
    for registry in runtime.config.agent_registries:
        url = str(registry.url or "").strip()
        if url:
            yield url
