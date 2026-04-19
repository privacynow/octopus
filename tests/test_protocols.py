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
    TargetSelector,
    canonical_protocol_document,
    parse_protocol_stage_decision,
    protocol_document_to_text,
    protocol_review_edge_key,
    validate_protocol_document,
)
from octopus_sdk.protocols.builtins import builtin_protocol_document
from octopus_sdk.registry.models import RegistryJsonRecord, RoutedTaskUpdate
from octopus_registry.protocol_runtime import runtime_protocol_selector
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
        "participants": [{"participant_key": "worker", "display_name": "Worker", "selector": {"kind": "skill", "value": "planning"}}],
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


def test_canonical_protocol_document_synthesizes_selector_from_legacy_required_skill() -> None:
    legacy = protocol_document()
    legacy["participants"][0].pop("selector", None)
    legacy["participants"][0]["required_skills"] = ["planning"]

    document = canonical_protocol_document(legacy)

    participant = document.participant("worker")
    assert participant.selector is not None
    assert participant.selector.kind == "skill"
    assert participant.selector.value == "planning"
    assert "required_skills" not in document.model_dump(mode="json")["participants"][0]


def test_validate_protocol_document_requires_assignment_rule_for_participants() -> None:
    invalid = protocol_document()
    invalid["participants"][0].pop("selector", None)

    result = validate_protocol_document(invalid)

    assert result.ok is False
    assert result.issues
    assert any(item.code == "participant.selector_required" for item in result.issues)


def test_validate_protocol_document_warns_when_legacy_required_skills_has_multiple_values() -> None:
    legacy = protocol_document()
    legacy["participants"][0].pop("selector", None)
    legacy["participants"][0]["required_skills"] = ["planning", "review"]

    result = validate_protocol_document(legacy, mode="draft")

    assert result.ok is True
    assert any(item.code == "participant.legacy_multi_skill" and item.blocking is False for item in result.issues)


def test_builtin_protocol_templates_use_selector_backed_assignment() -> None:
    for slug in ("software-engineering", "document-approval"):
        document = builtin_protocol_document(slug)
        assert document.participants
        for participant in document.participants:
            assert participant.selector is not None, f"{slug} participant {participant.participant_key} must declare a selector"
            assert "required_skills" not in participant.model_dump(mode="json")


def test_runtime_protocol_selector_prefers_entry_agent_for_skill_selectors() -> None:
    selector = runtime_protocol_selector(
        selector=TargetSelector(kind="skill", value="planning"),
        entry_agent_id="agent-1",
    )

    assert selector.kind == "skill"
    assert selector.value == "planning"
    assert selector.preferred_agent_id == "agent-1"


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
    assert loaded.protocol.draft_revision == 1


def test_registry_store_protocol_draft_conflict_requires_matching_revision(postgres_registry_truncated: str) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "blank"}),
        access=operator_access(),
    )
    assert created.ok is True
    assert created.protocol is not None
    protocol_id = created.protocol.protocol_id
    initial_revision = created.protocol.draft_revision
    assert initial_revision == 1

    first_save = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="conflict-protocol",
        display_name="Conflict Protocol",
        description="First writer",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **created.draft_definition_json.as_dict(),
                "metadata": {
                    "slug": "conflict-protocol",
                    "display_name": "Conflict Protocol",
                    "description": "First writer",
                },
            }
        ),
        expected_revision=initial_revision,
    )
    assert first_save.ok is True
    assert first_save.protocol is not None
    assert first_save.protocol.draft_revision == 2

    stale_save = store.save_protocol_draft(
        access=operator_access(),
        protocol_id=protocol_id,
        slug="conflict-protocol",
        display_name="Conflict Protocol",
        description="Stale writer",
        definition_json=RegistryJsonRecord.model_validate(
            {
                **created.draft_definition_json.as_dict(),
                "metadata": {
                    "slug": "conflict-protocol",
                    "display_name": "Conflict Protocol",
                    "description": "Stale writer",
                },
            }
        ),
        expected_revision=initial_revision,
    )
    assert stale_save.ok is False
    assert stale_save.status == "conflict"
    assert stale_save.protocol is not None
    assert stale_save.protocol.draft_revision == 2
    assert stale_save.draft_definition_json.as_dict()["metadata"]["description"] == "First writer"


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
    approval = store.get_protocol_template("document-approval", access=operator_access())
    assert approval.slug == "document-approval"
    assert approval.display_name == "Document Approval"


def test_registry_store_authoring_manifest_lists_templates_and_sections(postgres_registry_truncated: str) -> None:
    from app.db.postgres_init import run_init

    store = RegistryPostgresStore(postgres_registry_truncated)
    with get_connection(postgres_registry_truncated) as conn:
        assert run_init(conn) == []
        conn.commit()

    manifest = store.get_protocol_authoring_manifest(access=operator_access())

    assert manifest.templates
    assert any(item.slug == "software-engineering" for item in manifest.templates)
    assert any(item.slug == "document-approval" for item in manifest.templates)
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

    approval_created = store.create_protocol_draft(
        ProtocolDraftCreateRecord.model_validate({"source_kind": "template", "template_slug": "document-approval"}),
        access=operator_access(),
    )

    assert approval_created.ok is True
    assert approval_created.protocol is not None
    assert approval_created.protocol.slug != "document-approval"
    assert approval_created.draft_definition_json["metadata"]["display_name"].startswith("Document Approval")
    assert approval_created.draft_definition_json["stages"]
    assert approval_created.validation is not None
    assert approval_created.validation.ok is True


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


