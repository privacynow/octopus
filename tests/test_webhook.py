"""Tests for outbound completion webhook delivery and circuit breaking."""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_breaker(monkeypatch):
    import app.webhook as wh

    wh._breaker = wh._CircuitBreaker()

    async def _fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(wh, "_async_sleep", _fast_sleep)
    yield


def _response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://hooks.example.com/completed")
    return httpx.Response(status_code, request=request)


def _install_async_client(monkeypatch, results, calls):
    class FakeAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            calls.append({"url": url, "json": json, "timeout": self.timeout})
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr("app.webhook.httpx.AsyncClient", FakeAsyncClient)


@pytest.mark.asyncio
async def test_fire_skips_when_url_empty(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [], calls)

    await wh.fire_completion_webhook(
        "",
        chat_id=123,
        conversation_ref="conv-1",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert calls == []


@pytest.mark.asyncio
async def test_fire_blocks_private_ip_targets(monkeypatch, caplog):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(200)], calls)

    with caplog.at_level("WARNING"):
        await wh.fire_completion_webhook(
            "https://10.0.0.15/completed",
            chat_id=123,
            conversation_ref="conv-1",
            status="completed",
            summary="done",
            completed_at="2026-03-16T00:00:00Z",
        )

    assert calls == []
    assert any("Completion webhook blocked" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_fire_blocks_metadata_targets(monkeypatch, caplog):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(200)], calls)

    with caplog.at_level("WARNING"):
        await wh.fire_completion_webhook(
            "https://169.254.169.254/latest/meta-data",
            chat_id=123,
            conversation_ref="conv-1",
            status="completed",
            summary="done",
            completed_at="2026-03-16T00:00:00Z",
        )

    assert calls == []
    assert any("Completion webhook blocked" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_fire_allows_loopback_dev_target(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(200)], calls)

    await wh.fire_completion_webhook(
        "http://127.0.0.1:9999/completed",
        chat_id=123,
        conversation_ref="conv-1",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fire_delivers_on_success(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(200)], calls)

    await wh.fire_completion_webhook(
        "https://hooks.example.com/completed",
        chat_id=123,
        conversation_ref="conv-1",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == 1
    assert calls[0]["url"] == "https://hooks.example.com/completed"
    assert calls[0]["json"] == {
        "event": "conversation_completed",
        "conversation_ref": "conv-1",
        "chat_id": 123,
        "status": "completed",
        "summary": "done",
        "completed_at": "2026-03-16T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_fire_retries_on_5xx(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(503), _response(503), _response(200)], calls)

    await wh.fire_completion_webhook(
        "https://hooks.example.com/completed",
        chat_id=123,
        conversation_ref="conv-1",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == 3


@pytest.mark.asyncio
async def test_fire_no_retry_on_4xx(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    _install_async_client(monkeypatch, [_response(400)], calls)

    await wh.fire_completion_webhook(
        "https://hooks.example.com/completed",
        chat_id=123,
        conversation_ref="conv-1",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    now = [100.0]
    monkeypatch.setattr(wh.time, "monotonic", lambda: now[0])
    _install_async_client(
        monkeypatch,
        [_response(500)] * (wh._FAILURE_THRESHOLD * wh._MAX_ATTEMPTS),
        calls,
    )

    for index in range(wh._FAILURE_THRESHOLD):
        await wh.fire_completion_webhook(
            "https://hooks.example.com/completed",
            chat_id=123,
            conversation_ref=f"conv-{index}",
            status="completed",
            summary="done",
            completed_at="2026-03-16T00:00:00Z",
        )

    assert len(calls) == wh._FAILURE_THRESHOLD * wh._MAX_ATTEMPTS

    await wh.fire_completion_webhook(
        "https://hooks.example.com/completed",
        chat_id=123,
        conversation_ref="conv-skipped",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == wh._FAILURE_THRESHOLD * wh._MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_circuit_recovers_after_timeout(monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    now = [100.0]
    monkeypatch.setattr(wh.time, "monotonic", lambda: now[0])
    _install_async_client(
        monkeypatch,
        [_response(500)] * (wh._FAILURE_THRESHOLD * wh._MAX_ATTEMPTS) + [_response(200)],
        calls,
    )

    for index in range(wh._FAILURE_THRESHOLD):
        await wh.fire_completion_webhook(
            "https://hooks.example.com/completed",
            chat_id=123,
            conversation_ref=f"conv-{index}",
            status="completed",
            summary="done",
            completed_at="2026-03-16T00:00:00Z",
        )

    now[0] += wh._RECOVERY_SECONDS + 1

    await wh.fire_completion_webhook(
        "https://hooks.example.com/completed",
        chat_id=123,
        conversation_ref="conv-recovery",
        status="completed",
        summary="done",
        completed_at="2026-03-16T00:00:00Z",
    )

    assert len(calls) == wh._FAILURE_THRESHOLD * wh._MAX_ATTEMPTS + 1


@pytest.mark.asyncio
async def test_webhook_logging_redacts_query_tokens(caplog, monkeypatch):
    import app.webhook as wh

    calls: list[dict] = []
    request = httpx.Request("POST", "https://hooks.example.com/completed?token=secret")
    _install_async_client(
        monkeypatch,
        [httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500, request=request))],
        calls,
    )

    with caplog.at_level("WARNING"):
        await wh.fire_completion_webhook(
            "https://hooks.example.com/completed?token=secret",
            chat_id=123,
            conversation_ref="conv-1",
            status="completed",
            summary="done",
            completed_at="2026-03-16T00:00:00Z",
        )

    assert any("Completion webhook failed" in record.message for record in caplog.records)
    assert not any("token=secret" in record.message for record in caplog.records)
