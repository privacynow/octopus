from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from octopus_sdk.bot_runtime import WorkflowComposition
from octopus_sdk.bot_runtime import BotRuntime
from octopus_sdk.composition import WorkflowComposer, WorkflowComposerError, WorkflowNotConfiguredError
from octopus_sdk.deferred_notifications import DeferredNotification
from octopus_sdk.providers import CredentialEnvRecord, PreflightContext, ProviderConfigRecord, ProviderStateRecord, RunContext
from octopus_sdk.registry.models import DiscoveredAgentRef
from octopus_sdk.sessions import SessionState
from octopus_sdk.testing import (
    InMemoryDeferredNotificationStore,
    InMemorySessionStore,
    InMemoryWorkQueue,
)
from octopus_sdk.work_queue import WorkerHeartbeat
from octopus_sdk.workflows.skills import RuntimeSkillInfoRecord, SkillMutationResult
from tests.support.config_support import make_config


class _Messages:
    def approval_usage(self) -> str: return "approval"
    def settings_compact_on_label(self) -> str: return "on"
    def settings_compact_off_label(self) -> str: return "off"
    def trust_no_model_profiles(self) -> str: return "no profiles"
    def trust_model_profile_not_available(self, profile: str, available: list[str]) -> str:
        return f"{profile}:{','.join(available)}"
    def trust_model_profile_set(self, profile: str, model: str) -> str: return f"{profile}:{model}"
    def no_projects_configured(self) -> str: return "no projects"
    def trust_no_project_active(self) -> str: return "no project"
    def trust_project_cleared(self, working_dir: str) -> str: return working_dir
    def trust_unknown_project(self, value: str) -> str: return value
    def trust_already_using_project(self, value: str) -> str: return value
    def trust_switched_project(self, value: str, root_dir: str, *, file_policy: str = "", model_profile: str = "") -> str:
        return f"{value}:{root_dir}:{file_policy}:{model_profile}"
    def trust_file_policy_set(self, value: str) -> str: return value
    def cancel_live_requested(self) -> str: return "live"
    def cancel_queued_superseded(self) -> str: return "queued"
    def credential_setup_cancelled(self) -> str: return "setup cancelled"
    def credential_setup_another_user_in_progress(self) -> str: return "foreign"
    def cancel_pending_request(self) -> str: return "pending"
    def nothing_to_cancel(self) -> str: return "nothing"
    def recovery_error_try_again(self) -> str: return "retry"
    def recovery_already_handled(self) -> str: return "already"
    def recovery_error_discard_try_again(self) -> str: return "discard retry"
    def recovery_discarded_confirm(self) -> str: return "discarded"
    def recovery_discarded_edit(self) -> str: return "discarded edit"
    def recovery_unknown_action(self) -> str: return "unknown"
    def recovery_blocked_replay_edit(self) -> str: return "blocked"
    def recovery_already_handled_edit(self) -> str: return "already edit"
    def recovery_payload_missing_edit(self) -> str: return "payload"
    def recovery_replay_failed_edit(self) -> str: return "failed"
    def recovery_replaying_toast(self) -> str: return "toast"
    def recovery_replaying_edit(self) -> str: return "replaying"
    def recovery_notice_prompt(self) -> str: return "notice"
    def recovery_button_run_again(self) -> str: return "run again"
    def recovery_button_skip(self) -> str: return "skip"
    def approval_request_no_longer_valid(self) -> str: return "invalid"
    def approval_no_pending_approve(self) -> str: return "no approve"
    def approval_no_pending_reject(self) -> str: return "no reject"
    def approval_rejected(self) -> str: return "rejected"
    def retry_skip_confirmation(self) -> str: return "skip confirm"
    def retry_nothing_pending(self) -> str: return "nothing pending"


class _CatalogService:
    def catalog(self) -> dict[str, object]:
        return {}
    def list_tracks(self, skill_name: str):
        del skill_name
        return []
    def resolve_track(self, skill_name: str):
        del skill_name
        return None
    def resolve_runtime_track(self, skill_name: str):
        del skill_name
        return None
    def has_skill(self, skill_name: str) -> bool:
        del skill_name
        return False
    def has_runtime_skill(self, skill_name: str) -> bool:
        del skill_name
        return False
    def requirements(self, skill_name: str):
        del skill_name
        return []
    def runtime_requirements(self, skill_name: str):
        del skill_name
        return []
    def resolve_info(self, skill_name: str):
        del skill_name
        return RuntimeSkillInfoRecord(
            display_name="Skill",
            description="",
            body="",
            source_kind="builtin",
            providers=(),
            requirement_keys=(),
        )
    def create_custom_draft(self, skill_name: str, *, owner_actor: str = ""):
        del skill_name, owner_actor
        raise AssertionError("not used")
    def filter_resolvable(self, names: list[str]) -> list[str]:
        return list(names)
    def validate_active(self, skill_names: list[str]) -> list[str]:
        return []


