"""Isolation regression tests for handler runtime (Priority 4).

Proves reset_handler_test_runtime() clears all handler globals and DB caches,
and that no state leaks between tests when the conftest autouse fixture runs.
"""

import tempfile
from pathlib import Path

import pytest

import app.storage as storage_mod
import app.telegram_handlers as th
import app.work_queue as work_queue_mod
from tests.support.handler_support import reset_handler_test_runtime, setup_globals
from tests.support.config_support import make_config as make_bot_config


def test_reset_clears_all_handler_globals():
    """Mutate runtime state then reset; assert everything is cleared."""
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test"))
    from tests.support.handler_support import FakeProvider
    prov = FakeProvider("claude")
    setup_globals(cfg, prov, boot_id="mutated-boot", bot_instance=object())
    th._pending_work_items[999] = "fake-item-id"
    th.CHAT_LOCKS[12345]  # ensure key exists (defaultdict)

    reset_handler_test_runtime()

    assert th._config is None
    assert th._provider is None
    assert th._boot_id == ""
    assert th._rate_limiter is None
    assert th._bot_instance is None
    assert len(th._pending_work_items) == 0
    assert len(th.CHAT_LOCKS) == 0


def test_clean_runtime_has_no_leaked_state():
    """Start with clean runtime; assert no leaked globals."""
    reset_handler_test_runtime()

    assert th._config is None
    assert th._provider is None
    assert th._bot_instance is None
    assert len(th._pending_work_items) == 0
    assert len(th.CHAT_LOCKS) == 0


def test_reset_closes_session_and_transport_db_caches():
    """Open session and transport DBs, then reset; assert caches are empty."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        storage_mod.ensure_data_dirs(data_dir)
        storage_mod._db(data_dir)  # open session DB
        work_queue_mod._transport_db(data_dir)  # open transport DB
        assert len(storage_mod._db_connections) >= 1
        assert len(work_queue_mod._db_connections) >= 1
        reset_handler_test_runtime()
        assert len(storage_mod._db_connections) == 0, "Session DB cache should be empty after reset"
        assert len(work_queue_mod._db_connections) == 0, "Transport DB cache should be empty after reset"
