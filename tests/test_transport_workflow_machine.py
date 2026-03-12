"""Contract tests for transport/recovery workflow (library-backed).

Covers allowed/forbidden transitions, guards (per-chat single-claimed,
pre-claimed same worker, recover_stale_claim requires is_stale), and outcome
classification. Uses the real TransportRecoveryMachine and run_transport_event.
already_handled is repository-level; the machine never returns it. Integration
with work_queue and handlers stays in test_work_queue.py and
test_workitem_integration.py.
"""

import pytest

from app.workflows.results import TransportDisposition
from app.workflows.transport_recovery import (
    TransportRecoveryMachine,
    TransportWorkflowModel,
    run_transport_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def model(
    state: str,
    worker_id: str | None = None,
    has_other_claimed: bool = False,
    is_stale: bool = False,
    requesting_worker_id: str = "",
) -> TransportWorkflowModel:
    return TransportWorkflowModel(
        state=state,
        worker_id=worker_id,
        has_other_claimed_for_chat=has_other_claimed,
        is_stale=is_stale,
        requesting_worker_id=requesting_worker_id,
    )


# ---------------------------------------------------------------------------
# Allowed transitions (via run_transport_event)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,from_state,to_state,disposition,kwargs",
    [
        ("claim_inline", "queued", "claimed", TransportDisposition.ok, {"requesting_worker_id": "w1"}),
        ("claim_worker", "queued", "claimed", TransportDisposition.ok, {}),
        ("complete", "queued", "done", TransportDisposition.done, {}),
        ("complete", "claimed", "done", TransportDisposition.done, {}),
        ("fail", "queued", "failed", TransportDisposition.failed, {}),
        ("fail", "claimed", "failed", TransportDisposition.failed, {}),
        ("move_to_pending_recovery", "claimed", "pending_recovery", TransportDisposition.ok, {}),
        ("recover_stale_claim", "claimed", "queued", TransportDisposition.stale_recovered, {}),
        ("reclaim_for_replay", "pending_recovery", "claimed", TransportDisposition.replayed, {}),
        ("discard_recovery", "pending_recovery", "done", TransportDisposition.discarded, {}),
        ("supersede_recovery", "pending_recovery", "done", TransportDisposition.superseded, {}),
    ],
)
def test_allowed_transitions(event, from_state, to_state, disposition, kwargs):
    is_stale = event == "recover_stale_claim"
    m = model(from_state, is_stale=is_stale, **{k: v for k, v in kwargs.items() if k == "requesting_worker_id" and v})
    result = run_transport_event(m, event, **kwargs)
    assert result.allowed is True, result.reason
    assert result.new_state == to_state
    assert result.disposition == disposition


def test_claim_inline_from_claimed_same_worker_no_op():
    """Pre-claimed inline item: same worker re-claiming is allowed (no state change)."""
    m = model("claimed", worker_id="worker-1", requesting_worker_id="worker-1")
    result = run_transport_event(m, "claim_inline", requesting_worker_id="worker-1")
    assert result.allowed is True
    assert result.new_state == "claimed"
    assert result.disposition == TransportDisposition.already_claimed_by_worker


def test_claim_inline_from_claimed_other_worker_blocked():
    """Item claimed by one worker; different worker cannot claim_inline (ownership)."""
    m = model(
        "claimed",
        worker_id="owner",
        requesting_worker_id="other",
        has_other_claimed=False,
    )
    result = run_transport_event(m, "claim_inline", requesting_worker_id="other")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat
    assert "other_claimed_for_chat" in result.reason or result.reason


def test_claim_inline_from_claimed_ownerless_blocked():
    """Item in claimed with no worker_id (ownerless) blocks claim_inline by any worker."""
    m = TransportWorkflowModel(
        state="claimed",
        worker_id=None,
        requesting_worker_id="other",
        has_other_claimed_for_chat=False,
    )
    result = run_transport_event(m, "claim_inline", requesting_worker_id="other")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_claim_inline_from_queued_requires_requester():
    """claim_inline from queued without requesting_worker_id is rejected."""
    m = model("queued")
    result = run_transport_event(m, "claim_inline")  # no requesting_worker_id
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


