"""Tests for storage.py — session CRUD (SQLite-backed), path resolution, uploads."""

import json
import tempfile
from pathlib import Path

from app.storage import (
    _reset_db,
    build_upload_path,
    default_session,
    ensure_data_dirs,
    is_image_path,
    load_session,
    resolve_allowed_path,
    sanitize_filename,
    list_sessions,
    save_session,
    session_exists,
)


# -- sanitize_filename --

def test_sanitize_filename_clean():
    assert sanitize_filename("hello.txt") == "hello.txt"


def test_sanitize_filename_spaces():
    assert sanitize_filename("my file (1).doc") == "my_file_1_.doc"


def test_sanitize_filename_empty():
    assert sanitize_filename("...") == "attachment"


# -- is_image_path --

def test_is_image_path_png():
    assert is_image_path(Path("test.png")) is True


def test_is_image_path_jpg():
    assert is_image_path(Path("test.JPG")) is True


def test_is_image_path_txt():
    assert is_image_path(Path("test.txt")) is False


# -- session management --

def test_session_management():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        assert (data_dir / "uploads").is_dir()
        # sessions.db is created on first session use (no longer by ensure_data_dirs)

        # default_session
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        assert s["provider"] == "claude"
        assert s["provider_state"]["session_id"] == "abc"
        assert s["approval_mode"] == "on"
        assert "created_at" in s
        assert "updated_at" in s

        # save + load (first use creates sessions.db)
        save_session(data_dir, 12345, s)
        assert (data_dir / "sessions.db").exists()
        assert session_exists(data_dir, 12345)
        assert not session_exists(data_dir, 99998)

        loaded = load_session(data_dir, 12345, "claude", lambda: {"session_id": "abc", "started": False}, "on")
        assert loaded["provider"] == "claude"
        assert loaded["provider_state"]["session_id"] == "abc"

        # load with new provider_state keys (migration-safe)
        loaded2 = load_session(data_dir, 12345, "claude", lambda: {"session_id": "abc", "started": False, "new_key": "default"}, "on")
        assert loaded2["provider_state"]["new_key"] == "default"

        # explicit approval mode survives reload, including its source flag
        s["approval_mode"] = "off"
        s["approval_mode_explicit"] = True
        save_session(data_dir, 12345, s)
        loaded3 = load_session(
            data_dir,
            12345,
            "claude",
            lambda: {"session_id": "abc", "started": False},
            "on",
        )
        assert loaded3["approval_mode"] == "off"
        assert loaded3["approval_mode_explicit"] is True

        # fresh session for new chat
        fresh = load_session(data_dir, 99999, "codex", lambda: {"thread_id": None}, "off")
        assert fresh["provider"] == "codex"
        assert fresh["provider_state"]["thread_id"] is None

        _reset_db(data_dir)


# -- resolve_allowed_path --

def test_resolve_allowed_path():
    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "test.txt"
        test_file.write_text("x")
        roots = [Path(tmp)]

        resolved = resolve_allowed_path(str(test_file), roots)
        assert resolved == test_file.resolve()

        resolved2 = resolve_allowed_path("test.txt", roots)
        assert resolved2 == test_file.resolve()

        resolved3 = resolve_allowed_path("/etc/passwd", roots)
        assert resolved3 is None

        resolved4 = resolve_allowed_path("/nonexistent/file", roots)
        assert resolved4 is None


# -- build_upload_path --

def test_build_upload_path():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        path = build_upload_path(data_dir, 42, "photo.jpg")
        assert str(path).startswith(str(data_dir / "uploads" / "42"))
        assert path.name.endswith("_photo.jpg")
        _reset_db(data_dir)


# -- list_sessions --

def test_list_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

        # Empty database
        assert list_sessions(data_dir) == []

        # Create two sessions
        s1 = default_session("claude", {"session_id": "a", "started": False}, "on")
        s1["active_skills"] = ["code-review"]
        save_session(data_dir, 111, s1)

        s2 = default_session("codex", {"thread_id": None}, "off")
        s2["pending_approval"] = {"prompt": "test", "created_at": 0}
        save_session(data_dir, 222, s2)

        result = list_sessions(data_dir)
        assert len(result) == 2

        # Most recently updated should be first
        assert result[0]["chat_id"] == 222
        assert result[1]["chat_id"] == 111

        # Check fields
        s222 = result[0]
        assert s222["provider"] == "codex"
        assert s222["has_pending"] is True
        assert s222["has_setup"] is False
        assert s222["approval_mode"] == "off"

        s111 = result[1]
        assert s111["active_skills"] == ["code-review"]
        assert s111["provider"] == "claude"
        assert s111["has_pending"] is False

        _reset_db(data_dir)


