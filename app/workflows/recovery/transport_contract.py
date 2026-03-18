"""Shared recovery transport types and row validation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.workflows.recovery.machine import TRANSPORT_STATES
from app.workflows.recovery.results import TransportStateCorruption


class LeaveClaimed(Exception):
    """Control-flow signal: leave the current claimed work item unreconciled."""


class PendingRecovery(Exception):
    """Control-flow signal: item transitioned to pending_recovery."""


class ReclaimBlocked(Exception):
    """The item exists in pending_recovery but cannot be reclaimed."""


class DiscardResult(str, Enum):
    success = "success"
    already_handled = "already_handled"
    corruption = "corruption"


class ApplyResult(str, Enum):
    success = "success"
    already_handled = "already_handled"
    workflow_rejected = "workflow_rejected"
    corruption = "corruption"


class CancelRequestResult(str, Enum):
    queued_cancelled = "queued_cancelled"
    claimed_cancel_requested = "claimed_cancel_requested"
    nothing_to_cancel = "nothing_to_cancel"


def validate_work_item_row(row: dict[str, Any], item_id: str = "") -> None:
    """Raise TransportStateCorruption if row violates transport invariants."""

    state = row.get("state")
    if state not in TRANSPORT_STATES:
        raise TransportStateCorruption(
            f"unknown state {state!r}" + (f" for item {item_id}" if item_id else "")
        )
    dispatch_mode = row.get("dispatch_mode")
    if dispatch_mode not in ("fresh", "recovery"):
        raise TransportStateCorruption(
            "work item row must have dispatch_mode in ('fresh', 'recovery')"
            + (f" (item {item_id})" if item_id else "")
        )
    if state == "claimed":
        if row.get("worker_id") is None:
            raise TransportStateCorruption(
                "claimed row must have worker_id" + (f" (item {item_id})" if item_id else "")
            )
        if row.get("claimed_at") is None:
            raise TransportStateCorruption(
                "claimed row must have claimed_at" + (f" (item {item_id})" if item_id else "")
            )


_validate_work_item_row = validate_work_item_row
