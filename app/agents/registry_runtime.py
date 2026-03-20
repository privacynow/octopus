"""Per-connection registry runtime ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any

from app.agents.client import AgentRegistryClient
from app.agents.runtime import AgentRuntime
from app.agents.state import load_runtime_registry_connection_state
from app.agents.types import RegistryConnectionConfig
from app.config import BotConfig
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime_health import RuntimeHealthProjector, RuntimeHealthProvider


class RegistryRuntime:
    """Own configured registry connections and their sync loops."""

    def __init__(
        self,
        registries: tuple[RegistryConnectionConfig, ...],
        dispatcher: ChannelDispatcher,
        delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None,
        *,
        config: BotConfig,
        runtime_health_provider: RuntimeHealthProvider | None = None,
        runtime_health_projector: RuntimeHealthProjector[dict[str, Any]] | None = None,
        provider=None,
    ) -> None:
        self._registries = registries
        self._dispatcher = dispatcher
        self._delivery_handler = delivery_handler
        self._config = config
        self._runtime_health_provider = runtime_health_provider
        self._runtime_health_projector = runtime_health_projector
        self._provider = provider
        self._stop_requested = asyncio.Event()
        self._parent_stop_task: asyncio.Task[None] | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._runtimes: dict[str, AgentRuntime] = {}
        self._registry_by_id = {registry.registry_id: registry for registry in registries}
        self._channels_registered = False

    async def start(self, *, stop_event: asyncio.Event) -> None:
        if self._tasks:
            return

        self._stop_requested.clear()
        self._runtimes = {}
        self._tasks = {}
        self._parent_stop_task = asyncio.create_task(self._watch_parent_stop(stop_event))

        for registry in self._registries:
            runtime = AgentRuntime(
                self._connection_config(registry),
                delivery_handler=self._annotated_delivery_handler(registry.registry_id),
                runtime_health_provider=self._runtime_health_provider,
                runtime_health_projector=self._runtime_health_projector,
                provider=self._provider,
                registry=registry,
                channel_capabilities_resolver=self.channel_capabilities,
            )
            self._runtimes[registry.registry_id] = runtime
            self._tasks[registry.registry_id] = asyncio.create_task(
                runtime.run_forever(
                    self._stop_requested,
                    kind_filter=self._kind_filter_for_scope(registry.registry_scope),
                )
            )

        await asyncio.sleep(0)
        startup_errors = [
            task.exception()
            for task in self._tasks.values()
            if task.done() and task.exception() is not None
        ]
        if startup_errors:
            try:
                await self.stop()
            finally:
                raise startup_errors[0]

    async def stop(self) -> None:
        self._stop_requested.set()
        if self._parent_stop_task is not None:
            self._parent_stop_task.cancel()
            await asyncio.gather(self._parent_stop_task, return_exceptions=True)
            self._parent_stop_task = None

        task_failures: list[BaseException] = []
        if self._tasks:
            results = await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            task_failures = [
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ]
        self._tasks = {}
        self._runtimes = {}
        if task_failures:
            raise task_failures[0]

    def clients_for_mirroring(self) -> list[tuple[str, AgentRegistryClient]]:
        clients: list[tuple[str, AgentRegistryClient]] = []
        for registry in self._registries:
            if registry.registry_scope not in {"channel", "full"}:
                continue
            client = self._client_for_registry(registry.registry_id)
            if client is None:
                continue
            clients.append((registry.registry_id, client))
        return clients

    def channel_capabilities(self) -> tuple[str, ...]:
        return tuple(self._dispatcher.active_channel_types())

    def runtime_for_registry(self, registry_id: str) -> AgentRuntime | None:
        return self._runtimes.get(registry_id)

    def register_channels(self) -> None:
        if self._channels_registered:
            return

        from app.channels.registry.channel import RegistryConversationChannel, RegistryTaskChannel

        for registry in self._registries:
            if registry.registry_scope in {"channel", "full"}:
                self._dispatcher.register(
                    RegistryConversationChannel(
                        self._config,
                        registry,
                        registry_client_factory=lambda registry_id=registry.registry_id: self._client_for_registry(
                            registry_id
                        ),
                    )
                )
            if registry.registry_scope in {"coordination", "full"}:
                self._dispatcher.register(
                    RegistryTaskChannel(
                        self._config,
                        registry,
                        registry_client_factory=lambda registry_id=registry.registry_id: self._client_for_registry(
                            registry_id
                        ),
                    )
                )

        self._channels_registered = True

    def _connection_config(self, registry: RegistryConnectionConfig) -> BotConfig:
        return replace(
            self._config,
            agent_registries=(registry,),
            agent_registry_url=registry.url,
            agent_registry_enroll_token=registry.enroll_token,
            agent_poll_interval_seconds=registry.poll_interval_seconds,
        )

    def _annotated_delivery_handler(
        self,
        registry_id: str,
    ) -> Callable[[dict[str, object]], Awaitable[str]] | None:
        if self._delivery_handler is None:
            return None

        async def _wrapped(delivery: dict[str, object]) -> str:
            annotated = dict(delivery)
            annotated["registry_id"] = registry_id
            return await self._delivery_handler(annotated)

        return _wrapped

    async def _watch_parent_stop(self, stop_event: asyncio.Event) -> None:
        await stop_event.wait()
        self._stop_requested.set()

    def _kind_filter_for_scope(self, registry_scope: str) -> Sequence[str] | None:
        if registry_scope == "channel":
            return ("channel_input", "channel_action")
        if registry_scope == "coordination":
            return ("routed_task", "routed_result")
        return None

    def _client_for_registry(self, registry_id: str) -> AgentRegistryClient | None:
        registry = self._registry_by_id.get(registry_id)
        if registry is None:
            return None

        runtime = self._runtimes.get(registry_id)
        agent_token = ""
        if runtime is not None:
            agent_token = runtime.state.agent_token
        if not agent_token:
            state = load_runtime_registry_connection_state(
                self._config.data_dir,
                registry_id,
                registry_scope=registry.registry_scope,
            )
            agent_token = state.agent_token
        if not agent_token:
            return None
        return AgentRegistryClient(registry.url, agent_token=agent_token)
