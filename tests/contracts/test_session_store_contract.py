"""Session store contract: backend-neutral behavior. Runs against SQLite and Postgres via storage facade."""

import tempfile
from pathlib import Path

import pytest

from app.session_defaults import default_session
from app.storage import (
    ensure_data_dirs,
    load_session,
    list_sessions,
    save_session,
    delete_session,
    session_exists,
)


def _provider_state_factory():
    return {}


@pytest.fixture(params=["sqlite", "postgres"])
def backend_and_data_dir(request):
    """Provide (backend_name, data_dir) for contract tests. SQLite uses temp dir; Postgres uses truncated DB."""
    from app import runtime_backend
    from tests.support.config_support import make_config

    if request.param == "sqlite":
        runtime_backend.reset_for_test()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            ensure_data_dirs(data_dir)
            yield "sqlite", data_dir
        return

    # Postgres: need truncated DB URL, then init backend
    postgres_url = request.getfixturevalue("postgres_truncated")
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir, database_url=postgres_url)
        cfg = make_config(data_dir=data_dir, database_url=postgres_url)
        runtime_backend.init(cfg)
        try:
            yield "postgres", data_dir
        finally:
            runtime_backend.reset_for_test()


# --- session_exists ---

def test_session_exists_false_when_empty(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert session_exists(data_dir, 12345) is False


def test_session_exists_true_after_save(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    session = default_session("claude", _provider_state_factory(), "on")
    save_session(data_dir, 999, session)
    assert session_exists(data_dir, 999) is True
    assert session_exists(data_dir, 998) is False


# --- default load ---

def test_load_session_returns_default_when_missing(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    loaded = load_session(
        data_dir, 888, "codex", _provider_state_factory, "off", "", ()
    )
    assert loaded["provider"] == "codex"
    assert loaded["approval_mode"] == "off"
    assert "created_at" in loaded
    assert "updated_at" in loaded


# --- save / load roundtrip ---

def test_save_load_roundtrip(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    session = default_session(
        "claude", _provider_state_factory(), "on", "Engineer", ("debugging",)
    )
    session["active_skills"] = ["debugging", "testing"]
    session["project_id"] = "myproj"
    save_session(data_dir, 777, session)
    loaded = load_session(
        data_dir, 777, "claude", _provider_state_factory, "on", "", ()
    )
    assert loaded["active_skills"] == ["debugging", "testing"]
    assert loaded["project_id"] == "myproj"
    assert loaded["provider"] == "claude"


def test_load_merge_provider_state_factory_defaults(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    session = default_session("claude", _provider_state_factory, "on")
    session["provider_state"] = {"session_id": "s1"}
    save_session(data_dir, 666, session)
    loaded = load_session(
        data_dir, 666, "claude",
        lambda: {"session_id": "default", "new_key": "default_val"},
        "on",
    )
    assert loaded["provider_state"]["session_id"] == "s1"
    assert loaded["provider_state"]["new_key"] == "default_val"


# --- delete ---

def test_delete_session_removes_session(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    session = default_session("claude", _provider_state_factory(), "off")
    save_session(data_dir, 555, session)
    assert session_exists(data_dir, 555) is True
    delete_session(data_dir, 555)
    assert session_exists(data_dir, 555) is False
    loaded = load_session(data_dir, 555, "claude", _provider_state_factory, "off")
    assert loaded["provider"] == "claude"
    assert loaded.get("project_id") is None


# --- list behavior ---

def test_list_sessions_empty(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    assert list_sessions(data_dir) == []


def test_list_sessions_after_saves(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    save_session(
        data_dir, 111,
        default_session("claude", _provider_state_factory(), "on"),
    )
    save_session(
        data_dir, 222,
        default_session("codex", _provider_state_factory(), "off"),
    )
    listed = list_sessions(data_dir)
    assert len(listed) == 2
    chat_ids = {s["chat_id"] for s in listed}
    assert chat_ids == {111, 222}
    providers = {s["provider"] for s in listed}
    assert providers == {"claude", "codex"}


def test_list_sessions_ordering_by_updated_at(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    for chat_id in (1, 2, 3):
        save_session(
            data_dir, chat_id,
            default_session("claude", _provider_state_factory(), "off"),
        )
    listed = list_sessions(data_dir)
    assert len(listed) == 3
    assert [s["chat_id"] for s in listed] == [3, 2, 1]


# --- lazy creation (SQLite: DB created on first use; Postgres: N/A) ---

def test_session_db_created_on_first_use_sqlite(backend_and_data_dir):
    backend, data_dir = backend_and_data_dir
    if backend != "sqlite":
        pytest.skip("lazy file creation is SQLite-specific")
    assert not (data_dir / "sessions.db").exists()
    load_session(data_dir, 1, "claude", _provider_state_factory, "off")
    assert (data_dir / "sessions.db").exists()
