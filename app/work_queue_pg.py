"""Postgres-backed transport store (Phase 12). Same contract as work_queue.py."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from psycopg.rows import dict_row

from app.workflows.results import TransportDisposition, TransportStateCorruption
from app.workflows.transport_recovery import (
    TRANSPORT_STATES,
    TransportWorkflowModel,
    run_transport_event,
)
from app.transport_contract import (
    ApplyResult,
    CancelRequestResult,
    DiscardResult,
    ReclaimBlocked,
    _validate_work_item_row,
)

log = logging.getLogger(__name__)

_SCHEMA = "bot_runtime"


class _DuplicateUpdate(Exception):
    """Signals duplicate event_id in record_and_enqueue (rollback and return False, None)."""
    pass


@contextmanager
def _cur(conn):
    """Cursor that returns dict-like rows. Closes on exit."""
    cur = conn.cursor(row_factory=dict_row)
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def _write_tx(conn):
    """Single transaction wrapper. On exit: COMMIT or ROLLBACK."""
    if getattr(conn, "_in_transport_tx", False):
        raise RuntimeError("nested transport transaction")
    conn._in_transport_tx = True
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn._in_transport_tx = False


def _load_work_item_by_id(conn, item_id: str) -> dict[str, Any] | None:
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT * FROM {_SCHEMA}.work_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    row = dict(row)
    _validate_work_item_row(row, item_id)
    return row


def _load_work_item_by_conversation_event(
    conn,
    conversation_key: str,
    event_id: str,
) -> dict[str, Any] | None:
    with _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT w.*, u.kind, u.payload FROM {_SCHEMA}.work_items w
            JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id
            WHERE w.conversation_key = %s AND w.event_id = %s
            """,
            (conversation_key, event_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    row = dict(row)
    _validate_work_item_row(row)
    return row


def _assert_no_invalid_rows_for_conversation(conn, conversation_key: str) -> None:
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT id, state, worker_id, claimed_at, dispatch_mode FROM {_SCHEMA}.work_items WHERE conversation_key = %s",
            (conversation_key,),
        )
        rows = cur.fetchall()
    claimed = 0
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "claimed":
            claimed += 1
    if claimed > 1:
        raise TransportStateCorruption(
            f"conversation {conversation_key} has {claimed} claimed work items (at most one allowed)"
        )


