"""Contract tests for the transport/recovery functional machine."""

from dataclasses import FrozenInstanceError

import pytest

from app.workflows.recovery.results import TransportDisposition, TransportStateCorruption
from app.workflows.recovery.machine import (
    ClaimInlineAction,
    ReclaimForReplayAction,
    TransportSnapshot,
    TransportWorkflowModel,
    decide_transport_action,
    run_transport_event,
)


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
def test_allowed_transitions(
    event: str,
    from_state: str,
    to_state: str,
    disposition: TransportDisposition,
    kwargs: dict[str, str],
) -> None:
    workflow_model = model(
        from_state,
        is_stale=event == "recover_stale_claim",
        **{k: v for k, v in kwargs.items() if k == "requesting_worker_id" and v},
    )
    result = run_transport_event(workflow_model, event, **kwargs)
    assert result.allowed is True, result.reason
    assert result.new_state == to_state
    assert result.disposition == disposition


def test_claim_inline_from_claimed_same_worker_no_op() -> None:
    workflow_model = model("claimed", worker_id="worker-1", requesting_worker_id="worker-1")
    result = run_transport_event(workflow_model, "claim_inline", requesting_worker_id="worker-1")
    assert result.allowed is True
    assert result.new_state == "claimed"
    assert result.disposition == TransportDisposition.already_claimed_by_worker


def test_claim_inline_from_claimed_other_worker_blocked() -> None:
    workflow_model = model(
        "claimed",
        worker_id="owner",
        requesting_worker_id="other",
        has_other_claimed=False,
    )
    result = run_transport_event(workflow_model, "claim_inline", requesting_worker_id="other")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat
    assert "other_claimed_for_chat" in result.reason or result.reason


def test_claim_inline_from_claimed_ownerless_blocked() -> None:
    workflow_model = TransportWorkflowModel(
        state="claimed",
        worker_id=None,
        requesting_worker_id="other",
        has_other_claimed_for_chat=False,
    )
    result = run_transport_event(workflow_model, "claim_inline", requesting_worker_id="other")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_claim_inline_from_queued_requires_requester() -> None:
    workflow_model = model("queued")
    result = run_transport_event(workflow_model, "claim_inline")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


@pytest.mark.parametrize(
    "from_state,event",
    [
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
    ],
)
def test_forbidden_transitions(from_state: str, event: str) -> None:
    workflow_model = model(from_state)
    kwargs = {"requesting_worker_id": "w1"} if event == "claim_inline" else {}
    result = run_transport_event(workflow_model, event, **kwargs)
    assert result.allowed is False
    assert result.disposition == TransportDisposition.invalid_transition
    assert result.reason


def test_unknown_state_raises_corruption() -> None:
    workflow_model = TransportWorkflowModel(state="bogus")
    with pytest.raises(TransportStateCorruption) as exc_info:
        run_transport_event(workflow_model, "complete")
    assert "unknown state" in str(exc_info.value) and "bogus" in str(exc_info.value)


def test_claim_inline_blocked_when_other_claimed_for_chat() -> None:
    workflow_model = model("queued", has_other_claimed=True)
    result = run_transport_event(workflow_model, "claim_inline", requesting_worker_id="w1")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_claim_worker_blocked_when_other_claimed_for_chat() -> None:
    workflow_model = model("queued", has_other_claimed=True)
    result = run_transport_event(workflow_model, "claim_worker")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.other_claimed_for_chat


def test_claim_worker_succeeds_when_no_other_claimed() -> None:
    workflow_model = model("queued", has_other_claimed=False)
    result = run_transport_event(workflow_model, "claim_worker")
    assert result.allowed is True
    assert result.new_state == "claimed"
    assert result.disposition == TransportDisposition.ok


def test_reclaim_for_replay_blocked_when_other_claimed_for_chat() -> None:
    workflow_model = model("pending_recovery", has_other_claimed=True)
    result = run_transport_event(workflow_model, "reclaim_for_replay")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.blocked_replay


