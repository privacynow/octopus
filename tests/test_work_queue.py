"""Tests for the durable transport layer (app/work_queue.py)."""

import asyncio
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.workflows.results import TransportStateCorruption
from app.work_queue import (
    _assert_no_invalid_rows_for_chat,
    _claim_queued_item,
    _load_work_item_by_id,
    _reset_transport_db,
    _transport_db,
    _validate_work_item_row,
    _write_tx,
    DiscardResult,
    LeaveClaimed,
    claim_for_update,
    claim_next,
    claim_next_any,
    close_transport_db,
    complete_work_item,
    discard_recovery,
    enqueue_work_item,
    fail_work_item,
    get_latest_pending_recovery,
    get_update_payload,
    has_queued_or_claimed,
    mark_pending_recovery,
    purge_old,
    record_and_enqueue,
    record_update,
    reclaim_for_replay,
    recover_stale_claims,
    supersede_pending_recovery,
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
    complete_work_item(data_dir, first["id"])
    second = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert second is not None
    assert second["update_id"] == 201


def test_record_and_enqueue_preclaim_derived_from_machine(data_dir):
    """Preclaim (create as claimed) only when machine allows claim_inline; impossible rejection raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    # When machine rejects claim_inline in preclaim path, repository raises (no silent fallback to queued).
    record_update(data_dir, 8888, chat_id=1, user_id=42, kind="message")
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state="queued",
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            enqueue_work_item(data_dir, chat_id=1, update_id=8888, worker_id="handler-1")
    assert "claim_inline" in str(exc_info.value) or "rejected" in str(exc_info.value).lower()
    conn = _transport_db(data_dir)
    assert conn.in_transaction is False
    row = conn.execute("SELECT id FROM work_items WHERE update_id = ?", (8888,)).fetchone()
    assert row is None  # _write_tx rolled back; no work item committed

    # When machine allows, item is created as claimed (normal path).
    record_update(data_dir, 8889, chat_id=1, user_id=42, kind="message")
    item_id2 = enqueue_work_item(data_dir, chat_id=1, update_id=8889, worker_id="handler-1")
    row2 = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "claimed"
    assert row2["worker_id"] == "handler-1"


def test_record_and_enqueue_worker_id_none_inserts_queued(data_dir):
    """Repository shape: record_and_enqueue(worker_id=None) always inserts queued."""
    is_new, item_id = record_and_enqueue(
        data_dir, 5001, chat_id=1, user_id=42, kind="message", worker_id=None
    )
    assert is_new is True
    assert item_id is not None
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "queued"


def test_record_and_enqueue_worker_id_claimed_only_when_no_other_claimed(data_dir):
    """Repository shape: record_and_enqueue(worker_id=...) inserts claimed only when chat has no claimed item."""
    # No other claimed -> created as claimed
    is_new, item_id = record_and_enqueue(
        data_dir, 5010, chat_id=1, user_id=42, kind="message", worker_id="handler-1"
    )
    assert is_new is True
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "handler-1"
    # Same chat already has claimed -> next item must be queued
    is_new2, item_id2 = record_and_enqueue(
        data_dir, 5011, chat_id=1, user_id=42, kind="message", worker_id="handler-1"
    )
    assert is_new2 is True
    row2 = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "queued"


def test_enqueue_work_item_matches_record_and_enqueue_initial_state(data_dir):
    """Repository shape: enqueue_work_item and record_and_enqueue use same initial-state semantics."""
    # record_and_enqueue(worker_id=None) -> queued
    _, id1 = record_and_enqueue(data_dir, 5020, chat_id=1, user_id=42, kind="message", worker_id=None)
    # enqueue_work_item(worker_id=None) -> queued
    record_update(data_dir, 5021, chat_id=2, user_id=42, kind="message")
    id2 = enqueue_work_item(data_dir, chat_id=2, update_id=5021, worker_id=None)
    conn = _transport_db(data_dir)
    for iid in (id1, id2):
        row = conn.execute("SELECT state FROM work_items WHERE id = ?", (iid,)).fetchone()
        assert row["state"] == "queued"
    # record_and_enqueue(worker_id=X) with no other claimed -> claimed
    _, id3 = record_and_enqueue(
        data_dir, 5022, chat_id=3, user_id=42, kind="message", worker_id="h1"
    )
    # enqueue_work_item(worker_id=X) with no other claimed -> claimed
    record_update(data_dir, 5023, chat_id=4, user_id=42, kind="message")
    id4 = enqueue_work_item(data_dir, chat_id=4, update_id=5023, worker_id="h1")
    for iid in (id3, id4):
        row = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (iid,)).fetchone()
        assert row["state"] == "claimed"
        assert row["worker_id"] == "h1"


def test_claim_for_update_exact_row_path_already_handled_when_state_changed(data_dir):
    """Repository shape: claim_for_update returns None (already_handled) when item was already claimed by another worker."""
    record_and_enqueue(
        data_dir, 5030, chat_id=1, user_id=42, kind="message", worker_id="handler-1"
    )
    # Same update: handler-1 can claim; different worker cannot
    item1 = claim_for_update(data_dir, chat_id=1, update_id=5030, worker_id="handler-1")
    assert item1 is not None
    assert item1["state"] == "claimed"
    assert item1["worker_id"] == "handler-1"
    item2 = claim_for_update(data_dir, chat_id=1, update_id=5030, worker_id="other-worker")
    assert item2 is None
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT state, worker_id FROM work_items WHERE update_id = 5030"
    ).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "handler-1"


def test_claim_next_returns_none_when_another_worker_claimed(data_dir):
    """Repository shape: shared claim helper returns already_handled (None) when reread shows state changed."""
    record_update(data_dir, 5040, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=5040)
    first = claim_next(data_dir, chat_id=1, worker_id="worker-a")
    assert first is not None
    assert first["state"] == "claimed"
    second = claim_next(data_dir, chat_id=1, worker_id="worker-b")
    assert second is None


def test_shared_claim_helper_raises_corruption_when_reread_still_queued(data_dir):
    """Repository shape: when UPDATE matches 0 rows but reread still shows queued, raise TransportStateCorruption."""
    from unittest.mock import MagicMock, patch

    record_update(data_dir, 5050, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=5050)
    real_conn = _transport_db(data_dir)
    update_seen = [False]

    class ConnWrapper:
        def __init__(self, conn):
            self._conn = conn
        def execute(self, sql, params=()):
            if "UPDATE work_items" in sql and "SET state = ?" in sql and not update_seen[0]:
                update_seen[0] = True
                mock_cur = MagicMock()
                mock_cur.rowcount = 0
                return mock_cur
            return self._conn.execute(sql, params)
        def __getattr__(self, name):
            return getattr(self._conn, name)

    with patch("app.work_queue._transport_db", return_value=ConnWrapper(real_conn)):
        with pytest.raises(TransportStateCorruption) as exc_info:
            claim_next(data_dir, chat_id=1, worker_id="w1")
    assert "queued" in str(exc_info.value).lower()


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
    complete_work_item(data_dir, item_id)

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, completed_at FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"
    assert row["completed_at"] is not None


def test_complete_work_item_failed(data_dir):
    """Failed items store an error message."""
    record_update(data_dir, 401, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=401)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    fail_work_item(data_dir, item_id, error="timeout")

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, error FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "failed"
    assert row["error"] == "timeout"


def test_discard_recovery_result(data_dir):
    """discard_recovery returns DiscardResult.success or already_handled."""
    record_update(data_dir, 403, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=403)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)

    result = discard_recovery(data_dir, item_id)
    assert result == DiscardResult.success

    # Second call: row no longer pending_recovery -> already_handled
    result2 = discard_recovery(data_dir, item_id)
    assert result2 == DiscardResult.already_handled


def test_load_work_item_by_id_raises_on_invalid_state():
    """_load_work_item_by_id raises TransportStateCorruption when row state is invalid."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
        ("item-bogus", 1, 406, "bogus", "2025-01-01T00:00:00"),
    )
    conn.commit()

    with pytest.raises(TransportStateCorruption) as exc_info:
        _load_work_item_by_id(conn, "item-bogus")
    assert "unknown state" in str(exc_info.value) and "bogus" in str(exc_info.value)
    conn.close()


