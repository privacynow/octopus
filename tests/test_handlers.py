"""Core handler integration tests: happy-path routing, session lifecycle, /help, /start, /doctor, /project."""

import asyncio
import re
import tempfile
from pathlib import Path

import pytest

from app.agents.bridge import conversation_key_for_ref, telegram_conversation_ref
from app.agents.state import save_registry_connection_state
from app.agents.types import RegistryConnectionState
from app.agents.delivery import handle_registry_delivery
from app.channels.registry.refs import registry_conversation_ref, registry_task_ref
from app.channels.telegram.bootstrap import build_bootstrap
import app.channels.telegram.worker as telegram_worker
from app.channels.telegram.session_io import (
    load as telegram_load_session,
    save as telegram_save_session,
)
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from app.ports.agent_directory import AgentSearchResult, AuthorityResolution
from app.ports.health_publication import AuthorityStatus, ConnectionSummary
from app.ports.task_routing import TaskSubmissionResult
from app.ports.task_routing import TaskResultReport
from app.providers.base import RunContext, RunResult
from app.runtime.inbound_types import InboundMessage, InboundUser
from app.storage import debug_session_connection, default_session, save_session
from app import work_queue
from tests.support.config_support import make_registry_connection
from tests.support.handler_support import (
    current_bot_instance,
    current_execution_runtime,
    current_runtime,
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    fresh_data_dir,
    fresh_env,
    get_callback_data_values,
    last_reply,
    load_session_disk,
    drain_one_worker_item,
    make_config,
    make_registry_delivery_runtime,
    public_user_config_overrides,
    send_callback,
    send_command,
    send_text,
    setup_globals,
)


def _conv(value):
    return telegram_conversation_key(value)


def _actor(value):
    return telegram_actor_key(value)


def _event(value):
    return telegram_event_id(value)


def _reg_conv(conversation_ref: str) -> str:
    return conversation_key_for_ref(conversation_ref)


def _reg_ref(external_id: str) -> str:
    return registry_conversation_ref("default", external_id)


def _reg_task(external_id: str) -> str:
    return registry_task_ref("default", external_id)


def _registry_delivery_runtime(cfg, prov):
    return make_registry_delivery_runtime(cfg, prov)


async def async_noop(*args, **kwargs):
    del args, kwargs
    return None


async def test_happy_path():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Hello world", provider_state_updates={"started": True})]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hi there")

        import app.channels.telegram.ingress as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        assert "hi there" in prov.run_calls[0]["prompt"]

        ctx = prov.run_calls[0]["context"]
        assert isinstance(ctx, RunContext)
        assert any("uploads" in d for d in ctx.extra_dirs)
        assert ctx.skip_permissions is False

        session = load_session_disk(data_dir, _conv(12345), prov)
        assert session["provider_state"]["started"] == True
        # Worker sends via bot, not msg.replies
        bot = current_bot_instance()
        assert len(bot.sent_messages) >= 2
        assert "Hello world" in " ".join(m.get("text", "") for m in bot.sent_messages)


async def test_worker_dispatch_schedules_completion_webhook_for_terminal_outcome(monkeypatch):
    with fresh_env(
        config_overrides={"completion_webhook_url": "https://hooks.example.com/completed"}
    ) as (data_dir, _cfg, prov):
        import app.channels.telegram.ingress as th

        called: list[dict[str, object]] = []

        async def fake_fire(url, *, chat_id, conversation_ref, status, summary, completed_at):
            called.append(
                {
                    "url": url,
                    "chat_id": chat_id,
                    "conversation_ref": conversation_ref,
                    "status": status,
                    "summary": summary,
                    "completed_at": completed_at,
                }
            )

        monkeypatch.setattr("app.webhook.fire_completion_webhook", fake_fire)
        prov.run_results = [RunResult(text="Terminal reply from provider.")]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="telegram-user"),
            conversation_key=_conv(12345),
            text="Do the thing.",
            source="telegram",
        )
        item = {"id": "webhook-item-1", "conversation_key": _conv(12345), "event_id": _event(7001), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )
        await asyncio.sleep(0)

        assert len(called) == 1
        assert called[0]["url"] == "https://hooks.example.com/completed"
        assert called[0]["chat_id"] == 12345
        assert called[0]["status"] == "completed"
        assert "Terminal reply from provider." in str(called[0]["summary"])


async def test_worker_dispatch_skips_completion_webhook_for_delegation_proposed(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "completion_webhook_url": "https://hooks.example.com/completed",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, _cfg, prov):
        import app.channels.telegram.ingress as th

        called: list[dict[str, object]] = []

        async def fake_fire(url, *, chat_id, conversation_ref, status, summary, completed_at):
            called.append(
                {
                    "url": url,
                    "chat_id": chat_id,
                    "conversation_ref": conversation_ref,
                    "status": status,
                    "summary": summary,
                    "completed_at": completed_at,
                }
            )

        monkeypatch.setattr("app.webhook.fire_completion_webhook", fake_fire)
        prov.run_results = [
            RunResult(
                text="",
                delegation_title="Delegation plan",
                delegation_resume_instruction="Resume after child completion.",
                delegation_tasks=[
                    {
                        "routed_task_id": "task-1",
                        "title": "Delegate task",
                        "target_agent_id": "developer-1",
                        "instructions": "Do the delegated work.",
                    }
                ],
            )
        ]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="registry-ui"),
            conversation_key=_reg_conv(_reg_ref("conv-webhook")),
            text="Delegate this work.",
            source="registry",
            conversation_ref=_reg_ref("conv-webhook"),
            authority_ref="registry:default",
        )
        item = {"id": "webhook-item-2", "conversation_key": _reg_conv(_reg_ref("conv-webhook")), "event_id": _event(7002), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )
        await asyncio.sleep(0)

        assert called == []


async def test_worker_dispatch_skips_completion_webhook_for_routed_task(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "completion_webhook_url": "https://hooks.example.com/completed",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_data_dir, _cfg, prov):
        called: list[dict[str, object]] = []

        async def fake_fire(url, *, chat_id, conversation_ref, status, summary, completed_at):
            called.append(
                {
                    "url": url,
                    "chat_id": chat_id,
                    "conversation_ref": conversation_ref,
                    "status": status,
                    "summary": summary,
                    "completed_at": completed_at,
                }
            )

        async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
            del authority_ref, result
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

        monkeypatch.setattr("app.webhook.fire_completion_webhook", fake_fire)
        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "report_routed_task_result",
            fake_report_routed_task_result,
        )
        prov.run_results = [RunResult(text="Delegated review complete.")]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="origin-bot"),
            conversation_key=_reg_task("routed-task-webhook-1"),
            text="Review the latest spec.",
            source="registry",
            conversation_ref=_reg_task("routed-task-webhook-1"),
            routed_task_id="routed-task-webhook-1",
            authority_ref="registry:default",
        )
        item = {
            "id": "registry-item-webhook-1",
            "conversation_key": _reg_task("routed-task-webhook-1"),
            "event_id": _event(7004),
            "dispatch_mode": "fresh",
        }

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )
        await asyncio.sleep(0)

        assert len(prov.run_calls) == 1
        assert called == []


async def test_help_and_start_include_discover_in_registry_mode():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            agent_mode="registry",
            agent_registries=(make_registry_connection(),),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        help_msg = await send_command(th.cmd_help, chat, user, "/help")
        start_msg = await send_command(th.cmd_start, chat, user, "/start")

        assert "/discover" in help_msg.replies[0]["text"]
        assert "/discover" in start_msg.replies[0]["text"]


async def test_discover_connected_registry_returns_matching_agents(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, _cfg, prov):
        import app.channels.telegram.ingress as th

        seen_queries: list[object] = []

        async def fake_search_agents(*, query):
            seen_queries.append(query)
            return AgentSearchResult(
                status="complete",
                agents=[
                    {
                        "authority_ref": "registry:prod",
                        "agent_id": "agent-2",
                        "display_name": "Dev Bot",
                        "slug": "dev-bot",
                        "role": "developer",
                        "capabilities": ["python", "testing"],
                        "tags": ["backend"],
                        "description": "Builds backend features.",
                        "connectivity_state": "connected",
                        "current_capacity": 0,
                        "max_capacity": 2,
                    }
                ],
                responding_authorities=["registry:prod"],
            )

        current_runtime().services.control_plane.health_publication.connection_summary = (
            lambda: ConnectionSummary(
                authorities=[
                    AuthorityStatus(
                        authority_ref="registry:prod",
                        connectivity_state="configured",
                        capabilities=["agent_directory", "task_routing"],
                    )
                ]
            )
        )
        current_runtime().services.control_plane.agent_directory.search_agents = fake_search_agents

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_discover,
            chat,
            user,
            "/discover role:developer capability:python tag:backend schema review",
            args=["role:developer", "capability:python", "tag:backend", "schema", "review"],
        )

        assert seen_queries
        query = seen_queries[0]
        assert query.role == "developer"
        assert query.capabilities == ("python",)
        assert query.tags == ("backend",)
        assert query.free_text == "schema review"
        assert query.exclude_agent_ids == ()
        reply = msg.replies[0]["text"]
        assert "Dev Bot" in reply
        assert "developer" in reply
        assert "prod" in reply
        assert "python, testing" in reply
        assert "Builds backend features." in reply


async def test_discover_standalone_reports_unavailable():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, agent_mode="standalone")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_discover,
            chat,
            user,
            "/discover role:developer",
            args=["role:developer"],
        )

        assert "standalone mode" in msg.replies[0]["text"]


async def test_discover_degraded_reports_registry_connectivity():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, _cfg, prov):
        import app.channels.telegram.ingress as th

        current_runtime().services.control_plane.health_publication.connection_summary = (
            lambda: ConnectionSummary(
                authorities=[
                    AuthorityStatus(
                        authority_ref="registry:default",
                        connectivity_state="configured",
                        capabilities=["agent_directory", "task_routing"],
                    )
                ]
            )
        )

        async def fake_search_agents(*, query):
            del query
            return AgentSearchResult(status="unavailable")

        current_runtime().services.control_plane.agent_directory.search_agents = fake_search_agents

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_discover,
            chat,
            user,
            "/discover role:developer",
            args=["role:developer"],
        )

        reply = msg.replies[0]["text"]
        assert "registry connectivity is degraded" in reply.lower()
        assert "could not be reached" in reply.lower()
        assert "connecterror" not in reply.lower()


async def test_discover_registry_failure_omits_backend_response_details():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th

        current_runtime().services.control_plane.health_publication.connection_summary = (
            lambda: ConnectionSummary(
                authorities=[
                    AuthorityStatus(
                        authority_ref="registry:default",
                        connectivity_state="configured",
                        capabilities=["agent_directory", "task_routing"],
                    )
                ]
            )
        )

        async def fake_search_agents(*, query):
            del query
            raise RuntimeError("search failed")

        current_runtime().services.control_plane.agent_directory.search_agents = fake_search_agents

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = await send_command(
            th.cmd_discover,
            chat,
            user,
            "/discover role:developer",
            args=["role:developer"],
        )

        reply = msg.replies[0]["text"]
        assert "Agent discovery failed." in reply
        assert "request failed" in reply
        assert "search failed" not in reply
        assert "HTTP 500" not in reply
        assert "/v1/agents/discovery/search" not in reply


