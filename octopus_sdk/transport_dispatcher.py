"""Dispatcher for transport-owned ref routing and lifecycle."""

from __future__ import annotations

import asyncio

from octopus_sdk.config import BotConfigBase
from octopus_sdk.transport import BotRuntimeHandle
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.work_queue import WorkItemRecord

class TransportDispatcher(TransportImplementation):
    """Registry of active transports keyed by ref prefix."""

    _DESCRIPTOR = TransportDescriptor(
        transport_type="composite",
        display_name="Composite transport dispatcher",
        supports_multiple=True,
        inbound_model="composite",
        contributes_transport_capability=False,
        accepts_transport_input=False,
        supports_conversation_binding=False,
        supports_timeline=False,
    )

    def __init__(self) -> None:
        self._transports_by_prefix: dict[str, TransportImplementation] = {}
        self._transport_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def transport_id(self) -> str:
        return "transport-dispatcher"

    @property
    def descriptor(self) -> TransportDescriptor:
        return self._DESCRIPTOR

    def ref_prefix(self) -> str:
        return "dispatch:"

    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        return self.create_egress(conversation_ref, config=config, **kw)

    def register(self, transport: TransportImplementation) -> None:
        prefix = transport.ref_prefix()
        if not prefix:
            raise ValueError("transport ref prefix must not be empty")
        for existing in self._transports_by_prefix:
            if prefix == existing or prefix.startswith(existing) or existing.startswith(prefix):
                raise ValueError(f"conflicting transport prefix: {prefix!r} vs {existing!r}")
        self._transports_by_prefix[prefix] = transport

    def _transport_for_ref(self, conversation_ref: str) -> TransportImplementation | None:
        for idx, char in reversed(list(enumerate(conversation_ref))):
            if char != ":":
                continue
            prefix = conversation_ref[: idx + 1]
            transport = self._transports_by_prefix.get(prefix)
            if transport is not None:
                return transport
        return None

    def create_egress(self, conversation_ref: str, *, config: BotConfigBase, **kw: object) -> TransportEgress:
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            raise ValueError(f"unknown conversation ref: {conversation_ref}")
        return transport.build_egress(conversation_ref=conversation_ref, config=config, **kw)

    def worker_egress_kwargs(self, *, conversation_ref: str) -> dict[str, object]:
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            return {}
        return transport.worker_egress_kwargs(conversation_ref=conversation_ref)

    def egress_ready_for_ref(self, conversation_ref: str, *, config: BotConfigBase, **kw: object) -> bool:
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            raise ValueError(f"unknown conversation ref: {conversation_ref}")
        return transport.can_build_egress(conversation_ref=conversation_ref, config=config, **kw)

    def transport_type_for_ref(self, conversation_ref: str) -> str | None:
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            return None
        return transport.descriptor.transport_type

    def active_transport_types(self) -> list[str]:
        seen: list[str] = []
        for transport in self._transports_by_prefix.values():
            transport_type = transport.descriptor.transport_type
            if (
                not transport.descriptor.contributes_transport_capability
                or transport_type in seen
            ):
                continue
            seen.append(transport_type)
        return seen

    async def start_all_transports(
        self,
        *,
        runtime: BotRuntimeHandle,
        stop_event: asyncio.Event,
    ) -> None:
        self._transport_tasks = {}
        for transport in self._transports_by_prefix.values():
            self._transport_tasks[transport.transport_id] = asyncio.create_task(
                transport.start(runtime=runtime, stop_event=stop_event)
            )
        await asyncio.sleep(0)
        startup_errors: list[BaseException] = []
        for task in self._transport_tasks.values():
            if not task.done():
                continue
            exc = task.exception()
            if exc is not None:
                startup_errors.append(exc)
        if startup_errors:
            try:
                await self.stop_all_transports()
            finally:
                raise startup_errors[0]

    async def stop_all_transports(self) -> None:
        for transport in self._transports_by_prefix.values():
            await transport.stop()
        task_failures: list[BaseException] = []
        if self._transport_tasks:
            results = await asyncio.gather(*self._transport_tasks.values(), return_exceptions=True)
            task_failures = [
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ]
        self._transport_tasks = {}
        if task_failures:
            raise task_failures[0]

    async def start(
        self,
        *,
        runtime: BotRuntimeHandle,
        stop_event: asyncio.Event,
    ) -> None:
        await self.start_all_transports(runtime=runtime, stop_event=stop_event)

    async def stop(self) -> None:
        await self.stop_all_transports()

    async def notify_deserialize_failure(
        self,
        item: WorkItemRecord,
        *,
        runtime: BotRuntimeHandle,
    ) -> None:
        transport = self._transport_for_ref(item.conversation_key)
        if transport is not None:
            await transport.notify_deserialize_failure(item, runtime=runtime)

    def claimed_item_context(
        self,
        *,
        event,
        item: WorkItemRecord,
    ):
        conversation_ref = str(
            getattr(event, "conversation_ref", "")
            or getattr(event, "message_conversation_ref", "")
            or item.conversation_key
        )
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            return super().claimed_item_context(event=event, item=item)
        return transport.claimed_item_context(event=event, item=item)

    def descriptor_for_ref(self, conversation_ref: str) -> TransportDescriptor | None:
        transport = self._transport_for_ref(conversation_ref)
        if transport is None:
            return None
        return transport.descriptor

    def get_transport(self, transport_id: str) -> TransportImplementation | None:
        for transport in self._transports_by_prefix.values():
            if transport.transport_id == transport_id:
                return transport
        return None
