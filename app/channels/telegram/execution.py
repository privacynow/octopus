"""Telegram execution, approval, and channel send helpers."""

from __future__ import annotations

import asyncio
import html
from pathlib import Path
from typing import Any, Callable

from telegram.error import BadRequest

from app.agents.bridge import telegram_conversation_ref
from app.agents.delegation import build_delegation_runtime
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.conversation import TelegramConversationRuntime
from app.channels.telegram.delegation_channel import propose_delegation_plan
from app.channels.telegram.pending import (
    TelegramPendingRuntime,
    approve_pending as pending_approve_pending,
    reject_pending as pending_reject_pending,
    retry_allow_pending as pending_retry_allow_pending,
    retry_skip_pending as pending_retry_skip_pending,
)
from app.channels.telegram.progress import (
    TelegramProgress,
    heartbeat,
    keep_typing,
    progress_timeline_callback,
)
from app.channels.telegram.runtime_skills import TelegramRuntimeSkillsRuntime
from app.channels.telegram.session_io import conversation_key, telegram_chat_id
from app.channels.telegram.state import TelegramRuntime
from app.credential_validation import validate_credential
from app.execution_context import ResolvedExecutionContext
from app.runtime.dispatch import RuntimeDispatchRuntime
from app.runtime.inbound_types import InboundAttachment
from app.runtime.session_runtime import resolve_session_context
from app.session_state import SessionState
from app.storage import chat_upload_dir, is_image_path, resolve_allowed_path
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    ExecutionSurfaceContext,
    RequestExecutionOutcome,
)
from app.workflows.execution.requests import (
    check_prompt_size_cross_chat as execution_check_prompt_size_cross_chat,
    execute_request as execution_execute_request,
    request_approval as execution_request_approval,
)


def run_result_was_interrupted(returncode: int) -> bool:
    return returncode < 0


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


async def format_provider_error(raw_text: str, returncode: int) -> str:
    raw_text = raw_text.strip()
    if not raw_text:
        return f"Provider exited with code {returncode} (no output)."
    if len(raw_text) <= _ERROR_DISPLAY_LIMIT:
        return html.escape(raw_text)

    proc = None
    try:
        from app.summarize import _clean_env

        prompt = _ERROR_SUMMARY_PROMPT.format(rc=returncode, text=raw_text[:4000])
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            "--model",
            "claude-haiku-4-5-20251001",
            "--output-format",
            "text",
            "--",
            prompt,
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

    head = raw_text[:800]
    tail = raw_text[-400:]
    return html.escape(f"{head}\n\n[…truncated…]\n\n{tail}")


def resolve_project(runtime: TelegramRuntime, session: SessionState):
    project_id = session.project_id
    if not project_id:
        return None
    for proj in runtime.config.projects:
        if proj.name == project_id:
            return proj
    return None


def resolve_context(
    runtime: TelegramRuntime,
    session: SessionState,
    trust_tier: str = "trusted",
) -> ResolvedExecutionContext:
    return resolve_session_context(
        session,
        config=runtime.config,
        provider_name=runtime.provider.name,
        trust_tier=trust_tier,
    )


def build_user_prompt(text: str, attachments: list[InboundAttachment]) -> tuple[str, list[str]]:
    prompt = text.strip() or "Inspect the attached files or images and help with them."
    image_paths: list[str] = []
    if attachments:
        lines = []
        for attachment in attachments:
            kind = "image" if attachment.is_image else "file"
            lines.append(f"- {attachment.path} ({kind}, original name: {attachment.original_name})")
            if attachment.is_image:
                image_paths.append(str(attachment.path))
        prompt = f"{prompt}\n\nAttached local files:\n" + "\n".join(lines)
    return prompt, image_paths


def allowed_roots(
    runtime: TelegramRuntime,
    chat_id: int | str,
    resolved: ResolvedExecutionContext | None = None,
) -> list[Path]:
    cfg = runtime.config
    if resolved:
        roots: list[Path] = [Path(resolved.working_dir)]
        roots.extend(Path(d) for d in resolved.base_extra_dirs)
    else:
        roots = [cfg.working_dir]
        roots.extend(cfg.extra_dirs)
    roots.append(chat_upload_dir(cfg.data_dir, conversation_key(chat_id)))
    return [root.resolve() for root in roots]


