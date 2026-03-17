"""Concern-owned use cases for credential management workflows."""

from __future__ import annotations

from app.credential_management_port import CredentialClearOutcome, CredentialManagementPort
from app.credential_service import get_credential_service
from app.session_state import SessionState


class CredentialManagementUseCases(CredentialManagementPort):
    def _credentials(self):
        return get_credential_service()

    def load_credentials(self, actor_key: str):
        return self._credentials().load(actor_key)

    def list_stored_skills(self, actor_key: str) -> tuple[str, ...]:
        return tuple(self._credentials().list_skill_names(actor_key))

    def clear_credentials(
        self,
        session: SessionState,
        *,
        actor_key: str,
        skill_name: str | None,
    ) -> CredentialClearOutcome:
        from app.inbound_use_case_factory import get_runtime_skill_setup_use_cases

        removed = tuple(self._credentials().delete(actor_key, skill_name))
        outcome = get_runtime_skill_setup_use_cases().apply_cleared_credentials(
            session,
            user_id=actor_key,
            removed_skills=list(removed),
            skill_name=skill_name,
        )
        return CredentialClearOutcome(
            removed_skills=removed,
            deactivated_skills=outcome.deactivated_skills,
            setup_cleared=outcome.setup_cleared,
            mutated=bool(removed) or outcome.mutated,
        )


_USE_CASES = CredentialManagementUseCases()


def get_credential_management_use_cases() -> CredentialManagementUseCases:
    return _USE_CASES
