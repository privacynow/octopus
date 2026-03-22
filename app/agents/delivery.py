"""Dispatch polled registry deliveries onto the existing local workflow core."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import work_queue
from app.agents.registry_capabilities import registry_authority_ref
from app.agents.bridge import (
    admit_registry_delivery,
    build_registry_action_envelope,
    build_registry_message_delivery,
    qualify_registry_parent_ref,
)
from app.agents.types import RoutedTaskResult
from app.config import BotConfig
from app.identity import conversation_key_for_ref
from app.runtime.work_admission import enqueue_inbound_envelope, record_inbound_envelope
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import BotServices
from app.runtime.session_runtime import (
    apply_runtime_delegation_result,
    load_runtime_session,
    save_runtime_session,
)
from app.skill_activation_service import get_skill_activation_service
from app.workflows.delegation.coordination import send_delegation_completion_message

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistryDeliveryRuntime:
    provider_name: str
    provider_state_factory: Callable[[], dict[str, Any]]
    services: BotServices
    bot: Any | None = None
    dispatcher: ChannelDispatcher | None = None


def build_registry_delivery_runtime(
    *,
    provider_name: str,
    provider_state_factory: Callable[[], dict[str, Any]],
    services: BotServices,
    bot: Any | None = None,
    dispatcher: ChannelDispatcher | None = None,
) -> RegistryDeliveryRuntime:
    return RegistryDeliveryRuntime(
        provider_name=provider_name,
        provider_state_factory=provider_state_factory,
        services=services,
        bot=bot,
        dispatcher=dispatcher,
    )


def _load_session(
    config: BotConfig,
    runtime: RegistryDeliveryRuntime,
    conversation_key: str,
):
    session = load_runtime_session(
        config.data_dir,
        conversation_key,
        provider_name=runtime.provider_name,
        provider_state_factory=runtime.provider_state_factory,
        approval_mode=config.approval_mode,
        default_role=config.role,
        default_skills=config.default_skills,
    )
    if get_skill_activation_service().normalize(session):
        _save_session(config, conversation_key, session)
    return session


def _save_session(
    config: BotConfig,
    conversation_key: str,
    session,
) -> None:
    save_runtime_session(config.data_dir, conversation_key, session)


def _registry_semantic_action(
    *,
    conversation_ref: str,
    action: str,
    payload: dict[str, object],
    delivery_id: str,
    registry_id: str,
):
    semantic = {
        "approve": "approve_pending",
        "reject": "reject_pending",
        "cancel_conversation": "cancel_conversation",
        "retry_skip": "retry_skip",
        "retry_allow": "retry_allow",
        "approve_delegation": "delegation_approve",
        "cancel_delegation": "delegation_cancel",
        "recovery_discard": "recovery_discard",
        "recovery_replay": "recovery_replay",
    }.get(action)
    if not semantic:
        return None

    params = dict(payload)
    if semantic in {"recovery_discard", "recovery_replay"}:
        update_id = int(payload.get("update_id") or 0)
        if update_id <= 0:
            return None
        params["update_id"] = update_id

    return build_registry_action_envelope(
        conversation_ref=conversation_ref,
        action=semantic,
        action_payload=params,
        actor_ref=f"registry-ui:{conversation_ref}",
        delivery_id=delivery_id,
        registry_id=registry_id,
    )


async def _publish_timeline(
    *,
    services: BotServices,
    conversation_ref: str,
    kind: str,
    title: str,
    body: str = "",
    status: str = "",
    progress: int | None = None,
    metadata: dict[str, object] | None = None,
    event_id: str | None = None,
) -> None:
    await services.control_plane.conversation_projection.publish_external_timeline(
        conversation_ref=conversation_ref,
        kind=kind,
        title=title,
        body=body,
        status=status,
        progress=progress,
        metadata=metadata,
        event_id=event_id,
    )


async def handle_registry_delivery(
    config: BotConfig,
    delivery: dict[str, object],
    *,
    runtime: RegistryDeliveryRuntime,
) -> str:
    kind = str(delivery.get("kind", ""))
    delivery_id = str(delivery.get("delivery_id", ""))
    registry_id = str(delivery.get("registry_id", "") or "")
    if kind in {"channel_input", "routed_task"}:
        return await admit_registry_delivery(
            config,
            delivery,
            dispatcher=runtime.dispatcher,
        )

    payload = delivery.get("payload", {})
    if not isinstance(payload, dict):
        return "rejected"
    if kind == "channel_action":
        if not registry_id:
            return "rejected"
        conversation_ref = str(payload.get("conversation_ref", "") or payload.get("conversation_id", ""))
        if not conversation_ref:
            return "rejected"
        conversation_ref = qualify_registry_parent_ref(registry_id, conversation_ref)
        action_payload = payload.get("payload", {})
        if not isinstance(action_payload, dict):
            action_payload = {}
        action = str(payload.get("action", "")).lower()
        if action in {"recovery_discard", "recovery_replay"} and "update_id" not in action_payload:
            action_payload = dict(action_payload)
            action_payload["update_id"] = payload.get("update_id")
        envelope = _registry_semantic_action(
            conversation_ref=conversation_ref,
            action=action,
            payload=action_payload,
            delivery_id=delivery_id,
            registry_id=registry_id,
        )
        if envelope is None:
            return "rejected"
        if action == "cancel_conversation":
            is_new = record_inbound_envelope(config.data_dir, envelope)
            if not is_new:
                return "accepted"
            result = work_queue.request_cancel(
                config.data_dir,
                envelope.conversation_key,
                envelope.actor_key,
                cancel_request_event_id=envelope.event_id,
            )
            if result == work_queue.CancelRequestResult.nothing_to_cancel:
                work_queue.enqueue_work_item(
                    config.data_dir,
                    envelope.conversation_key,
                    envelope.event_id,
                )
            return "accepted"
        enqueue_inbound_envelope(config.data_dir, envelope)
        return "accepted"

    if kind == "routed_result":
        if not registry_id:
            return "rejected"
        routed_task_id = str(payload.get("routed_task_id", ""))
        parent_conversation_id = qualify_registry_parent_ref(
            registry_id,
            str(payload.get("parent_conversation_id", "")),
        )
        result = payload.get("result", {})
        if not parent_conversation_id or not routed_task_id or not isinstance(result, dict):
            return "rejected"
        routed_result = RoutedTaskResult(
            routed_task_id=routed_task_id,
            status=str(result.get("status", "") or ""),
            summary=str(result.get("summary", "") or ""),
            full_text=str(result.get("full_text", "") or ""),
            artifacts=tuple(result.get("artifacts", ()) or ()),
            follow_up_questions=tuple(str(item) for item in (result.get("follow_up_questions", ()) or ()) if item),
            completed_at=str(result.get("completed_at", "") or ""),
        )
        if runtime.dispatcher is None:
            raise RuntimeError("Registry delivery runtime requires a channel dispatcher")
        if not runtime.dispatcher.egress_ready_for_ref(
            parent_conversation_id,
            config=config,
            bot=runtime.bot,
            conversation_key=conversation_key_for_ref(parent_conversation_id),
            source="registry",
        ):
            return "retry_later"
        conversation_key = conversation_key_for_ref(parent_conversation_id)
        applied = apply_runtime_delegation_result(
            config.data_dir,
            conversation_key,
            routed_task_id=routed_task_id,
            authority_ref=registry_authority_ref(registry_id),
            result=routed_result,
        )
        if not applied.matched:
            log.warning(
                "Routed result for task %s from authority %s did not match any pending delegation task",
                routed_task_id,
                registry_authority_ref(registry_id),
            )
            return "accepted"
        await _publish_timeline(
            services=runtime.services,
            conversation_ref=parent_conversation_id,
            kind="delegated_result",
            title="Delegated result received",
            body=routed_result.full_text or routed_result.summary,
            status=routed_result.status,
            metadata={"routed_task_id": routed_task_id},
            event_id=f"delegated-result:{routed_task_id}",
        )
        if not applied.ready_to_resume or applied.pending is None:
            return "accepted"
        continuation_text = applied.resume_prompt
        resume_delivery_id = (
            f"delegation-resume:{parent_conversation_id}:{int(applied.pending.created_at * 1000)}"
        )
        conversation_key, actor_key, event_id, serialized = build_registry_message_delivery(
            conversation_ref=parent_conversation_id,
            text=continuation_text,
            actor_ref=f"delegation-resume:{routed_task_id}",
            delivery_id=resume_delivery_id,
            registry_id=registry_id,
            skip_approval=True,
        )
        admit_status, _ = work_queue.record_and_admit_message(
            config.data_dir,
            event_id,
            conversation_key,
            actor_key,
            "message",
            serialized,
        )
        if admit_status == "admitted":
            if runtime.dispatcher is None:
                raise RuntimeError("Registry delivery runtime requires a channel dispatcher")
            channel_egress = runtime.dispatcher.create_egress(
                parent_conversation_id,
                config=config,
                bot=runtime.bot,
                conversation_key=conversation_key,
                source="registry",
            )
            try:
                await send_delegation_completion_message(applied.pending, channel_egress)
            except Exception:
                log.warning(
                    "Failed to send delegation completion summary for %s",
                    parent_conversation_id,
                    exc_info=True,
                )
            await _publish_timeline(
                services=runtime.services,
                conversation_ref=parent_conversation_id,
                kind="delegation_ready",
                title="All delegated results received",
                body=continuation_text,
                metadata={"routed_task_id": routed_task_id},
                event_id=f"delegation-ready:{parent_conversation_id}",
            )
        elif admit_status == "duplicate":
            await _publish_timeline(
                services=runtime.services,
                conversation_ref=parent_conversation_id,
                kind="delegation_ready",
                title="All delegated results received",
                body=continuation_text,
                metadata={"routed_task_id": routed_task_id},
                event_id=f"delegation-ready:{parent_conversation_id}",
            )
        return "accepted"

    return "rejected"
