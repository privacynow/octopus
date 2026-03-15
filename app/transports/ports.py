"""Outbound conversation port. Implemented by Telegram adapter and simulator."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TransportCapabilities:
    """What this transport supports (edit, answer, media, etc.)."""

    can_edit_message: bool = True
    can_answer_action: bool = True
    can_send_photo: bool = True
    can_send_document: bool = True


class EditableMessageHandle(ABC):
    """Handle to a message that can be edited (e.g. status/progress)."""

    @abstractmethod
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        """Update the message text."""
        ...

    @abstractmethod
    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        """Update the message reply markup."""
        ...


class ConversationIO(ABC):
    """Outbound conversation port: send text, media, typing, edit, answer.

    Implemented by the Telegram adapter and by the simulator. Domain code
    uses this interface so it does not depend on PTB or transport-specific APIs.
    """

    @property
    @abstractmethod
    def capabilities(self) -> TransportCapabilities:
        """What this transport supports."""
        ...

    @abstractmethod
    async def send_text(self, text: str, **kwargs: Any) -> EditableMessageHandle:
        """Send a text message. Returns a handle for later edits."""
        ...

    @abstractmethod
    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        """Send a photo."""
        ...

    @abstractmethod
    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        """Send a document."""
        ...

    @abstractmethod
    async def send_action(self, action: str) -> None:
        """Send typing/status action."""
        ...

    @abstractmethod
    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        """Answer a user action (e.g. callback query). Optional for message-only flows."""
        ...
