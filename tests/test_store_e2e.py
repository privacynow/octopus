"""End-to-end runtime skill lifecycle tests over the content-store model."""

from pathlib import Path

from app.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from app.content_store import get_content_store
from app.providers.base import RunResult
from app.skill_catalog_service import get_skill_catalog_service
from app.storage import close_db, ensure_data_dirs, load_session
from app import work_queue as _work_queue
from app.identity import telegram_conversation_key
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    drain_one_worker_item,
    last_reply,
    last_run_context,
    make_config,
    reset_handler_test_runtime,
    send_command,
    send_text,
    setup_globals,
)
from tests.support.runtime_skill_registry import FakeRuntimeSkillRegistry


REGISTRY_URL = "https://registry.example.test/index.json"
MARKER_V1 = "RUNTIME_E2E_MARKER_V1_a9c4"
MARKER_V2 = "RUNTIME_E2E_MARKER_V2_f7b2"
MARKER_CUSTOM = "RUNTIME_E2E_MARKER_CUSTOM_3d1f"
MARKER_BUILTIN = "RUNTIME_E2E_MARKER_BUILTIN_8e5a"


def _admin_cfg(data_dir: Path):
    return make_config(
        data_dir=data_dir,
        registry_url=REGISTRY_URL,
        admin_actor_keys=frozenset({"tg:100"}),
        admin_usernames=frozenset({"admin"}),
        allowed_actor_keys=frozenset({"tg:100", "tg:200"}),
        allowed_usernames=frozenset({"admin", "regular"}),
    )


def _setup_runtime_env(tmp_path: Path, monkeypatch):
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


def _track(name: str, *, body: str, source_kind: str, source_uri: str, is_mutable: bool) -> RuntimeSkillTrackRecord:
    return RuntimeSkillTrackRecord(
        slug=name,
        display_name=name,
        description="test fixture",
        source_kind=source_kind,
        source_uri=source_uri,
        owner_actor="tg:42" if source_kind == "custom" else "",
        visibility="private" if source_kind == "custom" else "shared",
        is_mutable=is_mutable,
        revision=SkillRevisionRecord(
            instruction_body=body,
            version_label="draft" if source_kind == "custom" else source_kind,
            created_by="tests",
        ),
    )


def _put_custom_skill(name: str, *, body: str) -> None:
    get_content_store().replace_skill_track(
        _track(
            name,
            body=body,
            source_kind="custom",
            source_uri=f"custom/{name}",
            is_mutable=True,
        )
    )


def _put_builtin_skill(name: str, *, body: str) -> None:
    get_content_store().replace_skill_track(
        _track(
            name,
            body=body,
            source_kind="builtin",
            source_uri=f"catalog/{name}",
            is_mutable=False,
        )
    )


def _delete_imported_track(name: str) -> None:
    store = get_content_store()
    imported = next(item for item in store.list_skill_tracks(name) if item.source_kind == "imported")
    assert store.delete_skill_track(
        name,
        source_kind="imported",
        source_uri=imported.source_uri,
        owner_actor=imported.owner_actor,
    )


async def test_install_add_message_prompt(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        msg = await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        assert "installed" in last_reply(msg).lower()

        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "do something")
        await drain_one_worker_item(data_dir)
        assert MARKER_V1 in last_run_context(prov).system_prompt
    finally:
        _cleanup_runtime(data_dir)


async def test_update_propagates_to_prompt(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1, version="1.0.0")
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "go")
        await drain_one_worker_item(data_dir)
        assert MARKER_V1 in last_run_context(prov).system_prompt
        prov.run_calls.clear()

        registry.add_skill("helper", body=MARKER_V2, version="2.0.0")
        await send_command(th.cmd_skills, chat, admin, "/skills update helper", ["update", "helper"])

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "go again")
        await drain_one_worker_item(data_dir)
        prompt = last_run_context(prov).system_prompt
        assert MARKER_V2 in prompt
        assert MARKER_V1 not in prompt
    finally:
        _cleanup_runtime(data_dir)


