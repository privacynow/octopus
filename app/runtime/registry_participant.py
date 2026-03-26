"""Runtime-side registry participant implementation over existing control-plane services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.agents.state import load_runtime_registry_connection_state
from app.config import BotConfig
from app.runtime.services import ControlPlaneServices
from octopus_sdk.agent_directory import AgentSearchResult, AuthorityResolution
from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    ApproveDelegationActionPayload,
    AuthorityId,
    CancelDelegationActionPayload,
    ConnectivityState,
    ConversationId,
    CoordinationActionEnvelope,
    CoordinationActionResult,
    DelegateTasksActionPayload,
    DelegationIntent,
    DirectAssignActionPayload,
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


def _is_live_connectivity_state(connectivity_state: str) -> bool:
    return str(connectivity_state or "") in {"connected", "degraded"}


def _registry_scope(config: BotConfig, registry_id: str) -> str:
    for registry in config.agent_registries:
        if registry.registry_id == registry_id:
            return registry.registry_scope
    return "full"


def _state_for_authority(config: BotConfig, authority_ref: str):
    registry_id = registry_id_from_authority_ref(str(authority_ref))
    return load_runtime_registry_connection_state(
        config.data_dir,
        registry_id,
        registry_scope=_registry_scope(config, registry_id),
    )


def _first_coordination_authority(config: BotConfig, *, require_live: bool = False) -> str:
    for registry in config.agent_registries:
        if registry.registry_scope not in {"coordination", "full"}:
            continue
        state = load_runtime_registry_connection_state(
            config.data_dir,
            registry.registry_id,
            registry_scope=registry.registry_scope,
        )
        if state.agent_id:
            if require_live and not _is_live_connectivity_state(str(state.connectivity_state or "")):
                continue
            return f"registry:{registry.registry_id}"
    return ""


def _coordination_unavailable_error(config: BotConfig) -> RuntimeError:
    has_coordination_registry = any(
        registry.registry_scope in {"coordination", "full"}
        for registry in config.agent_registries
    )
    if not has_coordination_registry:
        return RuntimeError(
            "Delegation unavailable: no coordination-capable registry connections are configured."
        )
    return RuntimeError(
        "Delegation unavailable: registry connectivity is degraded."
    )


class _ParticipantEnrollment(RegistryParticipant):
    def __init__(self, config: BotConfig) -> None:
        self._config = config

    async def enroll(self) -> EnrollmentResult:
        authority_ref = _first_coordination_authority(self._config)
        if not authority_ref:
            raise RuntimeError("Delegation unavailable: this bot is not enrolled in a coordination-capable registry.")
        state = _state_for_authority(self._config, authority_ref)
        return EnrollmentResult(
            agent_id=state.agent_id,
            agent_token=state.agent_token,
            slug=state.registered_slug,
            poll_cursor=state.poll_cursor,
        )

    async def heartbeat(self) -> None:
        return None

    def is_enrolled(self, authority: AuthorityId) -> bool:
        return bool(_state_for_authority(self._config, str(authority)).agent_id)

    def local_agent_id(self, authority: AuthorityId) -> str:
        return _state_for_authority(self._config, str(authority)).agent_id


class _ParticipantHealth(RegistryParticipantHealth):
    def __init__(self, config: BotConfig) -> None:
        self._config = config

    def enrollment_state(self) -> dict[AuthorityId, EnrollmentResult]:
        state: dict[AuthorityId, EnrollmentResult] = {}
        for registry in self._config.agent_registries:
            authority_ref = AuthorityId(f"registry:{registry.registry_id}")
            current = load_runtime_registry_connection_state(
                self._config.data_dir,
                registry.registry_id,
                registry_scope=registry.registry_scope,
            )
            state[authority_ref] = EnrollmentResult(
                agent_id=current.agent_id,
                agent_token=current.agent_token,
                slug=current.registered_slug,
                poll_cursor=current.poll_cursor,
            )
        return state

    def connectivity_state(self, authority: AuthorityId) -> ConnectivityState:
        return ConnectivityState(_state_for_authority(self._config, str(authority)).connectivity_state)

    def current_local_agent_ids(self) -> dict[AuthorityId, str]:
        return {
            AuthorityId(f"registry:{registry.registry_id}"): load_runtime_registry_connection_state(
                self._config.data_dir,
                registry.registry_id,
                registry_scope=registry.registry_scope,
            ).agent_id
            for registry in self._config.agent_registries
        }

    def live_local_agent_ids(self) -> dict[AuthorityId, str]:
        live: dict[AuthorityId, str] = {}
        for registry in self._config.agent_registries:
            authority_ref = AuthorityId(f"registry:{registry.registry_id}")
            state = load_runtime_registry_connection_state(
                self._config.data_dir,
                registry.registry_id,
                registry_scope=registry.registry_scope,
            )
            if not state.agent_id:
                continue
            if str(state.connectivity_state or "") not in {"connected", "degraded"}:
                continue
            live[authority_ref] = state.agent_id
        return live


class _ParticipantDiscovery(RegistryDiscovery):
    def __init__(self, config: BotConfig, control_plane: ControlPlaneServices) -> None:
        self._config = config
        self._control_plane = control_plane

    async def search_agents(self, *, query: AgentDiscoveryQuery) -> AgentSearchResult:
        if not _first_coordination_authority(self._config, require_live=True):
            return AgentSearchResult(status="unavailable")
        return await self._control_plane.agent_directory.search_agents(query=query)

    async def resolve_authority(self, *, selector: TargetSelector) -> AuthorityId:
        if not _first_coordination_authority(self._config, require_live=True):
            raise _coordination_unavailable_error(self._config)
        if selector.kind == "agent":
            resolution = await self._control_plane.agent_directory.resolve_target_authority(
                target_agent_id=selector.preferred_agent_id or selector.value,
            )
            if resolution.status != "resolved" or not resolution.authority_ref:
                raise RuntimeError("Target authority could not be resolved.")
            return AuthorityId(resolution.authority_ref)
        search = await self._control_plane.agent_directory.search_agents(
            query=AgentDiscoveryQuery(
                role=selector.value if selector.kind == "role" else "",
                capabilities=[selector.value] if selector.kind == "capability" else [],
                required_state="connected",
            )
        )
        if not search.agents:
            raise RuntimeError("Target authority could not be resolved.")
        return AuthorityId(search.agents[0].authority_ref)


class _ParticipantMirror(RegistryConversationMirror):
    def __init__(self, control_plane: ControlPlaneServices) -> None:
        self._control_plane = control_plane

    async def create_conversation(
        self,
        conversation_key: TransportConversationKey,
        *,
        origin_channel: str,
        external_ref: ExternalConversationRef,
    ) -> ConversationId:
        conversation_id = await self._control_plane.conversation_projection.create_conversation(
            target_agent_id=str(conversation_key),
            origin_channel=origin_channel,
            external_conversation_ref=str(external_ref),
            title=str(external_ref),
        )
        return ConversationId(conversation_id)

    async def publish_events(
        self,
        conversation_id: ConversationId,
        events: list[ConversationEvent],
    ) -> list[MirrorOutcome]:
        await self._control_plane.conversation_projection.publish_events(
            conversation_id=str(conversation_id),
            events=events,
        )
        return [MirrorOutcome(status="submitted", conversation_id=str(conversation_id))]

    async def submit_message(
        self,
        conversation_id: ConversationId,
        *,
        text: str,
        actor: TransportActorKey,
    ) -> list[MirrorOutcome]:
        del actor
        await self._control_plane.conversation_projection.add_message(
            conversation_id=str(conversation_id),
            text=text,
        )
        return [MirrorOutcome(status="submitted", conversation_id=str(conversation_id))]

    async def submit_action(
        self,
        conversation_id: ConversationId,
        *,
        envelope: CoordinationActionEnvelope,
    ) -> list[MirrorOutcome]:
        await self._control_plane.conversation_projection.submit_action(
            conversation_id=str(conversation_id),
            envelope=envelope,
        )
        return [MirrorOutcome(status="submitted", conversation_id=str(conversation_id))]


class _ParticipantCoordination(RegistryCoordination):
    def __init__(self, config: BotConfig, control_plane: ControlPlaneServices) -> None:
        self._config = config
        self._control_plane = control_plane

    def _projection_target_agent_id(self) -> str:
        authority_ref = _first_coordination_authority(self._config, require_live=True)
        if not authority_ref:
            return ""
        return _state_for_authority(self._config, authority_ref).agent_id

    def _require_live_coordination_authority(self) -> None:
        if not _first_coordination_authority(self._config, require_live=True):
            raise _coordination_unavailable_error(self._config)

    async def ensure_conversation_id(
        self,
        conversation_key: TransportConversationKey,
        *,
        conversation_ref: str,
        origin_channel: str,
        external_ref: ExternalConversationRef,
        title: str,
    ) -> ConversationId:
        del conversation_key
        if conversation_ref.startswith("registry:"):
            parts = conversation_ref.split(":")
            return ConversationId(parts[-1])
        target_agent_id = self._projection_target_agent_id()
        if not target_agent_id:
            raise _coordination_unavailable_error(self._config)
        conversation_id = await self._control_plane.conversation_projection.create_conversation(
            target_agent_id=target_agent_id,
            origin_channel=origin_channel,
            external_conversation_ref=str(external_ref),
            title=title,
        )
        return ConversationId(conversation_id)

    async def direct_assign(
        self,
        conversation_id: ConversationId,
        *,
        selector: TargetSelector,
        title: str,
        instructions: str,
        message_text: str = "",
    ) -> CoordinationActionResult:
        envelope = CoordinationActionEnvelope(
            action_id=uuid4().hex,
            action="direct_assign",
            payload=DirectAssignActionPayload(
                selector=selector,
                title=title,
                instructions=instructions,
                message_text=message_text,
            ).model_dump(exclude_unset=True),
        )
        self._require_live_coordination_authority()
        return await self._control_plane.conversation_projection.submit_action(
            conversation_id=str(conversation_id),
            envelope=envelope,
        )

    async def delegate_tasks(
        self,
        conversation_id: ConversationId,
        *,
        intent: DelegationIntent,
    ) -> CoordinationActionResult:
        envelope = CoordinationActionEnvelope(
            action_id=uuid4().hex,
            action="delegate_tasks",
            payload=DelegateTasksActionPayload(
                title=intent.title,
                resume_instruction=intent.resume_instruction,
                tasks=intent.tasks,
            ).model_dump(exclude_unset=True),
        )
        self._require_live_coordination_authority()
        return await self._control_plane.conversation_projection.submit_action(
            conversation_id=str(conversation_id),
            envelope=envelope,
        )

    async def approve_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult:
        envelope = CoordinationActionEnvelope(
            action_id=uuid4().hex,
            action="approve_delegation",
            payload=ApproveDelegationActionPayload(proposal_id=proposal_id).model_dump(),
        )
        self._require_live_coordination_authority()
        return await self._control_plane.conversation_projection.submit_action(
            conversation_id=str(conversation_id),
            envelope=envelope,
        )

    async def cancel_delegation(
        self,
        conversation_id: ConversationId,
        *,
        proposal_id: str,
    ) -> CoordinationActionResult:
        envelope = CoordinationActionEnvelope(
            action_id=uuid4().hex,
            action="cancel_delegation",
            payload=CancelDelegationActionPayload(proposal_id=proposal_id).model_dump(),
        )
        self._require_live_coordination_authority()
        return await self._control_plane.conversation_projection.submit_action(
            conversation_id=str(conversation_id),
            envelope=envelope,
        )

    async def preview_target_resolution(self, selector: TargetSelector) -> TargetResolutionPreview:
        if not _first_coordination_authority(self._config, require_live=True):
            return TargetResolutionPreview(
                status="unavailable",
                error="registry_unreachable",
            )
        if selector.kind == "agent":
            result: AuthorityResolution = await self._control_plane.agent_directory.resolve_target_authority(
                target_agent_id=selector.preferred_agent_id or selector.value,
            )
            return TargetResolutionPreview(
                authority_ref=result.authority_ref,
                target_label=selector.preferred_agent_id or selector.value,
                status=result.status,
                error=result.error,
            )
        search: AgentSearchResult = await self._control_plane.agent_directory.search_agents(
            query=AgentDiscoveryQuery(
                role=selector.value if selector.kind == "role" else "",
                capabilities=[selector.value] if selector.kind == "capability" else [],
                required_state="connected",
            )
        )
        first = search.agents[0] if search.agents else None
        return TargetResolutionPreview(
            authority_ref=first.authority_ref if first else "",
            target_label=selector.value,
            status="resolved" if first else search.status,
        )


@dataclass(frozen=True)
class ControlPlaneRegistryParticipant(RegistryParticipantImplementation):
    enrollment: RegistryParticipant
    mirror: RegistryConversationMirror
    coordination: RegistryCoordination
    discovery: RegistryDiscovery
    health: RegistryParticipantHealth


def build_control_plane_registry_participant(
    config: BotConfig,
    control_plane: ControlPlaneServices,
) -> RegistryParticipantImplementation:
    return ControlPlaneRegistryParticipant(
        enrollment=_ParticipantEnrollment(config),
        mirror=_ParticipantMirror(control_plane),
        coordination=_ParticipantCoordination(config, control_plane),
        discovery=_ParticipantDiscovery(config, control_plane),
        health=_ParticipantHealth(config),
    )


def build_noop_registry_participant() -> RegistryParticipantImplementation:
    return ControlPlaneRegistryParticipant(
        enrollment=_NoOpEnrollment(),
        mirror=_NoOpMirror(),
        coordination=_NoOpCoordination(),
        discovery=_NoOpDiscovery(),
        health=_NoOpHealth(),
    )
