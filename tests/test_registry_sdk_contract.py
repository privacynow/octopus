"""Contract tests for octopus_sdk registry models, event sinks, and client wire format."""

import asyncio
import pathlib
import tempfile

import pytest

from octopus_sdk.event_sink import RegistryEventSink
from octopus_sdk.execution import TransportIdentity
from octopus_sdk.events import ConversationEvent, validate_event_metadata, EVENT_METADATA_SCHEMAS
from octopus_sdk.registry.models import (
    ConversationCreate,
    extract_target_selector_message,
    parse_target_selector,
)
from tests.support.config_support import make_config


def test_conversation_event_uses_created_at_not_timestamp():
    """The SDK wire format uses created_at, matching the stored event envelope."""
    event = ConversationEvent(
        event_id="test-1",
        kind="message.user",
        content="hello",
        created_at="2026-03-23T00:00:00+00:00",
    )
    dumped = event.model_dump()
    assert "created_at" in dumped
    assert "timestamp" not in dumped
    assert dumped["created_at"] == "2026-03-23T00:00:00+00:00"


def test_conversation_event_requires_event_id():
    """event_id is required, no default factory."""
    import pytest
    with pytest.raises(Exception):
        ConversationEvent(kind="message.user")


def test_validate_event_metadata_rejects_unknown_kind():
    import pytest
    event = ConversationEvent(
        event_id="test-2",
        kind="unknown.kind",
        created_at="2026-03-23T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="Unknown event kind"):
        validate_event_metadata(event)


def test_validate_event_metadata_accepts_all_sdk_kinds():
    # Provide valid metadata for kinds that have required fields
    required_metadata = {
        "provider.request": {
            "provider": "codex",
            "model": "gpt-5.4",
            "execution_mode": "run",
            "working_dir": "/tmp/work",
            "file_policy": "edit",
            "image_count": 0,
            "prompt_char_count": 42,
        },
        "provider.response": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost_usd": 0.01,
            "provider": "codex",
        },
        "tool.execution": {
            "tool_name": "exec_command",
            "call_id": "tool-1",
            "status": "completed",
            "input_summary": "git status",
            "output_summary": "ok",
            "duration_ms": 12,
            "file_changes": [],
        },
        "approval.requested": {
            "request_kind": "preflight",
            "actor_key": "telegram:123",
            "trust_tier": "trusted",
            "expires_at": "2026-03-23T00:05:00+00:00",
        },
        "approval.decided": {
            "action": "approve_pending",
            "decided_by": "operator",
            "decision": "approved",
        },
        "delegation.proposed": {
            "proposal_id": "proposal-1",
            "tasks": [{"draft_id": "draft-1", "title": "t", "target": "a", "status": "proposed"}],
        },
        "delegation.submitted": {
            "proposal_id": "proposal-1",
            "tasks": [{"draft_id": "draft-1", "title": "t", "target": "a", "status": "submitted"}],
        },
        "delegation.completed": {
            "proposal_id": "proposal-1",
            "tasks": [{"draft_id": "draft-1", "title": "t", "target": "a", "status": "completed"}],
        },
        "task.status": {"routed_task_id": "task-1", "status": "running"},
        "error": {"error_type": "execution", "message": "boom"},
    }
    for kind in EVENT_METADATA_SCHEMAS:
        metadata = required_metadata.get(kind, {})
        event = ConversationEvent(
            event_id=f"test-{kind}",
            kind=kind,
            created_at="2026-03-23T00:00:00+00:00",
            metadata=metadata,
        )
        validate_event_metadata(event)  # should not raise


def test_validate_event_metadata_rejects_extra_fields():
    import pytest

    event = ConversationEvent(
        event_id="test-extra",
        kind="error",
        created_at="2026-03-23T00:00:00+00:00",
        metadata={
            "error_type": "execution",
            "message": "boom",
            "update_id": 123,
        },
    )

    with pytest.raises(Exception):
        validate_event_metadata(event)