def test_assert_no_invalid_rows_for_chat_raises():
    """assert_no_invalid_rows_for_chat raises TransportStateCorruption when any row has invalid state."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
        ("item-1", 1, 407, "queued", "2025-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
        ("item-2", 1, 408, "bogus", "2025-01-01T00:00:01"),
    )
    conn.commit()

    with pytest.raises(TransportStateCorruption) as exc_info:
        _assert_no_invalid_rows_for_chat(conn, 1)
    assert "unknown state" in str(exc_info.value) and "bogus" in str(exc_info.value)
    conn.close()


def test_complete_work_item_and_fail_work_item(data_dir):
    """complete_work_item marks done; fail_work_item marks failed."""
    record_update(data_dir, 409, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=409)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id)
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"

    record_update(data_dir, 410, chat_id=1, user_id=42, kind="message")
    item_id2 = enqueue_work_item(data_dir, chat_id=1, update_id=410)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    fail_work_item(data_dir, item_id2, error="test_error")
    row2 = conn.execute("SELECT state, error FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "failed"
    assert row2["error"] == "test_error"


# -- Queries ---------------------------------------------------------------

def test_has_queued_or_claimed(data_dir):
    """has_queued_or_claimed reflects current work item state."""
    assert has_queued_or_claimed(data_dir, chat_id=1) is False

    record_update(data_dir, 500, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=500)
    assert has_queued_or_claimed(data_dir, chat_id=1) is True

    item = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert has_queued_or_claimed(data_dir, chat_id=1) is True

    complete_work_item(data_dir, item["id"])
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
    complete_work_item(data_dir, item_id)

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
    complete_work_item(data_dir, item_id)

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


def test_record_and_enqueue_rollback_on_non_integrity_error(data_dir):
    """On non-IntegrityError (e.g. TransportStateCorruption from _insert_initial_work_item), transaction is rolled back and no rows remain."""
    from unittest.mock import patch

    update_id = 21000
    with patch("app.work_queue._insert_initial_work_item", side_effect=TransportStateCorruption("test")):
        with pytest.raises(TransportStateCorruption):
            record_and_enqueue(
                data_dir, update_id=update_id, chat_id=1, user_id=42, kind="message",
            )
    conn = _transport_db(data_dir)
    assert conn.in_transaction is False
    assert conn.execute("SELECT 1 FROM updates WHERE update_id = ?", (update_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM work_items WHERE update_id = ?", (update_id,)).fetchone() is None


def test_assert_no_invalid_rows_raises_when_two_claimed_in_chat(data_dir):
    """_assert_no_invalid_rows_for_chat raises TransportStateCorruption when more than one claimed row exists for the chat."""
    # Use a separate in-memory DB so we can have two claimed rows (production schema has unique index preventing that).
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, worker_id, claimed_at, created_at) VALUES (?, 1, 22001, 'claimed', 'w1', ?, ?)",
        ("id-1", now, now),
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, worker_id, claimed_at, created_at) VALUES (?, 1, 22002, 'claimed', 'w2', ?, ?)",
        ("id-2", now, now),
    )
    conn.commit()
    with pytest.raises(TransportStateCorruption) as exc_info:
        _assert_no_invalid_rows_for_chat(conn, 1)
    assert "2 claimed" in str(exc_info.value) or "claimed work items" in str(exc_info.value)
    conn.close()


def test_fresh_schema_has_one_claimed_per_chat_index(data_dir):
    """Fresh transport DB schema includes partial unique index enforcing at most one claimed row per chat."""
    conn = _transport_db(data_dir)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_one_claimed_per_chat'"
    ).fetchall()
    assert len(rows) == 1


def test_write_tx_rejects_nested_use(data_dir):
    """_write_tx raises RuntimeError when called while already in a transaction."""
    conn = _transport_db(data_dir)
    with pytest.raises(RuntimeError, match="nested transport transaction"):
        with _write_tx(conn):
            with _write_tx(conn):
                pass


# -- Impossible machine rejections surface as corruption (no silent normalization)
# ---------------------------------------------------------------------------


def test_mark_pending_recovery_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition for move_to_pending_recovery, repository raises and rolls back."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3001, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3001, worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            mark_pending_recovery(data_dir, item_id)
    assert "move_to_pending_recovery" in str(exc_info.value) or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "claimed"  # unchanged, tx rolled back


def test_discard_recovery_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition for discard_recovery, repository raises (not already_handled)."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3002, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3002, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            discard_recovery(data_dir, item_id)
    assert "discard_recovery" in str(exc_info.value) or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "pending_recovery"  # unchanged


def test_supersede_pending_recovery_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition for supersede_recovery, repository raises (not return 0)."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3003, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3003, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            supersede_pending_recovery(data_dir, 1)
    assert "supersede" in str(exc_info.value).lower() or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "pending_recovery"


def test_reclaim_for_replay_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition (not blocked_replay) for reclaim_for_replay, repository raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3004, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3004, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            reclaim_for_replay(data_dir, item_id, worker_id="w2")
    assert "reclaim" in str(exc_info.value).lower() or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "pending_recovery"


def test_get_latest_pending_recovery_raises_when_chat_invalid(data_dir):
    """get_latest_pending_recovery asserts chat integrity; structural corruption surfaces as TransportStateCorruption."""
    from unittest.mock import patch
    record_update(data_dir, 3020, chat_id=7, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=7, update_id=3020, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    with patch("app.work_queue._assert_no_invalid_rows_for_chat", side_effect=TransportStateCorruption("test two claimed")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            get_latest_pending_recovery(data_dir, 7)
    assert "test two claimed" in str(exc_info.value) or "two claimed" in str(exc_info.value).lower()


def test_has_queued_or_claimed_raises_when_chat_invalid(data_dir):
    """has_queued_or_claimed asserts chat integrity before returning."""
    from unittest.mock import patch
    with patch("app.work_queue._assert_no_invalid_rows_for_chat", side_effect=TransportStateCorruption("chat corrupt")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            has_queued_or_claimed(data_dir, 8)
    assert "chat corrupt" in str(exc_info.value)


def test_reclaim_for_replay_raises_corruption_when_chat_already_invalid(data_dir):
    """reclaim_for_replay asserts chat integrity; if chat is already invalid we get TransportStateCorruption, not ReclaimBlocked."""
    from unittest.mock import patch
    record_update(data_dir, 3021, chat_id=9, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=9, update_id=3021, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    with patch("app.work_queue._assert_no_invalid_rows_for_chat", side_effect=TransportStateCorruption("chat has two claimed")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            reclaim_for_replay(data_dir, item_id, worker_id="w2")
    assert "chat has two claimed" in str(exc_info.value) or "two claimed" in str(exc_info.value).lower()


def test_supersede_pending_recovery_raises_when_chat_invalid(data_dir):
    """supersede_pending_recovery asserts chat integrity before acting."""
    from unittest.mock import patch
    with patch("app.work_queue._assert_no_invalid_rows_for_chat", side_effect=TransportStateCorruption("invalid chat")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            supersede_pending_recovery(data_dir, 10)
    assert "invalid chat" in str(exc_info.value)


def test_claim_queued_item_returns_none_only_for_other_claimed_for_chat(data_dir):
    """_claim_queued_item returns None only when disposition is other_claimed_for_chat; invalid_transition raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3005, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3005)  # queued
    conn = _transport_db(data_dir)
    with _write_tx(conn):
        with patch("app.work_queue.run_transport_event") as mock_run:
            mock_run.return_value = TransitionResult(
                allowed=False,
                new_state=None,
                disposition=TransportDisposition.invalid_transition,
                reason="test",
            )
            with pytest.raises(TransportStateCorruption):
                _claim_queued_item(
                    conn, item_id=item_id, worker_id="w1",
                    has_other_claimed_for_chat=False, event_name="claim_worker",
                )