async def test_registry_channel_input_respects_approval_mode():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="registry-ui"),
            conversation_key=_reg_conv(_reg_ref("registry-conv-1")),
            text="Please refine this specification.",
            source="registry",
            conversation_ref=_reg_ref("registry-conv-1"),
            authority_ref="registry:default",
        )
        item = {"id": "registry-item-1", "conversation_key": _reg_conv(_reg_ref("registry-conv-1")), "event_id": _event(7001), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        session = load_session_disk(data_dir, _reg_conv(_reg_ref("registry-conv-1")), prov)
        assert len(prov.preflight_calls) == 1
        assert len(prov.run_calls) == 0
        assert session.get("pending_approval") is not None


async def test_approve_delegation_from_registry_delivery(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        submitted = []

        async def fake_resolve_target_authority(*, target_agent_id):
            assert target_agent_id == "developer-1"
            return AuthorityResolution(status="resolved", authority_ref="registry:default")

        async def fake_submit_routed_task(*, request, authority_ref):
            assert authority_ref == "registry:default"
            submitted.append(request)
            return TaskSubmissionResult(status="accepted", routed_task_id=request.routed_task_id)

        monkeypatch.setattr(
            current_runtime().services.control_plane.agent_directory,
            "resolve_target_authority",
            fake_resolve_target_authority,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "submit_routed_task",
            fake_submit_routed_task,
        )
        save_session(
            data_dir,
            _reg_conv(_reg_ref("conv-approve")),
            {
                **default_session(prov.name, prov.new_provider_state(), "off"),
                "pending_delegation": {
                    "conversation_ref": _reg_ref("conv-approve"),
                    "title": "Registry delegation",
                    "tasks": [
                        {
                            "routed_task_id": "task-1",
                            "title": "Implement feature",
                            "target_agent_id": "developer-1",
                            "instructions": "Build the feature.",
                            "status": "proposed",
                        }
                    ],
                },
            },
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-approve-delegation",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_ref": _reg_ref("conv-approve"),
                    "action": "approve_delegation",
                    "payload": {},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        session_after = load_session_disk(data_dir, _reg_conv(_reg_ref("conv-approve")), prov)
        pending = session_after.get("pending_delegation")
        assert outcome == "accepted"
        assert len(submitted) == 1
        assert pending is not None
        assert pending["status"] == "submitted"
        assert pending["tasks"][0]["status"] == "submitted"


async def test_cancel_delegation_from_registry_delivery():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        save_session(
            data_dir,
            _reg_conv(_reg_ref("conv-cancel")),
            {
                **default_session(prov.name, prov.new_provider_state(), "off"),
                "pending_delegation": {
                    "conversation_ref": _reg_ref("conv-cancel"),
                    "title": "Registry delegation",
                    "tasks": [
                        {
                            "routed_task_id": "task-1",
                            "title": "Implement feature",
                            "target_agent_id": "developer-1",
                            "instructions": "Build the feature.",
                            "status": "proposed",
                        }
                    ],
                },
            },
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-cancel-delegation",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_ref": _reg_ref("conv-cancel"),
                    "action": "cancel_delegation",
                    "payload": {},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        session_after = load_session_disk(data_dir, _reg_conv(_reg_ref("conv-cancel")), prov)
        assert outcome == "accepted"
        assert session_after.get("pending_delegation") is None


async def test_delegation_proposed_event_published(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_, _, prov):
        import app.channels.telegram.ingress as th

        published: list[tuple[str, str, str]] = []

        async def fake_publish_timeline(*, conversation_ref, kind, title, body="", status="", progress=None, metadata=None, event_id=None):
            del conversation_ref, status, progress, metadata, event_id
            published.append((kind, title, body))

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "publish_external_timeline",
            fake_publish_timeline,
        )
        prov.run_results = [
            RunResult(
                text="",
                delegation_title="Feature delegation",
                delegation_resume_instruction="Continue after the child tasks return.",
                delegation_tasks=[
                    {
                        "routed_task_id": "task-1",
                        "title": "Implement feature",
                        "target_agent_id": "developer-1",
                        "instructions": "Build the feature.",
                    }
                ],
            )
        ]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="registry-ui"),
            conversation_key=_reg_conv(_reg_ref("conv-proposed")),
            text="Ship the feature.",
            source="registry",
            conversation_ref=_reg_ref("conv-proposed"),
            authority_ref="registry:default",
        )
        item = {"id": "registry-item-proposed", "conversation_key": _reg_conv(_reg_ref("conv-proposed")), "event_id": _event(7101), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert any(kind == "delegation_proposed" for kind, _title, _body in published)


async def test_registry_routed_task_executes_and_reports_result(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_, cfg, prov):
        import app.channels.telegram.ingress as th
        from app.channels.registry.egress import RegistryChannelEgress

        reported: list[tuple[str, object]] = []

        async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
            reported.append(("result", routed_task_id, authority_ref, result))
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "report_routed_task_result",
            fake_report_routed_task_result,
        )

        async def fake_publish_event(self, *, kind, title, body="", status="", progress=None, metadata=None, event_id=None):
            del self, status, progress, metadata, event_id
            reported.append(("surface_event", kind, title, body))

        monkeypatch.setattr(RegistryChannelEgress, "_publish_event", fake_publish_event)
        prov.run_results = [RunResult(text="Delegated review complete.")]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="origin-bot"),
            conversation_key=_reg_task("routed-task-1"),
            text="Review the latest spec.",
            source="registry",
            conversation_ref=_reg_task("routed-task-1"),
            routed_task_id="routed-task-1",
            authority_ref="registry:default",
        )
        item = {"id": "registry-item-2", "conversation_key": _reg_task("routed-task-1"), "event_id": _event(7002), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert len(prov.preflight_calls) == 0
        assert len(prov.run_calls) == 1
        result_entries = [entry for entry in reported if entry[0] == "result"]
        assert len(result_entries) == 1
        _, routed_task_id, authority_ref, result = result_entries[0]
        assert routed_task_id == "routed-task-1"
        assert authority_ref == "registry:default"
        assert result.status == "completed"
        assert "Delegated review complete." in result.full_text
        assert [entry for entry in reported if entry[0] == "surface_event"] == []


async def test_registry_routed_task_progress_updates_task_status(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_, _cfg, prov):
        status_updates: list[tuple[str, object]] = []

        async def fake_update_routed_task_status(*, update, authority_ref):
            status_updates.append((authority_ref, update))

        async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
            del routed_task_id, authority_ref, result
            return TaskResultReport(status="reported")

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "update_routed_task_status",
            fake_update_routed_task_status,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "report_routed_task_result",
            fake_report_routed_task_result,
        )

        prov.run_results = [RunResult(text="Delegated review complete.")]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="origin-bot"),
            conversation_key=_reg_task("routed-task-progress-1"),
            text="Review the latest spec.",
            source="registry",
            conversation_ref=_reg_task("routed-task-progress-1"),
            routed_task_id="routed-task-progress-1",
            authority_ref="registry:default",
        )
        item = {
            "id": "registry-item-progress-1",
            "conversation_key": _reg_task("routed-task-progress-1"),
            "event_id": _event(7003),
            "dispatch_mode": "fresh",
        }

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert len(status_updates) == 2
        first_authority_ref, first_update = status_updates[0]
        assert first_authority_ref == "registry:default"
        assert first_update.routed_task_id == "routed-task-progress-1"
        assert first_update.status == "running"
        assert first_update.summary == "working…"
        assert first_update.timeline_events == ()
        assert first_update.progress is None

        last_authority_ref, last_update = status_updates[-1]
        assert last_authority_ref == "registry:default"
        assert last_update.routed_task_id == "routed-task-progress-1"
        assert last_update.status == "running"
        assert last_update.summary == "Completed."


async def test_registry_routed_task_result_report_failure_does_not_escape_worker(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_, cfg, prov):
        import app.channels.telegram.ingress as th
        from app.channels.registry.egress import RegistryChannelEgress

        published: list[tuple[str, str, str]] = []
        status_updates: list[tuple[str, object]] = []

        async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
            del routed_task_id, authority_ref, result
            return TaskResultReport(status="failed", error="registry unavailable")

        async def fake_update_routed_task_status(*, update, authority_ref):
            status_updates.append((authority_ref, update))

        async def fake_publish_event(self, *, kind, title, body="", status="", progress=None, metadata=None, event_id=None):
            del self, status, progress, metadata, event_id
            published.append((kind, title, body))

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "report_routed_task_result",
            fake_report_routed_task_result,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "update_routed_task_status",
            fake_update_routed_task_status,
        )
        monkeypatch.setattr(RegistryChannelEgress, "_publish_event", fake_publish_event)
        prov.run_results = [RunResult(text="Delegated review complete.")]

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="origin-bot"),
            conversation_key=_reg_task("routed-task-2"),
            text="Review the latest spec.",
            source="registry",
            conversation_ref=_reg_task("routed-task-2"),
            routed_task_id="routed-task-2",
            authority_ref="registry:default",
        )
        item = {"id": "registry-item-3", "conversation_key": _reg_task("routed-task-2"), "event_id": _event(7003), "dispatch_mode": "fresh"}

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert len(prov.run_calls) == 1
        assert published == []
        assert [entry[1].status for entry in status_updates] == [
            "running",
            "running",
            "partialfailed",
        ]
        authority_ref, update = status_updates[-1]
        assert authority_ref == "registry:default"
        assert update.routed_task_id == "routed-task-2"
        assert update.status == "partialfailed"
        assert "could not be delivered" in update.summary


async def test_registry_routed_task_interactive_block_reports_failure(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (_, _cfg, _prov):
        from app.channels.registry.egress import RegistryChannelEgress

        reported: list[tuple[str, str, str]] = []
        published: list[tuple[str, str, str]] = []

        async def fake_dispatch_message_request(*args, **kwargs):
            del args, kwargs
            return None

        async def fake_report_routed_task_result(*, routed_task_id, authority_ref, result):
            reported.append((routed_task_id, authority_ref, result.status))
            return TaskResultReport(status="reported", routed_task_id=routed_task_id)

        async def fake_publish_event(self, *, kind, title, body="", status="", progress=None, metadata=None, event_id=None):
            del self, status, progress, metadata, event_id
            published.append((kind, title, body))

        monkeypatch.setattr(
            telegram_worker,
            "dispatch_message_request",
            fake_dispatch_message_request,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "report_routed_task_result",
            fake_report_routed_task_result,
        )
        monkeypatch.setattr(RegistryChannelEgress, "_publish_event", fake_publish_event)

        event = InboundMessage(
            user=InboundUser(id=_actor(42), username="origin-bot"),
            conversation_key=_reg_task("routed-task-blocked-1"),
            text="Run the protected task.",
            source="registry",
            conversation_ref=_reg_task("routed-task-blocked-1"),
            routed_task_id="routed-task-blocked-1",
            authority_ref="registry:default",
        )
        item = {
            "id": "registry-item-blocked-1",
            "conversation_key": _reg_task("routed-task-blocked-1"),
            "event_id": _event(7004),
            "dispatch_mode": "fresh",
        }

        await telegram_worker.worker_dispatch(
            "message",
            event,
            item,
            runtime=current_runtime(),
            execution_runtime=current_execution_runtime(),
        )

        assert reported == [("routed-task-blocked-1", "registry:default", "failed")]
        assert published == []


async def test_registry_routed_result_resumes_parent_conversation_without_new_approval():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Spec delegation",
            "resume_instruction": "Use the delegated result to finish the parent task.",
            "tasks": [
                {
                    "routed_task_id": "child-task-1",
                    "title": "Developer task",
                    "status": "pending",
                }
            ],
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="Final synthesized answer.")]

        outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-1",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Implementation complete",
                        "full_text": "The delegated developer task completed successfully.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert outcome == "accepted"
        assert await drain_one_worker_item(data_dir) is True
        assert len(prov.run_calls) == 1
        assert "delegated developer task completed successfully" in prov.run_calls[0]["prompt"].lower()
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        assert session_after.get("pending_approval") is None
        assert session_after.get("pending_delegation") is None
        assert any(
            "Final synthesized answer." in message.get("text", "")
            for message in current_bot_instance().sent_messages
        )


async def test_delegation_completion_sends_final_message_all_completed():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Spec delegation",
            "tasks": [
                {
                    "routed_task_id": "child-task-1",
                    "title": "Implement feature",
                    "status": "submitted",
                }
            ],
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="Final parent answer.")]

        outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-1",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Implementation done",
                        "full_text": "Feature implemented successfully.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert outcome == "accepted"
        assert any(
            "All delegated tasks completed." in message.get("text", "")
            for message in current_bot_instance().sent_messages
        )
        assert await drain_one_worker_item(data_dir) is True


