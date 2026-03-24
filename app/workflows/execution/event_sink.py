"""Execution event sink — thin adapter over ConversationProjectionPort.

The sink is NOT a second registry client. It composes:
  - ConversationProjectionPort (the capability)
  - TransportIdentity (who/where)
  - BotConfig (publish level gating)

into typed methods that execute_request and delegation handlers call.
All failures are logged as warnings and swallowed — never blocks execution.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.config import BotConfig, should_publish_event
from app.ports.conversation_projection import ConversationProjectionPort
from app.workflows.execution.contracts import TransportIdentity

log = logging.getLogger(__name__)


class NoOpEventSink:
    """Stateless sink that discards all events. Thread-safe, reusable."""

    async def on_user_message(self, content: str, *, actor: str = "") -> None:
        pass

    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None:
        pass

    async def on_bot_reply(self, content: str) -> None:
        pass

    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None:
        pass

    async def on_delegation_proposed(self, tasks: list[dict[str, str]]) -> None:
        pass

    async def on_delegation_submitted(self, tasks: list[dict[str, str]]) -> None:
        pass

    async def on_delegation_completed(self, tasks: list[dict[str, str]]) -> None:
        pass


_NOOP_SINK = NoOpEventSink()


class RegistryEventSink:
    """Publishes execution events to a registry via ConversationProjectionPort.

    New instance per request (holds TransportIdentity). Caches conversation_id
    after first create_conversation call.
    """

    def __init__(
        self,
        projection: ConversationProjectionPort,
        transport: TransportIdentity,
        config: BotConfig,
    ) -> None:
        self._projection = projection
        self._transport = transport
        self._config = config
        self._conversation_id: str | None = None

    async def _ensure_conversation(self) -> str | None:
        if self._conversation_id is not None:
            return self._conversation_id
        try:
            self._conversation_id = await self._projection.create_conversation(
                target_agent_id=self._transport.target_agent_id,
                origin_channel=self._transport.origin_channel,
                external_conversation_ref=self._transport.external_conversation_ref,
                title=f"Chat {self._transport.external_conversation_ref}",
            )
            return self._conversation_id
        except Exception:
            log.warning("registry publish: create_conversation failed", exc_info=True)
            return None

    async def _publish(self, kind: str, *, actor: str = "", content: str = "", metadata: dict | None = None) -> None:
        if not should_publish_event(self._config, kind):
            return
        conversation_id = await self._ensure_conversation()
        if conversation_id is None:
            return
        try:
            from registry_sdk.events import ConversationEvent
            event = ConversationEvent(
                event_id=uuid4().hex,
                kind=kind,
                actor=actor,
                content=content,
                metadata=metadata or {},
            )
            await self._projection.publish_events(
                conversation_id=conversation_id,
                events=[event],
            )
        except Exception:
            log.warning("registry publish: publish_events failed for %s", kind, exc_info=True)

    async def on_user_message(self, content: str, *, actor: str = "") -> None:
        await self._publish("message.user", actor=actor, content=content)

    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None:
        await self._publish("provider.response", metadata={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "provider": provider,
        })

    async def on_bot_reply(self, content: str) -> None:
        await self._publish("message.bot", content=content)

    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None:
        await self._publish("error", content=content[:500], metadata={
            "error_type": error_type,
            "message": message[:500] if message else content[:500],
        })

    async def on_delegation_proposed(self, tasks: list[dict[str, str]]) -> None:
        await self._publish("delegation.proposed", metadata={"tasks": tasks})

    async def on_delegation_submitted(self, tasks: list[dict[str, str]]) -> None:
        await self._publish("delegation.submitted", metadata={"tasks": tasks})

    async def on_delegation_completed(self, tasks: list[dict[str, str]]) -> None:
        await self._publish("delegation.completed", metadata={"tasks": tasks})


def build_event_sink_for_context(
    transport: TransportIdentity | None,
    projection: ConversationProjectionPort | None,
    config: BotConfig,
) -> NoOpEventSink | RegistryEventSink:
    """Build an event sink from available context.

    Used by delegation handlers, delivery processors, and any path
    outside execute_request that needs to publish execution events.
    Returns NoOpEventSink if transport or projection is unavailable.
    """
    if transport is None or projection is None:
        return _NOOP_SINK
    if not should_publish_event(config, "message.user"):
        return _NOOP_SINK
    return RegistryEventSink(projection=projection, transport=transport, config=config)
