"""Registry conversation/task channels."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.client import AgentRegistryClient
from app.agents.types import RegistryConnectionConfig
from app.channels.registry.egress import RegistryChannelEgress
from app.channels.registry.refs import parse_registry_ref, registry_ref_external_id
from app.config import BotConfig
from app.ports.channel import Channel, ChannelDescriptor
from app.ports.egress import ChannelEgress
from app.runtime.channel_dispatcher import ChannelDispatcher


class _RegistryChannel(Channel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        ref_kind: str,
        descriptor: ChannelDescriptor,
        registry_client_factory: Callable[[], AgentRegistryClient | None] | None = None,
    ) -> None:
        self._config = config
        self._registry = registry
        self._ref_kind = ref_kind
        self._descriptor = descriptor
        self._registry_client_factory = registry_client_factory

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
        external_id = registry_ref_external_id(conversation_ref)
        routed_task_id = str(kw.get("routed_task_id", ""))
        if self._ref_kind == "task" and not routed_task_id:
            routed_task_id = external_id
        if parsed is not None:
            external_id = parsed[2]
        return RegistryChannelEgress(
            self._config,
            conversation_ref=conversation_ref,
            registry_id=self._registry.registry_id,
            routed_task_id=routed_task_id,
            title=str(kw.get("title", "")),
            output_log=kw.get("output_log"),
            external_id=external_id,
            registry_client_factory=self._registry_client_factory,
        )


class RegistryConversationChannel(_RegistryChannel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        registry_client_factory: Callable[[], AgentRegistryClient | None] | None = None,
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
            registry_client_factory=registry_client_factory,
        )


class RegistryTaskChannel(_RegistryChannel):
    def __init__(
        self,
        config: BotConfig,
        registry: RegistryConnectionConfig,
        *,
        registry_client_factory: Callable[[], AgentRegistryClient | None] | None = None,
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
                supports_timeline=True,
            ),
            registry_client_factory=registry_client_factory,
        )


def register_registry_channels(
    config: BotConfig,
    registries: tuple[RegistryConnectionConfig, ...],
    dispatcher: ChannelDispatcher,
) -> None:
    for registry in registries:
        if registry.registry_scope in {"channel", "full"}:
            dispatcher.register(RegistryConversationChannel(config, registry))
        if registry.registry_scope in {"coordination", "full"}:
            dispatcher.register(RegistryTaskChannel(config, registry))
