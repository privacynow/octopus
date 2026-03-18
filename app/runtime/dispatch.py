"""Channel-agnostic provider-call dispatch plumbing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, MutableMapping

from app.config import BotConfig
from app.providers.base import Provider


@dataclass(frozen=True)
class RuntimeDispatchRuntime:
    """Explicit runtime-owned provider dispatch collaborators.

    This runtime owns only provider-call plumbing:
    - progress object creation
    - typing/heartbeat lifecycle
    - cancellation registry wiring
    - provider invocation
    """

    config: BotConfig
    provider: Provider
    boot_id: str
    cancellations: MutableMapping[int | str, asyncio.Event]
    progress_factory: Callable[..., Any]
    keep_typing: Callable[..., Awaitable[None]]
    heartbeat: Callable[..., Awaitable[None]]
    format_provider_error: Callable[[str, int], Awaitable[str]]
    run_result_was_interrupted: Callable[[int], bool]


@dataclass(frozen=True)
class ProviderDispatchOutcome:
    progress: Any
    result: Any


async def _run_provider_call(
    chat_id: int | str,
    *,
    message,
    label: str,
    cancel_event: asyncio.Event | None,
    runtime: RuntimeDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None,
    invoke: Callable[[Any, asyncio.Event], Awaitable[Any]],
) -> ProviderDispatchOutcome:
    status_msg = await message.reply_text(label)
    progress = runtime.progress_factory(
        status_msg,
        runtime.config,
        timeline_callback=timeline_callback,
    )
    content_started = asyncio.Event()
    progress.content_started = content_started
    typing_task = asyncio.create_task(runtime.keep_typing(message.chat))
    heartbeat_task = asyncio.create_task(runtime.heartbeat(progress, content_started))

    local_cancel_event = cancel_event or asyncio.Event()
    runtime.cancellations[chat_id] = local_cancel_event
    try:
        result = await invoke(progress, local_cancel_event)
    finally:
        runtime.cancellations.pop(chat_id, None)
        heartbeat_task.cancel()
        typing_task.cancel()
        await asyncio.gather(heartbeat_task, typing_task, return_exceptions=True)

    return ProviderDispatchOutcome(progress=progress, result=result)


async def run_provider_request(
    chat_id: int | str,
    *,
    prompt: str,
    image_paths: list[str],
    message,
    provider_state: dict[str, Any],
    context,
    cancel_event: asyncio.Event | None = None,
    label: str,
    runtime: RuntimeDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
) -> ProviderDispatchOutcome:
    """Run a provider execution request with runtime-managed progress plumbing."""

    return await _run_provider_call(
        chat_id,
        message=message,
        label=label,
        cancel_event=cancel_event,
        runtime=runtime,
        timeline_callback=timeline_callback,
        invoke=lambda progress, local_cancel_event: runtime.provider.run(
            provider_state,
            prompt,
            image_paths,
            progress,
            context=context,
            cancel=local_cancel_event,
        ),
    )


async def run_provider_preflight(
    chat_id: int | str,
    *,
    prompt: str,
    image_paths: list[str],
    message,
    context,
    cancel_event: asyncio.Event | None = None,
    label: str,
    runtime: RuntimeDispatchRuntime,
    timeline_callback: Callable[[str, bool], Awaitable[None]] | None = None,
) -> ProviderDispatchOutcome:
    """Run a provider preflight request with runtime-managed progress plumbing."""

    return await _run_provider_call(
        chat_id,
        message=message,
        label=label,
        cancel_event=cancel_event,
        runtime=runtime,
        timeline_callback=timeline_callback,
        invoke=lambda progress, local_cancel_event: runtime.provider.run_preflight(
            prompt,
            image_paths,
            progress,
            context=context,
            cancel=local_cancel_event,
        ),
    )
