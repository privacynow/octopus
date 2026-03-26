"""Telegram channel egress implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telegram.constants import ParseMode

from app import user_messages as _msg
from app.channels.telegram import presenters as telegram_presenters
from app.config import BotConfig
from octopus_sdk.transport import (
    EditableHandle,
    TransportCapabilities,
    TransportEgress,
)
from app.runtime.services import BotServices


log = logging.getLogger(__name__)


class TelegramEditableHandle(EditableHandle):
    """Wrap a PTB message for later edits."""

    def __init__(self, message: Any) -> None:
        self._message = message

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        if self._message is None:
            return
        await self._message.edit_text(text, **kwargs)

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        if self._message is None:
            return
        await self._message.edit_message_reply_markup(reply_markup=reply_markup, **kwargs)


class TelegramChannelEgress(TransportEgress):
    """PTB-backed channel egress for Telegram conversations."""

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        *,
        config: BotConfig | None = None,
        conversation_ref: str = "",
        services: BotServices,
        mirror_input_event: bool = True,
        target_message_id: int | None = None,
    ) -> None:
        self._bot = bot
        self.chat_id = chat_id
        self._config = config
        self.conversation_ref = conversation_ref
        self._services = services
        self._mirror_input_event = mirror_input_event
        self._target_message_id = target_message_id
        self.chat = _ChatShim(self)
        self.text = None
        self.replies: list[str] = []

    @property
    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities(channel_name="telegram")

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        sent = await self._bot.send_message(self.chat_id, text, **kwargs)
        self.replies.append(text)
        return TelegramEditableHandle(sent)

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        await self._bot.send_photo(self.chat_id, photo, **kwargs)

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        await self._bot.send_document(self.chat_id, document, **kwargs)

    async def send_action(self, action: str) -> None:
        try:
            await self._bot.send_chat_action(self.chat_id, action)
        except Exception:
            log.debug(
                "send_chat_action failed for chat %s",
                self.chat_id,
                exc_info=True,
            )

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        del text, show_alert
        return None

    async def bind(self, *, title: str, config: Any) -> None:
        del config, title

    async def on_message_received(self, text: str) -> None:
        del text

    async def on_outcome(self, outcome: Any) -> None:
        del outcome

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        keyboard = telegram_presenters.recovery_notice_markup(
            update_id,
            run_again_label,
            skip_label,
        )
        await self._bot.send_message(
            self.chat_id,
            f"<i>{_msg.recovery_notice_intro()}</i>\n\n{preview}\n\n{prompt}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    async def show_foreign_setup(self, foreign_setup) -> None:
        from app.channels.telegram.execution import show_foreign_setup

        await show_foreign_setup(self, foreign_setup)

    async def show_setup_prompt(self, missing_skill: str, first_requirement: dict[str, object]) -> None:
        from app.channels.telegram.execution import show_setup_prompt

        await show_setup_prompt(self, missing_skill, first_requirement)

    async def send_retry_prompt(self, denials: tuple[dict[str, Any], ...], callback_token: str) -> None:
        from app.channels.telegram.execution import send_retry_prompt

        await send_retry_prompt(self, denials, callback_token)

    async def send_approval_prompt(self, callback_token: str) -> None:
        from app.channels.telegram.execution import send_approval_prompt

        await send_approval_prompt(self, callback_token)

    async def send_formatted_reply(self, text: str) -> None:
        from app.channels.telegram.execution import send_formatted_reply

        await send_formatted_reply(self, text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: Any = None,
    ) -> None:
        from app.channels.telegram.execution import send_path_to_chat
        from app.channels.telegram import presenters as telegram_presenters
        from app.storage import chat_upload_dir, resolve_allowed_path

        cfg = self._config
        if cfg is None:
            return
        if resolved_ctx is not None:
            roots: list[Path] = [Path(resolved_ctx.working_dir)]
            roots.extend(Path(d) for d in resolved_ctx.base_extra_dirs)
        else:
            roots = [cfg.working_dir]
            roots.extend(cfg.extra_dirs)
        roots.append(chat_upload_dir(cfg.data_dir, conversation_key_value))
        allowed_roots = [root.resolve() for root in roots]

        for dtype, raw_path in directives:
            allowed_path = resolve_allowed_path(raw_path, allowed_roots)
            if not allowed_path:
                rendered = telegram_presenters.cannot_send_path_message(raw_path)
                await self.reply_text(rendered.text, **rendered.kwargs())
                continue
            await send_path_to_chat(self, allowed_path, force_image=(dtype == "IMAGE"))

    async def send_compact_reply(self, text: str, conversation_key_value: str, slot: int) -> None:
        from app.channels.telegram.execution import send_compact_reply

        await send_compact_reply(self, text, conversation_key_value, slot)

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session,
        *,
        conversation_ref: str,
        result,
    ):
        from app.channels.telegram.delegation_channel import propose_delegation_plan
        from types import SimpleNamespace

        if self._config is None:
            raise RuntimeError("Telegram delegation requires config")
        runtime = SimpleNamespace(
            config=self._config,
            provider=SimpleNamespace(
                name=self._config.provider_name,
                new_provider_state=lambda _conversation_key: {},
            ),
            services=self._services,
        )
        return await propose_delegation_plan(
            runtime,
            conversation_key_value,
            self,
            session,
            conversation_ref=conversation_ref,
            result=result,
        )

    async def reply_text(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)

    async def reply_document(self, document: Any, **kwargs: Any) -> None:
        await self.send_document(document, **kwargs)

    async def reply_photo(self, photo: Any, **kwargs: Any) -> None:
        await self.send_photo(photo, **kwargs)

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self.send_text(text, **kwargs)

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        if self._target_message_id is None:
            return
        await self._bot.edit_message_text(
            chat_id=self.chat_id,
            message_id=self._target_message_id,
            text=text,
            **kwargs,
        )

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        if self._target_message_id is None:
            return
        await self._bot.edit_message_reply_markup(
            chat_id=self.chat_id,
            message_id=self._target_message_id,
            reply_markup=reply_markup,
            **kwargs,
        )

    async def delete(self) -> None:
        return None


class _ChatShim:
    """Minimal chat shim for keep_typing(message.chat)."""

    def __init__(self, conversation: TelegramChannelEgress) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_message(text, **kwargs)
