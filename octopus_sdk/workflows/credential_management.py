"""SDK-owned credential management workflows."""

from __future__ import annotations

from octopus_sdk.sessions import SessionState
from octopus_sdk.workflows.credentials import (
    CredentialClearOutcome,
    CredentialManagementPort,
    CredentialServicePort,
)
from octopus_sdk.workflows.skills import RuntimeSkillSetupPort


class CredentialManagementUseCases(CredentialManagementPort):
    def __init__(
        self,
        *,
        credentials: CredentialServicePort,
        setup: RuntimeSkillSetupPort,
    ) -> None:
        self._credentials = credentials
        self._setup = setup

    def load_credentials(self, actor_key: str):
        return self._credentials.load(actor_key)

    def list_stored_skills(self, actor_key: str) -> tuple[str, ...]:
        return tuple(self._credentials.list_skill_names(actor_key))

    def clear_credentials(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str | None,
    ) -> CredentialClearOutcome:
        removed = tuple(self._credentials.delete(actor_key, skill_name))
        outcome = self._setup.apply_cleared_credentials(
            session,
            actor_key=actor_key,
            removed_skills=list(removed),
            skill_name=skill_name,
        )
        return CredentialClearOutcome(
            removed_skills=removed,
            deactivated_skills=outcome.deactivated_skills,
            setup_cleared=outcome.setup_cleared,
            mutated=bool(removed) or outcome.mutated,
        )