async def test_delegation_completion_sends_final_message_partial_failed():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Spec delegation",
            "tasks": [
                {
                    "routed_task_id": "child-task-1",
                    "title": "Implement feature",
                    "status": "submitted",
                },
                {
                    "routed_task_id": "child-task-2",
                    "title": "Review feature",
                    "status": "submitted",
                },
            ],
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="Final parent answer.")]

        first = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-1",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Implementation done",
                        "full_text": "Feature implemented successfully.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        second = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-2",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "failed",
                        "summary": "Review crashed",
                        "full_text": "Review tool crashed.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert first == "accepted"
        assert second == "accepted"
        summary_texts = " ".join(message.get("text", "") for message in current_bot_instance().sent_messages)
        assert "Some delegated tasks failed." in summary_texts
        assert "Review feature [failed]" in summary_texts
        assert "retry the failed tasks" in summary_texts


async def test_registry_routed_result_busy_keeps_pending_delegation_for_retry(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Spec delegation",
            "tasks": [
                {
                    "routed_task_id": "child-task-2",
                    "title": "Reviewer task",
                    "status": "pending",
                }
            ],
        }
        save_session(data_dir, _conv(chat_id), session)

        monkeypatch.setattr(
            "app.agents.delivery.work_queue.record_and_admit_message",
            lambda *args, **kwargs: ("queued", "item-queued"),
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-2",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Review complete",
                        "full_text": "The reviewer finished and returned notes.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert outcome == "accepted"
        assert len(prov.run_calls) == 0
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        pending = session_after.get("pending_delegation")
        assert pending is not None
        assert pending["tasks"][0]["status"] == "completed"
        assert pending["tasks"][0]["summary"] == "Review complete"


async def test_registry_routed_result_duplicate_resume_does_not_resend_completion_summary(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Spec delegation",
            "tasks": [
                {
                    "routed_task_id": "child-task-dup",
                    "title": "Reviewer task",
                    "status": "submitted",
                }
            ],
        }
        save_session(data_dir, _conv(chat_id), session)

        monkeypatch.setattr(
            "app.agents.delivery.work_queue.record_and_admit_message",
            lambda *args, **kwargs: ("duplicate", "item-dup"),
        )

        outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-dup",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Review complete",
                        "full_text": "The reviewer finished and returned notes.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert outcome == "accepted"
        assert not any(
            "All delegated tasks completed." in message.get("text", "")
            for message in current_bot_instance().sent_messages
        )
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        pending = session_after.get("pending_delegation")
        assert pending is not None
        assert pending["status"] == "completed"


async def test_registry_routed_result_multi_child_resumes_only_after_final_child():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Two-child delegation",
            "resume_instruction": "Synthesize both child results before replying.",
            "tasks": [
                {
                    "routed_task_id": "child-task-a",
                    "title": "Developer task",
                    "status": "pending",
                },
                {
                    "routed_task_id": "child-task-b",
                    "title": "Reviewer task",
                    "status": "pending",
                },
            ],
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="Combined final answer.")]

        first_outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-a",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Developer complete",
                        "full_text": "Developer child result.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert first_outcome == "accepted"
        assert await drain_one_worker_item(data_dir) is False
        assert len(prov.run_calls) == 0
        mid_session = load_session_disk(data_dir, _conv(chat_id), prov)
        pending_mid = mid_session.get("pending_delegation")
        assert pending_mid is not None
        assert pending_mid["tasks"][0]["status"] == "completed"
        assert pending_mid["tasks"][1]["status"] == "pending"

        final_outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-b",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Reviewer complete",
                        "full_text": "Reviewer child result.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert final_outcome == "accepted"
        assert await drain_one_worker_item(data_dir) is True
        assert len(prov.run_calls) == 1
        prompt = prov.run_calls[0]["prompt"]
        assert "Developer child result." in prompt
        assert "Reviewer child result." in prompt
        final_session = load_session_disk(data_dir, _conv(chat_id), prov)
        assert final_session.get("pending_delegation") is None


async def test_registry_channel_parent_resumes_through_registry_channel(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from app.channels.registry.egress import RegistryChannelEgress

        published: list[tuple[str, str, str]] = []

        async def fake_publish_event(self, *, kind, title, body="", status="", progress=None, metadata=None, event_id=None):
            del self, status, progress, metadata, event_id
            published.append((kind, title, body))

        monkeypatch.setattr(RegistryChannelEgress, "_publish_event", fake_publish_event)

        conversation_ref = _reg_ref("parent-conv-1")
        chat_id = _reg_conv(conversation_ref)
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Registry parent delegation",
            "tasks": [
                {
                    "routed_task_id": "child-task-registry",
                    "title": "Requirements task",
                    "status": "pending",
                }
            ],
        }
        save_session(data_dir, chat_id, session)
        prov.run_results = [RunResult(text="Registry parent final answer.")]

        outcome = await handle_registry_delivery(
            cfg,
            {
                "registry_id": "default",
                "kind": "routed_result",
                "payload": {
                    "routed_task_id": "child-task-registry",
                    "parent_conversation_id": conversation_ref,
                    "result": {
                        "status": "completed",
                        "summary": "Requirements complete",
                        "full_text": "Requirements child result.",
                    },
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )

        assert outcome == "accepted"
        assert await drain_one_worker_item(data_dir) is True
        assert len(prov.run_calls) == 1
        assert current_bot_instance().sent_messages == []
        assert any(
            kind == "bot_message" and "Registry parent final answer." in body
            for kind, _title, body in published
        )


async def test_registry_channel_action_retry_skip_clears_pending_retry():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_retry"] = {
            "request_user_id": "tg:42",
            "prompt": "Retry this",
            "image_paths": [],
            "context_hash": "",
            "denials": [],
            "trust_tier": "trusted",
            "created_at": 0,
        }
        save_session(data_dir, _conv(chat_id), session)

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-retry-skip",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_id": telegram_conversation_ref(cfg, chat_id),
                    "action": "retry_skip",
                    "payload": {},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        assert outcome == "accepted"
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        assert session_after.get("pending_retry") is None


async def test_registry_channel_action_retry_allow_executes_request():
    with fresh_env(
        config_overrides={
            "approval_mode": "on",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        session = default_session(prov.name, prov.new_provider_state(), "on")
        session["pending_retry"] = {
            "request_user_id": "tg:42",
            "prompt": "Retry this with extra access",
            "image_paths": [],
            "context_hash": "",
            "denials": [{"path": str(data_dir / "extra")}],
            "trust_tier": "trusted",
            "created_at": 0,
        }
        save_session(data_dir, _conv(chat_id), session)
        prov.run_results = [RunResult(text="retry complete")]

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-retry-allow",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_id": telegram_conversation_ref(cfg, chat_id),
                    "action": "retry_allow",
                    "payload": {},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        assert outcome == "accepted"
        assert len(prov.run_calls) == 1
        assert prov.run_calls[0]["prompt"] == "Retry this with extra access"
        session_after = load_session_disk(data_dir, _conv(chat_id), prov)
        assert session_after.get("pending_retry") is None


async def test_registry_channel_action_recovery_discard_discards_pending_recovery():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.runtime_backend as runtime_backend

        chat_id = 12345
        _, item_id = work_queue.record_and_enqueue(
            data_dir, _event(600), _conv(chat_id), _actor(42), "message",
            payload='{"text": "old message"}',
        )
        conn = work_queue.debug_transport_connection(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-recovery-discard",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_id": telegram_conversation_ref(cfg, chat_id),
                    "action": "recovery_discard",
                    "payload": {"update_id": 600},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        row = conn.execute(
            "SELECT state, error FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert outcome == "accepted"
        assert row["state"] == "done"
        assert row["error"] == "discarded"


async def test_registry_channel_action_recovery_replay_executes_request():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.runtime_backend as runtime_backend

        chat_id = 12345
        _, item_id = work_queue.record_and_enqueue(
            data_dir, _event(601), _conv(chat_id), _actor(42), "message",
            payload='{"actor_key": "tg:42", "username": "alice", "conversation_key": "tg:12345", "text": "replay me", "attachments": []}',
        )
        conn = work_queue.debug_transport_connection(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'pending_recovery' WHERE id = ?",
            (item_id,),
        )
        conn.commit()
        prov.run_results = [RunResult(text="replayed")]

        outcome = await handle_registry_delivery(
            cfg,
            {
                "delivery_id": "registry-recovery-replay",
                "registry_id": "default",
                "kind": "channel_action",
                "payload": {
                    "conversation_id": telegram_conversation_ref(cfg, chat_id),
                    "action": "recovery_replay",
                    "payload": {"update_id": 601},
                },
            },
            runtime=_registry_delivery_runtime(cfg, prov),
        )
        assert await drain_one_worker_item(data_dir) is True

        row = conn.execute(
            "SELECT state FROM work_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert outcome == "accepted"
        assert len(prov.run_calls) == 1
        assert prov.run_calls[0]["prompt"] == "replay me"
        assert row["state"] == "done"


async def test_registry_recovery_notice_timeline_includes_update_id(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
        ) as (_, cfg, prov):
            import app.channels.telegram.ingress as th
            from app.channels.registry.egress import RegistryChannelEgress

            published: list[dict[str, object]] = []

            async def fake_publish_event(self, **kwargs):
                del self
                published.append(kwargs)

            monkeypatch.setattr(RegistryChannelEgress, "_publish_event", fake_publish_event)

            event = InboundMessage(
                user=InboundUser(id=_actor(42), username="registry-ui"),
                conversation_key=_reg_conv(_reg_ref("registry-conv-2")),
                text="resume later",
                source="registry",
                conversation_ref=_reg_ref("registry-conv-2"),
                authority_ref="registry:default",
            )
            item = {"id": "registry-item-4", "conversation_key": event.conversation_key, "event_id": _event(8123), "dispatch_mode": "recovery"}

            with pytest.raises(work_queue.PendingRecovery):
                await telegram_worker.worker_dispatch(
                    "message",
                    event,
                    item,
                    runtime=current_runtime(),
                    execution_runtime=current_execution_runtime(),
                )

            recovery_events = [item for item in published if item["kind"] == "recovery_notice"]
            assert recovery_events
            assert recovery_events[0]["metadata"]["update_id"] == 8123


async def test_cmd_new():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", {"session_id": "old-sess", "started": True}, "on")
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, telegram_conversation_key(12345), session)

        scripts_dir = data_dir / "scripts" / "12345" / "some-skill"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hi")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/new")

        import app.channels.telegram.ingress as th

        await th.cmd_new(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        new_session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert not new_session["provider_state"].get("started")
        assert new_session["approval_mode"] == "off"
        assert not (data_dir / "scripts" / "12345").exists()
        assert "Fresh" in " ".join(r.get("text", "") for r in msg.replies)


async def test_provider_timeout():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="partial output", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="long running task")

        import app.channels.telegram.ingress as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        reply_texts = " ".join(m.get("text", "") for m in current_bot_instance().sent_messages)
        assert "partial output" not in reply_texts
        assert sum(1 for m in current_bot_instance().sent_messages if m.get("text")) >= 1
        session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_provider_error_returncode():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Error: segfault in subprocess", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="crash me")

        import app.channels.telegram.ingress as th

        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        reply_texts = " ".join(m.get("text", "") for m in current_bot_instance().sent_messages)
        assert "segfault" not in reply_texts
        assert sum(1 for m in current_bot_instance().sent_messages if m.get("text")) >= 1
        session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_cmd_role():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, role="default engineer")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/role")
        await th.cmd_role(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=[]))
        assert "default engineer" in " ".join(r.get("text", "") for r in msg1.replies)

        msg2 = FakeMessage(chat=chat, text="/role security auditor")
        await th.cmd_role(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["security", "auditor"]))
        session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert session.get("role") == "security auditor"

        msg3 = FakeMessage(chat=chat, text="/role clear")
        await th.cmd_role(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["clear"]))
        session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert session.get("role") == "default engineer"
        assert "default" in " ".join(r.get("text", "") for r in msg3.replies).lower()


async def test_role_in_provider_context():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, role="Kubernetes expert")
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="deploy my app"), user=user, chat=chat),
            FakeContext(),
        )
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        assert "Kubernetes expert" in prov.run_calls[0]["context"].system_prompt


