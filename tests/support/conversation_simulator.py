"""Project-owned conversation simulator. Injects events, runs real worker, exposes ordered output log."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from typing import Any

import app.channels.telegram.ingress as _th
from app import work_queue
from app.agents.bridge import build_registry_message_delivery
from tests.support.handler_support import (
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeUpdate,
    FakeUser,
    MinimalFakeBot,
    bot_texts,
    drain_one_worker_item,
    running_worker,
    set_bot_instance,
    setup_globals,
)


class ConversationSimulator:
    """Simulates a conversation over the real worker path. One ordered output log."""

    def __init__(self, data_dir: Path, config: Any, provider: Any) -> None:
        self.data_dir = data_dir
        self.config = config
        self.provider = provider
        self._bot = MinimalFakeBot()
        self._output_log = []  # One ordered user-visible stream (handler replies + bot sends/edits)
        self._bot._output_log = self._output_log
        setup_globals(config, provider)
        set_bot_instance(self._bot)

    def inject_message(self, chat_id: int, user_id: int, text: str) -> None:
        """Admit a plain message (handler path). Call from sync or async; for async use inject_message_async."""
        chat = FakeChat(chat_id)
        user = FakeUser(user_id)
        msg = FakeMessage(chat=chat, text=text)
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        async def _do():
            await _th.handle_message(upd, FakeContext())

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            raise RuntimeError("Use inject_message_async from an async test")
        asyncio.run(_do())

    async def inject_message_async(self, chat_id: int, user_id: int, text: str) -> FakeUpdate:
        """Admit a plain message (handler path). Returns the FakeUpdate so tests can use update_id and effective_message."""
        chat = FakeChat(chat_id)
        user = FakeUser(user_id)
        msg = FakeMessage(chat=chat, text=text)
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await _th.handle_message(upd, FakeContext())
        return upd

    async def inject_registry_message_async(
        self,
        conversation_ref: str,
        text: str,
        actor_ref: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, Any]:
        """Admit a registry-surface message through the same durable worker boundary."""
        chat_id, user_id, update_id, payload = build_registry_message_delivery(
            conversation_ref=conversation_ref,
            text=text,
            actor_ref=actor_ref,
            delivery_id=f"sim-registry:{uuid.uuid4().hex}",
            skip_approval=skip_approval,
        )
        status, item_id = work_queue.record_and_admit_message(
            self.data_dir,
            update_id,
            chat_id,
            user_id,
            "message",
            payload,
        )
        return {
            "chat_id": chat_id,
            "user_id": user_id,
            "update_id": update_id,
            "status": status,
            "item_id": item_id,
        }

    async def inject_command_async(self, chat_id: int, user_id: int, command: str, args: list[str] | None = None) -> FakeUpdate:
        """Send a command (e.g. /cancel). Returns the FakeUpdate so tests can use update_id and effective_message for reply assertions."""
        chat = FakeChat(chat_id)
        user = FakeUser(user_id)
        cmd_name = command.lstrip("/").split()[0] if command else ""
        handler = getattr(_th, "cmd_cancel", None) if cmd_name == "cancel" else getattr(_th, "cmd_" + cmd_name, None)
        if handler is None:
            raise ValueError(f"No handler for {command}")
        msg = FakeMessage(chat=chat, text=command)
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await handler(upd, FakeContext(args=args or []))
        return upd

    def get_output_log(self) -> list[str]:
        """Ordered user-visible text output. Includes: reply_text/edit_text on handler messages; chat.send_message, reply_photo/reply_document (caption or [photo]/[document]); bot send_message/send_photo/send_document and edit_text; callback answer (text or [answer]); callback edit_message_text. Markup-only edits (edit_message_reply_markup) are not included. One entry per output."""
        if self._output_log:
            return [entry.get("text", "") for entry in self._output_log]
        return bot_texts(self._bot)

    def get_output_log_merged(self) -> str:
        """Single string of all output for substring checks."""
        return " ".join(self.get_output_log())

    async def wait_for_provider_started(self, timeout: float = 2.0) -> None:
        """Wait until the provider run has started (provider_started event set)."""
        if not getattr(self.provider, "provider_started", None):
            return
        await asyncio.wait_for(self.provider.provider_started.wait(), timeout=timeout)

    async def wait_for_text(self, substring: str, timeout: float = 2.0) -> None:
        """Wait until the output log contains substring."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if substring in self.get_output_log_merged():
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"Output log did not contain {substring!r} within {timeout}s. Got: {self.get_output_log_merged()!r}")

    @contextlib.asynccontextmanager
    async def running_worker(self, poll_interval: float = 0.01):
        """Start the real worker loop; stop on exit."""
        async with running_worker(self.data_dir, poll_interval=poll_interval) as (task, stop_event):
            yield task, stop_event

    async def drain_one(self) -> bool:
        """Claim and dispatch one work item. Returns True if one was drained."""
        return await drain_one_worker_item(self.data_dir)
