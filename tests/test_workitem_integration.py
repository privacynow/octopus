"""Integration tests for work-item claim serialization.

These tests exercise the real production code path: handler decorator →
_chat_lock → work_queue SQLite → claim_for_update / claim_next.  The only
fakes are the Telegram transport and provider subprocess — those are the
actual external boundaries.

Each test creates real contention: concurrent asyncio tasks, real SQLite
transactions, real _chat_lock acquisition.  No mock databases, no mock
locks, no mock work_queue.
"""

import asyncio

import pytest

from app.providers.base import RunResult
from app import work_queue
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeUpdate,
    FakeUser,
    fresh_env,
    send_command,
    set_bot_instance,
)


# ---------------------------------------------------------------------------
# 1. Stale recovered item is not silently consumed by a fresh message
#
# Scenario: boot recovery re-queues item 100 (stale).  A fresh message
# (update 101) arrives.  The handler must process 101 and leave 100 for
# the worker_loop — not mark 100 done as a side effect.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_message_does_not_consume_stale_recovered_item():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9001

        # Simulate a stale recovered item sitting in the queue
        work_queue.record_and_enqueue(data_dir, 100, chat_id, 42, "message")

        # A fresh message arrives through the real handler path
        prov.run_results = [RunResult(text="fresh response")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="fresh message")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        # The fresh message's work item (update_id from FakeUpdate) is done
        conn = work_queue._transport_db(data_dir)
        fresh_item = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert fresh_item is not None
        assert fresh_item["state"] == "done", (
            f"Fresh item should be done, got: {fresh_item['state']}"
        )

        # Stale item 100 must still be queued — available for worker_loop
        stale_item = conn.execute(
            "SELECT state FROM work_items WHERE update_id = 100",
        ).fetchone()
        assert stale_item["state"] == "queued", (
            f"Stale item 100 should remain queued for worker, got: {stale_item['state']}"
        )


# ---------------------------------------------------------------------------
# 2. Two concurrent messages for the same chat serialize correctly
#
# Scenario: update 200 and 201 arrive near-simultaneously.  Each must
# claim and complete its own work item.  Neither should complete the
# other's item.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_messages_each_claim_own_item():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9002

        # Provider returns different text so we can distinguish
        prov.run_results = [
            RunResult(text="response to first"),
            RunResult(text="response to second"),
        ]

        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        msg1 = FakeMessage(chat=chat, text="first")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)

        msg2 = FakeMessage(chat=chat, text="second")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)

        # Launch both concurrently — _chat_lock serializes them
        await asyncio.gather(
            th.handle_message(upd1, FakeContext()),
            th.handle_message(upd2, FakeContext()),
        )

        # Both items should be done
        conn = work_queue._transport_db(data_dir)
        for upd in [upd1, upd2]:
            row = conn.execute(
                "SELECT state FROM work_items WHERE update_id = ?",
                (upd.update_id,),
            ).fetchone()
            assert row is not None, f"No work item for update {upd.update_id}"
            assert row["state"] == "done", (
                f"Item for update {upd.update_id} should be done, got: {row['state']}"
            )

        # No orphaned queued items for this chat
        queued = conn.execute(
            "SELECT count(*) as n FROM work_items WHERE chat_id = ? AND state = 'queued'",
            (chat_id,),
        ).fetchone()
        assert queued["n"] == 0, (
            f"No items should remain queued, got: {queued['n']}"
        )


# ---------------------------------------------------------------------------
# 3. claim_for_update does not break per-chat serialization
#
# If the worker has already claimed an item for a chat, a handler
# entering _chat_lock must not create a second claimed item.  The
# in-memory lock prevents this in normal operation, but the durable
# layer must be independently safe.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_for_update_blocked_by_existing_claimed_item():
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9003

        work_queue.record_and_enqueue(data_dir, 300, chat_id, 42, "message")
        work_queue.record_and_enqueue(data_dir, 301, chat_id, 42, "message")

        # Worker claims item 300
        first = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert first is not None and first["update_id"] == 300

        # Handler tries to claim item 301 — must fail (chat already has a claimed item)
        second = work_queue.claim_for_update(data_dir, chat_id, 301, "handler-1")
        assert second is None, "Must not claim while another item is claimed"

        # Verify only one claimed item exists
        conn = work_queue._transport_db(data_dir)
        claimed_count = conn.execute(
            "SELECT count(*) as n FROM work_items WHERE chat_id = ? AND state = 'claimed'",
            (chat_id,),
        ).fetchone()
        assert claimed_count["n"] == 1

        # After completing the first, the second becomes claimable
        work_queue.complete_work_item(data_dir, first["id"], state="done")
        third = work_queue.claim_for_update(data_dir, chat_id, 301, "handler-1")
        assert third is not None and third["update_id"] == 301


