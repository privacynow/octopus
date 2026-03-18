"""Shared fakes and helpers for handler integration tests.

Worker-owned test model (authoritative):
- Handler-only: handle_message() / send_text() only; assert no provider run, dedup/busy/rejection.
- Single execution: handle_message() then await drain_one_worker_item(data_dir); assert prov.run_calls, session, current_bot_instance().sent_messages.
- Real concurrency: async with running_worker(data_dir): admit via handle_message(), use provider gates, /cancel; assert on bot-side log.
"""

import asyncio
import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.agents.delivery import build_registry_delivery_runtime
import app.channels.telegram.routing as _th
from app.channels.telegram.state import TelegramRuntime, build_telegram_runtime
from app.content_models import RuntimeSkillTrackRecord, SkillRevisionRecord
from app.providers.base import RunResult
from app.storage import close_db, ensure_data_dirs, load_session
from app import work_queue as _work_queue
from tests.support.config_support import make_config as _make_config


_TEST_RUNTIME: TelegramRuntime | None = None


def current_runtime() -> TelegramRuntime:
    if _TEST_RUNTIME is None:
        raise RuntimeError("Telegram test runtime is not configured")
    return _TEST_RUNTIME


def reset_handler_test_runtime() -> None:
    """Clear all handler-related module globals and DB caches for test isolation.

    Call before/after tests so no state leaks between cases. Required for
    parallel-safe handler tests (Priority 4).
    Phase 13: reset backend first so session_store()/transport_store() are valid.
    """
    import app.runtime_backend as _rb
    _rb.reset_for_test()
    import app.content_store as _cs
    _cs.reset_for_test()
    import app.credential_store as _creds
    _creds.reset_for_test()

    global _TEST_RUNTIME
    if _TEST_RUNTIME is not None:
        _TEST_RUNTIME.pending_work_items.clear()
        _TEST_RUNTIME.chat_locks.clear()
        _TEST_RUNTIME.cancellation_registry.clear()
        _TEST_RUNTIME.bot_instance = None
        try:
            _TEST_RUNTIME.current_update_id.set(None)
        except LookupError:
            pass
    _TEST_RUNTIME = None
    global _next_update_id
    _next_update_id = 0
    # Backend lifecycle is owned by runtime_backend.reset_for_test() above; no duplicate close.


@contextlib.contextmanager
def fresh_data_dir():
    """TemporaryDirectory + ensure_data_dirs + close both DBs on exit.

    Closes session and transport SQLite connections BEFORE the temp dir is
    deleted, preventing WAL checkpoint hangs on deleted files.
    """
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        try:
            yield data_dir
        finally:
            close_db(data_dir)
            _work_queue.close_transport_db(data_dir)


def public_user_config_overrides(**extra):
    """Default config overrides for tests that need a public (non-trusted) user.

    Returns allow_open=True and allowed_user_ids=frozenset({42}) so that
    uid 42 is trusted and any other uid (e.g. 999) is public. Merge with
    test-specific overrides, e.g. public_model_profiles=frozenset({\"fast\"}).
    """
    return {"allow_open": True, "allowed_user_ids": frozenset({42}), **extra}


@contextlib.contextmanager
def fresh_env(*, config_overrides=None, provider_name="claude", boot_id="test-boot", bot_instance=None):
    """Context manager that sets up a temp data_dir, config, provider, globals,
    and tears down the DB connection on exit.  Yields (data_dir, cfg, prov)."""
    with fresh_data_dir() as data_dir:
        prov = FakeProvider(provider_name)
        overrides = dict(working_dir=data_dir)
        if config_overrides:
            overrides.update(config_overrides)
        cfg = make_config(data_dir, **overrides)
        setup_globals(cfg, prov, boot_id=boot_id, bot_instance=bot_instance)
        try:
            yield data_dir, cfg, prov
        finally:
            reset_handler_test_runtime()


