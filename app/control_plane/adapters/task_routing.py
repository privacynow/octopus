"""Bus-backed task-routing adapter."""

from __future__ import annotations

from uuid import uuid4

from octopus_sdk.registry.models import RoutedTaskRequest, RoutedTaskResult, RoutedTaskUpdate
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.control_plane.requests import (
    ReportTaskResultPayload,
    SubmitRoutedTaskPayload,
    TimelineEventPayload,
    UpdateRoutedTaskStatusPayload,
)
from octopus_sdk.task_routing import TaskResultReport, TaskSubmissionResult


def _timeline_payload(event) -> TimelineEventPayload:
    if isinstance(event, dict):
        return TimelineEventPayload.model_validate(dict(event))
    return TimelineEventPayload(
        event_id=event.event_id,
        conversation_id=event.conversation_id,
        kind=event.kind,
        title=event.title,
        body=event.body,
        status=event.status,
        progress=event.progress,
        metadata=dict(event.metadata),
        created_at=event.created_at,
    )


class BusTaskRouting:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    async def submit_routed_task(
        self,
        *,
        request: RoutedTaskRequest,
        authority_ref: str,
    ) -> TaskSubmissionResult:
        payload = SubmitRoutedTaskPayload(
            routed_task_id=request.routed_task_id,
            parent_conversation_id=request.parent_conversation_id,
            origin_agent_id=request.origin_agent_id,
            target_agent_id=request.target_agent_id,
            title=request.title,
            instructions=request.instructions,
            context=dict(request.context),
            constraints=dict(request.constraints),
            requested_capabilities=list(request.requested_capabilities),
            priority=request.priority,
            created_at=request.created_at,
        )
        try:
            reply = await self._bus.request(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="task_routing",
                    operation="submit_routed_task",
                    payload_json=payload.model_dump_json(),
                    authority_ref=authority_ref,
                    idempotency_key=request.routed_task_id,
                )
            )
        except TimeoutError:
            return TaskSubmissionResult(status="unavailable", error="control-plane request timed out")
        if reply.status == "failed":
            return TaskSubmissionResult(status="failed", error=reply.error or "control-plane request failed")
        return TaskSubmissionResult.model_validate_json(reply.result_json or '{"status":"accepted"}')

    async def report_routed_task_result(
        self,
        *,
        routed_task_id: str,
        authority_ref: str,
        result: RoutedTaskResult,
    ) -> TaskResultReport:
        payload = ReportTaskResultPayload(
            routed_task_id=routed_task_id,
            status=result.status,
            transition_id=result.transition_id,
            summary=result.summary,
            full_text=result.full_text,
            artifacts=list(result.artifacts),
            follow_up_questions=list(result.follow_up_questions),
            completed_at=result.completed_at,
        )
        try:
            reply = await self._bus.request(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="task_routing",
                    operation="report_routed_task_result",
                    payload_json=payload.model_dump_json(),
                    authority_ref=authority_ref,
                    idempotency_key=routed_task_id,
                )
            )
        except TimeoutError:
            return TaskResultReport(status="unavailable", error="control-plane request timed out")
        if reply.status == "failed":
            return TaskResultReport(status="failed", error=reply.error or "control-plane request failed")
        return TaskResultReport.model_validate_json(reply.result_json or '{"status":"reported"}')

    async def update_routed_task_status(
        self,
        *,
        update: RoutedTaskUpdate,
        authority_ref: str,
    ) -> None:
        payload = UpdateRoutedTaskStatusPayload(
            routed_task_id=update.routed_task_id,
            status=update.status,
            transition_id=update.transition_id,
            summary=update.summary,
            timeline_events=[_timeline_payload(event) for event in update.timeline_events],
            progress=update.progress,
            updated_at=update.updated_at,
        )
        await self._bus.submit(
            ControlCommand(
                command_id=uuid4().hex,
                capability="task_routing",
                operation="update_routed_task_status",
                payload_json=payload.model_dump_json(),
                authority_ref=authority_ref,
                idempotency_key=update.transition_id,
            )
        )
