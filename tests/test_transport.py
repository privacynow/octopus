"""Tests for the inbound transport normalization layer (app/transport.py)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.transport import (
    InboundAttachment,
    InboundCallback,
    InboundCommand,
    InboundMessage,
    InboundUser,
    normalize_callback,
    normalize_command,
    normalize_message,
    normalize_user,
)
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    make_config,
    setup_globals,
    test_data_dir,
)

checks = Checks()
run_test = checks.add_test


# ---------------------------------------------------------------------------
# normalize_user
# ---------------------------------------------------------------------------

def test_normalize_user_basic():
    user = FakeUser(uid=42, username="Alice")
    result = normalize_user(user)
    checks.check_true("returns InboundUser", isinstance(result, InboundUser))
    checks.check("id matches", result.id, 42)
    checks.check("username lowercased", result.username, "alice")


run_test("normalize_user basic", test_normalize_user_basic)


def test_normalize_user_no_username():
    user = FakeUser(uid=99, username=None)
    user.username = None
    result = normalize_user(user)
    checks.check("id", result.id, 99)
    checks.check("username empty for None", result.username, "")


run_test("normalize_user no username", test_normalize_user_no_username)


def test_normalize_user_empty_username():
    user = FakeUser(uid=1)
    user.username = ""
    result = normalize_user(user)
    checks.check("username empty", result.username, "")


run_test("normalize_user empty username", test_normalize_user_empty_username)


def test_normalize_user_none():
    """normalize_user(None) returns None, not an exception."""
    result = normalize_user(None)
    checks.check_true("returns None for None user", result is None)


run_test("normalize_user None returns None", test_normalize_user_none)


# ---------------------------------------------------------------------------
# normalize_command
# ---------------------------------------------------------------------------

def test_normalize_command_basic():
    chat = FakeChat(12345)
    user = FakeUser(42, "bob")
    msg = FakeMessage(chat=chat, text="/help skills approval")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext(args=["skills", "approval"])

    result = normalize_command(upd, ctx)
    checks.check_true("returns InboundCommand", isinstance(result, InboundCommand))
    checks.check("chat_id", result.chat_id, 12345)
    checks.check("user.id", result.user.id, 42)
    checks.check("command", result.command, "help")
    checks.check("args", result.args, ("skills", "approval"))


run_test("normalize_command basic", test_normalize_command_basic)


def test_normalize_command_with_bot_mention():
    """Commands like /help@mybotname should strip the @botname suffix."""
    chat = FakeChat(99)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/help@mybotname")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext(args=[])

    result = normalize_command(upd, ctx)
    checks.check("command strips bot mention", result.command, "help")


run_test("normalize_command with bot mention", test_normalize_command_with_bot_mention)


def test_normalize_command_no_args():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/start")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext()

    result = normalize_command(upd, ctx)
    checks.check("command", result.command, "start")
    checks.check("args empty", result.args, ())


run_test("normalize_command no args", test_normalize_command_no_args)


def test_normalize_command_no_user():
    """normalize_command returns None when update has no user."""
    chat = FakeChat(1)
    msg = FakeMessage(chat=chat, text="/help")
    upd = FakeUpdate(message=msg, user=None, chat=chat)
    upd.effective_user = None

    result = normalize_command(upd, FakeContext())
    checks.check_true("returns None for no user", result is None)


run_test("normalize_command no user", test_normalize_command_no_user)


# ---------------------------------------------------------------------------
# normalize_callback
# ---------------------------------------------------------------------------

def test_normalize_callback_basic():
    chat = FakeChat(555)
    user = FakeUser(77, "carol")
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data="approval_approve", message=msg)
    upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

    result = normalize_callback(upd)
    checks.check_true("returns InboundCallback", isinstance(result, InboundCallback))
    checks.check("chat_id", result.chat_id, 555)
    checks.check("user.id", result.user.id, 77)
    checks.check("data", result.data, "approval_approve")


run_test("normalize_callback basic", test_normalize_callback_basic)


def test_normalize_callback_complex_data():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data="skill_update_confirm:my-skill", message=msg)
    upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

    result = normalize_callback(upd)
    checks.check("data preserved", result.data, "skill_update_confirm:my-skill")


run_test("normalize_callback complex data", test_normalize_callback_complex_data)


def test_normalize_callback_empty_data():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data=None, message=msg)
    query.data = None
    upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

    result = normalize_callback(upd)
    checks.check("empty data", result.data, "")


run_test("normalize_callback empty data", test_normalize_callback_empty_data)


def test_normalize_callback_no_user():
    """normalize_callback returns None when update has no user."""
    chat = FakeChat(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data="approval_approve", message=msg)
    upd = FakeUpdate(message=msg, user=None, chat=chat, callback_query=query)
    upd.effective_user = None

    result = normalize_callback(upd)
    checks.check_true("returns None for no user", result is None)


run_test("normalize_callback no user", test_normalize_callback_no_user)


# ---------------------------------------------------------------------------
# normalize_message
# ---------------------------------------------------------------------------

async def test_normalize_message_text():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir()
        chat = FakeChat(100)
        user = FakeUser(50, "dave")
        msg = FakeMessage(chat=chat, text="hello world")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        result = await normalize_message(upd, FakeContext(), data_dir)
        checks.check_true("returns InboundMessage", isinstance(result, InboundMessage))
        checks.check("chat_id", result.chat_id, 100)
        checks.check("user.id", result.user.id, 50)
        checks.check("user.username", result.user.username, "dave")
        checks.check("text", result.text, "hello world")
        checks.check("no attachments", result.attachments, ())


run_test("normalize_message text", test_normalize_message_text())


async def test_normalize_message_caption():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir()
        chat = FakeChat(100)
        user = FakeUser(50)
        msg = FakeMessage(chat=chat)
        msg.text = None
        msg.caption = "photo caption"
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        result = await normalize_message(upd, FakeContext(), data_dir)
        checks.check("caption used as text", result.text, "photo caption")


run_test("normalize_message caption", test_normalize_message_caption())


async def test_normalize_message_empty():
    """Returns None when there's no text and no attachments."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir()
        chat = FakeChat(100)
        user = FakeUser(50)
        msg = FakeMessage(chat=chat)
        msg.text = None
        msg.caption = None
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        result = await normalize_message(upd, FakeContext(), data_dir)
        checks.check_true("returns None for empty", result is None)


