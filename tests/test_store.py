"""Tests for the managed immutable skill store.

Covers:
- Store discovery (list_store_skills, skill_info)
- Search matching
- Content hashing (hash_directory)
- Install/uninstall lifecycle via refs and objects
- Ref read/write round-trip and provenance
- Update detection (check_updates, update_skill, update_all)
- Custom override detection (has_custom_override)
- Diff between managed/custom/store
- GC of unreferenced objects
- Startup recovery idempotence
- Schema version guard
- Admin gate (is_admin helper)
- Prompt size warning (check_prompt_size)
"""

import atexit
import json
import os
import shutil
import tempfile
import time

from pathlib import Path
from unittest.mock import patch
from tests.support.config_support import make_config


# ---------------------------------------------------------------------------
# Setup: temp dirs for store and managed skills
# ---------------------------------------------------------------------------

tmp_root = tempfile.mkdtemp()
tmp_store = Path(tmp_root) / "store"
tmp_custom = Path(tmp_root) / "custom"
tmp_managed = Path(tmp_root) / "managed"
tmp_objects = tmp_managed / "objects"
tmp_refs = tmp_managed / "refs"
tmp_tmp = tmp_managed / "tmp"
tmp_version = tmp_managed / "version.json"
tmp_lock = tmp_managed / ".lock"
tmp_data = Path(tmp_root) / "data"

tmp_store.mkdir()
tmp_custom.mkdir()
tmp_managed.mkdir()
tmp_objects.mkdir()
tmp_refs.mkdir()
tmp_tmp.mkdir()
(tmp_data / "sessions").mkdir(parents=True)

# Monkey-patch store module dirs
import app.store as store_mod
_originals = {
    "STORE_DIR": store_mod.STORE_DIR,
    "CUSTOM_DIR": store_mod.CUSTOM_DIR,
    "MANAGED_DIR": store_mod.MANAGED_DIR,
    "OBJECTS_DIR": store_mod.OBJECTS_DIR,
    "REFS_DIR": store_mod.REFS_DIR,
    "TMP_DIR": store_mod.TMP_DIR,
    "VERSION_FILE": store_mod.VERSION_FILE,
    "LOCK_FILE": store_mod.LOCK_FILE,
}
store_mod.STORE_DIR = tmp_store
store_mod.CUSTOM_DIR = tmp_custom
store_mod.MANAGED_DIR = tmp_managed
store_mod.OBJECTS_DIR = tmp_objects
store_mod.REFS_DIR = tmp_refs
store_mod.TMP_DIR = tmp_tmp
store_mod.VERSION_FILE = tmp_version
store_mod.LOCK_FILE = tmp_lock


def _restore_originals():
    for attr, val in _originals.items():
        setattr(store_mod, attr, val)
    shutil.rmtree(tmp_root, ignore_errors=True)


atexit.register(_restore_originals)


def _create_store_skill(name, display_name=None, description="", body="Instructions here.", extra_files=None):
    """Create a skill in the temp store dir."""
    d = tmp_store / name
    d.mkdir(parents=True, exist_ok=True)
    dn = display_name or name.replace("-", " ").title()
    (d / "skill.md").write_text(
        f"---\nname: {name}\ndisplay_name: {dn}\ndescription: {description}\n---\n\n{body}\n"
    )
    if extra_files:
        for fname, content in extra_files.items():
            (d / fname).write_text(content)
    return d


def _create_custom_skill(name, body="Custom instructions."):
    """Create a user-created skill in the temp custom dir."""
    d = tmp_custom / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "skill.md").write_text(
        f"---\nname: {name}\ndisplay_name: {name.title()}\ndescription: Custom\n---\n\n{body}\n"
    )
    return d


def _cleanup_custom():
    if tmp_custom.is_dir():
        shutil.rmtree(tmp_custom)
    tmp_custom.mkdir()


def _cleanup_store():
    if tmp_store.is_dir():
        shutil.rmtree(tmp_store)
    tmp_store.mkdir()


def _cleanup_managed():
    """Remove all refs and objects."""
    if tmp_refs.is_dir():
        shutil.rmtree(tmp_refs)
    tmp_refs.mkdir()
    if tmp_objects.is_dir():
        shutil.rmtree(tmp_objects)
    tmp_objects.mkdir()
    if tmp_tmp.is_dir():
        shutil.rmtree(tmp_tmp)
    tmp_tmp.mkdir()


# ===========================================================================
# Store Discovery
# ===========================================================================

