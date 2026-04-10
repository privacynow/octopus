from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import app.runtime_backend as runtime_backend
from app.agents.state import RegistryConnectionState, save_registry_connection_state
from octopus_registry.authority import StoreBackedRegistryAuthority
from octopus_registry.store_postgres import RegistryPostgresStore
from app.runtime.services import build_runtime
from app.runtime.registry_participant import build_control_plane_registry_participant
from app.runtime.services import ControlPlaneServices
from octopus_sdk.agent_directory import NoOpAgentDirectory
from octopus_sdk.conversation_projection import NoOpConversationProjection
from octopus_sdk.health_publication import NoOpHealthPublication
from octopus_sdk.registry_inspection import NoOpRegistryInspection
from octopus_sdk.inbound_types import InboundEnvelope, InboundMessage, InboundUser, serialize_inbound
from octopus_sdk.registry.client import RegistryClient
from octopus_sdk.registry.models import (
    AgentCard,
    AgentDiscoveryQuery,
    ConversationCreate,
    ConversationId,
    CoordinationActionEnvelope,
    RegistryJsonRecord,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    RuntimeHealthPayload,
    RuntimeHealthSummaryRecord,
    TargetSelector,
)
from octopus_sdk.task_routing import NoOpTaskRouting
from octopus_sdk.workflows.pending import PendingRequestOutcome
from octopus_sdk.sessions import PendingApproval
from octopus_sdk.tests.support import RecordingWorkQueue, make_sdk_harness
from tests.support.config_support import make_config, make_registry_connection
from tests.support.handler_support import FakeProvider, MinimalFakeBot


def _noop_control_plane_services() -> ControlPlaneServices:
    return ControlPlaneServices(
        conversation_projection=NoOpConversationProjection(),
        task_routing=NoOpTaskRouting(),
        agent_directory=NoOpAgentDirectory(),
        registry_inspection=NoOpRegistryInspection(),
        health_publication=NoOpHealthPublication(),
    )


def _agent_card(*, slug: str, display_name: str) -> AgentCard:
    return AgentCard(
        bot_key=f"bot:{slug}",
        slug=slug,
        display_name=display_name,
        registry_scope="full",
        channel_capabilities=["telegram", "registry"],
    )


async def test_transport_profile_behavioral_suite_uses_sdk_transport_only_runtime(tmp_path: Path) -> None:
    harness = make_sdk_harness(tmp_path)
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(workflows)
    transport = runtime.transport
    assert transport.descriptor.transport_type == "stub"

    egress = transport.build_egress(
        conversation_ref="stub:conversation:1",
        config=runtime.config,
    )
    await egress.bind(title="Reference chat", config=runtime.config)
    await egress.send_formatted_reply("hello")
    await egress.send_approval_prompt("approval-1")

    envelope = InboundEnvelope(
        transport="stub",
        event_id="evt-cert-1",
        conversation_key="stub:conversation:1",
        actor_key="stub:user:1",
        received_at=datetime.now(timezone.utc),
        event=InboundMessage(
            user=InboundUser(id="stub:user:1", username="sdk"),
            conversation_key="stub:conversation:1",
            text="hello",
            source="stub",
        ),
    )
    admitted = await runtime.submit(envelope)
    assert admitted.status == "admitted"


