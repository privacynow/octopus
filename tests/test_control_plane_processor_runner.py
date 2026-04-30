from __future__ import annotations

import asyncio
from collections import Counter
import logging
import tempfile
from pathlib import Path

import pytest
from psycopg import connect

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
        implemented_admin_interfaces: dict[str, set[str]],
        reply: ControlReply | None = None,
        side_effect=None,
    ) -> None:
        self._implemented_admin_interfaces = implemented_admin_interfaces
        self._reply = reply or ControlReply(command_id="reply", status="completed", result_json='{"ok": true}')
        self._side_effect = side_effect
        self.seen: list[ControlCommand] = []

    def implemented_admin_interfaces(self) -> dict[str, set[str]]:
        return self._implemented_admin_interfaces

    async def process(self, command: ControlCommand) -> ControlReply:
        self.seen.append(command)
        if self._side_effect is not None:
            return await self._side_effect(command)
        return self._reply.model_copy(update={"command_id": command.command_id})


class _FakeLeaseBus:
    def __init__(self, command: ControlCommand) -> None:
        self._command = command
        self._claimed = False
        self.renewals: list[tuple[str, str, float]] = []
        self.completed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str, str]] = []
        self.dead_letters: list[tuple[str, str, str]] = []
        self.purge_calls = 0

    async def reclaim_expired(self) -> int:
        return 0

    async def purge_old_commands(self, older_than_hours: int = 72) -> int:
        del older_than_hours
        self.purge_calls += 1
        return 0

    async def poll_commands(self, *, allowed_admin_targets: set[tuple[str, str]], limit: int = 20) -> list[ControlCommand]:
        del allowed_admin_targets, limit
        if self._claimed:
            return []
        self._claimed = True
        return [self._command.model_copy(update={"claimed_at": "claim-1"})]

    async def renew_lease(
        self,
        command_id: str,
        *,
        claimed_at: str,
        extension_seconds: float = 30.0,
    ) -> bool:
        self.renewals.append((command_id, claimed_at, extension_seconds))
        return True

    async def complete(
        self,
        command_id: str,
        *,
        claimed_at: str,
        result_json: str | None = None,
    ) -> None:
        del result_json
        self.completed.append((command_id, claimed_at))

    async def fail(self, command_id: str, *, claimed_at: str, error: str) -> None:
        self.failed.append((command_id, claimed_at, error))

    async def dead_letter(self, command_id: str, *, claimed_at: str, reason: str) -> None:
        self.dead_letters.append((command_id, claimed_at, reason))


class _FlakyLoopBus:
    def __init__(self, failing_step: str) -> None:
        self.failing_step = failing_step
        self.calls: Counter[str] = Counter()

    async def reclaim_expired(self) -> int:
        self.calls["reclaim"] += 1
        if self.failing_step == "reclaim" and self.calls["reclaim"] == 1:
            raise RuntimeError("reclaim boom")
        return 0

    async def purge_old_commands(self, older_than_hours: int = 72) -> int:
        del older_than_hours
        self.calls["purge"] += 1
        if self.failing_step == "purge" and self.calls["purge"] == 1:
            raise RuntimeError("purge boom")
        return 0

    async def poll_commands(self, *, allowed_admin_targets: set[tuple[str, str]], limit: int = 20) -> list[ControlCommand]:
        del allowed_admin_targets, limit
        self.calls["poll"] += 1
        if self.failing_step == "poll" and self.calls["poll"] == 1:
            raise RuntimeError("poll boom")
        return []


def _command(
    command_id: str,
    *,
    admin_interface: str = "conversation_projection",
    admin_operation: str = "bind_conversation",
    implementation_ref: str = "registry:alpha",
    max_retries: int = 3,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        admin_interface=admin_interface,
        admin_operation=admin_operation,
        payload_json='{"ok": true}',
        implementation_ref=implementation_ref,
        max_retries=max_retries,
    )


