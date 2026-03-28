"""Support utilities for SDK-local wiring verification and certification tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from octopus_sdk.authorization import AuthorizationPort
from octopus_sdk.bot_runtime import BotRuntime, ExecutionServices, SessionRuntimePort, WorkflowComposition
from octopus_sdk.composition import WorkflowComposer
from octopus_sdk.config import BotConfigBase
from octopus_sdk.content_models import (
    LifecycleApprovalRecord,
    ProviderGuidanceRevisionRecord,
    ProviderGuidanceTrackRecord,
    RuntimeSkillTrackRecord,
    SkillRevisionRecord,
)
from octopus_sdk.content_store import ContentStorePort
from octopus_sdk.execution import RequestExecutionOutcome, TransportIdentity
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.inbound_types import InboundUser
from octopus_sdk.providers import (
    CredentialEnvRecord,
    PreflightContext,
    Provider,
    ProviderConfigRecord,
    ProviderStateRecord,
    RunContext,
    RunResult,
)
from octopus_sdk.registry_participant import RegistryParticipantImplementation
from octopus_sdk.registry.models import DiscoveredAgentRef
from octopus_sdk.sessions import AwaitingSkillSetup, SessionState
from octopus_sdk.skill_types import SkillRequirement
from octopus_sdk.testing import (
    InMemoryDeferredNotificationStore,
    InMemorySessionStore,
    InMemoryWorkQueue,
)
from octopus_sdk.transport import (
    EditableHandle,
    TransportBindingRecord,
    TransportCapabilities,
    TransportDescriptor,
    TransportEgress,
    TransportImplementation,
)
from octopus_sdk.work_queue import WorkQueuePort
from octopus_sdk.workflows.credentials import CredentialServicePort
from octopus_sdk.workflows.provider_guidance import ProviderGuidanceServicePort
from octopus_sdk.workflows.skills import (
    RuntimeSkillCatalogItem,
    RuntimeSkillDetail,
    RuntimeSkillDraftRecord,
    RuntimeSkillInfoRecord,
    RuntimeSkillTrackRecord as WorkflowRuntimeSkillTrackRecord,
    SkillActivationServicePort,
    SkillCatalogServicePort,
    SkillImportServicePort,
    SkillMutationResult,
    SkillUpdateStatus,
)


class StubEditableHandle(EditableHandle):
    async def edit_text(self, text: str, **kwargs: object) -> None:
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: object | None = None, **kwargs: object) -> None:
        del reply_markup, kwargs


@dataclass
class StubEgress(TransportEgress):
    sent_texts: list[str] = field(default_factory=list)
    status_labels: list[str] = field(default_factory=list)
    approval_tokens: list[str] = field(default_factory=list)
    retry_prompts: list[tuple[tuple[object, ...], str]] = field(default_factory=list)
    recovery_notices: list[tuple[str, str]] = field(default_factory=list)
    foreign_setups: list[AwaitingSkillSetup] = field(default_factory=list)
    setup_prompts: list[tuple[str, SkillRequirement]] = field(default_factory=list)
    directives: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    delegation_requests: list[tuple[str, str]] = field(default_factory=list)
    binding: TransportBindingRecord = field(default_factory=TransportBindingRecord)
    bound_title: str = ""

    @property
    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities(
            can_edit_message=True,
            can_answer_action=False,
            can_send_photo=False,
            can_send_document=False,
            can_render_timeline=False,
            can_present_actions=False,
            can_share_conversation=False,
            channel_name="stub",
        )

    async def send_text(self, text: str, **kwargs: object) -> EditableHandle:
        del kwargs
        self.sent_texts.append(text)
        return StubEditableHandle()

    async def send_status(self, text: str, **kwargs: object) -> EditableHandle:
        del kwargs
        self.status_labels.append(text)
        return StubEditableHandle()

    async def send_photo(self, photo: Path | str | bytes, **kwargs: object) -> None:
        del photo, kwargs

    async def send_document(self, document: Path | str | bytes, **kwargs: object) -> None:
        del document, kwargs

    async def send_action(self, action: str) -> None:
        del action

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        del text, show_alert

    async def sync_binding(self, binding: TransportBindingRecord) -> None:
        self.binding = binding

    async def bind(self, *, title: str, config: BotConfigBase) -> None:
        del config
        self.bound_title = title

    async def send_recovery_notice(
        self,
        *,
        preview: str,
        prompt: str,
        run_again_label: str,
        skip_label: str,
        update_id: int,
    ) -> None:
        del run_again_label, skip_label, update_id
        self.recovery_notices.append((preview, prompt))

    def typing_target(self) -> TransportEgress:
        return self

    async def show_foreign_setup(self, foreign_setup: AwaitingSkillSetup) -> None:
        self.foreign_setups.append(foreign_setup)

    async def show_setup_prompt(self, missing_skill: str, first_requirement: SkillRequirement) -> None:
        self.setup_prompts.append((missing_skill, first_requirement))

    async def send_retry_prompt(
        self,
        denials: tuple[object, ...],
        callback_token: str,
    ) -> None:
        self.retry_prompts.append((denials, callback_token))

    async def send_approval_prompt(self, callback_token: str) -> None:
        self.approval_tokens.append(callback_token)

    async def send_formatted_reply(self, text: str) -> None:
        await self.send_text(text)

    async def send_directed_artifacts(
        self,
        conversation_key_value: str,
        directives: list[tuple[str, str]],
        *,
        resolved_ctx: ResolvedExecutionContext | None = None,
    ) -> None:
        del resolved_ctx
        self.directives.append((conversation_key_value, list(directives)))

    async def send_compact_reply(self, text: str, conversation_key_value: str, slot: int) -> None:
        del conversation_key_value, slot
        await self.send_formatted_reply(text)

    async def propose_delegation_plan(
        self,
        conversation_key_value: str,
        session: SessionState,
        *,
        conversation_ref: str,
        result: RunResult,
    ) -> RequestExecutionOutcome | None:
        del session, result
        self.delegation_requests.append((conversation_key_value, conversation_ref))
        return RequestExecutionOutcome(status="delegation_proposed")


@dataclass
class StubTransport(TransportImplementation):
    started: bool = False
    stopped: bool = False
    egresses: dict[str, StubEgress] = field(default_factory=dict)

    @property
    def transport_id(self) -> str:
        return "stub"

    @property
    def descriptor(self) -> TransportDescriptor:
        return TransportDescriptor(
            transport_type="stub",
            display_name="Stub",
            supports_multiple=True,
            inbound_model="poll",
            supports_conversation_binding=False,
            supports_timeline=False,
        )

    def ref_prefix(self) -> str:
        return "stub:"

    def build_egress(self, *, conversation_ref: str, config: BotConfigBase, **kw: object) -> TransportEgress:
        del config, kw
        return self.egresses.setdefault(conversation_ref, StubEgress())

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        del runtime
        self.started = True
        stop_event.set()

    async def stop(self) -> None:
        self.stopped = True


class StubProvider(Provider):
    name = "claude"

    def new_provider_state(self, conversation_key: str) -> ProviderStateRecord:
        return ProviderStateRecord({"conversation_key": conversation_key})

    async def run(
        self,
        provider_state: ProviderStateRecord,
        prompt: str,
        image_paths: list[str],
        progress,
        context: RunContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        del provider_state, prompt, image_paths, context, cancel
        await progress.update("stub-progress", force=True)
        return RunResult(text="sdk response")

    async def run_preflight(
        self,
        prompt: str,
        image_paths: list[str],
        progress,
        context: PreflightContext | None = None,
        cancel: asyncio.Event | None = None,
    ) -> RunResult:
        del prompt, image_paths, progress, context, cancel
        return RunResult(text="approval plan")

    def check_health(self) -> list[str]:
        return []

    async def check_auth_health(self) -> list[str]:
        return []

    async def check_runtime_health(self) -> list[str]:
        return []


class StubMessages:
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
    def recovery_orphaned_command(self, detail: str) -> str: return detail
    def recovery_notice_prompt(self) -> str: return "notice"
    def recovery_button_run_again(self) -> str: return "run again"
    def recovery_button_skip(self) -> str: return "skip"
    def approval_request_no_longer_valid(self) -> str: return "invalid"
    def approval_no_pending_approve(self) -> str: return "no approve"
    def approval_no_pending_reject(self) -> str: return "no reject"
    def approval_rejected(self) -> str: return "rejected"
    def retry_skip_confirmation(self) -> str: return "skip confirm"
    def retry_nothing_pending(self) -> str: return "nothing pending"


class StubCatalogService(SkillCatalogServicePort):
    def catalog(self) -> dict[str, object]:
        return {"docs": object()}

    def list_tracks(self, skill_name: str) -> list[WorkflowRuntimeSkillTrackRecord]:
        track = self.resolve_track(skill_name)
        return [] if track is None else [track]

    def resolve_track(self, skill_name: str) -> WorkflowRuntimeSkillTrackRecord | None:
        if skill_name != "docs":
            return None
        return WorkflowRuntimeSkillTrackRecord(
            slug="docs",
            display_name="Docs",
            description="Docs skill",
            source_kind="builtin",
            revision=SkillRevisionRecord(instruction_body="Use docs"),
            visibility="shared",
            is_mutable=False,
            active_revision_id="docs-r1",
            published_revision_id="docs-r1",
        )

    def resolve_runtime_track(self, skill_name: str) -> WorkflowRuntimeSkillTrackRecord | None:
        return self.resolve_track(skill_name)

    def has_skill(self, skill_name: str) -> bool:
        return skill_name == "docs"

    def has_runtime_skill(self, skill_name: str) -> bool:
        return skill_name == "docs"

    def requirements(self, skill_name: str) -> list[SkillRequirement]:
        del skill_name
        return []

    def runtime_requirements(self, skill_name: str) -> list[SkillRequirement]:
        del skill_name
        return []

    def resolve_info(self, skill_name: str) -> RuntimeSkillInfoRecord | None:
        if skill_name != "docs":
            return None
        return RuntimeSkillInfoRecord(
            display_name="Docs",
            description="Docs skill",
            body="Use docs",
            source_kind="builtin",
            providers=("stub",),
            requirement_keys=(),
        )

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = "") -> WorkflowRuntimeSkillTrackRecord:
        del owner_actor
        return WorkflowRuntimeSkillTrackRecord(
            slug=skill_name,
            display_name=skill_name.title(),
            description="Custom",
            source_kind="custom",
            revision=SkillRevisionRecord(instruction_body=f"Use {skill_name}"),
            visibility="private",
            is_mutable=True,
            active_revision_id=f"{skill_name}-draft",
            published_revision_id="",
        )

    def filter_resolvable(self, names: list[str]) -> list[str]:
        return [name for name in names if self.has_skill(name)]

    def validate_active(self, skill_names: list[str]) -> list[str]:
        return [name for name in skill_names if self.has_skill(name)]


class StubImportService(SkillImportServicePort):
    def registry_search(self, registry_url: str, query: str) -> list[object]:
        del registry_url, query
        return []

    def install_from_registry(self, name: str, registry_url: str) -> SkillMutationResult:
        del registry_url
        return SkillMutationResult(name=name, ok=True, message="installed")

    def uninstall(self, name: str, default_skills: tuple[str, ...] = ()) -> SkillMutationResult:
        del default_skills
        return SkillMutationResult(name=name, ok=True, message="uninstalled")

    def update(self, name: str) -> SkillMutationResult:
        return SkillMutationResult(name=name, ok=True, message="updated")

    def update_all(self) -> list[SkillMutationResult]:
        return []

    def diff(self, name: str, *, max_chars: int = 4000) -> SkillMutationResult:
        del max_chars
        return SkillMutationResult(name=name, ok=True, message="diff")

    def has_custom_override(self, name: str) -> bool:
        del name
        return False

    def list_updates(self) -> list[SkillUpdateStatus]:
        return []


class StubActivationService(SkillActivationServicePort):
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


class StubCredentialService(CredentialServicePort):
    def list_skill_names(self, actor_key: str) -> list[str]:
        del actor_key
        return ["docs"]

    def load(self, actor_key: str) -> dict[str, dict[str, str]]:
        del actor_key
        return {"docs": {"API_KEY": "secret"}}

    def load_for_skills(self, actor_key: str, skill_names: list[str]) -> dict[str, dict[str, str]]:
        del actor_key
        return {name: {"API_KEY": "secret"} for name in skill_names}

    def save(self, actor_key: str, skill_name: str, cred_key: str, value: str) -> None:
        del actor_key, skill_name, cred_key, value

    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]:
        del actor_key
        return [] if skill_name is None else [skill_name]

    def missing_requirements(
        self,
        requirements: list[SkillRequirement],
        credential_values: dict[str, str],
    ) -> list[SkillRequirement]:
        missing: list[SkillRequirement] = []
        for requirement in requirements:
            if not credential_values.get(requirement.key):
                missing.append(requirement)
        return missing

    def build_env(
        self,
        active_skills: list[str],
        user_credentials: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        del active_skills
        merged: dict[str, str] = {}
        for values in user_credentials.values():
            merged.update(values)
        return merged

    async def validate_value(
        self,
        requirement: SkillRequirement,
        value: str,
        *,
        validator=None,
        skill_name: str | None = None,
    ) -> tuple[bool, str]:
        del requirement, validator, skill_name
        return bool(value.strip()), "" if value.strip() else "empty"


class StubGuidanceService(ProviderGuidanceServicePort):
    def system_prompt(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> str:
        del role, active_skills, available_agents
        return "system"

    def effective_guidance_preview(self, provider_name: str, *, instance_key: str = "") -> str:
        del provider_name, instance_key
        return "guidance"

    def provider_config(
        self,
        provider_name: str,
        active_skills: list[str],
        credential_env: CredentialEnvRecord | None = None,
    ) -> ProviderConfigRecord:
        del provider_name, active_skills, credential_env
        return ProviderConfigRecord()

    def capability_summary(self, provider_name: str, active_skills: list[str]) -> str:
        del provider_name, active_skills
        return "caps"

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> int:
        del role, active_skills, available_agents
        return 1

    def estimate_prompt_size(
        self,
        role: str,
        current_skills: list[str],
        new_skill: str,
    ) -> tuple[int, bool]:
        del role, current_skills, new_skill
        return 1, False

    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]:
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
        del role, active_skills, provider_name, available_agents
        return RunContext(
            extra_dirs=list(extra_dirs),
            system_prompt="system",
            capability_summary="caps",
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
            provider_config=ProviderConfigRecord(),
            credential_env=credential_env or CredentialEnvRecord(),
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
        del role, active_skills, provider_name
        return PreflightContext(
            extra_dirs=list(extra_dirs),
            system_prompt="preflight",
            capability_summary="caps",
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
        )

    def apply_compact_mode(self, system_prompt: str, compact: bool) -> str:
        del compact
        return system_prompt

    def stage_codex_scripts(self, data_dir: Path, conversation_key: str, active_skills: list[str]) -> Path | None:
        del data_dir, conversation_key, active_skills
        return None

    def cleanup_codex_scripts(self, data_dir: Path, conversation_key: str) -> None:
        del data_dir, conversation_key


class StubContentStore(ContentStorePort):
    def __init__(self) -> None:
        self._skills: dict[str, RuntimeSkillTrackRecord] = {}
        self._guidance: dict[tuple[str, str, str], ProviderGuidanceTrackRecord] = {}

    def get_provider_guidance(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> ProviderGuidanceTrackRecord | None:
        return self._guidance.get((provider_name, scope_kind, scope_key))

    def list_provider_guidance_revisions(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[ProviderGuidanceRevisionRecord]:
        track = self.get_provider_guidance(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        return [] if track is None else [track.revision]

    def list_provider_guidance_approvals(
        self,
        provider_name: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> list[LifecycleApprovalRecord]:
        del provider_name, scope_kind, scope_key
        return []

    def get_latest_provider_guidance_approval_action(
        self,
        provider_name: str,
        revision_id: str,
        *,
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> str:
        del provider_name, revision_id, scope_kind, scope_key
        return ""

    def apply_provider_guidance_lifecycle_transition(
        self,
        provider_name: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: str = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
        scope_kind: str = "system",
        scope_key: str = "",
    ) -> None:
        del revision_id, set_status, published_pointer, approval_action, actor, note
        track = self.get_provider_guidance(provider_name, scope_kind=scope_kind, scope_key=scope_key)
        if track is None:
            return
        self._guidance[(provider_name, scope_kind, scope_key)] = track

    def upsert_provider_guidance_draft(self, record: ProviderGuidanceTrackRecord) -> None:
        self._guidance[(record.provider, record.scope_kind, record.scope_key)] = record

    def list_skill_revisions(self, skill_name: str) -> list[SkillRevisionRecord]:
        track = self._skills.get(skill_name)
        return [] if track is None else [track.revision]

    def list_skill_approvals(self, skill_name: str) -> list[LifecycleApprovalRecord]:
        del skill_name
        return []

    def get_latest_skill_approval_action(self, skill_name: str, revision_id: str) -> str:
        del skill_name, revision_id
        return ""

    def apply_skill_lifecycle_transition(
        self,
        skill_name: str,
        revision_id: str,
        *,
        set_status: str | None = None,
        published_pointer: str = "unchanged",
        approval_action: str | None = None,
        actor: str = "",
        note: str = "",
    ) -> None:
        del revision_id, set_status, published_pointer, approval_action, actor, note
        track = self._skills.get(skill_name)
        if track is None:
            return
        self._skills[skill_name] = track

    def upsert_skill_draft(self, record: RuntimeSkillTrackRecord) -> None:
        self._skills[record.slug] = record


class StubTextFormatting:
    def summarize_text(self, text: str, limit: int = 240) -> str:
        clean = " ".join(text.strip().split())
        return clean if len(clean) <= limit else clean[: limit - 1] + "…"


@dataclass
class StubCompletionWebhook:
    calls: list[tuple[str, int, str, str, str, str]] = field(default_factory=list)

    async def __call__(
        self,
        url: str,
        *,
        chat_id: int,
        conversation_ref: str,
        status: str,
        summary: str,
        completed_at: str,
    ) -> None:
        self.calls.append((url, chat_id, conversation_ref, status, summary, completed_at))


@dataclass
class RecordingWorkQueue(InMemoryWorkQueue):
    calls: list[str] = field(default_factory=list)

    def record_and_admit_message(
        self,
        data_dir: Path,
        event_id: str,
        conversation_key: str,
        actor_key: str,
        kind: str,
        payload: str = "{}",
    ) -> tuple[str, str | None]:
        self.calls.append("record_and_admit_message")
        return super().record_and_admit_message(
            data_dir,
            event_id,
            conversation_key,
            actor_key,
            kind,
            payload=payload,
        )


class StubAuthorization(AuthorizationPort):
    def is_allowed(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
        *,
        override: str | None = None,
    ) -> bool:
        del config, user, override
        return True

    def is_admin(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
    ) -> bool:
        del config, user
        return True

    def trust_tier(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
    ) -> str:
        del config, user
        return "trusted"

    def access_policy(
        self,
        config: BotConfigBase,
        user: InboundUser | None,
        *,
        override: str | None = None,
    ) -> str:
        del config, user
        return override or "allow"


@dataclass
class StubRegistryHealth:
    current_ids: dict[str, str] = field(default_factory=dict)
    live_ids: dict[str, str] = field(default_factory=dict)

    def current_local_agent_ids(self) -> dict[str, str]:
        return dict(self.current_ids)

    def live_local_agent_ids(self) -> dict[str, str]:
        return dict(self.live_ids or self.current_ids)


@dataclass
class StubRegistryParticipant:
    health: StubRegistryHealth = field(default_factory=StubRegistryHealth)


@dataclass
class StubArtifacts:
    root: Path
    saved_items: list[tuple[str, str, str, str]] = field(default_factory=list)

    def upload_dir(self, conversation_key: str) -> Path:
        path = self.root / "uploads" / conversation_key.replace(":", "_")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_raw(
        self,
        conversation_key: str,
        prompt: str,
        raw_text: str,
        *,
        kind: str = "request",
    ) -> int:
        self.saved_items.append((conversation_key, prompt, raw_text, kind))
        return len(self.saved_items)


def trust_tier_resolver(
    conversation_ref: str,
    user: InboundUser | None,
    *,
    config: BotConfigBase,
    dispatcher=None,
) -> str:
    del conversation_ref, user, config, dispatcher
    return "trusted"


def make_test_config(
    tmp_path: Path,
    *,
    approval_mode: str = "off",
    process_role: str = "bot",
) -> BotConfigBase:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return BotConfigBase(
        instance="sdk-wiring",
        allow_open=False,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
        provider_name="claude",
        model="stub-model",
        working_dir=tmp_path,
        extra_dirs=(),
        data_dir=data_dir,
        timeout_seconds=30,
        approval_mode=approval_mode,
        autonomous=False,
        role="",
        role_from_file=False,
        default_skills=(),
        stream_update_interval_seconds=0.05,
        typing_interval_seconds=0.05,
        codex_sandbox="workspace-write",
        codex_skip_git_repo_check=False,
        codex_full_auto=False,
        codex_dangerous=False,
        codex_profile="",
        admin_actor_keys=frozenset(),
        admin_usernames=frozenset(),
        admin_users_explicit=False,
        compact_mode=False,
        summary_model="",
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
        projects=(),
        model_profiles={},
        default_model_profile="",
        public_working_dir="",
        public_model_profiles=frozenset(),
        registry_url="",
        agent_mode="standalone",
        agent_display_name="SDK Wiring",
        agent_slug="sdk-wiring",
        agent_role="",
        agent_tags=(),
        agent_description="",
        agent_capabilities=(),
        agent_registries=(),
        agent_poll_interval_seconds=5.0,
        runtime_mode="local",
        process_role=process_role,
        claim_lease_ttl_seconds=60,
        claim_sweep_interval_seconds=5.0,
        delegation_timeout_seconds=30,
        database_url="",
        db_pool_min_size=1,
        db_pool_max_size=1,
        db_connect_timeout_seconds=5,
        registry_publish_level="minimal",
    )


def make_transport_identity(
    *,
    conversation_key: str,
    actor: str,
    conversation_ref: str,
) -> TransportIdentity:
    return TransportIdentity(
        conversation_key=conversation_key,
        origin_channel="stub",
        actor=actor,
        external_conversation_ref=conversation_ref,
        target_agent_id="",
        conversation_ref=conversation_ref,
        routed_task_id="",
        authority_ref="",
    )


@dataclass
class SdkHarness:
    config: BotConfigBase
    composer: WorkflowComposer
    provider: StubProvider
    transport: StubTransport
    sessions: InMemorySessionStore
    work_queue: RecordingWorkQueue
    deferred_notifications: InMemoryDeferredNotificationStore
    authorization: StubAuthorization
    artifacts: StubArtifacts
    _workflow_holder: dict[str, WorkflowComposition]

    def build_runtime(
        self,
        workflows: WorkflowComposition,
        *,
        allow_test_mode: bool = True,
        local_agent_ids: dict[str, str] | None = None,
    ) -> BotRuntime:
        self._workflow_holder["workflows"] = workflows
        registry = StubRegistryParticipant(
            health=StubRegistryHealth(
                current_ids=dict(local_agent_ids or {}),
                live_ids=dict(local_agent_ids or {}),
            )
        )
        return BotRuntime(
            config=self.config,
            transport=self.transport,
            registry=registry,  # type: ignore[arg-type]
            provider=self.provider,
            sessions=self.sessions,
            workflows=workflows,
            authorization=self.authorization,
            work_queue=self.work_queue,
            execution_services=ExecutionServices(
                guidance=StubGuidanceService(),
                skill_activation=StubActivationService(),
                runtime_skill_setup=workflows.runtime_skills.setup,
                sessions=self.sessions,
                artifacts=self.artifacts,
            ),
            allow_test_mode=allow_test_mode,
        )


def make_sdk_harness(
    tmp_path: Path,
    *,
    approval_mode: str = "off",
    process_role: str = "bot",
    work_queue: RecordingWorkQueue | None = None,
) -> SdkHarness:
    config = make_test_config(
        tmp_path,
        approval_mode=approval_mode,
        process_role=process_role,
    )
    provider = StubProvider()
    transport = StubTransport()
    messages = StubMessages()
    catalog_service = StubCatalogService()
    import_service = StubImportService()
    activation_service = StubActivationService()
    credential_service = StubCredentialService()
    guidance_service = StubGuidanceService()
    content_store = StubContentStore()
    queue = work_queue or RecordingWorkQueue()
    workflow_holder: dict[str, WorkflowComposition] = {}
    deferred_notifications = InMemoryDeferredNotificationStore()
    sessions = InMemorySessionStore(
        config=config,
        catalog=lambda: workflow_holder["workflows"].runtime_skills.catalog,
    )
    composer = (
        WorkflowComposer()
        .with_messages(messages)
        .with_config(config)
        .with_sessions(sessions)
        .with_catalog_service(catalog_service)
        .with_import_service(import_service)
        .with_skill_activation(activation_service)
        .with_credentials(credential_service)
        .with_provider_guidance(guidance_service)
        .with_content_store(content_store)
        .with_work_queue(queue)
        .with_trust_tier_resolver(trust_tier_resolver)
        .with_text_formatting(StubTextFormatting())
        .with_completion_webhook(StubCompletionWebhook())
        .with_deferred_notifications(deferred_notifications)
        .with_prompt_size_warning_threshold(10)
    )
    return SdkHarness(
        config=config,
        composer=composer,
        provider=provider,
        transport=transport,
        sessions=sessions,
        work_queue=queue,
        deferred_notifications=deferred_notifications,
        authorization=StubAuthorization(),
        artifacts=StubArtifacts(tmp_path),
        _workflow_holder=workflow_holder,
    )
