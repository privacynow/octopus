"""Registry store contract: Postgres-backed registry behavior."""

from datetime import datetime, timezone
import re

import pytest
from pydantic import ValidationError

from octopus_registry.store_base import RoutingSkillDisabledError
from octopus_registry.store_base import PROTECTED_ROUTED_TASK_STATUSES
from octopus_registry.store_base import RegistryScopeError
from octopus_registry.store_base import conversation_status_for_event
from octopus_registry.store_base import hash_agent_token
from octopus_registry.store_postgres import RegistryPostgresStore, _SCHEMA
from app.runtime_health import (
    QueueSnapshot,
    RuntimeDiagnostic,
    RuntimeHealthReport,
    RuntimeHealthSummary,
    SharedRuntimeSnapshot,
    WorkerHeartbeat,
    report_to_dict,
)
from octopus_sdk.registry.models import (
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
    ApproveDelegationActionPayload,
    ApproveRejectActionPayload,
    CancelTaskActionPayload,
    CoordinationActionEnvelope,
    DelegateTasksActionPayload,
    DelegationTaskDraft,
    DirectAssignActionPayload,
    EventRecord,
    RegistryJsonRecord,
    RuntimeHealthDiagnosticRecord,
    RuntimeHealthPayload,
    RuntimeHealthSummaryRecord,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    TargetSelector,
    TimelineEventPayload,
)


def _card(
    slug: str,
    routing_skills: list[str] | None = None,
    *,
    display_name: str | None = None,
    registry_scope: str = "full",
) -> AgentCard:
    return AgentCard(
        display_name=display_name or slug,
        slug=slug,
        role="developer",
        registry_scope=registry_scope,
        routing_skills=routing_skills or ["python"],
        tags=["backend"],
        description=f"{slug} description",
        provider="codex",
        mode="registry",
        connectivity_state="connected",
        channel_capabilities=["registry"],
        version="test",
        bot_key=f"bot-{slug}",
    )


def _enroll(
    store,
    slug: str,
    routing_skills: list[str] | None = None,
    *,
    display_name: str | None = None,
    registry_scope: str = "full",
) -> tuple[str, str]:
    enrolled = store.enroll(_card(slug, routing_skills, display_name=display_name, registry_scope=registry_scope))
    store.register(
        enrolled.agent_token,
        AgentRegisterRequest(
            agent_card=_card(slug, routing_skills, display_name=display_name, registry_scope=registry_scope),
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=2,
        ),
    )
    return enrolled.agent_id, enrolled.agent_token


def _runtime_health_payload(
    *,
    worker_count: int = 2,
    generated_at: str = "2026-03-16T00:00:10+00:00",
) -> RuntimeHealthPayload:
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
    wire = report_to_dict(report)
    return RuntimeHealthPayload(
        schema_version=int(wire["schema_version"]),
        generated_at=generated_at,
        summary=RuntimeHealthSummaryRecord.model_validate(wire["summary"]),
        snapshot=RegistryJsonRecord(wire["snapshot"]),
        diagnostics=[
            RuntimeHealthDiagnosticRecord.model_validate(item)
            for item in wire["diagnostics"]
        ],
    )


def _stored_agent_token(store, agent_id: str) -> str:
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


def _create_routed_task(
    store,
    *,
    routed_task_id: str = "task-1",
) -> tuple[object, str, str, str, str]:
    origin_id, _origin_token = _enroll(store, f"origin-{routed_task_id}")
    target_id, target_token = _enroll(store, f"target-{routed_task_id}", ["reviewer"])
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title=f"Conversation {routed_task_id}",
        origin_channel="registry",
        external_conversation_ref=f"conv-{routed_task_id}",
    )
    routed = store.create_routed_task(
        RoutedTaskRequest(
            routed_task_id=routed_task_id,
            parent_conversation_id=conversation.conversation_id,
            origin_transport_ref=f"telegram:origin:{routed_task_id}",
            origin_agent_id=origin_id,
            target_agent_id=target_id,
            title="Review task",
            instructions="Review the spec.",
            context=RegistryJsonRecord(),
            constraints=RegistryJsonRecord(),
            requested_skills=["reviewer"],
            priority="normal",
            created_at="2026-03-16T00:00:00+00:00",
        )
    )
    return routed, origin_id, target_id, target_token, conversation.conversation_id


def _lease_routed_task(store, target_token: str) -> None:
    deliveries = store.poll(target_token, cursor=0, limit=20).deliveries
    assert any(item.kind == "routed_task" for item in deliveries)


def _start_routed_task(store, target_token: str, routed_task_id: str) -> None:
    store.update_routed_task_status(
        target_token,
        routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=routed_task_id,
            status="running",
            transition_id=f"{routed_task_id}-start",
            summary="started",
            timeline_events=[],
        ),
    )


@pytest.fixture()
def store(postgres_registry_truncated: str):
    yield RegistryPostgresStore(postgres_registry_truncated)