def test_store_discovery():
    _cleanup_store()
    assert store_mod.list_store_skills() == {}

    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("data-analysis", description="Data analysis tools")
    catalog = store_mod.list_store_skills()
    assert len(catalog) == 2
    assert catalog["api-testing"].name == "api-testing"
    assert catalog["api-testing"].description == "API test helpers"
    assert catalog["data-analysis"].name == "data-analysis"

    # Malformed skill.md is skipped
    bad = tmp_store / "bad-skill"
    bad.mkdir()
    (bad / "skill.md").write_text("---\nname: [invalid yaml\n  broken:\n---\n")
    catalog2 = store_mod.list_store_skills()
    assert len(catalog2) == 2

    # Dir without skill.md is skipped
    (tmp_store / "no-skillmd").mkdir()
    catalog3 = store_mod.list_store_skills()
    assert len(catalog3) == 2

    # Skill with requires.yaml detected
    _create_store_skill("cred-skill", extra_files={"requires.yaml": "credentials:\n  - key: TOKEN\n"})
    catalog4 = store_mod.list_store_skills()
    assert catalog4["cred-skill"].has_requirements is True
    assert catalog4["api-testing"].has_requirements is False

    # Skill with provider YAML detected
    _create_store_skill("provider-skill", extra_files={
        "claude.yaml": "mcp_servers: {}\n",
        "codex.yaml": "scripts: []\n",
    })
    catalog5 = store_mod.list_store_skills()
    assert catalog5["provider-skill"].has_claude_config is True
    assert catalog5["provider-skill"].has_codex_config is True
    assert catalog5["api-testing"].has_claude_config is False


# ===========================================================================
# Search
# ===========================================================================

def test_search():
    # Relies on store state from test_store_discovery — rebuild to be safe
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("data-analysis", description="Data analysis tools")
    _create_store_skill("cred-skill", extra_files={"requires.yaml": "credentials:\n  - key: TOKEN\n"})
    _create_store_skill("provider-skill", extra_files={
        "claude.yaml": "mcp_servers: {}\n",
        "codex.yaml": "scripts: []\n",
    })

    results = store_mod.search("api")
    assert len(results) == 1
    assert results[0].name == "api-testing"

    results2 = store_mod.search("tools")
    assert len(results2) == 1
    assert results2[0].name == "data-analysis"

    results3 = store_mod.search("nonexistent")
    assert len(results3) == 0

    results4 = store_mod.search("skill")
    assert len(results4) >= 2

    # Case insensitive
    results5 = store_mod.search("API")
    assert len(results5) == 1


# ===========================================================================
# Skill Info
# ===========================================================================

def test_skill_info():
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")

    info = store_mod.skill_info("api-testing")
    assert info is not None
    si, body = info
    assert si.name == "api-testing"
    assert "Instructions here" in body

    assert store_mod.skill_info("nonexistent") is None


# ===========================================================================
# Content Hashing
# ===========================================================================

def test_content_hashing():
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("data-analysis", description="Data analysis tools")

    hash1 = store_mod.hash_directory(tmp_store / "api-testing")
    hash2 = store_mod.hash_directory(tmp_store / "api-testing")
    assert hash1 == hash2

    hash3 = store_mod.hash_directory(tmp_store / "data-analysis")
    assert hash1 != hash3


# ===========================================================================
# Install
# ===========================================================================

def test_install():
    _cleanup_custom()
    _cleanup_managed()
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("data-analysis", description="Data analysis tools")

    # Install a skill
    ok, msg = store_mod.install("api-testing")
    assert ok is True
    assert "installed" in msg

    # Verify ref was created
    ref = store_mod.read_ref("api-testing")
    assert ref is not None
    assert ref.source == "store"
    assert ref.source_uri == "skills/store/api-testing"

    # Verify object was created
    obj_dir = store_mod.object_dir(ref.digest)
    assert obj_dir.is_dir()
    assert (obj_dir / "skill.md").is_file()

    # SHA-256 verification: object hash matches store source
    store_hash = store_mod.hash_directory(tmp_store / "api-testing")
    assert ref.digest == store_hash

    # Install nonexistent
    ok2, msg2 = store_mod.install("nonexistent")
    assert ok2 is False
    assert "not found" in msg2

    # Conflict: user-created custom skill with same name (no existing ref)
    _create_custom_skill("conflict-skill")
    _create_store_skill("conflict-skill", description="Store version")
    ok3, msg3 = store_mod.install("conflict-skill")
    assert ok3 is False
    assert "custom skill" in msg3

    # Re-install (update) an already installed skill
    ok4, msg4 = store_mod.install("api-testing")
    assert ok4 is True
    assert "reinstalled" in msg4


