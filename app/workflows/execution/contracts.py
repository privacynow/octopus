"""Local contracts for execution and preflight workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from app.ports.agent_directory import AgentDirectoryPort
from app.ports.channel import ChannelDescriptor
from app.ports.delegation import DelegationIntentParser
from app.runtime.dispatch import RuntimeDispatchRuntime


@dataclass(frozen=True)
class TransportIdentity:
    """Channel-supplied bundle for durable side effects (registry, session, logging).

    Every channel must supply this per execution. It describes how this
    conversation maps to registry projection, session storage, and UI.
    Replaces the former ExecutionChannelContext.
    """
    conversation_key: str = ""
    origin_channel: str = ""
    external_conversation_ref: str = ""
    target_agent_id: str = ""
    conversation_ref: str = ""
    routed_task_id: str = ""
    authority_ref: str = ""
    actor: str = ""
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None


# Backward compat alias — callers being migrated
ExecutionChannelContext = TransportIdentity


@dataclass(frozen=True)
class ExecutionChannelMetadata:
    descriptor: ChannelDescriptor | None = None
    message_conversation_ref: str = ""
    routed_task_id: str = ""
    authority_ref: str = ""
    chat_id: int | str = ""
    conversation_key: str = ""
    origin_channel: str = ""
    external_conversation_ref: str = ""
    target_agent_id: str = ""
    actor: str = ""


@runtime_checkable
class ExecutionEventSink(Protocol):
    """Port for publishing execution events to registries."""

    async def on_user_message(self, content: str, *, actor: str = "") -> None: ...
    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None: ...
    async def on_bot_reply(self, content: str) -> None: ...
    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None: ...
    async def on_delegation_proposed(self, tasks: list[dict[str, str]]) -> None: ...
    async def on_delegation_submitted(self, tasks: list[dict[str, str]]) -> None: ...


@dataclass(frozen=True)
class RequestExecutionOutcome:
    status: str
    reply_text: str = ""
    error_text: str = ""
    denials: tuple[dict[str, Any], ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ExecutionRuntime:
    dispatch: RuntimeDispatchRuntime
    build_transport_identity: Callable[[Any, int | str], TransportIdentity]
    build_event_sink: Callable[[TransportIdentity], ExecutionEventSink]
    render_provider_error: Callable[[str], str]
    show_foreign_setup: Callable[[Any, Any], Awaitable[None]]
    show_setup_prompt: Callable[[Any, str, dict[str, object]], Awaitable[None]]
    send_retry_prompt: Callable[[Any, tuple[dict[str, Any], ...], str], Awaitable[None]]
    send_approval_prompt: Callable[[Any, str], Awaitable[None]]
    send_formatted_reply: Callable[..., Awaitable[None]]
    send_directed_artifacts: Callable[..., Awaitable[None]]
    send_compact_reply: Callable[..., Awaitable[None]]
    propose_delegation_plan: Callable[..., Awaitable[RequestExecutionOutcome]]
    delegation_parser: DelegationIntentParser | None = field(default=None)
    agent_directory: AgentDirectoryPort | None = field(default=None)