# -- JSON file migration --

def test_json_file_migration():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir(parents=True)
        (data_dir / "credentials").mkdir(parents=True)

        # Create legacy JSON session files
        sessions_dir = data_dir / "sessions"
        sessions_dir.mkdir()
        s = default_session("claude", {"session_id": "migrated"}, "on")
        s["active_skills"] = ["github-integration"]
        (sessions_dir / "12345.json").write_text(json.dumps(s))

        s2 = default_session("codex", {"thread_id": "t1"}, "off")
        (sessions_dir / "67890.json").write_text(json.dumps(s2))

        # Also a corrupt file — should be skipped
        (sessions_dir / "bad.json").write_text("{corrupt")

        ensure_data_dirs(data_dir)
        # First use of session store creates DB and runs JSON migration
        list_sessions(data_dir)

        assert not sessions_dir.exists()
        assert (data_dir / "sessions.db").exists()

        # Verify migrated data
        loaded = load_session(data_dir, 12345, "claude", lambda: {"session_id": "new"}, "on")
        assert loaded["provider_state"]["session_id"] == "migrated"
        assert loaded["active_skills"] == ["github-integration"]

        loaded2 = load_session(data_dir, 67890, "codex", lambda: {"thread_id": None}, "off")
        assert loaded2["provider_state"]["thread_id"] == "t1"

        # Corrupt file was skipped — no session for "bad"
        assert not session_exists(data_dir, 0)

        result = list_sessions(data_dir)
        assert len(result) == 2

        _reset_db(data_dir)


# -- Session/upload isolation (from test_high_risk.py) --


