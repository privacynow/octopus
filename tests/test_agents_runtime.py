import asyncio
from collections.abc import Awaitable
from pathlib import Path

from app.runtime.registry_participant import AgentRuntime
from tests.support.config_support import make_config, make_registry_connection


def _close_awaitable(awaitable: Awaitable[object]) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


async def test_run_forever_backoff_doubles_on_consecutive_failures(monkeypatch, tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        agent_poll_interval_seconds=2.0,
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])
    stop_event = asyncio.Event()
    sleeps: list[float] = []

    async def fake_sync_once() -> str:
        runtime._mark_state("degraded", error="timeout")
        return "degraded"

    async def fake_wait_for(awaitable, timeout):
        _close_awaitable(awaitable)
        sleeps.append(timeout)
        if len(sleeps) >= 5:
            stop_event.set()
            return None
        raise asyncio.TimeoutError

    monkeypatch.setattr(runtime, "sync_once", fake_sync_once)
    monkeypatch.setattr("random.uniform", lambda low, high: high)
    monkeypatch.setattr("app.runtime.registry_participant.asyncio.wait_for", fake_wait_for)

    await runtime.run_forever(stop_event)

    assert sleeps == [4.0, 8.0, 16.0, 32.0, 64.0]
    assert all(timeout <= 64.0 for timeout in sleeps)
    assert all(curr <= min(prev * 2, 64.0) for prev, curr in zip(sleeps, sleeps[1:]))


async def test_run_forever_backoff_resets_after_reconnect(monkeypatch, tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        agent_poll_interval_seconds=2.0,
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])
    stop_event = asyncio.Event()
    sleeps: list[float] = []
    states = iter(["degraded", "degraded", "connected"])

    async def fake_sync_once() -> str:
        state = next(states)
        runtime._mark_state(state, error="" if state == "connected" else "timeout")
        return state

    async def fake_poll_once() -> int:
        return 0

    async def fake_wait_for(awaitable, timeout):
        _close_awaitable(awaitable)
        sleeps.append(timeout)
        if len(sleeps) >= 3:
            stop_event.set()
            return None
        raise asyncio.TimeoutError

    monkeypatch.setattr(runtime, "sync_once", fake_sync_once)
    monkeypatch.setattr(runtime, "poll_once", fake_poll_once)
    monkeypatch.setattr("random.uniform", lambda low, high: high)
    monkeypatch.setattr("app.runtime.registry_participant.asyncio.wait_for", fake_wait_for)

    await runtime.run_forever(stop_event)

    assert sleeps == [4.0, 8.0, 2.0]
    assert sleeps[-1] <= 2.0


async def test_run_forever_polls_only_when_connected(monkeypatch, tmp_path: Path):
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        agent_poll_interval_seconds=2.0,
    )
    runtime = AgentRuntime(config, registry=config.agent_registries[0])
    stop_event = asyncio.Event()
    poll_calls: list[str] = []

    async def fake_sync_once() -> str:
        runtime._mark_state("standalone")
        return "standalone"

    async def fake_poll_once() -> int:
        poll_calls.append("poll")
        return 0

    async def fake_wait_for(awaitable, timeout):
        _close_awaitable(awaitable)
        stop_event.set()
        return None

    monkeypatch.setattr(runtime, "sync_once", fake_sync_once)
    monkeypatch.setattr(runtime, "poll_once", fake_poll_once)
    monkeypatch.setattr("random.uniform", lambda low, high: high)
    monkeypatch.setattr("app.runtime.registry_participant.asyncio.wait_for", fake_wait_for)

    await runtime.run_forever(stop_event)

    assert poll_calls == []
