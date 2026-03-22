"""Telegram channel egress implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telegram.constants import ParseMode

from app import user_messages as _msg
from app.channels.telegram import presenters as telegram_presenters
from app.config import BotConfig
from app.ports.egress import (
    ChannelCapabilities,
    ChannelEgress,
    EditableHandle,
)
from app.runtime.services import BotServices, build_noop_bot_services


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


class TelegramChannelEgress(ChannelEgress):
    """PTB-backed channel egress for Telegram conversations."""

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        *,
        config: BotConfig | None = None,
        conversation_ref: str = "",
        services: BotServices | None = None,
        mirror_input_event: bool = True,
        target_message_id: int | None = None,
    ) -> None:
        self._bot = bot
        self.chat_id = chat_id
        self._config = config
        self.conversation_ref = conversation_ref
        self._services = services or build_noop_bot_services()
        self._mirror_input_event = mirror_input_event
        self._target_message_id = target_message_id
        self.chat = _ChatShim(self)
        self.text = None
        self.replies: list[str] = []

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(channel_name="telegram")

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
