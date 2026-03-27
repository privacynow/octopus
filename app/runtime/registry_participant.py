"""Runtime-side registry participant implementation over existing control-plane services."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.registry_errors import registry_error_detail
from app.agents.registry_capabilities import registry_id_from_authority_ref
from app.agents.state import (
    RegistryConnectionState,
    load_runtime_registry_connection_state,
    save_registry_connection_state,
)
from app.config import BotConfig
from app.runtime.bot_services import ControlPlaneServices
from app.runtime_health import (
    RuntimeHealthRegistryProjector,
    RuntimeHealthProjector,
    RuntimeHealthProvider,
)
from octopus_sdk.config import RegistryConnectionConfig
from octopus_sdk.identity import bot_identity
from octopus_sdk.agent_directory import AgentSearchResult, AuthorityResolution
from octopus_sdk.events import ConversationEvent
from octopus_sdk.registry.models import (
    AgentDiscoveryQuery,
    AgentCard,
    DeliveryPollResult,
    EnrollmentResult,
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
    ExternalConversationRef,
    MirrorOutcome,
    RuntimeHealthPayload,
    TargetResolutionPreview,
    TargetSelector,
    TransportActorKey,
    TransportConversationKey,
    utcnow_iso,
)
from octopus_sdk.registry_participant import (
    RegistryConversationMirror,
    RegistryCoordination,
    RegistryDiscovery,
    RegistryParticipant,
    RegistryParticipantHealth,
    RegistryParticipantImplementation,
)


log = logging.getLogger(__name__)


def _registered_card_hash(card: AgentCard) -> str:
    payload = card.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AgentRuntime:
    """Maintains bot identity and heartbeat against the central registry."""

    def __init__(
        self,
        config: BotConfig,
        *,
        delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None = None,
        runtime_health_provider: RuntimeHealthProvider | None = None,
        runtime_health_projector: RuntimeHealthProjector[RuntimeHealthPayload] | None = None,
        provider=None,
        registry: RegistryConnectionConfig | None = None,
        channel_capabilities_resolver: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.config = config
        self._delivery_handler = delivery_handler
        if registry is None and config.agent_mode == "registry":
            raise ValueError("AgentRuntime requires an explicit registry connection in registry mode")
        self._registry = registry
        self._channel_capabilities_resolver = channel_capabilities_resolver
        if self._registry is None:
            self._state = RegistryConnectionState(registry_id="", registry_scope="full")
        else:
            self._state = load_runtime_registry_connection_state(
                config.data_dir,
                self._registry.registry_id,
                registry_scope=self._registry.registry_scope,
            )
        self._runtime_health_provider = runtime_health_provider
        self._runtime_health_projector = runtime_health_projector or RuntimeHealthRegistryProjector()
        self._provider = provider

    @property
    def state(self) -> RegistryConnectionState:
        return self._state

    def _channel_capabilities(self) -> tuple[str, ...]:
        if self._channel_capabilities_resolver is not None:
            return self._channel_capabilities_resolver()
        channels: list[str] = []
        if self.config.telegram_token:
            channels.append("telegram")
        if any(registry.registry_scope in {"channel", "full"} for registry in self.config.agent_registries):
            channels.append("registry")
        return tuple(channels)

    def _configured_registry_url(self) -> str:
        if self._registry is None:
            return ""
        return self._registry.url

    def _configured_enroll_token(self) -> str:
        if self._registry is None:
            return ""
        return self._registry.enroll_token

    def requested_card(self) -> AgentCard:
        capabilities = self._effective_capabilities()
        return AgentCard(
            display_name=self.config.agent_display_name or self.config.instance,
            slug=self._state.registered_slug or self.config.agent_slug,
            role=self.config.agent_role or self.config.role,
            registry_scope=self._state.registry_scope or (self._registry.registry_scope if self._registry is not None else "full"),
            capabilities=list(capabilities),
            tags=list(self.config.agent_tags),
            description=self.config.agent_description,
            provider=self.config.provider_name,
            mode=self.config.agent_mode,
            connectivity_state=self._state.connectivity_state,
            current_capacity=0,
            max_capacity=1,
            channel_capabilities=list(self._channel_capabilities()),
            version="",
            bot_key=bot_identity(self.config.data_dir),
        )

    def _effective_capabilities(self) -> tuple[str, ...]:
        return self.config.agent_capabilities

    def _client(self) -> AgentRegistryClient:
        return AgentRegistryClient(
            self._configured_registry_url(),
            agent_token=self._state.agent_token,
        )

    async def _runtime_health_payload(self) -> RuntimeHealthPayload | None:
        if self._runtime_health_provider is None or self._provider is None:
            return None
        report = await self._runtime_health_provider.collect(
            self.config,
            self._provider,
            caller_is_bot=True,
            session_context=None,
        )
        return self._runtime_health_projector.project(report)

    def _save_state(self) -> None:
        if self._registry is None:
            return
        save_registry_connection_state(self.config.data_dir, self._state)

    def _mark_state(
        self,
        connectivity_state: str,
        *,
        error: str = "",
        detail: str = "",
    ) -> None:
        self._state.connectivity_state = connectivity_state
        self._state.last_error = error
        self._state.last_error_detail = detail
        if connectivity_state == "connected":
            self._state.last_successful_contact_at = utcnow_iso()
        self._save_state()

    async def sync_once(self) -> str:
        if self.config.agent_mode == "standalone":
            self._mark_state("standalone")
            return "standalone"

        if not self._configured_registry_url():
            self._mark_state(
                "degraded",
                error="registry_url_missing",
                detail="Registry URL not configured.",
            )
            return "degraded"

        try:
            if not self._state.agent_id or not self._state.agent_token:
                enroll_token = self._configured_enroll_token()
                if not enroll_token:
                    self._mark_state(
                        "degraded",
                        error="registry_enroll_token_missing",
                        detail="Registry enrollment token not configured.",
                    )
                    return "degraded"
                enroll = await AgentRegistryClient(self._configured_registry_url()).enroll(
                    self.requested_card(),
                    enroll_token,
                )
                enroll = EnrollmentResult.model_validate(enroll)
                self._state.agent_id = enroll.agent_id
                self._state.agent_token = enroll.agent_token
                self._state.registered_slug = enroll.slug or self.config.agent_slug
                self._state.poll_cursor = enroll.poll_cursor or "0"
                self._save_state()

            card = self.requested_card().model_copy(
                update={
                    "slug": self._state.registered_slug or self.config.agent_slug,
                    "connectivity_state": "connected",
                }
            )
            client = self._client()
            card_hash = _registered_card_hash(card)
            if self._state.registered_card_hash != card_hash:
                await client.register(
                    card,
                    connectivity_state="connected",
                    current_capacity=0,
                    max_capacity=1,
                )
                self._state.registered_card_hash = card_hash
                self._save_state()
            runtime_health_payload = None
            try:
                runtime_health_payload = await self._runtime_health_payload()
            except Exception:
                log.exception(
                    "Runtime health collection failed for %s; continuing without mirrored health",
                    self.config.instance,
                )
            heartbeat_kwargs = {
                "connectivity_state": "connected",
                "current_capacity": 0,
                "max_capacity": 1,
            }
            if runtime_health_payload is not None:
                heartbeat_kwargs["runtime_health"] = runtime_health_payload
            await client.heartbeat(**heartbeat_kwargs)
        except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
            if isinstance(exc, RegistryClientError):
                error_code = exc.error_code
                detail = exc.operator_detail
            elif isinstance(exc, asyncio.TimeoutError):
                error_code = "registry_timeout"
                detail = "Registry sync timed out."
            else:
                error_code = "registry_unreachable"
                detail = f"Registry sync failed with {exc.__class__.__name__}."
            log.warning(
                "Agent registry sync degraded for %s: %s",
                self.config.instance,
                registry_error_detail(error_code, detail),
            )
            self._mark_state("degraded", error=error_code, detail=detail)
            return "degraded"

        self._mark_state("connected")
        return "connected"

    async def poll_once(self, *, kind_filter: Sequence[str] | None = None) -> int:
        if self._delivery_handler is None or self._state.connectivity_state != "connected":
            return 0
        client = self._client()
        poll_kwargs: dict[str, object] = {
            "cursor": self._state.poll_cursor or "0",
            "limit": 20,
            "wait_seconds": 0,
        }
        if kind_filter is not None:
            poll_kwargs["kind_filter"] = tuple(kind_filter)
        result = await client.poll(
            **poll_kwargs,
        )
        result = DeliveryPollResult.model_validate(result)
        deliveries = list(result.deliveries)
        if not deliveries:
            self._state.poll_cursor = str(result.next_cursor or self._state.poll_cursor or "0")
            self._save_state()
            return 0

        accepted: list[str] = []
        rejected: list[str] = []
        retry_later: list[str] = []
        for delivery in deliveries:
            delivery_payload = delivery.model_dump(mode="json")
            delivery_id = str(delivery_payload.get("delivery_id", ""))
            try:
                classification = await self._delivery_handler(delivery_payload)
            except Exception:
                log.exception(
                    "Agent delivery handler failed for %s on %s",
                    self.config.instance,
                    delivery_id,
                )
                rejected.append(delivery_id)
                continue
            if classification == "accepted":
                accepted.append(delivery_id)
            elif classification == "retry_later":
                retry_later.append(delivery_id)
            else:
                rejected.append(delivery_id)
        if accepted:
            await client.ack(accepted, classification="accepted")
        if rejected:
            await client.ack(rejected, classification="rejected")
        if retry_later:
            await client.ack(retry_later, classification="retry_later")
        self._state.poll_cursor = str(result.next_cursor or self._state.poll_cursor or "0")
        self._save_state()
        return len(deliveries)

    async def run_forever(
        self,
        stop_event: asyncio.Event,
        *,
        kind_filter: Sequence[str] | None = None,
    ) -> None:
        import random

        base = max(1.0, self.config.agent_poll_interval_seconds)
        max_backoff = min(300.0, base * 32)
        current_backoff = base
        while not stop_event.is_set():
            state = await self.sync_once()
            if state == "connected":
                try:
                    if kind_filter is None:
                        await self.poll_once()
                    else:
                        await self.poll_once(kind_filter=kind_filter)
                except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
                    if isinstance(exc, RegistryClientError):
                        error_code = exc.error_code
                        detail = exc.operator_detail
                    elif isinstance(exc, asyncio.TimeoutError):
                        error_code = "registry_timeout"
                        detail = "Registry poll timed out."
                    else:
                        error_code = "registry_unreachable"
                        detail = f"Registry poll failed with {exc.__class__.__name__}."
                    log.warning(
                        "Agent registry poll degraded for %s: %s",
                        self.config.instance,
                        registry_error_detail(error_code, detail),
                    )
                    self._mark_state("degraded", error=error_code, detail=detail)
                except Exception:
                    log.exception("Unexpected registry poll failure for %s", self.config.instance)
            if self._state.connectivity_state == "connected":
                current_backoff = base
            else:
                current_backoff = min(current_backoff * 2, max_backoff)
            sleep_time = random.uniform(0, current_backoff)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                continue


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
