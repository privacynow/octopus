from __future__ import annotations

from datetime import datetime, timedelta, timezone

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolRunRecord,
    ProtocolStageDefinitionRecord,
    ProtocolStageExecutionRecord,
    canonical_protocol_document,
    evaluate_protocol_stage_timeout,
    parse_protocol_stage_decision,
    protocol_dispatch_decision,
    validate_protocol_document,
)
from octopus_sdk.registry.models import AgentCard, RegistryJsonRecord
from octopus_registry.postgres import get_connection
from octopus_registry.store_postgres import RegistryPostgresStore
from psycopg.types.json import Jsonb


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


def _operator_access() -> ProtocolAccessContextRecord:
    return ProtocolAccessContextRecord(
        actor_ref="operator-session",
        org_id="local",
        roles=["author", "publisher", "operator", "auditor", "admin"],
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


def _published_protocol(
    store: RegistryPostgresStore,
    *,
    slug: str = "mini-protocol",
    document: dict[str, object] | None = None,
):
    payload = document or _protocol_document()
    saved = store.save_protocol_draft(
        access=_operator_access(),
        protocol_id="",
        slug=slug,
        display_name=str(payload.get("metadata", {}).get("display_name", slug)),
        description=str(payload.get("metadata", {}).get("description", "")),
        definition_json=RegistryJsonRecord.model_validate(payload),
    )
    assert saved.ok is True
    assert saved.protocol is not None
    published = store.publish_protocol(saved.protocol.protocol_id, access=_operator_access())
    assert published.ok is True
    assert published.protocol is not None
    return published


def _running_protocol_run(
    store: RegistryPostgresStore,
    *,
    document: dict[str, object] | None = None,
):
    enroll = store.enroll(_agent_card(bot_key="m1"))
    published = _published_protocol(store, document=document)
    created = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=_operator_access(),
    )
    assert created.ok is True
    assert created.run is not None
    detail = store.get_protocol_run(created.run.protocol_run_id, access=_operator_access())
    assert detail.stage_executions
    return enroll, published, created, detail


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


def test_validate_protocol_document_migrates_legacy_schema_value() -> None:
    legacy = _protocol_document()
    legacy["schema_version"] = 0

    result = validate_protocol_document(legacy)

    assert result.ok is True
    assert result.normalized_document is not None
    assert result.normalized_document.schema_version == 1


def test_protocol_dispatch_decision_blocks_when_another_write_lease_is_active() -> None:
    document = canonical_protocol_document(_protocol_document())
    run = ProtocolRunRecord(
        protocol_run_id="run-1",
        current_stage_execution_id="current-stage",
        created_at="2026-04-16T00:00:00+00:00",
    )
    active_stage = ProtocolStageExecutionRecord(
        protocol_stage_execution_id="other-stage",
        protocol_run_id="run-1",
        stage_key="planning",
        participant_key="worker",
        status="running",
        lease_owner="other-stage",
        lease_expires_at="2099-01-01T00:00:00+00:00",
    )

    decision = protocol_dispatch_decision(
        document=document,
        run=run,
        stage=document.stage("planning"),
        stage_executions=[active_stage],
        now="2026-04-16T01:00:00+00:00",
        lease_owner="current-stage",
        lease_ttl_seconds=900,
    )

    assert decision.ok is False
    assert decision.error_code == "LEASE_HELD"


def test_evaluate_protocol_stage_timeout_marks_run_failed() -> None:
    document = canonical_protocol_document(_protocol_document())
    engine = evaluate_protocol_stage_timeout(
        document=document,
        run=ProtocolRunRecord(
            protocol_run_id="run-1",
            created_at="2026-04-16T00:00:00+00:00",
        ),
        stage_execution=ProtocolStageExecutionRecord(
            protocol_stage_execution_id="stage-1",
            protocol_run_id="run-1",
            stage_key="planning",
            participant_key="worker",
            status="running",
        ),
        now="2026-04-16T00:30:00+00:00",
    )

    assert engine.run_status == "failed"
    assert engine.stage_status == "failed"
    assert engine.failure_code == "stage_timeout"


def test_registry_store_preserves_invalid_protocol_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    saved = store.save_protocol_draft(
        access=_operator_access(),
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

    loaded = store.get_protocol(saved.protocol.protocol_id, access=_operator_access())
    assert loaded.ok is True
    assert loaded.validation is not None
    assert loaded.validation.ok is False
    assert loaded.draft_document is None
    assert loaded.draft_definition_json.as_dict()["metadata"]["slug"] == "broken-protocol"


def test_registry_store_protocol_run_advances_from_work_to_review(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = _running_protocol_run(store)
    token = enroll.agent_token
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
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "abc123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    detail = store.get_protocol_run(created.run.protocol_run_id, access=_operator_access())
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

    detail = store.get_protocol_run(created.run.protocol_run_id, access=_operator_access())
    assert detail.run.status == "completed"
    assert detail.run.termination_summary == "Accepted."


def test_registry_store_protocol_timeout_sweeps_without_task_result(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = _running_protocol_run(
        store,
        document={
            **_protocol_document(),
            "stages": [
                {
                    **_protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                _protocol_document()["stages"][1],
            ],
        },
    )
    stage = detail.stage_executions[0]
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET timeout_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    store.poll(enroll.agent_token, cursor=0, limit=5)

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=_operator_access())
    assert refreshed.run.status == "failed"
    assert refreshed.run.blocked_code == ""
    assert refreshed.run.termination_summary == ""
    assert refreshed.stage_executions[0].failure_code == "stage_timeout"


def test_registry_store_uses_database_for_builtin_protocol_template(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pd.current_version_id
                FROM agent_registry.protocol_definitions pd
                WHERE pd.slug = 'software-engineering'
                """,
            )
            row = cur.fetchone()
            assert row is not None
            cur.execute(
                """
                UPDATE agent_registry.protocol_definition_versions
                SET definition_json = %s
                WHERE protocol_definition_version_id = %s
                """,
                (
                    Jsonb(
                        {
                            **_protocol_document(),
                            "metadata": {
                                "slug": "software-engineering",
                                "display_name": "DB Seeded Protocol",
                                "description": "Database-backed template.",
                            },
                        }
                    ),
                    row[0],
                ),
            )
        conn.commit()

    template = store.get_protocol_template("software-engineering", access=_operator_access())
    assert template.display_name == "DB Seeded Protocol"


def test_registry_store_create_run_returns_not_visible_for_foreign_org(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = _published_protocol(store)
    enroll = store.enroll(_agent_card(bot_key="m1"))

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=ProtocolAccessContextRecord(
            actor_ref="foreign-operator",
            org_id="foreign-org",
            roles=["author", "publisher", "operator", "auditor"],
        ),
    )

    assert result.ok is False
    assert result.status == "not_visible"


def test_registry_store_archive_protocol_marks_definition_archived(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = _published_protocol(store)

    archived = store.archive_protocol(published.protocol.protocol_id, access=_operator_access())

    assert archived.ok is True
    assert archived.protocol is not None
    assert archived.protocol.lifecycle_state == "archived"
