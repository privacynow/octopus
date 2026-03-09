"""Tests for storage.py — session CRUD, path resolution, uploads."""

import json
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.storage import (
    build_upload_path,
    default_session,
    ensure_data_dirs,
    is_image_path,
    load_session,
    resolve_allowed_path,
    sanitize_filename,
    list_sessions,
    save_session,
    session_file,
)
from tests.support.assertions import Checks

checks = Checks()
check = checks.check


# -- sanitize_filename --
print("\n=== sanitize_filename ===")
check("clean", sanitize_filename("hello.txt"), "hello.txt")
check("spaces", sanitize_filename("my file (1).doc"), "my_file_1_.doc")
check("empty", sanitize_filename("..."), "attachment")

# -- is_image_path --
print("\n=== is_image_path ===")
check("png", is_image_path(Path("test.png")), True)
check("jpg", is_image_path(Path("test.JPG")), True)
check("txt", is_image_path(Path("test.txt")), False)

# -- session management --
print("\n=== session management ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    ensure_data_dirs(data_dir)
    check("sessions dir exists", (data_dir / "sessions").is_dir(), True)
    check("uploads dir exists", (data_dir / "uploads").is_dir(), True)

    # default_session
    s = default_session("claude", {"session_id": "abc", "started": False}, "on")
    check("provider set", s["provider"], "claude")
    check("provider_state set", s["provider_state"]["session_id"], "abc")
    check("approval mode", s["approval_mode"], "on")
    check("has created_at", "created_at" in s, True)
    check("has updated_at", "updated_at" in s, True)

    # save + load
    save_session(data_dir, 12345, s)
    loaded = load_session(data_dir, 12345, "claude", lambda: {"session_id": "abc", "started": False}, "on")
    check("loaded provider", loaded["provider"], "claude")
    check("loaded state", loaded["provider_state"]["session_id"], "abc")

    # load with new provider_state keys (migration-safe)
    loaded2 = load_session(data_dir, 12345, "claude", lambda: {"session_id": "abc", "started": False, "new_key": "default"}, "on")
    check("new key filled", loaded2["provider_state"]["new_key"], "default")

    session_file(data_dir, 54321).write_text("{not json")
    corrupt_loaded = load_session(
        data_dir,
        54321,
        "codex",
        lambda: {"thread_id": None},
        "off",
    )
    check("corrupt session falls back to provider", corrupt_loaded["provider"], "codex")
    check("corrupt session falls back to fresh state", corrupt_loaded["provider_state"]["thread_id"], None)

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
    check("explicit approval mode restored", loaded3["approval_mode"], "off")
    check("explicit approval source restored", loaded3["approval_mode_explicit"], True)

    # fresh session for new chat
    fresh = load_session(data_dir, 99999, "codex", lambda: {"thread_id": None}, "off")
    check("fresh session provider", fresh["provider"], "codex")
    check("fresh session state", fresh["provider_state"]["thread_id"], None)

# -- resolve_allowed_path --
print("\n=== resolve_allowed_path ===")
with tempfile.TemporaryDirectory() as tmp:
    test_file = Path(tmp) / "test.txt"
    test_file.write_text("x")
    roots = [Path(tmp)]

    resolved = resolve_allowed_path(str(test_file), roots)
    check("absolute allowed", resolved, test_file.resolve())

    resolved2 = resolve_allowed_path("test.txt", roots)
    check("relative allowed", resolved2, test_file.resolve())

    resolved3 = resolve_allowed_path("/etc/passwd", roots)
    check("outside roots", resolved3, None)

    resolved4 = resolve_allowed_path("/nonexistent/file", roots)
    check("nonexistent", resolved4, None)

# -- build_upload_path --
print("\n=== build_upload_path ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    ensure_data_dirs(data_dir)
    path = build_upload_path(data_dir, 42, "photo.jpg")
    check("upload in chat dir", str(path).startswith(str(data_dir / "uploads" / "42")), True)
    check("upload has safe name", path.name.endswith("_photo.jpg"), True)

# -- list_sessions --
print("\n=== list_sessions ===")
with tempfile.TemporaryDirectory() as tmp:
    data_dir = Path(tmp)
    ensure_data_dirs(data_dir)

    # Empty directory
    check("empty sessions", list_sessions(data_dir), [])

    # Create two sessions
    s1 = default_session("claude", {"session_id": "a", "started": False}, "on")
    s1["active_skills"] = ["code-review"]
    save_session(data_dir, 111, s1)

    s2 = default_session("codex", {"thread_id": None}, "off")
    s2["pending_request"] = {"prompt": "test", "created_at": 0}
    save_session(data_dir, 222, s2)

    result = list_sessions(data_dir)
    check("two sessions returned", len(result), 2)

    # Most recently updated should be first
    check("sorted by updated_at", result[0]["chat_id"], 222)
    check("second session", result[1]["chat_id"], 111)

    # Check fields
    s222 = result[0]
    check("provider field", s222["provider"], "codex")
    check("has_pending", s222["has_pending"], True)
    check("has_setup", s222["has_setup"], False)
    check("approval_mode field", s222["approval_mode"], "off")

    s111 = result[1]
    check("active_skills", s111["active_skills"], ["code-review"])
    check("provider field 2", s111["provider"], "claude")
    check("has_pending 2", s111["has_pending"], False)

    # Non-existent data_dir
    check("missing dir", list_sessions(Path("/tmp/nonexistent-xyz")), [])

    # Corrupt file is skipped
    (data_dir / "sessions" / "bad.json").write_text("{corrupt")
    result2 = list_sessions(data_dir)
    check("corrupt skipped", len(result2), 2)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
