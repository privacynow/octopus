"""Formal routed-task lifecycle validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