def _claim_queued_item(
    conn,
    *,
    item_id: str,
    worker_id: str,
    has_other_claimed_for_chat: bool,
    event_name: str,
) -> dict[str, Any] | None:
    row = _load_work_item_by_id(conn, item_id)
    if row is None or row["state"] != "queued":
        return None
    model = TransportWorkflowModel(
        state="queued",
        has_other_claimed_for_chat=has_other_claimed_for_chat,
    )
    if event_name == "claim_inline":
        result = run_transport_event(model, "claim_inline", requesting_worker_id=worker_id)
    else:
        result = run_transport_event(model, "claim_worker")
    if not result.allowed:
        if result.disposition == TransportDisposition.other_claimed_for_chat:
            return None
        raise TransportStateCorruption(
            f"_claim_queued_item: workflow rejected for item {item_id}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    with _cur(conn) as cur:
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.work_items
            SET state = %s, worker_id = %s, claimed_at = %s
            WHERE id = %s AND state = 'queued'
            """,
            (result.new_state, worker_id, now, item_id),
        )
        if cur.rowcount > 0:
            cur.execute(f"SELECT * FROM {_SCHEMA}.work_items WHERE id = %s", (item_id,))
            item = cur.fetchone()
            if item is None:
                return None
            out = dict(item)
            _validate_work_item_row(out, item_id)
            return out
        cur.execute(
            f"SELECT state, worker_id, claimed_at FROM {_SCHEMA}.work_items WHERE id = %s",
            (item_id,),
        )
        re_read = cur.fetchone()
    if re_read is None:
        return None
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != "queued":
        return None
    log.error(
        "_claim_queued_item: invariant violation item %s (still queued after UPDATE 0 rows)",
        item_id,
    )
    raise TransportStateCorruption(
        f"claim update matched 0 rows but item {item_id} still queued"
    )


def _apply_transport_event(
    conn,
    item_id: str,
    event_name: str,
    expected_source_state: str,
    build_model: Callable[[dict], TransportWorkflowModel],
    update_extras: str,
    update_extra_args: tuple,
    **event_kwargs: Any,
) -> ApplyResult:
    row = _load_work_item_by_id(conn, item_id)
    if row is None:
        return ApplyResult.already_handled
    if row["state"] != expected_source_state:
        return ApplyResult.already_handled
    model = build_model(row)
    result = run_transport_event(model, event_name, **event_kwargs)
    if not result.allowed:
        raise TransportStateCorruption(
            f"_apply_transport_event: workflow rejected for item {item_id} event {event_name!r}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    with _cur(conn) as cur:
        if update_extras:
            placeholders = (result.new_state,) + update_extra_args + (item_id, expected_source_state)
            cur.execute(
                f"UPDATE {_SCHEMA}.work_items SET state = %s, " + update_extras + " WHERE id = %s AND state = %s",
                placeholders,
            )
        else:
            cur.execute(
                f"UPDATE {_SCHEMA}.work_items SET state = %s WHERE id = %s AND state = %s",
                (result.new_state, item_id, expected_source_state),
            )
        if cur.rowcount > 0:
            return ApplyResult.success
        cur.execute(
            f"SELECT state, worker_id, claimed_at FROM {_SCHEMA}.work_items WHERE id = %s",
            (item_id,),
        )
        re_read = cur.fetchone()
    if re_read is None:
        return ApplyResult.already_handled
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != expected_source_state:
        return ApplyResult.already_handled
    log.error("_apply_transport_event: invariant violation item %s (still %s)", item_id, expected_source_state)
    return ApplyResult.corruption


def _apply_claim_event(
    conn,
    item_id: str,
    event_name: str,
    expected_source_state: str,
    worker_id: str,
    build_model: Callable[[dict], TransportWorkflowModel],
    **event_kwargs: Any,
) -> dict[str, Any] | None:
    row = _load_work_item_by_id(conn, item_id)
    if row is None or row["state"] != expected_source_state:
        return None
    model = build_model(row)
    result = run_transport_event(model, event_name, **event_kwargs)
    if not result.allowed:
        if result.disposition == TransportDisposition.other_claimed_for_chat:
            return None
        if result.disposition == TransportDisposition.blocked_replay:
            raise ReclaimBlocked(item_id)
        raise TransportStateCorruption(
            f"_apply_claim_event: workflow rejected for item {item_id} event {event_name!r}: "
            f"{result.disposition} — {result.reason}"
        )
    now = datetime.now(timezone.utc).isoformat()
    with _cur(conn) as cur:
        cur.execute(
            f"""
            UPDATE {_SCHEMA}.work_items
            SET state = %s, worker_id = %s, claimed_at = %s, completed_at = NULL
            WHERE id = %s AND state = %s
            """,
            (result.new_state, worker_id, now, item_id, expected_source_state),
        )
        if cur.rowcount > 0:
            cur.execute(f"SELECT * FROM {_SCHEMA}.work_items WHERE id = %s", (item_id,))
            out = cur.fetchone()
            if out is None:
                return None
            r = dict(out)
            _validate_work_item_row(r, item_id)
            return r
        cur.execute(
            f"SELECT state, worker_id, claimed_at FROM {_SCHEMA}.work_items WHERE id = %s",
            (item_id,),
        )
        re_read = cur.fetchone()
    if re_read is None:
        return None
    _validate_work_item_row(dict(re_read), item_id)
    if re_read["state"] != expected_source_state:
        return None
    log.error("_apply_claim_event: invariant violation item %s (still %s)", item_id, expected_source_state)
    raise TransportStateCorruption(
        f"claim update matched 0 rows but item {item_id} still in {re_read['state']!r}"
    )


def _insert_initial_work_item(
    conn,
    *,
    item_id: str,
    conversation_key: str,
    event_id: str,
    worker_id: str | None,
    created_at: str,
) -> str:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'claimed' LIMIT 1",
            (conversation_key,),
        )
        has_other_claimed = cur.fetchone() is not None
    if bool(worker_id) and not has_other_claimed:
        model = TransportWorkflowModel(state="queued", has_other_claimed_for_chat=False)
        result = run_transport_event(model, "claim_inline", requesting_worker_id=worker_id)
        if result.allowed:
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.work_items
                    (id, conversation_key, event_id, state, worker_id, claimed_at, created_at, dispatch_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'fresh')
                    """,
                    (item_id, conversation_key, event_id, result.new_state, worker_id, created_at, created_at),
                )
            return item_id
        raise TransportStateCorruption(
            f"_insert_initial_work_item: claim_inline rejected for item {item_id}: "
            f"{result.disposition} — {result.reason}"
        )
    with _cur(conn) as cur:
        cur.execute(
            f"""
            INSERT INTO {_SCHEMA}.work_items (id, conversation_key, event_id, state, created_at, dispatch_mode)
            VALUES (%s, %s, %s, 'queued', %s, 'fresh')
            """,
            (item_id, conversation_key, event_id, created_at),
        )
    return item_id


