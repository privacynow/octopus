"""Registry-backed conversation surface for registry UI and routed work."""

from __future__ import annotations

import html
import uuid
from pathlib import Path
from typing import Any

from app.agents.bridge import bind_conversation, publish_timeline_event
from app.config import BotConfig
from app.transports.ports import (
    InteractionSurface,
    SurfaceCapabilities,
    SurfaceEditableHandle,
)


class RegistryEditableHandle(SurfaceEditableHandle):
    def __init__(self, conversation: "RegistryConversationIO", *, event_id: str, kind: str, title: str) -> None:
        self._conversation = conversation
        self._event_id = event_id
        self._kind = kind
        self._title = title

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self._conversation.last_status_text = text
        self._conversation._append_output("edit", html.unescape(text))
        await publish_timeline_event(
            self._conversation.config,
            conversation_ref=self._conversation.conversation_ref,
            kind=self._kind,
            title=self._title,
            body=text,
            metadata=self._conversation._metadata(),
            event_id=self._event_id,
        )

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs
        return None


class RegistryConversationIO(InteractionSurface):
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
        self.chat = _RegistryChatShim(self)

    @property
    def capabilities(self) -> SurfaceCapabilities:
        return SurfaceCapabilities(
            can_edit_message=True,
            can_answer_action=True,
            can_send_photo=False,
            can_send_document=False,
            can_render_timeline=True,
            can_present_actions=True,
            can_share_conversation=True,
            surface_name="registry",
        )

    def _metadata(self) -> dict[str, Any]:
        return {"routed_task_id": self.routed_task_id} if self.routed_task_id else {}

    def _append_output(self, kind: str, text: str) -> None:
        if self._output_log is None:
            return
        self._output_log.append({"type": kind, "text": text})

    async def send_text(self, text: str, **kwargs: Any) -> SurfaceEditableHandle:
        del kwargs
        event_id = uuid.uuid4().hex
        self.sent_messages.append(text)
        self._append_output("send", text)
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="bot_message",
            title="Bot reply",
            body=text,
            metadata=self._metadata(),
            event_id=event_id,
        )
        return RegistryEditableHandle(self, event_id=event_id, kind="bot_message", title="Bot reply")

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        caption = kwargs.get("caption", "[photo]")
        self._append_output("send", caption)
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="attachment",
            title="Photo",
            body=f"{caption}\n{photo if isinstance(photo, (str, Path)) else '[binary]'}",
            metadata=self._metadata(),
        )

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        caption = kwargs.get("caption", "[document]")
        self._append_output("send", caption)
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="attachment",
            title="Document",
            body=f"{caption}\n{document if isinstance(document, (str, Path)) else '[binary]'}",
            metadata=self._metadata(),
        )

    async def send_action(self, action: str) -> None:
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="surface_action",
            title="Bot action",
            body=action,
            metadata=self._metadata(),
        )

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        detail = text or ("alert" if show_alert else "ack")
        self._append_output("answer", detail)
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="action_answer",
            title="Action handled",
            body=detail,
            metadata=self._metadata(),
        )

    async def publish_timeline(self, event: Any) -> None:
        body = getattr(event, "body", "") or getattr(event, "text", "") or ""
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind=getattr(event, "kind", "timeline"),
            title=getattr(event, "title", "Update"),
            body=body,
            metadata=self._metadata(),
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

    async def on_message_received(self, text: str) -> None:
        del text
        return None

    async def on_outcome(self, outcome: Any) -> None:
        del outcome
        return None

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        del preview, run_again_label, skip_label
        self._append_output("send", prompt)
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="recovery_notice",
            title="Interrupted work needs replay",
            body=prompt,
            metadata={
                **self._metadata(),
                "update_id": update_id,
            },
        )

    async def reply_text(self, text: str, **kwargs: Any) -> SurfaceEditableHandle:
        return await self.send_text(text, **kwargs)

    async def reply_document(self, document: Any, **kwargs: Any) -> None:
        await self.send_document(document, **kwargs)

    async def reply_photo(self, photo: Any, **kwargs: Any) -> None:
        await self.send_photo(photo, **kwargs)

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self.send_text(text, **kwargs)

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del kwargs
        self.last_status_text = text
        self._append_output("edit", html.unescape(text))
        await publish_timeline_event(
            self.config,
            conversation_ref=self.conversation_ref,
            kind="status",
            title="Status",
            body=html.unescape(text),
            metadata=self._metadata(),
        )

    async def delete(self) -> None:
        return None


class _RegistryChatShim:
    def __init__(self, conversation: RegistryConversationIO) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_message(text, **kwargs)

    async def send_action(self, action: str) -> None:
        await self._conversation.send_action(action)