# ---------------------------------------------------------------------------
# Forbidden transitions (invalid from state)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_state,event", [
    ("queued", "move_to_pending_recovery"),
    ("queued", "reclaim_for_replay"),
    ("queued", "recover_stale_claim"),
    ("done", "claim_inline"),
    ("done", "complete"),
    ("failed", "claim_worker"),
    ("claimed", "reclaim_for_replay"),
    ("claimed", "discard_recovery"),
    ("pending_recovery", "claim_inline"),
    ("pending_recovery", "complete"),
])
def test_forbidden_transitions(from_state, event):
    m = model(from_state)
    kwargs = {"requesting_worker_id": "w1"} if event == "claim_inline" else {}
    result = run_transport_event(m, event, **kwargs)
    assert result.allowed is False
    assert result.disposition == TransportDisposition.invalid_transition
    assert result.reason  # machine or adapter provides a reason


def test_unknown_state_raises_corruption():
    """Unknown model state raises TransportStateCorruption so callers surface corruption."""
    from app.workflows.results import TransportStateCorruption

    m = TransportWorkflowModel(state="bogus")
    with pytest.raises(TransportStateCorruption) as exc_info:
        run_transport_event(m, "complete")
    assert "unknown state" in str(exc_info.value) and "bogus" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Guards: per-chat single-claimed
# ---------------------------------------------------------------------------


def test_claim_inline_blocked_when_other_claimed_for_chat():
    m = model("queued", has_other_claimed=True)
    result = run_transport_event(m, "claim_inline", requesting_worker_id="w1")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_claim_worker_blocked_when_other_claimed_for_chat():
    m = model("queued", has_other_claimed=True)
    result = run_transport_event(m, "claim_worker")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_reclaim_for_replay_blocked_when_other_claimed_for_chat():
    """Replay button clicked but another item for same chat is already claimed."""
    m = model("pending_recovery", has_other_claimed=True)
    result = run_transport_event(m, "reclaim_for_replay")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.blocked_replay


# ---------------------------------------------------------------------------
# Real machine: direct instantiation and event methods
# ---------------------------------------------------------------------------


def test_machine_direct_claim_inline():
    """Real StateMachine updates model.state and model.disposition when requester is set."""
    m = model("queued", requesting_worker_id="w1")
    sm = TransportRecoveryMachine(model=m, rtc=True, allow_event_without_transition=False)
    sm.claim_inline()
    assert m.state == "claimed"
    assert m.disposition == TransportDisposition.ok


def test_machine_same_worker_reclaim():
    m = model("claimed", worker_id="w1", requesting_worker_id="w1")
    sm = TransportRecoveryMachine(model=m, rtc=True, allow_event_without_transition=False)
    sm.claim_inline()
    assert m.state == "claimed"
    assert m.disposition == TransportDisposition.already_claimed_by_worker


def test_machine_transition_not_allowed_raises():
    """TransitionNotAllowed when event has no transition from current state."""
    from statemachine.exceptions import TransitionNotAllowed

    m = model("done")
    sm = TransportRecoveryMachine(model=m, rtc=True, allow_event_without_transition=False)
    with pytest.raises(TransitionNotAllowed):
        sm.complete()


# ---------------------------------------------------------------------------
# Outcome classification (dispositions)
# ---------------------------------------------------------------------------


def test_discard_recovery_disposition():
    m = model("pending_recovery")
    result = run_transport_event(m, "discard_recovery")
    assert result.disposition == TransportDisposition.discarded
    assert result.new_state == "done"


def test_supersede_recovery_disposition():
    m = model("pending_recovery")
    result = run_transport_event(m, "supersede_recovery")
    assert result.disposition == TransportDisposition.superseded
    assert result.new_state == "done"


def test_stale_recovered_disposition():
    """recover_stale_claim allowed only when repository passed is_stale=True."""
    m = model("claimed", worker_id="dead-worker", is_stale=True)
    result = run_transport_event(m, "recover_stale_claim")
    assert result.disposition == TransportDisposition.stale_recovered
    assert result.new_state == "queued"


def test_recover_stale_claim_requires_stale_guard():
    """recover_stale_claim from claimed with is_stale=False is guard_failed (fresh work)."""
    m = model("claimed", worker_id="current-worker", is_stale=False)
    result = run_transport_event(m, "recover_stale_claim")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.guard_failed
    assert "not_stale" in result.reason or result.reason


def test_done_and_failed_are_terminal_dispositions():
    m_claimed = model("claimed")
    r_done = run_transport_event(m_claimed, "complete")
    assert r_done.disposition == TransportDisposition.done
    m_claimed2 = model("claimed")
    r_failed = run_transport_event(m_claimed2, "fail")
    assert r_failed.disposition == TransportDisposition.failed
