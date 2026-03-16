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

    Implemented by surface adapters: TelegramConversationIO, RegistryConversationIO,
    and the simulator fake. Domain code uses this interface and must not depend on
    PTB, registry HTTP, or any surface-specific API. Orchestration code imports only
    this module — never a concrete adapter.
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

    async def bind(self, *, title: str, config: Any) -> None:
        """Bind the current conversation to the registry control plane if supported."""
        del title, config
        return None

    async def on_message_received(self, text: str) -> None:
        """Handle surface-specific side effects when a message is admitted."""
        del text
        return None

    async def on_outcome(self, outcome: Any) -> None:
        """Handle surface-specific side effects for a completed execution outcome."""
        del outcome
        return None

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        """Render a recovery notice on the active surface.

        Surfaces that can present interactive UI to the user (e.g. Telegram inline
        keyboard) must override this method. The default no-op is only correct for
        surfaces that rely on timeline events alone for progress visibility (e.g.
        registry surfaces that publish a recovery_notice timeline event instead).
        A surface that silently inherits this no-op will not inform the user that
        their interrupted work needs replay — it is a silent failure contract.
        """
        del preview, prompt, run_again_label, skip_label, update_id
        return None
