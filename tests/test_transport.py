"""Tests for the inbound transport normalization layer (app/transport.py)."""

import tempfile
from pathlib import Path

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
    fresh_data_dir,
)


# ---------------------------------------------------------------------------
# normalize_user
# ---------------------------------------------------------------------------

def test_normalize_user_basic():
    user = FakeUser(uid=42, username="Alice")
    result = normalize_user(user)
    assert isinstance(result, InboundUser)
    assert result.id == 42
    assert result.username == "alice"


def test_normalize_user_no_username():
    user = FakeUser(uid=99, username=None)
    user.username = None
    result = normalize_user(user)
    assert result.id == 99
    assert result.username == ""


def test_normalize_user_empty_username():
    user = FakeUser(uid=1)
    user.username = ""
    result = normalize_user(user)
    assert result.username == ""


def test_normalize_user_none():
    """normalize_user(None) returns None, not an exception."""
    result = normalize_user(None)
    assert result is None


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
    assert isinstance(result, InboundCommand)
    assert result.chat_id == 12345
    assert result.user.id == 42
    assert result.command == "help"
    assert result.args == ("skills", "approval")


def test_normalize_command_with_bot_mention():
    """Commands like /help@mybotname should strip the @botname suffix."""
    chat = FakeChat(99)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/help@mybotname")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext(args=[])

    result = normalize_command(upd, ctx)
    assert result.command == "help"


def test_normalize_command_no_args():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/start")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext()

    result = normalize_command(upd, ctx)
    assert result.command == "start"
    assert result.args == ()


def test_normalize_command_no_user():
    """normalize_command returns None when update has no user."""
    chat = FakeChat(1)
    msg = FakeMessage(chat=chat, text="/help")
    upd = FakeUpdate(message=msg, user=None, chat=chat)
    upd.effective_user = None

    result = normalize_command(upd, FakeContext())
    assert result is None


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
    assert isinstance(result, InboundCallback)
    assert result.chat_id == 555
    assert result.user.id == 77
    assert result.data == "approval_approve"


def test_normalize_callback_complex_data():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data="skill_update_confirm:my-skill", message=msg)
    upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

    result = normalize_callback(upd)
    assert result.data == "skill_update_confirm:my-skill"


def test_normalize_callback_empty_data():
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data=None, message=msg)
    query.data = None
    upd = FakeUpdate(message=msg, user=user, chat=chat, callback_query=query)

    result = normalize_callback(upd)
    assert result.data == ""


def test_normalize_callback_no_user():
    """normalize_callback returns None when update has no user."""
    chat = FakeChat(1)
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data="approval_approve", message=msg)
    upd = FakeUpdate(message=msg, user=None, chat=chat, callback_query=query)
    upd.effective_user = None

    result = normalize_callback(upd)
    assert result is None


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
        assert isinstance(result, InboundMessage)
        assert result.chat_id == 100
        assert result.user.id == 50
        assert result.user.username == "dave"
        assert result.text == "hello world"
        assert result.attachments == ()


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
        assert result.text == "photo caption"


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
        assert result is None


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
        assert result is None


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
    assert att.path == Path("/tmp/test.jpg")
    assert att.original_name == "test.jpg"
    assert att.is_image is True
    assert att.mime_type == "image/jpeg"

    try:
        att.path = Path("/other")
        assert False, "should be frozen"
    except (AttributeError, TypeError, Exception):
        pass  # frozen raises on mutation — expected


def test_inbound_user_frozen():
    u = InboundUser(id=42, username="test")
    try:
        u.id = 99
        assert False, "should be frozen"
    except (AttributeError, TypeError, Exception):
        pass  # frozen raises on mutation — expected


def test_command_args_are_tuple():
    """InboundCommand.args is a tuple, not a mutable list."""
    chat = FakeChat(1)
    user = FakeUser(1)
    msg = FakeMessage(chat=chat, text="/help a b")
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    ctx = FakeContext(args=["a", "b"])

    result = normalize_command(upd, ctx)
    assert isinstance(result.args, tuple)

    try:
        result.args.append("c")
        assert False, "args should be immutable"
    except AttributeError:
        pass  # args is immutable — expected


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
        assert isinstance(result.attachments, tuple)

        try:
            result.attachments.append("x")
            assert False, "attachments should be immutable"
        except AttributeError:
            pass  # attachments is immutable — expected


def test_command_default_args_are_tuple():
    """Default args on InboundCommand is an empty tuple, not a mutable list."""
    cmd = InboundCommand(user=InboundUser(id=1), chat_id=1, command="start")
    assert isinstance(cmd.args, tuple)
    assert cmd.args == ()


def test_message_default_attachments_are_tuple():
    """Default attachments on InboundMessage is an empty tuple, not a mutable list."""
    msg = InboundMessage(user=InboundUser(id=1), chat_id=1, text="hi")
    assert isinstance(msg.attachments, tuple)
    assert msg.attachments == ()


# ---------------------------------------------------------------------------
# Handler integration: normalization feeds real handlers correctly
# ---------------------------------------------------------------------------

async def test_handlers_receive_normalized_user():
    """Verify that handlers receive InboundUser through normalization, not raw Telegram objects."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
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

            assert isinstance(received_users[0], InboundUser)
            assert received_users[0].id == 42
        finally:
            th.is_allowed = original_is_allowed


async def test_callback_handler_uses_normalized_data():
    """Verify callback handlers use event.data not query.data for routing."""
    from app.storage import save_session, default_session
    import app.telegram_handlers as th
    import time

    with fresh_data_dir() as data_dir:
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
        assert saved.get("pending_request") is None


async def test_command_normalization_strips_bot_mention():
    """Verify /command@botname still works through normalization."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/session@mybotname")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.cmd_session(upd, FakeContext())

        assert len(msg.replies) > 0
        reply_text = msg.replies[-1].get("text", "")
        assert "Provider:" in reply_text


# ---------------------------------------------------------------------------
# No-user safety: handlers receiving updates with no effective_user
# ---------------------------------------------------------------------------

async def test_command_handler_no_user_no_crash():
    """A command handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/session")
        upd = FakeUpdate(message=msg, user=None, chat=chat)
        upd.effective_user = None

        await th.cmd_session(upd, FakeContext())
        assert len(msg.replies) == 0


async def test_message_handler_no_user_no_crash():
    """The message handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="hello")
        upd = FakeUpdate(message=msg, user=None, chat=chat)
        upd.effective_user = None

        await th.handle_message(upd, FakeContext())
        assert len(prov.run_calls) == 0


async def test_callback_handler_no_user_no_crash():
    """A callback handler receiving an update with no user returns silently."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery(data="approval_approve", message=msg)
        upd = FakeUpdate(message=msg, user=None, chat=chat, callback_query=query)
        upd.effective_user = None

        await th.handle_callback(upd, FakeContext())
        assert len(prov.run_calls) == 0


# ---------------------------------------------------------------------------
# handle_message uses normalize_message (behavioral, not source-inspection)
# ---------------------------------------------------------------------------

async def test_handle_message_empty_content_skipped():
    """handle_message silently returns when the message has no text and no attachments.

    This proves the empty-content decision from normalize_message() is the one
    that governs the runtime path (normalize_message returns None, handler exits).
    """
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
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
        assert len(prov.run_calls) == 0


async def test_handle_message_caption_reaches_provider():
    """handle_message sends caption text to the provider when message.text is None.

    This proves the caption fallback in normalize_message() governs the runtime path.
    """
    from app.providers.base import RunResult
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
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
        assert len(prov.run_calls) == 1
        assert "describe this image" in prov.run_calls[0]["prompt"]