async def test_new_preserves_default_skills():
    from tests.support.skill_test_helpers import save_user_credential, derive_encryption_key

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, _actor(42), "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration", "extra-skill"]
        save_session(data_dir, telegram_conversation_key(12345), session)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        await th.cmd_new(FakeUpdate(message=FakeMessage(chat=chat, text="/new"), user=user, chat=chat), FakeContext())
        session = load_session_disk(data_dir, telegram_conversation_key(12345), prov)
        assert "github-integration" in session.get("active_skills", [])
        assert "extra-skill" not in session.get("active_skills", [])


async def test_help_topics():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        msg1 = FakeMessage(chat=chat, text="/help skills")
        await th.cmd_help(FakeUpdate(message=msg1, user=user, chat=chat), FakeContext(args=["skills"]))
        assert "/skills add" in msg1.replies[0]["text"]

        msg2 = FakeMessage(chat=chat, text="/help approval")
        await th.cmd_help(FakeUpdate(message=msg2, user=user, chat=chat), FakeContext(args=["approval"]))
        approval_text = msg2.replies[0]["text"]
        assert "Approval Mode" in approval_text
        assert ("retry" in approval_text.lower() or "recovery" in approval_text.lower()) and (
            "button" in approval_text.lower() or "in-chat" in approval_text.lower()
        ), "/help approval must mention retry/recovery via in-chat buttons (Phase 14)"

        msg3 = FakeMessage(chat=chat, text="/help credentials")
        await th.cmd_help(FakeUpdate(message=msg3, user=user, chat=chat), FakeContext(args=["credentials"]))
        assert "/clear_credentials" in msg3.replies[0]["text"]

        msg4 = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=msg4, user=user, chat=chat), FakeContext(args=[]))
        assert "/skills" in msg4.replies[0]["text"]
        assert "CLI Bridge" not in msg4.replies[0]["text"]
        assert "/settings" in msg4.replies[0]["text"]


async def test_help_and_start_include_settings():
    """/help and /start must expose /settings, /project, /session for discoverability (Bucket B)."""
    with fresh_env(config_overrides={
        "projects": (("testproj", "/tmp", ()),),
    }) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/settings" in help_text
        assert "/project" in help_text
        assert "/session" in help_text
        assert "/retry" not in help_text
        assert not re.search(r"(?:^|\n)/clear\s", help_text), "must not advertise /clear (use /new); /clear_credentials is fine"
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/settings" in start_text
        assert "/project" in start_text
        assert "/session" in start_text
        assert "/retry" not in start_text
        assert not re.search(r"(?:^|\n)/clear\s", start_text), "must not advertise /clear (use /new)"
        assert "/doctor" in help_text and "full" in help_text and "health" in help_text, (
            "/help must show /doctor as full app health check (Phase 14)"
        )
        assert "/doctor" in start_text and "full" in start_text and "health" in start_text, (
            "/start must show /doctor as full app health check (Phase 14)"
        )
        # Phase 14 second slice: controls set and recovery hint
        assert "Chat options:" in help_text
        assert ("Run again" in help_text or "Skip" in help_text) and "status message" in help_text
        assert "Chat options:" in start_text
        assert ("Run again" in start_text or "Skip" in start_text) and "status message" in start_text


async def test_help_and_start_no_model_when_profiles_empty():
    """Phase 14: /help and /start must NOT advertise /model when no model profiles configured."""
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/model" not in help_text, (
            "/help must not advertise /model when no model profiles configured"
        )
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/model" not in start_text, (
            "/start must not advertise /model when no model profiles configured"
        )


async def test_help_and_start_no_project_when_projects_empty():
    """Phase 14: /help and /start must NOT advertise /project when no projects configured."""
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/settings" in help_text
        assert "/project" not in help_text, (
            "/help must not advertise /project when no projects configured"
        )
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/project" not in start_text, (
            "/start must not advertise /project when no projects configured"
        )


async def test_help_and_start_public_user_excludes_project_and_policy():
    """Bucket B follow-up: public users must not see /project or /policy in /start or /help."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({1, 2, 3}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(999)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/project" not in help_text
        assert "/policy" not in help_text
        assert "/settings" in help_text
        assert "/session" in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/project" not in start_text
        assert "/policy" not in start_text
        assert "/settings" in start_text
        assert "/session" in start_text


async def test_help_and_start_non_admin_excludes_admin_sessions():
    """Bucket B follow-up: non-admin trusted users must not see /admin sessions in /start or /help."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, admin_user_ids=frozenset(), admin_usernames=frozenset())
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/admin sessions" not in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/admin sessions" not in start_text


async def test_help_and_start_admin_sees_admin_sessions_and_trusted_commands():
    """Bucket B follow-up: admin users see /admin sessions and full trusted command set."""
    with fresh_env(config_overrides={
        "admin_user_ids": frozenset({42}),
        "admin_usernames": frozenset(),
        "projects": (("testproj", "/tmp", ()),),
    }) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        help_msg = FakeMessage(chat=chat, text="/help")
        await th.cmd_help(FakeUpdate(message=help_msg, user=user, chat=chat), FakeContext(args=[]))
        help_text = help_msg.replies[0]["text"]
        assert "/admin sessions" in help_text
        assert "/project" in help_text
        assert "/settings" in help_text
        assert "/session" in help_text
        start_msg = FakeMessage(chat=chat, text="/start")
        await th.cmd_start(FakeUpdate(message=start_msg, user=user, chat=chat), FakeContext(args=[]))
        start_text = start_msg.replies[0]["text"]
        assert "/admin sessions" in start_text
        assert "/project" in start_text


def test_bucket_b_command_registration_parity():
    """Bucket B: key user-facing commands (start, help, settings, project, session) must be registered."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        import app.channels.telegram.ingress as th
        from telegram.ext import CommandHandler

        app = build_bootstrap(cfg, prov).application
        registered = set()
        for group_handlers in app.handlers.values():
            for h in group_handlers:
                if isinstance(h, CommandHandler):
                    commands = getattr(h, "commands", None) or (
                        (getattr(h, "command", None),) if getattr(h, "command", None) else ()
                    )
                    registered.update(commands)
        required = {"start", "help", "settings", "project", "session", "cancel"}
        missing = required - registered
        assert not missing, f"Bucket B main commands must be registered; missing: {missing}"


def test_build_application_sequential_updates():
    """build_application uses sequential update processing; live runs are worker-owned so /cancel works."""
    with fresh_env() as (_, cfg, prov):
        import app.channels.telegram.ingress as th

        app = build_bootstrap(cfg, prov).application
        # Default sequential processing (no custom update processor)
        assert app.update_processor is None or "CancelPriority" not in type(app.update_processor).__name__


async def test_first_run_welcome():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="plan: read files")]
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        # Welcome is sent by handler to message.chat (FakeChat) when no session exists
        sent_chat = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "ready" in sent_chat.lower()
        assert "Approval mode is on" in sent_chat
        await drain_one_worker_item(data_dir)
        # Worker sends approval plan via bot
        bot = current_bot_instance()
        sent_bot = " ".join(m.get("text", m.get("edit_text", "")) for m in bot.sent_messages)
        assert "preparing" in sent_bot.lower() or "plan" in sent_bot.lower()


async def test_first_run_welcome_compact_mode():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, compact_mode=True)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="hi")]
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        # Welcome (including compact) is sent by handler to message.chat when no session exists
        sent_chat = " ".join(m.get("text", "") for m in chat.sent_messages)
        assert "Compact mode is on" in sent_chat
        assert "/compact off" in sent_chat
        await drain_one_worker_item(data_dir)


async def test_first_run_welcome_no_compact():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, compact_mode=False)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="hi")]
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="hello")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        await drain_one_worker_item(data_dir)
        bot = current_bot_instance()
        sent = " ".join(m.get("text", m.get("edit_text", "")) for m in bot.sent_messages)
        assert "Compact mode" not in sent


async def test_start_deep_link():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/start foo")
        await th.cmd_start(FakeUpdate(message=msg, user=user, chat=chat), FakeContext(args=["foo"]))
        assert "Unknown help topic" not in msg.replies[0]["text"]
        assert "Agent Bot" in msg.replies[0]["text"]


async def test_doctor_admin_warning():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1, 2, 3}),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        import app.channels.telegram.ingress as th

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" in reply


async def test_doctor_no_warning_explicit_admin():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        import app.channels.telegram.ingress as th

        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" not in reply


async def test_prompt_size_warning_before_activation():
    from tests.support import skill_test_helpers as skills_mod

    with fresh_data_dir() as data_dir:
        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            d = custom_dir / "big-skill"
            d.mkdir(parents=True)
            (d / "skill.md").write_text(
                "---\nname: big-skill\ndisplay_name: Big\n"
                "description: test\n---\n\n" + "x" * 9000 + "\n"
            )

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="ok")]
            setup_globals(cfg, prov)

            session = default_session("claude", prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(1), session)

            import app.channels.telegram.ingress as th
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(
                th.cmd_skills, chat, user, "/skills add big-skill",
                args=["add", "big-skill"])

            reply = last_reply(msg)
            assert "prompt context" in reply
            assert "8,000" in reply
            assert "Continue" in reply

            session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
            assert "big-skill" not in session.get("active_skills", [])
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


async def test_prompt_size_no_warning_small_skill():
    from tests.support import skill_test_helpers as skills_mod

    with fresh_data_dir() as data_dir:
        orig_custom_dir = skills_mod.CUSTOM_DIR
        try:
            custom_dir = data_dir / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            d = custom_dir / "tiny-skill"
            d.mkdir(parents=True)
            (d / "skill.md").write_text(
                "---\nname: tiny-skill\ndisplay_name: Tiny\n"
                "description: test\n---\n\nSmall instructions.\n"
            )

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            prov.run_results = [RunResult(text="ok")]
            setup_globals(cfg, prov)

            session = default_session("claude", prov.new_provider_state(), "off")
            save_session(data_dir, telegram_conversation_key(1), session)

            import app.channels.telegram.ingress as th
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(
                th.cmd_skills, chat, user, "/skills add tiny-skill",
                args=["add", "tiny-skill"])

            reply = last_reply(msg)
            assert "activated" in reply
            assert "prompt context" not in reply

            session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
            assert "tiny-skill" in session.get("active_skills", [])
        finally:
            skills_mod.CUSTOM_DIR = orig_custom_dir


async def test_doctor_stale_session_warnings():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session1 = default_session("claude", prov.new_provider_state(), "off")
        session1["pending_approval"] = {"prompt": "do something", "created_at": 0}
        save_session(data_dir, telegram_conversation_key(100), session1)

        session2 = default_session("claude", prov.new_provider_state(), "off")
        session2["awaiting_skill_setup"] = {"user_id": "tg:42", "skill": "test", "started_at": 0}
        save_session(data_dir, telegram_conversation_key(200), session2)

        session3 = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, telegram_conversation_key(300), session3)

        import app.channels.telegram.ingress as th
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "pending approval" in reply
        assert "credential setup" in reply


async def test_doctor_no_warning_explicit_admin_equal_to_allowed():
    """If BOT_ADMIN_USERS is explicitly set to same as BOT_ALLOWED_USERS,
    /doctor should NOT warn (operator made a deliberate choice)."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allowed_user_ids=frozenset({1, 2, 3}),
            admin_user_ids=frozenset({1, 2, 3}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        import app.channels.telegram.ingress as th
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "BOT_ADMIN_USERS" not in reply


async def test_doctor_no_stale_warning_for_fresh_sessions():
    import time as _time
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session1 = default_session("claude", prov.new_provider_state(), "off")
        session1["pending_approval"] = {"prompt": "do something", "created_at": _time.time()}
        save_session(data_dir, telegram_conversation_key(100), session1)

        session2 = default_session("claude", prov.new_provider_state(), "off")
        session2["awaiting_skill_setup"] = {"user_id": "tg:42", "skill": "test", "started_at": _time.time()}
        save_session(data_dir, telegram_conversation_key(200), session2)

        import app.channels.telegram.ingress as th
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert "stale pending" not in reply
        assert "stale credential" not in reply


async def test_doctor_missing_data_dir():
    """collect_runtime_health_report should not crash when data_dir doesn't exist yet.

    Reproduces: operator runs --doctor before first bot startup, data_dir
    doesn't exist.  Previously crashed in scan_stale_sessions -> SQLite open.
    """
    import tempfile
    from app.runtime_health import collect_runtime_health_report

    with tempfile.TemporaryDirectory() as tmp:
        missing_dir = Path(tmp) / "not-yet-created"
        # Verify it really doesn't exist -- no stale leftovers possible
        assert not missing_dir.exists()

        cfg = make_config(missing_dir)
        prov = FakeProvider("claude")

        report = await collect_runtime_health_report(cfg, prov)
        assert report is not None
        assert isinstance(report.diagnostics, tuple)
        # Stale session scan should have been skipped entirely
        stale_msgs = [
            item.message for item in report.diagnostics
            if item.level == "warning" and "stale" in item.message.lower()
        ]
        assert len(stale_msgs) == 0


async def test_doctor_corrupt_session_db():
    """collect_runtime_health_report should report corrupt DB, not crash.

    Reproduces: operator's sessions.db gets corrupted (disk error, partial
    write, manual edit).  Previously raised DatabaseError: file is not a
    database, crashing the health command instead of reporting the problem.
    """
    import tempfile
    from app.runtime_health import collect_runtime_health_report
    from app.storage import close_db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Create a corrupt sessions.db -- junk bytes, not a valid SQLite file
        db_path = data_dir / "sessions.db"
        db_path.write_bytes(b"this is not a valid sqlite database file at all")

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")

        try:
            report = await collect_runtime_health_report(cfg, prov)
            assert report is not None
            # Should have caught the corruption and reported it as an error
            corruption_errors = [
                item.message
                for item in report.diagnostics
                if item.level == "error"
                and ("corrupt" in item.message.lower() or "database" in item.message.lower())
            ]
            assert len(corruption_errors) >= 1
            # Should NOT have stale session warnings (scan couldn't run)
            stale_msgs = [
                item.message for item in report.diagnostics
                if item.level == "warning" and "stale" in item.message.lower()
            ]
            assert len(stale_msgs) == 0
        finally:
            close_db(data_dir)


async def test_cmd_doctor_corrupt_db_telegram():
    """/doctor via Telegram should reply with an error, not crash, on corrupt DB.

    This exercises the real user-facing path: user sends /doctor in chat,
    cmd_doctor calls _load() which hits SQLite, DB is corrupt.  Previously
    the handler raised DatabaseError unhandled and the user saw nothing.
    """
    import tempfile
    from app.storage import close_db

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Bootstrap a real DB first so the config/dirs are valid
        from app.storage import ensure_data_dirs
        ensure_data_dirs(data_dir)
        close_db(data_dir)

        # Now corrupt the DB file
        db_path = data_dir / "sessions.db"
        db_path.write_bytes(b"this is not a valid sqlite database file at all")

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th
        chat = FakeChat(1)
        user = FakeUser(42)

        try:
            msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
            reply = last_reply(msg)
            # Handler should reply (not crash silently)
            assert len(reply) > 0
            # Reply should mention the DB problem
            assert "corrupt" in reply.lower() or "database" in reply.lower()
        finally:
            close_db(data_dir)


async def test_doctor_schema_mismatch_cli():
    """collect_runtime_health_report should report a newer session DB schema, not crash.

    Reproduces: operator downgrades the bot, sessions.db has schema_version=99.
    Session store raises RuntimeError which was not caught by the stale session
    scan handler (only sqlite3 exceptions were caught).
    """
    import tempfile
    from app.runtime_health import collect_runtime_health_report
    from app.storage import close_db, ensure_data_dirs

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        conn = debug_session_connection(data_dir)
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        close_db(data_dir)

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")

        report = await collect_runtime_health_report(cfg, prov)
        assert report is not None
        schema_errors = [
            item.message
            for item in report.diagnostics
            if item.level == "error"
            and ("schema" in item.message.lower() or "newer" in item.message.lower())
        ]
        assert len(schema_errors) >= 1


async def test_doctor_schema_mismatch_telegram():
    """/doctor via Telegram should reply with schema error, not crash.

    Same scenario as CLI but through the real handler path: cmd_doctor calls
    _load() which hits the session store and raises RuntimeError for schema mismatch.
    """
    import tempfile
    from app.storage import close_db, ensure_data_dirs

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        conn = debug_session_connection(data_dir)
        conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        conn.commit()
        close_db(data_dir)

        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.channels.telegram.ingress as th
        chat = FakeChat(1)
        user = FakeUser(42)

        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        reply = last_reply(msg)
        assert len(reply) > 0
        assert "schema" in reply.lower() or "newer" in reply.lower()


async def test_send_file_directive():
    """Provider response with SEND_FILE: directive delivers the file to chat."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a file within the allowed working_dir
        test_file = data_dir / "output.txt"
        test_file.write_text("file contents here")

        prov.run_results = [RunResult(text=f"Here is the file\nSEND_FILE: {test_file}")]

        chat = FakeChat(12345)
        user = FakeUser(42)
        await send_text(chat, user, "generate a file")
        await drain_one_worker_item(data_dir)

        import app.channels.telegram.ingress as th
        bot = current_bot_instance()
        doc_sent = [m for m in bot.sent_messages if m.get("document") is not None]
        assert len(doc_sent) >= 1


async def test_send_image_directive():
    """Provider response with SEND_IMAGE: directive delivers the image to chat."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, working_dir=data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Create a fake image file within the allowed working_dir
        test_img = data_dir / "chart.png"
        test_img.write_bytes(b"\x89PNG fake image data")

        prov.run_results = [RunResult(text=f"Here is the chart\nSEND_IMAGE: {test_img}")]

        chat = FakeChat(12345)
        user = FakeUser(42)
        await send_text(chat, user, "make a chart")
        await drain_one_worker_item(data_dir)

        import app.channels.telegram.ingress as th
        bot = current_bot_instance()
        photo_sent = [m for m in bot.sent_messages if m.get("photo") is not None]
        assert len(photo_sent) >= 1


# ---------------------------------------------------------------------------
# /project command tests
# ---------------------------------------------------------------------------

async def test_project_list_no_projects():
    """When no projects are configured, /project list says so."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["list"])
        reply = last_reply(msg)
        assert "No projects configured" in reply


async def test_project_list_shows_projects():
    """When projects are configured, /project list shows them."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(1)
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["list"])
            reply = last_reply(msg)
            assert "myapp" in reply
            assert proj_dir in reply


