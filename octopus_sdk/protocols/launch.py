"""Shared protocol launch helpers for conversation-facing surfaces."""

from __future__ import annotations

from pydantic import Field

from octopus_sdk.registry.models import RegistryJsonRecord, RegistryRecordModel

from .models import ProtocolDefinitionRecord, ProtocolRunCreateRecord, ProtocolRunMutationRecord
from .ports import ProtocolCatalogPort, ProtocolInvocationPort


class ProtocolConversationLaunchRequestRecord(RegistryRecordModel):
    protocol_ref: str = ""
    entry_agent_id: str = ""
    root_conversation_id: str = ""
    origin_channel: str = ""
    workspace_ref: str = ""
    repo_ref: str = ""
    branch_ref: str = ""
    problem_statement: str = ""
    constraints_json: RegistryJsonRecord = Field(default_factory=RegistryJsonRecord)


class ProtocolConversationLaunchResultRecord(RegistryRecordModel):
    definition: ProtocolDefinitionRecord
    request: ProtocolRunCreateRecord
    mutation: ProtocolRunMutationRecord


def filter_launchable_protocols(
    protocols: list[ProtocolDefinitionRecord] | tuple[ProtocolDefinitionRecord, ...] | None,
) -> list[ProtocolDefinitionRecord]:
    visible = [
        item
        for item in (protocols or [])
        if str(item.lifecycle_state or "") == "published"
        and str(item.current_version_id or "")
    ]
    return sorted(
        visible,
        key=lambda item: (
            str(item.display_name or item.slug or item.protocol_id or "").strip().lower(),
            str(item.slug or item.protocol_id or "").strip().lower(),
        ),
    )


async def list_launchable_protocols(
    catalog: ProtocolCatalogPort,
    *,
    cursor: int = 0,
    limit: int = 100,
) -> list[ProtocolDefinitionRecord]:
    rows = await catalog.list_protocols(
        cursor=cursor,
        limit=limit,
        lifecycle_state="published",
    )
    return filter_launchable_protocols(rows)


async def resolve_launchable_protocol(
    catalog: ProtocolCatalogPort,
    protocol_ref: str,
) -> ProtocolDefinitionRecord:
    target = str(protocol_ref or "").strip()
    if not target:
        raise ValueError("protocol_ref is required")
    candidates = await list_launchable_protocols(catalog)
    match = next(
        (
            item
            for item in candidates
            if target in {
                str(item.protocol_id or "").strip(),
                str(item.slug or "").strip(),
            }
        ),
        None,
    )
    if match is None:
        raise KeyError(target)
    return match


def build_conversation_protocol_run_request(
    definition: ProtocolDefinitionRecord,
    payload: ProtocolConversationLaunchRequestRecord | dict[str, object],
) -> ProtocolRunCreateRecord:
    request = ProtocolConversationLaunchRequestRecord.model_validate(payload)
    if not str(request.entry_agent_id or "").strip():
        raise ValueError("entry_agent_id is required")
    if not str(request.problem_statement or "").strip():
        raise ValueError("problem_statement is required")
    return ProtocolRunCreateRecord(
        protocol_id=str(definition.protocol_id or "").strip(),
        entry_agent_id=str(request.entry_agent_id or "").strip(),
        root_conversation_id=str(request.root_conversation_id or "").strip(),
        origin_channel=str(request.origin_channel or "").strip(),
        workspace_ref=str(request.workspace_ref or "").strip(),
        repo_ref=str(request.repo_ref or "").strip(),
        branch_ref=str(request.branch_ref or "").strip(),
        problem_statement=str(request.problem_statement or "").strip(),
        constraints_json=RegistryJsonRecord.model_validate(request.constraints_json or {}),
    )


async def launch_protocol_from_conversation(
    catalog: ProtocolCatalogPort,
    invoker: ProtocolInvocationPort,
    payload: ProtocolConversationLaunchRequestRecord | dict[str, object],
    *,
    idempotency_key: str = "",
    origin: str = "",
) -> ProtocolConversationLaunchResultRecord:
    request_payload = ProtocolConversationLaunchRequestRecord.model_validate(payload)
    definition = await resolve_launchable_protocol(catalog, request_payload.protocol_ref)
    run_request = build_conversation_protocol_run_request(definition, request_payload)
    mutation = await invoker.invoke_protocol(
        run_request,
        idempotency_key=idempotency_key,
        origin=origin or request_payload.origin_channel,
    )
    return ProtocolConversationLaunchResultRecord(
        definition=definition,
        request=run_request,
        mutation=mutation,
    )
