"""Transport-layer types. Reuses inbound event types from app.channels.telegram.normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.channels.telegram.normalization import InboundAction, InboundCallback, InboundCommand, InboundMessage


@dataclass(frozen=True)
class InboundEnvelope:
    """Normalized inbound delivery: one update with conversation and actor identity."""

    transport: str
    event_id: str
    conversation_key: str
    actor_key: str
    received_at: datetime
    event: InboundMessage | InboundCommand | InboundCallback | InboundAction
    conversation_ref: str = ""
    surface_binding_id: str = ""

    @property
    def kind(self) -> str:
        if isinstance(self.event, InboundMessage):
            return "message"
        if isinstance(self.event, InboundCommand):
            return "command"
        if isinstance(self.event, InboundCallback):
            return "callback"
        if isinstance(self.event, InboundAction):
            return "action"
        return "unknown"
