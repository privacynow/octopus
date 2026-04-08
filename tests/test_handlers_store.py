"""Handler integration tests for registry-backed runtime skill lifecycle flows."""

from pathlib import Path

from octopus_sdk.providers import RunResult
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.storage import close_db, ensure_data_dirs
from app import work_queue as _work_queue
from octopus_sdk.identity import telegram_conversation_key
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeProvider,
    FakeUser,
    drain_one_worker_item,
    has_markup_removal,
    last_reply,
    last_run_context,
    load_session_disk,
    make_config,
    reset_handler_test_runtime,
    send_callback,
    send_command,
    send_text,
    setup_globals,
)
from tests.support.runtime_skill_registry import FakeRuntimeSkillRegistry


REGISTRY_URL = "https://registry.example.test/index.json"
STORE_V1 = "HANDLER_IMPORT_MARKER_V1_4e02"
STORE_V2 = "HANDLER_IMPORT_MARKER_V2_91d7"


def _admin_cfg(data_dir: Path):
    return make_config(
        data_dir=data_dir,
        registry_url=REGISTRY_URL,
        admin_actor_keys=frozenset({"tg:100"}),
        admin_usernames=frozenset({"admin"}),
        allowed_actor_keys=frozenset({"tg:100", "tg:200"}),
        allowed_usernames=frozenset({"admin", "regular"}),
    )


