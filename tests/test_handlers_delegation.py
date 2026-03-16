from app.agents.state import AgentRuntimeState, save_agent_runtime_state
from app.providers.base import RunResult
from app.storage import default_session, save_session
from tests.support.handler_support import (
    drain_one_worker_item,
    fresh_env,
    last_reply,
    load_session_disk,
    send_callback,
    send_text,
)


async def test_execute_request_proposes_delegation_and_persists_pending_delegation():
    with fresh_env(
        config_overrides={
            "approval_mode": "off",
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, _, prov):
        import app.telegram_handlers as th
        from tests.support.handler_support import FakeChat, FakeUser

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

        session = load_session_disk(data_dir, chat.id, prov)
        pending = session.get("pending_delegation")
        assert pending is not None
        assert [task["status"] for task in pending["tasks"]] == ["proposed", "proposed"]
        assert [task["instructions"] for task in pending["tasks"]] == [
            "Build the feature end to end.",
            "Review correctness and risk.",
        ]
        assert any(
            "<b>Delegation plan</b>" in message.get("text", "")
            and message.get("reply_markup") is not None
            for message in th._bot_instance.sent_messages
        )


async def test_delegation_approve_submits_tasks_and_updates_session(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, _, prov):
        import app.telegram_handlers as th
        from tests.support.handler_support import FakeChat, FakeUser

        submitted = []

        class FakeRegistryClient:
            async def submit_routed_task(self, request):
                submitted.append(request)
                return {"ok": True}

        monkeypatch.setattr(th, "registry_client", lambda cfg: FakeRegistryClient())
        save_agent_runtime_state(
            data_dir,
            AgentRuntimeState(
                agent_id="origin-agent",
                agent_token="secret",
                connectivity_state="connected",
            ),
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": th.telegram_conversation_ref(th._cfg(), chat.id),
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
        save_session(data_dir, chat.id, session)

        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, chat.id, prov)
        pending = session_after.get("pending_delegation")
        assert len(submitted) == 1
        assert submitted[0].routed_task_id == "task-1"
        assert submitted[0].origin_agent_id == "origin-agent"
        assert submitted[0].target_agent_id == "developer-1"
        assert submitted[0].instructions == "Build the feature end to end."
        assert pending is not None
        assert pending["tasks"][0]["status"] == "submitted"
        assert "Delegation approved. 1 request(s) sent to specialist bots." in last_reply(msg)
        assert query.answered is True


async def test_delegation_cancel_clears_session_and_does_not_submit(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, _, prov):
        import app.telegram_handlers as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        class FakeRegistryClient:
            async def submit_routed_task(self, request):
                called.append(request)
                return {"ok": True}

        monkeypatch.setattr(th, "registry_client", lambda cfg: FakeRegistryClient())

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": th.telegram_conversation_ref(th._cfg(), chat.id),
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
        save_session(data_dir, chat.id, session)

        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_cancel:{chat.id}")

        session_after = load_session_disk(data_dir, chat.id, prov)
        assert called == []
        assert session_after.get("pending_delegation") is None
        assert last_reply(msg) == "Delegation cancelled. No requests were sent."
        assert query.answered is True


async def test_delegation_approve_degraded_mode_blocks_submission_and_preserves_state(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, _, prov):
        import app.telegram_handlers as th
        from tests.support.handler_support import FakeChat, FakeUser

        called = []

        class FakeRegistryClient:
            async def submit_routed_task(self, request):
                called.append(request)
                return {"ok": True}

        monkeypatch.setattr(th, "registry_client", lambda cfg: FakeRegistryClient())
        save_agent_runtime_state(
            data_dir,
            AgentRuntimeState(
                agent_id="origin-agent",
                agent_token="secret",
                connectivity_state="degraded",
                last_error="registry unavailable",
            ),
        )

        chat = FakeChat()
        user = FakeUser()
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": th.telegram_conversation_ref(th._cfg(), chat.id),
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
        save_session(data_dir, chat.id, session)

        _, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, chat.id, prov)
        pending = session_after.get("pending_delegation")
        assert called == []
        assert pending is not None
        assert pending["tasks"][0]["status"] == "proposed"
        assert "Delegation is unavailable because registry connectivity is degraded." in last_reply(msg)


async def test_delegation_approve_no_pending_is_a_no_op():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registry_url": "http://registry.test",
            "agent_registry_enroll_token": "enroll-secret",
        }
    ) as (data_dir, _, prov):
        import app.telegram_handlers as th
        from tests.support.handler_support import FakeChat, FakeUser

        save_agent_runtime_state(
            data_dir,
            AgentRuntimeState(
                agent_id="origin-agent",
                agent_token="secret",
                connectivity_state="connected",
            ),
        )

        chat = FakeChat()
        user = FakeUser()
        query, msg = await send_callback(th.handle_delegation_callback, chat, user, f"delegation_approve:{chat.id}")

        session_after = load_session_disk(data_dir, chat.id, prov)
        assert session_after.get("pending_delegation") is None
        assert last_reply(msg) == "Nothing to approve."
        assert query.answered is True
