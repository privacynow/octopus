from app.channels.telegram.guidance import handle_guidance_command
from app.identity import telegram_actor_key, telegram_conversation_key
from app.runtime.inbound_types import InboundCommand, InboundUser
from tests.support.handler_support import (
    FakeChat,
    FakeMessage,
    FakeUpdate,
)


async def test_guidance_command_admin_gate_runs_from_explicit_boundary():
    chat = FakeChat(12345)
    message = FakeMessage(chat=chat, text="/guidance approve claude")
    update = FakeUpdate(message=message, chat=chat)
    event = InboundCommand(
        user=InboundUser(id=telegram_actor_key(42), username="testuser"),
        conversation_key=telegram_conversation_key(chat.id),
        command="guidance",
        args=["approve", "claude"],
        source="telegram",
    )

    await handle_guidance_command(event, update, is_admin=False)

    assert message.replies
    assert "admin" in message.replies[-1]["text"].lower()
