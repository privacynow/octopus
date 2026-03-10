"""Handler integration tests for skill-store flows (immutable store model)."""

import tempfile
from pathlib import Path

from app.providers.base import RunResult
from app.storage import close_db, ensure_data_dirs, load_session, save_session, default_session
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    has_markup_removal,
    last_reply,
    last_run_context,
    load_session_disk,
    make_config,
    make_store_skill,
    send_callback,
    send_command,
    send_text,
    setup_globals,
)

STORE_V1 = "STORE_HELPER_V1_d4e8"
STORE_V2 = "STORE_HELPER_V2_b7f1"


def _store_env(tmp):
    import app.store as store_mod
    import app.skills as skills_mod

    data_dir = Path(tmp) / "data"
    ensure_data_dirs(data_dir)
    tmp_store = Path(tmp) / "store"
    tmp_custom = Path(tmp) / "custom"
    tmp_managed = Path(tmp) / "managed"
    tmp_objects = tmp_managed / "objects"
    tmp_refs = tmp_managed / "refs"
    tmp_tmp = tmp_managed / "tmp"
    tmp_version = tmp_managed / "version.json"
    tmp_lock = tmp_managed / ".lock"

    tmp_store.mkdir()
    tmp_custom.mkdir()
    tmp_managed.mkdir()
    tmp_objects.mkdir()
    tmp_refs.mkdir()
    tmp_tmp.mkdir()

    import json
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

    def cleanup():
        close_db(data_dir)
        store_mod.STORE_DIR = original["STORE_DIR"]
        store_mod.CUSTOM_DIR = original["CUSTOM_DIR"]
        store_mod.MANAGED_DIR = original["MANAGED_DIR"]
        store_mod.OBJECTS_DIR = original["OBJECTS_DIR"]
        store_mod.REFS_DIR = original["REFS_DIR"]
        store_mod.TMP_DIR = original["TMP_DIR"]
        store_mod.VERSION_FILE = original["VERSION_FILE"]
        store_mod.LOCK_FILE = original["LOCK_FILE"]
        skills_mod.CUSTOM_DIR = original["skills_CUSTOM_DIR"]

    return data_dir, tmp_store, tmp_custom, cleanup


def _admin_cfg(data_dir):
    return make_config(
        data_dir=data_dir,
        admin_user_ids=frozenset({100}),
        admin_usernames=frozenset({"admin"}),
        allowed_user_ids=frozenset({100, 200}),
        allowed_usernames=frozenset({"admin", "regular"}),
    )


async def test_handler_nonadmin_install_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            msg = await send_command(
                __import__("app.telegram_handlers", fromlist=["cmd_skills"]).cmd_skills,
                FakeChat(2001),
                FakeUser(uid=200, username="regular"),
                "/skills install helper",
                ["install", "helper"],
            )

            assert "admin" in last_reply(msg).lower()
            # No ref should exist
            import app.store as store_mod
            assert not (store_mod.read_ref("helper") is not None)
        finally:
            cleanup()


async def test_handler_admin_install_creates_ref():
    import app.store as store_mod
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            msg = await send_command(th.cmd_skills, FakeChat(1001), FakeUser(uid=100, username="admin"),
                                     "/skills install helper", ["install", "helper"])

            assert "installed" in last_reply(msg).lower()

            # Ref should exist
            ref = store_mod.read_ref("helper")
            assert ref is not None
            assert ref.source == "store"

            # Object should exist
            obj_dir = store_mod.object_dir(ref.digest)
            assert obj_dir.is_dir()
        finally:
            cleanup()


