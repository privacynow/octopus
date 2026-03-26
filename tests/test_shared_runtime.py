"""Shared Runtime ingress and worker-ownership tests."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timezone
from unittest.mock import patch

from app import work_queue
from app.channels.telegram.bootstrap import build_bootstrap
from app.channels.telegram import shared_mode_dispatch as telegram_shared_mode_dispatch
from app.channels.telegram.session_io import event_key
from octopus_sdk.providers import RunResult
from app.storage import default_session, save_session
from octopus_sdk.inbound_types import InboundAction, InboundEnvelope, InboundUser, deserialize_inbound
from app.runtime.work_admission import record_inbound_envelope
from octopus_sdk.transport import InboundSubmissionResult
import app.channels.telegram.ingress as telegram_ingress
from tests.support.handler_support import (
    current_boot_id,
    current_shared_runtime_builders,
    current_runtime,
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeUpdate,
    FakeUser,
    drain_one_worker_item,
    fresh_env,
    load_session_disk,
)
from tests.support.service_support import build_test_bot_services


_SHARED_OVERRIDES = {
    "runtime_mode": "shared",
    "bot_mode": "webhook",
    "webhook_url": "https://bot.example.com/webhook",
}


def _conv(chat_id: int) -> str:
    return f"tg:{chat_id}"


@contextlib.asynccontextmanager
async def _permissive_chat_lock(_runtime, _chat_id, **_kwargs):
    yield False


class _FakeSubmitter:
    def __init__(self) -> None:
        self.admitted: list[InboundEnvelope] = []
        self.enqueued: list[InboundEnvelope] = []
        self.recorded: list[InboundEnvelope] = []

    async def admit_message(self, envelope: InboundEnvelope) -> InboundSubmissionResult:
        self.admitted.append(envelope)
        return InboundSubmissionResult(status="queued", item_id="item-1")

    async def enqueue(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult:
        del worker_id
        self.enqueued.append(envelope)
        return InboundSubmissionResult(status="queued", item_id="item-2")

    async def record(self, envelope: InboundEnvelope) -> bool:
        self.recorded.append(envelope)
        return True


async def test_shared_build_application_registers_shared_dispatch_handlers():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (_data_dir, cfg, prov):
        from telegram.ext import CallbackQueryHandler, CommandHandler

        app = build_bootstrap(cfg, prov, services=build_test_bot_services()).application
        command_callbacks: dict[str, str] = {}
        callback_patterns: list[tuple[str, str]] = []
        for group_handlers in app.handlers.values():
            for handler in group_handlers:
                if isinstance(handler, CommandHandler):
                    for command in getattr(handler, "commands", ()):
                        command_callbacks[str(command)] = getattr(handler.callback, "__name__", "")
                if isinstance(handler, CallbackQueryHandler):
                    callback_patterns.append((str(handler.pattern), getattr(handler.callback, "__name__", "")))

        assert command_callbacks["approve"] == "shared_command_dispatch"
        assert command_callbacks["cancel"] == "shared_command_dispatch"
        assert command_callbacks["help"] == "cmd_help"
        assert any(
            pattern.endswith("^(retry_|approval_)')") and callback == "shared_callback_dispatch"
            for pattern, callback in callback_patterns
        )
        assert any(
            pattern.endswith("^expand:')") and callback == "handle_expand_callback"
            for pattern, callback in callback_patterns
        )


async def test_shared_message_path_remains_persist_first():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, prov):
        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=user, chat=chat)

        await th.handle_message(update, FakeContext())

        assert prov.run_calls == []
        items = work_queue.get_work_items_for_chat(data_dir, _conv(chat.id))
        assert any(item["kind"] == "message" and item["state"] == "queued" for item in items)
        message_payload = work_queue.get_update_payload(data_dir, event_key(update.update_id))
        assert message_payload is not None
        message_event = deserialize_inbound("message", message_payload)
        assert message_event.transport == "telegram"

        assert await drain_one_worker_item(data_dir) is True
        assert len(prov.run_calls) == 1


async def test_shared_message_path_uses_runtime_submitter() -> None:
    with fresh_env(config_overrides=_SHARED_OVERRIDES):
        runtime = current_runtime()
        fake_submitter = _FakeSubmitter()
        runtime.submitter = fake_submitter
        chat = FakeChat(12345)
        user = FakeUser(42)
        message = FakeMessage(chat=chat, text="hello")
        update = FakeUpdate(message=message, user=user, chat=chat)

        await telegram_ingress.handle_message(update, FakeContext())

        assert len(fake_submitter.admitted) == 1
        assert fake_submitter.admitted[0].kind == "message"
        assert "queued" in message.replies[-1]["text"].lower()


async def test_shared_command_dispatch_persists_action_without_inline_execution():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(42)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="/approve"), user=user, chat=chat)
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=[]),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert prov.run_calls == []
        payload = work_queue.get_update_payload(data_dir, event_key(update.update_id))
        assert payload is not None
        event = deserialize_inbound("action", payload)
        assert event.action == "approve_pending"
        assert event.transport == "telegram"
        items = work_queue.get_work_items_for_chat(data_dir, _conv(chat.id))
        assert any(item["kind"] == "action" and item["state"] == "queued" for item in items)


def test_record_inbound_envelope_persists_transport_from_envelope() -> None:
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        event = InboundAction(
            user=InboundUser(id="slack:alice", username="alice"),
            conversation_key="slack:C123",
            action="approve_pending",
            params={},
            source="slack",
        )
        envelope = InboundEnvelope(
            transport="slack-webhook",
            event_id="evt-slack-1",
            conversation_key="slack:C123",
            actor_key="slack:alice",
            received_at=datetime.now(timezone.utc),
            event=event,
        )

        assert record_inbound_envelope(data_dir, envelope) is True
        payload = work_queue.get_update_payload(data_dir, "evt-slack-1")
        restored = deserialize_inbound("action", payload)

        assert restored.transport == "slack-webhook"


async def test_shared_command_dispatch_replies_to_unknown_commands():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (_data_dir, _cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(42)
        message = FakeMessage(chat=chat, text="/definitelynotacommand")
        update = FakeUpdate(message=message, user=user, chat=chat)
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=[]),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert prov.run_calls == []
        assert "isn't recognized" in message.replies[-1]["text"]


async def test_shared_callback_dispatch_persists_action_without_inline_execution():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(42)
        callback_message = FakeMessage(chat=chat, text="approve?")
        query = FakeCallbackQuery("approval_approve", message=callback_message, user=user)
        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        _build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_callback_dispatch(
            update,
            FakeContext(),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert prov.run_calls == []
        assert query.answered is True
        payload = work_queue.get_update_payload(data_dir, event_key(update.update_id))
        assert payload is not None
        event = deserialize_inbound("action", payload)
        assert event.action == "approve_pending"
        items = work_queue.get_work_items_for_chat(data_dir, _conv(chat.id))
        assert any(item["kind"] == "action" and item["state"] == "queued" for item in items)


async def test_shared_command_dispatch_uses_runtime_submitter_for_worker_owned_actions() -> None:
    with fresh_env(config_overrides=_SHARED_OVERRIDES):
        runtime = current_runtime()
        fake_submitter = _FakeSubmitter()
        runtime.submitter = fake_submitter
        chat = FakeChat(12345)
        user = FakeUser(42)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="/approve"), user=user, chat=chat)
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=[]),
            runtime=runtime,
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert len(fake_submitter.enqueued) == 1
        assert fake_submitter.enqueued[0].kind == "action"


async def test_shared_skills_command_routes_through_runtime_skill_owner(monkeypatch):
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def fake_handle_skills_command(event, update, *, runtime):
        del update, runtime
        calls.append((event.command, tuple(event.args or ())))

    with fresh_env(config_overrides=_SHARED_OVERRIDES):
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()
        chat = FakeChat(12345)
        user = FakeUser(42)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="/skills list"), user=user, chat=chat)
        monkeypatch.setattr(
            telegram_shared_mode_dispatch,
            "runtime_skill_handle_skills_command",
            fake_handle_skills_command,
        )

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=["list"]),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

    assert calls == [("skills", ("list",))]


async def test_shared_worker_executes_persisted_approve_action():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, prov):
        chat_id = 12345
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_approval"] = {
            "actor_key": "tg:42",
            "prompt": "Ship it",
            "image_paths": [],
            "attachment_dicts": [],
            "context_hash": "",
            "trust_tier": "trusted",
            "created_at": time.time(),
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="done")]

        chat = FakeChat(chat_id)
        user = FakeUser(42)
        update = FakeUpdate(message=FakeMessage(chat=chat, text="/approve"), user=user, chat=chat)
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=[]),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert len(prov.run_calls) == 0
        assert await drain_one_worker_item(data_dir) is True
        assert len(prov.run_calls) == 1
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        assert session_after.get("pending_approval") is None


async def test_shared_cancel_records_action_and_sets_durable_flag():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, prov):
        chat_id = 12345
        payload = (
            '{"actor_key":"tg:42","username":"alice","conversation_key":"tg:12345",'
            '"text":"long running","source":"telegram","attachments":[]}'
        )
        status, _item_id = work_queue.record_and_admit_message(
            data_dir,
            "tg:777",
            _conv(chat_id),
            "tg:42",
            "message",
            payload,
        )
        assert status == "admitted"
        claimed = work_queue.claim_next_any(data_dir, current_boot_id())
        assert claimed is not None

        chat = FakeChat(chat_id)
        user = FakeUser(42)
        message = FakeMessage(chat=chat, text="/cancel")
        update = FakeUpdate(message=message, user=user, chat=chat)
        build_conversation_runtime, build_runtime_skill_runtime = current_shared_runtime_builders()

        await telegram_shared_mode_dispatch.shared_command_dispatch(
            update,
            FakeContext(args=[]),
            runtime=current_runtime(),
            chat_lock=_permissive_chat_lock,
            build_conversation_runtime=build_conversation_runtime,
            build_runtime_skill_runtime=build_runtime_skill_runtime,
        )

        assert work_queue.is_cancel_requested(data_dir, claimed["id"]) is True
        payload = work_queue.get_update_payload(data_dir, event_key(update.update_id))
        assert payload is not None
        event = deserialize_inbound("action", payload)
        assert event.action == "cancel_conversation"
        items = work_queue.get_work_items_for_chat(data_dir, _conv(chat_id))
        assert len(items) == 1
        assert any("cancel" in reply.get("text", "").lower() for reply in message.replies)


async def test_worker_id_is_traceable():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (_data_dir, cfg, prov):
        telegram_bootstrap = build_bootstrap(cfg, prov, services=build_test_bot_services())
        parts = telegram_bootstrap.runtime.boot_id.split(":")
        assert len(parts) == 3
        assert parts[1].isdigit()
        assert len(parts[2]) == 12


async def test_periodic_stale_sweep_recovers_expired_claim():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        from app.worker import worker_loop

        status, item_id = work_queue.record_and_admit_message(
            data_dir,
            "tg:778",
            _conv(12345),
            "tg:42",
            "message",
            '{"text":"stale"}',
        )
        assert status == "admitted"
        claimed = work_queue.claim_next_any(data_dir, "old-worker")
        assert claimed is not None and claimed["id"] == item_id

        conn = work_queue.debug_transport_connection(data_dir)
        backdated = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 600))
        conn.execute("UPDATE work_items SET claimed_at = ? WHERE id = ?", (backdated, item_id))
        conn.commit()

        stop = asyncio.Event()

        async def stop_soon():
            await asyncio.sleep(0.05)
            stop.set()

        async def dispatch(_kind, _event, _item):
            raise AssertionError("dispatch should not run in sweep-only test")

        with patch("app.worker.work_queue.claim_next_any", return_value=None):
            await asyncio.gather(
                worker_loop(
                    data_dir,
                    "sweeper",
                    dispatch,
                    poll_interval=0.01,
                    lease_ttl=300,
                    sweep_interval=0.0,
                    stop_event=stop,
                ),
                stop_soon(),
            )

        items = work_queue.get_work_items_for_chat(data_dir, _conv(12345))
        recovered = [row for row in items if row["id"] == item_id]
        assert recovered and recovered[0]["state"] == "queued"
        assert recovered[0]["dispatch_mode"] == "recovery"


async def test_periodic_stale_sweep_ignores_live_claim():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        from app.worker import worker_loop

        status, item_id = work_queue.record_and_admit_message(
            data_dir,
            "tg:779",
            _conv(12345),
            "tg:42",
            "message",
            '{"text":"live"}',
        )
        assert status == "admitted"
        claimed = work_queue.claim_next_any(data_dir, "worker-a")
        assert claimed is not None and claimed["id"] == item_id

        stop = asyncio.Event()

        async def stop_soon():
            await asyncio.sleep(0.05)
            stop.set()

        async def dispatch(_kind, _event, _item):
            raise AssertionError("dispatch should not run in sweep-only test")

        with patch("app.worker.work_queue.claim_next_any", return_value=None):
            await asyncio.gather(
                worker_loop(
                    data_dir,
                    "worker-b",
                    dispatch,
                    poll_interval=0.01,
                    lease_ttl=300,
                    sweep_interval=0.0,
                    stop_event=stop,
                ),
                stop_soon(),
            )

        items = work_queue.get_work_items_for_chat(data_dir, _conv(12345))
        live = [row for row in items if row["id"] == item_id]
        assert live and live[0]["state"] == "claimed"
        conn = work_queue.debug_transport_connection(data_dir)
        row = conn.execute("SELECT worker_id FROM work_items WHERE id = ?", (item_id,)).fetchone()
        assert row is not None and row["worker_id"] == "worker-a"


async def test_worker_loop_writes_and_clears_heartbeat():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        from app.worker import worker_loop

        stop = asyncio.Event()
        heartbeat_calls: list[object] = []
        real_upsert = work_queue.upsert_worker_heartbeat

        def _tracking_upsert(*args, **kwargs):
            heartbeat_calls.append((args, kwargs))
            return real_upsert(*args, **kwargs)

        async def stop_soon():
            await asyncio.sleep(0.05)
            stop.set()

        async def dispatch(_kind, _event, _item):
            raise AssertionError("dispatch should not run in idle heartbeat test")

        with patch("app.worker.work_queue.upsert_worker_heartbeat", side_effect=_tracking_upsert), \
             patch("app.worker.work_queue.claim_next_any", return_value=None):
            await asyncio.gather(
                worker_loop(
                    data_dir,
                    "host:123:heartbeat",
                    dispatch,
                    poll_interval=0.01,
                    stop_event=stop,
                    process_role="worker",
                    heartbeat_enabled=True,
                    heartbeat_interval=0.01,
                ),
                stop_soon(),
            )

        assert heartbeat_calls
        assert work_queue.list_worker_heartbeats(data_dir) == []


async def test_worker_loop_heartbeat_tracks_current_item():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        from app.worker import worker_loop

        status, item_id = work_queue.record_and_admit_message(
            data_dir,
            "tg:9001",
            _conv(12345),
            "tg:42",
            "message",
            '{"actor_key":"tg:42","username":"alice","conversation_key":"tg:12345","text":"hello","source":"telegram","attachments":[]}',
        )
        assert status == "admitted"

        stop = asyncio.Event()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def dispatch(_kind, _event, item):
            assert item["id"] == item_id
            entered.set()
            await release.wait()
            stop.set()

        task = asyncio.create_task(
            worker_loop(
                data_dir,
                "host:456:item",
                dispatch,
                poll_interval=0.01,
                stop_event=stop,
                process_role="worker",
                heartbeat_enabled=True,
                heartbeat_interval=0.01,
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=0.5)
            heartbeats = work_queue.list_worker_heartbeats(data_dir)
            assert len(heartbeats) == 1
            heartbeat = heartbeats[0]
            assert heartbeat.current_item_id == item_id
            assert heartbeat.current_conversation_key == _conv(12345)
            assert heartbeat.current_kind == "message"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=0.5)

        assert work_queue.list_worker_heartbeats(data_dir) == []


async def test_worker_loop_usage_purge_runs_at_most_hourly():
    with fresh_env(config_overrides=_SHARED_OVERRIDES) as (data_dir, _cfg, _prov):
        from app.worker import worker_loop

        stop = asyncio.Event()
        purge_calls: list[float] = []
        monotonic_values = iter([0.0, 10.0, 20.0, 3701.0])
        claim_calls = 0

        def _monotonic() -> float:
            try:
                return next(monotonic_values)
            except StopIteration:
                return 3701.0

        def _claim_none(*_args, **_kwargs):
            nonlocal claim_calls
            claim_calls += 1
            if claim_calls >= 4:
                stop.set()
            return None

        async def dispatch(_kind, _event, _item):
            raise AssertionError("dispatch should not run in usage-purge test")

        with patch("app.worker.time.monotonic", side_effect=_monotonic), \
             patch("app.worker.work_queue.claim_next_any", side_effect=_claim_none), \
             patch("app.worker.work_queue.recover_stale_claims", return_value=0), \
             patch(
                 "app.worker.work_queue.purge_old_usage",
                 side_effect=lambda *_args, **_kwargs: purge_calls.append(time.time()) or 0,
             ):
            await worker_loop(
                data_dir,
                "usage-purge-worker",
                dispatch,
                poll_interval=0.0,
                sweep_interval=0.0,
                stop_event=stop,
            )

        assert len(purge_calls) == 2
