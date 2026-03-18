import asyncio
from collections import defaultdict
from pathlib import Path

import app.channels.telegram.bootstrap as telegram_bootstrap
import app.channels.telegram.cancellation as telegram_cancellation
import app.channels.telegram.routing as th
import app.channels.telegram.state as telegram_state
from app.channels.telegram.cancellation import TelegramCancellationRegistry
from app.channels.telegram.state import TelegramRuntime, build_telegram_runtime
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


def test_build_telegram_runtime_returns_explicit_runtime_instance():
    cfg = make_config(data_dir=Path("/tmp/channel-state"))
    provider = FakeProvider("claude")

    runtime = build_telegram_runtime(cfg, provider, boot_id="boot-123")

    assert isinstance(runtime, TelegramRuntime)
    assert runtime.config is cfg
    assert runtime.provider is provider
    assert runtime.boot_id == "boot-123"
    assert runtime.rate_limiter is not None
    assert runtime.bot_instance is None
    assert isinstance(runtime.cancellation_registry, TelegramCancellationRegistry)
    assert isinstance(runtime.chat_locks, defaultdict)
    assert runtime.pending_work_items == {}


def test_build_bootstrap_constructs_runtime_and_application():
    cfg = make_config(data_dir=Path("/tmp/channel-bootstrap"))
    provider = FakeProvider("claude")

    bundle = telegram_bootstrap.build_bootstrap(cfg, provider)

    assert bundle.runtime.config is cfg
    assert bundle.runtime.provider is provider
    assert bundle.runtime.bot_instance is bundle.application.bot
    assert bundle.application.bot_data["telegram_runtime"] is bundle.runtime
    assert bundle.application.bot_data["telegram_boot_id"] == bundle.runtime.boot_id


def test_runtime_owns_explicit_cancellation_registry():
    runtime = build_telegram_runtime(make_config(data_dir=Path("/tmp/channel-cancel")), FakeProvider("claude"))

    event = asyncio.Event()
    runtime.cancellation_registry.set(12345, event)

    assert runtime.cancellation_registry.get(12345) is event
    runtime.cancellation_registry.clear()
    assert runtime.cancellation_registry.get(12345) is None


def test_singleton_accessors_are_deleted():
    for name in (
        "install_channel_state",
        "get_channel_state",
        "peek_channel_state",
        "reset_channel_state",
        "set_bot_instance",
    ):
        assert not hasattr(telegram_state, name)

    for name in ("get_cancellation_registry", "reset_cancellation_registry"):
        assert not hasattr(telegram_cancellation, name)


def test_routing_module_globals_are_deleted():
    assert not hasattr(th, "CHAT_LOCKS")
    assert not hasattr(th, "_pending_work_items")
    assert not hasattr(th, "_current_update_id")
    assert not hasattr(th, "_cfg")
    assert not hasattr(th, "_prov")
    assert not hasattr(th, "_config")
    assert not hasattr(th, "_provider")
    assert not hasattr(th, "_bot_instance")
    assert not hasattr(th, "_LIVE_CANCEL")
