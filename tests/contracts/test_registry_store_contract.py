"""Registry store contract: backend-neutral behavior for SQLite and Postgres."""

from pathlib import Path
import re

import pytest

from app.registry_service.store import RegistrySQLiteStore
from app.registry_service.store_base import CapabilityDisabledError
from app.registry_service.store_base import PROTECTED_ROUTED_TASK_STATUSES
from app.registry_service.store_base import RegistryScopeError
from app.registry_service.store_base import hash_agent_token
from app.runtime_health import (
    QueueSnapshot,
    RuntimeDiagnostic,
    RuntimeHealthReport,
    RuntimeHealthSummary,
    SharedRuntimeSnapshot,
    WorkerHeartbeat,
    report_to_dict,
)


def _card(
    slug: str,
    capabilities: list[str] | None = None,
    *,
    registry_scope: str = "full",
) -> dict:
    return {
        "display_name": slug,
        "slug": slug,
        "role": "developer",
        "registry_scope": registry_scope,
        "capabilities": capabilities or ["python"],
        "tags": ["backend"],
        "description": f"{slug} description",
        "provider": "codex",
        "mode": "registry",
        "connectivity_state": "connected",
        "channel_capabilities": ["registry"],
        "version": "test",
    }


def _enroll(
    store,
    slug: str,
    capabilities: list[str] | None = None,
    *,
    registry_scope: str = "full",
) -> tuple[str, str]:
    enrolled = store.enroll(_card(slug, capabilities, registry_scope=registry_scope))
    store.register(
        enrolled["agent_token"],
        {
            "agent_card": _card(slug, capabilities, registry_scope=registry_scope),
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    return enrolled["agent_id"], enrolled["agent_token"]


def _runtime_health_payload(*, worker_count: int = 2) -> dict:
    workers = tuple(
        WorkerHeartbeat(
            worker_id=f"worker-{idx}",
            process_role="worker",
            started_at="2026-03-16T00:00:00+00:00",
            last_seen_at=f"2026-03-16T00:00:0{idx}+00:00",
            current_item_id=f"item-{idx}",
            current_conversation_key=f"tg:{idx}",
            current_kind="message",
            items_processed=idx,
            stale_recoveries_seen=0,
            last_error="",
        )
        for idx in range(1, worker_count + 1)
    )
    snapshot = SharedRuntimeSnapshot(
        queue=QueueSnapshot(
            fresh_queued_count=3,
            claimed_count=1,
            pending_recovery_count=0,
            recovery_queued_count=1,
            oldest_claimed_at="2026-03-16T00:00:00+00:00",
        ),
        workers=workers,
        healthy_worker_count=worker_count,
        stale_worker_count=0,
    )
    report = RuntimeHealthReport(
        generated_at="2026-03-16T00:00:10+00:00",
        summary=RuntimeHealthSummary(
            status="degraded",
            healthy_worker_count=worker_count,
            stale_worker_count=0,
            fresh_queued_count=3,
            claimed_count=1,
            pending_recovery_count=0,
            recovery_queued_count=1,
            oldest_claim_age_seconds=10,
            warning_count=1,
            error_count=0,
        ),
        snapshot=snapshot,
        diagnostics=(
            RuntimeDiagnostic(
                level="warning",
                code="shared.pending_recovery_backlog",
                message="Something needs review.",
            ),
        ),
    )
    return report_to_dict(report)


def _stored_agent_token(store, agent_id: str) -> str:
    if isinstance(store, RegistrySQLiteStore):
        with store._connect() as conn:
            row = conn.execute(
                "SELECT agent_token FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        assert row is not None
        return str(row["agent_token"])

    from app.registry_service.store_postgres import RegistryPostgresStore, _SCHEMA
    from psycopg.rows import dict_row

    assert isinstance(store, RegistryPostgresStore)
    with store._connect() as conn:
        cur = conn.cursor(row_factory=dict_row)
        try:
            cur.execute(
                f"SELECT agent_token FROM {_SCHEMA}.agents WHERE agent_id = %s",
                (agent_id,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
    assert row is not None
    return str(row["agent_token"])


def _routed_task_row(store, routed_task_id: str):
    if isinstance(store, RegistrySQLiteStore):
        with store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM routed_tasks WHERE routed_task_id = ?",
                (routed_task_id,),
            ).fetchone()
        assert row is not None
        return row

    from app.registry_service.store_postgres import RegistryPostgresStore, _SCHEMA
    from psycopg.rows import dict_row

    assert isinstance(store, RegistryPostgresStore)
    with store._connect() as conn:
        cur = conn.cursor(row_factory=dict_row)
        try:
            cur.execute(
                f"SELECT * FROM {_SCHEMA}.routed_tasks WHERE routed_task_id = %s",
                (routed_task_id,),
            )
            row = cur.fetchone()
        finally:
            cur.close()
    assert row is not None
    return row


def _create_routed_task(store, *, routed_task_id: str = "task-1") -> tuple[dict, str, str, str]:
    origin_id, _origin_token = _enroll(store, f"origin-{routed_task_id}")
    target_id, target_token = _enroll(store, f"target-{routed_task_id}", ["reviewer"])
    routed = store.create_routed_task(
        {
            "routed_task_id": routed_task_id,
            "parent_conversation_id": f"conv-{routed_task_id}",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review task",
            "instructions": "Review the spec.",
            "context": {},
            "constraints": {},
            "requested_capabilities": ["reviewer"],
            "priority": "normal",
            "created_at": "2026-03-16T00:00:00+00:00",
        }
    )
    return routed, origin_id, target_id, target_token


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path: Path):
    if request.param == "sqlite":
        yield RegistrySQLiteStore(tmp_path / "registry.sqlite3")
        return

    postgres_url = request.getfixturevalue("postgres_registry_truncated")
    from app.registry_service.store_postgres import RegistryPostgresStore

    yield RegistryPostgresStore(postgres_url)


def test_enroll_and_register_returns_agent_id(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    assert agent_id
    assert agent_token
    agents = store.list_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == agent_id


def test_enroll_persists_registry_scope(store):
    agent_id, _agent_token = _enroll(store, "channel-bot", registry_scope="channel")

    agents = store.list_agents()

    assert len(agents) == 1
    assert agents[0]["agent_id"] == agent_id
    assert agents[0]["registry_scope"] == "channel"


def test_enroll_hashes_agent_token_at_rest(store):
    agent_id, agent_token = _enroll(store, "hashed-bot")

    stored = _stored_agent_token(store, agent_id)

    assert stored == hash_agent_token(agent_token)
    assert stored != agent_token
    assert re.fullmatch(r"[0-9a-f]{64}", stored)


def test_poll_delivers_to_enrolled_agent(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    delivery = store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )

    polled = store.poll(agent_token, cursor=0, limit=20)

    assert delivery["delivery_id"]
    assert len(polled["deliveries"]) == 1
    assert polled["deliveries"][0]["kind"] == "channel_input"
    assert polled["deliveries"][0]["payload"]["text"] == "hello"


def test_ack_marks_delivery_done(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )

    polled = store.poll(agent_token, cursor=0, limit=20)
    delivery_id = polled["deliveries"][0]["delivery_id"]
    store.ack(agent_token, delivery_ids=[delivery_id], classification="accepted")

    assert store.poll(agent_token, cursor=0, limit=20)["deliveries"] == []


def test_search_agents_by_capability(store):
    _enroll(store, "rust-bot", ["rust"])

    hits = store.search_agents({"capabilities": ["rust"], "required_state": "connected"})
    misses = store.search_agents({"capabilities": ["python"], "required_state": "connected"})

    assert [item["slug"] for item in hits] == ["rust-bot"]
    assert misses == []


def test_search_agents_excludes_offline(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.deregister(agent_token)

    assert store.search_agents({"required_state": "connected"}) == []


def test_create_routed_task_and_lookup(store):
    routed, origin_id, target_id, target_token = _create_routed_task(
        store, routed_task_id="task-1"
    )

    deliveries = store.poll(target_token, cursor=0, limit=20)["deliveries"]

    assert routed["routed_task_id"] == "task-1"
    assert routed["delivery_id"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "routed_task"


@pytest.mark.parametrize("protected_status", PROTECTED_ROUTED_TASK_STATUSES)
def test_routed_task_status_updates_do_not_overwrite_protected_status(store, protected_status):
    routed_task_id = f"task-status-{protected_status}"
    protected_summary = f"{protected_status} summary"
    _routed, _origin_id, _target_id, target_token = _create_routed_task(
        store, routed_task_id=routed_task_id
    )

    if protected_status == "completed":
        store.update_routed_task_result(
            target_token,
            routed_task_id,
            {
                "status": "completed",
                "summary": protected_summary,
                "full_text": "Full result",
            },
        )
    else:
        store.update_routed_task_status(
            target_token,
            routed_task_id,
            {
                "status": protected_status,
                "summary": protected_summary,
                "timeline_events": [],
            },
        )

    store.update_routed_task_status(
        target_token,
        routed_task_id,
        {
            "status": "running",
            "summary": "late progress",
            "timeline_events": [],
        },
    )

    task = _routed_task_row(store, routed_task_id)

    assert task["status"] == protected_status
    assert task["summary"] == protected_summary
    if protected_status == "completed":
        assert "Full result" in str(task["result_json"])


def test_routed_task_result_can_overwrite_partialfailed(store):
    _routed, _origin_id, _target_id, target_token = _create_routed_task(
        store, routed_task_id="task-status-recovered"
    )

    store.update_routed_task_status(
        target_token,
        "task-status-recovered",
        {
            "status": "partialfailed",
            "summary": "delivery failed",
            "timeline_events": [],
        },
    )

    store.update_routed_task_result(
        target_token,
        "task-status-recovered",
        {
            "status": "completed",
            "summary": "done",
            "full_text": "Recovered result",
        },
    )

    task = _routed_task_row(store, "task-status-recovered")

    assert task["status"] == "completed"
    assert task["summary"] == "done"
    assert "Recovered result" in str(task["result_json"])


def test_assert_agent_scope_rejects_wrong_scope(store):
    _, agent_token = _enroll(store, "channel-bot", registry_scope="channel")

    with pytest.raises(RegistryScopeError):
        store.assert_agent_scope(agent_token, {"coordination", "full"})


def test_channel_scope_poll_filters_routed_deliveries(store):
    agent_id, agent_token = _enroll(store, "channel-bot", registry_scope="channel")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )
    store.create_delivery(
        target_agent_id=agent_id,
        kind="routed_task",
        payload={"routed_task_id": "task-1"},
    )

    deliveries = store.poll(agent_token, cursor=0, limit=20)["deliveries"]

    assert [item["kind"] for item in deliveries] == ["channel_input"]


def test_coordination_scope_poll_filters_channel_deliveries(store):
    agent_id, agent_token = _enroll(store, "coord-bot", registry_scope="coordination")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )
    store.create_delivery(
        target_agent_id=agent_id,
        kind="routed_task",
        payload={"routed_task_id": "task-1"},
    )

    deliveries = store.poll(agent_token, cursor=0, limit=20)["deliveries"]

    assert [item["kind"] for item in deliveries] == ["routed_task"]


def test_create_routed_task_disabled_capability_raises(store):
    origin_id, _ = _enroll(store, "origin-bot")
    target_id, _ = _enroll(store, "target-bot", ["reviewer"])
    store.set_capability_override("reviewer", enabled=False)

    with pytest.raises(CapabilityDisabledError):
        store.create_routed_task(
            {
                "routed_task_id": "task-disabled",
                "parent_conversation_id": "conv-1",
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": "Disabled review task",
                "skill": "reviewer",
                "instructions": "Review the spec.",
                "context": {},
                "constraints": {},
                "priority": "normal",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        )


def test_bind_conversation_is_visible(store):
    _, agent_token = _enroll(store, "alpha-bot")

    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "c1",
            "title": "Conversation 1",
            "origin_channel": "telegram",
        },
    )

    conversations = store.list_conversations()
    assert [item["conversation_id"] for item in conversations] == ["c1"]


def test_create_conversation_delivers_channel_input(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    conversation = store.create_conversation(
        target_agent_id=agent_id,
        title="Registry conversation",
        message_text="hello from registry",
    )
    deliveries = store.poll(agent_token, cursor=0, limit=20)["deliveries"]

    assert conversation["conversation_id"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "channel_input"
    assert deliveries[0]["payload"]["text"] == "hello from registry"


def test_timeline_publish_and_retrieve(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-1",
            "title": "Bound conversation",
            "origin_channel": "registry",
        },
    )

    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-1",
                "conversation_id": "conv-1",
                "kind": "progress",
                "title": "Working",
                "body": "Doing the work",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    events = store.get_conversation_timeline("conv-1")
    assert len(events) == 1
    assert events[0]["kind"] == "progress"
    assert events[0]["body"] == "Doing the work"


def test_usage_summary_from_timeline(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-usage",
            "title": "Usage conversation",
            "origin_channel": "registry",
        },
    )
    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-usage",
                "conversation_id": "conv-usage",
                "kind": "usage",
                "title": "Token usage",
                "body": "",
                "metadata": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "cost_usd": 0.0123,
                    "provider": "claude",
                },
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    rows = store.get_usage_summary("2026-03-15T00:00:00+00:00")

    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "conv-usage"
    assert rows[0]["metadata"]["prompt_tokens"] == 123
    assert rows[0]["metadata"]["completion_tokens"] == 45


def test_heartbeat_persists_runtime_health_and_workers(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    store.heartbeat(
        agent_token,
        {
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
            "runtime_health": _runtime_health_payload(worker_count=2),
        },
    )

    listed = store.list_agents()
    assert listed[0]["runtime_health_summary"]["status"] == "degraded"
    assert listed[0]["runtime_health_summary"]["healthy_worker_count"] == 2
    detail = store.get_agent_runtime_health(agent_id)
    assert detail is not None
    assert detail["report"]["summary"]["claimed_count"] == 1
    assert len(detail["workers"]) == 2


def test_heartbeat_replaces_missing_worker_rows(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    first = _runtime_health_payload(worker_count=2)
    second = _runtime_health_payload(worker_count=1)
    second["generated_at"] = "2026-03-16T00:00:20+00:00"
    second["summary"]["healthy_worker_count"] = 1

    store.heartbeat(
        agent_token,
        {
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
            "runtime_health": first,
        },
    )
    store.heartbeat(
        agent_token,
        {
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
            "runtime_health": second,
        },
    )

    detail = store.get_agent_runtime_health(agent_id)
    assert detail is not None
    assert detail["last_mirrored_at"] == "2026-03-16T00:00:20+00:00"
    assert [row["worker_id"] for row in detail["workers"]] == ["worker-1"]


def test_search_conversations_fts(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-search",
            "title": "Search conversation",
            "origin_channel": "registry",
        },
    )
    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-search",
                "conversation_id": "conv-search",
                "kind": "progress",
                "title": "Search body",
                "body": "the quick brown fox",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    results = store.search_conversations("quick")

    assert len(results) == 1
    assert results[0]["conversation_id"] == "conv-search"
    assert results[0]["snippet"]


def test_capability_override_disabled_excludes_from_search(store):
    _enroll(store, "rust-bot", ["rust"])
    store.set_capability_override("rust", enabled=False)

    assert store.search_agents({"capabilities": ["rust"], "required_state": "connected"}) == []


def test_list_capabilities_aggregates_declared(store):
    _enroll(store, "alpha-bot", ["python"])
    _enroll(store, "beta-bot", ["python"])

    capabilities = {item["capability_name"]: item for item in store.list_capabilities()}

    assert "python" in capabilities
    assert capabilities["python"]["declared_by_agents"] == ["alpha-bot", "beta-bot"]


def test_capability_override_survives_agent_deregistration(store):
    _, agent_token = _enroll(store, "go-bot", ["go"])
    store.set_capability_override("go", enabled=False)
    store.deregister(agent_token)

    capabilities = {item["capability_name"]: item for item in store.list_capabilities()}

    assert capabilities["go"]["enabled"] is False
    assert capabilities["go"]["declared_by_agents"] == []
