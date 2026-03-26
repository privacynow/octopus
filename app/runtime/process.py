"""Profile-driven runtime composition and process execution helpers."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass

from telegram.error import Conflict, InvalidToken, NetworkError, TimedOut

from app.agents.registry_capabilities import registry_authority_capabilities, registry_id_from_authority_ref
from app.agents.state import runtime_registry_agent_id
from app.channels.registry.channel import register_registry_channels
from app.channels.registry.delivery_transport import build_registry_delivery_transport
from app.channels.telegram.channel import TelegramTransport
from app.channels.telegram.bootstrap import build_worker_bundle
from app.config import BotConfig, BotMode, ProcessRole
from app.content_store import init_content_store_for_config
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.credential_store import init_credential_store_for_config
from app.runtime.services import build_bus_bot_services
from app.runtime.services import BotServices
from app.runtime.transport_dispatcher import TransportDispatcher
from app.startup_diagnostics import (
    collect_telegram_doctor_diagnostics,
    format_startup_exception,
    sanitize_url_for_logging,
)
from app.storage import close_db
from app.storage import ensure_data_dirs
from app.worker import poll_interval_for_runtime, start_worker_task
from app.work_queue import close_transport_db, purge_old, recover_stale_claims
from octopus_sdk.bot_runtime import BotRuntime
from octopus_sdk.bot_runtime import RuntimeLifecyclePort
from octopus_sdk.providers import Provider
from app.runtime.session_runtime import LocalSessionRuntime

log = logging.getLogger(__name__)


@dataclass
class RuntimeProcess:
    boot_id: str
    services: BotServices
    bot_runtime: BotRuntime


@dataclass
class WorkerRuntimeLifecycle(RuntimeLifecyclePort):
    config: BotConfig
    worker_runtime_bundle: object | None
    worker_task: asyncio.Task[None] | None = None
    worker_stop: asyncio.Event | None = None

    async def startup(self, stop_event: asyncio.Event) -> None:
        if self.worker_runtime_bundle is None:
            del stop_event
            return
        if runs_worker(self.config):
            self.worker_task, self.worker_stop = start_worker_task(
                self.config.data_dir,
                self.worker_runtime_bundle.runtime.boot_id,
                self.worker_runtime_bundle.worker_dispatch,
                deserialize_failure_notifier=self.worker_runtime_bundle.worker_deserialize_failure_notifier,
                poll_interval=poll_interval_for_runtime(self.config.runtime_mode),
                lease_ttl=self.config.claim_lease_ttl_seconds,
                sweep_interval=self.config.claim_sweep_interval_seconds,
                process_role=self.config.process_role,
                heartbeat_enabled=(self.config.runtime_mode == "shared"),
            )
        del stop_event

    async def shutdown(self) -> None:
        if self.worker_runtime_bundle is None:
            return
        if self.worker_stop is not None:
            self.worker_stop.set()
        if self.worker_task is not None:
            try:
                await asyncio.wait_for(self.worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.worker_task.cancel()


def runs_ingress(config: BotConfig) -> bool:
    return bool(config.telegram_token) and config.process_role in {
        ProcessRole.ALL.value,
        ProcessRole.WEBHOOK.value,
    }


def runs_worker(config: BotConfig) -> bool:
    return config.process_role in {ProcessRole.ALL.value, ProcessRole.WORKER.value}


def runs_registry_transport(config: BotConfig) -> bool:
    if config.agent_mode != "registry":
        return False
    if config.runtime_mode == "shared":
        return config.process_role in {ProcessRole.ALL.value, ProcessRole.WEBHOOK.value}
    return config.process_role == ProcessRole.ALL.value


def should_validate_provider_auth(config: BotConfig) -> bool:
    return config.process_role != ProcessRole.WEBHOOK.value


def log_runtime_profile(config: BotConfig, provider: Provider) -> None:
    log.info("Instance: %s", config.instance)
    log.info("Provider: %s", provider.name)
    log.info("Working dir: %s", config.working_dir)
    log.info("Data dir: %s", config.data_dir)
    log.info("Agent mode: %s", config.agent_mode)
    if config.agent_mode == "registry":
        if config.agent_registries:
            for registry in config.agent_registries:
                log.info(
                    "Registry connection [%s] (%s): %s",
                    registry.registry_id,
                    registry.registry_scope,
                    sanitize_url_for_logging(registry.url) if registry.url else "(missing url)",
                )
        else:
            log.warning("Registry mode is configured but no registry connections are present.")

    if config.allowed_actor_keys or config.allowed_usernames:
        log.info("Allowed actor keys: %s", sorted(config.allowed_actor_keys))
        log.info("Allowed usernames: %s", sorted(config.allowed_usernames))
    elif config.allow_open:
        log.warning("Bot is open to everyone (BOT_ALLOW_OPEN=1)")

    log.info("Process role: %s", config.process_role)


async def run_doctor(
    config: BotConfig,
    provider: Provider,
    *,
    include_provider_runtime_probe: bool = False,
) -> None:
    from app.runtime_health import collect_runtime_health_report, format_runtime_health_for_doctor

    report = await collect_runtime_health_report(
        config,
        provider,
        include_provider_runtime_probe=include_provider_runtime_probe,
    )
    extra_lines: list[str] = []
    if runs_ingress(config):
        extra_lines = await collect_telegram_doctor_diagnostics(
            config.telegram_token,
            instance=config.instance,
        )
    for line in format_runtime_health_for_doctor(report):
        stream = sys.stderr if line.startswith(("FAIL: ", "WARN: ")) else sys.stdout
        print(f"  {line}", file=stream)
    for line in extra_lines:
        print(f"  {line}", file=sys.stderr)
    if report.summary.error_count or extra_lines:
        raise SystemExit(1)
    print("All checks passed.")
    raise SystemExit(0)


async def run_provider_health(provider: Provider) -> None:
    errors: list[str] = []
    errors.extend(provider.check_health())
    if not errors:
        errors.extend(await provider.check_runtime_health())
    if errors:
        for error in errors:
            print(f"  FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Provider auth and runtime OK.")
    raise SystemExit(0)


def _close_runtime_resources(config: BotConfig) -> None:
    if config.database_url:
        from app.db.postgres import close_pools

        close_pools()
    else:
        close_transport_db(config.data_dir)
        close_db(config.data_dir)


def _exit_startup_failure(exc: BaseException, config: BotConfig, *, mode: str) -> None:
    lines = format_startup_exception(exc, instance=config.instance, mode=mode)
    if not isinstance(exc, (InvalidToken, Conflict, NetworkError, TimedOut)):
        log.error(
            "Unexpected startup failure in %s mode: %s",
            mode,
            exc.__class__.__name__,
        )
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(1)


def run_runtime_process(config: BotConfig, runtime_process: RuntimeProcess) -> None:
    if not config.telegram_token:
        log.info("Bot starting (registry-only)...")
        runner = runtime_process.bot_runtime.run()
        failure_mode = "registry-only"
    elif config.process_role == ProcessRole.WORKER.value:
        log.info("Bot starting (worker-only)...")
        runner = runtime_process.bot_runtime.run()
        failure_mode = "worker"
    elif config.bot_mode == BotMode.WEBHOOK.value:
        log.info("Bot starting (webhook)...")
        log.info("Webhook URL: %s", sanitize_url_for_logging(config.webhook_url))
        log.info("Listening on %s:%d", config.webhook_listen, config.webhook_port)
        runner = runtime_process.bot_runtime.run()
        failure_mode = "webhook"
    else:
        from app.runtime_health import check_polling_conflict

        try:
            conflict_msg = asyncio.run(check_polling_conflict(config.telegram_token))
        except Exception as exc:
            log.debug("Startup conflict check failed: %s", exc.__class__.__name__)
            conflict_msg = None
        if conflict_msg:
            log.error(
                "%s Stop the other instance (e.g. systemctl --user stop octopus-agent@%s.service) or wait a minute, then try again.",
                conflict_msg,
                config.instance,
            )
            raise SystemExit(1)

        log.info("Bot starting (long-poll)...")
        runner = runtime_process.bot_runtime.run()
        failure_mode = "polling"

    try:
        asyncio.run(runner)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _exit_startup_failure(exc, config, mode=failure_mode)
    finally:
        _close_runtime_resources(config)


def _build_services(config: BotConfig):
    bus = ControlPlaneBus(config.data_dir)
    authority_capabilities = (
        registry_authority_capabilities(config.agent_registries)
        if config.agent_registries
        else {}
    )
    directory = build_control_plane_directory(authority_capabilities)

    def _agent_id_for_authority(authority_ref: str) -> str:
        try:
            registry_id = registry_id_from_authority_ref(authority_ref)
        except ValueError:
            return ""
        registry = next(
            (item for item in config.agent_registries if item.registry_id == registry_id),
            None,
        )
        return runtime_registry_agent_id(
            config.data_dir,
            registry_id,
            registry_scope=registry.registry_scope if registry is not None else "full",
        )

    services = build_bus_bot_services(
        bus,
        directory,
        config=config,
        agent_id_for_authority=_agent_id_for_authority,
    )
    if authority_capabilities and not services.registry.health.live_local_agent_ids():
        log.warning(
            "Registry capabilities configured but no agent enrollment found. "
            "Event publishing and delegation will not work until bots enroll."
        )
    return bus, directory, services


def validate_required_runtime_profile(config: BotConfig) -> None:
    if not config.telegram_token:
        return
    if config.agent_mode != "registry":
        raise RuntimeError(
            "Telegram runtime requires BOT_AGENT_MODE=registry in this implementation."
        )
    if not config.agent_registries:
        raise RuntimeError(
            "Telegram runtime requires configured registry connections in this implementation."
        )
    has_channel = any(
        registry.registry_scope in {"channel", "full"}
        for registry in config.agent_registries
    )
    has_coordination = any(
        registry.registry_scope in {"coordination", "full"}
        for registry in config.agent_registries
    )
    if not has_channel or not has_coordination:
        raise RuntimeError(
            "Telegram runtime requires full registry participant coverage "
            "(channel and coordination capabilities)."
        )


def compose_runtime_process(config: BotConfig, provider: Provider) -> RuntimeProcess:
    validate_required_runtime_profile(config)
    bus, directory, services = _build_services(config)
    dispatcher = TransportDispatcher()
    worker_runtime_bundle = None
    runtime_boot_id = ""

    if config.telegram_token:
        telegram_transport = TelegramTransport(
            config,
            provider,
            services,
            dispatcher=dispatcher,
        )
        dispatcher.register(telegram_transport)
        runtime_boot_id = telegram_transport.boot_id
    else:
        worker_runtime_bundle = build_worker_bundle(config, provider, services=services)
        worker_runtime_bundle.runtime.transport_dispatcher = dispatcher
        runtime_boot_id = worker_runtime_bundle.runtime.boot_id

    if not runtime_boot_id:
        raise RuntimeError("Runtime process requires a boot identifier")

    if config.agent_registries:
        register_registry_channels(
            config,
            config.agent_registries,
            dispatcher,
            services=services,
        )
    if runs_registry_transport(config):
        dispatcher.register(
            build_registry_delivery_transport(
                config,
                provider,
                services=services,
                dispatcher=dispatcher,
                bus=bus,
                directory=directory,
            )
        )

    bot_runtime = BotRuntime(
        config=config,
        transport=dispatcher,
        registry=services.registry,
        provider=provider,
        sessions=LocalSessionRuntime(config),
        workflows=services.workflows,
        authorization=services.authorization,
        work_queue=services.work_queue,
        lifecycle=WorkerRuntimeLifecycle(
            config=config,
            worker_runtime_bundle=worker_runtime_bundle,
        ),
    )

    return RuntimeProcess(
        boot_id=runtime_boot_id,
        services=services,
        bot_runtime=bot_runtime,
    )


def prepare_and_run_runtime(config: BotConfig, provider: Provider) -> None:
    ensure_data_dirs(config.data_dir, database_url=config.database_url or "")
    init_content_store_for_config(config)
    init_credential_store_for_config(config)
    log_runtime_profile(config, provider)

    runtime_process = compose_runtime_process(config, provider)
    if runs_worker(config):
        recover_stale_claims(
            config.data_dir,
            runtime_process.boot_id,
            max_age_seconds=config.claim_lease_ttl_seconds,
        )
        purge_old(config.data_dir)

    run_runtime_process(config, runtime_process)
