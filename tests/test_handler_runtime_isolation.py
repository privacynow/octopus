"""Isolation regression tests for explicit Telegram handler runtime."""

import tempfile
from pathlib import Path

import app.storage as storage_mod
import app.channels.telegram.ingress as th
import app.work_queue as work_queue_mod
from tests.support.config_support import make_config as make_bot_config
from tests.support.handler_support import (
    FakeProvider,
    current_runtime,
    reset_handler_test_runtime,
    setup_globals,
)


def test_reset_clears_explicit_test_runtime_state():
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test"))
    prov = FakeProvider("claude")
    setup_globals(cfg, prov, boot_id="mutated-boot", bot_instance=object())
    runtime = current_runtime()
    runtime.pending_work_items[999] = "fake-item-id"
    runtime.chat_locks[12345]
    runtime.cancellation_registry.set(12345, __import__("asyncio").Event())

    reset_handler_test_runtime()

    try:
        current_runtime()
    except RuntimeError:
        pass
    else:
        raise AssertionError("test runtime should be cleared after reset")


def test_setup_globals_builds_explicit_runtime_shape():
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test-explicit-runtime"))
    prov = FakeProvider("claude")
    bot = object()
    setup_globals(cfg, prov, boot_id="explicit-boot", bot_instance=bot)

    runtime = current_runtime()
    assert runtime.config is cfg
    assert runtime.provider is prov
    assert runtime.boot_id == "explicit-boot"
    assert runtime.bot_instance is bot
    assert runtime.cancellation_registry.get(12345) is None
    assert runtime.pending_work_items == {}


def test_setup_globals_does_not_restore_deleted_routing_globals():
    cfg = make_bot_config(data_dir=Path("/tmp/iso-test-no-routing-globals"))
    prov = FakeProvider("claude")
    setup_globals(cfg, prov, boot_id="boot-no-routing", bot_instance=object())

    assert not hasattr(th, "CHAT_LOCKS")
    assert not hasattr(th, "_pending_work_items")
    assert not hasattr(th, "_current_update_id")


def test_reset_closes_session_and_transport_db_caches():
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
        assert len(session_store2._connections) == 0
        assert len(transport_store2._connections) == 0
