"""Telegram channel bootstrap and ingress lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

from telegram.error import TelegramError

from app.channels.telegram.bootstrap import TelegramBootstrap, build_bootstrap
from app.channels.telegram.egress import TelegramChannelEgress
from app.config import BotMode, BotConfig, ProcessRole
from app.identity import telegram_numeric_id
from app.ports.channel import ChannelBootstrap, ChannelDescriptor, ChannelIngress
from app.ports.egress import ChannelEgress
from app.providers.base import Provider
from app.runtime.services import BotServices, build_noop_bot_services


class TelegramChannelBootstrap(ChannelBootstrap):
    """Channel bootstrap for the Telegram runtime."""

    def __init__(
        self,
        config: BotConfig,
        provider: Provider,
        services: BotServices | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._services = services or build_noop_bot_services()

    @property
    def channel_id(self) -> str:
        return "telegram"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return ChannelDescriptor(
            channel_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            requires_polling=(self._config.bot_mode != BotMode.WEBHOOK.value),
            trust_tier="untrusted",
            contributes_channel_capability=True,
            accepts_channel_input=True,
            supports_conversation_binding=True,
            supports_timeline=True,
        )

    def ref_prefix(self) -> str:
        return "telegram:"

    def _resolve_chat_id(
        self,
        *,
        conversation_ref: str,
        conversation_key: str = "",
        chat_id: int | None = None,
    ) -> int | None:
        if chat_id is not None:
            return chat_id
        if conversation_key:
            resolved = telegram_numeric_id(conversation_key)
            if resolved is not None:
                return resolved
        suffix = conversation_ref.rsplit(":", 1)[-1]
        return int(suffix) if suffix.isdigit() else None

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        del config
        if kw.get("bot") is None:
            return False
        conversation_key = str(kw.get("conversation_key", ""))
        chat_id = kw.get("chat_id")
        return self._resolve_chat_id(
            conversation_ref=conversation_ref,
            conversation_key=conversation_key,
            chat_id=chat_id,
        ) is not None

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
        bot = kw.get("bot")
        if bot is None:
            raise RuntimeError("Telegram channel requires a bot instance")

        conversation_key = str(kw.get("conversation_key", ""))
        chat_id = self._resolve_chat_id(
            conversation_ref=conversation_ref,
            conversation_key=conversation_key,
            chat_id=kw.get("chat_id"),
        )
        if chat_id is None:
            raise RuntimeError(
                f"Telegram channel requires a Telegram conversation key, got {conversation_ref!r}"
            )

        return TelegramChannelEgress(
            bot,
            chat_id,
            config=config,
            conversation_ref=conversation_ref,
            services=self._services,
            mirror_input_event=(kw.get("source", "telegram") == "telegram"),
            target_message_id=kw.get("target_message_id"),
        )

    def build_ingress(self, *, config: Any, delivery_handler: Any) -> ChannelIngress:
        del config, delivery_handler
        return TelegramChannelIngress(
            build_bootstrap(self._config, self._provider, services=self._services),
            descriptor=self.descriptor,
        )


class TelegramChannelIngress(ChannelIngress):
    """PTB-backed Telegram ingress runner."""

    def __init__(self, bootstrap: TelegramBootstrap, *, descriptor: ChannelDescriptor) -> None:
        self._bootstrap = bootstrap
        self._descriptor = descriptor
        self._stop_requested = asyncio.Event()
        self._cleanup_lock = asyncio.Lock()
        self._bootstrapped = False
        self._app_started = False
        self._updater_started = False

    @property
    def channel_id(self) -> str:
        return "telegram"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return self._descriptor

    @property
    def application(self):
        return self._bootstrap.application

    @property
    def runtime(self):
        return self._bootstrap.runtime

    @property
    def worker_dispatch(self):
        return self._bootstrap.worker_dispatch

    @property
    def worker_deserialize_failure_notifier(self):
        return self._bootstrap.worker_deserialize_failure_notifier

    async def start(self, *, stop_event: asyncio.Event) -> None:
        self._stop_requested.clear()
        try:
            if not hasattr(self.application, "bot_data"):
                self.application.bot_data = {}
            self.application.bot_data["dispatcher_stop_event"] = stop_event
            await self.application._bootstrap_initialize(max_retries=0)
            self._bootstrapped = True
            if self.application.post_init:
                await self.application.post_init(self.application)

            if self.runtime.config.process_role != ProcessRole.WORKER.value:
                await self._start_live_updates()

            await self._wait_for_stop(stop_event)
        except asyncio.CancelledError:
            raise
        except BaseException:
            stop_event.set()
            raise
        finally:
            await self._shutdown_application()

    async def stop(self) -> None:
        self._stop_requested.set()

    async def health_check(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel_type": self.descriptor.channel_type,
            "boot_id": self.runtime.boot_id,
            "bot_mode": self.runtime.config.bot_mode,
            "process_role": self.runtime.config.process_role,
            "requires_polling": self.descriptor.requires_polling,
            "accepts_channel_input": self.descriptor.accepts_channel_input,
            "app_started": self._app_started,
            "updater_started": self._updater_started,
        }

    async def _start_live_updates(self) -> None:
        updater = self.application.updater
        if updater is None:
            raise RuntimeError("Telegram application updater is unavailable")

        if self.runtime.config.bot_mode == BotMode.WEBHOOK.value:
            await updater.start_webhook(
                listen=self.runtime.config.webhook_listen,
                port=self.runtime.config.webhook_port,
                webhook_url=self.runtime.config.webhook_url,
                secret_token=self.runtime.config.webhook_secret or None,
                url_path="/webhook",
            )
        else:
            await updater.start_polling(
                error_callback=self._poll_error_callback,
            )
        self._updater_started = True
        await self.application.start()
        self._app_started = True

    async def _wait_for_stop(self, stop_event: asyncio.Event) -> None:
        external_wait = asyncio.create_task(stop_event.wait())
        local_wait = asyncio.create_task(self._stop_requested.wait())
        try:
            await asyncio.wait(
                {external_wait, local_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            external_wait.cancel()
            local_wait.cancel()
            await asyncio.gather(external_wait, local_wait, return_exceptions=True)

    async def _shutdown_application(self) -> None:
        async with self._cleanup_lock:
            try:
                if self._updater_started and self.application.updater is not None:
                    await self.application.updater.stop()
                if self._app_started:
                    await self.application.stop()
                    if self.application.post_stop:
                        await self.application.post_stop(self.application)
            finally:
                try:
                    if self._bootstrapped:
                        await self.application.shutdown()
                finally:
                    if self._bootstrapped and self.application.post_shutdown:
                        await self.application.post_shutdown(self.application)
                    bot_data = getattr(self.application, "bot_data", None)
                    if isinstance(bot_data, dict):
                        bot_data.pop("dispatcher_stop_event", None)
                    self._updater_started = False
                    self._app_started = False
                    self._bootstrapped = False

    def _poll_error_callback(self, exc: TelegramError) -> None:
        self.application.create_task(self.application.process_error(error=exc, update=None))
