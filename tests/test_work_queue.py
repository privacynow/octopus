"""Tests for the durable transport layer (app/work_queue.py)."""

import asyncio
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.workflows.results import TransportStateCorruption
from app.work_queue import (
    DiscardResult,
    LeaveClaimed,
    debug_transport_connection,
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
from app.work_queue_sqlite_impl import (
    _SCHEMA_VERSION,
    _assert_no_invalid_rows_for_conversation,
    _claim_queued_item,
    _load_work_item_by_id,
    _run_migrations,
    _validate_work_item_row,
    _write_tx,
)
from app.runtime.inbound_types import (
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
    InboundAttachment,
    serialize_inbound,
    deserialize_inbound,
)


def _conv(value):
    return telegram_conversation_key(value)


def _actor(value):
    return telegram_actor_key(value)


def _event(value):
    return telegram_event_id(value)


def _transport_db(data_dir):
    """SQLite transport DB for tests; use runtime backend store."""
    return debug_transport_connection(data_dir)


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        yield d
        close_transport_db(d)


# -- Update journal --------------------------------------------------------

def test_record_update_idempotent(data_dir):
    """Inserting the same event_id twice: first returns True, second returns False."""
    assert record_update(data_dir, _event(1001), conversation_key=_conv(1), actor_key=_actor(42), kind="message") is True
    assert record_update(data_dir, _event(1001), conversation_key=_conv(1), actor_key=_actor(42), kind="message") is False


def test_record_update_stores_payload(data_dir):
    """Payload is stored and retrievable."""
    record_update(data_dir, _event(2001), conversation_key=_conv(1), actor_key=_actor(42), kind="message", payload='{"text":"hello"}')
    assert get_update_payload(data_dir, _event(2001)) == '{"text":"hello"}'


def test_get_update_payload_missing(data_dir):
    assert get_update_payload(data_dir, _event(9999)) is None


# -- Work items: enqueue and claim -----------------------------------------

def test_enqueue_and_claim(data_dir):
    """Enqueue a work item, claim it, verify state transitions."""
    record_update(data_dir, _event(100), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(100))
    assert item_id

    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert item is not None
    assert item["id"] == item_id
    assert item["state"] == "claimed"
    assert item["worker_id"] == "w1"


def test_claim_blocks_second_claim_same_chat(data_dir):
    """Two queued items for same chat: only one claimable at a time."""
    record_update(data_dir, _event(200), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(201), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(200))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(201))

    first = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert first is not None

    # Second claim for same chat fails while first is claimed
    second = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert second is None

    # Complete the first, second becomes claimable
    complete_work_item(data_dir, first["id"])
    second = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert second is not None
    assert second["event_id"] == _event(201)


