from datetime import datetime, timezone

from app.runtime.inbound_types import (
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


def test_registry_inbound_payloads_round_trip_registry_id() -> None:
    message_payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id="reg:actor", username="registry"),
            conversation_key="registry:prod:task:task-1",
            text="hello",
            source="registry",
            conversation_ref="registry:prod:task:task-1",
            routed_task_id="task-1",
            registry_id="prod",
        )
    )
    action_payload = serialize_inbound(
        InboundAction(
            user=InboundUser(id="reg:actor", username="registry"),
            conversation_key="registry:prod:conversation:conv-1",
            action="delegation_approve",
            params={"ok": True},
            source="registry",
            conversation_ref="registry:prod:conversation:conv-1",
            registry_id="prod",
        )
    )

    message = deserialize_inbound("message", message_payload)
    action = deserialize_inbound("action", action_payload)

    assert isinstance(message, InboundMessage)
    assert isinstance(action, InboundAction)
    assert message.registry_id == "prod"
    assert action.registry_id == "prod"