def test_session_provider_mismatch():
    """Switching providers must reset provider_state; same provider preserves it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        chat_id = 1001

        claude_state_factory = lambda: {"session_id": "new-id", "started": False}
        codex_state_factory = lambda: {"thread_id": None}

        # Save a Claude session with explicit approval_mode override
        session = default_session("claude", claude_state_factory(), "on")
        session["provider_state"]["started"] = True
        session["provider_state"]["session_id"] = "abc-123"
        session["approval_mode"] = "off"
        session["approval_mode_explicit"] = True
        save_session(data_dir, chat_id, session)

        # Reload as Codex — provider_state must be reset
        loaded_codex = load_session(data_dir, chat_id, "codex", codex_state_factory, "on")
        assert loaded_codex["provider_state"].get("started") is None
        assert loaded_codex["provider_state"].get("session_id") is None
        # Approval mode from saved session should persist
        assert loaded_codex["approval_mode"] == "off"

        # Same provider reload should preserve state
        loaded_same = load_session(data_dir, chat_id, "claude", claude_state_factory, "on")
        assert loaded_same["provider_state"]["started"] is True
        assert loaded_same["provider_state"]["session_id"] == "abc-123"
        assert loaded_same["approval_mode"] == "off"


def test_upload_isolation():
    """Per-chat upload dirs are isolated; cross-chat access is denied."""
    from app.storage import chat_upload_dir, resolve_allowed_path

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        chat_a_dir = chat_upload_dir(data_dir, 111)
        chat_b_dir = chat_upload_dir(data_dir, 222)
        file_a = chat_a_dir / "secret.txt"
        file_a.write_text("chat A secret")
        file_b = chat_b_dir / "secret.txt"
        file_b.write_text("chat B secret")

        roots_a = [Path("/home/test"), chat_a_dir]
        roots_b = [Path("/home/test"), chat_b_dir]

        assert resolve_allowed_path(str(file_a), roots_a) is not None
        assert resolve_allowed_path(str(file_b), roots_a) is None
        assert resolve_allowed_path(str(file_b), roots_b) is not None
        assert resolve_allowed_path(str(file_a), roots_b) is None

        # Neither chat can access the shared uploads root
        shared_uploads = data_dir / "uploads"
        rogue_file = shared_uploads / "rogue.txt"
        rogue_file.write_text("should be inaccessible")
        assert resolve_allowed_path(str(rogue_file), roots_a) is None


def test_upload_isolation_provider_commands():
    """Provider commands must not contain shared uploads path."""
    from app.providers.claude import ClaudeProvider
    from tests.support.config_support import make_config

    p = ClaudeProvider(make_config(provider_name="claude"))
    cmd = p._build_run_cmd({"session_id": "x", "started": False}, "test")
    assert not any("uploads" in a for a in cmd)

    # When caller passes chat-specific dir, only that dir appears
    cmd_with = p._build_run_cmd(
        {"session_id": "x", "started": False}, "test",
        extra_dirs=["/tmp/data/uploads/111"]
    )
    assert "/tmp/data/uploads/111" in cmd_with


# -- Session contract: corruption fallback --

def test_load_session_corrupt_provider_state_falls_back_to_defaults():
    """If stored provider_state is not a mapping (e.g. a list), load_session must
    fall back to defaults instead of raising TypeError."""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        # Save a valid session first
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        save_session(data_dir, 55555, s)
        # Corrupt provider_state to a list in the raw JSON
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT data FROM sessions WHERE chat_id = 55555").fetchone()
        import json as _json
        data = _json.loads(row[0])
        data["provider_state"] = [1, 2, 3]  # not a mapping
        conn.execute("UPDATE sessions SET data = ? WHERE chat_id = 55555", (_json.dumps(data),))
        conn.commit()
        conn.close()
        # Close cached connection so load_session re-reads the corrupted file
        from app.storage import close_db
        close_db(data_dir)
        # Must not raise — should fall back to fresh provider_state
        loaded = load_session(data_dir, 55555, "claude", lambda: {"session_id": "new", "started": False}, "on")
        assert isinstance(loaded["provider_state"], dict)
        assert loaded["provider_state"]["session_id"] == "new"
        # Prove the row was actually found and partially loaded (not a fresh/empty session)
        assert loaded["created_at"] == s["created_at"], "session row was not read — test is blind"
        _reset_db(data_dir)


def test_created_at_preserved_on_resave():
    """created_at must not change on subsequent saves (write-once contract)."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        original_created = s["created_at"]
        save_session(data_dir, 77777, s)
        # Load, mutate, and re-save
        loaded = load_session(data_dir, 77777, "claude", lambda: {"session_id": "abc", "started": False}, "on")
        loaded["role"] = "test-role"
        save_session(data_dir, 77777, loaded)
        # Reload and verify created_at is unchanged
        reloaded = load_session(data_dir, 77777, "claude", lambda: {"session_id": "abc", "started": False}, "on")
        assert reloaded["created_at"] == original_created
        _reset_db(data_dir)


def test_falsy_created_at_normalized_on_save():
    """If created_at is falsy (empty string), save must normalize it to a
    real timestamp so it round-trips as a non-empty value."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        s["created_at"] = ""  # force falsy
        save_session(data_dir, 88888, s)
        loaded = load_session(data_dir, 88888, "claude", lambda: {"session_id": "abc", "started": False}, "on")
        assert loaded["created_at"] != "", "falsy created_at was not normalized on save"
        assert len(loaded["created_at"]) > 10, "created_at should be an ISO timestamp"
        _reset_db(data_dir)


def test_load_session_non_object_json_falls_back_to_defaults():
    """If stored JSON decodes to a non-object (e.g. a list), load_session must
    fall back to defaults instead of raising AttributeError."""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        save_session(data_dir, 66666, s)
        # Overwrite stored data with a valid-JSON non-object
        db_path = data_dir / "sessions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE sessions SET data = '[]' WHERE chat_id = 66666")
        conn.commit()
        conn.close()
        from app.storage import close_db
        close_db(data_dir)
        loaded = load_session(data_dir, 66666, "claude", lambda: {"session_id": "new", "started": False}, "on")
        assert isinstance(loaded["provider_state"], dict)
        assert loaded["provider"] == "claude"
        _reset_db(data_dir)
