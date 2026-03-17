"""Transport store contract: backend-neutral behavior. Runs against SQLite and Postgres via work_queue facade."""

import json
import tempfile
import time
from pathlib import Path

import pytest

from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.storage import ensure_data_dirs
from app.transport_contract import CancelRequestResult, DiscardResult
from app.work_queue import (
    cancel_queued_fresh_for_chat,
    claim_for_update,
    claim_next,
    claim_next_any,
    complete_work_item,
    discard_recovery,
    enqueue_work_item,
    fail_work_item,
    get_latest_pending_recovery,
    get_pending_recovery_for_update,
    get_update_payload,
    get_usage_since,
    get_user_access,
    get_work_items_for_chat,
    has_claimed_for_chat,
    has_queued_or_claimed,
    list_user_access,
    mark_pending_recovery,
    is_cancel_requested,
    request_cancel,
    reclaim_for_replay,
    record_and_admit_message,
    record_and_enqueue,
    record_update,
    record_usage,
    recover_stale_claims,
    set_user_access,
    supersede_pending_recovery,
    update_payload,
)


def _conv(value: int) -> str:
    return telegram_conversation_key(value)


def _actor(value: int) -> str:
    return telegram_actor_key(value)


def _event(value: int) -> str:
    return telegram_event_id(value)


@pytest.fixture(params=["sqlite", "postgres"])
def backend_and_data_dir(request):
    """Provide (backend_name, data_dir) for contract tests."""
    from app import runtime_backend
    from tests.support.config_support import make_config

    if request.param == "sqlite":
        runtime_backend.reset_for_test()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            ensure_data_dirs(data_dir)
            yield "sqlite", data_dir
        return

    postgres_url = request.getfixturevalue("postgres_truncated")
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir, database_url=postgres_url)
        cfg = make_config(data_dir=data_dir, database_url=postgres_url)
        runtime_backend.init(cfg)
        try:
            yield "postgres", data_dir
        finally:
            runtime_backend.reset_for_test()


