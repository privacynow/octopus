"""Operator-facing startup diagnostics for bot process launch paths."""

from __future__ import annotations

import logging
import os
import re
import traceback
from typing import Final
from urllib.parse import ParseResult, urlparse, urlunparse

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
_TELEGRAM_URL_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"(https://api\.telegram\.org/bot)(\d+:[A-Za-z0-9_-]{20,})",
)
_TELEGRAM_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d+:[A-Za-z0-9_-]{20,}\b",
)
_POSTGRES_URL_PASSWORD_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<scheme>postgresql(?:\+\w+)?://)"
    r"(?P<username>[^:/@\s]+)"
    r":(?P<password>[^@/\s]+)"
    r"@",
)
_BEARER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\bBearer\s+[A-Za-z0-9._-]{16,}\b",
    re.IGNORECASE,
)
_SANITIZED_TOKEN: Final[str] = "<redacted-telegram-token>"
_SANITIZED_BEARER: Final[str] = "Bearer <redacted-bearer-token>"
_SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "TELEGRAM_BOT_TOKEN",
    "BOT_DATABASE_URL",
    "BOT_WEBHOOK_SECRET",
    "BOT_AGENT_REGISTRY_ENROLL_TOKEN",
    "REGISTRY_UI_TOKEN",
    "REGISTRY_ENROLL_TOKEN",
    "REGISTRY_SESSION_SECRET",
    "BOT_CREDENTIAL_KEY",
)


def _redacted_env_placeholder(env_name: str) -> str:
    label = env_name.lower().replace("_", "-")
    return f"<redacted-{label}>"


def _derived_secret_values(env_name: str, value: str) -> tuple[tuple[str, str], ...]:
    derived: list[tuple[str, str]] = []
    if env_name == "BOT_DATABASE_URL":
        parsed = urlparse(value)
        if parsed.password:
            derived.append(
                (
                    parsed.password,
                    f"{_redacted_env_placeholder(env_name)}-password",
                )
            )
    return tuple(derived)


def _configured_secret_values() -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for env_name in _SECRET_ENV_NAMES:
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        values.append((value, _redacted_env_placeholder(env_name)))
        values.extend(_derived_secret_values(env_name, value))
    values.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(values)


def sanitize_url_for_logging(raw: str) -> str:
    """Strip query/fragment data and redact embedded credentials for log output."""
    parsed = urlparse(raw)
    if not parsed.scheme:
        base = raw.split("#", 1)[0].split("?", 1)[0]
        suffix = "?<redacted>" if "?" in raw else ""
        return redact_sensitive_startup_text(f"{base}{suffix}")

    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"

    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:<redacted>@"
        else:
            userinfo = f"{userinfo}@"
        netloc = f"{userinfo}{hostname}"
    else:
        netloc = hostname

    sanitized = ParseResult(
        scheme=parsed.scheme,
        netloc=netloc,
        path=parsed.path,
        params=parsed.params,
        query="<redacted>" if parsed.query else "",
        fragment="",
    )
    return redact_sensitive_startup_text(urlunparse(sanitized))


def redact_sensitive_startup_text(text: str) -> str:
    """Redact secret-bearing values operator-visible strings."""
    redacted = _TELEGRAM_URL_TOKEN_RE.sub(rf"\1{_SANITIZED_TOKEN}", text)
    redacted = _TELEGRAM_TOKEN_RE.sub(_SANITIZED_TOKEN, redacted)
    redacted = _POSTGRES_URL_PASSWORD_RE.sub(
        lambda match: (
            f"{match.group('scheme')}"
            f"{match.group('username')}:<redacted>@"
        ),
        redacted,
    )
    redacted = _BEARER_TOKEN_RE.sub(_SANITIZED_BEARER, redacted)
    for value, replacement in _configured_secret_values():
        redacted = redacted.replace(value, replacement)
    return redacted


def _sanitize_log_args(args):
    if isinstance(args, tuple):
        return tuple(
            redact_sensitive_startup_text(arg) if isinstance(arg, str) else arg
            for arg in args
        )
    if isinstance(args, dict):
        return {
            key: redact_sensitive_startup_text(value) if isinstance(value, str) else value
            for key, value in args.items()
        }
    if isinstance(args, str):
        return redact_sensitive_startup_text(args)
    return args


class StartupLogRedactionFilter(logging.Filter):
    """Remove token-bearing details startup/runtime logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_startup_text(record.msg)
        record.args = _sanitize_log_args(record.args)
        if isinstance(record.msg, str) and record.msg.startswith("HTTP Request:"):
            return False
        if record.exc_info:
            _exc_type, exc, _tb = record.exc_info
            if isinstance(exc, InvalidToken):
                record.msg = "Telegram startup failed: Telegram rejected TELEGRAM_BOT_TOKEN."
                record.args = ()
                record.exc_info = None
            else:
                record.exc_text = redact_sensitive_startup_text(
                    "".join(traceback.format_exception(*record.exc_info))
                ).rstrip()
                record.exc_info = None
        return True


def configure_startup_logging() -> None:
    """Sanitize startup logging before third-party libraries emit secrets."""
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, StartupLogRedactionFilter) for f in handler.filters):
            handler.addFilter(StartupLogRedactionFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def env_file_hint(instance: str) -> str:
    if instance in ("", "default"):
        return ".deploy/bots/<slug>/.env"
    return f".deploy/bots/{instance}/.env"


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
            "Set a real token @BotFather before starting the bot."
        ]
    if not telegram_token_looks_plausible(stripped):
        return [
            f"FAIL: TELEGRAM_BOT_TOKEN in {env_hint} does not look like a real Telegram bot token. "
            "Use the full token @BotFather and try again."
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
            "Update it with a valid token @BotFather and restart."
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
            f"Update TELEGRAM_BOT_TOKEN in {env_hint} with a valid token @BotFather, then start again.",
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
