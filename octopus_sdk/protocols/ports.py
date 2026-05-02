"""Protocol invocation and observation ports shared across bot surfaces."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .auto_design import (
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignSessionRecord,
)
from .models import (
    ProtocolArtifactRecord,
    ProtocolAuthoringOptionsRecord,
    ProtocolDefinitionDiffRecord,
    ProtocolDefinitionDocumentRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolDraftCreateRecord,
    ProtocolIssueRecord,
    ProtocolMutationRecord,
    ProtocolRunCreateRecord,
    ProtocolRunDetailRecord,
    ProtocolRunExportRecord,
    ProtocolRunMutationRecord,
    ProtocolRunRecord,
    ProtocolTemplateCreateRecord,
    ProtocolTemplateSummaryRecord,
    ProtocolTextDocumentRecord,
    ProtocolTransitionRecord,
)
from octopus_sdk.registry.models import TransportActorKey


@runtime_checkable
class ProtocolCatalogPort(Protocol):
    async def list_protocols(
        self,
        *,
        cursor: int = 0,
        limit: int = 50,
        lifecycle_state: str = "",
        slug: str = "",
        created_after: str = "",
    ) -> list[ProtocolDefinitionRecord]: ...


@runtime_checkable
class ProtocolAuthoringPort(Protocol):
    async def get_protocol_authoring_options(self) -> ProtocolAuthoringOptionsRecord: ...

    async def list_protocol_templates(self) -> list[ProtocolTemplateSummaryRecord]: ...

    async def get_protocol_template(self, slug: str) -> ProtocolDefinitionDocumentRecord: ...

    async def get_protocol(self, protocol_id: str) -> ProtocolMutationRecord: ...

    async def get_protocol_version(self, protocol_id: str, version_id: str) -> ProtocolDefinitionVersionRecord: ...

    async def save_protocol(
        self,
        *,
        protocol_id: str = "",
        slug: str = "",
        display_name: str = "",
        description: str = "",
        definition_json: dict[str, object] | None = None,
    ) -> ProtocolMutationRecord: ...

    async def create_protocol_draft(self, payload: ProtocolDraftCreateRecord) -> ProtocolMutationRecord: ...

    async def create_protocol_template(self, payload: ProtocolTemplateCreateRecord) -> ProtocolMutationRecord: ...

    async def delete_protocol(self, protocol_id: str) -> ProtocolMutationRecord: ...

    async def validate_protocol(self, protocol_id: str) -> ProtocolMutationRecord: ...

    async def publish_protocol(self, protocol_id: str) -> ProtocolMutationRecord: ...

    async def archive_protocol(self, protocol_id: str) -> ProtocolMutationRecord: ...

    async def parse_protocol_document_text(
        self,
        *,
        definition_text: str,
        format: str = "json",
        validation_mode: str = "strict",
    ) -> ProtocolTextDocumentRecord: ...

    async def export_protocol_draft(self, protocol_id: str, format: str = "json") -> ProtocolTextDocumentRecord: ...

    async def diff_protocol_draft(self, protocol_id: str, format: str = "json") -> ProtocolDefinitionDiffRecord: ...


@runtime_checkable
class ProtocolAutoDesignSessionPort(Protocol):
    async def create_protocol_auto_design_session(
        self,
        payload: ProtocolAutoDesignRequestRecord | dict[str, object],
    ) -> ProtocolAutoDesignSessionRecord: ...

    async def get_protocol_auto_design_session(self, session_id: str) -> ProtocolAutoDesignSessionRecord: ...

    async def revise_protocol_auto_design_session(
        self,
        session_id: str,
        payload: ProtocolAutoDesignRequestRecord | dict[str, object],
    ) -> ProtocolAutoDesignSessionRecord: ...

    async def apply_protocol_auto_design_session(self, session_id: str) -> ProtocolAutoDesignSessionRecord: ...

    async def publish_protocol_auto_design_session(self, session_id: str) -> ProtocolAutoDesignSessionRecord: ...

    async def run_protocol_auto_design_session(
        self,
        session_id: str,
        payload: dict[str, object] | None = None,
    ) -> ProtocolAutoDesignSessionRecord: ...


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
        root_conversation_id: str = "",
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


@runtime_checkable
class ProtocolArtifactAccessPort(Protocol):
    async def get_run_artifact_content(
        self,
        run_id: str,
        artifact_key: str,
        *,
        download: bool = False,
    ) -> bytes: ...


@runtime_checkable
class ProtocolRunControlPort(Protocol):
    async def act_on_protocol_run(
        self,
        run_id: str,
        *,
        action: str,
        reason: str = "",
        idempotency_key: str = "",
        expected_version: int | None = None,
    ) -> ProtocolRunMutationRecord: ...
