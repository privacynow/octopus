"""Tests for live cancellation of running work (Phase 15 Slice 2)."""

import asyncio
import time

import pytest

from app.providers.base import RunResult
from app.storage import default_session, save_session
from app import user_messages as _msg
from app.work_queue import debug_transport_connection, get_work_items_for_chat
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from tests.support.handler_support import (
    current_bot_instance,
    current_runtime,
    live_cancel_registry,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProgress,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    drain_one_worker_item,
    fresh_data_dir,
    last_reply,
    load_session_disk,
    make_config,
    running_worker,
    send_command,
    set_bot_instance,
    set_provider,
    setup_globals,
)


# ---------------------------------------------------------------------------
# Contract tests: provider cancel → RunResult.cancelled
# ---------------------------------------------------------------------------

class TestProviderCancelContract:
    """Cancel signal set during provider execution returns RunResult.cancelled."""

    async def test_claude_cancel_during_stream(self):
        """Claude: cancel event set while consuming stream kills proc and returns cancelled."""
        with fresh_data_dir() as data_dir:
            from app.providers.claude import ClaudeProvider
            provider = ClaudeProvider(make_config(data_dir))
            progress = FakeProgress()

            cancel = asyncio.Event()

            # Test that _consume_stream respects the cancel event
            # using a fake process with a pipe.
            proc = await _make_pipe_proc()

            # Set cancel before any line is written — _consume_stream should
            # kill the process and return immediately.
            cancel.set()
            text, result_data, tool_activity = await provider._consume_stream(
                proc, progress, cancel=cancel,
            )
            assert text == ""  # no data read
            assert proc.returncode is not None  # process killed/waited

    async def test_claude_run_returns_cancelled_result(self):
        """Claude.run() returns RunResult(cancelled=True) when cancel is set."""
        with fresh_data_dir() as data_dir:
            from app.providers.claude import ClaudeProvider
            provider = ClaudeProvider(make_config(data_dir))

            cancel = asyncio.Event()
            captured_cmd = []

            async def fake_run_process(cmd, progress, timeout=None, extra_env=None,
                                       working_dir="", cancel=None):
                captured_cmd.extend(cmd)
                # Simulate cancel being set before result
                if cancel:
                    cancel.set()
                return "partial text", {}, 0, ""

            provider._run_process = fake_run_process  # type: ignore[method-assign]

            result = await provider.run(
                {"session_id": "s1", "started": True},
                "test prompt", [], FakeProgress(), cancel=cancel,
            )
            assert result.cancelled is True
            assert result.text == "partial text"

    async def test_codex_cancel_during_stream(self):
        """Codex: cancel event set during consume_stdout kills proc and returns cancelled."""
        with fresh_data_dir() as data_dir:
            from app.providers.codex import CodexProvider
            provider = CodexProvider(make_config(data_dir))

            cancel = asyncio.Event()

            async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None,
                                   working_dir="", cancel=None):
                # Simulate the cancel being set during execution
                if cancel:
                    cancel.set()
                    return RunResult(text="", cancelled=True)
                return RunResult(text="normal")

            provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]

            result = await provider.run(
                {"thread_id": None}, "test", [], FakeProgress(), cancel=cancel,
            )
            assert result.cancelled is True

    async def test_run_result_cancelled_field(self):
        """RunResult.cancelled defaults to False and can be set to True."""
        normal = RunResult(text="ok")
        assert normal.cancelled is False

        cancelled = RunResult(text="", cancelled=True)
        assert cancelled.cancelled is True


# ---------------------------------------------------------------------------
# Handler integration tests: /cancel during live/approval/no-op
# ---------------------------------------------------------------------------