async def test_project_use_switches_project():
    """'/project use <name>' binds the chat to a project and resets provider state."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("frontend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(2001)
            user = FakeUser(1)

            # First send a message to create session state
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hello")
            await drain_one_worker_item(data_dir)

            # Now switch project
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "frontend"])
            reply = last_reply(msg)
            assert "Switched to project" in reply
            assert "frontend" in reply
            assert "Provider session reset" in reply

            # Verify session has project_id set and provider state reset
            session = load_session_disk(data_dir, telegram_conversation_key(2001), prov)
            assert session["project_id"] == "frontend"
            # Provider state should be fresh
            assert session["provider_state"].get("started") is not True


async def test_project_use_unknown_project():
    """'/project use <unknown>' returns error."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (("myapp", "/tmp", ()),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "nonexistent"])
        reply = last_reply(msg)
        assert "Unknown project" in reply


async def test_project_clear_resets_to_default():
    """'/project clear' removes the project binding and resets provider state."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(3001)
            user = FakeUser(1)

            # Bind to project first
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hello")
            await drain_one_worker_item(data_dir)
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "myapp"])

            # Clear
            msg = await send_command(th.cmd_project, chat, user, "/project", args=["clear"])
            reply = last_reply(msg)
            assert "Project cleared" in reply

            session = load_session_disk(data_dir, telegram_conversation_key(3001), prov)
            assert session.get("project_id", "") == ""


async def test_project_show_current():
    """'/project' with no args shows the current project."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("backend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(4001)
            user = FakeUser(1)

            # No project active
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = last_reply(msg)
            assert "No project" in reply

            # Bind and check
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "backend"])
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = last_reply(msg)
            assert "backend" in reply


async def test_project_switch_invalidates_pending():
    """Switching projects clears pending approval requests."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("proj1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(5001)
            user = FakeUser(1)

            # Create a session with a pending request
            session = default_session("claude", prov.new_provider_state(), "on")
            session["pending_approval"] = {"prompt": "do something", "created_at": 0}
            save_session(data_dir, telegram_conversation_key(5001), session)

            # Switch project
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "proj1"])

            # Pending should be cleared
            session = load_session_disk(data_dir, telegram_conversation_key(5001), prov)
            assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_session_shows_project():
    """/session shows the active project when one is bound."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("webapp", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(6001)
            user = FakeUser(1)

            # Bind to project
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "webapp"])

            # Check /session output
            msg = await send_command(th.cmd_session, chat, user, "/session")
            reply = last_reply(msg)
            assert "webapp" in reply
            assert proj_dir in reply


async def test_context_hash_changes_with_project():
    """Context hash should differ when project_id changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], working_dir="", file_policy="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, project_id="").context_hash
    hash2 = ResolvedExecutionContext(**_d, project_id="myproject").context_hash
    assert hash1 != hash2


# ---------------------------------------------------------------------------
# /policy — file policy (6.3)
# ---------------------------------------------------------------------------

async def test_policy_default_is_edit():
    """/policy with no args shows current policy; default is edit."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy")
        reply = last_reply(msg)
        assert "edit" in reply


async def test_policy_set_inspect():
    """/policy inspect switches to read-only mode and resets provider state."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Send a message to create session with provider state
        await send_text(chat, user, "hello")
        await drain_one_worker_item(data_dir)
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("file_policy", "") != "inspect"

        # Set inspect
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        reply = last_reply(msg)
        assert "inspect" in reply
        assert "reset" in reply.lower()

        # Verify persisted
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("file_policy") == "inspect"


async def test_policy_set_edit():
    """/policy edit switches back to edit mode."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect first
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        # Switch to edit
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        reply = last_reply(msg)
        assert "edit" in reply

        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session.get("file_policy") == "edit"


async def test_policy_same_value_noop():
    """/policy edit when already edit shows already-set message, no reset."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        # Default is edit, so should say "already"
        reply = last_reply(msg)
        assert "already" in reply.lower()


async def test_policy_invalid_arg():
    """/policy with bad argument shows usage hint."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["delete"])
        reply = last_reply(msg)
        assert "inspect" in reply and "edit" in reply  # usage hint


async def test_policy_shown_in_session():
    """/session output includes file policy."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "inspect" in reply
        assert "File policy" in reply


async def test_policy_inspect_passed_to_provider():
    """When file_policy=inspect, provider run() receives it in context."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        # Set inspect
        await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        # Send a message
        await send_text(chat, user, "analyze the code")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.file_policy == "inspect"


async def test_policy_edit_passed_to_provider():
    """When file_policy=edit (default), provider run() gets empty or 'edit'."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        await send_text(chat, user, "write code")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        # Default: empty string (no file_policy set in session)
        assert ctx.file_policy == ""


async def test_context_hash_changes_with_file_policy():
    """Context hash should differ when file_policy changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], project_id="", working_dir="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, file_policy="").context_hash
    hash2 = ResolvedExecutionContext(**_d, file_policy="inspect").context_hash
    assert hash1 != hash2


async def test_context_hash_changes_with_working_dir():
    """Context hash should differ when working_dir changes."""
    from app.execution_context import ResolvedExecutionContext
    _d = dict(role="role", active_skills=["skill"], skill_digests={}, provider_config_digest="", execution_config_digest="", base_extra_dirs=[], project_id="", file_policy="", provider_name="")
    hash1 = ResolvedExecutionContext(**_d, working_dir="").context_hash
    hash2 = ResolvedExecutionContext(**_d, working_dir="/opt/frontend").context_hash
    assert hash1 != hash2
    hash3 = ResolvedExecutionContext(**_d, working_dir="/opt/backend").context_hash
    assert hash2 != hash3


# ===========================================================================
# /model command + settings inline keyboard
# ===========================================================================

_PROFILES = {"fast": "claude-haiku-4-5-20251001", "balanced": "claude-sonnet-4-6", "best": "claude-opus-4-6"}

