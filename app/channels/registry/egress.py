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

from app.agents.client import AgentRegistryClient
from app.agents.state import load_runtime_registry_connection_state
from app.formatting import summarize_text
from octopus_sdk.registry.models import DelegationIntent
from octopus_sdk.registry.models import RoutedTaskUpdate
from app.channels.registry.refs import binding_external_id_for_ref, parse_registry_ref
from app.config import BotConfig
from app.formatting import trim_text
from octopus_sdk.execution import RequestExecutionOutcome
from octopus_sdk.execution_context import ResolvedExecutionContext
from app.runtime.session_runtime import LocalSessionRuntime
from octopus_sdk.transport import (
    EditableHandle,
    TransportBindingRecord,
    TransportCapabilities,
    TransportEgress,
)
from octopus_sdk.workflows.delegation import (
    ParticipantDelegationRuntime,
    propose_participant_delegation,
)
from octopus_sdk.providers import DenialRecord
from octopus_sdk.sessions import AwaitingSkillSetup, SessionState
from octopus_sdk.skill_types import SkillRequirement
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
        if not self._conversation._is_task_ref():
            await self._conversation._publish_progress(text, event_id=self._event_id)

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs
        return None


class RegistryChannelEgress(TransportEgress):
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

    def _is_ephemeral_status_text(self, text: str) -> bool:
        normalized = " ".join(str(text or "").split())
        return normalized in {"Working…", "Working...", "Resuming…", "Resuming..."}

    @property
    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities(
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
        from octopus_sdk.events import ConversationEvent

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
        # Extract conversation_id the qualified registry ref
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
        del event_id
        summary = self._plain_text_snippet(html_text, limit=240)
        if not summary:
            return
        now = time.monotonic()
        if now - self._last_progress_published_at < self._PROGRESS_MIN_INTERVAL:
            return
        self._last_progress_published_at = now

        if self._is_task_ref():
            if not self.routed_task_id or not self.authority_ref:
                return
            try:
                await self._services.control_plane.task_routing.update_routed_task_status(
                    update=RoutedTaskUpdate(
                        routed_task_id=self.routed_task_id,
                        status="running",
                        transition_id=uuid.uuid4().hex,
                        summary=summary,
                    ),
                    authority_ref=self.authority_ref,
                )
            except Exception:
                log.warning(
                    "Routed task progress publish failed for %s",
                    self.conversation_ref,
                    exc_info=True,
                )
            return

        registry = next(
            (item for item in self.config.agent_registries if item.registry_id == self.registry_id),
            None,
        )
        if registry is None or not registry.url:
            return
        state = load_runtime_registry_connection_state(
            self.config.data_dir,
            self.registry_id,
            registry_scope=registry.registry_scope,
        )
        if not state.agent_token:
            return
        parsed = parse_registry_ref(self.conversation_ref)
        conversation_id = parsed[2] if parsed else self.conversation_ref
        client = AgentRegistryClient(
            registry.url,
            agent_token=state.agent_token,
            timeout_seconds=10.0,
        )
        try:
            await client.publish_progress(
                conversation_id,
                content=summary,
                created_at=_utcnow_iso(),
            )
        except Exception:
            log.warning(
                "Conversation progress publish failed for %s",
                self.conversation_ref,
                exc_info=True,
            )

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        del kwargs
        event_id = uuid.uuid4().hex
        self.sent_messages.append(text)
        self._append_output("send", text)
        if not self._is_task_ref() and not self._is_ephemeral_status_text(text):
            await self._publish_event(
                kind="message.bot",
                title="Bot reply",
                body=text,
                event_id=event_id,
            )
        elif not self._is_task_ref():
            await self._publish_progress(text, event_id=event_id)
        return RegistryEditableHandle(self, event_id=event_id)

    async def send_status(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)

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

    def typing_target(self):
        return self

    async def sync_binding(self, binding: TransportBindingRecord) -> None:
        title = str(binding.title or "").strip()
        if title:
            self.title = title
        external_id = str(binding.external_id or "").strip()
        if external_id:
            self.external_id = external_id

    async def bind(self, *, title: str, config: BotConfig) -> None:
        del config
        self.title = title or self.title
        if self._is_task_ref():
            return
        await self._publish_event(kind="task.status", title="Conversation started", metadata={"status": "started"})

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
            metadata={
                "error_type": "recovery",
                "message": "Execution paused. Choose how to continue.",
            },
        )

    async def reply_text(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)

    async def show_foreign_setup(self, foreign_setup: AwaitingSkillSetup) -> None:
        detail = getattr(foreign_setup, "actor_key", "") or "another operator"
        await self.send_text(
            f"Setup must be completed by {detail} before this request can continue."
        )

    async def show_setup_prompt(self, missing_skill: str, first_requirement: SkillRequirement) -> None:
        detail = str(first_requirement.get("label") or first_requirement.get("kind") or "required setup").strip()
        await self.send_text(
            f"Setup required for {missing_skill or 'this request'}: {detail}."
        )

    async def send_retry_prompt(
        self,
        denials: tuple[DenialRecord, ...],
        callback_token: str,
    ) -> None:
        del callback_token
        count = len(denials)
        await self.send_text(
            f"Execution needs approval before retrying {count} blocked action(s)."
        )

    async def send_approval_prompt(self, callback_token: str) -> None:
        del callback_token
        await self.send_text("Approval required before this plan can continue.")

    async def send_formatted_reply(self, text: str) -> None:
        await self.send_text(text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: ResolvedExecutionContext | None = None,
    ) -> None:
        del conversation_key_value, resolved_ctx
        for dtype, raw_path in directives:
            await self.send_text(f"{dtype}: {raw_path}")

    async def send_compact_reply(self, text: str, conversation_key_value: str, slot: int) -> None:
        del conversation_key_value, slot
        await self.send_text(text)

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: SessionState,
        *,
        conversation_ref: str,
        result: RunResult,
    ) -> RequestExecutionOutcome:
        intent = getattr(result, "coordination_intent", None)
        if intent is None or not intent.tasks:
            return RequestExecutionOutcome(status="failed", error_text="No coordination intent was supplied.")
        title = str(getattr(intent, "title", "") or "").strip() or summarize_text(getattr(result, "text", "") or "") or "Delegation plan"
        try:
            plan = await propose_participant_delegation(
                ParticipantDelegationRuntime(
                    config=self.config,
                    provider_name=self.config.provider_name,
                    provider_state_factory=lambda _conversation_key: {},
                    coordination=self._services.registry.coordination,
                    sessions=LocalSessionRuntime(self.config),
                ),
                conversation_key_value,
                session,
                conversation_ref=conversation_ref,
                title=title,
                intent=DelegationIntent(
                    title=title,
                    resume_instruction=intent.resume_instruction,
                    tasks=list(intent.tasks),
                ),
                origin_channel="registry",
                external_ref=self.external_id or conversation_key_value,
            )
        except Exception as exc:
            return RequestExecutionOutcome(status="failed", error_text=str(exc))

        if plan.status == "delegation_submitted":
            await self.send_text("Delegation approved. Specialist requests were sent.")
            return RequestExecutionOutcome(status="delegation_submitted")

        lines = [f"Delegation plan: {title}"]
        for task in plan.pending.tasks if plan.pending is not None else ():
            label = task.target_agent_id or task.title or task.routed_task_id
            lines.append(f"- {task.title or 'Task'} -> {label}")
        for preview in plan.previews:
            if preview.status != "resolved":
                detail = preview.detail or preview.status
                lines.append(f"- Resolution issue: {detail}")
        await self.send_text("\n".join(lines))
        return RequestExecutionOutcome(status="delegation_proposed")


class _RegistryChatShim:
    def __init__(self, conversation: RegistryChannelEgress) -> None:
        self._conversation = conversation

    async def send_message(self, text: str, **kwargs: Any) -> Any:
        return await self._conversation.send_text(text, **kwargs)