# ===========================================================================
# is_store_installed
# ===========================================================================

def test_is_store_installed():
    _cleanup_custom()
    _cleanup_managed()
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("conflict-skill", description="Store version")
    _create_custom_skill("conflict-skill")
    store_mod.install("api-testing")

    assert store_mod.is_store_installed("api-testing") is True
    assert store_mod.is_store_installed("conflict-skill") is False
    assert store_mod.is_store_installed("nonexistent") is False


# ===========================================================================
# Uninstall
# ===========================================================================

def test_uninstall():
    _cleanup_custom()
    _cleanup_managed()
    _cleanup_store()
    _create_store_skill("api-testing", description="API test helpers")
    _create_store_skill("data-analysis", description="Data analysis tools")

    # Install first
    store_mod.install("api-testing")
    store_mod.install("data-analysis")

    # Uninstall
    ok, msg = store_mod.uninstall("api-testing", default_skills=())
    assert ok is True
    assert "uninstalled" in msg

    # Ref should be gone
    ref = store_mod.read_ref("api-testing")
    assert ref is None

    # Uninstall nonexistent
    ok2, msg2 = store_mod.uninstall("nonexistent", default_skills=())
    assert ok2 is False

    # Uninstall non-managed custom skill
    _create_custom_skill("my-custom")
    ok3, msg3 = store_mod.uninstall("my-custom", default_skills=())
    assert ok3 is False
    assert "not installed" in msg3

    # Uninstall refused while in BOT_SKILLS
    ok4, msg4 = store_mod.uninstall("data-analysis", default_skills=("data-analysis",))
    assert ok4 is False
    assert "BOT_SKILLS" in msg4
    # Ref should still exist
    assert store_mod.read_ref("data-analysis") is not None

    # Uninstall with custom override note
    _create_custom_skill("data-analysis")
    ok5, msg5 = store_mod.uninstall("data-analysis", default_skills=())
    assert ok5 is True
    assert "custom override" in msg5


# ===========================================================================
# Ref Round-Trip
# ===========================================================================

def test_ref_round_trip():
    _cleanup_managed()

    from app.store import SkillRef

    test_ref = SkillRef(
        schema_version=1,
        digest="abc123deadbeef",
        source="store",
        source_uri="skills/store/test-skill",
        installed_at="2026-01-01T00:00:00+00:00",
        version="1.0",
        publisher="test-pub",
        signature=None,
        pinned=True,
    )
    store_mod._write_ref("test-skill", test_ref)
    read_back = store_mod.read_ref("test-skill")
    assert read_back.source == "store"
    assert read_back.digest == "abc123deadbeef"
    assert read_back.source_uri == "skills/store/test-skill"
    assert read_back.installed_at == "2026-01-01T00:00:00+00:00"
    assert read_back.version == "1.0"
    assert read_back.publisher == "test-pub"
    assert read_back.signature is None
    assert read_back.pinned is True

    # Corrupt ref returns None
    (tmp_refs / "corrupt.json").write_text("not json")
    assert store_mod.read_ref("corrupt") is None

    # Missing ref returns None
    assert store_mod.read_ref("does-not-exist") is None


# ===========================================================================
# Update Checking
# ===========================================================================

def test_update_checking():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    # Create and install a skill
    _create_store_skill("updatable", description="v1", body="Version 1 instructions.")
    store_mod.install("updatable")

    # No changes — up to date
    updates = store_mod.check_updates()
    assert len(updates) == 1
    assert updates[0] == ("updatable", "up_to_date")

    # Modify store content — update available
    _create_store_skill("updatable", description="v2", body="Version 2 instructions.")
    updates2 = store_mod.check_updates()
    assert len(updates2) == 1
    assert updates2[0] == ("updatable", "update_available")


# ===========================================================================
# Update Skill
# ===========================================================================

