"""Shared runtime admission helpers for normalized inbound envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.access import is_allowed_user_with_override, trust_tier
from app import work_queue
from app.runtime.transport_dispatcher import TransportDispatcher
from octopus_sdk.inbound_types import InboundEnvelope, serialize_inbound
from octopus_sdk.transport import BotRuntimeHandle, InboundSubmissionResult


def trust_tier_for_ref(
    conversation_ref: str,
    user: Any,
    *,
    config,
    dispatcher: TransportDispatcher | None,
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


class LocalInboundSubmitter(BotRuntimeHandle):
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    async def admit_message(self, envelope: InboundEnvelope) -> InboundSubmissionResult:
        status, item_id = admit_fresh_message(self._data_dir, envelope)
        return InboundSubmissionResult(status=status, item_id=item_id)

    async def enqueue(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult:
        is_new, item_id = enqueue_inbound_envelope(
            self._data_dir,
            envelope,
            worker_id=worker_id,
        )
        return InboundSubmissionResult(
            status="queued" if is_new else "duplicate",
            item_id=item_id,
        )

    async def record(self, envelope: InboundEnvelope) -> bool:
        return record_inbound_envelope(self._data_dir, envelope)


def build_local_inbound_submitter(data_dir: Path) -> BotRuntimeHandle:
    return LocalInboundSubmitter(data_dir)


def admit_worker_message(
    *,
    data_dir: Path,
    item_id: str,
    conversation_ref: str,
    user: Any,
    config,
    dispatcher: TransportDispatcher | None,
) -> WorkerMessageAdmission:
    resolved_trust = trust_tier_for_ref(
        conversation_ref,
        user,
        config=config,
        dispatcher=dispatcher,
    )
    descriptor = dispatcher.descriptor_for_ref(conversation_ref) if dispatcher is not None else None
    if descriptor is not None and descriptor.trust_tier == "trusted":
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
    payload = serialize_inbound(envelope.event, transport=envelope.transport)
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

    payload = serialize_inbound(envelope.event, transport=envelope.transport)
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

    payload = serialize_inbound(envelope.event, transport=envelope.transport)
    return work_queue.record_update(
        data_dir,
        envelope.event_id,
        envelope.conversation_key,
        envelope.actor_key,
        envelope.kind,
        payload=payload,
    )