# ---------------------------------------------------------------------------
# Participation hardening (protocol_kit_plan Step 2)
#
# These guard the invariant that protocol stages ride the task framework and
# that the substrate stays coherent end-to-end: dispatch writes to recipient,
# completion transitions the execution, and the recipient conversation carries
# enough context for UI navigation back to the run.
# ---------------------------------------------------------------------------


def _recipient_conversation_id_for_task(store: RegistryPostgresStore, routed_task_id: str, target_agent_id: str) -> str:
    conversations = store.list_conversations(for_agent_id=target_agent_id, limit=50)
    expected_ref = f"routed-task:{routed_task_id}"
    recipient = next(
        (conv for conv in conversations if conv.external_conversation_ref == expected_ref),
        None,
    )
    assert recipient is not None, f"No recipient task-thread conversation for {routed_task_id}"
    return str(recipient.conversation_id)


def test_protocol_stage_dispatch_writes_events_to_recipient_conversation(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, _created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]
    assert first_stage.routed_task_id.startswith("protocol-stage:")

    recipient_conversation_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )

    recipient_events = store.list_events(recipient_conversation_id).events
    stage_events = [event for event in recipient_events if str(event.kind or "") == "task.status"]
    assert stage_events, "Recipient conversation must receive at least one task.status event"

    queued_event = stage_events[0]
    metadata = queued_event.metadata.as_dict() if queued_event.metadata is not None else {}
    assert metadata.get("routed_task_id") == first_stage.routed_task_id
    assert str(metadata.get("status") or "") == "queued"


def test_protocol_stage_completion_via_routed_task_result_updates_both_sides(
    postgres_registry_truncated: str,
) -> None:
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    origin_conv_id = str(created.run.root_conversation_id or "")
    recipient_conv_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )
    assert origin_conv_id and recipient_conv_id

    origin_before = len(store.list_events(origin_conv_id).events)
    recipient_before = len(store.list_events(recipient_conv_id).events)

    result = store.update_routed_task_result(
        enroll.agent_token,
        first_stage.routed_task_id,
        {
            "status": "completed",
            "transition_id": "done-harden-1",
            "summary": "Plan updated.",
            "full_text": "Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
            "artifacts": [
                {
                    "artifact_key": "plan",
                    "artifact_kind": "workspace_file",
                    "path": "protocol/plan.md",
                    "exists": True,
                    "size_bytes": 42,
                    "content_hash": "hash-harden",
                    "modified_at": "2026-04-16T00:00:00+00:00",
                    "verification_state": "verified",
                }
            ],
        },
    )
    assert result.events_written is True
    assert result.recipient_conversation_id == recipient_conv_id
    assert result.recipient_inserted_events, "Completion must write to the recipient conversation"

    origin_after = store.list_events(origin_conv_id).events
    recipient_after = store.list_events(recipient_conv_id).events
    assert len(origin_after) > origin_before
    assert len(recipient_after) > recipient_before

    newest_recipient = recipient_after[-1]
    metadata = newest_recipient.metadata.as_dict() if newest_recipient.metadata is not None else {}
    assert metadata.get("status") == "completed"
    assert metadata.get("routed_task_id") == first_stage.routed_task_id

    refreshed = store.get_protocol_run(created.run.protocol_run_id, access=operator_access())
    assert refreshed.run.current_stage_key == "review"
    assert refreshed.stage_executions[0].stage_key == "review"


def test_recipient_conversation_event_carries_protocol_stage_navigation_context(
    postgres_registry_truncated: str,
) -> None:
    """UI navigation from recipient conversation back to the run must not rely on
    out-of-band state. The routed_task_id embedded in each recipient event is
    the link: it is a ``protocol-stage:<stage_execution_id>`` key that the
    registry already resolves to a run via ``_protocol_run_id_from_task_record``.
    """
    store = RegistryPostgresStore(postgres_registry_truncated)
    enroll, _published, created, detail = running_protocol_run(store)
    first_stage = detail.stage_executions[0]

    recipient_conv_id = _recipient_conversation_id_for_task(
        store, first_stage.routed_task_id, enroll.agent_id
    )

    events = store.list_events(recipient_conv_id).events
    task_events = [event for event in events if str(event.kind or "") == "task.status"]
    assert task_events

    for event in task_events:
        metadata = event.metadata.as_dict() if event.metadata is not None else {}
        routed_task_id = str(metadata.get("routed_task_id") or "")
        assert routed_task_id.startswith("protocol-stage:"), (
            "Recipient events must carry the protocol-stage routed task id so the UI "
            "can navigate to the owning run"
        )

    task = store.get_task(first_stage.routed_task_id)
    task_request = task.request.as_dict() if task.request is not None else {}
    context = task_request.get("context") if isinstance(task_request, dict) else None
    assert isinstance(context, dict)
    assert context.get("protocol_run_id") == created.run.protocol_run_id
    assert context.get("stage_key") == "planning"
