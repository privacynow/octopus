"""Registry mirroring contract tests -- Phase 9.

Tests cover:
1. Store contracts (deterministic IDs, idempotent enrollment, empty-field rejection)
2. BusConversationProjection adapter (multi-authority create/publish, mismatch detection, cache)
3. Execution runtime wiring (conversation_projection present)
4. Delivery canonical identity (bot_key, origin_channel, external_conversation_ref, stable fields)
5. Session collapse (registry conversation refs collapse, task refs do not)
6. Bus retry on failure (mirror_retry command submitted on create_conversation bus error)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from app.control_plane.adapters.conversation_projection import BusConversationProjection
from app.control_plane.directory import ControlPlaneDirectory
from app.control_plane.models import ControlCommand, ControlReply
from octopus_sdk.identity import conversation_key_for_ref
from app.registry_service.store import RegistrySQLiteStore
from octopus_sdk.registry.models import AgentCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> RegistrySQLiteStore:
    db_path = tmp_path / "registry.sqlite3"
    return RegistrySQLiteStore(db_path)


def _enroll_agent(
    store: RegistrySQLiteStore,
    *,
    bot_key: str = "bot-alpha",
    display_name: str = "Alpha",
    slug: str = "alpha",
    registry_scope: str = "full",
):
    return store.enroll(
        AgentCard(
            bot_key=bot_key,
            display_name=display_name,
            slug=slug,
            registry_scope=registry_scope,
        )
    )


class _FakeBus:
    """Minimal bus fake that records requests/submits and returns canned replies."""

    def __init__(self) -> None:
        self.submitted: list[ControlCommand] = []
        self.requests: list[ControlCommand] = []
        self._request_replies: dict[str, ControlReply | Exception] = {}

    async def submit(self, command: ControlCommand) -> str:
        self.submitted.append(command)
        return command.command_id

    async def request(self, command: ControlCommand, *, timeout_seconds: float = 10.0) -> ControlReply:
        del timeout_seconds
        self.requests.append(command)
        reply = self._request_replies.get(command.authority_ref)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise TimeoutError("no reply configured for authority")
        return reply


def _directory_with(*authority_refs: str) -> ControlPlaneDirectory:
    directory = ControlPlaneDirectory()
    for ref in authority_refs:
        directory.register(capability="conversation_projection", authority_ref=ref)
    return directory


def _success_reply(conversation_id: str) -> ControlReply:
    return ControlReply(
        command_id=uuid4().hex,
        status="completed",
        result_json=json.dumps({"conversation_id": conversation_id}),
    )


def _projection_adapter(
    bus: _FakeBus,
    directory: ControlPlaneDirectory,
    *,
    agent_id: str = "agent-1",
) -> BusConversationProjection:
    return BusConversationProjection(
        bus,
        directory,
        agent_id_for_authority=lambda _authority_ref: agent_id,
    )


# ===================================================================
# 1. Store contract tests
# ===================================================================


class TestStoreContracts:
    def test_create_conversation_deterministic_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        agent = _enroll_agent(store, bot_key="bot-x", slug="agentx")
        agent_id = agent.agent_id

        conv1 = store.create_conversation(
            target_agent_id=agent_id,
            origin_channel="telegram",
            external_conversation_ref="telegram:bot-x:12345",
            title="First",
        )
        conv2 = store.create_conversation(
            target_agent_id=agent_id,
            origin_channel="telegram",
            external_conversation_ref="telegram:bot-x:12345",
            title="Second",
        )

        assert conv1.conversation_id == conv2.conversation_id
        cid = conv1.conversation_id
        assert len(cid) == 32
        assert all(c in "0123456789abcdef" for c in cid)

        # Verify the deterministic formula: sha256(bot_key:origin_channel:external_ref)[:32]
        canonical = "bot-x:telegram:telegram:bot-x:12345"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:32]
        assert cid == expected

    def test_create_conversation_concurrent_idempotency(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        agent = _enroll_agent(store, bot_key="bot-idem", slug="idem")
        agent_id = agent.agent_id

        conv_a = store.create_conversation(
            target_agent_id=agent_id,
            origin_channel="registry",
            external_conversation_ref="ref-1",
            title="First call",
        )
        conv_b = store.create_conversation(
            target_agent_id=agent_id,
            origin_channel="registry",
            external_conversation_ref="ref-1",
            title="Second call",
        )

        assert conv_a.conversation_id == conv_b.conversation_id

    def test_create_conversation_different_agents_same_canonical_key(self, tmp_path: Path) -> None:
        """Two agents sharing the same bot_key produce the same conversation_id."""
        store = _make_store(tmp_path)
        agent_a = _enroll_agent(store, bot_key="shared-bot", slug="agent-a", display_name="A")
        agent_b = _enroll_agent(store, bot_key="shared-bot", slug="agent-b", display_name="B")

        # bot_key-based idempotent re-enroll returns the same agent_id
        # so agent_a and agent_b are actually the same agent row.
        # The contract is: same bot_key -> same deterministic conversation_id.
        conv_a = store.create_conversation(
            target_agent_id=agent_a.agent_id,
            origin_channel="telegram",
            external_conversation_ref="tg:42",
            title="From A",
        )
        conv_b = store.create_conversation(
            target_agent_id=agent_b.agent_id,
            origin_channel="telegram",
            external_conversation_ref="tg:42",
            title="From B",
        )

        assert conv_a.conversation_id == conv_b.conversation_id

    def test_create_conversation_rejects_empty_origin_channel(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        agent = _enroll_agent(store, slug="reject-test")

        with pytest.raises(ValueError, match="origin_channel"):
            store.create_conversation(
                target_agent_id=agent.agent_id,
                origin_channel="",
                external_conversation_ref="ref-1",
                title="Bad",
            )

    def test_create_conversation_rejects_empty_external_ref(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        agent = _enroll_agent(store, slug="reject-test2")

        with pytest.raises(ValueError, match="external_conversation_ref"):
            store.create_conversation(
                target_agent_id=agent.agent_id,
                origin_channel="telegram",
                external_conversation_ref="",
                title="Bad",
            )

    def test_no_timeline_events_table(self, tmp_path: Path) -> None:
        """Fresh SQLite store has no timeline_events table (events stored in events table)."""
        store = _make_store(tmp_path)
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        assert "timeline_events" not in tables

    def test_enrollment_idempotent_by_bot_key(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        first = _enroll_agent(store, bot_key="rekey-bot", slug="rekey")
        second = _enroll_agent(store, bot_key="rekey-bot", slug="rekey")

        assert first.agent_id == second.agent_id
        # Token is refreshed on re-enroll, but agent_id stays the same
        assert first.agent_token != second.agent_token


# ===================================================================
# 2. Adapter tests (BusConversationProjection)
# ===================================================================


class TestBusConversationProjectionAdapter:
    async def test_adapter_creates_on_all_authorities(self) -> None:
        bus = _FakeBus()
        directory = _directory_with("registry:alpha", "registry:beta")

        expected_cid = hashlib.sha256(b"agent-1:telegram:ref-1").hexdigest()[:32]
        bus._request_replies["registry:alpha"] = _success_reply(expected_cid)
        bus._request_replies["registry:beta"] = _success_reply(expected_cid)

        adapter = _projection_adapter(bus, directory)
        cid = await adapter.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="ref-1",
            title="Test",
        )

        assert cid == expected_cid
        # Both authorities received a request
        authority_refs = sorted(cmd.authority_ref for cmd in bus.requests)
        assert authority_refs == ["registry:alpha", "registry:beta"]

    async def test_adapter_publishes_to_all_authorities(self) -> None:
        bus = _FakeBus()
        directory = _directory_with("registry:alpha", "registry:beta")

        cid = "abc123"
        bus._request_replies["registry:alpha"] = _success_reply(cid)
        bus._request_replies["registry:beta"] = _success_reply(cid)

        adapter = _projection_adapter(bus, directory)
        await adapter.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="ref-1",
            title="Test",
        )

        # Clear request log, now publish events
        bus.submitted.clear()

        # Create a minimal event-like object with required attributes
        class _FakeEvent:
            def __init__(self, event_id: str, kind: str, content: str):
                self.event_id = event_id
                self.kind = kind
                self.content = content
                self.metadata = {}

            def model_dump(self):
                return {
                    "event_id": self.event_id,
                    "kind": self.kind,
                    "content": self.content,
                    "metadata": self.metadata,
                }

        await adapter.publish_events(
            conversation_id=cid,
            events=[_FakeEvent("evt-1", "message.user", "hello")],
        )

        # submit called for both authorities
        authority_refs = sorted(cmd.authority_ref for cmd in bus.submitted)
        assert authority_refs == ["registry:alpha", "registry:beta"]

    async def test_adapter_verifies_deterministic_id_match(self, caplog) -> None:
        bus = _FakeBus()
        directory = _directory_with("registry:alpha", "registry:beta")

        bus._request_replies["registry:alpha"] = _success_reply("id-aaaa")
        bus._request_replies["registry:beta"] = _success_reply("id-bbbb")

        adapter = _projection_adapter(bus, directory)
        with caplog.at_level(logging.CRITICAL):
            cid = await adapter.create_conversation(
                target_agent_id="agent-1",
                origin_channel="telegram",
                external_conversation_ref="ref-1",
                title="Mismatch test",
            )

        # First authority's ID wins
        assert cid == "id-aaaa"
        # Critical warning logged about mismatch
        assert any("MISMATCH" in record.message for record in caplog.records)

    async def test_adapter_cache_populated_on_create(self) -> None:
        bus = _FakeBus()
        directory = _directory_with("registry:alpha")

        cid = "cached-id"
        bus._request_replies["registry:alpha"] = _success_reply(cid)

        adapter = _projection_adapter(bus, directory)
        await adapter.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="ref-1",
            title="Cache test",
        )

        assert cid in adapter._identity_cache
        cached = adapter._identity_cache[cid]
        assert cached["origin_channel"] == "telegram"
        assert cached["external_conversation_ref"] == "ref-1"
        assert cached["target_agent_id"] == "agent-1"
        assert cached["title"] == "Cache test"


# ===================================================================
# 3. Execution integration test
# ===================================================================


class TestExecutionRuntimeWiring:
    def test_execution_runtime_has_conversation_projection(self, tmp_path: Path) -> None:
        """ExecutionRuntime built through the Telegram builder path has conversation_projection."""
        from tests.support.handler_support import fresh_env, current_runtime

        with fresh_env() as (_data_dir, cfg, prov):
            runtime = current_runtime()
            cp = runtime.services.control_plane.conversation_projection
            assert cp is not None


# ===================================================================
# 4. Delivery canonical identity tests
# ===================================================================


class TestDeliveryCanonicalIdentity:
    def test_delivery_payload_carries_canonical_identity(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        agent = _enroll_agent(store, bot_key="delivery-bot", slug="delivery")
        agent_id = agent.agent_id

        conv = store.create_conversation(
            target_agent_id=agent_id,
            origin_channel="telegram",
            external_conversation_ref="telegram:delivery-bot:99",
            title="Delivery test",
        )
        cid = conv.conversation_id

        result = store.add_conversation_message(cid, "Hello operator")
        assert result.accepted is True

        # Check the delivery was created with canonical identity fields
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT payload_json FROM deliveries WHERE target_agent_id = ? ORDER BY seq DESC LIMIT 1",
            (agent_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        payload = json.loads(rows[0]["payload_json"])

        assert payload["bot_key"] == "delivery-bot"
        assert payload["origin_channel"] == "telegram"
        assert payload["external_conversation_ref"] == "telegram:delivery-bot:99"
        assert "stable_event_id" in payload
        assert len(payload["stable_event_id"]) == 32  # uuid hex
        assert "stable_created_at" in payload
        assert payload["stable_created_at"]  # non-empty ISO timestamp


# ===================================================================
# 5. Session collapse tests
# ===================================================================


class TestSessionCollapse:
    def test_session_collapse_same_conversation_different_registries(self) -> None:
        """Two registry refs with same conversation_id but different registry_ids collapse."""
        ref_a = "registry:alpha:conversation:conv-42"
        ref_b = "registry:beta:conversation:conv-42"

        key_a = conversation_key_for_ref(ref_a)
        key_b = conversation_key_for_ref(ref_b)

        assert key_a == key_b
        assert key_a == "registry:conversation:conv-42"

    def test_task_refs_not_collapsed(self) -> None:
        """Two registry task refs with different registry_ids do NOT collapse."""
        ref_a = "registry:alpha:task:task-1"
        ref_b = "registry:beta:task:task-1"

        key_a = conversation_key_for_ref(ref_a)
        key_b = conversation_key_for_ref(ref_b)

        # Task refs are not collapsed -- they stay as-is
        assert key_a != key_b
        assert key_a == ref_a
        assert key_b == ref_b


# ===================================================================
# 6. Bus retry on failure tests
# ===================================================================


class TestBusRetryOnFailure:
    async def test_create_conversation_failure_submits_mirror_retry(self) -> None:
        """When bus.request fails on create_conversation, a mirror_retry command is submitted."""
        bus = _FakeBus()
        directory = _directory_with("registry:alpha", "registry:beta")

        # Alpha fails, beta succeeds
        bus._request_replies["registry:alpha"] = ConnectionError("registry down")
        bus._request_replies["registry:beta"] = _success_reply("cid-ok")

        adapter = _projection_adapter(bus, directory)
        cid = await adapter.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="ref-1",
            title="Retry test",
        )

        assert cid == "cid-ok"

        # A mirror_retry command should have been submitted for the failed authority
        retry_commands = [
            cmd for cmd in bus.submitted
            if cmd.capability == "mirror_retry"
        ]
        assert len(retry_commands) == 1
        retry = retry_commands[0]
        assert retry.authority_ref == "registry:alpha"
        assert retry.operation == "create_conversation"
        assert retry.max_retries == 10
        payload = json.loads(retry.payload_json)
        assert payload["target_agent_id"] == "agent-1"
        assert payload["origin_channel"] == "telegram"
        assert payload["external_conversation_ref"] == "ref-1"
        assert payload["title"] == "Retry test"
        assert retry.idempotency_key.startswith("mirror:create:")

    async def test_publish_events_failure_submits_mirror_retry(self) -> None:
        """When bus.submit fails on publish_events, a mirror_retry command is submitted."""

        class _FailOnSecondSubmitBus(_FakeBus):
            """Fails the first submit (conversation_projection publish) but allows mirror_retry."""
            def __init__(self):
                super().__init__()
                self._submit_call_count = 0

            async def submit(self, command: ControlCommand) -> str:
                self._submit_call_count += 1
                # The first submit per authority is the conversation_projection publish_events.
                # Fail it for alpha (first submit call), allow the mirror_retry (second submit).
                if command.capability == "conversation_projection" and command.authority_ref == "registry:alpha":
                    self.submitted.append(command)
                    raise ConnectionError("bus write failed")
                self.submitted.append(command)
                return command.command_id

        bus = _FailOnSecondSubmitBus()
        directory = _directory_with("registry:alpha")

        cid = "conv-publish-test"
        bus._request_replies["registry:alpha"] = _success_reply(cid)

        adapter = _projection_adapter(bus, directory)
        # First create so cache is populated
        await adapter.create_conversation(
            target_agent_id="agent-1",
            origin_channel="telegram",
            external_conversation_ref="ref-1",
            title="Publish retry",
        )

        class _FakeEvent:
            def __init__(self, event_id):
                self.event_id = event_id
            def model_dump(self):
                return {"event_id": self.event_id, "kind": "message.user", "content": "hi"}

        await adapter.publish_events(
            conversation_id=cid,
            events=[_FakeEvent("evt-1")],
        )

        retry_commands = [
            cmd for cmd in bus.submitted
            if cmd.capability == "mirror_retry"
        ]
        assert len(retry_commands) == 1
        retry = retry_commands[0]
        assert retry.authority_ref == "registry:alpha"
        assert retry.operation == "publish_events"
        assert retry.max_retries == 10
        payload = json.loads(retry.payload_json)
        assert payload["conversation_id"] == cid
        assert payload["events"][0]["event_id"] == "evt-1"
        assert retry.idempotency_key.startswith("mirror:publish:")