def test_participant_profile_behavioral_suite_uses_live_state_and_degraded_behavior(tmp_path: Path) -> None:
    connected_config = make_config(
        data_dir=tmp_path / "connected",
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        connected_config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="connected",
        ),
    )
    participant = build_control_plane_registry_participant(
        connected_config,
        _noop_control_plane_services(),
    )
    assert participant.health.live_local_agent_ids() == {"registry:default": "agent-1"}

    offline_config = make_config(
        data_dir=tmp_path / "offline",
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
    )
    save_registry_connection_state(
        offline_config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="offline",
        ),
    )
    degraded = build_control_plane_registry_participant(
        offline_config,
        _noop_control_plane_services(),
    )
    discovery = asyncio.run(
        degraded.discovery.search_agents(
            query=AgentDiscoveryQuery(free_text="m2"),
        )
    )
    assert discovery.status == "unavailable"

    preview = asyncio.run(
        degraded.coordination.preview_target_resolution(
            TargetSelector(kind="agent", value="m2"),
        )
    )
    assert preview.status == "unavailable"
    with pytest.raises(RuntimeError, match="registry connectivity is degraded"):
        asyncio.run(
            degraded.coordination.direct_assign(
                ConversationId("conv-1"),
                selector=TargetSelector(kind="agent", value="m2"),
                title="Assign",
                instructions="Do the thing",
            )
        )


def test_workflow_profile_behavioral_suite_exposes_full_operator_surface(tmp_path: Path) -> None:
    harness = make_sdk_harness(tmp_path)
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(workflows)
    session = runtime.sessions.load(
        "stub:conversation:1",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
    )
    session.pending_approval = PendingApproval(
        actor_key="sdk:actor",
        prompt="run",
        image_paths=[],
        attachment_dicts=[],
        context_hash="ctx",
    )

    reset = runtime.workflows.conversation.control.reset_session(
        session,
        actor_key="sdk:actor",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode_default=runtime.config.approval_mode,
        default_role=runtime.config.role,
        default_skills=runtime.config.default_skills,
        projects=runtime.config.projects,
        conversation_key="stub:conversation:1",
    )
    approval = runtime.workflows.pending.requests.approve(
        session,
        cfg=runtime.config,
        provider_name=runtime.provider.name,
    )
    credentials = runtime.workflows.credentials.management.load_credentials("sdk:actor")
    guidance = runtime.workflows.provider_guidance.preview.preview(
        runtime.provider.name,
        role="operator",
        active_skills=[],
        compact_mode=False,
    )
    skill_session = runtime.sessions.load(
        "stub:conversation:skills",
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=runtime.config.approval_mode,
    )
    satisfaction = runtime.workflows.runtime_skills.setup.check_satisfaction(
        skill_session,
        actor_key="sdk:actor",
        active_skills=[],
    )
    recovery_payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id="sdk:actor", username="sdk"),
            conversation_key="stub:conversation:1",
            text="recover me",
            source="stub",
        ),
        transport="stub",
    )
    payload = runtime.work_queue.record_and_enqueue(
        runtime.config.data_dir,
        "evt-cert-recovery",
        "stub:conversation:1",
        "sdk:actor",
        "message",
        payload=recovery_payload,
    )
    assert payload[0] is True
    assert payload[1] is not None
    runtime.work_queue.mark_pending_recovery(runtime.config.data_dir, payload[1])
    recovery = runtime.workflows.recovery.replay.prepare_action(
        data_dir=runtime.config.data_dir,
        conversation_key="stub:conversation:1",
        event_id="evt-cert-recovery",
        action="recovery_replay",
        worker_id="worker-1",
        config=runtime.config,
    )

    assert reset.status == "reset"
    assert isinstance(approval, PendingRequestOutcome)
    assert credentials == {"docs": {"API_KEY": "secret"}}
    assert guidance.provider == runtime.provider.name
    assert satisfaction.status == "satisfied"
    assert recovery.status == "replay_ready"


async def test_infrastructure_profile_behavioral_suite_uses_typed_work_queue_and_authorization(tmp_path: Path) -> None:
    work_queue = RecordingWorkQueue()
    harness = make_sdk_harness(tmp_path, work_queue=work_queue)
    workflows = harness.composer.build_for_testing()
    runtime = harness.build_runtime(workflows)

    envelope = InboundEnvelope(
        transport="stub",
        event_id="evt-cert-2",
        conversation_key="stub:conversation:2",
        actor_key="stub:user:2",
        received_at=datetime.now(timezone.utc),
        event=InboundMessage(
            user=InboundUser(id="stub:user:2", username="infra"),
            conversation_key="stub:conversation:2",
            text="queue me",
            source="stub",
        ),
    )
    result = await runtime.submit(envelope)
    assert result.status == "admitted"
    assert runtime.authorization.access_policy(runtime.config, None) == "allow"
    assert work_queue.calls == ["record_and_admit_message"]


