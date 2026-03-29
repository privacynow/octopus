"""Postgres-backed transport store (Phase 12). Same contract as work_queue.py."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from psycopg.rows import dict_row

from octopus_sdk.work_queue import (
    QueueSnapshot,
    UsageRecord,
    UserAccessRecord,
    WorkItemRecord,
    WorkerHeartbeat,
)
from octopus_sdk.work_queue import TransportDisposition, TransportStateCorruption
from octopus_sdk.workflows.recovery_machine import (
    TRANSPORT_STATES,
    TransportWorkflowModel,
    run_transport_event,
)
from octopus_sdk.work_queue import (
    ApplyResult,
    CancelRequestResult,
    DiscardResult,
    ReclaimBlocked,
    coerce_usage_records,
    coerce_user_access_records,
    coerce_work_item_record,
    coerce_work_item_records,
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
    if "payload" in row:
        row["payload"] = _payload_json_text(row["payload"])
    _validate_work_item_row(row)
    return row


def _payload_json_text(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value) if value is not None else "{}"


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
    """Record update and durably admit fresh work. Returns (status, item_id).

    status: 'duplicate' | 'admitted' | 'queued'. item_id set when admitted or queued.
    """
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
            had_prior_fresh = has_fresh_queued_or_claimed(conn, conversation_key)
            with _cur(conn) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_SCHEMA}.work_items (id, conversation_key, event_id, state, created_at, dispatch_mode)
                    VALUES (%s, %s, %s, 'queued', %s, 'fresh')
                    """,
                    (item_id, conversation_key, event_id, now),
                )
            return ("queued" if had_prior_fresh else "admitted", item_id)
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
) -> WorkItemRecord | None:
    with _write_tx(conn):
        _assert_no_invalid_rows_for_conversation(conn, conversation_key)
        row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
        if row is None:
            return None
        if row["state"] == "claimed" and row.get("worker_id") == worker_id:
            return WorkItemRecord.from_mapping(row)
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
            out["payload"] = _payload_json_text(u["payload"])
        return WorkItemRecord.from_mapping(out)

def claim_next(conn, conversation_key: str, worker_id: str) -> WorkItemRecord | None:
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
        return None if out is None else WorkItemRecord.from_mapping(out)