# ---------------------------------------------------------------------------
# Public API (conn as first arg)
# ---------------------------------------------------------------------------

def record_and_enqueue(
    conn,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
    *,
    worker_id: str | None = None,
) -> tuple[bool, str | None]:
    now = datetime.now(timezone.utc).isoformat()
    item_id = uuid.uuid4().hex
    try:
        with _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.updates (event_id, conversation_key, actor_key, kind, payload, received_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (event_id, conversation_key, actor_key, kind, payload, now),
                )
                if cur.rowcount == 0:
                    raise _DuplicateUpdate()
            _insert_initial_work_item(
                conn, item_id=item_id, conversation_key=conversation_key, event_id=event_id,
                worker_id=worker_id, created_at=now,
            )
        return True, item_id
    except _DuplicateUpdate:
        return False, None


def record_and_admit_message(
    conn,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> tuple[str, str | None]:
    """Record update and admit or reject for provider work. Returns (status, item_id).
    status: 'duplicate' | 'admitted' | 'busy'. item_id set when admitted or busy."""
    now = datetime.now(timezone.utc).isoformat()
    item_id = uuid.uuid4().hex
    try:
        with _write_tx(conn):
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.updates (event_id, conversation_key, actor_key, kind, payload, received_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (event_id, conversation_key, actor_key, kind, payload, now),
                )
                if cur.rowcount == 0:
                    raise _DuplicateUpdate()
            # Serialize admission per conversation so only one fresh queued/claimed
            # item can exist at a time.
            with _cur(conn) as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (conversation_key,),
                )
            if has_fresh_queued_or_claimed(conn, conversation_key):
                with _cur(conn) as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_SCHEMA}.work_items (id, conversation_key, event_id, state, error, created_at, dispatch_mode)
                        VALUES (%s, %s, %s, 'failed', 'chat_busy', %s, 'fresh')
                        """,
                        (item_id, conversation_key, event_id, now),
                    )
                return ("busy", item_id)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.work_items (id, conversation_key, event_id, state, created_at, dispatch_mode)
                    VALUES (%s, %s, %s, 'queued', %s, 'fresh')
                    """,
                    (item_id, conversation_key, event_id, now),
                )
            return ("admitted", item_id)
    except _DuplicateUpdate:
        return ("duplicate", None)


