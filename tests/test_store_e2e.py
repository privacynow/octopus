"""End-to-end integration tests for the managed immutable store.

These test the full user-visible experience through the handler layer:
a user sends commands, the bot responds, and we verify what they actually
see and what the provider actually receives. Every test starts from a
Telegram command and ends by checking user-visible output or provider input.

Covers:
- Install → add → message → correct content reaches provider
- Uninstall → session normalization → stale skill pruned from /skills output
- Update → new content reaches provider on next message
- /skills info shows resolved content (not drifted store copy)
- /skills info works for custom-only, managed, catalog, and override skills
- /skills list accurately reflects active state after uninstall
- Custom override shadows managed skill in provider prompt
- Session normalization works across all command paths (not just messages)
- --doctor catches incompatible store schema
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import close_db, ensure_data_dirs
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    last_reply,
    last_run_context,
    make_config,
    make_store_skill,
    make_skill,
    send_command,
    send_text,
    setup_globals,
    load_session_disk,
)

checks = Checks()
_tests: list[tuple[str, object]] = []

MARKER_V1 = "UNIQUE_V1_MARKER_e2e_a9c4"
MARKER_V2 = "UNIQUE_V2_MARKER_e2e_f7b2"
MARKER_CUSTOM = "UNIQUE_CUSTOM_MARKER_e2e_3d1f"
MARKER_CATALOG = "UNIQUE_CATALOG_MARKER_e2e_8e5a"


def run_test(name, coro):
    _tests.append((name, coro))


def _store_env(tmp):
    """Set up an isolated store environment with all dirs monkey-patched."""
    import app.store as store_mod
    import app.skills as skills_mod

    data_dir = Path(tmp) / "data"
    ensure_data_dirs(data_dir)
    tmp_store = Path(tmp) / "store"
    tmp_custom = Path(tmp) / "custom"
    tmp_catalog = Path(tmp) / "catalog"
    tmp_managed = Path(tmp) / "managed"
    tmp_objects = tmp_managed / "objects"
    tmp_refs = tmp_managed / "refs"
    tmp_tmp = tmp_managed / "tmp"
    tmp_version = tmp_managed / "version.json"
    tmp_lock = tmp_managed / ".lock"

    for d in (tmp_store, tmp_custom, tmp_catalog, tmp_managed, tmp_objects, tmp_refs, tmp_tmp):
        d.mkdir(parents=True)
    tmp_version.write_text(json.dumps({"schema": 1}) + "\n")

    original = {
        "STORE_DIR": store_mod.STORE_DIR,
        "CUSTOM_DIR": store_mod.CUSTOM_DIR,
        "MANAGED_DIR": store_mod.MANAGED_DIR,
        "OBJECTS_DIR": store_mod.OBJECTS_DIR,
        "REFS_DIR": store_mod.REFS_DIR,
        "TMP_DIR": store_mod.TMP_DIR,
        "VERSION_FILE": store_mod.VERSION_FILE,
        "LOCK_FILE": store_mod.LOCK_FILE,
        "skills_CUSTOM_DIR": skills_mod.CUSTOM_DIR,
        "skills_CATALOG_DIR": skills_mod.CATALOG_DIR,
    }
    store_mod.STORE_DIR = tmp_store
    store_mod.CUSTOM_DIR = tmp_custom
    store_mod.MANAGED_DIR = tmp_managed
    store_mod.OBJECTS_DIR = tmp_objects
    store_mod.REFS_DIR = tmp_refs
    store_mod.TMP_DIR = tmp_tmp
    store_mod.VERSION_FILE = tmp_version
    store_mod.LOCK_FILE = tmp_lock
    skills_mod.CUSTOM_DIR = tmp_custom
    skills_mod.CATALOG_DIR = tmp_catalog

    def cleanup():
        close_db(data_dir)
        for attr, val in original.items():
            if attr.startswith("skills_"):
                setattr(skills_mod, attr[len("skills_"):], val)
            else:
                setattr(store_mod, attr, val)

    return data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup


def _admin_cfg(data_dir):
    return make_config(
        data_dir=data_dir,
        admin_user_ids=frozenset({100}),
        admin_usernames=frozenset({"admin"}),
        allowed_user_ids=frozenset({100, 200}),
        allowed_usernames=frozenset({"admin", "regular"}),
    )


def _make_catalog_skill(catalog_dir, name, body):
    d = catalog_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "skill.md").write_text(
        f"---\nname: {name}\ndisplay_name: {name}\n"
        f"description: test catalog skill\n---\n\n{body}\n"
    )
    return d


# ============================================================================
# E2E: Full lifecycle — install → add → message → correct content in prompt
# ============================================================================

async def test_install_add_message_prompt():
    """User installs a skill, adds it, sends a message — the skill's content
    must appear in the system prompt passed to the provider."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install
            msg = await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            checks.check_in("install reply", "installed", last_reply(msg).lower())

            # Add to session
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Send a message — provider should receive the skill content
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "do something")
            ctx = last_run_context(prov)
            checks.check_true("prompt exists", ctx is not None and ctx.system_prompt)
            checks.check_in("V1 marker in prompt", MARKER_V1, ctx.system_prompt)
        finally:
            cleanup()