def test_record_and_enqueue_preclaim_derived_from_machine(data_dir):
    """Preclaim (create as claimed) only when machine allows claim_inline; impossible rejection raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    # When machine rejects claim_inline in preclaim path, repository raises (no silent fallback to queued).
    record_update(data_dir, _event(8888), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state="queued",
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(8888), worker_id="handler-1")
    assert "claim_inline" in str(exc_info.value) or "rejected" in str(exc_info.value).lower()
    conn = _transport_db(data_dir)
    assert conn.in_transaction is False
    row = conn.execute("SELECT id FROM work_items WHERE event_id = ?", (_event(8888),)).fetchone()
    assert row is None  # _write_tx rolled back; no work item committed

    # When machine allows, item is created as claimed (normal path).
    record_update(data_dir, _event(8889), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id2 = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(8889), worker_id="handler-1")
    row2 = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "claimed"
    assert row2["worker_id"] == "handler-1"


def test_record_and_enqueue_worker_id_none_inserts_queued(data_dir):
    """Repository shape: record_and_enqueue(worker_id=None) always inserts queued."""
    is_new, item_id = record_and_enqueue(
        data_dir, _event(5001), conversation_key=_conv(1), actor_key=_actor(42), kind="message", worker_id=None
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
        data_dir, _event(5010), conversation_key=_conv(1), actor_key=_actor(42), kind="message", worker_id="handler-1"
    )
    assert is_new is True
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "handler-1"
    # Same chat already has claimed -> next item must be queued
    is_new2, item_id2 = record_and_enqueue(
        data_dir, _event(5011), conversation_key=_conv(1), actor_key=_actor(42), kind="message", worker_id="handler-1"
    )
    assert is_new2 is True
    row2 = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "queued"


def test_enqueue_work_item_matches_record_and_enqueue_initial_state(data_dir):
    """Repository shape: enqueue_work_item and record_and_enqueue use same initial-state semantics."""
    # record_and_enqueue(worker_id=None) -> queued
    _, id1 = record_and_enqueue(data_dir, _event(5020), conversation_key=_conv(1), actor_key=_actor(42), kind="message", worker_id=None)
    # enqueue_work_item(worker_id=None) -> queued
    record_update(data_dir, _event(5021), conversation_key=_conv(2), actor_key=_actor(42), kind="message")
    id2 = enqueue_work_item(data_dir, conversation_key=_conv(2), event_id=_event(5021), worker_id=None)
    conn = _transport_db(data_dir)
    for iid in (id1, id2):
        row = conn.execute("SELECT state FROM work_items WHERE id = ?", (iid,)).fetchone()
        assert row["state"] == "queued"
    # record_and_enqueue(worker_id=X) with no other claimed -> claimed
    _, id3 = record_and_enqueue(
        data_dir, _event(5022), conversation_key=_conv(3), actor_key=_actor(42), kind="message", worker_id="h1"
    )
    # enqueue_work_item(worker_id=X) with no other claimed -> claimed
    record_update(data_dir, _event(5023), conversation_key=_conv(4), actor_key=_actor(42), kind="message")
    id4 = enqueue_work_item(data_dir, conversation_key=_conv(4), event_id=_event(5023), worker_id="h1")
    for iid in (id3, id4):
        row = conn.execute("SELECT state, worker_id FROM work_items WHERE id = ?", (iid,)).fetchone()
        assert row["state"] == "claimed"
        assert row["worker_id"] == "h1"


def test_claim_for_update_exact_row_path_already_handled_when_state_changed(data_dir):
    """Repository shape: claim_for_update returns None (already_handled) when item was already claimed by another worker."""
    record_and_enqueue(
        data_dir, _event(5030), conversation_key=_conv(1), actor_key=_actor(42), kind="message", worker_id="handler-1"
    )
    # Same update: handler-1 can claim; different worker cannot
    item1 = claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(5030), worker_id="handler-1")
    assert item1 is not None
    assert item1["state"] == "claimed"
    assert item1["worker_id"] == "handler-1"
    item2 = claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(5030), worker_id="other-worker")
    assert item2 is None
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT state, worker_id FROM work_items WHERE event_id = ?",
        (_event(5030),),
    ).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "handler-1"


def test_claim_next_returns_none_when_another_worker_claimed(data_dir):
    """Repository shape: shared claim helper returns already_handled (None) when reread shows state changed."""
    record_update(data_dir, _event(5040), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(5040))
    first = claim_next(data_dir, conversation_key=_conv(1), worker_id="worker-a")
    assert first is not None
    assert first["state"] == "claimed"
    second = claim_next(data_dir, conversation_key=_conv(1), worker_id="worker-b")
    assert second is None


def test_shared_claim_helper_raises_corruption_when_reread_still_queued(data_dir):
    """Repository shape: when UPDATE matches 0 rows but reread still shows queued, raise TransportStateCorruption."""
    from unittest.mock import MagicMock, patch
    from app import runtime_backend

    record_update(data_dir, _event(5050), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(5050))
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

    store = runtime_backend.transport_store()
    with patch.object(store, "_transport_db", return_value=ConnWrapper(real_conn)):
        with pytest.raises(TransportStateCorruption) as exc_info:
            claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert "queued" in str(exc_info.value).lower()


def test_claim_allows_different_chat(data_dir):
    """Items for different chats can be claimed concurrently."""
    record_update(data_dir, _event(300), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(301), conversation_key=_conv(2), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(300))
    enqueue_work_item(data_dir, conversation_key=_conv(2), event_id=_event(301))

    first = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    second = claim_next(data_dir, conversation_key=_conv(2), worker_id="w1")
    assert first is not None
    assert second is not None


def test_claim_nothing_queued(data_dir):
    """Claiming with nothing queued returns None."""
    assert claim_next(data_dir, conversation_key=_conv(1), worker_id="w1") is None


def test_complete_work_item_done(data_dir):
    """Complete marks item as done."""
    record_update(data_dir, _event(400), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(400))
    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    complete_work_item(data_dir, item_id)

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, completed_at FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"
    assert row["completed_at"] is not None


def test_complete_work_item_failed(data_dir):
    """Failed items store an error message."""
    record_update(data_dir, _event(401), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(401))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    fail_work_item(data_dir, item_id, error="timeout")

    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state, error FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "failed"
    assert row["error"] == "timeout"


def test_discard_recovery_result(data_dir):
    """discard_recovery returns DiscardResult.success or already_handled."""
    record_update(data_dir, _event(403), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(403))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
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
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) VALUES (?, ?, ?, ?, ?, 'fresh')",
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
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) VALUES (?, ?, ?, ?, ?, 'fresh')",
        ("item-1", 1, 407, "queued", "2025-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, created_at, dispatch_mode) VALUES (?, ?, ?, ?, ?, 'fresh')",
        ("item-2", 1, 408, "bogus", "2025-01-01T00:00:01"),
    )
    conn.commit()

    with pytest.raises(TransportStateCorruption) as exc_info:
        _assert_no_invalid_rows_for_conversation(conn, 1)
    assert "unknown state" in str(exc_info.value) and "bogus" in str(exc_info.value)
    conn.close()


def test_complete_work_item_and_fail_work_item(data_dir):
    """complete_work_item marks done; fail_work_item marks failed."""
    record_update(data_dir, _event(409), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(409))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    complete_work_item(data_dir, item_id)
    conn = _transport_db(data_dir)
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"

    record_update(data_dir, _event(410), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id2 = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(410))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    fail_work_item(data_dir, item_id2, error="test_error")
    row2 = conn.execute("SELECT state, error FROM work_items WHERE id = ?", (item_id2,)).fetchone()
    assert row2["state"] == "failed"
    assert row2["error"] == "test_error"


# -- Queries ---------------------------------------------------------------

def test_has_queued_or_claimed(data_dir):
    """has_queued_or_claimed reflects current work item state."""
    assert has_queued_or_claimed(data_dir, conversation_key=_conv(1)) is False

    record_update(data_dir, _event(500), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(500))
    assert has_queued_or_claimed(data_dir, conversation_key=_conv(1)) is True

    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert has_queued_or_claimed(data_dir, conversation_key=_conv(1)) is True

    complete_work_item(data_dir, item["id"])
    assert has_queued_or_claimed(data_dir, conversation_key=_conv(1)) is False


# -- Recovery and retention ------------------------------------------------

def test_recover_stale_claims_different_worker_after_ttl(data_dir):
    """Age-expired claims recover even when owned by another worker."""
    record_update(data_dir, _event(600), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(600))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="old-worker")

    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE work_items SET claimed_at = ? WHERE event_id = ?", (old_time, _event(600)))
    conn.commit()

    requeued = recover_stale_claims(data_dir, current_worker_id="new-worker", max_age_seconds=300)
    assert requeued == 1

    # Item is now claimable again
    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="new-worker")
    assert item is not None


def test_recover_stale_claims_expired(data_dir):
    """Claims held too long by the current worker are requeued."""
    record_update(data_dir, _event(601), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(601))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")

    # Backdate the claimed_at
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE work_items SET claimed_at = ? WHERE event_id = ?", (old_time, _event(601)))
    conn.commit()

    requeued = recover_stale_claims(data_dir, current_worker_id="w1", max_age_seconds=300)
    assert requeued == 1


def test_recover_stale_claims_fresh_not_touched(data_dir):
    """Fresh claims by the current worker are not requeued."""
    record_update(data_dir, _event(602), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(602))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")

    requeued = recover_stale_claims(data_dir, current_worker_id="w1", max_age_seconds=300)
    assert requeued == 0


def test_recover_stale_claims_live_other_worker_not_touched(data_dir):
    """A live claim owned by another worker is not stale until the lease expires."""
    record_update(data_dir, _event(603), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(603))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="worker-a")

    requeued = recover_stale_claims(data_dir, current_worker_id="worker-b", max_age_seconds=300)
    assert requeued == 0


def test_purge_old(data_dir):
    """Purge removes old completed items and their updates."""
    record_update(data_dir, _event(700), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(700))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    complete_work_item(data_dir, item_id)

    # Backdate
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE work_items SET created_at = ? WHERE id = ?", (old_time, item_id))
    conn.execute("UPDATE updates SET received_at = ? WHERE event_id = ?", (old_time, _event(700)))
    conn.commit()

    deleted = purge_old(data_dir, older_than_hours=24)
    assert deleted == 1

    # Verify both tables are clean
    assert conn.execute("SELECT count(*) FROM work_items").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM updates").fetchone()[0] == 0


def test_purge_keeps_recent(data_dir):
    """Purge does not remove recent completed items."""
    record_update(data_dir, _event(701), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(701))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    complete_work_item(data_dir, item_id)

    deleted = purge_old(data_dir, older_than_hours=24)
    assert deleted == 0


def test_purge_keeps_active(data_dir):
    """Purge does not touch queued or claimed items regardless of age."""
    record_update(data_dir, _event(702), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(702))

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
        user=InboundUser(id=_actor(42), username="alice"),
        conversation_key=_conv(1), text="hello world",
        attachments=(
            InboundAttachment(path=Path("/tmp/photo.jpg"), original_name="photo.jpg",
                              is_image=True, mime_type="image/jpeg"),
        ),
    )
    payload = serialize_inbound(msg)
    restored = deserialize_inbound("message", payload)
    assert isinstance(restored, InboundMessage)
    assert restored.user.id == _actor(42)
    assert restored.user.username == "alice"
    assert restored.text == "hello world"
    assert len(restored.attachments) == 1
    assert restored.attachments[0].original_name == "photo.jpg"


def test_serialize_command_round_trip():
    """InboundCommand survives serialize/deserialize."""
    cmd = InboundCommand(
        user=InboundUser(id=_actor(42), username="alice"),
        conversation_key=_conv(1), command="help", args=("topic",),
    )
    payload = serialize_inbound(cmd)
    restored = deserialize_inbound("command", payload)
    assert isinstance(restored, InboundCommand)
    assert restored.command == "help"
    assert restored.args == ("topic",)


def test_serialize_callback_round_trip():
    """InboundCallback survives serialize/deserialize."""
    cb = InboundCallback(
        user=InboundUser(id=_actor(42), username="alice"),
        conversation_key=_conv(1), data="approval_approve",
    )
    payload = serialize_inbound(cb)
    restored = deserialize_inbound("callback", payload)
    assert isinstance(restored, InboundCallback)
    assert restored.data == "approval_approve"


# -- One work item per update ----------------------------------------------

def test_one_work_item_per_update(data_dir):
    """UNIQUE constraint on event_id prevents duplicate work items."""
    record_update(data_dir, _event(800), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(800))
    with pytest.raises(Exception):
        enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(800))


# -- update_payload --------------------------------------------------------

def test_update_payload(data_dir):
    """update_payload replaces the stored payload for an existing update."""
    record_update(data_dir, _event(900), conversation_key=_conv(1), actor_key=_actor(42), kind="message", payload="{}")
    assert get_update_payload(data_dir, _event(900)) == "{}"

    update_payload(data_dir, _event(900), '{"text":"hello"}')
    assert get_update_payload(data_dir, _event(900)) == '{"text":"hello"}'


# -- claim_next_any --------------------------------------------------------

def test_claim_next_any_empty(data_dir):
    """claim_next_any returns None on empty queue."""
    assert claim_next_any(data_dir, "w1") is None


def test_claim_next_any_single_item(data_dir):
    """claim_next_any claims a single queued item."""
    record_update(data_dir, _event(1000), conversation_key=_conv(1), actor_key=_actor(42), kind="message", payload='{"text":"hi"}')
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1000))

    item = claim_next_any(data_dir, "w1")
    assert item is not None
    assert item["conversation_key"] == _conv(1)
    assert item["state"] == "claimed"
    assert item["kind"] == "message"
    assert item["payload"] == '{"text":"hi"}'


def test_claim_next_any_skips_busy_chat(data_dir):
    """claim_next_any skips chats that already have a claimed item."""
    # Chat 1: two items
    record_update(data_dir, _event(1100), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(1101), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1100))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1101))

    first = claim_next_any(data_dir, "w1")
    assert first is not None
    assert first["conversation_key"] == _conv(1)

    # Second claim should return None (only chat 1, and it's busy)
    second = claim_next_any(data_dir, "w1")
    assert second is None


def test_claim_next_any_cross_chat(data_dir):
    """claim_next_any claims items from different chats concurrently."""
    record_update(data_dir, _event(1200), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(1201), conversation_key=_conv(2), actor_key=_actor(42), kind="command")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1200))
    enqueue_work_item(data_dir, conversation_key=_conv(2), event_id=_event(1201))

    first = claim_next_any(data_dir, "w1")
    assert first is not None

    second = claim_next_any(data_dir, "w1")
    assert second is not None

    # Different chats
    assert first["conversation_key"] != second["conversation_key"]


def test_claim_next_any_includes_payload(data_dir):
    """claim_next_any returns kind and payload from the joined updates table."""
    msg = InboundMessage(
        user=InboundUser(id=_actor(42), username="alice"),
        conversation_key=_conv(5), text="test message",
        attachments=(),
    )
    payload = serialize_inbound(msg)
    record_update(data_dir, _event(1300), conversation_key=_conv(5), actor_key=_actor(42), kind="message", payload=payload)
    enqueue_work_item(data_dir, conversation_key=_conv(5), event_id=_event(1300))

    item = claim_next_any(data_dir, "w1")
    assert item["kind"] == "message"
    restored = deserialize_inbound(item["kind"], item["payload"])
    assert isinstance(restored, InboundMessage)
    assert restored.text == "test message"
    assert restored.user.id == _actor(42)


# -- Worker loop -----------------------------------------------------------

async def test_worker_loop_processes_items(data_dir):
    """Worker loop claims and dispatches items from the queue."""
    from app.worker import worker_loop

    # Set up two items in different chats
    record_update(data_dir, _event(1400), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(1), text="hello", attachments=())))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1400))

    record_update(data_dir, _event(1401), conversation_key=_conv(2), actor_key=_actor(42), kind="command",
                  payload=serialize_inbound(InboundCommand(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(2), command="help", args=())))
    enqueue_work_item(data_dir, conversation_key=_conv(2), event_id=_event(1401))

    dispatched = []

    async def dispatch(kind, event, item):
        dispatched.append((kind, event, item["conversation_key"]))

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
    rows = conn.execute("SELECT state FROM work_items ORDER BY event_id").fetchall()
    assert all(r["state"] == "done" for r in rows)


async def test_worker_loop_handles_dispatch_failure(data_dir):
    """Worker loop marks items as failed when dispatch raises."""
    from app.worker import worker_loop

    record_update(data_dir, _event(1500), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(1), text="fail", attachments=())))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1500))

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
    row = conn.execute(
        "SELECT state, error FROM work_items WHERE event_id = ?",
        (_event(1500),),
    ).fetchone()
    assert row["state"] == "failed"
    assert "provider crash" in row["error"]


async def test_worker_loop_handles_bad_payload(data_dir):
    """Worker loop marks items as failed when payload can't be deserialized."""
    from app.worker import worker_loop

    record_update(data_dir, _event(1600), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload="not-valid-json")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1600))

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
    row = conn.execute(
        "SELECT state, error FROM work_items WHERE event_id = ?",
        (_event(1600),),
    ).fetchone()
    assert row["state"] == "failed"
    assert row["error"] == "deserialize_error"


