import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from octopus_sdk.channels import ChannelBootstrap, ChannelDescriptor, ChannelIngress
from octopus_sdk.config import BotConfigBase
from octopus_sdk.egress import ChannelCapabilities, ChannelEgress, EditableHandle
from octopus_sdk.event_sink import NoOpEventSink
from octopus_sdk.execution import RequestExecutionOutcome, TransportIdentity, execute_request
from octopus_sdk.execution_context import ResolvedExecutionContext, resolve_execution_context
from octopus_sdk.providers import PreflightContext, Provider, RunContext, RunResult
from octopus_sdk.runtime import ExecutionServices, build_execution_runtime
from octopus_sdk.runtime_dispatch import RuntimeDispatchRuntime
from octopus_sdk.sessions import SessionState, default_session, session_from_dict, session_to_dict


class _StubEditableHandle(EditableHandle):
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        del text, kwargs

    async def edit_reply_markup(self, reply_markup: Any = None, **kwargs: Any) -> None:
        del reply_markup, kwargs


class _StubEgress(ChannelEgress):
    def __init__(self) -> None:
        self.sent_texts: list[str] = []

    @property
    def capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            can_edit_message=True,
            can_answer_action=False,
            can_send_photo=False,
            can_send_document=False,
            can_render_timeline=False,
            can_present_actions=False,
            can_share_conversation=False,
            channel_name="stub",
        )

    async def send_text(self, text: str, **kwargs: Any) -> EditableHandle:
        del kwargs
        self.sent_texts.append(text)
        return _StubEditableHandle()

    async def send_photo(self, photo: Path | str | bytes, **kwargs: Any) -> None:
        del photo, kwargs

    async def send_document(self, document: Path | str | bytes, **kwargs: Any) -> None:
        del document, kwargs

    async def send_action(self, action: str) -> None:
        del action

    async def answer_action(self, text: str | None = None, show_alert: bool = False) -> None:
        del text, show_alert


class _StubIngress(ChannelIngress):
    @property
    def channel_id(self) -> str:
        return "stub"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return ChannelDescriptor(
            channel_type="stub",
            display_name="Stub",
            supports_multiple=True,
            requires_polling=False,
            supports_conversation_binding=False,
            supports_timeline=False,
        )

    async def start(self, *, stop_event: asyncio.Event) -> None:
        del stop_event

    async def stop(self) -> None:
        return None

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True}


class _StubChannel(ChannelBootstrap):
    @property
    def channel_id(self) -> str:
        return "stub"

    @property
    def descriptor(self) -> ChannelDescriptor:
        return ChannelDescriptor(
            channel_type="stub",
            display_name="Stub",
            supports_multiple=True,
            requires_polling=False,
            supports_conversation_binding=False,
            supports_timeline=False,
        )

    def ref_prefix(self) -> str:
        return "stub:"

    def build_egress(self, *, conversation_ref: str, config: Any, **kw: Any) -> ChannelEgress:
        del conversation_ref, config, kw
        return _StubEgress()

    def build_ingress(self, *, config: Any, delivery_handler) -> ChannelIngress:
        del config, delivery_handler
        return _StubIngress()


class _StubProvider(Provider):
    name = "stub"

    def new_provider_state(self, conversation_key: str) -> dict[str, Any]:
        del conversation_key
        return {}

    async def run(
        self,
        provider_state: dict[str, Any],
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
        available_agents: list[dict[str, str]] | None = None,
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
        credential_env: dict[str, str] | None = None,
        working_dir: str = "",
        file_policy: str = "",
        effective_model: str = "",
        available_agents: list[dict[str, str]] | None = None,
    ) -> RunContext:
        del role, active_skills, provider_name, available_agents
        return RunContext(
            extra_dirs=extra_dirs,
            system_prompt="stub-system-prompt",
            capability_summary="",
            working_dir=working_dir,
            file_policy=file_policy,
            effective_model=effective_model,
            credential_env=credential_env or {},
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
    credential_env: dict[str, str] | None = None
    foreign_setup: Any = None
    setup_state: Any = None
    first_requirement: dict[str, object] | None = None
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
        return _StubSkillSetupOutcome(status="satisfied", credential_env={})


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
    def __init__(self, status_message: Any, config: BotConfigBase, timeline_callback=None) -> None:
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
        registry_agent_ids={},
    )


