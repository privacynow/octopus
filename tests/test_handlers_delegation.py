import time

from octopus_sdk.identity import telegram_conversation_ref
from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.agent_directory import AuthorityResolution
from octopus_sdk.providers import RunResult
from octopus_sdk.registry.models import CoordinationActionResult, DelegationIntent, DelegationTaskDraft, TargetSelector
from app.storage import default_session, save_session
from tests.support.config_support import make_registry_connection
from tests.support.handler_support import (
    current_runtime,
    current_bot_instance,
    drain_one_worker_item,
    fresh_env,
    last_reply,
    load_session_disk,
    send_callback,
    send_text,
)


def _coordination_intent(*, title="Feature delegation", target_agent_id="developer-1", instructions="Build the feature end to end."):
    return DelegationIntent(
        title=title,
        resume_instruction="Continue after the delegated tasks return.",
        tasks=[
            DelegationTaskDraft(
                draft_id="task-1",
                selector=TargetSelector(kind="agent", value=target_agent_id, preferred_agent_id=target_agent_id),
                title="Implement feature",
                instructions=instructions,
            )
        ],
    )


async def test_execute_request_proposes_delegation_and_persists_pending_delegation(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_publish_level": "off",
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_create_conversation(**kwargs):
            del kwargs
            return "conversation-1"

        async def fake_submit_action(*, conversation_id, envelope):
            assert conversation_id == "conversation-1"
            assert envelope.action == "delegate_tasks"
            assert envelope.payload["origin_transport_ref"] == telegram_conversation_ref(cfg, chat.id)
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
            )

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "create_conversation",
            fake_create_conversation,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        async def fake_resolve_target_authority(*, target_agent_id):
            assert target_agent_id == "developer-1"
            return AuthorityResolution(status="resolved", authority_ref="registry:default")

        monkeypatch.setattr(
            current_runtime().services.control_plane.agent_directory,
            "resolve_target_authority",
            fake_resolve_target_authority,
        )

        chat = FakeChat()
        user = FakeUser()
        prov.run_results = [
            RunResult(
                text="",
                coordination_intent=_coordination_intent(),
            )
        ]

        msg = await send_text(chat, user, "Ship the feature.")
        assert await drain_one_worker_item(data_dir) is True

        session = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session.get("pending_delegation")
        assert pending is not None
        assert pending["proposal_id"] == "proposal-1"
        assert pending["conversation_ref"] == "conversation-1"
        assert [task["status"] for task in pending["tasks"]] == ["proposed"]
        assert [task["instructions"] for task in pending["tasks"]] == ["Build the feature end to end."]
        rendered_messages = list(msg.replies) + list(current_bot_instance().sent_messages)
        assert any(
            "<b>Delegation plan</b>" in message.get("text", "")
            and "ready via" in message.get("text", "")
            and message.get("reply_markup") is not None
            for message in rendered_messages
        )


async def test_telegram_delegation_approve_callback_submits_tasks_and_updates_session(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_publish_level": "off",
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        submitted = []

        async def fake_submit_action(*, conversation_id, envelope):
            submitted.append((conversation_id, envelope))
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
                routed_tasks=[
                    {
                        "routed_task_id": "server-task-1",
                        "target_agent_id": "developer-1",
                        "authority_ref": "",
                        "title": "Implement feature",
                        "status": "queued",
                    }
                ],
            )

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "status": "proposed",
            "title": "Feature delegation",
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session_after.get("pending_delegation")
        assert len(submitted) == 1
        conversation_id, envelope = submitted[0]
        assert conversation_id == "conversation-1"
        assert envelope.action == "delegation_approve"
        assert pending is not None
        assert pending["status"] == "submitted"
        assert pending["tasks"][0]["routed_task_id"] == "server-task-1"
        assert pending["tasks"][0]["status"] == "submitted"
        assert "Delegation approved. Specialist requests were sent." in last_reply(msg)
        assert query.answered is True


async def test_telegram_delegation_cancel_callback_clears_session_and_does_not_submit(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_submit_action(*, conversation_id, envelope):
            called.append((conversation_id, envelope))
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
            )

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "title": "Feature delegation",
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_cancel:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        assert len(called) == 1
        assert called[0][0] == "conversation-1"
        assert called[0][1].action == "delegation_cancel"
        assert session_after.get("pending_delegation") is None
        assert "cancelled" in last_reply(msg).lower()
        assert "sent" in last_reply(msg).lower()
        assert query.answered is True


