"""Execution and preflight workflow ownership."""

from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path

from app import user_messages as _msg
from app.approvals import build_preflight_prompt
from app.execution_context import ResolvedExecutionContext
from app.formatting import extract_send_directives
from app.provider_guidance_service import get_provider_guidance_service
from app.request_flow import extra_dirs_from_denials
from app.runtime import composition
from app.runtime.dispatch import run_provider_preflight, run_provider_request
from app.runtime.session_runtime import (
    load_runtime_session,
    resolve_session_context,
    save_runtime_session,
)
from app.session_state import PendingApproval, PendingRetry, SessionState
from app.storage import chat_upload_dir
from app.summarize import save_raw
from app.skill_activation_service import get_skill_activation_service
from app import work_queue
from app.runtime.inbound_types import InboundAttachment
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    RequestExecutionOutcome,
)
from app.ports.delegation import DelegationIntentParser
from app.workflows.execution.delegation_parser import XmlTagDelegationParser

import json
import logging
from uuid import uuid4

_log = logging.getLogger(__name__)

_DEFAULT_DELEGATION_PARSER = XmlTagDelegationParser()


async def _discover_available_agents(
    runtime: ExecutionRuntime,
    cfg,
) -> list[dict[str, str]] | None:
    """Query agent directory for available agents, returns None if unavailable."""
    if runtime.agent_directory is None:
        return None
    try:
        from app.agents.types import AgentDiscoveryQuery
        result = await runtime.agent_directory.search_agents(
            query=AgentDiscoveryQuery(),
        )
        if not result.agents:
            return None
        # Exclude self by slug (cfg.instance matches the bot's slug)
        own_slug = cfg.agent_slug or cfg.instance
        return [
            {
                "display_name": a.display_name,
                "slug": a.slug,
                "role": a.role,
                "capabilities": ", ".join(a.capabilities) if a.capabilities else "",
                "connectivity_state": a.connectivity_state,
                "agent_id": a.agent_id,
            }
            for a in result.agents
            if a.slug != own_slug
        ]
    except Exception:
        _log.debug("Agent discovery failed, proceeding without agent context", exc_info=True)
        return None


def _parse_delegation_from_response(
    text: str,
    available_agents: list[dict[str, str]] | None,
    parser: DelegationIntentParser | None = None,
) -> list[dict[str, str]]:
    """Parse delegation intent using the provided or default parser."""
    if not available_agents:
        return []
    effective_parser = parser or _DEFAULT_DELEGATION_PARSER
    return effective_parser.parse(text, available_agents)



