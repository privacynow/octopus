import asyncio
import ast
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from octopus_sdk.authorization import AuthorizationPort
from octopus_sdk.agent_directory import AgentSearchResult
from octopus_sdk.bot_runtime import (
    BotRuntime,
    ConversationWorkflows,
    CredentialWorkflows,
    PendingWorkflows,
    ProviderGuidanceWorkflows,
    RecoveryWorkflows,
    RuntimeSkillWorkflows,
    WorkflowComposition,
)
from octopus_sdk.bot_runtime import ExecutionServices
from octopus_sdk.bot_runtime import ProviderDispatchRuntime
from octopus_sdk.execution import ExecutionRuntime
from octopus_sdk.execution import RequestExecutionOutcome
from octopus_sdk.execution import TransportIdentity
from octopus_sdk.execution import execute_request
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.execution_context import resolve_execution_context
from octopus_sdk.inbound_types import InboundAction, InboundEnvelope, InboundMessage, InboundUser
from octopus_sdk.inbound_types import InboundActionParamsRecord
from octopus_sdk.providers import (
    CredentialEnvRecord,
    DenialRecord,
    PreflightContext,
    Provider,
    ProviderConfigRecord,
    ProviderStateRecord,
    RunContext,
    RunResult,
)
from octopus_sdk.registry.models import DiscoveredAgentRef
from octopus_sdk.registry.models import CoordinationActionResult
from octopus_sdk.registry.models import EnrollmentResult
from octopus_sdk.registry.models import MirrorOutcome
from octopus_sdk.registry.models import TargetResolutionPreview
from octopus_sdk.sessions import SessionState
from octopus_sdk.sessions import default_session
from octopus_sdk.sessions import session_from_dict
from octopus_sdk.sessions import session_to_dict
from octopus_sdk.sessions import AwaitingSkillSetup
from octopus_sdk.skill_types import CredentialValidationSpec, SkillRequirement
from octopus_sdk.work_queue import WorkQueuePort
from octopus_sdk.workflows.conversation import (
    ConversationCancelOutcome,
    ConversationResetOutcome,
    ModelProfileState,
    SettingMutationOutcome,
)
from octopus_sdk.workflows.credentials import CredentialClearOutcome
from octopus_sdk.workflows.pending import PendingExecutionPlan, PendingRequestOutcome
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleMutation,
    ProviderGuidancePreview,
)
from octopus_sdk.workflows.recovery import RecoveryActionOutcome
from octopus_sdk.workflows.recovery import WorkerRecoveryOutcome
from octopus_sdk.workflows.skills import (
    ConversationSkillListing,
    ConversationSkillMutationOutcome,
    RuntimeSkillCredentialClearOutcome,
    RuntimeSkillCatalogItem,
    RuntimeSkillCredentialSatisfactionOutcome,
    RuntimeSkillLifecycleMutation,
    RuntimeSkillMutationOutcome,
    RuntimeSkillDraftRecord,
    RuntimeSkillSearchResults,
    RuntimeSkillSetupAdvanceOutcome,
    RuntimeSkillSetupCancellationOutcome,
    RuntimeSkillSetupState,
)
from octopus_sdk.transport import EditableHandle
from octopus_sdk.transport import TransportBindingRecord
from octopus_sdk.transport import TransportCapabilities
from octopus_sdk.transport import TransportDescriptor
from octopus_sdk.transport import TransportEgress
from octopus_sdk.transport import TransportHealthRecord
from octopus_sdk.transport import TransportImplementation
from octopus_sdk.config import BotConfigBase


class _StubEditableHandle(EditableHandle):
    async def edit_text(self, text: str, **kwargs: object) -> None:
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: object | None = None, **kwargs: object) -> None:
        del reply_markup, kwargs


class _StubEgress(TransportEgress):
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.status_labels: list[str] = []
        self.recovery_notices: list[tuple[str, str]] = []
        self.retry_prompts: list[tuple[tuple[DenialRecord, ...], str]] = []
        self.approval_tokens: list[str] = []
        self.foreign_setups: list[AwaitingSkillSetup] = []
        self.setup_prompts: list[tuple[str, SkillRequirement]] = []
        self.directives: list[tuple[str, list[tuple[str, str]]]] = []
        self.delegation_requests: list[tuple[str, str]] = []
        self.binding = TransportBindingRecord()
        self.bound_title = ""

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
        return _StubEditableHandle()

    async def send_status(self, text: str, **kwargs: object) -> EditableHandle:
        del kwargs
        self.status_labels.append(text)
        return _StubEditableHandle()

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
        denials: tuple[DenialRecord, ...],
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