def claim_next_any(conn, worker_id: str) -> WorkItemRecord | None:
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
        if "payload" in out:
            out["payload"] = _payload_json_text(out["payload"])
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
            claimed_extra = ""
            claimed_params: tuple[object, ...]
            if cancel_request_event_id:
                claimed_extra = " AND event_id != %s"
                claimed_params = (conversation_key, cancel_request_event_id)
            else:
                claimed_params = (conversation_key,)
            cur.execute(
                f"""
                SELECT id, cancel_requested_at FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'claimed' AND dispatch_mode = 'fresh'
                {claimed_extra}
                ORDER BY created_at ASC
                LIMIT 1
                """,
                claimed_params,
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

            queued_extra = ""
            queued_params: tuple[object, ...]
            if cancel_request_event_id:
                queued_extra = " AND event_id != %s"
                queued_params = (conversation_key, cancel_request_event_id)
            else:
                queued_params = (conversation_key,)
            cur.execute(
                f"""
                SELECT id FROM {_SCHEMA}.work_items
                WHERE conversation_key = %s AND state = 'queued' AND dispatch_mode = 'fresh'
                {queued_extra}
                ORDER BY created_at ASC
                LIMIT 1
                """,
                queued_params,
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


def get_work_items_for_chat(conn, conversation_key: str) -> list[WorkItemRecord]:
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
    return [WorkItemRecord.from_mapping(dict(r)) for r in rows]


def list_incomplete_work_items(conn) -> list[WorkItemRecord]:
    """Return queued/claimed/recovery items that survive process restarts."""
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT w.*, u.kind, u.payload "
            f"FROM {_SCHEMA}.work_items w "
            f"JOIN {_SCHEMA}.updates u ON w.event_id = u.event_id "
            f"WHERE w.state IN ('queued', 'claimed', 'pending_recovery') "
            f"ORDER BY w.created_at ASC"
        )
        rows = cur.fetchall()
    records: list[WorkItemRecord] = []
    for row in rows:
        record = dict(row)
        if "payload" in record:
            record["payload"] = _payload_json_text(record["payload"])
        records.append(WorkItemRecord.from_mapping(record))
    return records


def get_queue_snapshot(conn) -> QueueSnapshot:
    """Return backend-neutral queue counts and oldest timestamps."""
    with _cur(conn) as cur:
        cur.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN state = 'queued' AND dispatch_mode = 'fresh' THEN 1 ELSE 0 END), 0) AS fresh_queued_count,
                COALESCE(SUM(CASE WHEN state = 'queued' AND dispatch_mode = 'recovery' THEN 1 ELSE 0 END), 0) AS recovery_queued_count,
                COALESCE(SUM(CASE WHEN state = 'claimed' THEN 1 ELSE 0 END), 0) AS claimed_count,
                COALESCE(SUM(CASE WHEN state = 'pending_recovery' THEN 1 ELSE 0 END), 0) AS pending_recovery_count,
                COALESCE(SUM(CASE WHEN state = 'claimed' AND cancel_requested_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS cancel_requested_claimed_count,
                MIN(CASE WHEN state = 'queued' AND dispatch_mode = 'fresh' THEN created_at END) AS oldest_fresh_queued_at,
                MIN(CASE WHEN state = 'queued' AND dispatch_mode = 'recovery' THEN created_at END) AS oldest_recovery_queued_at,
                MIN(CASE WHEN state = 'claimed' THEN claimed_at END) AS oldest_claimed_at,
                MIN(CASE WHEN state = 'pending_recovery' THEN created_at END) AS oldest_pending_recovery_at
            FROM {_SCHEMA}.work_items
            """
        )
        row = cur.fetchone()
    if row is None:
        return QueueSnapshot()
    return QueueSnapshot(
        fresh_queued_count=int(row["fresh_queued_count"] or 0),
        recovery_queued_count=int(row["recovery_queued_count"] or 0),
        claimed_count=int(row["claimed_count"] or 0),
        pending_recovery_count=int(row["pending_recovery_count"] or 0),
        cancel_requested_claimed_count=int(row["cancel_requested_claimed_count"] or 0),
        oldest_fresh_queued_at=(
            row["oldest_fresh_queued_at"].isoformat() if row["oldest_fresh_queued_at"] else None
        ),
        oldest_recovery_queued_at=(
            row["oldest_recovery_queued_at"].isoformat() if row["oldest_recovery_queued_at"] else None
        ),
        oldest_claimed_at=(
            row["oldest_claimed_at"].isoformat() if row["oldest_claimed_at"] else None
        ),
        oldest_pending_recovery_at=(
            row["oldest_pending_recovery_at"].isoformat() if row["oldest_pending_recovery_at"] else None
        ),
    )


def upsert_worker_heartbeat(conn, heartbeat: WorkerHeartbeat) -> None:
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.worker_heartbeats (
                    worker_id,
                    process_role,
                    started_at,
                    last_seen_at,
                    current_item_id,
                    current_conversation_key,
                    current_kind,
                    items_processed,
                    stale_recoveries_seen,
                    last_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (worker_id) DO UPDATE SET
                    process_role = EXCLUDED.process_role,
                    started_at = EXCLUDED.started_at,
                    last_seen_at = EXCLUDED.last_seen_at,
                    current_item_id = EXCLUDED.current_item_id,
                    current_conversation_key = EXCLUDED.current_conversation_key,
                    current_kind = EXCLUDED.current_kind,
                    items_processed = EXCLUDED.items_processed,
                    stale_recoveries_seen = EXCLUDED.stale_recoveries_seen,
                    last_error = EXCLUDED.last_error
                """,
                (
                    heartbeat.worker_id,
                    heartbeat.process_role,
                    heartbeat.started_at,
                    heartbeat.last_seen_at,
                    heartbeat.current_item_id,
                    heartbeat.current_conversation_key,
                    heartbeat.current_kind,
                    heartbeat.items_processed,
                    heartbeat.stale_recoveries_seen,
                    heartbeat.last_error,
                ),
            )


def clear_worker_heartbeat(conn, worker_id: str) -> None:
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"DELETE FROM {_SCHEMA}.worker_heartbeats WHERE worker_id = %s",
                (worker_id,),
            )


