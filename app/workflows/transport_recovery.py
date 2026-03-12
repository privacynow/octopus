"""Transport/recovery workflow: queued, claimed, pending_recovery, done, failed.

Library-backed: python-statemachine is the single source of truth for transition
legality. Repository owns SQL, idempotency, compare-and-update, and
already_handled. Machine callbacks are pure (no SQL, no I/O).
"""

from dataclasses import dataclass
from typing import Any

from statemachine import State
from statemachine import StateMachine
from statemachine.exceptions import TransitionNotAllowed

from app.workflows.results import (
    BlockedReplay,
    NotStaleClaim,
    OtherClaimedForChat,
    TransportDisposition,
    TransitionResult,
    TransportStateCorruption,
)

# ---------------------------------------------------------------------------
# States (must match work_items.state in DB)
# ---------------------------------------------------------------------------

TRANSPORT_STATES = frozenset({
    "queued",
    "claimed",
    "pending_recovery",
    "done",
    "failed",
})


# ---------------------------------------------------------------------------
# Domain model: machine input and callback host (mutable; machine writes state and disposition)
# ---------------------------------------------------------------------------


@dataclass
class TransportWorkflowModel:
    """Model for the transport StateMachine. Built from a work_items row + guard inputs.

    The machine reads/writes .state; validators/conditions read guard fields;
    actions (on=) set .disposition. No SQL or I/O in model methods.
    """

    state: str
    worker_id: str | None = None
    requesting_worker_id: str = ""
    has_other_claimed_for_chat: bool = False
    is_stale: bool = False
    disposition: TransportDisposition | None = None
    reason: str = ""

    # --- Conditions (used by machine cond=; return bool) ---

    def same_worker_reclaim(self) -> bool:
        """True if current item is claimed by the same worker requesting claim_inline."""
        return bool(
            self.worker_id
            and self.requesting_worker_id
            and self.worker_id == self.requesting_worker_id
        )

    def replay_claim_allowed(self) -> bool:
        """True if no other item for this chat is claimed (reclaim_for_replay allowed)."""
        return not self.has_other_claimed_for_chat

    # --- Validators (used by machine validators=; raise to block) ---

    def ensure_no_other_claimed(self) -> None:
        """Raise OtherClaimedForChat if another item for this chat is claimed."""
        if self.has_other_claimed_for_chat:
            raise OtherClaimedForChat("other_claimed_for_chat")

    def ensure_requester_for_claim(self) -> None:
        """Raise if claim_inline from queued is attempted without a requesting worker (ownership)."""
        if self.state == "queued" and not self.requesting_worker_id:
            raise OtherClaimedForChat("claim_inline requires requesting_worker_id")

    def ensure_no_other_worker_claiming(self) -> None:
        """Raise OtherClaimedForChat if item is claimed by a different worker or has no owner (claim_inline from claimed).

        claimed semantically requires an owner; ownerless claimed rows block claim_inline.
        """
        if self.state != "claimed" or not self.requesting_worker_id:
            return
        if not self.worker_id or self.worker_id != self.requesting_worker_id:
            raise OtherClaimedForChat("other_claimed_for_chat")

    def ensure_stale_claim(self) -> None:
        """Raise NotStaleClaim if the claim is not stale (recover_stale_claim guard)."""
        if not self.is_stale:
            raise NotStaleClaim("not_stale")

    def raise_blocked_replay(self) -> None:
        """Raise BlockedReplay (replay blocked by other claimed item)."""
        raise BlockedReplay("blocked_replay")

    # --- Actions (used by machine on=; set disposition) ---

    def mark_already_claimed(self) -> None:
        self.disposition = TransportDisposition.already_claimed_by_worker

    def mark_done(self) -> None:
        self.disposition = TransportDisposition.done

    def mark_failed(self) -> None:
        self.disposition = TransportDisposition.failed

    def mark_discarded(self) -> None:
        self.disposition = TransportDisposition.discarded

    def mark_superseded(self) -> None:
        self.disposition = TransportDisposition.superseded

    def mark_replayed(self) -> None:
        self.disposition = TransportDisposition.replayed

    def mark_stale_recovered(self) -> None:
        self.disposition = TransportDisposition.stale_recovered

    def mark_ok(self) -> None:
        self.disposition = TransportDisposition.ok


# ---------------------------------------------------------------------------
# Transport recovery StateMachine (python-statemachine 2.x)
# ---------------------------------------------------------------------------


