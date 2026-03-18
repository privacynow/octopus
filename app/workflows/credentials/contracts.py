"""Workflow-local contracts for credential-management flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.credential_types import CredentialMap
from app.session_state import SessionState


@dataclass(frozen=True)
class CredentialClearOutcome:
    removed_skills: tuple[str, ...]
    deactivated_skills: tuple[str, ...]
    setup_cleared: bool
    mutated: bool


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
