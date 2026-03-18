"""Runtime request orchestration outside Telegram adapter ownership."""

from __future__ import annotations

import asyncio
import html
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app import user_messages as _msg
from app.credential_flow import foreign_setup_message, format_credential_prompt
from app.provider_guidance_service import get_provider_guidance_service
from app.runtime import composition
from app import work_queue


def _th():
    import app.channels.telegram.ingress as th

    return th


def check_prompt_size_cross_chat(data_dir: Path, skill_name: str) -> list[str]:
    th = _th()
    cfg = th._cfg()
    return get_provider_guidance_service().check_prompt_size_cross_chat(
        data_dir,
        skill_name,
        cfg.provider_name,
        th._prov().new_provider_state,
        cfg.approval_mode,
    )


def prompt_weight(role: str, active_skills: list[str]) -> int:
    return get_provider_guidance_service().prompt_weight(role, active_skills)


async def check_credential_satisfaction(
    chat_id: int | str,
    user_id: int | str,
    session,
    message,
    *,
    resolved,
) -> dict[str, str] | None:
    th = _th()
    outcome = composition.workflows().runtime_skills.setup.check_satisfaction(
        session,
        user_id=th._actor_key(user_id),
        active_skills=resolved.active_skills,
    )
    if outcome.status == "satisfied":
        return outcome.credential_env or {}
    if outcome.status == "foreign_setup" and outcome.foreign_setup is not None:
        await message.reply_text(foreign_setup_message(outcome.foreign_setup))
        return None
    if outcome.status != "needs_setup" or outcome.setup_state is None or outcome.first_requirement is None:
        return None
    th._save(chat_id, session)
    await message.reply_text(
        f"Skill <code>{html.escape(outcome.missing_skill)}</code> needs setup.\n\n"
        f"{format_credential_prompt(outcome.first_requirement)}",
        parse_mode=ParseMode.HTML,
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
):
    th = _th()
    cfg = th._cfg()
    prov = th._prov()
    guidance = get_provider_guidance_service()
    session = th._load(chat_id)
    resolved = th._resolve_context(session, trust_tier=trust_tier)

    credential_env = await check_credential_satisfaction(
        chat_id,
        request_user_id,
        session,
        message,
        resolved=resolved,
    )
    if credential_env is None:
        return None

    upload_dir = str(th.chat_upload_dir(cfg.data_dir, th._conversation_key(chat_id)))
    all_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs) + (extra_dirs or [])

    if prov.name == "codex":
        scripts_dir = guidance.stage_codex_scripts(
            cfg.data_dir,
            th._conversation_key(chat_id),
            resolved.active_skills,
        )
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    context = guidance.build_run_context(
        resolved.role,
        resolved.active_skills,
        all_extra_dirs,
        provider_name=prov.name,
        credential_env=credential_env,
        working_dir=resolved.working_dir,
        file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
    )
    context.skip_permissions = skip_permissions

    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    context.system_prompt = guidance.apply_compact_mode(context.system_prompt, compact)
    context_hash = resolved.context_hash

    if prov.name == "codex":
        stored_hash = session.provider_state.get("context_hash")
        stored_boot = session.provider_state.get("boot_id")
        stale_thread = (
            (stored_hash and stored_hash != context_hash)
            or (stored_boot and stored_boot != th._boot_id)
        )
        if stale_thread and session.provider_state.get("thread_id"):
            th.log.info(
                "Clearing stale codex thread for chat %d (hash_match=%s, boot_match=%s)",
                chat_id,
                stored_hash == context_hash,
                stored_boot == th._boot_id,
            )
            session.provider_state["thread_id"] = None
        session.provider_state["context_hash"] = context_hash
        session.provider_state["boot_id"] = th._boot_id
        th._save(chat_id, session)

    is_resume = bool(session.provider_state.get("thread_id") or session.provider_state.get("started"))
    label = _msg.progress_resuming() if is_resume else _msg.progress_working()
    conversation_ref = ""
    routed_task_id = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "channel_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
        routed_task_id = getattr(message, "routed_task_id", "")
    elif cfg.agent_mode == "registry":
        conversation_ref = th.telegram_conversation_ref(cfg, chat_id)

    timeline_cb = None
    channel_name = getattr(getattr(message, "capabilities", None), "channel_name", "telegram")
    if conversation_ref and channel_name != "registry":
        timeline_cb = lambda html_text, force=False: th._progress_timeline_callback(
            conversation_ref,
            routed_task_id,
            html_text,
            force=force,
        )

    status_msg = await message.reply_text(label)
    progress = th.TelegramProgress(status_msg, cfg, timeline_callback=timeline_cb)
    content_started = asyncio.Event()
    progress.content_started = content_started
    typing_task = asyncio.create_task(th.keep_typing(message.chat))
    heartbeat_task = asyncio.create_task(th._heartbeat(progress, content_started))

    local_cancel_event = cancel_event or asyncio.Event()
    th._LIVE_CANCEL[chat_id] = local_cancel_event
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
        th._LIVE_CANCEL.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    if result.cancelled:
        session = th._load(chat_id)
        session.provider_state.update(result.provider_state_updates)
        th._save(chat_id, session)
        await progress.update(_msg.cancel_live_completed(), force=True)
        return th.RequestExecutionOutcome(status="cancelled")

    if th._run_result_was_interrupted(result.returncode):
        th.log.info("%s interrupted for chat %d (rc=%s); leaving work item claimed", prov.name, chat_id, result.returncode)
        raise work_queue.LeaveClaimed()

    session = th._load(chat_id)
    session.provider_state.update(result.provider_state_updates)

    if result.resume_failed:
        th.log.warning(
            "%s resume target invalid (rc=%s) for chat %d — resetting session state",
            prov.name,
            result.returncode,
            chat_id,
        )
        if prov.name == "codex":
            session.provider_state["thread_id"] = None
        else:
            session.provider_state.update(prov.new_provider_state())
    elif prov.name == "codex" and is_resume and not result.timed_out and result.returncode and result.returncode != 0:
        th.log.warning("codex resume error (rc=%s) for chat %d — clearing thread_id", result.returncode, chat_id)
        session.provider_state["thread_id"] = None

    th._save(chat_id, session)

    if result.timed_out:
        await progress.update(_msg.progress_request_timed_out(cfg.timeout_seconds), force=True)
        return th.RequestExecutionOutcome(status="timed_out")

    if result.returncode != 0:
        error_text = await th._format_provider_error(result.text, result.returncode)
        if result.resume_failed:
            error_text += _msg.progress_session_not_resumed()
        await progress.update(error_text, force=True)
        return th.RequestExecutionOutcome(status="failed", error_text=error_text)

    if result.denials:
        await progress.update(_msg.progress_completed_with_blocked(), force=True)
        session = th._load(chat_id)
        session.pending_retry = th.PendingRetry(
            request_user_id=request_user_id,
            prompt=prompt,
            image_paths=image_paths,
            context_hash=context_hash,
            denials=result.denials,
            trust_tier=trust_tier,
            created_at=time.time(),
        )
        th._save(chat_id, session)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("\u2705 " + _msg.retry_button_grant(), callback_data="retry_allow"),
            InlineKeyboardButton("\u274c " + _msg.retry_button_skip(), callback_data="retry_skip"),
        ]])
        await message.chat.send_message(
            f"\u26a0\ufe0f <b>{_msg.retry_permission_prompt()}</b>\n"
            f"{th.format_denials_html(result.denials)}\n\n"
            f"{_msg.retry_grant_and_retry_question()}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        cleaned_reply, directives = th.extract_send_directives(result.text)
        if cleaned_reply.strip():
            await th.send_formatted_reply(message, cleaned_reply)
            await th.send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
        return th.RequestExecutionOutcome(
            status="completed_with_denials",
            reply_text=cleaned_reply,
            denials=tuple(result.denials),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
        )

    if result.delegation_tasks:
        await progress.update("Delegation plan ready.", force=True)
        session = th._load(chat_id)
        return await th._propose_delegation_plan(
            chat_id,
            message,
            session,
            conversation_ref=conversation_ref or th.telegram_conversation_ref(cfg, chat_id),
            result=result,
        )

    await progress.update(_msg.progress_completed(), force=True)
    cleaned_reply, directives = th.extract_send_directives(result.text)
    slot = th.save_raw(cfg.data_dir, th._conversation_key(chat_id), prompt, cleaned_reply)

    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and len(cleaned_reply) > 800:
        await th._send_compact_reply(message, cleaned_reply, chat_id, slot)
    else:
        await th.send_formatted_reply(message, cleaned_reply)
    await th.send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
    return th.RequestExecutionOutcome(
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
    attachments,
    message,
    request_user_id: int | str = "",
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
) -> None:
    th = _th()
    cfg = th._cfg()
    prov = th._prov()
    guidance = get_provider_guidance_service()
    session = th._load(chat_id)

    if session.has_pending:
        await message.reply_text(_msg.approval_already_waiting())
        return

    resolved = th._resolve_context(session, trust_tier=trust_tier)
    credential_env = await check_credential_satisfaction(
        chat_id,
        request_user_id,
        session,
        message,
        resolved=resolved,
    )
    if credential_env is None:
        return
    del credential_env

    upload_dir = str(th.chat_upload_dir(cfg.data_dir, th._conversation_key(chat_id)))
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

    status_msg = await message.reply_text(_msg.approval_preparing())
    conversation_ref = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "channel_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
    elif cfg.agent_mode == "registry":
        conversation_ref = th.telegram_conversation_ref(cfg, th._telegram_chat_id(chat_id))
    timeline_cb = None
    channel_name = getattr(getattr(message, "capabilities", None), "channel_name", "telegram")
    if conversation_ref and channel_name != "registry":
        timeline_cb = lambda html_text, force=False: th._progress_timeline_callback(
            conversation_ref,
            "",
            html_text,
            force=force,
        )
    progress = th.TelegramProgress(status_msg, cfg, timeline_callback=timeline_cb)
    content_started = asyncio.Event()
    progress.content_started = content_started
    typing_task = asyncio.create_task(th.keep_typing(message.chat))
    heartbeat_task = asyncio.create_task(th._heartbeat(progress, content_started))

    preflight_prompt = th.build_preflight_prompt(prompt, prov.name)
    local_cancel_event = cancel_event or asyncio.Event()
    th._LIVE_CANCEL[chat_id] = local_cancel_event
    try:
        plan_result = await prov.run_preflight(
            preflight_prompt,
            image_paths,
            progress,
            context=preflight_context,
            cancel=local_cancel_event,
        )
    finally:
        th._LIVE_CANCEL.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    if plan_result.cancelled:
        await progress.update(_msg.cancel_live_completed(), force=True)
        return

    if th._run_result_was_interrupted(plan_result.returncode):
        th.log.info("Preflight interrupted for chat %d (rc=%s); leaving work item claimed", chat_id, plan_result.returncode)
        raise work_queue.LeaveClaimed()

    if plan_result.timed_out:
        await progress.update(_msg.approval_timeout(), force=True)
        return

    if plan_result.returncode != 0:
        error_text = await th._format_provider_error(plan_result.text, plan_result.returncode)
        await progress.update(f"{_msg.approval_check_failed_prefix()}\n{error_text}", force=True)
        return

    attachment_dicts = [
        {"path": str(a.path), "original_name": a.original_name, "is_image": a.is_image}
        for a in attachments
    ]
    session.pending_approval = th.PendingApproval(
        request_user_id=request_user_id,
        prompt=prompt,
        image_paths=image_paths,
        attachment_dicts=attachment_dicts,
        context_hash=context_hash,
        trust_tier=trust_tier,
        created_at=time.time(),
    )
    th._save(chat_id, session)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 " + _msg.approval_button_approve(), callback_data="approval_approve"),
        InlineKeyboardButton("\u274c " + _msg.approval_button_reject(), callback_data="approval_reject"),
    ]])
    await progress.update(_msg.approval_required(), force=True)
    plan_text = plan_result.text or "[empty plan]"
    th.save_raw(cfg.data_dir, th._conversation_key(chat_id), prompt, plan_text, kind="approval")
    await th.send_formatted_reply(message, "**Approval plan:**\n\n" + plan_text)
    await message.chat.send_message(_msg.approval_plan_question(), reply_markup=keyboard)