def test_complete_work_item_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition for complete, repository raises and rolls back."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3010, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3010, worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            complete_work_item(data_dir, item_id)
    assert "complete" in str(exc_info.value).lower() or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "claimed"


def test_fail_work_item_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition for fail, repository raises and rolls back."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, 3011, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=3011, worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            fail_work_item(data_dir, item_id, "timeout")
    assert "fail" in str(exc_info.value).lower() or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "claimed"


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


async def test_worker_loop_leaves_interrupted_item_claimed(data_dir):
    """Worker interruption should leave the claimed item for restart recovery."""
    from app.worker import worker_loop

    record_update(data_dir, 2200, chat_id=1, user_id=42, kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=42, username="alice"),
                      chat_id=1, text="recover me", attachments=())))
    enqueue_work_item(data_dir, chat_id=1, update_id=2200)

    async def dispatch(kind, event, item):
        raise LeaveClaimed()

    stop = asyncio.Event()

    async def run_then_stop():
        await asyncio.sleep(0.3)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "worker-a", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT state, worker_id FROM work_items WHERE update_id = 2200"
    ).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "worker-a"


# -- Row validation and fail-fast (development-time policy) ----------------

def test_validate_work_item_row_ownerless_claimed():
    """Validator raises TransportStateCorruption for claimed row with worker_id None."""
    with pytest.raises(TransportStateCorruption) as exc_info:
        _validate_work_item_row(
            {"state": "claimed", "worker_id": None, "claimed_at": "2025-01-01T00:00:00Z"},
            "item-1",
        )
    assert "worker_id" in str(exc_info.value).lower()