async def test_model_command_shows_profiles():
    """/model with no args shows current profile and inline buttons."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = msg.replies[-1]
        assert "balanced" in reply.get("text", "")
        # Should have inline keyboard buttons
        markup = reply.get("reply_markup")
        assert markup is not None


async def test_model_command_switches_profile():
    """/model fast should switch the session model profile."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["fast"])
        reply = last_reply(msg)
        assert "fast" in reply.lower()
        session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session.get("model_profile") == "fast"


async def test_model_command_no_profiles_configured():
    """/model should say no profiles if none configured."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert "no model profiles" in reply.lower()


async def test_settings_callback_model():
    """Inline button setting_model:fast should switch model profile."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_model:fast")
        session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session.get("model_profile") == "fast"


async def test_settings_callback_approval():
    """Inline button setting_approval:off should change approval mode."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_approval:off")
        session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session.get("approval_mode") == "off"


async def test_settings_callback_compact():
    """Inline button setting_compact:on should enable compact mode."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_compact:on")
        session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session.get("compact_mode") is True


async def test_settings_callback_policy():
    """Inline button setting_policy:inspect should change file policy."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, _ = await send_callback(th.handle_settings_callback, chat, user, "setting_policy:inspect")
        session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session.get("file_policy") == "inspect"


async def test_compact_change_does_not_reset_provider_state():
    """Changing compact mode via callback must not reset provider_state."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        prov.run_results = [RunResult(text="ok", provider_state_updates={"started": True})]
        await send_text(chat, user, "hi")
        await drain_one_worker_item(data_dir)
        session_before = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session_before["provider_state"].get("started") is True
        await send_callback(th.handle_settings_callback, chat, user, "setting_compact:on")
        session_after = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert session_after["provider_state"].get("started") is True
        assert session_after.get("compact_mode") is True


async def test_settings_command_shows_current_values():
    """/settings shows current project, model, policy, compact, approval and inline controls."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import get_callback_data_values
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myapp", proj_dir, ()),),
            "model_profiles": {"fast": "claude-3-5-haiku", "balanced": "claude-sonnet-4-6"},
            "default_model_profile": "balanced",
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(th.cmd_settings, chat, user, "/settings")
            reply = msg.replies[-1]
            text = reply.get("text", "")
            assert "Chat settings" in text
            assert "Project" in text
            assert "Model profile" in text
            assert "File policy" in text
            assert "Compact mode" in text
            assert "Approval mode" in text
            cbs = get_callback_data_values(reply)
            assert any(cb.startswith("setting_project:") for cb in cbs)
            assert any(cb.startswith("setting_model:") for cb in cbs)
            assert "setting_policy:inspect" in cbs
            assert "setting_policy:edit" in cbs
            assert "setting_compact:on" in cbs
            assert "setting_compact:off" in cbs
            assert "setting_approval:on" in cbs
            assert "setting_approval:off" in cbs
            from app.user_messages import settings_use_buttons_hint
            assert settings_use_buttons_hint() in text


async def test_project_default_shows_inline_keyboard():
    """/project with no args shows inline project selection when projects configured."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import get_callback_data_values
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("backend", proj_dir, ()), ("frontend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = msg.replies[-1]
            cbs = get_callback_data_values(reply)
            assert "setting_project:backend" in cbs
            assert "setting_project:frontend" in cbs
            # Clear button only when a project is active
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "backend"])
            msg2 = await send_command(th.cmd_project, chat, user, "/project")
            cbs2 = get_callback_data_values(msg2.replies[-1])
            assert "setting_project:clear" in cbs2


async def test_project_includes_next_step_hint():
    """Phase 14: /project (with projects) includes actionability hint (buttons or /project list)."""
    import app.channels.telegram.ingress as th
    from app.user_messages import project_use_buttons_or_list_hint
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("backend", proj_dir, ()), ("frontend", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            msg = await send_command(th.cmd_project, chat, user, "/project")
            reply = last_reply(msg)
            assert project_use_buttons_or_list_hint() in reply
            assert "buttons below" in reply or "project list" in reply.lower()


async def test_project_no_projects_shows_no_projects_configured():
    """Phase 14 follow-up: /project when no projects configured shows truthful message, not /project list hint."""
    import app.channels.telegram.ingress as th
    from app.user_messages import no_projects_configured
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_project, chat, user, "/project")
        reply = last_reply(msg)
        assert no_projects_configured() in reply
        assert "/project list" not in reply, "Must not point to /project list when no projects configured"


async def test_project_use_no_projects_shows_no_projects_configured():
    """Phase 14: /project use <name> with no projects returns no-projects message, not unknown-project."""
    import app.channels.telegram.ingress as th
    from app.user_messages import no_projects_configured
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "anything"])
        reply = last_reply(msg)
        assert no_projects_configured() in reply, (
            "/project use with no projects must say no-projects-configured, not unknown-project"
        )


async def test_project_clear_no_projects_shows_no_projects_configured():
    """Phase 14: /project clear with no projects returns no-projects message."""
    import app.channels.telegram.ingress as th
    from app.user_messages import no_projects_configured
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["clear"])
        reply = last_reply(msg)
        assert no_projects_configured() in reply, (
            "/project clear with no projects must say no-projects-configured"
        )


async def test_settings_callback_project_use():
    """setting_project:<name> callback switches project and resets provider state."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("myproj", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, user, "hi")
            await drain_one_worker_item(data_dir)
            query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:myproj")
            session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
            assert session["project_id"] == "myproj"
            assert session["provider_state"].get("started") is not True
            edit = cb_msg.replies[-1].get("edit_text", "")
            assert "Switched to project" in edit
            assert "myproj" in edit


async def test_settings_callback_project_clear():
    """setting_project:clear callback clears project and resets provider state."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("p1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            await send_command(th.cmd_project, chat, user, "/project", args=["use", "p1"])
            query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:clear")
            session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
            assert session.get("project_id", "") == ""
            edit = cb_msg.replies[-1].get("edit_text", "")
            assert "Project cleared" in edit


async def test_settings_command_minimal_config_shows_compact_approval_only():
    """Phase 14: /settings with no projects and no model profiles shows only compact/approval buttons."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        reply = last_reply(msg)
        assert "Chat settings" in reply
        # Should still show compact and approval
        assert "Compact mode" in reply
        assert "Approval mode" in reply
        # Keyboard should have compact and approval buttons but no model/project
        markup = msg.replies[-1].get("reply_markup")
        assert markup is not None, "/settings must always have inline keyboard"
        all_data = []
        for row in markup.inline_keyboard:
            for btn in row:
                all_data.append(btn.callback_data)
        assert any("setting_compact:" in d for d in all_data), "Must have compact buttons"
        assert any("setting_approval:" in d for d in all_data), "Must have approval buttons"
        assert not any("setting_model:" in d for d in all_data), (
            "Must not have model buttons when no profiles configured"
        )
        assert not any("setting_project:" in d for d in all_data), (
            "Must not have project buttons when no projects configured"
        )


async def test_settings_callback_model_no_profiles_configured():
    """Phase 14: setting_model:* callback with no model profiles returns no-profiles message."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    from app.user_messages import trust_no_model_profiles
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_model:anything")
        edit = cb_msg.replies[-1].get("edit_text", "")
        assert trust_no_model_profiles() in edit, (
            "Callback setting_model:* with no profiles must say no-model-profiles"
        )


async def test_settings_callback_project_no_projects_configured():
    """Phase 14: setting_project:* callback with no projects returns no-projects message, not mutation."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    from app.user_messages import no_projects_configured
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:anything")
        edit = cb_msg.replies[-1].get("edit_text", "")
        assert no_projects_configured() in edit, (
            "Callback setting_project:* with no projects must say no-projects-configured"
        )


async def test_settings_callback_project_clear_no_projects_no_mutation():
    """Phase 14: setting_project:clear with no projects must not clear persisted project_id."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    from app.storage import default_session, save_session
    from app.user_messages import no_projects_configured
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["project_id"] = "stale_project"
        save_session(data_dir, telegram_conversation_key(1), session)
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_project:clear")
        edit = cb_msg.replies[-1].get("edit_text", "")
        assert no_projects_configured() in edit
        reloaded = load_session_disk(data_dir, telegram_conversation_key(1), prov)
        assert reloaded.get("project_id") == "stale_project", (
            "Callback must not mutate session when projects are disabled"
        )


async def test_public_settings_shows_managed_and_no_project_policy_buttons():
    """Bucket D: public user /settings shows managed message and no project/policy buttons."""
    import app.channels.telegram.ingress as th
    from app.user_messages import trust_settings_managed_public

    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-fast", "balanced": "claude-balanced"},
        public_model_profiles=frozenset({"fast"}),
        projects=(("proj1", "/tmp/proj1", ()),),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        text = msg.replies[0]["text"]
        assert trust_settings_managed_public() in text
        cbs = get_callback_data_values(msg.replies[0])
        assert not any(cb.startswith("setting_project:") for cb in cbs)
        assert "setting_policy:inspect" not in cbs
        assert "setting_policy:edit" not in cbs
        assert any(cb.startswith("setting_model:") for cb in cbs)


async def test_public_settings_model_text_and_button_agree_when_default_restricted():
    """Bucket D follow-up: public /settings shows same profile in text and as selected button.

    When default_model_profile is restricted (e.g. balanced) and public only has fast,
    the screen must show Model profile: fast and the fast button must be checked.
    """
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "m1", "balanced": "m2"},
        default_model_profile="balanced",
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        reply = msg.replies[0]
        text = reply["text"]
        assert "Model profile:" in text
        assert "fast" in text
        cbs = get_callback_data_values(reply)
        assert "setting_model:fast" in cbs
        assert not any(cb.startswith("setting_model:") and cb != "setting_model:fast" for cb in cbs)
        markup = reply.get("reply_markup")
        assert markup is not None
        checkmark = "\u2705"
        for row in markup.inline_keyboard:
            for btn in row:
                if getattr(btn, "callback_data", None) == "setting_model:fast":
                    assert btn.text.startswith(checkmark), "fast button must be selected (checkmark)"
                    return
        assert False, "setting_model:fast button not found"


async def test_public_session_shows_resolved_and_managed_message():
    """Bucket D: public user /session shows resolved context and operator-managed message."""
    import app.channels.telegram.ingress as th
    from app.user_messages import trust_settings_managed_public

    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-fast"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        text = msg.replies[0]["text"]
        assert trust_settings_managed_public() in text
        assert "inspect" in text
        assert "Working dir" in text or "Provider" in text


async def test_public_model_shows_only_public_profiles():
    """Bucket D: public user /model shows only public_model_profiles in buttons."""
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "m1", "balanced": "m2", "best": "m3"},
        default_model_profile="balanced",
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        cbs = get_callback_data_values(msg.replies[0])
        model_buttons = [c for c in cbs if c.startswith("setting_model:")]
        assert len(model_buttons) == 1
        assert "setting_model:fast" in model_buttons


