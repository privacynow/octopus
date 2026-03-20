"""Lifecycle rules for control-plane commands."""

from __future__ import annotations

from dataclasses import dataclass

from statemachine import State, StateMachine

CONTROL_COMMAND_STATES = frozenset(
    {
        "pending",
        "claimed",
        "completed",
        "failed",
        "dead_letter",
    }
)


@dataclass(frozen=True)
class ControlCommandSnapshot:
    state: str
    retry_count: int = 0
    max_retries: int = 3
    lease_expired: bool = False


@dataclass(frozen=True)
class ControlCommandDecision:
    ok: bool
    new_state: str
    retry_count: int
    reason: str = ""


class _ControlCommandLifecycle(StateMachine):
    pending = State(initial=True)
    claimed = State()
    completed = State(final=True)
    failed = State()
    dead_letter = State(final=True)

    claim = pending.to(claimed)
    complete = claimed.to(completed)
    record_failure = claimed.to(failed)
    retry = failed.to(pending, cond="has_retry_capacity") | failed.to(
        dead_letter,
        unless="has_retry_capacity",
    )
    reclaim_expired = claimed.to(pending, cond="lease_has_expired")
    reject = pending.to(dead_letter) | claimed.to(dead_letter) | failed.to(dead_letter)

    def __init__(self, snapshot: ControlCommandSnapshot) -> None:
        self._snapshot = snapshot
        super().__init__(start_value=snapshot.state)

    def has_retry_capacity(self) -> bool:
        return self._snapshot.retry_count < self._snapshot.max_retries

    def lease_has_expired(self) -> bool:
        return self._snapshot.lease_expired


def run_control_command_event(
    snapshot: ControlCommandSnapshot,
    event_name: str,
) -> ControlCommandDecision:
    if snapshot.state not in CONTROL_COMMAND_STATES:
        raise ValueError(f"unknown control-plane command state {snapshot.state!r}")

    machine = _ControlCommandLifecycle(snapshot)
    event = getattr(machine, event_name, None)
    if event is None:
        raise ValueError(f"unknown control-plane command event {event_name!r}")
    try:
        event()
    except Exception as exc:
        return ControlCommandDecision(
            ok=False,
            new_state=snapshot.state,
            retry_count=snapshot.retry_count,
            reason=str(exc),
        )

    retry_count = snapshot.retry_count
    if event_name in {"retry", "reclaim_expired"} and machine.current_state.id == "pending":
        retry_count += 1
    return ControlCommandDecision(
        ok=True,
        new_state=machine.current_state.id,
        retry_count=retry_count,
    )
