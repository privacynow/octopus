"""Contract tests for channel egress composition."""

import tempfile
from pathlib import Path

from app.channels.registry.egress import RegistryChannelEgress
from app.channels.telegram.egress import TelegramChannelEgress
from app.identity import telegram_actor_key
from app.runtime.inbound_types import InboundUser
from app.runtime import composition
from app.runtime.work_admission import trust_tier_for_source
from tests.support.handler_support import (
    FakeProvider,
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
        surface = composition.create_channel_egress(
            "telegram:mybot:12345",
            bot=MinimalFakeBot(),
            chat_id=12345,
            source="telegram",
            config=cfg,
        )
        assert isinstance(surface, TelegramChannelEgress)
    finally:
        tmp.cleanup()


def test_factory_registry_ref_produces_registry_surface():
    tmp, cfg = _setup_runtime()
    try:
        surface = composition.create_channel_egress(
            "registry:abc123",
            bot=MinimalFakeBot(),
            chat_id=0,
            source="registry",
            config=cfg,
        )
        assert isinstance(surface, RegistryChannelEgress)
    finally:
        tmp.cleanup()


def test_factory_trust_tier_registry_source_is_trusted():
    tmp, cfg = _setup_runtime()
    try:
        tier = trust_tier_for_source("registry", user=None, config=cfg)
        assert tier == "trusted"
    finally:
        tmp.cleanup()


def test_factory_trust_tier_telegram_source_uses_user_tier():
    tmp, cfg = _setup_runtime(allow_open=True, allowed_user_ids=frozenset())
    try:
        tier = trust_tier_for_source(
            "telegram",
            user=InboundUser(id=telegram_actor_key(999), username="stranger"),
            config=cfg,
        )
        assert tier == "public"
    finally:
        tmp.cleanup()
