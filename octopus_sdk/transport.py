"""Unified transport contracts for bot-side ingress, egress, identity, and lifecycle."""

from __future__ import annotations

import asyncio
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Protocol

from octopus_sdk.inbound_types import InboundEnvelope
from octopus_sdk.providers import DenialRecord
from octopus_sdk.skill_types import SkillRequirement


@dataclass(frozen=True)
class TransportDescriptor:
    transport_type: str
    display_name: str
    supports_multiple: bool
    inbound_model: str
    trust_tier: str = "untrusted"
    contributes_transport_capability: bool = True
    accepts_transport_input: bool = True
    supports_conversation_binding: bool = True
    supports_timeline: bool = True
    supports_editing: bool = True
    supports_inline_actions: bool = True
    supports_recovery: bool = False


@dataclass(frozen=True)
class TransportCapabilities:
    can_edit_message: bool = True
    can_answer_action: bool = True
    can_send_photo: bool = True
    can_send_document: bool = True
    can_render_timeline: bool = False
    can_present_actions: bool = True
    can_share_conversation: bool = False
    channel_name: str = "telegram"

    @property
    def transport_name(self) -> str:
        return self.channel_name


@dataclass(frozen=True)
class InboundSubmissionResult:
    status: str
    item_id: str | None = None


class EditableHandle(ABC):
    @abstractmethod
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        ...


class TransportIdentityResolver(Protocol):
    def conversation_key(self, raw_conversation_id: object) -> str: ...

    def actor_key(self, raw_actor_id: object) -> str: ...

    def external_conversation_ref(self, raw_conversation_id: object) -> str: ...


class TransportEgress(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> TransportCapabilities:
        ...

    @abstractmethod
    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        ...

    @abstractmethod
    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        ...

    @abstractmethod
    async def send_action(self, action: str) -> None:
        ...

    @abstractmethod
    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        ...

    async def sync_binding(self, binding: Any) -> None:
        del binding
        return None

    async def bind(self, *, title: str, config: Any) -> None:
        del title, config
        return None

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
        del preview, prompt, run_again_label, skip_label, update_id
        return None

    async def send_status(self, text: str, **kwargs: Any) -> EditableHandle:
        return await self.send_text(text, **kwargs)

    def typing_target(self) -> Any:
        return self

    async def show_foreign_setup(self, foreign_setup: Any) -> None:
        del foreign_setup
        return None

    async def show_setup_prompt(
        self,
        missing_skill: str,
        first_requirement: SkillRequirement,
    ) -> None:
        del missing_skill, first_requirement
        return None

    async def send_retry_prompt(
        self,
        denials: tuple[DenialRecord, ...],
        callback_token: str,
    ) -> None:
        del denials, callback_token
        return None

    async def send_approval_prompt(self, callback_token: str) -> None:
        del callback_token
        return None

    async def send_formatted_reply(self, text: str) -> None:
        await self.send_text(text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: Any = None,
    ) -> None:
        del conversation_key_value, directives, resolved_ctx
        return None

    async def send_compact_reply(
        self,
        text: str,
        conversation_key_value: str,
        slot: int,
    ) -> None:
        del conversation_key_value, slot
        await self.send_formatted_reply(text)

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: Any,
        *,
        conversation_ref: str,
        result: Any,
    ) -> Any:
        del conversation_key_value, session, conversation_ref, result
        return None


class BotRuntimeHandle(Protocol):
    async def submit(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult: ...

    async def admit_message(self, envelope: InboundEnvelope) -> InboundSubmissionResult: ...

    async def enqueue(
        self,
        envelope: InboundEnvelope,
        *,
        worker_id: str | None = None,
    ) -> InboundSubmissionResult: ...

    async def record(self, envelope: InboundEnvelope) -> bool: ...


class TransportImplementation(ABC):
    @property
    @abstractmethod
    def transport_id(self) -> str:
        ...

    @property
    @abstractmethod
    def descriptor(self) -> TransportDescriptor:
        ...

    @property
    def identity(self) -> TransportIdentityResolver | None:
        return None

    @abstractmethod
    def ref_prefix(self) -> str:
        ...

    @abstractmethod
    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> TransportEgress:
        ...

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        try:
            self.build_egress(conversation_ref=conversation_ref, config=config, **kw)
        except RuntimeError:
            return False
        return True

    async def start(
        self,
        *,
        runtime: BotRuntimeHandle,
        stop_event: asyncio.Event,
    ) -> None:
        del runtime, stop_event
        await asyncio.sleep(0)

    async def stop(self) -> None:
        return None

    async def health_check(self) -> dict[str, Any]:
        return {
            "transport_id": self.transport_id,
            "transport_type": self.descriptor.transport_type,
            "inbound_model": self.descriptor.inbound_model,
        }
