import asyncio
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.channels.telegram.bootstrap as telegram_bootstrap
import app.channels.telegram.cancellation as telegram_cancellation
import app.channels.telegram.ingress as th
import app.channels.telegram.state as telegram_state
from app.channels.telegram.channel import TelegramChannelBootstrap, TelegramChannelIngress
from app.channels.telegram.egress import TelegramChannelEgress
from app.channels.telegram.cancellation import TelegramCancellationRegistry
from app.channels.telegram.state import TelegramRuntime, build_telegram_runtime
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import BotServices
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider, MinimalFakeBot


class _FakeUpdater:
    def __init__(self, lifecycle: list[object]) -> None:
        self._lifecycle = lifecycle
        self.start_polling = AsyncMock(side_effect=self._start_polling)
        self.start_webhook = AsyncMock(side_effect=self._start_webhook)
        self.stop = AsyncMock(side_effect=self._stop)

    async def _start_polling(self, **kwargs):
        self._lifecycle.append(("poll", kwargs))

    async def _start_webhook(self, **kwargs):
        self._lifecycle.append(("webhook", kwargs))

    async def _stop(self):
        self._lifecycle.append("updater_stop")


class _FakeApplication:
    def __init__(self, lifecycle: list[object]) -> None:
        self._lifecycle = lifecycle
        self.updater = _FakeUpdater(lifecycle)
        self.post_init = AsyncMock(side_effect=lambda _app: lifecycle.append("post_init"))
        self.post_stop = AsyncMock(side_effect=lambda _app: lifecycle.append("post_stop"))
        self.post_shutdown = AsyncMock(side_effect=lambda _app: lifecycle.append("post_shutdown"))

    async def _bootstrap_initialize(self, max_retries: int) -> None:
        self._lifecycle.append(("bootstrap", max_retries))

    async def start(self) -> None:
        self._lifecycle.append("start")

    async def stop(self) -> None:
        self._lifecycle.append("stop")

    async def shutdown(self) -> None:
        self._lifecycle.append("shutdown")

    async def process_error(self, *, error, update=None) -> None:
        self._lifecycle.append(("error", error, update))

    def create_task(self, coro):
        return asyncio.create_task(coro)


def _fake_ingress(cfg, *, lifecycle: list[object]) -> TelegramChannelIngress:
    provider = FakeProvider("claude")
    runtime = build_telegram_runtime(cfg, provider, boot_id="test-boot")
    bootstrap = telegram_bootstrap.TelegramBootstrap(
        application=_FakeApplication(lifecycle),
        runtime=runtime,
        worker_dispatch=lambda *_args, **_kwargs: None,
        worker_deserialize_failure_notifier=None,
    )
    return TelegramChannelIngress(
        bootstrap,
        descriptor=TelegramChannelBootstrap(cfg, provider).descriptor,
    )


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
    assert isinstance(runtime.services, BotServices)


def test_build_bootstrap_constructs_runtime_and_application():
    cfg = make_config(data_dir=Path("/tmp/channel-bootstrap"))
    provider = FakeProvider("claude")

    bundle = telegram_bootstrap.build_bootstrap(cfg, provider)

    assert bundle.runtime.config is cfg
    assert bundle.runtime.provider is provider
    assert bundle.runtime.bot_instance is bundle.application.bot
    assert bundle.application.bot_data["telegram_runtime"] is bundle.runtime
    assert bundle.application.bot_data["telegram_boot_id"] == bundle.runtime.boot_id


def test_telegram_channel_bootstrap_builds_ingress_and_dispatches_egress():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel"))
    provider = FakeProvider("claude")
    dispatcher = ChannelDispatcher()
    bootstrap = TelegramChannelBootstrap(cfg, provider)
    dispatcher.register(bootstrap)

    ingresses = dispatcher.build_all_ingresses(config=cfg, delivery_handler=lambda *_args: None)
    ingress = dispatcher.get_ingress("telegram")
    assert list(ingresses) == ["telegram"]
    assert isinstance(ingress, TelegramChannelIngress)
    assert ingress.runtime.config is cfg
    assert isinstance(ingress.runtime.services, BotServices)
    assert dispatcher.active_channel_types() == ["telegram"]

    egress = dispatcher.create_egress(
        "telegram:test-bot:12345",
        config=cfg,
        bot=MinimalFakeBot(),
        source="telegram",
    )
    assert isinstance(egress, TelegramChannelEgress)
    assert egress.chat_id == 12345


