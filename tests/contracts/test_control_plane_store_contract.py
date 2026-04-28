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
    admin_interface: str = "conversation_projection",
    admin_operation: str = "bind_conversation",
    implementation_ref: str = "registry:alpha",
    idempotency_key: str = "",
    max_retries: int = 3,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        admin_interface=admin_interface,
        admin_operation=admin_operation,
        payload_json='{"ok": true}',
        implementation_ref=implementation_ref,
        idempotency_key=idempotency_key,
        max_retries=max_retries,
    )


@pytest.fixture()
def bus_and_data_dir(postgres_truncated):
    from app import runtime_backend
    from tests.support.config_support import make_config

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir=data_dir, database_url=postgres_truncated)
        runtime_backend.init(cfg)
        try:
            yield ControlPlaneBus(data_dir), data_dir
        finally:
            runtime_backend.reset_for_test()


@pytest.fixture()
def backend_bus_and_data_dir(bus_and_data_dir):
    bus, data_dir = bus_and_data_dir
    return "postgres", bus, data_dir


@pytest.mark.asyncio
async def test_backend_selection_matches_runtime_backend(bus_and_data_dir):
    _bus, _data_dir = bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    assert store.__class__.__name__ == "PostgresControlPlaneStore"


@pytest.mark.asyncio
async def test_submit_poll_complete_and_reply_round_trip(bus_and_data_dir):
    bus, data_dir = bus_and_data_dir
    from app import runtime_backend

    command = _command("cmd-roundtrip")

    command_id = await bus.submit(command)
    claimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
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
async def test_request_waits_for_processor_completion(bus_and_data_dir):
    bus, _data_dir = bus_and_data_dir
    command = _command(
        "cmd-request",
        admin_interface="task_routing",
        admin_operation="submit_routed_task",
        implementation_ref="registry:coord",
    )

    async def processor() -> None:
        while True:
            claimed = await bus.poll_commands(
                allowed_admin_targets={("registry:coord", "task_routing")},
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
async def test_poll_commands_is_pair_aware(bus_and_data_dir):
    bus, _data_dir = bus_and_data_dir
    await bus.submit(
        _command(
            "cmd-pair-aware",
            admin_interface="task_routing",
            admin_operation="submit_routed_task",
        )
    )

    wrong = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    right = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "task_routing")},
    )

    assert wrong == []
    assert [item.command_id for item in right] == ["cmd-pair-aware"]


@pytest.mark.asyncio
async def test_submit_deduplicates_by_idempotency_key(bus_and_data_dir):
    bus, _data_dir = bus_and_data_dir
    first = _command("cmd-idem-1", idempotency_key="key-1")
    second = _command("cmd-idem-2", idempotency_key="key-1")

    first_id = await bus.submit(first)
    second_id = await bus.submit(second)
    claimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )

    assert first_id == "cmd-idem-1"
    assert second_id == "cmd-idem-1"
    assert [item.command_id for item in claimed] == ["cmd-idem-1"]


@pytest.mark.asyncio
async def test_fail_respects_retry_backoff_before_requeue(bus_and_data_dir):
    bus, _data_dir = bus_and_data_dir
    await bus.submit(_command("cmd-retry", max_retries=2))
    claimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in claimed] == ["cmd-retry"]

    await bus.fail(
        "cmd-retry",
        claimed_at=claimed[0].claimed_at,
        error="transient failure",
    )

    immediate = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert immediate == []

    time.sleep(1.1)

    retried = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in retried] == ["cmd-retry"]


@pytest.mark.asyncio
async def test_reclaim_expired_consumes_retry_budget(bus_and_data_dir):
    bus, data_dir = bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-expired", max_retries=1))
    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-expired"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1

    time.sleep(1.1)
    reclaimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
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
async def test_stale_claim_token_cannot_complete_reclaimed_command(bus_and_data_dir):
    bus, data_dir = bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-stale-complete", max_retries=1))
    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-stale-complete"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1
    time.sleep(1.1)

    reclaimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
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
async def test_stale_claim_token_cannot_fail_reclaimed_command(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-stale-fail", max_retries=0))
    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-stale-fail"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1
    time.sleep(1.1)

    reclaimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in reclaimed] == ["cmd-stale-fail"]

    await bus.fail(
        "cmd-stale-fail",
        claimed_at=claimed[0].claimed_at,
        error="stale failure",
    )
    assert store.get_reply(data_dir, "cmd-stale-fail") is None

    await bus.fail(
        "cmd-stale-fail",
        claimed_at=reclaimed[0].claimed_at,
        error="current failure",
    )
    reply = store.get_reply(data_dir, "cmd-stale-fail")
    assert reply is not None
    assert reply.status == "failed"
    assert reply.error == "current failure"


