"""Shared fakes and helpers for handler integration tests."""

import contextlib
import tempfile
from pathlib import Path

import app.telegram_handlers as _th
from app.providers.base import RunResult
from app.ratelimit import RateLimiter
from app.storage import close_db, ensure_data_dirs, load_session
from tests.support.config_support import make_config as _make_config


@contextlib.contextmanager
def test_data_dir():
    """TemporaryDirectory + ensure_data_dirs + close_db on exit.

    Closes the SQLite connection BEFORE the temp dir is deleted,
    preventing WAL checkpoint hangs on deleted files.
    """
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        try:
            yield data_dir
        finally:
            close_db(data_dir)


@contextlib.contextmanager
def test_env(*, config_overrides=None, provider_name="claude", boot_id="test-boot"):
    """Context manager that sets up a temp data_dir, config, provider, globals,
    and tears down the DB connection on exit.  Yields (data_dir, cfg, prov)."""
    with test_data_dir() as data_dir:
        prov = FakeProvider(provider_name)
        overrides = dict(working_dir=data_dir)
        if config_overrides:
            overrides.update(config_overrides)
        cfg = make_config(data_dir, **overrides)
        setup_globals(cfg, prov, boot_id=boot_id)
        yield data_dir, cfg, prov


class FakeChat:
    def __init__(self, chat_id=12345):
        self.id = chat_id
        self.sent_messages = []

    async def send_action(self, action):
        pass

    async def send_message(self, text=None, **kwargs):
        self.sent_messages.append({"text": text, **kwargs})
        return FakeMessage(chat=self, text=text)


class FakeMessage:
    def __init__(self, chat=None, text=None, user=None):
        self.chat = chat or FakeChat()
        self.text = text
        self.caption = None
        self.photo = None
        self.document = None
        self.replies = []
        self.deleted = False
        self._user = user

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return FakeMessage(chat=self.chat, text=text)

    async def delete(self):
        self.deleted = True

    async def edit_text(self, text, **kwargs):
        self.replies.append({"edit_text": text, **kwargs})

    async def reply_photo(self, **kwargs):
        self.replies.append({"photo": True, **kwargs})

    async def reply_document(self, **kwargs):
        self.replies.append({"document": True, **kwargs})

    async def edit_message_reply_markup(self, **kwargs):
        self.replies.append({"edit_reply_markup": True, **kwargs})


class FakeUser:
    def __init__(self, uid=42, username="testuser"):
        self.id = uid
        self.username = username


class FakeUpdate:
    def __init__(self, message=None, user=None, chat=None, callback_query=None):
        self.effective_user = user or FakeUser()
        self.effective_chat = chat or (message.chat if message else FakeChat())
        self.effective_message = message or FakeMessage(chat=self.effective_chat, user=self.effective_user)
        self.callback_query = callback_query