def _setup_handler_env(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    registry = FakeRuntimeSkillRegistry(tmp_path / "registry", registry_url=REGISTRY_URL)
    registry.patch(monkeypatch)
    prov = FakeProvider("claude")
    setup_globals(_admin_cfg(data_dir), prov)
    return data_dir, registry, prov


def _cleanup_runtime(data_dir: Path) -> None:
    close_db(data_dir)
    _work_queue.close_transport_db(data_dir)
    reset_handler_test_runtime()


async def test_handler_nonadmin_install_rejected(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1)
        msg = await send_command(
            th.cmd_skills,
            FakeChat(2001),
            FakeUser(uid=200, username="regular"),
            "/skills install helper",
            ["install", "helper"],
        )

        assert "admin" in last_reply(msg).lower()
        assert get_skill_import_service().is_installed("helper") is False
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_admin_install_creates_imported_track(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1)
        msg = await send_command(
            th.cmd_skills,
            FakeChat(1001),
            FakeUser(uid=100, username="admin"),
            "/skills install helper",
            ["install", "helper"],
        )

        assert "installed" in last_reply(msg).lower()
        resolved = get_skill_catalog_service().resolve_track("helper")
        assert resolved is not None
        assert resolved.source_kind == "imported"
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_update_propagates_to_prompt(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1, version="1.0.0")

        admin = FakeUser(uid=100, username="admin")
        regular = FakeUser(uid=200, username="regular")
        chat_admin = FakeChat(1001)
        chat_user = FakeChat(2001)

        await send_command(th.cmd_skills, chat_admin, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat_user, regular, "/skills add helper", ["add", "helper"])

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat_user, regular, "go")
        await drain_one_worker_item(data_dir)
        assert STORE_V1 in last_run_context(prov).system_prompt
        prov.run_calls.clear()

        registry.add_skill("helper", body=STORE_V2, version="2.0.0")
        msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills update all", ["update", "all"])
        assert "Update results" in last_reply(msg)

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat_user, regular, "go again")
        await drain_one_worker_item(data_dir)
        prompt = last_run_context(prov).system_prompt
        assert STORE_V2 in prompt
        assert STORE_V1 not in prompt
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_uninstall_removes_imported_track(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        assert get_skill_import_service().is_installed("helper") is True

        msg = await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])
        assert "uninstalled" in last_reply(msg).lower()
        assert get_skill_import_service().is_installed("helper") is False
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_prompt_size_warning_lists_impacted_chats(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1, version="1.0.0")

        admin = FakeUser(uid=100, username="admin")
        regular = FakeUser(uid=200, username="regular")
        chat_admin = FakeChat(1001)
        chat_user = FakeChat(2001)

        await send_command(th.cmd_skills, chat_admin, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat_admin, admin, "/skills add helper", ["add", "helper"])
        await send_command(th.cmd_skills, chat_user, regular, "/skills add helper", ["add", "helper"])

        registry.add_skill("helper", body=("x" * 9000), version="2.0.0")
        msg = await send_command(th.cmd_skills, chat_admin, admin, "/skills update all", ["update", "all"])
        reply = last_reply(msg)

        assert "Prompt size warnings" in reply
        assert "1001" in reply
        assert "2001" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_shows_imported_requirements(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill(
            "store-cred-skill",
            body="Instructions here.",
            requires=[{"key": "API_TOKEN", "prompt": "Enter token"}],
        )
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install store-cred-skill", ["install", "store-cred-skill"])
        msg = await send_command(th.cmd_skills, chat, admin, "/skills info store-cred-skill", ["info", "store-cred-skill"])

        assert "Setup: API_TOKEN" in " ".join(r.get("text", "") for r in msg.replies)
    finally:
        _cleanup_runtime(data_dir)


async def test_skill_update_callback_nonadmin_alert(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1)
        query, cb_msg = await send_callback(
            th.handle_skill_update_callback,
            FakeChat(2001),
            FakeUser(uid=200, username="regular"),
            "skill_update_confirm:helper",
        )

        assert len(query.answers) == 1
        assert query.answer_show_alert
        assert "admin" in query.answer_text.lower()
        assert len(cb_msg.replies) == 0
    finally:
        _cleanup_runtime(data_dir)


async def test_skill_update_callback_admin_confirm(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=STORE_V1, version="1.0.0")
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        old_digest = get_skill_catalog_service().resolve_track("helper").revision.digest
        registry.add_skill("helper", body=STORE_V2, version="2.0.0")

        query, cb_msg = await send_callback(
            th.handle_skill_update_callback,
            chat,
            admin,
            "skill_update_confirm:helper",
        )

        assert len(query.answers) == 1
        assert not query.answer_show_alert
        assert has_markup_removal(cb_msg)
        assert "updated" in (cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else "").lower()
        assert get_skill_catalog_service().resolve_track("helper").revision.digest != old_digest
    finally:
        _cleanup_runtime(data_dir)


async def test_skill_update_callback_cancel(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        query, cb_msg = await send_callback(
            th.handle_skill_update_callback,
            FakeChat(1001),
            FakeUser(uid=100, username="admin"),
            "skill_update_cancel",
        )

        assert len(query.answers) == 1
        assert has_markup_removal(cb_msg)
        assert "cancelled" in (cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else "").lower()
    finally:
        _cleanup_runtime(data_dir)


async def test_skill_add_callback_confirm(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=("x" * 9000))
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

        query, cb_msg = await send_callback(
            th.handle_skill_add_callback,
            chat,
            admin,
            "skill_add_confirm:helper",
        )

        assert len(query.answers) == 1
        assert not query.answer_show_alert
        assert has_markup_removal(cb_msg)
        assert "active in this conversation" in (cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else "").lower()
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert "helper" in session.get("active_skills", [])
    finally:
        _cleanup_runtime(data_dir)


async def test_skill_add_callback_cancel(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=("x" * 9000))
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        query, cb_msg = await send_callback(
            th.handle_skill_add_callback,
            chat,
            admin,
            "skill_add_cancel",
        )

        assert len(query.answers) == 1
        assert has_markup_removal(cb_msg)
        assert "cancelled" in (cb_msg.replies[-1].get("edit_text", "") if cb_msg.replies else "").lower()
        session = load_session_disk(data_dir, telegram_conversation_key(1001), prov)
        assert "helper" not in session.get("active_skills", [])
    finally:
        _cleanup_runtime(data_dir)


async def test_callback_unauthorized_alert(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    prov = FakeProvider("claude")
    cfg = make_config(
        data_dir=data_dir,
        allow_open=False,
        admin_actor_keys=frozenset({"tg:100"}),
        admin_usernames=frozenset({"admin"}),
        allowed_actor_keys=frozenset({"tg:100", "tg:200"}),
        registry_url=REGISTRY_URL,
    )
    setup_globals(cfg, prov)
    try:
        stranger = FakeUser(uid=999, username="nobody")
        chat = FakeChat(9999)

        query, cb_msg = await send_callback(
            th.handle_callback,
            chat,
            stranger,
            "approval_approve",
        )

        assert len(query.answers) == 1
        assert query.answer_show_alert
        assert "not authorized" in query.answer_text.lower()
        assert len(cb_msg.replies) == 0
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_skill_lifecycle_commands(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        admin = FakeUser(uid=100, username="admin")
        regular = FakeUser(uid=200, username="regular")
        chat = FakeChat(1001)

        created = await send_command(th.cmd_skills, chat, regular, "/skills create release-notes", ["create", "release-notes"])
        assert "Created custom draft" in last_reply(created)
        assert get_skill_catalog_service().resolve_runtime_track("release-notes") is None

        edited = await send_command(
            th.cmd_skills,
            chat,
            regular,
            "/skills edit release-notes Summarize releases carefully.",
            ["edit", "release-notes", "Summarize", "releases", "carefully."],
        )
        assert "Saved draft" in last_reply(edited)

        submitted = await send_command(th.cmd_skills, chat, regular, "/skills submit release-notes", ["submit", "release-notes"])
        assert "Submitted" in last_reply(submitted)

        submitted_again = await send_command(th.cmd_skills, chat, regular, "/skills submit release-notes", ["submit", "release-notes"])
        assert "already submitted" in last_reply(submitted_again).lower()

        approved = await send_command(th.cmd_skills, chat, admin, "/skills approve release-notes", ["approve", "release-notes"])
        assert "Approved" in last_reply(approved)

        approved_again = await send_command(th.cmd_skills, chat, admin, "/skills approve release-notes", ["approve", "release-notes"])
        assert "already approved" in last_reply(approved_again).lower()

        published = await send_command(th.cmd_skills, chat, admin, "/skills publish release-notes", ["publish", "release-notes"])
        assert "Published" in last_reply(published)
        assert get_skill_catalog_service().resolve_runtime_track("release-notes") is not None

        archived = await send_command(th.cmd_skills, chat, admin, "/skills archive release-notes", ["archive", "release-notes"])
        assert "Archived" in last_reply(archived)
        assert get_skill_catalog_service().resolve_runtime_track("release-notes") is None

        archived_again = await send_command(th.cmd_skills, chat, admin, "/skills archive release-notes", ["archive", "release-notes"])
        assert "already archived" in last_reply(archived_again).lower()
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_skill_export_import_roundtrips_full_draft(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        regular = FakeUser(uid=200, username="regular")
        chat = FakeChat(1001)

        created = await send_command(th.cmd_skills, chat, regular, "/skills create pkg-skill", ["create", "pkg-skill"])
        assert "Created custom draft" in last_reply(created)

        edited = await send_command(
            th.cmd_skills,
            chat,
            regular,
            "/skills edit pkg-skill Use the chat package editor.",
            ["edit", "pkg-skill", "Use", "the", "chat", "package", "editor."],
        )
        assert "Saved draft" in last_reply(edited)

        exported = await send_command(
            th.cmd_skills,
            chat,
            regular,
            "/skills export pkg-skill",
            ["export", "pkg-skill"],
        )
        assert exported.replies
        export_reply = exported.replies[-1]
        assert export_reply.get("document") is not None
        assert "Exported" in (export_reply.get("caption") or "")

        imported_message = exported.replies[-1]["document"]
        importing = FakeMessage(chat=chat, text="/skills import pkg-copy", user=regular)
        importing.document = imported_message
        imported = await send_command(
            th.cmd_skills,
            chat,
            regular,
            "/skills import pkg-copy",
            ["import", "pkg-copy"],
            message=importing,
        )
        assert "Imported skill package" in last_reply(imported)

        track = get_skill_catalog_service().resolve_track("pkg-copy")
        assert track is not None
        assert track.revision.instruction_body == "Use the chat package editor."
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_skill_create_invalid_name_uses_safe_message(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        regular = FakeUser(uid=200, username="regular")
        chat = FakeChat(1001)

        invalid = await send_command(th.cmd_skills, chat, regular, "/skills create Bad Name", ["create", "Bad Name"])

        reply = last_reply(invalid).lower()
        assert "lowercase" in reply
        assert "digits" in reply
        assert "hyphen" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_handler_provider_guidance_lifecycle_commands(monkeypatch, tmp_path: Path):
    import app.runtime.telegram_ingress as th

    data_dir, registry, prov = _setup_handler_env(tmp_path, monkeypatch)
    try:
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        edited = await send_command(
            th.cmd_guidance,
            chat,
            admin,
            "/guidance edit claude Use edited guidance",
            ["edit", "claude", "Use", "edited", "guidance"],
        )
        assert "Saved draft provider guidance" in last_reply(edited)

        submitted = await send_command(th.cmd_guidance, chat, admin, "/guidance submit claude", ["submit", "claude"])
        assert "Submitted provider guidance" in last_reply(submitted)

        submitted_again = await send_command(th.cmd_guidance, chat, admin, "/guidance submit claude", ["submit", "claude"])
        assert "already submitted" in last_reply(submitted_again).lower()

        approved = await send_command(th.cmd_guidance, chat, admin, "/guidance approve claude", ["approve", "claude"])
        assert "Approved provider guidance" in last_reply(approved)

        approved_again = await send_command(th.cmd_guidance, chat, admin, "/guidance approve claude", ["approve", "claude"])
        assert "already approved" in last_reply(approved_again).lower()

        published = await send_command(th.cmd_guidance, chat, admin, "/guidance publish claude", ["publish", "claude"])
        assert "Published provider guidance" in last_reply(published)

        published_again = await send_command(th.cmd_guidance, chat, admin, "/guidance publish claude", ["publish", "claude"])
        assert "already published" in last_reply(published_again).lower()

        preview = await send_command(th.cmd_guidance, chat, admin, "/guidance preview claude", ["preview", "claude"])
        assert "Use edited guidance" in last_reply(preview)
    finally:
        _cleanup_runtime(data_dir)
