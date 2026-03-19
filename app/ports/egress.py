"""Outbound egress contracts for channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChannelCapabilities:
    """What a channel can do on the outbound side."""

    can_edit_message: bool = True
    can_answer_action: bool = True
    can_send_photo: bool = True
    can_send_document: bool = True
    can_render_timeline: bool = False
    can_present_actions: bool = True
    can_share_conversation: bool = False
    channel_name: str = "telegram"


class EditableHandle(ABC):
    """Handle to an outbound item that can be edited in-place."""

    @abstractmethod
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        ...


class ConversationEgress(ABC):
    """Core outbound conversation contract shared by all channels."""

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilities:
        ...

    @abstractmethod
    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        ...

    @abstractmethod
    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def send_action(self, action: str) -> None:
        ...

    @abstractmethod
    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        ...


class ChannelEgress(ConversationEgress):
    """Extended outbound contract for channels that support richer interaction."""

    async def publish_timeline(self, event: Any) -> None:
        del event
        return None

    async def sync_binding(self, binding: Any) -> None:
        del binding
        return None

    async def bind(self, *, title: str, config: Any) -> None:
        del title, config
        return None

    async def on_message_received(self, text: str) -> None:
        del text
        return None

    async def on_outcome(self, outcome: Any) -> None:
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
        del preview, prompt, run_again_label, skip_label, update_id
        return None
