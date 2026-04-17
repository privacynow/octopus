from __future__ import annotations

import json
import random
import string
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from octopus_sdk.protocols import (
    ProtocolArtifactObservationRecord,
    ProtocolAccessContextRecord,
    ProtocolDraftCreateRecord,
    ProtocolStageDefinitionRecord,
    canonical_protocol_document,
    parse_protocol_stage_decision,
    protocol_document_to_text,
    protocol_review_edge_key,
    validate_protocol_document,
)
from octopus_sdk.registry.models import RegistryJsonRecord, RoutedTaskUpdate
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


def _generated_linear_protocol(seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    stage_count = rng.randint(2, 6)
    artifacts: list[dict[str, object]] = []
    stages: list[dict[str, object]] = []
    previous_artifact_key = ""
    for index in range(stage_count):
        artifact_key = f"artifact-{index}"
        stage_key = f"stage-{index}"
        artifacts.append(
            {
                "artifact_key": artifact_key,
                "kind": "workspace_file",
                "path": f"protocol/{artifact_key}.md",
            }
        )
        transitions: dict[str, str] = {
            "completed": "__complete__" if index == stage_count - 1 else f"stage-{index + 1}",
            "fail": "__failed__",
        }
        stages.append(
            {
                "stage_key": stage_key,
                "participant_key": "worker",
                "stage_kind": "work",
                "write_capable": True,
                "strict_completion": bool(rng.getrandbits(1)),
                "timeout_seconds": rng.choice((0, 30, 120)),
                "inputs": [previous_artifact_key] if previous_artifact_key else [],
                "outputs": [artifact_key],
                "transitions": transitions,
                "instructions": f"Write {artifact_key}.",
            }
        )
        previous_artifact_key = artifact_key
    return {
        "schema_version": 1,
        "metadata": {
            "slug": f"generated-{seed}",
            "display_name": f"Generated {seed}",
            "description": "Generated protocol for validator coverage.",
        },
        "participants": [{"participant_key": "worker", "display_name": "Worker"}],
        "artifacts": artifacts,
        "stages": stages,
        "policies": {
            "single_active_writer": True,
            "max_review_rounds": rng.randint(1, 5),
        },
    }


def _random_jsonish(rng: random.Random, *, depth: int) -> object:
    if depth <= 0:
        return rng.choice(
            (
                None,
                True,
                False,
                rng.randint(-10, 10),
                "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(0, 8))),
            )
        )
    kind = rng.choice(("dict", "list", "scalar"))
    if kind == "dict":
        return {
            "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(1, 6))): _random_jsonish(
                rng,
                depth=depth - 1,
            )
            for _ in range(rng.randint(0, 4))
        }
    if kind == "list":
        return [_random_jsonish(rng, depth=depth - 1) for _ in range(rng.randint(0, 4))]
    return _random_jsonish(rng, depth=0)


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


def test_validate_protocol_document_rejects_workspace_path_traversal() -> None:
    invalid = protocol_document()
    invalid["artifacts"] = [
        {
            "artifact_key": "plan",
            "kind": "workspace_file",
            "path": "../secret/plan.md",
        }
    ]

    result = validate_protocol_document(invalid)

    assert result.ok is False
    assert result.errors
    assert "escape the workspace root" in result.errors[0]


def test_validate_protocol_document_accepts_generated_reachable_linear_graphs() -> None:
    for seed in range(25):
        result = validate_protocol_document(_generated_linear_protocol(seed))
        assert result.ok is True, f"generated protocol failed validation for seed={seed}: {result.errors}"


def test_validate_protocol_document_fuzz_does_not_raise_uncaught_exceptions() -> None:
    for seed in range(100):
        payload = _random_jsonish(random.Random(seed), depth=3)
        if not isinstance(payload, dict):
            payload = {"payload": payload}
        result = validate_protocol_document(payload)
        assert isinstance(result.ok, bool), f"validator returned invalid result for seed={seed}"


