"""Telegram-specific protocol control helpers and run follow-up watches."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse, urlunparse

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
_START_OPTION_ALIASES = {
    "goal": "problem_statement",
    "problem": "problem_statement",
    "workspace": "workspace_ref",
    "workspace-ref": "workspace_ref",
    "context": "context",
    "constraints": "constraints",
    "constraint": "constraints",
    "expected": "expected_outputs",
    "expected-output": "expected_outputs",
    "expected-outputs": "expected_outputs",
    "outputs": "expected_outputs",
}


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


def _human_registry_base_url(raw_base: str) -> str:
    explicit = (
        os.environ.get("BOT_REGISTRY_PUBLIC_URL")
        or os.environ.get("OCTOPUS_REGISTRY_PUBLIC_URL")
        or os.environ.get("REGISTRY_PUBLIC_URL")
        or ""
    ).strip()
    if explicit:
        return explicit.rstrip("/")
    base = str(raw_base or "").strip()
    parsed = urlparse(base)
    if (parsed.hostname or "").strip().lower() != "registry":
        return base.rstrip("/")
    port = parsed.port or 8787
    netloc = f"127.0.0.1:{port}"
    return urlunparse((parsed.scheme or "http", netloc, "", "", "", "")).rstrip("/")


def _configured_registry_url(runtime: TelegramRuntime, registry_url: str = "") -> str:
    base = str(registry_url or "").strip()
    if not base:
        registry = next(iter(runtime.config.agent_registries), None)
        base = str(getattr(registry, "url", "") or "").strip() if registry is not None else ""
    return _human_registry_base_url(base) if base else ""


def protocol_run_url(runtime: TelegramRuntime, run_id: str, *, registry_url: str = "") -> str:
    base = _configured_registry_url(runtime, registry_url)
    if not base:
        return ""
    return f"{base.rstrip('/')}/ui/runs?run_id={quote(str(run_id or '').strip())}"


def protocol_artifact_url(
    runtime: TelegramRuntime,
    run_id: str,
    artifact_key: str,
    *,
    registry_url: str = "",
    download: bool = False,
    browse: bool = False,
    preview: bool = False,
    member_path: str = "",
) -> str:
    base = _configured_registry_url(runtime, registry_url)
    if not base:
        return ""
    run_token = quote(str(run_id or "").strip())
    artifact_token = quote(str(artifact_key or "").strip())
    if not run_token or not artifact_token:
        return ""
    query_items = {
        key: value
        for key, value in (
            ("download", "true" if download else ""),
            ("browse", "true" if browse else ""),
            ("preview", "true" if preview else ""),
            ("path", str(member_path or "").strip()),
        )
        if value
    }
    query = urlencode(query_items)
    suffix = f"?{query}" if query else ""
    return f"{base.rstrip('/')}/v1/protocol-runs/{run_token}/artifacts/{artifact_token}/content{suffix}"


def protocol_run_short_id(run_id: str) -> str:
    token = str(run_id or "").strip()
    return token[:8] if len(token) > 8 else token


def protocol_run_human_label(run) -> str:
    protocol = str(
        getattr(run, "protocol_display_name", "")
        or getattr(run, "protocol_slug", "")
        or getattr(run, "protocol_id", "")
        or "Protocol"
    ).strip()
    short_id = protocol_run_short_id(str(getattr(run, "protocol_run_id", "") or ""))
    return f"{protocol} ({short_id})" if short_id else protocol


def protocol_artifact_human_label(artifact) -> str:
    key = str(getattr(artifact, "artifact_key", "") or "").strip()
    path = str(getattr(artifact, "workspace_path", "") or getattr(artifact, "location", "") or "").strip()
    name = Path(path).name.strip() if path else ""
    return name or key or "Artifact"


def protocol_artifact_is_package(artifact) -> bool:
    path = str(getattr(artifact, "workspace_path", "") or getattr(artifact, "location", "") or "").strip()
    key = str(getattr(artifact, "artifact_key", "") or "").strip().lower()
    basename = Path(path.rstrip("/")).name if path else ""
    lower_hint = " ".join([path, key, basename]).lower()
    if any(token in lower_hint for token in ("package", "bundle", "folder", "directory")):
        return True
    return bool(path) and "." not in basename


def protocol_artifact_previewable(artifact) -> bool:
    path = str(getattr(artifact, "workspace_path", "") or getattr(artifact, "location", "") or "").strip()
    return Path(path).suffix.lower() in {
        ".md",
        ".markdown",
        ".txt",
        ".log",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".sh",
        ".sql",
        ".rb",
        ".go",
        ".java",
        ".rs",
        ".php",
    }


async def recent_protocol_runs(protocol_service, *, limit: int = 10):
    runs = await protocol_service.list_runs(limit=limit)
    return list(runs or [])


async def resolve_protocol_run_ref(protocol_service, run_ref: str, *, limit: int = 10):
    token = str(run_ref or "").strip()
    if not token:
        raise KeyError("run_ref_required")
    lowered = token.lower()
    if lowered not in {"latest", "last", "recent"} and not token.isdigit():
        try:
            return await protocol_service.get_run_status(token)
        except RegistryClientError as exc:
            if exc.error_code not in {"PROTOCOL_RUN_NOT_FOUND", "PROTOCOL_NOT_VISIBLE"}:
                raise
    runs = await recent_protocol_runs(protocol_service, limit=limit)
    if lowered in {"latest", "last", "recent"}:
        if not runs:
            raise KeyError("no_recent_runs")
        return await protocol_service.get_run_status(runs[0].protocol_run_id)
    if token.isdigit():
        index = int(token) - 1
        if index < 0 or index >= len(runs):
            raise KeyError("run_index_out_of_range")
        return await protocol_service.get_run_status(runs[index].protocol_run_id)
    matches = [
        item
        for item in runs
        if str(item.protocol_run_id or "").startswith(token)
        or token.lower() in {
            str(getattr(item, "protocol_id", "") or "").strip().lower(),
            str(getattr(item, "protocol_slug", "") or "").strip().lower(),
        }
    ]
    if len(matches) == 1:
        return await protocol_service.get_run_status(matches[0].protocol_run_id)
    if not matches:
        return await protocol_service.get_run_status(token)
    raise KeyError("ambiguous_run_ref")


def resolve_protocol_artifact_ref(detail, artifact_ref: str):
    token = str(artifact_ref or "").strip()
    if not token:
        raise KeyError("artifact_ref_required")
    artifacts = list(getattr(detail, "artifacts", None) or [])
    if token.isdigit():
        index = int(token) - 1
        if index < 0 or index >= len(artifacts):
            raise KeyError("artifact_index_out_of_range")
        return artifacts[index]
    lowered = token.lower()
    matches = [
        item for item in artifacts
        if str(getattr(item, "artifact_key", "") or "").strip() == token
        or str(getattr(item, "artifact_key", "") or "").strip().lower().startswith(lowered)
        or protocol_artifact_human_label(item).lower().startswith(lowered)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise KeyError("artifact_not_found")
    raise KeyError("ambiguous_artifact_ref")


def parse_protocol_start_args(args: Iterable[str]) -> tuple[str, dict[str, object]]:
    """Parse `/protocol start` arguments into the shared launch input shape.

    Supported form:

    `/protocol start <slug> <goal> --context <text> --constraints <text>
    --expected-outputs <text> --workspace <ref>`

    Text for each option consumes words until the next `--option` marker. The
    simple historical form still works because all tokens after the slug become
    the problem statement when no markers are present.
    """

    parts = [str(item or "").strip() for item in args if str(item or "").strip()]
    if not parts:
        return "", {}
    slug = parts[0]
    values: dict[str, list[str]] = {"problem_statement": []}
    active_key = "problem_statement"
    for token in parts[1:]:
        if token.startswith("--") and len(token) > 2:
            raw_name, sep, inline_value = token[2:].partition("=")
            next_key = _START_OPTION_ALIASES.get(raw_name.strip().lower())
            if next_key:
                active_key = next_key
                values.setdefault(active_key, [])
                if sep and inline_value.strip():
                    values[active_key].append(inline_value.strip())
                continue
        values.setdefault(active_key, []).append(token)
    inputs = {
        key: " ".join(value_parts).strip()
        for key, value_parts in values.items()
        if " ".join(value_parts).strip()
    }
    return slug, inputs


def protocol_artifact_download_filename(artifact) -> str:
    path = str(
        getattr(artifact, "workspace_path", "")
        or getattr(artifact, "location", "")
        or ""
    ).strip()
    key = str(getattr(artifact, "artifact_key", "") or "artifact").strip()
    name = Path(path).name.strip() if path else ""
    filename = name or key or "artifact"
    lower_hint = " ".join([key, path, filename]).lower()
    if "." not in Path(filename).name and any(token in lower_hint for token in ("package", "bundle", "directory", "folder")):
        return f"{filename}.zip"
    return filename


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
