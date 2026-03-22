"""Entry point: load config, build provider, run bot."""

import argparse
import asyncio
import logging
import signal
import sys

from telegram.error import Conflict, InvalidToken, NetworkError, TimedOut

from app.config import BotConfig, ProcessRole, fail_fast, load_config, load_config_provider_health
from app.providers.base import Provider
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from app.control_plane.processor_runner import ProcessorRunner
from app.agents.delivery import build_registry_delivery_runtime, handle_registry_delivery
from app.agents.registry_capabilities import registry_authority_capabilities
from app.agents.registry_control_processor import RegistryControlProcessor
from app.agents.registry_runtime import RegistryRuntime
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from app.storage import close_db, ensure_data_dirs
from app.work_queue import close_transport_db, recover_stale_claims, purge_old
from app.worker import poll_interval_for_runtime, start_worker_task
from app.channels.telegram.channel import TelegramChannelBootstrap
from app.channels.telegram.bootstrap import build_worker_bundle
from app.channels.registry.channel import register_registry_channels
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import build_bus_bot_services, build_noop_bot_services
from app.runtime_health import CanonicalRuntimeHealthProvider
from app.startup_diagnostics import (
    collect_telegram_doctor_diagnostics,
    configure_startup_logging,
    format_database_startup_exception,
    format_startup_exception,
    sanitize_url_for_logging,
)

PROVIDERS: dict[str, type] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
configure_startup_logging()
log = logging.getLogger(__name__)


def make_provider(config: BotConfig) -> Provider:
    cls = PROVIDERS.get(config.provider_name)
    if cls is None:
        print(f"Unknown provider: {config.provider_name}", file=sys.stderr)
        raise SystemExit(1)
    return cls(config)


