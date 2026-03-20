from __future__ import annotations

import pytest

from app.control_plane.machine import (
    ControlCommandSnapshot,
    run_control_command_event,
)


def test_control_command_machine_claims_pending_command() -> None:
    decision = run_control_command_event(
        ControlCommandSnapshot(state="pending"),
        "claim",
    )

    assert decision.ok is True
    assert decision.new_state == "claimed"
    assert decision.retry_count == 0


def test_control_command_machine_completes_claimed_command() -> None:
    decision = run_control_command_event(
        ControlCommandSnapshot(state="claimed"),
        "complete",
    )

    assert decision.ok is True
    assert decision.new_state == "completed"


def test_control_command_machine_records_claimed_failure_before_retry() -> None:
    decision = run_control_command_event(
        ControlCommandSnapshot(state="claimed"),
        "record_failure",
    )

    assert decision.ok is True
    assert decision.new_state == "failed"
    assert decision.retry_count == 0


def test_control_command_machine_retries_failed_command_when_capacity_remains() -> None:
    decision = run_control_command_event(
        ControlCommandSnapshot(state="failed", retry_count=1, max_retries=3),
        "retry",
    )

    assert decision.ok is True
    assert decision.new_state == "pending"
    assert decision.retry_count == 2


def test_control_command_machine_dead_letters_failed_command_when_retry_budget_spent() -> None:
    decision = run_control_command_event(
        ControlCommandSnapshot(state="failed", retry_count=3, max_retries=3),
        "retry",
    )

    assert decision.ok is True
    assert decision.new_state == "dead_letter"
    assert decision.retry_count == 3


def test_control_command_machine_reclaims_only_expired_claims() -> None:
    allowed = run_control_command_event(
        ControlCommandSnapshot(state="claimed", retry_count=0, max_retries=3, lease_expired=True),
        "reclaim_expired",
    )
    blocked = run_control_command_event(
        ControlCommandSnapshot(state="claimed", retry_count=0, max_retries=3, lease_expired=False),
        "reclaim_expired",
    )

    assert allowed.ok is True
    assert allowed.new_state == "pending"
    assert allowed.retry_count == 1
    assert blocked.ok is False
    assert blocked.new_state == "claimed"


def test_control_command_machine_rejects_unknown_state() -> None:
    with pytest.raises(ValueError, match="unknown control-plane command state"):
        run_control_command_event(ControlCommandSnapshot(state="mystery"), "claim")
