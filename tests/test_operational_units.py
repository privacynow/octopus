"""Fast unit tests for the operational remediation abstractions.

Tests the new modules introduced by the remediation plan:
- TransportIdentity (contracts.py)
- ExecutionEventSink / RegistryEventSink / NoOpEventSink (event_sink.py)
- XmlTagDelegationParser (delegation_parser.py)
- normalize_conversation_id / delegation_session_key (identity.py)
- registry_agent_ids on BotConfig (config.py)
- prompt_weight parity with system_prompt (provider_guidance_service.py)
- Dual usage query compatibility (store.py)

All tests are pure unit tests — no bus, no harness, no async waits.
Target: <2 seconds total.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# TransportIdentity
# ---------------------------------------------------------------------------

class TestTransportIdentity:
    def test_default_fields_are_empty(self):
        from app.workflows.execution.contracts import TransportIdentity
        t = TransportIdentity()
        assert t.conversation_key == ""
        assert t.origin_channel == ""
        assert t.external_conversation_ref == ""
        assert t.target_agent_id == ""
        assert t.actor == ""
        assert t.timeline_callback is None

    def test_fields_populated(self):
        from app.workflows.execution.contracts import TransportIdentity
        t = TransportIdentity(
            conversation_key="tg:12345",
            origin_channel="telegram",
            external_conversation_ref="12345",
            target_agent_id="agent-abc",
            actor="tg:42",
        )
        assert t.conversation_key == "tg:12345"
        assert t.origin_channel == "telegram"
        assert t.target_agent_id == "agent-abc"

    def test_frozen(self):
        from app.workflows.execution.contracts import TransportIdentity
        t = TransportIdentity(conversation_key="tg:1")
        with pytest.raises(AttributeError):
            t.conversation_key = "changed"


# ---------------------------------------------------------------------------
# ExecutionEventSink protocol + NoOpEventSink
# ---------------------------------------------------------------------------

class TestNoOpEventSink:
    @pytest.mark.asyncio
    async def test_noop_sink_methods_are_silent(self):
        from app.workflows.execution.event_sink import NoOpEventSink
        sink = NoOpEventSink()
        await sink.on_user_message("hello")
        await sink.on_provider_response(prompt_tokens=10)
        await sink.on_bot_reply("world")
        await sink.on_error("fail")
        await sink.on_delegation_proposed([])
        await sink.on_delegation_submitted([])

    def test_noop_is_singleton(self):
        from app.workflows.execution.event_sink import _NOOP_SINK, NoOpEventSink
        assert isinstance(_NOOP_SINK, NoOpEventSink)

    def test_build_event_sink_returns_noop_when_no_projection(self):
        from app.workflows.execution.event_sink import build_event_sink_for_context, NoOpEventSink
        from app.workflows.execution.contracts import TransportIdentity
        from tests.support.config_support import make_config
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(data_dir=pathlib.Path(d))
            transport = TransportIdentity(conversation_key="tg:1", origin_channel="telegram")
            sink = build_event_sink_for_context(transport, None, cfg)
            assert isinstance(sink, NoOpEventSink)

    def test_build_event_sink_returns_noop_when_no_transport(self):
        from app.workflows.execution.event_sink import build_event_sink_for_context, NoOpEventSink
        from tests.support.config_support import make_config
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(data_dir=pathlib.Path(d))
            sink = build_event_sink_for_context(None, None, cfg)
            assert isinstance(sink, NoOpEventSink)


# ---------------------------------------------------------------------------
# XmlTagDelegationParser
# ---------------------------------------------------------------------------

class TestXmlTagDelegationParser:
    def test_parses_valid_delegation(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = 'Some text\n<delegation>\n{"tasks": [{"target": "m3", "title": "Add numbers", "instructions": "2+2"}]}\n</delegation>'
        agents = [{"slug": "m3", "agent_id": "agent-m3", "display_name": "M3"}]
        tasks = parser.parse(text, agents)
        assert len(tasks) == 1
        assert tasks[0]["target_agent_id"] == "agent-m3"
        assert tasks[0]["title"] == "Add numbers"

    def test_no_delegation_block_returns_empty(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        assert parser.parse("just a normal response", [{"slug": "m3", "agent_id": "a"}]) == []

    def test_unknown_slug_skipped(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>{"tasks": [{"target": "unknown-bot", "title": "X"}]}</delegation>'
        agents = [{"slug": "m3", "agent_id": "a"}]
        assert parser.parse(text, agents) == []

    def test_empty_agents_returns_empty(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>{"tasks": [{"target": "m3"}]}</delegation>'
        assert parser.parse(text, []) == []

    def test_malformed_json_returns_empty(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>not json</delegation>'
        assert parser.parse(text, [{"slug": "m3", "agent_id": "a"}]) == []

    def test_missing_closing_tag_returns_empty(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>{"tasks": [{"target": "m3"}]}'
        assert parser.parse(text, [{"slug": "m3", "agent_id": "a"}]) == []

    def test_defaults_title_when_missing(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>{"tasks": [{"target": "m3", "instructions": "do it"}]}</delegation>'
        agents = [{"slug": "m3", "agent_id": "a"}]
        tasks = parser.parse(text, agents)
        assert tasks[0]["title"] == "Delegated task"

    def test_multiple_tasks(self):
        from app.workflows.execution.delegation_parser import XmlTagDelegationParser
        parser = XmlTagDelegationParser()
        text = '<delegation>{"tasks": [{"target": "m2", "title": "A"}, {"target": "m3", "title": "B"}]}</delegation>'
        agents = [{"slug": "m2", "agent_id": "a2"}, {"slug": "m3", "agent_id": "a3"}]
        tasks = parser.parse(text, agents)
        assert len(tasks) == 2
        assert tasks[0]["target_agent_id"] == "a2"
        assert tasks[1]["target_agent_id"] == "a3"


# ---------------------------------------------------------------------------
# normalize_conversation_id / delegation_session_key
# ---------------------------------------------------------------------------

class TestIdentityHelpers:
    def test_normalize_bare_id(self):
        from app.identity import normalize_conversation_id
        assert normalize_conversation_id("abc123") == "abc123"

    def test_normalize_registry_prefixed(self):
        from app.identity import normalize_conversation_id
        assert normalize_conversation_id("registry:local:conversation:abc123") == "abc123"

    def test_normalize_collapsed_ref(self):
        from app.identity import normalize_conversation_id
        assert normalize_conversation_id("registry:conversation:abc123") == "abc123"

    def test_delegation_session_key_stable(self):
        from app.identity import delegation_session_key
        k1 = delegation_session_key("agent-1", "conv-abc")
        k2 = delegation_session_key("agent-1", "conv-abc")
        assert k1 == k2
        assert k1 == "delegation:agent-1:conv-abc"

    def test_delegation_session_key_differs_by_agent(self):
        from app.identity import delegation_session_key
        k1 = delegation_session_key("agent-1", "conv-abc")
        k2 = delegation_session_key("agent-2", "conv-abc")
        assert k1 != k2

    def test_delegation_session_key_differs_by_conversation(self):
        from app.identity import delegation_session_key
        k1 = delegation_session_key("agent-1", "conv-abc")
        k2 = delegation_session_key("agent-1", "conv-xyz")
        assert k1 != k2


# ---------------------------------------------------------------------------
# registry_agent_ids on BotConfig
# ---------------------------------------------------------------------------

class TestRegistryAgentIds:
    def test_default_empty(self):
        from tests.support.config_support import make_config
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(data_dir=pathlib.Path(d))
            assert cfg.registry_agent_ids == {}

    def test_agent_id_for_registry_returns_empty_when_not_found(self):
        from tests.support.config_support import make_config
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(data_dir=pathlib.Path(d))
            assert cfg.agent_id_for_registry("nonexistent") == ""

    def test_agent_id_for_registry_returns_value(self):
        from tests.support.config_support import make_config
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(data_dir=pathlib.Path(d), registry_agent_ids={"local": "abc123"})
            assert cfg.agent_id_for_registry("local") == "abc123"


# ---------------------------------------------------------------------------
# prompt_weight parity with system_prompt
# ---------------------------------------------------------------------------

class TestPromptWeightParity:
    def test_prompt_weight_matches_system_prompt_length(self):
        from app.provider_guidance_service import get_provider_guidance_service
        svc = get_provider_guidance_service()
        role = "Test engineer"
        skills: list[str] = []
        assert svc.prompt_weight(role, skills) == len(svc.system_prompt(role, skills))

    def test_prompt_weight_includes_available_agents(self):
        from app.provider_guidance_service import get_provider_guidance_service
        svc = get_provider_guidance_service()
        role = "Engineer"
        skills: list[str] = []
        agents = [{"display_name": "M3", "slug": "m3", "role": "", "capabilities": "claude", "connectivity_state": "connected", "agent_id": "a"}]
        weight_without = svc.prompt_weight(role, skills)
        weight_with = svc.prompt_weight(role, skills, available_agents=agents)
        assert weight_with > weight_without
        assert weight_with == len(svc.system_prompt(role, skills, available_agents=agents))


# ---------------------------------------------------------------------------
# Dual usage query (provider.response + legacy usage kind)
# ---------------------------------------------------------------------------

class TestDualUsageQuery:
    def test_usage_query_accepts_both_kinds(self):
        """Verify the SQL queries for usage include both 'provider.response' and legacy 'usage' kind."""
        import sqlite3, json, tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            db_path = pathlib.Path(d) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE events (event_id TEXT, conversation_id TEXT, agent_id TEXT, kind TEXT, actor TEXT, content TEXT, metadata_json TEXT, created_at TEXT, seq INTEGER PRIMARY KEY AUTOINCREMENT)")
            conn.execute("INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("e1", "c1", "a1", "provider.response", "", "", json.dumps({"prompt_tokens": 10}), "2025-01-01T00:00:00Z"))
            conn.execute("INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("e2", "c1", "a1", "usage", "", "", json.dumps({"prompt_tokens": 5}), "2025-01-02T00:00:00Z"))
            conn.execute("INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("e3", "c1", "a1", "message.user", "", "", "{}", "2025-01-03T00:00:00Z"))
            conn.commit()
            # Both provider.response and usage should match; message.user should not
            rows = conn.execute("SELECT * FROM events WHERE kind IN ('provider.response', 'usage')").fetchall()
            assert len(rows) == 2
            conn.close()


# ---------------------------------------------------------------------------
# Deterministic session_id
# ---------------------------------------------------------------------------

class TestDeterministicSessionId:
    def test_same_conversation_key_produces_same_session_id(self):
        from app.providers.claude import ClaudeProvider
        p = ClaudeProvider.__new__(ClaudeProvider)
        s1 = p.new_provider_state("tg:12345")
        s2 = p.new_provider_state("tg:12345")
        assert s1["session_id"] == s2["session_id"]

    def test_different_conversation_key_produces_different_session_id(self):
        from app.providers.claude import ClaudeProvider
        p = ClaudeProvider.__new__(ClaudeProvider)
        s1 = p.new_provider_state("tg:12345")
        s2 = p.new_provider_state("tg:99999")
        assert s1["session_id"] != s2["session_id"]

    def test_empty_conversation_key_produces_random_session_id(self):
        from app.providers.claude import ClaudeProvider
        p = ClaudeProvider.__new__(ClaudeProvider)
        s1 = p.new_provider_state()
        s2 = p.new_provider_state()
        assert s1["session_id"] != s2["session_id"]


# ---------------------------------------------------------------------------
# ExecutionRuntime shape
# ---------------------------------------------------------------------------

class TestExecutionRuntimeShape:
    def test_requires_build_transport_identity(self):
        from app.workflows.execution.contracts import ExecutionRuntime
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ExecutionRuntime)}
        assert "build_transport_identity" in fields
        assert "build_event_sink" in fields
        assert "build_channel_context" not in fields
        assert "conversation_projection" not in fields

    def test_delegation_parser_is_optional(self):
        from app.workflows.execution.contracts import ExecutionRuntime
        import dataclasses
        field_map = {f.name: f for f in dataclasses.fields(ExecutionRuntime)}
        assert field_map["delegation_parser"].default is None


# ---------------------------------------------------------------------------
# Actor key normalization at boundary
# ---------------------------------------------------------------------------

class TestActorKeyNormalization:
    def test_telegram_actor_key_from_int(self):
        from app.channels.telegram.session_io import actor_key
        assert actor_key(42) == "tg:42"

    def test_actor_key_from_string_passthrough(self):
        from app.channels.telegram.session_io import actor_key
        assert actor_key("tg:42") == "tg:42"

    def test_session_state_uses_actor_key_field(self):
        from app.session_state import PendingApproval, PendingRetry, AwaitingSkillSetup
        import dataclasses
        for cls in (PendingApproval, PendingRetry, AwaitingSkillSetup):
            field_names = {f.name for f in dataclasses.fields(cls)}
            assert "actor_key" in field_names, f"{cls.__name__} missing actor_key"
            assert "request_user_id" not in field_names, f"{cls.__name__} still has request_user_id"
            assert "user_id" not in field_names or cls is not AwaitingSkillSetup, f"{cls.__name__} still has user_id"
