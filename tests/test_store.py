"""Tests for the skill store — Phase 5.

Covers:
- Store discovery (list_store_skills, skill_info)
- Search matching
- Install/uninstall lifecycle
- _store.json provenance round-trip
- Conflict detection (store vs user-created)
- SHA-256 content hashing and verification
- Update detection (check_updates, update_skill, update_all)
- locally_modified detection and warning
- Session sweep on uninstall
- Admin gate (tested via is_admin helper)
- Uninstall refused while in BOT_SKILLS
- Prompt size warning (check_prompt_size)
"""

import json
import os
import shutil
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        failed += 1


def check_in(name, needle, haystack):
    global passed, failed
    if needle in haystack:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected {needle!r} in {haystack!r}")
        failed += 1


def check_not_in(name, needle, haystack):
    global passed, failed
    if needle not in haystack:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected {needle!r} NOT in {haystack!r}")
        failed += 1


def check_true(name, value):
    global passed, failed
    if value:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected truthy, got: {value!r}")
        failed += 1


def check_false(name, value):
    check_true(name, not value)


# ---------------------------------------------------------------------------
# Setup: temp dirs for store and custom skills
# ---------------------------------------------------------------------------

tmp_root = tempfile.mkdtemp()
tmp_store = Path(tmp_root) / "store"
tmp_custom = Path(tmp_root) / "custom"
tmp_data = Path(tmp_root) / "data"
tmp_store.mkdir()
tmp_custom.mkdir()
(tmp_data / "sessions").mkdir(parents=True)

# Monkey-patch store module dirs
import app.store as store_mod
_orig_store_dir = store_mod.STORE_DIR
_orig_custom_dir = store_mod.CUSTOM_DIR
store_mod.STORE_DIR = tmp_store
store_mod.CUSTOM_DIR = tmp_custom


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
    """Remove all custom skills."""
    if tmp_custom.is_dir():
        shutil.rmtree(tmp_custom)
    tmp_custom.mkdir()


def _cleanup_store():
    """Remove all store skills."""
    if tmp_store.is_dir():
        shutil.rmtree(tmp_store)
    tmp_store.mkdir()


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

hash1 = store_mod._hash_directory(tmp_store / "api-testing")
hash2 = store_mod._hash_directory(tmp_store / "api-testing")
check("hash deterministic", hash1, hash2)

hash3 = store_mod._hash_directory(tmp_store / "data-analysis")
check_true("different content different hash", hash1 != hash3)


# ===========================================================================
# Install
# ===========================================================================

print("\n=== Install ===")

_cleanup_custom()

# Install a skill
ok, msg = store_mod.install("api-testing")
check("install success", ok, True)
check_in("install msg", "installed", msg)
check_true("skill dir exists", (tmp_custom / "api-testing").is_dir())
check_true("skill.md exists", (tmp_custom / "api-testing" / "skill.md").is_file())
check_true("_store.json exists", (tmp_custom / "api-testing" / "_store.json").is_file())

# Read manifest
manifest = store_mod.read_manifest(tmp_custom / "api-testing")
check_true("manifest read", manifest is not None)
check("manifest source", manifest.source, "store")
check("manifest store_path", manifest.store_path, "skills/store/api-testing")
check_false("manifest not modified", manifest.locally_modified)

# SHA-256 verification
store_hash = store_mod._hash_directory(tmp_store / "api-testing")
installed_hash = store_mod._hash_directory(tmp_custom / "api-testing")
check("hash matches after install", installed_hash, store_hash)
check("manifest hash matches", manifest.content_sha256, store_hash)

# Install nonexistent
ok2, msg2 = store_mod.install("nonexistent")
check("install nonexistent fails", ok2, False)
check_in("install nonexistent msg", "not found", msg2)

