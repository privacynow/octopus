from __future__ import annotations

import pytest

from app.agents.client import RegistryClientError
from app.agents.registry_capabilities import (
    registry_authority_capabilities,
    registry_authority_ref,
    registry_id_from_authority_ref,
)
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.types import RegistryConnectionConfig
from app.control_plane.models import ControlCommand
from app.control_plane.requests import (
    PublishHealthRequest,
    ReportTaskResultPayload,
    ResolveTargetAuthorityRequest,
    SearchAgentsRequest,
    SubmitRoutedTaskPayload,
    TimelineEventPayload,
    UpdateRoutedTaskStatusPayload,
)
from app.ports.agent_directory import AgentSearchResult, AuthorityResolution
from app.ports.task_routing import TaskResultReport, TaskSubmissionResult


class _FakeRegistryClient:
    def __init__(self, *, fail: bool = False, search_rows: list[dict] | None = None) -> None:
        self.fail = fail
        self.search_rows = list(search_rows or [])
        self.bound: list[dict] = []
        self.published: list[list[object]] = []
        self.submitted_tasks: list[object] = []
        self.reported_results: list[tuple[str, object]] = []
        self.status_updates: list[tuple[str, object]] = []
        self.heartbeats: list[dict] = []
        self.created_conversations: list[dict] = []
        self.published_events: list[tuple[str, list]] = []

    async def sync_binding(self, **kwargs):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.bound.append(kwargs)
        return {"ok": True}

    async def submit_routed_task(self, request):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.submitted_tasks.append(request)
        return {"routed_task_id": request.routed_task_id, "delivery_id": "delivery-1"}

    async def routed_task_result(self, routed_task_id, result):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.reported_results.append((routed_task_id, result))
        return {"routed_task_id": routed_task_id, "status": "completed"}

    async def routed_task_status(self, routed_task_id, update):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.status_updates.append((routed_task_id, update))
        return {"routed_task_id": routed_task_id, "status": update.status}

    async def search(self, query):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.last_search = query
        return list(self.search_rows)

    async def create_conversation(self, *, target_agent_id, origin_channel, external_conversation_ref, title=""):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        record = {
            "target_agent_id": target_agent_id,
            "origin_channel": origin_channel,
            "external_conversation_ref": external_conversation_ref,
            "title": title,
        }
        self.created_conversations.append(record)
        return {"conversation_id": f"conv-{len(self.created_conversations)}"}

    async def publish_events(self, conversation_id, events):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.published_events.append((conversation_id, list(events)))
        return {"published_count": len(events)}

    async def heartbeat(self, **kwargs):
        if self.fail:
            raise RegistryClientError("registry unavailable", operator_detail="registry unavailable")
        self.heartbeats.append(kwargs)
        return {"ok": True}


class _FakeRegistryRuntime:
    def __init__(self, registries, clients: dict[str, _FakeRegistryClient], *, origin_ids: dict[str, str] | None = None) -> None:
        self.registries = tuple(registries)
        self._clients = clients
        self._origin_ids = dict(origin_ids or {})

    def client_for_registry(self, registry_id: str):
        return self._clients.get(registry_id)

    def origin_agent_id(self, registry_id: str) -> str:
        return self._origin_ids.get(registry_id, "")


def _command(
    command_id: str,
    *,
    capability: str,
    operation: str,
    authority_ref: str,
    payload_json: str,
) -> ControlCommand:
    return ControlCommand(
        command_id=command_id,
        capability=capability,
        operation=operation,
        payload_json=payload_json,
        authority_ref=authority_ref,
    )


def test_registry_authority_capabilities_tracks_scope_in_one_builder() -> None:
    channel = RegistryConnectionConfig(
        registry_id="channel",
        url="http://channel",
        enroll_token="enroll-channel",
        registry_scope="channel",
    )
    coordination = RegistryConnectionConfig(
        registry_id="coord",
        url="http://coord",
        enroll_token="enroll-coord",
        registry_scope="coordination",
    )
    full = RegistryConnectionConfig(
        registry_id="full",
        url="http://full",
        enroll_token="enroll-full",
        registry_scope="full",
    )

    mapping = registry_authority_capabilities((channel, coordination, full))

    assert mapping == {
        "registry:channel": {"conversation_projection", "health_publication"},
        "registry:coord": {"task_routing", "agent_directory", "health_publication"},
        "registry:full": {
            "conversation_projection",
            "task_routing",
            "agent_directory",
            "health_publication",
        },
    }
    assert registry_authority_ref("channel") == "registry:channel"
    assert registry_id_from_authority_ref("registry:coord") == "coord"
    with pytest.raises(ValueError, match="unsupported registry authority_ref"):
        registry_id_from_authority_ref("slack:workspace-1")