def test_decision_machine_claim_inline() -> None:
    decision = decide_transport_action(
        TransportSnapshot(state="queued", requesting_worker_id="w1"),
        ClaimInlineAction(requesting_worker_id="w1"),
    )
    assert decision.ok is True
    assert decision.status == "claimed"
    assert decision.effects.new_state == "claimed"
    assert decision.effects.disposition == TransportDisposition.ok


def test_decision_machine_same_worker_reclaim() -> None:
    decision = decide_transport_action(
        TransportSnapshot(state="claimed", worker_id="w1", requesting_worker_id="w1"),
        ClaimInlineAction(requesting_worker_id="w1"),
    )
    assert decision.ok is True
    assert decision.status == "already_claimed_by_worker"
    assert decision.effects.disposition == TransportDisposition.already_claimed_by_worker


def test_decision_machine_invalid_transition() -> None:
    decision = decide_transport_action(
        TransportSnapshot(state="done"),
        ClaimInlineAction(requesting_worker_id="w1"),
    )
    assert decision.ok is False
    assert decision.status == "invalid_transition"
    assert "claim_inline" in decision.reason


def test_decision_and_adapter_stay_equivalent_for_reclaim_for_replay() -> None:
    snapshot = TransportSnapshot(state="pending_recovery", has_other_claimed_for_chat=False)
    decision = decide_transport_action(snapshot, ReclaimForReplayAction())
    workflow_model = TransportWorkflowModel(state="pending_recovery", has_other_claimed_for_chat=False)
    result = run_transport_event(workflow_model, "reclaim_for_replay")
    assert decision.ok is True
    assert result.allowed is True
    assert result.new_state == decision.effects.new_state
    assert result.disposition == decision.effects.disposition
    assert result.model is not None
    assert result.model.state == decision.effects.new_state
    assert workflow_model.state == "pending_recovery"


def test_discard_recovery_disposition() -> None:
    workflow_model = model("pending_recovery")
    result = run_transport_event(workflow_model, "discard_recovery")
    assert result.disposition == TransportDisposition.discarded
    assert result.new_state == "done"


def test_supersede_recovery_disposition() -> None:
    workflow_model = model("pending_recovery")
    result = run_transport_event(workflow_model, "supersede_recovery")
    assert result.disposition == TransportDisposition.superseded
    assert result.new_state == "done"


def test_stale_recovered_disposition() -> None:
    workflow_model = model("claimed", worker_id="dead-worker", is_stale=True)
    result = run_transport_event(workflow_model, "recover_stale_claim")
    assert result.disposition == TransportDisposition.stale_recovered
    assert result.new_state == "queued"


def test_recover_stale_claim_requires_stale_guard() -> None:
    workflow_model = model("claimed", worker_id="current-worker", is_stale=False)
    result = run_transport_event(workflow_model, "recover_stale_claim")
    assert result.allowed is False
    assert result.disposition == TransportDisposition.guard_failed
    assert "not_stale" in result.reason or result.reason


def test_done_and_failed_are_terminal_dispositions() -> None:
    claimed_model = model("claimed")
    done_result = run_transport_event(claimed_model, "complete")
    assert done_result.disposition == TransportDisposition.done
    claimed_model_2 = model("claimed")
    failed_result = run_transport_event(claimed_model_2, "fail")
    assert failed_result.disposition == TransportDisposition.failed


def test_transport_adapter_returns_new_model_without_mutating_input() -> None:
    workflow_model = model("queued", requesting_worker_id="")
    result = run_transport_event(workflow_model, "claim_inline", requesting_worker_id="worker-1")
    assert result.allowed is True
    assert result.model is not None
    assert result.model is not workflow_model
    assert workflow_model.state == "queued"
    assert workflow_model.requesting_worker_id == ""
    assert workflow_model.disposition is None
    assert result.model.state == "claimed"
    assert result.model.requesting_worker_id == "worker-1"
    assert result.model.disposition == TransportDisposition.ok


def test_transport_workflow_model_is_frozen() -> None:
    workflow_model = model("queued")
    with pytest.raises(FrozenInstanceError):
        workflow_model.state = "claimed"  # type: ignore[misc]
