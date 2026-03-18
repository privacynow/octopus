"""Telegram channel bootstrap ownership."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram.ext import Application

from app.channels.telegram import routing
from app.channels.telegram.state import TelegramRuntime, build_telegram_runtime
from app.config import BotConfig
from app.providers.base import Provider


@dataclass(frozen=True)
class TelegramBootstrap:
    """Bootstrap-owned Telegram channel bundle."""

    application: Application
    runtime: TelegramRuntime
    worker_dispatch: Callable[[str, Any, dict], Awaitable[None]]


def build_bootstrap(config: BotConfig, provider: Provider) -> TelegramBootstrap:
    """Construct the Telegram runtime, PTB application, and worker dispatch."""

    runtime = build_telegram_runtime(config, provider)
    application = routing.build_application(runtime)
    return TelegramBootstrap(
        application=application,
        runtime=runtime,
        worker_dispatch=functools.partial(routing.worker_dispatch, runtime=runtime),
    )
