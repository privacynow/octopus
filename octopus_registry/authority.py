"""Typed registry authority implementations backed by the registry store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AckResult,
    AgentCard,
    AgentDiscoveryQuery,
    AgentHeartbeatRequest,
    AgentId,
    AgentRecord,
    AgentRegisterRequest,
    AuthorityId,
    ConversationCreate,
    ConversationId,
    ConversationRecord,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    DeliveryId,
    DeliveryRecord,
    DeliveryPollResult,
    EnrollmentResult,
    EventRecord,
    ExternalConversationRef,
    HealthSummary,
    MessageRecord,
    MirrorOutcome,
    RoutedTaskRequest,
    RoutedTaskResult,
    RoutedTaskUpdate,
    RuntimeHealthPayload,
    TargetSelector,
    TaskRecord,
    TransportActorKey,
    parse_target_selector,
    utcnow_iso,
)
from octopus_sdk.registry.management import ManagementResult
from octopus_sdk.registry_authority import (
    RegistryAuthorityConversationStore,
    RegistryAuthorityDelivery,
    RegistryAuthorityDirectory,
    RegistryAuthorityEnrollment,
    RegistryAuthorityHealth,
    RegistryAuthorityMirror,
    RegistryAuthorityTaskRouter,
)

from .store_base import (
    AbstractRegistryStore,
    validated_heartbeat_payload,
    validated_register_payload,
    validated_routed_task_request,
)


def _local_authority_ref() -> AuthorityId:
    return AuthorityId("registry:local")


def _record(model_cls, payload):
    return model_cls.model_validate(payload)


@dataclass
class StoreBackedRegistryAuthority(
    RegistryAuthorityConversationStore,
    RegistryAuthorityTaskRouter,
    RegistryAuthorityDirectory,
    RegistryAuthorityHealth,
    RegistryAuthorityMirror,
    RegistryAuthorityEnrollment,
    RegistryAuthorityDelivery,
):
    """SDK authority facade over the existing registry store.

    The store still owns persistence and HTTP-facing auth. This facade exposes the
    typed SDK authority surface and caches active enrollment tokens for the bot
    runtimes enrolled through the current authority process.
    """

    store: AbstractRegistryStore
    _agent_tokens: dict[str, str] = field(default_factory=dict)
    _delivery_targets: dict[str, str] = field(default_factory=dict)

    def remember_agent_token(self, agent_id: str, agent_token: str) -> None:
        if agent_id and agent_token:
            self._agent_tokens[str(agent_id)] = str(agent_token)

    def _remember_enrollment(self, result: EnrollmentResult) -> EnrollmentResult:
        if result.agent_id and result.agent_token:
            self.remember_agent_token(str(result.agent_id), str(result.agent_token))
        return result

    def _token_for_agent(self, agent_id: str) -> str:
        token = self._agent_tokens.get(str(agent_id))
        if not token:
            raise PermissionError(
                f"Authority runtime has no live enrollment token cached for agent {agent_id}"
            )
        return token

    def _target_agent_for_conversation(self, conversation_id: str) -> str:
        conversation = self.store.get_conversation(conversation_id)
        target_agent_id = str(conversation.target_agent_id or "")
        if not target_agent_id:
            raise KeyError(f"Unknown conversation target for {conversation_id}")
        return target_agent_id

    def _target_agent_for_task(self, routed_task_id: str) -> str:
        task = self.store.get_task(routed_task_id)
        target_agent_id = str(task.target_agent_id or "")
        if not target_agent_id:
            raise KeyError(f"Unknown routed task target for {routed_task_id}")
        return target_agent_id

    def create_conversation(self, conversation: ConversationCreate) -> ConversationRecord:
        return self.store.create_conversation(
            target_agent_id=conversation.target_agent_id,
            title=conversation.title,
            origin_channel=conversation.origin_channel,
            external_conversation_ref=conversation.external_conversation_ref,
        )

    def add_message(
        self,
        conversation_id: ConversationId,
        text: str,
        actor: TransportActorKey,
    ) -> MessageRecord:
        del actor
        normalized = str(text or "").strip()
        parts = normalized.split(None, 1)
        if parts and parse_target_selector(parts[0]) is not None and len(parts) == 1:
            raise ValueError("Add instructions after the target selector to route work directly.")
        return self.store.add_conversation_message(str(conversation_id), normalized)

    def submit_action(
        self,
        conversation_id: ConversationId,
        envelope: CoordinationActionEnvelope,
    ) -> CoordinationActionResult:
        return self.store.add_conversation_action(str(conversation_id), envelope)

    def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[EventRecord]:
        target_agent_id = self._target_agent_for_conversation(str(conversation_id))
        token = self._token_for_agent(target_agent_id)
        result = self.store.publish_events(
            token,
            str(conversation_id),
            [event.model_dump(mode="json") for event in events],
        )
        return list(result.inserted_events)

    def submit_routed_task(self, task: RoutedTaskRequest | dict) -> TaskRecord:
        request = (
            task
            if isinstance(task, RoutedTaskRequest)
            else RoutedTaskRequest.model_validate(task)
        )
        return self.store.create_routed_task(request.model_dump(mode="json"))

    def update_routed_task(self, update: RoutedTaskUpdate | dict) -> TaskRecord:
        typed_update = (
            update
            if isinstance(update, RoutedTaskUpdate)
            else RoutedTaskUpdate.model_validate(update)
        )
        target_agent_id = self._target_agent_for_task(typed_update.routed_task_id)
        token = self._token_for_agent(target_agent_id)
        payload = typed_update.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
        )
        payload.pop("routed_task_id", None)
        return self.store.update_routed_task_status(
            token,
            typed_update.routed_task_id,
            payload,
        )

    def report_routed_result(self, result: RoutedTaskResult | dict) -> TaskRecord:
        typed_result = (
            result
            if isinstance(result, RoutedTaskResult)
            else RoutedTaskResult.model_validate(result)
        )
        target_agent_id = self._target_agent_for_task(typed_result.routed_task_id)
        token = self._token_for_agent(target_agent_id)
        payload = typed_result.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
        )
        payload.pop("routed_task_id", None)
        return self.store.update_routed_task_result(
            token,
            typed_result.routed_task_id,
            payload,
        )

    def search_agents(self, query: AgentDiscoveryQuery) -> list[AgentRecord]:
        return self.store.search_agents(query.model_dump(mode="json"))

    def resolve_target_authority(self, selector: TargetSelector) -> AuthorityId:
        del selector
        return _local_authority_ref()

    def accept_heartbeat(
        self,
        agent_id: AgentId,
        health: RuntimeHealthPayload,
    ) -> HealthSummary:
        token = self._token_for_agent(agent_id)
        result = self.store.heartbeat(
            token,
            {
                "connectivity_state": "connected",
                "current_capacity": 0,
                "max_capacity": 1,
                "runtime_health": health.model_dump(mode="json"),
            },
        )
        return HealthSummary(
            agent=result.agent,
            collections_changed=result.collections_changed,
            server_time=result.server_time,
        )

    def get_connectivity_summary(self) -> HealthSummary:
        agents = self.store.list_agents(limit=1000)
        connected = next(
            (
                item
                for item in agents
                if str(item.connectivity_state or "") == "connected"
            ),
            None,
        )
        return HealthSummary(
            agent=connected,
            collections_changed=False,
            server_time=utcnow_iso(),
        )

    def deterministic_conversation_id(
        self,
        bot_key: str,
        origin_channel: str,
        external_ref: ExternalConversationRef,
    ) -> ConversationId:
        canonical = f"{bot_key}:{origin_channel}:{external_ref}"
        return ConversationId(hashlib.sha256(canonical.encode()).hexdigest()[:32])

    def mirror_create(self, conversation: ConversationCreate) -> MirrorOutcome:
        created = self.create_conversation(conversation)
        return MirrorOutcome(
            authority_ref=str(_local_authority_ref()),
            status="committed",
            conversation_id=created.conversation_id,
            event_ids=[],
            retry_required=False,
        )

    def mirror_publish(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[MirrorOutcome]:
        inserted = self.publish_events(conversation_id, events)
        return [
            MirrorOutcome(
                authority_ref=str(_local_authority_ref()),
                status="committed",
                conversation_id=str(conversation_id),
                event_ids=[event.event_id],
                retry_required=False,
            )
            for event in inserted
        ]

    def mirror_message(
        self,
        conversation_id: ConversationId,
        text: str,
        actor: TransportActorKey,
    ) -> list[MirrorOutcome]:
        message = self.add_message(conversation_id, text, actor)
        event_id = message.event.event_id if message.event is not None else ""
        return [
            MirrorOutcome(
                authority_ref=str(_local_authority_ref()),
                status="committed",
                conversation_id=str(conversation_id),
                event_ids=[event_id] if event_id else [],
                retry_required=False,
            )
        ]

    def mirror_action(
        self,
        conversation_id: ConversationId,
        envelope: CoordinationActionEnvelope,
    ) -> list[MirrorOutcome]:
        result = self.submit_action(conversation_id, envelope)
        event = result.event
        if isinstance(event, dict):
            event_id = str(event.get("event_id", "") or "")
        else:
            event_id = str(getattr(event, "event_id", "") or "")
        return [
            MirrorOutcome(
                authority_ref=str(_local_authority_ref()),
                status="committed",
                conversation_id=str(conversation_id),
                event_ids=[event_id] if event_id else [],
                retry_required=False,
            )
        ]

    def enroll_agent(self, card: AgentCard) -> EnrollmentResult:
        return self._remember_enrollment(self.store.enroll(card.model_dump(mode="json")))

    def renew_enrollment(self, agent_id: AgentId, card: AgentCard) -> EnrollmentResult:
        token = self._token_for_agent(agent_id)
        result = self.store.register(
            token,
            {
                "agent_card": card.model_dump(mode="json"),
                "connectivity_state": "connected",
                "current_capacity": card.current_capacity,
                "max_capacity": card.max_capacity,
            },
        )
        return EnrollmentResult(
            agent_id=result.agent_id,
            agent_token=token,
            slug=result.slug,
            poll_cursor="0",
        )

    def disconnect_agent(self, agent_id: AgentId) -> AgentRecord:
        token = self._token_for_agent(agent_id)
        return self.store.deregister(token)

    def register_agent(
        self,
        agent_token: str,
        payload: AgentRegisterRequest | dict,
    ) -> HealthSummary:
        request = (
            payload
            if isinstance(payload, AgentRegisterRequest)
            else validated_register_payload(payload)
        )
        agent = self.store.register(agent_token, request)
        agent_id = str(agent.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        return HealthSummary(
            agent=agent,
            collections_changed=True,
            server_time=utcnow_iso(),
        )

    def heartbeat_agent(
        self,
        agent_token: str,
        payload: AgentHeartbeatRequest | dict,
    ) -> HealthSummary:
        request = (
            payload
            if isinstance(payload, AgentHeartbeatRequest)
            else validated_heartbeat_payload(payload)
        )
        result = self.store.heartbeat(agent_token, request)
        agent_id = str(result.agent.agent_id or "") if result.agent is not None else ""
        self.remember_agent_token(agent_id, agent_token)
        return result

    def search_agents_for_agent(
        self,
        agent_token: str,
        query: AgentDiscoveryQuery | dict,
    ) -> list[AgentRecord]:
        typed_query = (
            query
            if isinstance(query, AgentDiscoveryQuery)
            else AgentDiscoveryQuery.model_validate(query)
        )
        self.store.assert_agent_scope(agent_token, {"coordination", "full"})
        self.store.heartbeat(agent_token, {"connectivity_state": "connected"})
        return self.search_agents(typed_query)

    def submit_routed_task_for_agent(
        self,
        agent_token: str,
        task: RoutedTaskRequest | dict,
    ) -> TaskRecord:
        self.store.assert_agent_scope(agent_token, {"coordination", "full"})
        self.store.heartbeat(agent_token, {"connectivity_state": "connected"})
        typed_task = (
            task
            if isinstance(task, RoutedTaskRequest)
            else validated_routed_task_request(task)
        )
        return self.submit_routed_task(typed_task)

    def update_routed_task_for_agent(
        self,
        agent_token: str,
        update: RoutedTaskUpdate | dict,
    ) -> TaskRecord:
        agent_row = self.store.resolve_agent_for_token(agent_token)
        if agent_row is None:
            raise PermissionError("unknown agent token")
        agent_id = str(agent_row.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        typed_update = (
            update
            if isinstance(update, RoutedTaskUpdate)
            else RoutedTaskUpdate.model_validate(update)
        )
        return self.update_routed_task(typed_update)

    def report_routed_result_for_agent(
        self,
        agent_token: str,
        result: RoutedTaskResult | dict,
    ) -> TaskRecord:
        agent_row = self.store.resolve_agent_for_token(agent_token)
        if agent_row is None:
            raise PermissionError("unknown agent token")
        agent_id = str(agent_row.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        typed_result = (
            result
            if isinstance(result, RoutedTaskResult)
            else RoutedTaskResult.model_validate(result)
        )
        return self.report_routed_result(typed_result)

    def poll_for_agent(
        self,
        agent_token: str,
        *,
        cursor: int,
        limit: int,
    ) -> DeliveryPollResult:
        agent_row = self.store.resolve_agent_for_token(agent_token)
        if agent_row is None:
            raise PermissionError("unknown agent token")
        agent_id = str(agent_row.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        result = self.store.poll(agent_token, cursor=cursor, limit=limit)
        for delivery in result.deliveries:
            self._delivery_targets[str(delivery.delivery_id)] = agent_id
        return result

    def ack_for_agent(
        self,
        agent_token: str,
        *,
        delivery_ids: list[str],
        classification: str | None,
    ) -> AckResult:
        agent_row = self.store.resolve_agent_for_token(agent_token)
        if agent_row is None:
            raise PermissionError("unknown agent token")
        agent_id = str(agent_row.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        result = AckResult.model_validate(
            self.store.ack(
                agent_token,
                delivery_ids=delivery_ids,
                classification=str(classification or "accepted"),
            )
        )
        for delivery_id in delivery_ids:
            self._delivery_targets.pop(str(delivery_id), None)
        return result

    def report_management_result_for_agent(
        self,
        agent_token: str,
        request_id: str,
        payload: ManagementResult,
    ) -> ManagementResult:
        agent_row = self.store.resolve_agent_for_token(agent_token)
        if agent_row is None:
            raise PermissionError("unknown agent token")
        agent_id = str(agent_row.agent_id or "")
        self.remember_agent_token(agent_id, agent_token)
        return self.store.report_management_result(agent_token, request_id, payload)

    def disconnect_agent_token(self, agent_token: str) -> AgentRecord:
        result = self.store.deregister(agent_token)
        agent_id = str(result.agent_id or "")
        if agent_id:
            self._agent_tokens.pop(agent_id, None)
        return result

    def poll_deliveries(self, agent_id: AgentId, cursor: int) -> list[DeliveryRecord]:
        token = self._token_for_agent(agent_id)
        result = self.store.poll(token, cursor=cursor, limit=100)
        deliveries = list(result.deliveries)
        for delivery in deliveries:
            self._delivery_targets[str(delivery.delivery_id)] = str(agent_id)
        return deliveries

    def ack_delivery(self, delivery_id: DeliveryId) -> AckResult:
        agent_id = self._delivery_targets.get(str(delivery_id))
        if not agent_id:
            raise KeyError(f"Unknown delivery target for {delivery_id}")
        token = self._token_for_agent(agent_id)
        result = AckResult.model_validate(
            self.store.ack(token, delivery_ids=[str(delivery_id)], classification="accepted")
        )
        self._delivery_targets.pop(str(delivery_id), None)
        return result

    def fail_delivery(self, delivery_id: DeliveryId, reason: str) -> AckResult:
        del reason
        agent_id = self._delivery_targets.get(str(delivery_id))
        if not agent_id:
            raise KeyError(f"Unknown delivery target for {delivery_id}")
        token = self._token_for_agent(agent_id)
        result = AckResult.model_validate(
            self.store.ack(token, delivery_ids=[str(delivery_id)], classification="rejected")
        )
        self._delivery_targets.pop(str(delivery_id), None)
        return result
