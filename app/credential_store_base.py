"""Backend-neutral credential-store contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractCredentialStore(ABC):
    @abstractmethod
    def list_skill_names(self, actor_key: str) -> list[str]:
        """Return skill names that have stored credentials for one actor."""

    @abstractmethod
    def load(self, actor_key: str) -> dict[str, dict[str, str]]:
        """Return plaintext credentials as {skill_name: {cred_key: value}}."""

    @abstractmethod
    def load_for_skills(self, actor_key: str, skill_names: list[str]) -> dict[str, dict[str, str]]:
        """Return plaintext credentials only for the requested skills."""

    @abstractmethod
    def save(
        self,
        actor_key: str,
        skill_name: str,
        cred_key: str,
        value: str,
    ) -> None:
        """Persist one credential value for one actor + skill."""

    @abstractmethod
    def delete(self, actor_key: str, skill_name: str | None = None) -> list[str]:
        """Delete one skill's credentials or all credentials for an actor."""