async def _run_doctor(
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
    if _runs_ingress(config):
        extra_lines = await collect_telegram_doctor_diagnostics(
            config.telegram_token,
            instance=config.instance,
        )
    for line in format_runtime_health_for_doctor(report):
        if line.startswith("FAIL: "):
            print(f"  {line}", file=sys.stderr)
        elif line.startswith("WARN: "):
            print(f"  {line}", file=sys.stderr)
        else:
            print(f"  {line}")
    for line in extra_lines:
        print(f"  {line}", file=sys.stderr)
    if report.summary.error_count or extra_lines:
        raise SystemExit(1)
    print("All checks passed.")
    raise SystemExit(0)


def run_doctor(
    config: BotConfig,
    provider: Provider,
    *,
    include_provider_runtime_probe: bool = False,
) -> None:
    asyncio.run(
        _run_doctor(
            config,
            provider,
            include_provider_runtime_probe=include_provider_runtime_probe,
        )
    )


async def _run_provider_health(provider: Provider) -> None:
    """Run provider binary, auth, and live runtime probes. No DB, no Telegram."""
    errors: list[str] = []
    errors.extend(provider.check_health())
    if not errors:
        errors.extend(await provider.check_runtime_health())
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
    print("Provider auth and runtime OK.")
    raise SystemExit(0)


def _runs_ingress(config: BotConfig) -> bool:
    return bool(config.telegram_token) and config.process_role in {
        ProcessRole.ALL.value,
        ProcessRole.WEBHOOK.value,
    }


def _runs_worker(config: BotConfig) -> bool:
    return config.process_role in {ProcessRole.ALL.value, ProcessRole.WORKER.value}


def _runs_registry_runtime(config: BotConfig) -> bool:
    if config.agent_mode != "registry":
        return False
    if config.runtime_mode == "shared":
        return config.process_role in {ProcessRole.ALL.value, ProcessRole.WEBHOOK.value}
    return config.process_role == ProcessRole.ALL.value


def _should_validate_provider_auth(config: BotConfig) -> bool:
    return config.process_role != ProcessRole.WEBHOOK.value


def _close_runtime_resources(config: BotConfig) -> None:
    if config.database_url:
        from app.db.postgres import close_pools

        close_pools()
    else:
        close_transport_db(config.data_dir)
        close_db(config.data_dir)


def _exit_startup_failure(exc: BaseException, config: BotConfig, *, mode: str) -> None:
    lines = format_startup_exception(exc, instance=config.instance, mode=mode)
    if isinstance(exc, (InvalidToken, Conflict, NetworkError, TimedOut)):
        for line in lines:
            print(line, file=sys.stderr)
    else:
        log.error(
            "Unexpected startup failure in %s mode: %s",
            mode,
            exc.__class__.__name__,
        )
        for line in lines:
            print(line, file=sys.stderr)
    raise SystemExit(1)


async def run_dispatcher_process(
    dispatcher: ChannelDispatcher,
    *,
    startup=None,
    shutdown=None,
) -> None:
    """Start all dispatcher-owned ingresses and wait for shutdown."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            continue

    try:
        if startup is not None:
            await startup(stop_event)
        await dispatcher.start_all_ingresses(stop_event=stop_event)
        await stop_event.wait()
    finally:
        stop_event.set()
        await dispatcher.stop_all_ingresses()
        if shutdown is not None:
            await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Octopus Agent Platform")
    parser.add_argument("instance", nargs="?", default=None, help="Instance name (default: from BOT_INSTANCE env)")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run full health checks (config, DB, provider auth, Telegram) and exit",
    )
    parser.add_argument(
        "--doctor-live-provider",
        action="store_true",
        help="With --doctor, also run the live provider runtime probe",
    )
    parser.add_argument(
        "--provider-health",
        action="store_true",
        help="Run provider auth and live runtime checks only (no DB or Telegram)",
    )
    args = parser.parse_args()
    if args.doctor_live_provider and not args.doctor:
        parser.error("--doctor-live-provider requires --doctor")

    if args.provider_health:
        config = load_config_provider_health()
        provider = make_provider(config)
        asyncio.run(_run_provider_health(provider))
        return

    config = load_config(args.instance)
    provider = make_provider(config)
    fail_fast(config)

    # Single backend bootstrap seam: SQLite (default) or Postgres when BOT_DATABASE_URL set.
    from app import runtime_backend
    runtime_backend.init(config)

    # When using Postgres, run schema/doctor before proceeding.
    if config.database_url:
        try:
            from app.db.postgres import get_connection
            from app.db.postgres_doctor import run_doctor as run_postgres_doctor
            with get_connection(
                config.database_url,
                min_size=config.db_pool_min_size,
                max_size=config.db_pool_max_size,
                connect_timeout=config.db_connect_timeout_seconds,
            ) as conn:
                errors = run_postgres_doctor(conn)
        except Exception as e:
            log.error("Database startup check failed: %s", e.__class__.__name__)
            for line in format_database_startup_exception(e):
                print(line, file=sys.stderr)
            sys.exit(1)
        if errors:
            for e in errors:
                print(f"  FAIL: {e}", file=sys.stderr)
            print(
                "Run: docker compose --project-directory . -f infra/compose/docker-compose.yml "
                "--profile tools run --rm db-bootstrap (or db-update). See README.",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.doctor:
        run_doctor(
            config,
            provider,
            include_provider_runtime_probe=args.doctor_live_provider,
        )

    if _should_validate_provider_auth(config):
        # Validate provider auth before starting when this process may execute provider work.
        auth_errors = asyncio.run(provider.check_auth_health())
        if auth_errors:
            print("Provider not authenticated or unavailable.", file=sys.stderr)
            for e in auth_errors:
                print(f"  {e}", file=sys.stderr)
            print("Run ./scripts/provider/provider_login.sh to authenticate, or check your subscription.", file=sys.stderr)
            sys.exit(1)

    ensure_data_dirs(config.data_dir, database_url=config.database_url or "")
    init_content_store_for_config(config)
    init_credential_store_for_config(config)

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
            log.info("Registry connections: (none configured)")

    if config.allowed_actor_keys or config.allowed_usernames:
        log.info("Allowed actor keys: %s", sorted(config.allowed_actor_keys))
        log.info("Allowed usernames: %s", sorted(config.allowed_usernames))
    elif config.allow_open:
        log.warning("Bot is open to everyone (BOT_ALLOW_OPEN=1)")

    log.info("Process role: %s", config.process_role)
    bus = ControlPlaneBus(config.data_dir)
    authority_capabilities = (
        registry_authority_capabilities(config.agent_registries)
        if config.agent_registries
        else {}
    )
    directory = build_control_plane_directory(authority_capabilities)
    services = (
        build_bus_bot_services(bus, directory)
        if authority_capabilities
        else build_noop_bot_services()
    )
    dispatcher = ChannelDispatcher()
    telegram_ingress = None
    worker_runtime_bundle = None
    app = None
    if config.telegram_token:
        dispatcher.register(TelegramChannelBootstrap(config, provider, services))
        dispatcher.build_all_ingresses(config=config, delivery_handler=lambda *_args, **_kwargs: None)
        telegram_ingress = dispatcher.get_ingress("telegram")
        if telegram_ingress is None:
            raise RuntimeError("Telegram channel ingress was not built")
        telegram_ingress.runtime.channel_dispatcher = dispatcher
        worker_runtime_bundle = telegram_ingress
        app = telegram_ingress.application
    else:
        worker_runtime_bundle = build_worker_bundle(config, provider, services=services)
        worker_runtime_bundle.runtime.channel_dispatcher = dispatcher

    assert worker_runtime_bundle is not None
    boot_id = worker_runtime_bundle.runtime.boot_id

    if _runs_worker(config):
        # Recover stale work items from previous boot and purge old transport data
        recover_stale_claims(
            config.data_dir,
            boot_id,
            max_age_seconds=config.claim_lease_ttl_seconds,
        )
        purge_old(config.data_dir)

    # Worker loop: drains orphaned/recovered work items from the durable queue.
    # In single-worker mode the inline handler path handles most items; the
    # worker loop catches items that survived a crash or were left behind.
    _worker_task = None
    _worker_stop = None
    registry_runtime = None
    control_plane_runner = None
    control_plane_runner_task = None
    if config.agent_registries:
        register_registry_channels(config, config.agent_registries, dispatcher)
    if _runs_registry_runtime(config):
        delivery_runtime = build_registry_delivery_runtime(
            provider_name=provider.name,
            provider_state_factory=provider.new_provider_state,
            services=services,
            bot=app.bot if app is not None else None,
            dispatcher=dispatcher,
        )
        registry_runtime = RegistryRuntime(
            config.agent_registries,
            dispatcher,
            lambda delivery: handle_registry_delivery(
                config,
                delivery,
                runtime=delivery_runtime,
            ),
            config=config,
            runtime_health_provider=CanonicalRuntimeHealthProvider(),
            provider=provider,
        )
        control_plane_runner = ProcessorRunner(bus)
        control_plane_runner.register(RegistryControlProcessor(registry_runtime))

    async def _start_background_runtime(stop_event: asyncio.Event) -> None:
        nonlocal _worker_task, _worker_stop, control_plane_runner_task
        if _runs_worker(config):
            _worker_task, _worker_stop = start_worker_task(
                config.data_dir,
                boot_id,
                worker_runtime_bundle.worker_dispatch,
                deserialize_failure_notifier=worker_runtime_bundle.worker_deserialize_failure_notifier,
                poll_interval=poll_interval_for_runtime(config.runtime_mode),
                lease_ttl=config.claim_lease_ttl_seconds,
                sweep_interval=config.claim_sweep_interval_seconds,
                process_role=config.process_role,
                heartbeat_enabled=(config.runtime_mode == "shared"),
            )
        if registry_runtime is not None:
            await registry_runtime.start(stop_event=stop_event)
        if control_plane_runner is not None:
            await bus.reconcile_orphans(allowed_pairs=directory.all_pairs())
            control_plane_runner_task = asyncio.create_task(
                control_plane_runner.run(stop_event=stop_event)
            )

    async def _stop_background_runtime() -> None:
        nonlocal control_plane_runner_task
        if control_plane_runner is not None:
            await control_plane_runner.stop()
        if control_plane_runner_task is not None:
            try:
                await asyncio.wait_for(control_plane_runner_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                control_plane_runner_task.cancel()
            finally:
                control_plane_runner_task = None
        if registry_runtime is not None:
            await registry_runtime.stop()
        if _worker_stop:
            _worker_stop.set()
        if _worker_task:
            try:
                await asyncio.wait_for(_worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _worker_task.cancel()

    if app is not None:
        async def _on_post_init(_app) -> None:
            process_stop_event = _app.bot_data.get("dispatcher_stop_event")
            if not isinstance(process_stop_event, asyncio.Event):
                raise RuntimeError("Dispatcher stop event is not attached to the Telegram application")
            await _start_background_runtime(process_stop_event)

        async def _on_post_shutdown(_app) -> None:
            await _stop_background_runtime()

        app.post_init = _on_post_init
        app.post_shutdown = _on_post_shutdown

    if not config.telegram_token:
        log.info("Bot starting (registry-only)...")
        try:
            asyncio.run(
                run_dispatcher_process(
                    dispatcher,
                    startup=_start_background_runtime,
                    shutdown=_stop_background_runtime,
                )
            )
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            _exit_startup_failure(exc, config, mode="registry-only")
        finally:
            _close_runtime_resources(config)
    elif config.process_role == ProcessRole.WORKER.value:
        log.info("Bot starting (worker-only)...")
        try:
            asyncio.run(run_dispatcher_process(dispatcher))
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            _exit_startup_failure(exc, config, mode="worker")
        finally:
            _close_runtime_resources(config)
    elif config.bot_mode == "webhook":
        log.info("Bot starting (webhook)...")
        log.info("Webhook URL: %s", sanitize_url_for_logging(config.webhook_url))
        log.info("Listening on %s:%d", config.webhook_listen, config.webhook_port)
        try:
            asyncio.run(run_dispatcher_process(dispatcher))
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            _exit_startup_failure(exc, config, mode="webhook")
        finally:
            _close_runtime_resources(config)
    else:
        # Fail fast if another process is already polling (Telegram allows only one getUpdates per token).
        from app.runtime_health import check_polling_conflict
        try:
            conflict_msg = asyncio.run(check_polling_conflict(config.telegram_token))
        except Exception as e:
            log.debug(
                "Startup conflict check failed: %s",
                e.__class__.__name__,
            )
            conflict_msg = None
        if conflict_msg:
            log.error(
                "%s Stop the other instance (e.g. systemctl --user stop octopus-agent@%s.service) or wait a minute, then try again.",
                conflict_msg,
                config.instance,
            )
            sys.exit(1)

        log.info("Bot starting (long-poll)...")
        try:
            asyncio.run(run_dispatcher_process(dispatcher))
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            _exit_startup_failure(exc, config, mode="polling")
        finally:
            _close_runtime_resources(config)


if __name__ == "__main__":
    main()
