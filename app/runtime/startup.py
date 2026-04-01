"""Startup validation, diagnostics, and runtime process guards."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from telegram.error import Conflict, InvalidToken, NetworkError, TimedOut

import app.runtime_backend as runtime_backend
from app.config import BotConfig, ProcessRole
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from app.startup_diagnostics import (
    collect_telegram_doctor_diagnostics,
    format_database_startup_exception,
    format_startup_exception,
    sanitize_url_for_logging,
)
from app.storage import close_db, ensure_data_dirs
from app.work_queue import close_transport_db, purge_old
from octopus_sdk.providers import Provider

if TYPE_CHECKING:
    from app.runtime.services import RuntimeBuild

log = logging.getLogger(__name__)


def runs_ingress(config: BotConfig) -> bool:
    return bool(config.telegram_token) and config.process_role in {
        ProcessRole.ALL.value,
        ProcessRole.WEBHOOK.value,
    }


def initialize_runtime_health_startup(config: BotConfig) -> None:
    """Initialize only the runtime dependencies needed by doctor/health checks."""
    runtime_backend.init(config)
    ensure_data_dirs(config.data_dir, database_url=config.database_url or "")
    init_content_store_for_config(config)
    init_credential_store_for_config(config)


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

    initialize_runtime_health_startup(config)
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


def run_database_startup_checks(config: BotConfig) -> None:
    if not config.database_url:
        return
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
    except Exception as exc:
        log.error("Database startup check failed: %s", exc.__class__.__name__)
        for line in format_database_startup_exception(exc):
            print(line, file=sys.stderr)
        raise SystemExit(1) from exc
    if errors:
        for error in errors:
            print(f"  FAIL: {error}", file=sys.stderr)
        print(
            "Run: docker compose --project-directory . -f infra/compose/docker-compose.yml "
            "--profile tools run --rm db-bootstrap (or db-update). See README.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def validate_provider_auth(config: BotConfig, provider: Provider) -> None:
    if not should_validate_provider_auth(config):
        return
    auth_errors = asyncio.run(provider.check_auth_health())
    if not auth_errors:
        return
    print("Provider startup validation failed.", file=sys.stderr)
    for error in auth_errors:
        print(f"  {error}", file=sys.stderr)
    print(
        "Run ./octopus and choose Diagnose -> Provider auth to authenticate, or check your subscription.",
        file=sys.stderr,
    )
    raise SystemExit(1)


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


def initialize_runtime_startup(config: BotConfig, provider: Provider) -> None:
    initialize_runtime_health_startup(config)
    run_database_startup_checks(config)
    validate_provider_auth(config, provider)
    validate_required_runtime_profile(config)
    log_runtime_profile(config, provider)


def close_runtime_resources(config: BotConfig) -> None:
    if config.database_url:
        from app.db.postgres import close_pools

        close_pools()
    else:
        close_transport_db(config.data_dir)
        close_db(config.data_dir)

    purge_old(config.data_dir)


def exit_startup_failure(exc: BaseException, config: BotConfig, *, mode: str) -> None:
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


def run_runtime_process(config: BotConfig, runtime_build: "RuntimeBuild") -> None:
    from app.config import BotMode
    from app.runtime_health import check_polling_conflict

    if not config.telegram_token:
        log.info("Bot starting (registry-only)...")
        failure_mode = "registry-only"
    elif config.process_role == ProcessRole.WORKER.value:
        log.info("Bot starting (worker-only)...")
        failure_mode = "worker"
    elif config.bot_mode == BotMode.WEBHOOK.value:
        log.info("Bot starting (webhook)...")
        log.info("Webhook URL: %s", sanitize_url_for_logging(config.webhook_url))
        log.info("Listening on %s:%d", config.webhook_listen, config.webhook_port)
        failure_mode = "webhook"
    else:
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
        failure_mode = "polling"

    try:
        asyncio.run(runtime_build.bot_runtime.run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        exit_startup_failure(exc, config, mode=failure_mode)
    finally:
        close_runtime_resources(config)