async def send_formatted_reply(message, text: str) -> None:
    for rendered in telegram_presenters.formatted_reply_messages(text):
        try:
            await message.reply_text(rendered.text, **rendered.kwargs())
        except BadRequest:
            await message.reply_text(telegram_presenters.formatted_reply_fallback_text(rendered.text))


async def edit_or_reply_text(message, text: str, **kwargs) -> None:
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


async def send_compact_reply(message, text: str, chat_id: int, slot: int) -> None:
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
    with path.open("rb") as handle:
        if should_image:
            await message.reply_photo(photo=handle)
        else:
            await message.reply_document(document=handle)


async def send_directed_artifacts(
    chat_id: int,
    message,
    directives: list[tuple[str, str]],
    resolved_ctx: ResolvedExecutionContext | None = None,
    *,
    runtime: TelegramRuntime,
) -> None:
    for dtype, raw_path in directives:
        allowed_path = resolve_allowed_path(
            raw_path,
            allowed_roots(runtime, chat_id, resolved_ctx),
        )
        if not allowed_path:
            rendered = telegram_presenters.cannot_send_path_message(raw_path)
            await message.reply_text(rendered.text, **rendered.kwargs())
            continue
        await send_path_to_chat(message, allowed_path, force_image=(dtype == "IMAGE"))


async def show_foreign_setup(message, foreign_setup) -> None:
    rendered = telegram_presenters.conversation_foreign_setup_message(foreign_setup)
    await message.reply_text(rendered.text, **rendered.kwargs())


async def show_setup_prompt(message, missing_skill: str, first_requirement: dict[str, object]) -> None:
    rendered = telegram_presenters.ingress_setup_prompt_message(missing_skill, first_requirement)
    await message.reply_text(rendered.text, **rendered.kwargs())


async def send_retry_prompt(message, denials: tuple[dict[str, Any], ...]) -> None:
    rendered = telegram_presenters.retry_prompt(denials)
    await message.chat.send_message(rendered.text, **rendered.kwargs())


async def send_approval_prompt(message) -> None:
    rendered = telegram_presenters.approval_prompt()
    await message.chat.send_message(rendered.text, **rendered.kwargs())


def build_conversation_runtime(
    runtime: TelegramRuntime,
    *,
    chat_lock: Callable[..., Any],
) -> TelegramConversationRuntime:
    return TelegramConversationRuntime(
        state=runtime,
        cancellations=runtime.cancellation_registry,
        chat_lock=chat_lock,
        edit_or_reply_text=edit_or_reply_text,
    )


def build_runtime_skill_runtime(
    runtime: TelegramRuntime,
    *,
    chat_lock: Callable[..., Any],
) -> TelegramRuntimeSkillsRuntime:
    return TelegramRuntimeSkillsRuntime(
        state=runtime,
        chat_lock=chat_lock,
        validate_credential=validate_credential,
        check_prompt_size_cross_chat=lambda data_dir, skill_name: check_prompt_size_cross_chat(
            runtime,
            data_dir,
            skill_name,
        ),
    )


def build_dispatch_runtime(runtime: TelegramRuntime) -> RuntimeDispatchRuntime:
    return RuntimeDispatchRuntime(
        config=runtime.config,
        provider=runtime.provider,
        boot_id=runtime.boot_id,
        cancellations=runtime.cancellation_registry,
        progress_factory=TelegramProgress,
        keep_typing=lambda chat: keep_typing(chat, runtime=runtime),
        heartbeat=heartbeat,
        format_provider_error=format_provider_error,
        run_result_was_interrupted=run_result_was_interrupted,
    )