async def test_handler_store_update_propagates():
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            regular = FakeUser(uid=200, username="regular")
            chat_admin = FakeChat(1001)
            chat_user = FakeChat(2001)

            await send_command(th.cmd_skills, chat_admin, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat_user, regular, "/skills add helper", ["add", "helper"])

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat_user, regular, "go")
            assert STORE_V1 in last_run_context(prov).system_prompt
            prov.run_calls.clear()

            (tmp_store / "helper" / "skill.md").write_text(
                "---\nname: helper\ndisplay_name: helper\n"
                "description: test fixture\n---\n\n" + STORE_V2 + "\n"
            )
            msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills update all", ["update", "all"])
            assert "Update results" in last_reply(msg)

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat_user, regular, "go again")
            ctx = last_run_context(prov)
            assert STORE_V2 in ctx.system_prompt
            assert STORE_V1 not in ctx.system_prompt
        finally:
            cleanup()


async def test_handler_uninstall_removes_ref():
    import app.store as store_mod
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat_admin = FakeChat(1001)

            await send_command(th.cmd_skills, chat_admin, admin, "/skills install helper", ["install", "helper"])
            assert store_mod.read_ref("helper") is not None

            msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills uninstall helper", ["uninstall", "helper"])
            assert "uninstalled" in last_reply(msg).lower()
            assert store_mod.read_ref("helper") is None
        finally:
            cleanup()


async def test_handler_prompt_size_warning_lists_chats():
    from unittest.mock import patch
    import app.skills as skills_mod
    import app.telegram_handlers as th
    from app.skills import PROMPT_SIZE_WARNING_THRESHOLD

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            regular = FakeUser(uid=200, username="regular")
            chat_admin = FakeChat(1001)
            chat_user = FakeChat(2001)

            await send_command(th.cmd_skills, chat_admin, admin, "/skills install helper", ["install", "helper"])
            await send_command(th.cmd_skills, chat_admin, admin, "/skills add helper", ["add", "helper"])
            await send_command(th.cmd_skills, chat_user, regular, "/skills add helper", ["add", "helper"])

            (tmp_store / "helper" / "skill.md").write_text(
                "---\nname: helper\ndisplay_name: helper\n"
                "description: test fixture\n---\n\n" + STORE_V2 + "\n"
            )

            original_build = skills_mod.build_system_prompt

            def fake_oversize(role, active_skills):
                if "helper" in active_skills:
                    return "x" * (PROMPT_SIZE_WARNING_THRESHOLD + 500)
                return original_build(role, active_skills)

            with patch("app.skills.build_system_prompt", fake_oversize):
                msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills update all", ["update", "all"])

            reply = last_reply(msg)
            assert "Prompt size warnings" in reply
            assert "1001" in reply
            assert "2001" in reply
        finally:
            cleanup()


async def test_smoke_store_lifecycle():
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            msg = await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            assert "installed" in last_reply(msg).lower()

            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            assert STORE_V1 in last_run_context(prov).system_prompt
            prov.run_calls.clear()

            msg = await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])
            assert "uninstalled" in last_reply(msg).lower()

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            assert STORE_V1 not in last_run_context(prov).system_prompt
        finally:
            cleanup()


async def test_skills_info_store_requirements():
    import app.store as store_mod
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            skill_dir = tmp_store / "store-cred-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: store-cred-skill\ndisplay_name: Store Cred\n"
                "description: A store skill\n---\n\nInstructions here.\n"
            )
            (skill_dir / "requires.yaml").write_text("credentials:\n  - key: API_TOKEN\n    prompt: Enter token\n")

            cfg = make_config(data_dir)
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            chat = FakeChat(12345)
            user = FakeUser(42)
            msg = await send_command(th.cmd_skills, chat, user, "/skills info store-cred-skill", ["info", "store-cred-skill"])
            assert "Requires: API_TOKEN" in " ".join(r.get("text", "") for r in msg.replies)
        finally:
            cleanup()


