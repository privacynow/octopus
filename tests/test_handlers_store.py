"""Handler integration tests for skill-store flows (immutable store model)."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import _db_connections, ensure_data_dirs, load_session, save_session, default_session
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    last_reply,
    last_run_context,
    load_session_disk,
    make_config,
    make_store_skill,
    send_command,
    send_text,
    setup_globals,
)

checks = Checks()
_tests: list[tuple[str, object]] = []

STORE_V1 = "STORE_HELPER_V1_d4e8"
STORE_V2 = "STORE_HELPER_V2_b7f1"


def run_test(name, coro):
    _tests.append((name, coro))


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

            checks.check_in("blocked msg mentions admin", "admin", last_reply(msg).lower())
            # No ref should exist
            import app.store as store_mod
            checks.check_false("skill not installed", store_mod.read_ref("helper") is not None)
        finally:
            cleanup()


run_test("handler: non-admin install rejected", test_handler_nonadmin_install_rejected())


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

            checks.check_in("reply confirms install", "installed", last_reply(msg).lower())

            # Ref should exist
            ref = store_mod.read_ref("helper")
            checks.check_true("ref created", ref is not None)
            checks.check("ref source", ref.source, "store")

            # Object should exist
            obj_dir = store_mod._object_dir(ref.digest)
            checks.check_true("object exists", obj_dir.is_dir())
        finally:
            cleanup()


run_test("handler: admin install creates ref", test_handler_admin_install_creates_ref())


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
            checks.check_in("V1 in prompt", STORE_V1, last_run_context(prov).system_prompt)
            prov.run_calls.clear()

            (tmp_store / "helper" / "skill.md").write_text(
                "---\nname: helper\ndisplay_name: helper\n"
                "description: test fixture\n---\n\n" + STORE_V2 + "\n"
            )
            msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills update all", ["update", "all"])
            checks.check_in("update reply", "Update results", last_reply(msg))

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat_user, regular, "go again")
            ctx = last_run_context(prov)
            checks.check_in("V2 in prompt", STORE_V2, ctx.system_prompt)
            checks.check_not_in("V1 gone", STORE_V1, ctx.system_prompt)
        finally:
            cleanup()


run_test("handler: store update propagates to provider", test_handler_store_update_propagates())


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
            checks.check_true("ref exists after install", store_mod.read_ref("helper") is not None)

            msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills uninstall helper", ["uninstall", "helper"])
            checks.check_in("reply confirms uninstall", "uninstalled", last_reply(msg).lower())
            checks.check("ref removed", store_mod.read_ref("helper"), None)
        finally:
            cleanup()


run_test("handler: uninstall removes ref", test_handler_uninstall_removes_ref())


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
            checks.check_in("warning header", "Prompt size warnings", reply)
            checks.check_in("admin chat warned", "1001", reply)
            checks.check_in("user chat warned", "2001", reply)
        finally:
            cleanup()


run_test("handler: prompt size warning lists chats", test_handler_prompt_size_warning_lists_chats())


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
            checks.check_in("smoke: installed", "installed", last_reply(msg).lower())

            await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go")
            checks.check_in("smoke: marker in prompt", STORE_V1, last_run_context(prov).system_prompt)
            prov.run_calls.clear()

            msg = await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])
            checks.check_in("smoke: uninstalled", "uninstalled", last_reply(msg).lower())

            prov.run_results = [RunResult(text="ok")]
            await send_text(chat, admin, "go again")
            checks.check_not_in("smoke: marker gone", STORE_V1, last_run_context(prov).system_prompt)
        finally:
            cleanup()


run_test("smoke: store lifecycle", test_smoke_store_lifecycle())


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
            checks.check_in("store skill shows Requires", "Requires: API_TOKEN", " ".join(r.get("text", "") for r in msg.replies))
        finally:
            cleanup()


run_test("/skills info store requirements", test_skills_info_store_requirements())


def _close_all_db_connections():
    """Close all leaked SQLite connections between tests."""
    for conn in _db_connections.values():
        try:
            conn.close()
        except Exception:
            pass
    _db_connections.clear()


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
        finally:
            _close_all_db_connections()


async def _main():
    await _run_all()
    print(f"\n{'=' * 40}")
    print(f"  {checks.passed} passed, {checks.failed} failed")
    print(f"{'=' * 40}")
    raise SystemExit(1 if checks.failed else 0)


if __name__ == "__main__":
    asyncio.run(_main())