run_test("e2e: install → add → message → correct prompt", test_install_add_message_prompt())


# ============================================================================
# E2E: Update → new content reaches provider
# ============================================================================

async def test_update_propagates_to_prompt():
    """After /skills update, the next message must see the new content."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Verify V1
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            checks.check_in("V1 before update", MARKER_V1, last_run_context(prov).system_prompt)
            prov.run_calls.clear()

            # Update the store source and run update
            make_store_skill(tmp_store, "helper", body=MARKER_V2)
            await send_command(th.cmd_skills, chat, admin, "/skills update helper", ["update", "helper"])

            # Verify V2 replaces V1
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            prompt = last_run_context(prov).system_prompt
            checks.check_in("V2 after update", MARKER_V2, prompt)
            checks.check_not_in("V1 gone after update", MARKER_V1, prompt)
        finally:
            cleanup()


run_test("e2e: update → new content in prompt", test_update_propagates_to_prompt())


# ============================================================================
# E2E: Uninstall → session normalization → stale skill pruned
# ============================================================================

async def test_uninstall_prunes_from_skills_command():
    """After uninstalling a skill, /skills (bare command) should NOT show it
    as active. This tests normalization happens on the command path, not just
    on the message path."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Verify it's active
            msg = await send_command(th.cmd_skills, chat, admin, "/skills", [])
            checks.check_in("helper is active before uninstall", "helper", last_reply(msg).lower())

            # Uninstall
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # /skills (bare) — helper must NOT appear as active
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills", [])
            reply = last_reply(msg2)
            checks.check_in("no active skills", "No active skills", reply)
        finally:
            cleanup()


run_test("e2e: uninstall → /skills shows no active", test_uninstall_prunes_from_skills_command())


# ============================================================================
# E2E: Uninstall → /skills list doesn't show stale [active]
# ============================================================================

