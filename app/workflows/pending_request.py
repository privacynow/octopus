"""Pending approval/retry workflow (Phase 11, second extraction).

States: none, pending_approval, pending_retry. Terminal outcomes via
disposition (executed, rejected, expired, invalidated, cancelled).
Library-backed: python-statemachine is the single source of truth for
transition legality. Session persistence stays in handlers/storage.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from statemachine import State
from statemachine import StateMachine
from statemachine.exceptions import TransitionNotAllowed


# ---------------------------------------------------------------------------
# Disposition and result (pending-request-specific)
# ---------------------------------------------------------------------------

class PendingRequestDisposition(str, Enum):
    """Classification of pending-request transition outcomes."""
    ok = "ok"
    executed = "executed"
    rejected = "rejected"
    expired = "expired"
    invalidated = "invalidated"  # context changed (stale)
    cancelled = "cancelled"
    invalid_transition = "invalid_transition"
    guard_failed = "guard_failed"


@dataclass(frozen=True)
class PendingRequestTransitionResult:
    """Result of asking the pending-request machine to validate a transition."""
    allowed: bool
    new_state: str | None
    disposition: PendingRequestDisposition
    reason: str = ""


# ---------------------------------------------------------------------------
# Domain model: machine input (mutable; machine writes state and disposition)
# ---------------------------------------------------------------------------

PENDING_REQUEST_STATES = frozenset({"none", "pending_approval", "pending_retry"})


@dataclass
class PendingRequestWorkflowModel:
    """Model for the pending-request StateMachine.

    state: none | pending_approval | pending_retry.
    validation_result: "ok" | "expired" | "context_changed" — set by caller
    before approve_execute / expire / invalidate_stale.
    """

    state: str
    validation_result: str = "ok"  # ok | expired | context_changed
    disposition: PendingRequestDisposition | None = None

    def validation_ok(self) -> bool:
        return self.validation_result == "ok"

    def is_expired(self) -> bool:
        return self.validation_result == "expired"

    def is_context_stale(self) -> bool:
        return self.validation_result == "context_changed"

    def mark_executed(self) -> None:
        self.disposition = PendingRequestDisposition.executed

    def mark_rejected(self) -> None:
        self.disposition = PendingRequestDisposition.rejected

    def mark_expired(self) -> None:
        self.disposition = PendingRequestDisposition.expired

    def mark_invalidated(self) -> None:
        self.disposition = PendingRequestDisposition.invalidated

    def mark_cancelled(self) -> None:
        self.disposition = PendingRequestDisposition.cancelled

    def mark_ok(self) -> None:
        self.disposition = PendingRequestDisposition.ok


# ---------------------------------------------------------------------------
# Pending request StateMachine (python-statemachine 2.x)
# ---------------------------------------------------------------------------

class PendingRequestMachine(StateMachine, strict_states=True):
    """Pending approval/retry workflow: single source of truth for transition legality.

    States: none (initial), pending_approval, pending_retry.
    Instantiate with model=PendingRequestWorkflowModel(...), rtc=True,
    allow_event_without_transition=False.
    """

    none = State("None", value="none", initial=True)
    pending_approval = State("PendingApproval", value="pending_approval")
    pending_retry = State("PendingRetry", value="pending_retry")

    create_approval = none.to(pending_approval, on="mark_ok")
    create_retry = none.to(pending_retry, on="mark_ok")

    approve_execute = (
        pending_approval.to(none, cond="validation_ok", on="mark_executed")
        | pending_retry.to(none, cond="validation_ok", on="mark_executed")
    )
    reject = (
        pending_approval.to(none, on="mark_rejected")
        | pending_retry.to(none, on="mark_rejected")
    )
    expire = (
        pending_approval.to(none, cond="is_expired", on="mark_expired")
        | pending_retry.to(none, cond="is_expired", on="mark_expired")
    )
    invalidate_stale = (
        pending_approval.to(none, cond="is_context_stale", on="mark_invalidated")
        | pending_retry.to(none, cond="is_context_stale", on="mark_invalidated")
    )
    cancel = (
        pending_approval.to(none, on="mark_cancelled")
        | pending_retry.to(none, on="mark_cancelled")
    )
    clear_after_execution = none.to(none, on="mark_ok")  # no-op from none

    def validation_ok(self) -> bool:
        return self.model.validation_ok()

    def is_expired(self) -> bool:
        return self.model.is_expired()

    def is_context_stale(self) -> bool:
        return self.model.is_context_stale()

    def mark_executed(self) -> None:
        self.model.mark_executed()

    def mark_rejected(self) -> None:
        self.model.mark_rejected()

    def mark_expired(self) -> None:
        self.model.mark_expired()

    def mark_invalidated(self) -> None:
        self.model.mark_invalidated()

    def mark_cancelled(self) -> None:
        self.model.mark_cancelled()

    def mark_ok(self) -> None:
        self.model.mark_ok()


# ---------------------------------------------------------------------------
# Adapter: run event, catch TransitionNotAllowed, return PendingRequestTransitionResult
# ---------------------------------------------------------------------------

_PENDING_EVENT_METHODS = frozenset({
    "create_approval", "create_retry", "approve_execute", "reject",
    "expire", "invalidate_stale", "cancel", "clear_after_execution",
})


def run_pending_request_event(
    model: PendingRequestWorkflowModel,
    event_name: str,
    **kwargs: Any,
) -> PendingRequestTransitionResult:
    """Run the given event on the pending-request machine. Pure adapter; no I/O.

    Caller sets model.validation_result before approve_execute / expire / invalidate_stale.
    Returns PendingRequestTransitionResult. On success, model.state and model.disposition
    are updated by the machine.
    """
    if event_name not in _PENDING_EVENT_METHODS:
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=PendingRequestDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )
    if model.state not in PENDING_REQUEST_STATES:
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=PendingRequestDisposition.invalid_transition,
            reason=f"unknown state {model.state!r}",
        )
    if kwargs:
        model.validation_result = kwargs.get("validation_result", model.validation_result)

    machine = PendingRequestMachine(
        model=model,
        rtc=True,
        allow_event_without_transition=False,
    )
    method = getattr(machine, event_name)

    try:
        method()
    except TransitionNotAllowed as e:
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=PendingRequestDisposition.guard_failed,
            reason=str(e) or f"no transition {event_name!r} from {model.state!r}",
        )
    new_state = model.state
    disposition = model.disposition
    if disposition is None:
        disposition = PendingRequestDisposition.ok
    return PendingRequestTransitionResult(
        allowed=True,
        new_state=new_state,
        disposition=disposition,
        reason="",
    )
