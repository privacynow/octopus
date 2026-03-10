"""Tests for the durable transport layer (app/work_queue.py)."""

import asyncio
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.work_queue import (
    _reset_transport_db,
    _transport_db,
    claim_next,
    claim_next_any,
    close_transport_db,
    complete_work_item,
    enqueue_work_item,
    has_queued_or_claimed,
    get_update_payload,
    purge_old,
    record_and_enqueue,
    record_update,
    recover_stale_claims,
    update_payload,
)
from app.transport import (
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
    InboundAttachment,
    serialize_inbound,
    deserialize_inbound,
)


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        yield d
        close_transport_db(d)


# -- Update journal --------------------------------------------------------

def test_record_update_idempotent(data_dir):
    """Inserting the same update_id twice: first returns True, second returns False."""
    assert record_update(data_dir, 1001, chat_id=1, user_id=42, kind="message") is True
    assert record_update(data_dir, 1001, chat_id=1, user_id=42, kind="message") is False


def test_record_update_stores_payload(data_dir):
    """Payload is stored and retrievable."""
    record_update(data_dir, 2001, chat_id=1, user_id=42, kind="message", payload='{"text":"hello"}')
    assert get_update_payload(data_dir, 2001) == '{"text":"hello"}'


def test_get_update_payload_missing(data_dir):
    assert get_update_payload(data_dir, 9999) is None


# -- Work items: enqueue and claim -----------------------------------------

def test_enqueue_and_claim(data_dir):
    """Enqueue a work item, claim it, verify state transitions."""
    record_update(data_dir, 100, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=100)
    assert item_id

    item = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert item is not None
    assert item["id"] == item_id
    assert item["state"] == "claimed"
    assert item["worker_id"] == "w1"


def test_claim_blocks_second_claim_same_chat(data_dir):
    """Two queued items for same chat: only one claimable at a time."""
    record_update(data_dir, 200, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 201, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=200)
    enqueue_work_item(data_dir, chat_id=1, update_id=201)

    first = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert first is not None

    # Second claim for same chat fails while first is claimed
    second = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert second is None

    # Complete the first, second becomes claimable
    complete_work_item(data_dir, first["id"], state="done")
    second = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert second is not None
    assert second["update_id"] == 201


def test_claim_allows_different_chat(data_dir):
    """Items for different chats can be claimed concurrently."""
    record_update(data_dir, 300, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 301, chat_id=2, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=300)
    enqueue_work_item(data_dir, chat_id=2, update_id=301)

    first = claim_next(data_dir, chat_id=1, worker_id="w1")
    second = claim_next(data_dir, chat_id=2, worker_id="w1")
    assert first is not None
    assert second is not None


def test_claim_nothing_queued(data_dir):
    """Claiming with nothing queued returns None."""
    assert claim_next(data_dir, chat_id=1, worker_id="w1") is None


def test_complete_work_item_done(data_dir):
    """Complete marks item as done."""
    record_update(data_dir, 400, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=400)
    item = claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id, state="done")

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, completed_at FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"
    assert row["completed_at"] is not None


def test_complete_work_item_failed(data_dir):
    """Failed items store an error message."""
    record_update(data_dir, 401, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=401)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id, state="failed", error="timeout")

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, error FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "failed"
    assert row["error"] == "timeout"


# -- Queries ---------------------------------------------------------------

def test_has_queued_or_claimed(data_dir):
    """has_queued_or_claimed reflects current work item state."""
    assert has_queued_or_claimed(data_dir, chat_id=1) is False

    record_update(data_dir, 500, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=500)
    assert has_queued_or_claimed(data_dir, chat_id=1) is True

    item = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert has_queued_or_claimed(data_dir, chat_id=1) is True

    complete_work_item(data_dir, item["id"], state="done")
    assert has_queued_or_claimed(data_dir, chat_id=1) is False


# -- Recovery and retention ------------------------------------------------

