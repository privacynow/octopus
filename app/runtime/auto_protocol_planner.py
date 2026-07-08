"""App-owned Auto Protocol planner executor for bot runtime composition."""

from __future__ import annotations

import asyncio

from app.config import BotConfig
from app.runtime.auto_protocol_design import design_auto_protocol_with_provider
from octopus_sdk.protocols.auto_design import ProtocolAutoDesignModelRequestRecord, ProtocolAutoDesignModelResponseRecord
from octopus_sdk.providers import ProgressSink, Provider


class AppAutoDesignPlanner:
    def __init__(self, config: BotConfig, provider: Provider) -> None:
        self._config = config
        self._provider = provider

    async def design_auto_protocol(
        self,
        request: ProtocolAutoDesignModelRequestRecord,
        *,
        progress: ProgressSink,
        cancel: asyncio.Event | None = None,
    ) -> ProtocolAutoDesignModelResponseRecord:
        return await design_auto_protocol_with_provider(
            request,
            config=self._config,
            provider=self._provider,
            provider_state_factory=self._provider.new_provider_state,
            progress=progress,
            cancel=cancel,
        )
