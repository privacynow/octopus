"""Project-owned transport abstraction. Inbound envelopes and outbound conversation port."""

from app.transports.ports import (
    ConversationIO,
    EditableMessageHandle,
    TransportCapabilities,
)
from app.transports.types import InboundEnvelope

__all__ = [
    "ConversationIO",
    "EditableMessageHandle",
    "InboundEnvelope",
    "TransportCapabilities",
]