def test_recover_stale_claims_different_worker(data_dir):
    """Stale claims by a different worker are requeued."""
    record_update(data_dir, 600, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=600)
    claim_next(data_dir, chat_id=1, worker_id="old-worker")

    requeued = recover_stale_claims(data_dir, current_worker_id="new-worker")
    assert requeued == 1

    # Item is now claimable again
    item = claim_next(data_dir, chat_id=1, worker_id="new-worker")
    assert item is not None


def test_recover_stale_claims_expired(data_dir):
    """Claims held too long by the current worker are requeued."""
    record_update(data_dir, 601, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=601)
    claim_next(data_dir, chat_id=1, worker_id="w1")

    # Backdate the claimed_at
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE work_items SET claimed_at = ? WHERE update_id = 601", (old_time,))
    conn.commit()

    requeued = recover_stale_claims(data_dir, current_worker_id="w1", max_age_seconds=300)
    assert requeued == 1


def test_recover_stale_claims_fresh_not_touched(data_dir):
    """Fresh claims by the current worker are not requeued."""
    record_update(data_dir, 602, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=602)
    claim_next(data_dir, chat_id=1, worker_id="w1")

    requeued = recover_stale_claims(data_dir, current_worker_id="w1", max_age_seconds=300)
    assert requeued == 0


def test_purge_old(data_dir):
    """Purge removes old completed items and their updates."""
    record_update(data_dir, 700, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=700)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id, state="done")

    # Backdate
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE work_items SET created_at = ? WHERE id = ?", (old_time, item_id))
    conn.execute("UPDATE updates SET received_at = ? WHERE update_id = 700", (old_time,))
    conn.commit()

    deleted = purge_old(data_dir, older_than_hours=24)
    assert deleted == 1

    # Verify both tables are clean
    assert conn.execute("SELECT count(*) FROM work_items").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM updates").fetchone()[0] == 0


def test_purge_keeps_recent(data_dir):
    """Purge does not remove recent completed items."""
    record_update(data_dir, 701, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=701)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id, state="done")

    deleted = purge_old(data_dir, older_than_hours=24)
    assert deleted == 0


def test_purge_keeps_active(data_dir):
    """Purge does not touch queued or claimed items regardless of age."""
    record_update(data_dir, 702, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=702)

    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE work_items SET created_at = ?", (old_time,))
    conn.commit()

    deleted = purge_old(data_dir, older_than_hours=24)
    assert deleted == 0


# -- Serialization round-trip ----------------------------------------------

def test_serialize_message_round_trip():
    """InboundMessage survives serialize/deserialize."""
    msg = InboundMessage(
        user=InboundUser(id=42, username="alice"),
        chat_id=1, text="hello world",
        attachments=(
            InboundAttachment(path=Path("/tmp/photo.jpg"), original_name="photo.jpg",
                              is_image=True, mime_type="image/jpeg"),
        ),
    )
    payload = serialize_inbound(msg)
    restored = deserialize_inbound("message", payload)
    assert isinstance(restored, InboundMessage)
    assert restored.user.id == 42
    assert restored.user.username == "alice"
    assert restored.text == "hello world"
    assert len(restored.attachments) == 1
    assert restored.attachments[0].original_name == "photo.jpg"


def test_serialize_command_round_trip():
    """InboundCommand survives serialize/deserialize."""
    cmd = InboundCommand(
        user=InboundUser(id=42, username="alice"),
        chat_id=1, command="help", args=("topic",),
    )
    payload = serialize_inbound(cmd)
    restored = deserialize_inbound("command", payload)
    assert isinstance(restored, InboundCommand)
    assert restored.command == "help"
    assert restored.args == ("topic",)


def test_serialize_callback_round_trip():
    """InboundCallback survives serialize/deserialize."""
    cb = InboundCallback(
        user=InboundUser(id=42, username="alice"),
        chat_id=1, data="approval_approve",
    )
    payload = serialize_inbound(cb)
    restored = deserialize_inbound("callback", payload)
    assert isinstance(restored, InboundCallback)
    assert restored.data == "approval_approve"


