"""Public runtime support contracts for transport implementations.

The SDK owns the execution/runtime contract surface needed to build a bot
without importing ``app.*`` internals. Concrete applications provide the
service implementations and transport-specific callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from octopus_sdk.config import BotConfigBase
from octopus_sdk.execution_context import ResolvedExecutionContext
from octopus_sdk.providers import PreflightContext, RunContext
from octopus_sdk.sessions import SessionState


@runtime_checkable
class ProviderGuidancePort(Protocol):
    def check_prompt_size_cross_chat(
        self,
        data_dir: Path,
        skill_name: str,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
    ) -> list[str]: ...

    def prompt_weight(
        self,
        role: str,
        active_skills: list[str],
        available_agents: list[dict[str, str]] | None = None,
    ) -> int: ...

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
    ) -> RunContext: ...

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
    ) -> PreflightContext: ...

    def apply_compact_mode(
        self,
        system_prompt: str,
        compact: bool,
    ) -> str: ...

    def stage_codex_scripts(
        self,
        data_dir: Path,
        conversation_key: str,
        active_skills: list[str],
    ) -> Path | None: ...


@runtime_checkable
class SkillActivationPort(Protocol):
    def normalize(self, session: SessionState) -> list[str]: ...


@runtime_checkable
class RuntimeSkillSetupPort(Protocol):
    def check_satisfaction(
        self,
        session: SessionState,
        *,
        actor_key: str,
        active_skills: list[str],
    ) -> Any: ...


@runtime_checkable
class SessionRuntimePort(Protocol):
    def load(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState: ...

    def save(
        self,
        conversation_key: str,
        session: SessionState,
    ) -> None: ...

    def resolve_context(
        self,
        session: SessionState,
        *,
        config: BotConfigBase,
        provider_name: str,
        trust_tier: str = "trusted",
    ) -> ResolvedExecutionContext: ...


@runtime_checkable
class ArtifactStorePort(Protocol):
    def upload_dir(
        self,
        conversation_key: str,
    ) -> Path: ...

    def save_raw(
        self,
        conversation_key: str,
        prompt: str,
        raw_text: str,
        *,
        kind: str = "request",
    ) -> int: ...


@dataclass(frozen=True)
class ExecutionServices:
    guidance: ProviderGuidancePort
    skill_activation: SkillActivationPort
    runtime_skill_setup: RuntimeSkillSetupPort
    sessions: SessionRuntimePort
    artifacts: ArtifactStorePort


def build_execution_runtime(
    *,
    dispatch,
    services: ExecutionServices,
    interrupted_exc: type[BaseException],
    build_transport_identity,
    build_event_sink,
    render_provider_error,
    show_foreign_setup,
    show_setup_prompt,
    send_retry_prompt,
    send_approval_prompt,
    send_formatted_reply,
    send_directed_artifacts,
    send_compact_reply,
    propose_delegation_plan,
    delegation_parser=None,
    agent_directory=None,
):
    from octopus_sdk.execution import ExecutionRuntime

    return ExecutionRuntime(
        dispatch=dispatch,
        services=services,
        interrupted_exc=interrupted_exc,
        build_transport_identity=build_transport_identity,
        build_event_sink=build_event_sink,
        render_provider_error=render_provider_error,
        show_foreign_setup=show_foreign_setup,
        show_setup_prompt=show_setup_prompt,
        send_retry_prompt=send_retry_prompt,
        send_approval_prompt=send_approval_prompt,
        send_formatted_reply=send_formatted_reply,
        send_directed_artifacts=send_directed_artifacts,
        send_compact_reply=send_compact_reply,
        propose_delegation_plan=propose_delegation_plan,
        delegation_parser=delegation_parser,
        agent_directory=agent_directory,
    )
