"""Telegram session and key helpers."""

from __future__ import annotations

from app.channels.telegram.state import TelegramRuntime
from octopus_sdk.identity import (
    parse_actor_key,
    parse_conversation_key,
    telegram_actor_key,
    telegram_event_id,
    telegram_numeric_id,
)
from app.runtime.session_runtime import load_runtime_session, save_runtime_session
from octopus_sdk.sessions import SessionState
from app.skill_activation_service import get_skill_activation_service


def conversation_key(chat_id: int | str) -> str:
    return parse_conversation_key(chat_id)


def actor_key(user_id: int | str) -> str:
    if isinstance(user_id, str):
        return parse_actor_key(user_id)
    return telegram_actor_key(user_id)


def event_key(update_id: int | str) -> str:
    if isinstance(update_id, str):
        return update_id if ":" in update_id or not update_id.isdigit() else telegram_event_id(update_id)
    return telegram_event_id(update_id)


def telegram_chat_id(chat_id: int | str) -> int:
    if isinstance(chat_id, int):
        return chat_id
    numeric = telegram_numeric_id(chat_id)
    if numeric is None:
        raise RuntimeError(f"Telegram API requires a Telegram conversation key, got {chat_id!r}")
    return numeric


def load(runtime: TelegramRuntime, chat_id: int | str) -> SessionState:
    cfg = runtime.config
    session = load_runtime_session(
        cfg.data_dir,
        conversation_key(chat_id),
        provider_name=runtime.provider.name,
        provider_state_factory=runtime.provider.new_provider_state,
        approval_mode=cfg.approval_mode,
        default_role=cfg.role,
        default_skills=cfg.default_skills,
    )
    if get_skill_activation_service().normalize(session):
        save(runtime, chat_id, session)
    return session


def save(runtime: TelegramRuntime, chat_id: int | str, session: SessionState) -> None:
    save_runtime_session(runtime.config.data_dir, conversation_key(chat_id), session)