class _ImportService:
    def registry_search(self, registry_url: str, query: str):
        del registry_url, query
        return []
    def install_from_registry(self, name: str, registry_url: str):
        del registry_url
        return SkillMutationResult(name=name, ok=True, message="installed")
    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()):
        del default_skills
        return SkillMutationResult(name=name, ok=True, message="removed")
    def update(self, name: str):
        return SkillMutationResult(name=name, ok=True, message="updated")
    def update_all(self):
        return []
    def diff(self, name: str, *, max_chars: int = 4000):
        del max_chars
        return SkillMutationResult(name=name, ok=True, message="diff")
    def has_custom_override(self, name: str) -> bool:
        del name
        return False
    def list_updates(self):
        return []


class _ActivationService:
    def normalize(self, session: SessionState) -> list[str]:
        return list(session.active_skills)
    def list_active(self, session: SessionState) -> list[str]:
        return list(session.active_skills)
    def activate(self, session: SessionState, skill_name: str) -> bool:
        if skill_name in session.active_skills:
            return False
        session.active_skills.append(skill_name)
        return True
    def deactivate(self, session: SessionState, skill_name: str) -> bool:
        if skill_name not in session.active_skills:
            return False
        session.active_skills.remove(skill_name)
        return True
    def clear(self, session: SessionState) -> None:
        session.active_skills = []


class _CredentialService:
    def list_skill_names(self, actor_key: str):
        del actor_key
        return []
    def load(self, actor_key: str):
        del actor_key
        return {}
    def load_for_skills(self, actor_key: str, skill_names: list[str]):
        del actor_key, skill_names
        return {}
    def save(self, actor_key: str, skill_name: str, cred_key: str, value: str) -> None:
        del actor_key, skill_name, cred_key, value
    def delete(self, actor_key: str, skill_name: str | None = None):
        del actor_key, skill_name
        return []
    def missing_requirements(self, requirements, credential_values):
        del credential_values
        return list(requirements)
    def build_env(self, active_skills, user_credentials):
        del active_skills, user_credentials
        return {}
    async def validate_value(self, requirement, value: str, *, validator=None, skill_name: str | None = None):
        del requirement, value, validator, skill_name
        return True, ""


class _GuidanceService:
    def system_prompt(self, role: str, active_skills: list[str], available_agents: list[DiscoveredAgentRef] | None = None) -> str:
        del role, active_skills, available_agents
        return "prompt"
    def effective_guidance_preview(self, provider_name: str, *, instance_key: str = "") -> str:
        del provider_name, instance_key
        return "guidance"
    def provider_config(self, provider_name: str, active_skills: list[str], credential_env: CredentialEnvRecord | None = None) -> ProviderConfigRecord:
        del provider_name, active_skills, credential_env
        return ProviderConfigRecord()
    def capability_summary(self, provider_name: str, active_skills: list[str]) -> str:
        del provider_name, active_skills
        return "caps"
    def prompt_weight(self, role: str, active_skills: list[str], available_agents: list[DiscoveredAgentRef] | None = None) -> int:
        del role, active_skills, available_agents
        return 1
    def estimate_prompt_size(self, role: str, current_skills: list[str], new_skill: str) -> tuple[int, bool]:
        del role, current_skills, new_skill
        return 1, False
    def check_prompt_size_cross_chat(self, data_dir: Path, skill_name: str, provider_name: str, provider_state_factory, approval_mode: str) -> list[str]:
        del data_dir, skill_name, provider_name, provider_state_factory, approval_mode
        return []
    def build_run_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        credential_env: CredentialEnvRecord | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> RunContext:
        del role, active_skills, extra_dirs, provider_name, credential_env, working_dir, file_policy, effective_model, available_agents
        return RunContext(
            extra_dirs=[],
            system_prompt="prompt",
            capability_summary="caps",
            file_policy="edit",
        )
    def build_preflight_context(
        self,
        role: str,
        active_skills: list[str],
        extra_dirs: list[str],
        *,
        provider_name: str,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
    ) -> PreflightContext:
        del role, active_skills, extra_dirs, provider_name, working_dir, file_policy, effective_model
        return PreflightContext(
            extra_dirs=[],
            system_prompt="prompt",
            capability_summary="caps",
        )
    def apply_compact_mode(self, system_prompt: str, compact: bool) -> str:
        del compact
        return system_prompt
    def stage_codex_scripts(self, data_dir: Path, conversation_key: str, active_skills: list[str]) -> Path | None:
        del data_dir, conversation_key, active_skills
        return None


