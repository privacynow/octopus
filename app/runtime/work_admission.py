"""Shared runtime admission helpers for normalized inbound envelopes."""

from __future__ import annotations

from pathlib import Path

from app import work_queue
from app.runtime.inbound_types import InboundEnvelope, serialize_inbound


def admit_fresh_message(data_dir: Path, envelope: InboundEnvelope) -> tuple[str, str | None]:
    """Admit a fresh message from the transport boundary. Returns (status, item_id).

    status: 'duplicate' | 'admitted' | 'queued'. item_id set when admitted or queued.
    This is the authoritative request seam: all fresh plain-message admission
    goes through the project-owned envelope type.
    """
    payload = serialize_inbound(envelope.event)
    return work_queue.record_and_admit_message(
        data_dir,
        envelope.event_id,
        envelope.conversation_key,
        envelope.actor_key,
        envelope.kind,
        payload=payload,
    )


def enqueue_inbound_envelope(
    data_dir: Path,
    envelope: InboundEnvelope,
    *,
    worker_id: str | None = None,
) -> tuple[bool, str | None]:
    """Record and enqueue a normalized non-message interaction for worker execution."""

    payload = serialize_inbound(envelope.event)
    return work_queue.record_and_enqueue(
        data_dir,
        envelope.event_id,
        envelope.conversation_key,
        envelope.actor_key,
        envelope.kind,
        payload=payload,
        worker_id=worker_id,
    )


def record_inbound_envelope(data_dir: Path, envelope: InboundEnvelope) -> bool:
    """Record a normalized interaction without enqueueing it for worker execution."""

    payload = serialize_inbound(envelope.event)
    return work_queue.record_update(
        data_dir,
        envelope.event_id,
        envelope.conversation_key,
        envelope.actor_key,
        envelope.kind,
        payload=payload,
    )