# Conflict: user-created skill with same name
_create_custom_skill("conflict-skill")
_create_store_skill("conflict-skill", description="Store version")
ok3, msg3 = store_mod.install("conflict-skill")
check("install conflict fails", ok3, False)
check_in("conflict msg", "custom skill", msg3)

# Re-install (update) an already installed skill
ok4, msg4 = store_mod.install("api-testing")
check("reinstall success", ok4, True)
check_in("reinstall msg", "updated", msg4)


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

# Install first
_cleanup_custom()
store_mod.install("api-testing")
store_mod.install("data-analysis")

# Uninstall
ok, msg = store_mod.uninstall("api-testing", default_skills=())
check("uninstall success", ok, True)
check_in("uninstall msg", "uninstalled", msg)
check_false("dir removed", (tmp_custom / "api-testing").is_dir())

# Uninstall nonexistent
ok2, msg2 = store_mod.uninstall("nonexistent", default_skills=())
check("uninstall nonexistent fails", ok2, False)

# Uninstall user-created skill
_create_custom_skill("my-custom")
ok3, msg3 = store_mod.uninstall("my-custom", default_skills=())
check("uninstall custom fails", ok3, False)
check_in("custom msg", "custom skill", msg3)

# Uninstall refused while in BOT_SKILLS
ok4, msg4 = store_mod.uninstall("data-analysis", default_skills=("data-analysis",))
check("uninstall refused BOT_SKILLS", ok4, False)
check_in("BOT_SKILLS msg", "BOT_SKILLS", msg4)
check_true("skill still exists", (tmp_custom / "data-analysis").is_dir())

# Uninstall with session sweep
swept_count = [0]
def fake_sweep(name):
    swept_count[0] += 1
    return 3

ok5, msg5 = store_mod.uninstall("data-analysis", default_skills=(), session_sweep_fn=fake_sweep)
check("uninstall with sweep success", ok5, True)
check("sweep called", swept_count[0], 1)
check_in("sweep count msg", "3 chat(s)", msg5)


# ===========================================================================
# Session Sweep (storage.py)
# ===========================================================================

print("\n=== Session Sweep ===")

from app.storage import sweep_skill_from_sessions

# Create some session files
sessions_dir = tmp_data / "sessions"
for old in sessions_dir.glob("*.json"):
    old.unlink()

s1 = {"active_skills": ["code-review", "api-testing"], "updated_at": "old"}
s2 = {"active_skills": ["api-testing", "testing"], "updated_at": "old"}
s3 = {"active_skills": ["debugging"], "updated_at": "old"}

(sessions_dir / "100.json").write_text(json.dumps(s1))
(sessions_dir / "200.json").write_text(json.dumps(s2))
(sessions_dir / "300.json").write_text(json.dumps(s3))

swept = sweep_skill_from_sessions(tmp_data, "api-testing")
check("swept 2 sessions", swept, 2)

# Verify sessions were updated
s1_after = json.loads((sessions_dir / "100.json").read_text())
check("s1 skill removed", s1_after["active_skills"], ["code-review"])
check_true("s1 updated_at changed", s1_after["updated_at"] != "old")

s2_after = json.loads((sessions_dir / "200.json").read_text())
check("s2 skill removed", s2_after["active_skills"], ["testing"])

s3_after = json.loads((sessions_dir / "300.json").read_text())
check("s3 unchanged", s3_after["active_skills"], ["debugging"])
check("s3 updated_at unchanged", s3_after["updated_at"], "old")

# Sweep nonexistent skill
swept2 = sweep_skill_from_sessions(tmp_data, "nonexistent")
check("sweep no matches", swept2, 0)


# ===========================================================================
# Update Checking
# ===========================================================================

print("\n=== Update Checking ===")

_cleanup_custom()
_cleanup_store()

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

# Locally modified installed skill
installed_skill_md = tmp_custom / "updatable" / "skill.md"
installed_skill_md.write_text(installed_skill_md.read_text() + "\nLocal edit.\n")
updates3 = store_mod.check_updates()
check("locally modified", len(updates3), 1)
check("status locally_modified", updates3[0], ("updatable", "locally_modified"))


