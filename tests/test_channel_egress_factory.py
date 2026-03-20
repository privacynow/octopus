"""Contract tests for dispatcher-based channel egress composition."""

import tempfile
from pathlib import Path

from app.agents.bridge import telegram_conversation_ref
from app.channels.registry.refs import registry_conversation_ref
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.telegram.egress import TelegramChannelEgress
from app.identity import telegram_actor_key
from app.runtime.inbound_types import InboundUser
from app.runtime.work_admission import trust_tier_for_ref
from tests.support.handler_support import (
    FakeProvider,
    MinimalFakeBot,
    current_runtime,
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


def test_dispatcher_telegram_ref_produces_telegram_channel_egress():
    tmp, cfg = _setup_runtime()
    try:
        channel_egress = current_runtime().channel_dispatcher.create_egress(
            telegram_conversation_ref(cfg, 12345),
            bot=MinimalFakeBot(),
            chat_id=12345,
            source="telegram",
            config=cfg,
        )
        assert isinstance(channel_egress, TelegramChannelEgress)
    finally:
        tmp.cleanup()


def test_dispatcher_registry_ref_produces_registry_channel_egress():
    tmp = tempfile.TemporaryDirectory()
    cfg = make_config(
        Path(tmp.name),
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    setup_globals(cfg, FakeProvider("claude"))
    try:
        channel_egress = current_runtime().channel_dispatcher.create_egress(
            registry_conversation_ref("default", "abc123"),
            bot=MinimalFakeBot(),
            chat_id=0,
            source="registry",
            config=cfg,
        )
        assert isinstance(channel_egress, RegistryChannelEgress)
    finally:
        tmp.cleanup()


def test_dispatcher_trust_tier_registry_ref_is_trusted():
    tmp = tempfile.TemporaryDirectory()
    cfg = make_config(
        Path(tmp.name),
        agent_mode="registry",
        agent_registry_url="http://registry.test",
        agent_registry_enroll_token="enroll-secret",
    )
    setup_globals(cfg, FakeProvider("claude"))
    try:
        tier = trust_tier_for_ref(
            registry_conversation_ref("default", "conv-1"),
            user=None,
            config=cfg,
            dispatcher=current_runtime().channel_dispatcher,
        )
        assert tier == "trusted"
    finally:
        tmp.cleanup()


def test_dispatcher_trust_tier_telegram_ref_uses_user_tier():
    tmp, cfg = _setup_runtime(allow_open=True, allowed_user_ids=frozenset())
    try:
        tier = trust_tier_for_ref(
            telegram_conversation_ref(cfg, 12345),
            user=InboundUser(id=telegram_actor_key(999), username="stranger"),
            config=cfg,
            dispatcher=current_runtime().channel_dispatcher,
        )
        assert tier == "public"
    finally:
        tmp.cleanup()