def test_enroll_and_register_returns_agent_id(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    assert agent_id
    assert agent_token
    agents = store.list_agents()
    assert len(agents) == 1
    assert agents[0].agent_id == agent_id


def test_enroll_persists_registry_scope(store):
    agent_id, _agent_token = _enroll(store, "channel-bot", registry_scope="channel")

    agents = store.list_agents()

    assert len(agents) == 1
    assert agents[0].agent_id == agent_id
    assert agents[0].registry_scope == "channel"


def test_enroll_requires_explicit_registry_scope(store):
    with pytest.raises(ValueError, match="registry_scope"):
        store.enroll(
            {
                "display_name": "Missing Scope Bot",
                "slug": "missing-scope-bot",
                "role": "developer",
                "routing_skills": ["python"],
                "tags": ["backend"],
                "description": "Missing scope",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "version": "test",
            }
        )


def test_enroll_hashes_agent_token_at_rest(store):
    agent_id, agent_token = _enroll(store, "hashed-bot")

    stored = _stored_agent_token(store, agent_id)

    assert stored == hash_agent_token(agent_token)
    assert stored != agent_token
    assert re.fullmatch(r"[0-9a-f]{64}", stored)


def test_enroll_and_poll_expose_stable_registry_epoch(store):
    enrolled = store.enroll(_card("epoch-bot"))
    store.register(
        enrolled.agent_token,
        AgentRegisterRequest(
            agent_card=_card("epoch-bot"),
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
        ),
    )

    polled = store.poll(enrolled.agent_token, cursor=0, limit=20)

    assert enrolled.registry_epoch
    assert polled.registry_epoch == enrolled.registry_epoch


def test_poll_delivers_to_enrolled_agent(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    delivery = store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )

    polled = store.poll(agent_token, cursor=0, limit=20)

    assert delivery.delivery_id
    assert len(polled.deliveries) == 1
    assert polled.deliveries[0].kind == "channel_input"
    assert polled.deliveries[0].payload["text"] == "hello"


def test_ack_marks_delivery_done(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )

    polled = store.poll(agent_token, cursor=0, limit=20)
    delivery_id = polled.deliveries[0].delivery_id
    store.ack(agent_token, delivery_ids=[delivery_id], classification="accepted")

    assert store.poll(agent_token, cursor=0, limit=20).deliveries == []


def test_poll_redelivers_leased_delivery_when_cursor_did_not_advance(store):
    agent_id, agent_token = _enroll(store, "leased-bot")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )

    first = store.poll(agent_token, cursor=0, limit=20)
    second = store.poll(agent_token, cursor=0, limit=20)

    assert len(first.deliveries) == 1
    assert len(second.deliveries) == 1
    assert second.deliveries[0].delivery_id == first.deliveries[0].delivery_id
    assert second.deliveries[0].state == "leased"

    store.ack(agent_token, delivery_ids=[first.deliveries[0].delivery_id], classification="accepted")

    assert store.poll(agent_token, cursor=0, limit=20).deliveries == []


def test_conversation_status_transitions_cover_running_terminal_and_cancelling_states():
    # SDK kind names
    assert conversation_status_for_event("message.user", "open") == "running"
    assert conversation_status_for_event("message.bot", "running") == "running"
    assert conversation_status_for_event("message.bot", "cancelling") == "cancelling"
    assert conversation_status_for_event("task.status", "running") == "running"
    assert conversation_status_for_event("error", "running") == "failed"
    assert conversation_status_for_event("approval.decided", "open") == "open"


def test_ack_rejects_invalid_classification(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )
    polled = store.poll(agent_token, cursor=0, limit=20)
    delivery_id = polled.deliveries[0].delivery_id

    with pytest.raises(ValueError, match="classification"):
        store.ack(agent_token, delivery_ids=[delivery_id], classification="later")


def test_search_agents_by_skill(store):
    _enroll(store, "rust-bot", ["rust"])

    hits = store.search_agents(AgentDiscoveryQuery(skills=["rust"], required_state="connected"))
    misses = store.search_agents(AgentDiscoveryQuery(skills=["python"], required_state="connected"))

    assert [item.slug for item in hits] == ["rust-bot"]
    assert misses == []