class FakeProgress:
    """Test double for TelegramProgress that matches production shape.

    Mirrors all public attributes that production code reads:
    - last_text: last HTML text passed to update()
    - last_update: monotonic time of last update() call
    - content_started: asyncio.Event set by providers on first real text
    - _content_delivered: tracks whether first post-content update landed
    - updates: list of all HTML texts passed to update() (test-only)

    Models the same rate-limiting behaviour as TelegramProgress so tests
    catch suppression bugs (e.g. first content update dropped after a
    forced tool status edit).
    """
    def __init__(self, *, interval: float = 0.0):
        import asyncio
        import time as _time
        self.updates: list[str] = []
        self.last_text: str = ""
        self.last_update: float = 0.0
        self.content_started: asyncio.Event = asyncio.Event()
        self._content_delivered: bool = False
        self._interval: float = interval
        self._time = _time

    async def update(self, html_text: str, *, force: bool = False) -> None:
        if not html_text or html_text == self.last_text:
            return
        now = self._time.monotonic()
        # Mirror production: first non-forced update after content_started
        # bypasses rate limiting so the user sees real reply text.
        cs = self.content_started
        if not force and not self._content_delivered and cs and cs.is_set():
            force = True
        if not force and now - self.last_update < self._interval:
            return
        self.updates.append(html_text)
        self.last_text = html_text
        self.last_update = now
        if cs and cs.is_set():
            self._content_delivered = True


class FakeChat:
    def __init__(self, chat_id=12345):
        self.id = chat_id
        self.sent_messages = []

    async def send_action(self, action):
        pass

    async def send_message(self, text=None, **kwargs):
        self.sent_messages.append({"text": text, **kwargs})
        _append_simulator_output_log("send", text or "")
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
        _append_simulator_output_log("reply", text)
        return FakeMessage(chat=self.chat, text=text)

    async def delete(self):
        self.deleted = True

    async def edit_text(self, text, **kwargs):
        self.replies.append({"edit_text": text, **kwargs})
        _append_simulator_output_log("edit", text)

    async def reply_photo(self, **kwargs):
        self.replies.append({"photo": True, **kwargs})
        _append_simulator_output_log("reply", kwargs.get("caption") or "[photo]")

    async def reply_document(self, **kwargs):
        self.replies.append({"document": True, **kwargs})
        _append_simulator_output_log("reply", kwargs.get("caption") or "[document]")

    async def edit_message_reply_markup(self, **kwargs):
        self.replies.append({"edit_reply_markup": True, **kwargs})


class FakeUser:
    def __init__(self, uid=42, username="testuser"):
        self.id = uid
        self.username = username


_next_update_id = 0

class FakeUpdate:
    def __init__(self, message=None, user=None, chat=None, callback_query=None):
        global _next_update_id
        _next_update_id += 1
        self.update_id = _next_update_id
        self.effective_user = user or FakeUser()
        self.effective_chat = chat or (message.chat if message else FakeChat())
        self.effective_message = message or FakeMessage(chat=self.effective_chat, user=self.effective_user)
        self.message = message  # PTB CommandHandler/MessageHandler check update.message
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
        _append_simulator_output_log("answer", text or "[answer]")

    async def edit_message_reply_markup(self, reply_markup=None):
        self.message.replies.append({"edit_reply_markup": True, "reply_markup": reply_markup})
        # Markup-only edits are not appended to the simulator output log (user-visible log is text-only for callbacks).

    async def edit_message_text(self, text, **kwargs):
        self.message.replies.append({"edit_text": text, **kwargs})
        _append_simulator_output_log("edit", text)


class FakeContext:
    def __init__(self, args=None, runtime: TelegramRuntime | None = None):
        self.args = args or []
        telegram_runtime = runtime
        try:
            if telegram_runtime is None:
                telegram_runtime = current_runtime()
        except RuntimeError:
            telegram_runtime = None
        self.telegram_runtime = telegram_runtime
        if telegram_runtime is not None:
            self.application = SimpleNamespace(
                bot=telegram_runtime.bot_instance,
                bot_data={
                    "telegram_runtime": telegram_runtime,
                    "telegram_boot_id": telegram_runtime.boot_id,
                },
            )
        else:
            self.application = SimpleNamespace(bot=None, bot_data={})


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

    async def run(self, provider_state, prompt, image_paths, progress, context=None, cancel=None):
        self.run_calls.append({
            "provider_state": dict(provider_state),
            "prompt": prompt,
            "image_paths": image_paths,
            "context": context,
        })
        # Exercise the progress path so tests catch broken status messages
        await progress.update("working…", force=True)
        if self.run_results:
            return self.run_results.pop(0)
        return RunResult(text="default response")

    async def run_preflight(self, prompt, image_paths, progress, context=None, cancel=None):
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
        telegram_token="0:test_token_not_real",
        approval_mode="off",
        stream_update_interval_seconds=0.0,
        typing_interval_seconds=60.0,
        # Default test users are trusted — covers UIDs commonly used in tests.
        # Excludes 999 (test-stranger used for unauthorized user tests).
        allowed_user_ids=frozenset({1, 2, 3, 42, 50, 99, 100, 200}),
    )
    defaults.update(overrides)
    return _make_config(**defaults)


