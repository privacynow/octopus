"""SDK authority contracts for the registry server implementation."""

from __future__ import annotations

from typing import Protocol

from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import AckResult
from octopus_sdk.registry.models import AgentCard
from octopus_sdk.registry.models import AgentDiscoveryQuery
from octopus_sdk.registry.models import AgentId
from octopus_sdk.registry.models import AgentRecord
from octopus_sdk.registry.models import AuthorityId
from octopus_sdk.registry.models import ConversationCreate
from octopus_sdk.registry.models import ConversationId
from octopus_sdk.registry.models import ConversationRecord
from octopus_sdk.registry.models import CoordinationActionEnvelope
from octopus_sdk.registry.models import CoordinationActionResult
from octopus_sdk.registry.models import DeliveryId
from octopus_sdk.registry.models import DeliveryRecord
from octopus_sdk.registry.models import EnrollmentResult
from octopus_sdk.registry.models import EventRecord
from octopus_sdk.registry.models import ExternalConversationRef
from octopus_sdk.registry.models import HealthSummary
from octopus_sdk.registry.models import MessageRecord
from octopus_sdk.registry.models import MirrorOutcome
from octopus_sdk.registry.models import RoutedTaskRequest
from octopus_sdk.registry.models import RoutedTaskResult
from octopus_sdk.registry.models import RoutedTaskUpdate
from octopus_sdk.registry.models import RuntimeHealthPayload
from octopus_sdk.registry.models import TargetSelector
from octopus_sdk.registry.models import TaskRecord
from octopus_sdk.registry.models import TransportActorKey


class RegistryAuthorityConversationStore(Protocol):
    def create_conversation(self, conversation: ConversationCreate) -> ConversationRecord: ...

    def add_message(
        self,
        conversation_id: ConversationId,
        text: str,
        actor: TransportActorKey,
    ) -> MessageRecord: ...

    def submit_action(
        self,
        conversation_id: ConversationId,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult: ...

    def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[EventRecord]: ...


class RegistryAuthorityTaskRouter(Protocol):
    def submit_routed_task(self, task: RoutedTaskRequest) -> TaskRecord: ...

    def update_routed_task(self, update: RoutedTaskUpdate) -> TaskRecord: ...

    def report_routed_result(self, result: RoutedTaskResult) -> TaskRecord: ...


class RegistryAuthorityDirectory(Protocol):
    def search_agents(self, query: AgentDiscoveryQuery) -> list[AgentRecord]: ...

    def resolve_target_authority(self, selector: TargetSelector) -> AuthorityId: ...


class RegistryAuthorityHealth(Protocol):
    def accept_heartbeat(
        self,
        agent_id: AgentId,
        health: RuntimeHealthPayload,
    ) -> HealthSummary: ...

    def get_connectivity_summary(self) -> HealthSummary: ...


class RegistryAuthorityMirror(Protocol):
    def deterministic_conversation_id(
        self,
        bot_key: str,
        origin_channel: str,
        external_ref: ExternalConversationRef,
    ) -> ConversationId: ...

    def mirror_create(self, conversation: ConversationCreate) -> MirrorOutcome: ...

    def mirror_publish(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[MirrorOutcome]: ...

    def mirror_message(
        self,
        conversation_id: ConversationId,
        text: str,
        actor: TransportActorKey,
    ) -> list[MirrorOutcome]: ...

    def mirror_action(
        self,
        conversation_id: ConversationId,
        envelope: CoordinationActionEnvelope,
    ) -> list[MirrorOutcome]: ...


class RegistryAuthorityEnrollment(Protocol):
    def enroll_agent(self, card: AgentCard) -> EnrollmentResult: ...

    def renew_enrollment(self, agent_id: AgentId, card: AgentCard) -> EnrollmentResult: ...

    def disconnect_agent(self, agent_id: AgentId) -> AgentRecord: ...


class RegistryAuthorityDelivery(Protocol):
    def poll_deliveries(self, agent_id: AgentId, cursor: int) -> list[DeliveryRecord]: ...

    def ack_delivery(self, delivery_id: DeliveryId) -> AckResult: ...

    def fail_delivery(self, delivery_id: DeliveryId, reason: str) -> AckResult: ...
