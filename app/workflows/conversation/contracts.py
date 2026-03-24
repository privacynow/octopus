"""Workflow-local contracts for conversation control and settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.config import BotConfig
from app.session_state import SessionState

ProviderStateFactory = Callable[[str], dict]


@dataclass(frozen=True)
class ConversationResetOutcome:
    status: str
    message: str = ""
    replacement_session: SessionState | None = None
    cleanup_scripts: bool = False


@dataclass(frozen=True)
class ConversationCancelOutcome:
    status: str
    mutated: bool = False
    message: str = ""


class ConversationControlPort(Protocol):
    def reset_session(
        self,
        session: SessionState,
        *,
        actor_key: str,
        provider_name: str,
        provider_state_factory: ProviderStateFactory,
        approval_mode_default: str,
        default_role: str,
        default_skills: tuple[str, ...],
        conversation_key: str,
    ) -> ConversationResetOutcome: ...

    def cancel_conversation(
        self,
        session: SessionState,
        *,
        data_dir: Path,
        conversation_key: str,
        actor_key: str,
        live_cancel_event: Any = None,
        cancel_request_event_id: str = "",
        allow_override: bool = False,
    ) -> ConversationCancelOutcome: ...


@dataclass(frozen=True)
class ModelProfileState:
    available_profiles: tuple[str, ...]
    current_profile: str


@dataclass(frozen=True)
class SettingMutationOutcome:
    status: str
    mutated: bool = False
    message: str = ""
    effective_policy: str = ""
    effective_model: str = ""
    current_profile: str = ""
    compact_enabled: bool | None = None


class ConversationSettingsPort(Protocol):
    def model_profile_state(
        self,
        session: SessionState,
        cfg: BotConfig,
        trust_tier: str,
        effective_model: str,
    ) -> ModelProfileState: ...

    def set_approval_mode(self, session: SessionState, value: str) -> SettingMutationOutcome: ...

    def set_compact_mode(self, session: SessionState, value: bool) -> SettingMutationOutcome: ...

    def set_role(
        self,
        session: SessionState,
        value: str,
        *,
        default_role: str,
    ) -> SettingMutationOutcome: ...

    def set_model_profile(
        self,
        session: SessionState,
        profile: str,
        *,
        cfg: BotConfig,
        provider_name: str,
        trust_tier: str,
    ) -> SettingMutationOutcome: ...

    def set_project(
        self,
        session: SessionState,
        value: str,
        *,
        cfg: BotConfig,
        provider_state_factory: ProviderStateFactory,
        conversation_key: str,
    ) -> SettingMutationOutcome: ...

    def set_file_policy(
        self,
        session: SessionState,
        value: str,
        *,
        cfg: BotConfig,
        provider_name: str,
        trust_tier: str,
        provider_state_factory: ProviderStateFactory,
        conversation_key: str,
    ) -> SettingMutationOutcome: ...