class FakeCallbackQuery:
    def __init__(self, data, message=None, user=None):
        self.data = data
        self.message = message or FakeMessage()
        self._user = user
        self.answers = []

    @property
    def answered(self):
        return len(self.answers) > 0

    @property
    def answer_text(self):
        return self.answers[-1]["text"] if self.answers else None

    @property
    def answer_show_alert(self):
        return self.answers[-1]["show_alert"] if self.answers else False

    async def answer(self, text=None, show_alert=False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.message.replies.append({"edit_reply_markup": True, "reply_markup": reply_markup})

    async def edit_message_text(self, text, **kwargs):
        self.message.replies.append({"edit_text": text, **kwargs})


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []


class FakeProvider:
    def __init__(self, name="claude"):
        self.name = name
        self.run_calls = []
        self.preflight_calls = []
        self.run_results = []
        self.preflight_results = []
        self._health_errors = []

    def new_provider_state(self):
        if self.name == "codex":
            return {"thread_id": None}
        return {"session_id": "test-session-id", "started": False}

    async def run(self, provider_state, prompt, image_paths, progress, context=None):
        self.run_calls.append({
            "provider_state": dict(provider_state),
            "prompt": prompt,
            "image_paths": image_paths,
            "context": context,
        })
        if self.run_results:
            return self.run_results.pop(0)
        return RunResult(text="default response")

    async def run_preflight(self, prompt, image_paths, progress, context=None):
        self.preflight_calls.append({
            "prompt": prompt,
            "image_paths": image_paths,
            "context": context,
        })
        if self.preflight_results:
            return self.preflight_results.pop(0)
        return RunResult(text="plan: read files")

    def check_health(self):
        return list(self._health_errors)

    async def check_runtime_health(self):
        return []


def make_config(data_dir, **overrides):
    defaults = dict(
        data_dir=Path(data_dir),
        telegram_token="1234567890:AABBCCDDEEFFaabbccddeeff_01234567",
        approval_mode="off",
        stream_update_interval_seconds=0.0,
        typing_interval_seconds=60.0,
    )
    defaults.update(overrides)
    return _make_config(**defaults)


def setup_globals(config, provider, *, boot_id="test-boot"):
    _th._config = config
    _th._provider = provider
    _th._boot_id = boot_id
    _th._rate_limiter = RateLimiter(
        per_minute=config.rate_limit_per_minute,
        per_hour=config.rate_limit_per_hour,
    )
    _th.CHAT_LOCKS.clear()


def load_session_disk(data_dir, chat_id, provider):
    return load_session(data_dir, chat_id, provider.name, provider.new_provider_state, "off")


async def send_command(handler, chat, user, text, args=None):
    msg = FakeMessage(chat=chat, text=text)
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    await handler(upd, FakeContext(args=args or []))
    return msg


async def send_callback(handler, chat, user, data):
    """Fire a callback handler, return (query, message) for assertion."""
    msg = FakeMessage(chat=chat)
    query = FakeCallbackQuery(data, message=msg, user=user)
    upd = FakeUpdate(user=user, chat=chat, callback_query=query)
    await handler(upd, FakeContext())
    return query, msg


async def send_text(chat, user, text):
    msg = FakeMessage(chat=chat, text=text)
    upd = FakeUpdate(message=msg, user=user, chat=chat)
    await _th.handle_message(upd, FakeContext())
    return msg


def last_reply(msg):
    if not msg.replies:
        return ""
    reply = msg.replies[-1]
    return reply.get("text", reply.get("edit_text", ""))


def has_markup_removal(msg_or_replies):
    """Check if any reply entry is an edit_reply_markup with reply_markup=None."""
    replies = msg_or_replies if isinstance(msg_or_replies, list) else msg_or_replies.replies
    return any(r.get("edit_reply_markup") and r.get("reply_markup") is None for r in replies)


def get_callback_data_values(reply):
    """Extract callback_data strings from a reply_markup InlineKeyboardMarkup."""
    markup = reply.get("reply_markup")
    if markup is None:
        return []
    # InlineKeyboardMarkup.inline_keyboard is a list of rows (lists of buttons)
    values = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                values.append(btn.callback_data)
    return values


def last_run_call(provider):
    return provider.run_calls[-1] if provider.run_calls else None


def last_run_context(provider):
    call = last_run_call(provider)
    return call["context"] if call else None


def make_skill(custom_dir, name, *, body, requires=None):
    d = custom_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "skill.md").write_text(
        f"---\nname: {name}\ndisplay_name: {name}\n"
        f"description: test fixture\n---\n\n{body}\n"
    )
    if requires:
        lines = ["credentials:"]
        for requirement in requires:
            lines.append(f'  - key: {requirement["key"]}')
            lines.append(
                f'    prompt: "{requirement.get("prompt", "enter " + requirement["key"])}"'
            )
            if "help_url" in requirement:
                lines.append(f'    help_url: {requirement["help_url"]}')
        (d / "requires.yaml").write_text("\n".join(lines) + "\n")
    return d


def make_store_skill(store_dir, name, *, body):
    d = store_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "skill.md").write_text(
        f"---\nname: {name}\ndisplay_name: {name}\n"
        f"description: test fixture\n---\n\n{body}\n"
    )
    return d
