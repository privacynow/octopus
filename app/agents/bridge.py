"""Bridge registry deliveries and timeline mirroring onto the existing worker path."""

from __future__ import annotations

import html
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app import work_queue
from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import load_agent_runtime_state
from app.agents.types import RoutedTaskResult, TimelineEvent
from app.config import BotConfig
from app.identity import telegram_conversation_key
from app.transport import InboundAction, InboundMessage, InboundUser, serialize_inbound
from app.runtime.composition import conversation_channel_name
from app.transports.types import InboundEnvelope

log = logging.getLogger(__name__)


def conversation_key_for_ref(conversation_ref: str) -> str:
    if conversation_channel_name(conversation_ref) == "telegram":
        try:
            return telegram_conversation_key(conversation_ref.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return conversation_ref
    return conversation_ref


def agent_identity(config: BotConfig) -> str:
    state = load_agent_runtime_state(config.data_dir)
    return state.agent_id or config.agent_slug or config.instance


def telegram_conversation_ref(config: BotConfig, chat_id: int) -> str:
    return f"telegram:{agent_identity(config)}:{chat_id}"


def registry_client(config: BotConfig) -> AgentRegistryClient | None:
    if config.agent_mode != "registry" or not config.agent_registry_url:
        return None
    state = load_agent_runtime_state(config.data_dir)
    if not state.agent_token:
        return None
    return AgentRegistryClient(config.agent_registry_url, agent_token=state.agent_token)


async def bind_conversation(
    config: BotConfig,
    *,
    conversation_ref: str,
    title: str,
    origin_surface: str,
    external_id: str,
) -> None:
    client = registry_client(config)
    if client is None:
        return
    try:
        await client.sync_binding(
            conversation_id=conversation_ref,
            title=title,
            origin_surface=origin_surface,
            external_id=external_id,
        )
    except RegistryClientError as exc:
        log.debug("Registry conversation bind failed for %s: %s", conversation_ref, exc)


async def publish_timeline_event(
    config: BotConfig,
    *,
    conversation_ref: str,
    kind: str,
    title: str,
    body: str = "",
    status: str = "",
    progress: int | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
) -> None:
    client = registry_client(config)
    if client is None:
        return
    event = TimelineEvent(
        event_id=event_id or uuid.uuid4().hex,
        conversation_id=conversation_ref,
        kind=kind,
        title=title,
        body=body,
        status=status,
        progress=progress,
        metadata=metadata or {},
    )
    try:
        await client.publish_timeline([event])
    except RegistryClientError as exc:
        log.debug("Registry timeline publish failed for %s: %s", conversation_ref, exc)


def build_registry_message_delivery(
    *,
    conversation_ref: str,
    text: str,
    actor_ref: str,
    delivery_id: str,
    routed_task_id: str = "",
    skip_approval: bool = False,
) -> tuple[str, str, str, str]:
    conversation_key = conversation_key_for_ref(conversation_ref)
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id=actor_key, username="registry"),
            conversation_key=conversation_key,
            text=text,
            attachments=(),
            source="registry",
            conversation_ref=conversation_ref,
            routed_task_id=routed_task_id,
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
) -> InboundEnvelope:
    conversation_key = conversation_key_for_ref(conversation_ref)
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    event = InboundAction(
        user=InboundUser(id=actor_key, username="registry"),
        conversation_key=conversation_key,
        action=action,
        params=dict(action_payload),
        source="registry",
        conversation_ref=conversation_ref,
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


async def admit_registry_delivery(config: BotConfig, delivery: dict[str, Any]) -> str:
    """Convert a registry delivery into a normal local work item or control action."""
    kind = delivery.get("kind", "")
    payload = delivery.get("payload", {})
    delivery_id = delivery.get("delivery_id", "")
    data_dir = config.data_dir

    if kind == "surface_input":
        conversation_ref = payload["conversation_id"]
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=payload.get("text", ""),
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=delivery_id,
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
            await bind_conversation(
                config,
                conversation_ref=conversation_ref,
                title=payload.get("title", "Registry conversation"),
                origin_surface="registry",
                external_id=conversation_ref,
            )
            await publish_timeline_event(
                config,
                conversation_ref=conversation_ref,
                kind="surface_input",
                title="Registry message",
                body=payload.get("text", ""),
            )
        return "accepted"

    if kind == "routed_task":
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
        conversation_ref = request["routed_task_id"]
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=text,
            actor_ref=f"agent:{request.get('origin_agent_id', '')}",
            delivery_id=delivery_id,
            routed_task_id=request["routed_task_id"],
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
            await bind_conversation(
                config,
                conversation_ref=conversation_ref,
                title=request.get("title", "Delegated task"),
                origin_surface="registry",
                external_id=request["routed_task_id"],
            )
            await publish_timeline_event(
                config,
                conversation_ref=conversation_ref,
                kind="routed_task",
                title="Delegated task received",
                body=text,
                metadata={
                    "routed_task_id": request["routed_task_id"],
                    "parent_conversation_id": request.get("parent_conversation_id", ""),
                    "origin_agent_id": request.get("origin_agent_id", ""),
                },
            )
        return "accepted"

    return "rejected"


def summarize_text(text: str, limit: int = 240) -> str:
    clean = " ".join(text.strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"