def test_search_agents_excludes_disconnected(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.deregister(agent_token)

    assert store.search_agents(AgentDiscoveryQuery(required_state="connected")) == []


def test_create_routed_task_and_lookup(store):
    routed, origin_id, target_id, target_token, _conversation_id = _create_routed_task(
        store, routed_task_id="task-1"
    )
    task = store.get_task("task-1")

    deliveries = store.poll(target_token, cursor=0, limit=20).deliveries

    assert routed.routed_task_id == "task-1"
    assert routed.delivery_id
    assert task.origin_transport_ref == "telegram:origin:task-1"
    assert task.request["origin_transport_ref"] == "telegram:origin:task-1"
    assert len(deliveries) == 1
    assert deliveries[0].kind == "routed_task"
    assert deliveries[0].payload["external_conversation_ref"] == "routed-task:task-1"


def test_create_routed_task_creates_recipient_conversation_projection(store):
    routed, _origin_id, target_id, target_token, _conversation_id = _create_routed_task(
        store,
        routed_task_id="task-recipient-projection",
    )

    deliveries = store.poll(target_token, cursor=0, limit=20).deliveries
    conversations = store.list_conversations(for_agent_id=target_id, limit=25)
    recipient_conversation = next(
        conversation
        for conversation in conversations
        if conversation.external_conversation_ref == "routed-task:task-recipient-projection"
    )
    events = store.list_events(recipient_conversation.conversation_id).events

    assert len(deliveries) == 1
    assert deliveries[0].payload["external_conversation_ref"] == "routed-task:task-recipient-projection"
    assert recipient_conversation.origin_channel == "registry"
    assert recipient_conversation.conversation_type == "task_thread"
    assert routed.recipient_conversation_id == recipient_conversation.conversation_id
    assert routed.recipient_inserted_events
    assert routed.recipient_inserted_events[0].conversation_id == recipient_conversation.conversation_id
    assert events
    assert events[0].kind == "task.status"
    assert events[0].metadata["status"] == "queued"


def test_list_conversations_can_filter_by_conversation_type(store):
    _routed, origin_id, target_id, target_token, _conversation_id = _create_routed_task(
        store,
        routed_task_id="task-filter-task-thread",
    )
    regular = store.create_conversation(
        target_agent_id=target_id,
        title="Regular conversation",
        origin_channel="telegram",
        external_conversation_ref="telegram:bot-filter:12345",
    )

    task_threads = store.list_conversations(
        for_agent_id=target_id,
        limit=25,
        conversation_type="task_thread",
    )
    regular_only = store.list_conversations(
        for_agent_id=target_id,
        limit=25,
        conversation_type="conversation",
    )

    assert all(item.conversation_type == "task_thread" for item in task_threads)
    assert all(item.conversation_type == "conversation" for item in regular_only)
    assert any(item.external_conversation_ref == "routed-task:task-filter-task-thread" for item in task_threads)


def test_recipient_task_thread_type_survives_status_and_result_updates(store):
    routed_task_id = "task-thread-survives"
    _routed, _origin_id, target_id, target_token, _conversation_id = _create_routed_task(
        store,
        routed_task_id=routed_task_id,
    )
    recipient = next(
        item
        for item in store.list_conversations(for_agent_id=target_id, limit=50)
        if item.external_conversation_ref == f"routed-task:{routed_task_id}"
    )
    assert recipient.conversation_type == "task_thread"

    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, routed_task_id)

    after_status = store.get_conversation(recipient.conversation_id)
    assert after_status.conversation_type == "task_thread"

    store.update_routed_task_result(
        target_token,
        routed_task_id,
        RoutedTaskResult(
            routed_task_id=routed_task_id,
            status="completed",
            transition_id=f"{routed_task_id}-complete",
            summary="done",
            full_text="done",
        ),
    )

    after_result = store.get_conversation(recipient.conversation_id)
    assert after_result.conversation_type == "task_thread"


def test_create_routed_task_mirrors_parent_conversation_event(store):
    routed, _origin_id, _target_id, _target_token, conversation_id = _create_routed_task(
        store, routed_task_id="task-mirror-create"
    )

    events = store.list_events(conversation_id).events

    assert routed.events_written is True
    assert routed.inserted_events[0].seq and routed.inserted_events[0].seq > 0
    assert len(events) == 1
    assert events[0].kind == "task.status"
    assert events[0].metadata == {"routed_task_id": "task-mirror-create", "status": "queued"}
    assert events[0].seq == routed.inserted_events[0].seq


def test_create_routed_task_requires_required_fields(store):
    origin_id, _origin_token = _enroll(store, "origin-create")
    target_id, _target_token = _enroll(store, "target-create", ["reviewer"])
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Create validation conversation",
        origin_channel="registry",
        external_conversation_ref="conv-create",
    )

    with pytest.raises(ValueError, match="title"):
        store.create_routed_task(
            RoutedTaskRequest(
                routed_task_id="task-missing-title",
                parent_conversation_id=conversation.conversation_id,
                origin_agent_id=origin_id,
                target_agent_id=target_id,
                title="",
                instructions="Review the spec.",
                requested_skills=["reviewer"],
            )
        )


@pytest.mark.parametrize("protected_status", ("completed", "failed", "cancelled", "timed_out"))
def test_routed_task_status_updates_do_not_overwrite_protected_status(store, protected_status):
    routed_task_id = f"task-status-{protected_status}"
    protected_summary = f"{protected_status} summary"
    _routed, _origin_id, _target_id, target_token, conversation_id = _create_routed_task(
        store, routed_task_id=routed_task_id
    )
    _lease_routed_task(store, target_token)

    if protected_status == "completed":
        _start_routed_task(store, target_token, routed_task_id)
        store.update_routed_task_result(
            target_token,
            routed_task_id,
            RoutedTaskResult(
                status="completed",
                transition_id=f"{routed_task_id}-complete",
                summary=protected_summary,
                full_text="Full result",
                routed_task_id=routed_task_id,
            ),
        )
    elif protected_status == "failed":
        _start_routed_task(store, target_token, routed_task_id)
        store.update_routed_task_status(
            target_token,
            routed_task_id,
            RoutedTaskUpdate(
                routed_task_id=routed_task_id,
                status="failed",
                transition_id=f"{routed_task_id}-{protected_status}",
                summary=protected_summary,
                timeline_events=[],
            ),
        )
    elif protected_status == "cancelled":
        store.add_conversation_action(
            conversation_id,
            CoordinationActionEnvelope(
                action_id=f"{routed_task_id}-cancel",
                action="cancel_task",
                payload=CancelTaskActionPayload(routed_task_id=routed_task_id),
            ),
        )
    else:
        store.update_routed_task_status(
            target_token,
            routed_task_id,
            RoutedTaskUpdate(
                routed_task_id=routed_task_id,
                status=protected_status,
                transition_id=f"{routed_task_id}-{protected_status}",
                summary=protected_summary,
                timeline_events=[],
            ),
        )

    with pytest.raises(ValueError):
        store.update_routed_task_status(
            target_token,
            routed_task_id,
            RoutedTaskUpdate(
                routed_task_id=routed_task_id,
                status="running",
                transition_id=f"{routed_task_id}-late-progress",
                summary="late progress",
                timeline_events=[],
            ),
        )

    task = _routed_task_row(store, routed_task_id)

    assert task["status"] == protected_status
    if protected_status == "cancelled":
        assert task["summary"] == "Cancelled by operator."
    else:
        assert task["summary"] == protected_summary
    if protected_status == "completed":
        assert "Full result" in str(task["result_json"])

