from __future__ import annotations

from pathlib import Path

from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AgentCard,
    AgentDiscoveryQuery,
    ConversationCreate,
    CoordinationActionEnvelope,
    RegistryJsonRecord,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    RuntimeHealthSummaryRecord,
    RuntimeHealthPayload,
)

from octopus_registry.authority import StoreBackedRegistryAuthority
from octopus_registry.store import RegistrySQLiteStore


def _authority(tmp_path: Path) -> StoreBackedRegistryAuthority:
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
    return StoreBackedRegistryAuthority(store)


def _card(*, slug: str, display_name: str) -> AgentCard:
    return AgentCard(
        bot_key=f"bot:{slug}",
        slug=slug,
        display_name=display_name,
        registry_scope="full",
        channel_capabilities=["telegram", "registry"],
    )


def test_store_backed_authority_passes_core_authority_profile(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    enrollment = authority.enroll_agent(_card(slug="m1", display_name="M1"))

    renewed = authority.renew_enrollment(
        enrollment.agent_id,
        _card(slug="m1", display_name="M1 Renamed"),
    )
    assert renewed.agent_id == enrollment.agent_id
    assert renewed.agent_token == enrollment.agent_token

    heartbeat = authority.accept_heartbeat(
        enrollment.agent_id,
        RuntimeHealthPayload(
            summary=RuntimeHealthSummaryRecord(ok=True),
            snapshot=RegistryJsonRecord({"workers": [{"worker_id": "worker-1", "items_processed": 2}]}),
        ),
    )
    assert heartbeat.agent is not None
    assert heartbeat.agent.display_name == "M1 Renamed"

    discovered = authority.search_agents(AgentDiscoveryQuery())
    assert [agent.slug for agent in discovered] == ["m1"]

    conversation = authority.create_conversation(
        ConversationCreate(
            target_agent_id=enrollment.agent_id,
            origin_channel="telegram",
            external_conversation_ref="chat-1",
            title="Test conversation",
        )
    )
    assert conversation.title == "Test conversation"

    message = authority.add_message(
        conversation.conversation_id,
        "hello operator",
        actor="telegram:operator",
    )
    assert message.accepted is True
    assert message.event is not None
    assert message.event.kind == "message.user"

    action = authority.submit_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="cancel-1",
            action="cancel_conversation",
            payload=RegistryJsonRecord(),
        ),
    )
    assert action.accepted is True
    assert action.action == "cancel_conversation"

    published = authority.publish_events(
        conversation.conversation_id,
        [
            ConversationEvent(
                event_id="evt-1",
                kind="message.bot",
                content="done",
                created_at="2026-03-26T00:00:00+00:00",
            )
        ],
    )
    assert [event.event_id for event in published] == ["evt-1"]

    task = authority.submit_routed_task(
        RoutedTaskRequest(
            routed_task_id="task-1",
            parent_conversation_id=conversation.conversation_id,
            origin_agent_id=enrollment.agent_id,
            target_agent_id=enrollment.agent_id,
            title="Compute",
            instructions="Return the answer only",
        )
    )
    assert task.routed_task_id == "task-1"

    deliveries = authority.poll_deliveries(enrollment.agent_id, cursor=0)
    assert deliveries
    assert {delivery.kind for delivery in deliveries} >= {"channel_input", "routed_task"}

    updated = authority.update_routed_task(
        RoutedTaskUpdate(
            routed_task_id="task-1",
            status="running",
            transition_id="transition-1",
            summary="halfway",
        )
    )
    assert updated.status == "running"

    completed = authority.report_routed_result(
        RoutedTaskResult(
            routed_task_id="task-1",
            status="completed",
            transition_id="transition-2",
            summary="finished",
            full_text="5",
        )
    )
    assert completed.status == "completed"

    accepted = authority.ack_delivery(deliveries[0].delivery_id)
    assert accepted.updated == 1
    assert accepted.classification == "accepted"
    if len(deliveries) > 1:
        rejected = authority.fail_delivery(deliveries[1].delivery_id, "rejected by test")
        assert rejected.updated == 1
        assert rejected.classification == "rejected"

    disconnected = authority.disconnect_agent(enrollment.agent_id)
    assert disconnected.agent_id == enrollment.agent_id
    assert disconnected.connectivity_state == "offline"
