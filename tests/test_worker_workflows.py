from types import SimpleNamespace

import pytest

from app import work_queue
from app.agents.bridge import telegram_conversation_ref
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import registry_conversation_ref
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.runtime.inbound_types import InboundMessage, InboundUser
from app.runtime.work_admission import admit_worker_message
from app.workflows.recovery.replay import get_recovery_use_cases
import app.channels.telegram.worker as telegram_worker
from tests.support.config_support import make_registry_connection
from tests.support.handler_support import (
    current_execution_runtime,
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
            conversation_ref=telegram_conversation_ref(current_runtime().config, 12345),
            user=InboundUser(id=telegram_actor_key(42), username="blocked"),
            config=current_runtime().config,
            dispatcher=current_runtime().channel_dispatcher,
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
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, _cfg, _prov):
        result = admit_worker_message(
            data_dir=data_dir,
            item_id="registry-item",
            conversation_ref=registry_conversation_ref("default", "conv-1"),
            user=InboundUser(id="registry:actor", username="registry"),
            config=current_runtime().config,
            dispatcher=current_runtime().channel_dispatcher,
        )

        assert result.allowed is True
        assert result.status == "allowed"
        assert result.trust_tier == "trusted"


def test_admit_worker_message_does_not_auto_allow_unknown_surface() -> None:
    with fresh_env(config_overrides={"allowed_user_ids": frozenset()}) as (data_dir, _cfg, _prov):
        _, item_id = work_queue.record_and_enqueue(
            data_dir,
            "future-event-1",
            "future:workspace:room-1",
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
            conversation_ref="future:workspace:room-1",
            user=InboundUser(id=telegram_actor_key(42), username="blocked"),
            config=current_runtime().config,
            dispatcher=current_runtime().channel_dispatcher,
        )

        row = work_queue.debug_transport_connection(data_dir).execute(
            "SELECT state, error FROM work_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        assert result.allowed is False
        assert result.status == "not_allowed"
        assert row["state"] == "failed"
        assert row["error"] == "not_allowed"


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


@pytest.mark.asyncio
async def test_worker_recovery_for_routed_task_skips_bind_and_notice(monkeypatch) -> None:
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, _cfg, _prov):
        calls: list[str] = []

        async def fake_dispatch_worker_recovery(*, bind_egress, send_notice, **kwargs):
            del kwargs
            await bind_egress()
            await send_notice(
                SimpleNamespace(
                    preview="recover me",
                    prompt="Recover?",
                    run_again_label="Run again",
                    skip_label="Skip",
                    update_id=0,
                )
            )
            return SimpleNamespace(status="handled")

        monkeypatch.setattr(
            telegram_worker,
            "get_recovery_use_cases",
            lambda: SimpleNamespace(dispatch_worker_recovery=fake_dispatch_worker_recovery),
        )

        async def fake_bind(self, *, title, config):
            del title, config
            calls.append("bind")

        async def fake_send_recovery_notice(self, *, preview, prompt, run_again_label, skip_label, update_id):
            del preview, prompt, run_again_label, skip_label, update_id
            calls.append("send")

        monkeypatch.setattr(RegistryChannelEgress, "bind", fake_bind)
        monkeypatch.setattr(RegistryChannelEgress, "send_recovery_notice", fake_send_recovery_notice)

        event = InboundMessage(
            user=InboundUser(id="registry:actor", username="registry"),
            conversation_key="registry:default:task:routed-task-recovery-1",
            text="recover routed task",
            source="registry",
            conversation_ref="registry:default:task:routed-task-recovery-1",
            routed_task_id="routed-task-recovery-1",
            authority_ref="registry:default",
        )
        item = {
            "id": "routed-task-recovery-item-1",
            "conversation_key": "registry:default:task:routed-task-recovery-1",
            "event_id": "recovery-event-1",
            "dispatch_mode": "recovery",
        }

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert calls == []


@pytest.mark.asyncio
async def test_worker_recovery_for_conversation_still_binds_and_sends_notice(monkeypatch) -> None:
    with fresh_env() as (_data_dir, _cfg, _prov):
        calls: list[str] = []

        async def fake_dispatch_worker_recovery(*, bind_egress, send_notice, **kwargs):
            del kwargs
            await bind_egress()
            await send_notice(
                SimpleNamespace(
                    preview="recover me",
                    prompt="Recover?",
                    run_again_label="Run again",
                    skip_label="Skip",
                    update_id=8102,
                )
            )
            return SimpleNamespace(status="handled")

        monkeypatch.setattr(
            telegram_worker,
            "get_recovery_use_cases",
            lambda: SimpleNamespace(dispatch_worker_recovery=fake_dispatch_worker_recovery),
        )

        async def fake_bind(self, *, title, config):
            del title, config
            calls.append("bind")

        async def fake_send_recovery_notice(self, *, preview, prompt, run_again_label, skip_label, update_id):
            del preview, prompt, run_again_label, skip_label, update_id
            calls.append("send")

        monkeypatch.setattr(
            "app.channels.telegram.egress.TelegramChannelEgress.bind",
            fake_bind,
        )
        monkeypatch.setattr(
            "app.channels.telegram.egress.TelegramChannelEgress.send_recovery_notice",
            fake_send_recovery_notice,
        )

        event = InboundMessage(
            user=InboundUser(id=telegram_actor_key(42), username="telegram"),
            conversation_key=telegram_conversation_key(12345),
            text="recover telegram conversation",
            source="telegram",
        )
        item = {
            "id": "conversation-recovery-item-1",
            "conversation_key": telegram_conversation_key(12345),
            "event_id": telegram_event_id(8103),
            "dispatch_mode": "recovery",
        }

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert calls == ["bind", "send"]
