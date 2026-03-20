from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.models import ControlCommand
from app.storage import ensure_data_dirs


def _command(
    command_id: str,
    *,
    capability: str = "conversation_projection",
    operation: str = "bind_conversation",
    authority_ref: str = "registry:alpha",
    idempotency_key: str = "",
    max_retries: int = 3,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        capability=capability,
        operation=operation,
        payload_json='{"ok": true}',
        authority_ref=authority_ref,
        idempotency_key=idempotency_key,
        max_retries=max_retries,
    )


@pytest.fixture(params=["sqlite", "postgres"])
def backend_bus_and_data_dir(request):
    from app import runtime_backend
    from tests.support.config_support import make_config

    if request.param == "sqlite":
        runtime_backend.reset_for_test()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            ensure_data_dirs(data_dir)
            bus = ControlPlaneBus(data_dir)
            bus.reset_for_test()
            yield "sqlite", bus, data_dir
        return

    postgres_url = request.getfixturevalue("postgres_truncated")
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir, database_url=postgres_url)
        cfg = make_config(data_dir=data_dir, database_url=postgres_url)
        runtime_backend.init(cfg)
        try:
            yield "postgres", ControlPlaneBus(data_dir), data_dir
        finally:
            runtime_backend.reset_for_test()


@pytest.mark.asyncio
async def test_backend_selection_matches_runtime_backend(backend_bus_and_data_dir):
    backend, _bus, _data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    if backend == "sqlite":
        assert store.__class__.__name__ == "SQLiteControlPlaneStore"
    else:
        assert store.__class__.__name__ == "PostgresControlPlaneStore"


@pytest.mark.asyncio
async def test_submit_poll_complete_and_reply_round_trip(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    command = _command("cmd-roundtrip")

    command_id = await bus.submit(command)
    claimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in claimed] == [command_id]

    await bus.complete(
        command_id,
        claimed_at=claimed[0].claimed_at,
        result_json='{"accepted": true}',
    )

    reply = runtime_backend.control_plane_store().get_reply(data_dir, command_id)
    assert reply is not None
    assert reply.status == "completed"
    assert reply.result_json == '{"accepted": true}'


@pytest.mark.asyncio
async def test_request_waits_for_processor_completion(backend_bus_and_data_dir):
    _backend, bus, _data_dir = backend_bus_and_data_dir
    command = _command(
        "cmd-request",
        capability="task_routing",
        operation="submit_routed_task",
        authority_ref="registry:coord",
    )

    async def processor() -> None:
        while True:
            claimed = await bus.poll_commands(
                allowed_pairs={("registry:coord", "task_routing")},
            )
            if claimed:
                await bus.complete(
                    claimed[0].command_id,
                    claimed_at=claimed[0].claimed_at,
                    result_json='{"status":"accepted","routed_task_id":"task-1"}',
                )
                return
            await asyncio.sleep(0.05)

    worker = asyncio.create_task(processor())
    try:
        reply = await bus.request(command, timeout_seconds=2.0)
    finally:
        await worker

    assert reply.status == "completed"
    assert reply.result_json == '{"status":"accepted","routed_task_id":"task-1"}'


@pytest.mark.asyncio
async def test_poll_commands_is_pair_aware(backend_bus_and_data_dir):
    _backend, bus, _data_dir = backend_bus_and_data_dir
    await bus.submit(
        _command(
            "cmd-pair-aware",
            capability="task_routing",
            operation="submit_routed_task",
        )
    )

    wrong = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    right = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "task_routing")},
    )

    assert wrong == []
    assert [item.command_id for item in right] == ["cmd-pair-aware"]


@pytest.mark.asyncio
async def test_submit_deduplicates_by_idempotency_key(backend_bus_and_data_dir):
    _backend, bus, _data_dir = backend_bus_and_data_dir
    first = _command("cmd-idem-1", idempotency_key="key-1")
    second = _command("cmd-idem-2", idempotency_key="key-1")

    first_id = await bus.submit(first)
    second_id = await bus.submit(second)
    claimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )

    assert first_id == "cmd-idem-1"
    assert second_id == "cmd-idem-1"
    assert [item.command_id for item in claimed] == ["cmd-idem-1"]


@pytest.mark.asyncio
async def test_fail_respects_retry_backoff_before_requeue(backend_bus_and_data_dir):
    _backend, bus, _data_dir = backend_bus_and_data_dir
    await bus.submit(_command("cmd-retry", max_retries=2))
    claimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in claimed] == ["cmd-retry"]

    await bus.fail(
        "cmd-retry",
        claimed_at=claimed[0].claimed_at,
        error="transient failure",
    )

    immediate = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert immediate == []

    time.sleep(1.1)

    retried = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in retried] == ["cmd-retry"]


@pytest.mark.asyncio
async def test_reclaim_expired_consumes_retry_budget(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-expired", max_retries=1))
    claimed = store.poll_commands(
        data_dir,
        allowed_pairs={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-expired"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1

    time.sleep(1.1)
    reclaimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in reclaimed] == ["cmd-expired"]

    await bus.fail(
        "cmd-expired",
        claimed_at=reclaimed[0].claimed_at,
        error="second failure",
    )
    reply = store.get_reply(data_dir, "cmd-expired")
    assert reply is not None
    assert reply.status == "failed"
    assert reply.error == "second failure"


@pytest.mark.asyncio
async def test_stale_claim_token_cannot_complete_reclaimed_command(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-stale-complete", max_retries=1))
    claimed = store.poll_commands(
        data_dir,
        allowed_pairs={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-stale-complete"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1
    time.sleep(1.1)

    reclaimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in reclaimed] == ["cmd-stale-complete"]

    await bus.complete(
        "cmd-stale-complete",
        claimed_at=claimed[0].claimed_at,
        result_json='{"accepted": false}',
    )
    assert store.get_reply(data_dir, "cmd-stale-complete") is None

    await bus.complete(
        "cmd-stale-complete",
        claimed_at=reclaimed[0].claimed_at,
        result_json='{"accepted": true}',
    )
    reply = store.get_reply(data_dir, "cmd-stale-complete")
    assert reply is not None
    assert reply.status == "completed"
    assert reply.result_json == '{"accepted": true}'


@pytest.mark.asyncio
async def test_reconcile_orphans_dead_letters_removed_and_revoked_pairs(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    await bus.submit(_command("cmd-valid"))
    await bus.submit(_command("cmd-removed", authority_ref="registry:gone"))
    await bus.submit(
        _command(
            "cmd-revoked",
            capability="task_routing",
            operation="submit_routed_task",
        )
    )

    dead = await bus.reconcile_orphans(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert dead == 2

    claimed = await bus.poll_commands(
        allowed_pairs={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in claimed] == ["cmd-valid"]
    assert store.get_reply(data_dir, "cmd-removed") is not None
    assert store.get_reply(data_dir, "cmd-revoked") is not None