def _load(runtime: ExecutionRuntime, conversation_key: str) -> SessionState:
    cfg = runtime.dispatch.config
    provider = runtime.dispatch.provider
    session = load_runtime_session(
        cfg.data_dir,
        conversation_key,
        provider_name=provider.name,
        provider_state_factory=provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    _log.debug("_load(%s): session_id=%s started=%s", conversation_key[:40],
               session.provider_state.get("session_id", "")[:12],
               session.provider_state.get("started"))
    if get_skill_activation_service().normalize(session):
        _save(runtime, conversation_key, session)
    return session


def _save(runtime: ExecutionRuntime, conversation_key: str, session: SessionState) -> None:
    save_runtime_session(runtime.dispatch.config.data_dir, conversation_key, session)


def _resolve_context(
    runtime: ExecutionRuntime,
    session: SessionState,
    *,
    trust_tier: str,
) -> ResolvedExecutionContext:
    return resolve_session_context(
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
    return get_provider_guidance_service().check_prompt_size_cross_chat(
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


def prompt_weight(role: str, active_skills: list[str], available_agents: list[dict[str, str]] | None = None) -> int:
    return get_provider_guidance_service().prompt_weight(role, active_skills, available_agents=available_agents)


async def check_credential_satisfaction(
    conversation_key: str,
    actor_key: str,
    session: SessionState,
    message,
    *,
    resolved: ResolvedExecutionContext,
    runtime: ExecutionRuntime,
) -> dict[str, str] | None:
    outcome = composition.workflows().runtime_skills.setup.check_satisfaction(
        session,
        user_id=actor_key,
        active_skills=resolved.active_skills,
    )
    if outcome.status == "satisfied":
        return outcome.credential_env or {}
    if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
        await runtime.show_foreign_setup(message, outcome.foreign_setup)
        return None
    if (
        outcome.status != "needs_setup"
        or outcome.setup_state is None
        or outcome.first_requirement is None
    ):
        return None
    _save(runtime, conversation_key, session)
    await runtime.show_setup_prompt(
        message,
        outcome.missing_skill,
        outcome.first_requirement,
    )
    return None


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
    *,
    runtime: ExecutionRuntime,
) -> RequestExecutionOutcome | None:
    cfg = runtime.dispatch.config
    prov = runtime.dispatch.provider
    guidance = get_provider_guidance_service()

    # Build transport identity and event sink FIRST — all durable operations use transport fields
    transport = runtime.build_transport_identity(message, chat_id)
    conversation_key = transport.conversation_key
    event_sink = runtime.build_event_sink(transport)

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

    await event_sink.on_user_message(prompt, actor=str(request_user_id) if request_user_id else "")

    upload_dir = str(chat_upload_dir(cfg.data_dir, conversation_key))
    all_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs) + (extra_dirs or [])

    if prov.name == "codex":
        scripts_dir = guidance.stage_codex_scripts(
            cfg.data_dir,
            conversation_key,
            resolved.active_skills,
        )
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    # Discover available agents for delegation context in system prompt
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
    autonomous_grant = cfg.autonomous and session.approval_mode != "on"
    context.skip_permissions = skip_permissions or autonomous_grant

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
    label = _msg.progress_resuming() if is_resume else _msg.progress_working()

    dispatched = await run_provider_request(
        chat_id,
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
        await progress.update(_msg.cancel_live_completed(), force=True)
        return RequestExecutionOutcome(status="cancelled")

    if runtime.dispatch.run_result_was_interrupted(result.returncode):
        raise work_queue.LeaveClaimed()

    session.provider_state.update(result.provider_state_updates)

    if result.resume_failed:
        if prov.name == "codex":
            session.provider_state["thread_id"] = None
        else:
            session.provider_state.update(prov.new_provider_state())
    elif prov.name == "codex" and is_resume and not result.timed_out and result.returncode and result.returncode != 0:
        session.provider_state["thread_id"] = None

    _save(runtime, conversation_key, session)
    _log.info("Session saved after provider return: session_id=%s started=%s",
              session.provider_state.get("session_id", "")[:12],
              session.provider_state.get("started"))

    await event_sink.on_provider_response(
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
        provider=prov.name,
    )

    if result.timed_out:
        await progress.update(_msg.progress_request_timed_out(cfg.timeout_seconds), force=True)
        return RequestExecutionOutcome(status="timed_out")

    if result.returncode != 0:
        error_text = await runtime.dispatch.format_provider_error(result.text, result.returncode)
        error_text = runtime.render_provider_error(error_text)
        if result.resume_failed:
            error_text += runtime.render_provider_error(_msg.progress_session_not_resumed())
        await progress.update(error_text, force=True)
        await event_sink.on_error(error_text, error_type="provider_error", message=error_text[:500])
        return RequestExecutionOutcome(status="failed", error_text=error_text)

    if result.denials:
        await progress.update(_msg.progress_completed_with_blocked(), force=True)
        session = _load(runtime, conversation_key)
        session.pending_retry = PendingRetry(
            request_user_id=request_user_id,
            prompt=prompt,
            image_paths=image_paths,
            context_hash=context_hash,
            denials=result.denials,
            callback_token=secrets.token_hex(6),
            trust_tier=trust_tier,
            created_at=time.time(),
        )
        _save(runtime, conversation_key, session)
        await runtime.send_retry_prompt(
            message,
            tuple(result.denials),
            session.pending_retry.callback_token,
        )
        cleaned_reply, directives = extract_send_directives(result.text)
        if cleaned_reply.strip():
            await runtime.send_formatted_reply(message, cleaned_reply)
            await runtime.send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
        return RequestExecutionOutcome(
            status="completed_with_denials",
            reply_text=cleaned_reply,
            denials=tuple(result.denials),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
        )

    # Parse delegation intent from provider response if not already populated
    if not result.delegation_tasks and available_agents:
        parsed_tasks = _parse_delegation_from_response(result.text, available_agents, parser=runtime.delegation_parser)
        if parsed_tasks:
            _log.info("Parsed %d delegation tasks from provider response", len(parsed_tasks))
            result.delegation_tasks.extend(parsed_tasks)

    if result.delegation_tasks:
        _log.info("Delegation tasks present (%d), proposing plan", len(result.delegation_tasks))
        await progress.update("Delegation plan ready.", force=True)
        session = _load(runtime, conversation_key)
        _log.info("Session reloaded for delegation: session_id=%s started=%s",
                  session.provider_state.get("session_id", "")[:12],
                  session.provider_state.get("started"))
        return await runtime.propose_delegation_plan(
            chat_id,
            message,
            session,
            conversation_ref=transport.conversation_ref,
            result=result,
        )

    await progress.update(_msg.progress_completed(), force=True)
    cleaned_reply, directives = extract_send_directives(result.text)
    slot = save_raw(cfg.data_dir, conversation_key, prompt, cleaned_reply)

    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and len(cleaned_reply) > 800 and transport.origin_channel == "telegram":
        await runtime.send_compact_reply(message, cleaned_reply, chat_id, slot)
    else:
        await runtime.send_formatted_reply(message, cleaned_reply)
    await runtime.send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
    await event_sink.on_bot_reply(cleaned_reply[:2000] if cleaned_reply else "")
    return RequestExecutionOutcome(
        status="completed",
        reply_text=cleaned_reply,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
    )


async def dispatch_message_request(
    chat_id: int | str,
    prompt: str,
    image_paths: list[str],
    attachments: list[InboundAttachment],
    message,
    *,
    approval_mode: str,
    routed_task_id: str = "",
    skip_approval: bool = False,
    request_user_id: int | str = "",
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    runtime: ExecutionRuntime,
) -> RequestExecutionOutcome | None:
    if not routed_task_id and not skip_approval and approval_mode == "on":
        await request_approval(
            chat_id,
            prompt,
            image_paths,
            attachments,
            message,
            request_user_id=request_user_id,
            trust_tier=trust_tier,
            cancel_event=cancel_event,
            runtime=runtime,
        )
        return None
    return await execute_request(
        chat_id,
        prompt,
        image_paths,
        message,
        request_user_id=request_user_id,
        trust_tier=trust_tier,
        cancel_event=cancel_event,
        runtime=runtime,
    )


async def request_approval(
    chat_id: int | str,
    prompt: str,
    image_paths: list[str],
    attachments,
    message,
    request_user_id: int | str = "",
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    *,
    runtime: ExecutionRuntime,
) -> None:
    cfg = runtime.dispatch.config
    prov = runtime.dispatch.provider
    guidance = get_provider_guidance_service()
    transport = runtime.build_transport_identity(message, chat_id)
    conversation_key = transport.conversation_key
    session = _load(runtime, conversation_key)

    if session.has_pending:
        await message.reply_text(_msg.approval_already_waiting())
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

    upload_dir = str(chat_upload_dir(cfg.data_dir, conversation_key))
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
        chat_id,
        prompt=build_preflight_prompt(prompt, prov.name),
        image_paths=image_paths,
        message=message,
        context=preflight_context,
        cancel_event=cancel_event,
        label=_msg.approval_preparing(),
        runtime=runtime.dispatch,
        timeline_callback=transport.timeline_callback,
    )
    progress = dispatched.progress
    plan_result = dispatched.result

    if plan_result.cancelled:
        await progress.update(_msg.cancel_live_completed(), force=True)
        return

    if runtime.dispatch.run_result_was_interrupted(plan_result.returncode):
        raise work_queue.LeaveClaimed()

    if plan_result.timed_out:
        await progress.update(_msg.approval_timeout(), force=True)
        return

    if plan_result.returncode != 0:
        error_text = await runtime.dispatch.format_provider_error(plan_result.text, plan_result.returncode)
        rendered_error = runtime.render_provider_error(
            f"{_msg.approval_check_failed_prefix()}\n{error_text}"
        )
        await progress.update(rendered_error, force=True)
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
        callback_token=secrets.token_hex(6),
        trust_tier=trust_tier,
        created_at=time.time(),
    )
    _save(runtime, conversation_key, session)

    await progress.update(_msg.approval_required(), force=True)
    plan_text = plan_result.text or "[empty plan]"
    save_raw(runtime.dispatch.config.data_dir, conversation_key, prompt, plan_text, kind="approval")
    await runtime.send_formatted_reply(message, "**Approval plan:**\n\n" + plan_text)
    await runtime.send_approval_prompt(message, session.pending_approval.callback_token)
