"""Shared runtime helpers for session loading, saving, and context resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import BotConfig
from octopus_sdk.bot_runtime import SessionRuntimePort, SkillActivationPort
from octopus_sdk.execution_context import ResolvedExecutionContext, resolve_execution_context
from octopus_sdk.sessions import (
    SessionState,
    normalize_provider_session,
    normalize_single_project_session,
    session_from_dict,
    session_to_dict,
)
from app.storage import (
    default_session,
    list_sessions,
    load_session,
    save_session,
    session_exists,
)
from octopus_sdk.workflows.skills import RuntimeSkillCatalogPort


CatalogResolver = RuntimeSkillCatalogPort | Callable[[], RuntimeSkillCatalogPort]


@dataclass(frozen=True)
class LocalSessionRuntime(SessionRuntimePort):
    config: BotConfig
    catalog: CatalogResolver | None = None
    activation: SkillActivationPort | None = None

    def _catalog(self) -> RuntimeSkillCatalogPort:
        catalog = self.catalog
        if callable(catalog):
            catalog = catalog()
        if catalog is None:
            raise RuntimeError("LocalSessionRuntime requires a runtime-skill catalog")
        return catalog

    def _activation(self) -> SkillActivationPort | None:
        return self.activation

    def load(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState:
        session = load_runtime_session(
            self.config.data_dir,
            conversation_key,
            provider_name=provider_name,
            provider_state_factory=provider_state_factory,
            approval_mode=approval_mode,
            default_role=default_role,
            default_skills=default_skills,
        )
        mutated = normalize_provider_session(
            session,
            provider_name=provider_name,
            provider_state_factory=provider_state_factory,
            conversation_key=conversation_key,
        )
        mutated = normalize_single_project_session(
            session,
            projects=self.config.projects,
            provider_state_factory=provider_state_factory,
            conversation_key=conversation_key,
        ) or mutated
        activation = self._activation()
        if activation is not None and activation.normalize(session):
            mutated = True
        if mutated:
            save_runtime_session(self.config.data_dir, conversation_key, session)
        return session

    def save(
        self,
        conversation_key: str,
        session: SessionState,
    ) -> None:
        save_runtime_session(self.config.data_dir, conversation_key, session)

    def list_incomplete_sessions(self) -> list[str]:
        keys: list[str] = []
        for record in list_sessions(self.config.data_dir):
            conversation_key = str(record.get("conversation_key", "") or "")
            if not conversation_key:
                continue
            if any(
                record.get(field)
                for field in (
                    "pending_approval",
                    "pending_retry",
                    "awaiting_skill_setup",
                    "pending_delegation",
                )
            ):
                keys.append(conversation_key)
        return keys

    def recover_after_crash(
        self,
        conversation_key: str,
        *,
        provider_name: str,
        provider_state_factory,
        approval_mode: str,
        default_role: str = "",
        default_skills: tuple[str, ...] = (),
    ) -> SessionState | None:
        if not session_exists(self.config.data_dir, conversation_key):
            return None
        session = load_runtime_session(
            self.config.data_dir,
            conversation_key,
            provider_name=provider_name,
            provider_state_factory=provider_state_factory,
            approval_mode=approval_mode,
            default_role=default_role,
            default_skills=default_skills,
        )
        mutated = normalize_provider_session(
            session,
            provider_name=provider_name,
            provider_state_factory=provider_state_factory,
            conversation_key=conversation_key,
        )
        mutated = normalize_single_project_session(
            session,
            projects=self.config.projects,
            provider_state_factory=provider_state_factory,
            conversation_key=conversation_key,
        ) or mutated
        activation = self._activation()
        if activation is not None and activation.normalize(session):
            mutated = True
        if mutated:
            save_runtime_session(self.config.data_dir, conversation_key, session)
        return session

    def resolve_context(
        self,
        session: SessionState,
        *,
        config: BotConfig,
        provider_name: str,
        trust_tier: str = "trusted",
    ) -> ResolvedExecutionContext:
        return resolve_session_context(
            session,
            config=config,
            provider_name=provider_name,
            trust_tier=trust_tier,
            catalog=self._catalog(),
        )


def resolve_session_context(
    session: SessionState,
    *,
    config: BotConfig,
    provider_name: str,
    trust_tier: str = "trusted",
    catalog: RuntimeSkillCatalogPort,
) -> ResolvedExecutionContext:
    return resolve_execution_context(
        session,
        config,
        provider_name,
        trust_tier=trust_tier,
        catalog=catalog,
    )


def load_runtime_session(
    data_dir: Path,
    conversation_key: str,
    *,
    provider_name: str,
    provider_state_factory: Callable[[str], dict],
    approval_mode: str,
    default_role: str = "",
    default_skills: tuple[str, ...] = (),
) -> SessionState:
    raw = load_session(
        data_dir,
        conversation_key,
        provider_name,
        provider_state_factory,
        approval_mode,
        default_role,
        default_skills,
    )
    return session_from_dict(raw)


def save_runtime_session(
    data_dir: Path,
    conversation_key: str,
    session: SessionState,
) -> None:
    save_session(data_dir, conversation_key, session_to_dict(session))

def default_runtime_session(
    *,
    provider_name: str,
    provider_state_factory: Callable[[str], dict],
    approval_mode: str,
    conversation_key: str,
    default_role: str = "",
    default_skills: tuple[str, ...] = (),
) -> SessionState:
    return session_from_dict(
        default_session(
            provider_name,
            provider_state_factory(conversation_key),
            approval_mode,
            default_role,
            default_skills,
        )
    )