# -- One work item per update ----------------------------------------------

def test_one_work_item_per_update(data_dir):
    """UNIQUE constraint on update_id prevents duplicate work items."""
    record_update(data_dir, 800, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=800)
    with pytest.raises(Exception):
        enqueue_work_item(data_dir, chat_id=1, update_id=800)


# -- update_payload --------------------------------------------------------

def test_update_payload(data_dir):
    """update_payload replaces the stored payload for an existing update."""
    record_update(data_dir, 900, chat_id=1, user_id=42, kind="message", payload="{}")
    assert get_update_payload(data_dir, 900) == "{}"

    update_payload(data_dir, 900, '{"text":"hello"}')
    assert get_update_payload(data_dir, 900) == '{"text":"hello"}'


# -- claim_next_any --------------------------------------------------------

def test_claim_next_any_empty(data_dir):
    """claim_next_any returns None on empty queue."""
    assert claim_next_any(data_dir, "w1") is None


def test_claim_next_any_single_item(data_dir):
    """claim_next_any claims a single queued item."""
    record_update(data_dir, 1000, chat_id=1, user_id=42, kind="message", payload='{"text":"hi"}')
    enqueue_work_item(data_dir, chat_id=1, update_id=1000)

    item = claim_next_any(data_dir, "w1")
    assert item is not None
    assert item["chat_id"] == 1
    assert item["state"] == "claimed"
    assert item["kind"] == "message"
    assert item["payload"] == '{"text":"hi"}'


def test_claim_next_any_skips_busy_chat(data_dir):
    """claim_next_any skips chats that already have a claimed item."""
    # Chat 1: two items
    record_update(data_dir, 1100, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 1101, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=1100)
    enqueue_work_item(data_dir, chat_id=1, update_id=1101)

    first = claim_next_any(data_dir, "w1")
    assert first is not None
    assert first["chat_id"] == 1

    # Second claim should return None (only chat 1, and it's busy)
    second = claim_next_any(data_dir, "w1")
    assert second is None


def test_claim_next_any_cross_chat(data_dir):
    """claim_next_any claims items from different chats concurrently."""
    record_update(data_dir, 1200, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 1201, chat_id=2, user_id=42, kind="command")
    enqueue_work_item(data_dir, chat_id=1, update_id=1200)
    enqueue_work_item(data_dir, chat_id=2, update_id=1201)

    first = claim_next_any(data_dir, "w1")
    assert first is not None

    second = claim_next_any(data_dir, "w1")
    assert second is not None

    # Different chats
    assert first["chat_id"] != second["chat_id"]


def test_claim_next_any_includes_payload(data_dir):
    """claim_next_any returns kind and payload from the joined updates table."""
    msg = InboundMessage(
        user=InboundUser(id=42, username="alice"),
        chat_id=5, text="test message",
        attachments=(),
    )
    payload = serialize_inbound(msg)
    record_update(data_dir, 1300, chat_id=5, user_id=42, kind="message", payload=payload)
    enqueue_work_item(data_dir, chat_id=5, update_id=1300)

    item = claim_next_any(data_dir, "w1")
    assert item["kind"] == "message"
    restored = deserialize_inbound(item["kind"], item["payload"])
    assert isinstance(restored, InboundMessage)
    assert restored.text == "test message"
    assert restored.user.id == 42


# -- Worker loop -----------------------------------------------------------