async def test_skill_update_callback_nonadmin_alert():
    """Non-admin clicking update callback gets an alert, not silent rejection."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            chat = FakeChat(2001)
            regular = FakeUser(uid=200, username="regular")
            query, cb_msg = await send_callback(
                th.handle_skill_update_callback, chat, regular, "skill_update_confirm:helper")

            assert len(query.answers) == 1
            assert query.answer_show_alert
            assert "admin" in query.answer_text.lower()
            assert len(cb_msg.replies) == 0
        finally:
            cleanup()


async def test_skill_update_callback_admin_confirm():
    """Admin confirming update via callback actually updates the skill and shows result."""
    import app.store as store_mod
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install first
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
            old_ref = store_mod.read_ref("helper")
            assert old_ref is not None

            # Update store source
            (tmp_store / "helper" / "skill.md").write_text(
                "---\nname: helper\ndisplay_name: helper\n"
                "description: test fixture\n---\n\n" + STORE_V2 + "\n"
            )

            # Admin confirms update via callback
            query, cb_msg = await send_callback(
                th.handle_skill_update_callback, chat, admin, "skill_update_confirm:helper")

            assert len(query.answers) == 1
            assert not query.answer_show_alert
            assert has_markup_removal(cb_msg)
            reply_text = cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else ""
            assert "helper" in reply_text

            new_ref = store_mod.read_ref("helper")
            assert new_ref is not None and new_ref.digest != old_ref.digest
        finally:
            cleanup()


async def test_skill_update_callback_cancel():
    """Cancel button on update callback edits message without updating."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            query, cb_msg = await send_callback(
                th.handle_skill_update_callback, chat, admin, "skill_update_cancel")

            assert len(query.answers) == 1
            assert has_markup_removal(cb_msg)
            reply_text = cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else ""
            assert "cancelled" in reply_text.lower()
        finally:
            cleanup()


async def test_skill_add_callback_confirm():
    """Confirming skill add via callback activates the skill in session."""
    import app.store as store_mod
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            # Install the skill so it's in the catalog
            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            # Confirm add via callback (simulates user clicking "Yes" on size warning)
            query, cb_msg = await send_callback(
                th.handle_skill_add_callback, chat, admin, "skill_add_confirm:helper")

            assert len(query.answers) == 1
            assert not query.answer_show_alert
            assert has_markup_removal(cb_msg)
            reply_text = cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else ""
            assert "activated" in reply_text.lower()

            # Skill should be in session
            session = load_session_disk(data_dir, 1001, prov)
            assert "helper" in session.get("active_skills", [])
        finally:
            cleanup()


async def test_skill_add_callback_cancel():
    """Cancel button on skill add callback edits message without activating."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            make_store_skill(tmp_store, "helper", body=STORE_V1)
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            admin = FakeUser(uid=100, username="admin")
            chat = FakeChat(1001)

            await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

            query, cb_msg = await send_callback(
                th.handle_skill_add_callback, chat, admin, "skill_add_cancel")

            assert len(query.answers) == 1
            assert has_markup_removal(cb_msg)
            reply_text = cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else ""
            assert "cancelled" in reply_text.lower()

            # Skill should NOT be in session
            session = load_session_disk(data_dir, 1001, prov)
            assert "helper" not in session.get("active_skills", [])
        finally:
            cleanup()


async def test_callback_unauthorized_alert():
    """Unauthorized user clicking any callback gets 'Not authorized' alert."""
    import app.telegram_handlers as th

    with tempfile.TemporaryDirectory() as tmp:
        data_dir, tmp_store, tmp_custom, cleanup = _store_env(tmp)
        try:
            prov = FakeProvider("claude")
            setup_globals(_admin_cfg(data_dir), prov)

            # User 999 is not in allowed_user_ids
            stranger = FakeUser(uid=999, username="nobody")
            chat = FakeChat(9999)

            query, cb_msg = await send_callback(
                th.handle_callback, chat, stranger, "approval_approve")

            assert len(query.answers) == 1
            assert query.answer_show_alert
            assert "not authorized" in query.answer_text.lower()
            assert len(cb_msg.replies) == 0
        finally:
            cleanup()
