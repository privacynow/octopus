"""Shared runtime admission helpers for normalized inbound envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.access import is_allowed_user_with_override, trust_tier
from app import work_queue
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.inbound_types import InboundEnvelope, serialize_inbound


def trust_tier_for_ref(
    conversation_ref: str,
    user: Any,
    *,
    config,
    dispatcher: ChannelDispatcher | None,
) -> str:
    """Resolve trust at the inbound admission boundary."""
    if dispatcher is not None:
        descriptor = dispatcher.descriptor_for_ref(conversation_ref)
        if descriptor is not None and descriptor.trust_tier == "trusted":
            return descriptor.trust_tier
    return trust_tier(config, user)


@dataclass(frozen=True)
class WorkerMessageAdmission:
    status: str
    allowed: bool
    trust_tier: str


def admit_worker_message(
    *,
    data_dir: Path,
    item_id: str,
    conversation_ref: str,
    user: Any,
    config,
    dispatcher: ChannelDispatcher | None,
) -> WorkerMessageAdmission:
    resolved_trust = trust_tier_for_ref(
        conversation_ref,
        user,
        config=config,
        dispatcher=dispatcher,
    )
    channel_type = dispatcher.channel_type_for_ref(conversation_ref) if dispatcher is not None else None
    if channel_type != "telegram":
        return WorkerMessageAdmission(
            status="allowed",
            allowed=True,
            trust_tier=resolved_trust,
        )

    override = work_queue.get_user_access(data_dir, getattr(user, "id", ""))
    if not is_allowed_user_with_override(config, user, override):
        work_queue.fail_work_item(data_dir, item_id, error="not_allowed")
        return WorkerMessageAdmission(
            status="not_allowed",
            allowed=False,
            trust_tier=resolved_trust,
        )
    return WorkerMessageAdmission(
        status="allowed",
        allowed=True,
        trust_tier=resolved_trust,
    )


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
