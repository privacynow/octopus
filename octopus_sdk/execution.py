"""Channel-neutral execution contracts and workflow orchestration."""

from __future__ import annotations

import asyncio
import html
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from octopus_sdk.approvals import build_preflight_prompt
from octopus_sdk.bot_runtime import ExecutionServices
from octopus_sdk.bot_runtime import ProviderDispatchRuntime
from octopus_sdk.bot_runtime import run_provider_preflight
from octopus_sdk.bot_runtime import run_provider_request
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.execution_events import ExecutionEventSink
from octopus_sdk.formatting import extract_send_directives
from octopus_sdk.identity import resolve_external_conversation_ref
from octopus_sdk.inbound_types import InboundAttachment
from octopus_sdk.providers import CredentialEnvRecord, DenialRecord
from octopus_sdk.request_flow import extra_dirs_from_denials
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.sessions import (
    PendingApproval,
    PendingApprovalAttachmentRecord,
    PendingRetry,
    SessionState,
    trusted_conversation_bypasses_approvals,
)
from octopus_sdk.registry.models import AgentDiscoveryQuery, DiscoveredAgentRef
from octopus_sdk.runtime.skills import skill_execution_manifest_hash
from octopus_sdk.runtime.skills import normalize_skill_kind
from octopus_sdk.transport import TransportEgress

_log = logging.getLogger(__name__)


def _progress_working() -> str:
    return "Working…"


def _progress_resuming() -> str:
    return "Resuming…"


def _cancel_live_completed() -> str:
    return "Cancelled."


def _progress_request_timed_out(seconds: int) -> str:
    return f"Request timed out after {seconds} seconds."


def _progress_session_not_resumed() -> str:
    return "\n\n<i>Session could not be resumed — your next message will start fresh.</i>"


def _progress_completed_with_blocked() -> str:
    return "Completed, but some actions were blocked."


def _progress_completed() -> str:
    return "Completed."


def _busy_message() -> str:
    return "Another request is in progress. Try again in a moment."


def _execution_fault_latched_note() -> str:
    return "Execution fault latched. Reset required before retry."


def _blocked_execution_message(detail: str) -> str:
    detail_text = str(detail or "Execution is faulted.").strip()
    return (
        "Bot execution is faulted and new requests are blocked until reset.\n"
        f"Last failure: {detail_text}"
    )


def _approval_already_waiting() -> str:
    return "A plan is already waiting. Use /approve or /reject first."


def _approval_preparing() -> str:
    return "Preparing your plan…"


def _approval_timeout() -> str:
    return "Preparing the plan took too long."


def _approval_check_failed_prefix() -> str:
    return "Plan check failed:"


def _approval_required() -> str:
    return "Review the plan below, then approve or reject."


def interactive_followup_unavailable() -> RequestExecutionOutcome:
    return RequestExecutionOutcome(
        status="failed",
        error_text=(
            "Routed task could not continue because it requires an interactive "
            "setup or approval step."
        ),
    )


@dataclass(frozen=True)
class TransportIdentity:
    """Channel-supplied bundle for durable side effects."""

    conversation_key: str
    origin_channel: str
    actor: str
    external_conversation_ref: str
    target_agent_id: str
    conversation_ref: str
    routed_task_id: str
    authority_ref: str
    requested_skills: tuple[str, ...] = ()
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None


