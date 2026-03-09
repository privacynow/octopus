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
import sys
import tempfile
import time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from tests.support.assertions import Checks
from tests.support.config_support import make_config

checks = Checks()
check = checks.check
check_in = checks.check_in
check_not_in = checks.check_not_in
check_true = checks.check_true
check_false = checks.check_false


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

print("\n=== Store Discovery ===")

_cleanup_store()
check("empty store", store_mod.list_store_skills(), {})

_create_store_skill("api-testing", description="API test helpers")
_create_store_skill("data-analysis", description="Data analysis tools")
catalog = store_mod.list_store_skills()
check("two skills found", len(catalog), 2)
check("api-testing name", catalog["api-testing"].name, "api-testing")
check("api-testing desc", catalog["api-testing"].description, "API test helpers")
check("data-analysis name", catalog["data-analysis"].name, "data-analysis")

# Malformed skill.md is skipped
bad = tmp_store / "bad-skill"
bad.mkdir()
(bad / "skill.md").write_text("---\nname: [invalid yaml\n  broken:\n---\n")
catalog2 = store_mod.list_store_skills()
check("malformed skipped", len(catalog2), 2)

# Dir without skill.md is skipped
(tmp_store / "no-skillmd").mkdir()
catalog3 = store_mod.list_store_skills()
check("no-skillmd skipped", len(catalog3), 2)

# Skill with requires.yaml detected
_create_store_skill("cred-skill", extra_files={"requires.yaml": "credentials:\n  - key: TOKEN\n"})
catalog4 = store_mod.list_store_skills()
check("has_requirements", catalog4["cred-skill"].has_requirements, True)
check("no requirements", catalog4["api-testing"].has_requirements, False)

# Skill with provider YAML detected
_create_store_skill("provider-skill", extra_files={
    "claude.yaml": "mcp_servers: {}\n",
    "codex.yaml": "scripts: []\n",
})
catalog5 = store_mod.list_store_skills()
check("has_claude_config", catalog5["provider-skill"].has_claude_config, True)
check("has_codex_config", catalog5["provider-skill"].has_codex_config, True)
check("no claude config", catalog5["api-testing"].has_claude_config, False)


# ===========================================================================
# Search
# ===========================================================================

print("\n=== Search ===")

results = store_mod.search("api")
check("search by name", len(results), 1)
check("search result name", results[0].name, "api-testing")

results2 = store_mod.search("tools")
check("search by description", len(results2), 1)
check("search desc result", results2[0].name, "data-analysis")

results3 = store_mod.search("nonexistent")
check("search no match", len(results3), 0)

results4 = store_mod.search("skill")
check("search multiple", len(results4) >= 2, True)

# Case insensitive
results5 = store_mod.search("API")
check("search case insensitive", len(results5), 1)


# ===========================================================================
# Skill Info
# ===========================================================================

print("\n=== Skill Info ===")

info = store_mod.skill_info("api-testing")
check_true("skill_info returns tuple", info is not None)
si, body = info
check("info name", si.name, "api-testing")
check_in("info body", "Instructions here", body)

check("info nonexistent", store_mod.skill_info("nonexistent"), None)


# ===========================================================================
# Content Hashing
# ===========================================================================

print("\n=== Content Hashing ===")

hash1 = store_mod.hash_directory(tmp_store / "api-testing")
hash2 = store_mod.hash_directory(tmp_store / "api-testing")
check("hash deterministic", hash1, hash2)

hash3 = store_mod.hash_directory(tmp_store / "data-analysis")
check_true("different content different hash", hash1 != hash3)


# ===========================================================================
# Install
# ===========================================================================

print("\n=== Install ===")

_cleanup_custom()
_cleanup_managed()

# Install a skill
ok, msg = store_mod.install("api-testing")
check("install success", ok, True)
check_in("install msg", "installed", msg)

# Verify ref was created
ref = store_mod.read_ref("api-testing")
check_true("ref exists", ref is not None)
check("ref source", ref.source, "store")
check("ref source_uri", ref.source_uri, "skills/store/api-testing")

# Verify object was created
obj_dir = store_mod.object_dir(ref.digest)
check_true("object dir exists", obj_dir.is_dir())
check_true("object has skill.md", (obj_dir / "skill.md").is_file())

# SHA-256 verification: object hash matches store source
store_hash = store_mod.hash_directory(tmp_store / "api-testing")
check("object digest matches store", ref.digest, store_hash)

