"""Contract tests for registry_sdk types and client wire format."""

from registry_sdk.events import ConversationEvent, validate_event_metadata, EVENT_METADATA_SCHEMAS
from registry_sdk.conversations import ConversationCreate


def test_conversation_event_uses_created_at_not_timestamp():
    """The SDK wire format uses created_at, matching the stored event envelope."""
    event = ConversationEvent(event_id="test-1", kind="message.user", content="hello")
    dumped = event.model_dump()
    assert "created_at" in dumped
    assert "timestamp" not in dumped
    assert dumped["created_at"]  # non-empty default


def test_conversation_event_requires_event_id():
    """event_id is required, no default factory."""
    import pytest
    with pytest.raises(Exception):
        ConversationEvent(kind="message.user")


def test_validate_event_metadata_rejects_unknown_kind():
    import pytest
    event = ConversationEvent(event_id="test-2", kind="unknown.kind")
    with pytest.raises(ValueError, match="Unknown event kind"):
        validate_event_metadata(event)


def test_validate_event_metadata_accepts_all_sdk_kinds():
    for kind in EVENT_METADATA_SCHEMAS:
        event = ConversationEvent(event_id=f"test-{kind}", kind=kind)
        validate_event_metadata(event)  # should not raise


def test_conversation_create_rejects_blank_fields():
    import pytest
    with pytest.raises(Exception):
        ConversationCreate(target_agent_id="", origin_channel="telegram", external_conversation_ref="123")
    with pytest.raises(Exception):
        ConversationCreate(target_agent_id="agent-1", origin_channel="", external_conversation_ref="123")
    with pytest.raises(Exception):
        ConversationCreate(target_agent_id="agent-1", origin_channel="telegram", external_conversation_ref="")


def test_sdk_client_publish_events_wraps_in_events_key():
    """Verify the client sends {"events": [...]} not a raw array."""
    import asyncio
    import json
    from unittest.mock import AsyncMock, patch
    from registry_sdk.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    event = ConversationEvent(event_id="wire-1", kind="message.bot", content="hello")

    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"inserted": 1, "skipped": 0}'
            text = '{"inserted": 1, "skipped": 0}'
            def json(self):
                return {"inserted": 1, "skipped": 0}
            @property
            def headers(self):
                return {"content-type": "application/json"}
        captured["json"] = kwargs.get("json")
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        asyncio.run(client.publish_events("conv-1", [event]))

    assert "events" in captured["json"]
    assert isinstance(captured["json"]["events"], list)
    assert captured["json"]["events"][0]["event_id"] == "wire-1"
    assert "created_at" in captured["json"]["events"][0]
    assert "timestamp" not in captured["json"]["events"][0]


def test_sdk_client_enroll_sends_body_not_header():
    """Verify enroll sends enrollment_token in JSON body, not X-Enrollment-Token header."""
    import asyncio
    from unittest.mock import patch
    from registry_sdk.client import RegistryClient

    client = RegistryClient("http://test:8787", "")
    captured = {}

    async def mock_post(self, url, **kwargs):
        class FakeResp:
            status_code = 200
            text = '{"agent_id": "a1", "agent_token": "t1", "slug": "bot"}'
            def json(self):
                return {"agent_id": "a1", "agent_token": "t1", "slug": "bot"}
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers", {})
        return FakeResp()

    with patch("httpx.AsyncClient.post", mock_post):
        result = asyncio.run(client.enroll("enroll-secret", {"display_name": "Bot"}))

    assert captured["json"]["enrollment_token"] == "enroll-secret"
    assert captured["json"]["agent_card"] == {"display_name": "Bot"}
    assert "X-Enrollment-Token" not in captured.get("headers", {})
    assert result["agent_id"] == "a1"