@pytest.mark.asyncio
async def test_registry_control_processor_processes_health_commands() -> None:
    registry = RegistryConnectionConfig(
        registry_id="alpha",
        url="http://alpha",
        enroll_token="enroll-alpha",
        registry_scope="full",
    )
    client = _FakeRegistryClient()
    processor = RegistryControlProcessor(_FakeRegistryRuntime((registry,), {"alpha": client}))

    health_reply = await processor.process(
        _command(
            "cmd-health",
            capability="health_publication",
            operation="publish_health",
            authority_ref="registry:alpha",
            payload_json=PublishHealthRequest(
                connectivity_state="connected",
                current_capacity=1,
                max_capacity=2,
                runtime_health_json='{"summary":{"ok":true}}',
            ).model_dump_json(),
        )
    )

    assert health_reply.status == "completed"
    assert client.heartbeats == [
        {
            "connectivity_state": "connected",
            "current_capacity": 1,
            "max_capacity": 2,
            "runtime_health": {"summary": {"ok": True}},
        }
    ]


@pytest.mark.asyncio
async def test_registry_control_processor_processes_task_routing_and_directory_commands() -> None:
    registry = RegistryConnectionConfig(
        registry_id="alpha",
        url="http://alpha",
        enroll_token="enroll-alpha",
        registry_scope="full",
    )
    client = _FakeRegistryClient(
        search_rows=[
            {
                "agent_id": "target-1",
                "display_name": "Target",
                "slug": "target",
                "role": "ops",
                "capabilities": ["bash"],
                "tags": ["prod"],
                "description": "Target agent",
                "connectivity_state": "connected",
                "current_capacity": 1,
                "max_capacity": 2,
            }
        ]
    )
    runtime = _FakeRegistryRuntime((registry,), {"alpha": client}, origin_ids={"alpha": "self-alpha"})
    processor = RegistryControlProcessor(runtime)

    submit_reply = await processor.process(
        _command(
            "cmd-submit",
            capability="task_routing",
            operation="submit_routed_task",
            authority_ref="registry:alpha",
            payload_json=SubmitRoutedTaskPayload(
                routed_task_id="task-1",
                parent_conversation_id="parent-1",
                origin_agent_id="origin-1",
                target_agent_id="target-1",
                title="Investigate",
                instructions="Check logs",
                context={"severity": "high"},
                constraints={"mode": "readonly"},
                requested_capabilities=["bash"],
                created_at="2026-03-20T00:00:00+00:00",
            ).model_dump_json(),
        )
    )
    status_reply = await processor.process(
        _command(
            "cmd-status",
            capability="task_routing",
            operation="update_routed_task_status",
            authority_ref="registry:alpha",
            payload_json=UpdateRoutedTaskStatusPayload(
                routed_task_id="task-1",
                status="running",
                summary="halfway",
                timeline_events=[
                    TimelineEventPayload(
                        event_id="evt-1",
                        conversation_id="parent-1",
                        kind="progress",
                        title="Halfway",
                        progress=50,
                        created_at="2026-03-20T00:00:00+00:00",
                    )
                ],
                progress=50,
                updated_at="2026-03-20T00:00:10+00:00",
            ).model_dump_json(),
        )
    )
    result_reply = await processor.process(
        _command(
            "cmd-result",
            capability="task_routing",
            operation="report_routed_task_result",
            authority_ref="registry:alpha",
            payload_json=ReportTaskResultPayload(
                routed_task_id="task-1",
                status="completed",
                summary="done",
                full_text="all good",
                artifacts=[{"path": "/tmp/report.txt"}],
                follow_up_questions=["next?"],
                completed_at="2026-03-20T00:01:00+00:00",
            ).model_dump_json(),
        )
    )
    search_reply = await processor.process(
        _command(
            "cmd-search",
            capability="agent_directory",
            operation="search_agents",
            authority_ref="registry:alpha",
            payload_json=SearchAgentsRequest(role="ops").model_dump_json(),
        )
    )
    resolve_reply = await processor.process(
        _command(
            "cmd-resolve",
            capability="agent_directory",
            operation="resolve_target_authority",
            authority_ref="registry:alpha",
            payload_json=ResolveTargetAuthorityRequest(target_agent_id="target-1").model_dump_json(),
        )
    )

    submission = TaskSubmissionResult.model_validate_json(submit_reply.result_json or "{}")
    report = TaskResultReport.model_validate_json(result_reply.result_json or "{}")
    search = AgentSearchResult.model_validate_json(search_reply.result_json or "{}")
    resolution = AuthorityResolution.model_validate_json(resolve_reply.result_json or "{}")

    assert submit_reply.status == "completed"
    assert status_reply.status == "completed"
    assert result_reply.status == "completed"
    assert search_reply.status == "completed"
    assert resolve_reply.status == "completed"
    assert submission.status == "accepted"
    assert submission.delivery_id == "delivery-1"
    assert report.status == "reported"
    assert search.agents[0].authority_ref == "registry:alpha"
    assert search.agents[0].agent_id == "target-1"
    assert resolution.status == "resolved"
    assert resolution.authority_ref == "registry:alpha"
    assert client.submitted_tasks[0].context == {"severity": "high"}
    assert client.status_updates[0][1].timeline_events[0]["event_id"] == "evt-1"
    assert client.status_updates[0][1].progress == 50
    assert client.status_updates[0][1].updated_at == "2026-03-20T00:00:10+00:00"
    assert client.reported_results[0][1].artifacts == ({"path": "/tmp/report.txt"},)
    assert client.last_search.exclude_agent_ids == ("self-alpha",)