async def test_worker_loop_processes_items(data_dir):
    """Worker loop claims and dispatches items from the queue."""
    from app.worker import worker_loop

    # Set up two items in different chats
    record_update(data_dir, 1400, chat_id=1, user_id=42, kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=1, text="hello", attachments=())))
    enqueue_work_item(data_dir, chat_id=1, update_id=1400)

    record_update(data_dir, 1401, chat_id=2, user_id=42, kind="command",
                  payload=serialize_inbound(InboundCommand(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=2, command="help", args=())))
    enqueue_work_item(data_dir, chat_id=2, update_id=1401)

    dispatched = []

    async def dispatch(kind, event, item):
        dispatched.append((kind, event, item["chat_id"]))

    stop = asyncio.Event()

    async def run_then_stop():
        # Let the worker process items, then stop
        await asyncio.sleep(0.2)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "w1", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    assert len(dispatched) == 2
    kinds = {d[0] for d in dispatched}
    assert kinds == {"message", "command"}

    # Both items should be completed
    conn = _transport_db(data_dir)
    rows = conn.execute("SELECT state FROM work_items ORDER BY update_id").fetchall()
    assert all(r["state"] == "done" for r in rows)


async def test_worker_loop_handles_dispatch_failure(data_dir):
    """Worker loop marks items as failed when dispatch raises."""
    from app.worker import worker_loop

    record_update(data_dir, 1500, chat_id=1, user_id=42, kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=1, text="fail", attachments=())))
    enqueue_work_item(data_dir, chat_id=1, update_id=1500)

    async def failing_dispatch(kind, event, item):
        raise RuntimeError("provider crash")

    stop = asyncio.Event()
    async def run_then_stop():
        await asyncio.sleep(0.2)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "w1", failing_dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, error FROM work_items WHERE update_id = 1500").fetchone()
    assert row["state"] == "failed"
    assert "provider crash" in row["error"]


async def test_worker_loop_handles_bad_payload(data_dir):
    """Worker loop marks items as failed when payload can't be deserialized."""
    from app.worker import worker_loop

    record_update(data_dir, 1600, chat_id=1, user_id=42, kind="message",
                  payload="not-valid-json")
    enqueue_work_item(data_dir, chat_id=1, update_id=1600)

    dispatched = []
    async def dispatch(kind, event, item):
        dispatched.append(kind)

    stop = asyncio.Event()
    async def run_then_stop():
        await asyncio.sleep(0.2)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "w1", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    # Dispatch should not have been called (deserialization failed)
    assert len(dispatched) == 0

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, error FROM work_items WHERE update_id = 1600").fetchone()
    assert row["state"] == "failed"
    assert row["error"] == "deserialize_error"


async def test_worker_loop_respects_per_chat_serialization(data_dir):
    """Worker loop processes items from the same chat in order."""
    from app.worker import worker_loop

    # Two items in same chat
    for uid in (1700, 1701):
        record_update(data_dir, uid, chat_id=1, user_id=42, kind="message",
                      payload=serialize_inbound(InboundMessage(
                          user=InboundUser(id=42, username="alice"),
                          chat_id=1, text=f"msg-{uid}", attachments=())))
        enqueue_work_item(data_dir, chat_id=1, update_id=uid)

    order = []
    async def dispatch(kind, event, item):
        order.append(item["update_id"])

    stop = asyncio.Event()
    async def run_then_stop():
        await asyncio.sleep(0.3)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "w1", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    assert order == [1700, 1701]


# -- Handler integration: payload storage ----------------------------------

def test_handler_dedup_stores_command_payload(data_dir):
    """_dedup_update with a payload stores it in the update journal."""
    cmd = InboundCommand(
        user=InboundUser(id=42, username="alice"),
        chat_id=1, command="help", args=("skills",),
    )
    payload = serialize_inbound(cmd)
    record_update(data_dir, 1800, chat_id=1, user_id=42, kind="command", payload=payload)

    stored = get_update_payload(data_dir, 1800)
    restored = deserialize_inbound("command", stored)
    assert isinstance(restored, InboundCommand)
    assert restored.command == "help"
    assert restored.args == ("skills",)


