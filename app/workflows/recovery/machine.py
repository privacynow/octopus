"""Functional decision machine for transport recovery progression."""

from __future__ import annotations

from dataclasses import dataclass

from app.workflows.recovery.results import TransportDisposition, TransitionResult, TransportStateCorruption

TRANSPORT_STATES = frozenset(
    {
        "queued",
        "claimed",
        "pending_recovery",
        "done",
        "failed",
    }
)


@dataclass
class TransportWorkflowModel:
    state: str
    worker_id: str | None = None
    requesting_worker_id: str = ""
    has_other_claimed_for_chat: bool = False
    is_stale: bool = False
    disposition: TransportDisposition | None = None
    reason: str = ""


@dataclass(frozen=True)
class TransportSnapshot:
    state: str
    worker_id: str | None = None
    requesting_worker_id: str = ""
    has_other_claimed_for_chat: bool = False
    is_stale: bool = False


@dataclass(frozen=True)
class TransportEffects:
    new_state: str | None = None
    disposition: TransportDisposition | None = None


@dataclass(frozen=True)
class TransportDecision:
    status: str
    ok: bool
    effects: TransportEffects = TransportEffects()
    reason: str = ""


@dataclass(frozen=True)
class ClaimInlineAction:
    requesting_worker_id: str = ""


@dataclass(frozen=True)
class ClaimWorkerAction:
    pass


@dataclass(frozen=True)
class CompleteAction:
    pass


@dataclass(frozen=True)
class FailAction:
    pass


@dataclass(frozen=True)
class MoveToPendingRecoveryAction:
    pass


@dataclass(frozen=True)
class RecoverStaleClaimAction:
    pass


@dataclass(frozen=True)
class ReclaimForReplayAction:
    pass


@dataclass(frozen=True)
class DiscardRecoveryAction:
    pass


@dataclass(frozen=True)
class SupersedeRecoveryAction:
    pass


TransportAction = (
    ClaimInlineAction
    | ClaimWorkerAction
    | CompleteAction
    | FailAction
    | MoveToPendingRecoveryAction
    | RecoverStaleClaimAction
    | ReclaimForReplayAction
    | DiscardRecoveryAction
    | SupersedeRecoveryAction
)


def decide_transport_action(
    snapshot: TransportSnapshot,
    action: TransportAction,
) -> TransportDecision:
    state = snapshot.state
    if state not in TRANSPORT_STATES:
        raise TransportStateCorruption(f"unknown state {state!r}")

    if isinstance(action, ClaimInlineAction):
        requester = action.requesting_worker_id
        if state == "queued":
            if snapshot.has_other_claimed_for_chat:
                return TransportDecision(
                    status="other_claimed_for_chat",
                    ok=False,
                    reason="other_claimed_for_chat",
                )
            if not requester:
                return TransportDecision(
                    status="other_claimed_for_chat",
                    ok=False,
                    reason="claim_inline requires requesting_worker_id",
                )
            return TransportDecision(
                status="claimed",
                ok=True,
                effects=TransportEffects(
                    new_state="claimed",
                    disposition=TransportDisposition.ok,
                ),
            )
        if state == "claimed":
            if requester and snapshot.worker_id and requester == snapshot.worker_id:
                return TransportDecision(
                    status="already_claimed_by_worker",
                    ok=True,
                    effects=TransportEffects(
                        new_state="claimed",
                        disposition=TransportDisposition.already_claimed_by_worker,
                    ),
                )
            if snapshot.has_other_claimed_for_chat:
                return TransportDecision(
                    status="other_claimed_for_chat",
                    ok=False,
                    reason="other_claimed_for_chat",
                )
            if requester and (not snapshot.worker_id or requester != snapshot.worker_id):
                return TransportDecision(
                    status="other_claimed_for_chat",
                    ok=False,
                    reason="other_claimed_for_chat",
                )
            return TransportDecision(
                status="claimed",
                ok=True,
                effects=TransportEffects(
                    new_state="claimed",
                    disposition=TransportDisposition.ok,
                ),
            )
        return TransportDecision(
            status="invalid_transition",
            ok=False,
            reason=f"no transition 'claim_inline' from {state!r}",
        )

    if isinstance(action, ClaimWorkerAction):
        if state != "queued":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'claim_worker' from {state!r}",
            )
        if snapshot.has_other_claimed_for_chat:
            return TransportDecision(
                status="other_claimed_for_chat",
                ok=False,
                reason="other_claimed_for_chat",
            )
        return TransportDecision(
            status="claimed",
            ok=True,
            effects=TransportEffects(
                new_state="claimed",
                disposition=TransportDisposition.ok,
            ),
        )

    if isinstance(action, CompleteAction):
        if state not in {"queued", "claimed"}:
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'complete' from {state!r}",
            )
        return TransportDecision(
            status="done",
            ok=True,
            effects=TransportEffects(
                new_state="done",
                disposition=TransportDisposition.done,
            ),
        )

    if isinstance(action, FailAction):
        if state not in {"queued", "claimed"}:
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'fail' from {state!r}",
            )
        return TransportDecision(
            status="failed",
            ok=True,
            effects=TransportEffects(
                new_state="failed",
                disposition=TransportDisposition.failed,
            ),
        )

    if isinstance(action, MoveToPendingRecoveryAction):
        if state != "claimed":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'move_to_pending_recovery' from {state!r}",
            )
        return TransportDecision(
            status="pending_recovery",
            ok=True,
            effects=TransportEffects(
                new_state="pending_recovery",
                disposition=TransportDisposition.ok,
            ),
        )

    if isinstance(action, RecoverStaleClaimAction):
        if state != "claimed":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'recover_stale_claim' from {state!r}",
            )
        if not snapshot.is_stale:
            return TransportDecision(
                status="guard_failed",
                ok=False,
                reason="not_stale",
            )
        return TransportDecision(
            status="stale_recovered",
            ok=True,
            effects=TransportEffects(
                new_state="queued",
                disposition=TransportDisposition.stale_recovered,
            ),
        )

    if isinstance(action, ReclaimForReplayAction):
        if state != "pending_recovery":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'reclaim_for_replay' from {state!r}",
            )
        if snapshot.has_other_claimed_for_chat:
            return TransportDecision(
                status="blocked_replay",
                ok=False,
                reason="blocked_replay",
            )
        return TransportDecision(
            status="replayed",
            ok=True,
            effects=TransportEffects(
                new_state="claimed",
                disposition=TransportDisposition.replayed,
            ),
        )

    if isinstance(action, DiscardRecoveryAction):
        if state != "pending_recovery":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'discard_recovery' from {state!r}",
            )
        return TransportDecision(
            status="discarded",
            ok=True,
            effects=TransportEffects(
                new_state="done",
                disposition=TransportDisposition.discarded,
            ),
        )

    if isinstance(action, SupersedeRecoveryAction):
        if state != "pending_recovery":
            return TransportDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'supersede_recovery' from {state!r}",
            )
        return TransportDecision(
            status="superseded",
            ok=True,
            effects=TransportEffects(
                new_state="done",
                disposition=TransportDisposition.superseded,
            ),
        )

    raise ValueError(f"Unknown transport action: {action!r}")