# ---------------------------------------------------------------------------
# 4. Callback handler (approval) does not consume stale items
#
# Scenario: a stale item is queued for recovery.  User taps "approve"
# on an existing pending approval.  The approval callback must claim its
# own work item via the context variable, not the stale one.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_callback_does_not_consume_stale_item():
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat_id = 9004

        # Step 1: create a pending approval via normal message flow
        prov.preflight_results = [RunResult(text="plan: do stuff")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg1 = FakeMessage(chat=chat, text="do something requiring approval")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())

        session = th._load(chat_id)
        assert session.pending_approval is not None, "Should have pending approval"

        # Step 2: inject a stale recovered item into the queue
        work_queue.record_and_enqueue(data_dir, 500, chat_id, 42, "message")

        # Step 3: approve via callback
        prov.run_results = [RunResult(text="executed the plan")]
        query = FakeCallbackQuery(
            "approval_approve",
            message=FakeMessage(chat=chat),
            user=user,
        )
        upd2 = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_callback(upd2, FakeContext())

        # Step 4: verify stale item 500 is still queued
        conn = work_queue._transport_db(data_dir)
        stale = conn.execute(
            "SELECT state FROM work_items WHERE update_id = 500",
        ).fetchone()
        assert stale["state"] == "queued", (
            f"Stale item 500 should remain queued, got: {stale['state']}"
        )


# ---------------------------------------------------------------------------
# 5. /project use serializes with in-flight request
#
# Scenario: a message is being processed (lock held).  /project use
# arrives and waits for the lock.  When it acquires the lock, the
# in-flight request is done.  The project switch then safely resets
# provider_state without racing.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_project_switch_waits_for_inflight_request():
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "projects": (("proj1", "/tmp/p1", ()), ("proj2", "/tmp/p2", ())),
    }) as (data_dir, cfg, prov):
        chat_id = 9005

        # Provider takes some time (simulated by the test flow)
        prov.run_results = [
            RunResult(text="long response", provider_state_updates={"started": True}),
        ]

        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        # Send message — this holds the lock during execution
        msg1 = FakeMessage(chat=chat, text="do work")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())

        # Verify started=True
        session = th._load(chat_id)
        assert session.provider_state["started"] is True

        # Now /project use — must acquire lock, reset state
        from tests.support.handler_support import send_command
        await send_command(
            th.cmd_project, chat, user,
            "/project use proj1", args=["use", "proj1"],
        )

        session = th._load(chat_id)
        assert session.project_id == "proj1"
        assert session.provider_state["started"] is False, (
            "/project use must reset provider_state after acquiring lock"
        )


# ---------------------------------------------------------------------------
# 6. Preflight uses the same model as execution
#
# The resolved effective_model must flow into both PreflightContext and
# RunContext.  This test exercises the real builder chain.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preflight_and_execution_use_same_model():
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "approval_mode": "on",
        "model_profiles": {"fast": "claude-fast-model"},
    }) as (data_dir, cfg, prov):
        chat_id = 9006

        # Set model profile
        session = th._load(chat_id)
        session.model_profile = "fast"
        th._save(chat_id, session)

        # Approval flow: preflight then execution
        prov.preflight_results = [RunResult(text="plan: use fast model")]
        prov.run_results = [RunResult(text="executed with fast model")]

        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        # Send message — triggers preflight
        msg = FakeMessage(chat=chat, text="do something")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        # Verify preflight received the model
        assert len(prov.preflight_calls) == 1
        preflight_ctx = prov.preflight_calls[0]["context"]
        assert preflight_ctx.effective_model == "claude-fast-model", (
            f"Preflight model: {preflight_ctx.effective_model!r}"
        )

        # Approve it
        query = FakeCallbackQuery(
            "approval_approve",
            message=FakeMessage(chat=chat),
            user=user,
        )
        upd2 = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_callback(upd2, FakeContext())

        # Verify execution received the same model
        assert len(prov.run_calls) == 1
        run_ctx = prov.run_calls[0]["context"]
        assert run_ctx.effective_model == "claude-fast-model", (
            f"Execution model: {run_ctx.effective_model!r}"
        )


# ---------------------------------------------------------------------------
# 7. Worker-claimed item blocks live handler (decorated command)
#
# Scenario: worker claims item 100 via claim_next_any (outside the
# in-memory lock).  Before the worker enters _chat_lock, a decorated
# command (/new) arrives and acquires the lock first.  The command
# must NOT run — ClaimBlocked prevents the handler body from executing.
# The command's own work item stays queued for the worker to process.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_command_blocked_by_worker_claimed_item():
    import app.telegram_handlers as th
    from tests.support.handler_support import send_command

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9007

        # Simulate a recovered item the worker has claimed (durable state)
        work_queue.record_and_enqueue(data_dir, 100, chat_id, 42, "message")
        worker_item = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert worker_item is not None
        assert worker_item["update_id"] == 100

        # A decorated command arrives while the worker holds the claimed item
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        await send_command(th.cmd_new, chat, user, "/new")

        conn = work_queue._transport_db(data_dir)

        # Worker's item must still be claimed — not touched by the command
        row_100 = conn.execute(
            "SELECT state, worker_id FROM work_items WHERE update_id = 100",
        ).fetchone()
        assert row_100["state"] == "claimed", (
            f"Worker item 100 should remain claimed, got: {row_100['state']}"
        )

        # The command's own work item must still be queued (not done)
        cmd_items = conn.execute(
            "SELECT update_id, state FROM work_items "
            "WHERE chat_id = ? AND update_id != 100 ORDER BY update_id",
            (chat_id,),
        ).fetchall()
        assert len(cmd_items) == 1, f"Expected 1 command work item, got {len(cmd_items)}"
        assert cmd_items[0]["state"] == "queued", (
            f"Command item should be queued (blocked by worker), "
            f"got: {cmd_items[0]['state']}"
        )

        # Provider was never called — the command body didn't run
        assert len(prov.run_calls) == 0
        assert len(prov.preflight_calls) == 0


