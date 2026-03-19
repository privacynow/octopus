import logging

import pytest
from telegram.error import Conflict, InvalidToken, NetworkError

from app.startup_diagnostics import (
    collect_telegram_doctor_diagnostics,
    configure_startup_logging,
    env_file_hint,
    format_database_startup_exception,
    format_startup_exception,
    redact_sensitive_startup_text,
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
