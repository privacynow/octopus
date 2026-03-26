"""Bus-backed conversation projection adapter with mirrored multi-authority support."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand
from app.control_plane.requests import (
    AddConversationMessagePayload,
    SubmitConversationActionPayload,
)
from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    CoordinationActionEnvelope,
    CoordinationActionResult,
    MessageRecord,
)

log = logging.getLogger(__name__)


def _unconfigured_agent_id_for_authority(authority_ref: str) -> str:
    raise RuntimeError(
        f"conversation_projection agent_id_for_authority not configured for {authority_ref}"
    )


class BusConversationProjection:
    """Projects conversations onto all authorities that expose ``conversation_projection``.

    ``create_conversation`` is sent to **every** authority sequentially.
    All returned conversation_ids must be identical (deterministic server-side),
    otherwise a critical warning is logged.

    ``publish_events`` fans out to all authorities best-effort (failures are
    logged but never block).  On a cache miss the adapter re-issues a
    ``create_conversation`` for that authority before publishing (idempotent).
    """

    bus_timeout_seconds: float = 5.0

    def __init__(
        self,
        bus: ControlPlaneBus,
        directory: ControlPlaneDirectory,
        *,
        agent_id_for_authority: Callable[[str], str] | None = None,
    ) -> None:
        self._bus = bus
        self._directory = directory
        if agent_id_for_authority is None:
            self._agent_id_for_authority = _unconfigured_agent_id_for_authority
        else:
            self._agent_id_for_authority = agent_id_for_authority

        # Volatile in-memory cache:
        #   conversation_id -> {target_agent_id, origin_channel, external_conversation_ref, title}
        self._identity_cache: dict[str, dict[str, str]] = {}

    def _resolved_agent_id(self, authority_ref: str) -> str:
        agent_id = self._agent_id_for_authority(authority_ref)
        if not agent_id:
            raise RuntimeError(
                f"conversation_projection missing agent_id for authority {authority_ref}"
            )
        return agent_id

    # ------------------------------------------------------------------
    # create_conversation -- mirrored to every authority
    # ------------------------------------------------------------------

    async def create_conversation(
        self,
        *,
        target_agent_id: str,
        origin_channel: str,
        external_conversation_ref: str,
        title: str,
    ) -> str:
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )
        if not authorities:
            raise RuntimeError("no authority registered for conversation_projection")

        conversation_ids: list[str] = []
        first_conversation_id: str = ""

        for authority_ref in authorities:
            resolved_agent_id = self._resolved_agent_id(authority_ref)
            payload = json.dumps({
                "target_agent_id": resolved_agent_id,
                "origin_channel": origin_channel,
                "external_conversation_ref": external_conversation_ref,
                "title": title,
            })
            idempotency_key = (
                f"{resolved_agent_id}:{origin_channel}:{external_conversation_ref}"
            )
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        capability="conversation_projection",
                        operation="create_conversation",
                        payload_json=payload,
                        authority_ref=authority_ref,
                        idempotency_key=idempotency_key,
                    ),
                    timeout_seconds=self.bus_timeout_seconds,
                )
                if reply.status == "failed":
                    log.error(
                        "create_conversation failed on %s: %s",
                        authority_ref,
                        reply.error,
                    )
                    continue
                result_json = reply.result_json if reply.result_json is not None else "{}"
                result = json.loads(result_json)
                cid = str(result.get("conversation_id", ""))
                if not cid:
                    log.error("create_conversation on %s returned empty conversation_id", authority_ref)
                    continue
                conversation_ids.append(cid)
                if not first_conversation_id:
                    first_conversation_id = cid
            except Exception:
                log.error(
                    "create_conversation bus error on %s",
                    authority_ref,
                    exc_info=True,
                )
                try:
                    await self._bus.submit(ControlCommand(
                        command_id=uuid4().hex,
                        capability="mirror_retry",
                        operation="create_conversation",
                        payload_json=json.dumps({
                            "target_agent_id": resolved_agent_id,
                            "origin_channel": origin_channel,
                            "external_conversation_ref": external_conversation_ref,
                            "title": title,
                        }),
                        authority_ref=authority_ref,
                        idempotency_key=f"mirror:create:{resolved_agent_id}:{origin_channel}:{external_conversation_ref}",
                        max_retries=10,
                    ))
                except Exception:
                    log.warning(
                        "Failed to submit mirror_retry create_conversation for %s",
                        authority_ref,
                        exc_info=True,
                    )

        if not first_conversation_id:
            raise RuntimeError("create_conversation failed on all authorities")

        # Verify deterministic IDs across authorities
        mismatched = [cid for cid in conversation_ids if cid != first_conversation_id]
        if mismatched:
            log.critical(
                "CONVERSATION ID MISMATCH across authorities: primary=%s mismatched=%s",
                first_conversation_id,
                mismatched,
            )

        # Populate in-memory cache
        self._identity_cache[first_conversation_id] = {
            "target_agent_id": target_agent_id,
            "origin_channel": origin_channel,
            "external_conversation_ref": external_conversation_ref,
            "title": title,
        }

        return first_conversation_id

    # ------------------------------------------------------------------
    # publish_events -- best-effort fan-out to every authority
    # ------------------------------------------------------------------

    async def publish_events(
        self,
        *,
        conversation_id: str,
        events: list[ConversationEvent],
    ) -> None:
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )
        if not authorities:
            return
        if conversation_id not in self._identity_cache and authorities:
            recovery_authority = authorities[0]
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        capability="conversation_projection",
                        operation="get_conversation",
                        payload_json=json.dumps({"conversation_id": conversation_id}),
                        authority_ref=recovery_authority,
                    ),
                    timeout_seconds=self.bus_timeout_seconds,
                )
                if reply.status == "completed" and reply.result_json:
                    conv = json.loads(reply.result_json)
                    oc = conv.get("origin_channel", "")
                    ecr = conv.get("external_conversation_ref", "")
                    if oc and ecr:
                        self._identity_cache[conversation_id] = {
                            "target_agent_id": conv.get("target_agent_id", ""),
                            "origin_channel": oc,
                            "external_conversation_ref": ecr,
                            "title": conv.get("title", ""),
                        }
            except Exception:
                log.warning(
                    "Failed to recover canonical identity for conversation %s",
                    conversation_id,
                    exc_info=True,
                )
        for authority_ref in authorities:
            cached = self._identity_cache.get(conversation_id)
            if not cached:
                log.warning(
                    "publish_events: cannot recover canonical identity for %s on %s; skipping",
                    conversation_id,
                    authority_ref,
                )
                continue
            try:
                resolved_agent_id = self._resolved_agent_id(authority_ref)
                create_payload = json.dumps({
                    "target_agent_id": resolved_agent_id,
                    "origin_channel": cached["origin_channel"],
                    "external_conversation_ref": cached["external_conversation_ref"],
                    "title": cached.get("title", ""),
                })
                await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        capability="conversation_projection",
                        operation="create_conversation",
                        payload_json=create_payload,
                        authority_ref=authority_ref,
                        idempotency_key=(
                            f"{resolved_agent_id}:{cached['origin_channel']}:"
                            f"{cached['external_conversation_ref']}"
                        ),
                    ),
                    timeout_seconds=self.bus_timeout_seconds,
                )
            except Exception:
                log.warning(
                    "create-before-publish failed on %s for conversation %s; proceeding with publish anyway",
                    authority_ref,
                    conversation_id,
                    exc_info=True,
                )
            payload = json.dumps({
                "conversation_id": conversation_id,
                "events": [e.model_dump() for e in events],
            })
            try:
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
            except Exception:
                log.warning(
                    "publish_events failed on %s for conversation %s",
                    authority_ref,
                    conversation_id,
                    exc_info=True,
                )
                try:
                    await self._bus.submit(
                        ControlCommand(
                            command_id=uuid4().hex,
                            capability="mirror_retry",
                            operation="publish_events",
                            payload_json=payload,
                            authority_ref=authority_ref,
                            idempotency_key=(
                                f"mirror:publish:{conversation_id}:"
                                f"{','.join(e.event_id for e in events)}"
                            ),
                            max_retries=10,
                        )
                    )
                except Exception:
                    log.warning(
                        "Failed to submit mirror_retry publish_events for %s",
                        authority_ref,
                        exc_info=True,
                    )

    async def add_message(
        self,
        *,
        conversation_id: str,
        text: str,
    ) -> MessageRecord:
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )
        if not authorities:
            raise RuntimeError("no authority registered for conversation_projection")
        payload = AddConversationMessagePayload(
            conversation_id=conversation_id,
            text=text,
        )
        first_success: MessageRecord | None = None
        last_error = "add_message failed on all authorities"
        for authority_ref in authorities:
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        capability="conversation_projection",
                        operation="add_message",
                        payload_json=payload.model_dump_json(),
                        authority_ref=authority_ref,
                        idempotency_key=f"{conversation_id}:message:{text}",
                    ),
                    timeout_seconds=self.bus_timeout_seconds,
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if reply.status == "failed":
                last_error = reply.error or last_error
                continue
            result = MessageRecord.model_validate_json(reply.result_json or "{}")
            if first_success is None:
                first_success = result
        if first_success is None:
            raise RuntimeError(last_error)
        return first_success

    async def submit_action(
        self,
        *,
        conversation_id: str,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )
        if not authorities:
            raise RuntimeError("no authority registered for conversation_projection")
        payload = SubmitConversationActionPayload(
            conversation_id=conversation_id,
            envelope=envelope,
        )
        first_success: CoordinationActionResult | None = None
        last_error = "submit_action failed on all authorities"
        for authority_ref in authorities:
            try:
                reply = await self._bus.request(
                    ControlCommand(
                        command_id=uuid4().hex,
                        capability="conversation_projection",
                        operation="submit_action",
                        payload_json=payload.model_dump_json(),
                        authority_ref=authority_ref,
                        idempotency_key=envelope.action_id,
                    ),
                    timeout_seconds=self.bus_timeout_seconds,
                )
            except Exception as exc:
                last_error = str(exc)
                continue
            if reply.status == "failed":
                last_error = reply.error or last_error
                continue
            result = CoordinationActionResult.model_validate_json(
                reply.result_json or "{}"
            )
            if result.accepted and first_success is None:
                first_success = result
        if first_success is None:
            raise RuntimeError(last_error)
        return first_success
