"""Concern-owned use cases for recovery replay and discard workflows."""

from __future__ import annotations

from pathlib import Path

from app import user_messages as _msg
from app.recovery_port import (
    RecoveryActionOutcome,
    RecoveryReplayPlan,
    RecoveryPort,
)
from app import work_queue
from app.transports import factory
from app.transport import InboundMessage, deserialize_inbound
from app.workflows.results import TransportStateCorruption


class RecoveryUseCases(RecoveryPort):
    """Canonical replay/discard flows shared by surfaces."""

    def prepare_action(
        self,
        *,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        action: str,
        worker_id: str,
        ignore_claimed_item_id: str = "",
        config,
    ) -> RecoveryActionOutcome:
        try:
            recovery_item = work_queue.get_pending_recovery_for_update(
                data_dir,
                conversation_key,
                event_id,
            )
        except TransportStateCorruption:
            return RecoveryActionOutcome(
                status="error",
                toast_message=_msg.recovery_error_try_again(),
                show_alert=True,
            )
        if recovery_item is None:
            return RecoveryActionOutcome(
                status="already_handled",
                toast_message=_msg.recovery_already_handled(),
            )
        if action == "recovery_discard":
            try:
                discard_outcome = work_queue.discard_recovery(data_dir, recovery_item["id"])
            except TransportStateCorruption:
                return RecoveryActionOutcome(
                    status="error",
                    toast_message=_msg.recovery_error_try_again(),
                    show_alert=True,
                )
            if discard_outcome == work_queue.DiscardResult.already_handled:
                return RecoveryActionOutcome(
                    status="already_handled",
                    toast_message=_msg.recovery_already_handled(),
                )
            if discard_outcome == work_queue.DiscardResult.corruption:
                return RecoveryActionOutcome(
                    status="discard_error",
                    toast_message=_msg.recovery_error_discard_try_again(),
                )
            return RecoveryActionOutcome(
                status="discarded",
                toast_message=_msg.recovery_discarded_confirm(),
                edit_message=_msg.recovery_discarded_edit(),
            )
        if action != "recovery_replay":
            return RecoveryActionOutcome(
                status="invalid_action",
                toast_message=_msg.recovery_unknown_action(),
            )
        try:
            item = work_queue.reclaim_for_replay(
                data_dir,
                recovery_item["id"],
                worker_id,
                ignore_claimed_item_id=ignore_claimed_item_id,
            )
        except TransportStateCorruption:
            return RecoveryActionOutcome(
                status="error",
                toast_message=_msg.recovery_error_try_again(),
                show_alert=True,
            )
        except work_queue.ReclaimBlocked:
            return RecoveryActionOutcome(
                status="replay_blocked",
                edit_message=_msg.recovery_blocked_replay_edit(),
            )
        if item is None:
            return RecoveryActionOutcome(
                status="already_handled",
                edit_message=_msg.recovery_already_handled_edit(),
            )
        payload_str = item.get("payload") or work_queue.get_update_payload(data_dir, event_id)
        if not payload_str:
            work_queue.fail_work_item(data_dir, item["id"], error="payload_missing")
            return RecoveryActionOutcome(
                status="payload_missing",
                edit_message=_msg.recovery_payload_missing_edit(),
            )
        try:
            event = deserialize_inbound("message", payload_str)
        except Exception:
            work_queue.fail_work_item(data_dir, item["id"], error="deserialize_error")
            return RecoveryActionOutcome(
                status="deserialize_failed",
                edit_message=_msg.recovery_replay_failed_edit(),
            )
        if not isinstance(event, InboundMessage):
            work_queue.fail_work_item(data_dir, item["id"], error="not_message")
            return RecoveryActionOutcome(
                status="not_message",
                edit_message=_msg.recovery_replay_failed_edit(),
            )
        trust_tier = factory.trust_tier_for_source(
            getattr(event, "source", "telegram"),
            event.user,
            config=config,
        )
        return RecoveryActionOutcome(
            status="replay_ready",
            toast_message=_msg.recovery_replaying_toast(),
            edit_message=_msg.recovery_replaying_edit(),
            replay_plan=RecoveryReplayPlan(
                item_id=str(item["id"]),
                event=event,
                trust_tier=trust_tier,
            ),
        )

    def complete_replay(self, *, data_dir: Path, item_id: str) -> None:
        work_queue.complete_work_item(data_dir, item_id)

    def fail_replay(self, *, data_dir: Path, item_id: str, error: str = "replay_failed") -> None:
        work_queue.fail_work_item(data_dir, item_id, error=error)


_USE_CASES = RecoveryUseCases()


def get_recovery_use_cases() -> RecoveryUseCases:
    return _USE_CASES