_EVENT_NAMES = frozenset(
    {
        "claim_inline",
        "claim_worker",
        "complete",
        "fail",
        "move_to_pending_recovery",
        "recover_stale_claim",
        "reclaim_for_replay",
        "discard_recovery",
        "supersede_recovery",
    }
)


def _build_action(event_name: str, requesting_worker_id: str) -> TransportAction | None:
    if event_name == "claim_inline":
        return ClaimInlineAction(requesting_worker_id=requesting_worker_id)
    if event_name == "claim_worker":
        return ClaimWorkerAction()
    if event_name == "complete":
        return CompleteAction()
    if event_name == "fail":
        return FailAction()
    if event_name == "move_to_pending_recovery":
        return MoveToPendingRecoveryAction()
    if event_name == "recover_stale_claim":
        return RecoverStaleClaimAction()
    if event_name == "reclaim_for_replay":
        return ReclaimForReplayAction()
    if event_name == "discard_recovery":
        return DiscardRecoveryAction()
    if event_name == "supersede_recovery":
        return SupersedeRecoveryAction()
    return None


def run_transport_event(
    model: TransportWorkflowModel,
    event_name: str,
    **kwargs: object,
) -> TransitionResult:
    """Run a transport event through the functional machine adapter."""

    if event_name not in _EVENT_NAMES:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )

    requesting_worker_id = str(kwargs.get("requesting_worker_id", model.requesting_worker_id) or "")
    action = _build_action(event_name, requesting_worker_id)
    if action is None:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )

    decision = decide_transport_action(
        TransportSnapshot(
            state=model.state,
            worker_id=model.worker_id,
            requesting_worker_id=requesting_worker_id,
            has_other_claimed_for_chat=model.has_other_claimed_for_chat,
            is_stale=model.is_stale,
        ),
        action,
    )
    if not decision.ok:
        disposition = {
            "other_claimed_for_chat": TransportDisposition.other_claimed_for_chat,
            "blocked_replay": TransportDisposition.blocked_replay,
            "guard_failed": TransportDisposition.guard_failed,
            "invalid_transition": TransportDisposition.invalid_transition,
        }.get(decision.status, TransportDisposition.invalid_transition)
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=disposition,
            reason=decision.reason,
        )

    if decision.effects.new_state is not None:
        model.state = decision.effects.new_state
    model.requesting_worker_id = requesting_worker_id
    if decision.effects.disposition is not None:
        model.disposition = decision.effects.disposition
    else:
        model.disposition = TransportDisposition.ok

    return TransitionResult(
        allowed=True,
        new_state=model.state,
        disposition=model.disposition,
        reason="",
    )