def test_record_update_idempotent(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    assert record_update(
        data_dir, _event(1001), conversation_key=_conv(1), actor_key=_actor(42), kind="message"
    ) is True
    assert record_update(
        data_dir, _event(1001), conversation_key=_conv(1), actor_key=_actor(42), kind="message"
    ) is False


def test_record_update_stores_payload(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(
        data_dir,
        _event(2001),
        conversation_key=_conv(1),
        actor_key=_actor(42),
        kind="message",
        payload='{"text":"hello"}',
    )
    raw = get_update_payload(data_dir, _event(2001))
    assert raw is not None
    assert json.loads(raw) == {"text": "hello"}


def test_get_update_payload_missing(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    assert get_update_payload(data_dir, _event(9999)) is None


def test_update_payload(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(
        data_dir,
        _event(3001),
        conversation_key=_conv(1),
        actor_key=_actor(42),
        kind="message",
        payload="{}",
    )
    update_payload(data_dir, _event(3001), '{"edited": true}')
    raw = get_update_payload(data_dir, _event(3001))
    assert raw is not None
    assert json.loads(raw) == {"edited": True}


def test_record_and_enqueue_returns_true_and_item_id(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    is_new, item_id = record_and_enqueue(data_dir, _event(100), _conv(1), _actor(42), "message")
    assert is_new is True
    assert item_id is not None


def test_record_and_enqueue_idempotent_duplicate_update(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_and_enqueue(data_dir, _event(101), _conv(1), _actor(42), "message")
    is_new2, item_id2 = record_and_enqueue(data_dir, _event(101), _conv(1), _actor(42), "message")
    assert is_new2 is False
    assert item_id2 is None


def test_enqueue_work_item_returns_id(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(102), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(102))
    assert item_id is not None


def test_claim_for_update_and_complete(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_and_enqueue(data_dir, _event(200), _conv(1), _actor(42), "message", payload='{"text":"hi"}')
    item = claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(200), worker_id="w1")
    assert item is not None
    assert item["state"] == "claimed"
    complete_work_item(data_dir, item["id"])
    assert has_queued_or_claimed(data_dir, _conv(1)) is False


def test_claim_next_returns_queued_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(201), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(201))
    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert item is not None
    assert item["event_id"] == _event(201)
    assert item["state"] == "claimed"


def test_claim_next_none_when_nothing_queued(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    assert claim_next(data_dir, conversation_key=_conv(1), worker_id="w1") is None


def test_claim_next_any_returns_any_chat_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(301), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(302), conversation_key=_conv(2), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(301))
    enqueue_work_item(data_dir, conversation_key=_conv(2), event_id=_event(302))
    item = claim_next_any(data_dir, worker_id="w1")
    assert item is not None
    assert item["event_id"] in (_event(301), _event(302))


def test_only_one_claimed_per_chat(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(401), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    record_update(data_dir, _event(402), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(401))
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(402))
    first = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert first is not None
    second = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert second is None
    complete_work_item(data_dir, first["id"])
    second = claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    assert second is not None
    assert second["event_id"] == _event(402)


def test_complete_work_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(501), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    item_id = enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(501))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="w1")
    complete_work_item(data_dir, item_id)
    assert has_queued_or_claimed(data_dir, _conv(1)) is False


def test_fail_work_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(502), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    _, item_id = record_and_enqueue(data_dir, _event(502), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(502), worker_id="w1")
    fail_work_item(data_dir, item_id, "test error")
    assert has_queued_or_claimed(data_dir, _conv(1)) is False


def test_request_cancel_sets_flag_on_claimed_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, _event(550), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(550), worker_id="w1")
    result = request_cancel(
        data_dir,
        conversation_key=_conv(1),
        actor_key=_actor(42),
        cancel_request_event_id=_event(551),
    )
    assert result == CancelRequestResult.claimed_cancel_requested
    assert is_cancel_requested(data_dir, item_id) is True


def test_request_cancel_returns_nothing_when_idle(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    result = request_cancel(
        data_dir,
        conversation_key=_conv(1),
        actor_key=_actor(42),
        cancel_request_event_id=_event(552),
    )
    assert result == CancelRequestResult.nothing_to_cancel


def test_request_cancel_cancels_queued_fresh_item(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    status, item_id = record_and_admit_message(
        data_dir,
        _event(553),
        _conv(1),
        _actor(42),
        "message",
        '{"text":"queued"}',
    )
    assert status == "admitted"
    result = request_cancel(
        data_dir,
        conversation_key=_conv(1),
        actor_key=_actor(42),
        cancel_request_event_id=_event(554),
    )
    assert result == CancelRequestResult.queued_cancelled
    items = get_work_items_for_chat(data_dir, _conv(1))
    cancelled = [row for row in items if row["id"] == item_id]
    assert cancelled and cancelled[0]["state"] == "failed"
    assert cancelled[0]["error"] == "cancelled"


def test_recover_stale_claims_honors_cancel_request(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, _event(555), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(555), worker_id="w1")
    result = request_cancel(
        data_dir,
        conversation_key=_conv(1),
        actor_key=_actor(42),
        cancel_request_event_id=_event(556),
    )
    assert result == CancelRequestResult.claimed_cancel_requested
    recovered = recover_stale_claims(data_dir, current_worker_id="w2", max_age_seconds=0)
    assert recovered >= 1
    items = get_work_items_for_chat(data_dir, _conv(1))
    final = [row for row in items if row["id"] == item_id]
    assert final and final[0]["state"] == "failed"
    assert final[0]["error"] == "cancelled"


def test_mark_pending_recovery_and_get_latest(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, _event(601), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(601), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    latest = get_latest_pending_recovery(data_dir, _conv(1))
    assert latest is not None
    assert latest["id"] == item_id
    by_update = get_pending_recovery_for_update(data_dir, _conv(1), _event(601))
    assert by_update is not None
    assert by_update["id"] == item_id


def test_supersede_pending_recovery(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, _event(602), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(602), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    n = supersede_pending_recovery(data_dir, _conv(1))
    assert n >= 1
    assert get_latest_pending_recovery(data_dir, _conv(1)) is None


def test_discard_recovery(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, _event(701), _conv(1), _actor(42), "message")
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(701), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    result = discard_recovery(data_dir, item_id)
    assert result == DiscardResult.success
    assert get_latest_pending_recovery(data_dir, _conv(1)) is None


def test_reclaim_for_replay(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(
        data_dir, _event(702), _conv(1), _actor(42), "message", payload='{"text":"replay me"}'
    )
    claim_for_update(data_dir, conversation_key=_conv(1), event_id=_event(702), worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    item = reclaim_for_replay(data_dir, item_id, worker_id="w2")
    assert item is not None
    assert item["state"] == "claimed"
    assert item["worker_id"] == "w2"


def test_recover_stale_claims(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(801), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(801))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="old-boot")
    assert has_claimed_for_chat(data_dir, _conv(1)) is True
    time.sleep(1.1)
    n = recover_stale_claims(data_dir, current_worker_id="new-boot", max_age_seconds=1)
    assert n == 1
    item = claim_next(data_dir, conversation_key=_conv(1), worker_id="new-boot")
    assert item is not None
    assert item["event_id"] == _event(801)


def test_live_claim_by_other_worker_not_recovered(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(802), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(802))
    claim_next(data_dir, conversation_key=_conv(1), worker_id="worker-a")
    n = recover_stale_claims(data_dir, current_worker_id="worker-b", max_age_seconds=300)
    assert n == 0
    assert has_claimed_for_chat(data_dir, _conv(1)) is True


def test_has_queued_or_claimed_false_when_empty(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    assert has_queued_or_claimed(data_dir, _conv(1)) is False


def test_has_queued_or_claimed_true_after_enqueue(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_update(data_dir, _event(901), conversation_key=_conv(1), actor_key=_actor(42), kind="message")
    enqueue_work_item(data_dir, conversation_key=_conv(1), event_id=_event(901))
    assert has_queued_or_claimed(data_dir, _conv(1)) is True


def test_cancel_queued_fresh_for_chat_terminal_state(backend_and_data_dir):
    """cancel_queued_fresh_for_chat: returns True, targeted item is failed/cancelled, no fresh runnable remains."""
    _backend, data_dir = backend_and_data_dir
    conversation_key = _conv(99)
    status, item_id = record_and_admit_message(
        data_dir,
        event_id=_event(5001),
        conversation_key=conversation_key,
        actor_key=_actor(42),
        kind="message",
        payload="{}",
    )
    assert status == "admitted"
    assert item_id is not None

    ok = cancel_queued_fresh_for_chat(data_dir, conversation_key)
    assert ok is True

    items = get_work_items_for_chat(data_dir, conversation_key)
    cancelled = [i for i in items if i.get("state") == "failed" and i.get("error") == "cancelled"]
    runnable = [i for i in items if i.get("state") in ("queued", "claimed")]
    assert len(cancelled) == 1, f"Exactly one item must be failed/cancelled, got: {items}"
    assert len(runnable) == 0, f"No runnable items after cancel, got: {items}"
    assert has_queued_or_claimed(data_dir, conversation_key) is False


def test_second_fresh_message_queues_not_rejects(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    first_status, first_item_id = record_and_admit_message(
        data_dir,
        _event(5002),
        _conv(7),
        _actor(42),
        "message",
        '{"text":"first"}',
    )
    second_status, second_item_id = record_and_admit_message(
        data_dir,
        _event(5003),
        _conv(7),
        _actor(42),
        "message",
        '{"text":"second"}',
    )
    assert first_status == "admitted"
    assert second_status == "queued"
    items = get_work_items_for_chat(data_dir, _conv(7))
    by_id = {row["id"]: row for row in items}
    assert by_id[first_item_id]["state"] == "queued"
    assert by_id[second_item_id]["state"] == "queued"


def test_queued_items_drain_fifo(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    statuses = [
        record_and_admit_message(data_dir, _event(5004), _conv(8), _actor(42), "message", '{"text":"1"}'),
        record_and_admit_message(data_dir, _event(5005), _conv(8), _actor(42), "message", '{"text":"2"}'),
        record_and_admit_message(data_dir, _event(5006), _conv(8), _actor(42), "message", '{"text":"3"}'),
    ]
    assert [status for status, _item_id in statuses] == ["admitted", "queued", "queued"]
    first = claim_next(data_dir, conversation_key=_conv(8), worker_id="w1")
    assert first is not None and first["event_id"] == _event(5004)
    complete_work_item(data_dir, first["id"])
    second = claim_next(data_dir, conversation_key=_conv(8), worker_id="w1")
    assert second is not None and second["event_id"] == _event(5005)
    complete_work_item(data_dir, second["id"])
    third = claim_next(data_dir, conversation_key=_conv(8), worker_id="w1")
    assert third is not None and third["event_id"] == _event(5006)


def test_single_claimed_per_conversation_with_queued_backlog(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_and_admit_message(data_dir, _event(5007), _conv(9), _actor(42), "message", '{"text":"1"}')
    record_and_admit_message(data_dir, _event(5008), _conv(9), _actor(42), "message", '{"text":"2"}')
    first = claim_next(data_dir, conversation_key=_conv(9), worker_id="w1")
    assert first is not None
    second = claim_next(data_dir, conversation_key=_conv(9), worker_id="w2")
    assert second is None


def test_user_access_no_row_returns_none(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    assert get_user_access(data_dir, actor_key=_actor(99999)) is None


def test_user_access_set_and_get_round_trip(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    set_user_access(data_dir, actor_key=_actor(100), access="blocked", reason="test", granted_by=_actor(1))
    assert get_user_access(data_dir, actor_key=_actor(100)) == "blocked"
    set_user_access(data_dir, actor_key=_actor(100), access="allowed", reason="reversed", granted_by=_actor(1))
    assert get_user_access(data_dir, actor_key=_actor(100)) == "allowed"


def test_user_access_list_covers_all_rows(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    set_user_access(data_dir, actor_key=_actor(200), access="allowed", reason="a", granted_by=_actor(1))
    set_user_access(data_dir, actor_key=_actor(201), access="blocked", reason="b", granted_by=_actor(1))
    rows = list_user_access(data_dir)
    actor_keys = {row["actor_key"] for row in rows}
    assert _actor(200) in actor_keys
    assert _actor(201) in actor_keys
    assert all(row["access"] in ("allowed", "blocked") for row in rows)


def test_record_usage_and_retrieve(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_usage(
        data_dir,
        conversation_key=_conv(1),
        work_item_id="work-1",
        provider="claude",
        prompt_tokens=123,
        completion_tokens=45,
        cost_usd=0.0123,
    )

    rows = get_usage_since(data_dir, since_epoch=0.0)

    assert len(rows) == 1
    row = rows[0]
    assert row["conversation_key"] == _conv(1)
    assert row["work_item_id"] == "work-1"
    assert row["provider"] == "claude"
    assert row["prompt_tokens"] == 123
    assert row["completion_tokens"] == 45
    assert row["cost_usd"] == pytest.approx(0.0123)
    assert isinstance(row["recorded_at"], float)
    assert row["recorded_at"] > 0


def test_get_usage_since_filters_by_time(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_usage(
        data_dir,
        conversation_key=_conv(1),
        work_item_id="work-a",
        provider="claude",
        prompt_tokens=1,
        completion_tokens=2,
        cost_usd=0.0,
    )
    time.sleep(0.02)
    threshold = time.time()
    time.sleep(0.02)
    record_usage(
        data_dir,
        conversation_key=_conv(2),
        work_item_id="work-b",
        provider="codex",
        prompt_tokens=3,
        completion_tokens=4,
        cost_usd=0.0,
    )

    rows = get_usage_since(data_dir, since_epoch=threshold)

    assert len(rows) == 1
    assert rows[0]["work_item_id"] == "work-b"


def test_record_usage_zero_tokens_persists(backend_and_data_dir):
    _backend, data_dir = backend_and_data_dir
    record_usage(
        data_dir,
        conversation_key=_conv(5),
        work_item_id="work-zero",
        provider="codex",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
    )

    rows = get_usage_since(data_dir, since_epoch=0.0)

    assert len(rows) == 1
    row = rows[0]
    assert row["conversation_key"] == _conv(5)
    assert row["work_item_id"] == "work-zero"
    assert row["provider"] == "codex"
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0
    assert row["cost_usd"] == pytest.approx(0.0)
