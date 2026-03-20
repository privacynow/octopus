"""Telegram progress lifecycle and timeline plumbing."""

from __future__ import annotations

import asyncio
import logging
import time

from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, NetworkError, TimedOut

from app.formatting import trim_text
from app import user_messages as _msg
from app.config import BotConfig
from app.channels.telegram.state import TelegramRuntime


log = logging.getLogger(__name__)


class TelegramProgress:
    def __init__(self, message, config: BotConfig, *, timeline_callback=None) -> None:
        self.message = message
        self.last_text = ""
        self.last_update = 0.0
        self._interval = config.stream_update_interval_seconds
        self._content_delivered = False
        self._timeline_callback = timeline_callback

    async def update(self, html_text: str, *, force: bool = False) -> None:
        html_text = trim_text(html_text, 3500)
        if not html_text or html_text == self.last_text:
            return
        now = time.monotonic()
        cs = getattr(self, "content_started", None)
        if not force and not self._content_delivered and cs and cs.is_set():
            force = True
        if not force and now - self.last_update < self._interval:
            return
        try:
            await self.message.edit_text(html_text, parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.debug("progress update failed: %s", exc)
                return
        except (TimedOut, NetworkError) as exc:
            log.debug("progress update skipped (network): %s", exc)
            return
        self.last_text = html_text
        self.last_update = now
        if cs and cs.is_set():
            self._content_delivered = True
        if self._timeline_callback is not None:
            try:
                await self._timeline_callback(html_text, force=force)
            except Exception:
                log.warning("Control-plane timeline callback failed", exc_info=True)


async def progress_timeline_callback(
    runtime: TelegramRuntime,
    conversation_ref: str,
    routed_task_id: str,
    html_text: str,
    *,
    force: bool = False,
) -> None:
    del force
    await runtime.services.control_plane.conversation_projection.publish_external_timeline(
        conversation_ref=conversation_ref,
        kind="progress",
        title="Progress",
        body=html_text,
        metadata={"routed_task_id": routed_task_id} if routed_task_id else {},
    )


async def keep_typing(chat, *, runtime: TelegramRuntime) -> None:
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(runtime.config.typing_interval_seconds)
    except asyncio.CancelledError:
        pass


_HEARTBEAT_FIRST = 5.0
_HEARTBEAT_SUBSEQUENT = 10.0


async def heartbeat(progress, content_started: asyncio.Event) -> None:
    """Show elapsed time on the progress message while idle."""

    try:
        start = time.monotonic()
        await asyncio.sleep(_HEARTBEAT_FIRST)
        while not content_started.is_set():
            last = getattr(progress, "last_update", 0.0)
            since_last = time.monotonic() - last if last else _HEARTBEAT_FIRST
            if since_last < _HEARTBEAT_SUBSEQUENT:
                await asyncio.sleep(_HEARTBEAT_SUBSEQUENT - since_last)
                continue
            elapsed = int(time.monotonic() - start)
            await progress.update(_msg.progress_still_working(elapsed), force=True)
            await asyncio.sleep(_HEARTBEAT_SUBSEQUENT)
    except asyncio.CancelledError:
        pass
