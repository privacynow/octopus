"""Workflow-side execution channel context resolution."""

from __future__ import annotations

from typing import Awaitable, Callable

from app.workflows.execution.contracts import (
    ExecutionChannelMetadata,
    TransportIdentity,
)


def _transport_fields(metadata: ExecutionChannelMetadata) -> dict:
    """Extract transport identity fields from metadata."""
    return dict(
        conversation_key=metadata.conversation_key,
        origin_channel=metadata.origin_channel,
        external_conversation_ref=metadata.external_conversation_ref,
        target_agent_id=metadata.target_agent_id,
        actor=metadata.actor,
    )


def build_transport_identity_from_metadata(
    metadata: ExecutionChannelMetadata,
    *,
    build_conversation_ref: Callable[[int], str],
    conversation_callback_factory: Callable[[str, str], Callable[[str, bool], Awaitable[None]]],
    routed_task_callback_factory: Callable[[str, str], Callable[[str, bool], Awaitable[None]]],
) -> TransportIdentity:
    conversation_ref = metadata.message_conversation_ref
    if not conversation_ref and isinstance(metadata.chat_id, int):
        conversation_ref = build_conversation_ref(metadata.chat_id)
    transport = _transport_fields(metadata)
    if metadata.routed_task_id and metadata.authority_ref:
        return TransportIdentity(
            conversation_ref=conversation_ref,
            routed_task_id=metadata.routed_task_id,
            authority_ref=metadata.authority_ref,
            timeline_callback=routed_task_callback_factory(
                metadata.routed_task_id,
                metadata.authority_ref,
            ),
            **transport,
        )
    descriptor = metadata.descriptor
    if (
        conversation_ref
        and descriptor is not None
        and descriptor.supports_conversation_binding
        and descriptor.supports_timeline
    ):
        return TransportIdentity(
            conversation_ref=conversation_ref,
            routed_task_id=metadata.routed_task_id,
            authority_ref=metadata.authority_ref,
            timeline_callback=conversation_callback_factory(
                conversation_ref,
                metadata.routed_task_id,
            ),
            **transport,
        )
    return TransportIdentity(
        conversation_ref=conversation_ref,
        routed_task_id=metadata.routed_task_id,
        authority_ref=metadata.authority_ref,
        timeline_callback=None,
        **transport,
    )
