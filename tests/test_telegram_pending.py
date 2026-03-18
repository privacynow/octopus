from app.channels.telegram.pending import TelegramPendingRuntime, reject_pending
from app.channels.telegram.state import get_channel_state
from app.identity import telegram_conversation_key
from app.storage import default_session, save_session
from tests.support.handler_support import (
    FakeMessage,
    FakeProvider,
    fresh_data_dir,
    make_config,
    reset_handler_test_runtime,
    setup_globals,
)


async def _unused_execute_request(*args, **kwargs):
    raise AssertionError("execute_request should not run in reject_pending")


async def _unused_request_approval(*args, **kwargs):
    raise AssertionError("request_approval should not run in reject_pending")


async def _noop_edit_or_reply_text(message, text, **kwargs):
    await message.reply_text(text, **kwargs)


def _unused_build_user_prompt(*args, **kwargs):
    raise AssertionError("build_user_prompt should not run in reject_pending")


async def test_reject_pending_runs_from_explicit_runtime_boundary():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)
        try:
            chat_id = 12345
            session = default_session(prov.name, prov.new_provider_state(), "on")
            session["pending_approval"] = {
                "request_user_id": "tg:42",
                "prompt": "dangerous request",
                "image_paths": [],
                "attachment_dicts": [],
                "context_hash": "",
                "created_at": 0,
            }
            save_session(data_dir, telegram_conversation_key(chat_id), session)

            runtime = TelegramPendingRuntime(
                state=get_channel_state(),
                chat_lock=None,
                edit_or_reply_text=_noop_edit_or_reply_text,
                execute_request=_unused_execute_request,
                request_approval=_unused_request_approval,
                build_user_prompt=_unused_build_user_prompt,
            )
            message = FakeMessage(text="")

            await reject_pending(chat_id, message, runtime=runtime)

            assert message.replies
            assert "rejected" in message.replies[-1]["text"].lower()
        finally:
            reset_handler_test_runtime()
