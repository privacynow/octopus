from __future__ import annotations

import pytest

from octopus_sdk.protocol_engine import ProtocolRunEngine
from octopus_sdk.protocols import (
    ProtocolArtifactObservationRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
    ProtocolStageTaskResultRecord,
    canonical_protocol_document,
)
from tests.support.protocol_support import protocol_document


def _engine() -> ProtocolRunEngine:
    return ProtocolRunEngine()


def _document():
    return canonical_protocol_document(protocol_document())


def _run() -> ProtocolRunRecord:
    return ProtocolRunRecord(
        protocol_run_id="run-1",
        created_at="2026-04-16T00:00:00+00:00",
        current_stage_execution_id="stage-current",
    )


def _stage_execution(
    *,
    stage_key: str = "planning",
    participant_key: str = "worker",
    status: str = "running",
    timeout_at: str = "",
    decision: str = "",
) -> ProtocolStageExecutionRecord:
    return ProtocolStageExecutionRecord(
        protocol_stage_execution_id=f"{stage_key}-exec",
        protocol_run_id="run-1",
        stage_key=stage_key,
        participant_key=participant_key,
        status=status,
        timeout_at=timeout_at,
        decision=decision,
    )


def test_protocol_run_engine_dispatch_preflight_blocks_active_write_lease() -> None:
    document = _document()
    decision = _engine().dispatch_preflight(
        document=document,
        run=_run(),
        stage=document.stage("planning"),
        stage_executions=[
            ProtocolStageExecutionRecord(
                protocol_stage_execution_id="other-stage",
                protocol_run_id="run-1",
                stage_key="planning",
                participant_key="worker",
                status="running",
                lease_owner="other-stage",
                lease_expires_at="2099-01-01T00:00:00+00:00",
            )
        ],
        now="2026-04-16T01:00:00+00:00",
        lease_owner="stage-current",
        lease_ttl_seconds=900,
    )

    assert decision.ok is False
    assert decision.error_code == "LEASE_HELD"


def test_protocol_run_engine_marks_late_completed_result_as_timeout() -> None:
    document = _document()
    result = ProtocolStageTaskResultRecord(
        routed_task_id="protocol-stage:planning-exec",
        status="completed",
        summary="Plan updated.",
        full_text="Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
        artifacts=[
            ProtocolArtifactObservationRecord(
                artifact_key="plan",
                artifact_kind="workspace_file",
                path="protocol/plan.md",
                exists=True,
                size_bytes=128,
                content_hash="abc123",
                modified_at="2026-04-16T00:10:00+00:00",
                verification_state="verified",
            )
        ],
        completed_at="2026-04-16T00:30:00+00:00",
    )

    decision = _engine().evaluate_task_result(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(timeout_at="2026-04-16T00:05:00+00:00"),
        stage_executions=[],
        result=result,
    )

    assert decision.run_status == "failed"
    assert decision.failure_code == "stage_timeout"


def test_protocol_run_engine_blocks_when_artifact_is_missing() -> None:
    document = _document()
    result = ProtocolStageTaskResultRecord(
        routed_task_id="protocol-stage:planning-exec",
        status="completed",
        summary="Plan updated.",
        full_text="Updated protocol/plan.md.\nPROTOCOL_SUMMARY: Plan updated.",
        artifacts=[],
        completed_at="2026-04-16T00:10:00+00:00",
    )

    decision = _engine().evaluate_task_result(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(),
        stage_executions=[],
        result=result,
    )

    assert decision.run_status == "blocked"
    assert decision.failure_code == "artifact_missing"


def test_protocol_run_engine_blocks_when_review_round_cap_is_exceeded() -> None:
    document = canonical_protocol_document(
        {
            **protocol_document(),
            "policies": {
                "single_active_writer": True,
                "max_review_rounds": 1,
            },
        }
    )
    result = ProtocolStageTaskResultRecord(
        routed_task_id="protocol-stage:review-exec",
        status="completed",
        summary="Needs changes.",
        full_text="Needs more work.\nPROTOCOL_DECISION: revise\nPROTOCOL_SUMMARY: Needs changes.",
        completed_at="2026-04-16T00:10:00+00:00",
    )
    prior_revise = ProtocolStageExecutionRecord(
        protocol_stage_execution_id="review-old",
        protocol_run_id="run-1",
        stage_key="review",
        participant_key="reviewer",
        status="completed",
        decision="revise",
    )

    decision = _engine().evaluate_task_result(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(stage_key="review", participant_key="reviewer"),
        stage_executions=[prior_revise],
        result=result,
    )

    assert decision.run_status == "blocked"
    assert decision.failure_code == "max_review_rounds_exceeded"


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_decision"),
    [
        ("accept", "completed", "accept"),
        ("send_back", "running", "revise"),
    ],
)
def test_protocol_run_engine_applies_operator_review_actions(
    action: str,
    expected_status: str,
    expected_decision: str,
) -> None:
    document = _document()

    decision = _engine().evaluate_operator_action(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(stage_key="review", participant_key="reviewer", status="blocked"),
        stage_executions=[],
        action=action,
        reason="Operator intervention.",
        now="2026-04-16T00:12:00+00:00",
    )

    assert decision.run_status == expected_status
    assert decision.decision == expected_decision


def test_protocol_run_engine_rejects_retry_from_running_stage() -> None:
    document = _document()

    decision = _engine().evaluate_operator_action(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(status="running"),
        stage_executions=[],
        action="retry",
        reason="Try again.",
        now="2026-04-16T00:12:00+00:00",
    )

    assert decision.run_status == "blocked"
    assert decision.failure_code == "invalid_retry_state"