def test_protocol_artifact_observation_rejects_absolute_or_traversing_paths() -> None:
    with pytest.raises(ValueError, match="relative to the workspace root"):
        ProtocolArtifactObservationRecord.model_validate(
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "/tmp/plan.md",
            }
        )

    with pytest.raises(ValueError, match="escape the workspace root"):
        ProtocolArtifactObservationRecord.model_validate(
            {
                "artifact_key": "plan",
                "artifact_kind": "workspace_file",
                "path": "../secret/plan.md",
            }
        )


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
    assert detail.run.current_stage_execution_id == review_stage.protocol_stage_execution_id
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


def test_registry_store_duplicate_routed_task_result_is_idempotent(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    token = enroll.agent_token
    stage = detail.stage_executions[0]
    payload = {
        "status": "completed",
        "transition_id": "done-dup",
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
    }

    store.update_routed_task_result(token, stage.routed_task_id, payload)
    first = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    first_stage_ids = [item.protocol_stage_execution_id for item in first.stage_executions]
    first_transition_ids = [item.protocol_transition_id for item in first.transitions]

    store.update_routed_task_result(token, stage.routed_task_id, payload)
    second = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())

    assert second.run.current_stage_execution_id == first.run.current_stage_execution_id
    assert [item.protocol_stage_execution_id for item in second.stage_executions] == first_stage_ids
    assert [item.protocol_transition_id for item in second.transitions] == first_transition_ids


def test_registry_store_running_status_renews_protocol_write_lease(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    stage = detail.stage_executions[0]
    expired = "2000-01-01T00:00:00+00:00"
    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_stage_executions
                SET lease_expires_at = %s
                WHERE protocol_stage_execution_id = %s
                """,
                (expired, stage.protocol_stage_execution_id),
            )
        conn.commit()

    store.update_routed_task_status(
        enroll.agent_token,
        stage.routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=stage.routed_task_id,
            status="leased",
            transition_id="lease-renew-lease",
            summary="Leased.",
            timeline_events=[],
        ),
    )
    store.update_routed_task_status(
        enroll.agent_token,
        stage.routed_task_id,
        RoutedTaskUpdate(
            routed_task_id=stage.routed_task_id,
            status="running",
            transition_id="lease-renew-1",
            summary="Still working.",
            timeline_events=[],
        ),
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    renewed = next(
        item for item in refreshed.stage_executions if item.protocol_stage_execution_id == stage.protocol_stage_execution_id
    )
    assert renewed.status == "running"
    assert renewed.lease_expires_at > expired


def test_registry_store_list_protocols_accepts_default_include_drafts(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    listed = store.list_protocols(access=operator_access(), limit=10)

    assert any(item.protocol_id == published.protocol.protocol_id for item in listed)


def test_registry_store_exposes_review_loop_count_and_cap(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    planning_stage = detail.stage_executions[0]

    store.update_routed_task_result(
        enroll.agent_token,
        planning_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "plan-complete",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "plan123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    review_detail = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    review_stage = next(item for item in review_detail.stage_executions if item.stage_key == "review")
    store.update_routed_task_result(
        enroll.agent_token,
        review_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "review-revise",
            "summary": "Needs changes.",
            "full_text": "Needs more work.\nPROTOCOL_DECISION: revise\nPROTOCOL_SUMMARY: Needs changes.",
        },
    )

    revised = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    listed = store.list_protocol_runs(access=operator_access())
    run_summary = next(item for item in listed if item.protocol_run_id == created.run.protocol_run_id)

    assert revised.run.current_review_rounds == 1
    assert revised.run.max_review_rounds == 3
    assert revised.run.current_review_edge_key == protocol_review_edge_key("review", "planning")
    assert run_summary.current_review_rounds == 1
    assert run_summary.max_review_rounds == 3


def test_registry_store_late_result_after_timeout_does_not_reopen_run(postgres_registry_truncated: str) -> None:
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
    timed_out = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    transition_ids = [item.protocol_transition_id for item in timed_out.transitions]
    stage_ids = [item.protocol_stage_execution_id for item in timed_out.stage_executions]

    store.update_routed_task_result(
        enroll.agent_token,
        stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "late-1",
            "summary": "Late completion.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Late completion.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 128,
                    "content_hash": "late123",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert maintenance.swept_count == 1
    assert refreshed.run.status == "failed"
    assert [item.protocol_transition_id for item in refreshed.transitions] == transition_ids
    assert [item.protocol_stage_execution_id for item in refreshed.stage_executions] == stage_ids


def test_registry_store_protocol_timeline_scales_for_large_transition_history(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, detail = running_protocol_run(store)
    run_id = created.run.protocol_run_id
    stage_id = detail.stage_executions[0].protocol_stage_execution_id
    inserted = 400
    now = datetime.now(timezone.utc).isoformat()

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            for index in range(inserted):
                cur.execute(
                    """
                    INSERT INTO agent_registry.protocol_transitions (
                        protocol_transition_id, protocol_run_id, from_stage_execution_id,
                        to_stage_execution_id, transition_kind, decision, reason, error_code,
                        metadata_json, actor_type, actor_ref, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_id,
                        stage_id,
                        stage_id,
                        "progress",
                        "",
                        f"perf-{index}",
                        "",
                        Jsonb({}),
                        "protocol_engine",
                        stage_id,
                        now,
                    ),
                )
        conn.commit()

    store.get_protocol_run_timeline(run_id, access=operator_access())
    started = time.perf_counter()
    timeline = store.get_protocol_run_timeline(run_id, access=operator_access())
    elapsed = time.perf_counter() - started

    assert len(timeline) >= inserted
    # Generous local threshold to catch regressions in the hot-path timeline query without flaking on CI noise.
    assert elapsed < 2.0


