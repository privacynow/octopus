import asyncio
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.channels.telegram.bootstrap as telegram_bootstrap
import app.runtime.telegram_ingress as th
import app.channels.telegram.state as telegram_state
from app.channels.telegram.channel import TelegramTransport
from app.channels.telegram.egress import TelegramChannelEgress
from app.channels.telegram.state import TelegramCancellationRegistry, TelegramRuntime, build_telegram_runtime
from app.runtime.services import BotServices
from octopus_sdk.transport_dispatcher import TransportDispatcher
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider
from tests.support.handler_support import MinimalFakeBot
from tests.support.service_support import build_test_bot_services
from octopus_sdk.transport import InboundSubmissionResult
from octopus_sdk.work_queue import WorkItemRecord


class _RuntimeHandle:
    async def submit(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="admitted")

    async def admit_message(self, envelope):
        del envelope
        return InboundSubmissionResult(status="admitted")

    async def enqueue(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="queued")

    async def record(self, envelope):
        del envelope
        return True


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
        self.bot_data: dict[str, object] = {}

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


def _fake_transport(cfg, *, lifecycle: list[object]) -> TelegramTransport:
    provider = FakeProvider("claude")
    services = build_test_bot_services()
    transport = TelegramTransport(cfg, provider, services)
    runtime = build_telegram_runtime(cfg, provider, boot_id="test-boot", services=services)
    runtime.transport_dispatcher = TransportDispatcher()
    transport._bootstrap = telegram_bootstrap.TelegramBootstrap(
        application=_FakeApplication(lifecycle),
        runtime=runtime,
        execution_runtime=telegram_bootstrap._execution_runtime(runtime),
    )
    return transport


def test_build_telegram_runtime_returns_explicit_runtime_instance():
    cfg = make_config(data_dir=Path("/tmp/channel-state"))
    provider = FakeProvider("claude")

    runtime = build_telegram_runtime(
        cfg,
        provider,
        boot_id="boot-123",
        services=build_test_bot_services(),
    )

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
    assert runtime.submitter is not None


def test_build_bootstrap_constructs_runtime_and_application():
    cfg = make_config(data_dir=Path("/tmp/channel-bootstrap"))
    provider = FakeProvider("claude")

    bundle = telegram_bootstrap.build_bootstrap(cfg, provider, services=build_test_bot_services())

    assert bundle.runtime.config is cfg
    assert bundle.runtime.provider is provider
    assert bundle.runtime.bot_instance is bundle.application.bot
    assert bundle.application.bot_data["telegram_runtime"] is bundle.runtime
    assert bundle.application.bot_data["telegram_boot_id"] == bundle.runtime.boot_id


def test_telegram_transport_registers_and_dispatches_egress():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel"))
    provider = FakeProvider("claude")
    dispatcher = TransportDispatcher()
    transport = TelegramTransport(cfg, provider, build_test_bot_services(), dispatcher=dispatcher)
    dispatcher.register(transport)

    registered = dispatcher.get_transport("telegram")
    assert registered is transport
    assert registered.boot_id == transport.boot_id
    assert dispatcher.reported_transport_implementations() == ["telegram"]

    egress = dispatcher.create_egress(
        "telegram:test-bot:12345",
        config=cfg,
        bot=MinimalFakeBot(),
        source="telegram",
    )
    assert isinstance(egress, TelegramChannelEgress)
    assert egress.chat_id == 12345


def test_telegram_transport_rejects_missing_bot_for_egress():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel-missing-bot"))
    transport = TelegramTransport(cfg, FakeProvider("claude"), build_test_bot_services())

    with pytest.raises(RuntimeError, match="requires a bot instance"):
        transport.build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            source="telegram",
        )


def test_telegram_transport_can_build_egress_without_constructing_one():
    cfg = make_config(data_dir=Path("/tmp/telegram-channel-readiness"))
    transport = TelegramTransport(cfg, FakeProvider("claude"), build_test_bot_services())

    assert (
        transport.can_build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            bot=MinimalFakeBot(),
            source="telegram",
        )
        is True
    )
    assert (
        transport.can_build_egress(
            conversation_ref="telegram:test-bot:not-a-chat-id",
            config=cfg,
            bot=MinimalFakeBot(),
            source="telegram",
        )
        is False
    )
    assert (
        transport.can_build_egress(
            conversation_ref="telegram:test-bot:12345",
            config=cfg,
            bot=None,
            source="telegram",
        )
        is False
    )


