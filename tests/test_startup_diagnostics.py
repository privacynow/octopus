import logging
import sys

import pytest
from telegram.error import Conflict, InvalidToken, NetworkError

from app.startup_diagnostics import (
    collect_telegram_doctor_diagnostics,
    configure_startup_logging,
    env_file_hint,
    format_database_startup_exception,
    format_startup_exception,
    redact_sensitive_startup_text,
    sanitize_url_for_logging,
    StartupLogRedactionFilter,
)


def test_env_file_hint_uses_instance_name():
    assert env_file_hint("default") == ".env.bot"
    assert env_file_hint("blue") == ".env.bot.blue"


def test_format_startup_exception_for_invalid_token():
    lines = format_startup_exception(
        InvalidToken("bad token"),
        instance="default",
        mode="polling",
    )
    assert any("Telegram rejected TELEGRAM_BOT_TOKEN" in line for line in lines)
    assert any("@BotFather" in line for line in lines)


def test_format_startup_exception_for_conflict():
    lines = format_startup_exception(
        Conflict("conflict"),
        instance="default",
        mode="polling",
    )
    assert any("another process is already using this bot token" in line for line in lines)


def test_format_startup_exception_for_network_error():
    lines = format_startup_exception(
        NetworkError("timeout"),
        instance="default",
        mode="polling",
    )
    assert any("could not reach Telegram" in line for line in lines)


def test_format_database_startup_exception_hides_connection_string():
    class OperationalError(RuntimeError):
        pass

    lines = format_database_startup_exception(
        OperationalError("postgresql://bot:secret@example.com/bot refused connection"),
    )
    joined = "\n".join(lines)
    assert "could not connect to the configured database" in joined
    assert "secret@example.com" not in joined


def test_redact_sensitive_startup_text_masks_telegram_token_and_url():
    token = "8493136018:AAET-xjK_v8TviI7et1N8pCvI3O0bbmVLFl"
    text = (
        f"HTTP Request: POST https://api.telegram.org/bot{token}/getMe "
        f"and token {token} was rejected"
    )
    redacted = redact_sensitive_startup_text(text)
    assert token not in redacted
    assert "<redacted-telegram-token>" in redacted


def test_redact_sensitive_startup_text_masks_postgres_password_and_bearer_token():
    text = (
        "Database error for postgresql://bot:super-secret@example.com/bot "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
    )
    redacted = redact_sensitive_startup_text(text)
    assert "super-secret" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "bot:<redacted>@" in redacted
    assert "Bearer <redacted-bearer-token>" in redacted


def test_redact_sensitive_startup_text_masks_configured_secret_values(monkeypatch):
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-super-secret")
    redacted = redact_sensitive_startup_text("using ui-super-secret for UI auth")
    assert "ui-super-secret" not in redacted
    assert "<redacted-registry-ui-token>" in redacted


def test_redact_sensitive_startup_text_masks_database_password_fragment(monkeypatch):
    monkeypatch.setenv("BOT_DATABASE_URL", "postgresql://bot:supersecret@db.example.com/bot")

    redacted = redact_sensitive_startup_text("driver surfaced password supersecret without DSN context")

    assert "supersecret" not in redacted
    assert "<redacted-bot-database-url>-password" in redacted


def test_redact_sensitive_startup_text_masks_bot_side_secret_values(monkeypatch):
    monkeypatch.setenv("BOT_AGENT_REGISTRY_ENROLL_TOKEN", "agent-enroll-secret")
    monkeypatch.setenv("BOT_WEBHOOK_SECRET", "webhook-secret-value")
    redacted = redact_sensitive_startup_text(
        "registry agent-enroll-secret webhook webhook-secret-value"
    )
    assert "agent-enroll-secret" not in redacted
    assert "webhook-secret-value" not in redacted
    assert "<redacted-bot-agent-registry-enroll-token>" in redacted
    assert "<redacted-bot-webhook-secret>" in redacted