def test_update_skill():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    _create_store_skill("update-me", description="v1", body="V1.")
    store_mod.install("update-me")

    # Update when already up to date
    ok, msg = store_mod.update_skill("update-me")
    assert ok is True
    assert "up to date" in msg

    # Make store version newer
    _create_store_skill("update-me", description="v2", body="V2.")
    ok2, msg2 = store_mod.update_skill("update-me")
    assert ok2 is True
    assert "updated" in msg2

    # Verify ref now points to new content
    ref = store_mod.read_ref("update-me")
    store_hash = store_mod.hash_directory(tmp_store / "update-me")
    assert ref.digest == store_hash

    # Verify object has new content
    obj_dir = store_mod.object_dir(ref.digest)
    installed_body = (obj_dir / "skill.md").read_text()
    assert "V2" in installed_body

    # Update nonexistent
    ok3, msg3 = store_mod.update_skill("nonexistent")
    assert ok3 is False

    # Update non-managed skill
    _create_custom_skill("my-skill")
    ok4, msg4 = store_mod.update_skill("my-skill")
    assert ok4 is False
    assert "no longer available" in msg4


# ===========================================================================
# Update All
# ===========================================================================

def test_update_all():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    _create_store_skill("skill-a", body="V1.")
    _create_store_skill("skill-b", body="V1.")
    _create_store_skill("skill-c", body="V1.")
    store_mod.install("skill-a")
    store_mod.install("skill-b")
    store_mod.install("skill-c")

    # Make a and c have updates
    _create_store_skill("skill-a", body="V2.")
    _create_store_skill("skill-c", body="V2.")

    results = store_mod.update_all()
    assert len(results) == 2
    names_updated = [r[0] for r in results]
    assert "skill-a" in names_updated
    assert "skill-c" in names_updated
    assert all(r[1] for r in results)

    # No more updates
    results2 = store_mod.update_all()
    assert len(results2) == 0


# ===========================================================================
# Custom Override Detection
# ===========================================================================

def test_custom_override_detection():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    # Install a managed skill
    _create_store_skill("shadowed", body="Managed version.")
    store_mod.install("shadowed")

    # No override yet
    assert store_mod.has_custom_override("shadowed") is False

    # Create custom skill with same name
    _create_custom_skill("shadowed", body="Custom version.")
    assert store_mod.has_custom_override("shadowed") is True

    # Custom only (no ref) — not an override
    _create_custom_skill("custom-only", body="Just custom.")
    assert store_mod.has_custom_override("custom-only") is False


# ===========================================================================
# Diff
# ===========================================================================

def test_diff():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    # Custom override vs managed
    _create_store_skill("diff-test", body="Managed content.")
    store_mod.install("diff-test")
    _create_custom_skill("diff-test", body="Custom content.")

    ok, diff_text = store_mod.diff_skill("diff-test")
    assert ok is True
    assert "managed" in diff_text
    assert "custom" in diff_text

    # Managed vs store (update preview)
    _cleanup_custom()
    _create_store_skill("diff-test", body="Updated store content.")
    ok2, diff_text2 = store_mod.diff_skill("diff-test")
    assert ok2 is True
    assert "installed" in diff_text2
    assert "store" in diff_text2

    # No differences
    _create_store_skill("diff-test", body="Managed content.")  # match what was installed
    # Need to reinstall to match
    store_mod.install("diff-test")
    ok3, diff_text3 = store_mod.diff_skill("diff-test")
    assert ok3 is True
    assert "no differences" in diff_text3.lower()

    # Nonexistent
    ok4, msg4 = store_mod.diff_skill("nonexistent")
    assert ok4 is False


# ===========================================================================
# Garbage Collection
# ===========================================================================

def test_garbage_collection():
    _cleanup_custom()
    _cleanup_store()
    _cleanup_managed()

    # Create and install a skill, then uninstall it
    _create_store_skill("gc-test", body="GC me.")
    store_mod.install("gc-test")
    ref = store_mod.read_ref("gc-test")
    digest = ref.digest

    # Uninstall — object becomes unreferenced
    store_mod.uninstall("gc-test", default_skills=())

    # GC with default grace — should NOT remove (too young)
    removed = store_mod.gc(grace_seconds=3600)
    assert len(removed) == 0
    assert store_mod._object_exists(digest)

    # GC with zero grace — should remove
    removed2 = store_mod.gc(grace_seconds=0)
    assert len(removed2) == 1
    assert removed2[0] == digest
    assert not store_mod._object_exists(digest)

    # GC doesn't touch referenced objects
    _create_store_skill("gc-keep", body="Keep me.")
    store_mod.install("gc-keep")
    ref_keep = store_mod.read_ref("gc-keep")
    removed3 = store_mod.gc(grace_seconds=0)
    assert len(removed3) == 0
    assert store_mod._object_exists(ref_keep.digest)


# ===========================================================================
# Startup Recovery
# ===========================================================================

