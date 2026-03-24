"""Channel contracts for ref ownership, ingress, and metadata."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from octopus_sdk.egress import ChannelEgress


@dataclass(frozen=True)
class ChannelDescriptor:
    channel_type: str
    display_name: str
    supports_multiple: bool
    requires_polling: bool
    trust_tier: str = "untrusted"
    contributes_channel_capability: bool = True
    accepts_channel_input: bool = True
    supports_conversation_binding: bool = True
    supports_timeline: bool = True


class Channel(ABC):
    """Owns a ref prefix and builds egress for it."""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        ...

    @property
    @abstractmethod
    def descriptor(self) -> ChannelDescriptor:
        ...

    @abstractmethod
    def ref_prefix(self) -> str:
        ...

    @abstractmethod
    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
        ...

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        try:
            self.build_egress(conversation_ref=conversation_ref, config=config, **kw)
        except RuntimeError:
            return False
        return True


class ChannelBootstrap(Channel):
    """A channel that also owns an ingress runner."""

    @abstractmethod
    def build_ingress(
        self,
        *,
        config: Any,
        delivery_handler: Callable[..., Any],
    ) -> "ChannelIngress":
        ...


class ChannelIngress(ABC):
    """Independent ingress runner built by a channel bootstrap."""

    @property
    @abstractmethod
    def channel_id(self) -> str:
        ...

    @property
    @abstractmethod
    def descriptor(self) -> ChannelDescriptor:
        ...

    @abstractmethod
    async def start(self, *, stop_event: asyncio.Event) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        ...
