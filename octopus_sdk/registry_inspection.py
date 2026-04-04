"""Read-only registry inspection port used by runtime facts and audits."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from octopus_sdk.registry.models import ConversationRecord, EventPageRecord, TaskRecord


@runtime_checkable
class RegistryInspectionPort(Protocol):
    async def get_conversation(self, authority_ref: str, conversation_id: str) -> ConversationRecord: ...

    async def get_task(self, authority_ref: str, routed_task_id: str) -> TaskRecord: ...

    async def list_events(
        self,
        authority_ref: str,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord: ...


class NoOpRegistryInspection:
    async def get_conversation(self, authority_ref: str, conversation_id: str) -> ConversationRecord:
        del authority_ref, conversation_id
        raise RuntimeError("Registry inspection unavailable")

    async def get_task(self, authority_ref: str, routed_task_id: str) -> TaskRecord:
        del authority_ref, routed_task_id
        raise RuntimeError("Registry inspection unavailable")

    async def list_events(
        self,
        authority_ref: str,
        conversation_id: str,
        *,
        kind: str = "",
        before_seq: int = 0,
        after_seq: int = 0,
        limit: int = 50,
    ) -> EventPageRecord:
        del authority_ref, conversation_id, kind, before_seq, after_seq, limit
        raise RuntimeError("Registry inspection unavailable")