async def test_worker_loop_respects_per_chat_serialization(data_dir):
    """Worker loop processes items from the same chat in order."""
    from app.worker import worker_loop

    # Two items in same chat
    for uid in (1700, 1701):
        record_update(data_dir, _event(uid), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                      payload=serialize_inbound(InboundMessage(
                          user=InboundUser(id=_actor(42), username="alice"),
                          conversation_key=_conv(1), text=f"msg-{uid}", attachments=())))
        enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(uid))

    order = []
    async def dispatch(kind, event, item):
        order.append(item["event_id"])

    stop = asyncio.Event()
    async def run_then_stop():
        await asyncio.sleep(0.3)
        stop.set()

    await asyncio.gather(
        worker_loop(data_dir, "w1", dispatch, poll_interval=0.05, stop_event=stop),
        run_then_stop(),
    )

    assert order == [_event(1700), _event(1701)]


# -- Handler integration: payload storage ----------------------------------

def test_handler_dedup_stores_command_payload(data_dir):
    """_dedup_update with a payload stores it in the update journal."""
    cmd = InboundCommand(
        user=InboundUser(id=_actor(42), username="alice"),
        conversation_key=_conv(1), command="help", args=("skills",),
    )
    payload = serialize_inbound(cmd)
    record_update(data_dir, _event(1800), conversation_key=_conv(1), actor_key=_actor(42), kind="command", payload=payload)

    stored = get_update_payload(data_dir, _event(1800))
    restored = deserialize_inbound("command", stored)
    assert isinstance(restored, InboundCommand)
    assert restored.command == "help"
    assert restored.args == ("skills",)