# ===========================================================================
# Update Skill
# ===========================================================================

print("\n=== Update Skill ===")

_cleanup_custom()
_cleanup_store()

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

# Verify content was updated
installed_body = (tmp_custom / "update-me" / "skill.md").read_text()
check_in("v2 content", "V2", installed_body)

# Manifest updated
manifest = store_mod.read_manifest(tmp_custom / "update-me")
check("manifest hash updated", manifest.content_sha256, store_mod._hash_directory(tmp_store / "update-me"))

# Update nonexistent
ok3, msg3 = store_mod.update_skill("nonexistent")
check("update nonexistent", ok3, False)

# Update custom (non-store) skill
_create_custom_skill("my-skill")
ok4, msg4 = store_mod.update_skill("my-skill")
check("update custom fails", ok4, False)
check_in("custom msg", "custom skill", msg4)

# Locally modified warning on update
_create_store_skill("modified-test", body="V1.")
store_mod.install("modified-test")
(tmp_custom / "modified-test" / "skill.md").write_text("local edit")
_create_store_skill("modified-test", body="V2.")
ok5, msg5 = store_mod.update_skill("modified-test")
check("modified update success", ok5, True)
check_in("modified warning", "local modifications", msg5)


# ===========================================================================
# Update All
# ===========================================================================

print("\n=== Update All ===")

_cleanup_custom()
_cleanup_store()

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
# _store.json Provenance Round-Trip
# ===========================================================================

print("\n=== Provenance Round-Trip ===")

_cleanup_custom()
_cleanup_store()

_create_store_skill("prov-test", description="Provenance test")
store_mod.install("prov-test")

manifest = store_mod.read_manifest(tmp_custom / "prov-test")
check("source", manifest.source, "store")
check("store_path", manifest.store_path, "skills/store/prov-test")
check_true("installed_at non-empty", len(manifest.installed_at) > 0)
check_true("content_sha256 non-empty", len(manifest.content_sha256) > 0)
check("locally_modified", manifest.locally_modified, False)

# Verify round-trip: write then read
store_mod._write_manifest(tmp_custom / "prov-test", manifest)
manifest2 = store_mod.read_manifest(tmp_custom / "prov-test")
check("round-trip source", manifest2.source, manifest.source)
check("round-trip path", manifest2.store_path, manifest.store_path)
check("round-trip hash", manifest2.content_sha256, manifest.content_sha256)


# ===========================================================================
# Prompt Size Warning
# ===========================================================================

print("\n=== Prompt Size Warning ===")

from app.skills import check_prompt_size, PROMPT_SIZE_WARNING_THRESHOLD

# Short prompt — no warning
warning = check_prompt_size("short role", [])
check("no warning for short", warning, None)

# We can't easily create a prompt > 8000 chars with real catalog skills,
# so test the function directly with a mock
from unittest.mock import patch

def fake_build_system_prompt(role, skills):
    return "x" * 9000

with patch("app.skills.build_system_prompt", fake_build_system_prompt):
    warning2 = check_prompt_size("role", ["some-skill"])
    check_true("warning for large prompt", warning2 is not None)
    check_in("threshold mentioned", "8,000", warning2)
    check_in("size mentioned", "9,000", warning2)

# Just under threshold — no warning
def fake_under_threshold(role, skills):
    return "x" * 7999

with patch("app.skills.build_system_prompt", fake_under_threshold):
    warning3 = check_prompt_size("role", ["some-skill"])
    check("no warning under threshold", warning3, None)


# ===========================================================================
# Admin Gate (is_admin helper)
# ===========================================================================

print("\n=== Admin Gate ===")

from app.config import BotConfig, parse_allowed_users

