import time

from app.identity import telegram_conversation_ref
from app.identity import telegram_conversation_key
from app.ports.agent_directory import AuthorityResolution
from app.ports.task_routing import TaskSubmissionResult
from app.providers.base import RunResult
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


async def test_execute_request_proposes_delegation_and_persists_pending_delegation(monkeypatch):
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_resolve_target_authority(*, target_agent_id):
            if target_agent_id == "developer-1":
                return AuthorityResolution(status="resolved", authority_ref="registry:dev")
            return AuthorityResolution(status="resolved", authority_ref="registry:review")

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
                delegation_title="Feature delegation",
                delegation_resume_instruction="Continue after the delegated tasks return.",
                delegation_tasks=[
                    {
                        "routed_task_id": "task-1",
                        "title": "Implement feature",
                        "target_agent_id": "developer-1",
                        "instructions": "Build the feature end to end.",
                    },
                    {
                        "routed_task_id": "task-2",
                        "title": "Review feature",
                        "target_agent_id": "reviewer-1",
                        "instructions": "Review correctness and risk.",
                    },
                ],
            )
        ]

        await send_text(chat, user, "Ship the feature.")
        assert await drain_one_worker_item(data_dir) is True

        session = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        pending = session.get("pending_delegation")
        assert pending is not None
        assert [task["status"] for task in pending["tasks"]] == ["proposed", "proposed"]
        assert [task["instructions"] for task in pending["tasks"]] == [
            "Build the feature end to end.",
            "Review correctness and risk.",
        ]
        assert any(
            "<b>Delegation plan</b>" in message.get("text", "")
            and "ready via" in message.get("text", "")
            and message.get("reply_markup") is not None
            for message in current_bot_instance().sent_messages
        )


async def test_telegram_delegation_approve_callback_submits_tasks_and_updates_session(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        submitted = []

        async def fake_resolve_target_authority(*, target_agent_id):
            assert target_agent_id == "developer-1"
            return AuthorityResolution(status="resolved", authority_ref="registry:default")

        async def fake_submit_routed_task(*, request, authority_ref):
            submitted.append((request, authority_ref))
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

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
        request, authority_ref = submitted[0]
        assert request.routed_task_id == "task-1"
        assert request.origin_agent_id == ""
        assert request.target_agent_id == "developer-1"
        assert request.instructions == "Build the feature end to end."
        assert authority_ref == "registry:default"
        assert pending is not None
        assert pending["status"] == "submitted"
        assert pending["tasks"][0]["authority_ref"] == "registry:default"
        assert pending["tasks"][0]["status"] == "submitted"
        assert "Delegation approved. 1 request(s) sent to specialist bots." in last_reply(msg)
        assert query.answered is True


async def test_telegram_delegation_cancel_callback_clears_session_and_does_not_submit(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_submit_routed_task(*, request, authority_ref):
            called.append((request, authority_ref))
            return TaskSubmissionResult(status="accepted", routed_task_id=request.routed_task_id)

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "submit_routed_task",
            fake_submit_routed_task,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
        assert called == []
        assert session_after.get("pending_delegation") is None
        assert last_reply(msg) == "Delegation cancelled. No requests were sent."
        assert query.answered is True


async def test_delegation_approve_degraded_mode_blocks_submission_and_preserves_state(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_resolve_target_authority(*, target_agent_id):
            del target_agent_id
            return AuthorityResolution(status="unavailable", error="registry_unreachable")

        async def fake_submit_routed_task(*, request, authority_ref):
            called.append((request, authority_ref))
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

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
        assert called == []
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
        }
    ) as (data_dir, _, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        chat = FakeChat()
        user = FakeUser()
        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, telegram_conversation_key(chat.id), prov)
        assert session_after.get("pending_delegation") is None
        assert last_reply(msg) == "Nothing to approve."
        assert query.answered is True


async def test_delegation_approve_hides_registry_error_text(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_resolve_target_authority(*, target_agent_id):
            del target_agent_id
            return AuthorityResolution(status="resolved", authority_ref="registry:default")

        async def fake_submit_routed_task(*, request, authority_ref):
            del request, authority_ref
            return TaskSubmissionResult(status="failed", error="registry_server_error")

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

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        async def fake_submit_routed_task(*, request, authority_ref):
            called.append((request, authority_ref))
            return TaskSubmissionResult(status="accepted", routed_task_id=request.routed_task_id)

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "submit_routed_task",
            fake_submit_routed_task,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
        session = default_session(prov.name, prov.new_provider_state(), "off")
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


async def test_recently_submitted_delegation_does_not_expire_from_old_proposal_age(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "delegation_timeout_seconds": 3600,
        }
    ) as (data_dir, cfg, prov):
        import app.channels.telegram.ingress as th
        from tests.support.handler_support import FakeChat, FakeUser

        async def fake_submit_routed_task(*, request, authority_ref):
            return TaskSubmissionResult(status="accepted", routed_task_id=request.routed_task_id)

        async def fake_resolve_target_authority(*, target_agent_id):
            return AuthorityResolution(status="resolved", authority_ref="registry:dev")

        monkeypatch.setattr(
            current_runtime().services.control_plane.task_routing,
            "submit_routed_task",
            fake_submit_routed_task,
        )
        monkeypatch.setattr(
            current_runtime().services.control_plane.agent_directory,
            "resolve_target_authority",
            fake_resolve_target_authority,
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": telegram_conversation_ref(cfg, chat.id),
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
