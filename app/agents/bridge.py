"""Bridge registry deliveries onto the existing worker path."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import work_queue
from app.agents.registry_capabilities import registry_authority_ref
from app.channels.registry.refs import (
    binding_external_id_for_ref,
    qualify_registry_conversation_ref,
    registry_task_ref,
)
from app.config import BotConfig
from octopus_sdk.identity import conversation_key_for_ref
from octopus_sdk.inbound_types import (
    InboundAction,
    InboundEnvelope,
    InboundMessage,
    InboundUser,
    serialize_inbound,
)


def qualify_registry_parent_ref(registry_id: str, conversation_ref: str) -> str:
    if not registry_id:
        raise ValueError("Registry parent ref qualification requires an explicit registry_id")
    return qualify_registry_conversation_ref(registry_id, conversation_ref)


def build_registry_message_delivery(
    *,
    conversation_ref: str,
    text: str,
    actor_ref: str,
    delivery_id: str,
    external_conversation_ref: str = "",
    routed_task_id: str = "",
    registry_id: str,
    skip_approval: bool = False,
    conversation_key_override: str = "",
) -> tuple[str, str, str, str]:
    if not registry_id:
        raise ValueError("Registry message delivery requires an explicit registry_id")
    conversation_key = conversation_key_override or conversation_key_for_ref(conversation_ref)
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id=actor_key, username="registry"),
            conversation_key=conversation_key,
            text=text,
            attachments=(),
            source="registry",
            transport="registry",
            conversation_ref=conversation_ref,
            external_conversation_ref=external_conversation_ref,
            routed_task_id=routed_task_id,
            authority_ref=registry_authority_ref(registry_id),
            skip_approval=skip_approval,
        )
    )
    return conversation_key, actor_key, event_id, payload


def build_registry_action_envelope(
    *,
    conversation_ref: str,
    action: str,
    action_payload: dict[str, Any],
    actor_ref: str,
    delivery_id: str,
    registry_id: str,
    external_conversation_ref: str = "",
) -> InboundEnvelope:
    if not registry_id:
        raise ValueError("Registry action delivery requires an explicit registry_id")
    conversation_key = conversation_key_for_ref(conversation_ref)
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    event = InboundAction(
        user=InboundUser(id=actor_key, username="registry"),
        conversation_key=conversation_key,
        action=action,
        params=dict(action_payload),
        source="registry",
        transport="registry",
        conversation_ref=conversation_ref,
        external_conversation_ref=external_conversation_ref,
        authority_ref=registry_authority_ref(registry_id),
    )
    return InboundEnvelope(
        transport="registry",
        event_id=event_id,
        conversation_key=conversation_key,
        actor_key=actor_key,
        received_at=datetime.now(timezone.utc),
        event=event,
        conversation_ref=conversation_ref,
    )


async def admit_registry_delivery(
    config: BotConfig,
    delivery: dict[str, Any],
    *,
    dispatcher: Any | None = None,
) -> str:
    """Convert a registry delivery into a normal local work item or control action."""
    kind = str(delivery.get("kind", ""))
    payload = delivery.get("payload", {})
    delivery_id = delivery.get("delivery_id", "")
    registry_id = str(delivery.get("registry_id", "") or "")
    data_dir = config.data_dir

    if kind == "channel_input":
        if not registry_id:
            return "rejected"
        conversation_ref = qualify_registry_conversation_ref(registry_id, str(payload["conversation_id"]))
        # Use stable_event_id from the delivery payload for cross-registry dedup
        stable_event_id = str(payload.get("stable_event_id", "") or "")
        effective_delivery_id = stable_event_id if stable_event_id else delivery_id
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=payload.get("text", ""),
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=effective_delivery_id,
            external_conversation_ref=str(payload.get("external_conversation_ref", "") or ""),
            registry_id=registry_id,
        )
        status, _ = work_queue.record_and_admit_message(
            data_dir,
            event_id,
            conversation_key,
            actor_key,
            "message",
            serialized,
        )
        if status in {"admitted", "queued", "duplicate"}:
            if dispatcher is None:
                raise RuntimeError("Registry delivery admission requires a channel dispatcher")
            channel_egress = dispatcher.create_egress(
                conversation_ref,
                config=config,
                conversation_key=conversation_key,
                source="registry",
            )
            await channel_egress.sync_binding(
                {
                    "conversation_ref": conversation_ref,
                    "title": payload.get("title", "Registry conversation"),
                    "origin_channel": "registry",
                    "external_id": str(payload.get("external_conversation_ref", "") or binding_external_id_for_ref(conversation_ref)),
                }
            )
        return "accepted"

    if kind == "routed_task":
        if not registry_id:
            return "rejected"
        request = payload
        context_lines = []
        if request.get("context"):
            context_lines.append(f"Context: {request['context']}")
        if request.get("constraints"):
            context_lines.append(f"Constraints: {request['constraints']}")
        if request.get("requested_capabilities"):
            context_lines.append(
                "Requested capabilities: " + ", ".join(request.get("requested_capabilities", []))
            )
        text = request.get("instructions", "").strip()
        if request.get("title"):
            text = f"{request['title']}\n\n{text}".strip()
        if context_lines:
            text = text + "\n\n" + "\n".join(context_lines)
        from octopus_sdk.identity import delegation_session_key
        conversation_ref = registry_task_ref(registry_id, request["routed_task_id"])
        # Use delegation_session_key so multiple tasks from the same parent share one provider session
        origin_agent_id = request.get("origin_agent_id", "")
        parent_conversation_id = request.get("parent_conversation_id", "")
        if origin_agent_id and parent_conversation_id:
            shared_key = delegation_session_key(origin_agent_id, parent_conversation_id)
        else:
            shared_key = ""
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            conversation_key_override=shared_key,
            text=text,
            actor_ref=f"agent:{request.get('origin_agent_id', '')}",
            delivery_id=delivery_id,
            routed_task_id=request["routed_task_id"],
            registry_id=registry_id,
        )
        status, _ = work_queue.record_and_admit_message(
            data_dir,
            event_id,
            conversation_key,
            actor_key,
            "message",
            serialized,
        )
        return "accepted"

    return "rejected"
