"""Telegram channel bootstrap helpers."""

from __future__ import annotations

from app.channels.telegram.routing import build_application, worker_dispatch

__all__ = ["build_application", "worker_dispatch"]
