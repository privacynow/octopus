from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app import runtime_backend
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.models import ControlCommand, ControlReply
from app.control_plane.processor_runner import ProcessorRunner
from app.storage import ensure_data_dirs
from tests.support.config_support import make_config


class _RecordingProcessor:
    def __init__(
        self,
        *,
        authority_capabilities: dict[str, set[str]],
        reply: ControlReply | None = None,
        side_effect=None,
    ) -> None:
        self._authority_capabilities = authority_capabilities
        self._reply = reply or ControlReply(command_id="reply", status="completed", result_json='{"ok": true}')
        self._side_effect = side_effect
        self.seen: list[ControlCommand] = []

    def authority_capabilities(self) -> dict[str, set[str]]:
        return self._authority_capabilities

    async def process(self, command: ControlCommand) -> ControlReply:
        self.seen.append(command)
        if self._side_effect is not None:
            return await self._side_effect(command)
        return self._reply.model_copy(update={"command_id": command.command_id})


class _FakeLeaseBus:
    def __init__(self, command: ControlCommand) -> None:
        self._command = command
        self._claimed = False
        self.renewals: list[tuple[str, float]] = []
        self.completed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.dead_letters: list[tuple[str, str]] = []

    async def reclaim_expired(self) -> int:
        return 0

    async def poll_commands(self, *, allowed_pairs: set[tuple[str, str]], limit: int = 20) -> list[ControlCommand]:
        del allowed_pairs, limit
        if self._claimed:
            return []
        self._claimed = True
        return [self._command]

    async def renew_lease(self, command_id: str, *, extension_seconds: float = 30.0) -> bool:
        self.renewals.append((command_id, extension_seconds))
        return True

    async def complete(self, command_id: str, *, result_json: str | None = None) -> None:
        del result_json
        self.completed.append(command_id)

    async def fail(self, command_id: str, *, error: str) -> None:
        self.failed.append((command_id, error))

    async def dead_letter(self, command_id: str, *, reason: str) -> None:
        self.dead_letters.append((command_id, reason))


def _command(
    command_id: str,
    *,
    capability: str = "conversation_projection",
    operation: str = "bind_conversation",
    authority_ref: str = "registry:alpha",
    max_retries: int = 3,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        capability=capability,
        operation=operation,
        payload_json='{"ok": true}',
        authority_ref=authority_ref,
        max_retries=max_retries,
    )


@pytest.fixture
def sqlite_bus_and_data_dir():
    runtime_backend.reset_for_test()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        bus = ControlPlaneBus(data_dir)
        bus.reset_for_test()
        yield bus, data_dir
    runtime_backend.reset_for_test()


async def _wait_for_reply(bus: ControlPlaneBus, data_dir: Path, command_id: str, *, timeout: float = 1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        reply = runtime_backend.control_plane_store().get_reply(data_dir, command_id)
        if reply is not None:
            return reply
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"timed out waiting for reply {command_id}")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", ["sqlite", "postgres"])
async def test_processor_runner_claims_and_dispatches_by_authority_pair(backend_name, request):
    if backend_name == "sqlite":
        runtime_backend.reset_for_test()
        tmpdir = tempfile.TemporaryDirectory()
        data_dir = Path(tmpdir.name)
        ensure_data_dirs(data_dir)
        bus = ControlPlaneBus(data_dir)
        bus.reset_for_test()
    else:
        postgres_url = request.getfixturevalue("postgres_truncated")
        tmpdir = tempfile.TemporaryDirectory()
        data_dir = Path(tmpdir.name)
        ensure_data_dirs(data_dir, database_url=postgres_url)
        runtime_backend.init(make_config(data_dir=data_dir, database_url=postgres_url))
        bus = ControlPlaneBus(data_dir)

    try:
        runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
        projection = _RecordingProcessor(
            authority_capabilities={"registry:alpha": {"conversation_projection"}},
        )
        routing = _RecordingProcessor(
            authority_capabilities={"registry:coord": {"task_routing"}},
        )
        runner.register(projection)
        runner.register(routing)

        await bus.submit(_command("cmd-proj", authority_ref="registry:alpha"))
        await bus.submit(
            _command(
                "cmd-route",
                capability="task_routing",
                operation="submit_routed_task",
                authority_ref="registry:coord",
            )
        )

        stop_event = asyncio.Event()
        task = asyncio.create_task(runner.run(stop_event=stop_event))

        await _wait_for_reply(bus, data_dir, "cmd-proj")
        await _wait_for_reply(bus, data_dir, "cmd-route")
        stop_event.set()
        await task

        assert [command.command_id for command in projection.seen] == ["cmd-proj"]
        assert [command.command_id for command in routing.seen] == ["cmd-route"]
    finally:
        tmpdir.cleanup()
        runtime_backend.reset_for_test()


@pytest.mark.asyncio
async def test_processor_runner_retries_transient_failure_then_completes(sqlite_bus_and_data_dir, monkeypatch):
    bus, data_dir = sqlite_bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
    attempts = 0

    async def flaky(command: ControlCommand) -> ControlReply:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient boom")
        return ControlReply(command_id=command.command_id, status="completed", result_json='{"ok": true}')

    processor = _RecordingProcessor(
        authority_capabilities={"registry:alpha": {"conversation_projection"}},
        side_effect=flaky,
    )
    runner.register(processor)
    monkeypatch.setattr("app.control_plane.sqlite_impl.retry_backoff_seconds", lambda _retry_count: 0)

    await bus.submit(_command("cmd-retry"))

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))

    reply = await _wait_for_reply(bus, data_dir, "cmd-retry")
    stop_event.set()
    await task

    assert reply.status == "completed"
    assert attempts == 2


