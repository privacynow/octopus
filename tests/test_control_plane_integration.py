from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from app import runtime_backend
from app.agents.bridge import telegram_conversation_ref
from app.agents.client import RegistryClientError
from app.agents.delivery import build_registry_delivery_runtime, handle_registry_delivery
from app.agents.registry_capabilities import (
    registry_authority_capabilities,
    registry_authority_ref,
)
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.registry_runtime import RegistryRuntime
from app.agents.state import save_registry_connection_state
from app.agents.types import (
    RegistryConnectionConfig,
    RegistryConnectionState,
    RoutedTaskResult,
    RoutedTaskUpdate,
    TimelineEvent,
    to_wire,
)
from app.channels.telegram.channel import TelegramChannelBootstrap
from app.channels.telegram.progress import progress_timeline_callback
from app.channels.telegram.state import build_telegram_runtime
import app.channels.telegram.worker as telegram_worker
from app.config import BotConfig
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.control_plane.processor_runner import ProcessorRunner
from app.identity import telegram_conversation_key
from app.ports.health_publication import HealthReport
from app.ports.task_routing import TaskResultReport
from app.registry_service.store import RegistrySQLiteStore
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import BotServices, build_bus_bot_services
from app.storage import ensure_data_dirs
from app.workflows.execution.contracts import RequestExecutionOutcome
from app.workflows.execution.finalization import FinalizationContext, finalize_execution
from tests.support.config_support import make_config, make_registry_connection
from tests.support.handler_support import FakeProvider, MinimalFakeBot


@dataclass(frozen=True)
class _SeededRegistry:
    registry: RegistryConnectionConfig
    store: RegistrySQLiteStore
    local_agent_id: str
    local_agent_token: str
    origin_agent_id: str = ""
    origin_agent_token: str = ""


