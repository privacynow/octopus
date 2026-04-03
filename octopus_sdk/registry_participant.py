"""SDK interfaces for bot-side registry participation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from octopus_sdk.agent_directory import AgentSearchResult
from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    AuthorityId,
    ConnectivityState,
    ConversationId,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    DelegationIntent,
    EnrollmentResult,
    ExternalConversationRef,
    MirrorOutcome,
    TargetResolutionPreview,
    TargetSelector,
    TransportActorKey,
    TransportConversationKey,
)


@runtime_checkable
class RegistryParticipant(Protocol):
    async def enroll(self) -> EnrollmentResult: ...

    async def heartbeat(self) -> None: ...

    def is_enrolled(self, authority: AuthorityId) -> bool: ...

    def local_agent_id(self, authority: AuthorityId) -> str: ...


@runtime_checkable
class RegistryConversationMirror(Protocol):
    async def create_conversation(
        self,
        conversation_key: TransportConversationKey,
        *,
        origin_channel: str,
        external_ref: ExternalConversationRef,
    ) -> ConversationId: ...

    async def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[MirrorOutcome]: ...

    async def submit_message(
        self,
        conversation_id: ConversationId,
        *,
        text: str,
        actor: TransportActorKey,
    ) -> list[MirrorOutcome]: ...

    async def submit_action(
        self,
        conversation_id: ConversationId,
        *,
        envelope: CoordinationActionEnvelope,
    ) -> list[MirrorOutcome]: ...


@runtime_checkable
class RegistryCoordination(Protocol):
    async def ensure_conversation_id(
        self,
        conversation_key: TransportConversationKey,
        *,
        conversation_ref: str,
        origin_channel: str,
        external_ref: ExternalConversationRef,
        title: str,
    ) -> ConversationId: ...

    async def direct_assign(
        self,
        conversation_id: ConversationId,
        *,
        selector: TargetSelector,
        title: str,
        instructions: str,
        origin_transport_ref: str = "",
        authorized_actor_key: str = "",
        message_text: str = "",
        requested_skills: list[str] | tuple[str, ...] = (),
    ) -> CoordinationActionResult: ...

    async def delegate_tasks(
        self,
        conversation_id: ConversationId,
        *,
        intent: DelegationIntent,
    ) -> CoordinationActionResult: ...

    async def approve_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult: ...

    async def cancel_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult: ...

    async def preview_target_resolution(
        self,
        selector: TargetSelector,
    ) -> TargetResolutionPreview: ...


@runtime_checkable
class RegistryDiscovery(Protocol):
    async def search_agents(
        self,
        *,
        query: AgentDiscoveryQuery,
    ) -> AgentSearchResult: ...

    async def resolve_authority(self, *, selector: TargetSelector) -> AuthorityId: ...


@runtime_checkable
class RegistryParticipantHealth(Protocol):
    def enrollment_state(self) -> dict[AuthorityId, EnrollmentResult]: ...

    def connectivity_state(self, authority: AuthorityId) -> ConnectivityState: ...

    def current_local_agent_ids(self) -> dict[AuthorityId, str]: ...

    def live_local_agent_ids(self) -> dict[AuthorityId, str]: ...


@runtime_checkable
class RegistryParticipantImplementation(Protocol):
    enrollment: RegistryParticipant
    mirror: RegistryConversationMirror
    coordination: RegistryCoordination
    discovery: RegistryDiscovery
    health: RegistryParticipantHealth
