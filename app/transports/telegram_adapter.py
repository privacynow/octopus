"""Telegram transport adapter. Wraps PTB Bot and Message behind the conversation port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.transports.ports import (
    ConversationIO,
    EditableMessageHandle,
    TransportCapabilities,
)


class TelegramEditableMessageHandle(EditableMessageHandle):
    """Wraps a PTB Message (or send_message result) for edits."""

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


class TelegramConversationIO(ConversationIO):
    """Conversation port implemented via PTB Bot API. Used for worker-owned output."""

    def __init__(self, bot: Any, chat_id: int) -> None:
        self._bot = bot
        self.chat_id = chat_id
        self.chat = _ChatShim(self)
        self.text = None
        self.replies: list[str] = []

    @property
    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities()

    async def send_text(self, text: str, **kwargs: Any) -> EditableMessageHandle:
        sent = await self._bot.send_message(self.chat_id, text, **kwargs)
        self.replies.append(text)
        return TelegramEditableMessageHandle(sent)

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        await self._bot.send_photo(self.chat_id, photo, **kwargs)

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        await self._bot.send_document(self.chat_id, document, **kwargs)

    async def send_action(self, action: str) -> None:
        try:
            await self._bot.send_chat_action(self.chat_id, action)
        except Exception:
            pass

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        pass  # Worker path has no callback query to answer

    # Compatibility with existing execute_request/request_approval (message.reply_text, etc.)
    async def reply_text(self, text: str, **kwargs: Any) -> EditableMessageHandle:
        return await self.send_text(text, **kwargs)

    async def reply_document(self, document: Any, **kwargs: Any) -> None:
        await self.send_document(document, **kwargs)

    async def reply_photo(self, photo: Any, **kwargs: Any) -> None:
        await self.send_photo(photo, **kwargs)

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._bot.send_message(self.chat_id, text, **kwargs)

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        pass  # No single message to edit in worker path

    async def delete(self) -> None:
        pass


class _ChatShim:
    """Minimal chat shim for keep_typing(message.chat)."""

    def __init__(self, conversation: TelegramConversationIO) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_message(text, **kwargs)