def test_validate_work_item_row_claimed_without_claimed_at():
    """Validator raises TransportStateCorruption for claimed row with claimed_at None."""
    with pytest.raises(TransportStateCorruption) as exc_info:
        _validate_work_item_row(
            {"state": "claimed", "worker_id": "w1", "claimed_at": None},
            "item-2",
        )
    assert "claimed_at" in str(exc_info.value).lower()


def test_load_work_item_by_id_raises_on_ownerless_claimed():
    """load_work_item_by_id raises when row is claimed but worker_id is NULL (e.g. tampered DB)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, worker_id, claimed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-claimed", 1, 500, "claimed", None, None, "2025-01-01T00:00:00"),
    )
    conn.commit()

    with pytest.raises(TransportStateCorruption) as exc_info:
        _load_work_item_by_id(conn, "item-claimed")
    assert "worker_id" in str(exc_info.value).lower()
    conn.close()


def test_load_work_item_by_id_raises_on_claimed_without_claimed_at():
    """load_work_item_by_id raises when row is claimed but claimed_at is NULL."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, worker_id, claimed_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("item-claimed", 1, 501, "claimed", "w1", None, "2025-01-01T00:00:00"),
    )
    conn.commit()

    with pytest.raises(TransportStateCorruption) as exc_info:
        _load_work_item_by_id(conn, "item-claimed")
    assert "claimed_at" in str(exc_info.value).lower()
    conn.close()


