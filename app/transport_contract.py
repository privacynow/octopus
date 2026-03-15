"""Shared transport types and row validation. Used by work_queue facade and SQLite/Postgres backends."""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.workflows.results import TransportStateCorruption
from app.workflows.transport_recovery import TRANSPORT_STATES


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


def validate_work_item_row(row: dict[str, Any], item_id: str = "") -> None:
    """Raise TransportStateCorruption if row violates transport invariants."""
    state = row.get("state")
    if state not in TRANSPORT_STATES:
        raise TransportStateCorruption(
            f"unknown state {state!r}" + (f" for item {item_id}" if item_id else "")
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


# Backend modules expect this name
_validate_work_item_row = validate_work_item_row