def test_recovery_after_crash(data_dir):
    """Simulate crash: items claimed by old worker are recovered and re-claimable."""
    # Worker "old" claims an item then "crashes"
    record_update(data_dir, _event(1900), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(1), text="before crash", attachments=())))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(1900))
    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="old-worker")
    assert item is not None

    # Verify it's not claimable while held
    assert claim_next(data_dir, conversation_key=_conv(1), worker_id="new-worker") is None

    # New worker starts, recovers stale claims
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE work_items SET claimed_at = ? WHERE event_id = ?", (old_time, _event(1900)))
    conn.commit()

    recovered = recover_stale_claims(data_dir, current_worker_id="new-worker", max_age_seconds=300)
    assert recovered == 1

    # Now it's claimable by the new worker
    item = claim_next_any(data_dir, "new-worker")
    assert item is not None
    assert item["event_id"] == _event(1900)

    # And the payload is intact
    restored = deserialize_inbound(item["kind"], item["payload"])
    assert isinstance(restored, InboundMessage)
    assert restored.text == "before crash"


# -- REGRESSION: atomic record+enqueue ------------------------------------

def test_record_and_enqueue_atomic_new(data_dir):
    """record_and_enqueue creates both update and work item atomically."""
    is_new, item_id = record_and_enqueue(
        data_dir, event_id=_event(2000), conversation_key=_conv(1), actor_key=_actor(42),
        kind="message", payload='{"text":"atomic"}',
    )
    assert is_new is True
    assert item_id is not None

    # Both rows exist
    assert get_update_payload(data_dir, _event(2000)) == '{"text":"atomic"}'
    assert has_queued_or_claimed(data_dir, conversation_key=_conv(1)) is True


