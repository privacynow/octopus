import asyncio
from pathlib import Path

import pytest

import app.channels.telegram.ingress as th
from app.channels.telegram.cancellation import (
    TelegramCancellationRegistry,
    get_cancellation_registry,
    reset_cancellation_registry,
)
from app.channels.telegram.state import (
    TelegramChannelState,
    build_channel_state,
    get_channel_state,
    install_channel_state,
    reset_channel_state,
    set_bot_instance,
)
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    reset_channel_state()
    reset_cancellation_registry()
    yield
    reset_channel_state()
    reset_cancellation_registry()


def test_channel_state_build_and_install_round_trips():
    cfg = make_config(data_dir=Path("/tmp/channel-state"))
    provider = FakeProvider("claude")

    state = build_channel_state(cfg, provider, boot_id="boot-123")

    assert isinstance(state, TelegramChannelState)
    assert state.config is cfg
    assert state.provider is provider
    assert state.boot_id == "boot-123"
    assert state.rate_limiter is not None
    assert state.bot_instance is None

    install_channel_state(state)
    assert get_channel_state() is state

    bot = object()
    set_bot_instance(bot)
    assert get_channel_state().bot_instance is bot


def test_cancellation_registry_is_explicit_and_resettable():
    registry = get_cancellation_registry()

    assert isinstance(registry, TelegramCancellationRegistry)
    event = asyncio.Event()
    registry.set(12345, event)
    assert registry.get(12345) is event
    assert 12345 in registry

    reset_cancellation_registry()

    assert get_cancellation_registry().get(12345) is None
    assert len(get_cancellation_registry()) == 0


def test_ingress_legacy_state_accessors_are_deleted():
    assert not hasattr(th, "_cfg")
    assert not hasattr(th, "_prov")
    assert not hasattr(th, "_config")
    assert not hasattr(th, "_provider")
    assert not hasattr(th, "_bot_instance")
    assert not hasattr(th, "_LIVE_CANCEL")
