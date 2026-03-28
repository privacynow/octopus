"""Registry delivery transport lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from app.agents.client import AgentRegistryClient
from app.agents.registry_capabilities import registry_authority_ref
from app.agents.state import runtime_registry_agent_id
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.state import load_runtime_registry_connection_state
from app.channels.registry.refs import (
    binding_external_id_for_ref,
    qualify_registry_conversation_ref,
    registry_task_ref,
)
from app.config import BotConfig
from app.runtime.session_runtime import (
    apply_runtime_delegation_result,
    load_runtime_session,
    save_runtime_session,
)
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.processor_runner import ProcessorRunner
from octopus_sdk.transport_dispatcher import TransportDispatcher
from app.runtime.services import BotServices
from app.runtime_health import CanonicalRuntimeHealthProvider
from app.runtime.registry_participant import AgentRuntime
from app.skill_activation_service import get_skill_activation_service
from app import work_queue
from octopus_sdk.config import BotConfigBase
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.identity import (
    conversation_key_for_ref,
    delegation_session_key,
    resolve_delegation_parent_identity,
    telegram_chat_id_from_ref,
)
from octopus_sdk.inbound_types import (
    InboundAction,
    InboundEnvelope,
    InboundMessage,
    InboundUser,
    serialize_inbound,
)
from octopus_sdk.providers import Provider
from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.registry.management import ManagementRequest
from octopus_sdk.registry.management_executor import (
    ManagementExecutionContext,
    execute_management_request,
)
from octopus_sdk.transport import (
    BotRuntimeHandle,
    TransportBindingRecord,
    TransportDescriptor,
    TransportEgress,
    TransportHealthRecord,
    TransportImplementation,
)
from octopus_sdk.workflows.delegation import send_delegation_completion_message


@dataclass(frozen=True)
class _RegistryControlAccess:
    config: BotConfig
    registries: tuple[RegistryConnectionConfig, ...]
    runtimes_by_id: dict[str, AgentRuntime]

    def client_for_registry(self, registry_id: str) -> AgentRegistryClient | None:
        registry = next((item for item in self.registries if item.registry_id == registry_id), None)
        if registry is None:
            return None
        runtime = self.runtimes_by_id.get(registry_id)
        if runtime is not None and runtime.state.agent_token:
            return AgentRegistryClient(registry.url, agent_token=runtime.state.agent_token)
        state = load_runtime_registry_connection_state(
            self.config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )
        if not state.agent_token:
            return None
        return AgentRegistryClient(registry.url, agent_token=state.agent_token)

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
    provider_state_factory: Callable[[str], dict[str, Any]]
    services: BotServices
    submitter: BotRuntimeHandle | None = None
    bot: Any | None = None
    dispatcher: TransportDispatcher | None = None


def build_registry_delivery_runtime(
    *,
    provider_name: str,
    provider_state_factory: Callable[[str], dict[str, Any]],
    services: BotServices,
    submitter: BotRuntimeHandle | None = None,
    bot: Any | None = None,
    dispatcher: TransportDispatcher | None = None,
) -> RegistryDeliveryRuntime:
    return RegistryDeliveryRuntime(
        provider_name=provider_name,
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
    actor_ref: str,
    delivery_id: str,
    external_conversation_ref: str = "",
    routed_task_id: str = "",
    registry_id: str,
    skip_approval: bool = False,
    conversation_key_override: str = "",
    authorized_actor_key: str = "",
    source_transport: str = "registry",
) -> tuple[str, str, str, str]:
    envelope = build_registry_message_envelope(
        conversation_ref=conversation_ref,
        text=text,
        actor_ref=actor_ref,
        delivery_id=delivery_id,
        external_conversation_ref=external_conversation_ref,
        routed_task_id=routed_task_id,
        registry_id=registry_id,
        skip_approval=skip_approval,
        conversation_key_override=conversation_key_override,
        authorized_actor_key=authorized_actor_key,
        source_transport=source_transport,
    )
    payload = serialize_inbound(envelope.event)
    return envelope.conversation_key, envelope.actor_key, envelope.event_id, payload


def build_registry_message_envelope(
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
    authorized_actor_key: str = "",
    source_transport: str = "registry",
) -> InboundEnvelope:
    if not registry_id:
        raise ValueError("Registry message delivery requires an explicit registry_id")
    source_transport = str(source_transport or "registry").strip() or "registry"
    conversation_key = conversation_key_override or conversation_key_for_ref(conversation_ref)
    actor_key = f"reg:{actor_ref}"
    event_id = f"reg:{delivery_id}"
    event = InboundMessage(
        user=InboundUser(id=actor_key, username="registry"),
        conversation_key=conversation_key,
        text=text,
        attachments=(),
        source=source_transport,
        transport=source_transport,
        conversation_ref=conversation_ref,
        external_conversation_ref=external_conversation_ref,
        routed_task_id=routed_task_id,
        authorized_actor_key=authorized_actor_key,
        authority_ref=registry_authority_ref(registry_id),
        skip_approval=skip_approval,
    )
    return InboundEnvelope(
        transport=source_transport,
        event_id=event_id,
        conversation_key=conversation_key,
        actor_key=actor_key,
        received_at=datetime.now(timezone.utc),
        event=event,
        conversation_ref=conversation_ref,
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


def _routed_task_text(request: dict[str, Any]) -> str:
    title = str(request.get("title", "")).strip()
    instructions = str(request.get("instructions", "")).strip()
    if title and instructions and title != instructions:
        return f"{title}\n\n{instructions}".strip()
    return instructions or title


async def admit_registry_delivery(
    config: BotConfig,
    delivery: dict[str, Any],
    *,
    submitter: BotRuntimeHandle,
    dispatcher: TransportDispatcher | None = None,
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
        # Registry UI input originates from the registry surface, so these remain
        # registry envelopes even when the conversation later mirrors elsewhere.
        envelope = build_registry_message_envelope(
            conversation_ref=conversation_ref,
            text=payload.get("text", ""),
            actor_ref=f"registry-ui:{conversation_ref}",
            delivery_id=effective_delivery_id,
            external_conversation_ref=str(payload.get("external_conversation_ref", "") or ""),
            registry_id=registry_id,
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
        context_lines = []
        if request.get("context"):
            context_lines.append(f"Context: {request['context']}")
        if request.get("constraints"):
            context_lines.append(f"Constraints: {request['constraints']}")
        if request.get("requested_capabilities"):
            context_lines.append(
                "Requested capabilities: " + ", ".join(request.get("requested_capabilities", []))
            )
        text = _routed_task_text(request)
        if context_lines:
            text = text + "\n\n" + "\n".join(context_lines)
        conversation_ref = registry_task_ref(registry_id, request["routed_task_id"])
        origin_agent_id = request.get("origin_agent_id", "")
        parent_conversation_id = request.get("parent_conversation_id", "")
        if origin_agent_id and parent_conversation_id:
            shared_key = delegation_session_key(origin_agent_id, parent_conversation_id)
        else:
            shared_key = ""
        # Routed task deliveries originate from the registry and intentionally
        # enter the worker through the registry transport.
        envelope = build_registry_message_envelope(
            conversation_ref=conversation_ref,
            conversation_key_override=shared_key,
            text=text,
            actor_ref=f"agent:{request.get('origin_agent_id', '')}",
            delivery_id=delivery_id,
            external_conversation_ref=str(request.get("external_conversation_ref", "") or ""),
            routed_task_id=request["routed_task_id"],
            authorized_actor_key=str(request.get("authorized_actor_key", "") or ""),
            registry_id=registry_id,
        )
        await submitter.admit_message(envelope)
        return "accepted"

    return "rejected"


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


def _save_session(config: BotConfig, conversation_key: str, session) -> None:
    save_runtime_session(config.data_dir, conversation_key, session)


def _registry_semantic_action(
    *,
    conversation_ref: str,
    action: str,
    payload: dict[str, object],
    delivery_id: str,
    registry_id: str,
    external_conversation_ref: str = "",
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
        external_conversation_ref=external_conversation_ref,
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
    submitter = runtime.submitter
    if submitter is None:
        raise RuntimeError("Registry delivery runtime is missing a bot runtime submitter")
    if kind in {"channel_input", "routed_task"}:
        return await admit_registry_delivery(
            config,
            delivery,
            submitter=submitter,
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
        stable_event_id = str(payload.get("stable_event_id", "") or "")
        effective_delivery_id = stable_event_id if stable_event_id else delivery_id
        envelope = _registry_semantic_action(
            conversation_ref=conversation_ref,
            action=action,
            payload=action_payload,
            delivery_id=effective_delivery_id,
            registry_id=registry_id,
            external_conversation_ref=str(payload.get("external_conversation_ref", "") or ""),
        )
        if envelope is None:
            return "rejected"
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
        if runtime.dispatcher is None:
            raise RuntimeError("Registry delivery runtime requires a channel dispatcher")
        if not runtime.dispatcher.egress_ready_for_ref(
            parent_target_ref,
            config=config,
            bot=runtime.bot,
            conversation_key=parent_conversation_key,
            source=_transport_for_conversation_ref(parent_target_ref),
        ):
            return "retry_later"
        applied = apply_runtime_delegation_result(
            config.data_dir,
            parent_conversation_key,
            routed_task_id=routed_task_id,
            authority_ref=registry_authority_ref(registry_id),
            result=routed_result,
        )
        if not applied.matched:
            import logging

            logging.getLogger(__name__).warning(
                "Routed result for task %s authority %s did not match any pending delegation task",
                routed_task_id,
                registry_authority_ref(registry_id),
            )
            return "accepted"
        if not applied.ready_to_resume or applied.pending is None:
            return "accepted"
        continuation_text = applied.resume_prompt
        resume_delivery_id = (
            f"delegation-resume:{parent_target_ref}:{int(applied.pending.created_at * 1000)}"
        )
        resume_transport = _transport_for_conversation_ref(parent_target_ref)
        envelope = build_registry_message_envelope(
            conversation_ref=parent_target_ref,
            text=continuation_text,
            actor_ref=f"delegation-resume:{routed_task_id}",
            delivery_id=resume_delivery_id,
            external_conversation_ref=parent_external_conversation_ref or parent_target_ref,
            registry_id=registry_id,
            skip_approval=True,
            conversation_key_override=parent_conversation_key,
            source_transport=resume_transport,
        )
        submission = await submitter.admit_message(envelope)
        admit_status = submission.status
        if admit_status == "admitted":
            if runtime.dispatcher is None:
                raise RuntimeError("Registry delivery runtime requires a channel dispatcher")
            channel_egress = runtime.dispatcher.create_egress(
                parent_target_ref,
                config=config,
                bot=runtime.bot,
                conversation_key=parent_conversation_key,
                source=resume_transport,
                external_id=parent_external_conversation_ref or parent_target_ref,
                chat_id=telegram_chat_id_from_ref(parent_target_ref),
            )
            if not parent_target_ref.startswith("registry:"):
                try:
                    await send_delegation_completion_message(applied.pending, channel_egress.send_text)
                except Exception:
                    pass
            from octopus_sdk.event_sink import build_event_sink_for_context
            from octopus_sdk.execution import TransportIdentity

            transport = TransportIdentity(
                conversation_key=parent_conversation_key,
                origin_channel="registry",
                actor="registry:delegation-resume",
                external_conversation_ref=(
                    parent_external_conversation_ref or parent_target_ref
                ),
                target_agent_id=runtime_registry_agent_id(config.data_dir, registry_id),
                conversation_ref="",
                routed_task_id="",
                authority_ref="",
            )
            sink = build_event_sink_for_context(
                transport,
                runtime.services.control_plane.conversation_projection,
                config,
            )
            tasks_summary = [
                {"title": t.title, "target": t.target_agent_id, "status": t.status}
                for t in (applied.pending.tasks or [])
            ]
            await sink.on_delegation_completed(
                tasks_summary,
                proposal_id=(applied.pending.proposal_id or f"delegation:{parent_conversation_key}"),
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
        result = await execute_management_request(
            request,
            context=ManagementExecutionContext(
                config=config,
                workflows=runtime.services.workflows,
                provider_state_factory=runtime.provider_state_factory,
            ),
        )
        client = AgentRegistryClient(registry.url, agent_token=state.agent_token)
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
            contributes_transport_capability=False,
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
                channel_capabilities_resolver=self._dispatcher.active_transport_types,
                management_capabilities_resolver=lambda: self._services.workflows.management_capabilities,
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
        await self._bus.reconcile_orphans(allowed_pairs=self._directory.all_pairs())
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