class _NonTestSessionStore(InMemorySessionStore):
    pass


class _NonTestWorkQueue(InMemoryWorkQueue):
    pass


def _trust_tier_resolver(conversation_ref: str, user: object | None, *, config, dispatcher=None) -> str:
    del conversation_ref, user, config, dispatcher
    return "trusted"


def _build_workflows(
    *,
    include_optional: bool = True,
    include_deferred_notifications: bool = True,
) -> WorkflowComposition:
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    holder: dict[str, WorkflowComposition] = {}
    sessions = InMemorySessionStore(
        config=config,
        catalog=lambda: holder["workflows"].runtime_skills.catalog,
    )
    composer = (
        WorkflowComposer()
        .with_messages(_Messages())
        .with_config(config)
        .with_sessions(sessions)
        .with_work_queue(InMemoryWorkQueue())
    )
    if include_deferred_notifications:
        composer = composer.with_deferred_notifications(InMemoryDeferredNotificationStore())
    if include_optional:
        composer = (
            composer
            .with_catalog_service(_CatalogService())
            .with_import_service(_ImportService())
            .with_skill_activation(_ActivationService())
            .with_credentials(_CredentialService())
            .with_provider_guidance(_GuidanceService())
            .with_trust_tier_resolver(_trust_tier_resolver)
        )
    holder["workflows"] = composer.build_for_testing()
    return holder["workflows"]


def _fully_configured_composer() -> WorkflowComposer:
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    holder: dict[str, WorkflowComposition] = {}
    sessions = InMemorySessionStore(
        config=config,
        catalog=lambda: holder["workflows"].runtime_skills.catalog,
    )
    composer = (
        WorkflowComposer()
        .with_messages(_Messages())
        .with_config(config)
        .with_sessions(sessions)
        .with_catalog_service(_CatalogService())
        .with_import_service(_ImportService())
        .with_skill_activation(_ActivationService())
        .with_credentials(_CredentialService())
        .with_provider_guidance(_GuidanceService())
        .with_trust_tier_resolver(_trust_tier_resolver)
        .with_work_queue(InMemoryWorkQueue())
        .with_deferred_notifications(InMemoryDeferredNotificationStore())
    )
    holder["workflows"] = composer.build_for_testing()
    return composer


def test_workflow_composer_requires_mandatory_ports() -> None:
    with pytest.raises(WorkflowComposerError):
        WorkflowComposer().build()


def test_workflow_composer_build_rejects_test_implementations() -> None:
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    composer = (
        WorkflowComposer()
        .with_messages(_Messages())
        .with_config(config)
        .with_sessions(InMemorySessionStore(config=config))
        .with_work_queue(InMemoryWorkQueue())
        .with_deferred_notifications(InMemoryDeferredNotificationStore())
    )
    with pytest.raises(WorkflowComposerError, match="build_for_testing"):
        composer.build()


def test_workflow_composer_build_rejects_test_only_deferred_notification_store() -> None:
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    composer = (
        WorkflowComposer()
        .with_messages(_Messages())
        .with_config(config)
        .with_sessions(_NonTestSessionStore(config=config))
        .with_work_queue(_NonTestWorkQueue())
        .with_deferred_notifications(InMemoryDeferredNotificationStore())
    )
    with pytest.raises(WorkflowComposerError, match="deferred_notifications"):
        composer.build()


def test_in_memory_deferred_notifications_store_flushes_and_expires() -> None:
    store = InMemoryDeferredNotificationStore()
    data_dir = Path("/tmp/sdk-deferred-notifications")
    live = DeferredNotification(
        target_agent_id="agent-1",
        actor_key="actor-1",
        content="live",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-02T00:00:00+00:00",
    )
    stale = DeferredNotification(
        target_agent_id="agent-1",
        actor_key="actor-1",
        content="stale",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-01T00:00:01+00:00",
    )
    store.enqueue(data_dir, live)
    store.enqueue(data_dir, stale)

    assert store.expire_stale(data_dir, now="2026-01-01T00:00:02+00:00") == 1
    delivered = store.flush(
        data_dir,
        target_agent_id="agent-1",
        actor_key="actor-1",
        now="2026-01-01T12:00:00+00:00",
    )
    assert [item.content for item in delivered] == ["live"]


