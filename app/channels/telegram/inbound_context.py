"""Telegram inbound ref/trust helpers shared by ingress paths."""

from __future__ import annotations

from octopus_sdk.identity import resolve_event_conversation_ref
from app.runtime.work_admission import trust_tier_for_ref


def event_conversation_ref(*, config, event) -> str:
    return resolve_event_conversation_ref(config=config, event=event)


def event_trust_tier(*, config, dispatcher, event) -> str:
    return trust_tier_for_ref(
        event_conversation_ref(config=config, event=event),
        event.user,
        config=config,
        dispatcher=dispatcher,
    )
