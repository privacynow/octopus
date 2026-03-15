"""Entry point: load config, build provider, run bot."""

import argparse
import asyncio
import logging
import sys

from app.config import BotConfig, fail_fast, load_config, load_config_provider_health
from app.providers.base import Provider
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.storage import close_db, ensure_data_dirs
from app.work_queue import close_transport_db, recover_stale_claims, purge_old
from app.worker import start_worker_task
from app.store import startup_recovery
from app.telegram_handlers import build_application

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
    from app.doctor import collect_doctor_report
    report = await collect_doctor_report(config, provider)
    if report.errors:
        for e in report.errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
    if report.warnings:
        for w in report.warnings:
            print(f"  WARN: {w}", file=sys.stderr)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Agent Bot")
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

    # Phase 13: Only local runtime is supported. Reject shared until Phase 18.
    if config.runtime_mode != "local":
        print("Only Local Runtime is supported (BOT_RUNTIME_MODE=local).", file=sys.stderr)
        if config.runtime_mode == "shared":
            print("BOT_RUNTIME_MODE=shared (Shared Runtime) is not available until Phase 18.", file=sys.stderr)
        sys.exit(1)

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
            print("Run: docker compose --profile tools run --rm db-bootstrap (or db-update). See README.", file=sys.stderr)
            sys.exit(1)

    if args.doctor:
        run_doctor(config, provider)

    # Validate provider auth before starting (same check as doctor; clear message if missing)
    runtime_errors = asyncio.run(provider.check_runtime_health())
    if runtime_errors:
        print("Provider not authenticated or unavailable.", file=sys.stderr)
        for e in runtime_errors:
            print(f"  {e}", file=sys.stderr)
        print("Run ./scripts/provider_login.sh to authenticate, or check your subscription.", file=sys.stderr)
        sys.exit(1)

    ensure_data_dirs(config.data_dir, database_url=config.database_url or "")
    startup_recovery()

    log.info("Instance: %s", config.instance)
    log.info("Provider: %s", provider.name)
    log.info("Working dir: %s", config.working_dir)
    log.info("Data dir: %s", config.data_dir)

    if config.allowed_user_ids or config.allowed_usernames:
        log.info("Allowed user IDs: %s", sorted(config.allowed_user_ids))
        log.info("Allowed usernames: %s", sorted(config.allowed_usernames))
    elif config.allow_open:
        log.warning("Bot is open to everyone (BOT_ALLOW_OPEN=1)")

    app = build_application(config, provider)

    # Recover stale work items from previous boot and purge old transport data
    from app.telegram_handlers import _boot_id as boot_id
    recover_stale_claims(config.data_dir, boot_id)
    purge_old(config.data_dir)

    # Worker loop: drains orphaned/recovered work items from the durable queue.
    # In single-worker mode the inline handler path handles most items; the
    # worker loop catches items that survived a crash or were left behind.
    _worker_task = None
    _worker_stop = None

    async def _on_post_init(_app) -> None:
        nonlocal _worker_task, _worker_stop
        from app.telegram_handlers import worker_dispatch
        _worker_task, _worker_stop = start_worker_task(
            config.data_dir, boot_id, worker_dispatch,
        )

    async def _on_post_shutdown(_app) -> None:
        if _worker_stop:
            _worker_stop.set()
        if _worker_task:
            try:
                await asyncio.wait_for(_worker_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _worker_task.cancel()

    app.post_init = _on_post_init
    app.post_shutdown = _on_post_shutdown

    if config.bot_mode == "webhook":
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
            if config.database_url:
                from app.db.postgres import close_pools
                close_pools()
            else:
                close_transport_db(config.data_dir)
                close_db(config.data_dir)
    else:
        # Fail fast if another process is already polling (Telegram allows only one getUpdates per token).
        from app.doctor import check_polling_conflict
        try:
            conflict_msg = asyncio.run(check_polling_conflict(config.telegram_token))
        except Exception as e:
            log.debug("Startup conflict check failed: %s", e)
            conflict_msg = None
        if conflict_msg:
            log.error(
                "%s Stop the other instance (e.g. systemctl --user stop telegram-agent-bot@%s.service) or wait a minute, then try again.",
                conflict_msg,
                config.instance,
            )
            sys.exit(1)

        log.info("Bot starting (long-poll)...")
        try:
            app.run_polling()
        finally:
            if config.database_url:
                from app.db.postgres import close_pools
                close_pools()
            else:
                close_transport_db(config.data_dir)
                close_db(config.data_dir)


if __name__ == "__main__":
    main()
