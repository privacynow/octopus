"""Tests for live cancellation of running work (Phase 15 Slice 2)."""

import asyncio
import time

import pytest

from app.providers.base import RunResult
from app.storage import default_session, save_session
from tests.support.handler_support import (
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProgress,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    fresh_data_dir,
    last_reply,
    load_session_disk,
    make_config,
    send_command,
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

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # Simulate a live execution by registering a cancel event
            cancel_event = asyncio.Event()
            th._LIVE_CANCEL[12345] = cancel_event

            try:
                msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
                assert cancel_event.is_set(), "cancel event should be set"

                from app.user_messages import cancel_live_requested
                assert last_reply(msg) == cancel_live_requested()
            finally:
                th._LIVE_CANCEL.pop(12345, None)

    async def test_cancel_no_live_execution_falls_through(self):
        """When no live execution, /cancel falls through to pending/setup check."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

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

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            session["pending_approval"] = {
                "request_user_id": 42,
                "prompt": "test",
                "image_paths": [],
                "attachment_dicts": [],
                "context_hash": "abc",
                "created_at": time.time(),
            }
            save_session(data_dir, 12345, session)

            msg = await send_command(th.cmd_cancel, chat, user, "/cancel")
            from app.user_messages import cancel_pending_request
            assert last_reply(msg) == cancel_pending_request()


class TestCancelledOutcome:
    """execute_request and request_approval handle cancelled RunResult correctly."""

    async def test_execute_request_cancelled_updates_status(self):
        """Cancelled execution updates status to 'Cancelled.' and does not send final text."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="partial output", cancelled=True)]
            setup_globals(cfg, prov)

            import app.telegram_handlers as th
            from app.user_messages import cancel_live_completed

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # _StickyReplyMessage so status edits land on the same reply log
            msg = _StickyReplyMessage(chat=chat, text="do something")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            all_reply_texts = [
                r.get("text", r.get("edit_text", ""))
                for r in msg.replies
            ]
            # Status message must show cancel_live_completed() via edit
            assert any(t == cancel_live_completed() for t in all_reply_texts),                 f"Expected status \'{cancel_live_completed()}\' in replies: {all_reply_texts}"
            # "partial output" must NOT appear anywhere
            assert not any("partial output" in t for t in all_reply_texts if t),                 f"Cancelled execution should not send final text. Replies: {all_reply_texts}"

    async def test_request_approval_cancelled_does_not_store_pending(self):
        """Cancelled preflight does not store pending_approval."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.preflight_results = [RunResult(text="", cancelled=True)]
            setup_globals(cfg, prov)

            import app.telegram_handlers as th
            # load_session_disk already imported at module level

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "on")
            save_session(data_dir, 12345, session)

            msg = FakeMessage(chat=chat, text="plan something")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # Session should not have pending_approval stored
            s = load_session_disk(data_dir, 12345, prov)
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

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # After execution completes, the registry should be clean
            assert 12345 not in th._LIVE_CANCEL

    async def test_live_cancel_registry_cleaned_on_error(self):
        """_LIVE_CANCEL entry is removed even when provider returns an error."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="error", returncode=1)]
            setup_globals(cfg, prov)

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            assert 12345 not in th._LIVE_CANCEL

    async def test_double_cancel_is_idempotent(self):
        """Setting cancel event twice does not raise or cause issues."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            cancel_event = asyncio.Event()
            th._LIVE_CANCEL[12345] = cancel_event

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
                th._LIVE_CANCEL.pop(12345, None)

    async def test_cancel_after_completion_is_noop(self):
        """After execution completes, /cancel shows nothing_to_cancel."""
        with fresh_data_dir() as data_dir:
            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # Execute a request to completion
            msg = FakeMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            assert 12345 not in th._LIVE_CANCEL

            # Now cancel — should show nothing_to_cancel
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

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            msg = _StickyReplyMessage(chat=chat, text="first")
            update = FakeUpdate(message=msg, user=user, chat=chat)
            await th.handle_message(update, FakeContext())

            # provider_state_updates must have been persisted
            s = load_session_disk(data_dir, 12345, prov)
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

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # First request — cancelled
            msg1 = _StickyReplyMessage(chat=chat, text="first")
            update1 = FakeUpdate(message=msg1, user=user, chat=chat)
            await th.handle_message(update1, FakeContext())

            # Second request — should succeed normally and see started=True
            msg2 = _StickyReplyMessage(chat=chat, text="second")
            update2 = FakeUpdate(message=msg2, user=user, chat=chat)
            await th.handle_message(update2, FakeContext())

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


class TestCancelConcurrency:
    """Prove cancel works under real cooperative concurrency."""

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
        """cmd_cancel runs and responds while _chat_lock is held by
        execute_request. Proves cancel does not block behind the lock."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.telegram_handlers as th

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            msg = _StickyReplyMessage(chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async def send_cancel_after_provider_starts():
                # Wait until the provider is running and the lock is held
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                assert th.CHAT_LOCKS[12345].locked(), "Lock should be held"
                assert 12345 in th._LIVE_CANCEL, "Cancel registry should exist"

                # Send /cancel — must complete without blocking on the lock
                cancel_msg = await asyncio.wait_for(
                    send_command(th.cmd_cancel, chat, user, "/cancel"),
                    timeout=0.5,
                )
                from app.user_messages import cancel_live_requested
                assert last_reply(cancel_msg) == cancel_live_requested(), \
                    f"Expected cancel ack. Got: {last_reply(cancel_msg)}"

                # Cancel event should now be set while lock is still held
                assert th._LIVE_CANCEL.get(12345) is None or th._LIVE_CANCEL[12345].is_set(), \
                    "Cancel event should be set"

            # Run handle_message and cancel concurrently
            await asyncio.gather(
                th.handle_message(update, FakeContext()),
                send_cancel_after_provider_starts(),
            )

            # Provider saw the cancel
            assert prov.saw_cancel, "Provider should have observed cancel"

    async def test_two_stage_ux_ordering(self):
        """User sees 'Cancellation requested.' before 'Cancelled.' on
        the status message, from a single concurrent execution.

        Oracle: shared event log across both message objects, proving
        cross-message ordering from a single timeline."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.telegram_handlers as th
            from app.user_messages import cancel_live_completed, cancel_live_requested

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # Shared event log: both messages append (source, text) here.
            event_log: list[tuple[str, str]] = []

            # Status message for the original request
            msg = _OrderedMessage(event_log, "status", chat=chat, text="do work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async def send_cancel_after_provider_starts():
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                # Build the /cancel command message on the same shared log
                cancel_msg = _OrderedMessage(event_log, "cancel", chat=chat, text="/cancel")
                cancel_upd = FakeUpdate(message=cancel_msg, user=user, chat=chat)
                await asyncio.wait_for(
                    th.cmd_cancel(cancel_upd, FakeContext()),
                    timeout=0.5,
                )

            await asyncio.gather(
                th.handle_message(update, FakeContext()),
                send_cancel_after_provider_starts(),
            )

            # Both messages must appear in the shared log
            all_texts = [text for _, text in event_log]
            assert cancel_live_requested() in all_texts, \
                f"Cancel ack missing from event log: {event_log}"
            assert cancel_live_completed() in all_texts, \
                f"Terminal status missing from event log: {event_log}"

            # Ordering: cancel ack must appear before terminal status
            ack_idx = next(i for i, (_, t) in enumerate(event_log)
                          if t == cancel_live_requested())
            done_idx = next(i for i, (_, t) in enumerate(event_log)
                          if t == cancel_live_completed())
            assert ack_idx < done_idx, (
                f"Cancel ack (index {ack_idx}) must appear before terminal "
                f"status (index {done_idx}). Event log: {event_log}"
            )

    # -- Contract 3: Cancel non-corruption ----------------------------------

    async def test_cancel_mid_stream_preserves_partial_state(self):
        """Cancel after partial progress preserves provider_state_updates
        and does not send a malformed final reply.

        Oracle: load_session_disk for state, _StickyReplyMessage for status."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            prov.with_state_updates({"started": True})
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.telegram_handlers as th
            from app.user_messages import cancel_live_completed

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            msg = _StickyReplyMessage(chat=chat, text="mid-stream work")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            async def cancel_after_progress():
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                # Provider has already emitted "working…" progress update.
                # Now cancel mid-execution.
                cancel_event = th._LIVE_CANCEL.get(12345)
                assert cancel_event is not None, "_LIVE_CANCEL must exist"
                cancel_event.set()

            await asyncio.gather(
                th.handle_message(update, FakeContext()),
                cancel_after_progress(),
            )

            # Provider state updates were persisted despite cancel
            s = load_session_disk(data_dir, 12345, prov)
            assert s["provider_state"]["started"] is True, \
                f"provider_state_updates must persist on cancel. Got: {s['provider_state']}"

            # Status message shows Cancelled.
            all_edits = [
                r.get("text", r.get("edit_text", ""))
                for r in msg.replies
            ]
            assert any(t == cancel_live_completed() for t in all_edits), \
                f"Status must show '{cancel_live_completed()}'. Got: {all_edits}"

            # Partial progress appeared before cancel
            assert any("working" in t for t in all_edits if t), \
                f"Progress should appear before cancel. Got: {all_edits}"

            # No final assistant reply was sent to the chat
            for sent in chat.sent_messages:
                text = sent.get("text", "")
                assert "gated response" not in text, \
                    f"Final reply should not be sent on cancel. Got: {text}"

    async def test_next_request_after_concurrent_cancel(self):
        """After a concurrent cancel, the next request sees persisted state,
        executes normally, and _LIVE_CANCEL is clean.

        Strengthens the existing next-request test with real concurrency."""
        with fresh_data_dir() as data_dir:
            prov = _GatedProvider("claude")
            prov.with_state_updates({"started": True})
            cfg = make_config(data_dir)
            setup_globals(cfg, prov)

            import app.telegram_handlers as th
            from app.user_messages import cancel_live_completed

            chat = FakeChat(12345)
            user = FakeUser(42)
            session = default_session(prov.name, prov.new_provider_state(), "off")
            save_session(data_dir, 12345, session)

            # First request — cancel concurrently
            msg1 = _StickyReplyMessage(chat=chat, text="first")
            update1 = FakeUpdate(message=msg1, user=user, chat=chat)

            async def cancel_first():
                await asyncio.wait_for(prov.provider_started.wait(), timeout=2.0)
                cancel_event = th._LIVE_CANCEL.get(12345)
                assert cancel_event is not None
                cancel_event.set()

            await asyncio.gather(
                th.handle_message(update1, FakeContext()),
                cancel_first(),
            )

            # Registry is clean after the first request
            assert 12345 not in th._LIVE_CANCEL, \
                "_LIVE_CANCEL must be cleaned after execution"

            # Second request — swap provider directly (setup_globals would
            # reset CHAT_LOCKS and other per-chat state we need to keep).
            import app.telegram_handlers as th2
            prov2 = FakeProvider("claude")
            prov2.run_results = [RunResult(text="normal response")]
            th2._provider = prov2

            msg2 = _StickyReplyMessage(chat=chat, text="second")
            update2 = FakeUpdate(message=msg2, user=user, chat=chat)
            await th.handle_message(update2, FakeContext())

            # Second call saw started=True from the persisted cancelled run
            assert len(prov2.run_calls) == 1
            assert prov2.run_calls[0]["provider_state"]["started"] is True, \
                f"Second request must see persisted state. Got: {prov2.run_calls[0]['provider_state']}"

            # Registry still clean
            assert 12345 not in th._LIVE_CANCEL

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