def test_in_memory_session_store_recovery_methods_fail_loudly() -> None:
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    store = InMemorySessionStore(config=config)
    with pytest.raises(NotImplementedError):
        store.list_incomplete_sessions()
    with pytest.raises(NotImplementedError):
        store.recover_after_crash(
            "stub:conversation:1",
            provider_name="stub",
            provider_state_factory=lambda _key: ProviderStateRecord(),
            approval_mode="off",
        )


def test_in_memory_work_queue_recovery_methods_fail_loudly(tmp_path: Path) -> None:
    queue = InMemoryWorkQueue()
    data_dir = tmp_path / "sdk-composer-queue"
    with pytest.raises(NotImplementedError):
        queue.list_incomplete_work_items(data_dir)
    with pytest.raises(NotImplementedError):
        queue.recover_after_crash(data_dir, lease_ttl_seconds=0)


def test_workflow_composer_optional_capabilities_fail_loudly() -> None:
    workflows = _build_workflows(
        include_optional=False,
        include_deferred_notifications=False,
    )
    with pytest.raises(WorkflowNotConfiguredError):
        workflows.provider_guidance.management.detail("stub")
    with pytest.raises(WorkflowNotConfiguredError):
        workflows.runtime_skills.catalog.list_skills("docs")
    with pytest.raises(WorkflowNotConfiguredError):
        workflows.deferred_notifications.flush(
            Path("/tmp/sdk-deferred-notifications"),
            target_agent_id="agent-1",
            actor_key="actor-1",
        )


def test_workflow_composer_tracks_management_capabilities_from_optional_ports() -> None:
    workflows = _build_workflows()
    assert workflows.management_capabilities == (
        "skill_catalog",
        "conversation_skills",
    )


def test_in_memory_session_store_load_save_and_resolve_context() -> None:
    workflows = _build_workflows()
    config = make_config(data_dir=Path("/tmp/sdk-composer"))
    store = InMemorySessionStore(config=config, catalog=lambda: workflows.runtime_skills.catalog)

    session = store.load(
        "stub:conversation:1",
        provider_name="stub",
        provider_state_factory=lambda conversation_key: ProviderStateRecord({"id": conversation_key}),
        approval_mode="off",
    )
    session.role = "tester"
    store.save("stub:conversation:1", session)

    loaded = store.load(
        "stub:conversation:1",
        provider_name="stub",
        provider_state_factory=lambda conversation_key: ProviderStateRecord({"id": conversation_key}),
        approval_mode="off",
    )
    resolved = store.resolve_context(
        loaded,
        config=config,
        provider_name="stub",
    )

    assert loaded.role == "tester"
    assert resolved.role == "tester"


def test_in_memory_work_queue_supports_submit_claim_complete_and_heartbeat(tmp_path: Path) -> None:
    queue = InMemoryWorkQueue()
    data_dir = tmp_path / "queue"

    admitted_status, admitted_id = queue.record_and_admit_message(
        data_dir,
        "evt-1",
        "chat-1",
        "user-1",
        "message",
        payload="{}",
    )
    queued_new, queued_id = queue.record_and_enqueue(
        data_dir,
        "evt-2",
        "chat-1",
        "user-1",
        "action",
        payload="{}",
    )
    claimed = queue.claim_next_any(data_dir, "worker-1")
    queue.complete_work_item(data_dir, queued_id or "")
    queue.upsert_worker_heartbeat(
        data_dir,
        WorkerHeartbeat(
            worker_id="worker-1",
            process_role="worker",
            started_at="2026-01-01T00:00:00+00:00",
            last_seen_at="2026-01-01T00:00:00+00:00",
        ),
    )

    assert admitted_status == "admitted"
    assert admitted_id
    assert queued_new is True
    assert claimed is not None
    assert claimed.id == queued_id
    assert queue.get_queue_snapshot(data_dir).claimed_count == 0
    assert len(queue.list_worker_heartbeats(data_dir)) == 1


async def test_bot_runtime_refuses_test_only_workflows_without_explicit_override(tmp_path: Path) -> None:
    class _Transport:
        async def start(self, *, runtime, stop_event) -> None:
            del runtime
            stop_event.set()

        async def stop(self) -> None:
            return None

    workflows = _build_workflows()
    runtime = BotRuntime(
        config=make_config(data_dir=tmp_path / "runtime"),
        transport=_Transport(),
        registry=type("_Registry", (), {})(),
        provider=type("_Provider", (), {"name": "stub"})(),
        sessions=InMemorySessionStore(config=make_config(data_dir=tmp_path / "runtime")),
        workflows=workflows,
        authorization=type("_Auth", (), {})(),
        work_queue=InMemoryWorkQueue(),
    )
    with pytest.raises(RuntimeError, match="test-only workflow composition"):
        await runtime.run()