def test_sanitize_url_for_logging_strips_query_and_password():
    redacted = sanitize_url_for_logging(
        "https://alice:pw@example.com/hooks/completed?token=secret&mode=test#frag"
    )
    assert "pw" not in redacted
    assert "token=secret" not in redacted
    assert "<redacted>" in redacted
    assert redacted.startswith("https://alice:<redacted>@example.com/hooks/completed")


def test_startup_log_redaction_filter_sanitizes_invalid_token_exception():
    token = "8493136018:AAET-xjK_v8TviI7et1N8pCvI3O0bbmVLFl"
    record = logging.LogRecord(
        name="telegram.ext._utils.networkloop",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Network Retry Loop (Bootstrap Initialize Application): Invalid token. Aborting retry loop.",
        args=(),
        exc_info=None,
    )
    record.exc_info = (
        InvalidToken,
        InvalidToken(f"The token `{token}` was rejected by the server."),
        None,
    )
    assert StartupLogRedactionFilter().filter(record) is True
    assert record.exc_info is None
    assert token not in str(record.msg)
    assert "TELEGRAM_BOT_TOKEN" in str(record.msg)


def test_startup_log_redaction_filter_drops_noisy_http_request_lines():
    token = "8493136018:AAET-xjK_v8TviI7et1N8pCvI3O0bbmVLFl"
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"HTTP Request: GET https://api.telegram.org/bot{token}/getMe \"HTTP/1.1 401 Unauthorized\"",
        args=(),
        exc_info=None,
    )
    assert StartupLogRedactionFilter().filter(record) is False


def test_startup_log_redaction_filter_sanitizes_traceback_text(monkeypatch):
    monkeypatch.setenv("BOT_DATABASE_URL", "postgresql://bot:secret@example.com/bot")
    record = logging.LogRecord(
        name="app.runtime_health",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Database startup failed",
        args=(),
        exc_info=None,
    )
    exc = RuntimeError("postgresql://bot:secret@example.com/bot refused connection")
    try:
        raise exc
    except RuntimeError:
        record.exc_info = sys.exc_info()
    assert StartupLogRedactionFilter().filter(record) is True
    assert record.exc_info is None
    assert record.exc_text is not None
    assert "secret@example.com" not in record.exc_text
    assert "<redacted-bot-database-url>" in record.exc_text or "bot:<redacted>@" in record.exc_text


def test_configure_startup_logging_raises_httpx_log_level():
    logger = logging.getLogger("httpx")
    original_level = logger.level
    try:
        logger.setLevel(logging.INFO)
        configure_startup_logging()
        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(original_level)


@pytest.mark.asyncio
async def test_collect_telegram_doctor_diagnostics_flags_placeholder_token():
    lines = await collect_telegram_doctor_diagnostics("123:fake", instance="default")
    assert any("Telegram rejected TELEGRAM_BOT_TOKEN" in line for line in lines)
    assert any("@BotFather" in line for line in lines)


@pytest.mark.asyncio
async def test_collect_telegram_doctor_diagnostics_reports_unauthorized(monkeypatch):
    class FakeResponse:
        status_code = 401

        def json(self):
            return {"ok": False, "description": "Unauthorized"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("app.startup_diagnostics.httpx.AsyncClient", lambda timeout=5.0: FakeClient())

    lines = await collect_telegram_doctor_diagnostics(
        "123456:ABC-DEFghijklmnopqrstuvwxyz",
        instance="default",
    )

    assert any("Telegram rejected TELEGRAM_BOT_TOKEN" in line for line in lines)


@pytest.mark.asyncio
async def test_collect_telegram_doctor_diagnostics_accepts_success(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "result": {"id": 123}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("app.startup_diagnostics.httpx.AsyncClient", lambda timeout=5.0: FakeClient())

    lines = await collect_telegram_doctor_diagnostics(
        "123456:ABC-DEFghijklmnopqrstuvwxyz",
        instance="green",
    )

    assert lines == []