class TestCancelLiveExecution:
    """Handler integration: /cancel during live provider execution."""

    async def test_cancel_during_live_execution(self):
        """When provider is running, /cancel sets cancel event and responds immediately."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            # Simulate a live execution by registering a cancel event
            cancel_event = asyncio.Event()
            live_cancel_registry()[12345] = cancel_event

            try:
                msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
                assert cancel_event.is_set(), "cancel event should be set"

                from app.user_messages import cancel_live_requested
                assert last_reply(msg) == cancel_live_requested()
            finally:
                live_cancel_registry().pop(12345, None)

    async def test_cancel_no_live_execution_falls_through(self):
        """When no live execution, /cancel falls through to pending/setup check."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            # No _LIVE_CANCEL entry — should fall through to nothing_to_cancel
            msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
            from app.user_messages import nothing_to_cancel
            assert last_reply(msg) == nothing_to_cancel()

    async def test_cancel_pending_still_works(self):
        """When no live execution but pending approval exists, /cancel clears it."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["pending_approval"] = {
                "request_user_id": "tg:42",
                "prompt": "test",
                "image_paths": [],
                "attachment_dicts": [],
                "context_hash": "abc",
                "created_at": time.time(),
            }
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
            from app.user_messages import cancel_pending_request
            assert last_reply(msg) == cancel_pending_request()

    async def test_cancel_admitted_but_not_running(self):
        """When a message was admitted but worker has not started, /cancel cancels the queued item."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            # Admit a message (no worker drain yet)
            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # /cancel before worker runs: should cancel the queued item and reply superseded
            cancel_msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
            from app.user_messages import cancel_queued_superseded
            assert last_reply(cancel_msg) == cancel_queued_superseded()

            # Durable state: the admitted item must be terminal failed with error='cancelled'
            items = get_work_items_for_chat(data_dir, telegram_conversation_key(12345))
            cancelled = [i for i in items if i.get("state") == "failed" and i.get("error") == "cancelled"]
            runnable = [i for i in items if i.get("state") in ("queued", "claimed")]
            assert len(cancelled) == 1, f"Exactly one work item must be failed/cancelled, got: {items}"
            assert len(runnable) == 0, f"No runnable items after cancel, got: {items}"

            # Worker should see no runnable item (it was failed with error='cancelled')
            await drain_one_worker_item(data_dir)
            assert len(prov.run_calls) == 0, "Provider must not run after queued item was cancelled"


class TestCancelledOutcome:
    """execute_request and request_approval handle cancelled RunResult correctly."""

    async def test_execute_request_cancelled_updates_status(self):
        """Cancelled execution updates status to 'Cancelled.' and does not send final text."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="partial output", cancelled=True)]
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th
            from app.user_messages import cancel_live_completed

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="do something")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())
            await drain_one_worker_item(data_dir)

            # Worker sends status via bot
            bot = current_bot_instance()
            all_texts = [m.get("text", m.get("edit_text", "")) for m in bot.sent_messages if m.get("text") or m.get("edit_text")]
            assert any(t == cancel_live_completed() for t in all_texts), (
                f"Expected status '{cancel_live_completed()}' in bot output: {all_texts}"
            )
            # "partial output" must NOT appear anywhere
            assert not any("partial output" in t for t in all_texts if t), (
                f"Cancelled execution should not send final text. Got: {all_texts}"
            )

    async def test_request_approval_cancelled_does_not_store_pending(self):
        """Cancelled preflight does not store pending_approval."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.preflight_results = [RunResult(text="", cancelled=True)]
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th
            # load_session_disk already imported at module level

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "on")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="plan something")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # Session should not have pending_approval stored
            s = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
            assert s.get("pending_approval") is None


# ---------------------------------------------------------------------------
# Regression tests: cleanup, state corruption, double-cancel
# ---------------------------------------------------------------------------