# ---------------------------------------------------------------------------
# 8. Worker-claimed item blocks live message handler
#
# Same race but via handle_message (not decorated — uses _chat_lock
# directly).  The message handler must not run; its work item stays
# queued for the worker.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_message_blocked_by_worker_claimed_item():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9008

        # Worker has claimed item 100
        work_queue.record_and_enqueue(data_dir, 100, chat_id, 42, "message")
        worker_item = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert worker_item is not None

        # A live message arrives while the worker holds the claim
        prov.run_results = [RunResult(text="should not run")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="live message")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        conn = work_queue._transport_db(data_dir)

        # Worker's item stays claimed
        row_100 = conn.execute(
            "SELECT state FROM work_items WHERE update_id = 100",
        ).fetchone()
        assert row_100["state"] == "claimed"

        # The message's work item stays queued (not done, not claimed)
        msg_item = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert msg_item is not None, "Message work item should exist"
        assert msg_item["state"] == "queued", (
            f"Message item should be queued (blocked by worker), "
            f"got: {msg_item['state']}"
        )

        # Provider was never called
        assert len(prov.run_calls) == 0


# ---------------------------------------------------------------------------
# 9. After worker finishes, the blocked item becomes claimable
#
# End-to-end: worker claimed → live message blocked → worker completes
# → message can now be claimed and processed normally.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_blocked_item_processable_after_worker_completes():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 9009

        # Worker claims and holds item 100
        work_queue.record_and_enqueue(data_dir, 100, chat_id, 42, "message")
        worker_item = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert worker_item is not None

        # Live message arrives — blocked
        prov.run_results = [RunResult(text="response after unblock")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg1 = FakeMessage(chat=chat, text="blocked message")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())

        conn = work_queue._transport_db(data_dir)
        item1 = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd1.update_id,),
        ).fetchone()
        assert item1["state"] == "queued", "Should be queued while worker holds claim"

        # Worker finishes
        work_queue.complete_work_item(data_dir, worker_item["id"], state="done")

        # Now the message can be processed normally
        prov.run_results = [RunResult(text="now it works")]
        msg2 = FakeMessage(chat=chat, text="blocked message")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(upd2, FakeContext())

        # The new message's item should be done
        item2 = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd2.update_id,),
        ).fetchone()
        assert item2["state"] == "done", (
            f"After worker finished, new message should complete normally, "
            f"got: {item2['state']}"
        )

        # And the original blocked item is still queued (would be picked
        # up by worker_loop in production)
        item1_after = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd1.update_id,),
        ).fetchone()
        assert item1_after["state"] == "queued"


# ---------------------------------------------------------------------------
# 10. Worker-claimed item blocks live callback and answers the query
#
# Scenario: worker claims item 100, then an approval callback arrives.
# ClaimBlocked fires in the decorator, but the callback query must still
# be answered (Telegram shows a spinner until query.answer() is called).
# The callback's work item stays queued for the worker.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_callback_blocked_by_worker_and_query_answered():
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat_id = 9010

        # Step 1: create a pending approval via normal message flow
        prov.preflight_results = [RunResult(text="plan: do stuff")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg1 = FakeMessage(chat=chat, text="do something requiring approval")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())

        session = th._load(chat_id)
        assert session.pending_approval is not None

        # Step 2: simulate worker claiming an item for this chat
        work_queue.record_and_enqueue(data_dir, 600, chat_id, 42, "message")
        worker_item = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert worker_item is not None
        assert worker_item["update_id"] == 600

        # Step 3: approval callback arrives while worker holds claim
        prov.run_results = [RunResult(text="should not run")]
        query = FakeCallbackQuery(
            "approval_approve",
            message=FakeMessage(chat=chat),
            user=user,
        )
        upd2 = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_callback(upd2, FakeContext())

        # The callback query MUST be answered (no Telegram spinner left hanging)
        assert query.answered, (
            "Callback query must be answered even when ClaimBlocked fires"
        )

        conn = work_queue._transport_db(data_dir)

        # Worker's item stays claimed
        row_600 = conn.execute(
            "SELECT state FROM work_items WHERE update_id = 600",
        ).fetchone()
        assert row_600["state"] == "claimed"

        # Callback's work item stays queued
        cb_item = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd2.update_id,),
        ).fetchone()
        assert cb_item is not None
        assert cb_item["state"] == "queued", (
            f"Callback item should be queued (blocked by worker), "
            f"got: {cb_item['state']}"
        )

        # Provider was never called
        assert len(prov.run_calls) == 0


