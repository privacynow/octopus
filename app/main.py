"""Profile-driven bot entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import fail_fast, load_config, load_config_provider_health
from app.runtime.process import (
    prepare_and_run_runtime,
    run_doctor,
    run_provider_health,
    should_validate_provider_auth,
    validate_required_runtime_profile,
)
from app.startup_diagnostics import (
    configure_startup_logging,
    format_database_startup_exception,
)
from octopus_sdk.providers import Provider
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider

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


def make_provider(config) -> Provider:
    provider_cls = PROVIDERS.get(config.provider_name)
    if provider_cls is None:
        print(f"Unknown provider: {config.provider_name}", file=sys.stderr)
        raise SystemExit(1)
    return provider_cls(config)


def _parse_args() -> argparse.Namespace:
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
    return args


def _run_database_startup_checks(config) -> None:
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


def _validate_provider_auth(config, provider: Provider) -> None:
    if not should_validate_provider_auth(config):
        return
    auth_errors = asyncio.run(provider.check_auth_health())
    if not auth_errors:
        return
    print("Provider not authenticated or unavailable.", file=sys.stderr)
    for error in auth_errors:
        print(f"  {error}", file=sys.stderr)
    print(
        "Run ./octopus and choose Diagnose -> Provider auth to authenticate, or check your subscription.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main() -> None:
    args = _parse_args()

    if args.provider_health:
        provider_health_config = load_config_provider_health()
        asyncio.run(run_provider_health(make_provider(provider_health_config)))
        return

    config = load_config(args.instance)
    provider = make_provider(config)
    fail_fast(config)

    from app import runtime_backend

    runtime_backend.init(config)
    _run_database_startup_checks(config)

    if args.doctor:
        asyncio.run(
            run_doctor(
                config,
                provider,
                include_provider_runtime_probe=args.doctor_live_provider,
            )
        )
        return

    _validate_provider_auth(config, provider)
    validate_required_runtime_profile(config)
    prepare_and_run_runtime(config, provider)


if __name__ == "__main__":
    main()