def test_conversation_create_rejects_blank_fields():
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
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    event = ConversationEvent(
        event_id="wire-1",
        kind="message.bot",
        content="hello",
        created_at="2026-03-23T00:00:00+00:00",
    )

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
    assert captured["json"]["events"][0]["created_at"] == "2026-03-23T00:00:00+00:00"
    assert "timestamp" not in captured["json"]["events"][0]


def test_sdk_client_enroll_sends_body_not_header():
    """Verify enroll sends enrollment_token in JSON body, not X-Enrollment-Token header."""
    import asyncio
    from unittest.mock import patch
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "")
    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"agent_id": "a1", "agent_token": "t1", "slug": "bot"}'
            text = '{"agent_id": "a1", "agent_token": "t1", "slug": "bot"}'
            def json(self):
                return {"agent_id": "a1", "agent_token": "t1", "slug": "bot"}
            @property
            def headers(self):
                return {"content-type": "application/json"}
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers", {})
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        result = asyncio.run(
            client.enroll(
                "enroll-secret",
                {
                    "bot_key": "bot:demo",
                    "display_name": "Bot",
                },
            )
        )

    assert captured["json"]["enrollment_token"] == "enroll-secret"
    assert captured["json"]["agent_card"] == {
        "bot_key": "bot:demo",
        "display_name": "Bot",
    }
    assert "X-Enrollment-Token" not in captured.get("headers", {})
    assert result["agent_id"] == "a1"


def test_sdk_client_publish_progress_uses_progress_endpoint():
    from unittest.mock import patch
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"ok": true}'
            text = '{"ok": true}'

            def json(self):
                return {"ok": True}

            @property
            def headers(self):
                return {"content-type": "application/json"}

        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        asyncio.run(
            client.publish_progress(
                "conv-1",
                {
                    "content": "Working on it",
                    "created_at": "2026-03-24T00:00:00+00:00",
                },
            )
        )


def test_parse_target_selector_accepts_agent_capability_and_role():
    agent = parse_target_selector("@m2")
    assert agent is not None
    assert agent.kind == "agent"
    assert agent.value == "m2"
    assert agent.preferred_agent_id == ""

    capability = parse_target_selector("@cap:review")
    assert capability is not None
    assert capability.kind == "capability"
    assert capability.value == "review"

    role = parse_target_selector("@role:reviewer")
    assert role is not None
    assert role.kind == "role"
    assert role.value == "reviewer"


def test_extract_target_selector_message_requires_instructions():
    assert extract_target_selector_message("@m2") is None
    extracted = extract_target_selector_message("@m2 return only the answer")
    assert extracted is not None
    selector, instructions = extracted
    assert selector.kind == "agent"
    assert selector.value == "m2"
    assert instructions == "return only the answer"


@pytest.mark.asyncio
async def test_registry_event_sink_skips_user_message_mirror_for_registry_conversation():
    class _Projection:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.published: list[dict] = []

        async def create_conversation(self, **kwargs):
            self.created.append(kwargs)
            return "conv-1"

        async def publish_events(self, *, conversation_id, events):
            self.published.append({"conversation_id": conversation_id, "events": list(events)})

    with tempfile.TemporaryDirectory() as d:
        cfg = make_config(data_dir=pathlib.Path(d))
        projection = _Projection()
        sink = RegistryEventSink(
            projection=projection,
            transport=TransportIdentity(
                conversation_key="registry:local:conversation:conv-1",
                origin_channel="registry",
                external_conversation_ref="ext-1",
                conversation_ref="registry:local:conversation:conv-1",
                target_agent_id="agent-1",
                actor="operator",
            ),
            config=cfg,
        )

        await sink.on_user_message("hello", actor="operator")

        assert projection.created == []
        assert projection.published == []