# ---------------------------------------------------------------------------
# 11. Recovery notice: worker_dispatch sends notice, not auto-replay
#
# When a recovered InboundMessage is dispatched by the worker, it must
# send a recovery notice with Replay/Discard buttons instead of blindly
# replaying through the provider.  The work item transitions to
# pending_recovery.
# ---------------------------------------------------------------------------

class _FakeBot:
    """Minimal bot for worker_dispatch — send_message returns a FakeMessage."""
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        msg = FakeMessage(chat=FakeChat(chat_id), text=text)
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return msg

    async def send_chat_action(self, chat_id, action):
        pass


@pytest.mark.asyncio
async def test_worker_dispatch_sends_recovery_notice():
    """Recovered InboundMessage gets a recovery notice with buttons,
    not an automatic replay through the provider."""
    import app.telegram_handlers as th
    from app.transport import InboundMessage, InboundUser

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 11001

        # Create a claimed work item (simulating post-recovery claim)
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 500, chat_id, 42, "message",
            payload='{"text": "do something dangerous"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = 'test' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            event = InboundMessage(
                user=InboundUser(id=42, username="alice"),
                chat_id=chat_id,
                text="do something dangerous",
                attachments=(),
            )
            item = {"chat_id": chat_id, "update_id": 500, "id": item_id}

            with pytest.raises(work_queue.PendingRecovery):
                await th.worker_dispatch("message", event, item)

            # Provider must NOT have been called
            assert len(prov.run_calls) == 0, "No auto-replay allowed"

            # Recovery notice was sent with buttons
            notice = [s for s in bot.sent if "interrupted" in s.get("text", "")]
            assert notice, "Expected recovery notice"
            assert notice[0].get("reply_markup") is not None, "Expected inline keyboard"

            # Work item is now pending_recovery
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "pending_recovery"
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 12. Recovery discard: user clicks Discard → item finalized
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_discard_callback_finalizes_item():
    """Clicking Discard on a recovery notice finalizes the item as
    'discarded' and edits the message."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12001

        # Create a pending_recovery work item
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 600, chat_id, 42, "message",
            payload='{"text": "old message"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            query = FakeCallbackQuery(
                data=f"recovery_discard:{600}",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd = FakeUpdate(
                callback_query=query,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )

            await th.handle_recovery_callback(upd, FakeContext())

            # Item finalized as discarded
            row = conn.execute(
                "SELECT state, error FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "done"
            assert row["error"] == "discarded"

            # Query was answered
            assert query.answered

            # Message was edited to show discard confirmation
            edits = [r for r in query.message.replies if "edit_text" in r]
            assert edits
            assert "discarded" in edits[0]["edit_text"].lower()
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 13. Recovery replay: user clicks Replay → original message is executed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_replay_callback_executes_original():
    """Clicking Replay on a recovery notice replays the original message
    through execute_request."""
    import app.telegram_handlers as th
    from app.transport import serialize_inbound, InboundMessage, InboundUser

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 13001

        # Create a pending_recovery work item with a real payload
        event = InboundMessage(
            user=InboundUser(id=42, username="alice"),
            chat_id=chat_id,
            text="explain quantum computing",
            attachments=(),
        )
        payload = serialize_inbound(event)
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 700, chat_id, 42, "message", payload=payload,
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        prov.run_results = [RunResult(text="quantum explanation")]
        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            query = FakeCallbackQuery(
                data=f"recovery_replay:{700}",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd = FakeUpdate(
                callback_query=query,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )

            await th.handle_recovery_callback(upd, FakeContext())

            # Provider was called — replay executed
            assert len(prov.run_calls) == 1, (
                f"Expected 1 provider call, got {len(prov.run_calls)}"
            )

            # Item finalized as done
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "done"

            # Query was answered
            assert query.answered
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 14. Fresh message supersedes pending_recovery
#
# A fresh live message must supersede any pending_recovery for the chat,
# not wait for the user to click Replay/Discard.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_message_supersedes_pending_recovery():
    """A fresh message arriving for a chat with a pending_recovery item
    supersedes the recovery — the fresh message proceeds and the old
    item is finalized as superseded."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 14001

        # Create a pending_recovery work item
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 800, chat_id, 42, "message",
            payload='{"text": "old message"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        # A fresh message arrives
        prov.run_results = [RunResult(text="fresh response")]
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="new question")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        # Fresh message's item is done
        fresh_row = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert fresh_row["state"] == "done"

        # Old pending_recovery is superseded
        old_row = conn.execute(
            "SELECT state, error FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert old_row["state"] == "done"
        assert old_row["error"] == "superseded"


# ---------------------------------------------------------------------------
# 15. Double-click on recovery buttons is idempotent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_double_click_is_idempotent():
    """Clicking Replay or Discard twice on the same recovery notice
    is safe — second click gets 'already handled'."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 15001

        # Create a pending_recovery work item
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 900, chat_id, 42, "message",
            payload='{"text": "test"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            # First click — discard
            query1 = FakeCallbackQuery(
                data=f"recovery_discard:{900}",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd1 = FakeUpdate(
                callback_query=query1,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd1, FakeContext())

            # Verify first click worked
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "done"

            # Second click — same button
            query2 = FakeCallbackQuery(
                data=f"recovery_discard:{900}",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd2 = FakeUpdate(
                callback_query=query2,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd2, FakeContext())

            # Second click was answered (no crash)
            assert query2.answered
            assert "already been handled" in (query2.answer_text or "")
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 16. Failed notice delivery marks item failed through worker_loop
#
# If send_message fails, worker_dispatch re-raises.  Worker_loop catches
# the exception and marks the item failed (not done).  The item must not
# end up in pending_recovery or done — both would silently lose the
# user's request.  This test exercises through worker_loop, which is the
# real completion owner.
# ---------------------------------------------------------------------------

class _ExplodingBot(_FakeBot):
    """Bot whose send_message always raises."""
    async def send_message(self, chat_id, text, **kwargs):
        raise RuntimeError("Telegram API down")


@pytest.mark.asyncio
async def test_failed_notice_delivery_marks_item_failed_via_worker_loop():
    """If the recovery notice cannot be delivered, worker_loop must mark
    the item failed — not done, not pending_recovery."""
    import app.telegram_handlers as th
    from app.worker import worker_loop
    from app.transport import serialize_inbound, InboundMessage, InboundUser

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 16001
        worker_id = "test-worker-16"

        # Create a queued item with a real serialized payload.
        event = InboundMessage(
            user=InboundUser(id=42, username="alice"),
            chat_id=chat_id,
            text="stranded?",
            attachments=(),
        )
        payload = serialize_inbound(event)
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 1600, chat_id, 42, "message", payload=payload,
        )

        bot = _ExplodingBot()
        set_bot_instance(bot)
        try:
            # Wrap worker_dispatch to stop the loop after one dispatch.
            stop = asyncio.Event()
            original_dispatch = th.worker_dispatch
            async def dispatch_then_stop(kind, event, item):
                try:
                    return await original_dispatch(kind, event, item)
                finally:
                    stop.set()

            # Run worker_loop — it will claim, dispatch (which raises),
            # mark the item failed, then stop.
            await worker_loop(data_dir, worker_id, dispatch_then_stop,
                              stop_event=stop, poll_interval=0)

            # Item must be failed — not done, not pending_recovery.
            conn = work_queue._transport_db(data_dir)
            row = conn.execute(
                "SELECT state, error FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "failed", (
                f"Item should be failed after notice delivery failure, got: {row['state']}"
            )
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 17. Multiple pending_recovery items for same chat: each addressable
#
# If two items are recovered for the same chat, both get notices and
# each button targets the correct item by update_id.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_pending_recovery_items_each_addressable():
    """Two pending_recovery items for the same chat: clicking Discard
    on the older one must finalize it, not the newer one."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 17001

        # Create two pending_recovery items for the same chat.
        _, item_id_1 = work_queue.record_and_enqueue(
            data_dir, 1700, chat_id, 42, "message",
            payload='{"text": "first recovered"}',
        )
        _, item_id_2 = work_queue.record_and_enqueue(
            data_dir, 1701, chat_id, 42, "message",
            payload='{"text": "second recovered"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id IN (?, ?)",
            (item_id_1, item_id_2),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            # Discard the OLDER item (update_id 1700).
            query1 = FakeCallbackQuery(
                data="recovery_discard:1700",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd1 = FakeUpdate(
                callback_query=query1,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd1, FakeContext())

            # Older item finalized.
            row1 = conn.execute(
                "SELECT state, error FROM work_items WHERE id = ?", (item_id_1,)
            ).fetchone()
            assert row1["state"] == "done"
            assert row1["error"] == "discarded"

            # Newer item still pending.
            row2 = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id_2,)
            ).fetchone()
            assert row2["state"] == "pending_recovery", (
                f"Newer item should still be pending_recovery, got: {row2['state']}"
            )

            # Now discard the newer item too.
            query2 = FakeCallbackQuery(
                data="recovery_discard:1701",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd2 = FakeUpdate(
                callback_query=query2,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd2, FakeContext())

            row2 = conn.execute(
                "SELECT state, error FROM work_items WHERE id = ?", (item_id_2,)
            ).fetchone()
            assert row2["state"] == "done"
            assert row2["error"] == "discarded"
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 18. Discard race: concurrent discard after item already finalized
#
# If discard loses a race to replay or supersession, it must answer
# "already handled", not lie about having discarded.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discard_race_after_replay_answers_already_handled():
    """If the item was already reclaimed for replay before discard runs,
    discard must report 'already handled', not 'Discarded.'."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 18001

        _, item_id = work_queue.record_and_enqueue(
            data_dir, 1800, chat_id, 42, "message",
            payload='{"text": "raced"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            # Simulate replay winning the race: reclaim moves to 'claimed'.
            work_queue.reclaim_for_replay(data_dir, item_id, "test-boot")

            # Now discard arrives late.
            query = FakeCallbackQuery(
                data="recovery_discard:1800",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd = FakeUpdate(
                callback_query=query,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd, FakeContext())

            # Must answer "already handled", not "Discarded."
            assert query.answered
            assert "already been handled" in (query.answer_text or ""), (
                f"Expected 'already been handled', got: {query.answer_text}"
            )

            # Item must NOT have been finalized by the discard path.
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "claimed", (
                f"Item should still be claimed (replay owns it), got: {row['state']}"
            )
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 19. Replay reclaim respects per-chat single-claimed invariant
#
# reclaim_for_replay must not create two claimed rows for the same chat.
# If another item is already claimed (e.g. worker processing a fresh
# message), the reclaim must be rejected.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replay_reclaim_blocked_by_existing_claimed_item():
    """reclaim_for_replay must reject if another item for the same chat
    is already claimed — preserving the per-chat single-claimed invariant."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 19001

        # Item 1: a pending_recovery item the user wants to replay.
        _, item_id_recovery = work_queue.record_and_enqueue(
            data_dir, 1900, chat_id, 42, "message",
            payload='{"text": "old recovered"}',
        )
        # Item 2: a fresh item currently claimed by the worker.
        _, item_id_worker = work_queue.record_and_enqueue(
            data_dir, 1901, chat_id, 42, "message",
            payload='{"text": "fresh in-flight"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id_recovery,),
        )
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = 'worker-2' WHERE id = ?",
            (item_id_worker,),
        )
        conn.commit()

        # reclaim_for_replay must raise ReclaimBlocked — another item is claimed.
        with pytest.raises(work_queue.ReclaimBlocked):
            work_queue.reclaim_for_replay(data_dir, item_id_recovery, "worker-1")

        # Recovery item must still be pending_recovery.
        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?", (item_id_recovery,)
        ).fetchone()
        assert row["state"] == "pending_recovery"

        # Worker item must still be claimed — exactly one claimed row.
        claimed_rows = conn.execute(
            "SELECT id FROM work_items WHERE chat_id = ? AND state = 'claimed'",
            (chat_id,),
        ).fetchall()
        assert len(claimed_rows) == 1
        assert claimed_rows[0]["id"] == item_id_worker


