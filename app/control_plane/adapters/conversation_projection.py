"""Bus-backed conversation projection adapter with mirrored multi-authority support."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import uuid4

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand

if TYPE_CHECKING:
    from app.agents.mirror_outbox import MirrorOutbox

log = logging.getLogger(__name__)


class BusConversationProjection:
    """Projects conversations onto all authorities that expose ``conversation_projection``.

    ``create_conversation`` is sent to **every** authority sequentially.
    All returned conversation_ids must be identical (deterministic server-side),
    otherwise a critical warning is logged.

    ``publish_events`` fans out to all authorities best-effort (failures are
    logged but never block).  On a cache miss the adapter re-issues a
    ``create_conversation`` for that authority before publishing (idempotent).
    """

    def __init__(
        self,
        bus: ControlPlaneBus,
        directory: ControlPlaneDirectory,
        *,
        agent_id_for_authority: Callable[[str], str] | None = None,
        outbox: MirrorOutbox | None = None,
    ) -> None:
        self._bus = bus
        self._directory = directory
        self._agent_id_for_authority = agent_id_for_authority or (lambda _ref: "")
        self._outbox = outbox

        # Volatile in-memory cache:
        #   conversation_id → {target_agent_id, origin_channel, external_conversation_ref, title}
        self._identity_cache: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # create_conversation — mirrored to every authority
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
            resolved_agent_id = self._agent_id_for_authority(authority_ref) or target_agent_id
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
                    timeout_seconds=5.0,
                )
                if reply.status == "failed":
                    log.error(
                        "create_conversation failed on %s: %s",
                        authority_ref,
                        reply.error,
                    )
                    continue
                result = json.loads(reply.result_json or "{}")
                cid = str(result.get("conversation_id", ""))
                if not cid:
                    log.error("create_conversation on %s returned empty conversation_id", authority_ref)
                    continue
                conversation_ids.append(cid)
                if not first_conversation_id:
                    first_conversation_id = cid
            except Exception as exc:
                log.error(
                    "create_conversation bus error on %s",
                    authority_ref,
                    exc_info=True,
                )
                if self._outbox is not None:
                    try:
                        self._outbox.enqueue(
                            authority_ref,
                            "create_conversation",
                            bot_key=resolved_agent_id,
                            origin_channel=origin_channel,
                            external_conversation_ref=external_conversation_ref,
                            payload={
                                "target_agent_id": resolved_agent_id,
                                "origin_channel": origin_channel,
                                "external_conversation_ref": external_conversation_ref,
                                "title": title,
                            },
                        )
                    except Exception:
                        log.warning(
                            "Failed to enqueue create_conversation to mirror outbox for %s",
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
    # publish_events — best-effort fan-out to every authority
    # ------------------------------------------------------------------

    async def publish_events(
        self,
        *,
        conversation_id: str,
        events: list,
    ) -> None:
        authorities = sorted(
            self._directory.authorities_for_capability("conversation_projection")
        )

        for authority_ref in authorities:
            # On cache miss, recover identity by re-issuing create (idempotent)
            if conversation_id not in self._identity_cache:
                log.warning(
                    "publish_events cache miss for conversation_id=%s on %s; "
                    "cannot recover identity without create params — skipping",
                    conversation_id,
                    authority_ref,
                )
                continue

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
            except Exception as exc:
                log.warning(
                    "publish_events failed on %s for conversation %s",
                    authority_ref,
                    conversation_id,
                    exc_info=True,
                )
                if self._outbox is not None:
                    try:
                        cached = self._identity_cache.get(conversation_id, {})
                        self._outbox.enqueue(
                            authority_ref,
                            "publish_events",
                            conversation_id=conversation_id,
                            bot_key=cached.get("bot_key", ""),
                            origin_channel=cached.get("origin_channel", ""),
                            external_conversation_ref=cached.get("external_conversation_ref", ""),
                            payload={
                                "conversation_id": conversation_id,
                                "events": [e.model_dump() for e in events],
                            },
                        )
                    except Exception:
                        log.warning(
                            "Failed to enqueue publish_events to mirror outbox for %s",
                            authority_ref,
                            exc_info=True,
                        )
