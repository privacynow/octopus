import pytest

from app import work_queue
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.runtime.inbound_types import InboundUser
from app.runtime.work_admission import admit_worker_message
from app.workflows.recovery.replay import get_recovery_use_cases
from tests.support.handler_support import (
    current_runtime,
    fresh_env,
)


def test_admit_worker_message_fails_unauthorized_telegram_item() -> None:
    with fresh_env(config_overrides={"allowed_user_ids": frozenset()}) as (data_dir, _cfg, _prov):
        _, item_id = work_queue.record_and_enqueue(
            data_dir,
            telegram_event_id(8101),
            telegram_conversation_key(12345),
            telegram_actor_key(42),
            "message",
            payload='{"text": "blocked"}',
        )
        work_queue.set_user_access(
            data_dir,
            actor_key=telegram_actor_key(42),
            access="blocked",
            reason="blocked for test",
            granted_by=telegram_actor_key(1),
        )

        result = admit_worker_message(
            data_dir=data_dir,
            item_id=item_id,
            source="telegram",
            user=InboundUser(id=telegram_actor_key(42), username="blocked"),
            config=current_runtime().config,
        )

        row = work_queue.debug_transport_connection(data_dir).execute(
            "SELECT state, error FROM work_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        assert result.allowed is False
        assert result.status == "not_allowed"
        assert row["state"] == "failed"
        assert row["error"] == "not_allowed"


def test_admit_worker_message_allows_registry_input() -> None:
    with fresh_env() as (data_dir, _cfg, _prov):
        result = admit_worker_message(
            data_dir=data_dir,
            item_id="registry-item",
            source="registry",
            user=InboundUser(id="registry:actor", username="registry"),
            config=current_runtime().config,
        )

        assert result.allowed is True
        assert result.status == "allowed"
        assert result.trust_tier == "trusted"


@pytest.mark.asyncio
async def test_recovery_workflow_binds_and_sends_notice_before_marking_pending_recovery() -> None:
    with fresh_env() as (data_dir, _cfg, _prov):
        _, item_id = work_queue.record_and_enqueue(
            data_dir,
            telegram_event_id(8102),
            telegram_conversation_key(12345),
            telegram_actor_key(42),
            "message",
            payload='{"text": "recover me"}',
        )
        conn = work_queue.debug_transport_connection(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = ?, claimed_at = ? WHERE id = ?",
            ("test", "2025-01-01T00:00:00+00:00", item_id),
        )
        conn.commit()

        calls: list[str] = []

        async def bind_egress() -> None:
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            calls.append(f"bind:{row['state']}")

        async def send_notice(notice) -> None:
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            calls.append(f"send:{row['state']}")
            assert notice.update_id == 8102
            assert "recover me" in notice.preview

        result = await get_recovery_use_cases().dispatch_worker_recovery(
            data_dir=data_dir,
            item_id=item_id,
            original_text="recover me",
            update_id=8102,
            bind_egress=bind_egress,
            send_notice=send_notice,
        )

        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        assert result.status == "pending_recovery"
        assert calls == ["bind:claimed", "send:claimed"]
        assert row["state"] == "pending_recovery"