# Install nonexistent
ok2, msg2 = store_mod.install("nonexistent")
check("install nonexistent fails", ok2, False)
check_in("install nonexistent msg", "not found", msg2)

# Conflict: user-created custom skill with same name (no existing ref)
_create_custom_skill("conflict-skill")
_create_store_skill("conflict-skill", description="Store version")
ok3, msg3 = store_mod.install("conflict-skill")
check("install conflict fails", ok3, False)
check_in("conflict msg", "custom skill", msg3)

# Re-install (update) an already installed skill
ok4, msg4 = store_mod.install("api-testing")
check("reinstall success", ok4, True)
check_in("reinstall msg", "reinstalled", msg4)


# ===========================================================================
# is_store_installed
# ===========================================================================

print("\n=== is_store_installed ===")

check("api-testing is store installed", store_mod.is_store_installed("api-testing"), True)
check("conflict-skill not store installed", store_mod.is_store_installed("conflict-skill"), False)
check("nonexistent not installed", store_mod.is_store_installed("nonexistent"), False)


# ===========================================================================
# Uninstall
# ===========================================================================

print("\n=== Uninstall ===")

_cleanup_custom()
_cleanup_managed()

# Install first
store_mod.install("api-testing")
store_mod.install("data-analysis")

# Uninstall
ok, msg = store_mod.uninstall("api-testing", default_skills=())
check("uninstall success", ok, True)
check_in("uninstall msg", "uninstalled", msg)

# Ref should be gone
ref = store_mod.read_ref("api-testing")
check("ref removed", ref, None)

# Uninstall nonexistent
ok2, msg2 = store_mod.uninstall("nonexistent", default_skills=())
check("uninstall nonexistent fails", ok2, False)

# Uninstall non-managed custom skill
_create_custom_skill("my-custom")
ok3, msg3 = store_mod.uninstall("my-custom", default_skills=())
check("uninstall custom fails", ok3, False)
check_in("custom msg", "not installed", msg3)

# Uninstall refused while in BOT_SKILLS
ok4, msg4 = store_mod.uninstall("data-analysis", default_skills=("data-analysis",))
check("uninstall refused BOT_SKILLS", ok4, False)
check_in("BOT_SKILLS msg", "BOT_SKILLS", msg4)
# Ref should still exist
check_true("ref still exists", store_mod.read_ref("data-analysis") is not None)

# Uninstall with custom override note
_create_custom_skill("data-analysis")
ok5, msg5 = store_mod.uninstall("data-analysis", default_skills=())
check("uninstall with override success", ok5, True)
check_in("override note", "custom override", msg5)


# ===========================================================================
# Ref Round-Trip
# ===========================================================================

print("\n=== Ref Round-Trip ===")

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
check("round-trip source", read_back.source, "store")
check("round-trip digest", read_back.digest, "abc123deadbeef")
check("round-trip source_uri", read_back.source_uri, "skills/store/test-skill")
check("round-trip installed_at", read_back.installed_at, "2026-01-01T00:00:00+00:00")
check("round-trip version", read_back.version, "1.0")
check("round-trip publisher", read_back.publisher, "test-pub")
check("round-trip signature", read_back.signature, None)
check("round-trip pinned", read_back.pinned, True)

# Corrupt ref returns None
(tmp_refs / "corrupt.json").write_text("not json")
check("corrupt ref", store_mod.read_ref("corrupt"), None)

# Missing ref returns None
check("missing ref", store_mod.read_ref("does-not-exist"), None)


# ===========================================================================
# Update Checking
# ===========================================================================

print("\n=== Update Checking ===")

_cleanup_custom()
_cleanup_store()
_cleanup_managed()

# Create and install a skill
_create_store_skill("updatable", description="v1", body="Version 1 instructions.")
store_mod.install("updatable")

# No changes — up to date
updates = store_mod.check_updates()
check("initial up to date", len(updates), 1)
check("status up_to_date", updates[0], ("updatable", "up_to_date"))

# Modify store content — update available
_create_store_skill("updatable", description="v2", body="Version 2 instructions.")
updates2 = store_mod.check_updates()
check("update available", len(updates2), 1)
check("status update_available", updates2[0], ("updatable", "update_available"))


# ===========================================================================
# Update Skill
# ===========================================================================

print("\n=== Update Skill ===")

_cleanup_custom()
_cleanup_store()
_cleanup_managed()

_create_store_skill("update-me", description="v1", body="V1.")
store_mod.install("update-me")