@pytest.mark.asyncio
async def test_replay_callback_blocked_by_claimed_item_answers_user():
    """When the user clicks Replay but another item is already claimed
    for the chat, the callback must inform the user rather than silently
    failing or creating two claimed rows."""
    import app.telegram_handlers as th
    from app.transport import serialize_inbound, InboundMessage, InboundUser

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 19002

        event = InboundMessage(
            user=InboundUser(id=42, username="alice"),
            chat_id=chat_id,
            text="replay me",
            attachments=(),
        )
        payload = serialize_inbound(event)
        _, item_id_recovery = work_queue.record_and_enqueue(
            data_dir, 1910, chat_id, 42, "message", payload=payload,
        )
        _, item_id_worker = work_queue.record_and_enqueue(
            data_dir, 1911, chat_id, 42, "message",
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id_recovery,),
        )
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = 'worker' WHERE id = ?",
            (item_id_worker,),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            query = FakeCallbackQuery(
                data="recovery_replay:1910",
                message=FakeMessage(chat=FakeChat(chat_id)),
                user=FakeUser(uid=42),
            )
            upd = FakeUpdate(
                callback_query=query,
                user=FakeUser(uid=42),
                chat=FakeChat(chat_id),
            )
            await th.handle_recovery_callback(upd, FakeContext())

            # Must not have called the provider.
            assert len(prov.run_calls) == 0

            # Recovery item must still be pending_recovery.
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id_recovery,)
            ).fetchone()
            assert row["state"] == "pending_recovery"

            # User must be informed via message edit (query was already
            # answered with "Replaying…" before the reclaim check).
            edits = [r for r in query.message.replies if "edit_text" in r]
            assert edits, "Expected message edit informing user"
            assert "in progress" in edits[0]["edit_text"]
        finally:
            set_bot_instance(None)