def test_recovery_after_crash(data_dir):
    """Simulate crash: items claimed by old worker are recovered and re-claimable."""
    # Worker "old" claims an item then "crashes"
    record_update(data_dir, 1900, chat_id=1, user_id=42, kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=1, text="before crash", attachments=())))
    enqueue_work_item(data_dir, chat_id=1, update_id=1900)
    item = claim_next(data_dir, chat_id=1, worker_id="old-worker")
    assert item is not None

    # Verify it's not claimable while held
    assert claim_next(data_dir, chat_id=1, worker_id="new-worker") is None

    # New worker starts, recovers stale claims
    recovered = recover_stale_claims(data_dir, current_worker_id="new-worker")
    assert recovered == 1

    # Now it's claimable by the new worker
    item = claim_next_any(data_dir, "new-worker")
    assert item is not None
    assert item["update_id"] == 1900

    # And the payload is intact
    restored = deserialize_inbound(item["kind"], item["payload"])
    assert isinstance(restored, InboundMessage)
    assert restored.text == "before crash"


# -- REGRESSION: atomic record+enqueue ------------------------------------

def test_record_and_enqueue_atomic_new(data_dir):
    """record_and_enqueue creates both update and work item atomically."""
    is_new, item_id = record_and_enqueue(
        data_dir, update_id=2000, chat_id=1, user_id=42,
        kind="message", payload='{"text":"atomic"}',
    )
    assert is_new is True
    assert item_id is not None

    # Both rows exist
    assert get_update_payload(data_dir, 2000) == '{"text":"atomic"}'
    assert has_queued_or_claimed(data_dir, chat_id=1) is True


def test_record_and_enqueue_duplicate(data_dir):
    """record_and_enqueue rejects duplicate update_id — no orphan update row."""
    is_new, item_id = record_and_enqueue(
        data_dir, update_id=2001, chat_id=1, user_id=42, kind="message",
    )
    assert is_new is True

    # Second call for same update_id
    is_new2, item_id2 = record_and_enqueue(
        data_dir, update_id=2001, chat_id=1, user_id=42, kind="message",
    )
    assert is_new2 is False
    assert item_id2 is None


def test_record_and_enqueue_no_orphan_update(data_dir):
    """After duplicate rejection, redelivery must NOT see a ghost update row
    with zero work items (the original bug)."""
    # First: atomic insert succeeds
    record_and_enqueue(data_dir, update_id=2002, chat_id=1, user_id=42, kind="message")

    # Verify work item exists
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT count(*) FROM work_items WHERE update_id = 2002"
    ).fetchone()
    assert row[0] == 1

    # Simulate: redelivery returns duplicate
    is_new, _ = record_and_enqueue(
        data_dir, update_id=2002, chat_id=1, user_id=42, kind="message",
    )
    assert is_new is False
    # Still exactly 1 work item
    row = conn.execute(
        "SELECT count(*) FROM work_items WHERE update_id = 2002"
    ).fetchone()
    assert row[0] == 1


# -- REGRESSION: worker replay with real dispatch -------------------------

async def test_worker_replay_calls_dispatch_for_message(data_dir):
    """Worker loop calls dispatch (not just logs) for recovered messages,
    proving the recovered work item is actually processed."""
    from app.worker import worker_loop

    record_update(data_dir, 2100, chat_id=1, user_id=42, kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=1, text="replay me", attachments=())))
    enqueue_work_item(data_dir, chat_id=1, update_id=2100)
    # Claim by old worker, then recover
    claim_next(data_dir, chat_id=1, worker_id="old-worker")
    recover_stale_claims(data_dir, current_worker_id="new-worker")

    dispatched = []
    async def dispatch(kind, event, item):
        dispatched.append((kind, event.text if hasattr(event, "text") else None))

    stop = asyncio.Event()
    async def run_then_stop():
        await asyncio.sleep(0.3)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "new-worker", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    # Dispatch was called (not silently dropped)
    assert len(dispatched) == 1
    assert dispatched[0] == ("message", "replay me")

    # Item is marked done
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state FROM work_items WHERE update_id = 2100").fetchone()
    assert row["state"] == "done"