async def test_delegation_approve_degraded_mode_blocks_submission_and_preserves_state(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_submit_action(*, conversation_id, envelope):
            called.append((conversation_id, envelope))
            raise RuntimeError("registry_unreachable")

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "title": "Feature delegation",
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        _, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session_after.get("pending_delegation")
        assert len(called) == 1
        assert pending is not None
        assert pending["tasks"][0]["status"] == "proposed"
        assert "Delegation is unavailable because registry connectivity is degraded." in last_reply(msg)
        assert "could not be reached" in last_reply(msg).lower()
        assert "connecterror" not in last_reply(msg).lower()


async def test_delegation_approve_no_pending_is_a_no_op():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, _, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        chat = FakeChat()
        user = FakeUser()
        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        assert session_after.get("pending_delegation") is None
        assert "nothing" in last_reply(msg).lower()
        assert "approve" in last_reply(msg).lower()
        assert query.answered is True


async def test_delegation_approve_hides_registry_error_text(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_submit_action(*, conversation_id, envelope):
            del conversation_id, envelope
            raise RuntimeError("registry_server_error")

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "title": "Feature delegation",
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        _, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        text = last_reply(msg)
        assert "temporarily unavailable" in text.lower()
        assert "proxy banner" not in text.lower()
        assert "http 503" not in text.lower()


async def test_delegation_approve_rejects_stale_plan_without_submission(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "delegation_timeout_seconds": 3600,
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_submit_action(*, conversation_id, envelope):
            called.append((conversation_id, envelope))
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
            )

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "title": "Feature delegation",
            "created_at": 0.0,
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        _, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session_after.get("pending_delegation")
        assert called == []
        assert pending is not None
        assert pending["status"] == "partial_failed"
        assert pending["tasks"][0]["status"] == "failed"
        assert "Delegation plan expired before approval." in last_reply(msg)


async def test_stale_submitted_delegation_expires_on_next_worker_message():
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "delegation_timeout_seconds": 3600,
        }
    ) as (data_dir, _cfg, prov):
        from tests.support.handler_support import FakeChat, FakeUser

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(_cfg, chat.id),
            "title": "Feature delegation",
            "created_at": 0.0,
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "submitted",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        await send_text(chat, user, "continue please")
        assert await drain_one_worker_item(data_dir) is True

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session_after.get("pending_delegation")
        assert pending is not None
        assert pending["status"] == "partial_failed"
        assert pending["tasks"][0]["status"] == "failed"
        assert "delegation timed out" in pending["tasks"][0]["summary"]


async def test_recently_submitted_delegation_does_not_expire__old_proposal_age(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "delegation_timeout_seconds": 3600,
            "registry_publish_level": "off",
            "registry_agent_ids": {"default": "test-agent", "dev": "test-agent-dev"},
        }
    ) as (data_dir, cfg, prov):
        import app.runtime.telegram_ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_submit_action(*, conversation_id, envelope):
            return CoordinationActionResult(
                conversation_id=conversation_id,
                action_id=envelope.action_id,
                action=envelope.action,
                accepted=True,
                proposal_id="proposal-1",
                routed_tasks=[
                    {
                        "routed_task_id": "server-task-1",
                        "target_agent_id": "developer-1",
                        "authority_ref": "",
                        "title": "Implement feature",
                        "status": "queued",
                    }
                ],
            )

        monkeypatch.setattr(
            current_runtime().services.control_plane.conversation_projection,
            "submit_action",
            fake_submit_action,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state("tg:test"), "off")
        session["pending_delegation"] = {
            "conversation_ref": "conversation-1",
            "proposal_id": "proposal-1",
            "title": "Feature delegation",
            "created_at": time.time() - 3599,
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                }
            ],
        }
        save_session(data_dir, telegram_conversation_key(chat.id), session)

        _, approve_msg = await send_callback(
            th.handle_delegation_callback,
            chat,
            user,
            f"delegation_approve:{chat.id}",
        )

        assert "approved" in last_reply(approve_msg).lower()

        await send_text(chat, user, "continue please")
        assert await drain_one_worker_item(data_dir) is True

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session_after.get("pending_delegation")
        assert pending is not None
        assert pending["status"] == "submitted"
        assert pending["tasks"][0]["status"] == "submitted"
        assert pending["tasks"][0]["submitted_at"] > pending["created_at"]