# ---------------------------------------------------------------------------
# 21. Command handler does NOT supersede pending_recovery
#
# Only fresh messages (handle_message) should supersede pending_recovery.
# Commands like /cancel that go through _chat_lock without
# supersede_recovery=True must leave pending_recovery items alone.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_command_does_not_supersede_pending_recovery():
    """A command going through _chat_lock must not supersede
    pending_recovery items — only handle_message should."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 21001

        # Create a pending_recovery item.
        _, item_id_recovery = work_queue.record_and_enqueue(
            data_dir, 2100, chat_id, 42, "message",
            payload='{"text": "interrupted request"}',
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id_recovery,),
        )
        conn.commit()

        # Send a /cancel command — goes through _chat_lock without
        # supersede_recovery=True.
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="/cancel")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.cmd_cancel(upd, FakeContext())

        # The pending_recovery item must still be pending_recovery.
        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?", (item_id_recovery,)
        ).fetchone()
        assert row["state"] == "pending_recovery", (
            f"Command superseded pending_recovery — state is {row['state']}"
        )


# ---------------------------------------------------------------------------
# 22. reclaim_for_replay distinguishes "gone" from "blocked"
#
# When reclaim_for_replay cannot proceed:
# - Item gone/handled → returns None
# - Item exists but blocked by claimed → raises ReclaimBlocked
# Callers use this to show the correct message.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reclaim_distinguishes_gone_from_blocked():
    """reclaim_for_replay returns None when item is gone, raises
    ReclaimBlocked when blocked by per-chat claimed invariant."""
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 22001

        # Create two items: one pending_recovery, one claimed.
        _, item_id_recovery = work_queue.record_and_enqueue(
            data_dir, 2200, chat_id, 42, "message",
        )
        _, item_id_claimed = work_queue.record_and_enqueue(
            data_dir, 2201, chat_id, 42, "message",
        )
        conn = work_queue._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id_recovery,),
        )
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = 'w' WHERE id = ?",
            (item_id_claimed,),
        )
        conn.commit()

        # Blocked case: item exists but another is claimed → ReclaimBlocked.
        with pytest.raises(work_queue.ReclaimBlocked):
            work_queue.reclaim_for_replay(data_dir, item_id_recovery, "w2")

        # Item still pending_recovery after blocked attempt.
        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?", (item_id_recovery,)
        ).fetchone()
        assert row["state"] == "pending_recovery"

        # Now finalize the claimed item and also the recovery item.
        work_queue.complete_work_item(data_dir, item_id_claimed, state="done")
        work_queue.finalize_recovery(data_dir, item_id_recovery, "discarded")

        # Gone case: item no longer in pending_recovery → returns None.
        result = work_queue.reclaim_for_replay(data_dir, item_id_recovery, "w2")
        assert result is None


# ---------------------------------------------------------------------------
# 23. Fresh command items are handler-owned from creation
#
# The bug: _dedup_update() created items as 'queued', letting the worker
# steal fresh commands via claim_next_any().  The worker then sent false
# "interrupted by a restart" notices.  Fix: items start as 'claimed'
# by the inline handler's _boot_id.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_command_item_created_as_claimed():
    """_dedup_update creates work items as 'claimed' (handler-owned),
    not 'queued'.  The worker's claim_next_any must not be able to
    steal them."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12001
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        # Send a lock-free command through the real decorator
        await send_command(th.cmd_session, chat, user, "/session")

        conn = work_queue._transport_db(data_dir)

        # The work item must be 'done' (handler completed it), and its
        # worker_id must be the inline handler's _boot_id, not a worker.
        items = conn.execute(
            "SELECT state, worker_id FROM work_items WHERE chat_id = ?",
            (chat_id,),
        ).fetchall()
        assert len(items) == 1
        assert items[0]["state"] == "done"
        assert items[0]["worker_id"] == th._boot_id


