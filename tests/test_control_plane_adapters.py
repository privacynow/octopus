from __future__ import annotations

import json

from app.agents.types import (
    AgentDiscoveryQuery,
    DiscoveredAgentRef,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
)
from app.control_plane.adapters import (
    BusAgentDirectory,
    BusConversationProjection,
    BusHealthPublication,
    BusTaskRouting,
)
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlReply
from app.ports.agent_directory import AgentSearchResult, AuthorityResolution
from app.ports.health_publication import HealthReport
from app.ports.task_routing import TaskSubmissionResult


class _FakeBus:
    def __init__(self) -> None:
        self.submitted = []
        self.requests = []
        self._request_replies: dict[str, ControlReply | Exception] = {}

    async def submit(self, command):
        self.submitted.append(command)
        return command.command_id

    async def request(self, command, *, timeout_seconds: float = 10.0):
        del timeout_seconds
        self.requests.append(command)
        reply = self._request_replies.get(command.authority_ref)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise TimeoutError("no reply")
        return reply


def _directory() -> ControlPlaneDirectory:
    directory = ControlPlaneDirectory()
    directory.register(capability="conversation_projection", authority_ref="registry:alpha")
    directory.register(capability="conversation_projection", authority_ref="registry:beta")
    directory.register(capability="agent_directory", authority_ref="registry:alpha")
    directory.register(capability="agent_directory", authority_ref="registry:beta")
    directory.register(capability="health_publication", authority_ref="registry:alpha")
    return directory


async def test_task_routing_submit_sets_idempotency_and_parses_reply() -> None:
    bus = _FakeBus()
    bus._request_replies["registry:alpha"] = ControlReply(
        command_id="reply-1",
        status="completed",
        result_json=TaskSubmissionResult(
            status="accepted",
            routed_task_id="task-1",
            delivery_id="delivery-1",
        ).model_dump_json(),
    )
    adapter = BusTaskRouting(bus, _directory())

    result = await adapter.submit_routed_task(
        request=RoutedTaskRequest(
            routed_task_id="task-1",
            parent_conversation_id="parent-1",
            origin_agent_id="origin-1",
            target_agent_id="target-1",
            title="Investigate",
            instructions="Check logs",
        ),
        authority_ref="registry:alpha",
    )

    assert result.status == "accepted"
    assert bus.requests[0].idempotency_key == "task-1"


async def test_task_routing_result_timeout_returns_typed_unavailable() -> None:
    bus = _FakeBus()
    adapter = BusTaskRouting(bus, _directory())

    result = await adapter.report_routed_task_result(
        routed_task_id="task-1",
        authority_ref="registry:alpha",
        result=RoutedTaskResult(routed_task_id="task-1", status="completed", summary="done"),
    )

    assert result.status == "unavailable"
    assert "timed out" in result.error


async def test_task_routing_status_update_preserves_timeline_progress_and_updated_at() -> None:
    bus = _FakeBus()
    adapter = BusTaskRouting(bus, _directory())

    await adapter.update_routed_task_status(
        update=RoutedTaskUpdate(
            routed_task_id="task-1",
            status="running",
            summary="halfway",
            timeline_events=(
                {
                    "event_id": "evt-1",
                    "conversation_id": "parent-1",
                    "kind": "progress",
                    "title": "Halfway",
                    "progress": 50,
                },
            ),
            progress=50,
            updated_at="2026-03-20T00:00:00+00:00",
        ),
        authority_ref="registry:alpha",
    )

    payload = json.loads(bus.submitted[0].payload_json)
    assert payload["progress"] == 50
    assert payload["updated_at"] == "2026-03-20T00:00:00+00:00"
    assert payload["timeline_events"][0]["event_id"] == "evt-1"
    assert bus.submitted[0].idempotency_key == "task-1:2026-03-20T00:00:00+00:00"


