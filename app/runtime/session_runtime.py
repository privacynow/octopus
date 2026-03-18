"""Shared runtime helpers for session loading, saving, and context resolution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import BotConfig
from app.execution_context import ResolvedExecutionContext, resolve_execution_context
from app.session_state import SessionState, session_from_dict, session_to_dict
from app.storage import default_session, load_session, save_session


def resolve_session_context(
    session: SessionState,
    *,
    config: BotConfig,
    provider_name: str,
    trust_tier: str = "trusted",
) -> ResolvedExecutionContext:
    return resolve_execution_context(session, config, provider_name, trust_tier=trust_tier)


def load_runtime_session(
    data_dir: Path,
    conversation_key: str,
    *,
    provider_name: str,
    provider_state_factory: Callable[[], dict],
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
    provider_state_factory: Callable[[], dict],
    approval_mode: str,
    default_role: str = "",
    default_skills: tuple[str, ...] = (),
) -> SessionState:
    return session_from_dict(
        default_session(
            provider_name,
            provider_state_factory(),
            approval_mode,
            default_role,
            default_skills,
        )
    )