def record_update(
    conn,
    event_id: str,
    conversation_key: str,
    actor_key: str,
    kind: str,
    payload: str = "{}",
) -> bool:
    """Insert update row; return False only for duplicate event_id (ON CONFLICT DO NOTHING).
    All other errors (schema, connection, etc.) propagate; do not swallow."""
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.updates (event_id, conversation_key, actor_key, kind, payload, received_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (event_id, conversation_key, actor_key, kind, payload, now),
            )
            return cur.rowcount > 0


def enqueue_work_item(
    conn,
    conversation_key: str,
    event_id: str,
    *,
    worker_id: str | None = None,
) -> str:
    item_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _insert_initial_work_item(
            conn, item_id=item_id, conversation_key=conversation_key, event_id=event_id,
            worker_id=worker_id, created_at=now,
        )
    return item_id


def update_payload(conn, event_id: str, payload: str) -> None:
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"UPDATE {_SCHEMA}.updates SET payload = %s WHERE event_id = %s",
                (payload, event_id),
            )


def claim_for_update(
    conn,
    conversation_key: str,
    event_id: str,
    worker_id: str,
) -> dict[str, Any] | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
        if row is None:
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            return dict(row)
        if row["state"] != "queued":
            return None
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'claimed' LIMIT 1",
                (conversation_key,),
            )
            has_other_claimed = cur.fetchone() is not None
        out = _claim_queued_item(
            conn, item_id=row["id"], worker_id=worker_id,
            has_other_claimed_for_chat=bool(has_other_claimed), event_name="claim_inline",
        )
        if out is None:
            return None
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT kind, payload FROM {_SCHEMA}.updates WHERE event_id = %s",
                (out["event_id"],),
            )
            u = cur.fetchone()
        if u:
            out["kind"] = u["kind"]
            out["payload"] = u["payload"]
        return out


def claim_next(conn, conversation_key: str, worker_id: str) -> dict[str, Any] | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT id FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'queued'
                AND NOT EXISTS (
                  SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'claimed'
                )
                ORDER BY created_at LIMIT 1
                """,
                (conversation_key, conversation_key),
            )
            row = cur.fetchone()
        if row is None:
            return None
        out = _claim_queued_item(
            conn, item_id=row["id"], worker_id=worker_id,
            has_other_claimed_for_chat=False, event_name="claim_worker",
        )
        return out


def claim_next_any(conn, worker_id: str) -> dict[str, Any] | None:
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT id, conversation_key FROM {_SCHEMA}.work_items
                WHERE state = 'queued'
                AND conversation_key NOT IN (
                  SELECT DISTINCT conversation_key FROM {_SCHEMA}.work_items WHERE state = 'claimed'
                )
                ORDER BY created_at LIMIT 1
                """,
            )
            row = cur.fetchone()
        if row is None:
            return None
        _assert_no_invalid_rows_for_conversation(conn, row["conversation_key"])
        out = _claim_queued_item(
            conn, item_id=row["id"], worker_id=worker_id,
            has_other_claimed_for_chat=False, event_name="claim_worker",
        )
        if out is None:
            return None
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT w.*, u.kind, u.payload FROM {_SCHEMA}.work_items w
                JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id
                WHERE w.id = %s
                """,
                (out["id"],),
            )
            item = cur.fetchone()
        if item is None:
            return None
        out = dict(item)
        _validate_work_item_row(out, out["id"])
        return out


def complete_work_item(conn, item_id: str) -> None:
    """Exact CAS on loaded_state; reread on rowcount zero (Phase 11 contract)."""
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None:
            return
        loaded_state = row["state"]
        if loaded_state not in ("queued", "claimed"):
            return
        model = TransportWorkflowModel(state=loaded_state)
        result = run_transport_event(model, "complete")
        if not result.allowed:
            raise TransportStateCorruption(
                f"complete_work_item: workflow rejected for item {item_id}: "
                f"{result.disposition} — {result.reason}"
            )
        now = datetime.now(timezone.utc).isoformat()
        with _cur(conn) as cur:
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.work_items SET state = %s, completed_at = %s, error = NULL
                WHERE id = %s AND state = %s
                """,
                (result.new_state, now, item_id, loaded_state),
            )
            if cur.rowcount > 0:
                return
        re_read = _load_work_item_by_id(conn, item_id)
        if re_read is None:
            return
        _validate_work_item_row(re_read, item_id)
        if re_read["state"] == loaded_state:
            log.error(
                "complete_work_item: invariant violation item %s (still %s)",
                item_id, re_read["state"],
            )
            raise TransportStateCorruption(
                f"complete_work_item: update matched 0 rows but item {item_id} still in {re_read['state']!r}"
            )


