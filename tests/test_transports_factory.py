"""Contract tests for the outbound surface factory."""

import tempfile
from pathlib import Path

from app.transports import factory
from app.transports.registry_adapter import RegistryConversationIO
from app.transports.telegram_adapter import TelegramConversationIO
from tests.support.handler_support import (
    FakeProvider,
    FakeUser,
    MinimalFakeBot,
    make_config,
    setup_globals,
)


def _setup_runtime(*, allow_open: bool = False, allowed_user_ids=frozenset({1})):
    tmp = tempfile.TemporaryDirectory()
    cfg = make_config(
        Path(tmp.name),
        allow_open=allow_open,
        allowed_user_ids=allowed_user_ids,
        allowed_usernames=frozenset(),
    )
    setup_globals(cfg, FakeProvider("claude"))
    return tmp, cfg


def test_factory_telegram_ref_produces_telegram_surface():
    tmp, cfg = _setup_runtime()
    try:
        surface = factory.create_outbound_surface(
            "telegram:mybot:12345",
            bot=MinimalFakeBot(),
            chat_id=12345,
            source="telegram",
            config=cfg,
        )
        assert isinstance(surface, TelegramConversationIO)
    finally:
        tmp.cleanup()


def test_factory_registry_ref_produces_registry_surface():
    tmp, cfg = _setup_runtime()
    try:
        surface = factory.create_outbound_surface(
            "registry:abc123",
            bot=MinimalFakeBot(),
            chat_id=0,
            source="registry",
            config=cfg,
        )
        assert isinstance(surface, RegistryConversationIO)
    finally:
        tmp.cleanup()


def test_factory_trust_tier_registry_source_is_trusted():
    tier = factory.trust_tier_for_source("registry", user=None)
    assert tier == "trusted"


def test_factory_trust_tier_telegram_source_uses_user_tier():
    tmp, cfg = _setup_runtime(allow_open=True, allowed_user_ids=frozenset())
    try:
        del cfg
        tier = factory.trust_tier_for_source(
            "telegram",
            user=FakeUser(uid=999, username="stranger"),
        )
        assert tier == "public"
    finally:
        tmp.cleanup()