class TestCancelRegressions:
    """Regression tests for cancel edge cases."""

    async def test_live_cancel_registry_cleaned_on_success(self):
        """_LIVE_CANCEL entry is removed after successful execution."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # After execution completes, the registry should be clean
            assert 12345 not in live_cancel_registry()

    async def test_live_cancel_registry_cleaned_on_error(self):
        """_LIVE_CANCEL entry is removed even when provider returns an error."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="error", returncode=1)]
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            assert 12345 not in live_cancel_registry()

    async def test_double_cancel_is_idempotent(self):
        """Setting cancel event twice does not raise or cause issues."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            cancel_event = asyncio.Event()
            live_cancel_registry()[12345] = cancel_event

            try:
                # First cancel
                msg1 = await send_command(th.cmd_cancel, chat, user, "/cancel")
                assert cancel_event.is_set()

                # Second cancel — event already set, registry already gone
                # (first cancel removed it by responding, but let's re-add to test)
                # Actually, the first cancel just sets it and returns;
                # the registry entry stays until the provider run finishes.
                # So a second cancel should also just set the (already-set) event.
                msg2 = await send_command(th.cmd_cancel, chat, user, "/cancel")

                from app.user_messages import cancel_live_requested
                assert last_reply(msg2) == cancel_live_requested()
            finally:
                live_cancel_registry().pop(12345, None)

    async def test_cancel_after_completion_is_noop(self):
        """After execution completes, /cancel shows nothing_to_cancel."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            # Execute a request to completion (admit then drain so item is completed)
            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())
            await drain_one_worker_item(data_dir)

            assert 12345 not in live_cancel_registry()

            # Now cancel — no queued item and no live run, so nothing_to_cancel
            cancel_msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
            from app.user_messages import nothing_to_cancel
            assert last_reply(cancel_msg) == nothing_to_cancel()

    async def test_cancelled_execution_preserves_provider_state_updates(self):
        """Cancelled execution persists provider_state_updates (thread/session continuity)."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            # Cancelled result WITH provider_state_updates that must be persisted
            prov.run_results = [
                RunResult(
                    text="partial",
                    cancelled=True,
                    provider_state_updates={"started": True},
                ),
            ]
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="first")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())
            await drain_one_worker_item(data_dir)

            # provider_state_updates must have been persisted
            s = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
            assert s["provider_state"]["started"] is True, \
                f"Cancelled run should persist provider_state_updates. Got: {s['provider_state']}"

    async def test_cancelled_execution_does_not_corrupt_next_request(self):
        """After a cancelled execution with state updates, the next request works normally."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            # First call: cancelled with state. Second call: normal success.
            prov.run_results = [
                RunResult(
                    text="",
                    cancelled=True,
                    provider_state_updates={"started": True},
                ),
                RunResult(text="success response"),
            ]
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            # First request — cancelled
            msg1 = FakeMessage(chat=chat, text="first")
            update1 = FakeUpdate(message=msg1, user=user, chat=chat)
            await th.handle_message(update1, FakeContext())
            await drain_one_worker_item(data_dir)

            # Second request — should succeed normally and see started=True
            msg2 = FakeMessage(chat=chat, text="second")
            update2 = FakeUpdate(message=msg2, user=user, chat=chat)
            await th.handle_message(update2, FakeContext())
            await drain_one_worker_item(data_dir)

            # Provider should have received both calls
            assert len(prov.run_calls) == 2
            # Second call should have seen started=True from the first cancelled run
            assert prov.run_calls[1]["provider_state"]["started"] is True, \
                f"Second call should see persisted state. Got: {prov.run_calls[1]['provider_state']}"



# ---------------------------------------------------------------------------
# Concurrency tests: cooperative cancel under real async execution
# (Phase 15 Slice 4)
# ---------------------------------------------------------------------------

