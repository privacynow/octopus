"""Registry delivery transport lifecycle."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Any
from collections.abc import Callable, Mapping

from app.agents.registry_projection_interfaces import registry_implementation_ref
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.state import load_runtime_registry_connection_state
from app.channels.registry.refs import (
    binding_external_id_for_ref,
    qualify_registry_conversation_ref,
    registry_task_ref,
)
from app.config import BotConfig
from app.runtime.session_runtime import save_runtime_session
from app.storage import build_upload_path, is_image_path
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.processor_runner import ProcessorRunner
from octopus_sdk.transport_dispatcher import TransportDispatcher
from app.runtime.services import BotServices
from app.runtime_health import CanonicalRuntimeHealthProvider
from app.runtime.registry_participant import AgentRuntime
from app import work_queue
from octopus_sdk.config import BotConfigBase
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.identity import (
    conversation_key_for_ref,
    delegation_session_key,
    resolve_delegation_parent_identity,
    resolve_external_conversation_ref,
)
from octopus_sdk.inbound_types import (
    InboundAction,
    InboundAttachment,
    InboundEnvelope,
    InboundMessage,
    InboundUser,
    serialize_inbound,
)
from octopus_sdk.providers import Provider
from octopus_sdk.registry.client import RegistryClient
from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.registry.management import (
    ArtifactRuntimeFetchRequest,
    ArtifactRuntimeHealthRequest,
    ArtifactRuntimeLogsRequest,
    DesignAutoProtocolRequest,
    DesignAutoProtocolResult,
    ManagementRequest,
    ManagementResult,
    StartArtifactRuntimeRequest,
    StopArtifactRuntimeRequest,
    WorkspaceCleanupRequest,
    WorkspaceUsageRequest,
)
from octopus_sdk.registry.management_executor import (
    ManagementExecutionContext,
    execute_management_request,
)
from octopus_sdk.transport import (
    BotRuntimeHandle,
    DelegationContinuationRequest,
    TransportBindingRecord,
    TransportDescriptor,
    TransportEgress,
    TransportHealthRecord,
    TransportImplementation,
)
log = logging.getLogger(__name__)

@dataclass(frozen=True)
class _RegistryControlAccess:
    config: BotConfig
    registries: tuple[RegistryConnectionConfig, ...]
    runtimes_by_id: dict[str, AgentRuntime]

    def client_for_registry(self, registry_id: str) -> RegistryClient | None:
        registry = next((item for item in self.registries if item.registry_id == registry_id), None)
        if registry is None:
            return None
        runtime = self.runtimes_by_id.get(registry_id)
        if runtime is not None and runtime.state.agent_token:
            return RegistryClient(registry.url, agent_token=runtime.state.agent_token)
        state = load_runtime_registry_connection_state(
            self.config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        if not state.agent_token:
            return None
        return RegistryClient(registry.url, agent_token=state.agent_token)

    def origin_agent_id(self, registry_id: str) -> str:
        registry = next((item for item in self.registries if item.registry_id == registry_id), None)
        if registry is None:
            return ""
        runtime = self.runtimes_by_id.get(registry_id)
        if runtime is not None:
            return runtime.state.agent_id
        state = load_runtime_registry_connection_state(
            self.config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        return state.agent_id


@dataclass(frozen=True)
class RegistryDeliveryRuntime:
    provider_name: str
    provider: Provider | None
    provider_state_factory: Callable[[str], dict[str, Any]]
    services: BotServices
    submitter: BotRuntimeHandle | None = None
    bot: Any | None = None
    dispatcher: TransportDispatcher | None = None


def build_registry_delivery_runtime(
    *,
    provider_name: str,
    provider: Provider | None = None,
    provider_state_factory: Callable[[str], dict[str, Any]],
    services: BotServices,
    submitter: BotRuntimeHandle | None = None,
    bot: Any | None = None,
    dispatcher: TransportDispatcher | None = None,
) -> RegistryDeliveryRuntime:
    return RegistryDeliveryRuntime(
        provider_name=provider_name,
        provider=provider,
        provider_state_factory=provider_state_factory,
        services=services,
        submitter=submitter,
        bot=bot,
        dispatcher=dispatcher,
    )


def qualify_registry_parent_ref(registry_id: str, conversation_ref: str) -> str:
    if not registry_id:
        raise ValueError("Registry parent ref qualification requires an explicit registry_id")
    return qualify_registry_conversation_ref(registry_id, conversation_ref)


def build_registry_message_delivery(
    *,
    conversation_ref: str,
    text: str,
    title_text: str = "",
    actor_ref: str,
    delivery_id: str,
    external_conversation_ref: str = "",
    routed_task_id: str = "",
    registry_id: str,
    skip_approval: bool = False,
    conversation_key_override: str = "",
    authorized_actor_key: str = "",
    context_text: str = "",
    constraints_text: str = "",
    requested_skills: tuple[str, ...] = (),
    protocol_stage_contract: dict[str, Any] | None = None,
    working_dir_hint: str = "",
    attachments: tuple[InboundAttachment, ...] = (),
    source_transport: str = "registry",
    admission_class: str = "external",
) -> tuple[str, str, str, str]:
    envelope = build_registry_message_envelope(
        conversation_ref=conversation_ref,
        text=text,
        title_text=title_text,
        actor_ref=actor_ref,
        delivery_id=delivery_id,
        external_conversation_ref=external_conversation_ref,
        routed_task_id=routed_task_id,
        registry_id=registry_id,
        skip_approval=skip_approval,
        conversation_key_override=conversation_key_override,
        authorized_actor_key=authorized_actor_key,
        context_text=context_text,
        constraints_text=constraints_text,
        requested_skills=requested_skills,
        protocol_stage_contract=protocol_stage_contract,
        working_dir_hint=working_dir_hint,
        attachments=attachments,
        source_transport=source_transport,
        admission_class=admission_class,
    )
    payload = serialize_inbound(envelope.event)
    return envelope.conversation_key, envelope.actor_key, envelope.event_id, payload


def build_registry_message_envelope(
    *,
    conversation_ref: str,
    text: str,
    title_text: str = "",
    actor_ref: str,
    delivery_id: str,
    external_conversation_ref: str = "",
    routed_task_id: str = "",
    registry_id: str,
    skip_approval: bool = False,
    conversation_key_override: str = "",
    authorized_actor_key: str = "",
    context_text: str = "",
    constraints_text: str = "",
    requested_skills: tuple[str, ...] = (),
    protocol_stage_contract: dict[str, Any] | None = None,
    working_dir_hint: str = "",
    attachments: tuple[InboundAttachment, ...] = (),
    source_transport: str = "registry",
    admission_class: str = "external",
) -> InboundEnvelope:
    if not registry_id:
        raise ValueError("Registry message delivery requires an explicit registry_id")
    source_transport = str(source_transport or "registry").strip() or "registry"
    conversation_key = conversation_key_override or conversation_key_for_ref(conversation_ref)
    resolved_external_ref = resolve_external_conversation_ref(
        origin_channel=source_transport,
        external_conversation_ref=external_conversation_ref,
        conversation_ref=conversation_ref,
        conversation_key=conversation_key,
    )
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    event = InboundMessage(
        user=InboundUser(id=actor_key, username="registry"),
        conversation_key=conversation_key,
        text=text,
        title_text=title_text,
        attachments=attachments,
        source=source_transport,
        transport=source_transport,
        conversation_ref=conversation_ref,
        external_conversation_ref=resolved_external_ref,
        routed_task_id=routed_task_id,
        context_text=context_text,
        constraints_text=constraints_text,
        requested_skills=requested_skills,
        protocol_stage_contract=dict(protocol_stage_contract or {}),
        working_dir_hint=str(working_dir_hint or ""),
        authorized_actor_key=authorized_actor_key,
        authority_ref=registry_implementation_ref(registry_id),
        skip_approval=skip_approval,
        admission_class=admission_class,
    )
    return InboundEnvelope(
        transport=source_transport,
        event_id=event_id,
        conversation_key=conversation_key,
        actor_key=actor_key,
        received_at=datetime.now(timezone.utc),
        event=event,
        conversation_ref=conversation_ref,
        admission_class=admission_class,
    )


def _transport_for_conversation_ref(conversation_ref: str) -> str:
    token = str(conversation_ref or "").strip()
    if not token or ":" not in token:
        return "registry"
    return token.split(":", 1)[0] or "registry"


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
    resolved_external_ref = resolve_external_conversation_ref(
        origin_channel="registry",
        external_conversation_ref=external_conversation_ref,
        conversation_ref=conversation_ref,
        conversation_key=conversation_key,
    )
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
        external_conversation_ref=resolved_external_ref,
        authority_ref=registry_implementation_ref(registry_id),
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

def _coerce_registry_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, sort_keys=True)
    return str(value or "").strip()


def _resource_refs_from_request(request: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in request.get("resource_refs", []) or []:
        text = str(item or "").strip()
        if text:
            refs.append(text)
    constraints = request.get("constraints", {})
    if isinstance(constraints, Mapping):
        for item in constraints.get("resource_refs", []) or []:
            text = str(item or "").strip()
            if text and text not in refs:
                refs.append(text)
    return refs


def _registry_client_for_delivery(config: BotConfig, registry_id: str) -> RegistryClient | None:
    registry = next((item for item in config.agent_registries if item.registry_id == registry_id), None)
    if registry is None or not registry.url:
        return None
    state = load_runtime_registry_connection_state(
        config.data_dir,
        registry_id,
        registry_scope=registry.registry_scope,
    )
    if not state.agent_token:
        return None
    return RegistryClient(registry.url, agent_token=state.agent_token)


async def _materialize_registry_resources(
    *,
    config: BotConfig,
    registry_id: str,
    conversation_key: str,
    resource_refs: object,
) -> tuple[InboundAttachment, ...]:
    refs = [
        str(item or "").strip()
        for item in (resource_refs or [])
        if str(item or "").strip()
    ]
    if not refs:
        return ()
    client = _registry_client_for_delivery(config, registry_id)
    if client is None:
        raise RuntimeError("Registry resource materialization requires an enrolled registry client")
    attachments: list[InboundAttachment] = []
    for resource_id in refs:
        resource = await client.get_resource(resource_id)
        content = await client.download_resource_content(resource_id)
        original_name = resource.original_name or f"{resource_id}.bin"
        target = build_upload_path(config.data_dir, conversation_key, original_name)
        target.write_bytes(content)
        mime_type = resource.mime_type or ""
        attachments.append(
            InboundAttachment(
                path=target,
                original_name=original_name,
                is_image=mime_type.startswith("image/") or is_image_path(target),
                mime_type=mime_type or None,
                resource_id=resource_id,
                source_surface=resource.source_surface or "registry",
            )
        )
    return tuple(attachments)


async def admit_registry_delivery(
    config: BotConfig,
    delivery: dict[str, Any],
    *,
    submitter: BotRuntimeHandle,
    dispatcher: TransportDispatcher | None = None,
    runtime: RegistryDeliveryRuntime | None = None,
) -> str:
    kind = str(delivery.get("kind", ""))
    payload = delivery.get("payload", {})
    delivery_id = delivery.get("delivery_id", "")
    registry_id = str(delivery.get("registry_id", "") or "")
    if kind == "channel_input":
        if not registry_id:
            return "rejected"
        conversation_ref = qualify_registry_conversation_ref(registry_id, str(payload["conversation_id"]))
        stable_event_id = str(payload.get("stable_event_id", "") or "")
        effective_delivery_id = stable_event_id if stable_event_id else delivery_id
        conversation_key = conversation_key_for_ref(conversation_ref)
        attachments = await _materialize_registry_resources(
            config=config,
            registry_id=registry_id,
            conversation_key=conversation_key,
            resource_refs=payload.get("resource_refs", []),
        )
        # Registry UI input originates from the registry surface, so these remain
        # registry envelopes even when the conversation later mirrors elsewhere.
        envelope = build_registry_message_envelope(
            conversation_ref=conversation_ref,
            text=payload.get("text", ""),
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=effective_delivery_id,
            external_conversation_ref=str(payload.get("external_conversation_ref", "") or ""),
            registry_id=registry_id,
            attachments=attachments,
        )
        submission = await submitter.admit_message(envelope)
        if submission.status in {"admitted", "queued", "duplicate"}:
            if dispatcher is None:
                raise RuntimeError("Registry delivery admission requires a channel dispatcher")
            channel_egress = dispatcher.create_egress(
                conversation_ref,
                config=config,
                conversation_key=envelope.conversation_key,
                source="registry",
            )
            await channel_egress.sync_binding(
                TransportBindingRecord(
                    conversation_ref=conversation_ref,
                    title=str(payload.get("title", "Registry conversation") or ""),
                    origin_channel="registry",
                    external_id=str(
                        payload.get("external_conversation_ref", "") or binding_external_id_for_ref(conversation_ref)
                    ),
                )
            )
        return "accepted"

    if kind == "routed_task":
        if not registry_id:
            return "rejected"
        request = payload
        title_text = _coerce_registry_message_text(request.get("title", ""))
        text = _coerce_registry_message_text(request.get("instructions", "")) or title_text
        conversation_ref = registry_task_ref(registry_id, request["routed_task_id"])
        origin_agent_id = request.get("origin_agent_id", "")
        parent_conversation_id = request.get("parent_conversation_id", "")
        session_key_override = str(request.get("session_key_override", "") or "").strip()
        if session_key_override:
            shared_key = session_key_override
        elif origin_agent_id and parent_conversation_id:
            shared_key = delegation_session_key(origin_agent_id, parent_conversation_id)
        else:
            shared_key = ""
        conversation_key_for_resources = shared_key or conversation_key_for_ref(conversation_ref)
        attachments = await _materialize_registry_resources(
            config=config,
            registry_id=registry_id,
            conversation_key=conversation_key_for_resources,
            resource_refs=_resource_refs_from_request(request),
        )
        # Routed task deliveries originate from the registry and intentionally
        # enter the worker through the registry transport.
        envelope = build_registry_message_envelope(
            conversation_ref=conversation_ref,
            conversation_key_override=shared_key,
            text=text,
            title_text=title_text,
            actor_ref=f"agent:{request.get('origin_agent_id', '')}",
            delivery_id=delivery_id,
            external_conversation_ref=str(request.get("external_conversation_ref", "") or ""),
            routed_task_id=request["routed_task_id"],
            authorized_actor_key=str(request.get("authorized_actor_key", "") or ""),
            context_text=_coerce_registry_message_text(request.get("context", "")),
            constraints_text=_coerce_registry_message_text(request.get("constraints", "")),
            requested_skills=tuple(str(item).strip() for item in (request.get("requested_skills", []) or ()) if str(item).strip()),
            protocol_stage_contract=_protocol_stage_contract_from_request(request),
            registry_id=registry_id,
            attachments=attachments,
        )
        if runtime is not None and envelope.conversation_key:
            working_dir_hint = _apply_routed_task_session_overrides(
                config=config,
                runtime=runtime,
                conversation_key=envelope.conversation_key,
                request=request,
            )
            envelope = replace(
                envelope,
                event=replace(envelope.event, working_dir_hint=working_dir_hint),
            )
        await submitter.admit_message(envelope)
        return "accepted"

    return "rejected"


def _load_session(
    config: BotConfig,
    runtime: RegistryDeliveryRuntime,
    conversation_key: str,
):
    return runtime.services.sessions.load(
        conversation_key,
        provider_name=runtime.provider_name,
        provider_state_factory=runtime.provider_state_factory,
        approval_mode=config.approval_mode,
        default_role=config.role,
        default_skills=config.default_skills,
    )


def _save_session(config: BotConfig, conversation_key: str, session) -> None:
    save_runtime_session(config.data_dir, conversation_key, session)


def _apply_routed_task_session_overrides(
    *,
    config: BotConfig,
    runtime: RegistryDeliveryRuntime,
    conversation_key: str,
    request: dict[str, Any],
) -> str:
    project_id = str(request.get("project_id_override", "") or "").strip()
    file_policy = str(request.get("file_policy_override", "") or "").strip()
    session = _load_session(config, runtime, conversation_key)
    mutated = False
    if project_id and session.project_id != project_id:
        session.project_id = project_id
        session.provider_state = runtime.provider_state_factory(conversation_key)
        session.clear_pending()
        mutated = True
    if file_policy and session.file_policy != file_policy:
        session.file_policy = file_policy
        if not project_id:
            session.provider_state = runtime.provider_state_factory(conversation_key)
            session.clear_pending()
        mutated = True
    if mutated:
        _save_session(config, conversation_key, session)
    resolved = runtime.services.sessions.resolve_context(
        session,
        config=config,
        provider_name=runtime.provider_name,
        trust_tier="trusted",
    )
    return str(resolved.working_dir or config.working_dir or "").strip()


def _protocol_stage_contract_from_request(request: dict[str, Any]) -> dict[str, Any]:
    internal_context = request.get("internal_context", {})
    if not isinstance(internal_context, dict):
        return {}
    contract = internal_context.get("protocol_stage_contract", {})
    return dict(contract) if isinstance(contract, dict) else {}


async def handle_registry_delivery(
    config: BotConfig,
    delivery: dict[str, object],
    *,
    runtime: RegistryDeliveryRuntime,
) -> str:
    kind = str(delivery.get("kind", ""))
    delivery_id = str(delivery.get("delivery_id", ""))
    registry_id = str(delivery.get("registry_id", "") or "")
    submitter = runtime.submitter
    if submitter is None:
        raise RuntimeError("Registry delivery runtime is missing a bot runtime submitter")
    if kind in {"channel_input", "routed_task"}:
        return await admit_registry_delivery(
            config,
            delivery,
            submitter=submitter,
            dispatcher=runtime.dispatcher,
            runtime=runtime,
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
        if action in {"recovery_discard", "recovery_replay"} and "recovery_id" not in action_payload:
            action_payload = dict(action_payload)
            action_payload["recovery_id"] = payload.get("recovery_id")
        if action not in {
            "approve_pending",
            "reject_pending",
            "cancel_conversation",
            "retry_skip",
            "retry_allow",
            "delegation_approve",
            "delegation_cancel",
            "recovery_discard",
            "recovery_replay",
        }:
            return "rejected"
        if action in {"recovery_discard", "recovery_replay"}:
            recovery_id = str(action_payload.get("recovery_id") or "").strip()
            if not recovery_id:
                return "rejected"
            action_payload = dict(action_payload)
            action_payload["recovery_id"] = recovery_id
        stable_event_id = str(payload.get("stable_event_id", "") or "")
        effective_delivery_id = stable_event_id if stable_event_id else delivery_id
        envelope = build_registry_action_envelope(
            conversation_ref=conversation_ref,
            action=action,
            action_payload=action_payload,
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=effective_delivery_id,
            registry_id=registry_id,
            external_conversation_ref=str(payload.get("external_conversation_ref", "") or ""),
        )
        if action == "cancel_conversation":
            is_new = await submitter.record(envelope)
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
        await submitter.enqueue(envelope)
        return "accepted"

    if kind == "routed_result":
        if not registry_id:
            return "rejected"
        routed_task_id = str(payload.get("routed_task_id", ""))
        if routed_task_id.startswith("protocol-stage:"):
            return "accepted"
        parent_conversation_id = qualify_registry_parent_ref(
            registry_id,
            str(payload.get("parent_conversation_id", "")),
        )
        parent_transport_ref = str(payload.get("parent_transport_ref", "") or "")
        parent_external_conversation_ref = str(
            payload.get("parent_external_conversation_ref", "") or ""
        )
        result = payload.get("result", {})
        if not parent_conversation_id or not routed_task_id or not isinstance(result, dict):
            return "rejected"
        parent_target_ref, parent_conversation_key = resolve_delegation_parent_identity(
            parent_transport_ref=parent_transport_ref,
            parent_external_conversation_ref=parent_external_conversation_ref,
            parent_conversation_id=parent_conversation_id,
        )
        if not parent_target_ref or not parent_conversation_key:
            return "rejected"
        routed_result = RoutedTaskResult(
            routed_task_id=routed_task_id,
            status=str(result.get("status", "") or ""),
            transition_id=str(result.get("transition_id", "") or ""),
            summary=str(result.get("summary", "") or ""),
            full_text=str(result.get("full_text", "") or ""),
            artifacts=tuple(result.get("artifacts", ()) or ()),
            follow_up_questions=tuple(str(item) for item in (result.get("follow_up_questions", ()) or ()) if item),
            completed_at=str(result.get("completed_at", "") or ""),
        )
        try:
            continuation = await submitter.continue_delegation(
                DelegationContinuationRequest(
                    parent_conversation_key=parent_conversation_key,
                    parent_transport_ref=parent_target_ref,
                    parent_external_conversation_ref=(
                        parent_external_conversation_ref or parent_target_ref
                    ),
                    routed_task_id=routed_task_id,
                    authority_ref=registry_implementation_ref(registry_id),
                    result=routed_result,
                )
            )
        except Exception:
            log.warning(
                "Delegation continuation failed for routed task %s",
                routed_task_id,
                exc_info=True,
            )
            return "retry_later"
        if not continuation.matched:
            log.warning(
                "Routed result for task %s authority %s did not match any pending delegation task",
                routed_task_id,
                registry_implementation_ref(registry_id),
            )
        return "accepted"

    if kind == "management_request":
        if not registry_id:
            return "rejected"
        try:
            request = ManagementRequest.model_validate(payload)
        except Exception:
            return "rejected"
        registry = next(
            (item for item in config.agent_registries if item.registry_id == registry_id),
            None,
        )
        if registry is None:
            return "rejected"
        state = load_runtime_registry_connection_state(
            config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        if not state.agent_token:
            return "retry_later"
        if isinstance(request.payload, DesignAutoProtocolRequest):
            from app.runtime.auto_protocol_design import design_auto_protocol_with_provider

            try:
                if runtime.provider is None:
                    raise RuntimeError("Auto Protocol planner requires a provider-capable runtime.")
                response = await design_auto_protocol_with_provider(
                    request.payload.request,
                    config=config,
                    provider=runtime.provider,
                    provider_state_factory=runtime.provider_state_factory,
                )
                result = ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=True,
                    payload=DesignAutoProtocolResult(response=response),
                )
            except Exception as exc:
                result = ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=False,
                    error_code="request_failed",
                    error_detail=str(exc),
                )
        elif isinstance(
            request.payload,
            (
                StartArtifactRuntimeRequest,
                StopArtifactRuntimeRequest,
                ArtifactRuntimeHealthRequest,
                ArtifactRuntimeLogsRequest,
                ArtifactRuntimeFetchRequest,
                WorkspaceUsageRequest,
                WorkspaceCleanupRequest,
            ),
        ):
            from app.runtime import artifact_runtime

            try:
                if isinstance(request.payload, StartArtifactRuntimeRequest):
                    payload = await artifact_runtime.start_artifact_runtime(
                        request.payload,
                        config=config,
                    )
                elif isinstance(request.payload, StopArtifactRuntimeRequest):
                    payload = await artifact_runtime.stop_artifact_runtime(request.payload)
                elif isinstance(request.payload, ArtifactRuntimeHealthRequest):
                    payload = await artifact_runtime.artifact_runtime_health(request.payload)
                elif isinstance(request.payload, ArtifactRuntimeLogsRequest):
                    payload = await artifact_runtime.artifact_runtime_logs(request.payload)
                elif isinstance(request.payload, WorkspaceUsageRequest):
                    from app.runtime import workspace_hygiene

                    payload = await workspace_hygiene.workspace_usage(request.payload, config=config)
                elif isinstance(request.payload, WorkspaceCleanupRequest):
                    from app.runtime import workspace_hygiene

                    payload = await workspace_hygiene.workspace_cleanup(request.payload, config=config)
                else:
                    payload = await artifact_runtime.artifact_runtime_fetch(request.payload)
                result = ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=True,
                    payload=payload,
                )
            except Exception as exc:
                result = ManagementResult(
                    request_id=request.request_id,
                    agent_id=request.agent_id,
                    success=False,
                    error_code="request_failed",
                    error_detail=str(exc),
                )
        else:
            result = await execute_management_request(
                request,
                context=ManagementExecutionContext(
                    config=config,
                    workflows=runtime.services.workflows,
                    provider_state_factory=runtime.provider_state_factory,
                    execution_faults=runtime.services.execution_services.execution_faults,
                ),
            )
        client = RegistryClient(registry.url, agent_token=state.agent_token)
        try:
            await client.management_result(request.request_id, result)
        except Exception:
            return "retry_later"
        return "accepted"

    return "rejected"


class RegistryDeliveryTransport(TransportImplementation):
    """Own registry delivery polling as a transport lifecycle participant."""

    def __init__(
        self,
        config: BotConfig,
        provider: Provider,
        *,
        services: BotServices,
        dispatcher: TransportDispatcher,
        bus: ControlPlaneBus,
        directory: ControlPlaneDirectory,
    ) -> None:
        self._config = config
        self._provider = provider
        self._services = services
        self._dispatcher = dispatcher
        self._bus = bus
        self._directory = directory
        self._stop_requested = asyncio.Event()
        self._runtime_tasks: dict[str, asyncio.Task[None]] = {}
        self._registry_runtimes: dict[str, AgentRuntime] = {}
        self._parent_stop_task: asyncio.Task[None] | None = None
        delivery_runtime = build_registry_delivery_runtime(
            provider_name=provider.name,
            provider=provider,
            provider_state_factory=provider.new_provider_state,
            services=services,
            bot=None,
            dispatcher=dispatcher,
        )
        self._delivery_runtime = delivery_runtime
        self._control_access = _RegistryControlAccess(
            config=config,
            registries=config.agent_registries,
            runtimes_by_id=self._registry_runtimes,
        )
        self._processor_runner = ProcessorRunner(bus)
        self._processor_runner.register(RegistryControlProcessor(self._control_access))
        self._processor_task: asyncio.Task[None] | None = None

    @property
    def transport_id(self) -> str:
        return "registry-delivery"

    @property
    def descriptor(self) -> TransportDescriptor:
        return TransportDescriptor(
            transport_type="registry",
            display_name="Registry delivery",
            supports_multiple=True,
            inbound_model="delivery",
            trust_tier="trusted",
            report_in_agent_status=False,
            accepts_transport_input=True,
            supports_conversation_binding=False,
            supports_timeline=False,
            supports_editing=False,
            supports_inline_actions=False,
            supports_recovery=False,
        )

    def ref_prefix(self) -> str:
        return "registry-delivery:"

    def can_build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> bool:
        del conversation_ref, config, kw
        return False

    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        del conversation_ref, config, kw
        raise RuntimeError("Registry delivery transport does not build egress directly")

    def _advertised_routing_skills(self) -> tuple[str, ...]:
        catalog = self._services.workflows.runtime_skills.catalog
        return tuple(
            item.name
            for item in catalog.list_skills()
            if item.can_activate and item.runtime_available
        )

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        self._delivery_runtime = replace(self._delivery_runtime, submitter=runtime)
        self._stop_requested.clear()
        self._registry_runtimes = {}
        self._runtime_tasks = {}
        self._control_access.runtimes_by_id.clear()
        self._parent_stop_task = asyncio.create_task(self._watch_parent_stop(stop_event))
        for registry in self._config.agent_registries:
            runtime = AgentRuntime(
                self._config,
                delivery_handler=self._annotated_delivery_handler(registry.registry_id),
                runtime_health_provider=CanonicalRuntimeHealthProvider(),
                provider=self._provider,
                registry=registry,
                routing_skills_resolver=self._advertised_routing_skills,
                transport_implementations_resolver=self._dispatcher.reported_transport_implementations,
                supported_admin_operations_resolver=lambda: self._services.workflows.supported_admin_operations,
            )
            self._registry_runtimes[registry.registry_id] = runtime
            self._runtime_tasks[registry.registry_id] = asyncio.create_task(
                runtime.run_forever(
                    self._stop_requested,
                    kind_filter=self._kind_filter_for_scope(registry.registry_scope),
                )
            )
        await asyncio.sleep(0)
        startup_errors = [
            task.exception()
            for task in self._runtime_tasks.values()
            if task.done() and task.exception() is not None
        ]
        if startup_errors:
            try:
                await self.stop()
            finally:
                raise startup_errors[0]
        await self._bus.reconcile_orphans(allowed_admin_targets=self._directory.all_pairs())
        self._processor_task = asyncio.create_task(
            self._processor_runner.run(stop_event=stop_event)
        )
        external_wait = asyncio.create_task(stop_event.wait())
        local_wait = asyncio.create_task(self._stop_requested.wait())
        try:
            await asyncio.wait(
                {external_wait, local_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            external_wait.cancel()
            local_wait.cancel()
            await asyncio.gather(external_wait, local_wait, return_exceptions=True)
            await self.stop()

    async def stop(self) -> None:
        self._stop_requested.set()
        if self._parent_stop_task is not None:
            self._parent_stop_task.cancel()
            await asyncio.gather(self._parent_stop_task, return_exceptions=True)
            self._parent_stop_task = None
        await self._processor_runner.stop()
        if self._processor_task is not None:
            try:
                await asyncio.wait_for(self._processor_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._processor_task.cancel()
            finally:
                self._processor_task = None
        task_failures: list[BaseException] = []
        if self._runtime_tasks:
            results = await asyncio.gather(*self._runtime_tasks.values(), return_exceptions=True)
            task_failures = [
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ]
        self._runtime_tasks = {}
        self._registry_runtimes.clear()
        self._control_access.runtimes_by_id.clear()
        if task_failures:
            raise task_failures[0]

    async def health_check(self) -> TransportHealthRecord:
        return TransportHealthRecord(
            transport_id=self.transport_id,
            transport_type=self.descriptor.transport_type,
            inbound_model=self.descriptor.inbound_model,
            registry_ids=tuple(registry.registry_id for registry in self._config.agent_registries),
            ok=any(
                registry.registry_scope in {"coordination", "full"}
                for registry in self._config.agent_registries
            ),
        )

    async def _watch_parent_stop(self, stop_event: asyncio.Event) -> None:
        await stop_event.wait()
        self._stop_requested.set()

    def _annotated_delivery_handler(self, registry_id: str):
        async def _wrapped(delivery: dict[str, object]) -> str:
            annotated = dict(delivery)
            annotated["registry_id"] = registry_id
            return await handle_registry_delivery(
                self._config,
                annotated,
                runtime=self._delivery_runtime,
            )

        return _wrapped

    @staticmethod
    def _kind_filter_for_scope(registry_scope: str):
        if registry_scope == "channel":
            return ("channel_input", "channel_action", "management_request")
        if registry_scope == "coordination":
            return ("routed_task", "routed_result")
        return None


def build_registry_delivery_transport(
    config: BotConfig,
    provider: Provider,
    *,
    services: BotServices,
    dispatcher: TransportDispatcher,
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
) -> RegistryDeliveryTransport:
    return RegistryDeliveryTransport(
        config,
        provider,
        services=services,
        dispatcher=dispatcher,
        bus=bus,
        directory=directory,
    )