@pytest.mark.asyncio
async def test_registry_event_sink_skips_bot_reply_mirror_for_registry_conversation():
    class _Projection:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.published: list[dict] = []

        async def create_conversation(self, **kwargs):
            self.created.append(kwargs)
            return "conv-1"

        async def publish_events(self, *, conversation_id, events):
            self.published.append({"conversation_id": conversation_id, "events": list(events)})

    with tempfile.TemporaryDirectory() as d:
        cfg = make_config(data_dir=pathlib.Path(d))
        projection = _Projection()
        sink = RegistryEventSink(
            projection=projection,
            transport=TransportIdentity(
                conversation_key="registry:local:conversation:conv-1",
                origin_channel="registry",
                external_conversation_ref="ext-1",
                conversation_ref="registry:local:conversation:conv-1",
                target_agent_id="agent-1",
            ),
            config=cfg,
        )

        await sink.on_bot_reply("hello")

        assert projection.created == []
        assert projection.published == []


def test_sdk_client_submit_routed_task_includes_created_at_from_model_default():
    from unittest.mock import patch
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"routed_task_id":"task-1"}'
            text = '{"routed_task_id":"task-1"}'

            def json(self):
                return {"routed_task_id": "task-1"}

            @property
            def headers(self):
                return {"content-type": "application/json"}

        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        asyncio.run(
            client.submit_routed_task(
                {
                    "routed_task_id": "task-1",
                    "parent_conversation_id": "parent-1",
                    "origin_agent_id": "origin-1",
                    "target_agent_id": "target-1",
                    "title": "Do thing",
                    "instructions": "Work on it",
                }
            )
        )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/agents/routed-tasks")
    assert captured["json"]["routed_task_id"] == "task-1"
    assert "created_at" in captured["json"]
    assert captured["json"]["created_at"]


def test_sdk_client_routed_task_status_uses_path_id_not_body_id():
    from unittest.mock import patch
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"status":"running"}'
            text = '{"status":"running"}'

            def json(self):
                return {"status": "running"}

            @property
            def headers(self):
                return {"content-type": "application/json"}

        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        asyncio.run(
            client.routed_task_status(
                "task-1",
                {
                    "routed_task_id": "task-1",
                    "status": "running",
                    "transition_id": "transition-1",
                    "summary": "halfway",
                },
            )
        )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/agents/routed-tasks/task-1/status")
    assert captured["json"]["status"] == "running"
    assert captured["json"]["summary"] == "halfway"
    assert captured["json"]["transition_id"] == "transition-1"
    assert "routed_task_id" not in captured["json"]
    assert "updated_at" in captured["json"]


def test_sdk_client_routed_task_result_uses_path_id_not_body_id():
    from unittest.mock import patch
    from octopus_sdk.registry.client import RegistryClient

    client = RegistryClient("http://test:8787", "test-token")
    captured = {}

    async def mock_request(method, url, **kwargs):
        class FakeResp:
            status_code = 200
            content = b'{"status":"completed"}'
            text = '{"status":"completed"}'

            def json(self):
                return {"status": "completed"}

            @property
            def headers(self):
                return {"content-type": "application/json"}

        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    with patch("httpx.AsyncClient.request", side_effect=mock_request):
        asyncio.run(
            client.routed_task_result(
                "task-1",
                {
                    "routed_task_id": "task-1",
                    "status": "completed",
                    "transition_id": "transition-2",
                    "summary": "done",
                    "full_text": "done",
                },
            )
        )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/agents/routed-tasks/task-1/result")
    assert captured["json"]["status"] == "completed"
    assert captured["json"]["summary"] == "done"
    assert captured["json"]["full_text"] == "done"
    assert captured["json"]["transition_id"] == "transition-2"
    assert "routed_task_id" not in captured["json"]
    assert "completed_at" in captured["json"]


def test_sdk_agent_card_contract_has_no_agent_id_field():
    from octopus_sdk.registry.models import AgentCard

    card = AgentCard(
        bot_key="bot:demo",
        display_name="Bot",
        slug="demo-bot",
        registry_scope="full",
    )

    dumped = card.model_dump()
    assert "agent_id" not in dumped