def test_routed_task_status_and_result_auto_mirror_events(store):
    _routed, _origin_id, _target_id, target_token, conversation_id = _create_routed_task(
        store, routed_task_id="task-auto-mirror"
    )
    _lease_routed_task(store, target_token)

    status_result = store.update_routed_task_status(
        target_token,
        "task-auto-mirror",
        RoutedTaskUpdate(
            routed_task_id="task-auto-mirror",
            status="running",
            transition_id="task-auto-mirror-running",
            summary="halfway there",
            timeline_events=[],
        ),
    )
    result_result = store.update_routed_task_result(
        target_token,
        "task-auto-mirror",
        RoutedTaskResult(
            routed_task_id="task-auto-mirror",
            status="completed",
            transition_id="task-auto-mirror-complete",
            summary="done",
            full_text="All set",
            completed_at="2026-03-16T00:01:00+00:00",
        ),
    )

    events = store.list_events(conversation_id).events
    recipient_conversation = next(
        conversation
        for conversation in store.list_conversations(limit=25)
        if conversation.external_conversation_ref == "routed-task:task-auto-mirror"
    )
    recipient_events = store.list_events(recipient_conversation.conversation_id).events

    assert status_result.events_written is True
    assert status_result.inserted_events[0].seq and status_result.inserted_events[0].seq > 0
    assert status_result.recipient_conversation_id == recipient_conversation.conversation_id
    assert status_result.recipient_inserted_events
    assert status_result.recipient_inserted_events[0].conversation_id == recipient_conversation.conversation_id
    assert result_result.events_written is True
    assert result_result.inserted_events[0].seq and result_result.inserted_events[0].seq > 0
    assert result_result.recipient_conversation_id == recipient_conversation.conversation_id
    assert result_result.recipient_inserted_events
    assert result_result.recipient_inserted_events[0].conversation_id == recipient_conversation.conversation_id
    assert [event.metadata["status"] for event in events] == ["queued", "running", "completed"]
    assert [event.metadata["status"] for event in recipient_events] == ["queued", "running", "completed"]


def test_list_tasks_can_filter_by_parent_conversation_id(store):
    first, origin_id, target_id, _token, conversation_id = _create_routed_task(
        store,
        routed_task_id="task-parent-filter-1",
    )
    second_conversation = store.create_conversation(
        target_agent_id=target_id,
        origin_channel="registry",
        external_conversation_ref="parent-filter-conv-2",
        title="Second parent",
    )
    store.create_routed_task(
        RoutedTaskRequest(
            routed_task_id="task-parent-filter-2",
            parent_conversation_id=second_conversation.conversation_id,
            origin_agent_id=origin_id,
            target_agent_id=target_id,
            title="Second task",
            instructions="Do second work.",
            created_at="2026-03-25T00:00:00+00:00",
        )
    )

    tasks = store.list_tasks(parent_conversation_id=conversation_id)
    assert [task.routed_task_id for task in tasks] == [first.routed_task_id]


def test_list_tasks_can_filter_by_completed_since_iso(store):
    old_task_id = "task-completed-old"
    recent_task_id = "task-completed-recent"

    _routed, _origin_id, _target_id, target_token, _conversation_id = _create_routed_task(
        store,
        routed_task_id=old_task_id,
    )
    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, old_task_id)
    store.update_routed_task_result(
        target_token,
        old_task_id,
        RoutedTaskResult(
            routed_task_id=old_task_id,
            status="completed",
            transition_id=f"{old_task_id}-complete",
            summary="done",
            full_text="Older completion",
            completed_at="2026-03-15T00:00:00+00:00",
        ),
    )

    _routed, _origin_id, _target_id, target_token, _conversation_id = _create_routed_task(
        store,
        routed_task_id=recent_task_id,
    )
    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, recent_task_id)
    store.update_routed_task_result(
        target_token,
        recent_task_id,
        RoutedTaskResult(
            routed_task_id=recent_task_id,
            status="completed",
            transition_id=f"{recent_task_id}-complete",
            summary="done",
            full_text="Recent completion",
            completed_at="2026-03-16T00:30:00+00:00",
        ),
    )

    tasks = store.list_tasks(
        status="completed",
        completed_since_iso="2026-03-16T00:00:00+00:00",
    )

    assert [task.routed_task_id for task in tasks] == [recent_task_id]


def test_list_agents_supports_query_and_connectivity_filters(store):
    _enroll(store, "alpha-reviewer")
    beta_id, beta_token = _enroll(store, "beta-builder")
    store.deregister(beta_token)

    q_hits = store.list_agents(q="review")
    connected_hits = store.list_agents(connectivity_state="connected")
    disconnected_hits = store.list_agents(connectivity_state="disconnected")

    assert [item.slug for item in q_hits] == ["alpha-reviewer"]
    assert {item.slug for item in connected_hits} == {"alpha-reviewer"}
    assert [item.agent_id for item in disconnected_hits] == [beta_id]


def test_routed_task_status_requires_explicit_non_empty_status(store):
    _routed, _origin_id, _target_id, target_token, _conversation_id = _create_routed_task(
        store, routed_task_id="task-status-required"
    )

    with pytest.raises(ValueError, match="status"):
        store.update_routed_task_status(
            target_token,
            "task-status-required",
            RoutedTaskUpdate(
                routed_task_id="task-status-required",
                transition_id="task-status-required-transition",
                summary="missing status",
                timeline_events=[],
            ),
        )


