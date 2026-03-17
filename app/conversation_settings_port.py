"""Contracts for conversation settings workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.config import BotConfig
from app.session_state import SessionState

ProviderStateFactory = Callable[[], dict]


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
    ) -> SettingMutationOutcome: ...