def set_bot_instance(bot_instance) -> None:
    """Set the handler's bot instance (for worker_dispatch etc.)."""
    current_runtime().bot_instance = bot_instance


def set_provider(provider) -> None:
    """Set the current provider on the installed Telegram channel state."""
    current_runtime().provider = provider


def current_bot_instance():
    try:
        return current_runtime().bot_instance
    except RuntimeError:
        return None


def current_boot_id() -> str:
    return current_runtime().boot_id


def make_registry_delivery_runtime(config, provider, *, bot_instance=None):
    bot = current_bot_instance() if bot_instance is None else bot_instance
    return build_registry_delivery_runtime(
        provider_name=provider.name,
        provider_state_factory=provider.new_provider_state,
        bot=bot,
    )


def live_cancel_registry():
    return current_runtime().cancellation_registry


def _append_simulator_output_log(kind: str, text: str) -> None:
    """When the bot has _output_log (simulator), append one user-visible output for a single ordered stream."""
    try:
        bot = current_runtime().bot_instance
    except RuntimeError:
        bot = None
    if bot is not None and getattr(bot, "_output_log", None) is not None:
        bot._output_log.append({"type": kind, "text": text})


class _MinimalFakeSentMessage:
    """Fake message returned by MinimalFakeBot.send_message. Edits append to bot.sent_messages in order."""

    def __init__(self, bot: "MinimalFakeBot", chat_id: int):
        self._bot = bot
        self._chat_id = chat_id

    async def edit_text(self, text, **kwargs):
        self._bot.sent_messages.append({"edit_text": text, **kwargs})
        _append_simulator_output_log("edit", text)

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        self._bot.sent_messages.append({"edit_reply_markup": True, "reply_markup": reply_markup, **kwargs})

    async def reply_text(self, text, **kwargs):
        return await self._bot.send_message(self._chat_id, text, **kwargs)


class MinimalFakeBot:
    """Minimal bot for worker_dispatch. send_message + edit_text/edit_reply_markup all append to sent_messages in order.

    When _output_log is set (e.g. by ConversationSimulator), sends and edits also append there
    so one ordered user-visible output stream is available for tests.
    """

    def __init__(self):
        self.sent_messages = []
        self._output_log = None  # Set by ConversationSimulator for single ordered log

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        _append_simulator_output_log("send", text)
        return _MinimalFakeSentMessage(self, chat_id)

    async def edit_message_text(self, *, chat_id, message_id, text, **kwargs):
        self.sent_messages.append(
            {"chat_id": chat_id, "message_id": message_id, "edit_text": text, **kwargs}
        )
        _append_simulator_output_log("edit", text)

    async def edit_message_reply_markup(self, *, chat_id, message_id, reply_markup=None, **kwargs):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "edit_reply_markup": True,
                "reply_markup": reply_markup,
                **kwargs,
            }
        )

    async def send_chat_action(self, chat_id, action):
        pass

    async def send_document(self, chat_id, document, **kwargs):
        self.sent_messages.append({"chat_id": chat_id, "document": document, **kwargs})
        _append_simulator_output_log("send", kwargs.get("caption") or "[document]")
        return _MinimalFakeSentMessage(self, chat_id)

    async def send_photo(self, chat_id, photo, **kwargs):
        self.sent_messages.append({"chat_id": chat_id, "photo": photo, **kwargs})
        _append_simulator_output_log("send", kwargs.get("caption") or "[photo]")
        return _MinimalFakeSentMessage(self, chat_id)