def test_record_and_enqueue_duplicate(data_dir):
    """record_and_enqueue rejects duplicate event_id — no orphan update row."""
    is_new, item_id = record_and_enqueue(
        data_dir, event_id=_event(2001), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
    )
    assert is_new is True

    # Second call for same event_id
    is_new2, item_id2 = record_and_enqueue(
        data_dir, event_id=_event(2001), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
    )
    assert is_new2 is False
    assert item_id2 is None


def test_record_and_enqueue_no_orphan_update(data_dir):
    """After duplicate rejection, redelivery must NOT see a ghost update row
    with zero work items (the original bug)."""
    # First: atomic insert succeeds
    record_and_enqueue(data_dir, event_id=_event(2002), conversation_key=_conv(1), actor_key=_actor(42), kind="message")

    # Verify work item exists
    conn = _transport_db(data_dir)
    row = conn.execute(
        "SELECT count(*) FROM work_items WHERE event_id = ?",
        (_event(2002),),
    ).fetchone()
    assert row[0] == 1

    # Simulate: redelivery returns duplicate
    is_new, _ = record_and_enqueue(
        data_dir, event_id=_event(2002), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
    )
    assert is_new is False
    # Still exactly 1 work item
    row = conn.execute(
        "SELECT count(*) FROM work_items WHERE event_id = ?",
        (_event(2002),),
    ).fetchone()
    assert row[0] == 1


def test_record_and_enqueue_rollback_on_non_integrity_error(data_dir):
    """On non-IntegrityError (e.g. TransportStateCorruption from _insert_initial_work_item), transaction is rolled back and no rows remain."""
    from unittest.mock import patch

    event_id = _event(21000)
    with patch("app.work_queue_sqlite_impl._insert_initial_work_item", side_effect=TransportStateCorruption("test")):
        with pytest.raises(TransportStateCorruption):
            record_and_enqueue(
                data_dir, event_id=event_id, conversation_key=_conv(1), actor_key=_actor(42), kind="message",
            )
    conn = _transport_db(data_dir)
    assert conn.in_transaction is False
    assert conn.execute("SELECT 1 FROM updates WHERE event_id = ?", (event_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM work_items WHERE event_id = ?", (event_id,)).fetchone() is None


def test_assert_no_invalid_rows_raises_when_two_claimed_in_chat(data_dir):
    """_assert_no_invalid_rows_for_conversation raises TransportStateCorruption when more than one claimed row exists for the chat."""
    # Use a separate in-memory DB so we can have two claimed rows (production schema has unique index preventing that).
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key TEXT, event_id TEXT, state TEXT, worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode) VALUES (?, ?, ?, 'claimed', 'w1', ?, ?, 'fresh')",
        ("id-1", _conv(1), _event(22001), now, now),
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode) VALUES (?, ?, ?, 'claimed', 'w2', ?, ?, 'fresh')",
        ("id-2", _conv(1), _event(22002), now, now),
    )
    conn.commit()
    with pytest.raises(TransportStateCorruption) as exc_info:
        _assert_no_invalid_rows_for_conversation(conn, _conv(1))
    assert "2 claimed" in str(exc_info.value) or "claimed work items" in str(exc_info.value)
    conn.close()


