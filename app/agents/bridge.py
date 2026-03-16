"""Bridge registry deliveries and timeline mirroring onto the existing worker path."""

from __future__ import annotations

import hashlib
import html
import logging
import uuid
from pathlib import Path
from typing import Any

from telegram.constants import ParseMode

from app import work_queue
from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import load_agent_runtime_state
from app.agents.types import RoutedTaskResult, TimelineEvent
from app.config import BotConfig
from app.transport import InboundMessage, InboundUser, serialize_inbound

log = logging.getLogger(__name__)


def _stable_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def registry_chat_id(conversation_ref: str) -> int:
    return _stable_int(f"registry-chat:{conversation_ref}")


def registry_update_id(delivery_id: str) -> int:
    return _stable_int(f"registry-update:{delivery_id}")


def registry_actor_id(actor_ref: str) -> int:
    return _stable_int(f"registry-actor:{actor_ref}")


def conversation_surface_name(conversation_ref: str) -> str:
    if conversation_ref.startswith("telegram:"):
        return "telegram"
    return "registry"


def local_chat_id_for_conversation(conversation_ref: str) -> int:
    if conversation_surface_name(conversation_ref) == "telegram":
        try:
            return int(conversation_ref.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return registry_chat_id(conversation_ref)
    return registry_chat_id(conversation_ref)


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
) -> tuple[int, int, int, str]:
    chat_id = local_chat_id_for_conversation(conversation_ref)
    user_id = registry_actor_id(actor_ref)
    update_id = registry_update_id(delivery_id)
    payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id=user_id, username="registry"),
            chat_id=chat_id,
            text=text,
            attachments=(),
            source="registry",
            conversation_ref=conversation_ref,
            routed_task_id=routed_task_id,
        )
    )
    return chat_id, user_id, update_id, payload


async def admit_registry_delivery(config: BotConfig, delivery: dict[str, Any]) -> str:
    """Convert a registry delivery into a normal local work item or control action."""
    kind = delivery.get("kind", "")
    payload = delivery.get("payload", {})
    delivery_id = delivery.get("delivery_id", "")
    data_dir = config.data_dir

    if kind == "surface_input":
        conversation_ref = payload["conversation_id"]
        chat_id, user_id, update_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=payload.get("text", ""),
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=delivery_id,
        )
        status, _ = work_queue.record_and_admit_message(
            data_dir,
            update_id,
            chat_id,
            user_id,
            "message",
            serialized,
        )
        if status == "busy":
            return "retry_later"
        if status in {"admitted", "duplicate"}:
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
        chat_id, user_id, update_id, serialized = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=text,
            actor_ref=f"agent:{request.get('origin_agent_id', '')}",
            delivery_id=delivery_id,
            routed_task_id=request["routed_task_id"],
        )
        status, _ = work_queue.record_and_admit_message(
            data_dir,
            update_id,
            chat_id,
            user_id,
            "message",
            serialized,
        )
        if status == "busy":
            return "retry_later"
        if status in {"admitted", "duplicate"}:
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
