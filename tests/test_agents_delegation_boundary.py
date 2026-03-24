from app.identity import telegram_conversation_ref
from app.agents.delegation import (
    build_delegation_runtime,
    handle_delegation_approve,
    handle_delegation_cancel,
    preview_delegation_targets,
)
from app.ports.agent_directory import AuthorityResolution
from app.ports.task_routing import TaskSubmissionResult
from app.session_state import DelegatedTask, PendingDelegation
from app.storage import default_session, save_session
from tests.support.config_support import make_registry_connection
from tests.support.handler_support import current_runtime, fresh_env, load_session_disk


class _ChannelEgress:
    def __init__(self) -> None:
        self.messages: list[tuple[str, object | None]] = []

    async def send_text(self, text: str, *, reply_markup=None) -> None:
        self.messages.append((text, reply_markup))


class _PreviewDirectory:
    def __init__(self, results):
        self._results = results

    async def resolve_target_authority(self, *, target_agent_id):
        return self._results[target_agent_id]


async def test_delegation_approve_boundary_uses_explicit_runtime(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_publish_level": "off",
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

        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
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
        save_session(data_dir, f"tg:{chat_id}", session)
        channel_egress = _ChannelEgress()

        await handle_delegation_approve(
            f"tg:{chat_id}",
            conversation_ref,
            channel_egress,
            runtime=build_delegation_runtime(
                config=cfg,
                provider_name=prov.name,
                provider_state_factory=prov.new_provider_state,
                task_routing=current_runtime().services.control_plane.task_routing,
                agent_directory=current_runtime().services.control_plane.agent_directory,
            ),
        )

        session_after = load_session_disk(data_dir, f"tg:{chat_id}", prov)
        pending = session_after.get("pending_delegation")
        assert len(submitted) == 1
        assert pending is not None
        assert pending["status"] == "submitted"
        assert pending["tasks"][0]["status"] == "submitted"
        assert channel_egress.messages == [
            (
                "Delegation approved. 1 request(s) sent to specialist bots."
                " I'll continue when results arrive.",
                None,
            )
        ]


async def test_delegation_cancel_boundary_uses_explicit_runtime():
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_publish_level": "off",
        }
    ) as (data_dir, cfg, prov):
        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
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
        save_session(data_dir, f"tg:{chat_id}", session)
        channel_egress = _ChannelEgress()

        await handle_delegation_cancel(
            f"tg:{chat_id}",
            conversation_ref,
            channel_egress,
            runtime=build_delegation_runtime(
                config=cfg,
                provider_name=prov.name,
                provider_state_factory=prov.new_provider_state,
                task_routing=current_runtime().services.control_plane.task_routing,
                agent_directory=current_runtime().services.control_plane.agent_directory,
            ),
        )

        session_after = load_session_disk(data_dir, f"tg:{chat_id}", prov)
        assert session_after.get("pending_delegation") is None
        assert channel_egress.messages == [("Delegation cancelled. No requests were sent.", None)]


async def test_preview_delegation_targets_marks_resolved_and_unresolved_agents():
    previews = await preview_delegation_targets(
        PendingDelegation(
            conversation_ref="telegram:bot:123",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    title="Implement",
                    target_agent_id="developer-1",
                ),
                DelegatedTask(
                    routed_task_id="task-2",
                    title="Review",
                    target_agent_id="reviewer-1",
                ),
            ],
        ),
        agent_directory=_PreviewDirectory(
            {
                "developer-1": AuthorityResolution(
                    status="resolved",
                    authority_ref="registry:default",
                ),
                "reviewer-1": AuthorityResolution(status="not_found"),
            }
        ),
    )

    assert previews[0].status == "resolved"
    assert previews[0].authority_ref == "registry:default"
    assert previews[1].status == "unresolved"
    assert "reviewer-1" in previews[1].detail


async def test_delegation_partial_submission_message_names_sent_and_remaining_tasks(monkeypatch):
    with fresh_env(
        config_overrides={
            "agent_mode": "registry",
            "agent_registries": (make_registry_connection(),),
            "registry_publish_level": "off",
        }
    ) as (data_dir, cfg, prov):
        attempts: list[str] = []
        fail_second = True

        async def fake_resolve_target_authority(*, target_agent_id):
            return AuthorityResolution(status="resolved", authority_ref=f"registry:{target_agent_id}")

        async def fake_submit_routed_task(*, request, authority_ref):
            del authority_ref
            attempts.append(request.target_agent_id)
            if fail_second and request.target_agent_id == "reviewer-1":
                return TaskSubmissionResult(status="failed", error="registry_server_error")
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

        chat_id = 12345
        conversation_ref = telegram_conversation_ref(cfg, chat_id)
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["pending_delegation"] = {
            "conversation_ref": conversation_ref,
            "title": "Feature delegation",
            "tasks": [
                {
                    "routed_task_id": "task-1",
                    "title": "Implement feature",
                    "target_agent_id": "developer-1",
                    "instructions": "Build the feature end to end.",
                    "status": "proposed",
                },
                {
                    "routed_task_id": "task-2",
                    "title": "Review feature",
                    "target_agent_id": "reviewer-1",
                    "instructions": "Review correctness and risk.",
                    "status": "proposed",
                },
            ],
        }
        save_session(data_dir, f"tg:{chat_id}", session)
        channel_egress = _ChannelEgress()
        runtime = build_delegation_runtime(
            config=cfg,
            provider_name=prov.name,
            provider_state_factory=prov.new_provider_state,
            task_routing=current_runtime().services.control_plane.task_routing,
            agent_directory=current_runtime().services.control_plane.agent_directory,
        )

        await handle_delegation_approve(
            f"tg:{chat_id}",
            conversation_ref,
            channel_egress,
            runtime=runtime,
        )

        session_after = load_session_disk(data_dir, f"tg:{chat_id}", prov)
        pending = session_after.get("pending_delegation")
        assert attempts == ["developer-1", "reviewer-1"]
        assert pending is not None
        assert pending["status"] == "submitted"
        assert [task["status"] for task in pending["tasks"]] == ["submitted", "proposed"]
        assert "Already sent to: developer-1." in channel_egress.messages[-1][0]
        assert "Still pending: reviewer-1." in channel_egress.messages[-1][0]
        assert "Approving again will only send the remaining requests." in channel_egress.messages[-1][0]

        attempts.clear()
        fail_second = False

        await handle_delegation_approve(
            f"tg:{chat_id}",
            conversation_ref,
            channel_egress,
            runtime=runtime,
        )

        session_final = load_session_disk(data_dir, f"tg:{chat_id}", prov)
        pending_final = session_final.get("pending_delegation")
        assert attempts == ["reviewer-1"]
        assert pending_final is not None
        assert [task["status"] for task in pending_final["tasks"]] == ["submitted", "submitted"]
        assert channel_egress.messages[-1][0] == (
            "Delegation approved. 1 request(s) sent to specialist bots."
            " I'll continue when results arrive."
        )
