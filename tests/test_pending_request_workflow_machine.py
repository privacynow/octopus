"""Contract tests for the pending approval/retry functional machine."""

from dataclasses import FrozenInstanceError

import pytest

from octopus_sdk.workflows.pending_machine import (
    ApproveExecuteAction,
    CreateApprovalAction,
    InvalidateStaleAction,
    PendingRequestDisposition,
    PendingRequestSnapshot,
    PendingRequestWorkflowModel,
    decide_pending_request_action,
    run_pending_request_event,
)


def model(state: str, validation_result: str = "ok") -> PendingRequestWorkflowModel:
    return PendingRequestWorkflowModel(state=state, validation_result=validation_result)


@pytest.mark.parametrize(
    "event,_state,to_state,disposition,kwargs",
    [
        ("create_approval", "none", "pending_approval", PendingRequestDisposition.ok, {}),
        ("create_retry", "none", "pending_retry", PendingRequestDisposition.ok, {}),
        (
            "approve_execute",
            "pending_approval",
            "none",
            PendingRequestDisposition.executed,
            {"validation_result": "ok"},
        ),
        (
            "approve_execute",
            "pending_retry",
            "none",
            PendingRequestDisposition.executed,
            {"validation_result": "ok"},
        ),
        ("reject", "pending_approval", "none", PendingRequestDisposition.rejected, {}),
        ("reject", "pending_retry", "none", PendingRequestDisposition.rejected, {}),
        (
            "expire",
            "pending_approval",
            "none",
            PendingRequestDisposition.expired,
            {"validation_result": "expired"},
        ),
        (
            "expire",
            "pending_retry",
            "none",
            PendingRequestDisposition.expired,
            {"validation_result": "expired"},
        ),
        (
            "invalidate_stale",
            "pending_approval",
            "none",
            PendingRequestDisposition.invalidated,
            {"validation_result": "context_changed"},
        ),
        (
            "invalidate_stale",
            "pending_retry",
            "none",
            PendingRequestDisposition.invalidated,
            {"validation_result": "context_changed"},
        ),
        ("cancel", "pending_approval", "none", PendingRequestDisposition.cancelled, {}),
        ("cancel", "pending_retry", "none", PendingRequestDisposition.cancelled, {}),
        ("clear_after_execution", "none", "none", PendingRequestDisposition.ok, {}),
    ],
)
def test_allowed_transitions(
    event: str,
    _state: str,
    to_state: str,
    disposition: PendingRequestDisposition,
    kwargs: dict[str, str],
) -> None:
    workflow_model = model(_state, validation_result=kwargs.get("validation_result", "ok"))
    result = run_pending_request_event(workflow_model, event, **kwargs)
    assert result.allowed is True, result.reason
    assert result.new_state == to_state
    assert result.disposition == disposition


@pytest.mark.parametrize(
    "_state,event",
    [
        ("none", "approve_execute"),
        ("none", "reject"),
        ("none", "expire"),
        ("none", "invalidate_stale"),
        ("none", "cancel"),
        ("pending_approval", "create_approval"),
        ("pending_approval", "create_retry"),
        ("pending_retry", "create_approval"),
        ("pending_retry", "create_retry"),
    ],
)
def test_forbidden_transitions(_state: str, event: str) -> None:
    validation_result = "ok"
    if event in ("expire", "invalidate_stale"):
        validation_result = "expired" if event == "expire" else "context_changed"
    workflow_model = model(_state, validation_result=validation_result)
    result = run_pending_request_event(
        workflow_model,
        event,
        **({"validation_result": validation_result} if event in ("expire", "invalidate_stale") else {}),
    )
    assert result.allowed is False
    assert result.disposition in (
        PendingRequestDisposition.invalid_transition,
        PendingRequestDisposition.guard_failed,
    )
    assert result.reason


def test_approve_execute_guard_expired() -> None:
    workflow_model = model("pending_approval", validation_result="expired")
    result = run_pending_request_event(workflow_model, "approve_execute", validation_result="expired")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_approve_execute_guard_context_changed() -> None:
    workflow_model = model("pending_approval", validation_result="context_changed")
    result = run_pending_request_event(
        workflow_model,
        "approve_execute",
        validation_result="context_changed",
    )
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_expire_guard_requires_expired() -> None:
    workflow_model = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(workflow_model, "expire", validation_result="ok")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_invalidate_stale_guard_requires_context_changed() -> None:
    workflow_model = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(workflow_model, "invalidate_stale", validation_result="ok")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_unknown_event_returns_invalid_transition() -> None:
    workflow_model = model("none")
    result = run_pending_request_event(workflow_model, "unknown_event")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.invalid_transition
    assert "unknown event" in result.reason


