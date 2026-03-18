"""Canonical simulated-transport E2E tests. Use ConversationSimulator and real worker path."""

import asyncio
from datetime import datetime, timezone

import pytest

from app import work_queue
from app.agents.bridge import conversation_key_for_ref
from app.identity import telegram_conversation_key, telegram_actor_key, telegram_event_id
from app.providers.base import RunResult
from app.storage import default_session, save_session
from app import user_messages as _msg
from tests.support.handler_support import (
    live_cancel_registry,
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    fresh_data_dir,
    last_reply,
    load_session_disk,
    make_config,
)
from tests.support.conversation_simulator import ConversationSimulator


def _conv(value):
    return telegram_conversation_key(value)


def _actor(value):
    return telegram_actor_key(value)


def _event(value):
    return telegram_event_id(value)


def _reg_conv(conversation_ref: str) -> str:
    return conversation_key_for_ref(conversation_ref)


class _GatedProvider(FakeProvider):
    """Blocks in run() until gate or cancel is set. Signals provider_started on entry."""

    def __init__(self, name="claude"):
        super().__init__(name)
        self.gate = asyncio.Event()
        self.provider_started = asyncio.Event()

    async def run(self, provider_state, prompt, image_paths, progress, context=None, cancel=None):
        self.run_calls.append({
            "provider_state": dict(provider_state),
            "prompt": prompt,
        })
        self.provider_started.set()
        if cancel is not None:
            done, _ = await asyncio.wait(
                [asyncio.create_task(self.gate.wait()), asyncio.create_task(cancel.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in done:
                t.cancel()
            if cancel.is_set():
                return RunResult(text="", cancelled=True)
        else:
            await self.gate.wait()
        if self.run_results:
            return self.run_results.pop(0)
        return RunResult(text="done")


@pytest.mark.asyncio
async def test_canonical_message_long_run_cancel():
    """Inject message → worker runs → inject /cancel → cancel ack and cancelled status.

    Durable-work contract: exactly one provider-starting message work item (reaches done
    via worker) and exactly one /cancel command work item (reaches done via
    _command_handler → _complete_pending_work_item). No extra runnable items.
    """
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th

        cfg = make_config(data_dir)
        prov = _GatedProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, _conv(12345), session)

        msg_upd = await sim.inject_message_async(12345, 42, "hello")
        message_update_id = msg_upd.update_id

        async with sim.running_worker():
            await sim.wait_for_provider_started()
            cancel_upd = await sim.inject_command_async(12345, 42, "/cancel")
            cancel_update_id = cancel_upd.update_id
            prov.gate.set()

        await sim.wait_for_text(_msg.cancel_live_completed(), timeout=2.0)

        # One ordered output stream: cancel ack then cancelled status
        out = sim.get_output_log()
        merged = sim.get_output_log_merged()
        assert _msg.cancel_live_requested() in merged, f"cancel ack missing from output: {out}"
        assert _msg.cancel_live_completed() in merged, f"cancelled status missing from output: {out}"
        idx_ack = merged.find(_msg.cancel_live_requested())
        idx_done = merged.find(_msg.cancel_live_completed())
        assert idx_ack < idx_done, "cancel ack must appear before cancelled status in ordered log"

        assert len(prov.run_calls) == 1
        assert 12345 not in live_cancel_registry()

        # Exact durable-work shape: one terminal item for the message, one for the /cancel command
        items = work_queue.get_work_items_for_chat(data_dir, _conv(12345))
        message_items = [i for i in items if i.get("event_id") == _event(message_update_id) and i.get("kind") == "message"]
        command_items = [i for i in items if i.get("event_id") == _event(cancel_update_id) and i.get("kind") == "command"]
        runnable = [i for i in items if i.get("state") in ("queued", "claimed")]

        assert len(message_items) == 1, f"expected exactly one work item for message update {message_update_id}, got: {items}"
        assert message_items[0].get("state") == "done", f"message item should be done, got: {message_items[0]}"

        assert len(command_items) == 1, f"expected exactly one work item for /cancel update {cancel_update_id}, got: {items}"
        assert command_items[0].get("state") == "done", f"command item should be done, got: {command_items[0]}"

        assert len(runnable) == 0, f"no runnable items for chat after cancel, got: {items}"


@pytest.mark.asyncio
async def test_simulator_cancel_before_worker_claim():
    """Message admitted, /cancel before worker claims → terminal failed/cancelled, provider 0."""
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, _conv(12345), session)

        msg_upd = await sim.inject_message_async(12345, 42, "work")
        cancel_upd = await sim.inject_command_async(12345, 42, "/cancel")
        assert last_reply(cancel_upd.effective_message) == _msg.cancel_queued_superseded()

        await sim.drain_one()
        assert len(prov.run_calls) == 0

        items = work_queue.get_work_items_for_chat(data_dir, _conv(12345))
        message_cancelled = [i for i in items if i.get("event_id") == _event(msg_upd.update_id) and i.get("kind") == "message" and i.get("state") == "failed" and i.get("error") == "cancelled"]
        assert len(message_cancelled) == 1, f"expected exactly one failed/cancelled message item, got: {items}"


@pytest.mark.asyncio
async def test_simulator_second_message_queues_fifo():
    """Second message while first is active is accepted into the durable queue and runs next."""
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th

        cfg = make_config(data_dir)
        prov = _GatedProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, _conv(12345), session)

        await sim.inject_message_async(12345, 42, "first")

        async with sim.running_worker():
            await sim.wait_for_provider_started()
            msg_second_upd = await sim.inject_message_async(12345, 42, "second")
            assert _msg.queue_accepted() in last_reply(msg_second_upd.effective_message)
            prov.gate.set()

        assert len(prov.run_calls) == 2

        items = work_queue.get_work_items_for_chat(data_dir, _conv(12345))
        runnable = [i for i in items if i.get("state") in ("queued", "claimed")]
        second_item = [i for i in items if i.get("event_id") == _event(msg_second_upd.update_id) and i.get("kind") == "message"]
        assert len(runnable) == 0, f"zero runnable items after completion, got: {items}"
        assert len(second_item) == 1, f"expected durable queued work item for second message update {msg_second_upd.update_id}, got: {items}"
        assert second_item[0]["state"] == "done"


