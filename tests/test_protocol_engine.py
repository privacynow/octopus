from __future__ import annotations

import pytest

from octopus_sdk.protocols.engine import ProtocolRunEngine
from octopus_sdk.protocols import (
    ProtocolArtifactObservationRecord,
    ProtocolParticipantResolutionRecord,
    ProtocolRunRecord,
    ProtocolStageExecutionRecord,
    ProtocolStageTaskResultRecord,
    canonical_protocol_document,
    protocol_review_edge_key,
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


def test_protocol_run_engine_builds_dispatch_request_from_shared_contract() -> None:
    document = _document()
    run = _run().model_copy(
        update={
            "entry_agent_id": "agent-1",
            "root_conversation_id": "conv-1",
            "protocol_definition_version_id": "version-1",
            "workspace_ref": "workspace-a",
            "problem_statement": "Build the thing.",
        }
    )
    stage = document.stage("planning")
    participant = document.participant(stage.participant_key)

    request = _engine().build_dispatch_request(
        document=document,
        run=run,
        stage=stage,
        participant=participant,
        stage_execution_id="planning-exec",
        target_agent_id="agent-2",
        artifacts=[],
        previous_feedback="Tighten the scope.",
        now="2026-04-16T00:00:00+00:00",
    )

    assert request.routed_task_id == "protocol-stage:planning-exec"
    assert request.target_agent_id == "agent-2"
    assert request.session_key_override == "protocol:run-1:participant:worker"
    assert request.project_id_override == "workspace-a"
    assert request.context["protocol_run_id"] == "run-1"
    assert request.internal_context["protocol_stage_contract"]["stage_key"] == "planning"
    assert request.requested_skills == ["planning"]


def test_protocol_run_engine_uses_participant_selector_for_dispatch() -> None:
    document = _document()
    participant = document.participant("worker")

    selector = _engine().dispatch_target_selector(
        run=_run().model_copy(update={"entry_agent_id": "agent-1"}),
        participant=participant,
    )

    assert selector.kind == "skill"
    assert selector.value == "planning"
    assert selector.preferred_agent_id == "agent-1"


def test_protocol_run_engine_evaluates_dispatch_with_shared_request_contract() -> None:
    document = _document()
    run = _run().model_copy(
        update={
            "entry_agent_id": "agent-1",
            "root_conversation_id": "conv-1",
            "protocol_definition_version_id": "version-1",
            "workspace_ref": "workspace-a",
            "problem_statement": "Build the thing.",
        }
    )
    stage_execution = _stage_execution(status="queued")
    dispatch = _engine().dispatch_preflight(
        document=document,
        run=run,
        stage=document.stage("planning"),
        stage_executions=[],
        now="2026-04-16T00:00:00+00:00",
        lease_owner=stage_execution.protocol_stage_execution_id,
        lease_ttl_seconds=900,
    )

    decision = _engine().evaluate_dispatch_resolution(
        document=document,
        run=run,
        stage_execution=stage_execution,
        artifacts=[],
        previous_feedback="Tighten the scope.",
        now="2026-04-16T00:00:00+00:00",
        resolution=ProtocolParticipantResolutionRecord(
            selector=_engine().dispatch_target_selector(
                run=run,
                participant=document.participant("worker"),
            ),
            resolved_agent_id="agent-2",
            resolved_authority_ref="registry:local",
            outcome="ok",
        ),
        timeout_at=dispatch.timeout_at,
        lease_owner=dispatch.lease_owner,
        lease_expires_at=dispatch.lease_expires_at,
    )

    assert decision.run_status == "running"
    assert decision.stage_status == "running"
    assert decision.transition_kind == "dispatch"
    assert decision.routed_task_request is not None
    assert decision.routed_task_request.routed_task_id == "protocol-stage:planning-exec"
    assert decision.routed_task_request.target_agent_id == "agent-2"


def test_protocol_run_engine_blocks_dispatch_when_resolution_fails() -> None:
    document = _document()
    run = _run().model_copy(update={"entry_agent_id": "agent-1"})
    stage_execution = _stage_execution(status="queued")
    dispatch = _engine().dispatch_preflight(
        document=document,
        run=run,
        stage=document.stage("planning"),
        stage_executions=[],
        now="2026-04-16T00:00:00+00:00",
        lease_owner=stage_execution.protocol_stage_execution_id,
        lease_ttl_seconds=900,
    )
    selector = _engine().dispatch_target_selector(
        run=run,
        participant=document.participant("worker"),
    )

    decision = _engine().evaluate_dispatch_resolution(
        document=document,
        run=run,
        stage_execution=stage_execution,
        artifacts=[],
        previous_feedback="",
        now="2026-04-16T00:00:00+00:00",
        resolution=ProtocolParticipantResolutionRecord(
            selector=selector,
            outcome="error",
            reason=f"no agent for {selector.value}",
        ),
        timeout_at=dispatch.timeout_at,
        lease_owner=dispatch.lease_owner,
        lease_expires_at=dispatch.lease_expires_at,
    )

    assert decision.run_status == "blocked"
    assert decision.failure_code == "participant_resolution_failed"


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
    decision = _engine().evaluate_task_result(
        document=document,
        run=_run(),
        stage_execution=_stage_execution(stage_key="review", participant_key="reviewer"),
        stage_executions=[],
        result=result,
        review_edge_counts={protocol_review_edge_key("review", "planning"): 1},
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
