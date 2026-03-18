import contextlib

from app.credential_validation import validate_credential
from app.channels.telegram.runtime_skills import (
    TelegramRuntimeSkillsRuntime,
    skills_show,
)
from app.identity import telegram_actor_key, telegram_conversation_key
from app.runtime.inbound_types import InboundCommand, InboundUser
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


async def test_runtime_skills_show_runs_from_explicit_runtime_boundary():
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
