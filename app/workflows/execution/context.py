"""Workflow-side execution channel context resolution."""

from __future__ import annotations

from typing import Awaitable, Callable

from app.workflows.execution.contracts import (
    ExecutionChannelContext,
    ExecutionChannelMetadata,
)


def build_execution_channel_context(
    metadata: ExecutionChannelMetadata,
    *,
    build_conversation_ref: Callable[[int], str],
    timeline_callback_factory: Callable[[str, str], Callable[[str, bool], Awaitable[None]]],
) -> ExecutionChannelContext:
    conversation_ref = metadata.message_conversation_ref
    if not conversation_ref and isinstance(metadata.chat_id, int):
        conversation_ref = build_conversation_ref(metadata.chat_id)
    descriptor = metadata.descriptor
    if (
        conversation_ref
        and descriptor is not None
        and descriptor.supports_conversation_binding
        and descriptor.supports_timeline
    ):
        return ExecutionChannelContext(
            conversation_ref=conversation_ref,
            routed_task_id=metadata.routed_task_id,
            authority_ref=metadata.authority_ref,
            timeline_callback=timeline_callback_factory(
                conversation_ref,
                metadata.routed_task_id,
            ),
        )
    return ExecutionChannelContext(
        conversation_ref=conversation_ref,
        routed_task_id=metadata.routed_task_id,
        authority_ref=metadata.authority_ref,
        timeline_callback=None,
    )
