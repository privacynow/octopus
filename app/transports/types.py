"""Transport-layer types. Reuses inbound event types from app.transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.transport import InboundCallback, InboundCommand, InboundMessage


@dataclass(frozen=True)
class InboundEnvelope:
    """Normalized inbound delivery: one update with conversation and actor identity."""

    transport: str
    update_id: int
    conversation_id: int | str
    actor_id: int
    received_at: datetime
    event: InboundMessage | InboundCommand | InboundCallback
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
        return "unknown"