@pytest.mark.asyncio
async def test_registry_control_processor_returns_failed_reply_without_blocking_other_authorities() -> None:
    alpha = RegistryConnectionConfig(
        registry_id="alpha",
        url="http://alpha",
        enroll_token="enroll-alpha",
        registry_scope="full",
    )
    beta = RegistryConnectionConfig(
        registry_id="beta",
        url="http://beta",
        enroll_token="enroll-beta",
        registry_scope="full",
    )
    runtime = _FakeRegistryRuntime(
        (alpha, beta),
        {
            "alpha": _FakeRegistryClient(fail=True),
            "beta": _FakeRegistryClient(),
        },
    )
    processor = RegistryControlProcessor(runtime)

    failed = await processor.process(
        _command(
            "cmd-alpha",
            capability="health_publication",
            operation="publish_health",
            authority_ref="registry:alpha",
            payload_json=PublishHealthRequest(
                connectivity_state="connected",
                current_capacity=1,
                max_capacity=2,
            ).model_dump_json(),
        )
    )
    succeeded = await processor.process(
        _command(
            "cmd-beta",
            capability="health_publication",
            operation="publish_health",
            authority_ref="registry:beta",
            payload_json=PublishHealthRequest(
                connectivity_state="connected",
                current_capacity=1,
                max_capacity=2,
            ).model_dump_json(),
        )
    )

    assert failed.status == "failed"
    assert "registry unavailable" in (failed.error or "")
    assert succeeded.status == "completed"


@pytest.mark.asyncio
async def test_registry_control_processor_processes_create_conversation() -> None:
    registry = RegistryConnectionConfig(
        registry_id="alpha",
        url="http://alpha",
        enroll_token="enroll-alpha",
        registry_scope="full",
    )
    client = _FakeRegistryClient()
    processor = RegistryControlProcessor(_FakeRegistryRuntime((registry,), {"alpha": client}))

    import json

    reply = await processor.process(
        _command(
            "cmd-create-conv",
            capability="conversation_projection",
            operation="create_conversation",
            authority_ref="registry:alpha",
            payload_json=json.dumps({
                "target_agent_id": "agent-1",
                "origin_channel": "telegram",
                "external_conversation_ref": "chat-123",
                "title": "Test conversation",
            }),
        )
    )

    assert reply.status == "completed"
    result = json.loads(reply.result_json or "{}")
    assert result["conversation_id"] == "conv-1"
    assert len(client.created_conversations) == 1
    assert client.created_conversations[0]["target_agent_id"] == "agent-1"
    assert client.created_conversations[0]["origin_channel"] == "telegram"


@pytest.mark.asyncio
async def test_registry_control_processor_processes_publish_events() -> None:
    registry = RegistryConnectionConfig(
        registry_id="alpha",
        url="http://alpha",
        enroll_token="enroll-alpha",
        registry_scope="full",
    )
    client = _FakeRegistryClient()
    processor = RegistryControlProcessor(_FakeRegistryRuntime((registry,), {"alpha": client}))

    import json

    reply = await processor.process(
        _command(
            "cmd-publish-events",
            capability="conversation_projection",
            operation="publish_events",
            authority_ref="registry:alpha",
            payload_json=json.dumps({
                "conversation_id": "conv-1",
                "events": [
                    {
                        "event_id": "evt-1",
                        "kind": "message.user",
                        "actor": "user",
                        "content": "Hello",
                        "metadata": {},
                    }
                ],
            }),
        )
    )

    assert reply.status == "completed"
    assert len(client.published_events) == 1
    assert client.published_events[0][0] == "conv-1"
    assert len(client.published_events[0][1]) == 1
    assert client.published_events[0][1][0].kind == "message.user"
