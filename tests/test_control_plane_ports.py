from __future__ import annotations

from app.access import get_authorization
from app.runtime import composition
import app.runtime_backend as runtime_backend
from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    MessageRecord,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
)
from octopus_sdk.agent_directory import (
    AgentDirectoryPort,
    NoOpAgentDirectory,
)
from octopus_sdk.conversation_projection import (
    ConversationProjectionPort,
    NoOpConversationProjection,
)
from octopus_sdk.health_publication import (
    ConnectionSummary,
    HealthPublicationPort,
    HealthReport,
    NoOpHealthPublication,
)
from octopus_sdk.task_routing import (
    NoOpTaskRouting,
    TaskResultReport,
    TaskRoutingPort,
    TaskSubmissionResult,
)
from app.runtime.services import BotServices, ControlPlaneServices
from tests.support.registry_participant_support import build_noop_registry_participant


async def test_noop_conversation_projection_satisfies_port_and_is_silent() -> None:
    projection = NoOpConversationProjection()

    assert isinstance(projection, ConversationProjectionPort)

    conversation_id = await projection.create_conversation(
        target_agent_id="agent-1",
        origin_channel="telegram",
        external_conversation_ref="telegram:bot:1",
        title="Chat",
    )
    assert isinstance(conversation_id, str)
    assert conversation_id == ""

    await projection.publish_events(
        conversation_id=conversation_id,
        events=[
            ConversationEvent(
                event_id="evt-1",
                kind="message.bot",
                content="done",
                created_at="2026-03-26T00:00:00+00:00",
            )
        ],
    )
    message = await projection.add_message(
        conversation_id=conversation_id,
        text="hello",
    )
    assert isinstance(message, MessageRecord)
    assert message.accepted is False


async def test_noop_task_routing_returns_unavailable_for_request_reply_methods() -> None:
    routing = NoOpTaskRouting()
    request = RoutedTaskRequest(
        routed_task_id="task-1",
        parent_conversation_id="parent-1",
        origin_agent_id="origin-1",
        target_agent_id="target-1",
        title="Delegate",
        instructions="Do the thing",
    )
    result = RoutedTaskResult(
        routed_task_id="task-1",
        status="completed",
        transition_id="task-1-complete",
        summary="done",
    )

    assert isinstance(routing, TaskRoutingPort)

    submission = await routing.submit_routed_task(
        request=request,
        authority_ref="registry:prod",
    )
    report = await routing.report_routed_task_result(
        routed_task_id="task-1",
        authority_ref="registry:prod",
        result=result,
    )

    assert isinstance(submission, TaskSubmissionResult)
    assert submission.status == "unavailable"
    assert submission.error == "no control plane"
    assert isinstance(report, TaskResultReport)
    assert report.status == "unavailable"
    assert report.error == "no control plane"


async def test_noop_task_routing_status_update_is_fire_and_forget() -> None:
    routing = NoOpTaskRouting()
    update = RoutedTaskUpdate(
        routed_task_id="task-1",
        status="running",
        transition_id="task-1-running",
        summary="halfway",
    )

    await routing.update_routed_task_status(
        update=update,
        authority_ref="registry:prod",
    )


async def test_noop_agent_directory_returns_typed_unavailable_results() -> None:
    directory = NoOpAgentDirectory()

    assert isinstance(directory, AgentDirectoryPort)

    search = await directory.search_agents(query=AgentDiscoveryQuery(role="ops"))
    resolution = await directory.resolve_target_authority(target_agent_id="agent-1")

    assert search.status == "unavailable"
    assert search.agents == []
    assert search.responding_authorities == []
    assert search.timed_out_authorities == []
    assert resolution.status == "unavailable"
    assert resolution.authority_ref == ""
    assert resolution.error == "no control plane"


async def test_noop_health_publication_and_service_container_remain_usable() -> None:
    projection = NoOpConversationProjection()
    routing = NoOpTaskRouting()
    directory = NoOpAgentDirectory()
    health = NoOpHealthPublication()

    assert isinstance(health, HealthPublicationPort)

    await health.publish_health(
        report=HealthReport(
            connectivity_state="standalone",
            current_capacity=0,
            max_capacity=1,
        )
    )
    summary = health.connection_summary()
    services = BotServices(
        control_plane=ControlPlaneServices(
            conversation_projection=projection,
            task_routing=routing,
            agent_directory=directory,
            health_publication=health,
        ),
        registry=build_noop_registry_participant(),
        workflows=composition.workflows(),
        authorization=get_authorization(),
        work_queue=runtime_backend.transport_store(),
    )

    assert isinstance(summary, ConnectionSummary)
    assert summary.authorities == []
    assert services.control_plane.conversation_projection is projection
    assert services.control_plane.task_routing is routing
    assert services.control_plane.agent_directory is directory
    assert services.control_plane.health_publication is health