class _StubTransport(TransportImplementation):
    def __init__(self) -> None:
        self._egress = _StubEgress()

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
        del conversation_ref, config, kw
        return self._egress

    async def start(self, *, runtime, stop_event: asyncio.Event) -> None:
        del runtime, stop_event


class _StubProvider(Provider):
    name = "stub"

    def new_provider_state(self, conversation_key: str) -> ProviderStateRecord:
        del conversation_key
        return ProviderStateRecord()

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
        return RunResult(text="preflight ok")

    def check_health(self) -> list[str]:
        return []

    async def check_auth_health(self) -> list[str]:
        return []

    async def check_runtime_health(self) -> list[str]:
        return []


def _provider_state_factory(_conversation_key: str) -> ProviderStateRecord:
    return ProviderStateRecord()


class _StubGuidance:
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

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[DiscoveredAgentRef] | None = None,
    ) -> int:
        del role, active_skills, available_agents
        return 0

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
            extra_dirs=extra_dirs,
            system_prompt="stub-system-prompt",
            capability_summary="",
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
            credential_env=credential_env or CredentialEnvRecord(),
            provider_config=ProviderConfigRecord(),
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
            extra_dirs=extra_dirs,
            system_prompt="stub-preflight",
            capability_summary="",
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
        )

    def apply_compact_mode(self, system_prompt: str, compact: bool) -> str:
        del compact
        return system_prompt

    def stage_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
        active_skills: list[str],
    ) -> Path | None:
        del data_dir, conversation_key, active_skills
        return None


class _StubSkillActivation:
    def normalize(self, session: SessionState) -> list[str]:
        del session
        return []


@dataclass
class _StubSkillSetupOutcome:
    status: str
    credential_env: CredentialEnvRecord | None = None
    foreign_setup: object | None = None
    setup_state: object | None = None
    first_requirement: SkillRequirement | None = None
    missing_skill: str = ""


class _StubRuntimeSkillSetup:
    def check_satisfaction(
        self,
        session: SessionState,
        *,
        actor_key: str,
        active_skills: list[str],
    ) -> _StubSkillSetupOutcome:
        del session, actor_key, active_skills
        return _StubSkillSetupOutcome(status="satisfied", credential_env=CredentialEnvRecord())