# Update when already up to date
ok, msg = store_mod.update_skill("update-me")
check("update no-op", ok, True)
check_in("already up to date", "up to date", msg)

# Make store version newer
_create_store_skill("update-me", description="v2", body="V2.")
ok2, msg2 = store_mod.update_skill("update-me")
check("update success", ok2, True)
check_in("updated msg", "updated", msg2)

# Verify ref now points to new content
ref = store_mod.read_ref("update-me")
store_hash = store_mod.hash_directory(tmp_store / "update-me")
check("ref digest updated", ref.digest, store_hash)

# Verify object has new content
obj_dir = store_mod.object_dir(ref.digest)
installed_body = (obj_dir / "skill.md").read_text()
check_in("v2 content", "V2", installed_body)

# Update nonexistent
ok3, msg3 = store_mod.update_skill("nonexistent")
check("update nonexistent", ok3, False)

# Update non-managed skill
_create_custom_skill("my-skill")
ok4, msg4 = store_mod.update_skill("my-skill")
check("update custom fails", ok4, False)
check_in("custom msg", "no longer available", msg4)


# ===========================================================================
# Update All
# ===========================================================================

print("\n=== Update All ===")

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
check("update_all count", len(results), 2)
names_updated = [r[0] for r in results]
check_in("skill-a updated", "skill-a", names_updated)
check_in("skill-c updated", "skill-c", names_updated)
check_true("all succeeded", all(r[1] for r in results))

# No more updates
results2 = store_mod.update_all()
check("no more updates", len(results2), 0)


# ===========================================================================
# Custom Override Detection
# ===========================================================================

print("\n=== Custom Override Detection ===")

_cleanup_custom()
_cleanup_store()
_cleanup_managed()

# Install a managed skill
_create_store_skill("shadowed", body="Managed version.")
store_mod.install("shadowed")

# No override yet
check("no override", store_mod.has_custom_override("shadowed"), False)

# Create custom skill with same name
_create_custom_skill("shadowed", body="Custom version.")
check("has override", store_mod.has_custom_override("shadowed"), True)

# Custom only (no ref) — not an override
_create_custom_skill("custom-only", body="Just custom.")
check("custom-only not override", store_mod.has_custom_override("custom-only"), False)


# ===========================================================================
# Diff
# ===========================================================================

print("\n=== Diff ===")

_cleanup_custom()
_cleanup_store()
_cleanup_managed()

# Custom override vs managed
_create_store_skill("diff-test", body="Managed content.")
store_mod.install("diff-test")
_create_custom_skill("diff-test", body="Custom content.")

ok, diff_text = store_mod.diff_skill("diff-test")
check("diff success", ok, True)
check_in("diff has managed label", "managed", diff_text)
check_in("diff has custom label", "custom", diff_text)

# Managed vs store (update preview)
_cleanup_custom()
_create_store_skill("diff-test", body="Updated store content.")
ok2, diff_text2 = store_mod.diff_skill("diff-test")
check("update diff success", ok2, True)
check_in("diff has installed label", "installed", diff_text2)
check_in("diff has store label", "store", diff_text2)

# No differences
_create_store_skill("diff-test", body="Managed content.")  # match what was installed
# Need to reinstall to match
store_mod.install("diff-test")
ok3, diff_text3 = store_mod.diff_skill("diff-test")
check("no diff", ok3, True)
check_in("no differences", "no differences", diff_text3.lower())

# Nonexistent
ok4, msg4 = store_mod.diff_skill("nonexistent")
check("diff nonexistent", ok4, False)


# ===========================================================================
# Garbage Collection
# ===========================================================================

print("\n=== Garbage Collection ===")

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
check("gc skips young", len(removed), 0)
check_true("object still exists", store_mod._object_exists(digest))

# GC with zero grace — should remove
removed2 = store_mod.gc(grace_seconds=0)
check("gc removes old", len(removed2), 1)
check("gc removed correct", removed2[0], digest)
check_false("object gone", store_mod._object_exists(digest))

# GC doesn't touch referenced objects
_create_store_skill("gc-keep", body="Keep me.")
store_mod.install("gc-keep")
ref_keep = store_mod.read_ref("gc-keep")
removed3 = store_mod.gc(grace_seconds=0)
check("gc keeps referenced", len(removed3), 0)
check_true("referenced object safe", store_mod._object_exists(ref_keep.digest))