@pytest.mark.asyncio
async def test_worker_cannot_steal_handler_owned_item():
    """claim_next_any must skip items already claimed by the inline handler.

    This is the exact race: decorator creates the item, then the worker
    polls before the handler finishes.  With the fix, the item starts as
    'claimed' so claim_next_any returns None."""
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12002

        # Simulate what _dedup_update does: create a claimed item
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 700, chat_id, 42, "command",
            worker_id="handler-boot-id",
        )

        # Worker polls — must NOT find anything claimable
        stolen = work_queue.claim_next_any(data_dir, "background-worker")
        assert stolen is None, (
            "Worker stole a handler-owned item — the race condition is back"
        )

        # The item is still claimed by the handler
        conn = work_queue._transport_db(data_dir)
        row = conn.execute(
            "SELECT state, worker_id FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row["state"] == "claimed"
        assert row["worker_id"] == "handler-boot-id"


# ---------------------------------------------------------------------------
# 24. No false recovery notice for lock-free commands
#
# Exact reproduction of the bug from dont_make_false_claims.md:
# /compact (no args) and /doctor sent through real handlers with a
# worker actively polling.  Must produce exactly one response per
# command, zero recovery notices.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_false_recovery_for_compact():
    """Fresh /compact must never trigger a recovery notice, even with
    an active worker.  Reproduces incident 1 from dont_make_false_claims.md."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12003
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        # Send /compact (no args) — lock-free path
        msg = await send_command(th.cmd_compact, chat, user, "/compact")

        # Exactly one reply (the compact status), zero recovery notices
        assert len(msg.replies) == 1
        reply_text = msg.replies[0].get("text", "")
        assert "Compact mode" in reply_text
        assert "interrupted" not in reply_text
        assert "restart" not in reply_text

        # Worker polls — nothing to steal
        stolen = work_queue.claim_next_any(data_dir, "worker-1")
        assert stolen is None

        # Work item completed by handler
        conn = work_queue._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE chat_id = ?", (chat_id,),
        ).fetchone()
        assert row["state"] == "done"


@pytest.mark.asyncio
async def test_no_false_recovery_for_doctor():
    """Fresh /doctor must never trigger a recovery notice, even with
    an active worker.  Reproduces incident 2 from dont_make_false_claims.md."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12004
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")

        # Doctor sends at least one reply; none should be recovery
        assert len(msg.replies) >= 1
        for reply in msg.replies:
            text = reply.get("text", "")
            assert "interrupted" not in text, f"False recovery notice: {text}"
            assert "restart" not in text, f"False restart claim: {text}"

        # Worker finds nothing
        stolen = work_queue.claim_next_any(data_dir, "worker-1")
        assert stolen is None


@pytest.mark.asyncio
async def test_no_false_recovery_for_session():
    """Adjacent lock-free command: /session must also be immune."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12005
        chat = FakeChat(chat_id=chat_id)
        user = FakeUser(uid=42)

        msg = await send_command(th.cmd_session, chat, user, "/session")

        assert len(msg.replies) >= 1
        for reply in msg.replies:
            text = reply.get("text", "")
            assert "interrupted" not in text
            assert "restart" not in text

        stolen = work_queue.claim_next_any(data_dir, "worker-1")
        assert stolen is None


# ---------------------------------------------------------------------------
# 25. Handler crash leaves item recoverable
#
# If the handler crashes before completing, the item must stay claimed
# (not done/queued).  Stale claim recovery picks it up later.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_crash_leaves_item_claimed_for_recovery():
    """If a handler raises before completing its work item, the item
    stays 'claimed' — recoverable by stale claim detection."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12006

        # Directly test the low-level contract: create a claimed item
        # (as _dedup_update does), then DON'T complete it.
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 800, chat_id, 42, "command",
            worker_id=th._boot_id,
        )

        # Item is claimed — worker can't steal it
        stolen = work_queue.claim_next_any(data_dir, "worker-1")
        assert stolen is None

        # Stale claim detection: a new boot sees a claimed item from the
        # old boot and requeues it (different worker_id = stale).
        requeued = work_queue.recover_stale_claims(data_dir, "new-boot-id")
        assert requeued == 1

        # After recovery the item is queued again — worker can claim it
        worker_item = work_queue.claim_next_any(data_dir, "worker-1")
        assert worker_item is not None
        assert worker_item["update_id"] == 800


