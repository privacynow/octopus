"""Registry delivery transport lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.agents.client import AgentRegistryClient
from app.agents.delivery import build_registry_delivery_runtime, handle_registry_delivery
from app.agents.runtime import AgentRuntime
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.state import load_runtime_registry_connection_state
from app.config import BotConfig
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.processor_runner import ProcessorRunner
from app.runtime.transport_dispatcher import TransportDispatcher
from app.runtime.services import BotServices
from app.runtime_health import CanonicalRuntimeHealthProvider
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.providers import Provider
from octopus_sdk.transport import TransportDescriptor, TransportEgress, TransportImplementation


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

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        del conversation_ref, config, kw
        return False

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> TransportEgress:
        del conversation_ref, config, kw
        raise RuntimeError("Registry delivery transport does not build egress directly")

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        self._delivery_runtime.submitter = runtime
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

    async def health_check(self) -> dict[str, Any]:
        return {
            "transport_id": self.transport_id,
            "transport_type": self.descriptor.transport_type,
            "inbound_model": self.descriptor.inbound_model,
            "registry_ids": [registry.registry_id for registry in self._config.agent_registries],
            "has_coordination_connection": any(
                registry.registry_scope in {"coordination", "full"}
                for registry in self._config.agent_registries
            ),
        }

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
            return ("channel_input", "channel_action")
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