async def test_model_includes_choose_profile_hint():
    """Phase 14: /model (with profiles) includes selection hint."""
    import app.channels.telegram.ingress as th
    from app.user_messages import model_choose_profile_hint
    with fresh_env(config_overrides={
        "model_profiles": {"fast": "m1", "balanced": "m2"},
        "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert model_choose_profile_hint() in reply


async def test_settings_callback_policy_denial_public():
    """Bucket D: public user clicking policy button gets trust_file_policy_public (command/callback parity)."""
    import app.channels.telegram.ingress as th
    from app.user_messages import trust_file_policy_public

    with fresh_env(config_overrides=public_user_config_overrides()) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        await send_command(th.cmd_settings, chat, user, "/settings")
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("setting_policy:edit", message=cb_msg)
        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_settings_callback(update, FakeContext())
        edit_text = cb_msg.replies[-1].get("edit_text", "")
        assert edit_text == trust_file_policy_public()


async def test_settings_callback_project_denial_public():
    """Bucket D: public user clicking project button gets trust_project_public (command/callback parity)."""
    import app.channels.telegram.ingress as th
    from app.user_messages import trust_project_public

    with fresh_env(config_overrides=public_user_config_overrides(
        projects=(("aproj", "/tmp/a", ()),),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        await send_command(th.cmd_settings, chat, user, "/settings")
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("setting_project:aproj", message=cb_msg)
        update = FakeUpdate(user=user, chat=chat, callback_query=query)
        await th.handle_settings_callback(update, FakeContext())
        edit_text = cb_msg.replies[-1].get("edit_text", "")
        assert edit_text == trust_project_public()


async def test_settings_callback_project_clears_pending():
    """Project change via callback clears pending approval/retry."""
    import app.channels.telegram.ingress as th
    from tests.support.handler_support import send_callback
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides={
            "projects": (("proj1", proj_dir, ()),),
        }) as (data_dir, cfg, prov):
            chat = FakeChat(1)
            user = FakeUser(42)
            session = default_session("claude", prov.new_provider_state(), "on")
            session["pending_approval"] = {"prompt": "do it", "created_at": 0}
            save_session(data_dir, telegram_conversation_key(1), session)
            await send_callback(th.handle_settings_callback, chat, user, "setting_project:proj1")
            session = load_session_disk(data_dir, telegram_conversation_key(1), prov)
            assert session.get("pending_approval") is None and session.get("pending_retry") is None


async def test_session_shows_model_profile():
    """/session should display the model profile and effective model."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": _PROFILES, "default_model_profile": "balanced",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "balanced" in reply
        assert "claude-sonnet-4-6" in reply


async def test_session_shows_prompt_weight():
    """/session should display prompt weight estimate."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "Prompt weight" in reply


async def test_session_includes_control_surface_hint_trusted():
    """Phase 14: /session for trusted user includes pointer to /settings, /project, /model (chat settings)."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {"fast": "m1", "balanced": "m2"},
        "default_model_profile": "balanced",
        "projects": (("testproj", "/tmp", ()),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "change chat settings" in reply
        assert "/settings" in reply
        assert "/project" in reply
        assert "/model" in reply


async def test_session_hint_minimal_config_shows_settings_only():
    """Phase 14: /session with no projects and no model profiles shows only /settings."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={}) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "change chat settings" in reply
        assert "/settings" in reply
        assert "/model" not in reply, (
            "/session hint must not advertise /model when no model profiles configured"
        )
        assert "/project" not in reply, (
            "/session hint must not advertise /project when no projects configured"
        )


async def test_session_control_surface_hint_trusted_no_projects_omits_project():
    """Phase 14: /session for trusted user with no projects omits /project from hint."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {"fast": "m1"},
        "default_model_profile": "fast",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "change chat settings" in reply
        assert "/settings" in reply
        assert "/model" in reply
        assert "/project" not in reply, (
            "Trusted user with no projects must not see /project in hint"
        )


async def test_session_control_surface_hint_public_no_project():
    """Phase 14: /session for public user must not advertise /project; hint says change chat settings."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "m1"},
        public_model_profiles=frozenset({"fast"}),
        projects=(("proj1", "/tmp/p1", ()),),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(999)
        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "change chat settings" in reply
        assert "/settings" in reply
        assert "/model" in reply
        assert "/project" not in reply, (
            "Public user must not see /project in session hint"
        )


# -- Re-homed from test_request_flow: handler-channel /session, /settings, /model, callbacks ---

async def test_session_command_shows_public_context():
    """/session display reflects public-user restrictions (resolved context)."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides=public_user_config_overrides(public_working_dir="/tmp/public-sandbox")) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        msg = await send_command(th.cmd_session, chat, stranger, "/session")
        reply = last_reply(msg)
        assert "/tmp/public-sandbox" in reply
        assert "inspect" in reply.lower()


async def test_skills_command_hides_unresolvable_session_skills():
    """/skills display must use resolved active skills, not stale raw session.active_skills."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42, username="owner")
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["active_skills"] = ["code-review", "missing-skill"]
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        msg = await send_command(th.cmd_skills, chat, user, "/skills")
        reply = last_reply(msg)
        assert "Code Review" in reply
        assert "missing-skill" not in reply


async def test_settings_command_public_user_no_trusted_leak():
    """/settings for public user must not leak trusted project/path; use resolved context."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides=public_user_config_overrides(
            public_working_dir="/tmp/public-sandbox",
            projects=(("secret", proj_dir, ()),),
        )) as (data_dir, cfg, prov):
            chat = FakeChat(12345)
            trusted_user = FakeUser(uid=42, username="owner")
            stranger = FakeUser(uid=999, username="nobody")
            await send_command(th.cmd_project, chat, trusted_user, "/project", args=["use", "secret"])
            msg = await send_command(th.cmd_settings, chat, stranger, "/settings")
            reply = last_reply(msg)
            assert "/tmp/public-sandbox" in reply
            assert "inspect" in reply.lower()
            assert proj_dir not in reply
            assert "secret" not in reply
            assert "No project" in reply


async def test_settings_command_public_user_keyboard_no_project_or_policy():
    """/settings keyboard for public user must not include setting_project:* or setting_policy:*."""
    import app.channels.telegram.ingress as th
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides=public_user_config_overrides(
            public_working_dir="/tmp/pub",
            projects=(("myproj", proj_dir, ()),),
            model_profiles={"fast": "claude-haiku", "best": "claude-opus"},
            public_model_profiles=frozenset({"fast"}),
        )) as (data_dir, cfg, prov):
            chat = FakeChat(12345)
            stranger = FakeUser(uid=999, username="nobody")
            msg = await send_command(th.cmd_settings, chat, stranger, "/settings")
            reply = msg.replies[-1]
            cbs = get_callback_data_values(reply)
            assert not any(cb.startswith("setting_project:") for cb in cbs)
            assert not any(cb.startswith("setting_policy:") for cb in cbs)
            assert any(cb.startswith("setting_model:") for cb in cbs)
            assert "setting_compact:on" in cbs or "setting_compact:off" in cbs
            assert "setting_approval:on" in cbs or "setting_approval:off" in cbs


async def test_model_command_public_user_can_switch_to_allowed_profile():
    """/model fast succeeds for public user; reply is exact canonical success message."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        msg = await send_command(th.cmd_model, chat, stranger, "/model fast", args=["fast"])
        reply = last_reply(msg)
        expected = uimsg.trust_model_profile_set("fast", cfg.model_profiles["fast"])
        assert reply == expected


async def test_model_command_public_user_rejected_for_restricted_profile():
    """/model best fails for public user; reply is exact canonical denial message."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        msg = await send_command(th.cmd_model, chat, stranger, "/model best", args=["best"])
        reply = last_reply(msg)
        expected = uimsg.trust_model_profile_not_available("best", ["fast"])
        assert reply == expected


async def test_model_callback_public_user_rejected_for_restricted_profile():
    """setting_model:best callback fails for public user; edit_text is exact canonical denial."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:best")
        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        assert edit_texts
        expected = uimsg.trust_model_profile_not_available("best", ["fast"])
        assert edit_texts[-1] == expected


async def test_model_callback_public_user_allowed_for_available_profile():
    """setting_model:fast callback succeeds for public user; edit_text is exact canonical success."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:fast")
        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        assert edit_texts
        expected = uimsg.trust_model_profile_set("fast", cfg.model_profiles["fast"])
        assert edit_texts[-1] == expected


async def test_model_command_and_callback_same_denial_contract():
    """Parity: /model <restricted> and setting_model:<restricted> produce the same denial message."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku", "best": "claude-opus"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        cmd_msg = await send_command(th.cmd_model, chat, stranger, "/model best", args=["best"])
        cmd_reply = last_reply(cmd_msg)
        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:best")
        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        assert edit_texts
        cb_denial = edit_texts[-1]
        assert cmd_reply == cb_denial == uimsg.trust_model_profile_not_available("best", ["fast"])


async def test_model_command_and_callback_same_success_contract():
    """Parity: /model <allowed> and setting_model:<allowed> produce the same success message."""
    import app.channels.telegram.ingress as th
    from app import user_messages as uimsg
    with fresh_env(config_overrides=public_user_config_overrides(
        model_profiles={"fast": "claude-haiku", "best": "claude-opus"},
        public_model_profiles=frozenset({"fast"}),
    )) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")
        cmd_msg = await send_command(th.cmd_model, chat, stranger, "/model fast", args=["fast"])
        cmd_reply = last_reply(cmd_msg)
        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:fast")
        edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
        assert edit_texts
        cb_success = edit_texts[-1]
        expected = uimsg.trust_model_profile_set("fast", cfg.model_profiles["fast"])
        assert cmd_reply == cb_success == expected


async def test_project_callback_public_user_denied():
    """setting_project:<name> callback is denied for public user; edit_text equals trust_project_public()."""
    import app.channels.telegram.ingress as th
    from app.user_messages import trust_project_public
    with tempfile.TemporaryDirectory() as proj_dir:
        with fresh_env(config_overrides=public_user_config_overrides(
            projects=(("myproj", proj_dir, ()),),
        )) as (data_dir, cfg, prov):
            chat = FakeChat(12345)
            stranger = FakeUser(uid=999, username="nobody")
            query, cb_msg = await send_callback(
                th.handle_settings_callback, chat, stranger, "setting_project:myproj")
            edit_texts = [r.get("edit_text", "") for r in cb_msg.replies if r.get("edit_text")]
            assert edit_texts
            assert edit_texts[-1] == trust_project_public()


# -- Handler edge cases (from test_edge_sessions.py, test_edge_providers.py) --


async def test_empty_message_ignored():
    """Empty text message should not trigger provider."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        await send_text(chat, user, "")
        assert len(prov.run_calls) == 0


async def test_session_codex_shows_thread():
    """/session with codex provider shows thread info."""
    import app.channels.telegram.ingress as th
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        msg = await send_command(th.cmd_session, chat, user, "/session")
        reply = last_reply(msg)
        assert "Thread" in reply


async def test_message_after_new_gets_fresh_session():
    """/new then message should use fresh provider_state, not stale."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")

        prov.run_results = [
            RunResult(text="first response", provider_state_updates={"started": True}),
        ]
        await send_text(chat, user, "first message")
        await drain_one_worker_item(data_dir)
        session1 = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session1["provider_state"]["started"] is True

        # Reset
        await send_command(th.cmd_new, chat, user, "/new")
        session2 = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert session2["provider_state"]["started"] is False

        # Send another message
        prov.run_results = [
            RunResult(text="second response", provider_state_updates={"started": True}),
        ]
        await send_text(chat, user, "second message")
        await drain_one_worker_item(data_dir)
        assert len(prov.run_calls) == 2
        second_call = prov.run_calls[1]
        assert second_call["provider_state"]["started"] is False


async def test_provider_empty_response():
    """Provider returning empty text should not crash."""
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        prov.run_results = [RunResult(text="")]

        await send_text(chat, user, "hello")
        await drain_one_worker_item(data_dir)
        assert len(prov.run_calls) == 1


# =====================================================================
# Phase 15: Project-level inheritance in commands
# =====================================================================

from app.session_state import ProjectBinding


async def test_policy_status_shows_project_default():
    """/policy status reflects project-inherited file_policy when session has none."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project with inspect default
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Check /policy status — should show inspect (inherited from project)
        msg = await send_command(th.cmd_policy, chat, user, "/policy")
        reply = last_reply(msg)
        assert "inspect" in reply


async def test_policy_status_session_overrides_project():
    """/policy status shows session-explicit value even if project has a different default."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project with inspect default
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Explicitly set edit
        await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        # Check /policy status — should show edit (session explicit wins)
        msg = await send_command(th.cmd_policy, chat, user, "/policy")
        reply = last_reply(msg)
        assert "edit" in reply


async def test_project_switch_shows_inherited_defaults():
    """Project switch confirmation message includes inherited file_policy and model_profile."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect", model_profile="fast"),),
        "model_profiles": {"fast": "haiku", "best": "opus"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        reply = last_reply(msg)
        assert "inspect" in reply, "Switch message should mention project default policy"
        assert "fast" in reply, "Switch message should mention project default model"


async def test_project_switch_no_defaults_no_extra_lines():
    """Project with no inherited defaults shows basic switch message."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        reply = last_reply(msg)
        assert "default policy" not in reply.lower()
        assert "default model" not in reply.lower()


async def test_model_status_shows_project_default():
    """/model status reflects project-inherited model_profile when session has none."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        "model_profiles": {"fast": "haiku", "best": "opus"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project with fast default
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Check /model status — should show fast profile with haiku model
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert "fast" in reply, "Model status should show project-inherited profile"
        assert "haiku" in reply, "Model status should show effective model from project default"


async def test_policy_same_as_project_default_shows_already():
    """/policy inspect when project default is inspect and session has no override → already message."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Try to set inspect — should say "already" since project default is inspect
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["inspect"])
        reply = last_reply(msg)
        assert "already" in reply.lower()


