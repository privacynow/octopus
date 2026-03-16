"""Outbound conversation/surface ports.

`ConversationIO` remains the bot-facing output contract used today. The newer
multi-surface model extends the same seam with richer capability metadata so
Telegram, registry UI, and the simulator can render the same conversation truth
without creating parallel orchestration paths.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SurfaceCapabilities:
    """What a surface supports (edit, answer, media, richer timeline, etc.)."""

    can_edit_message: bool = True
    can_answer_action: bool = True
    can_send_photo: bool = True
    can_send_document: bool = True
    can_render_timeline: bool = False
    can_present_actions: bool = True
    can_share_conversation: bool = False
    surface_name: str = "telegram"


# Backward-compatible alias used across the current runtime.
TransportCapabilities = SurfaceCapabilities


class SurfaceEditableHandle(ABC):
    """Handle to a message/timeline item that can be edited."""

    @abstractmethod
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        """Update the message text."""
        ...

    @abstractmethod
    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        """Update the message reply markup."""
        ...


EditableMessageHandle = SurfaceEditableHandle


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


class InteractionSurface(ConversationIO):
    """Shared conversation surface contract.

    Existing domain code continues to call the narrower ConversationIO API.
    Registry UI and future richer clients can extend this surface with timeline
    and shared-conversation rendering without branching the execution core.
    """

    async def publish_timeline(self, event: Any) -> None:
        """Publish a richer timeline event when the surface supports it."""
        return None

    async def sync_binding(self, binding: Any) -> None:
        """Associate an external surface binding with the current conversation."""
        return None
