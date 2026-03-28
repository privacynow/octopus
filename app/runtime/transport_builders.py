"""Transport stack builders for runtime composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.channels.registry.channel import register_registry_channels
from app.channels.registry.delivery_transport import build_registry_delivery_transport
from app.channels.telegram.bootstrap import build_bootstrap
from app.channels.telegram.channel import TelegramTransport
from app.config import BotConfig
from app.control_plane.bus import ControlPlaneBus
from app.control_plane.directory import ControlPlaneDirectory
from app.runtime.startup import runs_registry_transport
from octopus_sdk.transport_dispatcher import TransportDispatcher
from app.runtime.bot_services import BotServices
from octopus_sdk.providers import Provider
from app.channels.telegram.state import TelegramRuntime

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeTransportBuild:
    dispatcher: TransportDispatcher
    boot_id: str
    telegram_runtime: TelegramRuntime


def build_runtime_transport_stack(
    config: BotConfig,
    provider: Provider,
    *,
    services: BotServices,
    bus: ControlPlaneBus,
    directory: ControlPlaneDirectory,
) -> RuntimeTransportBuild:
    dispatcher = TransportDispatcher()
    runtime_boot_id = ""

    telegram_bootstrap = build_bootstrap(
        config,
        provider,
        services=services,
        dispatcher=dispatcher,
    )
    telegram_transport = TelegramTransport(
        config,
        provider,
        services,
        dispatcher=dispatcher,
        bootstrap=telegram_bootstrap,
    )
    dispatcher.register(telegram_transport)
    runtime_boot_id = telegram_transport.boot_id

    if config.agent_registries:
        register_registry_channels(
            config,
            config.agent_registries,
            dispatcher,
            services=services,
        )
    if runs_registry_transport(config):
        dispatcher.register(
            build_registry_delivery_transport(
                config,
                provider,
                services=services,
                dispatcher=dispatcher,
                bus=bus,
                directory=directory,
            )
        )

    if not runtime_boot_id:
        raise RuntimeError("Runtime process requires a boot identifier")

    return RuntimeTransportBuild(
        dispatcher=dispatcher,
        boot_id=runtime_boot_id,
        telegram_runtime=telegram_bootstrap.runtime,
    )
