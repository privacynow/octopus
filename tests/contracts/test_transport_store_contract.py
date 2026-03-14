"""Transport store contract: backend-neutral behavior. Runs against SQLite and Postgres via work_queue facade."""

import json
import tempfile
import time
from pathlib import Path

import pytest

from app.work_queue import (
    record_update,
    get_update_payload,
    record_and_enqueue,
    enqueue_work_item,
    claim_for_update,
    claim_next,
    claim_next_any,
    complete_work_item,
    fail_work_item,
    has_claimed_for_chat,
    has_queued_or_claimed,
    mark_pending_recovery,
    get_latest_pending_recovery,
    get_pending_recovery_for_update,
    supersede_pending_recovery,
    discard_recovery,
    reclaim_for_replay,
    recover_stale_claims,
    update_payload,
)
from app.transport_contract import DiscardResult
from app.storage import ensure_data_dirs


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


# --- update journal idempotency ---

def test_record_update_idempotent(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert record_update(data_dir, 1001, chat_id=1, user_id=42, kind="message") is True
    assert record_update(data_dir, 1001, chat_id=1, user_id=42, kind="message") is False


# --- payload persistence ---

def test_record_update_stores_payload(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 2001, chat_id=1, user_id=42, kind="message", payload='{"text":"hello"}')
    raw = get_update_payload(data_dir, 2001)
    assert raw is not None
    assert json.loads(raw) == {"text": "hello"}


def test_get_update_payload_missing(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert get_update_payload(data_dir, 9999) is None


def test_update_payload(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 3001, chat_id=1, user_id=42, kind="message", payload="{}")
    update_payload(data_dir, 3001, '{"edited": true}')
    raw = get_update_payload(data_dir, 3001)
    assert raw is not None
    assert json.loads(raw) == {"edited": True}


# --- record_and_enqueue / enqueue ---

def test_record_and_enqueue_returns_true_and_item_id(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    # record_and_enqueue does update journal + work item in one go; no prior record_update
    is_new, item_id = record_and_enqueue(data_dir, 100, 1, 42, "message")
    assert is_new is True
    assert item_id is not None


def test_record_and_enqueue_idempotent_duplicate_update(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_and_enqueue(data_dir, 101, 1, 42, "message")
    is_new2, item_id2 = record_and_enqueue(data_dir, 101, 1, 42, "message")
    assert is_new2 is False
    assert item_id2 is None


def test_enqueue_work_item_returns_id(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 102, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=102)
    assert item_id is not None


# --- claim semantics ---

def test_claim_for_update_and_complete(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_and_enqueue(data_dir, 200, 1, 42, "message", payload='{"text":"hi"}')
    item = claim_for_update(data_dir, chat_id=1, update_id=200, worker_id="w1")
    assert item is not None
    assert item["state"] == "claimed"
    complete_work_item(data_dir, item["id"])
    assert has_queued_or_claimed(data_dir, 1) is False


def test_claim_next_returns_queued_item(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 201, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=201)
    item = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert item is not None
    assert item["update_id"] == 201
    assert item["state"] == "claimed"


def test_claim_next_none_when_nothing_queued(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert claim_next(data_dir, chat_id=1, worker_id="w1") is None


def test_claim_next_any_returns_any_chat_item(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 301, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 302, chat_id=2, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=301)
    enqueue_work_item(data_dir, chat_id=2, update_id=302)
    item = claim_next_any(data_dir, worker_id="w1")
    assert item is not None
    assert item["update_id"] in (301, 302)


# --- per-chat serialization ---

def test_only_one_claimed_per_chat(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 401, chat_id=1, user_id=42, kind="message")
    record_update(data_dir, 402, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=401)
    enqueue_work_item(data_dir, chat_id=1, update_id=402)
    first = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert first is not None
    second = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert second is None
    complete_work_item(data_dir, first["id"])
    second = claim_next(data_dir, chat_id=1, worker_id="w1")
    assert second is not None
    assert second["update_id"] == 402


# --- complete / fail transitions ---

def test_complete_work_item(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 501, chat_id=1, user_id=42, kind="message")
    item_id = enqueue_work_item(data_dir, chat_id=1, update_id=501)
    claim_next(data_dir, chat_id=1, worker_id="w1")
    complete_work_item(data_dir, item_id)
    assert has_queued_or_claimed(data_dir, 1) is False


def test_fail_work_item(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 502, chat_id=1, user_id=42, kind="message")
    _, item_id = record_and_enqueue(data_dir, 502, 1, 42, "message")
    claim_for_update(data_dir, chat_id=1, update_id=502, worker_id="w1")
    fail_work_item(data_dir, item_id, "test error")
    assert has_queued_or_claimed(data_dir, 1) is False


# --- pending recovery lifecycle ---

def test_mark_pending_recovery_and_get_latest(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, 601, 1, 42, "message")
    claim_for_update(data_dir, chat_id=1, update_id=601, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    latest = get_latest_pending_recovery(data_dir, 1)
    assert latest is not None
    assert latest["id"] == item_id
    by_update = get_pending_recovery_for_update(data_dir, 1, 601)
    assert by_update is not None
    assert by_update["id"] == item_id


def test_supersede_pending_recovery(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, 602, 1, 42, "message")
    claim_for_update(data_dir, chat_id=1, update_id=602, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    n = supersede_pending_recovery(data_dir, 1)
    assert n >= 1
    assert get_latest_pending_recovery(data_dir, 1) is None


# --- discard / replay ---

def test_discard_recovery(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, 701, 1, 42, "message")
    claim_for_update(data_dir, chat_id=1, update_id=701, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    result = discard_recovery(data_dir, item_id)
    assert result == DiscardResult.success
    assert get_latest_pending_recovery(data_dir, 1) is None


def test_reclaim_for_replay(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    _, item_id = record_and_enqueue(data_dir, 702, 1, 42, "message", payload='{"text":"replay me"}')
    claim_for_update(data_dir, chat_id=1, update_id=702, worker_id="w1")
    mark_pending_recovery(data_dir, item_id)
    item = reclaim_for_replay(data_dir, item_id, worker_id="w2")
    assert item is not None
    assert item["state"] == "claimed"
    assert item["worker_id"] == "w2"


# --- stale claim recovery ---

def test_recover_stale_claims(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 801, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=801)
    claim_next(data_dir, chat_id=1, worker_id="old-boot")
    assert has_claimed_for_chat(data_dir, 1) is True
    time.sleep(1.1)
    n = recover_stale_claims(data_dir, current_worker_id="new-boot", max_age_seconds=1)
    assert n == 1
    item = claim_next(data_dir, chat_id=1, worker_id="new-boot")
    assert item is not None
    assert item["update_id"] == 801


# --- has_queued_or_claimed ---

def test_has_queued_or_claimed_false_when_empty(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert has_queued_or_claimed(data_dir, 1) is False


def test_has_queued_or_claimed_true_after_enqueue(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    record_update(data_dir, 901, chat_id=1, user_id=42, kind="message")
    enqueue_work_item(data_dir, chat_id=1, update_id=901)
    assert has_queued_or_claimed(data_dir, 1) is True