run_test("normalize_message empty returns None", test_normalize_message_empty())


async def test_normalize_message_no_user():
    """normalize_message returns None when update has no user."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir()
        chat = FakeChat(1)
        msg = FakeMessage(chat=chat, text="hello")
        upd = FakeUpdate(message=msg, user=None, chat=chat)
        upd.effective_user = None

        result = await normalize_message(upd, FakeContext(), data_dir)
        checks.check_true("returns None for no user", result is None)


run_test("normalize_message no user", test_normalize_message_no_user())


# ---------------------------------------------------------------------------
# Frozen dataclass enforcement
# ---------------------------------------------------------------------------

def test_inbound_attachment_frozen():
    att = InboundAttachment(
        path=Path("/tmp/test.jpg"),
        original_name="test.jpg",
        is_image=True,
        mime_type="image/jpeg",
    )
    checks.check("path", att.path, Path("/tmp/test.jpg"))
    checks.check("original_name", att.original_name, "test.jpg")
    checks.check("is_image", att.is_image, True)
    checks.check("mime_type", att.mime_type, "image/jpeg")

    try:
        att.path = Path("/other")
        checks.check_true("should be frozen", False)
    except (AttributeError, TypeError, Exception):
        checks.check_true("frozen raises on mutation", True)


run_test("InboundAttachment frozen", test_inbound_attachment_frozen)


def test_inbound_user_frozen():
    u = InboundUser(id=42, username="test")
    try:
        u.id = 99
        checks.check_true("should be frozen", False)
    except (AttributeError, TypeError, Exception):
        checks.check_true("frozen raises on mutation", True)


run_test("InboundUser frozen", test_inbound_user_frozen)


def test_command_args_are_tuple():
    """InboundCommand.args is a tuple, not a mutable list."""
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/help a b")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext(args=["a", "b"])

    result = normalize_command(upd, ctx)
    checks.check_true("args is tuple", isinstance(result.args, tuple))

    try:
        result.args.append("c")
        checks.check_true("args should be immutable", False)
    except AttributeError:
        checks.check_true("args is immutable", True)


run_test("command args are tuple", test_command_args_are_tuple)


async def test_message_attachments_are_tuple():
    """InboundMessage.attachments is a tuple, not a mutable list."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "uploads").mkdir()
        chat = FakeChat(1)
        user = FakeUser(1)
        msg = FakeMessage(chat=chat, text="hi")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        result = await normalize_message(upd, FakeContext(), data_dir)
        checks.check_true("attachments is tuple", isinstance(result.attachments, tuple))

        try:
            result.attachments.append("x")
            checks.check_true("attachments should be immutable", False)
        except AttributeError:
            checks.check_true("attachments is immutable", True)


run_test("message attachments are tuple", test_message_attachments_are_tuple())


def test_command_default_args_are_tuple():
    """Default args on InboundCommand is an empty tuple, not a mutable list."""
    cmd = InboundCommand(user=InboundUser(id=1), chat_id=1, command="start")
    checks.check_true("default args is tuple", isinstance(cmd.args, tuple))
    checks.check("default args empty", cmd.args, ())


run_test("command default args are tuple", test_command_default_args_are_tuple)


def test_message_default_attachments_are_tuple():
    """Default attachments on InboundMessage is an empty tuple, not a mutable list."""
    msg = InboundMessage(user=InboundUser(id=1), chat_id=1, text="hi")
    checks.check_true("default attachments is tuple", isinstance(msg.attachments, tuple))
    checks.check("default attachments empty", msg.attachments, ())