def setup_globals(config, provider, *, boot_id="test-boot", bot_instance=None):
    """Install explicit Telegram channel state for tests."""
    reset_handler_test_runtime()
    global _TEST_RUNTIME
    import app.content_store as _cs
    import app.credential_store as _creds
    from app.content_seed import track_from_skill_dir
    from tests.support import skill_test_helpers as _skills_mod

    _cs.init_content_store_for_config(config)
    _creds.init_credential_store_for_config(config)
    custom_dir = getattr(_skills_mod, "CUSTOM_DIR", None)
    if isinstance(custom_dir, Path) and custom_dir.is_dir():
        store = _cs.get_content_store()
        for skill_dir in sorted(custom_dir.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "skill.md").is_file():
                store.replace_skill_track(
                    track_from_skill_dir(
                        skill_dir,
                        source_kind="custom",
                        source_uri=f"test-custom/{skill_dir.name}",
                        owner_actor="test",
                        visibility="private",
                        is_mutable=True,
                        version_label="draft",
                        created_by="test",
                    )
                )
    _TEST_RUNTIME = build_telegram_runtime(
        config,
        provider,
        boot_id=boot_id,
        bot_instance=bot_instance if bot_instance is not None else MinimalFakeBot(),
    )


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


async def drain_one_worker_item(data_dir: Path) -> bool:
    """Claim and dispatch one work item via the real worker path (for integration tests).

    Use after send_text when the test needs the provider to run. Returns True if
    an item was drained, False if queue was empty.
    """
    from app.runtime.inbound_types import deserialize_inbound
    from app.workflows.recovery.results import TransportStateCorruption

    runtime = current_runtime()
    boot_id = runtime.boot_id
    item = _work_queue.claim_next_any(data_dir, boot_id)
    if item is None:
        return False
    item_id = item["id"]
    kind = item.get("kind", "message")
    payload = item.get("payload", "{}")
    try:
        event = deserialize_inbound(kind, payload)
    except Exception:
        _work_queue.fail_work_item(data_dir, item_id, error="deserialize_error")
        return True
    try:
        await _th.worker_dispatch(kind, event, item, runtime=runtime)
        _work_queue.complete_work_item(data_dir, item_id)
    except _work_queue.PendingRecovery:
        pass
    except _work_queue.LeaveClaimed:
        pass
    except TransportStateCorruption:
        raise
    except Exception:
        _work_queue.fail_work_item(data_dir, item_id, error="drain_exception")
    return True


@contextlib.asynccontextmanager
async def running_worker(data_dir: Path, *, poll_interval: float = 0.01):
    """Start the real worker loop in the background; stop cleanly on exit.

    Use for tests that need real concurrency (cancel while run active, busy while run active).
    Yields (task, stop_event). Worker uses explicit runtime-bound dispatch.
    """
    from app.worker import start_worker_task

    runtime = current_runtime()

    async def _dispatch(kind: str, event, item: dict) -> None:
        await _th.worker_dispatch(kind, event, item, runtime=runtime)

    task, stop_event = start_worker_task(
        data_dir,
        runtime.boot_id,
        _dispatch,
        poll_interval=poll_interval,
    )
    try:
        yield task, stop_event
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def bot_texts(bot) -> list[str]:
    """All text from bot.sent_messages: send text and edit_text in order."""
    out = []
    for m in getattr(bot, "sent_messages", []):
        t = m.get("text") or m.get("edit_text")
        if t:
            out.append(t)
    return out


def last_bot_text(bot, default: str = "") -> str:
    """Last text in bot.sent_messages (send or edit)."""
    texts = bot_texts(bot)
    return texts[-1] if texts else default


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


def seed_runtime_skill(
    name,
    *,
    body,
    requires=None,
    source_kind="custom",
    description="test fixture",
    owner_actor="test",
):
    import app.content_store as _cs

    requirement_rows = []
    for requirement in requires or []:
        requirement_rows.append(
            {
                "key": requirement["key"],
                "prompt": requirement.get("prompt", f'enter {requirement["key"]}'),
                "help_url": requirement.get("help_url"),
                "validate": requirement.get("validate"),
            }
        )
    track = RuntimeSkillTrackRecord(
        slug=name,
        display_name=name,
        description=description,
        source_kind=source_kind,
        source_uri=f"test-{source_kind}/{name}",
        owner_actor=owner_actor if source_kind == "custom" else "",
        visibility="private" if source_kind == "custom" else "shared",
        is_mutable=(source_kind == "custom"),
        revision=SkillRevisionRecord(
            instruction_body=body,
            requirements=requirement_rows,
            version_label="draft" if source_kind == "custom" else source_kind,
            created_by=owner_actor,
        ),
    )
    _cs.get_content_store().replace_skill_track(track)
    return track
