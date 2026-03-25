"""Dispatcher for channel-owned ref routing and ingress lifecycle."""

from __future__ import annotations

import asyncio
from typing import Any

from octopus_sdk.channels import Channel, ChannelBootstrap, ChannelDescriptor, ChannelIngress
from octopus_sdk.egress import ChannelEgress


class ChannelDispatcher:
    """Registry of active channels keyed by ref prefix."""

    def __init__(self) -> None:
        self._channels_by_prefix: dict[str, Channel] = {}
        self._ingresses: dict[str, ChannelIngress] = {}
        self._ingress_tasks: dict[str, asyncio.Task[None]] = {}

    def register(self, channel: Channel) -> None:
        prefix = channel.ref_prefix()
        if not prefix:
            raise ValueError("channel ref prefix must not be empty")
        for existing in self._channels_by_prefix:
            if prefix == existing or prefix.startswith(existing) or existing.startswith(prefix):
                raise ValueError(f"conflicting channel prefix: {prefix!r} vs {existing!r}")
        self._channels_by_prefix[prefix] = channel

    def _channel_for_ref(self, conversation_ref: str) -> Channel | None:
        for idx, char in reversed(list(enumerate(conversation_ref))):
            if char != ":":
                continue
            prefix = conversation_ref[: idx + 1]
            channel = self._channels_by_prefix.get(prefix)
            if channel is not None:
                return channel
        return None

    def create_egress(self, conversation_ref: str, *, config: Any, **kw: Any) -> ChannelEgress:
        channel = self._channel_for_ref(conversation_ref)
        if channel is None:
            raise ValueError(f"unknown conversation ref: {conversation_ref}")
        return channel.build_egress(conversation_ref=conversation_ref, config=config, **kw)

    def egress_ready_for_ref(self, conversation_ref: str, *, config: Any, **kw: Any) -> bool:
        channel = self._channel_for_ref(conversation_ref)
        if channel is None:
            raise ValueError(f"unknown conversation ref: {conversation_ref}")
        return channel.can_build_egress(conversation_ref=conversation_ref, config=config, **kw)

    def channel_type_for_ref(self, conversation_ref: str) -> str | None:
        channel = self._channel_for_ref(conversation_ref)
        if channel is None:
            return None
        return channel.descriptor.channel_type

    def active_channel_types(self) -> list[str]:
        seen: list[str] = []
        for channel in self._channels_by_prefix.values():
            channel_type = channel.descriptor.channel_type
            if not channel.descriptor.contributes_channel_capability or channel_type in seen:
                continue
            seen.append(channel_type)
        return seen

    def build_all_ingresses(
        self,
        *,
        config: Any,
        delivery_handler: Any,
    ) -> dict[str, ChannelIngress]:
        self._ingresses = {}
        for channel in self._channels_by_prefix.values():
            if not isinstance(channel, ChannelBootstrap):
                continue
            ingress = channel.build_ingress(config=config, delivery_handler=delivery_handler)
            self._ingresses[ingress.channel_id] = ingress
        return dict(self._ingresses)

    async def start_all_ingresses(self, *, stop_event: asyncio.Event) -> None:
        self._ingress_tasks = {}
        for ingress in self._ingresses.values():
            self._ingress_tasks[ingress.channel_id] = asyncio.create_task(
                ingress.start(stop_event=stop_event)
            )
        await asyncio.sleep(0)
        startup_errors: list[BaseException] = []
        for task in self._ingress_tasks.values():
            if not task.done():
                continue
            exc = task.exception()
            if exc is not None:
                startup_errors.append(exc)
        if startup_errors:
            try:
                await self.stop_all_ingresses()
            finally:
                raise startup_errors[0]

    async def stop_all_ingresses(self) -> None:
        for ingress in self._ingresses.values():
            await ingress.stop()
        task_failures: list[BaseException] = []
        if self._ingress_tasks:
            results = await asyncio.gather(*self._ingress_tasks.values(), return_exceptions=True)
            task_failures = [
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ]
        self._ingress_tasks = {}
        if task_failures:
            raise task_failures[0]

    def descriptor_for_ref(self, conversation_ref: str) -> ChannelDescriptor | None:
        channel = self._channel_for_ref(conversation_ref)
        if channel is None:
            return None
        return channel.descriptor

    def get_ingress(self, channel_id: str) -> ChannelIngress | None:
        return self._ingresses.get(channel_id)
