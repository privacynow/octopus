"""Shared credential-domain service."""

from __future__ import annotations

from app.credential_store import get_credential_store
from app.credential_types import CredentialMap, CredentialValidator
from app.credential_validation import validate_credential as default_validate_credential
from app.skill_types import SkillRequirement


class CredentialService:
    def _store(self):
        return get_credential_store()

    def list_skill_names(self, actor_key: str) -> list[str]:
        return self._store().list_skill_names(actor_key)

    def load(self, actor_key: str) -> CredentialMap:
        return self._store().load(actor_key)

    def load_for_skills(self, actor_key: str, skill_names: list[str]) -> CredentialMap:
        normalized = [name for name in dict.fromkeys(skill_names) if name]
        if not normalized:
            return {}
        return self._store().load_for_skills(actor_key, normalized)

    def save(
        self,
        actor_key: str,
        skill_name: str,
        cred_key: str,
        value: str,
    ) -> None:
        self._store().save(actor_key, skill_name, cred_key, value)

    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]:
        return self._store().delete(actor_key, skill_name)

    def missing_requirements(
        self,
        requirements: list[SkillRequirement],
        credential_values: dict[str, str],
    ) -> list[SkillRequirement]:
        return [item for item in requirements if item.key not in credential_values]

    def build_env(
        self,
        active_skills: list[str],
        user_credentials: CredentialMap,
    ) -> dict[str, str]:
        env: dict[str, str] = {}
        for skill in active_skills:
            env.update(user_credentials.get(skill, {}))
        return env

    async def validate_value(
        self,
        requirement: SkillRequirement,
        value: str,
        *,
        validator: CredentialValidator | None = None,
        skill_name: str | None = None,
    ) -> tuple[bool, str]:
        if validator is None or validator is default_validate_credential:
            return await default_validate_credential(
                requirement,
                value,
                skill_name=skill_name,
            )
        return await validator(requirement, value)


_SERVICE = CredentialService()


def get_credential_service() -> CredentialService:
    return _SERVICE