async def test_uninstall_prunes_from_skills_output_and_list(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

        msg = await send_command(th.cmd_skills, chat, admin, "/skills", [])
        assert "helper" in last_reply(msg).lower()

        await send_command(th.cmd_skills, chat, admin, "/skills uninstall helper", ["uninstall", "helper"])

        msg2 = await send_command(th.cmd_skills, chat, admin, "/skills", [])
        assert "No active skills" in last_reply(msg2)

        msg3 = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
        reply3 = last_reply(msg3)
        assert "[active]" not in reply3
        assert "helper" not in reply3.lower()
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_shows_imported_content_not_registry_drift(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1, version="1.0.0")
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        registry.add_skill("helper", body=MARKER_V2, version="2.0.0")

        msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
        reply = last_reply(msg)
        assert MARKER_V1 in reply
        assert MARKER_V2 not in reply
        assert "Resolves to: imported" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_custom_only(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        _put_custom_skill("my-custom", body=MARKER_CUSTOM)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        msg = await send_command(th.cmd_skills, chat, admin, "/skills info my-custom", ["info", "my-custom"])
        reply = last_reply(msg)
        assert MARKER_CUSTOM in reply
        assert "Resolves to: custom" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_builtin(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        _put_builtin_skill("builtin-tool", body=MARKER_BUILTIN)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        msg = await send_command(th.cmd_skills, chat, admin, "/skills info builtin-tool", ["info", "builtin-tool"])
        reply = last_reply(msg)
        assert MARKER_BUILTIN in reply
        assert "Resolves to: builtin" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_custom_override(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        _put_custom_skill("helper", body=MARKER_CUSTOM)

        msg = await send_command(th.cmd_skills, chat, admin, "/skills info helper", ["info", "helper"])
        reply = last_reply(msg)
        assert MARKER_CUSTOM in reply
        assert MARKER_V1 not in reply
        assert "Resolves to: custom" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_custom_override_shadows_imported_in_prompt(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
        _put_custom_skill("helper", body=MARKER_CUSTOM)

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "go")
        await drain_one_worker_item(data_dir)
        prompt = last_run_context(prov).system_prompt
        assert MARKER_CUSTOM in prompt
        assert MARKER_V1 not in prompt
    finally:
        _cleanup_runtime(data_dir)


async def test_cross_user_imported_skill(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        regular = FakeUser(uid=200, username="regular")
        admin_chat = FakeChat(1001)
        user_chat = FakeChat(2001)

        await send_command(th.cmd_skills, admin_chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, user_chat, regular, "/skills add helper", ["add", "helper"])

        prov.run_results = [RunResult(text="ok")]
        await send_text(user_chat, regular, "hello")
        await drain_one_worker_item(data_dir)
        assert MARKER_V1 in last_run_context(prov).system_prompt
    finally:
        _cleanup_runtime(data_dir)


async def test_three_tier_resolution_in_prompt(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        _put_builtin_skill("helper", body=MARKER_BUILTIN)
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])

        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "go")
        await drain_one_worker_item(data_dir)
        prompt = last_run_context(prov).system_prompt
        assert MARKER_V1 in prompt
        assert MARKER_BUILTIN not in prompt
        prov.run_calls.clear()

        _put_custom_skill("helper", body=MARKER_CUSTOM)
        prov.run_results = [RunResult(text="ok")]
        await send_text(chat, admin, "go again")
        await drain_one_worker_item(data_dir)
        prompt2 = last_run_context(prov).system_prompt
        assert MARKER_CUSTOM in prompt2
        assert MARKER_V1 not in prompt2
        assert MARKER_BUILTIN not in prompt2
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_list_shows_imported_and_override_tags(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

        msg = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
        assert "(imported)" in last_reply(msg)

        _put_custom_skill("helper", body=MARKER_CUSTOM)
        msg2 = await send_command(th.cmd_skills, chat, admin, "/skills list", ["list"])
        assert "[custom override]" in last_reply(msg2)
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_updates_and_diff_reflect_registry_drift(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1, version="1.0.0")
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])

        msg = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
        assert "up to date" in last_reply(msg)

        registry.add_skill("helper", body=MARKER_V2, version="2.0.0")
        msg2 = await send_command(th.cmd_skills, chat, admin, "/skills updates", ["updates"])
        assert "update available" in last_reply(msg2)

        diff = await send_command(th.cmd_skills, chat, admin, "/skills diff helper", ["diff", "helper"])
        diff_reply = last_reply(diff)
        assert MARKER_V1 in diff_reply
        assert MARKER_V2 in diff_reply
    finally:
        _cleanup_runtime(data_dir)


async def test_normalization_on_add_path_persists_to_disk(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        _put_builtin_skill("other", body=MARKER_BUILTIN)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
        _delete_imported_track("helper")

        await send_command(th.cmd_skills, chat, admin, "/skills add other", ["add", "other"])

        msg = await send_command(th.cmd_skills, chat, admin, "/skills", [])
        reply = last_reply(msg)
        assert "other" in reply.lower()
        assert "helper" not in reply.lower()

        raw = load_session(
            data_dir,
            telegram_conversation_key(1001),
            "claude",
            prov.new_provider_state,
            "off",
        )
        assert raw.get("active_skills", []) == ["other"]
    finally:
        _cleanup_runtime(data_dir)


async def test_admin_sessions_filters_stale_skills(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill("helper", body=MARKER_V1)
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install helper", ["install", "helper"])
        await send_command(th.cmd_skills, chat, admin, "/skills add helper", ["add", "helper"])
        _delete_imported_track("helper")

        msg = await send_command(th.cmd_admin, chat, admin, "/admin sessions 1001", ["sessions", "1001"])
        reply = last_reply(msg)
        assert "Skills (0)" in reply
        assert "helper" not in reply.lower().replace("skills (0): none", "")
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_shows_provider_compatibility(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        registry.add_skill(
            "provider-skill",
            body="Some instructions.",
            claude_config={"mcp_servers": {}},
            codex_config={"scripts": []},
        )
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)

        await send_command(th.cmd_skills, chat, admin, "/skills install provider-skill", ["install", "provider-skill"])
        msg = await send_command(th.cmd_skills, chat, admin, "/skills info provider-skill", ["info", "provider-skill"])
        reply = last_reply(msg)
        assert "Providers:" in reply
        assert "claude" in reply
        assert "codex" in reply
    finally:
        _cleanup_runtime(data_dir)


async def test_skills_info_nonexistent(monkeypatch, tmp_path: Path):
    import app.channels.telegram.ingress as th

    data_dir, registry, prov = _setup_runtime_env(tmp_path, monkeypatch)
    try:
        admin = FakeUser(uid=100, username="admin")
        chat = FakeChat(1001)
        msg = await send_command(th.cmd_skills, chat, admin, "/skills info nope", ["info", "nope"])
        assert "not found" in last_reply(msg).lower()
    finally:
        _cleanup_runtime(data_dir)
