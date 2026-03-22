from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.control_plane.models import ControlCommand, ControlReply
from app.control_plane.requests import (
    ReportTaskResultPayload,
    ResolveTargetAuthorityRequest,
    SearchAgentsRequest,
    SubmitRoutedTaskPayload,
    TimelineEventPayload,
    UpdateRoutedTaskStatusPayload,
)


def test_control_command_requires_non_empty_authority_ref() -> None:
    with pytest.raises(ValidationError):
        ControlCommand(
            command_id="cmd-1",
            capability="conversation_projection",
            operation="create_conversation",
            payload_json="{}",
            authority_ref="",
        )


def test_control_reply_rejects_completed_reply_with_error() -> None:
    with pytest.raises(ValidationError):
        ControlReply(
            command_id="cmd-1",
            status="completed",
            error="boom",
        )


def test_control_reply_requires_error_for_failed_reply() -> None:
    with pytest.raises(ValidationError):
        ControlReply(
            command_id="cmd-1",
            status="failed",
        )


def test_control_reply_rejects_failed_reply_with_result_payload() -> None:
    with pytest.raises(ValidationError):
        ControlReply(
            command_id="cmd-1",
            status="failed",
            error="boom",
            result_json='{"ok": false}',
        )


def test_control_plane_request_models_validate_domain_payloads() -> None:
    task = SubmitRoutedTaskPayload(
        routed_task_id="task-1",
        parent_conversation_id="parent-1",
        origin_agent_id="origin-1",
        target_agent_id="target-1",
        title="Investigate",
        instructions="Check the thing",
        context={"ticket": 42},
        constraints={"readonly": True},
        requested_capabilities=["logs"],
        created_at="2026-03-20T00:00:00+00:00",
    )
    event = TimelineEventPayload(
        event_id="evt-1",
        conversation_id="parent-1",
        kind="progress",
        title="Halfway",
        metadata={"phase": 1},
        created_at="2026-03-20T00:00:00+00:00",
    )
    update = UpdateRoutedTaskStatusPayload(
        routed_task_id="task-1",
        status="running",
        summary="halfway",
        timeline_events=[event],
        progress=50,
        updated_at="2026-03-20T00:01:00+00:00",
    )
    result = ReportTaskResultPayload(
        routed_task_id="task-1",
        status="completed",
        summary="done",
        full_text="all done",
        artifacts=[{"path": "/tmp/out.txt"}],
        follow_up_questions=["Need anything else?"],
        completed_at="2026-03-20T00:02:00+00:00",
    )
    search = SearchAgentsRequest(
        role="ops",
        capabilities=["logs"],
        tags=["oncall"],
        free_text="incident",
        exclude_agent_ids=["agent-1"],
        required_state="connected",
    )
    resolve = ResolveTargetAuthorityRequest(target_agent_id="agent-2")

    assert task.context == {"ticket": 42}
    assert task.constraints == {"readonly": True}
    assert update.timeline_events[0].event_id == "evt-1"
    assert result.artifacts == [{"path": "/tmp/out.txt"}]
    assert search.exclude_agent_ids == ["agent-1"]
    assert resolve.target_agent_id == "agent-2"