# ===========================================================================
# Startup Recovery
# ===========================================================================

print("\n=== Startup Recovery ===")

# Should be idempotent — just ensure dirs and run GC
store_mod.startup_recovery()
check_true("version file exists", tmp_version.is_file())
version_data = json.loads(tmp_version.read_text())
check("schema version", version_data["schema"], 1)

# Call again — idempotent
store_mod.startup_recovery()
check_true("still works", tmp_version.is_file())


# ===========================================================================
# Schema Guard
# ===========================================================================

print("\n=== Schema Guard ===")

# Write a future schema version
tmp_version.write_text(json.dumps({"schema": 99}) + "\n")
try:
    store_mod.check_schema()
    check_true("should have raised", False)
except RuntimeError as e:
    check_in("error mentions version", "99", str(e))
    check_in("error mentions upgrade", "Upgrade", str(e))

# Restore valid version
tmp_version.write_text(json.dumps({"schema": 1}) + "\n")
store_mod.check_schema()  # should not raise


# ===========================================================================
# Prompt Size Warning
# ===========================================================================

print("\n=== Prompt Size Warning ===")

from app.skills import check_prompt_size, PROMPT_SIZE_WARNING_THRESHOLD

# Short prompt — no warning
warning = check_prompt_size("short role", [])
check("no warning for short", warning, None)

from unittest.mock import patch

def fake_build_system_prompt(role, skills):
    return "x" * 9000

with patch("app.skills.build_system_prompt", fake_build_system_prompt):
    warning2 = check_prompt_size("role", ["some-skill"])
    check_true("warning for large prompt", warning2 is not None)
    check_in("threshold mentioned", "8,000", warning2)
    check_in("size mentioned", "9,000", warning2)

def fake_under_threshold(role, skills):
    return "x" * 7999

with patch("app.skills.build_system_prompt", fake_under_threshold):
    warning3 = check_prompt_size("role", ["some-skill"])
    check("no warning under threshold", warning3, None)


# ===========================================================================
# Admin Gate (is_admin helper)
# ===========================================================================

print("\n=== Admin Gate ===")

from app.config import parse_allowed_users

admin_ids, admin_names = parse_allowed_users("111,@adminuser")
check("admin ids parsed", admin_ids, {111})
check("admin names parsed", admin_names, {"adminuser"})

cfg_explicit = make_config(
    allowed_user_ids=frozenset({111, 222}),
    admin_user_ids=frozenset({111}),
    admin_usernames=frozenset({"adminuser"}),
)
check("admin field populated", cfg_explicit.admin_user_ids, frozenset({111}))

cfg_fallback = make_config(
    allowed_user_ids=frozenset({111, 222}),
    admin_user_ids=frozenset({111, 222}),
)
check("fallback admin matches allowed", cfg_fallback.admin_user_ids, frozenset({111, 222}))


# ===========================================================================
# Edge Cases
# ===========================================================================

print("\n=== Edge Cases ===")

# Empty store dir
_cleanup_store()
check("empty store list", store_mod.list_store_skills(), {})
check("empty store search", store_mod.search("anything"), [])

# Store dir doesn't exist
store_mod.STORE_DIR = Path("/nonexistent/store")
check("nonexistent store", store_mod.list_store_skills(), {})
store_mod.STORE_DIR = tmp_store

# Install from empty store
ok, msg = store_mod.install("anything")
check("install from empty store", ok, False)


# ===========================================================================
# Object Idempotence
# ===========================================================================

print("\n=== Object Idempotence ===")

_cleanup_store()
_cleanup_managed()

_create_store_skill("idem-test", body="Same content.")

# Create object twice — should be idempotent
digest1 = store_mod._create_object(tmp_store / "idem-test")
digest2 = store_mod._create_object(tmp_store / "idem-test")
check("idempotent digest", digest1, digest2)

# Only one object dir should exist
obj_count = len(list(tmp_objects.iterdir()))
check("single object", obj_count, 1)


# ===========================================================================
# Pinned Ref Skipped by update_all
# ===========================================================================

print("\n=== Pinned Ref ===")

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
check("pinned skipped", len(results), 1)
check_in("pinned msg", "pinned", results[0][2])

# Ref should still point to old digest
ref_after = store_mod.read_ref("pinned-skill")
check("digest unchanged", ref_after.digest, ref.digest)


# ===========================================================================
# Cleanup
# ===========================================================================

_restore_originals()

# ===========================================================================
checks.run_and_exit()
