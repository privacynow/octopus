"""Contract tests for pending approval/retry workflow (library-backed).

Covers allowed/forbidden transitions, guards (validation_ok, is_expired,
is_context_stale), and outcome classification. Uses the real
PendingRequestMachine and run_pending_request_event. Session persistence
stays in handlers; integration coverage in request_flow/handler tests.
"""

import pytest

from app.workflows.pending_request import (
    PendingRequestDisposition,
    PendingRequestMachine,
    PendingRequestTransitionResult,
    PendingRequestWorkflowModel,
    run_pending_request_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def model(
    state: str,
    validation_result: str = "ok",
) -> PendingRequestWorkflowModel:
    return PendingRequestWorkflowModel(state=state, validation_result=validation_result)


# ---------------------------------------------------------------------------
# Allowed transitions (via run_pending_request_event)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,from_state,to_state,disposition,kwargs",
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
    from_state: str,
    to_state: str,
    disposition: PendingRequestDisposition,
    kwargs: dict,
) -> None:
    m = model(from_state, validation_result=kwargs.get("validation_result", "ok"))
    result = run_pending_request_event(m, event, **kwargs)
    assert result.allowed is True, result.reason
    assert result.new_state == to_state
    assert result.disposition == disposition


# ---------------------------------------------------------------------------
# Forbidden transitions (invalid from state)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "from_state,event",
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
def test_forbidden_transitions(from_state: str, event: str) -> None:
    val = "ok"
    if event in ("expire", "invalidate_stale"):
        val = "expired" if event == "expire" else "context_changed"
    m = model(from_state, validation_result=val)
    result = run_pending_request_event(
        m, event, **({"validation_result": val} if event in ("expire", "invalidate_stale") else {})
    )
    assert result.allowed is False
    assert result.disposition in (
        PendingRequestDisposition.invalid_transition,
        PendingRequestDisposition.guard_failed,
    )
    assert result.reason or result.disposition == PendingRequestDisposition.invalid_transition


# ---------------------------------------------------------------------------
# Guards: approve_execute requires validation_ok
# ---------------------------------------------------------------------------


def test_approve_execute_guard_expired() -> None:
    """approve_execute from pending_approval with validation_result=expired is guard_failed."""
    m = model("pending_approval", validation_result="expired")
    result = run_pending_request_event(m, "approve_execute", validation_result="expired")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_approve_execute_guard_context_changed() -> None:
    """approve_execute from pending_approval with validation_result=context_changed is guard_failed."""
    m = model("pending_approval", validation_result="context_changed")
    result = run_pending_request_event(m, "approve_execute", validation_result="context_changed")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_expire_guard_requires_expired() -> None:
    """expire from pending_approval with validation_result=ok has no matching transition (guard)."""
    m = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(m, "expire", validation_result="ok")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


def test_invalidate_stale_guard_requires_context_changed() -> None:
    """invalidate_stale with validation_result=ok is guard_failed."""
    m = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(m, "invalidate_stale", validation_result="ok")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.guard_failed


# ---------------------------------------------------------------------------
# Unknown event/state
# ---------------------------------------------------------------------------


def test_unknown_event_returns_invalid_transition() -> None:
    m = model("none")
    result = run_pending_request_event(m, "unknown_event")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.invalid_transition
    assert "unknown event" in result.reason or "unknown_event" in result.reason


def test_unknown_state_returns_invalid_transition() -> None:
    m = PendingRequestWorkflowModel(state="bogus")
    result = run_pending_request_event(m, "create_approval")
    assert result.allowed is False
    assert result.disposition == PendingRequestDisposition.invalid_transition
    assert "unknown state" in result.reason or "bogus" in result.reason


# ---------------------------------------------------------------------------
# Real machine: direct instantiation and event methods
# ---------------------------------------------------------------------------


def test_machine_direct_create_approval() -> None:
    """StateMachine updates model.state and model.disposition on create_approval."""
    m = model("none")
    sm = PendingRequestMachine(model=m, rtc=True, allow_event_without_transition=False)
    sm.create_approval()
    assert m.state == "pending_approval"
    assert m.disposition == PendingRequestDisposition.ok


def test_machine_direct_approve_execute() -> None:
    m = model("pending_approval", validation_result="ok")
    sm = PendingRequestMachine(model=m, rtc=True, allow_event_without_transition=False)
    sm.approve_execute()
    assert m.state == "none"
    assert m.disposition == PendingRequestDisposition.executed


def test_machine_transition_not_allowed_raises() -> None:
    """TransitionNotAllowed when event has no transition from current state."""
    from statemachine.exceptions import TransitionNotAllowed

    m = model("none")
    sm = PendingRequestMachine(model=m, rtc=True, allow_event_without_transition=False)
    with pytest.raises(TransitionNotAllowed):
        sm.approve_execute()


# ---------------------------------------------------------------------------
# Outcome classification (dispositions)
# ---------------------------------------------------------------------------


def test_executed_disposition() -> None:
    m = model("pending_approval", validation_result="ok")
    result = run_pending_request_event(m, "approve_execute", validation_result="ok")
    assert result.disposition == PendingRequestDisposition.executed
    assert result.new_state == "none"


def test_rejected_disposition() -> None:
    m = model("pending_approval")
    result = run_pending_request_event(m, "reject")
    assert result.disposition == PendingRequestDisposition.rejected
    assert result.new_state == "none"


def test_expired_disposition() -> None:
    m = model("pending_approval", validation_result="expired")
    result = run_pending_request_event(m, "expire", validation_result="expired")
    assert result.disposition == PendingRequestDisposition.expired
    assert result.new_state == "none"


def test_invalidated_disposition() -> None:
    m = model("pending_retry", validation_result="context_changed")
    result = run_pending_request_event(m, "invalidate_stale", validation_result="context_changed")
    assert result.disposition == PendingRequestDisposition.invalidated
    assert result.new_state == "none"


def test_cancelled_disposition() -> None:
    m = model("pending_retry")
    result = run_pending_request_event(m, "cancel")
    assert result.disposition == PendingRequestDisposition.cancelled
    assert result.new_state == "none"


# ---------------------------------------------------------------------------
# Handler path: classification + machine yields correct disposition
# ---------------------------------------------------------------------------


def test_approve_path_ok_executes_via_machine() -> None:
    """When classification is ok, approve_execute returns executed (handler proceeds)."""
    m = PendingRequestWorkflowModel(state="pending_approval", validation_result="ok")
    result = run_pending_request_event(m, "approve_execute", validation_result="ok")
    assert result.allowed is True
    assert result.disposition == PendingRequestDisposition.executed
    assert result.new_state == "none"


def test_approve_path_expired_returns_expired_disposition() -> None:
    """When classification is expired, expire event returns expired (handler clears and shows message)."""
    m = PendingRequestWorkflowModel(state="pending_approval", validation_result="expired")
    result = run_pending_request_event(m, "expire", validation_result="expired")
    assert result.allowed is True
    assert result.disposition == PendingRequestDisposition.expired
    assert result.new_state == "none"


def test_approve_path_context_changed_returns_invalidated_disposition() -> None:
    """When classification is context_changed, invalidate_stale returns invalidated (handler clears)."""
    m = PendingRequestWorkflowModel(state="pending_retry", validation_result="context_changed")
    result = run_pending_request_event(m, "invalidate_stale", validation_result="context_changed")
    assert result.allowed is True
    assert result.disposition == PendingRequestDisposition.invalidated
    assert result.new_state == "none"
