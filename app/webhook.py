"""Outbound completion webhook: fire-and-forget POST with retry, backoff, and circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential, wait_random

from app.startup_diagnostics import sanitize_url_for_logging

log = logging.getLogger(__name__)

_TIMEOUT = 10.0
_MAX_ATTEMPTS = 3
_FAILURE_THRESHOLD = 5
_RECOVERY_SECONDS = 60.0
_async_sleep = asyncio.sleep


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.HTTPError)


@dataclass
class _CircuitBreaker:
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _half_open_in_flight: bool = field(default=False, init=False)

    def allow_request(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at < _RECOVERY_SECONDS:
            return False
        if self._half_open_in_flight:
            return False
        self._half_open_in_flight = True
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open_in_flight = False

    def record_failure(self) -> None:
        if self._half_open_in_flight:
            self._opened_at = time.monotonic()
            self._half_open_in_flight = False
            self._failures = _FAILURE_THRESHOLD
            log.warning("Completion webhook circuit re-opened after failed recovery attempt")
            return
        self._failures += 1
        if self._failures >= _FAILURE_THRESHOLD:
            if self._opened_at is None:
                log.warning(
                    "Completion webhook circuit opened after %d consecutive failures",
                    self._failures,
                )
            self._opened_at = time.monotonic()


_breaker = _CircuitBreaker()


def _webhook_failure_label(url: str, exc: BaseException) -> str:
    sanitized_url = sanitize_url_for_logging(url)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} via {sanitized_url}"
    return f"{exc.__class__.__name__} via {sanitized_url}"


async def _attempt_post(url: str, payload: dict) -> None:
    """Single POST attempt. Raises on non-2xx or transport error."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def fire_completion_webhook(
    url: str,
    *,
    chat_id: int,
    conversation_ref: str,
    status: str,
    summary: str,
    completed_at: str,
) -> None:
    """POST completion payload with retry/backoff and a per-process circuit breaker."""
    if not url:
        return
    if not _breaker.allow_request():
        log.debug("Completion webhook circuit open, skipping for %s", conversation_ref)
        return

    payload = {
        "event": "conversation_completed",
        "conversation_ref": conversation_ref,
        "chat_id": chat_id,
        "status": status,
        "summary": summary,
        "completed_at": completed_at,
    }

    attempts = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=1, min=2, max=30) + wait_random(0, 1),
            retry=retry_if_exception(_is_retryable),
            sleep=_async_sleep,
            reraise=True,
        ):
            with attempt:
                attempts = attempt.retry_state.attempt_number
                await _attempt_post(url, payload)
        _breaker.record_success()
        log.debug("Completion webhook delivered for %s", conversation_ref)
    except Exception as exc:
        _breaker.record_failure()
        log.warning(
            "Completion webhook failed after %d attempt(s) for %s: %s",
            attempts or 1,
            conversation_ref,
            _webhook_failure_label(url, exc),
        )
