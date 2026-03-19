"""Operator-facing startup diagnostics for bot process launch paths."""

from __future__ import annotations

from typing import Final

import httpx
from telegram.error import Conflict, InvalidToken, NetworkError, TimedOut

_PLACEHOLDER_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "",
        "x",
        "fake",
        "fake-token",
        "123:fake",
        "changeme",
        "replace-me",
        "your-bot-token",
        "your-telegram-bot-token",
        "<telegram-bot-token>",
        "<botfather-token>",
        "0:test_token_not_real",
    }
)


def env_file_hint(instance: str) -> str:
    return ".env.bot" if instance in ("", "default") else f".env.bot.{instance}"


def telegram_token_is_placeholder(token: str) -> bool:
    normalized = token.strip().lower()
    return normalized in _PLACEHOLDER_TOKENS


def telegram_token_looks_plausible(token: str) -> bool:
    parts = token.strip().split(":", 1)
    return len(parts) == 2 and parts[0].isdigit() and len(parts[1]) >= 20


async def collect_telegram_doctor_diagnostics(token: str, *, instance: str) -> list[str]:
    """Return operator-facing FAIL lines for Telegram startup health."""
    env_hint = env_file_hint(instance)
    stripped = token.strip()
    if telegram_token_is_placeholder(stripped):
        return [
            f"FAIL: Telegram rejected TELEGRAM_BOT_TOKEN in {env_hint}. "
            "Set a real token from @BotFather before starting the bot."
        ]
    if not telegram_token_looks_plausible(stripped):
        return [
            f"FAIL: TELEGRAM_BOT_TOKEN in {env_hint} does not look like a real Telegram bot token. "
            "Use the full token from @BotFather and try again."
        ]

    url = f"https://api.telegram.org/bot{stripped}/getMe"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return [
            "FAIL: Telegram API check timed out. Check outbound network access, DNS, proxy, "
            "or firewall settings and try again."
        ]
    except httpx.HTTPError as exc:
        return [
            "FAIL: Telegram API check could not reach Telegram. "
            f"Network error: {exc.__class__.__name__}."
        ]

    description = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        description = str(payload.get("description", "") or "")

    if response.status_code == 401 or "unauthorized" in description.lower():
        return [
            f"FAIL: Telegram rejected TELEGRAM_BOT_TOKEN in {env_hint}. "
            "Update it with a valid token from @BotFather and restart."
        ]
    if response.status_code >= 400:
        detail = description or f"HTTP {response.status_code}"
        return [f"FAIL: Telegram API health check failed: {detail}"]
    if isinstance(payload, dict) and payload.get("ok") is False:
        detail = description or "unknown Telegram API error"
        return [f"FAIL: Telegram API health check failed: {detail}"]
    return []


def format_startup_exception(exc: BaseException, *, instance: str, mode: str) -> list[str]:
    """Return concise operator-facing startup error lines."""
    env_hint = env_file_hint(instance)
    if isinstance(exc, InvalidToken):
        return [
            "Startup failed: Telegram rejected TELEGRAM_BOT_TOKEN.",
            f"Update TELEGRAM_BOT_TOKEN in {env_hint} with a valid token from @BotFather, then start again.",
        ]
    if isinstance(exc, Conflict):
        return [
            f"Startup failed: another process is already using this bot token for {mode} delivery.",
            "Stop the other poller or switch this bot to webhook mode, then try again.",
        ]
    if isinstance(exc, (TimedOut, NetworkError)):
        return [
            "Startup failed: the bot could not reach Telegram during startup.",
            "Check outbound network access, DNS, proxy, or firewall settings, then try again.",
        ]
    return [
        f"Startup failed unexpectedly in {mode} mode.",
        "Run the full app health check for a clearer diagnosis, then inspect logs if the problem continues.",
    ]


def format_database_startup_exception(exc: BaseException) -> list[str]:
    """Return concise operator-facing database startup error lines."""
    exc_name = exc.__class__.__name__.lower()
    if exc_name in {"operationalerror", "interfaceerror"} or isinstance(
        exc, (ConnectionError, OSError, TimeoutError),
    ):
        return [
            "Database startup check failed: the bot could not connect to the configured database.",
            "Check BOT_DATABASE_URL, database credentials, network reachability, and whether Postgres is running.",
        ]
    return [
        "Database startup check failed before the bot could start.",
        "Check BOT_DATABASE_URL, database credentials, and whether the schema/bootstrap steps completed successfully.",
    ]
