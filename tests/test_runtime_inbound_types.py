from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.channels.registry.delivery_transport import build_registry_message_envelope
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
    assert envelope.admission_class == "external"


def test_registry_inbound_payloads_round_trip_authority_ref() -> None:
    message_payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id="reg:actor", username="registry"),
            conversation_key="registry:prod:task:task-1",
            text="hello",
            title_text="Task title",
            source="registry",
            transport="registry",
            conversation_ref="registry:prod:task:task-1",
            external_conversation_ref="registry-ext-1",
            routed_task_id="task-1",
            context_text="Investigate the deployment.",
            constraints_text="Read only.",
            requested_skills=("architecture",),
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
    assert message.title_text == "Task title"
    assert action.authority_ref == "registry:prod"
    assert message.external_conversation_ref == "registry-ext-1"
    assert message.context_text == "Investigate the deployment."
    assert message.constraints_text == "Read only."
    assert message.requested_skills == ("architecture",)
    assert action.external_conversation_ref == "registry-ext-2"
    assert message.transport == "registry"
    assert action.transport == "registry"
    assert message.admission_class == "external"


def test_inbound_message_round_trips_internal_admission_class() -> None:
    payload = serialize_inbound(
        InboundMessage(
            user=InboundUser(id="reg:resume", username="registry"),
            conversation_key="tg:12345",
            text="resume",
            source="telegram",
            transport="telegram",
            conversation_ref="telegram:bot:12345",
            admission_class="internal",
        )
    )

    event = deserialize_inbound("message", payload)

    assert isinstance(event, InboundMessage)
    assert event.admission_class == "internal"


def test_registry_message_envelope_defaults_external_and_supports_internal() -> None:
    external = build_registry_message_envelope(
        conversation_ref="telegram:bot:12345",
        text="hello",
        actor_ref="registry-ui:12345",
        delivery_id="delivery-1",
        registry_id="default",
        source_transport="telegram",
    )
    internal = build_registry_message_envelope(
        conversation_ref="telegram:bot:12345",
        text="resume",
        actor_ref="delegation-resume:task-1",
        delivery_id="delivery-2",
        registry_id="default",
        source_transport="telegram",
        admission_class="internal",
    )

    assert external.admission_class == "external"
    assert external.event.admission_class == "external"
    assert internal.admission_class == "internal"
    assert internal.event.admission_class == "internal"


def test_external_ingress_files_do_not_hardcode_internal_admission() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telegram_ingress = (
        repo_root / "app" / "runtime" / "telegram_ingress.py"
    ).read_text(encoding="utf-8")
    telegram_dispatch = (
        repo_root / "app" / "runtime" / "telegram_shared_dispatch.py"
    ).read_text(encoding="utf-8")
    telegram_normalization = (
        repo_root / "app" / "runtime" / "telegram_normalization.py"
    ).read_text(encoding="utf-8")
    registry_delivery = (
        repo_root / "app" / "channels" / "registry" / "delivery_transport.py"
    ).read_text(encoding="utf-8")
    bot_runtime = (
        repo_root / "octopus_sdk" / "bot_runtime.py"
    ).read_text(encoding="utf-8")

    assert 'admission_class="internal"' not in telegram_ingress
    assert 'admission_class="internal"' not in telegram_dispatch
    assert 'admission_class="internal"' not in telegram_normalization
    assert 'admission_class="internal"' not in registry_delivery
    assert bot_runtime.count('admission_class="internal"') >= 1


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