def test_fresh_schema_has_one_claimed_per_chat_index(data_dir):
    """Fresh transport DB schema includes partial unique index enforcing at most one claimed row per conversation."""
    conn = _transport_db(data_dir)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_one_claimed_per_conv'"
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

    record_update(data_dir, _event(3001), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3001), worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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

    record_update(data_dir, _event(3002), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3002), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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

    record_update(data_dir, _event(3003), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3003), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
        mock_run.return_value = TransitionResult(
            allowed=False,
            new_state=None,
            disposition=TransportDisposition.invalid_transition,
            reason="test",
        )
        with pytest.raises(TransportStateCorruption) as exc_info:
            supersede_pending_recovery(data_dir, _conv(1))
    assert "supersede" in str(exc_info.value).lower() or "workflow rejected" in str(exc_info.value).lower()
    assert conn.in_transaction is False
    row = conn.execute("SELECT state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row is not None and row["state"] == "pending_recovery"


def test_reclaim_for_replay_raises_on_invalid_transition(data_dir):
    """When machine returns invalid_transition (not blocked_replay) for reclaim_for_replay, repository raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, _event(3004), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3004), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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
    record_update(data_dir, _event(3020), conversation_key=_conv(7), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(7), event_id=_event(3020), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    with patch("app.work_queue_sqlite_impl._assert_no_invalid_rows_for_conversation", side_effect=TransportStateCorruption("test two claimed")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            get_latest_pending_recovery(data_dir, _conv(7))
    assert "test two claimed" in str(exc_info.value) or "two claimed" in str(exc_info.value).lower()


def test_has_queued_or_claimed_raises_when_chat_invalid(data_dir):
    """has_queued_or_claimed asserts chat integrity before returning."""
    from unittest.mock import patch
    with patch("app.work_queue_sqlite_impl._assert_no_invalid_rows_for_conversation", side_effect=TransportStateCorruption("chat corrupt")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            has_queued_or_claimed(data_dir, _conv(8))
    assert "chat corrupt" in str(exc_info.value)


def test_reclaim_for_replay_raises_corruption_when_chat_already_invalid(data_dir):
    """reclaim_for_replay asserts chat integrity; if chat is already invalid we get TransportStateCorruption, not ReclaimBlocked."""
    from unittest.mock import patch
    record_update(data_dir, _event(3021), conversation_key=_conv(9), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(9), event_id=_event(3021), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    with patch("app.work_queue_sqlite_impl._assert_no_invalid_rows_for_conversation", side_effect=TransportStateCorruption("chat has two claimed")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            reclaim_for_replay(data_dir, item_id, worker_id="w2")
    assert "chat has two claimed" in str(exc_info.value) or "two claimed" in str(exc_info.value).lower()


def test_supersede_pending_recovery_raises_when_chat_invalid(data_dir):
    """supersede_pending_recovery asserts chat integrity before acting."""
    from unittest.mock import patch
    with patch("app.work_queue_sqlite_impl._assert_no_invalid_rows_for_conversation", side_effect=TransportStateCorruption("invalid chat")):
        with pytest.raises(TransportStateCorruption) as exc_info:
            supersede_pending_recovery(data_dir, _conv(10))
    assert "invalid chat" in str(exc_info.value)


def test_claim_queued_item_returns_none_only_for_other_claimed_for_chat(data_dir):
    """_claim_queued_item returns None only when disposition is other_claimed_for_chat; invalid_transition raises."""
    from unittest.mock import patch
    from app.workflows.results import TransitionResult, TransportDisposition

    record_update(data_dir, _event(3005), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3005))  # queued
    conn = _transport_db(data_dir)
    with _write_tx(conn):
        with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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

    record_update(data_dir, _event(3010), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3010), worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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

    record_update(data_dir, _event(3011), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(3011), worker_id="w1")
    conn = _transport_db(data_dir)
    with patch("app.work_queue_sqlite_impl.run_transport_event") as mock_run:
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

    record_update(data_dir, _event(2100), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(1), text="replay me", attachments=())))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(2100))
    # Claim by old worker, then recover
    claim_next(data_dir, conversation_key=_conv(1), worker_id="old-worker")
    conn = _transport_db(data_dir)
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE work_items SET claimed_at = ? WHERE event_id = ?", (old_time, _event(2100)))
    conn.commit()
    recover_stale_claims(data_dir, current_worker_id="new-worker", max_age_seconds=300)

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
    row = conn.execute(
        "SELECT state FROM work_items WHERE event_id = ?",
        (_event(2100),),
    ).fetchone()
    assert row["state"] == "done"


async def test_worker_loop_leaves_interrupted_item_claimed(data_dir):
    """Worker interruption should leave the claimed item for restart recovery."""
    from app.worker import worker_loop

    record_update(data_dir, _event(2200), conversation_key=_conv(1), actor_key=_actor(42), kind="message",
                  payload=serialize_inbound(InboundMessage(
                      user=InboundUser(id=_actor(42), username="alice"),
                      conversation_key=_conv(1), text="recover me", attachments=())))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(2200))

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
        "SELECT state, worker_id FROM work_items WHERE event_id = ?",
        (_event(2200),),
    ).fetchone()
    assert row["state"] == "claimed"
    assert row["worker_id"] == "worker-a"


# -- Row validation and fail-fast (development-time policy) ----------------

def test_validate_work_item_row_ownerless_claimed():
    """Validator raises TransportStateCorruption for claimed row with worker_id None."""
    with pytest.raises(TransportStateCorruption) as exc_info:
        _validate_work_item_row(
            {"state": "claimed", "worker_id": None, "claimed_at": "2025-01-01T00:00:00Z", "dispatch_mode": "fresh"},
            "item-1",
        )
    assert "worker_id" in str(exc_info.value).lower()


def test_validate_work_item_row_claimed_without_claimed_at():
    """Validator raises TransportStateCorruption for claimed row with claimed_at None."""
    with pytest.raises(TransportStateCorruption) as exc_info:
        _validate_work_item_row(
            {"state": "claimed", "worker_id": "w1", "claimed_at": None, "dispatch_mode": "fresh"},
            "item-2",
        )
    assert "claimed_at" in str(exc_info.value).lower()


def test_load_work_item_by_id_raises_on_ownerless_claimed():
    """load_work_item_by_id raises when row is claimed but worker_id is NULL (e.g. tampered DB)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key TEXT, event_id TEXT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'fresh')",
        ("item-claimed", _conv(1), _event(500), "claimed", None, None, "2025-01-01T00:00:00"),
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
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key TEXT, event_id TEXT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "INSERT INTO work_items (id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'fresh')",
        ("item-claimed", _conv(1), _event(501), "claimed", "w1", None, "2025-01-01T00:00:00"),
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

    record_update(data_dir, _event(9000), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(9000))

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
            user=InboundUser(id=_actor(42), username="u"),
            conversation_key=_conv(1),
            text="hi",
            attachments=(),
        )
    )
    record_update(data_dir, _event(9001), conversation_key=_conv(1), actor_key=_actor(42), kind="message", payload=payload)
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(9001))

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
        "SELECT state FROM work_items WHERE event_id = ?",
        (_event(9001),),
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

    record_update(data_dir, _event(9100), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(9100))
    claimed_item = claim_next(data_dir, conversation_key=_conv(1), worker_id="worker-a")
    assert claimed_item is not None
    assert claimed_item["id"] == item_id
    assert claimed_item["state"] == "claimed"

    # Stale load: pretend the first load in complete_work_item sees queued (race).
    stale_row = {
        "id": item_id,
        "conversation_key": 1,
        "event_id": 9100,
        "state": "queued",
        "worker_id": None,
        "claimed_at": None,
        "completed_at": None,
        "error": None,
        "created_at": "2025-01-01T00:00:00+00:00",
        "dispatch_mode": "fresh",
    }

    with patch("app.work_queue_sqlite_impl._load_work_item_by_id", return_value=stale_row):
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
        "CREATE TABLE updates (event_id INTEGER PRIMARY KEY, conversation_key INT, actor_key INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
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
        "CREATE TABLE updates (event_id INTEGER PRIMARY KEY, conversation_key INT, actor_key INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
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
        "CREATE TABLE updates (event_id INTEGER PRIMARY KEY, conversation_key INT, actor_key INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    # Forged: same index name but non-unique and on event_id, no partial predicate
    conn.execute(
        "CREATE INDEX idx_one_claimed_per_chat ON work_items(event_id)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()


def test_forged_v2_db_wrong_partial_predicate_rejected(data_dir):
    """Existing DB with idx_one_claimed_per_chat with wrong WHERE (e.g. state != 'claimed') is rejected."""
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
        "CREATE TABLE updates (event_id INTEGER PRIMARY KEY, conversation_key INT, actor_key INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, conversation_key INT, event_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_one_claimed_per_chat ON work_items(conversation_key) WHERE state != 'claimed'"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError) as exc_info:
        _transport_db(data_dir)
    msg = str(exc_info.value)
    assert "Unsupported" in msg or "schema" in msg.lower()


