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
        assert (data_dir / "sessions.db").exists()
        assert (data_dir / "uploads").is_dir()

        # default_session
        s = default_session("claude", {"session_id": "abc", "started": False}, "on")
        assert s["provider"] == "claude"
        assert s["provider_state"]["session_id"] == "abc"
        assert s["approval_mode"] == "on"
        assert "created_at" in s
        assert "updated_at" in s

        # save + load
        save_session(data_dir, 12345, s)
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
        s2["pending_request"] = {"prompt": "test", "created_at": 0}
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

        # Initialize DB — should migrate JSON files
        ensure_data_dirs(data_dir)

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
