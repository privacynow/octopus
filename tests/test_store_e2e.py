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

import json
import tempfile
from pathlib import Path

from app.providers.base import RunResult
from app.storage import close_db, ensure_data_dirs
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

MARKER_V1 = "UNIQUE_V1_MARKER_e2e_a9c4"
MARKER_V2 = "UNIQUE_V2_MARKER_e2e_f7b2"
MARKER_CUSTOM = "UNIQUE_CUSTOM_MARKER_e2e_3d1f"
MARKER_CATALOG = "UNIQUE_CATALOG_MARKER_e2e_8e5a"


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
            assert "installed" in last_reply(msg).lower()

            # Add to session
            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

            # Send a message — provider should receive the skill content
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "do something")
            ctx = last_run_context(prov)
            assert ctx is not None and ctx.system_prompt
            assert MARKER_V1 in ctx.system_prompt
        finally:
            cleanup()


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
            assert MARKER_V1 in last_run_context(prov).system_prompt
            prov.run_calls.clear()

            # Update the store source and run update
            make_store_skill(tmp_store, "helper", body=MARKER_V2)
            await send_command(th.cmd_skills, chat, admin, "/skills update helper", ["update", "helper"])

            # Verify V2 replaces V1
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            prompt = last_run_context(prov).system_prompt
            assert MARKER_V2 in prompt
            assert MARKER_V1 not in prompt
        finally:
            cleanup()


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
            assert "helper" in last_reply(msg).lower()

            # Uninstall
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # /skills (bare) — helper must NOT appear as active
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills", [])
            reply = last_reply(msg2)
            assert "No active skills" in reply
        finally:
            cleanup()


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
            assert "[active]" in last_reply(msg)

            # Uninstall
            await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

            # /skills list — helper should NOT be [active] (it shouldn't even be listed)
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
            reply2 = last_reply(msg2)
            assert "[active]" not in reply2
        finally:
            cleanup()


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
            assert MARKER_V1 in reply
            assert MARKER_V2 not in reply
            assert "managed" in reply.lower()
        finally:
            cleanup()


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
            assert "not found" not in reply.lower()
            assert MARKER_CUSTOM in reply
            assert "custom" in reply.lower()
        finally:
            cleanup()


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
            assert "not found" not in reply.lower()
            assert MARKER_CATALOG in reply
            assert "catalog" in reply.lower()
        finally:
            cleanup()


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
            assert MARKER_CUSTOM in reply
            assert MARKER_V1 not in reply
            assert "overriding" in reply.lower()
        finally:
            cleanup()


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
            assert MARKER_CUSTOM in prompt
            assert MARKER_V1 not in prompt
        finally:
            cleanup()


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
            assert MARKER_V1 not in prompt
        finally:
            cleanup()


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
            assert MARKER_V1 in last_run_context(prov).system_prompt
        finally:
            cleanup()


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
            assert MARKER_V1 in prompt
            assert MARKER_CATALOG not in prompt
            prov.run_calls.clear()

            # Add custom override — should use custom, not managed or catalog
            make_skill(tmp_custom, "helper", body=MARKER_CUSTOM)
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            prompt2 = last_run_context(prov).system_prompt
            assert MARKER_CUSTOM in prompt2
            assert MARKER_V1 not in prompt2
            assert MARKER_CATALOG not in prompt2
        finally:
            cleanup()


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
            assert "(managed)" in reply
        finally:
            cleanup()


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
            assert "[custom override]" in reply
        finally:
            cleanup()


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
            assert "up to date" in last_reply(msg)

            # Advance store source
            make_store_skill(tmp_store, "helper", body=MARKER_V2)
            msg2 = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
            assert "update available" in last_reply(msg2)
        finally:
            cleanup()


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
            assert "other" in reply.lower()
            assert "helper" not in reply.lower()
        finally:
            cleanup()


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
            assert MARKER_V1 in reply
            assert "not installed" in reply.lower()
        finally:
            cleanup()


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
            assert "not found" in reply.lower()
        finally:
            cleanup()


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

            from app.main import _run_doctor
            try:
                await _run_doctor(cfg, prov)
                assert False, "should have raised SystemExit"
            except SystemExit as e:
                assert e.code == 1
        finally:
            cleanup()


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
            assert MARKER_CATALOG in last_run_context(prov).system_prompt
        finally:
            cleanup()


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
            assert MARKER_V1 in reply
            assert MARKER_V2 in reply
        finally:
            cleanup()


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
            assert "Skills (0)" in reply
            assert "helper" not in reply.lower().replace("skills (0): none", "")

            # /admin sessions summary — helper should not appear in top skills
            msg2 = await send_command(th.cmd_admin, chat, admin, "/admin sessions", ["sessions"])
            reply2 = last_reply(msg2)
            assert "helper" not in reply2.lower()
        finally:
            cleanup()


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
            assert "Claude" in reply
            assert "Codex" in reply
            assert "Providers:" in reply
        finally:
            cleanup()


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
            assert MARKER_V1 in reply
            # Should say "managed", NOT "custom (overriding managed)"
            assert "Resolves to: managed" in reply
            assert "overriding" not in reply.lower()
        finally:
            cleanup()


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
            assert MARKER_V1 in reply
            assert "Resolves to: managed" in reply
        finally:
            cleanup()


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
            assert "No active skills" in last_reply(msg1)

            # Read from SQLite — should have empty active_skills
            from app.storage import load_session
            raw = load_session(data_dir, 1001, "claude", prov.new_provider_state, "off")
            assert raw.get("active_skills", []) == []
        finally:
            cleanup()
