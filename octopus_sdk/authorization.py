"""SDK authorization contracts."""

from __future__ import annotations

from typing import Protocol

from octopus_sdk.config import BotConfigBase
from octopus_sdk.inbound_types import InboundUser
from octopus_sdk.transport_dispatcher import TransportDispatcher


class AuthorizationPort(Protocol):
    def is_allowed(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
        *,
        override: str | None = None,
    ) -> bool: ...

    def is_admin(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
    ) -> bool: ...

    def trust_tier(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
    ) -> str: ...

    def access_policy(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
        *,
        override: str | None = None,
    ) -> str: ...


class TrustTierResolverPort(Protocol):
    def __call__(
        self,
        conversation_ref: str,
        user: InboundUser | None,
        *,
        config: BotConfigBase,
        dispatcher: TransportDispatcher | None,
    ) -> str: ...
