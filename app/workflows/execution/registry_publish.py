"""Registry event publishing helper for the execution flow."""

from __future__ import annotations

import logging
from uuid import uuid4

from app.config import BotConfig, should_publish_event
from app.ports.conversation_projection import ConversationProjectionPort

log = logging.getLogger(__name__)


async def _publish_to_registry(
    projection: ConversationProjectionPort,
    config: BotConfig,
    kind: str,
    *,
    origin_channel: str,
    external_conversation_ref: str,
    target_agent_id: str,
    title: str,
    actor: str = "",
    content: str = "",
    metadata: dict | None = None,
) -> None:
    """Publish an event to the registry if the publish level includes this kind.

    Never blocks or crashes the calling execution flow -- all failures are
    logged as warnings and swallowed.
    """
    if not should_publish_event(config, kind):
        return

    # Generate event_id ONCE at callsite (stable across any internal retries)
    event_id = uuid4().hex

    try:
        conversation_id = await projection.create_conversation(
            target_agent_id=target_agent_id,
            origin_channel=origin_channel,
            external_conversation_ref=external_conversation_ref,
            title=title,
        )
    except Exception:
        log.warning("registry publish: create_conversation failed for %s", kind, exc_info=True)
        return

    try:
        from registry_sdk.events import ConversationEvent

        event = ConversationEvent(
            event_id=event_id,
            kind=kind,
            actor=actor,
            content=content,
            metadata=metadata or {},
        )
        await projection.publish_events(
            conversation_id=conversation_id,
            events=[event],
        )
    except Exception:
        log.warning("registry publish: publish_events failed for %s", kind, exc_info=True)
