from datetime import datetime, timezone

import pytest

from octopus_sdk.inbound_types import (
    InboundAction,
    InboundEnvelope,
    InboundMessage,
    InboundUser,
    deserialize_inbound,
    serialize_inbound,
)


def test_inbound_envelope_constructs_without_surface_binding_id() -> None:
    event = InboundAction(
        user=InboundUser(id="tg:42", username="alice"),
        conversation_key="tg:123",
        action="approve",
        params={"item_id": "abc"},
        source="telegram",
    )

    envelope = InboundEnvelope(
        transport="telegram",
        event_id="evt-1",
        conversation_key="tg:123",
        actor_key="tg:42",
        received_at=datetime.now(timezone.utc),
        event=event,
        conversation_ref="tg:123",
    )

    assert envelope.kind == "action"
    assert not hasattr(envelope, "surface_binding_id")


def test_registry_inbound_payloads_round_trip_authority_ref() -> None:
    message_payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id="reg:actor", username="registry"),
            conversation_key="registry:prod:task:task-1",
            text="hello",
            source="registry",
            transport="registry",
            conversation_ref="registry:prod:task:task-1",
            external_conversation_ref="registry-ext-1",
            routed_task_id="task-1",
            authority_ref="registry:prod",
        )
    )
    action_payload = serialize_inbound(
        InboundAction(
            user=InboundUser(id="reg:actor", username="registry"),
            conversation_key="registry:prod:conversation:conv-1",
            action="delegation_approve",
            params={"ok": True},
            source="registry",
            transport="registry",
            conversation_ref="registry:prod:conversation:conv-1",
            external_conversation_ref="registry-ext-2",
            authority_ref="registry:prod",
        )
    )

    message = deserialize_inbound("message", message_payload)
    action = deserialize_inbound("action", action_payload)

    assert isinstance(message, InboundMessage)
    assert isinstance(action, InboundAction)
    assert message.authority_ref == "registry:prod"
    assert action.authority_ref == "registry:prod"
    assert message.external_conversation_ref == "registry-ext-1"
    assert action.external_conversation_ref == "registry-ext-2"
    assert message.transport == "registry"
    assert action.transport == "registry"


def test_non_telegram_inbound_chat_id_falls_back_to_conversation_key() -> None:
    event = InboundAction(
        user=InboundUser(id="reg:actor", username="registry"),
        conversation_key="registry:prod:conversation:conv-1",
        action="approve_pending",
        params={},
        source="registry",
    )

    assert event.chat_id == "registry:prod:conversation:conv-1"


def test_deserialize_inbound_legacy_payload_falls_back_transport_to_source() -> None:
    payload = (
        '{"actor_key":"tg:42","username":"alice","conversation_key":"tg:12345",'
        '"text":"hello","source":"telegram","attachments":[]}'
    )

    event = deserialize_inbound("message", payload)

    assert isinstance(event, InboundMessage)
    assert event.transport == "telegram"


def test_deserialize_inbound_rejects_non_canonical_identity_payloads() -> None:
    payload = '{"user_id":42,"chat_id":99,"text":"hello","source":"telegram"}'

    with pytest.raises(ValueError, match="canonical actor_key/conversation_key"):
        deserialize_inbound("message", payload)


def test_deserialize_inbound_rejects_registry_payload_without_authority_ref() -> None:
    payload = (
        '{"actor_key":"reg:actor","username":"registry","conversation_key":"registry:prod:task:task-1",'
        '"text":"hello","source":"registry","conversation_ref":"registry:prod:task:task-1","routed_task_id":"task-1"}'
    )

    with pytest.raises(ValueError, match="canonical authority_ref"):
        deserialize_inbound("message", payload)


def test_deserialize_inbound_rejects_payload_without_canonical_source() -> None:
    payload = (
        '{"actor_key":"tg:42","username":"alice","conversation_key":"tg:12345",'
        '"text":"hello","attachments":[]}'
    )

    with pytest.raises(ValueError, match="canonical source"):
        deserialize_inbound("message", payload)


def test_deserialize_inbound_rejects_payload_with_blank_source() -> None:
    payload = (
        '{"actor_key":"tg:42","username":"alice","conversation_key":"tg:12345",'
        '"text":"hello","source":"   ","attachments":[]}'
    )

    with pytest.raises(ValueError, match="canonical source"):
        deserialize_inbound("message", payload)


@pytest.mark.parametrize(
    ("factory", "kwargs"),
    [
        (
            InboundMessage,
            {
                "user": InboundUser(id="tg:42", username="alice"),
                "conversation_key": "tg:123",
                "text": "hello",
            },
        ),
        (
            InboundAction,
            {
                "user": InboundUser(id="tg:42", username="alice"),
                "conversation_key": "tg:123",
                "action": "approve",
                "params": {},
            },
        ),
    ],
)
def test_inbound_event_constructors_require_explicit_source(factory, kwargs) -> None:
    with pytest.raises(ValueError, match="source must be explicit"):
        factory(**kwargs)
