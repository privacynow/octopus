"""Compatibility shim over SDK-owned claimed-item dispatch.

Completion ownership: the SDK `BotRuntime` owns claimed-item execution,
completion, and failure semantics. This module only forwards Telegram runtime
state into that SDK seam for legacy callers and tests.
"""

from __future__ import annotations

from octopus_sdk.bot_runtime import BotRuntime
from octopus_sdk.inbound_types import InboundAction, InboundCallback, InboundCommand, InboundMessage
from octopus_sdk.work_queue import WorkItemRecord


def _bot_runtime_from_state(runtime) -> BotRuntime:
    submitter = getattr(runtime, "submitter", None)
    if isinstance(submitter, BotRuntime):
        return submitter
    raise RuntimeError("Telegram runtime is missing the SDK BotRuntime submitter")


async def worker_dispatch(
    kind: str,
    event: InboundMessage | InboundAction | InboundCommand | InboundCallback,
    item: WorkItemRecord,
    *,
    runtime,
    execution_runtime=None,
) -> None:
    del execution_runtime
    await _bot_runtime_from_state(runtime).dispatch_claimed_item(kind, event, item)


async def notify_deserialize_failure(
    item: WorkItemRecord,
    *,
    runtime,
) -> None:
    bot_runtime = _bot_runtime_from_state(runtime)
    await bot_runtime.transport.notify_deserialize_failure(item, runtime=bot_runtime)
