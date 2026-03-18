"""Isolation regression tests for handler runtime (Priority 4).

Proves reset_handler_test_runtime() clears all handler globals and DB caches,
and that no state leaks between tests when the conftest autouse fixture runs.
"""

import tempfile
from pathlib import Path

import pytest

import app.storage as storage_mod
import app.channels.telegram.routing as th
import app.work_queue as work_queue_mod
from app.channels.telegram.state import peek_channel_state
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

    assert peek_channel_state() is None
    assert len(th._pending_work_items) == 0
    assert len(th.CHAT_LOCKS) == 0


def test_clean_runtime_has_no_leaked_state():
    """Start with clean runtime; assert no leaked globals."""
    reset_handler_test_runtime()

    assert peek_channel_state() is None
    assert len(th._pending_work_items) == 0
    assert len(th.CHAT_LOCKS) == 0


def test_setup_globals_does_not_restore_legacy_ingress_globals():
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test-no-legacy-globals"))
    from tests.support.handler_support import FakeProvider

    prov = FakeProvider("claude")
    setup_globals(cfg, prov, boot_id="boot-no-legacy", bot_instance=object())

    assert not hasattr(th, "_config")
    assert not hasattr(th, "_provider")
    assert not hasattr(th, "_bot_instance")
    assert not hasattr(th, "_LIVE_CANCEL")


def test_setup_globals_installs_explicit_channel_state():
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test-explicit-channel-state"))
    from tests.support.handler_support import FakeProvider

    prov = FakeProvider("claude")
    bot = object()
    setup_globals(cfg, prov, boot_id="explicit-boot", bot_instance=bot)

    state = peek_channel_state()
    assert state is not None
    assert state.config is cfg
    assert state.provider is prov
    assert state.boot_id == "explicit-boot"
    assert state.bot_instance is bot


def test_reset_closes_session_and_transport_db_caches():
    """Open session and transport DBs, then reset; assert new backend has empty caches."""
    from app import runtime_backend

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        storage_mod.ensure_data_dirs(data_dir)
        session_store = runtime_backend.session_store()
        transport_store = runtime_backend.transport_store()
        storage_mod.debug_session_connection(data_dir)
        work_queue_mod.debug_transport_connection(data_dir)
        assert len(session_store._connections) >= 1
        assert len(transport_store._connections) >= 1
        reset_handler_test_runtime()
        session_store2 = runtime_backend.session_store()
        transport_store2 = runtime_backend.transport_store()
        assert len(session_store2._connections) == 0, "Session DB cache should be empty after reset"
        assert len(transport_store2._connections) == 0, "Transport DB cache should be empty after reset"
