"""Execution event sink — thin adapter over ConversationProjectionPort.

The sink is NOT a second registry client. It composes:
  - ConversationProjectionPort (the capability)
  - TransportIdentity (who/where)
  - BotConfigBase (publish level gating)

into typed methods that execute_request and delegation handlers call.
All failures are logged as warnings and swallowed — never blocks execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from octopus_sdk.config import BotConfigBase, should_publish_event
from octopus_sdk.conversation_projection import ConversationProjectionPort
from octopus_sdk.providers import ToolExecutionRecord
from octopus_sdk.execution import TransportIdentity

log = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoOpEventSink:
    """Stateless sink that discards all events. Thread-safe, reusable."""

    async def on_user_message(self, content: str, *, actor: str = "") -> None:
        pass

    async def on_provider_request(
        self,
        content: str,
        *,
        provider: str,
        model: str,
        execution_mode: str,
        working_dir: str,
        file_policy: str,
        image_count: int,
        prompt_char_count: int,
    ) -> None:
        pass

    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None:
        pass

    async def on_tool_execution(self, record: ToolExecutionRecord, *, index: int = 0) -> None:
        del record, index

    async def on_approval_requested(
        self,
        content: str,
        *,
        request_kind: str,
        actor_key: str,
        trust_tier: str,
        expires_at: str = "",
        request_id: str = "",
        recovery_id: str = "",
    ) -> None:
        del content, request_kind, actor_key, trust_tier, expires_at, request_id, recovery_id

    async def on_bot_reply(self, content: str) -> None:
        pass

    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None:
        pass

    async def on_delegation_proposed(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
        pass

    async def on_delegation_submitted(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
        pass

    async def on_delegation_completed(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
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
        config: BotConfigBase,
    ) -> None:
        self._projection = projection
        self._transport = transport
        self._config = config
        self._conversation_id: str | None = None
        self._execution_event_prefix = uuid4().hex

    def _skip_user_message_mirror(self) -> bool:
        conversation_ref = self._transport.conversation_ref or ""
        return (
            self._transport.origin_channel == "registry"
            and ":conversation:" in conversation_ref
        )

    def _skip_bot_reply_mirror(self) -> bool:
        conversation_ref = self._transport.conversation_ref or ""
        return (
            self._transport.origin_channel == "registry"
            and ":conversation:" in conversation_ref
        )

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

    async def _publish(
        self,
        kind: str,
        *,
        event_id: str,
        actor: str = "",
        content: str = "",
        metadata: dict | None = None,
    ) -> None:
        if kind != "approval.requested" and not should_publish_event(self._config, kind):
            return
        conversation_id = await self._ensure_conversation()
        if conversation_id is None:
            return
        try:
            from octopus_sdk.events import ConversationEvent
            event = ConversationEvent(
                event_id=event_id,
                kind=kind,
                actor=actor,
                content=content,
                created_at=_utcnow_iso(),
                metadata=metadata or {},
            )
            await self._projection.publish_events(
                conversation_id=conversation_id,
                events=[event],
            )
        except Exception:
            log.warning("registry publish: publish_events failed for %s", kind, exc_info=True)

    async def on_user_message(self, content: str, *, actor: str = "") -> None:
        if self._skip_user_message_mirror():
            return
        await self._publish(
            "message.user",
            event_id=f"exec:{self._execution_event_prefix}:user",
            actor=actor,
            content=content,
        )

    async def on_provider_request(
        self,
        content: str,
        *,
        provider: str,
        model: str,
        execution_mode: str,
        working_dir: str,
        file_policy: str,
        image_count: int,
        prompt_char_count: int,
    ) -> None:
        await self._publish(
            "provider.request",
            event_id=f"exec:{self._execution_event_prefix}:request",
            content=content,
            metadata={
                "provider": provider,
                "model": model,
                "execution_mode": execution_mode,
                "working_dir": working_dir,
                "file_policy": file_policy,
                "image_count": image_count,
                "prompt_char_count": prompt_char_count,
            },
        )

    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None:
        await self._publish(
            "provider.response",
            event_id=f"exec:{self._execution_event_prefix}:response",
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd,
                "provider": provider,
            },
        )

    async def on_tool_execution(self, record: ToolExecutionRecord, *, index: int = 0) -> None:
        await self._publish(
            "tool.execution",
            event_id=f"exec:{self._execution_event_prefix}:tool:{index}",
            content=f"{record.tool_name} {record.status}",
            metadata={
                "tool_name": record.tool_name,
                "call_id": record.call_id,
                "status": record.status,
                "input_summary": record.input_summary,
                "output_summary": record.output_summary,
                "duration_ms": record.duration_ms,
                "file_changes": [
                    {
                        "path": item.path,
                        "change_type": item.change_type,
                        "summary": item.summary,
                    }
                    for item in record.file_changes
                ],
            },
        )

    async def on_approval_requested(
        self,
        content: str,
        *,
        request_kind: str,
        actor_key: str,
        trust_tier: str,
        expires_at: str = "",
        request_id: str = "",
        recovery_id: str = "",
    ) -> None:
        await self._publish(
            "approval.requested",
            event_id=request_id or f"approval:{self._execution_event_prefix}",
            content=content,
            metadata={
                "request_kind": request_kind,
                "actor_key": actor_key,
                "trust_tier": trust_tier,
                "expires_at": expires_at or None,
                "recovery_id": str(recovery_id or "").strip() or None,
            },
        )

    async def on_bot_reply(self, content: str) -> None:
        if self._skip_bot_reply_mirror():
            return
        await self._publish(
            "message.bot",
            event_id=f"exec:{self._execution_event_prefix}:bot",
            content=content,
        )

    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None:
        await self._publish(
            "error",
            event_id=f"exec:{self._execution_event_prefix}:error",
            content=content[:500],
            metadata={
                "error_type": error_type,
                "message": message[:500] if message else content[:500],
            },
        )

    async def on_delegation_proposed(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
        if not tasks:
            return
        await self._publish(
            "delegation.proposed",
            event_id=f"exec:{self._execution_event_prefix}:delegation:proposed",
            metadata={"proposal_id": proposal_id, "tasks": tasks},
        )

    async def on_delegation_submitted(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
        if not tasks:
            return
        await self._publish(
            "delegation.submitted",
            event_id=f"exec:{self._execution_event_prefix}:delegation:submitted",
            metadata={"proposal_id": proposal_id, "tasks": tasks},
        )

    async def on_delegation_completed(self, tasks: list[dict[str, str]], *, proposal_id: str) -> None:
        if not tasks:
            return
        await self._publish(
            "delegation.completed",
            event_id=f"exec:{self._execution_event_prefix}:delegation:completed",
            metadata={"proposal_id": proposal_id, "tasks": tasks},
        )


def build_event_sink_for_context(
    transport: TransportIdentity | None,
    projection: ConversationProjectionPort | None,
    config: BotConfigBase,
) -> NoOpEventSink | RegistryEventSink:
    """Build an event sink from available context.

    Used by delegation handlers, delivery processors, and any path
    outside execute_request that needs to publish execution events.
    Returns NoOpEventSink if transport or projection is unavailable.
    """
    if transport is None or projection is None:
        return _NOOP_SINK
    return RegistryEventSink(projection=projection, transport=transport, config=config)