def fail_work_item(conn, item_id: str, error: str) -> None:
    """Exact CAS on loaded_state; reread on rowcount zero (Phase 11 contract)."""
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None:
            return
        loaded_state = row["state"]
        if loaded_state not in ("queued", "claimed"):
            return
        model = TransportWorkflowModel(state=loaded_state)
        result = run_transport_event(model, "fail")
        if not result.allowed:
            raise TransportStateCorruption(
                f"fail_work_item: workflow rejected for item {item_id}: {result.disposition} — {result.reason}"
            )
        now = datetime.now(timezone.utc).isoformat()
        err = (error or "")[:500]
        with _cur(conn) as cur:
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.work_items SET state = %s, completed_at = %s, error = %s
                WHERE id = %s AND state = %s
                """,
                (result.new_state, now, err, item_id, loaded_state),
            )
            if cur.rowcount > 0:
                return
        re_read = _load_work_item_by_id(conn, item_id)
        if re_read is None:
            return
        _validate_work_item_row(re_read, item_id)
        if re_read["state"] == loaded_state:
            log.error(
                "fail_work_item: invariant violation item %s (still %s)",
                item_id, re_read["state"],
            )
            raise TransportStateCorruption(
                f"fail_work_item: update matched 0 rows but item {item_id} still in {re_read['state']!r}"
            )


def has_claimed_for_chat(conn, conversation_key: str) -> bool:
    """True if the conversation has any work item in claimed state."""
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'claimed' LIMIT 1",
            (conversation_key,),
        )
        return cur.fetchone() is not None


def has_queued_or_claimed(conn, conversation_key: str) -> bool:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state IN ('queued', 'claimed') LIMIT 1",
            (conversation_key,),
        )
        return cur.fetchone() is not None


def has_fresh_queued_or_claimed(conn, conversation_key: str) -> bool:
    """True if this conversation has any work item in queued or claimed state with dispatch_mode='fresh'."""
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state IN ('queued', 'claimed') "
            "AND dispatch_mode = 'fresh' LIMIT 1",
            (conversation_key,),
        )
        return cur.fetchone() is not None


def cancel_queued_fresh_for_chat(conn, conversation_key: str) -> bool:
    """If this conversation has a queued fresh item, mark it failed with error='cancelled'. Returns True if one was cancelled."""
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT id FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'queued' AND dispatch_mode = 'fresh'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (conversation_key,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        item_id = row["id"]
        now = datetime.now(timezone.utc).isoformat()
        with _cur(conn) as cur:
            cur.execute(
                f"""
                UPDATE {_SCHEMA}.work_items SET state = 'failed', completed_at = %s, error = 'cancelled'
                WHERE id = %s AND state = 'queued'
                """,
                (now, item_id),
            )
            return cur.rowcount > 0


def request_cancel(
    conn,
    conversation_key: str,
    actor_key: str,
    *,
    cancel_request_event_id: str = "",
) -> CancelRequestResult:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT id, cancel_requested_at FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'claimed' AND dispatch_mode = 'fresh'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (conversation_key,),
            )
            claimed = cur.fetchone()
            if claimed is not None:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.work_items
                    SET cancel_requested_at = COALESCE(cancel_requested_at, %s),
                        cancel_requested_by = %s,
                        cancel_request_event_id = %s
                    WHERE id = %s AND state = 'claimed'
                    """,
                    (now, actor_key, cancel_request_event_id, claimed["id"]),
                )
                return CancelRequestResult.claimed_cancel_requested

            cur.execute(
                f"""
                SELECT id FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'queued' AND dispatch_mode = 'fresh'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (conversation_key,),
            )
            queued = cur.fetchone()
            if queued is not None:
                cur.execute(
                    f"""
                    UPDATE {_SCHEMA}.work_items
                    SET state = 'failed', completed_at = %s, error = 'cancelled'
                    WHERE id = %s AND state = 'queued'
                    """,
                    (now, queued["id"]),
                )
                if cur.rowcount > 0:
                    return CancelRequestResult.queued_cancelled

        return CancelRequestResult.nothing_to_cancel


def is_cancel_requested(conn, item_id: str) -> bool:
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT cancel_requested_at FROM {_SCHEMA}.work_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
    return bool(row and row["cancel_requested_at"])


def get_work_items_for_chat(conn, conversation_key: str) -> list[dict[str, Any]]:
    """Return work items for a conversation with id, event_id, state, error, dispatch_mode, kind. Read-only."""
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT w.id, w.event_id, w.state, w.error, w.dispatch_mode, u.kind "
            f"FROM {_SCHEMA}.work_items w "
            f"JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id "
            f"WHERE w.conversation_key = %s ORDER BY w.created_at ASC",
            (conversation_key,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_update_payload(conn, event_id: str) -> str | None:
    import json
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT payload FROM {_SCHEMA}.updates WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    payload = row["payload"]
    if isinstance(payload, dict):
        return json.dumps(payload)
    return str(payload) if payload is not None else None


def mark_pending_recovery(conn, item_id: str) -> None:
    with _write_tx(conn):
        res = _apply_transport_event(
            conn, item_id, "move_to_pending_recovery", "claimed",
            lambda r: TransportWorkflowModel(state=r["state"]), "", (),
        )
        if res == ApplyResult.corruption:
            raise TransportStateCorruption(f"mark_pending_recovery: invariant violation item {item_id}")


def get_pending_recovery_for_update(
    conn,
    conversation_key: str,
    event_id: str,
) -> dict[str, Any] | None:
    row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return row


def get_latest_pending_recovery(conn, conversation_key: str) -> dict[str, Any] | None:
    _assert_no_invalid_rows_for_conversation(conn, conversation_key)
    with _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT w.*, u.kind, u.payload FROM {_SCHEMA}.work_items w
            JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id
            WHERE w.conversation_key = %s ORDER BY w.created_at DESC
            """,
            (conversation_key,),
        )
        rows = cur.fetchall()
    for row in rows:
        r = dict(row)
        _validate_work_item_row(r, r["id"])
        if r["state"] == "pending_recovery":
            return r
    return None