@pytest.mark.asyncio
async def test_worker_loop_stops_on_transport_state_corruption(data_dir):
    """Worker loop must fail fast on TransportStateCorruption (claim path), not spin forever."""
    from app.worker import worker_loop
    from unittest.mock import patch

    record_update(data_dir, 9000, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=9000)

    with patch("app.worker.work_queue.claim_next_any") as mock_claim:
        mock_claim.side_effect = TransportStateCorruption("corrupt row in DB")

        with pytest.raises(TransportStateCorruption, match="corrupt row"):
            await worker_loop(
                data_dir, "w1", lambda k, e, i: None,
                poll_interval=0.05, stop_event=asyncio.Event(),
            )


@pytest.mark.asyncio
async def test_worker_loop_stops_on_dispatch_path_corruption(data_dir):
    """Worker loop must fail fast when TransportStateCorruption is raised during dispatch."""
    from app.worker import worker_loop

    payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id=42, username="u"),
            chat_id=1,
            text="hi",
            attachments=(),
        )
    )
    record_update(data_dir, 9001, chat_id=1, user_id=42, kind="message", payload=payload)
    enqueue_work_item(data_dir, chat_id=1, update_id=9001)

    async def dispatch_raises_corruption(kind, event, item):
        raise TransportStateCorruption("boom during dispatch")

    with pytest.raises(TransportStateCorruption, match="boom during dispatch"):
        await asyncio.wait_for(
            worker_loop(
                data_dir, "w1", dispatch_raises_corruption,
                poll_interval=0.05, stop_event=asyncio.Event(),
            ),
            timeout=3.0,
        )

    # Item must still be claimed (worker did not complete it; loop exited).
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT state FROM work_items WHERE update_id = 9001"
    ).fetchone()
    assert row is not None
    assert row["state"] == "claimed"