async def test_uninstall_clears_active_in_list():
    """After uninstalling, /skills list should NOT mark the skill as [active]."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Verify active tag
            msg = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
            checks.check_in("active tag before", "[active]", last_reply(msg))

            # Uninstall
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # /skills list — helper should NOT be [active] (it shouldn't even be listed)
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
            reply2 = last_reply(msg2)
            checks.check_not_in("no active tag", "[active]", reply2)
        finally:
            cleanup()


run_test("e2e: uninstall → /skills list no stale [active]", test_uninstall_clears_active_in_list())


# ============================================================================
# E2E: /skills info shows resolved content (not drifted store)
# ============================================================================

async def test_skills_info_shows_installed_content_not_store():
    """When a managed skill is installed with V1 and the store advances to V2,
    /skills info should show V1 (the installed version), not V2."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Advance the store source (but don't update the managed skill)
            make_store_skill(tmp_store, "helper", body=MARKER_V2)

            # /skills info should show V1 (installed version), NOT V2 (store version)
            msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
            reply = last_reply(msg)
            checks.check_in("shows V1 content", MARKER_V1, reply)
            checks.check_not_in("does not show V2", MARKER_V2, reply)
            checks.check_in("shows managed source", "managed", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info shows installed content, not drifted store", test_skills_info_shows_installed_content_not_store())


# ============================================================================
# E2E: /skills info works for custom-only skill (not in store)
# ============================================================================

async def test_skills_info_custom_only():
    """/skills info for a custom-only skill (not in store) should show its
    content and identify it as custom, not '404 not found in store'."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            # Create a custom-only skill (not in store)
            make_skill(tmp_custom, "my-custom", body=MARKER_CUSTOM)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info my-custom", ["info", "my-custom"])
            reply = last_reply(msg)
            checks.check_not_in("no 404", "not found", reply.lower())
            checks.check_in("shows custom content", MARKER_CUSTOM, reply)
            checks.check_in("identifies as custom", "custom", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info works for custom-only skill", test_skills_info_custom_only())


# ============================================================================
# E2E: /skills info works for catalog skill
# ============================================================================

async def test_skills_info_catalog():
    """/skills info for a built-in catalog skill should show its content."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            # Create a catalog skill
            _make_catalog_skill(tmp_catalog, "builtin-tool", MARKER_CATALOG)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info builtin-tool", ["info", "builtin-tool"])
            reply = last_reply(msg)
            checks.check_not_in("no 404", "not found", reply.lower())
            checks.check_in("shows catalog content", MARKER_CATALOG, reply)
            checks.check_in("identifies as catalog", "catalog", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info works for catalog skill", test_skills_info_catalog())


# ============================================================================
# E2E: /skills info for custom override shows custom content
# ============================================================================

async def test_skills_info_custom_override():
    """When a custom skill shadows a managed skill, /skills info should show
    the custom content, not the managed content."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install managed version
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Create custom override with different content
            make_skill(tmp_custom, "helper", body=MARKER_CUSTOM)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
            reply = last_reply(msg)
            checks.check_in("shows custom body", MARKER_CUSTOM, reply)
            checks.check_not_in("not managed body", MARKER_V1, reply)
            checks.check_in("identifies override", "overriding", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info custom override shows custom content", test_skills_info_custom_override())


# ============================================================================
# E2E: Custom override shadows managed in provider prompt
# ============================================================================

async def test_custom_override_shadows_managed_in_prompt():
    """When a custom skill overrides a managed skill, the provider should
    receive the custom content, not the managed content."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Create custom override
            make_skill(tmp_custom, "helper", body=MARKER_CUSTOM)

            # Send message — provider should get custom content
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            prompt = last_run_context(prov).system_prompt
            checks.check_in("custom in prompt", MARKER_CUSTOM, prompt)
            checks.check_not_in("managed not in prompt", MARKER_V1, prompt)
        finally:
            cleanup()


run_test("e2e: custom override shadows managed in provider prompt", test_custom_override_shadows_managed_in_prompt())


# ============================================================================
# E2E: Uninstall → message path also gets normalization
# ============================================================================

async def test_uninstall_message_doesnt_crash():
    """After uninstalling a skill that was active, sending a message should
    work fine (not crash, not include the dead skill in the prompt)."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # Message should work and not include stale content
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            prompt = last_run_context(prov).system_prompt
            checks.check_not_in("stale content gone", MARKER_V1, prompt)
        finally:
            cleanup()


run_test("e2e: uninstall → message works, no stale content", test_uninstall_message_doesnt_crash())


# ============================================================================
# E2E: Cross-user — regular user sees managed skill added by admin
# ============================================================================

async def test_cross_user_managed_skill():
    """A regular user in a different chat should be able to add and use a
    managed skill installed by an admin."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            regular = FakeUser(uid=200, username="regular")
            admin_chat = FakeChat(1001)
            user_chat = FakeChat(2001)

            # Admin installs
            await send_command(th.cmd_skills, admin_chat, admin, "/skills install helper", ["install", "helper"])

            # Regular user adds and uses it
            await send_command(th.cmd_skills, user_chat, regular, "/skills add helper", ["add", "helper"])
            prov.run_results = [RunResult(text="ok")]
            await send_text(user_chat, regular, "hello")
            checks.check_in("user sees installed skill", MARKER_V1, last_run_context(prov).system_prompt)
        finally:
            cleanup()


run_test("e2e: regular user uses admin-installed managed skill", test_cross_user_managed_skill())


# ============================================================================
# E2E: Three-tier resolution ordering — custom > managed > catalog
# ============================================================================

async def test_three_tier_resolution_in_prompt():
    """With the same skill name in all three tiers, the custom version must
    be what reaches the provider."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            # All three tiers have 'helper' with different markers
            _make_catalog_skill(tmp_catalog, "helper", MARKER_CATALOG)
            make_store_skill(tmp_store, "helper", body=MARKER_V1)

            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install managed version
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Without custom override — should use managed (V1), not catalog
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            prompt = last_run_context(prov).system_prompt
            checks.check_in("managed wins over catalog", MARKER_V1, prompt)
            checks.check_not_in("catalog not used", MARKER_CATALOG, prompt)
            prov.run_calls.clear()

            # Add custom override — should use custom, not managed or catalog
            make_skill(tmp_custom, "helper", body=MARKER_CUSTOM)
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            prompt2 = last_run_context(prov).system_prompt
            checks.check_in("custom wins over all", MARKER_CUSTOM, prompt2)
            checks.check_not_in("managed not used", MARKER_V1, prompt2)
            checks.check_not_in("catalog not used 2", MARKER_CATALOG, prompt2)
        finally:
            cleanup()


run_test("e2e: three-tier resolution ordering in prompt", test_three_tier_resolution_in_prompt())


# ============================================================================
# E2E: /skills list shows (managed) tag for installed skill
# ============================================================================

async def test_skills_list_shows_managed_tag():
    """/skills list should annotate installed managed skills with (managed)."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            msg = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
            reply = last_reply(msg)
            checks.check_in("managed tag", "(managed)", reply)
        finally:
            cleanup()


run_test("e2e: /skills list shows (managed) tag", test_skills_list_shows_managed_tag())


# ============================================================================
# E2E: /skills list shows [custom override] when custom shadows managed
# ============================================================================

async def test_skills_list_shows_custom_override_tag():
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            make_skill(tmp_custom, "helper", body=MARKER_CUSTOM)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
            reply = last_reply(msg)
            checks.check_in("override tag", "[custom override]", reply)
        finally:
            cleanup()


run_test("e2e: /skills list shows [custom override] tag", test_skills_list_shows_custom_override_tag())


# ============================================================================
# E2E: /skills updates shows correct status after drift
# ============================================================================

async def test_skills_updates_shows_update_available():
    """After store source changes, /skills updates should show update_available."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Up to date
            msg = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
            checks.check_in("up to date", "up to date", last_reply(msg))

            # Advance store source
            make_store_skill(tmp_store, "helper", body=MARKER_V2)
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
            checks.check_in("update available", "update available", last_reply(msg2))
        finally:
            cleanup()


run_test("e2e: /skills updates shows correct status", test_skills_updates_shows_update_available())


# ============================================================================
# E2E: Normalization works for /skills add path too
# ============================================================================

async def test_normalization_on_skills_add_path():
    """If a skill was active but its ref was removed (e.g. by another instance),
    /skills add for a different skill should still work, and the stale skill
    should be gone from the active list."""
    import app.telegram_handlers as th
    import app.store as store_mod

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            _make_catalog_skill(tmp_catalog, "other", MARKER_CATALOG)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Simulate another instance removing the ref directly
            store_mod._delete_ref("helper")

            # Now add a different skill — session should self-heal
            await send_command(th.cmd_skills, chat, admin, "/skills add other", ["add", "other"])

            # Check active skills — only 'other', not stale 'helper'
            msg = await send_command(th.cmd_skills, chat, admin, "/skills", [])
            reply = last_reply(msg)
            checks.check_in("other is active", "other", reply.lower())
            checks.check_not_in("helper pruned", "helper", reply.lower())
        finally:
            cleanup()


run_test("e2e: normalization prunes stale on /skills add", test_normalization_on_skills_add_path())


# ============================================================================
# E2E: /skills info for uninstalled store skill (preview mode)
# ============================================================================

async def test_skills_info_uninstalled_store():
    """/skills info for a store skill that hasn't been installed yet should
    still show the store content as a preview."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Don't install — just preview
            msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
            reply = last_reply(msg)
            checks.check_in("shows store content", MARKER_V1, reply)
            checks.check_in("not installed hint", "not installed", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info preview for uninstalled store skill", test_skills_info_uninstalled_store())


# ============================================================================
# E2E: /skills info returns 404 for truly nonexistent
# ============================================================================

async def test_skills_info_nonexistent():
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info nope", ["info", "nope"])
            reply = last_reply(msg)
            checks.check_in("not found", "not found", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info 404 for nonexistent", test_skills_info_nonexistent())


# ============================================================================
# E2E: --doctor catches incompatible schema
# ============================================================================

async def test_doctor_catches_bad_schema():
    """run_doctor should fail when managed store has a future schema version."""
    import app.store as store_mod

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            prov = FakeProvider("claude")
            cfg = _admin_cfg(data_dir)

            # Write future schema
            store_mod.VERSION_FILE.write_text(json.dumps({"schema": 99}) + "\n")

            from app.main import run_doctor
            try:
                run_doctor(cfg, prov)
                checks.check_true("should have raised SystemExit", False)
            except SystemExit as e:
                checks.check("doctor exits 1", e.code, 1)
        finally:
            cleanup()


run_test("e2e: --doctor catches incompatible schema", test_doctor_catches_bad_schema())


# ============================================================================
# E2E: Catalog skill usable without install
# ============================================================================

async def test_catalog_skill_usable_without_install():
    """A built-in catalog skill should be usable via /skills add without
    any /skills install step."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            _make_catalog_skill(tmp_catalog, "builtin", MARKER_CATALOG)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Add directly — no install needed
            await send_command(th.cmd_skills, chat, admin, "/skills add builtin", ["add", "builtin"])

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            checks.check_in("catalog content in prompt", MARKER_CATALOG, last_run_context(prov).system_prompt)
        finally:
            cleanup()


run_test("e2e: catalog skill usable without install", test_catalog_skill_usable_without_install())


# ============================================================================
# E2E: /skills diff shows meaningful output
# ============================================================================

async def test_skills_diff_managed_vs_store():
    """After store source changes, /skills diff should show the differences."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Advance store
            make_store_skill(tmp_store, "helper", body=MARKER_V2)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills diff helper", ["diff", "helper"])
            reply = last_reply(msg)
            checks.check_in("diff shows V1", MARKER_V1, reply)
            checks.check_in("diff shows V2", MARKER_V2, reply)
        finally:
            cleanup()


run_test("e2e: /skills diff shows meaningful output", test_skills_diff_managed_vs_store())


# ============================================================================
# E2E: /admin sessions shows filtered skills after uninstall
# ============================================================================

async def test_admin_sessions_filters_stale_skills():
    """/admin sessions should NOT show uninstalled skills in the active count.
    This tests that stale active_skills in raw session JSON are filtered."""
    import app.telegram_handlers as th
    from app.storage import save_session, default_session

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install, add, then uninstall
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # /admin sessions detail — should NOT show helper
            msg = await send_command(th.cmd_admin, chat, admin, "/admin sessions 1001", ["sessions", "1001"])
            reply = last_reply(msg)
            checks.check_in("shows Skills (0)", "Skills (0)", reply)
            checks.check_not_in("helper not in detail", "helper", reply.lower().replace("skills (0): none", ""))

            # /admin sessions summary — helper should not appear in top skills
            msg2 = await send_command(th.cmd_admin, chat, admin, "/admin sessions", ["sessions"])
            reply2 = last_reply(msg2)
            checks.check_not_in("helper not in summary", "helper", reply2.lower())
        finally:
            cleanup()


run_test("e2e: /admin sessions filters stale skills", test_admin_sessions_filters_stale_skills())


# ============================================================================
# E2E: /skills info shows provider compatibility
# ============================================================================

async def test_skills_info_shows_providers():
    """/skills info should show provider compatibility (Providers: Claude, Codex)
    when the skill has provider YAML files."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            # Create a store skill with provider configs
            skill_dir = tmp_store / "provider-skill"
            skill_dir.mkdir()
            (skill_dir / "skill.md").write_text(
                "---\nname: provider-skill\ndisplay_name: Provider Skill\n"
                "description: has provider configs\n---\n\nSome instructions.\n"
            )
            (skill_dir / "claude.yaml").write_text("mcp_servers: {}\n")
            (skill_dir / "codex.yaml").write_text("scripts: []\n")

            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install the skill
            await send_command(th.cmd_skills, chat, admin, "/skills install provider-skill", ["install", "provider-skill"])

            # /skills info should show providers
            msg = await send_command(th.cmd_skills, chat, admin, "/skills info provider-skill", ["info", "provider-skill"])
            reply = last_reply(msg)
            checks.check_in("shows Claude provider", "Claude", reply)
            checks.check_in("shows Codex provider", "Codex", reply)
            checks.check_in("shows Providers label", "Providers:", reply)
        finally:
            cleanup()


run_test("e2e: /skills info shows provider compatibility", test_skills_info_shows_providers())


# ============================================================================
# E2E: /skills info source label matches actual resolution (stray dir edge case)
# ============================================================================

async def test_skills_info_source_stray_custom_dir():
    """An empty stray custom/<name>/ dir (without valid skill.md) alongside a
    managed ref should NOT make /skills info say 'custom (overriding managed)'.
    It should correctly identify as 'managed'."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install managed skill
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Create stray empty custom dir (no skill.md)
            (tmp_custom / "helper").mkdir(parents=True, exist_ok=True)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
            reply = last_reply(msg)
            checks.check_in("shows managed content", MARKER_V1, reply)
            # Should say "managed", NOT "custom (overriding managed)"
            checks.check_in("identifies as managed", "Resolves to: managed", reply)
            checks.check_not_in("not labeled as override", "overriding", reply.lower())
        finally:
            cleanup()


run_test("e2e: /skills info correct source with stray custom dir", test_skills_info_source_stray_custom_dir())


# ============================================================================
# E2E: /skills info source label with malformed custom skill.md
# ============================================================================

async def test_skills_info_source_malformed_custom():
    """A custom dir with malformed skill.md alongside managed ref should resolve
    to managed, not show an error or mislabel."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Create custom dir with malformed skill.md
            (tmp_custom / "helper").mkdir(parents=True, exist_ok=True)
            (tmp_custom / "helper" / "skill.md").write_text("---\nname: [broken yaml\n---\n")

            msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
            reply = last_reply(msg)
            checks.check_in("falls through to managed", MARKER_V1, reply)
            checks.check_in("labeled managed", "Resolves to: managed", reply)
        finally:
            cleanup()


run_test("e2e: /skills info falls through malformed custom to managed", test_skills_info_source_malformed_custom())


# ============================================================================
# E2E: Normalization actually persists (saves to disk)
# ============================================================================

async def test_normalization_persists_to_disk():
    """After normalization prunes a stale skill, the pruned state should be
    saved to disk — not just in memory for that one request."""
    import app.telegram_handlers as th
    import app.store as store_mod

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, tmp_catalog, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=MARKER_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Remove the ref directly (simulating another instance)
            store_mod._delete_ref("helper")

            # First load triggers normalization and save
            msg1 = await send_command(th.cmd_skills, chat, admin, "/skills", [])
            checks.check_in("first load: no active", "No active skills", last_reply(msg1))

            # Read from SQLite — should have empty active_skills
            from app.storage import load_session
            raw = load_session(data_dir, 1001, "claude", prov.new_provider_state, "off")
            checks.check("disk state pruned", raw.get("active_skills", []), [])
        finally:
            cleanup()


run_test("e2e: normalization persists pruned state to disk", test_normalization_persists_to_disk())


# ============================================================================
# Runner
# ============================================================================

async def _run_all():
    for name, coro in _tests:
        print(f"\n=== {name} ===")
        try:
            await coro
        except Exception as exc:
            print(f"  FAIL  {name} (exception: {exc})")
            import traceback
            traceback.print_exc()
            checks.failed += 1


async def _main():
    await _run_all()
    print(f"\n{'=' * 60}")
    print(f"  test_store_e2e.py: {checks.passed} passed, {checks.failed} failed")
    print(f"{'=' * 60}")
    raise SystemExit(1 if checks.failed else 0)


if __name__ == "__main__":
    asyncio.run(_main())
