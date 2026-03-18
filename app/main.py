"""Entry point: load config, build provider, run bot."""

import argparse
import asyncio
import logging
import signal
import sys

from app.config import BotConfig, ProcessRole, fail_fast, load_config, load_config_provider_health
from app.providers.base import Provider
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.agents.delivery import handle_registry_delivery
from app.agents.runtime import start_agent_runtime_task
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from app.storage import close_db, ensure_data_dirs
from app.work_queue import close_transport_db, recover_stale_claims, purge_old
from app.worker import poll_interval_for_runtime, start_worker_task
from app.channels.telegram.bootstrap import build_application
from app.runtime_health import CanonicalRuntimeHealthProvider

PROVIDERS: dict[str, type] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def make_provider(config: BotConfig) -> Provider:
    cls = PROVIDERS.get(config.provider_name)
    if cls is None:
        print(f"Unknown provider: {config.provider_name}", file=sys.stderr)
        raise SystemExit(1)
    return cls(config)


async def _run_doctor(config: BotConfig, provider: Provider) -> None:
    from app.runtime_health import collect_runtime_health_report, format_runtime_health_for_doctor

    report = await collect_runtime_health_report(config, provider)
    for line in format_runtime_health_for_doctor(report):
        if line.startswith("FAIL: "):
            print(f"  {line}", file=sys.stderr)
        elif line.startswith("WARN: "):
            print(f"  {line}", file=sys.stderr)
        else:
            print(f"  {line}")
    if report.summary.error_count:
        raise SystemExit(1)
    print("All checks passed.")
    raise SystemExit(0)


def run_doctor(config: BotConfig, provider: Provider) -> None:
    import asyncio
    asyncio.run(_run_doctor(config, provider))


async def _run_provider_health(provider: Provider) -> None:
    """Run only provider binary + runtime auth checks. No DB, no Telegram."""
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
    return config.process_role in {ProcessRole.ALL.value, ProcessRole.WEBHOOK.value}


def _runs_worker(config: BotConfig) -> bool:
    return config.process_role in {ProcessRole.ALL.value, ProcessRole.WORKER.value}


def _runs_registry_runtime(config: BotConfig) -> bool:
    if config.agent_mode != "registry":
        return False
    if config.runtime_mode == "shared":
        return config.process_role in {ProcessRole.ALL.value, ProcessRole.WEBHOOK.value}
    return config.process_role == ProcessRole.ALL.value


def _should_validate_provider_runtime(config: BotConfig) -> bool:
    return config.process_role != ProcessRole.WEBHOOK.value


def _close_runtime_resources(config: BotConfig) -> None:
    if config.database_url:
        from app.db.postgres import close_pools

        close_pools()
    else:
        close_transport_db(config.data_dir)
        close_db(config.data_dir)


async def run_worker_process(app) -> None:
    """Initialize the Telegram app globals and keep worker-owned tasks alive."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            continue

    await app.initialize()
    try:
        if app.post_init:
            await app.post_init(app)
        await stop_event.wait()
    finally:
        if app.post_shutdown:
            await app.post_shutdown(app)
        await app.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Octopus Agent Platform")
    parser.add_argument("instance", nargs="?", default=None, help="Instance name (default: from BOT_INSTANCE env)")
    parser.add_argument("--doctor", action="store_true", help="Run full health checks (config, DB, provider, Telegram) and exit")
    parser.add_argument("--provider-health", action="store_true", help="Run only provider auth/runtime checks and exit (no DB or Telegram)")
    args = parser.parse_args()

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
            print(f"Database error: {e}", file=sys.stderr)
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
        run_doctor(config, provider)

    if _should_validate_provider_runtime(config):
        # Validate provider auth before starting when this process may execute provider work.
        runtime_errors = asyncio.run(provider.check_runtime_health())
        if runtime_errors:
            print("Provider not authenticated or unavailable.", file=sys.stderr)
            for e in runtime_errors:
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
        log.info("Agent registry: %s", config.agent_registry_url or "(degraded: not configured)")

    if config.allowed_actor_keys or config.allowed_usernames:
        log.info("Allowed actor keys: %s", sorted(config.allowed_actor_keys))
        log.info("Allowed usernames: %s", sorted(config.allowed_usernames))
    elif config.allow_open:
        log.warning("Bot is open to everyone (BOT_ALLOW_OPEN=1)")

    log.info("Process role: %s", config.process_role)
    app = build_application(config, provider)

    from app.channels.telegram.ingress import _boot_id as boot_id

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
    _agent_task = None
    _agent_stop = None

    async def _on_post_init(_app) -> None:
        nonlocal _worker_task, _worker_stop, _agent_task, _agent_stop
        from app.channels.telegram.ingress import worker_dispatch
        if _runs_worker(config):
            _worker_task, _worker_stop = start_worker_task(
                config.data_dir,
                boot_id,
                worker_dispatch,
                poll_interval=poll_interval_for_runtime(config.runtime_mode),
                lease_ttl=config.claim_lease_ttl_seconds,
                sweep_interval=config.claim_sweep_interval_seconds,
                process_role=config.process_role,
                heartbeat_enabled=(config.runtime_mode == "shared"),
            )
        if _runs_registry_runtime(config):
            _agent_task, _agent_stop = start_agent_runtime_task(
                config,
                delivery_handler=lambda delivery: handle_registry_delivery(config, delivery),
                runtime_health_provider=CanonicalRuntimeHealthProvider(),
                provider=provider,
            )

    async def _on_post_shutdown(_app) -> None:
        if _agent_stop:
            _agent_stop.set()
        if _worker_stop:
            _worker_stop.set()
        if _agent_task:
            try:
                await asyncio.wait_for(_agent_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _agent_task.cancel()
        if _worker_task:
            try:
                await asyncio.wait_for(_worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _worker_task.cancel()

    app.post_init = _on_post_init
    app.post_shutdown = _on_post_shutdown

    if config.process_role == ProcessRole.WORKER.value:
        log.info("Bot starting (worker-only)...")
        try:
            asyncio.run(run_worker_process(app))
        except KeyboardInterrupt:
            pass
        finally:
            _close_runtime_resources(config)
    elif config.bot_mode == "webhook":
        log.info("Bot starting (webhook)...")
        log.info("Webhook URL: %s", config.webhook_url)
        log.info("Listening on %s:%d", config.webhook_listen, config.webhook_port)
        try:
            app.run_webhook(
                listen=config.webhook_listen,
                port=config.webhook_port,
                webhook_url=config.webhook_url,
                secret_token=config.webhook_secret or None,
                url_path="/webhook",
            )
        finally:
            _close_runtime_resources(config)
    else:
        # Fail fast if another process is already polling (Telegram allows only one getUpdates per token).
        from app.runtime_health import check_polling_conflict
        try:
            conflict_msg = asyncio.run(check_polling_conflict(config.telegram_token))
        except Exception as e:
            log.debug("Startup conflict check failed: %s", e)
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
            app.run_polling()
        finally:
            _close_runtime_resources(config)


if __name__ == "__main__":
    main()