async def test_policy_inherit_clears_session_override():
    """/policy inherit clears session-explicit policy, falls back to project default."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Explicitly set edit
        await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        # Inherit — should clear to project default
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["inherit"])
        reply = last_reply(msg)
        assert "cleared" in reply.lower()
        assert "inspect" in reply  # effective is project default


async def test_policy_inherit_already_inherited():
    """/policy inherit when already inherited shows already-inherited."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["inherit"])
        reply = last_reply(msg)
        assert "already" in reply.lower()


async def test_model_inherit_clears_session_override():
    """/model inherit clears session-explicit model_profile, falls back to project default."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        "model_profiles": {"fast": "haiku", "best": "opus"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Explicitly set best
        await send_command(th.cmd_model, chat, user, "/model", args=["best"])
        # Inherit — should clear to project default
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["inherit"])
        reply = last_reply(msg)
        assert "cleared" in reply.lower()
        assert "fast" in reply  # effective is project default
        assert "haiku" in reply  # effective model ID


async def test_model_inherit_already_inherited():
    """/model inherit when already inherited shows already-inherited."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {"fast": "haiku"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["inherit"])
        reply = last_reply(msg)
        assert "already" in reply.lower()


# =====================================================================
# Finding fixes: inherit guard + callback parity
# =====================================================================


async def test_model_inherit_works_when_no_profiles_configured():
    """/model inherit clears stale override even when model_profiles is empty."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Manually set a stale model_profile override
        session = telegram_load_session(current_runtime(), 1001)
        session.model_profile = "fast"
        telegram_save_session(current_runtime(), 1001, session)
        # /model inherit should clear it even with no profiles
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["inherit"])
        reply = last_reply(msg)
        assert "cleared" in reply.lower()
        # Verify the override is gone
        session = telegram_load_session(current_runtime(), 1001)
        assert session.model_profile == ""


async def test_settings_callback_policy_inherit():
    """setting_policy:inherit callback clears session file_policy override."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        # Set explicit edit
        await send_command(th.cmd_policy, chat, user, "/policy", args=["edit"])
        session = telegram_load_session(current_runtime(), 1001)
        assert session.file_policy == "edit"
        # Send inherit callback
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_policy:inherit")
        reply = last_reply(cb_msg)
        assert "cleared" in reply.lower() or "effective" in reply.lower()
        # Verify override cleared
        session = telegram_load_session(current_runtime(), 1001)
        assert session.file_policy == ""


async def test_settings_callback_model_inherit():
    """setting_model:inherit callback clears session model_profile override."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "projects": (ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        "model_profiles": {"fast": "haiku", "best": "opus"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Switch to project, set explicit best
        await send_command(th.cmd_project, chat, user, "/project", args=["use", "fe"])
        await send_command(th.cmd_model, chat, user, "/model", args=["best"])
        session = telegram_load_session(current_runtime(), 1001)
        assert session.model_profile == "best"
        # Send inherit callback
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_model:inherit")
        reply = last_reply(cb_msg)
        assert "cleared" in reply.lower()
        session = telegram_load_session(current_runtime(), 1001)
        assert session.model_profile == ""


async def test_settings_callback_policy_inherit_already():
    """setting_policy:inherit when already inherited shows already message."""
    import app.channels.telegram.ingress as th
    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_policy:inherit")
        reply = last_reply(cb_msg)
        assert "already" in reply.lower()


async def test_settings_callback_model_inherit_already():
    """setting_model:inherit when already inherited shows already message."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {"fast": "haiku"},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_model:inherit")
        reply = last_reply(cb_msg)
        assert "already" in reply.lower()


async def test_policy_buttons_show_inherit_when_override_set():
    """Policy buttons include Inherit button when session has explicit override."""
    from app.channels.telegram.presenters import policy_status

    rendered = policy_status("inspect", has_explicit_override=True)
    buttons = rendered.reply_markup.inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert any("Inherit" in l for l in labels)
    callbacks = [b.callback_data for b in buttons]
    assert "setting_policy:inherit" in callbacks


async def test_policy_buttons_no_inherit_when_no_override():
    """Policy buttons omit Inherit button when no explicit override."""
    from app.channels.telegram.presenters import policy_status

    rendered = policy_status("edit", has_explicit_override=False)
    buttons = rendered.reply_markup.inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert not any("Inherit" in l for l in labels)


async def test_model_buttons_show_inherit_when_override_set():
    """Model buttons include Inherit button when session has explicit override."""
    from app.channels.telegram.presenters import model_profile_status

    rendered = model_profile_status(
        ["fast", "best"],
        "fast",
        "gpt-5.4",
        has_explicit_override=True,
    )
    buttons = rendered.reply_markup.inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert any("Inherit" in l for l in labels)
    callbacks = [b.callback_data for b in buttons]
    assert "setting_model:inherit" in callbacks


async def test_model_buttons_no_inherit_when_no_override():
    """Model buttons omit Inherit button when no explicit override."""
    from app.channels.telegram.presenters import model_profile_status

    rendered = model_profile_status(
        ["fast", "best"],
        "fast",
        "gpt-5.4",
        has_explicit_override=False,
    )
    buttons = rendered.reply_markup.inline_keyboard[0]
    labels = [b.text for b in buttons]
    assert not any("Inherit" in l for l in labels)


# =====================================================================
# Finding fixes: inherit discoverability + double-default rendering
# =====================================================================


async def test_model_no_profiles_with_stale_override_hints_inherit():
    """/model with no profiles but stale override hints /model inherit."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Set stale override
        session = telegram_load_session(current_runtime(), 1001)
        session.model_profile = "fast"
        telegram_save_session(current_runtime(), 1001, session)
        # /model should mention inherit, not just "no profiles configured"
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert "inherit" in reply.lower()
        assert "fast" in reply  # mentions the stale override


async def test_model_no_profiles_no_override_shows_standard_message():
    """/model with no profiles and no stale override shows standard message."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        msg = await send_command(th.cmd_model, chat, user, "/model")
        reply = last_reply(msg)
        assert "inherit" not in reply.lower()


async def test_settings_shows_inherit_button_when_stale_model_override():
    """/settings renders inherit button when profiles empty but stale override exists."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Set stale override
        session = telegram_load_session(current_runtime(), 1001)
        session.model_profile = "fast"
        telegram_save_session(current_runtime(), 1001, session)
        # /settings should show an inherit button
        msg = await send_command(th.cmd_settings, chat, user, "/settings")
        # Check keyboard for inherit callback
        markup = msg.replies[-1].get("reply_markup")
        assert markup is not None
        all_callbacks = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        assert "setting_model:inherit" in all_callbacks


async def test_model_inherit_no_double_default():
    """/model inherit does not render '(default) ((default))'."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Set stale override
        session = telegram_load_session(current_runtime(), 1001)
        session.model_profile = "fast"
        telegram_save_session(current_runtime(), 1001, session)
        # /model inherit
        msg = await send_command(th.cmd_model, chat, user, "/model", args=["inherit"])
        reply = last_reply(msg)
        assert "cleared" in reply.lower()
        assert "((default))" not in reply
        assert "(default) (" not in reply


async def test_settings_callback_model_inherit_no_double_default():
    """setting_model:inherit callback does not render double default."""
    import app.channels.telegram.ingress as th
    with fresh_env(config_overrides={
        "model_profiles": {},
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=1001)
        user = FakeUser(uid=42, username="testuser")
        # Set stale override
        session = telegram_load_session(current_runtime(), 1001)
        session.model_profile = "fast"
        telegram_save_session(current_runtime(), 1001, session)
        # Callback inherit
        query, cb_msg = await send_callback(th.handle_settings_callback, chat, user, "setting_model:inherit")
        reply = last_reply(cb_msg)
        assert "cleared" in reply.lower()
        assert "((default))" not in reply
        assert "(default) (" not in reply


async def test_allowuser_grants_access_without_restart():
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({1, 100}),
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=12345)
        admin = FakeUser(uid=1, username="admin")
        stranger = FakeUser(uid=99999, username="stranger")

        assert th.is_allowed(current_runtime(), stranger) is False
        msg = await send_command(
            th.cmd_allowuser,
            chat,
            admin,
            "/allowuser 99999 incident access",
            args=["99999", "incident", "access"],
        )
        assert last_reply(msg) == "Actor tg:99999 added to allowed list."
        assert th.is_allowed(current_runtime(), stranger) is True

        await send_text(chat, stranger, "hello after allow")
        await drain_one_worker_item(data_dir)
        assert len(prov.run_calls) == 1


async def test_blockuser_blocks_allowed_user_without_restart():
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({1, 100}),
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=12345)
        admin = FakeUser(uid=1, username="admin")
        target = FakeUser(uid=100, username="trusted")

        assert th.is_allowed(current_runtime(), target) is True
        msg = await send_command(
            th.cmd_blockuser,
            chat,
            admin,
            "/blockuser 100 abuse",
            args=["100", "abuse"],
        )
        assert last_reply(msg) == "Actor tg:100 blocked."
        assert th.is_allowed(current_runtime(), target) is False

        await send_text(chat, target, "hello after block")
        assert len(prov.run_calls) == 0


async def test_listaccess_shows_rows():
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({1}),
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        del data_dir, cfg, prov
        chat = FakeChat(chat_id=12345)
        admin = FakeUser(uid=1, username="admin")

        await send_command(th.cmd_allowuser, chat, admin, "/allowuser 99999 temp", args=["99999", "temp"])
        await send_command(th.cmd_blockuser, chat, admin, "/blockuser 100 policy", args=["100", "policy"])
        msg = await send_command(th.cmd_listaccess, chat, admin, "/listaccess")

        reply = last_reply(msg)
        assert "Access overrides" in reply
        assert "99999" in reply
        assert "allowed" in reply
        assert "100" in reply
        assert "blocked" in reply
        assert msg.replies[-1]["parse_mode"] == "HTML"


@pytest.mark.parametrize("handler_name", ["cmd_allowuser", "cmd_blockuser"])
async def test_access_commands_reject_non_admin(handler_name):
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        del data_dir, cfg, prov
        chat = FakeChat(chat_id=12345)
        non_admin = FakeUser(uid=42, username="member")
        handler = getattr(th, handler_name)
        msg = await send_command(handler, chat, non_admin, "/access", args=["100"])
        assert last_reply(msg) == "This command requires admin access."


async def test_allowuser_usage_hint_for_missing_arg():
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({1}),
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        del data_dir, cfg, prov
        chat = FakeChat(chat_id=12345)
        admin = FakeUser(uid=1, username="admin")
        msg = await send_command(th.cmd_allowuser, chat, admin, "/allowuser", args=[])
        assert last_reply(msg) == "Usage: /allowuser <actor_key|user_id> [reason]"


@pytest.mark.parametrize(
    ("arg", "expected_actor"),
    [("abc", "abc"), ("42x", "42x"), ("99999", "tg:99999")],
)
async def test_allowuser_accepts_actor_keys_and_user_ids(arg, expected_actor):
    import app.channels.telegram.ingress as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({1}),
        "admin_user_ids": frozenset({1}),
    }) as (data_dir, cfg, prov):
        del data_dir, cfg, prov
        chat = FakeChat(chat_id=12345)
        admin = FakeUser(uid=1, username="admin")
        msg = await send_command(th.cmd_allowuser, chat, admin, f"/allowuser {arg}", args=[arg])
        assert last_reply(msg) == f"Actor {expected_actor} added to allowed list."