def supersede_pending_recovery(conn, conversation_key: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT id FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'pending_recovery'",
                (conversation_key,),
            )
            rows = cur.fetchall()
        count = 0
        for row in rows:
            full = _load_work_item_by_id(conn, row["id"])
            if full is None or full["state"] != "pending_recovery":
                continue
            res = _apply_transport_event(
                conn, full["id"], "supersede_recovery", "pending_recovery",
                lambda r: TransportWorkflowModel(state=r["state"]),
                "completed_at = %s, error = %s", (now, "superseded"),
            )
            if res == ApplyResult.success:
                count += 1
        if count:
            log.info(
                "Superseded %d pending_recovery items for conversation %s",
                count,
                conversation_key,
            )
        return count


def discard_recovery(conn, item_id: str) -> DiscardResult:
    now = datetime.now(timezone.utc).isoformat()
    with _write_tx(conn):
        res = _apply_transport_event(
            conn, item_id, "discard_recovery", "pending_recovery",
            lambda r: TransportWorkflowModel(state=r["state"]),
            "completed_at = %s, error = %s", (now, "discarded"),
        )
        if res == ApplyResult.success:
            return DiscardResult.success
        if res == ApplyResult.already_handled:
            return DiscardResult.already_handled
        return DiscardResult.corruption