def test_authority_profile_behavioral_suite_round_trips_store_backed_authority(postgres_db_url: str) -> None:
    authority = StoreBackedRegistryAuthority(RegistryPostgresStore(postgres_db_url))
    enrollment = authority.enroll_agent(_agent_card(slug="m1", display_name="M1"))
    renewed = authority.renew_enrollment(
        enrollment.agent_id,
        _agent_card(slug="m1", display_name="M1 Renamed"),
    )
    assert renewed.agent_id == enrollment.agent_id

    heartbeat = authority.accept_heartbeat(
        enrollment.agent_id,
        RuntimeHealthPayload(
            summary=RuntimeHealthSummaryRecord(ok=True),
            snapshot=RegistryJsonRecord({"workers": [{"worker_id": "worker-1"}]}),
        ),
    )
    assert heartbeat.agent is not None
    assert heartbeat.agent.display_name == "M1 Renamed"

    conversation = authority.create_conversation(
        ConversationCreate(
            target_agent_id=enrollment.agent_id,
            origin_channel="telegram",
            external_conversation_ref="chat-1",
            title="Test conversation",
        )
    )
    action = authority.submit_action(
        conversation.conversation_id,
        CoordinationActionEnvelope(
            action_id="cancel-1",
            action="cancel_conversation",
            payload=RegistryJsonRecord(),
        ),
    )
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
    deliveries = authority.poll_deliveries(enrollment.agent_id, cursor=0)
    updated = authority.update_routed_task(
        RoutedTaskUpdate(
            routed_task_id="task-1",
            status="running",
            transition_id="transition-1",
            summary="halfway",
        )
    )
    completed = authority.report_routed_result(
        RoutedTaskResult(
            routed_task_id="task-1",
            status="completed",
            transition_id="transition-2",
            summary="finished",
            full_text="5",
        )
    )
    accepted = authority.ack_delivery(deliveries[0].delivery_id)

    assert action.accepted is True
    assert task.routed_task_id == "task-1"
    assert deliveries
    assert updated.status == "running"
    assert completed.status == "completed"
    assert accepted.updated == 1


