"""Shared protocol service for bot and channel surfaces.

The Registry remains the protocol control plane. This service gives bot
channels one SDK-level interface over the existing Registry client methods and
launch helpers, so channels do not hand-roll protocol semantics.
"""

from __future__ import annotations

from .launch import (
    ProtocolConversationLaunchRequestRecord,
    ProtocolConversationLaunchResultRecord,
    build_protocol_run_request_from_inputs,
    launch_protocol_from_conversation,
    list_launchable_protocols,
    protocol_run_launch_form,
    resolve_launchable_protocol,
)
from .models import (
    ProtocolArtifactRecord,
    ProtocolDefinitionRecord,
    ProtocolRunInputFieldRecord,
    ProtocolRunLaunchFormRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
)
from .ports import (
    ProtocolArtifactAccessPort,
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
        artifact_access: ProtocolArtifactAccessPort | None = None,
    ) -> None:
        self._catalog = catalog or registry
        self._invoker = invoker or registry
        self._observer = observer or registry
        self._controller = controller or registry
        self._artifact_access = artifact_access or registry

    async def list_launchable(
        self,
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> list[ProtocolDefinitionRecord]:
        return await list_launchable_protocols(self._catalog, cursor=cursor, limit=limit)

    async def resolve_launchable(self, protocol_ref: str) -> ProtocolDefinitionRecord:
        return await resolve_launchable_protocol(self._catalog, protocol_ref)

    def default_launch_fields(self) -> list[ProtocolRunInputFieldRecord]:
        return protocol_run_launch_form(ProtocolDefinitionRecord()).fields

    def launch_form_for_definition(self, definition: ProtocolDefinitionRecord, document=None) -> ProtocolRunLaunchFormRecord:
        return protocol_run_launch_form(definition, document)

    async def launch_from_inputs(
        self,
        definition: ProtocolDefinitionRecord,
        inputs: dict[str, object],
        *,
        entry_agent_id: str,
        root_conversation_id: str = "",
        origin_channel: str = "",
        repo_ref: str = "",
        branch_ref: str = "",
        idempotency_key: str = "",
        origin: str = "",
    ) -> ProtocolRunMutationRecord:
        request = build_protocol_run_request_from_inputs(
            definition,
            inputs,
            entry_agent_id=entry_agent_id,
            root_conversation_id=root_conversation_id,
            origin_channel=origin_channel,
            repo_ref=repo_ref,
            branch_ref=branch_ref,
        )
        return await self._invoker.invoke_protocol(
            request,
            idempotency_key=idempotency_key,
            origin=origin or origin_channel,
        )

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

    async def get_run_artifact_content(
        self,
        run_id: str,
        artifact_key: str,
        *,
        download: bool = False,
    ) -> bytes:
        return await self._artifact_access.get_run_artifact_content(
            run_id,
            artifact_key,
            download=download,
        )

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
