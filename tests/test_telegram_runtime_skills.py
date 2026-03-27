import contextlib
from types import SimpleNamespace

from app.credential_validation import validate_credential
from app.workflows.runtime_skills.telegram import (
    TelegramRuntimeSkillsRuntime,
    handle_skills_command,
    skills_install,
    skills_show,
)
from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key
from octopus_sdk.inbound_types import InboundCommand, InboundUser
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    current_runtime,
    fresh_data_dir,
    make_config,
    reset_handler_test_runtime,
    setup_globals,
)


@contextlib.asynccontextmanager
async def _noop_chat_lock(*args, **kwargs):
    del args, kwargs
    yield False


async def test_runtime_skills_show_runs__explicit_runtime_boundary():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        try:
            chat = FakeChat(12345)
            message = FakeMessage(chat=chat, text="/skills")
            update = FakeUpdate(message=message, chat=chat)
            event = InboundCommand(
                user=InboundUser(id=telegram_actor_key(42), username="testuser"),
                conversation_key=telegram_conversation_key(chat.id),
                command="skills",
                source="telegram",
            )
            runtime = TelegramRuntimeSkillsRuntime(
                state=current_runtime(),
                chat_lock=_noop_chat_lock,
                validate_credential=validate_credential,
                check_prompt_size_cross_chat=lambda data_dir, skill_name: [],
            )

            await skills_show(event, update, runtime=runtime)

            assert message.replies
            assert "skill(s) available" in message.replies[-1]["text"]
        finally:
            reset_handler_test_runtime()


async def test_runtime_skills_command_usage_runs__explicit_runtime_boundary():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        try:
            chat = FakeChat(12345)
            message = FakeMessage(chat=chat, text="/skills nonsense")
            update = FakeUpdate(message=message, chat=chat)
            event = InboundCommand(
                user=InboundUser(id=telegram_actor_key(42), username="testuser"),
                conversation_key=telegram_conversation_key(chat.id),
                command="skills",
                args=["nonsense"],
                source="telegram",
            )
            runtime = TelegramRuntimeSkillsRuntime(
                state=current_runtime(),
                chat_lock=_noop_chat_lock,
                validate_credential=validate_credential,
                check_prompt_size_cross_chat=lambda data_dir, skill_name: [],
            )

            await handle_skills_command(event, update, runtime=runtime)

            assert message.replies
            assert "Usage" in message.replies[-1]["text"]
        finally:
            reset_handler_test_runtime()


async def test_runtime_skills_install_hides_raw_registry_exception(monkeypatch):
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, registry_url="https://registry.example.test/index.json")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        try:
            chat = FakeChat(12345)
            message = FakeMessage(chat=chat, text="/skills install helper")
            update = FakeUpdate(message=message, chat=chat)
            event = InboundCommand(
                user=InboundUser(id=telegram_actor_key(42), username="admin"),
                conversation_key=telegram_conversation_key(chat.id),
                command="skills",
                args=["install", "helper"],
                source="telegram",
            )
            runtime = TelegramRuntimeSkillsRuntime(
                state=current_runtime(),
                chat_lock=_noop_chat_lock,
                validate_credential=validate_credential,
                check_prompt_size_cross_chat=lambda data_dir, skill_name: [],
            )

            def _raise_install(name, registry_url):
                del name, registry_url
                raise RuntimeError("internal registry stacktrace /tmp/secret-token")

            fake_imports = SimpleNamespace(install_from_registry=_raise_install)
            monkeypatch.setattr(
                "app.workflows.runtime_skills.telegram._is_admin",
                lambda runtime, user: True,
            )
            monkeypatch.setattr(
                "app.workflows.runtime_skills.telegram._flows",
                lambda: SimpleNamespace(runtime_skills=SimpleNamespace(imports=fake_imports)),
            )

            await skills_install(event, update, "helper", runtime=runtime)

            assert message.replies
            reply_text = message.replies[-1]["text"]
            assert "Could not install this skill" in reply_text
            assert "secret-token" not in reply_text
            assert "/tmp/" not in reply_text
        finally:
            reset_handler_test_runtime()
