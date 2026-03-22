"""Bus-backed conversation projection adapter."""

from __future__ import annotations

import json
from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand


class BusConversationProjection:
    def __init__(self, bus: ControlPlaneBus, directory: ControlPlaneDirectory) -> None:
        self._bus = bus
        self._directory = directory

    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str,
    ) -> str:
        payload = json.dumps({
            "target_agent_id": target_agent_id,
            "origin_channel": origin_channel,
            "external_conversation_ref": external_conversation_ref,
            "title": title,
        })
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )
        if not authorities:
            raise RuntimeError("no authority registered for conversation_projection")
        authority_ref = authorities[0]
        reply = await self._bus.request(
            ControlCommand(
                command_id=uuid4().hex,
                capability="conversation_projection",
                operation="create_conversation",
                payload_json=payload,
                authority_ref=authority_ref,
                idempotency_key=f"{target_agent_id}:{origin_channel}:{external_conversation_ref}",
            )
        )
        if reply.status == "failed":
            raise RuntimeError(reply.error or "create_conversation failed")
        result = json.loads(reply.result_json or "{}")
        return str(result.get("conversation_id", ""))

    async def publish_events(
        self,
        *,
        conversation_id: str,
        events: list,
    ) -> None:
        payload = json.dumps({
            "conversation_id": conversation_id,
            "events": [e.model_dump() for e in events],
        })
        for authority_ref in sorted(
            self._directory.authorities_for_capability("conversation_projection")
        ):
            await self._bus.submit(
                ControlCommand(
                    command_id=uuid4().hex,
                    capability="conversation_projection",
                    operation="publish_events",
                    payload_json=payload,
                    authority_ref=authority_ref,
                    idempotency_key=f"{conversation_id}:{','.join(e.event_id for e in events)}",
                )
            )
