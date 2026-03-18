"""Local contracts for execution and preflight workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.runtime.dispatch import RuntimeDispatchRuntime


@dataclass(frozen=True)
class ExecutionSurfaceContext:
    conversation_ref: str = ""
    routed_task_id: str = ""
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None


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
    build_surface_context: Callable[[Any, int | str], ExecutionSurfaceContext]
    show_foreign_setup: Callable[[Any, Any], Awaitable[None]]
    show_setup_prompt: Callable[[Any, str, dict[str, object]], Awaitable[None]]
    send_retry_prompt: Callable[[Any, tuple[dict[str, Any], ...]], Awaitable[None]]
    send_approval_prompt: Callable[[Any], Awaitable[None]]
    send_formatted_reply: Callable[..., Awaitable[None]]
    send_directed_artifacts: Callable[..., Awaitable[None]]
    send_compact_reply: Callable[..., Awaitable[None]]
    propose_delegation_plan: Callable[..., Awaitable[RequestExecutionOutcome]]