def list_worker_heartbeats(conn) -> list[WorkerHeartbeat]:
    with _cur(conn) as cur:
        cur.execute(
            f"SELECT * FROM {_SCHEMA}.worker_heartbeats ORDER BY worker_id ASC"
        )
        rows = cur.fetchall()
    return [
        WorkerHeartbeat(
            worker_id=row["worker_id"],
            process_role=row["process_role"],
            started_at=row["started_at"].isoformat() if hasattr(row["started_at"], "isoformat") else str(row["started_at"]),
            last_seen_at=row["last_seen_at"].isoformat() if hasattr(row["last_seen_at"], "isoformat") else str(row["last_seen_at"]),
            current_item_id=row["current_item_id"],
            current_conversation_key=row["current_conversation_key"],
            current_kind=row["current_kind"],
            items_processed=int(row["items_processed"] or 0),
            stale_recoveries_seen=int(row["stale_recoveries_seen"] or 0),
            last_error=row["last_error"],
        )
        for row in rows
    ]


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
) -> WorkItemRecord | None:
    row = _load_work_item_by_conversation_event(conn, conversation_key, event_id)
    if row is None or row["state"] != "pending_recovery":
        return None
    return WorkItemRecord.from_mapping(row)


def get_latest_pending_recovery(conn, conversation_key: str) -> WorkItemRecord | None:
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
        if "payload" in r:
            r["payload"] = _payload_json_text(r["payload"])
        _validate_work_item_row(r, r["id"])
        if r["state"] == "pending_recovery":
            return WorkItemRecord.from_mapping(r)
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
) -> WorkItemRecord | None:
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
        if "payload" in r:
            r["payload"] = _payload_json_text(r["payload"])
        _validate_work_item_row(r, item_id)
        return WorkItemRecord.from_mapping(r)


def recover_stale_claims(conn, lease_ttl_seconds: int = 300) -> int:
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=lease_ttl_seconds)
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"SELECT id, state, worker_id, claimed_at, dispatch_mode, cancel_requested_at "
                f"FROM {_SCHEMA}.work_items "
                f"WHERE state = 'claimed' AND claimed_at IS NOT NULL AND claimed_at < %s",
                (stale_before,),
            )
            rows = cur.fetchall()
        requeued = 0
        for row in rows:
            r = dict(row)
            _validate_work_item_row(r, r["id"])
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


def recover_after_crash(conn, lease_ttl_seconds: int = 300) -> int:
    """Recover durable queue state after a worker or process restart."""
    return recover_stale_claims(conn, lease_ttl_seconds)


def purge_old(conn, older_than_seconds: int = 7 * 24 * 3600) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
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


def purge_old_usage(conn, older_than_seconds: int = 30 * 24 * 3600) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    with _write_tx(conn):
        with _cur(conn) as cur:
            cur.execute(
                f"""
                DELETE FROM {_SCHEMA}.usage_log
                WHERE recorded_at < %s
                """,
                (cutoff,),
            )
            return cur.rowcount


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


def list_user_access(conn) -> list[UserAccessRecord]:
    """Return all user access overrides ordered by most recent grant first."""
    with _cur(conn) as cur:
        cur.execute(
            "SELECT actor_key, access, reason, granted_by, granted_at "
            "FROM bot_runtime.user_access ORDER BY granted_at DESC"
        )
        rows = cur.fetchall()
    return [UserAccessRecord.from_mapping(dict(row)) for row in rows]


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