def test_startup_recovery():
    # Should be idempotent — just ensure dirs and run GC
    store_mod.startup_recovery()
    assert tmp_version.is_file()
    version_data = json.loads(tmp_version.read_text())
    assert version_data["schema"] == 1

    # Call again — idempotent
    store_mod.startup_recovery()
    assert tmp_version.is_file()


# ===========================================================================
# Schema Guard
# ===========================================================================

def test_schema_guard():
    # Write a future schema version
    tmp_version.write_text(json.dumps({"schema": 99}) + "\n")
    try:
        store_mod.check_schema()
        assert False, "should have raised"
    except RuntimeError as e:
        assert "99" in str(e)
        assert "Upgrade" in str(e)

    # Restore valid version
    tmp_version.write_text(json.dumps({"schema": 1}) + "\n")
    store_mod.check_schema()  # should not raise


# ===========================================================================
# Prompt Size Warning
# ===========================================================================

def test_prompt_size_warning():
    from app.skills import check_prompt_size, PROMPT_SIZE_WARNING_THRESHOLD

    # Short prompt — no warning
    warning = check_prompt_size("short role", [])
    assert warning is None

    def fake_build_system_prompt(role, skills):
        return "x" * 9000

    with patch("app.skills.build_system_prompt", fake_build_system_prompt):
        warning2 = check_prompt_size("role", ["some-skill"])
        assert warning2 is not None
        assert "8,000" in warning2
        assert "9,000" in warning2

    def fake_under_threshold(role, skills):
        return "x" * 7999

    with patch("app.skills.build_system_prompt", fake_under_threshold):
        warning3 = check_prompt_size("role", ["some-skill"])
        assert warning3 is None


# ===========================================================================
# Admin Gate (is_admin helper)
# ===========================================================================

def test_admin_gate():
    from app.config import parse_allowed_users

    admin_ids, admin_names = parse_allowed_users("111,@adminuser")
    assert admin_ids == {111}
    assert admin_names == {"adminuser"}

    cfg_explicit = make_config(
        allowed_user_ids=frozenset({111, 222}),
        admin_user_ids=frozenset({111}),
        admin_usernames=frozenset({"adminuser"}),
    )
    assert cfg_explicit.admin_user_ids == frozenset({111})

    cfg_fallback = make_config(
        allowed_user_ids=frozenset({111, 222}),
        admin_user_ids=frozenset({111, 222}),
    )
    assert cfg_fallback.admin_user_ids == frozenset({111, 222})


# ===========================================================================
# Edge Cases
# ===========================================================================

def test_edge_cases():
    # Empty store dir
    _cleanup_store()
    assert store_mod.list_store_skills() == {}
    assert store_mod.search("anything") == []

    # Store dir doesn't exist
    store_mod.STORE_DIR = Path("/nonexistent/store")
    assert store_mod.list_store_skills() == {}
    store_mod.STORE_DIR = tmp_store

    # Install from empty store
    ok, msg = store_mod.install("anything")
    assert ok is False


# ===========================================================================
# Object Idempotence
# ===========================================================================

def test_object_idempotence():
    _cleanup_store()
    _cleanup_managed()

    _create_store_skill("idem-test", body="Same content.")

    # Create object twice — should be idempotent
    digest1 = store_mod._create_object(tmp_store / "idem-test")
    digest2 = store_mod._create_object(tmp_store / "idem-test")
    assert digest1 == digest2

    # Only one object dir should exist
    obj_count = len(list(tmp_objects.iterdir()))
    assert obj_count == 1


# ===========================================================================
# Pinned Ref Skipped by update_all
# ===========================================================================

def test_pinned_ref():
    from app.store import SkillRef

    _cleanup_store()
    _cleanup_managed()

    _create_store_skill("pinned-skill", body="V1.")
    store_mod.install("pinned-skill")

    # Pin the ref
    ref = store_mod.read_ref("pinned-skill")
    pinned_ref = SkillRef(
        schema_version=ref.schema_version,
        digest=ref.digest,
        source=ref.source,
        source_uri=ref.source_uri,
        installed_at=ref.installed_at,
        pinned=True,
    )
    store_mod._write_ref("pinned-skill", pinned_ref)

    # Make update available
    _create_store_skill("pinned-skill", body="V2.")

    results = store_mod.update_all()
    assert len(results) == 1
    assert "pinned" in results[0][2]

    # Ref should still point to old digest
    ref_after = store_mod.read_ref("pinned-skill")
    assert ref_after.digest == ref.digest


# ===========================================================================
# Cleanup is handled by the atexit handler registered above.
# ===========================================================================