# ---------------------------------------------------------------------------
# 26. claim_for_update recognizes pre-claimed items
#
# When _chat_lock calls claim_for_update for an item already claimed
# by the same worker_id (pre-claimed by _dedup_update), it must return
# the item instead of None.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_for_update_recognizes_pre_claimed():
    """claim_for_update returns a pre-claimed item when the worker_id matches."""
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12007
        boot_id = "my-boot-id"

        _, item_id = work_queue.record_and_enqueue(
            data_dir, 900, chat_id, 42, "command",
            worker_id=boot_id,
        )

        # claim_for_update with same worker_id finds the pre-claimed item
        item = work_queue.claim_for_update(data_dir, chat_id, 900, boot_id)
        assert item is not None
        assert item["id"] == item_id
        assert item["state"] == "claimed"
        assert item["worker_id"] == boot_id

        # claim_for_update with different worker_id returns None
        # (another claimed item exists for this chat)
        item2 = work_queue.claim_for_update(data_dir, chat_id, 900, "different-id")
        assert item2 is None


# ---------------------------------------------------------------------------
# 27. complete_work_item state guard
#
# complete_work_item must not overwrite terminal states (done, failed,
# pending_recovery).  Defense in depth against the race.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_work_item_does_not_overwrite_terminal_state():
    """complete_work_item only transitions from queued/claimed, not from
    done/failed/pending_recovery."""
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12008

        _, item_id = work_queue.record_and_enqueue(
            data_dir, 950, chat_id, 42, "command",
        )
        # Complete it
        work_queue.complete_work_item(data_dir, item_id, state="done")

        conn = work_queue._transport_db(data_dir)
        row = conn.execute(
            "SELECT state, completed_at FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row["state"] == "done"
        original_completed_at = row["completed_at"]

        # Try to overwrite done → failed — must be a no-op
        work_queue.complete_work_item(data_dir, item_id, state="failed", error="too late")

        row2 = conn.execute(
            "SELECT state, error, completed_at FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row2["state"] == "done", "Terminal state must not be overwritten"
        assert row2["error"] is None
        assert row2["completed_at"] == original_completed_at


# ---------------------------------------------------------------------------
# 28. Per-chat serialization preserved with pre-claimed items
#
# When the worker holds a claimed item for a chat, a new command for
# the same chat must fall back to 'queued' (not 'claimed'), preserving
# the per-chat single-claimed invariant.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preclaim_falls_back_to_queued_when_chat_busy():
    """If another item is already claimed for the chat, new items are
    created as 'queued' to preserve per-chat serialization."""
    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 12009

        # Worker claims item 1000
        work_queue.record_and_enqueue(data_dir, 1000, chat_id, 42, "message")
        worker_item = work_queue.claim_next(data_dir, chat_id, "worker-1")
        assert worker_item is not None

        # New command arrives while worker holds the claim
        _, item_id = work_queue.record_and_enqueue(
            data_dir, 1001, chat_id, 42, "command",
            worker_id="handler-boot",
        )

        # New item must be 'queued' (not 'claimed') because the chat
        # already has a claimed item
        conn = work_queue._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row["state"] == "queued", (
            "Should fall back to queued when chat has existing claimed item"
        )