def test_run_migrations_is_idempotent_and_adds_m10_tables(data_dir):
    """Legacy transport DB migrates to current schema and can run migrations twice safely."""
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, "
        "dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_one_claimed_per_chat ON work_items(chat_id) WHERE state = 'claimed'"
    )
    conn.commit()

    _run_migrations(conn)
    _run_migrations(conn)

    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == str(_SCHEMA_VERSION)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    assert "usage_log" in tables
    assert "user_access" in tables
    conn.close()


def test_run_migrations_adds_dispatch_mode_for_v2_db(data_dir):
    """Legacy v2 transport DB gains dispatch_mode and M10 tables during migration."""
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_one_claimed_per_chat ON work_items(chat_id) WHERE state = 'claimed'"
    )
    conn.commit()

    _run_migrations(conn)

    work_item_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(work_items)").fetchall()
    }
    assert "dispatch_mode" in work_item_columns
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == str(_SCHEMA_VERSION)
    conn.close()


def test_transport_db_open_migrates_v5_legacy_identity_data(data_dir):
    """Opening a legacy v5 SQLite transport DB migrates Telegram-shaped IDs to v6 text keys."""
    db_path = data_dir / "transport.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '5')")
    conn.execute(
        "CREATE TABLE updates (update_id INTEGER PRIMARY KEY, chat_id INT, user_id INT, kind TEXT, "
        "payload TEXT DEFAULT '{}', received_at TEXT, state TEXT DEFAULT 'received')"
    )
    conn.execute(
        "CREATE TABLE work_items (id TEXT PRIMARY KEY, chat_id INT, update_id INT, state TEXT, "
        "worker_id TEXT, claimed_at TEXT, completed_at TEXT, error TEXT, created_at TEXT, "
        "dispatch_mode TEXT NOT NULL DEFAULT 'fresh')"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_one_claimed_per_chat ON work_items(chat_id) WHERE state = 'claimed'"
    )
    conn.execute(
        "CREATE TABLE usage_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, work_item_id TEXT NOT NULL, "
        "provider TEXT NOT NULL, prompt_tokens INTEGER NOT NULL DEFAULT 0, "
        "completion_tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0.0, "
        "recorded_at REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX idx_usage_log_chat ON usage_log(chat_id)")
    conn.execute("CREATE INDEX idx_usage_log_recorded_at ON usage_log(recorded_at)")
    conn.execute(
        "CREATE TABLE user_access ("
        "user_id INTEGER PRIMARY KEY, access TEXT NOT NULL CHECK(access IN ('allowed', 'blocked')), "
        "reason TEXT NOT NULL DEFAULT '', granted_by INTEGER NOT NULL DEFAULT 0, granted_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO updates (update_id, chat_id, user_id, kind, payload, received_at, state) "
        "VALUES (101, 12345, 42, 'message', '{\"text\":\"hello\"}', '2026-01-01T00:00:00+00:00', 'received')"
    )
    conn.execute(
        "INSERT INTO work_items (id, chat_id, update_id, state, worker_id, claimed_at, completed_at, error, created_at, dispatch_mode) "
        "VALUES ('item-1', 12345, 101, 'queued', NULL, NULL, NULL, NULL, '2026-01-01T00:00:01+00:00', 'fresh')"
    )
    conn.execute(
        "INSERT INTO usage_log (chat_id, work_item_id, provider, prompt_tokens, completion_tokens, cost_usd, recorded_at) "
        "VALUES (12345, 'item-1', 'claude', 10, 5, 0.0, 1234.5)"
    )
    conn.execute(
        "INSERT INTO user_access (user_id, access, reason, granted_by, granted_at) "
        "VALUES (42, 'allowed', 'seed', 7, 2345.6)"
    )
    conn.commit()
    conn.close()

    migrated = _transport_db(data_dir)

    version = migrated.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == str(_SCHEMA_VERSION)

    update_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(updates)").fetchall()}
    assert {"event_id", "conversation_key", "actor_key"} <= update_columns

    work_item_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(work_items)").fetchall()}
    assert {"event_id", "conversation_key"} <= work_item_columns

    usage_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(usage_log)").fetchall()}
    assert "conversation_key" in usage_columns

    access_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(user_access)").fetchall()}
    assert {"actor_key", "granted_by"} <= access_columns

    update_row = migrated.execute(
        "SELECT event_id, conversation_key, actor_key FROM updates WHERE event_id = ?",
        (_event(101),),
    ).fetchone()
    assert dict(update_row) == {
        "event_id": _event(101),
        "conversation_key": _conv(12345),
        "actor_key": _actor(42),
    }

    work_item_row = migrated.execute(
        "SELECT id, event_id, conversation_key FROM work_items WHERE id = 'item-1'"
    ).fetchone()
    assert dict(work_item_row) == {
        "id": "item-1",
        "event_id": _event(101),
        "conversation_key": _conv(12345),
    }

    usage_row = migrated.execute(
        "SELECT conversation_key, prompt_tokens, completion_tokens FROM usage_log WHERE work_item_id = 'item-1'"
    ).fetchone()
    assert dict(usage_row) == {
        "conversation_key": _conv(12345),
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }

    access_row = migrated.execute(
        "SELECT actor_key, granted_by, access, reason FROM user_access WHERE actor_key = ?",
        (_actor(42),),
    ).fetchone()
    assert dict(access_row) == {
        "actor_key": _actor(42),
        "granted_by": _actor(7),
        "access": "allowed",
        "reason": "seed",
    }

    assert get_update_payload(data_dir, _event(101)) == '{"text":"hello"}'
    claimed = claim_next(data_dir, _conv(12345), worker_id="worker-x")
    assert claimed is not None
    assert claimed["id"] == "item-1"
    assert claimed["event_id"] == _event(101)