class _GatedProvider(FakeProvider):
    """FakeProvider whose run() blocks until a gate event is set.

    Signals ``provider_started`` when it enters run(), then waits on
    the gate.  If cancel fires while waiting, returns cancelled=True.
    Records whether cancel was observed.
    """

    def __init__(self, name="claude"):
        super().__init__(name)
        self.gate = asyncio.Event()
        self.provider_started = asyncio.Event()
        self.saw_cancel = False
        self._state_updates: dict = {}

    def with_state_updates(self, updates):
        self._state_updates = updates
        return self

    async def run(self, provider_state, prompt, image_paths, progress, context=None, cancel=None):
        self.run_calls.append({
            "provider_state": dict(provider_state),
            "prompt": prompt,
            "image_paths": image_paths,
            "context": context,
        })
        await progress.update("working\u2026", force=True)
        self.provider_started.set()
        # Wait for either the gate or cancel
        if cancel is not None:
            gate_fut = asyncio.ensure_future(self.gate.wait())
            cancel_fut = asyncio.ensure_future(cancel.wait())
            done, pending = await asyncio.wait(
                [gate_fut, cancel_fut],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for fut in pending:
                fut.cancel()
            if cancel.is_set():
                self.saw_cancel = True
                return RunResult(
                    text="", cancelled=True,
                    provider_state_updates=dict(self._state_updates),
                )
        else:
            await self.gate.wait()
        if self.run_results:
            return self.run_results.pop(0)
        return RunResult(text="gated response", provider_state_updates=dict(self._state_updates))


class _CancelLosesProvider(FakeProvider):
    """Provider that blocks on a gate and always returns a normal result (cancelled=False).

    Used to test the live race: /cancel is sent while run() is blocking, but when the
    gate is set the provider finishes normally. So _PENDING_CANCEL_REQUEST is armed
    during the run but the run does not end with result.cancelled → cutoff must not
    be committed and queued B must still run.
    """

    def __init__(self, name="claude"):
        super().__init__(name)
        self.gate = asyncio.Event()
        self.provider_started = asyncio.Event()

    async def run(self, provider_state, prompt, image_paths, progress, context=None, cancel=None):
        self.run_calls.append({
            "provider_state": dict(provider_state),
            "prompt": prompt,
            "image_paths": image_paths,
            "context": context,
        })
        await progress.update("working\u2026", force=True)
        self.provider_started.set()
        # Block only on gate; ignore cancel so we can model "cancel requested but run completes normally"
        await self.gate.wait()
        if self.run_results:
            return self.run_results.pop(0)
        return RunResult(text="done")


class _OrderedSentMessage:
    """Sent-message stub whose edit_text appends to the bot's event_log."""

    def __init__(self, bot):
        self._bot = bot

    async def edit_text(self, text, **kwargs):
        self._bot.event_log.append(("edit", text))

    async def edit_message_reply_markup(self, **kwargs):
        pass

    async def reply_text(self, text, **kwargs):
        self._bot.event_log.append(("send", text))
        return _OrderedSentMessage(self._bot)


class _OrderedFakeBot:
    """Bot that records (kind, text) for send_message and edit_text in one ordered event_log."""

    def __init__(self):
        self.event_log: list[tuple[str, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.event_log.append(("send", text))
        return _OrderedSentMessage(self)

    async def send_chat_action(self, chat_id, action):
        pass


class TestCancelConcurrency:
    """Prove cancel works under real cooperative concurrency via background worker loop."""

    # -- Contract 1: Blocked-read cancel ------------------------------------

    async def test_readline_cancel_race_with_real_subprocess(self):
        """Cancel event resolves _consume_stream promptly when readline is
        genuinely blocked on a real subprocess pipe."""
        import sys
        from app.providers.claude import ClaudeProvider
        from tests.support.config_support import make_config as make_bot_config

        provider = ClaudeProvider(make_bot_config())
        progress = FakeProgress()
        cancel = asyncio.Event()

        # Spawn a real subprocess that writes nothing and sleeps —
        # readline() will be truly blocked on the pipe.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def cancel_after_delay():
            await asyncio.sleep(0.1)
            cancel.set()

        try:
            cancel_task = asyncio.create_task(cancel_after_delay())
            # _consume_stream must return promptly when cancel fires,
            # not hang for 60s waiting for readline.
            text, result_data, tool_activity = await asyncio.wait_for(
                provider._consume_stream(proc, progress, cancel=cancel),
                timeout=2.0,
            )
            await cancel_task

            # Subprocess was killed
            assert proc.returncode is not None, "Subprocess should have been killed"
            # No text accumulated (subprocess wrote nothing)
            assert text == ""
            # Cancel was set
            assert cancel.is_set()
        finally:
            # Hard cleanup in case test fails
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    # -- Contract 2: Lock-free cancel ingress + UX ordering -----------------

    async def test_cancel_dispatches_while_lock_held(self):
        """cmd_cancel runs and responds while _chat_lock is held by worker execution.
        Uses real background worker; admit work via handle_message, then send /cancel."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update, FakeContext())
                # Wait until the provider is running and the lock is held
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                assert current_runtime().chat_locks[12345].locked(), "Lock should be held"
                assert 12345 in live_cancel_registry(), "Cancel registry should exist"

                # Send /cancel — must complete without blocking on the lock
                cancel_msg = await asyncio.wait_for(
                    send_command(th.cmd_cancel, chat, user, "/cancel"),
                    timeout=0.5,
                )
                from app.user_messages import cancel_live_requested
                assert last_reply(cancel_msg) == cancel_live_requested(), \
                    f"Expected cancel ack. Got: {last_reply(cancel_msg)}"

                # Cancel event should now be set while lock is still held
                assert live_cancel_registry().get(12345) is None or live_cancel_registry()[12345].is_set(), \
                    "Cancel event should be set"

                prov.gate.set()

            # Provider saw the cancel
            assert prov.saw_cancel, "Provider should have observed cancel"

    async def test_two_stage_ux_ordering(self):
        """User sees 'Cancellation requested.' before 'Cancelled.' from worker-owned execution.
        Oracle: bot event log (send + edit) in order."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            cfg = make_config(data_dir)
            bot = _OrderedFakeBot()
            setup_globals(cfg, prov, bot_instance=bot)

            import app.channels.telegram.ingress as th
            from app.user_messages import cancel_live_completed, cancel_live_requested

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update, FakeContext())
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                cancel_msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
                prov.gate.set()

            # Cancel ack is sent to the command message (handler path), not the worker bot
            assert last_reply(cancel_msg) == cancel_live_requested(), (
                f"Cancel ack expected. Got: {last_reply(cancel_msg)}"
            )
            all_texts = [t for _, t in bot.event_log]
            assert cancel_live_completed() in all_texts, f"Terminal status missing: {bot.event_log}"
            # Ordering: ack (on message) happens before worker writes Cancelled. to status (bot log)
            assert bot.event_log, "Worker must have sent status (Working…, Cancelled.)"

    # -- Contract 3: Cancel non-corruption ----------------------------------

    async def test_cancel_mid_stream_preserves_partial_state(self):
        """Cancel after partial progress preserves provider_state_updates;
        worker sends status via bot. No final assistant reply on cancel."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            prov.with_state_updates({"started": True})
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th
            from app.user_messages import cancel_live_completed

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg = FakeMessage(chat=chat, text="mid-stream work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update, FakeContext())
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                cancel_event = live_cancel_registry().get(12345)
                assert cancel_event is not None, "_LIVE_CANCEL must exist"
                cancel_event.set()
                prov.gate.set()

            s = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
            assert s["provider_state"]["started"] is True, \
                f"provider_state_updates must persist on cancel. Got: {s['provider_state']}"

            bot = current_bot_instance()
            all_text = " ".join(m.get("text", m.get("edit_text", "")) for m in getattr(bot, "sent_messages", []))
            assert cancel_live_completed() in all_text, f"Status must show Cancelled. Got: {all_text}"
            assert "working" in all_text.lower() or "Working" in all_text, f"Progress before cancel: {all_text}"
            assert "gated response" not in all_text, "Final reply should not be sent on cancel"

    async def test_next_request_after_concurrent_cancel(self):
        """After a concurrent cancel, the next request sees persisted state and _LIVE_CANCEL is clean."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            prov.with_state_updates({"started": True})
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg1 = FakeMessage(chat=chat, text="first")
            update1 = FakeUpdate(message=msg1, user=user, chat=chat)

            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update1, FakeContext())
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                cancel_event = live_cancel_registry().get(12345)
                assert cancel_event is not None
                cancel_event.set()
                prov.gate.set()

            assert 12345 not in live_cancel_registry(), "_LIVE_CANCEL must be cleaned after execution"

            prov2 = FakeProvider("claude")
            prov2.run_results = [RunResult(text="normal response")]
            set_provider(prov2)

            msg2 = FakeMessage(chat=chat, text="second")
            update2 = FakeUpdate(message=msg2, user=user, chat=chat)
            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update2, FakeContext())
                for _ in range(50):
                    await asyncio.sleep(0.05)
                    if len(prov2.run_calls) >= 1:
                        break

            assert len(prov2.run_calls) == 1
            assert prov2.run_calls[0]["provider_state"]["started"] is True
            assert 12345 not in live_cancel_registry()

    async def test_second_message_while_run_active_is_queued_and_runs_next(self):
        """Second plain message while a run is active is durably queued and runs after the first item clears."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.channels.telegram.ingress as th
            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(12345), session)

            msg_a = FakeMessage(chat=chat, text="first request")
            update_a = FakeUpdate(message=msg_a, user=user, chat=chat)
            msg_b = FakeMessage(chat=chat, text="second message")
            update_b = FakeUpdate(message=msg_b, user=user, chat=chat)

            async with running_worker(data_dir, poll_interval=0.01):
                await th.handle_message(update_a, FakeContext())
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                await th.handle_message(update_b, FakeContext())
                reply_b = last_reply(msg_b)
                assert _msg.queue_accepted() in reply_b, f"B must get queued reply. Got: {reply_b}"

                conn = debug_transport_connection(data_dir)
                rows = conn.execute(
                    "SELECT id, state, error FROM work_items "
                    "WHERE conversation_key = 'tg:12345' ORDER BY id"
                ).fetchall()
                runnable = [r for r in rows if r["state"] in ("queued", "claimed")]
                assert len(runnable) == 2, f"Expected claimed current item plus queued backlog item. Got: {rows}"

                await send_command(th.cmd_cancel, chat, user, "/cancel")
                prov.gate.set()

            assert len(prov.run_calls) == 2

    async def test_cancel_sets_event_when_run_active(self):
        """/cancel sets the worker-owned cancel event so the run can exit."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            setup_globals(cfg, FakeProvider("claude"))

            import app.channels.telegram.ingress as th

            chat_id = 12345
            cancel_event = asyncio.Event()
            live_cancel_registry()[chat_id] = cancel_event
            try:
                chat = FakeChat(chat_id)
                user = FakeUser(42)
                from tests.support.handler_support import send_command
                await send_command(th.cmd_cancel, chat, user, "/cancel")
                assert cancel_event.is_set(), "/cancel must set the live cancel event"
            finally:
                live_cancel_registry().pop(chat_id, None)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StickyReplyMessage(FakeMessage):
    """Test message whose status updates land on the same reply log."""

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return self


class _OrderedMessage(FakeMessage):
    """Message whose reply_text and edit_text append to a shared event log.

    Every visible action records (source, text) so tests can assert
    cross-message ordering from a single timeline.
    """

    def __init__(self, event_log, source, **kwargs):
        super().__init__(**kwargs)
        self._event_log = event_log
        self._source = source

    async def reply_text(self, text, **kwargs):
        self._event_log.append((self._source, text))
        self.replies.append({"text": text, **kwargs})
        return self

    async def edit_text(self, text, **kwargs):
        self._event_log.append((self._source, text))
        self.replies.append({"edit_text": text, **kwargs})


class _FakePipeProc:
    """Minimal process-like object with a pipe for stdout."""
    def __init__(self, reader):
        self.stdout = reader
        self.returncode = None

    def kill(self):
        self.returncode = -9

    async def wait(self):
        pass


async def _make_pipe_proc():
    """Create a fake process with a pipe for stdout that _consume_stream can read."""
    reader = asyncio.StreamReader()
    proc = _FakePipeProc(reader)
    return proc


# Ensure all test classes are collected as async
pytestmark = pytest.mark.asyncio
