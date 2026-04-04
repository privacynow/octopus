"""Telegram execution, approval, and channel send helpers."""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram.error import BadRequest

from app import work_queue
from app.presentation import telegram as telegram_presenters
from app.workflows.conversation.telegram import TelegramConversationRuntime
from app.workflows.pending.telegram import TelegramPendingRuntime
from app.workflows.runtime_skills.telegram import TelegramRuntimeSkillsRuntime
from app.runtime.telegram_session_io import conversation_key, telegram_chat_id
from app.channels.telegram.state import TelegramRuntime
from app.agents.state import runtime_registry_agent_id
from app.credential_validation import validate_credential
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.identity import (
    telegram_conversation_ref,
    telegram_chat_id_from_ref,
    telegram_numeric_id,
)
from octopus_sdk.bot_runtime import ExecutionServices
from octopus_sdk.bot_runtime import ProviderDispatchRuntime
from octopus_sdk.inbound_types import InboundAttachment
from octopus_sdk.sessions import SessionState
from app.storage import chat_upload_dir, is_image_path, resolve_allowed_path
from app.summarize import save_raw
from octopus_sdk.execution import (
    ExecutionRuntime,
    ExecutionChannelMetadata,
    RequestExecutionOutcome,
    TransportIdentity,
    build_transport_identity_from_metadata,
    check_prompt_size_cross_chat as execution_check_prompt_size_cross_chat,
    execute_request as execution_execute_request,
    request_approval as execution_request_approval,
)

@dataclass(frozen=True)
class TelegramExecutionMessage:
    runtime: TelegramRuntime
    message: Any

    @property
    def chat(self):
        return self.message.chat

    async def send_text(self, text: str, **kwargs: Any):
        return await self.reply_text(text, **kwargs)

    async def reply_text(self, text: str, **kwargs: Any):
        return await self.message.reply_text(text, **kwargs)

    async def send_photo(self, photo: Any, **kwargs: Any) -> None:
        await self.reply_photo(photo, **kwargs)

    async def reply_photo(self, photo: Any, **kwargs: Any) -> None:
        await self.message.reply_photo(photo=photo, **kwargs)

    async def send_document(self, document: Any, **kwargs: Any) -> None:
        await self.reply_document(document, **kwargs)

    async def reply_document(self, document: Any, **kwargs: Any) -> None:
        await self.message.reply_document(document=document, **kwargs)

    async def send_action(self, action: str) -> None:
        await self.chat.send_action(action)

    def typing_target(self):
        return self.chat

    async def send_status(self, text: str, **kwargs: Any):
        return await self.send_text(text, **kwargs)

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        await self.message.edit_text(text, **kwargs)

    async def show_foreign_setup(self, foreign_setup) -> None:
        await show_foreign_setup(self, foreign_setup)

    async def show_setup_prompt(self, missing_skill: str, first_requirement: dict[str, object]) -> None:
        await show_setup_prompt(self, missing_skill, first_requirement)

    async def send_retry_prompt(self, denials: tuple[dict[str, Any], ...], callback_token: str) -> None:
        await send_retry_prompt(self, denials, callback_token)

    async def send_approval_prompt(self, callback_token: str) -> None:
        await send_approval_prompt(self, callback_token)

    async def send_formatted_reply(self, text: str) -> None:
        await send_formatted_reply(self, text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: ResolvedExecutionContext | None = None,
    ) -> None:
        await send_directed_artifacts(
            conversation_key_value,
            self,
            directives,
            resolved_ctx,
            runtime=self.runtime,
        )

    async def send_compact_reply(self, text: str, conversation_key_value: str, slot: int) -> None:
        await send_compact_reply(self, text, conversation_key_value, slot)

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: SessionState,
        *,
        conversation_ref: str,
        result,
    ) -> RequestExecutionOutcome:
        from app.workflows.delegation.telegram import propose_delegation_plan

        return await propose_delegation_plan(
            self.runtime,
            conversation_key_value,
            self,
            session,
            conversation_ref=conversation_ref,
            result=result,
        )


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
    return runtime.services.sessions.resolve_context(
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
    conversation_key_value: str,
    resolved: ResolvedExecutionContext | None = None,
) -> list[Path]:
    cfg = runtime.config
    if resolved:
        roots: list[Path] = [Path(resolved.working_dir)]
        roots.extend(Path(d) for d in resolved.base_extra_dirs)
    else:
        roots = [cfg.working_dir]
        roots.extend(cfg.extra_dirs)
    roots.append(chat_upload_dir(cfg.data_dir, conversation_key_value))
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


