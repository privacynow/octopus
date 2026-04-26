"""Shared protocol service for bot and channel surfaces.

The Registry remains the protocol control plane. This service gives bot
channels one SDK-level interface over the existing Registry client methods and
launch helpers, so channels do not hand-roll protocol semantics.
"""

from __future__ import annotations

from .launch import (
    ProtocolConversationLaunchRequestRecord,
    ProtocolConversationLaunchResultRecord,
    launch_protocol_from_conversation,
    list_launchable_protocols,
    resolve_launchable_protocol,
)
from .models import (
    ProtocolArtifactRecord,
    ProtocolDefinitionRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
)
from .ports import (
    ProtocolCatalogPort,
    ProtocolInvocationPort,
    ProtocolObservationPort,
    ProtocolRunControlPort,
)


class ProtocolService:
    """Product-level protocol operations shared by channel integrations."""

    def __init__(
        self,
        registry: ProtocolCatalogPort | ProtocolInvocationPort | ProtocolObservationPort | ProtocolRunControlPort,
        *,
        catalog: ProtocolCatalogPort | None = None,
        invoker: ProtocolInvocationPort | None = None,
        observer: ProtocolObservationPort | None = None,
        controller: ProtocolRunControlPort | None = None,
    ) -> None:
        self._catalog = catalog or registry
        self._invoker = invoker or registry
        self._observer = observer or registry
        self._controller = controller or registry

    async def list_launchable(
        self,
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> list[ProtocolDefinitionRecord]:
        return await list_launchable_protocols(self._catalog, cursor=cursor, limit=limit)

    async def resolve_launchable(self, protocol_ref: str) -> ProtocolDefinitionRecord:
        return await resolve_launchable_protocol(self._catalog, protocol_ref)

    async def launch_from_conversation(
        self,
        payload: ProtocolConversationLaunchRequestRecord | dict[str, object],
        *,
        idempotency_key: str = "",
        origin: str = "",
    ) -> ProtocolConversationLaunchResultRecord:
        return await launch_protocol_from_conversation(
            self._catalog,
            self._invoker,
            payload,
            idempotency_key=idempotency_key,
            origin=origin,
        )

    async def get_run_status(self, run_id: str) -> ProtocolRunDetailRecord:
        return await self._observer.get_run(run_id)

    async def list_run_artifacts(self, run_id: str) -> list[ProtocolArtifactRecord]:
        try:
            return await self._observer.list_run_artifacts(run_id)
        except AttributeError:
            detail = await self._observer.get_run(run_id)
            return list(detail.artifacts or [])

    async def act_on_run(
        self,
        run_id: str,
        *,
        action: str,
        reason: str = "",
        idempotency_key: str = "",
        expected_version: int | None = None,
    ) -> ProtocolRunMutationRecord:
        return await self._controller.act_on_protocol_run(
            run_id,
            action=action,
            reason=reason,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
        )

    async def export_run(self, run_id: str) -> ProtocolRunExportRecord:
        return await self._observer.export_run(run_id)
