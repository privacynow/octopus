"""Contract tests for channel dispatcher routing and ingress lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.ports.channel import Channel, ChannelBootstrap, ChannelDescriptor, ChannelIngress
from app.ports.egress import ChannelCapabilities, ChannelEgress, EditableHandle
from app.runtime.channel_dispatcher import ChannelDispatcher
from tests.support.config_support import make_config


class _DummyHandle(EditableHandle):
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs


class _FakeEgress(ChannelEgress):
    def __init__(self, channel_name: str) -> None:
        self._capabilities = ChannelCapabilities(channel_name=channel_name)

    @property
    def capabilities(self) -> ChannelCapabilities:
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


class _FakeIngress(ChannelIngress):
    def __init__(self, descriptor: ChannelDescriptor, channel_id: str) -> None:
        self._descriptor = descriptor
        self._channel_id = channel_id
        self.started = False
        self.stopped = False

    @property
    def channel_id(self) -> str:
        return self._channel_id

    @property
    def descriptor(self) -> ChannelDescriptor:
        return self._descriptor

    async def start(self, *, stop_event: asyncio.Event) -> None:
        self.started = True
        await stop_event.wait()

    async def stop(self) -> None:
        self.stopped = True

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True}


class _FailingIngress(_FakeIngress):
    async def start(self, *, stop_event: asyncio.Event) -> None:
        del stop_event
        raise RuntimeError("boom")


class _FakeChannel(Channel):
    def __init__(self, prefix: str, descriptor: ChannelDescriptor) -> None:
        self._prefix = prefix
        self._descriptor = descriptor

    @property
    def channel_id(self) -> str:
        return self._prefix.rstrip(":")

    @property
    def descriptor(self) -> ChannelDescriptor:
        return self._descriptor

    def ref_prefix(self) -> str:
        return self._prefix

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
        del conversation_ref, config, kw
        return _FakeEgress(self._descriptor.channel_type)


class _FakeBootstrap(_FakeChannel, ChannelBootstrap):
    def __init__(self, prefix: str, descriptor: ChannelDescriptor) -> None:
        super().__init__(prefix, descriptor)
        self.ingress = _FakeIngress(descriptor, self.channel_id)

    def build_ingress(self, *, config: Any, delivery_handler: Any) -> ChannelIngress:
        del config, delivery_handler
        return self.ingress


class _FailingBootstrap(_FakeChannel, ChannelBootstrap):
    def __init__(self, prefix: str, descriptor: ChannelDescriptor) -> None:
        super().__init__(prefix, descriptor)
        self.ingress = _FailingIngress(descriptor, self.channel_id)

    def build_ingress(self, *, config: Any, delivery_handler: Any) -> ChannelIngress:
        del config, delivery_handler
        return self.ingress


class _BotDependentChannel(_FakeChannel):
    def __init__(self, prefix: str, descriptor: ChannelDescriptor) -> None:
        super().__init__(prefix, descriptor)
        self.build_calls = 0
        self.readiness_calls = 0

    def can_build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> bool:
        del conversation_ref, config
        self.readiness_calls += 1
        return kw.get("bot") is not None

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
        del conversation_ref, config
        self.build_calls += 1
        if kw.get("bot") is None:
            raise RuntimeError("bot not ready")
        return _FakeEgress(self._descriptor.channel_type)


def test_dispatcher_routes_by_registered_prefix() -> None:
    dispatcher = ChannelDispatcher()
    telegram = _FakeBootstrap(
        "telegram:",
        ChannelDescriptor(
            channel_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            requires_polling=False,
        ),
    )
    registry_task = _FakeChannel(
        "registry:prod:task:",
        ChannelDescriptor(
            channel_type="registry",
            display_name="Registry Task",
            supports_multiple=True,
            requires_polling=True,
            contributes_channel_capability=False,
            accepts_channel_input=False,
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
    dispatcher = ChannelDispatcher()
    dispatcher.register(
        _FakeChannel(
            "registry:prod:",
            ChannelDescriptor(
                channel_type="registry",
                display_name="Registry",
                supports_multiple=True,
                requires_polling=True,
            ),
        )
    )

    with pytest.raises(ValueError, match="conflicting channel prefix"):
        dispatcher.register(
            _FakeChannel(
                "registry:prod:task:",
                ChannelDescriptor(
                    channel_type="registry",
                    display_name="Registry Task",
                    supports_multiple=True,
                    requires_polling=True,
                ),
            )
        )


def test_dispatcher_rejects_unknown_refs() -> None:
    dispatcher = ChannelDispatcher()
    cfg = make_config()

    with pytest.raises(ValueError, match="unknown conversation ref"):
        dispatcher.create_egress("unknown:ref", config=cfg)


def test_dispatcher_egress_ready_for_ref_checks_runtime_readiness() -> None:
    dispatcher = ChannelDispatcher()
    telegram = _BotDependentChannel(
        "telegram:",
        ChannelDescriptor(
            channel_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            requires_polling=False,
        ),
    )
    dispatcher.register(telegram)
    cfg = make_config()

    assert dispatcher.egress_ready_for_ref("telegram:bot123:42", config=cfg, bot=object()) is True
    assert dispatcher.egress_ready_for_ref("telegram:bot123:42", config=cfg, bot=None) is False
    assert telegram.readiness_calls == 2
    assert telegram.build_calls == 0


def test_active_channel_types_deduplicates_and_skips_non_capability_channels() -> None:
    dispatcher = ChannelDispatcher()
    dispatcher.register(
        _FakeBootstrap(
            "telegram:",
            ChannelDescriptor(
                channel_type="telegram",
                display_name="Telegram",
                supports_multiple=False,
                requires_polling=False,
            ),
        )
    )
    dispatcher.register(
        _FakeChannel(
            "registry:prod:conversation:",
            ChannelDescriptor(
                channel_type="registry",
                display_name="Registry Conversation",
                supports_multiple=True,
                requires_polling=True,
            ),
        )
    )
    dispatcher.register(
        _FakeChannel(
            "registry:prod:task:",
            ChannelDescriptor(
                channel_type="registry",
                display_name="Registry Task",
                supports_multiple=True,
                requires_polling=True,
                contributes_channel_capability=False,
                accepts_channel_input=False,
                supports_conversation_binding=False,
            ),
        )
    )

    assert dispatcher.active_channel_types() == ["telegram", "registry"]


async def test_build_start_and_stop_all_ingresses_only_uses_bootstraps() -> None:
    dispatcher = ChannelDispatcher()
    telegram = _FakeBootstrap(
        "telegram:",
        ChannelDescriptor(
            channel_type="telegram",
            display_name="Telegram",
            supports_multiple=False,
            requires_polling=False,
        ),
    )
    dispatcher.register(telegram)
    dispatcher.register(
        _FakeChannel(
            "registry:prod:task:",
            ChannelDescriptor(
                channel_type="registry",
                display_name="Registry Task",
                supports_multiple=True,
                requires_polling=True,
                contributes_channel_capability=False,
                accepts_channel_input=False,
                supports_conversation_binding=False,
            ),
        )
    )

    ingresses = dispatcher.build_all_ingresses(config=make_config(), delivery_handler=lambda *args: args)
    assert list(ingresses) == ["telegram"]
    assert dispatcher.get_ingress("telegram") is telegram.ingress

    stop_event = asyncio.Event()
    await dispatcher.start_all_ingresses(stop_event=stop_event)
    await asyncio.sleep(0)
    assert telegram.ingress.started is True

    stop_event.set()
    await dispatcher.stop_all_ingresses()
    assert telegram.ingress.stopped is True


async def test_start_all_ingresses_surfaces_startup_failures() -> None:
    dispatcher = ChannelDispatcher()
    dispatcher.register(
        _FailingBootstrap(
            "telegram:",
            ChannelDescriptor(
                channel_type="telegram",
                display_name="Telegram",
                supports_multiple=False,
                requires_polling=False,
            ),
        )
    )
    dispatcher.build_all_ingresses(config=make_config(), delivery_handler=lambda *args: args)

    with pytest.raises(RuntimeError, match="boom"):
        await dispatcher.start_all_ingresses(stop_event=asyncio.Event())