@pytest.fixture
def bus_and_data_dir(postgres_truncated):
    runtime_backend.reset_for_test()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        runtime_backend.init(make_config(data_dir=data_dir, database_url=postgres_truncated))
        bus = ControlPlaneBus(data_dir)
        bus.reset_for_test()
        yield bus, data_dir, postgres_truncated
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
async def test_processor_runner_claims_and_dispatches_by_authority_pair(postgres_truncated):
    runtime_backend.reset_for_test()
    tmpdir = tempfile.TemporaryDirectory()
    data_dir = Path(tmpdir.name)
    ensure_data_dirs(data_dir)
    runtime_backend.init(make_config(data_dir=data_dir, database_url=postgres_truncated))
    bus = ControlPlaneBus(data_dir)
    try:
        runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
        projection = _RecordingProcessor(
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
        )
        routing = _RecordingProcessor(
            implemented_admin_interfaces={"registry:coord": {"task_routing"}},
        )
        runner.register(projection)
        runner.register(routing)

        await bus.submit(_command("cmd-proj", implementation_ref="registry:alpha"))
        await bus.submit(
            _command(
                "cmd-route",
                admin_interface="task_routing",
                admin_operation="submit_routed_task",
                implementation_ref="registry:coord",
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
async def test_processor_runner_retries_transient_failure_then_completes(bus_and_data_dir, monkeypatch):
    bus, data_dir, _postgres_url = bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
    attempts = 0

    async def flaky(command: ControlCommand) -> ControlReply:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient boom")
        return ControlReply(command_id=command.command_id, status="completed", result_json='{"ok": true}')

    processor = _RecordingProcessor(
        implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
        side_effect=flaky,
    )
    runner.register(processor)
    monkeypatch.setattr("app.control_plane.postgres_impl.retry_backoff_seconds", lambda _retry_count: 0)

    await bus.submit(_command("cmd-retry"))

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))

    reply = await _wait_for_reply(bus, data_dir, "cmd-retry")
    stop_event.set()
    await task

    assert reply.status == "completed"
    assert attempts == 2


@pytest.mark.asyncio
async def test_processor_runner_dead_letters_after_retry_exhaustion(bus_and_data_dir):
    bus, data_dir, _postgres_url = bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)

    async def always_fail(command: ControlCommand) -> ControlReply:
        raise RuntimeError(f"boom:{command.command_id}")

    runner.register(
        _RecordingProcessor(
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
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
async def test_processor_runner_reclaims_expired_commands_before_dispatch(bus_and_data_dir, monkeypatch):
    bus, data_dir, postgres_url = bus_and_data_dir
    runner = ProcessorRunner(bus, poll_interval_seconds=0.01, reclaim_interval_seconds=0.01)
    processor = _RecordingProcessor(
        implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
    )
    runner.register(processor)

    await bus.submit(_command("cmd-expired"))
    claimed = await bus.poll_commands(allowed_admin_targets={("registry:alpha", "conversation_projection")})
    assert [item.command_id for item in claimed] == ["cmd-expired"]

    with connect(postgres_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
        """
        UPDATE bot_runtime.control_plane_commands
        SET lease_expires_at = '2000-01-01T00:00:00+00:00'
        WHERE command_id = %s
        """,
                ("cmd-expired",),
            )
        conn.commit()
    monkeypatch.setattr("app.control_plane.postgres_impl.retry_backoff_seconds", lambda _retry_count: 0)

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))

    reply = await _wait_for_reply(bus, data_dir, "cmd-expired")
    stop_event.set()
    await task

    assert reply.status == "completed"
    assert [command.command_id for command in processor.seen] == ["cmd-expired"]


