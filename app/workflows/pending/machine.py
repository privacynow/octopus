"""Functional decision machine for pending approval/retry progression."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PendingRequestDisposition(str, Enum):
    """Classification of pending-request transition outcomes."""

    ok = "ok"
    executed = "executed"
    rejected = "rejected"
    expired = "expired"
    invalidated = "invalidated"
    cancelled = "cancelled"
    invalid_transition = "invalid_transition"
    guard_failed = "guard_failed"


PENDING_REQUEST_STATES = frozenset({"none", "pending_approval", "pending_retry"})


@dataclass
class PendingRequestWorkflowModel:
    """Mutable workflow model consumed by the adapter."""

    state: str
    validation_result: str = "ok"
    disposition: PendingRequestDisposition | None = None


@dataclass(frozen=True)
class PendingRequestSnapshot:
    state: str
    validation_result: str = "ok"


@dataclass(frozen=True)
class PendingRequestEffects:
    new_state: str | None = None
    disposition: PendingRequestDisposition | None = None


@dataclass(frozen=True)
class PendingRequestDecision:
    status: str
    ok: bool
    effects: PendingRequestEffects = PendingRequestEffects()
    reason: str = ""


@dataclass(frozen=True)
class PendingRequestTransitionResult:
    """Public transition result used by workflows."""

    allowed: bool
    new_state: str | None
    disposition: PendingRequestDisposition
    reason: str = ""


@dataclass(frozen=True)
class CreateApprovalAction:
    pass


@dataclass(frozen=True)
class CreateRetryAction:
    pass


@dataclass(frozen=True)
class ApproveExecuteAction:
    validation_result: str = "ok"


@dataclass(frozen=True)
class RejectAction:
    pass


@dataclass(frozen=True)
class ExpireAction:
    validation_result: str = "ok"


@dataclass(frozen=True)
class InvalidateStaleAction:
    validation_result: str = "ok"


@dataclass(frozen=True)
class CancelAction:
    pass


@dataclass(frozen=True)
class ClearAfterExecutionAction:
    pass


PendingRequestAction = (
    CreateApprovalAction
    | CreateRetryAction
    | ApproveExecuteAction
    | RejectAction
    | ExpireAction
    | InvalidateStaleAction
    | CancelAction
    | ClearAfterExecutionAction
)


def decide_pending_request_action(
    snapshot: PendingRequestSnapshot,
    action: PendingRequestAction,
) -> PendingRequestDecision:
    state = snapshot.state

    if state not in PENDING_REQUEST_STATES:
        return PendingRequestDecision(
            status="invalid_state",
            ok=False,
            reason=f"unknown state {state!r}",
        )

    if isinstance(action, CreateApprovalAction):
        if state != "none":
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'create_approval' from {state!r}",
            )
        return PendingRequestDecision(
            status="created_approval",
            ok=True,
            effects=PendingRequestEffects(
                new_state="pending_approval",
                disposition=PendingRequestDisposition.ok,
            ),
        )

    if isinstance(action, CreateRetryAction):
        if state != "none":
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'create_retry' from {state!r}",
            )
        return PendingRequestDecision(
            status="created_retry",
            ok=True,
            effects=PendingRequestEffects(
                new_state="pending_retry",
                disposition=PendingRequestDisposition.ok,
            ),
        )

    if isinstance(action, ApproveExecuteAction):
        if state not in {"pending_approval", "pending_retry"}:
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'approve_execute' from {state!r}",
            )
        if action.validation_result != "ok":
            return PendingRequestDecision(
                status="guard_failed",
                ok=False,
                reason=f"approve_execute requires validation_result='ok' (got {action.validation_result!r})",
            )
        return PendingRequestDecision(
            status="executed",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.executed,
            ),
        )

    if isinstance(action, RejectAction):
        if state not in {"pending_approval", "pending_retry"}:
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'reject' from {state!r}",
            )
        return PendingRequestDecision(
            status="rejected",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.rejected,
            ),
        )

    if isinstance(action, ExpireAction):
        if state not in {"pending_approval", "pending_retry"}:
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'expire' from {state!r}",
            )
        if action.validation_result != "expired":
            return PendingRequestDecision(
                status="guard_failed",
                ok=False,
                reason=f"expire requires validation_result='expired' (got {action.validation_result!r})",
            )
        return PendingRequestDecision(
            status="expired",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.expired,
            ),
        )

    if isinstance(action, InvalidateStaleAction):
        if state not in {"pending_approval", "pending_retry"}:
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'invalidate_stale' from {state!r}",
            )
        if action.validation_result != "context_changed":
            return PendingRequestDecision(
                status="guard_failed",
                ok=False,
                reason=(
                    "invalidate_stale requires validation_result='context_changed' "
                    f"(got {action.validation_result!r})"
                ),
            )
        return PendingRequestDecision(
            status="invalidated",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.invalidated,
            ),
        )

    if isinstance(action, CancelAction):
        if state not in {"pending_approval", "pending_retry"}:
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'cancel' from {state!r}",
            )
        return PendingRequestDecision(
            status="cancelled",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.cancelled,
            ),
        )

    if isinstance(action, ClearAfterExecutionAction):
        if state != "none":
            return PendingRequestDecision(
                status="invalid_transition",
                ok=False,
                reason=f"no transition 'clear_after_execution' from {state!r}",
            )
        return PendingRequestDecision(
            status="cleared",
            ok=True,
            effects=PendingRequestEffects(
                new_state="none",
                disposition=PendingRequestDisposition.ok,
            ),
        )

    raise ValueError(f"Unknown pending-request action: {action!r}")


_EVENT_NAMES = frozenset(
    {
        "create_approval",
        "create_retry",
        "approve_execute",
        "reject",
        "expire",
        "invalidate_stale",
        "cancel",
        "clear_after_execution",
    }
)


def _build_action(event_name: str, validation_result: str) -> PendingRequestAction | None:
    if event_name == "create_approval":
        return CreateApprovalAction()
    if event_name == "create_retry":
        return CreateRetryAction()
    if event_name == "approve_execute":
        return ApproveExecuteAction(validation_result=validation_result)
    if event_name == "reject":
        return RejectAction()
    if event_name == "expire":
        return ExpireAction(validation_result=validation_result)
    if event_name == "invalidate_stale":
        return InvalidateStaleAction(validation_result=validation_result)
    if event_name == "cancel":
        return CancelAction()
    if event_name == "clear_after_execution":
        return ClearAfterExecutionAction()
    return None


def run_pending_request_event(
    model: PendingRequestWorkflowModel,
    event_name: str,
    **kwargs: object,
) -> PendingRequestTransitionResult:
    """Run a pending-request event through the functional machine adapter."""

    if event_name not in _EVENT_NAMES:
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=PendingRequestDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )

    validation_result = str(kwargs.get("validation_result", model.validation_result))
    action = _build_action(event_name, validation_result)
    if action is None:
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=PendingRequestDisposition.invalid_transition,
            reason=f"unknown event {event_name!r}",
        )

    decision = decide_pending_request_action(
        PendingRequestSnapshot(state=model.state, validation_result=validation_result),
        action,
    )
    if not decision.ok:
        disposition = (
            PendingRequestDisposition.invalid_transition
            if decision.status in {"invalid_transition", "invalid_state"}
            else PendingRequestDisposition.guard_failed
        )
        return PendingRequestTransitionResult(
            allowed=False,
            new_state=None,
            disposition=disposition,
            reason=decision.reason,
        )

    if decision.effects.new_state is not None:
        model.state = decision.effects.new_state
    if decision.effects.disposition is not None:
        model.disposition = decision.effects.disposition
    else:
        model.disposition = PendingRequestDisposition.ok
    model.validation_result = validation_result

    return PendingRequestTransitionResult(
        allowed=True,
        new_state=model.state,
        disposition=model.disposition,
        reason="",
    )