async def send_compact_reply(message, text: str, conversation_key_value: str, slot: int) -> None:
    chat_id = telegram_numeric_id(conversation_key_value)
    if chat_id is None:
        await send_formatted_reply(message, text)
        return
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
    conversation_key_value: str,
    message,
    directives: list[tuple[str, str]],
    resolved_ctx: ResolvedExecutionContext | None = None,
    *,
    runtime: TelegramRuntime,
) -> None:
    for dtype, raw_path in directives:
        allowed_path = resolve_allowed_path(
            raw_path,
            allowed_roots(runtime, conversation_key_value, resolved_ctx),
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


async def send_retry_prompt(message, denials: tuple[dict[str, Any], ...], callback_token: str) -> None:
    rendered = telegram_presenters.retry_prompt(denials, callback_token)
    await message.chat.send_message(rendered.text, **rendered.kwargs())


async def send_approval_prompt(message, callback_token: str) -> None:
    rendered = telegram_presenters.approval_prompt(callback_token)
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
) -> ProviderDispatchRuntime:
    return ProviderDispatchRuntime(
        config=runtime.config,
        provider=runtime.provider,
        boot_id=runtime.boot_id,
        cancellations=runtime.cancellation_registry,
        execution_inflight=runtime.execution_inflight,
    )


def execution_channel_metadata(
    runtime: TelegramRuntime,
    message,
    chat_id: int | str,
    *,
    actor_key: str = "",
) -> ExecutionChannelMetadata:
    conversation_ref = getattr(message, "conversation_ref", "")
    dispatcher = getattr(runtime, "transport_dispatcher", None)
    descriptor = None
    resolved_ref = conversation_ref
    if not resolved_ref and isinstance(chat_id, int):
        resolved_ref = telegram_conversation_ref(
            runtime.config,
            telegram_chat_id(chat_id),
        )
    if dispatcher is not None and resolved_ref:
        descriptor = dispatcher.descriptor_for_ref(resolved_ref)
    from octopus_sdk.identity import telegram_conversation_key, parse_conversation_key, telegram_actor_key

    transport_hint = str(
        getattr(message, "transport", "")
        or getattr(message, "source", "")
        or ""
    ).strip()
    resolved_chat_id = chat_id if isinstance(chat_id, int) else None
    if transport_hint == "telegram" and resolved_chat_id is None:
        resolved_chat_id = telegram_chat_id_from_ref(resolved_ref)
    if resolved_chat_id is None and isinstance(chat_id, str) and chat_id.isdigit():
        resolved_chat_id = int(chat_id)
    explicit_registry = transport_hint == "registry" or resolved_ref.startswith("registry:")

    if (transport_hint == "telegram" or resolved_chat_id is not None) and not explicit_registry:
        conv_key = (
            telegram_conversation_key(resolved_chat_id)
            if resolved_chat_id is not None
            else parse_conversation_key(chat_id)
        )
        origin = "telegram"
    else:
        conv_key = parse_conversation_key(chat_id)
        origin = transport_hint or "registry"

    # Resolve target_agent_id scoped by authority — no guessing
    authority_ref = getattr(message, "authority_ref", "")
    target_agent_id = ""
    if authority_ref:
        parts = authority_ref.split(":", 1)
        if len(parts) == 2 and parts[0] == "registry":
            target_agent_id = runtime_registry_agent_id(
                runtime.config.data_dir,
                parts[1],
            )

    actor = actor_key
    if not actor:
        _user = getattr(message, "_user", None)
        if _user is not None:
            actor = telegram_actor_key(getattr(_user, "id", 0))

    if origin == "telegram" and resolved_chat_id is not None:
        external_conversation_ref = str(resolved_chat_id)
    else:
        external_conversation_ref = str(
            getattr(message, "external_id", "")
            or getattr(message, "external_conversation_ref", "")
            or str(chat_id)
        )

    return ExecutionChannelMetadata(
        conversation_key=conv_key,
        origin_channel=origin,
        actor=actor,
        descriptor=descriptor,
        message_conversation_ref=resolved_ref,
        routed_task_id=getattr(message, "routed_task_id", ""),
        authority_ref=getattr(message, "authority_ref", ""),
        external_conversation_ref=external_conversation_ref,
        target_agent_id=target_agent_id,
    )