def get_usage_since(conn, *, since_epoch: float) -> list[UsageRecord]:
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
    return [UsageRecord.from_mapping(dict(row)) for row in rows]


class PostgresTransportStore:
    """Transport store backed by Postgres. Uses connection pool; data_dir ignored."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_min: int = 1,
        pool_max: int = 10,
        connect_timeout: int = 10,
    ) -> None:
        self._database_url = database_url
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._connect_timeout = connect_timeout

    @contextmanager
    def _conn(self):
        from app.db.postgres import get_connection

        with get_connection(
            self._database_url,
            min_size=self._pool_min,
            max_size=self._pool_max,
            connect_timeout=self._connect_timeout,
        ) as conn:
            yield conn

    def record_and_enqueue(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
        *,
        worker_id: str | None = None,
    ) -> tuple[bool, str | None]:
        with self._conn() as conn:
            return record_and_enqueue(conn, event_id, conversation_key, actor_key, kind, payload, worker_id=worker_id)

    def record_and_admit_message(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> tuple[str, str | None]:
        with self._conn() as conn:
            return record_and_admit_message(conn, event_id, conversation_key, actor_key, kind, payload)

    def record_update(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> bool:
        with self._conn() as conn:
            return record_update(conn, event_id, conversation_key, actor_key, kind, payload)

    def enqueue_work_item(
        self,
        data_dir: Path,
        conversation_key: str,
        event_id: str,
        *,
        worker_id: str | None = None,
    ) -> str:
        with self._conn() as conn:
            return enqueue_work_item(conn, conversation_key, event_id, worker_id=worker_id)

    def update_payload(self, data_dir: Path, event_id: str, payload: str) -> None:
        with self._conn() as conn:
            update_payload(conn, event_id, payload)

    def claim_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str, worker_id: str
    ) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(claim_for_update(conn, conversation_key, event_id, worker_id))

    def claim_next(self, data_dir: Path, conversation_key: str, worker_id: str) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(claim_next(conn, conversation_key, worker_id))

    def claim_next_any(self, data_dir: Path, worker_id: str) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(claim_next_any(conn, worker_id))

    def list_incomplete_work_items(self, data_dir: Path) -> list[WorkItemRecord]:
        with self._conn() as conn:
            return coerce_work_item_records(list_incomplete_work_items(conn))

    def recover_after_crash(self, data_dir: Path, *, lease_ttl_seconds: int = 300) -> int:
        with self._conn() as conn:
            return recover_after_crash(conn, lease_ttl_seconds)

    def complete_work_item(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            complete_work_item(conn, item_id)

    def fail_work_item(self, data_dir: Path, item_id: str, error: str) -> None:
        with self._conn() as conn:
            fail_work_item(conn, item_id, error)

    def cancel_queued_fresh_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return cancel_queued_fresh_for_chat(conn, conversation_key)

    def request_cancel(
        self,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        *,
        cancel_request_event_id: str = "",
    ) -> CancelRequestResult:
        with self._conn() as conn:
            return request_cancel(
                conn,
                conversation_key,
                actor_key,
                cancel_request_event_id=cancel_request_event_id,
            )

    def is_cancel_requested(self, data_dir: Path, item_id: str) -> bool:
        with self._conn() as conn:
            return is_cancel_requested(conn, item_id)

    def has_claimed_for_chat(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return has_claimed_for_chat(conn, conversation_key)

    def has_queued_or_claimed(self, data_dir: Path, conversation_key: str) -> bool:
        with self._conn() as conn:
            return has_queued_or_claimed(conn, conversation_key)

    def get_update_payload(self, data_dir: Path, event_id: str) -> str | None:
        with self._conn() as conn:
            return get_update_payload(conn, event_id)

    def get_work_items_for_chat(self, data_dir: Path, conversation_key: str) -> list[WorkItemRecord]:
        with self._conn() as conn:
            return coerce_work_item_records(get_work_items_for_chat(conn, conversation_key))

    def get_queue_snapshot(self, data_dir: Path) -> QueueSnapshot:
        with self._conn() as conn:
            return get_queue_snapshot(conn)

    def upsert_worker_heartbeat(self, data_dir: Path, heartbeat: WorkerHeartbeat) -> None:
        with self._conn() as conn:
            upsert_worker_heartbeat(conn, heartbeat)

    def clear_worker_heartbeat(self, data_dir: Path, worker_id: str) -> None:
        with self._conn() as conn:
            clear_worker_heartbeat(conn, worker_id)

    def list_worker_heartbeats(self, data_dir: Path) -> list[WorkerHeartbeat]:
        with self._conn() as conn:
            return list_worker_heartbeats(conn)

    def mark_pending_recovery(self, data_dir: Path, item_id: str) -> None:
        with self._conn() as conn:
            mark_pending_recovery(conn, item_id)

    def get_pending_recovery_for_update(
        self, data_dir: Path, conversation_key: str, event_id: str
    ) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(get_pending_recovery_for_update(conn, conversation_key, event_id))

    def get_latest_pending_recovery(self, data_dir: Path, conversation_key: str) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(get_latest_pending_recovery(conn, conversation_key))

    def supersede_pending_recovery(self, data_dir: Path, conversation_key: str) -> int:
        with self._conn() as conn:
            return supersede_pending_recovery(conn, conversation_key)

    def discard_recovery(self, data_dir: Path, item_id: str) -> DiscardResult:
        with self._conn() as conn:
            return discard_recovery(conn, item_id)

    def reclaim_for_replay(
        self,
        data_dir: Path,
        item_id: str,
        worker_id: str,
        *,
        ignore_claimed_item_id: str = "",
    ) -> WorkItemRecord | None:
        with self._conn() as conn:
            return coerce_work_item_record(
                reclaim_for_replay(
                    conn,
                    item_id,
                    worker_id,
                    ignore_claimed_item_id=ignore_claimed_item_id,
                )
            )

    def recover_stale_claims(self, data_dir: Path, *, lease_ttl_seconds: int = 300) -> int:
        with self._conn() as conn:
            return recover_stale_claims(conn, lease_ttl_seconds)

    def purge_old(self, data_dir: Path, *, older_than_seconds: int = 7 * 24 * 3600) -> int:
        with self._conn() as conn:
            return purge_old(conn, older_than_seconds)

    def purge_old_usage(self, data_dir: Path, *, older_than_seconds: int = 30 * 24 * 3600) -> int:
        with self._conn() as conn:
            return purge_old_usage(conn, older_than_seconds)

    def get_user_access(self, data_dir: Path, actor_key: str) -> str | None:
        with self._conn() as conn:
            return get_user_access_override(conn, actor_key)

    def set_user_access(
        self,
        data_dir: Path,
        actor_key: str,
        access: str,
        reason: str = "",
        granted_by: str = "",
    ) -> None:
        with self._conn() as conn:
            set_user_access(conn, actor_key, access, reason, granted_by)

    def list_user_access(self, data_dir: Path) -> list[UserAccessRecord]:
        with self._conn() as conn:
            return coerce_user_access_records(list_user_access(conn))

    def record_usage(
        self,
        data_dir: Path,
        *,
        conversation_key: str,
        work_item_id: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        with self._conn() as conn:
            record_usage(
                conn,
                conversation_key=conversation_key,
                work_item_id=work_item_id,
                provider=provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
            )

    def get_usage_since(self, data_dir: Path, *, since_epoch: float) -> list[UsageRecord]:
        with self._conn() as conn:
            return coerce_usage_records(get_usage_since(conn, since_epoch=since_epoch))

    def close_transport_db(self, data_dir: Path) -> None:
        pass

    def close_all_transport_db(self) -> None:
        pass

    def reset_db_for_test(self, data_dir: Path) -> None:
        pass

    def debug_connection(self, data_dir: Path):
        raise NotImplementedError(
            "Postgres transport store does not expose a runtime debug connection; "
            "use the conn-based transport implementation helpers in tests"
        )