def reclaim_for_replay(
    conn,
    item_id: str,
    worker_id: str,
    *,
    ignore_claimed_item_id: str = "",
) -> dict[str, Any] | None:
    with _write_tx(conn):
        row = _load_work_item_by_id(conn, item_id)
        if row is None or row["state"] != "pending_recovery":
            return None
        conversation_key = row["conversation_key"]
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        with _cur(conn) as cur:
            if ignore_claimed_item_id:
                cur.execute(
                    f"""
                    SELECT 1 FROM {_SCHEMA}.work_items
                    WHERE conversation_key = %s AND state = 'claimed' AND id <> %s
                    LIMIT 1
                    """,
                    (conversation_key, ignore_claimed_item_id),
                )
            else:
                cur.execute(
                    f"SELECT 1 FROM {_SCHEMA}.work_items WHERE conversation_key = %s AND state = 'claimed' LIMIT 1",
                    (conversation_key,),
                )
            has_claimed = cur.fetchone() is not None
        out = _apply_claim_event(
            conn, item_id, "reclaim_for_replay", "pending_recovery", worker_id,
            lambda r: TransportWorkflowModel(state=r["state"], has_other_claimed_for_chat=bool(has_claimed)),
        )
        if out is None:
            return None
        with _cur(conn) as cur:
            cur.execute(
                f"""
                SELECT w.*, u.kind, u.payload FROM {_SCHEMA}.work_items w
                JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id WHERE w.id = %s
                """,
                (item_id,),
            )
            full = cur.fetchone()
        if full is None:
            return None
        r = dict(full)
        _validate_work_item_row(r, item_id)
        return r


def recover_stale_claims(conn, current_worker_id: str, max_age_seconds: int = 300) -> int:
    now = datetime.now(timezone.utc)
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT id, state, worker_id, claimed_at, dispatch_mode, cancel_requested_at "
                f"FROM {_SCHEMA}.work_items WHERE state = 'claimed'"
            )
            rows = cur.fetchall()
        requeued = 0
        for row in rows:
            r = dict(row)
            _validate_work_item_row(r, r["id"])
            stale = False
            if row["worker_id"] != current_worker_id:
                stale = True
            elif row["claimed_at"]:
                claimed = row["claimed_at"]
                if hasattr(claimed, "isoformat"):
                    claimed_ts = claimed
                else:
                    claimed_ts = datetime.fromisoformat(str(claimed).replace("Z", "+00:00"))
                if (now - claimed_ts).total_seconds() > max_age_seconds:
                    stale = True
            if stale:
                model = TransportWorkflowModel(state="claimed", worker_id=row["worker_id"], is_stale=True)
                result = run_transport_event(model, "recover_stale_claim")
                if not result.allowed:
                    if result.disposition == TransportDisposition.guard_failed:
                        continue
                    raise TransportStateCorruption(
                        f"recover_stale_claims: workflow rejected for item {row['id']}: "
                        f"{result.disposition} — {result.reason}"
                    )
                with _cur(conn) as cur:
                    if row.get("cancel_requested_at"):
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.work_items
                            SET state = 'failed', completed_at = %s, error = 'cancelled'
                            WHERE id = %s AND state = 'claimed' AND worker_id = %s AND claimed_at = %s
                            """,
                            (now.isoformat(), row["id"], row["worker_id"], row["claimed_at"]),
                        )
                    else:
                        cur.execute(
                            f"""
                            UPDATE {_SCHEMA}.work_items
                            SET state = %s, worker_id = NULL, claimed_at = NULL, dispatch_mode = 'recovery'
                            WHERE id = %s AND state = 'claimed' AND worker_id = %s AND claimed_at = %s
                            """,
                            (result.new_state, row["id"], row["worker_id"], row["claimed_at"]),
                        )
                    if cur.rowcount > 0:
                        requeued += 1
                        continue
                re_read = _load_work_item_by_id(conn, row["id"])
                if re_read is None:
                    continue
                if (
                    re_read["state"] == "claimed"
                    and re_read["worker_id"] == row["worker_id"]
                    and re_read["claimed_at"] == row["claimed_at"]
                ):
                    raise TransportStateCorruption(
                        f"recover_stale_claims: update matched 0 rows but item {row['id']} still claimed"
                    )
        if requeued:
            log.info("Recovered %d stale work items", requeued)
        return requeued


def purge_old(conn, older_than_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                DELETE FROM {_SCHEMA}.work_items
                WHERE state IN ('done', 'failed', 'pending_recovery') AND created_at < %s
                """,
                (cutoff,),
            )
            deleted_items = cur.rowcount
            cur.execute(
                f"""
                DELETE FROM {_SCHEMA}.updates
                WHERE event_id NOT IN (SELECT event_id FROM {_SCHEMA}.work_items)
                AND received_at < %s
                """,
                (cutoff,),
            )
            deleted_updates = cur.rowcount
        if deleted_items or deleted_updates:
            log.info("Purged %d work items and %d updates", deleted_items, deleted_updates)
        return deleted_items