def test_telegram_channel_bootstrap_rejects_missing_bot_for_egress():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel-missing-bot"))
    bootstrap = TelegramChannelBootstrap(cfg, FakeProvider("claude"))

    with pytest.raises(RuntimeError, match="requires a bot instance"):
        bootstrap.build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            source="telegram",
        )


def test_telegram_channel_bootstrap_can_build_egress_without_constructing_one():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel-readiness"))
    bootstrap = TelegramChannelBootstrap(cfg, FakeProvider("claude"))

    assert (
        bootstrap.can_build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            bot=MinimalFakeBot(),
            source="telegram",
        )
        is True
    )
    assert (
        bootstrap.can_build_egress(
            conversation_ref="telegram:test-bot:not-a-chat-id",
            config=cfg,
            bot=MinimalFakeBot(),
            source="telegram",
        )
        is False
    )
    assert (
        bootstrap.can_build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            bot=None,
            source="telegram",
        )
        is False
    )


async def test_telegram_channel_ingress_poll_mode_runs_ptb_lifecycle():
    cfg = make_config(data_dir=Path("/tmp/telegram-ingress-poll"), bot_mode="poll")
    lifecycle: list[object] = []
    ingress = _fake_ingress(cfg, lifecycle=lifecycle)

    stop_event = asyncio.Event()
    task = asyncio.create_task(ingress.start(stop_event=stop_event))
    await asyncio.sleep(0)
    stop_event.set()
    await task

    assert lifecycle[0] == ("bootstrap", 0)
    assert lifecycle[1] == "post_init"
    assert lifecycle[2][0] == "poll"
    assert "error_callback" in lifecycle[2][1]
    assert lifecycle[3] == "start"
    assert lifecycle[-5:] == ["updater_stop", "stop", "post_stop", "shutdown", "post_shutdown"]
    health = await ingress.health_check()
    assert health["channel_id"] == "telegram"
    assert health["bot_mode"] == "poll"
    assert health["requires_polling"] is True


async def test_telegram_channel_ingress_webhook_mode_starts_webhook():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-webhook"),
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_listen="0.0.0.0",
        webhook_port=8443,
        webhook_secret="secret-token",
    )
    lifecycle: list[object] = []
    ingress = _fake_ingress(cfg, lifecycle=lifecycle)
    app = ingress.application

    stop_event = asyncio.Event()
    task = asyncio.create_task(ingress.start(stop_event=stop_event))
    await asyncio.sleep(0)
    stop_event.set()
    await task

    assert ("webhook", {
        "listen": "0.0.0.0",
        "port": 8443,
        "webhook_url": "https://bot.example.com/webhook",
        "secret_token": "secret-token",
        "url_path": "/webhook",
    }) in lifecycle
    app.updater.start_polling.assert_not_called()


async def test_telegram_channel_ingress_worker_role_skips_live_updater():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-worker"),
        runtime_mode="shared",
        process_role="worker",
        bot_mode="webhook",
        webhook_url="https://bot.example.com/webhook",
    )
    lifecycle: list[object] = []
    ingress = _fake_ingress(cfg, lifecycle=lifecycle)
    app = ingress.application

    stop_event = asyncio.Event()
    task = asyncio.create_task(ingress.start(stop_event=stop_event))
    await asyncio.sleep(0)
    await ingress.stop()
    await task

    assert ("bootstrap", 0) in lifecycle
    assert "post_init" in lifecycle
    assert "start" not in lifecycle
    app.updater.start_polling.assert_not_called()
    app.updater.start_webhook.assert_not_called()
    app.updater.stop.assert_not_called()
    health = await ingress.health_check()
    assert health["process_role"] == "worker"
    assert health["app_started"] is False
    assert health["updater_started"] is False


def test_runtime_owns_explicit_cancellation_registry():
    runtime = build_telegram_runtime(make_config(data_dir=Path("/tmp/channel-cancel")), FakeProvider("claude"))

    event = asyncio.Event()
    runtime.cancellation_registry.set(12345, event)

    assert runtime.cancellation_registry.get(12345) is event
    runtime.cancellation_registry.clear()
    assert runtime.cancellation_registry.get(12345) is None


def test_cancellation_registry_normalizes_numeric_chat_ids_to_qualified_keys():
    runtime = build_telegram_runtime(make_config(data_dir=Path("/tmp/channel-cancel")), FakeProvider("claude"))

    event = asyncio.Event()
    runtime.cancellation_registry.set(12345, event)

    assert runtime.cancellation_registry.get("tg:12345") is event
    assert "tg:12345" in runtime.cancellation_registry
    assert 12345 in runtime.cancellation_registry
    assert runtime.cancellation_registry.get("slack:12345") is None


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
