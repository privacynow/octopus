from __future__ import annotations

from octopus_sdk.protocols import (
    ProtocolStageDefinitionRecord,
    parse_protocol_stage_decision,
    validate_protocol_document,
)
from octopus_sdk.registry.models import AgentCard, RegistryJsonRecord
from octopus_registry.store_postgres import RegistryPostgresStore


def _agent_card(*, bot_key: str = "m1") -> AgentCard:
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


def _protocol_document() -> dict[str, object]:
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


def test_validate_protocol_document_accepts_minimal_protocol() -> None:
    result = validate_protocol_document(_protocol_document())
    assert result.ok is True
    assert result.normalized_document is not None
    assert result.normalized_document.first_stage_key == "planning"


def test_parse_protocol_stage_decision_requires_explicit_review_decision() -> None:
    stage = ProtocolStageDefinitionRecord(
        stage_key="review",
        participant_key="reviewer",
        stage_kind="review",
        transitions={"accept": "__complete__", "revise": "planning", "fail": "__failed__"},
    )
    decision = parse_protocol_stage_decision(
        stage=stage,
        full_text="PROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Looks good.",
    )
    assert decision.decision == "accept"
    assert decision.summary == "Looks good."


def test_registry_store_preserves_invalid_protocol_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    saved = store.save_protocol_draft(
        protocol_id="",
        slug="broken-protocol",
        display_name="Broken Protocol",
        description="Invalid draft",
        definition_json=RegistryJsonRecord.model_validate(
            {
                "metadata": {"slug": "broken-protocol"},
                "participants": [],
                "artifacts": [],
                "stages": [],
                "policies": {"single_active_writer": True, "max_review_rounds": 3},
            }
        ),
    )
    assert saved.ok is True
    assert saved.protocol is not None

    loaded = store.get_protocol(saved.protocol.protocol_id)
    assert loaded.ok is True
    assert loaded.validation is not None
    assert loaded.validation.ok is False
    assert loaded.draft_document is None
    assert loaded.draft_definition_json.as_dict()["metadata"]["slug"] == "broken-protocol"


def test_registry_store_protocol_run_advances_from_work_to_review(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll = store.enroll(_agent_card(bot_key="m1"))
    token = enroll.agent_token
    agent_id = enroll.agent_id

    saved = store.save_protocol_draft(
        protocol_id="",
        slug="mini-protocol",
        display_name="Mini Protocol",
        description="Test protocol",
        definition_json=RegistryJsonRecord.model_validate(_protocol_document()),
    )
    assert saved.ok is True
    protocol_id = saved.protocol.protocol_id

    published = store.publish_protocol(protocol_id)
    assert published.ok is True
    assert published.version is not None

    created = store.create_protocol_run(
        {
            "protocol_id": protocol_id,
            "entry_agent_id": agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        }
    )
    assert created.ok is True
    assert created.run is not None

    detail = store.get_protocol_run(created.run.protocol_run_id)
    assert detail.run.current_stage_key == "planning"
    assert detail.stage_executions
    first_stage = detail.stage_executions[0]
    assert first_stage.routed_task_id.startswith("protocol-stage:")

    store.update_routed_task_result(
        token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id)
    assert detail.run.current_stage_key == "review"
    review_stage = detail.stage_executions[0]
    assert review_stage.stage_key == "review"
    assert review_stage.status == "running"

    store.update_routed_task_result(
        token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-2",
            "summary": "Accepted.",
            "full_text": "Everything is complete.\nPROTOCOL_DECISION: accept\nPROTOCOL_SUMMARY: Accepted.",
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id)
    assert detail.run.status == "completed"
    assert detail.run.termination_summary == "Accepted."