async def test_authority_client_profile_behavioral_suite_uses_typed_wire_models() -> None:
    calls: list[tuple[str, str, object | None]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode()) if request.content else None
        calls.append((request.method, request.url.path, payload))
        path = request.url.path
        if path == "/v1/agents/enroll":
            return httpx.Response(200, json={"agent_id": "agent-1", "agent_token": "token-1", "slug": "m1"})
        if path == "/v1/agents/heartbeat":
            return httpx.Response(200, json={"agent": {"agent_id": "agent-1", "display_name": "M1"}, "server_time": "now"})
        if path == "/v1/agents/poll":
            return httpx.Response(
                200,
                json={
                    "deliveries": [
                        {
                            "delivery_id": "delivery-1",
                            "cursor": "1",
                            "registry_id": "default",
                            "kind": "channel_input",
                            "payload": {"text": "hello"},
                            "state": "queued",
                        }
                    ],
                    "next_cursor": "1",
                },
            )
        if path == "/v1/agents/ack":
            return httpx.Response(200, json={"updated": 1, "classification": "accepted"})
        if path == "/v1/conversations":
            return httpx.Response(
                200,
                json={
                    "conversation_id": "conv-1",
                    "target_agent_id": "agent-1",
                    "origin_channel": "telegram",
                    "external_conversation_ref": "chat-1",
                    "title": "Conversation",
                },
            )
        if path == "/v1/conversations/conv-1/actions":
            return httpx.Response(
                200,
                json={
                    "conversation_id": "conv-1",
                    "action_id": "action-1",
                    "action": "cancel_conversation",
                    "accepted": True,
                },
            )
        if path == "/v1/agents/routed-tasks":
            return httpx.Response(
                200,
                json={
                    "routed_task_id": "task-1",
                    "status": "queued",
                    "parent_conversation_id": "conv-1",
                    "origin_agent_id": "agent-1",
                    "target_agent_id": "agent-1",
                    "title": "Task",
                    "instructions": "Do work",
                },
            )
        raise AssertionError(f"unexpected registry client request: {request.method} {path}")

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = RegistryClient("http://registry.test", "token-1", client=http_client)
        enrollment = await client.enroll("secret", _agent_card(slug="m1", display_name="M1"))
        heartbeat = await client.heartbeat(
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
            runtime_health=RuntimeHealthPayload(summary=RuntimeHealthSummaryRecord(ok=True)),
        )
        deliveries = await client.poll()
        ack = await client.ack(["delivery-1"])
        conversation = await client.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="chat-1",
            title="Conversation",
        )
        action = await client.submit_action(
            "conv-1",
            CoordinationActionEnvelope(
                action_id="action-1",
                action="cancel_conversation",
                payload=RegistryJsonRecord(),
            ),
        )
        task = await client.submit_routed_task(
            RoutedTaskRequest(
                routed_task_id="task-1",
                parent_conversation_id="conv-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-1",
                title="Task",
                instructions="Do work",
            )
        )

    assert enrollment.agent_id == "agent-1"
    assert heartbeat.agent is not None
    assert deliveries.next_cursor == "1"
    assert ack.updated == 1
    assert conversation.conversation_id == "conv-1"
    assert action.accepted is True
    assert task.routed_task_id == "task-1"
    assert [path for _method, path, _payload in calls] == [
        "/v1/agents/enroll",
        "/v1/agents/heartbeat",
        "/v1/agents/poll",
        "/v1/agents/ack",
        "/v1/conversations",
        "/v1/conversations/conv-1/actions",
        "/v1/agents/routed-tasks",
    ]


async def test_telegram_runtime_passes_transport_participant_and_workflow_profiles(tmp_path: Path) -> None:
    runtime_backend.reset_for_test()
    config = make_config(
        data_dir=tmp_path,
        agent_mode="registry",
        agent_registries=(make_registry_connection(),),
        runtime_mode="shared",
    )
    save_registry_connection_state(
        config.data_dir,
        RegistryConnectionState(
            registry_id="default",
            registry_scope="full",
            agent_id="agent-1",
            agent_token="token-1",
            connectivity_state="connected",
        ),
    )
    runtime_backend.init(config)
    try:
        runtime_process = build_runtime(config, FakeProvider())
        dispatcher = runtime_process.bot_runtime.transport
        assert dispatcher.active_transport_types() == ["telegram", "registry"]

        egress = dispatcher.create_egress(
            "telegram:test:12345",
            config=config,
            bot=MinimalFakeBot(),
            conversation_key="telegram:12345",
            source="telegram",
        )
        await egress.bind(title="Telegram profile", config=config)

        registry = runtime_process.services.registry
        assert registry.health.live_local_agent_ids() == {"registry:default": "agent-1"}

        session = runtime_process.bot_runtime.sessions.load(
            "telegram:12345",
            provider_name=runtime_process.bot_runtime.provider.name,
            provider_state_factory=runtime_process.bot_runtime.provider.new_provider_state,
            approval_mode=config.approval_mode,
            default_role=config.role,
            default_skills=config.default_skills,
        )
        approval = runtime_process.services.workflows.conversation.settings.set_approval_mode(session, "on")
        assert approval.mutated is True
        credentials = runtime_process.services.workflows.credentials.management.load_credentials("telegram:42")
        assert isinstance(credentials, dict)
    finally:
        runtime_backend.reset_for_test()
