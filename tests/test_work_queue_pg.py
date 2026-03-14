"""Tests for Postgres-backed work queue (Phase 12). Require Postgres harness."""

import pytest

from app import work_queue_pg


def test_record_and_enqueue_idempotent(postgres_truncated):
    """Duplicate update_id returns (False, None) and does not create a second work item."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        is_new, item_id = work_queue_pg.record_and_enqueue(
            conn, update_id=1, chat_id=100, user_id=200, kind="message", payload="{}"
        )
        assert is_new is True
        assert item_id is not None
        is_new2, item_id2 = work_queue_pg.record_and_enqueue(
            conn, update_id=1, chat_id=100, user_id=200, kind="message", payload="{}"
        )
        assert is_new2 is False
        assert item_id2 is None


def test_claim_for_update_and_complete(postgres_truncated):
    """Claim a queued item by update_id then complete it."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        work_queue_pg.record_and_enqueue(
            conn, update_id=2, chat_id=101, user_id=201, kind="message",
            payload='{"text":"hi"}', worker_id=None,
        )
        item = work_queue_pg.claim_for_update(conn, chat_id=101, update_id=2, worker_id="w1")
        assert item is not None
        assert item["state"] == "claimed"
        work_queue_pg.complete_work_item(conn, item["id"])
        has = work_queue_pg.has_queued_or_claimed(conn, 101)
        assert has is False


def test_has_queued_or_claimed(postgres_truncated):
    """has_queued_or_claimed is True when item is queued or claimed."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        assert work_queue_pg.has_queued_or_claimed(conn, 102) is False
        work_queue_pg.record_and_enqueue(
            conn, update_id=3, chat_id=102, user_id=202, kind="message", payload="{}"
        )
        assert work_queue_pg.has_queued_or_claimed(conn, 102) is True


# -- Contract: complete_work_item clears stale error --

def test_complete_work_item_clears_stale_error(postgres_truncated):
    """complete_work_item must set error to NULL even if the row previously had an error value."""
    from app.db.postgres import get_connection
    with get_connection(postgres_truncated) as conn:
        _, item_id = work_queue_pg.record_and_enqueue(
            conn, update_id=90010, chat_id=1, user_id=42, kind="message", payload="{}"
        )
        assert item_id is not None
        # Manually inject an error value to simulate a prior state
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bot_runtime.work_items SET error = 'old error' WHERE id = %s",
                (item_id,),
            )
        conn.commit()
        work_queue_pg.complete_work_item(conn, item_id)
        # Verify error is cleared
        with conn.cursor() as cur:
            cur.execute(
                "SELECT error, state FROM bot_runtime.work_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
        assert row[1] == "done"
        assert row[0] is None, f"error field not cleared: {row[0]!r}"