@pytest.mark.asyncio
async def test_stale_claim_token_cannot_dead_letter_reclaimed_command(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-stale-dead-letter"))
    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-stale-dead-letter"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1
    time.sleep(1.1)

    reclaimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in reclaimed] == ["cmd-stale-dead-letter"]

    await bus.dead_letter(
        "cmd-stale-dead-letter",
        claimed_at=claimed[0].claimed_at,
        reason="stale dead-letter",
    )
    assert store.get_reply(data_dir, "cmd-stale-dead-letter") is None

    await bus.dead_letter(
        "cmd-stale-dead-letter",
        claimed_at=reclaimed[0].claimed_at,
        reason="current dead-letter",
    )
    reply = store.get_reply(data_dir, "cmd-stale-dead-letter")
    assert reply is not None
    assert reply.status == "failed"
    assert reply.error == "current dead-letter"


@pytest.mark.asyncio
async def test_stale_claim_token_cannot_renew_reclaimed_command(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    store.submit(data_dir, _command("cmd-stale-renew"))
    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        lease_seconds=0.01,
    )
    assert [item.command_id for item in claimed] == ["cmd-stale-renew"]

    time.sleep(0.05)
    assert store.reclaim_expired(data_dir) == 1
    time.sleep(1.1)

    reclaimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in reclaimed] == ["cmd-stale-renew"]

    assert not await bus.renew_lease(
        "cmd-stale-renew",
        claimed_at=claimed[0].claimed_at,
        extension_seconds=30.0,
    )
    assert await bus.renew_lease(
        "cmd-stale-renew",
        claimed_at=reclaimed[0].claimed_at,
        extension_seconds=30.0,
    )


@pytest.mark.asyncio
async def test_reconcile_orphans_dead_letters_removed_and_revoked_pairs(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    await bus.submit(_command("cmd-valid"))
    await bus.submit(_command("cmd-removed", implementation_ref="registry:gone"))
    await bus.submit(
        _command(
            "cmd-revoked",
            admin_interface="task_routing",
            admin_operation="submit_routed_task",
        )
    )

    dead = await bus.reconcile_orphans(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert dead == 2

    claimed = await bus.poll_commands(
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
    )
    assert [item.command_id for item in claimed] == ["cmd-valid"]
    assert store.get_reply(data_dir, "cmd-removed") is not None
    assert store.get_reply(data_dir, "cmd-revoked") is not None


@pytest.mark.asyncio
async def test_purge_old_commands_keeps_pending_and_claimed_rows(backend_bus_and_data_dir):
    _backend, bus, data_dir = backend_bus_and_data_dir
    from app import runtime_backend

    store = runtime_backend.control_plane_store()
    await bus.submit(_command("cmd-pending", implementation_ref="registry:beta"))
    await bus.submit(_command("cmd-claimed"))
    await bus.submit(_command("cmd-completed"))
    await bus.submit(_command("cmd-dead"))

    claimed = store.poll_commands(
        data_dir,
        allowed_admin_targets={("registry:alpha", "conversation_projection")},
        limit=3,
    )
    claimed_by_id = {item.command_id: item for item in claimed}
    assert set(claimed_by_id) == {"cmd-claimed", "cmd-completed", "cmd-dead"}

    await bus.complete(
        "cmd-completed",
        claimed_at=claimed_by_id["cmd-completed"].claimed_at,
        result_json='{"accepted": true}',
    )
    await bus.dead_letter(
        "cmd-dead",
        claimed_at=claimed_by_id["cmd-dead"].claimed_at,
        reason="cleanup test",
    )

    purged = await bus.purge_old_commands(older_than_hours=0)

    assert purged == 2
    assert store.get_reply(data_dir, "cmd-completed") is None
    assert store.get_reply(data_dir, "cmd-dead") is None
    assert await bus.renew_lease(
        "cmd-claimed",
        claimed_at=claimed_by_id["cmd-claimed"].claimed_at,
        extension_seconds=30.0,
    )

    pending = await bus.poll_commands(
        allowed_admin_targets={("registry:beta", "conversation_projection")},
    )
    assert [item.command_id for item in pending] == ["cmd-pending"]
