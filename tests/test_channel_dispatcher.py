"""Contract tests for transport dispatcher routing and lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.runtime.transport_dispatcher import TransportDispatcher
from octopus_sdk.transport import EditableHandle
from octopus_sdk.transport import TransportCapabilities
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.transport import InboundSubmissionResult
from tests.support.config_support import make_config


class _RuntimeHandle:
    async def submit(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="admitted")

    async def admit_message(self, envelope):
        del envelope
        return InboundSubmissionResult(status="admitted")

    async def enqueue(self, envelope, *, worker_id=None):
        del envelope, worker_id
        return InboundSubmissionResult(status="queued")

    async def record(self, envelope):
        del envelope
        return True


class _DummyHandle(EditableHandle):
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs


class _FakeEgress(TransportEgress):
    def __init__(self, transport_name: str) -> None:
        self._capabilities = TransportCapabilities(channel_name=transport_name)

    @property
    def capabilities(self) -> TransportCapabilities:
        return self._capabilities

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        del text, kwargs
        return _DummyHandle()

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        del photo, kwargs

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        del document, kwargs

    async def send_action(self, action: str) -> None:
        del action

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        del text, show_alert


class _FakeTransport(TransportImplementation):
    def __init__(self, prefix: str, descriptor: TransportDescriptor) -> None:
        self._prefix = prefix
        self._descriptor = descriptor
        self.started = False
        self.stopped = False

    @property
    def transport_id(self) -> str:
        return self._prefix.rstrip(":")

    @property
    def descriptor(self) -> TransportDescriptor:
        return self._descriptor

    def ref_prefix(self) -> str:
        return self._prefix

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> TransportEgress:
        del conversation_ref, config, kw
        return _FakeEgress(self._descriptor.transport_type)

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        del runtime
        self.started = True
        await stop_event.wait()

    async def stop(self) -> None:
        self.stopped = True

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True}


class _FailingTransport(_FakeTransport):
    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        del runtime, stop_event
        raise RuntimeError("boom")


class _BotDependentTransport(_FakeTransport):
    def __init__(self, prefix: str, descriptor: TransportDescriptor) -> None:
        super().__init__(prefix, descriptor)
        self.build_calls = 0
        self.readiness_calls = 0

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        del conversation_ref, config
        self.readiness_calls += 1
        return kw.get("bot") is not None

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> TransportEgress:
        del conversation_ref, config
        self.build_calls += 1
        if kw.get("bot") is None:
            raise RuntimeError("bot not ready")
        return _FakeEgress(self._descriptor.transport_type)


def test_dispatcher_routes_by_registered_prefix() -> None:
    dispatcher = TransportDispatcher()
    telegram = _FakeTransport(
        "telegram:",
        TransportDescriptor(
            transport_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            inbound_model="poll",
        ),
    )
    registry_task = _FakeTransport(
        "registry:prod:task:",
        TransportDescriptor(
            transport_type="registry",
            display_name="Registry Task",
            supports_multiple=True,
            inbound_model="delivery",
            contributes_transport_capability=False,
            accepts_transport_input=False,
            supports_conversation_binding=False,
        ),
    )
    dispatcher.register(telegram)
    dispatcher.register(registry_task)

    cfg = make_config()
    assert dispatcher.create_egress("telegram:bot123:42", config=cfg).capabilities.channel_name == "telegram"
    assert (
        dispatcher.create_egress("registry:prod:task:abc123", config=cfg).capabilities.channel_name
        == "registry"
    )
    assert dispatcher.descriptor_for_ref("registry:prod:task:abc123") == registry_task.descriptor


def test_dispatcher_rejects_conflicting_prefixes() -> None:
    dispatcher = TransportDispatcher()
    dispatcher.register(
        _FakeTransport(
            "registry:prod:",
            TransportDescriptor(
                transport_type="registry",
                display_name="Registry",
                supports_multiple=True,
                inbound_model="delivery",
            ),
        )
    )

    with pytest.raises(ValueError, match="conflicting transport prefix"):
        dispatcher.register(
            _FakeTransport(
                "registry:prod:task:",
                TransportDescriptor(
                    transport_type="registry",
                    display_name="Registry Task",
                    supports_multiple=True,
                    inbound_model="delivery",
                ),
            )
        )


def test_dispatcher_rejects_unknown_refs() -> None:
    dispatcher = TransportDispatcher()
    cfg = make_config()

    with pytest.raises(ValueError, match="unknown conversation ref"):
        dispatcher.create_egress("unknown:ref", config=cfg)


def test_dispatcher_egress_ready_for_ref_checks_runtime_readiness() -> None:
    dispatcher = TransportDispatcher()
    telegram = _BotDependentTransport(
        "telegram:",
        TransportDescriptor(
            transport_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            inbound_model="poll",
        ),
    )
    dispatcher.register(telegram)
    cfg = make_config()

    assert dispatcher.egress_ready_for_ref("telegram:bot123:42", config=cfg, bot=object()) is True
    assert dispatcher.egress_ready_for_ref("telegram:bot123:42", config=cfg, bot=None) is False
    assert telegram.readiness_calls == 2
    assert telegram.build_calls == 0


def test_active_transport_types_deduplicates_and_skips_non_capability_transports() -> None:
    dispatcher = TransportDispatcher()
    dispatcher.register(
        _FakeTransport(
            "telegram:",
            TransportDescriptor(
                transport_type="telegram",
                display_name="Telegram",
                supports_multiple=False,
                inbound_model="poll",
            ),
        )
    )
    dispatcher.register(
        _FakeTransport(
            "registry:prod:conversation:",
            TransportDescriptor(
                transport_type="registry",
                display_name="Registry Conversation",
                supports_multiple=True,
                inbound_model="delivery",
            ),
        )
    )
    dispatcher.register(
        _FakeTransport(
            "registry:prod:task:",
            TransportDescriptor(
                transport_type="registry",
                display_name="Registry Task",
                supports_multiple=True,
                inbound_model="delivery",
                contributes_transport_capability=False,
                accepts_transport_input=False,
                supports_conversation_binding=False,
            ),
        )
    )

    assert dispatcher.active_transport_types() == ["telegram", "registry"]


async def test_start_and_stop_all_transports() -> None:
    dispatcher = TransportDispatcher()
    telegram = _FakeTransport(
        "telegram:",
        TransportDescriptor(
            transport_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            inbound_model="poll",
        ),
    )
    dispatcher.register(telegram)
    dispatcher.register(
        _FakeTransport(
            "registry:prod:task:",
            TransportDescriptor(
                transport_type="registry",
                display_name="Registry Task",
                supports_multiple=True,
                inbound_model="delivery",
                contributes_transport_capability=False,
                accepts_transport_input=False,
                supports_conversation_binding=False,
            ),
        )
    )

    stop_event = asyncio.Event()
    await dispatcher.start_all_transports(runtime=_RuntimeHandle(), stop_event=stop_event)
    await asyncio.sleep(0)
    assert telegram.started is True

    stop_event.set()
    await dispatcher.stop_all_transports()
    assert telegram.stopped is True


async def test_start_all_transports_surfaces_startup_failures() -> None:
    dispatcher = TransportDispatcher()
    dispatcher.register(
        _FailingTransport(
            "telegram:",
            TransportDescriptor(
                transport_type="telegram",
                display_name="Telegram",
                supports_multiple=False,
                inbound_model="poll",
            ),
        )
    )

    with pytest.raises(RuntimeError, match="boom"):
        await dispatcher.start_all_transports(runtime=_RuntimeHandle(), stop_event=asyncio.Event())
