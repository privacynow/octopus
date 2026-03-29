"""In-memory session runtime for SDK composition tests."""

from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass, field

from octopus_sdk.bot_runtime import SessionRuntimePort
from octopus_sdk.config import BotConfigBase
from octopus_sdk.execution_context import ResolvedExecutionContext, resolve_execution_context
from octopus_sdk.sessions import SessionState, default_session, session_from_dict
from octopus_sdk.workflows.skills import RuntimeSkillCatalogPort


CatalogResolver = RuntimeSkillCatalogPort | Callable[[], RuntimeSkillCatalogPort]


@dataclass
class InMemorySessionStore(SessionRuntimePort):
    """A simple in-memory session store for SDK-only runtimes and tests."""

    config: BotConfigBase
    catalog: CatalogResolver | None = None
    _sessions: dict[str, SessionState] = field(default_factory=dict)

    def _catalog(self) -> RuntimeSkillCatalogPort:
        catalog = self.catalog
        if callable(catalog):
            catalog = catalog()
        if catalog is None:
            raise RuntimeError("InMemorySessionStore requires a runtime-skill catalog")
        return catalog

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
        session = self._sessions.get(conversation_key)
        if session is None:
            session = session_from_dict(
                default_session(
                    provider_name,
                    provider_state_factory(conversation_key),
                    approval_mode,
                    default_role,
                    default_skills,
                )
            )
            self._sessions[conversation_key] = copy.deepcopy(session)
        return copy.deepcopy(session)

    def save(
        self,
        conversation_key: str,
        session: SessionState,
    ) -> None:
        self._sessions[conversation_key] = copy.deepcopy(session)

    def list_incomplete_sessions(self) -> list[str]:
        raise NotImplementedError(
            "InMemorySessionStore is test-only and does not provide durable "
            "session recovery enumeration."
        )

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
        del (
            conversation_key,
            provider_name,
            provider_state_factory,
            approval_mode,
            default_role,
            default_skills,
        )
        raise NotImplementedError(
            "InMemorySessionStore is test-only and does not provide durable "
            "crash recovery."
        )

    def resolve_context(
        self,
        session: SessionState,
        *,
        config: BotConfigBase,
        provider_name: str,
        trust_tier: str = "trusted",
    ) -> ResolvedExecutionContext:
        return resolve_execution_context(
            session,
            config,
            provider_name,
            trust_tier=trust_tier,
            catalog=self._catalog(),
        )