def get_user_access_override(conn, actor_key: str) -> str | None:
    """Return 'allowed', 'blocked', or None when no override exists."""
    with _cur(conn) as cur:
        cur.execute(
            "SELECT access FROM bot_runtime.user_access WHERE actor_key = %s",
            (actor_key,),
        )
        row = cur.fetchone()
    return row["access"] if row else None


def set_user_access(
    conn,
    actor_key: str,
    access: str,
    reason: str,
    granted_by: str,
) -> None:
    """Upsert a user access override row."""
    now = datetime.now(timezone.utc)
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                """INSERT INTO bot_runtime.user_access
                       (actor_key, access, reason, granted_by, granted_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (actor_key) DO UPDATE SET
                       access = EXCLUDED.access,
                       reason = EXCLUDED.reason,
                       granted_by = EXCLUDED.granted_by,
                       granted_at = EXCLUDED.granted_at""",
                (actor_key, access, reason, granted_by, now),
            )


def list_user_access(conn) -> list[dict]:
    """Return all user access overrides ordered by most recent grant first."""
    with _cur(conn) as cur:
        cur.execute(
            "SELECT actor_key, access, reason, granted_by, granted_at "
            "FROM bot_runtime.user_access ORDER BY granted_at DESC"
        )
        rows = cur.fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(dict(row))
    return results


def record_usage(
    conn,
    *,
    conversation_key: str,
    work_item_id: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
) -> None:
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""INSERT INTO {_SCHEMA}.usage_log (
                       conversation_key, work_item_id, provider, prompt_tokens,
                       completion_tokens, cost_usd, recorded_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, NOW() AT TIME ZONE 'utc')""",
                (
                    conversation_key,
                    work_item_id,
                    provider,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                ),
            )


def get_usage_since(conn, *, since_epoch: float) -> list[dict]:
    since_dt = datetime.fromtimestamp(since_epoch, tz=timezone.utc)
    with _cur(conn) as cur:
        cur.execute(
            f"""SELECT
                   conversation_key, work_item_id, provider, prompt_tokens,
                   completion_tokens, cost_usd,
                   EXTRACT(EPOCH FROM recorded_at)::double precision AS recorded_at
               FROM {_SCHEMA}.usage_log
               WHERE recorded_at >= %s
               ORDER BY recorded_at""",
            (since_dt,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]