class _StubMessage:
    def __init__(self, egress: _StubEgress) -> None:
        self.egress = egress
        self.status_labels: list[str] = []
        self.reply_calls: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.reply_calls.append(text)


async def test_sdk_only_transport_can_execute_request(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    channel = _StubChannel()
    stub_ingress = channel.build_ingress(config=config, delivery_handler=lambda *args, **kwargs: None)
    egress = channel.build_egress(conversation_ref="stub:conversation:1", config=config)
    provider = _StubProvider()
    sessions = _StubSessions(config)
    artifacts = _StubArtifacts(tmp_path)

    dispatch = RuntimeDispatchRuntime(
        config=config,
        provider=provider,
        boot_id="sdk-proof",
        cancellations={},
        progress_factory=_StubProgress,
        send_status=_send_status,
        typing_target=lambda message: message,
        keep_typing=_no_op,
        heartbeat=_no_op,
        format_provider_error=_format_provider_error,
        run_result_was_interrupted=lambda _returncode: False,
    )
    runtime = build_execution_runtime(
        dispatch=dispatch,
        services=ExecutionServices(
            guidance=_StubGuidance(),
            skill_activation=_StubSkillActivation(),
            runtime_skill_setup=_StubRuntimeSkillSetup(),
            sessions=sessions,
            artifacts=artifacts,
        ),
        interrupted_exc=RuntimeError,
        build_transport_identity=lambda message, conversation_key, actor_key="": TransportIdentity(
            conversation_key=str(conversation_key),
            origin_channel="stub",
            external_conversation_ref=str(conversation_key),
            conversation_ref=f"stub:conversation:{conversation_key}",
            actor=actor_key,
        ),
        build_event_sink=lambda _transport: NoOpEventSink(),
        render_provider_error=lambda text: text,
        show_foreign_setup=_unexpected_async,
        show_setup_prompt=_unexpected_async,
        send_retry_prompt=_unexpected_async,
        send_approval_prompt=_unexpected_async,
        send_formatted_reply=_send_formatted_reply,
        send_directed_artifacts=_no_op,
        send_compact_reply=_send_compact_reply,
        propose_delegation_plan=_propose_delegation_plan,
    )
    message = _StubMessage(egress)
    transport = TransportIdentity(
        conversation_key="stub:conversation:1",
        origin_channel=channel.channel_id,
        external_conversation_ref="1",
        conversation_ref="stub:conversation:1",
        actor="stub:user:1",
    )

    outcome = await execute_request(
        transport,
        "Say hello from the SDK proof transport.",
        [],
        message,
        runtime=runtime,
    )

    assert stub_ingress.channel_id == "stub"
    assert outcome == RequestExecutionOutcome(status="completed", reply_text="sdk response")
    assert message.status_labels == ["Working…"]
    assert egress.sent_texts == ["sdk response"]
    assert artifacts.saved_items == [
        (
            "stub:conversation:1",
            "Say hello from the SDK proof transport.",
            "sdk response",
            "request",
        )
    ]


async def _send_status(message: _StubMessage, label: str) -> Any:
    message.status_labels.append(label)
    return SimpleNamespace()


async def _send_formatted_reply(message: _StubMessage, text: str, **kwargs: Any) -> None:
    del kwargs
    await message.egress.send_text(text)


async def _send_compact_reply(
    message: _StubMessage,
    text: str,
    conversation_key: str,
    slot: int,
) -> None:
    del conversation_key, slot
    await message.egress.send_text(text)


async def _format_provider_error(text: str, returncode: int) -> str:
    return f"{text} [{returncode}]"


async def _propose_delegation_plan(*args: Any, **kwargs: Any) -> RequestExecutionOutcome:
    del args, kwargs
    return RequestExecutionOutcome(status="completed")


async def _unexpected_async(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise AssertionError("unexpected async callback in sdk reference transport proof")


async def _no_op(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