# -- Contract: non-duplicate IntegrityError must raise --

def test_record_and_enqueue_raises_on_non_duplicate_integrity_error(data_dir):
    """record_and_enqueue must only swallow duplicate event_id errors.
    Other IntegrityError (e.g. NOT NULL on kind) must propagate."""
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        record_and_enqueue(
            data_dir, event_id=_event(90001), conversation_key=_conv(1), actor_key=_actor(42), kind=None,
        )


def test_record_update_raises_on_non_duplicate_integrity_error(data_dir):
    """record_update must only swallow duplicate event_id errors.
    Other IntegrityError (e.g. NOT NULL on kind) must propagate."""
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        record_update(data_dir, event_id=_event(90002), conversation_key=_conv(1), actor_key=_actor(42), kind=None)


def test_record_and_enqueue_still_returns_false_for_duplicate(data_dir):
    """Duplicate event_id must still return (False, None), not raise."""
    ok1, _ = record_and_enqueue(data_dir, event_id=_event(90003), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    assert ok1 is True
    ok2, item2 = record_and_enqueue(data_dir, event_id=_event(90003), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    assert ok2 is False
    assert item2 is None


# -- Contract: complete_work_item clears error field --

def test_complete_work_item_clears_stale_error(data_dir):
    """complete_work_item must set error to NULL, even if the row previously had an error value."""
    conn = _transport_db(data_dir)
    # Create and enqueue a work item
    ok, item_id = record_and_enqueue(data_dir, event_id=_event(90010), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    assert ok and item_id
    # Manually inject an error value to simulate a prior failure
    with _write_tx(conn):
        conn.execute("UPDATE work_items SET error = 'old error' WHERE id = ?", (item_id,))
    # Complete the item
    complete_work_item(data_dir, item_id)
    # Verify error is cleared
    row = conn.execute("SELECT error, state FROM work_items WHERE id = ?", (item_id,)).fetchone()
    assert row["state"] == "done"
    assert row["error"] is None
