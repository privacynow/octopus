"""Test-only registry participant stubs."""

from __future__ import annotations

from dataclasses import dataclass

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
from octopus_sdk.registry_participant import (
    RegistryConversationMirror,
    RegistryCoordination,
    RegistryDiscovery,
    RegistryParticipant,
    RegistryParticipantHealth,
    RegistryParticipantImplementation,
)


class _NoOpEnrollment(RegistryParticipant):
    async def enroll(self) -> EnrollmentResult:
        return EnrollmentResult()

    async def heartbeat(self) -> None:
        return None

    def is_enrolled(self, authority: AuthorityId) -> bool:
        del authority
        return False

    def local_agent_id(self, authority: AuthorityId) -> str:
        del authority
        return ""


class _NoOpHealth(RegistryParticipantHealth):
    def enrollment_state(self) -> dict[AuthorityId, EnrollmentResult]:
        return {}

    def connectivity_state(self, authority: AuthorityId) -> ConnectivityState:
        del authority
        return ConnectivityState("standalone")

    def current_local_agent_ids(self) -> dict[AuthorityId, str]:
        return {}

    def live_local_agent_ids(self) -> dict[AuthorityId, str]:
        return {}


class _NoOpDiscovery(RegistryDiscovery):
    async def search_agents(self, *, query: AgentDiscoveryQuery) -> AgentSearchResult:
        del query
        return AgentSearchResult(status="unavailable")

    async def resolve_authority(self, *, selector: TargetSelector) -> AuthorityId:
        del selector
        raise RuntimeError("Registry participation unavailable.")


class _NoOpMirror(RegistryConversationMirror):
    async def create_conversation(
        self,
        conversation_key: TransportConversationKey,
        *,
        origin_channel: str,
        external_ref: ExternalConversationRef,
    ) -> ConversationId:
        del conversation_key, origin_channel, external_ref
        return ConversationId("")

    async def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[MirrorOutcome]:
        del conversation_id, events
        return []

    async def submit_message(
        self,
        conversation_id: ConversationId,
        *,
        text: str,
        actor: TransportActorKey,
    ) -> list[MirrorOutcome]:
        del conversation_id, text, actor
        return []

    async def submit_action(
        self,
        conversation_id: ConversationId,
        *,
        envelope: CoordinationActionEnvelope,
    ) -> list[MirrorOutcome]:
        del conversation_id, envelope
        return []


class _NoOpCoordination(RegistryCoordination):
    async def ensure_conversation_id(
        self,
        conversation_key: TransportConversationKey,
        *,
        conversation_ref: str,
        origin_channel: str,
        external_ref: ExternalConversationRef,
        title: str,
    ) -> ConversationId:
        del conversation_key, conversation_ref, origin_channel, external_ref, title
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")

    async def direct_assign(
        self,
        conversation_id: ConversationId,
        *,
        selector: TargetSelector,
        title: str,
        instructions: str,
        message_text: str = "",
    ) -> CoordinationActionResult:
        del conversation_id, selector, title, instructions, message_text
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")

    async def delegate_tasks(
        self,
        conversation_id: ConversationId,
        *,
        intent: DelegationIntent,
    ) -> CoordinationActionResult:
        del conversation_id, intent
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")

    async def approve_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult:
        del conversation_id, proposal_id
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")

    async def cancel_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult:
        del conversation_id, proposal_id
        raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")

    async def preview_target_resolution(self, selector: TargetSelector) -> TargetResolutionPreview:
        del selector
        return TargetResolutionPreview(status="unavailable")


@dataclass(frozen=True)
class _NoOpRegistryParticipantImplementation(RegistryParticipantImplementation):
    enrollment: RegistryParticipant
    mirror: RegistryConversationMirror
    coordination: RegistryCoordination
    discovery: RegistryDiscovery
    health: RegistryParticipantHealth


def build_noop_registry_participant() -> RegistryParticipantImplementation:
    return _NoOpRegistryParticipantImplementation(
        enrollment=_NoOpEnrollment(),
        mirror=_NoOpMirror(),
        coordination=_NoOpCoordination(),
        discovery=_NoOpDiscovery(),
        health=_NoOpHealth(),
    )