@pytest.mark.asyncio
async def test_processor_runner_clean_shutdown_stops_claiming_and_waits_for_inflight(bus_and_data_dir):
    bus, data_dir, _postgres_url = bus_and_data_dir
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
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
            side_effect=blocking,
        )
    )

    await bus.submit(_command("cmd-first"))
    await bus.submit(_command("cmd-second", admin_operation="publish_timeline"))

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    stop_event.set()
    gate.set()
    await task

    first_reply = await _wait_for_reply(bus, data_dir, "cmd-first")
    assert first_reply.status == "completed"
    pending = await bus.poll_commands(allowed_admin_targets={("registry:alpha", "conversation_projection")}, limit=10)
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
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
            side_effect=wait_for_renewal,
        )
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    await asyncio.wait_for(gate.wait(), timeout=1.0)
    stop_event.set()
    await task

    assert bus.renewals
    assert bus.renewals[0] == ("cmd-lease", "claim-1", 30.0)
    assert bus.completed == [("cmd-lease", "claim-1")]
    assert bus.purge_calls >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_step", ["reclaim", "purge", "poll"])
async def test_processor_runner_logs_and_survives_transient_loop_errors(
    failing_step: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = _FlakyLoopBus(failing_step)
    runner = ProcessorRunner(
        bus,
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
    )
    caplog.set_level(logging.ERROR, logger="app.control_plane.processor_runner")
    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))

    deadline = asyncio.get_running_loop().time() + 1.0
    while True:
        if failing_step == "poll":
            if bus.calls["poll"] >= 2:
                break
        elif bus.calls[failing_step] >= 2 and bus.calls["poll"] >= 1:
            break
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"processor loop did not recover after {failing_step} failure")
        await asyncio.sleep(0.01)

    stop_event.set()
    await task

    assert "Control-plane processor loop iteration failed" in caplog.text


@pytest.mark.asyncio
async def test_processor_runner_forwards_claim_token_on_processor_failure(caplog) -> None:
    command = _command("cmd-fail")
    bus = _FakeLeaseBus(command)
    caplog.set_level(logging.ERROR, logger="app.control_plane.processor_runner")

    async def boom(_command: ControlCommand) -> ControlReply:
        raise RuntimeError("boom")

    runner = ProcessorRunner(
        bus,
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
        lease_renewal_interval_seconds=1.0,
    )
    runner.register(
        _RecordingProcessor(
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
            side_effect=boom,
        )
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    while not bus.failed:
        await asyncio.sleep(0.01)
    stop_event.set()
    await task

    assert bus.failed == [("cmd-fail", "claim-1", "boom")]
    assert "Control-plane processor crashed for command cmd-fail" in caplog.text


@pytest.mark.asyncio
async def test_processor_runner_forwards_claim_token_on_dead_letter_without_owner(caplog) -> None:
    command = _command("cmd-dead-letter", implementation_ref="registry:beta")
    bus = _FakeLeaseBus(command)
    caplog.set_level(logging.WARNING, logger="app.control_plane.processor_runner")
    runner = ProcessorRunner(
        bus,
        poll_interval_seconds=0.01,
        reclaim_interval_seconds=0.01,
        lease_renewal_interval_seconds=1.0,
    )
    runner.register(
        _RecordingProcessor(
            implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}},
        )
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run(stop_event=stop_event))
    while not bus.dead_letters:
        await asyncio.sleep(0.01)
    stop_event.set()
    await task

    assert len(bus.dead_letters) == 1
    command_id, claimed_at, reason = bus.dead_letters[0]
    assert command_id == "cmd-dead-letter"
    assert claimed_at == "claim-1"
    assert "no control-plane processor registered" in reason
    assert "Dead-lettering control-plane command cmd-dead-letter" in caplog.text


def test_processor_runner_rejects_duplicate_pair_ownership(bus_and_data_dir) -> None:
    bus, _data_dir, _postgres_url = bus_and_data_dir
    runner = ProcessorRunner(bus)
    runner.register(_RecordingProcessor(implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}}))

    with pytest.raises(ValueError, match="duplicate control-plane processor ownership"):
        runner.register(_RecordingProcessor(implemented_admin_interfaces={"registry:alpha": {"conversation_projection"}}))
