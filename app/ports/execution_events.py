"""Execution event sink port — shared protocol for publishing execution lifecycle events."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.providers.base import ToolExecutionRecord


@runtime_checkable
class ExecutionEventSink(Protocol):
    """Port for publishing execution events to registries."""

    async def on_user_message(self, content: str, *, actor: str = "") -> None: ...
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
    ) -> None: ...
    async def on_provider_response(self, *, prompt_tokens: int = 0, completion_tokens: int = 0, cost_usd: float = 0.0, provider: str = "") -> None: ...
    async def on_tool_execution(self, record: ToolExecutionRecord, *, index: int = 0) -> None: ...
    async def on_approval_requested(
        self,
        content: str,
        *,
        request_kind: str,
        actor_key: str,
        trust_tier: str,
        expires_at: str = "",
        request_id: str = "",
    ) -> None: ...
    async def on_bot_reply(self, content: str) -> None: ...
    async def on_error(self, content: str, *, error_type: str = "execution", message: str = "") -> None: ...
    async def on_delegation_proposed(self, tasks: list[dict[str, str]]) -> None: ...
    async def on_delegation_submitted(self, tasks: list[dict[str, str]]) -> None: ...
    async def on_delegation_completed(self, tasks: list[dict[str, str]]) -> None: ...
