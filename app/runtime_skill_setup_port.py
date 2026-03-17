"""Contracts for runtime skill credential setup workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.credential_types import CredentialValidator
from app.session_state import AwaitingSkillSetup, SessionState


@dataclass(frozen=True)
class RuntimeSkillSetupState:
    status: str
    setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupCancellationOutcome:
    status: str
    mutated: bool = False
    foreign_setup: AwaitingSkillSetup | None = None


@dataclass(frozen=True)
class RuntimeSkillSetupAdvanceOutcome:
    status: str
    mutated: bool = False
    validation_key: str = ""
    validation_error: str = ""
    next_requirement: dict[str, object] | None = None
    skill_name: str = ""


@dataclass(frozen=True)
class RuntimeSkillCredentialSatisfactionOutcome:
    status: str
    mutated: bool = False
    credential_env: dict[str, str] | None = None
    foreign_setup: AwaitingSkillSetup | None = None
    setup_state: AwaitingSkillSetup | None = None
    missing_skill: str = ""
    first_requirement: dict[str, object] | None = None


@dataclass(frozen=True)
class RuntimeSkillCredentialClearOutcome:
    mutated: bool
    setup_cleared: bool
    deactivated_skills: tuple[str, ...]


class RuntimeSkillSetupPort(Protocol):
    def foreign_setup(
        self,
        session: SessionState,
        *,
        user_id: str,
        skill_name: str | None = None,
    ) -> RuntimeSkillSetupState: ...

    def cancel(
        self,
        session: SessionState,
        *,
        user_id: str,
        allow_override: bool = False,
    ) -> RuntimeSkillSetupCancellationOutcome: ...

    def check_satisfaction(
        self,
        session: SessionState,
        *,
        user_id: str,
        active_skills: list[str],
        data_dir: Path,
        encryption_key: bytes,
    ) -> RuntimeSkillCredentialSatisfactionOutcome: ...

    async def submit_credential_value(
        self,
        session: SessionState,
        *,
        user_id: str,
        raw_value: str,
        data_dir: Path,
        encryption_key: bytes,
        validator: CredentialValidator,
    ) -> RuntimeSkillSetupAdvanceOutcome: ...

    def apply_cleared_credentials(
        self,
        session: SessionState,
        *,
        user_id: str,
        removed_skills: list[str],
        skill_name: str | None,
    ) -> RuntimeSkillCredentialClearOutcome: ...
