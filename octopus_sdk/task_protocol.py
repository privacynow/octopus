"""Formal routed-task lifecycle validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from statemachine import State, StateMachine

TaskActorRole = Literal["operator", "origin_bot", "target_bot", "system"]
RoutedTaskStatus = Literal[
    "queued",
    "leased",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
]
TaskTransition = Literal[
    "lease",
    "start",
    "progress",
    "complete",
    "fail",
    "cancel",
    "time_out",
]
DelegatedTaskStatus = Literal[
    "pending",
    "proposed",
    "submitted",
    "queued",
    "leased",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
]
PendingDelegationStatus = Literal[
    "proposed",
    "submitted",
    "completed",
    "partial_failed",
    "cancelled",
]
PendingDelegationTransition = Literal["sync_children", "cancel"]

ROUTED_TASK_STATES = frozenset(
    {
        "queued",
        "leased",
        "running",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
    }
)
DELEGATED_TASK_STATES = frozenset({"pending", "proposed", "submitted", *ROUTED_TASK_STATES})
DELEGATED_TASK_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timed_out"})
DELEGATED_TASK_ACTIVE_STATES = frozenset({"pending", "proposed", "submitted", "queued", "leased", "running"})
PENDING_DELEGATION_STATES = frozenset({"proposed", "submitted", "completed", "partial_failed", "cancelled"})
PENDING_DELEGATION_TERMINAL_STATES = frozenset({"completed", "partial_failed", "cancelled"})

_ROUTED_ALLOWED_NEXT_STATES = {
    "queued": frozenset({"queued", "leased", "completed", "failed", "cancelled", "timed_out"}),
    "leased": frozenset({"leased", "running", "completed", "failed", "cancelled", "timed_out"}),
    "running": frozenset({"running", "completed", "failed", "cancelled", "timed_out"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
    "timed_out": frozenset({"timed_out"}),
}
_PRE_ROUTED_ALLOWED_NEXT_STATES = {
    "pending": frozenset({"pending", "submitted", *ROUTED_TASK_STATES}),
    "proposed": frozenset({"proposed", "submitted", *ROUTED_TASK_STATES}),
    "submitted": frozenset({"submitted", *ROUTED_TASK_STATES}),
}
_PENDING_ALLOWED_NEXT_STATES = {
    "proposed": frozenset({"proposed", "submitted", "completed", "partial_failed", "cancelled"}),
    "submitted": frozenset({"submitted", "completed", "partial_failed"}),
    "completed": frozenset({"completed"}),
    "partial_failed": frozenset({"partial_failed"}),
    "cancelled": frozenset({"cancelled"}),
}


@dataclass(frozen=True)
class RoutedTaskSnapshot:
    status: str
    queued_at: str = ""
    leased_at: str = ""
    started_at: str = ""
    deadline_at: str = ""
    completed_at: str = ""
    failed_at: str = ""
    cancelled_at: str = ""
    last_transition_id: str = ""
    version: int = 0


@dataclass(frozen=True)
class TaskTransitionRequest:
    transition: TaskTransition
    actor_role: TaskActorRole
    transition_id: str
    occurred_at: str
    progress: int | None = None


@dataclass(frozen=True)
class TaskTransitionResult:
    ok: bool
    old_state: str
    new_state: str
    reason: str = ""
    duplicate: bool = False
    new_version: int = 0


@dataclass(frozen=True)
class PendingDelegationSnapshot:
    status: str
    task_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingDelegationTransitionRequest:
    transition: PendingDelegationTransition
    task_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingDelegationTransitionResult:
    ok: bool
    old_state: str
    new_state: str
    reason: str = ""

    @property
    def ready_to_resume(self) -> bool:
        return delegation_ready_to_resume(self.new_state)


def normalize_pending_delegation_status(status: str) -> str:
    text = (status or "").strip().lower()
    return text or "proposed"


def normalize_delegated_task_status(status: str) -> str:
    text = (status or "").strip().lower()
    return text or "proposed"


def derive_pending_delegation_status(task_statuses: Iterable[str]) -> PendingDelegationStatus:
    statuses = [normalize_delegated_task_status(status) for status in task_statuses]
    if not statuses:
        return "proposed"
    if all(status in DELEGATED_TASK_TERMINAL_STATES for status in statuses):
        if any(status != "completed" for status in statuses):
            return "partial_failed"
        return "completed"
    if any(status in DELEGATED_TASK_ACTIVE_STATES for status in statuses):
        return "submitted"
    return "proposed"


def delegation_ready_to_resume(status: str) -> bool:
    return normalize_pending_delegation_status(status) in {"completed", "partial_failed"}


def apply_pending_delegation_transition(
    snapshot: PendingDelegationSnapshot,
    request: PendingDelegationTransitionRequest,
) -> PendingDelegationTransitionResult:
    current = normalize_pending_delegation_status(snapshot.status)
    if current not in PENDING_DELEGATION_STATES:
        raise ValueError(f"unknown pending delegation state {snapshot.status!r}")
    if request.transition == "sync_children":
        target = derive_pending_delegation_status(
            request.task_statuses or snapshot.task_statuses
        )
    elif request.transition == "cancel":
        target = "cancelled"
    else:
        raise ValueError(f"unknown pending delegation transition {request.transition!r}")
    if target not in _PENDING_ALLOWED_NEXT_STATES[current]:
        return PendingDelegationTransitionResult(
            ok=False,
            old_state=current,
            new_state=current,
            reason=f"{current} cannot transition to {target}",
        )
    return PendingDelegationTransitionResult(
        ok=True,
        old_state=current,
        new_state=target,
    )


def validate_delegated_task_transition(current_status: str, next_status: str) -> TaskTransitionResult:
    current = normalize_delegated_task_status(current_status)
    target = normalize_delegated_task_status(next_status)
    if current not in DELEGATED_TASK_STATES:
        raise ValueError(f"unknown delegated-task state {current_status!r}")
    if target not in DELEGATED_TASK_STATES:
        raise ValueError(f"unknown delegated-task state {next_status!r}")
    if current in _PRE_ROUTED_ALLOWED_NEXT_STATES:
        allowed = _PRE_ROUTED_ALLOWED_NEXT_STATES[current]
    else:
        allowed = _ROUTED_ALLOWED_NEXT_STATES[current]
    if target not in allowed:
        return TaskTransitionResult(
            ok=False,
            old_state=current,
            new_state=current,
            reason=f"{current} cannot transition to {target}",
        )
    return TaskTransitionResult(
        ok=True,
        old_state=current,
        new_state=target,
    )


class _TaskLifecycle(StateMachine):
    queued = State(initial=True)
    leased = State()
    running = State()
    completed = State(final=True)
    failed = State(final=True)
    cancelled = State(final=True)
    timed_out = State(final=True)

    lease = queued.to(leased, cond="actor_can_lease")
    start = leased.to(running, cond="actor_is_target")
    progress = running.to.itself(cond="actor_is_target")
    complete = (
        queued.to(completed, cond="actor_can_complete")
        | leased.to(completed, cond="actor_can_complete")
        | running.to(completed, cond="actor_can_complete")
    )
    fail = (
        queued.to(failed, cond="actor_can_fail")
        | leased.to(failed, cond="actor_can_fail")
        | running.to(failed, cond="actor_can_fail")
    )
    cancel = (
        queued.to(cancelled, cond="actor_can_cancel")
        | leased.to(cancelled, cond="actor_can_cancel")
        | running.to(cancelled, cond="actor_can_cancel")
    )
    time_out = (
        queued.to(timed_out, cond="can_time_out")
        | leased.to(timed_out, cond="can_time_out")
        | running.to(timed_out, cond="can_time_out")
    )

    def __init__(self, snapshot: RoutedTaskSnapshot, request: TaskTransitionRequest) -> None:
        self._snapshot = snapshot
        self._request = request
        super().__init__(start_value=snapshot.status)

    def actor_is_target(self) -> bool:
        return self._request.actor_role == "target_bot"

    def actor_is_system(self) -> bool:
        return self._request.actor_role == "system"

    def actor_can_lease(self) -> bool:
        return self._request.actor_role in {"target_bot", "system"}

    def actor_can_cancel(self) -> bool:
        return self._request.actor_role in {"operator", "origin_bot", "system"}

    def actor_can_fail(self) -> bool:
        return self._request.actor_role in {"target_bot", "system"}

    def actor_can_complete(self) -> bool:
        return self._request.actor_role in {"target_bot", "system"}

    def is_expired(self) -> bool:
        deadline = (self._snapshot.deadline_at or "").strip()
        if not deadline:
            return False
        return deadline <= self._request.occurred_at

    def can_time_out(self) -> bool:
        if self._request.actor_role == "target_bot":
            return True
        return self.actor_is_system() and self.is_expired()


def apply_task_transition(
    snapshot: RoutedTaskSnapshot,
    request: TaskTransitionRequest,
) -> TaskTransitionResult:
    if snapshot.status not in ROUTED_TASK_STATES:
        raise ValueError(f"unknown routed-task state {snapshot.status!r}")
    if snapshot.last_transition_id and snapshot.last_transition_id == request.transition_id:
        return TaskTransitionResult(
            ok=True,
            old_state=snapshot.status,
            new_state=snapshot.status,
            duplicate=True,
            new_version=snapshot.version,
        )
    machine = _TaskLifecycle(snapshot, request)
    event = getattr(machine, request.transition, None)
    if event is None:
        raise ValueError(f"unknown task transition {request.transition!r}")
    try:
        event()
    except Exception as exc:
        return TaskTransitionResult(
            ok=False,
            old_state=snapshot.status,
            new_state=snapshot.status,
            reason=str(exc),
            new_version=snapshot.version,
        )
    return TaskTransitionResult(
        ok=True,
        old_state=snapshot.status,
        new_state=machine.current_state.id,
        new_version=snapshot.version + 1,
    )