def execution_channel_context(
    runtime: TelegramRuntime,
    message,
    chat_id: int | str,
) -> ExecutionSurfaceContext:
    conversation_ref = ""
    routed_task_id = ""
    if getattr(message, "capabilities", None) and getattr(message.capabilities, "channel_name", "") == "registry":
        conversation_ref = getattr(message, "conversation_ref", "")
        routed_task_id = getattr(message, "routed_task_id", "")
    elif runtime.config.agent_mode == "registry" and isinstance(chat_id, int):
        conversation_ref = telegram_conversation_ref(runtime.config, telegram_chat_id(chat_id))
    channel_name = getattr(getattr(message, "capabilities", None), "channel_name", "telegram")
    if conversation_ref and channel_name != "registry":

        async def timeline_callback(html_text: str, force: bool = False) -> None:
            await progress_timeline_callback(
                runtime,
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


def build_execution_runtime(runtime: TelegramRuntime) -> ExecutionRuntime:
    return ExecutionRuntime(
        dispatch=build_dispatch_runtime(runtime),
        build_surface_context=lambda message, chat_id: execution_channel_context(runtime, message, chat_id),
        show_foreign_setup=show_foreign_setup,
        show_setup_prompt=show_setup_prompt,
        send_retry_prompt=send_retry_prompt,
        send_approval_prompt=send_approval_prompt,
        send_formatted_reply=send_formatted_reply,
        send_directed_artifacts=lambda chat_id, message, directives, resolved_ctx=None: send_directed_artifacts(
            chat_id,
            message,
            directives,
            resolved_ctx,
            runtime=runtime,
        ),
        send_compact_reply=send_compact_reply,
        propose_delegation_plan=lambda chat_id, message, session, conversation_ref, result: propose_delegation_plan(
            runtime,
            chat_id,
            message,
            session,
            conversation_ref=conversation_ref,
            result=result,
        ),
    )


def build_delegation_channel_runtime(runtime: TelegramRuntime):
    return build_delegation_runtime(
        config=runtime.config,
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
    )


def _unexpected_chat_lock(*args, **kwargs):
    raise RuntimeError("chat_lock should not be used in direct execution wrappers")


def build_pending_runtime(
    runtime: TelegramRuntime,
    *,
    chat_lock: Callable[..., Any] = _unexpected_chat_lock,
) -> TelegramPendingRuntime:
    return TelegramPendingRuntime(
        state=runtime,
        chat_lock=chat_lock,
        edit_or_reply_text=edit_or_reply_text,
        execute_request=lambda *args, **kwargs: execute_request(*args, runtime=runtime, **kwargs),
        request_approval=lambda *args, **kwargs: request_approval(*args, runtime=runtime, **kwargs),
        build_user_prompt=build_user_prompt,
    )


def check_prompt_size_cross_chat(
    runtime: TelegramRuntime,
    data_dir: Path,
    skill_name: str,
) -> list[str]:
    return execution_check_prompt_size_cross_chat(
        data_dir,
        skill_name,
        runtime=build_execution_runtime(runtime),
    )


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
    runtime: TelegramRuntime,
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
        runtime=build_execution_runtime(runtime),
    )


async def request_approval(
    chat_id: int | str,
    prompt: str,
    image_paths: list[str],
    attachments: list[InboundAttachment],
    message,
    request_user_id: int | str = "",
    trust_tier: str = "trusted",
    cancel_event: asyncio.Event | None = None,
    *,
    runtime: TelegramRuntime,
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
        runtime=build_execution_runtime(runtime),
    )


async def approve_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramRuntime,
) -> None:
    await pending_approve_pending(
        chat_id,
        message,
        cancel_event=cancel_event,
        runtime=build_pending_runtime(runtime),
    )


async def reject_pending(chat_id: int | str, message, *, runtime: TelegramRuntime) -> None:
    await pending_reject_pending(chat_id, message, runtime=build_pending_runtime(runtime))


async def retry_skip_pending(chat_id: int | str, message, *, runtime: TelegramRuntime) -> None:
    await pending_retry_skip_pending(chat_id, message, runtime=build_pending_runtime(runtime))


async def retry_allow_pending(
    chat_id: int | str,
    message,
    *,
    cancel_event: asyncio.Event | None = None,
    runtime: TelegramRuntime,
) -> None:
    await pending_retry_allow_pending(
        chat_id,
        message,
        cancel_event=cancel_event,
        runtime=build_pending_runtime(runtime),
    )