def test_registry_store_loads_legacy_published_protocol_versions_via_in_memory_migration(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)
    assert published.version is not None

    legacy_payload = protocol_document()
    legacy_payload["schema_version"] = 0

    with get_connection(postgres_registry_truncated) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_registry.protocol_definition_versions
                SET definition_json = %s
                WHERE protocol_definition_version_id = %s
                """,
                (
                    Jsonb(legacy_payload),
                    published.version.protocol_definition_version_id,
                ),
            )
        conn.commit()

    version = store.get_protocol_version(
        published.protocol.protocol_id,
        published.version.protocol_definition_version_id,
        access=operator_access(),
    )
    migrated = canonical_protocol_document(version.definition_json)
    assert migrated.schema_version == 1
    assert migrated.stage("planning").strict_completion is False
    assert migrated.stage("planning").timeout_seconds == 0

    enroll = store.enroll(agent_card(bot_key="m1"))
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


def test_registry_store_sources_builtin_protocol_templates_from_code_not_authored_rows(postgres_registry_truncated: str) -> None:
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
            assert row is None

    template = store.get_protocol_template("software-engineering", access=operator_access())
    assert template.slug == "software-engineering"
    assert template.display_name


def test_registry_store_authoring_manifest_lists_templates_and_sections(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    manifest = store.get_protocol_authoring_manifest(access=operator_access())

    assert manifest.templates
    assert any(item.slug == "software-engineering" for item in manifest.templates)
    assert "design" in manifest.sections
    assert "advanced" in manifest.sections
    assert "review" in manifest.stage_kind_options


def test_registry_store_create_blank_protocol_draft_creates_persisted_invalid_starter(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)

    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    assert created.ok is True
    assert created.protocol is not None
    assert created.protocol.lifecycle_state == "draft"
    assert created.protocol.slug
    assert created.draft_definition_json["metadata"]["slug"] == ""
    assert created.draft_definition_json["metadata"]["display_name"] == ""
    assert created.draft_definition_json["stages"] == []
    assert created.validation is not None
    assert created.validation.mode == "draft"
    assert created.validation.ok is False
    assert "Add at least one stage before review or publish." in created.validation.errors


def test_registry_store_create_template_protocol_draft_clones_builtin_template(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "template", "template_slug": "software-engineering"}),
        access=operator_access(),
    )

    assert created.ok is True
    assert created.protocol is not None
    assert created.protocol.slug != "software-engineering"
    assert created.draft_definition_json["metadata"]["display_name"].endswith("Draft")
    assert created.draft_definition_json["stages"]
    assert created.validation is not None
    assert created.validation.ok is True


def test_registry_store_create_protocol_draft_clones_existing_protocol(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store, slug="clone-source")

    cloned = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate(
            {"source_kind": "protocol", "source_protocol_id": published.protocol.protocol_id}
        ),
        access=operator_access(),
    )

    assert cloned.ok is True
    assert cloned.protocol is not None
    assert cloned.protocol.protocol_id != published.protocol.protocol_id
    assert cloned.protocol.slug != published.protocol.slug
    assert cloned.draft_definition_json["metadata"]["display_name"].endswith("Draft")
    assert cloned.draft_definition_json["stages"]
    assert cloned.validation is not None
    assert cloned.validation.ok is True


def test_registry_store_delete_protocol_discards_unpublished_draft(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    deleted = store.delete_protocol(created.protocol.protocol_id, access=operator_access())

    assert deleted.ok is True
    assert deleted.status == "deleted"
    listed = store.list_protocols(access=operator_access(), limit=50)
    assert all(item.protocol_id != created.protocol.protocol_id for item in listed)


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


def test_registry_store_create_run_requires_entry_agent_id(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": "",
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert result.ok is False
    assert result.status == "invalid"
    assert "entry_agent_id is required" in result.message


def test_registry_store_create_run_rejects_unknown_entry_agent_id(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    published = published_protocol(store)

    result = store.create_protocol_run(
        {
            "protocol_id": published.protocol.protocol_id,
            "entry_agent_id": "agent-missing",
            "origin_channel": "registry",
            "workspace_ref": "default",
            "problem_statement": "Build the feature.",
            "constraints_json": {},
        },
        access=operator_access(),
    )

    assert result.ok is False
    assert result.status == "invalid"
    assert "entry_agent_id does not reference a known managed bot" in result.message


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


def test_registry_store_protocol_export_requires_operator_or_auditor_role(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    _enroll, _published, created, _detail = running_protocol_run(store)

    with pytest.raises(PermissionError, match="operator or auditor access"):
        store.export_protocol_run(
            created.run.protocol_run_id,
            access=ProtocolAccessContextRecord(
                actor_ref="author-only",
                org_id="local",
                roles=["author"],
            ),
        )

    exported = store.export_protocol_run(
        created.run.protocol_run_id,
        access=ProtocolAccessContextRecord(
            actor_ref="auditor-session",
            org_id="local",
            roles=["auditor"],
        ),
    )
    assert exported.run.protocol_run_id == created.run.protocol_run_id
    assert exported.definition_document.slug == "mini-protocol"
    assert [artifact.artifact_key for artifact in exported.artifacts] == ["plan"]
    assert exported.artifacts[0].verification_state == "declared"


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


def test_registry_store_parse_draft_mode_accepts_incomplete_protocols(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)

    parsed = store.parse_protocol_document_text(
        access=operator_access(),
        definition_text=json.dumps(
            {
                "schema_version": 1,
                "metadata": {"slug": "draft-protocol", "display_name": "Draft Protocol"},
                "participants": [],
                "artifacts": [],
                "stages": [],
                "policies": {"single_active_writer": True, "max_review_rounds": 5},
            }
        ),
        format="json",
        validation_mode="draft",
    )

    assert parsed.format == "json"
    assert parsed.document is not None
    assert parsed.validation is not None
    assert parsed.validation.mode == "draft"
    assert parsed.validation.ok is False
    assert parsed.validation.next_required_actions == ["participants.add_first", "stages.add_first"]
    assert "Add at least one stage before review or publish." in parsed.validation.errors


def test_registry_store_validate_protocol_returns_friendly_strict_issues_for_incomplete_drafts(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )

    validated = store.validate_protocol(created.protocol.protocol_id, access=operator_access())

    assert validated.ok is True
    assert validated.validation is not None
    assert validated.validation.mode == "strict"
    assert validated.validation.ok is False
    assert "Add at least one stage before review or publish." in validated.validation.errors


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
