"""Protocol invocation and observation ports shared across bot surfaces."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .models import (
    ProtocolArtifactRecord,
    ProtocolIssueRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
    ProtocolRunRecord,
    ProtocolTransitionRecord,
)
from octopus_sdk.registry.models import TransportActorKey


@runtime_checkable
class ProtocolInvocationPort(Protocol):
    async def invoke_protocol(
        self,
        payload: ProtocolRunCreateRecord | dict[str, object],
        *,
        idempotency_key: str = "",
        origin: TransportActorKey | str = "",
    ) -> ProtocolRunMutationRecord: ...


@runtime_checkable
class ProtocolObservationPort(Protocol):
    async def list_runs(
        self,
        *,
        cursor: int = 0,
        limit: int = 25,
        status: str = "",
        protocol_id: str = "",
        entry_agent_id: str = "",
        origin_channel: str = "",
    ) -> list[ProtocolRunRecord]: ...

    async def get_run(self, run_id: str) -> ProtocolRunDetailRecord: ...

    async def list_run_issues(
        self,
        *,
        cursor: int = 0,
        limit: int = 25,
        issue_kind: str = "",
        protocol_run_id: str = "",
        protocol_id: str = "",
    ) -> list[ProtocolIssueRecord]: ...

    async def list_run_artifacts(self, run_id: str) -> list[ProtocolArtifactRecord]: ...

    async def list_run_timeline(self, run_id: str) -> list[ProtocolTransitionRecord]: ...

    async def export_run(self, run_id: str) -> ProtocolRunExportRecord: ...

    async def stream_run(self, run_id: str) -> AsyncIterator[object]: ...
