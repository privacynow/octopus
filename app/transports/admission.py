"""Admission seam over the transport contract. Production ingress uses InboundEnvelope here."""

from __future__ import annotations

from pathlib import Path

from app import work_queue
from app.transport import serialize_inbound
from app.transports.types import InboundEnvelope


def admit_fresh_message(data_dir: Path, envelope: InboundEnvelope) -> tuple[str, str | None]:
    """Admit a fresh message from the transport boundary. Returns (status, item_id).

    status: 'duplicate' | 'admitted' | 'busy'. item_id set when admitted or busy.
    This is the authoritative request seam: all fresh plain-message admission
    goes through the project-owned envelope type.
    """
    payload = serialize_inbound(envelope.event)
    return work_queue.record_and_admit_message(
        data_dir,
        envelope.update_id,
        envelope.conversation_id,
        envelope.actor_id,
        envelope.kind,
        payload=payload,
    )
