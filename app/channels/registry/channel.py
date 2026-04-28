"""Registry conversation/task channels."""

from __future__ import annotations

from app.agents.registry_projection_interfaces import (
    registry_projection_interfaces_by_implementation_ref,
)
from octopus_sdk.config import RegistryConnectionConfig
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import binding_external_id_for_ref, parse_registry_ref
from app.config import BotConfig
from app.runtime.services import BotServices
from octopus_sdk.transport_dispatcher import TransportDispatcher
from octopus_sdk.config import BotConfigBase
from octopus_sdk.identity import conversation_key_for_ref, parse_actor_key
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportIdentityResolver
from octopus_sdk.transport import TransportImplementation


class _RegistryIdentityResolver(TransportIdentityResolver):
    def conversation_key(self, raw_conversation_id: object) -> str:
        return conversation_key_for_ref(str(raw_conversation_id).strip())

    def actor_key(self, raw_actor_id: object) -> str:
        return parse_actor_key(str(raw_actor_id).strip())

    def external_conversation_ref(self, raw_conversation_id: object) -> str:
        return binding_external_id_for_ref(str(raw_conversation_id).strip())


class _RegistryChannel(TransportImplementation):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        ref_kind: str,
        descriptor: TransportDescriptor,
        services: BotServices,
    ) -> None:
        self._config = config
        self._registry = registry
        self._ref_kind = ref_kind
        self._descriptor = descriptor
        self._services = services

    @property
    def transport_id(self) -> str:
        return f"registry:{self._registry.registry_id}:{self._ref_kind}"

    @property
    def descriptor(self) -> TransportDescriptor:
        return self._descriptor

    @property
    def identity(self) -> TransportIdentityResolver:
        return _RegistryIdentityResolver()

    def ref_prefix(self) -> str:
        return f"registry:{self._registry.registry_id}:{self._ref_kind}:"

    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        del config
        parsed = parse_registry_ref(conversation_ref)
        external_id = str(kw.get("external_id", "") or "").strip() or binding_external_id_for_ref(conversation_ref)
        routed_task_id = str(kw.get("routed_task_id", ""))
        if self._ref_kind == "task" and not routed_task_id:
            routed_task_id = external_id
        if self._ref_kind == "task" and parsed is not None and not external_id:
            external_id = parsed[2]
        return RegistryChannelEgress(
            self._config,
            conversation_ref=conversation_ref,
            registry_id=self._registry.registry_id,
            routed_task_id=routed_task_id,
            authority_ref=str(kw.get("authority_ref", "")),
            title=str(kw.get("title", "")),
            output_log=kw.get("output_log"),
            external_id=external_id,
            services=self._services,
        )


class RegistryConversationChannel(_RegistryChannel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        services: BotServices,
    ) -> None:
        super().__init__(
            config,
            registry,
            ref_kind="conversation",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name=f"Registry ({registry.registry_id})",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                report_in_agent_status=True,
                accepts_transport_input=True,
                supports_conversation_binding=True,
                supports_timeline=True,
            ),
            services=services,
        )


class RegistryTaskChannel(_RegistryChannel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        services: BotServices,
    ) -> None:
        super().__init__(
            config,
            registry,
            ref_kind="task",
            descriptor=TransportDescriptor(
                transport_type="registry",
                display_name=f"Registry Tasks ({registry.registry_id})",
                supports_multiple=True,
                inbound_model="delivery",
                trust_tier="trusted",
                report_in_agent_status=False,
                accepts_transport_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            services=services,
        )


def register_registry_channels(
    config: BotConfig,
    registries: tuple[RegistryConnectionConfig, ...],
    dispatcher: TransportDispatcher,
    *,
    services: BotServices,
) -> None:
    projection_interfaces_by_implementation = registry_projection_interfaces_by_implementation_ref(registries)
    for registry in registries:
        implementation_ref = f"registry:{registry.registry_id}"
        projection_interfaces = projection_interfaces_by_implementation.get(implementation_ref, set())
        if not projection_interfaces:
            continue
        if registry.registry_scope in {"channel", "full"}:
            dispatcher.register(
                RegistryConversationChannel(
                    config,
                    registry,
                    services=services,
                )
            )
        if registry.registry_scope in {"coordination", "full"}:
            dispatcher.register(
                RegistryTaskChannel(
                    config,
                    registry,
                    services=services,
                )
            )
