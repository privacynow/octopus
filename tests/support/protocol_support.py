from __future__ import annotations

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolDefinitionRecord,
    ProtocolMutationRecord,
    ProtocolRunMutationRecord,
)
from octopus_sdk.registry.models import AgentCard, RegistryJsonRecord
from octopus_registry.store_postgres import RegistryPostgresStore


def agent_card(*, bot_key: str = "m1") -> AgentCard:
    return AgentCard(
        bot_key=bot_key,
        display_name=bot_key.upper(),
        slug=bot_key,
        role="assistant",
        registry_scope="full",
        routing_skills=["planning"],
        tags=[],
        description="",
        provider="codex",
        mode="registry",
        connectivity_state="connected",
        current_capacity=0,
        max_capacity=1,
        channel_capabilities=["telegram"],
        management_capabilities=["conversation_settings"],
        version="test",
    )


def operator_access() -> ProtocolAccessContextRecord:
    return ProtocolAccessContextRecord(
        actor_ref="operator-session",
        org_id="local",
        roles=["author", "publisher", "operator", "auditor", "admin"],
    )


def protocol_document() -> dict[str, object]:
    return {
        "metadata": {
            "slug": "mini-protocol",
            "display_name": "Mini Protocol",
            "description": "Minimal protocol for test coverage.",
        },
        "participants": [
            {"participant_key": "worker", "display_name": "Worker"},
            {"participant_key": "reviewer", "display_name": "Reviewer"},
        ],
        "artifacts": [
            {
                "artifact_key": "plan",
                "kind": "workspace_file",
                "path": "protocol/plan.md",
            }
        ],
        "stages": [
            {
                "stage_key": "planning",
                "participant_key": "worker",
                "stage_kind": "work",
                "write_capable": True,
                "inputs": [],
                "outputs": ["plan"],
                "transitions": {"completed": "review"},
                "instructions": "Write protocol/plan.md.",
            },
            {
                "stage_key": "review",
                "participant_key": "reviewer",
                "stage_kind": "review",
                "inputs": ["plan"],
                "outputs": [],
                "transitions": {
                    "accept": "__complete__",
                    "revise": "planning",
                    "fail": "__failed__",
                },
                "instructions": "Review the plan.",
            },
        ],
        "policies": {
            "single_active_writer": True,
            "max_review_rounds": 3,
        },
    }


def published_protocol(
    store: RegistryPostgresStore,
    *,
    slug: str = "mini-protocol",
    document: dict[str, object] | None = None,
) -> ProtocolMutationRecord:
    payload = document or protocol_document()
    saved = store.save_protocol_draft(
        access=operator_access(),
        protocol_id="",
        slug=slug,
        display_name=str(payload.get("metadata", {}).get("display_name", slug)),
        description=str(payload.get("metadata", {}).get("description", "")),
        definition_json=RegistryJsonRecord.model_validate(payload),
    )
    assert saved.ok is True
    assert saved.protocol is not None
    published = store.publish_protocol(saved.protocol.protocol_id, access=operator_access())
    assert published.ok is True
    assert published.protocol is not None
    return published


def running_protocol_run(
    store: RegistryPostgresStore,
    *,
    document: dict[str, object] | None = None,
) -> tuple[object, ProtocolMutationRecord, ProtocolRunMutationRecord, object]:
    enroll = store.enroll(agent_card(bot_key="m1"))
    published = published_protocol(store, document=document)
    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    assert created.ok is True
    assert created.run is not None
    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.stage_executions
    return enroll, published, created, detail