def test_unknown_state_returns_invalid_transition() -> None:
    workflow_model = PendingRequestWorkflowModel(state="bogus")
    result = run_pending_request_event(workflow_model, "create_approval")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.invalid_transition
    assert "unknown state" in result.reason
    assert result.model == workflow_model


def test_decision_machine_create_approval() -> None:
    decision = decide_pending_request_action(
        PendingRequestSnapshot(state="none"),
        CreateApprovalAction(),
    )
    assert decision.ok is True
    assert decision.status == "created_approval"
    assert decision.effects.new_state == "pending_approval"
    assert decision.effects.disposition == PendingRequestDisposition.ok


def test_decision_machine_approve_execute() -> None:
    decision = decide_pending_request_action(
        PendingRequestSnapshot(state="pending_approval", validation_result="ok"),
        ApproveExecuteAction(validation_result="ok"),
    )
    assert decision.ok is True
    assert decision.status == "executed"
    assert decision.effects.new_state == "none"
    assert decision.effects.disposition == PendingRequestDisposition.executed


def test_decision_machine_invalid_transition() -> None:
    decision = decide_pending_request_action(
        PendingRequestSnapshot(state="none"),
        ApproveExecuteAction(validation_result="ok"),
    )
    assert decision.ok is False
    assert decision.status == "invalid_transition"
    assert "approve_execute" in decision.reason


def test_decision_and_adapter_stay_equivalent_for_invalidate_stale() -> None:
    snapshot = PendingRequestSnapshot(state="pending_retry", validation_result="context_changed")
    decision = decide_pending_request_action(
        snapshot,
        InvalidateStaleAction(validation_result="context_changed"),
    )
    workflow_model = PendingRequestWorkflowModel(
        state="pending_retry",
        validation_result="context_changed",
    )
    result = run_pending_request_event(
        workflow_model,
        "invalidate_stale",
        validation_result="context_changed",
    )
    assert decision.ok is True
    assert result.allowed is True
    assert result.new_state == decision.effects.new_state
    assert result.disposition == decision.effects.disposition
    assert result.model is not None
    assert result.model.state == decision.effects.new_state
    assert workflow_model.state == "pending_retry"


def test_pending_adapter_returns_new_model_without_mutating_input() -> None:
    workflow_model = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(workflow_model, "approve_execute", validation_result="ok")
    assert result.allowed is True
    assert result.model is not None
    assert result.model is not workflow_model
    assert workflow_model.state == "pending_approval"
    assert workflow_model.validation_result == "ok"
    assert workflow_model.disposition is None
    assert result.model.state == "none"
    assert result.model.disposition == PendingRequestDisposition.executed


def test_pending_workflow_model_is_frozen() -> None:
    workflow_model = model("pending_retry")
    with pytest.raises(FrozenInstanceError):
        workflow_model.state = "none"  # type: ignore[misc]


def test_executed_disposition() -> None:
    workflow_model = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(workflow_model, "approve_execute", validation_result="ok")
    assert result.disposition == PendingRequestDisposition.executed
    assert result.new_state == "none"


def test_rejected_disposition() -> None:
    workflow_model = model("pending_approval")
    result = run_pending_request_event(workflow_model, "reject")
    assert result.disposition == PendingRequestDisposition.rejected
    assert result.new_state == "none"


def test_expired_disposition() -> None:
    workflow_model = model("pending_approval", validation_result="expired")
    result = run_pending_request_event(workflow_model, "expire", validation_result="expired")
    assert result.disposition == PendingRequestDisposition.expired
    assert result.new_state == "none"


def test_invalidated_disposition() -> None:
    workflow_model = model("pending_retry", validation_result="context_changed")
    result = run_pending_request_event(
        workflow_model,
        "invalidate_stale",
        validation_result="context_changed",
    )
    assert result.disposition == PendingRequestDisposition.invalidated
    assert result.new_state == "none"


def test_cancelled_disposition() -> None:
    workflow_model = model("pending_retry")
    result = run_pending_request_event(workflow_model, "cancel")
    assert result.disposition == PendingRequestDisposition.cancelled
    assert result.new_state == "none"
