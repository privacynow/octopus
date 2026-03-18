"""Registry channel egress implementation."""

from __future__ import annotations

import html
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.agents.bridge import bind_conversation
from app.agents.client import AgentRegistryClient
from app.agents.state import load_agent_runtime_state
from app.agents.types import TimelineEvent
from app.config import BotConfig
from app.formatting import trim_text
from app.ports.egress import (
    ChannelCapabilities,
    ChannelEgress,
    EditableHandle,
)

log = logging.getLogger(__name__)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class RegistryEditableHandle(EditableHandle):
    def __init__(self, conversation: "RegistryChannelEgress", *, event_id: str, kind: str, title: str) -> None:
        self._conversation = conversation
        self._event_id = event_id
        self._kind = kind
        self._title = title

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self._conversation.last_status_text = text
        self._conversation._append_output("edit", html.unescape(text))
        await self._conversation._publish_progress(text, event_id=self._event_id)

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs
        return None


class RegistryChannelEgress(ChannelEgress):
    def __init__(
        self,
        config: BotConfig,
        *,
        conversation_ref: str,
        routed_task_id: str = "",
        title: str = "",
        output_log: list[dict[str, str]] | None = None,
    ) -> None:
        self.config = config
        self.conversation_ref = conversation_ref
        self.routed_task_id = routed_task_id
        self.title = title or "Registry conversation"
        self.sent_messages: list[str] = []
        self.last_status_text = ""
        self._output_log = output_log
        self._timeline_client: AgentRegistryClient | None = None
        self._timeline_client_checked = False
        self._last_progress_published_at: float = 0.0
        self._PROGRESS_MIN_INTERVAL = 5.0
        self.chat = _RegistryChatShim(self)

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            can_edit_message=True,
            can_answer_action=True,
            can_send_photo=False,
            can_send_document=False,
            can_render_timeline=True,
            can_present_actions=True,
            can_share_conversation=True,
            channel_name="registry",
        )

    def _metadata(self) -> dict[str, Any]:
        return {"routed_task_id": self.routed_task_id} if self.routed_task_id else {}

    def _append_output(self, kind: str, text: str) -> None:
        if self._output_log is None:
            return
        self._output_log.append({"type": kind, "text": text})

    def _registry_client(self) -> AgentRegistryClient | None:
        if self._timeline_client_checked:
            return self._timeline_client
        self._timeline_client_checked = True
        state = load_agent_runtime_state(self.config.data_dir)
        if not state.agent_token or not self.config.agent_registry_url:
            return None
        self._timeline_client = AgentRegistryClient(
            self.config.agent_registry_url,
            agent_token=state.agent_token,
        )
        return self._timeline_client

    def _plain_text_snippet(self, text: str, *, limit: int = 200) -> str:
        clean = html.unescape(_HTML_TAG_RE.sub(" ", text or ""))
        lines = [" ".join(line.split()) for line in clean.splitlines()]
        lines = [line for line in lines if line]
        body = lines[-1] if lines else " ".join(clean.split())
        return trim_text(body, limit)

    async def _publish_event(
        self,
        *,
        kind: str,
        title: str,
        body: str = "",
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> None:
        client = self._registry_client()
        if client is None:
            return
        event = TimelineEvent(
            event_id=event_id or uuid.uuid4().hex,
            conversation_id=self.conversation_ref,
            kind=kind,
            title=title,
            body=body,
            status=status,
            progress=progress,
            metadata={**self._metadata(), **(metadata or {})},
        )
        try:
            await client.publish_timeline([event])
        except Exception:
            log.debug("Timeline publish failed for %s (non-fatal)", self.conversation_ref, exc_info=True)

    async def _publish_progress(self, html_text: str, *, event_id: str | None = None) -> None:
        snippet = self._plain_text_snippet(html_text)
        if not snippet:
            return
        now = time.monotonic()
        if now - self._last_progress_published_at < self._PROGRESS_MIN_INTERVAL:
            return
        self._last_progress_published_at = now
        await self._publish_event(
            kind="progress",
            title="Working…",
            body=snippet,
            event_id=event_id,
        )

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        del kwargs
        event_id = uuid.uuid4().hex
        self.sent_messages.append(text)
        self._append_output("send", text)
        await self._publish_event(
            kind="bot_message",
            title="Bot reply",
            body=text,
            event_id=event_id,
        )
        return RegistryEditableHandle(self, event_id=event_id, kind="bot_message", title="Bot reply")

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        caption = kwargs.get("caption", "[photo]")
        self._append_output("send", caption)
        await self._publish_event(
            kind="attachment",
            title="Photo",
            body=f"{caption}\n{photo if isinstance(photo, (str, Path)) else '[binary]'}",
        )

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        caption = kwargs.get("caption", "[document]")
        self._append_output("send", caption)
        await self._publish_event(
            kind="attachment",
            title="Document",
            body=f"{caption}\n{document if isinstance(document, (str, Path)) else '[binary]'}",
        )

    async def send_action(self, action: str) -> None:
        await self._publish_event(kind="surface_action", title="Bot action", body=action)

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        detail = text or ("alert" if show_alert else "ack")
        self._append_output("answer", detail)
        await self._publish_event(kind="action_answer", title="Action handled", body=detail)

    async def publish_timeline(self, event: Any) -> None:
        body = getattr(event, "body", "") or getattr(event, "text", "") or ""
        await self._publish_event(
            kind=getattr(event, "kind", "timeline"),
            title=getattr(event, "title", "Update"),
            body=body,
            status=getattr(event, "status", ""),
            progress=getattr(event, "progress", None),
            metadata=getattr(event, "metadata", None),
        )

    async def sync_binding(self, binding: Any) -> None:
        del binding
        return None

    async def bind(self, *, title: str, config: Any) -> None:
        del config
        self.title = title or self.title
        await bind_conversation(
            self.config,
            conversation_ref=self.conversation_ref,
            title=self.title,
            origin_surface="registry",
            external_id=self.conversation_ref,
        )
        await self._publish_event(kind="started", title="Conversation started")

    async def on_message_received(self, text: str) -> None:
        del text
        return None

    async def on_outcome(self, outcome: Any) -> None:
        if outcome is None:
            return None
        returncode = getattr(outcome, "returncode", 0)
        timed_out = bool(getattr(outcome, "timed_out", False))
        if hasattr(outcome, "returncode"):
            if returncode == 0 and not timed_out:
                await self._publish_event(
                    kind="completed",
                    title="Done",
                    body=trim_text(getattr(outcome, "text", "") or "", 400),
                )
                return None
            reason = "Timed out" if timed_out else f"Exited {returncode}"
            await self._publish_event(kind="failed", title="Failed", body=reason)
            return None

        status = str(getattr(outcome, "status", "") or "")
        if status == "delegation_proposed":
            return None
        if status.startswith("completed"):
            body = getattr(outcome, "reply_text", "") or self._plain_text_snippet(self.last_status_text, limit=400)
            await self._publish_event(kind="completed", title="Done", body=trim_text(body, 400))
            return None
        if status == "timed_out":
            await self._publish_event(kind="failed", title="Failed", body="Timed out")
            return None
        if status == "cancelled":
            await self._publish_event(kind="cancelled", title="Cancelled", body="Cancelled")
            return None
        if status:
            body = getattr(outcome, "error_text", "") or status
            await self._publish_event(kind="failed", title="Failed", body=trim_text(body, 400))

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        del run_again_label, skip_label
        await self._publish_event(
            kind="recovery_notice",
            title="Recovery available",
            body=f"{preview}\n\n{prompt}".strip(),
            metadata={"update_id": update_id},
        )

    async def reply_text(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)


class _RegistryChatShim:
    def __init__(self, conversation: RegistryChannelEgress) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_text(text, **kwargs)
