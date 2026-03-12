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