run_test("default attachments are tuple", test_message_default_attachments_are_tuple)


# ---------------------------------------------------------------------------
# Handler integration: normalization feeds real handlers correctly
# ---------------------------------------------------------------------------

async def test_handlers_receive_normalized_user():
    """Verify that handlers receive InboundUser through normalization, not raw Telegram objects."""
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        original_is_allowed = th.is_allowed
        received_users = []

        def tracking_is_allowed(user):
            received_users.append(user)
            return original_is_allowed(user)

        th.is_allowed = tracking_is_allowed
        try:
            chat = FakeChat(12345)
            user = FakeUser(42)
            msg = FakeMessage(chat=chat, text="/session")
            upd = FakeUpdate(message=msg, user=user, chat=chat)
            await th.cmd_session(upd, FakeContext())

            checks.check_true("is_allowed received InboundUser",
                              isinstance(received_users[0], InboundUser))
            checks.check("received correct user id", received_users[0].id, 42)
        finally:
            th.is_allowed = original_is_allowed


run_test("handlers receive normalized user", test_handlers_receive_normalized_user())


async def test_callback_handler_uses_normalized_data():
    """Verify callback handlers use event.data not query.data for routing."""
    from app.storage import save_session, default_session
    import app.telegram_handlers as th
    import time

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "on")
        session["pending_request"] = {
            "request_user_id": 42,
            "prompt": "test prompt",
            "image_paths": [],
            "attachment_dicts": [],
            "context_hash": "",
            "created_at": time.time(),
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="plan text")
        query = FakeCallbackQuery(data="approval_reject", message=msg)
        upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

        await th.handle_callback(upd, FakeContext())

        from tests.support.handler_support import load_session_disk
        saved = load_session_disk(data_dir, 12345, prov)
        checks.check_true("pending cleared after reject",
                          saved.get("pending_request") is None)


run_test("callback handler uses normalized data", test_callback_handler_uses_normalized_data())


async def test_command_normalization_strips_bot_mention():
    """Verify /command@botname still works through normalization."""
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/session@mybotname")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.cmd_session(upd, FakeContext())

        checks.check_true("replied", len(msg.replies) > 0)
        reply_text = msg.replies[-1].get("text", "")
        checks.check_in("session info returned", "Provider:", reply_text)


run_test("command normalization strips bot mention", test_command_normalization_strips_bot_mention())


# ---------------------------------------------------------------------------
# No-user safety: handlers receiving updates with no effective_user
# ---------------------------------------------------------------------------

async def test_command_handler_no_user_no_crash():
    """A command handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/session")
        upd = FakeUpdate(message=msg, user=None, chat=chat)
        upd.effective_user = None

        await th.cmd_session(upd, FakeContext())
        checks.check("no replies for no-user", len(msg.replies), 0)


run_test("command handler no user no crash", test_command_handler_no_user_no_crash())


async def test_message_handler_no_user_no_crash():
    """The message handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="hello")
        upd = FakeUpdate(message=msg, user=None, chat=chat)
        upd.effective_user = None

        await th.handle_message(upd, FakeContext())
        checks.check("no provider calls", len(prov.run_calls), 0)


run_test("message handler no user no crash", test_message_handler_no_user_no_crash())


async def test_callback_handler_no_user_no_crash():
    """A callback handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery(data="approval_approve", message=msg)
        upd = FakeUpdate(message=msg, user=None, chat=chat, callback_query=query)
        upd.effective_user = None

        await th.handle_callback(upd, FakeContext())
        checks.check("no provider calls", len(prov.run_calls), 0)


run_test("callback handler no user no crash", test_callback_handler_no_user_no_crash())


# ---------------------------------------------------------------------------
# handle_message uses normalize_message (behavioral, not source-inspection)
# ---------------------------------------------------------------------------

async def test_handle_message_empty_content_skipped():
    """handle_message silently returns when the message has no text and no attachments.

    This proves the empty-content decision from normalize_message() is the one
    that governs the runtime path (normalize_message returns None, handler exits).
    """
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat)
        msg.text = None
        msg.caption = None
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())
        checks.check("no provider calls for empty message", len(prov.run_calls), 0)


run_test("handle_message empty content skipped", test_handle_message_empty_content_skipped())


async def test_handle_message_caption_reaches_provider():
    """handle_message sends caption text to the provider when message.text is None.

    This proves the caption fallback in normalize_message() governs the runtime path.
    """
    from app.providers.base import RunResult
    import app.telegram_handlers as th

    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat)
        msg.text = None
        msg.caption = "describe this image"
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())
        checks.check("provider called once", len(prov.run_calls), 1)
        checks.check_in("prompt has caption text", "describe this image",
                         prov.run_calls[0]["prompt"])


run_test("handle_message caption reaches provider", test_handle_message_caption_reaches_provider())


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    checks.run_async_and_exit()
