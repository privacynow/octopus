"""Telegram transport implementation and lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from telegram.error import TelegramError

from app import work_queue
from app.channels.telegram.bootstrap import TelegramBootstrap
from app.channels.telegram.bootstrap import build_bootstrap
from app.channels.telegram.egress import TelegramChannelEgress
from app.runtime import telegram_worker
from app.runtime import telegram_session_io
from app.config import BotConfig
from app.config import BotMode
from app.config import ProcessRole
from octopus_sdk.transport_dispatcher import TransportDispatcher
from app.runtime.services import BotServices
from octopus_sdk.config import BotConfigBase
from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key, telegram_numeric_id
from octopus_sdk.providers import Provider
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportHealthRecord
from octopus_sdk.transport import TransportIdentityResolver
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.work_queue import WorkItemRecord


class _TelegramIdentityResolver(TransportIdentityResolver):
    def conversation_key(self, raw_conversation_id: object) -> str:
        return telegram_conversation_key(str(raw_conversation_id).strip())

    def actor_key(self, raw_actor_id: object) -> str:
        return telegram_actor_key(str(raw_actor_id).strip())

    def external_conversation_ref(self, raw_conversation_id: object) -> str:
        return str(raw_conversation_id).strip()


class TelegramTransport(TransportImplementation):
    """PTB-backed Telegram transport with integrated ingress lifecycle."""

    def __init__(
        self,
        config: BotConfig,
        provider: Provider,
        services: BotServices,
        *,
        dispatcher: TransportDispatcher | None = None,
        bootstrap: TelegramBootstrap | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._services = services
        self._bootstrap = bootstrap or build_bootstrap(
            self._config,
            self._provider,
            services=self._services,
            dispatcher=dispatcher,
        )
        if dispatcher is not None and self._bootstrap.runtime.transport_dispatcher is None:
            raise RuntimeError("Telegram bootstrap requires a transport dispatcher")
        self._stop_requested = asyncio.Event()
        self._cleanup_lock = asyncio.Lock()
        self._bootstrapped = False
        self._app_started = False
        self._updater_started = False

    @property
    def transport_id(self) -> str:
        return "telegram"

    @property
    def descriptor(self) -> TransportDescriptor:
        return TransportDescriptor(
            transport_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            inbound_model=(
                "webhook"
                if self._config.bot_mode == BotMode.WEBHOOK.value
                else "poll"
            ),
            trust_tier="untrusted",
            contributes_transport_capability=True,
            accepts_transport_input=True,
            supports_conversation_binding=True,
            supports_timeline=True,
            supports_editing=True,
            supports_inline_actions=True,
            supports_recovery=True,
        )

    @property
    def identity(self) -> TransportIdentityResolver:
        return _TelegramIdentityResolver()

    @property
    def boot_id(self) -> str:
        return self._bootstrap.runtime.boot_id

    def ref_prefix(self) -> str:
        return "telegram:"

    def _resolve_chat_id(
        self,
        *,
        conversation_ref: str,
        conversation_key: str,
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

    def can_build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> bool:
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

    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        bot = kw.get("bot")
        if bot is None:
            raise RuntimeError("Telegram transport requires a bot instance")

        conversation_key = str(kw.get("conversation_key", ""))
        chat_id = self._resolve_chat_id(
            conversation_ref=conversation_ref,
            conversation_key=conversation_key,
            chat_id=kw.get("chat_id"),
        )
        if chat_id is None:
            raise RuntimeError(
                f"Telegram transport requires a Telegram conversation key, got {conversation_ref!r}"
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

    def worker_egress_kwargs(self, *, conversation_ref: str) -> dict[str, object]:
        del conversation_ref
        bot = self._bootstrap.runtime.bot_instance
        if bot is None:
            return {}
        return {"bot": bot}

    @asynccontextmanager
    async def claimed_item_context(self, *, event, item: WorkItemRecord):
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            yield
            return
        conversation_key = telegram_session_io.conversation_key(chat_id)
        lock = self._bootstrap.runtime.chat_locks[chat_id]
        async with lock:
            if getattr(event, "action", "") not in {"recovery_discard", "recovery_replay"}:
                work_queue.supersede_pending_recovery(
                    self._bootstrap.runtime.config.data_dir,
                    conversation_key,
                )
            yield

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        telegram_runtime = self._bootstrap.runtime
        telegram_runtime.submitter = runtime
        self._stop_requested.clear()
        try:
            if telegram_runtime.transport_dispatcher is None:
                raise RuntimeError("Telegram transport requires a transport dispatcher")
            application = self._bootstrap.application
            if application is not None:
                if not hasattr(application, "bot_data"):
                    application.bot_data = {}
                application.bot_data["dispatcher_stop_event"] = stop_event
                await application._bootstrap_initialize(max_retries=0)
                self._bootstrapped = True
                if application.post_init:
                    await application.post_init(application)

                if telegram_runtime.config.process_role != ProcessRole.WORKER.value:
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

    async def notify_deserialize_failure(
        self,
        item: WorkItemRecord,
        *,
        runtime,
    ) -> None:
        del runtime
        await telegram_worker.notify_deserialize_failure(
            item,
            runtime=self._bootstrap.runtime,
        )

    async def health_check(self) -> TransportHealthRecord:
        telegram_runtime = self._bootstrap.runtime
        return TransportHealthRecord(
            transport_id=self.transport_id,
            transport_type=self.descriptor.transport_type,
            inbound_model=self.descriptor.inbound_model,
            bot_mode=telegram_runtime.config.bot_mode,
            ok=(
                telegram_runtime.config.process_role == ProcessRole.WORKER.value
                or self._app_started
            ),
        )

    async def _start_live_updates(self) -> None:
        application = self._bootstrap.application
        telegram_runtime = self._bootstrap.runtime
        updater = application.updater
        if updater is None:
            raise RuntimeError("Telegram application updater is unavailable")

        if telegram_runtime.config.bot_mode == BotMode.WEBHOOK.value:
            await updater.start_webhook(
                listen=telegram_runtime.config.webhook_listen,
                port=telegram_runtime.config.webhook_port,
                webhook_url=telegram_runtime.config.webhook_url,
                secret_token=telegram_runtime.config.webhook_secret or None,
                url_path="/webhook",
            )
        else:
            await updater.start_polling(
                error_callback=self._poll_error_callback,
            )
        self._updater_started = True
        await application.start()
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
        application = self._bootstrap.application
        async with self._cleanup_lock:
            try:
                if self._updater_started and application.updater is not None:
                    await application.updater.stop()
                if self._app_started:
                    await application.stop()
                    if application.post_stop:
                        await application.post_stop(application)
            finally:
                try:
                    if self._bootstrapped:
                        await application.shutdown()
                finally:
                    if self._bootstrapped and application.post_shutdown:
                        await application.post_shutdown(application)
                    bot_data = getattr(application, "bot_data", None)
                    if isinstance(bot_data, dict):
                        bot_data.pop("dispatcher_stop_event", None)
                    self._updater_started = False
                    self._app_started = False
                    self._bootstrapped = False

    def _poll_error_callback(self, exc: TelegramError) -> None:
        application = self._bootstrap.application
        application.create_task(application.process_error(error=exc, update=None))