def build_execution_runtime(
    runtime: TelegramRuntime,
) -> ExecutionRuntime:
    return ExecutionRuntime(
        dispatch=build_dispatch_runtime(runtime),
        services=runtime.services.execution_services,
        interrupted_exc=work_queue.LeaveClaimed,
    )


def build_transport_identity(
    runtime: TelegramRuntime,
    message,
    chat_id: int | str,
    *,
    actor_key: str = "",
) -> TransportIdentity:
    from app.runtime.telegram_progress import (
        progress_timeline_callback,
        routed_task_progress_callback,
    )

    return build_transport_identity_from_metadata(
        execution_channel_metadata(runtime, message, chat_id, actor_key=actor_key),
        conversation_callback_factory=lambda conversation_ref, routed_task_id: (
            lambda html_text, force=False: progress_timeline_callback(
                runtime,
                conversation_ref,
                routed_task_id,
                html_text,
                force=force,
            )
        ),
        routed_task_callback_factory=lambda routed_task_id, authority_ref: (
            lambda html_text, force=False: routed_task_progress_callback(
                runtime,
                routed_task_id,
                authority_ref,
                html_text,
                force=force,
            )
        ),
    )


def _unexpected_chat_lock(*args, **kwargs):
    raise RuntimeError("chat_lock should not be used in direct execution wrappers")


def build_pending_runtime(
    runtime: TelegramRuntime,
    *,
    chat_lock: Callable[..., Any] = _unexpected_chat_lock,
    execution_runtime: ExecutionRuntime,
) -> TelegramPendingRuntime:
    async def _execute_request(
        chat_id: int | str,
        prompt: str,
        image_paths: list[str],
        message,
        **kwargs,
    ):
        raw_actor_key = kwargs.pop("actor_key", "")
        actor_key = "" if raw_actor_key is None else str(raw_actor_key)
        execution_message = TelegramExecutionMessage(runtime, message)
        transport = build_transport_identity(
            runtime,
            execution_message,
            chat_id,
            actor_key=actor_key,
        )
        return await execution_execute_request(
            transport,
            prompt,
            image_paths,
            execution_message,
            runtime=execution_runtime,
            **kwargs,
        )

    async def _request_approval(
        chat_id: int | str,
        prompt: str,
        image_paths: list[str],
        attachments,
        message,
        **kwargs,
    ):
        raw_actor_key = kwargs.pop("actor_key", "")
        actor_key = "" if raw_actor_key is None else str(raw_actor_key)
        execution_message = TelegramExecutionMessage(runtime, message)
        transport = build_transport_identity(
            runtime,
            execution_message,
            chat_id,
            actor_key=actor_key,
        )
        return await execution_request_approval(
            transport,
            prompt,
            image_paths,
            attachments,
            execution_message,
            runtime=execution_runtime,
            **kwargs,
        )

    return TelegramPendingRuntime(
        state=runtime,
        chat_lock=chat_lock,
        edit_or_reply_text=edit_or_reply_text,
        execute_request=_execute_request,
        request_approval=_request_approval,
        build_user_prompt=build_user_prompt,
    )
