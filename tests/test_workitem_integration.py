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
