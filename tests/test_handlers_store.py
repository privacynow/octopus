"""Handler integration tests for skill-store flows."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import ensure_data_dirs, load_session, save_session, default_session
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
    tmp_store.mkdir()
    tmp_custom.mkdir()

    original = (store_mod.STORE_DIR, store_mod.CUSTOM_DIR, skills_mod.CUSTOM_DIR)
    store_mod.STORE_DIR = tmp_store
    store_mod.CUSTOM_DIR = tmp_custom
    skills_mod.CUSTOM_DIR = tmp_custom

    def cleanup():
        store_mod.STORE_DIR, store_mod.CUSTOM_DIR, skills_mod.CUSTOM_DIR = original

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
            checks.check_false("skill not installed", (tmp_custom / "helper").is_dir())
        finally:
            cleanup()


run_test("handler: non-admin install rejected", test_handler_nonadmin_install_rejected())


async def test_handler_admin_install_writes_manifest():
    import json
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
            checks.check_true("skill dir created", (tmp_custom / "helper").is_dir())
            checks.check_true("_store.json exists", (tmp_custom / "helper" / "_store.json").is_file())

            manifest = json.loads((tmp_custom / "helper" / "_store.json").read_text())
            checks.check("manifest source", manifest["source"], "store")
            checks.check("manifest not modified", manifest["locally_modified"], False)
        finally:
            cleanup()


run_test("handler: admin install writes manifest", test_handler_admin_install_writes_manifest())


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


async def test_handler_local_modification_detected_and_cleared():
    import json
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
            installed = tmp_custom / "helper" / "skill.md"
            installed.write_text(installed.read_text() + "\nLOCAL_EDIT.\n")

            msg = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
            checks.check_in("locally modified reported", "locally modified", last_reply(msg))

            manifest = json.loads((tmp_custom / "helper" / "_store.json").read_text())
            checks.check("locally_modified flag set", manifest["locally_modified"], True)

            (tmp_store / "helper" / "skill.md").write_text(
                "---\nname: helper\ndisplay_name: helper\n"
                "description: test fixture\n---\n\n" + STORE_V2 + "\n"
            )
            msg_update = await send_command(th.cmd_skills, chat, admin, "/skills update helper", ["update", "helper"])
            reply = last_reply(msg_update)
            checks.check_in("confirmation prompt shown", "local modifications", reply)
            checks.check_in("diff hint shown", "/skills diff", reply)

            # Simulate clicking "Yes, overwrite" callback
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("skill_update_confirm:helper", message=cb_msg, user=admin)
            cb_update = FakeUpdate(callback_query=query, user=admin, chat=chat)
            await th.handle_skill_update_callback(cb_update, None)

            manifest = json.loads((tmp_custom / "helper" / "_store.json").read_text())
            checks.check("locally_modified cleared", manifest["locally_modified"], False)
        finally:
            cleanup()


run_test("handler: local modification detected and cleared", test_handler_local_modification_detected_and_cleared())


async def test_handler_uninstall_sweeps_sessions():
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
            await send_command(th.cmd_skills, chat_admin, admin, "/skills add helper", ["add", "helper"])
            await send_command(th.cmd_skills, chat_user, regular, "/skills add helper", ["add", "helper"])

            msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills uninstall helper", ["uninstall", "helper"])
            checks.check_in("reply confirms uninstall", "uninstalled", last_reply(msg).lower())
            checks.check_false("skill dir removed", (tmp_custom / "helper").is_dir())

            s1 = load_session_disk(data_dir, 1001, prov)
            s2 = load_session_disk(data_dir, 2001, prov)
            checks.check_not_in("admin chat swept", "helper", s1.get("active_skills", []))
            checks.check_not_in("user chat swept", "helper", s2.get("active_skills", []))
        finally:
            cleanup()


run_test("handler: uninstall sweeps active sessions", test_handler_uninstall_sweeps_sessions())


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

    orig_store = store_mod.STORE_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            ensure_data_dirs(data_dir)
            tmp_store = Path(tmp) / "store"
            store_mod.STORE_DIR = tmp_store

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
        store_mod.STORE_DIR = orig_store


run_test("/skills info store requirements", test_skills_info_store_requirements())


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
    print(f"\n{'=' * 40}")
    print(f"  {checks.passed} passed, {checks.failed} failed")
    print(f"{'=' * 40}")
    raise SystemExit(1 if checks.failed else 0)


if __name__ == "__main__":
    asyncio.run(_main())