async def test_telegram_transport_poll_mode_runs_ptb_lifecycle():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-poll"),
        bot_mode="poll",
        process_role="webhook",
    )
    lifecycle: list[object] = []
    transport = _fake_transport(cfg, lifecycle=lifecycle)

    stop_event = asyncio.Event()
    task = asyncio.create_task(transport.start(runtime=_RuntimeHandle(), stop_event=stop_event))
    await asyncio.sleep(0)
    stop_event.set()
    await task

    assert lifecycle[0] == ("bootstrap", 0)
    assert lifecycle[1] == "post_init"
    assert lifecycle[2][0] == "poll"
    assert "error_callback" in lifecycle[2][1]
    assert lifecycle[3] == "start"
    assert lifecycle[-5:] == ["updater_stop", "stop", "post_stop", "shutdown", "post_shutdown"]
    health = await transport.health_check()
    assert health["transport_id"] == "telegram"
    assert health["bot_mode"] == "poll"
    assert health["inbound_model"] == "poll"


async def test_telegram_transport_webhook_mode_starts_webhook():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-webhook"),
        bot_mode="webhook",
        process_role="webhook",
        webhook_url="https://bot.example.com/webhook",
        webhook_listen="0.0.0.0",
        webhook_port=8443,
        webhook_secret="secret-token",
    )
    lifecycle: list[object] = []
    transport = _fake_transport(cfg, lifecycle=lifecycle)
    app = transport._bootstrap.application

    stop_event = asyncio.Event()
    task = asyncio.create_task(transport.start(runtime=_RuntimeHandle(), stop_event=stop_event))
    await asyncio.sleep(0)
    stop_event.set()
    await task

    assert lifecycle[2][0] == "webhook"
    kwargs = lifecycle[2][1]
    assert kwargs["listen"] == "0.0.0.0"
    assert kwargs["port"] == 8443
    assert kwargs["webhook_url"] == "https://bot.example.com/webhook"
    assert kwargs["secret_token"] == "secret-token"
    assert kwargs["url_path"] == "/webhook"
    assert app.bot_data.get("dispatcher_stop_event") is None


async def test_telegram_transport_stops_on_local_stop_request():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-local-stop"),
        bot_mode="poll",
        process_role="webhook",
    )
    lifecycle: list[object] = []
    transport = _fake_transport(cfg, lifecycle=lifecycle)
    stop_event = asyncio.Event()

    task = asyncio.create_task(transport.start(runtime=_RuntimeHandle(), stop_event=stop_event))
    await asyncio.sleep(0)
    await transport.stop()
    await task

    assert "updater_stop" in lifecycle


async def test_telegram_transport_propagates_startup_failures():
    cfg = make_config(
        data_dir=Path("/tmp/telegram-ingress-failure"),
        bot_mode="poll",
        process_role="webhook",
    )
    lifecycle: list[object] = []
    transport = _fake_transport(cfg, lifecycle=lifecycle)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("bootstrap failed")

    transport._bootstrap.application._bootstrap_initialize = _boom

    stop_event = asyncio.Event()
    with pytest.raises(RuntimeError, match="bootstrap failed"):
        await transport.start(runtime=_RuntimeHandle(), stop_event=stop_event)
    assert stop_event.is_set()


async def test_poll_error_callback_schedules_application_error_processing():
    cfg = make_config(data_dir=Path("/tmp/telegram-error-callback"))
    lifecycle: list[object] = []
    transport = _fake_transport(cfg, lifecycle=lifecycle)

    class _Err(Exception):
        pass

    transport._poll_error_callback(_Err("boom"))
    await asyncio.sleep(0)

    assert lifecycle[0][0] == "error"
    assert isinstance(lifecycle[0][1], _Err)
    assert lifecycle[0][2] is None


def test_default_rate_limiter_in_public_mode_applies_safe_limits():
    cfg = make_config(
        data_dir=Path("/tmp/rate-limiter-open"),
        allow_open=True,
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
    )

    limiter = telegram_state._build_rate_limiter(cfg)

    assert limiter.per_minute == 5
    assert limiter.per_hour == 30


def test_configured_rate_limiter_preserves_explicit_limits():
    cfg = make_config(
        data_dir=Path("/tmp/rate-limiter-configured"),
        allow_open=True,
        rate_limit_per_minute=12,
        rate_limit_per_hour=144,
    )

    limiter = telegram_state._build_rate_limiter(cfg)

    assert limiter.per_minute == 12
    assert limiter.per_hour == 144


def test_rate_limiter_without_public_mode_keeps_zero_limits():
    cfg = make_config(
        data_dir=Path("/tmp/rate-limiter-private"),
        allow_open=False,
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
    )

    limiter = telegram_state._build_rate_limiter(cfg)

    assert limiter.per_minute == 0
    assert limiter.per_hour == 0