def test_routed_task_result_requires_explicit_non_empty_status(store):
    _routed, _origin_id, _target_id, target_token, _conversation_id = _create_routed_task(
        store, routed_task_id="task-result-required"
    )

    with pytest.raises(ValueError, match="status"):
        store.update_routed_task_result(
            target_token,
            "task-result-required",
            RoutedTaskResult(
                routed_task_id="task-result-required",
                transition_id="task-result-required-transition",
                summary="missing status",
                full_text="No explicit status",
                status="",
            ),
        )


def test_routed_task_status_rejection_does_not_upsert_timeline_events(store):
    routed_task_id = "task-status-no-timeline-upsert"
    _routed, _origin_id, _target_id, target_token, _conversation_id = _create_routed_task(
        store, routed_task_id=routed_task_id
    )
    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, routed_task_id)

    store.update_routed_task_result(
        target_token,
        routed_task_id,
        RoutedTaskResult(
            routed_task_id=routed_task_id,
            status="completed",
            transition_id=f"{routed_task_id}-complete",
            summary="done",
            full_text="Final result",
        ),
    )

    assert store.list_events("conv-blocked-timeline").events == []

    with pytest.raises(ValueError):
        store.update_routed_task_status(
            target_token,
            routed_task_id,
            RoutedTaskUpdate(
                routed_task_id=routed_task_id,
                status="running",
                transition_id=f"{routed_task_id}-late-progress",
                summary="late progress",
                timeline_events=[
                    TimelineEventPayload(
                        event_id="evt-blocked-timeline",
                        conversation_id="conv-blocked-timeline",
                        kind="progress",
                        title="Late progress",
                        body="This should not land.",
                        status="running",
                        progress=None,
                        metadata=RegistryJsonRecord(),
                        created_at="2026-03-16T00:00:05+00:00",
                    )
                ],
            ),
        )

    task = _routed_task_row(store, routed_task_id)

    assert task["status"] == "completed"
    assert "Final result" in str(task["result_json"])
    assert store.list_events("conv-blocked-timeline").events == []


def test_assert_agent_scope_rejects_wrong_scope(store):
    _, agent_token = _enroll(store, "channel-bot", registry_scope="channel")

    with pytest.raises(RegistryScopeError):
        store.assert_agent_scope(agent_token, {"coordination", "full"})


def test_channel_scope_poll_filters_routed_deliveries(store):
    agent_id, agent_token = _enroll(store, "channel-bot", registry_scope="channel")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )
    store.create_delivery(
        target_agent_id=agent_id,
        kind="routed_task",
        payload=RegistryJsonRecord({"routed_task_id": "task-1"}),
    )

    deliveries = store.poll(agent_token, cursor=0, limit=20).deliveries

    assert [item.kind for item in deliveries] == ["channel_input"]


def test_coordination_scope_poll_filters_channel_deliveries(store):
    agent_id, agent_token = _enroll(store, "coord-bot", registry_scope="coordination")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="channel_input",
        payload=RegistryJsonRecord({"conversation_id": "conv-1", "text": "hello"}),
    )
    store.create_delivery(
        target_agent_id=agent_id,
        kind="routed_task",
        payload=RegistryJsonRecord({"routed_task_id": "task-1"}),
    )

    deliveries = store.poll(agent_token, cursor=0, limit=20).deliveries

    assert [item.kind for item in deliveries] == ["routed_task"]


def test_create_routed_task_disabled_capability_raises(store):
    origin_id, _ = _enroll(store, "origin-bot")
    target_id, _ = _enroll(store, "target-bot", ["reviewer"])
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Disabled routing skill conversation",
        origin_channel="registry",
        external_conversation_ref="conv-1",
    )
    store.set_routing_skill_override("reviewer", enabled=False)

    with pytest.raises(RoutingSkillDisabledError):
        store.create_routed_task(
            RoutedTaskRequest(
                routed_task_id="task-disabled",
                parent_conversation_id=conversation.conversation_id,
                origin_agent_id=origin_id,
                target_agent_id=target_id,
                title="Disabled review task",
                instructions="Review the spec.",
                requested_skills=["reviewer"],
                context=RegistryJsonRecord(),
                constraints=RegistryJsonRecord(),
                priority="normal",
                created_at="2026-03-16T00:00:00+00:00",
            )
        )


def test_create_conversation_delivers_channel_input(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    conversation = store.create_conversation(
        target_agent_id=agent_id,
        title="Registry conversation",
        origin_channel="registry",
        external_conversation_ref="alpha-conv-1",
    )

    assert conversation.conversation_id


def test_add_conversation_message_requires_non_empty_text(store):
    agent_id, _agent_token = _enroll(store, "message-bot")
    conversation = store.create_conversation(
        target_agent_id=agent_id,
        title="Registry conversation",
        origin_channel="registry",
        external_conversation_ref="message-conv-1",
    )

    with pytest.raises(ValueError, match="message text"):
        store.add_conversation_message(conversation.conversation_id, "   ")


def test_add_conversation_action_requires_non_empty_action(store):
    agent_id, _agent_token = _enroll(store, "action-bot")
    conversation = store.create_conversation(
        target_agent_id=agent_id,
        title="Registry conversation",
        origin_channel="registry",
        external_conversation_ref="action-conv-1",
    )

    with pytest.raises(ValueError, match="action"):
        store.add_conversation_action(
            conversation.conversation_id,
            CoordinationActionEnvelope(
                action_id="action-1",
                action="",
                payload=RegistryJsonRecord(),
            ),
        )


def test_direct_assign_accepts_unique_display_name_alias(store):
    origin_id, _origin_token = _enroll(store, "origin-bot", display_name="Origin")
    target_id, _target_token = _enroll(store, "lift-and-shift-m2-bot", display_name="M2")
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Registry direct assignment",
        origin_channel="registry",
        external_conversation_ref="direct-assign-display-name",
    )

    result = store.add_conversation_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="direct-assign-display-name",
            action="direct_assign",
            payload=DirectAssignActionPayload(
                selector=TargetSelector(kind="agent", value="m2"),
                title="Add numbers",
                instructions="Add 2 and 2 and return the result only.",
            ),
        ),
    )

    assert result.accepted is True
    assert result.routed_tasks[0].target_agent_id == target_id


