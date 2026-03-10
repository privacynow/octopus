"""Tests for the durable transport layer (app/work_queue.py)."""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.work_queue import (
    _reset_transport_db,
    _transport_db,
    claim_next,
    close_transport_db,
    complete_work_item,
    enqueue_work_item,
    has_queued_or_claimed,
    get_update_payload,
    purge_old,
    record_update,
    recover_stale_claims,
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