class _StoreBackedRegistryClient:
    stores_by_url: dict[str, RegistrySQLiteStore] = {}
    failing_ops_by_url: dict[str, set[str]] = {}

    def __init__(
        self,
        base_url: str,
        *,
        agent_token: str = "",
        timeout_seconds: float = 10.0,
        client=None,
    ) -> None:
        del timeout_seconds, client
        self.base_url = base_url.rstrip("/")
        self.agent_token = agent_token

    def _store(self) -> RegistrySQLiteStore:
        return type(self).stores_by_url[self.base_url]

    def _maybe_fail(self, operation: str) -> None:
        if operation in type(self).failing_ops_by_url.get(self.base_url, set()):
            raise RegistryClientError(
                f"{operation} failed",
                error_code="registry_unreachable",
                operator_detail=f"{self.base_url}:{operation} failed",
            )

    async def sync_binding(
        self,
        *,
        conversation_id: str,
        title: str,
        origin_channel: str,
        external_id: str,
    ) -> dict[str, object]:
        self._maybe_fail("sync_binding")
        return self._store().bind_conversation(
            self.agent_token,
            {
                "conversation_id": conversation_id,
                "title": title,
                "origin_channel": origin_channel,
                "external_id": external_id,
            },
        )

    async def publish_timeline(self, events: list[TimelineEvent], *, checkpoint: str = "") -> dict[str, object]:
        del checkpoint
        self._maybe_fail("publish_timeline")
        return self._store().publish_timeline(
            self.agent_token,
            [to_wire(event) for event in events],
        )

    async def submit_routed_task(self, request) -> dict[str, object]:
        self._maybe_fail("submit_routed_task")
        store = self._store()
        store.assert_agent_scope(self.agent_token, {"coordination", "full"})
        store.heartbeat(self.agent_token, {"connectivity_state": "connected"})
        return store.create_routed_task(to_wire(request))

    async def routed_task_status(self, routed_task_id: str, update) -> dict[str, object]:
        self._maybe_fail("routed_task_status")
        return self._store().update_routed_task_status(
            self.agent_token,
            routed_task_id,
            to_wire(update),
        )

    async def routed_task_result(self, routed_task_id: str, result) -> dict[str, object]:
        self._maybe_fail("routed_task_result")
        return self._store().update_routed_task_result(
            self.agent_token,
            routed_task_id,
            to_wire(result),
        )

    async def heartbeat(
        self,
        *,
        connectivity_state: str,
        current_capacity: int,
        max_capacity: int,
        active_work_count: int = 0,
        timeline_checkpoint: str = "",
        runtime_health: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del active_work_count, timeline_checkpoint
        self._maybe_fail("heartbeat")
        return self._store().heartbeat(
            self.agent_token,
            {
                "connectivity_state": connectivity_state,
                "current_capacity": current_capacity,
                "max_capacity": max_capacity,
                "runtime_health": runtime_health or {},
            },
        )


def _agent_card(*, name: str, slug: str, registry_scope: str) -> dict[str, object]:
    return {
        "display_name": name,
        "slug": slug,
        "role": "assistant",
        "registry_scope": registry_scope,
        "capabilities": [],
        "tags": [],
        "description": "",
        "provider": "claude",
        "mode": "registry",
        "channel_capabilities": ["telegram"],
        "version": "test",
    }


def _register_agent(
    store: RegistrySQLiteStore,
    *,
    name: str,
    slug: str,
    registry_scope: str,
) -> tuple[str, str]:
    card = _agent_card(name=name, slug=slug, registry_scope=registry_scope)
    enrolled = store.enroll(card)
    store.register(
        enrolled["agent_token"],
        {
            "agent_card": card,
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )
    return str(enrolled["agent_id"]), str(enrolled["agent_token"])


def _seed_registry(
    *,
    data_dir: Path,
    registry: RegistryConnectionConfig,
    stores_dir: Path,
    with_origin_agent: bool = False,
) -> _SeededRegistry:
    store = RegistrySQLiteStore(stores_dir / f"{registry.registry_id}.sqlite3")
    local_agent_id, local_agent_token = _register_agent(
        store,
        name=f"{registry.registry_id}-local",
        slug=f"{registry.registry_id}-local",
        registry_scope=registry.registry_scope,
    )
    origin_agent_id = ""
    origin_agent_token = ""
    if with_origin_agent:
        origin_agent_id, origin_agent_token = _register_agent(
            store,
            name=f"{registry.registry_id}-origin",
            slug=f"{registry.registry_id}-origin",
            registry_scope="full",
        )
    save_registry_connection_state(
        data_dir,
        RegistryConnectionState(
            registry_id=registry.registry_id,
            registry_scope=registry.registry_scope,
            agent_id=local_agent_id,
            agent_token=local_agent_token,
            connectivity_state="connected",
        ),
    )
    return _SeededRegistry(
        registry=registry,
        store=store,
        local_agent_id=local_agent_id,
        local_agent_token=local_agent_token,
        origin_agent_id=origin_agent_id,
        origin_agent_token=origin_agent_token,
    )


def _init_backend(config: BotConfig) -> None:
    runtime_backend.reset_for_test()
    ensure_data_dirs(config.data_dir)
    runtime_backend.init(config)


def _services_for_config(config: BotConfig) -> BotServices:
    directory = build_control_plane_directory(
        registry_authority_capabilities(config.agent_registries)
    )
    return build_bus_bot_services(ControlPlaneBus(config.data_dir), directory)


@asynccontextmanager
async def _running_registry_processor(config: BotConfig):
    runner = ProcessorRunner(
        ControlPlaneBus(config.data_dir),
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
    )
    runner.register(
        RegistryControlProcessor(
            RegistryRuntime(config.agent_registries, ChannelDispatcher(), None, config=config)
        )
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    try:
        yield runner
    finally:
        stop_event.set()
        await task


async def _wait_for(predicate, *, timeout: float = 2.0, message: str = "condition not met") -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            if predicate():
                return
        except Exception:
            pass
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(message)
        await asyncio.sleep(0.01)


def _command_count(bus: ControlPlaneBus) -> int:
    conn = bus.debug_connection()
    row = conn.execute("SELECT COUNT(*) FROM control_plane_commands").fetchone()
    return int(row[0] if row is not None else 0)


def _timeline_kinds(store: RegistrySQLiteStore, conversation_ref: str) -> list[str]:
    return [event["kind"] for event in store.get_conversation_timeline(conversation_ref)]


def _install_store_backed_clients(
    monkeypatch: pytest.MonkeyPatch,
    seeded_registries: list[_SeededRegistry],
    *,
    failing_ops_by_url: dict[str, set[str]] | None = None,
) -> None:
    _StoreBackedRegistryClient.stores_by_url = {
        seeded.registry.url.rstrip("/"): seeded.store
        for seeded in seeded_registries
    }
    _StoreBackedRegistryClient.failing_ops_by_url = {
        url.rstrip("/"): set(ops)
        for url, ops in (failing_ops_by_url or {}).items()
    }
    monkeypatch.setattr(
        "app.agents.registry_runtime.AgentRegistryClient",
        _StoreBackedRegistryClient,
    )


def _build_telegram_runtime_with_dispatcher(
    config: BotConfig,
    *,
    services: BotServices,
):
    provider = FakeProvider()
    bot = MinimalFakeBot()
    runtime = build_telegram_runtime(
        config,
        provider,
        bot_instance=bot,
        services=services,
    )
    dispatcher = ChannelDispatcher()
    dispatcher.register(TelegramChannelBootstrap(config, provider, services))
    runtime.channel_dispatcher = dispatcher
    return runtime, dispatcher


@pytest.mark.asyncio
async def test_shared_worker_projects_telegram_events_through_bus_to_multiple_registries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = make_registry_connection(
        registry_id="channel",
        url="http://registry.channel",
        registry_scope="channel",
    )
    full = make_registry_connection(
        registry_id="full",
        url="http://registry.full",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(channel, full),
        runtime_mode="shared",
        process_role="worker",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = [
        _seed_registry(data_dir=tmp_path, registry=channel, stores_dir=stores_dir),
        _seed_registry(data_dir=tmp_path, registry=full, stores_dir=stores_dir),
    ]
    _install_store_backed_clients(monkeypatch, seeded)
    services = _services_for_config(config)
    runtime, dispatcher = _build_telegram_runtime_with_dispatcher(config, services=services)
    conversation_ref = telegram_conversation_ref(config, 12345)
    egress = dispatcher.create_egress(
        conversation_ref,
        config=config,
        bot=runtime.bot_instance,
        conversation_key=telegram_conversation_key(12345),
        source="telegram",
    )

    async with _running_registry_processor(config):
        await egress.bind(title="Ops channel", config=config)
        await _wait_for(
            lambda: all(
                seeded_registry.store.get_conversation(conversation_ref)["conversation_id"]
                == conversation_ref
                for seeded_registry in seeded
            ),
            message="conversation bind did not reach both registries",
        )
        await egress.on_message_received("hello from telegram")
        await progress_timeline_callback(runtime, conversation_ref, "", "working…", force=True)
        await egress.on_outcome(
            RequestExecutionOutcome(status="completed", reply_text="done")
        )
        await telegram_worker._publish_timeline_event_for_runtime(
            runtime,
            config=config,
            conversation_ref=conversation_ref,
            kind="usage",
            title="Usage",
            body="prompt_tokens=1",
        )
        await _wait_for(
            lambda: all(
                {"channel_input", "progress", "result", "usage"}
                <= set(_timeline_kinds(seeded_registry.store, conversation_ref))
                for seeded_registry in seeded
            ),
            message="telegram projection events did not reach all registries",
        )

    for seeded_registry in seeded:
        assert set(_timeline_kinds(seeded_registry.store, conversation_ref)) >= {
            "channel_input",
            "progress",
            "result",
            "usage",
        }


@pytest.mark.asyncio
async def test_shared_worker_registry_delivery_projects_parent_timeline_to_multiple_registries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = make_registry_connection(
        registry_id="channel",
        url="http://registry.channel",
        registry_scope="channel",
    )
    full = make_registry_connection(
        registry_id="full",
        url="http://registry.full",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(channel, full),
        runtime_mode="shared",
        process_role="worker",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = [
        _seed_registry(data_dir=tmp_path, registry=channel, stores_dir=stores_dir),
        _seed_registry(data_dir=tmp_path, registry=full, stores_dir=stores_dir),
    ]
    _install_store_backed_clients(monkeypatch, seeded)
    services = _services_for_config(config)
    _runtime, dispatcher = _build_telegram_runtime_with_dispatcher(config, services=services)
    delivery_runtime = build_registry_delivery_runtime(
        provider_name="claude",
        provider_state_factory=dict,
        services=services,
        bot=None,
        dispatcher=dispatcher,
    )
    parent_conversation_ref = telegram_conversation_ref(config, 456)

    async with _running_registry_processor(config):
        await services.control_plane.conversation_projection.bind_external_conversation(
            conversation_ref=parent_conversation_ref,
            title="Parent conversation",
            origin_channel="telegram",
            external_id="456",
        )
        await _wait_for(
            lambda: all(
                seeded_registry.store.get_conversation(parent_conversation_ref)["conversation_id"]
                == parent_conversation_ref
                for seeded_registry in seeded
            ),
            message="parent conversation bind did not reach both registries",
        )
        outcome = await handle_registry_delivery(
            config,
            {
                "kind": "routed_result",
                "registry_id": "full",
                "payload": {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": parent_conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Delegated summary",
                        "full_text": "Delegated full text",
                    },
                },
            },
            runtime=delivery_runtime,
        )

        await _wait_for(
            lambda: all(
                "delegated_result" in _timeline_kinds(seeded_registry.store, parent_conversation_ref)
                for seeded_registry in seeded
            ),
            message="registry delivery timeline did not reach both registries",
        )

    assert outcome == "retry_later"
    for seeded_registry in seeded:
        assert "delegated_result" in _timeline_kinds(
            seeded_registry.store,
            parent_conversation_ref,
        )


@pytest.mark.asyncio
async def test_shared_worker_projection_survives_one_degraded_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    healthy = make_registry_connection(
        registry_id="healthy",
        url="http://registry.healthy",
        registry_scope="channel",
    )
    degraded = make_registry_connection(
        registry_id="degraded",
        url="http://registry.degraded",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(healthy, degraded),
        runtime_mode="shared",
        process_role="worker",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = [
        _seed_registry(data_dir=tmp_path, registry=healthy, stores_dir=stores_dir),
        _seed_registry(data_dir=tmp_path, registry=degraded, stores_dir=stores_dir),
    ]
    _install_store_backed_clients(
        monkeypatch,
        seeded,
        failing_ops_by_url={
            degraded.url: {"sync_binding", "publish_timeline"},
        },
    )
    services = _services_for_config(config)
    runtime, dispatcher = _build_telegram_runtime_with_dispatcher(config, services=services)
    conversation_ref = telegram_conversation_ref(config, 777)
    egress = dispatcher.create_egress(
        conversation_ref,
        config=config,
        bot=runtime.bot_instance,
        conversation_key=telegram_conversation_key(777),
        source="telegram",
    )

    async with _running_registry_processor(config):
        await egress.bind(title="Degraded test", config=config)
        await _wait_for(
            lambda: seeded[0].store.get_conversation(conversation_ref)["conversation_id"]
            == conversation_ref,
            message="healthy registry did not receive conversation bind",
        )
        await egress.on_message_received("still projects")
        await _wait_for(
            lambda: "channel_input" in _timeline_kinds(seeded[0].store, conversation_ref),
            message="healthy registry did not receive projected input",
        )

    assert "channel_input" in _timeline_kinds(seeded[0].store, conversation_ref)
    with pytest.raises(KeyError):
        seeded[1].store.get_conversation(conversation_ref)


@pytest.mark.asyncio
async def test_shared_worker_reports_routed_task_result_through_bus_to_registry_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="default",
        url="http://registry.default",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
        runtime_mode="shared",
        process_role="worker",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(
        data_dir=tmp_path,
        registry=registry,
        stores_dir=stores_dir,
        with_origin_agent=True,
    )
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    seeded.store.create_routed_task(
        {
            "routed_task_id": "task-1",
            "parent_conversation_id": "parent-1",
            "origin_agent_id": seeded.origin_agent_id,
            "target_agent_id": seeded.local_agent_id,
            "title": "Review",
            "instructions": "Review the spec",
        }
    )

    async with _running_registry_processor(config):
        result = await services.control_plane.task_routing.report_routed_task_result(
            routed_task_id="task-1",
            authority_ref=registry_authority_ref("default"),
            result=RoutedTaskResult(
                routed_task_id="task-1",
                status="completed",
                summary="done",
                full_text="full delegated result",
            ),
        )

        await _wait_for(
            lambda: seeded.store.list_tasks()[0]["status"] == "completed",
            message="routed task result did not update registry store",
        )

    deliveries = seeded.store.poll(seeded.origin_agent_token, cursor=0, limit=10)["deliveries"]

    assert result.status == "reported"
    assert seeded.store.list_tasks()[0]["summary"] == "done"
    assert deliveries[0]["kind"] == "routed_result"
    assert deliveries[0]["payload"]["result"]["full_text"] == "full delegated result"


@pytest.mark.asyncio
async def test_local_mode_projects_through_bus_and_processor_in_same_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="local",
        url="http://registry.local",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
        runtime_mode="local",
        process_role="all",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(data_dir=tmp_path, registry=registry, stores_dir=stores_dir)
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    conversation_ref = "telegram:test-bot:555"

    async with _running_registry_processor(config):
        await services.control_plane.conversation_projection.bind_external_conversation(
            conversation_ref=conversation_ref,
            title="Local mode",
            origin_channel="telegram",
            external_id="555",
        )
        await _wait_for(
            lambda: seeded.store.get_conversation(conversation_ref)["conversation_id"]
            == conversation_ref,
            message="local-mode bind did not reach registry",
        )
        await services.control_plane.health_publication.publish_health(
            report=HealthReport(
                connectivity_state="connected",
                current_capacity=0,
                max_capacity=1,
                runtime_health_json='{"mode":"local"}',
            )
        )
        await _wait_for(
            lambda: seeded.store.list_agents()[0]["connectivity_state"] == "connected",
            message="local-mode health publication did not reach registry",
        )

    assert seeded.store.list_agents()[0]["connectivity_state"] == "connected"


@pytest.mark.asyncio
async def test_registry_only_bot_projects_without_telegram_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="registry-only",
        url="http://registry.only",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        telegram_token="",
        agent_mode="registry",
        agent_registries=(registry,),
        runtime_mode="local",
        process_role="all",
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(data_dir=tmp_path, registry=registry, stores_dir=stores_dir)
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    conversation_ref = "registry:registry-only:conversation:conv-1"

    async with _running_registry_processor(config):
        await services.control_plane.conversation_projection.bind_external_conversation(
            conversation_ref=conversation_ref,
            title="Registry only",
            origin_channel="registry",
            external_id="conv-1",
        )
        await _wait_for(
            lambda: seeded.store.get_conversation(conversation_ref)["conversation_id"]
            == conversation_ref,
            message="registry-only bind did not reach registry",
        )

    assert seeded.store.get_conversation(conversation_ref)["title"] == "Registry only"


@pytest.mark.asyncio
async def test_coordination_only_registry_enqueues_no_projection_commands(tmp_path: Path) -> None:
    registry = make_registry_connection(
        registry_id="coord",
        url="http://registry.coord",
        registry_scope="coordination",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
    )
    _init_backend(config)
    services = _services_for_config(config)
    bus = ControlPlaneBus(config.data_dir)

    await services.control_plane.conversation_projection.bind_external_conversation(
        conversation_ref="telegram:test-bot:1",
        title="No projection",
        origin_channel="telegram",
        external_id="1",
    )
    await services.control_plane.conversation_projection.publish_external_timeline(
        conversation_ref="telegram:test-bot:1",
        kind="channel_input",
        title="Message",
    )

    assert _command_count(bus) == 0


@pytest.mark.asyncio
async def test_control_plane_commands_survive_process_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="persist",
        url="http://registry.persist",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(data_dir=tmp_path, registry=registry, stores_dir=stores_dir)
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    bus = ControlPlaneBus(config.data_dir)
    conversation_ref = "telegram:test-bot:9"

    await services.control_plane.conversation_projection.bind_external_conversation(
        conversation_ref=conversation_ref,
        title="Persist me",
        origin_channel="telegram",
        external_id="9",
    )

    assert _command_count(bus) == 1
    with pytest.raises(KeyError):
        seeded.store.get_conversation(conversation_ref)

    runtime_backend.reset_for_test()
    _init_backend(config)
    async with _running_registry_processor(config):
        await _wait_for(
            lambda: seeded.store.get_conversation(conversation_ref)["conversation_id"]
            == conversation_ref,
            message="persisted command was not processed after restart",
        )

    assert seeded.store.get_conversation(conversation_ref)["title"] == "Persist me"


@pytest.mark.asyncio
async def test_routed_task_status_update_persists_timeline_events_and_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="status",
        url="http://registry.status",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(
        data_dir=tmp_path,
        registry=registry,
        stores_dir=stores_dir,
        with_origin_agent=True,
    )
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    seeded.store.create_routed_task(
        {
            "routed_task_id": "task-status-1",
            "parent_conversation_id": "parent-status-1",
            "origin_agent_id": seeded.origin_agent_id,
            "target_agent_id": seeded.local_agent_id,
            "title": "Status task",
            "instructions": "Keep me updated",
        }
    )

    async with _running_registry_processor(config):
        await services.control_plane.task_routing.update_routed_task_status(
            update=RoutedTaskUpdate(
                routed_task_id="task-status-1",
                status="running",
                summary="halfway",
                timeline_events=(
                    TimelineEvent(
                        event_id="evt-1",
                        conversation_id="parent-status-1",
                        kind="progress",
                        title="Halfway",
                        progress=50,
                    ),
                ),
                progress=50,
            ),
            authority_ref=registry_authority_ref("status"),
        )
        await _wait_for(
            lambda: seeded.store.list_tasks()[0]["status"] == "running"
            and bool(seeded.store.get_conversation_timeline("parent-status-1")),
            message="routed task status update did not reach registry store",
        )

    task = seeded.store.list_tasks()[0]
    timeline = seeded.store.get_conversation_timeline("parent-status-1")

    assert task["status"] == "running"
    assert task["summary"] == "halfway"
    assert timeline[0]["event_id"] == "evt-1"
    assert timeline[0]["progress"] == 50


@pytest.mark.asyncio
async def test_routed_task_report_failure_persists_partialfailed_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = make_registry_connection(
        registry_id="fallback",
        url="http://registry.fallback",
        registry_scope="full",
    )
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(registry,),
    )
    _init_backend(config)
    stores_dir = tmp_path / "registry-stores"
    stores_dir.mkdir()
    seeded = _seed_registry(
        data_dir=tmp_path,
        registry=registry,
        stores_dir=stores_dir,
        with_origin_agent=True,
    )
    _install_store_backed_clients(monkeypatch, [seeded])
    services = _services_for_config(config)
    seeded.store.create_routed_task(
        {
            "routed_task_id": "task-fallback-1",
            "parent_conversation_id": "parent-fallback-1",
            "origin_agent_id": seeded.origin_agent_id,
            "target_agent_id": seeded.local_agent_id,
            "title": "Fallback task",
            "instructions": "Keep me safe",
        }
    )

    async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
        del routed_task_id, authority_ref, result
        return TaskResultReport(status="failed", error="registry unavailable")

    monkeypatch.setattr(
        services.control_plane.task_routing,
        "report_routed_task_result",
        fake_report_routed_task_result,
    )

    async with _running_registry_processor(config):
        result = await finalize_execution(
            RequestExecutionOutcome(status="completed", reply_text="done"),
            context=FinalizationContext(
                config=config,
                item_id="item-fallback-1",
                conversation_key="registry:fallback:task:task-fallback-1",
                runtime_chat="registry:fallback:task:task-fallback-1",
                conversation_ref="registry:fallback:task:task-fallback-1",
                routed_task_id="task-fallback-1",
                authority_ref=registry_authority_ref("fallback"),
                task_routing=services.control_plane.task_routing,
            ),
        )
        await _wait_for(
            lambda: seeded.store.list_tasks()[0]["status"] == "partialfailed",
            message="fallback routed-task status did not reach registry store",
        )

    task = seeded.store.list_tasks()[0]

    assert result.routed_result_status == "report_failed"
    assert task["status"] == "partialfailed"
    assert "could not be delivered" in task["summary"]