def test_direct_assign_reuses_existing_operator_message_as_the_parent_narrative(store):
    origin_id, _origin_token = _enroll(store, "origin-bot", display_name="Origin")
    target_id, target_token = _enroll(store, "lift-and-shift-m2-bot", display_name="M2")
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Registry direct assignment history",
        origin_channel="registry",
        external_conversation_ref="direct-assign-history",
    )
    message = store.add_conversation_message(
        conversation.conversation_id,
        "@m2 add 2 and 2",
    )

    result = store.add_conversation_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="direct-assign-history",
            action="direct_assign",
            payload=DirectAssignActionPayload(
                selector=TargetSelector(kind="agent", value="m2"),
                title="Add numbers",
                instructions="Add 2 and 2 and return the result only.",
                parent_event_id=message.event.event_id if message.event is not None else "",
                message_text="@m2 add 2 and 2",
            ),
        ),
    )

    routed_task_id = result.routed_tasks[0].routed_task_id
    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, routed_task_id)
    store.update_routed_task_result(
        target_token,
        routed_task_id,
        RoutedTaskResult(
            routed_task_id=routed_task_id,
            status="completed",
            transition_id=f"{routed_task_id}-complete",
            summary="4",
            full_text="4",
        ),
    )

    events = store.list_events(conversation.conversation_id).events

    assert events[0].kind == "message.user"
    assert events[0].content == "@m2 add 2 and 2"
    assert events[0].metadata["source_action"] == "direct_assign"
    assert events[0].metadata["action_id"] == "direct-assign-history"
    assert events[0].metadata["selector_kind"] == "agent"
    assert events[0].metadata["selector_value"] == "m2"
    assert events[0].metadata["routed_task_id"] == routed_task_id
    assert events[0].metadata["requested_skills"] == []
    assert len([event for event in events if event.kind == "message.user"]) == 1
    assert not any(event.kind == "delegation.submitted" for event in events)
    assert any(
        event.kind == "task.status"
        and event.metadata["status"] == "completed"
        and event.metadata["routed_task_id"] == routed_task_id
        for event in events
    )


def test_delegation_approval_prefers_explicit_origin_transport_ref_from_proposal(store):
    origin_id, _origin_token = _enroll(store, "origin-bot", display_name="Origin")
    target_id, _target_token = _enroll(store, "lift-and-shift-m2-bot", display_name="M2")
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Delegation transport identity",
        origin_channel="telegram",
        external_conversation_ref="telegram:bot-origin:12345",
    )

    proposed = store.add_conversation_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="proposal-origin-transport-ref",
            action="delegate_tasks",
            payload=DelegateTasksActionPayload(
                title="Ask the specialist",
                resume_instruction="Resume in the parent chat.",
                origin_transport_ref="slack:workspace:channel-42",
                tasks=[
                    DelegationTaskDraft(
                        draft_id="draft-1",
                        selector=TargetSelector(kind="agent", value="m2", preferred_agent_id=target_id),
                        title="Investigate",
                        instructions="Return the findings.",
                    )
                ],
            ),
        ),
    )

    approved = store.add_conversation_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="approve-origin-transport-ref",
            action="delegation_approve",
            payload=ApproveDelegationActionPayload(proposal_id=proposed.proposal_id),
        ),
    )

    task = store.get_task(approved.routed_tasks[0].routed_task_id)

    assert task is not None
    assert task.origin_transport_ref == "slack:workspace:channel-42"
    assert task.request["origin_transport_ref"] == "slack:workspace:channel-42"


def test_direct_assign_rejects_ambiguous_display_name_alias(store):
    origin_id, _origin_token = _enroll(store, "origin-bot", display_name="Origin")
    _target_a, _token_a = _enroll(store, "lift-and-shift-m2-a", display_name="M2")
    _target_b, _token_b = _enroll(store, "lift-and-shift-m2-b", display_name="M2")
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Registry direct assignment",
        origin_channel="registry",
        external_conversation_ref="direct-assign-display-name-ambiguous",
    )

    with pytest.raises(ValueError, match="ambiguous"):
        store.add_conversation_action(
            conversation.conversation_id,
            CoordinationActionEnvelope(
                action_id="direct-assign-display-name-ambiguous",
                action="direct_assign",
                payload=DirectAssignActionPayload(
                    selector=TargetSelector(kind="agent", value="m2"),
                    title="Add numbers",
                    instructions="Add 2 and 2 and return the result only.",
                ),
            ),
        )


