"""Unified transport contracts for bot-side ingress, egress, identity, and lifecycle."""

from __future__ import annotations

import asyncio
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import fields
from pathlib import Path
from collections.abc import Iterator, Mapping
from typing import Protocol

from octopus_sdk.config import BotConfigBase
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.inbound_types import InboundEnvelope
from octopus_sdk.providers import DenialRecord
from octopus_sdk.registry.models import ExternalConversationRef
from octopus_sdk.registry.models import TransportActorKey
from octopus_sdk.registry.models import TransportConversationKey
from octopus_sdk.sessions import AwaitingSkillSetup
from octopus_sdk.sessions import SessionState
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


@dataclass(frozen=True)
class TransportBindingRecord:
    conversation_ref: str = ""
    title: str = ""
    origin_channel: str = ""
    external_id: str = ""


@dataclass(frozen=True)
class TransportHealthRecord(Mapping[str, object]):
    transport_id: str
    transport_type: str
    inbound_model: str
    bot_mode: str = ""
    registry_ids: tuple[str, ...] = ()
    ok: bool | None = None

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        for field in fields(self):
            yield field.name

    def __len__(self) -> int:
        return len(fields(self))

    def get(self, key: str, default: object = None) -> object:
        return getattr(self, key, default)


class TypingTarget(Protocol):
    async def send_action(self, action: str) -> None: ...


class EditableHandle(ABC):
    @abstractmethod
    async def edit_text(self, text: str, **kwargs: object) -> None:
        ...

    @abstractmethod
    async def edit_reply_markup(self, reply_markup: object | None = None, **kwargs: object) -> None:
        ...


class TransportIdentityResolver(Protocol):
    def conversation_key(self, raw_conversation_id: object) -> TransportConversationKey: ...

    def actor_key(self, raw_actor_id: object) -> TransportActorKey: ...

    def external_conversation_ref(self, raw_conversation_id: object) -> ExternalConversationRef: ...


class TransportEgress(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> TransportCapabilities:
        ...

    @abstractmethod
    async def send_text(self, text: str, **kwargs: object) -> EditableHandle:
        ...

    @abstractmethod
    async def send_photo(self, photo: Path | str | bytes, **kwargs: object) -> None:
        ...

    @abstractmethod
    async def send_document(self, document: Path | str | bytes, **kwargs: object) -> None:
        ...

    @abstractmethod
    async def send_action(self, action: str) -> None:
        ...

    @abstractmethod
    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        ...

    @abstractmethod
    async def sync_binding(self, binding: TransportBindingRecord) -> None:
        ...

    @abstractmethod
    async def bind(self, *, title: str, config: BotConfigBase) -> None:
        ...

    @abstractmethod
    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        ...

    @abstractmethod
    async def send_status(self, text: str, **kwargs: object) -> EditableHandle:
        ...

    @abstractmethod
    def typing_target(self) -> TypingTarget:
        ...

    @abstractmethod
    async def show_foreign_setup(self, foreign_setup: AwaitingSkillSetup) -> None:
        ...

    @abstractmethod
    async def show_setup_prompt(
        self,
        missing_skill: str,
        first_requirement: SkillRequirement,
    ) -> None:
        ...

    @abstractmethod
    async def send_retry_prompt(
        self,
        denials: tuple[DenialRecord, ...],
        callback_token: str,
    ) -> None:
        ...

    @abstractmethod
    async def send_approval_prompt(self, callback_token: str) -> None:
        ...

    @abstractmethod
    async def send_formatted_reply(self, text: str) -> None:
        ...

    @abstractmethod
    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: ResolvedExecutionContext | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def send_compact_reply(
        self,
        text: str,
        conversation_key_value: str,
        slot: int,
    ) -> None:
        ...

    @abstractmethod
    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: SessionState,
        *,
        conversation_ref: str,
        result: RunResult,
    ) -> RequestExecutionOutcome | None:
        ...


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
    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        ...

    def can_build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> bool:
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

    async def health_check(self) -> TransportHealthRecord:
        return TransportHealthRecord(
            transport_id=self.transport_id,
            transport_type=self.descriptor.transport_type,
            inbound_model=self.descriptor.inbound_model,
        )
