"""Entry point: load config, build provider, run bot."""

import argparse
import logging
import sys

from app.config import BotConfig, fail_fast, load_config
from app.providers.base import Provider
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from app.storage import close_db, ensure_data_dirs
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Agent Bot")
    parser.add_argument("instance", nargs="?", default=None, help="Instance name (default: from BOT_INSTANCE env)")
    parser.add_argument("--doctor", action="store_true", help="Run health checks and exit")
    args = parser.parse_args()

    config = load_config(args.instance)
    provider = make_provider(config)

    if args.doctor:
        run_doctor(config, provider)

    fail_fast(config)
    ensure_data_dirs(config.data_dir)
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
            close_db(config.data_dir)
    else:
        log.info("Bot starting (long-poll)...")
        try:
            app.run_polling()
        finally:
            close_db(config.data_dir)


if __name__ == "__main__":
    main()