def test_direct_assign_does_not_fuzzy_match_partial_alias(store):
    origin_id, _origin_token = _enroll(store, "origin-bot", display_name="Origin")
    _target_id, _target_token = _enroll(store, "lift-and-shift-m2-bot", display_name="M2")
    conversation = store.create_conversation(
        target_agent_id=origin_id,
        title="Registry direct assignment",
        origin_channel="registry",
        external_conversation_ref="direct-assign-no-fuzzy",
    )

    with pytest.raises(ValueError, match="No connected agent matches"):
        store.add_conversation_action(
            conversation.conversation_id,
            CoordinationActionEnvelope(
                action_id="direct-assign-no-fuzzy",
                action="direct_assign",
                payload=DirectAssignActionPayload(
                    selector=TargetSelector(kind="agent", value="m"),
                    title="Add numbers",
                    instructions="Add 2 and 2 and return the result only.",
                ),
            ),
        )


def test_delegated_task_usage_rolls_up_to_parent_conversation(store):
    routed_task_id = "task-usage-rollup"
    _routed, _origin_id, _target_id, target_token, conversation_id = _create_routed_task(
        store,
        routed_task_id=routed_task_id,
    )

    _lease_routed_task(store, target_token)
    _start_routed_task(store, target_token, routed_task_id)
    store.update_routed_task_result(
        target_token,
        routed_task_id,
        RoutedTaskResult(
            routed_task_id=routed_task_id,
            status="completed",
            transition_id=f"{routed_task_id}-complete",
            summary="4",
            full_text="4",
            prompt_tokens=13,
            completion_tokens=5,
            cost_usd=0.17,
            provider="codex",
        ),
    )

    usage_rows = store.get_usage_summary("1970-01-01T00:00:00+00:00")
    usage_row = next(item for item in usage_rows if item.conversation_id == conversation_id)
    assert usage_row.title == f"Conversation {routed_task_id}"
    assert usage_row.metadata["prompt_tokens"] == 13
    assert usage_row.metadata["completion_tokens"] == 5
    assert usage_row.metadata["cost_usd"] == 0.17
    assert usage_row.metadata["provider"] == "codex"

    per_conversation = store.get_usage(
        conversation_id=conversation_id,
        since="1970-01-01T00:00:00+00:00",
    )
    assert any(
        row.conversation_id == conversation_id
        and row.metadata["prompt_tokens"] == 13
        and row.metadata["completion_tokens"] == 5
        and row.metadata["cost_usd"] == 0.17
        and row.metadata["provider"] == "codex"
        for row in per_conversation
    )

    summary = store.get_summary(now_iso=datetime.now(timezone.utc).isoformat())
    assert summary.usage_24h == {
        "prompt_tokens": 13,
        "completion_tokens": 5,
        "cached_prompt_tokens": 0,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": False,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.0,
        "cost_available": False,
    }


def test_list_approvals_returns_only_pending_requests(store):
    agent_id, agent_token = _enroll(store, "approval-bot")
    pending = store.create_conversation(
        target_agent_id=agent_id,
        title="Pending approval conversation",
        origin_channel="registry",
        external_conversation_ref="approval-pending-1",
    )
    decided = store.create_conversation(
        target_agent_id=agent_id,
        title="Decided approval conversation",
        origin_channel="registry",
        external_conversation_ref="approval-decided-1",
    )

    store.publish_events(
        agent_token,
        pending.conversation_id,
        [
            EventRecord(
                event_id="approval-pending-event",
                kind="approval.requested",
                actor="operator",
                content="Review this change",
                created_at="2026-03-16T00:00:00+00:00",
                metadata={
                    "request_kind": "preflight",
                    "actor_key": "reg:operator",
                    "trust_tier": "trusted",
                    "expires_at": "2026-04-16T01:00:00+00:00",
                },
            )
        ],
    )
    store.publish_events(
        agent_token,
        decided.conversation_id,
        [
            EventRecord(
                event_id="approval-decided-event",
                kind="approval.requested",
                actor="operator",
                content="Approve this deployment",
                created_at="2026-03-16T00:05:00+00:00",
                metadata={
                    "request_kind": "delegation",
                    "actor_key": "reg:operator",
                    "trust_tier": "trusted",
                    "expires_at": "2026-04-16T01:05:00+00:00",
                },
            )
        ],
    )
    store.add_conversation_action(
        decided.conversation_id,
        CoordinationActionEnvelope(
            action_id="approval-action-1",
            action="approve_pending",
            payload=ApproveRejectActionPayload(request_id="approval-decided-event"),
        ),
    )

    approvals = store.list_approvals()

    assert [item.conversation_id for item in approvals] == [pending.conversation_id]
    assert approvals[0].request_id == "approval-pending-event"
    assert approvals[0].request_kind == "preflight"