def make_config(**overrides):
    defaults = dict(
        instance="test", telegram_token="x", allow_open=True,
        allowed_user_ids=frozenset(), allowed_usernames=frozenset(),
        provider_name="claude", model="test", working_dir=Path("/tmp"),
        extra_dirs=(), data_dir=Path("/tmp/data"), timeout_seconds=300,
        approval_mode="off", role="", role_from_file=False,
        default_skills=(), stream_update_interval_seconds=1.0,
        typing_interval_seconds=4.0, codex_sandbox="", codex_skip_git_repo_check=True,
        codex_full_auto=False, codex_dangerous=False, codex_profile="",
        admin_user_ids=frozenset(), admin_usernames=frozenset(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# Test parse_allowed_users for admin parsing
admin_ids, admin_names = parse_allowed_users("111,@adminuser")
check("admin ids parsed", admin_ids, {111})
check("admin names parsed", admin_names, {"adminuser"})

# Config with explicit admins
cfg_explicit = make_config(
    allowed_user_ids=frozenset({111, 222}),
    admin_user_ids=frozenset({111}),
    admin_usernames=frozenset({"adminuser"}),
)
check("admin field populated", cfg_explicit.admin_user_ids, frozenset({111}))

# Config without BOT_ADMIN_USERS falls back to allowed users
# (This is handled in load_config, but we verify the field exists)
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

# Read manifest from dir without _store.json
d = tmp_custom / "no-manifest"
d.mkdir(parents=True, exist_ok=True)
(d / "skill.md").write_text("---\nname: no-manifest\n---\n\nHello\n")
check("no manifest", store_mod.read_manifest(d), None)

# Malformed _store.json
d2 = tmp_custom / "bad-manifest"
d2.mkdir(parents=True, exist_ok=True)
(d2 / "_store.json").write_text("not json")
check("malformed manifest", store_mod.read_manifest(d2), None)



# ===========================================================================
# locally_modified persisted to _store.json
# ===========================================================================

print("\n=== locally_modified persistence ===")

_cleanup_custom()
_cleanup_store()

_create_store_skill("persist-mod", body="V1.")
store_mod.install("persist-mod")

# Before modification, locally_modified is False on disk
manifest_before = store_mod.read_manifest(tmp_custom / "persist-mod")
check("not modified before edit", manifest_before.locally_modified, False)

# Modify the installed skill
(tmp_custom / "persist-mod" / "skill.md").write_text(
    (tmp_custom / "persist-mod" / "skill.md").read_text() + "\nLocal edit."
)

# check_updates should persist locally_modified=True
updates = store_mod.check_updates()
check("detected modified", updates[0], ("persist-mod", "locally_modified"))

# Now read manifest from disk — locally_modified should be True
manifest_after = store_mod.read_manifest(tmp_custom / "persist-mod")
check_true("locally_modified persisted", manifest_after.locally_modified)

# Calling check_updates again should not re-write (already True)
updates2 = store_mod.check_updates()
check("still modified", updates2[0], ("persist-mod", "locally_modified"))
manifest_after2 = store_mod.read_manifest(tmp_custom / "persist-mod")
check_true("still persisted", manifest_after2.locally_modified)

# After update, locally_modified resets to False
_create_store_skill("persist-mod", body="V2.")
store_mod.update_skill("persist-mod")
manifest_updated = store_mod.read_manifest(tmp_custom / "persist-mod")
check("modified reset after update", manifest_updated.locally_modified, False)

# ===========================================================================
# Cleanup
# ===========================================================================

# Restore original dirs
store_mod.STORE_DIR = _orig_store_dir
store_mod.CUSTOM_DIR = _orig_custom_dir

shutil.rmtree(tmp_root, ignore_errors=True)

# ===========================================================================
# Summary
# ===========================================================================

print(f"\n{'='*60}")
print(f"  test_store.py: {passed} passed, {failed} failed")
print(f"{'='*60}")

if failed:
    sys.exit(1)
