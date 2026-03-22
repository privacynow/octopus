"""Bus-backed conversation projection adapter."""

from __future__ import annotations

from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.control_plane.requests import BindConversationRequest, PublishTimelineRequest


class BusConversationProjection:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    async def bind_external_conversation(
        self,
        *,
        conversation_ref: str,
        title: str,
        origin_channel: str,
        external_id: str,
    ) -> None:
        request = BindConversationRequest(
            conversation_ref=conversation_ref,
            title=title,
            origin_channel=origin_channel,
            external_id=external_id,
        )
        for authority_ref in sorted(
            self._directory.authorities_for_capability("conversation_projection")
        ):
            await self._bus.submit(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="conversation_projection",
                    operation="bind_conversation",
                    payload_json=request.model_dump_json(),
                    authority_ref=authority_ref,
                )
            )

    async def publish_external_timeline(
        self,
        *,
        conversation_ref: str,
        kind: str,
        title: str,
        body: str = "",
        status: str = "",
        progress: int | None = None,
        metadata: dict | None = None,
        event_id: str | None = None,
    ) -> None:
        request = PublishTimelineRequest(
            conversation_ref=conversation_ref,
            kind=kind,
            title=title,
            body=body,
            status=status,
            progress=progress,
            metadata=metadata or {},
            event_id=event_id,
        )
        for authority_ref in sorted(
            self._directory.authorities_for_capability("conversation_projection")
        ):
            await self._bus.submit(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="conversation_projection",
                    operation="publish_timeline",
                    payload_json=request.model_dump_json(),
                    authority_ref=authority_ref,
                    idempotency_key=event_id or "",
                )
            )