@pytest.mark.asyncio
async def test_simulator_credential_reply_while_worker_alive():
    """Credential reply while worker running: stays off queue, provider 0 for that message."""
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "test-skill",
            "remaining": [{"key": "TOKEN", "prompt": "Enter token", "help_url": None, "validate": None}],
        }
        save_session(data_dir, _conv(12345), session)

        async def fake_validate(req, value):
            return (True, "")

        original = th.validate_credential
        th.validate_credential = fake_validate
        try:
            async with sim.running_worker():
                await sim.inject_message_async(12345, 42, "my-secret-token")
        finally:
            th.validate_credential = original

        assert len(prov.run_calls) == 0
        session_after = load_session_disk(data_dir, _conv(12345), prov)
        assert session_after.get("awaiting_skill_setup") is None


@pytest.mark.asyncio
async def test_simulator_recovery_notice_no_provider_call():
    """Recovered item (dispatch_mode=recovery): recovery notice shown, item to pending_recovery, provider not called."""
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th
        from app import work_queue as wq

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, _conv(12345), session)

        wq.record_update(
            data_dir, _event(9001), _conv(12345), _actor(42), "message",
            payload='{"actor_key": "tg:42", "username": "", "conversation_key": "tg:12345", "text": "recovered"}',
        )
        conn = work_queue.debug_transport_connection(data_dir)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) VALUES (?, ?, ?, 'queued', ?, 'recovery')",
            ("recovery-item-1", _conv(12345), _event(9001), now),
        )
        conn.commit()

        await sim.drain_one()

        assert any("recovery" in t.lower() or _msg.recovery_notice_intro() in t for t in sim.get_output_log())
        assert len(prov.run_calls) == 0
        latest = wq.get_latest_pending_recovery(data_dir, _conv(12345))
        assert latest is not None


@pytest.mark.asyncio
async def test_simulator_callback_edit_message_text_in_output_log():
    """Callback that calls query.edit_message_text appears in the simulator ordered output log."""
    with fresh_data_dir() as data_dir:
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import (
            FakeChat,
            FakeContext,
            FakeMessage,
            FakeUpdate,
            FakeUser,
        )

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("skill_add_cancel", message=msg, user=user)
        upd = FakeUpdate(user=user, chat=chat, callback_query=query)

        await th.handle_skill_add_callback(upd, FakeContext())

        out = sim.get_output_log()
        assert "Skill activation cancelled." in out, f"callback edit_message_text must appear in output log, got: {out}"


@pytest.mark.asyncio
async def test_simulator_registry_message_runs_through_registry_surface_output():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            agent_mode="registry",
            agent_registry_url="http://registry.test",
            agent_registry_enroll_token="enroll-secret",
        )
        prov = FakeProvider("claude")
        sim = ConversationSimulator(data_dir, cfg, prov)

        conversation_ref = "registry:sim-conv-1"
        chat_id = _reg_conv(conversation_ref)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, chat_id, session)

        async with sim.running_worker():
            injected = await sim.inject_registry_message_async(
                conversation_ref,
                "build a plan",
                "registry-ui:sim-user",
            )
            assert injected["status"] == "admitted"
            await sim.wait_for_text("default response")

        assert len(prov.run_calls) == 1
        assert prov.run_calls[0]["prompt"] == "build a plan"
        assert "default response" in sim.get_output_log_merged()
        assert sim._bot.sent_messages == []
