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
        payload = SubmitRoutedTaskPayload.model_validate(request.model_dump(mode="json"))
        try:
            reply = await self._bus.request(
                ControlCommand(
                    command_id=uuid4().hex,
                    admin_interface="task_routing",
                    admin_operation="submit_routed_task",
                    payload_json=payload.model_dump_json(),
                    implementation_ref=authority_ref,
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
        payload = ReportTaskResultPayload.model_validate(
            {
                **result.model_dump(mode="json"),
                "routed_task_id": routed_task_id,
            }
        )
        try:
            reply = await self._bus.request(
                ControlCommand(
                    command_id=uuid4().hex,
                    admin_interface="task_routing",
                    admin_operation="report_routed_task_result",
                    payload_json=payload.model_dump_json(),
                    implementation_ref=authority_ref,
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
                admin_interface="task_routing",
                admin_operation="update_routed_task_status",
                payload_json=payload.model_dump_json(),
                implementation_ref=authority_ref,
                idempotency_key=update.transition_id,
            )
        )