def test_complete_work_item_exact_cas_does_not_overwrite_later_claim(data_dir):
    """Exact compare-and-update: a stale complete (loaded queued) must not overwrite a later claim.

    Simulates: A claims item; B had stale read of queued and runs complete_work_item.
    B's UPDATE WHERE state='queued' matches 0 rows; B rereads, sees claimed, returns already_handled.
    Item must remain claimed.
    """
    from unittest.mock import patch

    record_update(data_dir, 9100, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=9100)
    claimed_item = claim_next(data_dir, chat_id=1, worker_id="worker-a")
    assert claimed_item is not None
    assert claimed_item["id"] == item_id
    assert claimed_item["state"] == "claimed"

    # Stale load: pretend the first load in complete_work_item sees queued (race).
    stale_row = {
        "id": item_id,
        "chat_id": 1,
        "update_id": 9100,
        "state": "queued",
        "worker_id": None,
        "claimed_at": None,
        "completed_at": None,
        "error": None,
        "created_at": "2025-01-01T00:00:00+00:00",
    }

    with patch("app.work_queue._load_work_item_by_id", return_value=stale_row):
        complete_work_item(data_dir, item_id)

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "worker-a"


def test_meta_without_schema_version_fails_fast(data_dir):
    """When meta table exists but has no schema_version key, open fails with clear error."""
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('other_key', 'x')"
    )
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()


def test_schema_version_mismatch_raises_unsupported(data_dir):
    """Opening transport.db with wrong schema version raises RuntimeError (unsupported schema/layout)."""
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', '1')"
    )
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()


def test_forged_v2_db_with_wrong_index_rejected(data_dir):
    """Existing DB with schema_version=2 but idx_one_claimed_per_chat wrong (non-unique, wrong column) is rejected."""
    from app.work_queue import _SCHEMA_VERSION
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    # Forged: same index name but non-unique and on update_id, no partial predicate
    conn.execute(
        "CREATE INDEX idx_one_claimed_per_chat ON work_items(update_id)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()


def test_forged_v2_db_wrong_partial_predicate_rejected(data_dir):
    """Existing DB with idx_one_claimed_per_chat with wrong WHERE (e.g. state != 'claimed') is rejected."""
    from app.work_queue import _SCHEMA_VERSION
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_one_claimed_per_chat ON work_items(chat_id) WHERE state != 'claimed'"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()
