"""Registry channel egress implementation."""

from __future__ import annotations

import html
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.channels.registry.refs import binding_external_id_for_ref, parse_registry_ref
from app.config import BotConfig
from app.formatting import trim_text
from app.ports.egress import (
    ChannelCapabilities,
    ChannelEgress,
    EditableHandle,
)
from app.runtime.services import BotServices

log = logging.getLogger(__name__)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RegistryEditableHandle(EditableHandle):
    def __init__(self, conversation: "RegistryChannelEgress", *, event_id: str) -> None:
        self._conversation = conversation
        self._event_id = event_id

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
        registry_id: str = "",
        routed_task_id: str = "",
        authority_ref: str = "",
        title: str = "",
        output_log: list[dict[str, str]] | None = None,
        external_id: str = "",
        services: BotServices,
    ) -> None:
        parsed_ref = parse_registry_ref(conversation_ref)
        if parsed_ref is None:
            raise ValueError(
                f"Registry channel egress requires a qualified registry ref, got {conversation_ref!r}"
            )
        if registry_id and registry_id != parsed_ref[0]:
            raise ValueError(
                "Registry channel egress registry_id must match the qualified registry ref"
            )
        self.config = config
        self.conversation_ref = conversation_ref
        self._ref_kind = parsed_ref[1]
        self.registry_id = parsed_ref[0]
        self.routed_task_id = routed_task_id or (parsed_ref[2] if parsed_ref[1] == "task" else "")
        self.authority_ref = authority_ref
        self.title = title or "Registry conversation"
        self.external_id = external_id or binding_external_id_for_ref(conversation_ref)
        self.sent_messages: list[str] = []
        self.last_status_text = ""
        self._output_log = output_log
        self._services = services
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
            can_render_timeline=(self._ref_kind == "conversation"),
            can_present_actions=True,
            can_share_conversation=(self._ref_kind == "conversation"),
            channel_name="registry",
        )

    def _is_task_ref(self) -> bool:
        return self._ref_kind == "task"

    def _append_output(self, kind: str, text: str) -> None:
        if self._output_log is None:
            return
        self._output_log.append({"type": kind, "text": text})

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
        from registry_sdk.events import ConversationEvent

        resolved_event_id = event_id or uuid.uuid4().hex
        merged_metadata: dict[str, Any] = dict(metadata or {})
        if status:
            merged_metadata["status"] = status
        if progress is not None:
            merged_metadata["progress"] = progress
        event = ConversationEvent(
            event_id=resolved_event_id,
            kind=kind,
            content=body or title,
            created_at=_utcnow_iso(),
            metadata=merged_metadata,
        )
        # Extract conversation_id from the qualified registry ref
        parsed = parse_registry_ref(self.conversation_ref)
        conversation_id = parsed[2] if parsed else self.conversation_ref
        try:
            await self._services.control_plane.conversation_projection.publish_events(
                conversation_id=conversation_id,
                events=[event],
            )
        except Exception:
            log.warning(
                "Event publish failed for %s (non-fatal)",
                self.conversation_ref,
                exc_info=True,
            )

    async def _publish_progress(self, html_text: str, *, event_id: str | None = None) -> None:
        # Progress updates are ephemeral — not persisted as events.
        # The progress-bar edit mechanism still works via RegistryEditableHandle,
        # but we don't write a permanent event to the store.
        del html_text, event_id
        return

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        del kwargs
        event_id = uuid.uuid4().hex
        self.sent_messages.append(text)
        self._append_output("send", text)
        if not self._is_task_ref():
            await self._publish_event(
                kind="message.bot",
                title="Bot reply",
                body=text,
                event_id=event_id,
            )
        return RegistryEditableHandle(self, event_id=event_id)

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        if self._is_task_ref():
            return
        caption = kwargs.get("caption", "[photo]")
        self._append_output("send", caption)
        await self._publish_event(
            kind="message.bot",
            title="Photo",
            body=f"{caption}\n{photo if isinstance(photo, (str, Path)) else '[binary]'}",
            metadata={"attachments": [str(photo) if isinstance(photo, (str, Path)) else "[binary]"]},
        )

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        if self._is_task_ref():
            return
        caption = kwargs.get("caption", "[document]")
        self._append_output("send", caption)
        await self._publish_event(
            kind="message.bot",
            title="Document",
            body=f"{caption}\n{document if isinstance(document, (str, Path)) else '[binary]'}",
            metadata={"attachments": [str(document) if isinstance(document, (str, Path)) else "[binary]"]},
        )

    async def send_action(self, action: str) -> None:
        if self._is_task_ref():
            return
        # Bot actions are internal transport signals — not persisted as conversation events.
        return

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        if self._is_task_ref():
            return
        detail = text or ("alert" if show_alert else "ack")
        self._append_output("answer", detail)
        # Action answers are internal transport signals — not persisted.
        return

    async def sync_binding(self, binding: Any) -> None:
        del binding

    async def bind(self, *, title: str, config: Any) -> None:
        del config
        self.title = title or self.title
        if self._is_task_ref():
            return
        await self._publish_event(kind="task.status", title="Conversation started", metadata={"status": "started"})

    async def on_message_received(self, text: str) -> None:
        del text
        return None

    async def on_outcome(self, outcome: Any) -> None:
        if self._is_task_ref():
            return None
        if outcome is None:
            return None
        returncode = getattr(outcome, "returncode", 0)
        timed_out = bool(getattr(outcome, "timed_out", False))
        if hasattr(outcome, "returncode"):
            if returncode == 0 and not timed_out:
                await self._publish_event(
                    kind="task.status",
                    title="Done",
                    body=trim_text(getattr(outcome, "text", "") or "", 400),
                    metadata={"status": "completed"},
                )
                return None
            reason = "Timed out" if timed_out else f"Exited {returncode}"
            await self._publish_event(kind="error", title="Failed", body=reason, metadata={"error_type": "execution", "message": reason})
            return None

        status = str(getattr(outcome, "status", "") or "")
        if status.startswith("completed"):
            body = getattr(outcome, "reply_text", "") or self._plain_text_snippet(self.last_status_text, limit=400)
            await self._publish_event(kind="task.status", title="Done", body=trim_text(body, 400), metadata={"status": "completed"})
            return None
        if status == "timed_out":
            await self._publish_event(kind="error", title="Failed", body="Timed out", metadata={"error_type": "execution", "message": "Timed out"})
            return None
        if status == "cancelled":
            await self._publish_event(kind="task.status", title="Cancelled", body="Cancelled", metadata={"status": "cancelled"})
            return None
        if status:
            body = getattr(outcome, "error_text", "") or status
            await self._publish_event(kind="error", title="Failed", body=trim_text(body, 400), metadata={"error_type": "execution", "message": trim_text(body, 400)})

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        if self._is_task_ref():
            return
        del run_again_label, skip_label, update_id
        await self._publish_event(
            kind="error",
            title="Recovery available",
            body=f"{preview}\n\n{prompt}".strip(),
            metadata={"error_type": "recovery", "message": preview},
        )

    async def reply_text(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)


class _RegistryChatShim:
    def __init__(self, conversation: RegistryChannelEgress) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_text(text, **kwargs)