class _StubSessions:
    def __init__(self, config: BotConfigBase) -> None:
        self._config = config
        self._sessions: dict[str, SessionState] = {}

    def load(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState:
        if conversation_key not in self._sessions:
            raw = default_session(
                provider_name,
                provider_state_factory(conversation_key),
                approval_mode,
                default_role,
                default_skills,
            )
            self._sessions[conversation_key] = session_from_dict(raw)
        return session_from_dict(session_to_dict(self._sessions[conversation_key]))

    def save(self, conversation_key: str, session: SessionState) -> None:
        self._sessions[conversation_key] = session_from_dict(session_to_dict(session))

    def resolve_context(
        self,
        session: SessionState,
        *,
        config: BotConfigBase,
        provider_name: str,
        trust_tier: str = "trusted",
    ) -> ResolvedExecutionContext:
        return resolve_execution_context(
            session,
            config,
            provider_name,
            trust_tier=trust_tier,
        )


class _StubArtifacts:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.saved_items: list[tuple[str, str, str, str]] = []

    def upload_dir(self, conversation_key: str) -> Path:
        path = self._root / "uploads" / conversation_key.replace(":", "_")
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


class _StubProgress:
    def __init__(self, status_message: object, config: BotConfigBase, timeline_callback: object | None = None) -> None:
        del config
        self.status_message = status_message
        self.timeline_callback = timeline_callback
        self.content_started = None
        self.updates: list[tuple[str, bool]] = []

    async def update(self, html_text: str, *, force: bool = False) -> None:
        self.updates.append((html_text, force))


def _make_config(tmp_path: Path) -> BotConfigBase:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return BotConfigBase(
        instance="sdk-reference",
        allow_open=False,
        allowed_actor_keys=frozenset(),
        allowed_usernames=frozenset(),
        provider_name="stub",
        model="stub-model",
        working_dir=tmp_path,
        extra_dirs=(),
        data_dir=data_dir,
        timeout_seconds=30,
        approval_mode="off",
        autonomous=False,
        role="",
        role_from_file=False,
        default_skills=(),
        stream_update_interval_seconds=0.25,
        typing_interval_seconds=0.25,
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
        agent_display_name="SDK Reference",
        agent_slug="sdk-reference",
        agent_role="",
        agent_tags=(),
        agent_description="",
        agent_capabilities=(),
        agent_registries=(),
        agent_poll_interval_seconds=5.0,
        runtime_mode="local",
        process_role="all",
        claim_lease_ttl_seconds=60,
        claim_sweep_interval_seconds=5.0,
        delegation_timeout_seconds=30,
        database_url="",
        db_pool_min_size=1,
        db_pool_max_size=1,
        db_connect_timeout_seconds=5,
        registry_publish_level="minimal",
    )


def test_sdk_reference_transport_source_has_no_app_imports_or_callback_scaffolding() -> None:
    source = Path(__file__).read_text()
    tree = ast.parse(source, filename=str(Path(__file__)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("app") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith("app")
        elif isinstance(node, ast.Lambda):
            raise AssertionError(f"lambda callback scaffolding still present in {__file__}")


def test_sdk_reference_transport_uses_callback_free_dispatch_runtime() -> None:
    assert [field.name for field in fields(ProviderDispatchRuntime)] == [
        "config",
        "provider",
        "boot_id",
        "cancellations",
    ]


async def test_sdk_only_transport_can_execute_request(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    transport_impl = _StubTransport()
    egress = transport_impl.build_egress(conversation_ref="stub:conversation:1", config=config)
    provider = _StubProvider()
    sessions = _StubSessions(config)
    artifacts = _StubArtifacts(tmp_path)

    dispatch = ProviderDispatchRuntime(
        config=config,
        provider=provider,
        boot_id="sdk-proof",
        cancellations={},
    )
    runtime = ExecutionRuntime(
        dispatch=dispatch,
        services=ExecutionServices(
            guidance=_StubGuidance(),
            skill_activation=_StubSkillActivation(),
            runtime_skill_setup=_StubRuntimeSkillSetup(),
            sessions=sessions,
            artifacts=artifacts,
        ),
        interrupted_exc=RuntimeError,
    )
    transport = TransportIdentity(
        conversation_key="stub:conversation:1",
        origin_channel=transport_impl.transport_id,
        actor="stub:user:1",
        external_conversation_ref="1",
        target_agent_id="",
        conversation_ref="stub:conversation:1",
        routed_task_id="",
        authority_ref="",
    )

    outcome = await execute_request(
        transport,
        "Say hello the SDK proof transport.",
        [],
        egress,
        runtime=runtime,
    )

    assert outcome == RequestExecutionOutcome(status="completed", reply_text="sdk response")
    assert egress.status_labels == ["Working…"]
    assert egress.sent_texts == ["sdk response"]
    assert artifacts.saved_items == [
        (
            "stub:conversation:1",
            "Say hello the SDK proof transport.",
            "sdk response",
            "request",
        )
    ]
class _WorkflowRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record(self, name: str, *args: object, **kwargs: object) -> None:
        self.calls.append((name, args, kwargs))


class _StubConversationControl:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def reset_session(self, session: SessionState, **kwargs: object) -> ConversationResetOutcome:
        self._recorder.record("conversation.reset_session", session, **kwargs)
        return ConversationResetOutcome(status="reset")

    def cancel_conversation(self, session: SessionState, **kwargs: object) -> ConversationCancelOutcome:
        self._recorder.record("conversation.cancel_conversation", session, **kwargs)
        return ConversationCancelOutcome(status="cancelled", mutated=True)


class _StubConversationSettings:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def model_profile_state(self, session: SessionState, cfg: BotConfigBase, trust_tier: str, effective_model: str) -> ModelProfileState:
        self._recorder.record("conversation.model_profile_state", session, cfg, trust_tier, effective_model)
        return ModelProfileState(available_profiles=("default",), current_profile="default")

    def set_approval_mode(self, session: SessionState, value: str) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_approval_mode", session, value=value)
        return SettingMutationOutcome(status="updated", mutated=True, message=value)

    def set_compact_mode(self, session: SessionState, value: bool) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_compact_mode", session, value=value)
        return SettingMutationOutcome(status="updated", mutated=True, compact_enabled=value)

    def set_role(self, session: SessionState, value: str, *, default_role: str) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_role", session, value=value, default_role=default_role)
        return SettingMutationOutcome(status="updated", mutated=True, message=value)

    def set_model_profile(self, session: SessionState, profile: str, **kwargs: object) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_model_profile", session, profile=profile, **kwargs)
        return SettingMutationOutcome(status="updated", mutated=True, current_profile=profile)

    def set_project(self, session: SessionState, value: str, **kwargs: object) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_project", session, value=value, **kwargs)
        return SettingMutationOutcome(status="updated", mutated=True, message=value)

    def set_file_policy(self, session: SessionState, value: str, **kwargs: object) -> SettingMutationOutcome:
        self._recorder.record("conversation.set_file_policy", session, value=value, **kwargs)
        return SettingMutationOutcome(status="updated", mutated=True, effective_policy=value)


class _StubPendingRequests:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def approve(self, session: SessionState, **kwargs: object) -> PendingRequestOutcome:
        self._recorder.record("pending.approve", session, **kwargs)
        return PendingRequestOutcome(
            status="approved",
            mutated=True,
            execution_plan=PendingExecutionPlan(
                prompt="run",
                image_paths=(),
                actor_key="sdk:actor",
                trust_tier="trusted",
                extra_dirs=(),
            ),
        )

    def reject(self, session: SessionState) -> PendingRequestOutcome:
        self._recorder.record("pending.reject", session)
        return PendingRequestOutcome(status="rejected", mutated=True)

    def retry_skip(self, session: SessionState) -> PendingRequestOutcome:
        self._recorder.record("pending.retry_skip", session)
        return PendingRequestOutcome(status="retry_skipped", mutated=True)

    def retry_allow(self, session: SessionState, **kwargs: object) -> PendingRequestOutcome:
        self._recorder.record("pending.retry_allow", session, **kwargs)
        return PendingRequestOutcome(status="retry_allowed", mutated=True)


class _StubCredentialManagement:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def load_credentials(self, actor_key: str) -> dict[str, str]:
        self._recorder.record("credentials.load_credentials", actor_key)
        return {"API_KEY": "secret"}

    def list_stored_skills(self, actor_key: str) -> tuple[str, ...]:
        self._recorder.record("credentials.list_stored_skills", actor_key)
        return ("docs",)

    def clear_credentials(self, session: SessionState, *, actor_key: str, skill_name: str | None) -> CredentialClearOutcome:
        self._recorder.record("credentials.clear_credentials", session, actor_key=actor_key, skill_name=skill_name)
        return CredentialClearOutcome(
            removed_skills=tuple(filter(None, [skill_name])),
            deactivated_skills=tuple(filter(None, [skill_name])),
            setup_cleared=True,
            mutated=True,
        )


class _StubProviderGuidancePreview:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def preview(self, provider_name: str, *, role: str, active_skills: list[str], compact_mode: bool) -> ProviderGuidancePreview:
        self._recorder.record("provider_guidance.preview", provider_name, role=role, active_skills=active_skills, compact_mode=compact_mode)
        return ProviderGuidancePreview(
            provider=provider_name,
            effective_guidance="guidance",
            system_prompt="system",
            capability_summary="summary",
            provider_config=ProviderConfigRecord(),
            prompt_weight=1,
        )


class _StubProviderGuidanceManagement:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def detail(self, provider_name: str, **kwargs: object) -> None:
        self._recorder.record("provider_guidance.detail", provider_name, **kwargs)
        return None

    def edit_draft(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.edit_draft", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="edited", ok=True, message="edited")

    def submit(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.submit", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="submitted", ok=True, message="submitted")

    def approve(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.approve", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="approved", ok=True, message="approved")

    def reject(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.reject", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="rejected", ok=True, message="rejected")

    def publish(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.publish", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="published", ok=True, message="published")

    def archive(self, provider_name: str, **kwargs: object) -> ProviderGuidanceLifecycleMutation:
        self._recorder.record("provider_guidance.archive", provider_name, **kwargs)
        return ProviderGuidanceLifecycleMutation(status="archived", ok=True, message="archived")


class _StubRuntimeSkillCatalog:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def list_skills(self, query: str = "") -> list[RuntimeSkillCatalogItem]:
        self._recorder.record("skills.list_skills", query)
        return [
            RuntimeSkillCatalogItem(
                name="docs",
                display_name="Docs",
                description="Docs skill",
                source_kind="runtime",
                providers=("stub",),
                requirement_keys=(),
                has_custom_override=False,
                can_activate=True,
                can_update=False,
                can_uninstall=False,
            )
        ]

    def get_skill(self, skill_name: str):
        self._recorder.record("skills.get_skill", skill_name)
        return None

    def has_skill(self, skill_name: str) -> bool:
        self._recorder.record("skills.has_skill", skill_name)
        return True

    def has_runtime_skill(self, skill_name: str) -> bool:
        self._recorder.record("skills.has_runtime_skill", skill_name)
        return True

    def resolve_runtime_track(self, skill_name: str):
        self._recorder.record("skills.resolve_runtime_track", skill_name)
        return None

    def filter_resolvable(self, names: list[str]) -> list[str]:
        self._recorder.record("skills.filter_resolvable", tuple(names))
        return names

    def requirements(self, skill_name: str) -> tuple[SkillRequirement, ...]:
        self._recorder.record("skills.requirements", skill_name)
        return ()

    def missing_requirements(
        self,
        skill_name: str,
        credential_values: dict[str, str],
    ) -> tuple[SkillRequirement, ...]:
        self._recorder.record("skills.missing_requirements", skill_name, credential_values=credential_values)
        return ()

    def create_custom_draft(self, skill_name: str, *, owner_actor: str = ""):
        self._recorder.record("skills.create_custom_draft", skill_name, owner_actor=owner_actor)
        return RuntimeSkillDraftRecord(name=skill_name, visibility="private")


class _StubRuntimeSkillActivation:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def list_conversation_skills(self, active_skills: list[str]) -> ConversationSkillListing:
        self._recorder.record("skills.list_conversation_skills", tuple(active_skills))
        return ConversationSkillListing(active_skills=tuple(active_skills), active_skill_details=())

    def begin_activate(self, session: SessionState, **kwargs: object) -> ConversationSkillMutationOutcome:
        self._recorder.record("skills.begin_activate", session, **kwargs)
        return ConversationSkillMutationOutcome(status="activated", mutated=True)

    def confirm_activate(self, session: SessionState, skill_name: str) -> ConversationSkillMutationOutcome:
        self._recorder.record("skills.confirm_activate", session, skill_name=skill_name)
        return ConversationSkillMutationOutcome(status="activated", mutated=True)

    def begin_setup(self, session: SessionState, **kwargs: object) -> ConversationSkillMutationOutcome:
        self._recorder.record("skills.begin_setup", session, **kwargs)
        return ConversationSkillMutationOutcome(status="setup_started", mutated=True)

    def deactivate(self, session: SessionState, **kwargs: object) -> ConversationSkillMutationOutcome:
        self._recorder.record("skills.deactivate", session, **kwargs)
        return ConversationSkillMutationOutcome(status="deactivated", mutated=True)

    def clear(self, session: SessionState, **kwargs: object) -> ConversationSkillMutationOutcome:
        self._recorder.record("skills.clear", session, **kwargs)
        return ConversationSkillMutationOutcome(status="cleared", mutated=True)


class _StubRuntimeSkillImport:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def search(self, query: str, *, registry_url: str = "") -> RuntimeSkillSearchResults:
        self._recorder.record("skills.search", query, registry_url=registry_url)
        return RuntimeSkillSearchResults(catalog=(), registry=())

    def install_from_registry(self, skill_name: str, registry_url: str, **kwargs: object) -> RuntimeSkillMutationOutcome:
        self._recorder.record("skills.install_from_registry", skill_name, registry_url=registry_url, **kwargs)
        return RuntimeSkillMutationOutcome(name=skill_name, ok=True, message="installed")

    def uninstall(self, skill_name: str, **kwargs: object) -> RuntimeSkillMutationOutcome:
        self._recorder.record("skills.uninstall", skill_name, **kwargs)
        return RuntimeSkillMutationOutcome(name=skill_name, ok=True, message="uninstalled")

    def update(self, skill_name: str, **kwargs: object) -> RuntimeSkillMutationOutcome:
        self._recorder.record("skills.update", skill_name, **kwargs)
        return RuntimeSkillMutationOutcome(name=skill_name, ok=True, message="updated")

    def update_all(self, **kwargs: object) -> tuple[RuntimeSkillMutationOutcome, ...]:
        self._recorder.record("skills.update_all", **kwargs)
        return ()

    def diff(self, skill_name: str) -> RuntimeSkillMutationOutcome:
        self._recorder.record("skills.diff", skill_name)
        return RuntimeSkillMutationOutcome(name=skill_name, ok=True, message="diff")

    def list_updates(self) -> tuple[object, ...]:
        self._recorder.record("skills.list_updates")
        return ()


class _StubRuntimeSkillSetup:
    def __init__(self, recorder: _WorkflowRecorder | None = None) -> None:
        self._recorder = recorder or _WorkflowRecorder()

    def begin_setup(self, session: SessionState, **kwargs: object) -> RuntimeSkillCredentialSatisfactionOutcome:
        self._recorder.record("skills_setup.begin_setup", session, **kwargs)
        return RuntimeSkillCredentialSatisfactionOutcome(
            status="setup_started",
            mutated=True,
            credential_env=CredentialEnvRecord(),
        )

    def foreign_setup(self, session: SessionState, **kwargs: object):
        self._recorder.record("skills_setup.foreign_setup", session, **kwargs)
        return RuntimeSkillSetupState(status="none", setup=None)

    def cancel(self, session: SessionState, **kwargs: object):
        self._recorder.record("skills_setup.cancel", session, **kwargs)
        return RuntimeSkillSetupCancellationOutcome(
            status="cancelled",
            mutated=True,
            foreign_setup=None,
        )

    def check_satisfaction(self, session: SessionState, **kwargs: object) -> RuntimeSkillCredentialSatisfactionOutcome:
        self._recorder.record("skills_setup.check_satisfaction", session, **kwargs)
        return RuntimeSkillCredentialSatisfactionOutcome(
            status="satisfied",
            mutated=False,
            credential_env=CredentialEnvRecord(),
        )

    async def submit_credential_value(self, session: SessionState, **kwargs: object):
        self._recorder.record("skills_setup.submit_credential_value", session, **kwargs)
        return RuntimeSkillSetupAdvanceOutcome(status="advanced", mutated=True)

    def apply_cleared_credentials(self, session: SessionState, **kwargs: object):
        self._recorder.record("skills_setup.apply_cleared_credentials", session, **kwargs)
        return RuntimeSkillCredentialClearOutcome(
            mutated=True,
            setup_cleared=True,
            deactivated_skills=(),
        )


class _StubRuntimeSkillAuthoring:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def detail(self, skill_name: str):
        self._recorder.record("skills_authoring.detail", skill_name)
        return None

    def create_draft(self, skill_name: str, *, owner_actor: str = "") -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_authoring.create_draft", skill_name, owner_actor=owner_actor)
        return RuntimeSkillLifecycleMutation(status="drafted", ok=True, message="drafted")

    def edit_draft(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_authoring.edit_draft", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="edited", ok=True, message="edited")

    def submit(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_authoring.submit", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="submitted", ok=True, message="submitted")

    def publish(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_authoring.publish", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="published", ok=True, message="published")

    def archive(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_authoring.archive", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="archived", ok=True, message="archived")


class _StubRuntimeSkillApproval:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def approve(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_approval.approve", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="approved", ok=True, message="approved")

    def reject(self, skill_name: str, **kwargs: object) -> RuntimeSkillLifecycleMutation:
        self._recorder.record("skills_approval.reject", skill_name, **kwargs)
        return RuntimeSkillLifecycleMutation(status="rejected", ok=True, message="rejected")


class _StubRecovery:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def prepare_action(self, **kwargs: object) -> RecoveryActionOutcome:
        self._recorder.record("recovery.prepare_action", **kwargs)
        return RecoveryActionOutcome(status="ready")

    def complete_replay(self, **kwargs: object) -> None:
        self._recorder.record("recovery.complete_replay", **kwargs)

    def fail_replay(self, **kwargs: object) -> None:
        self._recorder.record("recovery.fail_replay", **kwargs)

    async def dispatch_worker_recovery(self, **kwargs: object):
        self._recorder.record("recovery.dispatch_worker_recovery", **kwargs)
        return WorkerRecoveryOutcome(status="dispatched", notice=None)


class _StubAuthorization:
    def __init__(self, recorder: _WorkflowRecorder) -> None:
        self._recorder = recorder

    def is_allowed(self, config: BotConfigBase, user: object | None, *, override: str | None = None) -> bool:
        self._recorder.record("authorization.is_allowed", config, user, override=override)
        return True

    def is_admin(self, config: BotConfigBase, user: object | None) -> bool:
        self._recorder.record("authorization.is_admin", config, user)
        return True

    def trust_tier(self, config: BotConfigBase, user: object | None) -> str:
        self._recorder.record("authorization.trust_tier", config, user)
        return "trusted"

    def access_policy(self, config: BotConfigBase, user: object | None, *, override: str | None = None) -> str:
        self._recorder.record("authorization.access_policy", config, user, override=override)
        return "allow"


class _StubWorkQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def record_and_admit_message(self, *args: object, **kwargs: object) -> tuple[str, str]:
        self.calls.append(("record_and_admit_message", args, kwargs))
        return "admitted", "work-1"

    def record_and_enqueue(self, *args: object, **kwargs: object) -> tuple[bool, str]:
        self.calls.append(("record_and_enqueue", args, kwargs))
        return True, "work-2"

    def record_update(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("record_update", args, kwargs))
        return True


class _StubRegistryParticipant:
    async def enroll(self) -> EnrollmentResult:
        return EnrollmentResult(
            agent_id="stub-agent",
            agent_token="stub-token",
            slug="stub-agent",
            poll_cursor="0",
        )

    async def heartbeat(self) -> None:
        return None

    def is_enrolled(self, authority: str) -> bool:
        return authority == "stub"

    def local_agent_id(self, authority: str) -> str:
        return "stub-agent" if authority == "stub" else ""


class _StubRegistryMirror:
    async def create_conversation(self, conversation_key: str, *, origin_channel: str, external_ref: object) -> str:
        del conversation_key, origin_channel, external_ref
        return "conv-1"

    async def publish_events(self, conversation_id: str, events: list[object]) -> list[MirrorOutcome]:
        del conversation_id, events
        return []

    async def submit_message(self, conversation_id: str, *, text: str, actor: str) -> list[MirrorOutcome]:
        del conversation_id, text, actor
        return []

    async def submit_action(self, conversation_id: str, *, envelope: object) -> list[MirrorOutcome]:
        del conversation_id, envelope
        return []


class _StubRegistryCoordination:
    async def ensure_conversation_id(
        self,
        conversation_key: str,
        *,
        conversation_ref: str,
        origin_channel: str,
        external_ref: object,
        title: str,
    ) -> str:
        del conversation_key, conversation_ref, origin_channel, external_ref, title
        return "conv-1"

    async def direct_assign(self, conversation_id: str, *, selector: object, title: str, instructions: str, message_text: str = "") -> CoordinationActionResult:
        del conversation_id, selector, title, instructions, message_text
        return CoordinationActionResult(
            conversation_id="conv-1",
            action_id="action-1",
            action="direct_assign",
            accepted=False,
            status="unavailable",
        )

    async def delegate_tasks(self, conversation_id: str, *, intent: object) -> CoordinationActionResult:
        del conversation_id, intent
        return CoordinationActionResult(
            conversation_id="conv-1",
            action_id="action-2",
            action="delegate_tasks",
            accepted=False,
            status="unavailable",
        )

    async def approve_delegation(self, conversation_id: str, *, proposal_id: str) -> CoordinationActionResult:
        del conversation_id, proposal_id
        return CoordinationActionResult(
            conversation_id="conv-1",
            action_id="action-3",
            action="approve_delegation",
            accepted=False,
            status="unavailable",
        )

    async def cancel_delegation(self, conversation_id: str, *, proposal_id: str) -> CoordinationActionResult:
        del conversation_id, proposal_id
        return CoordinationActionResult(
            conversation_id="conv-1",
            action_id="action-4",
            action="cancel_delegation",
            accepted=False,
            status="unavailable",
        )

    async def preview_target_resolution(self, selector: object) -> TargetResolutionPreview:
        del selector
        return TargetResolutionPreview(status="unavailable")


class _StubRegistryDiscovery:
    async def search_agents(self, *, query: object) -> AgentSearchResult:
        del query
        return AgentSearchResult(status="unavailable")

    async def resolve_authority(self, *, selector: object) -> str:
        del selector
        return "stub"


class _StubRegistryHealth:
    def enrollment_state(self) -> dict[str, EnrollmentResult]:
        return {
            "stub": EnrollmentResult(
                agent_id="stub-agent",
                agent_token="stub-token",
                slug="stub-agent",
                poll_cursor="0",
            )
        }

    def connectivity_state(self, authority: str) -> str:
        del authority
        return "connected"

    def current_local_agent_ids(self) -> dict[str, str]:
        return {"stub": "stub-agent"}

    def live_local_agent_ids(self) -> dict[str, str]:
        return {"stub": "stub-agent"}


@dataclass
class _StubRegistryParticipantImplementation:
    enrollment: _StubRegistryParticipant
    mirror: _StubRegistryMirror
    coordination: _StubRegistryCoordination
    discovery: _StubRegistryDiscovery
    health: _StubRegistryHealth


def _sdk_workflows(recorder: _WorkflowRecorder) -> WorkflowComposition:
    return WorkflowComposition(
        runtime_skills=RuntimeSkillWorkflows(
            catalog=_StubRuntimeSkillCatalog(recorder),
            activation=_StubRuntimeSkillActivation(recorder),
            imports=_StubRuntimeSkillImport(recorder),
            setup=_StubRuntimeSkillSetup(recorder),
            authoring=_StubRuntimeSkillAuthoring(recorder),
            approval=_StubRuntimeSkillApproval(recorder),
        ),
        credentials=CredentialWorkflows(
            management=_StubCredentialManagement(recorder),
        ),
        conversation=ConversationWorkflows(
            control=_StubConversationControl(recorder),
            settings=_StubConversationSettings(recorder),
        ),
        pending=PendingWorkflows(
            requests=_StubPendingRequests(recorder),
        ),
        recovery=RecoveryWorkflows(
            replay=_StubRecovery(recorder),
        ),
        provider_guidance=ProviderGuidanceWorkflows(
            preview=_StubProviderGuidancePreview(recorder),
            management=_StubProviderGuidanceManagement(recorder),
        ),
    )


def _sdk_runtime(tmp_path: Path, recorder: _WorkflowRecorder | None = None, work_queue: _StubWorkQueue | None = None) -> BotRuntime:
    config = _make_config(tmp_path)
    return BotRuntime(
        config=config,
        transport=_StubTransport(),
        registry=_StubRegistryParticipantImplementation(
            enrollment=_StubRegistryParticipant(),
            mirror=_StubRegistryMirror(),
            coordination=_StubRegistryCoordination(),
            discovery=_StubRegistryDiscovery(),
            health=_StubRegistryHealth(),
        ),
        provider=_StubProvider(),
        sessions=_StubSessions(config),
        workflows=_sdk_workflows(recorder or _WorkflowRecorder()),
        authorization=_StubAuthorization(recorder or _WorkflowRecorder()),
        work_queue=work_queue or _StubWorkQueue(),
    )


async def test_sdk_only_runtime_submit_uses_work_queue_contract(tmp_path: Path) -> None:
    work_queue = _StubWorkQueue()
    runtime = _sdk_runtime(tmp_path, work_queue=work_queue)

    message_event = InboundMessage(
        user=InboundUser(id="stub:user:1", username="sdk"),
        conversation_key="stub:conversation:1",
        text="hello",
        source="stub",
    )
    message_envelope = InboundEnvelope(
        transport="stub",
        event_id="evt-1",
        conversation_key="stub:conversation:1",
        actor_key="stub:user:1",
        received_at=datetime.now(timezone.utc),
        event=message_event,
    )
    action_event = InboundAction(
        user=InboundUser(id="stub:user:1", username="sdk"),
        conversation_key="stub:conversation:1",
        action="approve_pending",
        params=InboundActionParamsRecord(),
        source="stub",
    )
    action_envelope = InboundEnvelope(
        transport="stub",
        event_id="evt-2",
        conversation_key="stub:conversation:1",
        actor_key="stub:user:1",
        received_at=datetime.now(timezone.utc),
        event=action_event,
    )

    admitted = await runtime.submit(message_envelope)
    queued = await runtime.submit(action_envelope)
    recorded = await runtime.record(action_envelope)

    assert admitted.status == "admitted"
    assert queued.status == "queued"
    assert recorded is True
    assert [name for name, _args, _kwargs in work_queue.calls] == [
        "record_and_admit_message",
        "record_and_enqueue",
        "record_update",
    ]


def test_sdk_only_runtime_exposes_full_operator_workflow_surface(tmp_path: Path) -> None:
    recorder = _WorkflowRecorder()
    runtime = _sdk_runtime(tmp_path, recorder=recorder)
    session = _StubSessions(runtime.config).load(
        "stub:conversation:1",
        provider_name="stub",
        provider_state_factory=_provider_state_factory,
        approval_mode="off",
    )

    runtime.workflows.conversation.control.reset_session(
        session,
        actor_key="sdk:actor",
        provider_name="stub",
        provider_state_factory=_provider_state_factory,
        approval_mode_default="off",
        default_role="",
        default_skills=(),
        conversation_key="stub:conversation:1",
    )
    runtime.workflows.conversation.settings.set_model_profile(
        session,
        "default",
        cfg=runtime.config,
        provider_name="stub",
        trust_tier="trusted",
    )
    runtime.workflows.pending.requests.approve(
        session,
        cfg=runtime.config,
        provider_name="stub",
    )
    assert runtime.workflows.credentials.management.load_credentials("sdk:actor") == {"API_KEY": "secret"}
    preview = runtime.workflows.provider_guidance.preview.preview(
        "stub",
        role="operator",
        active_skills=[],
        compact_mode=False,
    )
    assert preview.provider == "stub"
    runtime.workflows.provider_guidance.management.edit_draft(
        "stub",
        actor_key="sdk:actor",
        body="body",
    )
    runtime.workflows.runtime_skills.catalog.list_skills("docs")
    runtime.workflows.runtime_skills.activation.list_conversation_skills(["docs"])
    runtime.workflows.runtime_skills.imports.search("docs", registry_url="http://registry")
    satisfaction = runtime.workflows.runtime_skills.setup.check_satisfaction(
        session,
        actor_key="sdk:actor",
        active_skills=["docs"],
    )
    assert satisfaction.status == "satisfied"
    runtime.workflows.runtime_skills.authoring.create_draft("docs", owner_actor="sdk:actor")
    runtime.workflows.runtime_skills.approval.approve("docs", actor_key="sdk:actor")
    outcome = runtime.workflows.recovery.replay.prepare_action(
        data_dir=runtime.config.data_dir,
        conversation_key="stub:conversation:1",
        event_id="evt-1",
        action="recovery_replay",
        worker_id="worker-1",
    )
    assert outcome.status == "ready"
    assert runtime.authorization.access_policy(runtime.config, None) == "allow"
    assert any(name == "conversation.reset_session" for name, _args, _kwargs in recorder.calls)
    assert any(name == "pending.approve" for name, _args, _kwargs in recorder.calls)
    assert any(name == "skills.search" for name, _args, _kwargs in recorder.calls)
    assert any(name == "recovery.prepare_action" for name, _args, _kwargs in recorder.calls)
