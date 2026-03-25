"""Registry conversation/task channels."""

from __future__ import annotations

from typing import Any

from app.agents.registry_capabilities import (
    registry_authority_capabilities,
    registry_authority_ref,
    registry_id_from_authority_ref,
)
from octopus_sdk.config import RegistryConnectionConfig
from app.agents.state import runtime_registry_agent_id
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import binding_external_id_for_ref, parse_registry_ref
from app.config import BotConfig
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import build_control_plane_directory
from octopus_sdk.channels import Channel, ChannelDescriptor
from octopus_sdk.egress import ChannelEgress
from app.runtime.channel_dispatcher import ChannelDispatcher
from app.runtime.services import BotServices, build_bus_bot_services, build_noop_bot_services


def _services_for_registry(
    bus: ControlPlaneBus,
    *,
    registry: RegistryConnectionConfig,
    authority_capabilities: dict[str, set[str]],
    config: BotConfig,
) -> BotServices:
    authority_ref = registry_authority_ref(registry.registry_id)
    capabilities = authority_capabilities.get(authority_ref, set())
    if not capabilities:
        return build_noop_bot_services()
    directory = build_control_plane_directory({authority_ref: set(capabilities)})

    def _agent_id_for_authority(ref: str) -> str:
        try:
            rid = registry_id_from_authority_ref(ref)
        except ValueError:
            return ""
        return runtime_registry_agent_id(
            config.data_dir,
            rid,
            registry_scope=registry.registry_scope,
        )

    return build_bus_bot_services(
        bus, directory, agent_id_for_authority=_agent_id_for_authority,
    )


class _RegistryChannel(Channel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        ref_kind: str,
        descriptor: ChannelDescriptor,
        services: BotServices,
    ) -> None:
        self._config = config
        self._registry = registry
        self._ref_kind = ref_kind
        self._descriptor = descriptor
        self._services = services

    @property
    def channel_id(self) -> str:
        return f"registry:{self._registry.registry_id}:{self._ref_kind}"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return self._descriptor

    def ref_prefix(self) -> str:
        return f"registry:{self._registry.registry_id}:{self._ref_kind}:"

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
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
            descriptor=ChannelDescriptor(
                channel_type="registry",
                display_name=f"Registry ({registry.registry_id})",
                supports_multiple=True,
                requires_polling=True,
                trust_tier="trusted",
                contributes_channel_capability=True,
                accepts_channel_input=True,
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
            descriptor=ChannelDescriptor(
                channel_type="registry",
                display_name=f"Registry Tasks ({registry.registry_id})",
                supports_multiple=True,
                requires_polling=True,
                trust_tier="trusted",
                contributes_channel_capability=False,
                accepts_channel_input=False,
                supports_conversation_binding=False,
                supports_timeline=False,
            ),
            services=services,
        )


def register_registry_channels(
    config: BotConfig,
    registries: tuple[RegistryConnectionConfig, ...],
    dispatcher: ChannelDispatcher,
) -> None:
    authority_capabilities = registry_authority_capabilities(registries)
    bus = ControlPlaneBus(config.data_dir)
    for registry in registries:
        services = _services_for_registry(
            bus,
            registry=registry,
            authority_capabilities=authority_capabilities,
            config=config,
        )
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