def test_heartbeat_persists_runtime_health_and_workers(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    store.heartbeat(
        agent_token,
        AgentHeartbeatRequest(
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=2,
            runtime_health=_runtime_health_payload(worker_count=2),
        ),
    )

    listed = store.list_agents()
    assert listed[0].runtime_health_summary.status == "degraded"
    assert listed[0].runtime_health_summary.healthy_worker_count == 2
    detail = store.get_agent_runtime_health(agent_id)
    assert detail is not None
    assert detail.report["summary"]["claimed_count"] == 1
    assert len(detail.workers) == 2


def test_heartbeat_replaces_missing_worker_rows(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    first = _runtime_health_payload(worker_count=2)
    second = _runtime_health_payload(worker_count=1, generated_at="2026-03-16T00:00:20+00:00")
    second = second.model_copy(
        update={
            "summary": second.summary.model_copy(update={"healthy_worker_count": 1}),
        }
    )

    store.heartbeat(
        agent_token,
        AgentHeartbeatRequest(
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=2,
            runtime_health=first,
        ),
    )
    store.heartbeat(
        agent_token,
        AgentHeartbeatRequest(
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=2,
            runtime_health=second,
        ),
    )

    detail = store.get_agent_runtime_health(agent_id)
    assert detail is not None
    assert detail.last_mirrored_at == "2026-03-16T00:00:20+00:00"
    assert [row.worker_id for row in detail.workers] == ["worker-1"]


def test_register_preserves_omitted_capacity_and_card_lists(store):
    agent_id, agent_token = _enroll(store, "partial-register-bot", ["python", "tests"])

    store.heartbeat(
        agent_token,
        AgentHeartbeatRequest(
            connectivity_state="connected",
            current_capacity=2,
            max_capacity=5,
        ),
    )

    updated = store.register(
        agent_token,
        AgentRegisterRequest(
            agent_card=AgentCard(
                bot_key="bot-partial-register-bot",
                display_name="Partial Register Bot",
                registry_scope="coordination",
            ),
            connectivity_state="connected",
        ),
    )

    assert updated.agent_id == agent_id
    assert updated.current_capacity == 2
    assert updated.max_capacity == 5
    assert updated.routing_skills == ["python", "tests"]
    assert updated.tags == ["backend"]
    assert updated.channel_capabilities == ["registry"]
    assert updated.registry_scope == "coordination"


def test_routing_skill_override_disabled_excludes_search(store):
    _enroll(store, "rust-bot", ["rust"])
    store.set_routing_skill_override("rust", enabled=False)

    assert store.search_agents(AgentDiscoveryQuery(skills=["rust"], required_state="connected")) == []


def test_search_agents_rejects_string_filters(store):
    _enroll(store, "alpha-bot", ["python"])

    with pytest.raises(ValidationError):
        AgentDiscoveryQuery(skills="python", required_state="connected")


def test_list_routing_skills_aggregates_declared(store):
    _enroll(store, "alpha-bot", ["python"])
    _enroll(store, "beta-bot", ["python"])

    skills = {item.skill_name: item for item in store.list_routing_skills()}

    assert "python" in skills
    assert skills["python"].advertised_by_agents == ["alpha-bot", "beta-bot"]


def test_routing_skill_override_survives_agent_deregistration(store):
    _, agent_token = _enroll(store, "go-bot", ["go"])
    store.set_routing_skill_override("go", enabled=False)
    store.deregister(agent_token)

    skills = {item.skill_name: item for item in store.list_routing_skills()}

    assert skills["go"].enabled is False
    assert skills["go"].advertised_by_agents == []


def test_update_agent_trust_tier_updates_record(store):
    agent_id, _ = _enroll(store, "trust-bot")

    updated = store.update_agent_trust_tier(agent_id, "trusted")

    assert updated.trust_tier == "trusted"
    reread = {agent.agent_id: agent for agent in store.list_agents()}
    assert reread[agent_id].trust_tier == "trusted"


def test_update_agent_trust_tier_rejects_unknown_tier(store):
    agent_id, _ = _enroll(store, "invalid-tier-bot")

    with pytest.raises(ValueError):
        store.update_agent_trust_tier(agent_id, "platinum")


def test_update_agent_capacity_overrides_current_and_max(store):
    agent_id, _ = _enroll(store, "capacity-bot")

    updated = store.update_agent_capacity(agent_id, current_capacity=3, max_capacity=9)

    assert updated.current_capacity == 3
    assert updated.max_capacity == 9


def test_rotate_agent_token_issues_new_token_and_invalidates_old(store):
    agent_id, old_token = _enroll(store, "rotate-bot")

    updated, new_token = store.rotate_agent_token(agent_id)

    assert new_token
    assert new_token != old_token
    assert updated.agent_id == agent_id
    assert _stored_agent_token(store, agent_id) == hash_agent_token(new_token)
    assert _stored_agent_token(store, agent_id) != hash_agent_token(old_token)


def test_soft_delete_agent_hides_from_default_listing(store):
    agent_id, _ = _enroll(store, "tombstone-bot")

    record = store.soft_delete_agent(agent_id)

    assert record.soft_deleted_at
    assert record.connectivity_state == "disconnected"
    visible_ids = [agent.agent_id for agent in store.list_agents()]
    assert agent_id not in visible_ids
    all_ids = [agent.agent_id for agent in store.list_agents(include_soft_deleted=True)]
    assert agent_id in all_ids


def test_preview_selector_resolution_returns_all_matches(store):
    _enroll(store, "python-a", ["python"])
    _enroll(store, "python-b", ["python"])
    _enroll(store, "rust-a", ["rust"])

    candidates = store.preview_selector_resolution(
        TargetSelector(kind="skill", value="python"),
    )

    slugs = sorted(str(row["slug"]) for row in candidates)
    assert slugs == ["python-a", "python-b"]


def test_preview_selector_resolution_exclude_filter_hides_agents(store):
    agent_a, _ = _enroll(store, "skill-excluded", ["reviewer"])
    agent_b, _ = _enroll(store, "skill-available", ["reviewer"])

    rest = store.preview_selector_resolution(
        TargetSelector(kind="skill", value="reviewer"),
        exclude_agent_ids=(agent_a,),
    )

    visible_ids = [row["agent_id"] for row in rest]
    assert agent_a not in visible_ids
    assert agent_b in visible_ids
