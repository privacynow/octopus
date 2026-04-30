"""Bus-backed registry-inspection adapter."""

from __future__ import annotations

from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.control_plane.requests import (
    GetConversationRequest,
    GetTaskRequest,
    ListConversationEventsRequest,
)
from octopus_sdk.registry.models import ConversationRecord, EventPageRecord, TaskRecord
from octopus_sdk.registry_inspection import RegistryInspectionPort


class BusRegistryInspection(RegistryInspectionPort):
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    def _validated_implementation_ref(self, implementation_ref: str) -> str:
        authorities = sorted(self._directory.implementations_for_admin_interface("registry_inspection"))
        if not implementation_ref or implementation_ref not in authorities:
            raise RuntimeError("registry inspection unavailable")
        return implementation_ref

    async def get_conversation(self, implementation_ref: str, conversation_id: str) -> ConversationRecord:
        payload = GetConversationRequest(conversation_id=conversation_id)
        reply = await self._bus.request(
            ControlCommand(
                command_id=uuid4().hex,
                admin_interface="registry_inspection",
                admin_operation="get_conversation",
                payload_json=payload.model_dump_json(),
                implementation_ref=self._validated_implementation_ref(implementation_ref),
                idempotency_key=f"registry-inspection:conversation:{conversation_id}",
            )
        )
        if reply.status == "failed":
            raise RuntimeError(reply.error or "registry inspection failed")
        return ConversationRecord.model_validate_json(reply.result_json or "{}")

    async def get_task(self, implementation_ref: str, routed_task_id: str) -> TaskRecord:
        payload = GetTaskRequest(routed_task_id=routed_task_id)
        reply = await self._bus.request(
            ControlCommand(
                command_id=uuid4().hex,
                admin_interface="registry_inspection",
                admin_operation="get_task",
                payload_json=payload.model_dump_json(),
                implementation_ref=self._validated_implementation_ref(implementation_ref),
                idempotency_key=f"registry-inspection:task:{routed_task_id}",
            )
        )
        if reply.status == "failed":
            raise RuntimeError(reply.error or "registry inspection failed")
        return TaskRecord.model_validate_json(reply.result_json or "{}")

    async def list_events(
        self,
        implementation_ref: str,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        payload = ListConversationEventsRequest(
            conversation_id=conversation_id,
            kind=kind,
            before_seq=before_seq,
            after_seq=after_seq,
            limit=limit,
        )
        reply = await self._bus.request(
            ControlCommand(
                command_id=uuid4().hex,
                admin_interface="registry_inspection",
                admin_operation="list_events",
                payload_json=payload.model_dump_json(),
                implementation_ref=self._validated_implementation_ref(implementation_ref),
                idempotency_key=(
                    f"registry-inspection:events:{conversation_id}:"
                    f"{kind}:{before_seq}:{after_seq}:{limit}"
                ),
            )
        )
        if reply.status == "failed":
            raise RuntimeError(reply.error or "registry inspection failed")
        return EventPageRecord.model_validate_json(reply.result_json or "{}")
