"""Telegram execution, approval, and channel send helpers."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram.error import BadRequest

from app.agents.bridge import telegram_conversation_ref
from app.agents.delegation import build_delegation_runtime
from app.channels.telegram import presenters as telegram_presenters
from app.channels.telegram.conversation import TelegramConversationRuntime
from app.channels.telegram.pending import TelegramPendingRuntime
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
from app.summarize import format_provider_error
from app.workflows.execution.contracts import (
    ExecutionRuntime,
    ExecutionChannelMetadata,
    RequestExecutionOutcome,
)
from app.workflows.execution.context import build_execution_channel_context
from app.workflows.execution.requests import (
    check_prompt_size_cross_chat as execution_check_prompt_size_cross_chat,
    execute_request as execution_execute_request,
    request_approval as execution_request_approval,
)


@dataclass(frozen=True)
class TelegramExecutionCollaborators:
    """Bound Telegram runtime collaborators for execution runtime builders."""

    progress_factory: type
    keep_typing: Callable[[Any], Any]
    heartbeat: Callable[..., Any]
    build_timeline_callback: Callable[[str, str], Callable[[str, bool], Awaitable[None]]]
    propose_delegation_plan: Callable[
        [int | str, Any, SessionState, str, Any],
        Awaitable[RequestExecutionOutcome],
    ]


def bind_execution_collaborators(
    runtime: TelegramRuntime,
    *,
    progress_factory: type,
    keep_typing_fn: Callable[[Any], Any],
    heartbeat_fn: Callable[..., Any],
    progress_timeline_callback_fn: Callable[..., Awaitable[None]],
    propose_delegation_plan_fn: Callable[..., Awaitable[RequestExecutionOutcome]],
) -> TelegramExecutionCollaborators:
    return TelegramExecutionCollaborators(
        progress_factory=progress_factory,
        keep_typing=lambda chat: keep_typing_fn(chat, runtime=runtime),
        heartbeat=heartbeat_fn,
        build_timeline_callback=lambda conversation_ref, routed_task_id: (
            lambda html_text, force=False: progress_timeline_callback_fn(
                runtime,
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )
        ),
        propose_delegation_plan=lambda chat_id, message, session, conversation_ref, result: (
            propose_delegation_plan_fn(
                runtime,
                chat_id,
                message,
                session,
                conversation_ref=conversation_ref,
                result=result,
            )
        ),
    )


def run_result_was_interrupted(returncode: int) -> bool:
    return returncode < 0


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
    execution_runtime: ExecutionRuntime,
) -> TelegramRuntimeSkillsRuntime:
    return TelegramRuntimeSkillsRuntime(
        state=runtime,
        chat_lock=chat_lock,
        validate_credential=validate_credential,
        check_prompt_size_cross_chat=lambda data_dir, skill_name: execution_check_prompt_size_cross_chat(
            data_dir,
            skill_name,
            runtime=execution_runtime,
        ),
    )


def build_dispatch_runtime(
    runtime: TelegramRuntime,
    *,
    collaborators: TelegramExecutionCollaborators,
) -> RuntimeDispatchRuntime:
    return RuntimeDispatchRuntime(
        config=runtime.config,
        provider=runtime.provider,
        boot_id=runtime.boot_id,
        cancellations=runtime.cancellation_registry,
        progress_factory=collaborators.progress_factory,
        keep_typing=collaborators.keep_typing,
        heartbeat=collaborators.heartbeat,
        format_provider_error=lambda raw_text, returncode: format_provider_error(
            raw_text,
            returncode,
            model=getattr(runtime.config, "provider_error_summary_model", "claude-haiku-4-5-20251001"),
        ),
        run_result_was_interrupted=run_result_was_interrupted,
    )


def execution_channel_metadata(
    runtime: TelegramRuntime,
    message,
    chat_id: int | str,
) -> ExecutionChannelMetadata:
    conversation_ref = getattr(message, "conversation_ref", "")
    dispatcher = getattr(runtime, "channel_dispatcher", None)
    descriptor = None
    resolved_ref = conversation_ref
    if not resolved_ref and isinstance(chat_id, int):
        resolved_ref = telegram_conversation_ref(
            runtime.config,
            telegram_chat_id(chat_id),
        )
    if dispatcher is not None and resolved_ref:
        descriptor = dispatcher.descriptor_for_ref(resolved_ref)
    return ExecutionChannelMetadata(
        descriptor=descriptor,
        message_conversation_ref=conversation_ref,
        routed_task_id=getattr(message, "routed_task_id", ""),
        chat_id=chat_id,
    )


def build_execution_runtime(
    runtime: TelegramRuntime,
    *,
    collaborators: TelegramExecutionCollaborators,
) -> ExecutionRuntime:
    return ExecutionRuntime(
        dispatch=build_dispatch_runtime(runtime, collaborators=collaborators),
        build_channel_context=lambda message, chat_id: build_execution_channel_context(
            execution_channel_metadata(runtime, message, chat_id),
            build_conversation_ref=lambda numeric_chat_id: telegram_conversation_ref(
                runtime.config,
                telegram_chat_id(numeric_chat_id),
            ),
            timeline_callback_factory=collaborators.build_timeline_callback,
        ),
        render_provider_error=html.escape,
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
        propose_delegation_plan=collaborators.propose_delegation_plan,
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
    execution_runtime: ExecutionRuntime,
) -> TelegramPendingRuntime:
    return TelegramPendingRuntime(
        state=runtime,
        chat_lock=chat_lock,
        edit_or_reply_text=edit_or_reply_text,
        execute_request=lambda *args, **kwargs: execution_execute_request(
            *args,
            runtime=execution_runtime,
            **kwargs,
        ),
        request_approval=lambda *args, **kwargs: execution_request_approval(
            *args,
            runtime=execution_runtime,
            **kwargs,
        ),
        build_user_prompt=build_user_prompt,
    )