async def test_agent_directory_scatter_gather_returns_partial_result_on_timeout() -> None:
    bus = _FakeBus()
    bus._request_replies["registry:alpha"] = ControlReply(
        command_id="reply-1",
        status="completed",
        result_json=AgentSearchResult(
            status="complete",
            agents=[
                DiscoveredAgentRef(
                    authority_ref="registry:alpha",
                    agent_id="agent-1",
                    display_name="Alpha",
                )
            ],
            responding_authorities=["registry:alpha"],
            timed_out_authorities=[],
        ).model_dump_json(),
    )
    bus._request_replies["registry:beta"] = TimeoutError("timeout")
    adapter = BusAgentDirectory(bus, _directory())

    result = await adapter.search_agents(query=AgentDiscoveryQuery(role="ops"))

    assert result.status == "partial"
    assert [agent.agent_id for agent in result.agents] == ["agent-1"]
    assert result.responding_authorities == ["registry:alpha"]
    assert result.timed_out_authorities == ["registry:beta"]


async def test_agent_directory_returns_typed_unavailable_when_no_authorities_exist() -> None:
    adapter = BusAgentDirectory(_FakeBus(), ControlPlaneDirectory())

    search = await adapter.search_agents(query=AgentDiscoveryQuery(role="ops"))
    resolution = await adapter.resolve_target_authority(target_agent_id="agent-1")

    assert search.status == "unavailable"
    assert resolution.status == "unavailable"


async def test_agent_directory_resolve_target_authority_aggregates_resolutions() -> None:
    bus = _FakeBus()
    bus._request_replies["registry:alpha"] = ControlReply(
        command_id="reply-a",
        status="completed",
        result_json=AuthorityResolution(
            status="resolved",
            authority_ref="registry:alpha",
        ).model_dump_json(),
    )
    bus._request_replies["registry:beta"] = ControlReply(
        command_id="reply-b",
        status="completed",
        result_json=AuthorityResolution(status="not_found").model_dump_json(),
    )
    adapter = BusAgentDirectory(bus, _directory())

    resolution = await adapter.resolve_target_authority(target_agent_id="agent-1")

    assert resolution.status == "resolved"
    assert resolution.authority_ref == "registry:alpha"


async def test_health_publication_fans_out_to_health_authorities_only() -> None:
    bus = _FakeBus()
    adapter = BusHealthPublication(bus, _directory())

    await adapter.publish_health(
        report=HealthReport(
            connectivity_state="connected",
            current_capacity=1,
            max_capacity=2,
            runtime_health_json="{}",
        )
    )

    assert [cmd.authority_ref for cmd in bus.submitted] == ["registry:alpha"]


def test_health_publication_connection_summary_reports_authority_capabilities() -> None:
    directory = ControlPlaneDirectory()
    directory.register(capability="conversation_projection", authority_ref="registry:full")
    directory.register(capability="task_routing", authority_ref="registry:full")
    directory.register(capability="agent_directory", authority_ref="registry:coord")
    directory.register(capability="conversation_projection", authority_ref="registry:channel")
    adapter = BusHealthPublication(_FakeBus(), directory)

    summary = adapter.connection_summary()

    assert [authority.model_dump() for authority in summary.authorities] == [
        {
            "authority_ref": "registry:channel",
            "connectivity_state": "configured",
            "capabilities": ["conversation_projection"],
        },
        {
            "authority_ref": "registry:coord",
            "connectivity_state": "configured",
            "capabilities": ["agent_directory"],
        },
        {
            "authority_ref": "registry:full",
            "connectivity_state": "configured",
            "capabilities": ["conversation_projection", "task_routing"],
        },
    ]


def test_health_publication_connection_summary_is_empty_without_authorities() -> None:
    adapter = BusHealthPublication(_FakeBus(), ControlPlaneDirectory())

    summary = adapter.connection_summary()

    assert [authority.model_dump() for authority in summary.authorities] == []
