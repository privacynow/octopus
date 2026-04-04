"""Session store contract against the Postgres runtime session store."""

import tempfile
from pathlib import Path

import pytest

from octopus_sdk.identity import telegram_conversation_key
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.sessions import default_session
from app.storage import (
    ensure_data_dirs,
    load_session,
    list_sessions,
    save_session,
    delete_session,
    session_exists,
)


def _provider_state_factory(conversation_key: str):
    del conversation_key
    return ProviderStateRecord()


@pytest.fixture()
def data_dir(postgres_truncated):
    """Provide a clean runtime data dir using the Postgres session store."""
    from app import runtime_backend
    from tests.support.config_support import make_config

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir=data_dir, database_url=postgres_truncated)
        runtime_backend.init(cfg)
        try:
            yield data_dir
        finally:
            runtime_backend.reset_for_test()


# --- session_exists ---

def test_session_exists_false_when_empty(data_dir):
    assert session_exists(data_dir, telegram_conversation_key(12345)) is False


def test_session_exists_true_after_save(data_dir):
    session = default_session("claude", _provider_state_factory("tg:test"), "on")
    save_session(data_dir, telegram_conversation_key(999), session)
    assert session_exists(data_dir, telegram_conversation_key(999)) is True
    assert session_exists(data_dir, telegram_conversation_key(998)) is False


# --- default load ---

def test_load_session_returns_default_when_missing(data_dir):
    loaded = load_session(
        data_dir, telegram_conversation_key(888), "codex", _provider_state_factory, "off", "", ()
    )
    assert loaded["provider"] == "codex"
    assert loaded["approval_mode"] == "off"
    assert "created_at" in loaded
    assert "updated_at" in loaded


# --- save / load roundtrip ---

def test_save_load_roundtrip(data_dir):
    session = default_session(
        "claude", _provider_state_factory("tg:test"), "on", "Engineer", ("debugging",)
    )
    session["active_skills"] = ["debugging", "testing"]
    session["project_id"] = "myproj"
    save_session(data_dir, telegram_conversation_key(777), session)
    loaded = load_session(
        data_dir, telegram_conversation_key(777), "claude", _provider_state_factory, "on", "", ()
    )
    assert loaded["active_skills"] == ["debugging", "testing"]
    assert loaded["project_id"] == "myproj"
    assert loaded["provider"] == "claude"


def test_load_session_preserves_saved_provider_state(data_dir):
    session = default_session("claude", _provider_state_factory, "on")
    session["provider_state"] = {"session_id": "s1"}
    save_session(data_dir, telegram_conversation_key(666), session)
    loaded = load_session(
        data_dir, telegram_conversation_key(666), "claude",
        lambda _ck="": ProviderStateRecord({"session_id": "default", "new_key": "default_val"}),
        "on",
    )
    assert loaded["provider_state"]["session_id"] == "s1"
    assert "new_key" not in loaded["provider_state"]


# --- delete ---

def test_delete_session_removes_session(data_dir):
    session = default_session("claude", _provider_state_factory("tg:test"), "off")
    save_session(data_dir, telegram_conversation_key(555), session)
    assert session_exists(data_dir, telegram_conversation_key(555)) is True
    delete_session(data_dir, telegram_conversation_key(555))
    assert session_exists(data_dir, telegram_conversation_key(555)) is False
    loaded = load_session(
        data_dir,
        telegram_conversation_key(555),
        "claude",
        _provider_state_factory,
        "off",
    )
    assert loaded["provider"] == "claude"
    assert loaded.get("project_id") is None


# --- list behavior ---

def test_list_sessions_empty(data_dir):
    assert list_sessions(data_dir) == []


def test_list_sessions_after_saves(data_dir):
    save_session(
        data_dir, telegram_conversation_key(111),
        default_session("claude", _provider_state_factory("tg:test"), "on"),
    )
    save_session(
        data_dir, telegram_conversation_key(222),
        default_session("codex", _provider_state_factory("tg:test"), "off"),
    )
    listed = list_sessions(data_dir)
    assert len(listed) == 2
    conversation_keys = {s["conversation_key"] for s in listed}
    assert conversation_keys == {
        telegram_conversation_key(111),
        telegram_conversation_key(222),
    }
    providers = {s["provider"] for s in listed}
    assert providers == {"claude", "codex"}


def test_list_sessions_ordering_by_updated_at(data_dir):
    for chat_id in (1, 2, 3):
        save_session(
            data_dir, telegram_conversation_key(chat_id),
            default_session("claude", _provider_state_factory("tg:test"), "off"),
        )
    listed = list_sessions(data_dir)
    assert len(listed) == 3
    assert [s["conversation_key"] for s in listed] == [
        telegram_conversation_key(3),
        telegram_conversation_key(2),
        telegram_conversation_key(1),
    ]