@dataclass(frozen=True)
class ExecutionChannelMetadata:
    conversation_key: str
    origin_channel: str
    actor: str
    descriptor: TransportDescriptor | None
    message_conversation_ref: str
    routed_task_id: str
    authority_ref: str
    external_conversation_ref: str
    target_agent_id: str
    requested_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequestExecutionOutcome:
    status: str
    reply_text: str = ""
    error_text: str = ""
    denials: tuple[DenialRecord, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int | None = None
    cached_completion_tokens: int | None = None
    cost_usd: float = 0.0


def completed_reply_outcome(reply_text: str) -> RequestExecutionOutcome:
    return RequestExecutionOutcome(status="completed", reply_text=reply_text)


@dataclass(frozen=True)
class ExecutionRuntime:
    dispatch: ProviderDispatchRuntime
    services: ExecutionServices
    interrupted_exc: type[BaseException]

def build_transport_identity_from_metadata(
    metadata: ExecutionChannelMetadata,
    *,
    conversation_callback_factory: Callable[[str, str], Callable[[str, bool], Awaitable[None]]],
    routed_task_callback_factory: Callable[[str, str], Callable[[str, bool], Awaitable[None]]],
) -> TransportIdentity:
    conversation_ref = metadata.message_conversation_ref
    external_conversation_ref = resolve_external_conversation_ref(
        origin_channel=metadata.origin_channel,
        external_conversation_ref=metadata.external_conversation_ref,
        conversation_ref=conversation_ref,
        conversation_key=metadata.conversation_key,
    )
    if metadata.routed_task_id and metadata.authority_ref:
        return TransportIdentity(
            conversation_key=metadata.conversation_key,
            origin_channel=metadata.origin_channel,
            actor=metadata.actor,
            external_conversation_ref=external_conversation_ref,
            target_agent_id=metadata.target_agent_id,
            conversation_ref=conversation_ref,
            routed_task_id=metadata.routed_task_id,
            authority_ref=metadata.authority_ref,
            requested_skills=metadata.requested_skills,
            timeline_callback=routed_task_callback_factory(
                metadata.routed_task_id,
                metadata.authority_ref,
            ),
        )
    descriptor = metadata.descriptor
    if (
        conversation_ref
        and descriptor is not None
        and descriptor.supports_conversation_binding
        and descriptor.supports_timeline
    ):
        return TransportIdentity(
            conversation_key=metadata.conversation_key,
            origin_channel=metadata.origin_channel,
            actor=metadata.actor,
            external_conversation_ref=external_conversation_ref,
            target_agent_id=metadata.target_agent_id,
            conversation_ref=conversation_ref,
            routed_task_id=metadata.routed_task_id,
            authority_ref=metadata.authority_ref,
            requested_skills=metadata.requested_skills,
            timeline_callback=conversation_callback_factory(
                conversation_ref,
                metadata.routed_task_id,
            ),
        )
    return TransportIdentity(
        conversation_key=metadata.conversation_key,
        origin_channel=metadata.origin_channel,
        actor=metadata.actor,
        external_conversation_ref=external_conversation_ref,
        target_agent_id=metadata.target_agent_id,
        conversation_ref=conversation_ref,
        routed_task_id=metadata.routed_task_id,
        authority_ref=metadata.authority_ref,
        requested_skills=metadata.requested_skills,
        timeline_callback=None,
    )


def _provider_request_content(prompt: str, system_prompt: str) -> str:
    parts: list[str] = []
    if system_prompt:
        parts.append(f"System prompt:\n{system_prompt}")
    parts.append(f"User prompt:\n{prompt}")
    return "\n\n---\n\n".join(parts)


def _should_publish_user_message(transport: TransportIdentity) -> bool:
    actor = str(transport.actor or "")
    return not (
        actor.startswith("reg:delegation-resume:")
        or actor.startswith("delegation-resume:")
    )


def _approval_expires_at(timeout_seconds: int) -> str:
    ttl_seconds = max(3600, timeout_seconds)
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _approval_event_id(conversation_key: str, callback_token: str) -> str:
    return f"approval:{conversation_key}:{callback_token}"


def _retry_approval_content(denials: list[DenialRecord]) -> str:
    lines = ["Execution needs approval to continue after blocked actions."]
    for denial in denials:
        tool_name = str(denial.get("tool_name") or denial.get("tool") or "tool").strip() or "tool"
        reason = str(denial.get("message") or denial.get("detail") or "blocked").strip() or "blocked"
        lines.append(f"- {tool_name}: {reason}")
    return "\n".join(lines)


async def _discover_available_agents(
    runtime: ExecutionRuntime,
    cfg,
) -> list[DiscoveredAgentRef] | None:
    if runtime.services.agent_directory is None:
        return None
    try:
        result = await runtime.services.agent_directory.search_agents(query=AgentDiscoveryQuery())
        if not result.agents:
            return None
        own_slug = cfg.agent_slug or cfg.instance
        return [a for a in result.agents if a.slug != own_slug]
    except Exception:
        _log.debug("Agent discovery failed, proceeding without agent context", exc_info=True)
        return None


def _load(runtime: ExecutionRuntime, conversation_key: str) -> SessionState:
    cfg = runtime.dispatch.config
    provider = runtime.dispatch.provider
    session = runtime.services.sessions.load(
        conversation_key,
        provider_name=provider.name,
        provider_state_factory=provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    if runtime.services.skill_activation.normalize(session):
        _save(runtime, conversation_key, session)
    return session


def _save(runtime: ExecutionRuntime, conversation_key: str, session: SessionState) -> None:
    runtime.services.sessions.save(conversation_key, session)


def _event_sink(runtime: ExecutionRuntime, transport: TransportIdentity) -> ExecutionEventSink:
    from octopus_sdk.event_sink import _NOOP_SINK, build_event_sink_for_context

    projection = runtime.services.conversation_projection
    if projection is None:
        return _NOOP_SINK
    return build_event_sink_for_context(transport, projection, runtime.dispatch.config)


def _resolve_context(
    runtime: ExecutionRuntime,
    session: SessionState,
    *,
    trust_tier: str,
) -> ResolvedExecutionContext:
    return runtime.services.sessions.resolve_context(
        session,
        config=runtime.dispatch.config,
        provider_name=runtime.dispatch.provider.name,
        trust_tier=trust_tier,
    )


def check_prompt_size_cross_chat(
    data_dir: Path,
    skill_name: str,
    *,
    runtime: ExecutionRuntime,
) -> list[str]:
    cfg = runtime.dispatch.config
    return runtime.services.guidance.check_prompt_size_cross_chat(
        data_dir,
        skill_name,
        cfg.provider_name,
        runtime.dispatch.provider.new_provider_state,
        cfg.approval_mode,
    )


def load_approval_mode(
    conversation_key: str,
    *,
    runtime: ExecutionRuntime,
) -> str:
    return _load(runtime, conversation_key).approval_mode


def prompt_weight(
    role: str,
    active_skills: list[str],
    available_agents: list[DiscoveredAgentRef] | None = None,
    *,
    runtime: ExecutionRuntime,
) -> int:
    return runtime.services.guidance.prompt_weight(
        role,
        active_skills,
        available_agents=available_agents,
    )


async def check_credential_satisfaction(
    conversation_key: str,
    actor_key: str,
    session: SessionState,
    message: TransportEgress,
    *,
    resolved: ResolvedExecutionContext,
    runtime: ExecutionRuntime,
) -> CredentialEnvRecord | None:
    outcome = runtime.services.runtime_skill_setup.check_satisfaction(
        session,
        actor_key=actor_key,
        active_skills=resolved.active_skills,
    )
    if outcome.status == "satisfied":
        return outcome.credential_env or CredentialEnvRecord()
    if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
        await message.show_foreign_setup(outcome.foreign_setup)
        return None
    if (
        outcome.status != "needs_setup"
        or outcome.setup_state is None
        or outcome.first_requirement is None
    ):
        return None
    _save(runtime, conversation_key, session)
    await message.show_setup_prompt(outcome.missing_skill, outcome.first_requirement)
    return None


async def _execute_request_locked(
    transport: TransportIdentity,
    prompt: str,
    image_paths: list[str],
    message: TransportEgress,
    extra_dirs: list[str] | None = None,
    skip_permissions: bool = False,
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    *,
    runtime: ExecutionRuntime,
) -> RequestExecutionOutcome | None:
    cfg = runtime.dispatch.config
    prov = runtime.dispatch.provider
    guidance = runtime.services.guidance

    conversation_key = transport.conversation_key
    event_sink = _event_sink(runtime, transport)

    session = _load(runtime, conversation_key)
    resolved = _resolve_context(runtime, session, trust_tier=trust_tier)

    credential_env = await check_credential_satisfaction(
        conversation_key,
        transport.actor,
        session,
        message,
        resolved=resolved,
        runtime=runtime,
    )
    if credential_env is None:
        return None

    if _should_publish_user_message(transport):
        await event_sink.on_user_message(prompt, actor=transport.actor)

    upload_dir = str(runtime.services.artifacts.upload_dir(conversation_key))
    all_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs) + (extra_dirs or [])

    if prov.name == "codex":
        scripts_dir = guidance.stage_codex_scripts(
            cfg.data_dir,
            conversation_key,
            resolved.active_skills,
        )
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    available_agents = await _discover_available_agents(runtime, cfg)

    context = guidance.build_run_context(
        resolved.role,
        resolved.active_skills,
        all_extra_dirs,
        provider_name=prov.name,
        credential_env=credential_env,
        working_dir=resolved.working_dir,
        file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
        available_agents=available_agents,
    )
    context.skip_permissions = skip_permissions or trusted_conversation_bypasses_approvals(
        session,
        trust_tier=trust_tier,
    )

    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    context.system_prompt = guidance.apply_compact_mode(context.system_prompt, compact)
    context_hash = resolved.context_hash

    if prov.name == "codex":
        stored_hash = session.provider_state.get("context_hash")
        stored_boot = session.provider_state.get("boot_id")
        stale_thread = (
            (stored_hash and stored_hash != context_hash)
            or (stored_boot and stored_boot != runtime.dispatch.boot_id)
        )
        if stale_thread and session.provider_state.get("thread_id"):
            session.provider_state["thread_id"] = None
        session.provider_state["context_hash"] = context_hash
        session.provider_state["boot_id"] = runtime.dispatch.boot_id
        _save(runtime, conversation_key, session)

    is_resume = bool(session.provider_state.get("thread_id") or session.provider_state.get("started"))
    provider_request_content = _provider_request_content(prompt, context.system_prompt)
    requested_skills = tuple(
        str(skill).strip().lower()
        for skill in (transport.requested_skills or ())
        if str(skill).strip()
    )
    active_skill_slugs = tuple(
        str(skill).strip().lower()
        for skill in session.active_skills
        if str(skill).strip()
    )
    composed_skill_slugs = tuple(
        str(skill).strip().lower()
        for skill in resolved.active_skills
        if str(skill).strip()
    )
    composed_track_revision_ids = tuple(
        str(resolved.skill_revision_ids.get(skill, "")).strip()
        for skill in composed_skill_slugs
        if str(resolved.skill_revision_ids.get(skill, "")).strip()
    )
    skill_kind_map = {
        str(skill).strip().lower(): normalize_skill_kind(resolved.skill_kinds.get(skill, "prompt"))
        for skill in composed_skill_slugs
    }
    skill_manifest = {
        "schema_version": 1,
        "routed_task_id": str(transport.routed_task_id or ""),
        "conversation_key": conversation_key,
        "bot_slug": str(cfg.agent_slug or cfg.instance or ""),
        "requested_skills": list(requested_skills),
        "active_skills": list(active_skill_slugs),
        "composed_skill_slugs": list(composed_skill_slugs),
        "composed_track_revision_ids": list(composed_track_revision_ids),
        "invoked_skill_slugs": [],
        "skill_kind_map": skill_kind_map,
        "prompt_manifest_hash": skill_execution_manifest_hash(
            routed_task_id=str(transport.routed_task_id or ""),
            conversation_key=conversation_key,
            bot_slug=str(cfg.agent_slug or cfg.instance or ""),
            requested_skills=requested_skills,
            active_skills=active_skill_slugs,
            composed_skill_slugs=composed_skill_slugs,
            composed_track_revision_ids=composed_track_revision_ids,
            invoked_skill_slugs=(),
            skill_kind_map=skill_kind_map,
        ),
    }
    await event_sink.on_provider_request(
        provider_request_content,
        provider=prov.name,
        model=resolved.effective_model or cfg.model or prov.name,
        execution_mode="resume" if is_resume else "run",
        working_dir=str(resolved.working_dir or cfg.working_dir),
        file_policy=resolved.file_policy or "edit",
        image_count=len(image_paths),
        prompt_char_count=len(provider_request_content),
        skill_manifest=skill_manifest,
    )
    label = _progress_resuming() if is_resume else _progress_working()

    dispatched = await run_provider_request(
        conversation_key,
        prompt=prompt,
        image_paths=image_paths,
        message=message,
        provider_state=session.provider_state,
        context=context,
        cancel_event=cancel_event,
        label=label,
        runtime=runtime.dispatch,
        timeline_callback=transport.timeline_callback,
    )
    progress = dispatched.progress
    result = dispatched.result

    if result.cancelled:
        session.provider_state.update(result.provider_state_updates)
        _save(runtime, conversation_key, session)
        await progress.update(_cancel_live_completed(), force=True)
        return RequestExecutionOutcome(status="cancelled")

    if runtime.dispatch.run_result_was_interrupted(result.returncode):
        raise runtime.interrupted_exc()

    session.provider_state.update(result.provider_state_updates)

    if result.resume_failed:
        if prov.name == "codex":
            session.provider_state["thread_id"] = None
        else:
            session.provider_state.update(prov.new_provider_state(conversation_key))
    elif prov.name == "codex" and is_resume and not result.timed_out and result.returncode and result.returncode != 0:
        session.provider_state["thread_id"] = None

    _save(runtime, conversation_key, session)

    await event_sink.on_provider_response(
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cached_prompt_tokens=result.cached_prompt_tokens,
        cached_completion_tokens=result.cached_completion_tokens,
        cost_usd=result.cost_usd,
        provider=prov.name,
    )
    for index, record in enumerate(result.tool_executions):
        await event_sink.on_tool_execution(record, index=index)

    if result.timed_out:
        await progress.update(_progress_request_timed_out(cfg.timeout_seconds), force=True)
        return RequestExecutionOutcome(status="timed_out")

    if result.returncode != 0:
        raw_error_text = await runtime.dispatch.format_provider_error(result.text, result.returncode)
        latched_fault = None
        if runtime.services.execution_faults is not None:
            latched_fault = runtime.services.execution_faults.record_provider_failure(
                provider_name=prov.name,
                error_text=raw_error_text,
                returncode=result.returncode,
            )
        error_text = html.escape(raw_error_text)
        if latched_fault is not None:
            error_text = f"{error_text}\n\n{html.escape(_execution_fault_latched_note())}"
        if result.resume_failed:
            error_text += html.escape(_progress_session_not_resumed())
        await progress.update(error_text, force=True)
        await event_sink.on_error(
            error_text,
            error_type="provider_error",
            message=raw_error_text[:500],
        )
        return RequestExecutionOutcome(status="failed", error_text=error_text)

    if result.denials:
        await progress.update(_progress_completed_with_blocked(), force=True)
        session = _load(runtime, conversation_key)
        session.pending_retry = PendingRetry(
            actor_key=transport.actor,
            prompt=prompt,
            image_paths=image_paths,
            context_hash=context_hash,
            denials=result.denials,
            callback_token=secrets.token_hex(6),
            trust_tier=trust_tier,
            created_at=time.time(),
        )
        _save(runtime, conversation_key, session)
        await event_sink.on_approval_requested(
            _retry_approval_content(result.denials),
            request_kind="retry",
            actor_key=transport.actor,
            trust_tier=trust_tier,
            expires_at=_approval_expires_at(cfg.timeout_seconds),
            request_id=_approval_event_id(conversation_key, session.pending_retry.callback_token),
        )
        await message.send_retry_prompt(tuple(result.denials), session.pending_retry.callback_token)
        cleaned_reply, directives = extract_send_directives(result.text)
        if cleaned_reply.strip():
            await message.send_formatted_reply(cleaned_reply)
            await message.send_directed_artifacts(
                conversation_key,
                directives,
                resolved_ctx=resolved,
            )
        return RequestExecutionOutcome(
            status="completed_with_denials",
            reply_text=cleaned_reply,
            denials=tuple(result.denials),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cached_prompt_tokens=result.cached_prompt_tokens,
            cached_completion_tokens=result.cached_completion_tokens,
            cost_usd=result.cost_usd,
        )

    if result.coordination_intent is not None:
        intent = result.coordination_intent
        _log.info("Coordination intent present (%d task(s)), proposing plan", len(intent.tasks))
        await progress.update("Delegation plan ready.", force=True)
        session = _load(runtime, conversation_key)
        return await message.propose_delegation_plan(
            conversation_key,
            session,
            conversation_ref=transport.conversation_ref,
            result=result,
        )

    await progress.update(_progress_completed(), force=True)
    cleaned_reply, directives = extract_send_directives(result.text)
    slot = runtime.services.artifacts.save_raw(conversation_key, prompt, cleaned_reply)

    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and len(cleaned_reply) > 800 and transport.origin_channel == "telegram":
        await message.send_compact_reply(cleaned_reply, conversation_key, slot)
    else:
        await message.send_formatted_reply(cleaned_reply)
    await message.send_directed_artifacts(
        conversation_key,
        directives,
        resolved_ctx=resolved,
    )
    await event_sink.on_bot_reply(cleaned_reply[:2000] if cleaned_reply else "")
    return RequestExecutionOutcome(
        status="completed",
        reply_text=cleaned_reply,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cached_prompt_tokens=result.cached_prompt_tokens,
        cached_completion_tokens=result.cached_completion_tokens,
        cost_usd=result.cost_usd,
    )


async def execute_request(
    transport: TransportIdentity,
    prompt: str,
    image_paths: list[str],
    message: TransportEgress,
    extra_dirs: list[str] | None = None,
    skip_permissions: bool = False,
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    *,
    runtime: ExecutionRuntime,
) -> RequestExecutionOutcome | None:
    conversation_key = transport.conversation_key
    event_sink = _event_sink(runtime, transport)

    if runtime.services.execution_faults is not None:
        execution_state = runtime.services.execution_faults.load()
        if str(execution_state.state or "healthy") == "faulted":
            blocked_text = html.escape(_blocked_execution_message(execution_state.detail))
            await message.send_formatted_reply(blocked_text)
            await event_sink.on_error(
                blocked_text,
                error_type="execution_fault",
                message=str(execution_state.detail or blocked_text)[:500],
            )
            return RequestExecutionOutcome(status="failed", error_text=blocked_text)

    if conversation_key in runtime.dispatch.execution_inflight:
        busy_text = html.escape(_busy_message())
        await message.send_formatted_reply(busy_text)
        await event_sink.on_error(
            busy_text,
            error_type="busy",
            message=_busy_message(),
        )
        return RequestExecutionOutcome(status="failed", error_text=busy_text)

    runtime.dispatch.execution_inflight.add(conversation_key)
    try:
        return await _execute_request_locked(
            transport,
            prompt,
            image_paths,
            message,
            extra_dirs,
            skip_permissions,
            trust_tier,
            cancel_event,
            runtime=runtime,
        )
    finally:
        runtime.dispatch.execution_inflight.discard(conversation_key)


async def dispatch_message_request(
    transport: TransportIdentity,
    prompt: str,
    image_paths: list[str],
    attachments: list[InboundAttachment],
    message: TransportEgress,
    *,
    approval_mode: str,
    routed_task_id: str = "",
    skip_approval: bool = False,
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    runtime: ExecutionRuntime,
) -> RequestExecutionOutcome | None:
    if not routed_task_id and not skip_approval and approval_mode == "on":
        await request_approval(
            transport,
            prompt,
            image_paths,
            attachments,
            message,
            trust_tier=trust_tier,
            cancel_event=cancel_event,
            runtime=runtime,
        )
        return None
    return await execute_request(
        transport,
        prompt,
        image_paths,
        message,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
        runtime=runtime,
    )


async def request_approval(
    transport: TransportIdentity,
    prompt: str,
    image_paths: list[str],
    attachments,
    message: TransportEgress,
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    *,
    runtime: ExecutionRuntime,
) -> None:
    cfg = runtime.dispatch.config
    prov = runtime.dispatch.provider
    guidance = runtime.services.guidance
    conversation_key = transport.conversation_key
    event_sink = _event_sink(runtime, transport)
    session = _load(runtime, conversation_key)

    if session.has_pending:
        await message.send_text(_approval_already_waiting())
        return

    resolved = _resolve_context(runtime, session, trust_tier=trust_tier)
    credential_env = await check_credential_satisfaction(
        conversation_key,
        transport.actor,
        session,
        message,
        resolved=resolved,
        runtime=runtime,
    )
    if credential_env is None:
        return
    del credential_env

    upload_dir = str(runtime.services.artifacts.upload_dir(conversation_key))
    preflight_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs)
    preflight_context = guidance.build_preflight_context(
        resolved.role,
        resolved.active_skills,
        preflight_extra_dirs,
        provider_name=prov.name,
        working_dir=resolved.working_dir,
        file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
    )
    context_hash = resolved.context_hash

    dispatched = await run_provider_preflight(
        conversation_key,
        prompt=build_preflight_prompt(prompt, prov.name),
        image_paths=image_paths,
        message=message,
        context=preflight_context,
        cancel_event=cancel_event,
        label=_approval_preparing(),
        runtime=runtime.dispatch,
        timeline_callback=transport.timeline_callback,
    )
    progress = dispatched.progress
    plan_result = dispatched.result

    if plan_result.cancelled:
        await progress.update(_cancel_live_completed(), force=True)
        return

    if runtime.dispatch.run_result_was_interrupted(plan_result.returncode):
        raise runtime.interrupted_exc()

    if plan_result.timed_out:
        await progress.update(_approval_timeout(), force=True)
        return

    if plan_result.returncode != 0:
        error_text = await runtime.dispatch.format_provider_error(plan_result.text, plan_result.returncode)
        rendered_error = html.escape(
            f"{_approval_check_failed_prefix()}\n{error_text}"
        )
        await progress.update(rendered_error, force=True)
        return

    attachment_dicts = [
        PendingApprovalAttachmentRecord(
            path=str(a.path),
            original_name=a.original_name,
            is_image=a.is_image,
            mime_type=a.mime_type,
        )
        for a in attachments
    ]
    session.pending_approval = PendingApproval(
        actor_key=transport.actor,
        prompt=prompt,
        image_paths=image_paths,
        attachment_dicts=attachment_dicts,
        context_hash=context_hash,
        callback_token=secrets.token_hex(6),
        trust_tier=trust_tier,
        created_at=time.time(),
    )
    plan_text = plan_result.text or "[empty plan]"
    _save(runtime, conversation_key, session)
    await event_sink.on_approval_requested(
        plan_text,
        request_kind="preflight",
        actor_key=transport.actor,
        trust_tier=trust_tier,
        expires_at=_approval_expires_at(cfg.timeout_seconds),
        request_id=_approval_event_id(conversation_key, session.pending_approval.callback_token),
    )

    await progress.update(_approval_required(), force=True)
    runtime.services.artifacts.save_raw(conversation_key, prompt, plan_text, kind="approval")
    await message.send_formatted_reply("**Approval plan:**\n\n" + plan_text)
    await message.send_approval_prompt(session.pending_approval.callback_token)
