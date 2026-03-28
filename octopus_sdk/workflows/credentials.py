"""SDK workflow contracts for credential management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from octopus_sdk.credential_types import CredentialMap
from octopus_sdk.sessions import SessionState
from octopus_sdk.skill_types import SkillRequirement


@dataclass(frozen=True)
class CredentialClearOutcome:
    removed_skills: tuple[str, ...]
    deactivated_skills: tuple[str, ...]
    setup_cleared: bool
    mutated: bool


class CredentialServicePort(Protocol):
    def list_skill_names(self, actor_key: str) -> list[str]: ...
    def load(self, actor_key: str) -> CredentialMap: ...
    def load_for_skills(self, actor_key: str, skill_names: list[str]) -> CredentialMap: ...
    def save(self, actor_key: str, skill_name: str, cred_key: str, value: str) -> None: ...
    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]: ...
    def missing_requirements(
        self,
        requirements: list[SkillRequirement],
        credential_values: dict[str, str],
    ) -> list[SkillRequirement]: ...
    def build_env(
        self,
        active_skills: list[str],
        user_credentials: CredentialMap,
    ) -> dict[str, str]: ...
    async def validate_value(
        self,
        requirement: SkillRequirement,
        value: str,
        *,
        validator: "CredentialValidatorPort | None" = None,
        skill_name: str | None = None,
    ) -> tuple[bool, str]: ...


class CredentialValidatorPort(Protocol):
    async def __call__(
        self,
        req: SkillRequirement,
        value: str,
        *,
        skill_name: str | None = None,
    ) -> tuple[bool, str]: ...


class CredentialManagementPort(Protocol):
    def load_credentials(self, actor_key: str) -> CredentialMap: ...

    def list_stored_skills(self, actor_key: str) -> tuple[str, ...]: ...

    def clear_credentials(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str | None,
    ) -> CredentialClearOutcome: ...
