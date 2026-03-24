"""Per-connection registry runtime ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.registry_capabilities import registry_authority_ref
from app.agents.runtime import AgentRuntime
from app.agents.state import load_runtime_registry_connection_state
from app.agents.types import AgentDiscoveryQuery, DiscoveredAgentRef, RegistryConnectionConfig
from app.config import BotConfig
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime_health import RuntimeHealthProjector, RuntimeHealthProvider


@dataclass(frozen=True)
class _ConnectedRegistry:
    registry: RegistryConnectionConfig
    client: AgentRegistryClient
    local_agent_id: str


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

    @property
    def registries(self) -> tuple[RegistryConnectionConfig, ...]:
        return self._registries

    async def start(self, *, stop_event: asyncio.Event) -> None:
        if self._tasks:
            return

        self._stop_requested.clear()
        self._runtimes = {}
        self._tasks = {}
        self._parent_stop_task = asyncio.create_task(self._watch_parent_stop(stop_event))

        for registry in self._registries:
            runtime = AgentRuntime(
                self._config,
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

    def channel_capabilities(self) -> tuple[str, ...]:
        return tuple(self._dispatcher.active_channel_types())

    def client_for_registry(self, registry_id: str) -> AgentRegistryClient | None:
        return self._client_for_registry(registry_id)

    def origin_agent_id(self, registry_id: str) -> str:
        return self._state_for_registry(registry_id).agent_id

    def has_coordination_connections(self) -> bool:
        return any(
            registry.registry_scope in {"coordination", "full"}
            for registry in self._registries
        )

    def has_connected_coordination_connection(self) -> bool:
        return bool(self._connected_registries(scopes={"coordination", "full"}))

    def has_enrolled_coordination_connection(self) -> bool:
        for registry in self._registries:
            if registry.registry_scope not in {"coordination", "full"}:
                continue
            state = self._state_for_registry(registry.registry_id)
            if state.agent_token or state.agent_id:
                return True
        return False

    def first_coordination_error(self) -> str:
        for registry in self._registries:
            if registry.registry_scope not in {"coordination", "full"}:
                continue
            state = self._state_for_registry(registry.registry_id)
            if state.last_error:
                return state.last_error
        return ""

    async def discover(self, query: AgentDiscoveryQuery) -> list[DiscoveredAgentRef]:
        discovered: list[DiscoveredAgentRef] = []
        first_error: RegistryClientError | None = None
        successful_search = False
        for connection in self._connected_registries(scopes={"coordination", "full"}):
            scoped_query = query
            if connection.local_agent_id:
                excludes = tuple(
                    dict.fromkeys(
                        (*query.exclude_agent_ids, connection.local_agent_id)
                    )
                )
                scoped_query = replace(query, exclude_agent_ids=excludes)
            try:
                rows = await connection.client.search(scoped_query)
            except RegistryClientError as exc:
                if first_error is None:
                    first_error = exc
                continue
            successful_search = True
            discovered.extend(
                DiscoveredAgentRef(
                    authority_ref=registry_authority_ref(connection.registry.registry_id),
                    agent_id=str(row.get("agent_id", "")),
                    display_name=str(row.get("display_name", "")),
                    slug=str(row.get("slug", "")),
                    role=str(row.get("role", "")),
                    capabilities=tuple(str(item) for item in row.get("capabilities", []) if item),
                    tags=tuple(str(item) for item in row.get("tags", []) if item),
                    description=str(row.get("description", "")),
                    connectivity_state=str(row.get("connectivity_state", "")),
                    current_capacity=int(row.get("current_capacity", 0) or 0),
                    max_capacity=int(row.get("max_capacity", 1) or 1),
                )
                for row in rows
            )
        if first_error is not None and not successful_search:
            raise first_error
        return sorted(
            discovered,
            key=lambda agent: (
                (agent.display_name or agent.slug or agent.agent_id).lower(),
                agent.authority_ref,
                agent.agent_id,
            ),
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

    def _state_for_registry(self, registry_id: str):
        registry = self._registry_by_id.get(registry_id)
        if registry is None:
            return load_runtime_registry_connection_state(
                self._config.data_dir,
                registry_id,
            )
        runtime = self._runtimes.get(registry_id)
        if runtime is not None:
            return runtime.state
        return load_runtime_registry_connection_state(
            self._config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope,
        )

    def _connected_registries(self, *, scopes: set[str]) -> list[_ConnectedRegistry]:
        connected: list[_ConnectedRegistry] = []
        for registry in self._registries:
            if registry.registry_scope not in scopes:
                continue
            state = self._state_for_registry(registry.registry_id)
            if state.connectivity_state != "connected":
                continue
            client = self._client_for_registry(registry.registry_id)
            if client is None:
                continue
            connected.append(
                _ConnectedRegistry(
                    registry=registry,
                    client=client,
                    local_agent_id=state.agent_id,
                )
            )
        return connected

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