@pytest.mark.asyncio
async def test_processor_runner_dead_letters_after_retry_exhaustion(sqlite_bus_and_data_dir):
    bus, data_dir = sqlite_bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)

    async def always_fail(command: ControlCommand) -> ControlReply:
        raise RuntimeError(f"boom:{command.command_id}")

    runner.register(
        _RecordingProcessor(
            authority_capabilities={"registry:alpha": {"conversation_projection"}},
            side_effect=always_fail,
        )
    )

    await bus.submit(_command("cmd-dead", max_retries=0))

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))

    reply = await _wait_for_reply(bus, data_dir, "cmd-dead")
    stop_event.set()
    await task

    assert reply.status == "failed"
    assert "boom:cmd-dead" in (reply.error or "")


@pytest.mark.asyncio
async def test_processor_runner_reclaims_expired_commands_before_dispatch(sqlite_bus_and_data_dir):
    bus, data_dir = sqlite_bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
    processor = _RecordingProcessor(
        authority_capabilities={"registry:alpha": {"conversation_projection"}},
    )
    runner.register(processor)

    await bus.submit(_command("cmd-expired"))
    claimed = await bus.poll_commands(allowed_pairs={("registry:alpha", "conversation_projection")})
    assert [item.command_id for item in claimed] == ["cmd-expired"]

    conn = runtime_backend.control_plane_store().debug_connection(data_dir)
    conn.execute(
        """
        UPDATE control_plane_commands
        SET lease_expires_at = '2000-01-01T00:00:00+00:00'
        WHERE command_id = ?
        """,
        ("cmd-expired",),
    )
    conn.commit()
    from app.control_plane import sqlite_impl

    original_backoff = sqlite_impl.retry_backoff_seconds
    sqlite_impl.retry_backoff_seconds = lambda _retry_count: 0

    try:
        stop_event = asyncio.Event()
        task = asyncio.create_task(runner.run(stop_event=stop_event))

        reply = await _wait_for_reply(bus, data_dir, "cmd-expired")
        stop_event.set()
        await task

        assert reply.status == "completed"
        assert [command.command_id for command in processor.seen] == ["cmd-expired"]
    finally:
        sqlite_impl.retry_backoff_seconds = original_backoff


@pytest.mark.asyncio
async def test_processor_runner_clean_shutdown_stops_claiming_and_waits_for_inflight(sqlite_bus_and_data_dir):
    bus, data_dir = sqlite_bus_and_data_dir
    gate = asyncio.Event()
    started = asyncio.Event()

    async def blocking(command: ControlCommand) -> ControlReply:
        started.set()
        await gate.wait()
        return ControlReply(command_id=command.command_id, status="completed", result_json='{"ok": true}')

    runner = ProcessorRunner(
        bus,
        claim_limit=1,
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
    )
    runner.register(
        _RecordingProcessor(
            authority_capabilities={"registry:alpha": {"conversation_projection"}},
            side_effect=blocking,
        )
    )

    await bus.submit(_command("cmd-first"))
    await bus.submit(_command("cmd-second", operation="publish_timeline"))

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    stop_event.set()
    gate.set()
    await task

    first_reply = await _wait_for_reply(bus, data_dir, "cmd-first")
    assert first_reply.status == "completed"
    pending = await bus.poll_commands(allowed_pairs={("registry:alpha", "conversation_projection")}, limit=10)
    assert [command.command_id for command in pending] == ["cmd-second"]


@pytest.mark.asyncio
async def test_processor_runner_renews_leases_for_inflight_commands() -> None:
    command = _command("cmd-lease")
    bus = _FakeLeaseBus(command)
    gate = asyncio.Event()

    async def wait_for_renewal(_command: ControlCommand) -> ControlReply:
        while not bus.renewals:
            await asyncio.sleep(0.01)
        gate.set()
        return ControlReply(command_id="cmd-lease", status="completed", result_json='{"ok": true}')

    runner = ProcessorRunner(
        bus,
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
        lease_renewal_interval_seconds=0.01,
    )
    runner.register(
        _RecordingProcessor(
            authority_capabilities={"registry:alpha": {"conversation_projection"}},
            side_effect=wait_for_renewal,
        )
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    await asyncio.wait_for(gate.wait(), timeout=1.0)
    stop_event.set()
    await task

    assert bus.renewals
    assert bus.completed == ["cmd-lease"]


def test_processor_runner_rejects_duplicate_pair_ownership(sqlite_bus_and_data_dir) -> None:
    bus, _data_dir = sqlite_bus_and_data_dir
    runner = ProcessorRunner(bus)
    runner.register(_RecordingProcessor(authority_capabilities={"registry:alpha": {"conversation_projection"}}))

    with pytest.raises(ValueError, match="duplicate control-plane processor ownership"):
        runner.register(_RecordingProcessor(authority_capabilities={"registry:alpha": {"conversation_projection"}}))
