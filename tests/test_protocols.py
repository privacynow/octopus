from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from octopus_sdk.protocols import (
    ProtocolAccessContextRecord,
    ProtocolStageDefinitionRecord,
    parse_protocol_stage_decision,
    protocol_document_to_text,
    validate_protocol_document,
)
from octopus_sdk.registry.models import RegistryJsonRecord
from octopus_registry.postgres import get_connection
from octopus_registry.store_postgres import RegistryPostgresStore
from psycopg.types.json import Jsonb
from tests.support.protocol_support import (
    agent_card,
    operator_access,
    protocol_document,
    published_protocol,
    running_protocol_run,
)


def test_validate_protocol_document_accepts_minimal_protocol() -> None:
    result = validate_protocol_document(protocol_document())
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
    legacy = protocol_document()
    legacy["schema_version"] = 0

    result = validate_protocol_document(legacy)

    assert result.ok is True
    assert result.normalized_document is not None
    assert result.normalized_document.schema_version == 1


def test_registry_store_preserves_invalid_protocol_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    saved = store.save_protocol_draft(
        access=operator_access(),
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

    loaded = store.get_protocol(saved.protocol.protocol_id, access=operator_access())
    assert loaded.ok is True
    assert loaded.validation is not None
    assert loaded.validation.ok is False
    assert loaded.draft_document is None
    assert loaded.draft_definition_json.as_dict()["metadata"]["slug"] == "broken-protocol"


def test_registry_store_protocol_run_advances_from_work_to_review(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
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

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
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

    detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert detail.run.status == "completed"
    assert detail.run.termination_summary == "Accepted."


def test_registry_store_protocol_timeout_sweeps_without_task_result(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
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

    maintenance = store.run_protocol_maintenance()

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert maintenance.swept_count == 1
    assert created.run.protocol_run_id in maintenance.affected_run_ids
    assert refreshed.run.status == "failed"
    assert refreshed.run.blocked_code == ""
    assert refreshed.run.termination_summary == ""
    assert refreshed.stage_executions[0].failure_code == "stage_timeout"


def test_registry_store_protocol_issues_report_timeout_and_blocked_runs(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(
        store,
        document={
            **protocol_document(),
            "stages": [
                {
                    **protocol_document()["stages"][0],
                    "timeout_seconds": 1,
                },
                protocol_document()["stages"][1],
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

    timeout_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="expired_timeout",
    )
    assert any(item.protocol_run_id == created.run.protocol_run_id for item in timeout_issues)

    maintenance = store.run_protocol_maintenance()

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert maintenance.swept_count == 1
    assert refreshed.run.status == "failed"

    blocked_enroll = store.enroll(agent_card(bot_key="m2"))
    blocked_published = published_protocol(
        store,
        slug="mini-protocol-blocked",
        document={
            **protocol_document(),
            "metadata": {
                **protocol_document()["metadata"],
                "slug": "mini-protocol-blocked",
                "display_name": "Mini Protocol Blocked",
            },
        },
    )
    blocked_created = store.create_protocol_run(
        {
            "protocol_id": blocked_published.protocol.protocol_id,
            "entry_agent_id": blocked_enroll.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the blocked feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    blocked_detail = store.get_protocol_run(blocked_created.run.protocol_run_id, access=operator_access())
    blocked_stage = blocked_detail.stage_executions[0]
    store.update_routed_task_result(
        blocked_enroll.agent_token,
        blocked_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "blocked-1",
            "summary": "Missing artifact.",
            "full_text": "Updated plan.\nPROTOCOL_SUMMARY: Missing artifact.",
            "artifacts": [],
        },
    )
    blocked_issues = store.list_protocol_issues(
        access=operator_access(),
        issue_kind="blocked_run",
    )
    assert any(item.protocol_run_id == blocked_created.run.protocol_run_id for item in blocked_issues)
    filtered_issues = store.list_protocol_issues(
        access=operator_access(),
        protocol_run_id=blocked_created.run.protocol_run_id,
    )
    assert filtered_issues
    assert all(item.protocol_run_id == blocked_created.run.protocol_run_id for item in filtered_issues)


def test_registry_store_uses_database_for_builtin_protocol_template(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
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
                            **protocol_document(),
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

    template = store.get_protocol_template("software-engineering", access=operator_access())
    assert template.display_name == "DB Seeded Protocol"


def test_registry_store_create_run_returns_not_visible_for_foreign_org(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    enroll = store.enroll(agent_card(bot_key="m1"))

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


def test_registry_store_get_run_raises_permission_error_for_foreign_org(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, _detail = running_protocol_run(store)

    with pytest.raises(PermissionError):
        store.get_protocol_run(
            created.run.protocol_run_id,
            access=ProtocolAccessContextRecord(
                actor_ref="foreign-operator",
                org_id="foreign-org",
                roles=["operator"],
            ),
        )


def test_registry_store_archive_protocol_marks_definition_archived(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    archived = store.archive_protocol(published.protocol.protocol_id, access=operator_access())

    assert archived.ok is True
    assert archived.protocol is not None
    assert archived.protocol.lifecycle_state == "archived"


def test_registry_store_protocol_text_routes_round_trip_json_yaml_and_diff(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    protocol_id = published.protocol.protocol_id

    parsed = store.parse_protocol_document_text(
        access=operator_access(),
        definition_text=protocol_document_to_text(protocol_document(), format="yaml"),
        format="yaml",
    )
    assert parsed.format == "yaml"
    assert parsed.validation is not None
    assert parsed.validation.ok is True
    assert parsed.document is not None
    assert parsed.text.strip().startswith("schema_version:")

    exported = store.export_protocol_draft(
        protocol_id,
        access=operator_access(),
        format="yaml",
    )
    assert exported.format == "yaml"
    assert "display_name: Mini Protocol" in exported.text

    saved = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="mini-protocol",
        display_name="Mini Protocol",
        description="Updated draft description",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **protocol_document(),
                "metadata": {
                    **protocol_document()["metadata"],
                    "description": "Updated draft description",
                },
            }
        ),
    )
    assert saved.ok is True

    diff = store.diff_protocol_draft(
        protocol_id,
        access=operator_access(),
        format="json",
    )
    assert diff.protocol_id == protocol_id
    assert diff.protocol_definition_version_id == published.version.protocol_definition_version_id
    assert "--- draft" in diff.diff
    assert "+++ published" in diff.diff
    assert "Updated draft description" in diff.diff


def test_registry_store_list_protocol_runs_filters_by_entry_agent_and_origin_channel(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    m1 = store.enroll(agent_card(bot_key="m1"))
    m2 = store.enroll(agent_card(bot_key="m2"))
    published = published_protocol(store)

    registry_run = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": m1.agent_id,
            "origin_channel": "registry",
            "workspace_ref": "workspace-registry",
            "problem_statement": "Registry initiated run.",
            "constraints_json": {},
        },
        access=operator_access(),
    )
    telegram_run = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": m2.agent_id,
            "origin_channel": "telegram",
            "workspace_ref": "workspace-telegram",
            "problem_statement": "Telegram initiated run.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert registry_run.ok is True
    assert telegram_run.ok is True

    filtered = store.list_protocol_runs(
        access=operator_access(),
        entry_agent_id=m2.agent_id,
        origin_channel="telegram",
        limit=10,
    )
    assert len(filtered) == 1
    assert filtered[0].protocol_run_id == telegram_run.run.protocol_run_id
    assert filtered[0].entry_agent_id == m2.agent_id
    assert filtered[0].origin_channel == "telegram"