class TransportRecoveryMachine(StateMachine, strict_states=True):
    """Transport/recovery workflow: single source of truth for transition legality.

    States: queued (initial), claimed, pending_recovery, done, failed (final).
    Instantiate with model=TransportWorkflowModel(…), rtc=True,
    allow_event_without_transition=False.
    """

    queued = State("Queued", value="queued", initial=True)
    claimed = State("Claimed", value="claimed")
    pending_recovery = State("PendingRecovery", value="pending_recovery")
    done = State("Done", value="done", final=True)
    failed = State("Failed", value="failed", final=True)

    # claim_inline: queued -> claimed (no other claimed, requester required), or claimed -> itself (same worker only)
    claim_inline = (
        claimed.to(claimed, cond="same_worker_reclaim", on="mark_already_claimed")
        | queued.to(
            claimed,
            validators=["ensure_no_other_claimed", "ensure_requester_for_claim"],
            on="mark_ok",
        )
        | claimed.to(
            claimed,
            validators=["ensure_no_other_claimed", "ensure_no_other_worker_claiming"],
        )
    )
    claim_worker = queued.to(claimed, validators="ensure_no_other_claimed", on="mark_ok")
    complete = (
        queued.to(done, on="mark_done")
        | claimed.to(done, on="mark_done")
    )
    fail = (
        queued.to(failed, on="mark_failed")
        | claimed.to(failed, on="mark_failed")
    )
    move_to_pending_recovery = claimed.to(pending_recovery, on="mark_ok")
    recover_stale_claim = claimed.to(
        queued, validators="ensure_stale_claim", on="mark_stale_recovered"
    )
    reclaim_for_replay = (
        pending_recovery.to(claimed, cond="replay_claim_allowed", on="mark_replayed")
        | pending_recovery.to(
            pending_recovery, validators="raise_blocked_replay"
        )
    )
    discard_recovery = pending_recovery.to(done, on="mark_discarded")
    supersede_recovery = pending_recovery.to(done, on="mark_superseded")

    # Delegations so the machine finds cond/validators on self and they use self.model
    def same_worker_reclaim(self) -> bool:
        return self.model.same_worker_reclaim()

    def replay_claim_allowed(self) -> bool:
        return self.model.replay_claim_allowed()

    def ensure_no_other_claimed(self) -> None:
        self.model.ensure_no_other_claimed()

    def ensure_requester_for_claim(self) -> None:
        self.model.ensure_requester_for_claim()

    def ensure_no_other_worker_claiming(self) -> None:
        self.model.ensure_no_other_worker_claiming()

    def ensure_stale_claim(self) -> None:
        self.model.ensure_stale_claim()

    def raise_blocked_replay(self) -> None:
        self.model.raise_blocked_replay()

    def mark_already_claimed(self) -> None:
        self.model.mark_already_claimed()

    def mark_done(self) -> None:
        self.model.mark_done()

    def mark_failed(self) -> None:
        self.model.mark_failed()

    def mark_discarded(self) -> None:
        self.model.mark_discarded()

    def mark_superseded(self) -> None:
        self.model.mark_superseded()

    def mark_replayed(self) -> None:
        self.model.mark_replayed()

    def mark_stale_recovered(self) -> None:
        self.model.mark_stale_recovered()

    def mark_ok(self) -> None:
        self.model.mark_ok()


# ---------------------------------------------------------------------------
# Thin adapter: run event, catch library/domain exceptions, return TransitionResult
# ---------------------------------------------------------------------------

_EVENT_METHODS: dict[str, str] = {
    "claim_inline": "claim_inline",
    "claim_worker": "claim_worker",
    "complete": "complete",
    "fail": "fail",
    "move_to_pending_recovery": "move_to_pending_recovery",
    "recover_stale_claim": "recover_stale_claim",
    "reclaim_for_replay": "reclaim_for_replay",
    "discard_recovery": "discard_recovery",
    "supersede_recovery": "supersede_recovery",
}


def run_transport_event(
    model: TransportWorkflowModel,
    event_name: str,
    **kwargs: Any,
) -> TransitionResult:
    """Run the given event on the transport machine. Pure adapter; no SQL.

    Sets model.requesting_worker_id from kwargs when present. Creates machine,
    calls the corresponding event method, catches TransitionNotAllowed and
    domain exceptions (OtherClaimedForChat, BlockedReplay, NotStaleClaim),
    returns TransitionResult. On success, model.state and model.disposition
    are updated by the machine.
    """
    if event_name not in _EVENT_METHODS:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )
    if model.state not in TRANSPORT_STATES:
        raise TransportStateCorruption(f"unknown state {model.state!r}")
    if kwargs:
        model.requesting_worker_id = kwargs.get("requesting_worker_id", model.requesting_worker_id) or ""

    machine = TransportRecoveryMachine(
        model=model,
        rtc=True,
        allow_event_without_transition=False,
    )
    method_name = _EVENT_METHODS[event_name]
    method = getattr(machine, method_name)

    try:
        method()
    except TransitionNotAllowed as e:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason=str(e) or f"no transition {event_name!r} from {model.state!r}",
        )
    except OtherClaimedForChat as e:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.other_claimed_for_chat,
            reason=e.args[0] if e.args else "other_claimed_for_chat",
        )
    except BlockedReplay as e:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.blocked_replay,
            reason=e.args[0] if e.args else "blocked_replay",
        )
    except NotStaleClaim as e:
        return TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.guard_failed,
            reason=e.args[0] if e.args else "not_stale",
        )
    # Success: model.state was updated by the machine; disposition set by on= actions
    new_state = model.state
    disposition = model.disposition
    if disposition is None:
        disposition = TransportDisposition.ok
    return TransitionResult(
        allowed=True,
        new_state=new_state,
        disposition=disposition,
        reason="",
    )
