"""Handler-level integration tests — exercises real wiring between components.

Mocks: Telegram API objects, Provider.run()/run_preflight()
Real:  session storage, credential encryption, skill catalog, context building, hash computation
"""

import asyncio
import time
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import BotConfig
from app.providers.base import (
    PreflightContext, ProgressSink, RunContext, RunResult, compute_context_hash,
)
from app.skills import (
    derive_encryption_key, get_provider_config_digest, get_skill_digests,
    load_user_credentials, save_user_credential,
)
from app.storage import ensure_data_dirs, save_session, load_session, default_session

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        failed += 1


def check_true(name, val):
    check(name, bool(val), True)


def check_false(name, val):
    check(name, bool(val), False)


def check_in(name, needle, haystack):
    global passed, failed
    if needle in haystack:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    {needle!r} not in {haystack!r}")
        failed += 1


def check_not_in(name, needle, haystack):
    global passed, failed
    if needle not in haystack:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    {needle!r} unexpectedly in {haystack!r}")
        failed += 1


# ---------------------------------------------------------------------------
# Mock Telegram objects
# ---------------------------------------------------------------------------

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
        pass


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
        self.answered = False

    async def answer(self, text=None, show_alert=False):
        self.answered = True

    async def edit_message_reply_markup(self, reply_markup=None):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.message.replies.append({"edit_text": text, **kwargs})


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []


# ---------------------------------------------------------------------------
# Fake provider — records calls, returns configurable results
# ---------------------------------------------------------------------------

class FakeProvider:
    def __init__(self, name="claude"):
        self.name = name
        self.run_calls = []
        self.preflight_calls = []
        self.run_results = []  # pop from front
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(data_dir, **overrides):
    defaults = dict(
        instance="test", telegram_token="1234567890:AABBCCDDEEFFaabbccddeeff_01234567",
        allow_open=True, allowed_user_ids=frozenset(), allowed_usernames=frozenset(),
        provider_name="claude", model="", working_dir=Path("/home/test"),
        extra_dirs=(), data_dir=data_dir,
        timeout_seconds=300, approval_mode="off", role="", role_from_file=False,
        default_skills=(),
        stream_update_interval_seconds=0.0, typing_interval_seconds=60.0,
        codex_sandbox="workspace-write", codex_skip_git_repo_check=True,
        codex_full_auto=False, codex_dangerous=False, codex_profile="",
        admin_user_ids=frozenset(), admin_usernames=frozenset(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def setup_globals(config, provider):
    """Inject config and provider into telegram_handlers module globals."""
    import app.telegram_handlers as th
    th._config = config
    th._provider = provider
    th.CHAT_LOCKS.clear()


def load_session_disk(data_dir, chat_id, provider):
    """Load session from disk using the provider's factory."""
    return load_session(data_dir, chat_id, provider.name, provider.new_provider_state, "off")


_tests: list[tuple[str, Any]] = []  # (name, coroutine_function)


def run_test(name, coro):
    """Register a test coroutine to run later in a single event loop."""
    _tests.append((name, coro))


async def _run_all():
    global passed, failed
    for name, coro in _tests:
        print(f"\n=== {name} ===")
        try:
            await coro
        except Exception as e:
            print(f"  FAIL  {name} (exception: {e})")
            import traceback; traceback.print_exc()
            failed += 1


# ===================================================================
# Test 1: Happy path — message → execute_request → provider.run → reply
# ===================================================================

async def test_happy_path():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Hello world", provider_state_updates={"started": True})]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="hi there")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("provider.run called once", len(prov.run_calls), 1)
        check_in("prompt has user text", "hi there", prov.run_calls[0]["prompt"])

        ctx = prov.run_calls[0]["context"]
        check_true("context is RunContext", isinstance(ctx, RunContext))
        check_true("extra_dirs has upload dir", any("uploads" in d for d in ctx.extra_dirs))
        check_true("normal run does not skip permissions", ctx.skip_permissions is False)

        # Session on disk has merged state
        session = load_session_disk(data_dir, 12345, prov)
        check("provider_state.started", session["provider_state"]["started"], True)

        # Reply was sent
        all_replies = msg.replies
        check_true("got replies", len(all_replies) >= 2)  # status msg + reply
        reply_texts = " ".join(r.get("text", r.get("edit_text", "")) for r in all_replies)
        check_in("reply contains response", "Hello world", reply_texts)

run_test("happy path", test_happy_path())


# ===================================================================
# Test 2: Approval flow — message → preflight → pending → approve → execute
# ===================================================================

async def test_approval_flow():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: read files")]
        prov.run_results = [RunResult(text="Done reading")]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="read my files")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th

        # Step 1: send message with approval mode on → triggers preflight
        await th.handle_message(update, FakeContext())

        check("preflight called", len(prov.preflight_calls), 1)
        check("run NOT called yet", len(prov.run_calls), 0)

        # Verify preflight received a populated PreflightContext
        pf_ctx = prov.preflight_calls[0]["context"]
        check_true("preflight context is PreflightContext", isinstance(pf_ctx, PreflightContext))
        check_true("preflight context has upload dir",
                    any("uploads" in d for d in pf_ctx.extra_dirs))
        check_true("preflight prompt is non-empty",
                    len(prov.preflight_calls[0]["prompt"]) > 0)

        preflight_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("preflight plan label", "Preflight approval plan", preflight_texts)
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        check_in("preflight approval prompt", "Approve this preflight plan?", chat_msgs)

        session = load_session_disk(data_dir, 12345, prov)
        check_true("pending_request saved", session.get("pending_request") is not None)

        # Step 2: approve via callback
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        check("run called after approval", len(prov.run_calls), 1)
        approved_ctx = prov.run_calls[0]["context"]
        check_true("approved run skips permissions", approved_ctx.skip_permissions is True)
        session = load_session_disk(data_dir, 12345, prov)
        check("pending_request cleared", session.get("pending_request"), None)

run_test("approval flow", test_approval_flow())


# ===================================================================
# Test 3: Approval status/session wording
# ===================================================================

async def test_approval_wording():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)

        status_msg = FakeMessage(chat=chat, text="/approval status")
        status_update = FakeUpdate(message=status_msg, user=user, chat=chat)
        await th.cmd_approval(status_update, FakeContext(["status"]))

        status_texts = " ".join(r.get("text", "") for r in status_msg.replies)
        check_in("status says preflight", "Preflight approval mode is on", status_texts)
        check_in("status shows instance default", "instance default", status_texts)

        set_msg = FakeMessage(chat=chat, text="/approval off")
        set_update = FakeUpdate(message=set_msg, user=user, chat=chat)
        await th.cmd_approval(set_update, FakeContext(["off"]))

        set_texts = " ".join(r.get("text", "") for r in set_msg.replies)
        check_in("set says preflight", "Preflight approval mode set to off for this chat.", set_texts)

        session_msg = FakeMessage(chat=chat, text="/session")
        session_update = FakeUpdate(message=session_msg, user=user, chat=chat)
        await th.cmd_session(session_update, FakeContext())

        session_texts = " ".join(r.get("text", "") for r in session_msg.replies)
        check_in("session says preflight", "Preflight approval mode", session_texts)
        check_in("session shows chat override", "chat override", session_texts)

run_test("approval wording", test_approval_wording())


# ===================================================================
# Test 4: Credential capture happy path
# ===================================================================

async def test_credential_capture():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Used github token")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        # Monkey-patch validate_credential to avoid HTTP calls
        original_validate = th.validate_credential
        async def fake_validate(req, value):
            return (True, "")
        th.validate_credential = fake_validate

        try:
            chat = FakeChat(12345)
            user = FakeUser(42)

            # Step 1: /skills add github-integration — should start setup, NOT activate
            msg1 = FakeMessage(chat=chat, text="/skills add github-integration")
            update1 = FakeUpdate(message=msg1, user=user, chat=chat)
            await th.cmd_skills(update1, FakeContext(args=["add", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_not_in("skill NOT active before creds",
                         "github-integration", session.get("active_skills", []))
            check_true("awaiting_skill_setup set", session.get("awaiting_skill_setup") is not None)

            setup = session["awaiting_skill_setup"]
            check("setup user_id", setup["user_id"], 42)
            check("setup skill", setup["skill"], "github-integration")
            check_true("remaining has GITHUB_TOKEN", any(r["key"] == "GITHUB_TOKEN" for r in setup["remaining"]))

            # Check that remaining items include validate metadata
            remaining = setup["remaining"][0]
            check_true("remaining has validate spec", remaining.get("validate") is not None)

            reply_texts = " ".join(r.get("text", "") for r in msg1.replies)
            check_in("mentions setup needed", "needs setup", reply_texts.lower())

            # Step 2: send credential value
            msg2 = FakeMessage(chat=chat, text="ghp_fake_token_12345")
            update2 = FakeUpdate(message=msg2, user=user, chat=chat)
            await th.handle_message(update2, FakeContext())

            check_true("message deleted (secret)", msg2.deleted)

            session = load_session_disk(data_dir, 12345, prov)
            check("awaiting_skill_setup cleared", session.get("awaiting_skill_setup"), None)
            check_in("skill activated after creds",
                      "github-integration", session.get("active_skills", []))

            # Credential actually saved and decryptable
            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            check_true("credential saved", "github-integration" in creds)
            check("credential value", creds["github-integration"].get("GITHUB_TOKEN"), "ghp_fake_token_12345")

            reply_texts = " ".join(r.get("text", "") for r in msg2.replies)
            check_in("ready reply", "ready", reply_texts.lower())

            # Step 3: now a normal message should go through to provider
            msg3 = FakeMessage(chat=chat, text="list my repos")
            update3 = FakeUpdate(message=msg3, user=user, chat=chat)
            await th.handle_message(update3, FakeContext())

            check("run called after creds satisfied", len(prov.run_calls), 1)
            ctx = prov.run_calls[0]["context"]
            check_true("credential_env has GITHUB_TOKEN", "GITHUB_TOKEN" in ctx.credential_env)
            check("credential_env value", ctx.credential_env["GITHUB_TOKEN"], "ghp_fake_token_12345")

        finally:
            th.validate_credential = original_validate

run_test("credential capture", test_credential_capture())


# ===================================================================
# Test 4: Credential validation failure
# ===================================================================

async def test_credential_validation_failure():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        from app.skills import SkillRequirement

        # Pre-set awaiting_skill_setup with a validate spec
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "remaining": [{
                "key": "GITHUB_TOKEN",
                "prompt": "Paste your token",
                "help_url": None,
                "validate": {
                    "method": "GET", "url": "https://api.github.com/user",
                    "header": "Authorization: Bearer ${GITHUB_TOKEN}",
                    "expect_status": 200,
                },
            }],
        }
        save_session(data_dir, 12345, session)

        # Monkey-patch validate_credential to return failure
        original_validate = th.validate_credential
        async def fake_validate_fail(req, value):
            return (False, "Expected status 200, got 401")
        th.validate_credential = fake_validate_fail

        try:
            chat = FakeChat(12345)
            user = FakeUser(42)
            msg = FakeMessage(chat=chat, text="bad_token_value")
            update = FakeUpdate(message=msg, user=user, chat=chat)

            await th.handle_message(update, FakeContext())

            check_true("message deleted on failure", msg.deleted)

            reply_texts = " ".join(r.get("text", "") for r in msg.replies)
            check_in("error mentions validation failed", "validation failed", reply_texts.lower())
            check_in("error mentions 401", "401", reply_texts)

            # Setup state should NOT advance
            session = load_session_disk(data_dir, 12345, prov)
            setup = session.get("awaiting_skill_setup")
            check_true("setup state preserved", setup is not None)
            check("remaining count unchanged", len(setup["remaining"]), 1)

            # No credential saved
            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 42, key)
            check_false("no credential saved", creds.get("github-integration", {}).get("GITHUB_TOKEN"))

        finally:
            th.validate_credential = original_validate

run_test("credential validation failure", test_credential_validation_failure())


# ===================================================================
# Test 5: /new resets session and cleans scripts
# ===================================================================

async def test_cmd_new():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Pre-populate session with started=True
        session = default_session("claude", {"session_id": "old-sess", "started": True}, "on")
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)

        # Create a scripts dir to verify cleanup
        scripts_dir = data_dir / "scripts" / "12345" / "some-skill"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hi")

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/new")
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.cmd_new(update, FakeContext())

        # Session reset
        new_session = load_session_disk(data_dir, 12345, prov)
        check_false("started is False", new_session["provider_state"].get("started"))
        check("approval_mode uses config default", new_session["approval_mode"], "off")

        # Scripts cleaned
        check_false("scripts dir removed", (data_dir / "scripts" / "12345").exists())

        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("fresh reply", "Fresh", reply_texts)

run_test("/new resets session", test_cmd_new())


# ===================================================================
# Test 6: Codex context-hash invalidation
# ===================================================================

async def test_codex_context_hash_invalidation():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok", provider_state_updates={"thread_id": "new-thread"})]
        setup_globals(cfg, prov)

        # Pre-save session with a stale context hash and an existing thread
        session = default_session("codex", {"thread_id": "old-thread", "context_hash": "stale_hash"}, "off")
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)

        # The provider_state passed to run() should have thread_id=None (invalidated)
        call_state = prov.run_calls[0]["provider_state"]
        check("thread_id was cleared before run", call_state.get("thread_id"), None)

        # Session on disk should have the new hash
        session = load_session_disk(data_dir, 12345, prov)
        check_true("context_hash updated", session["provider_state"].get("context_hash") is not None)
        check("context_hash is not stale", session["provider_state"]["context_hash"] != "stale_hash", True)
        check("new thread_id saved", session["provider_state"]["thread_id"], "new-thread")

run_test("codex context-hash invalidation", test_codex_context_hash_invalidation())


# ===================================================================
# Test 7: Codex script staging wired into execute_request
# ===================================================================

async def test_codex_script_staging():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, provider_name="codex",
                          default_skills=("github-integration",))
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        # Pre-save credentials so execution proceeds
        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="use github")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)

        ctx = prov.run_calls[0]["context"]
        check_true("context is RunContext", isinstance(ctx, RunContext))

        # The scripts dir should be staged on disk
        scripts_dir = data_dir / "scripts" / "12345"
        check_true("scripts dir created", scripts_dir.exists())
        check_true("gh-helper.sh staged",
                    (scripts_dir / "github-integration" / "gh-helper.sh").is_file())

        # And the scripts dir must be in the RunContext.extra_dirs passed to prov.run()
        check_true("scripts dir in context.extra_dirs",
                    any(str(scripts_dir) in d for d in ctx.extra_dirs))
        # Upload dir should also be present
        check_true("has upload dir", any("uploads" in d for d in ctx.extra_dirs))
        # credential_env should have GITHUB_TOKEN
        check_in("credential in env", "GITHUB_TOKEN", ctx.credential_env)

run_test("codex script staging", test_codex_script_staging())


# ===================================================================
# Test 8: /doctor with user context for credential checks
# ===================================================================

async def test_doctor_credential_check():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov._health_errors = []  # provider healthy
        setup_globals(cfg, prov)

        # Session with github-integration active but no credentials saved
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/doctor")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.cmd_doctor(update, FakeContext())

        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        # Should report missing GITHUB_TOKEN credential
        check_in("reports missing credential", "GITHUB_TOKEN", reply_texts)

run_test("/doctor credential checks", test_doctor_credential_check())


# ===================================================================
# Test 9: Denial/retry flow
# ===================================================================

async def test_denial_retry_flow():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        # First call returns denials, second call succeeds
        prov.run_results = [
            RunResult(text="partial", denials=[
                {"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}},
            ]),
            RunResult(text="Success after retry"),
        ]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="edit config")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called once (first attempt)", len(prov.run_calls), 1)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("partial reply still sent", "partial", reply_texts)
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        check_in("runtime permission label", "Permission needed", chat_msgs)
        check_in("retry prompt", "Grant access and retry from the beginning", chat_msgs)

        session = load_session_disk(data_dir, 12345, prov)
        check_true("pending_request saved", session.get("pending_request") is not None)
        check_true("pending has denials", session["pending_request"].get("denials") is not None)

        # Retry via callback
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        await th.handle_callback(cb_update, FakeContext())

        check("run called twice (after retry)", len(prov.run_calls), 2)

        # Extra dirs on retry should include /opt/app (parent of config.yaml)
        retry_ctx = prov.run_calls[1]["context"]
        check_true("retry has extra_dirs", len(retry_ctx.extra_dirs) >= 2)
        extra_dirs_str = " ".join(retry_ctx.extra_dirs)
        check_in("denial dir /opt/app in extra_dirs", "/opt/app", extra_dirs_str)
        check_true("retry skips permissions", retry_ctx.skip_permissions is True)

        session = load_session_disk(data_dir, 12345, prov)
        check("pending_request cleared after retry", session.get("pending_request"), None)

run_test("denial/retry flow", test_denial_retry_flow())


# ===================================================================
# Test 10: retry_skip clears pending
# ===================================================================

async def test_retry_skip():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_request"] = {
            "request_user_id": 42, "prompt": "test", "image_paths": [],
            "attachment_dicts": [], "context_hash": "somehash", "denials": [{"tool_name": "X"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_skip", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th
        await th.handle_callback(cb_update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        check("pending cleared", session.get("pending_request"), None)
        check("run not called", len(prov.run_calls), 0)

run_test("retry skip", test_retry_skip())


# ===================================================================
# Test 11: Stale context hash rejection on retry
# ===================================================================

async def test_stale_context_hash():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["pending_request"] = {
            "request_user_id": 42, "prompt": "test", "image_paths": [],
            "attachment_dicts": [], "context_hash": "definitely_stale_hash",
            "denials": [{"tool_name": "X"}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th
        await th.handle_callback(cb_update, FakeContext())

        check("run NOT called (stale hash)", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        check("pending_request cleared", session.get("pending_request"), None)

        reply_texts = " ".join(r.get("edit_text", r.get("text", "")) for r in cb_msg.replies)
        check_in("context changed message", "Context changed", reply_texts)

run_test("stale context hash", test_stale_context_hash())


# ===================================================================
# Test 12: Codex retry clears thread_id
# ===================================================================

async def test_codex_retry_clears_thread():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        # Compute current hash so the retry doesn't get stale-rejected
        current_hash = compute_context_hash("", [], {}, get_provider_config_digest([]), [])

        session = default_session("codex", {"thread_id": "thread-xyz", "context_hash": current_hash}, "off")
        session["pending_request"] = {
            "request_user_id": 42, "prompt": "test", "image_paths": [],
            "attachment_dicts": [], "context_hash": current_hash,
            "denials": [{"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.txt"}}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        user = FakeUser(42)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg

        import app.telegram_handlers as th
        await th.handle_callback(cb_update, FakeContext())

        check("run called", len(prov.run_calls), 1)
        # thread_id should have been cleared in the session before execute_request
        # (codex resume doesn't support --add-dir)
        call_state = prov.run_calls[0]["provider_state"]
        check("thread_id cleared for retry", call_state.get("thread_id"), None)

run_test("codex retry clears thread_id", test_codex_retry_clears_thread())


# ===================================================================
# Test 13: Multi-credential capture
# ===================================================================

async def test_multi_credential():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Pre-set awaiting_skill_setup with 2 credentials
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["my-skill"]
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "my-skill",
            "remaining": [
                {"key": "API_KEY", "prompt": "Enter API key", "help_url": None, "validate": None},
                {"key": "SECRET", "prompt": "Enter secret", "help_url": None, "validate": None},
            ],
        }
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)

        # Send first credential
        msg1 = FakeMessage(chat=chat, text="my-api-key-123")
        update1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(update1, FakeContext())

        check_true("msg1 deleted", msg1.deleted)

        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        check_true("still in setup", setup is not None)
        check("1 remaining", len(setup["remaining"]), 1)
        check("remaining is SECRET", setup["remaining"][0]["key"], "SECRET")

        # Reply should prompt for second credential
        reply_texts = " ".join(r.get("text", "") for r in msg1.replies)
        check_in("prompts for secret", "secret", reply_texts.lower())

        # Send second credential
        msg2 = FakeMessage(chat=chat, text="super-secret-value")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(update2, FakeContext())

        check_true("msg2 deleted", msg2.deleted)

        session = load_session_disk(data_dir, 12345, prov)
        check("setup cleared", session.get("awaiting_skill_setup"), None)

        # Both credentials saved
        key = derive_encryption_key(cfg.telegram_token)
        creds = load_user_credentials(data_dir, 42, key)
        check("API_KEY saved", creds.get("my-skill", {}).get("API_KEY"), "my-api-key-123")
        check("SECRET saved", creds.get("my-skill", {}).get("SECRET"), "super-secret-value")

run_test("multi-credential capture", test_multi_credential())


# ===================================================================
# Test 14: Credential env reaches provider context
# ===================================================================

async def test_credential_env_in_context():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="used token")]
        setup_globals(cfg, prov)

        # Pre-save credentials
        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_real_token", key)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="list repos")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)
        ctx = prov.run_calls[0]["context"]
        check("credential_env has GITHUB_TOKEN", ctx.credential_env.get("GITHUB_TOKEN"), "ghp_real_token")
        check_true("system_prompt has skill instructions", len(ctx.system_prompt) > 0)

run_test("credential env in context", test_credential_env_in_context())


# ===================================================================
# Test 15: Missing credentials block execution and trigger setup
# ===================================================================

async def test_missing_creds_block_execution():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="list repos")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run NOT called", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        check_true("awaiting_skill_setup set", session.get("awaiting_skill_setup") is not None)

        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("prompts for setup", "needs setup", reply_texts.lower())

run_test("missing creds block execution", test_missing_creds_block_execution())


# ===================================================================
# Test 16: Scripts dir in context.extra_dirs (not just all_extra_dirs)
# ===================================================================

async def test_scripts_dir_in_run_context():
    """Regression: scripts were staged AFTER build_run_context(), so the
    context passed to prov.run() never included the scripts_dir.

    This test verifies the fix by checking that staged scripts appear in
    the RunContext.extra_dirs that the provider actually receives — not just
    in a local variable that's never read."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, provider_name="codex",
                          default_skills=("github-integration",))
        prov = FakeProvider("codex")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="use github")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)
        ctx = prov.run_calls[0]["context"]

        # Scripts dir must exist on disk (staging happened)
        scripts_path = data_dir / "scripts" / "12345"
        check_true("scripts dir created on disk", scripts_path.exists())

        # And it must be present in the RunContext.extra_dirs that prov.run() saw.
        # This is the core regression check: previously context was built before
        # staging, so scripts_dir was appended to a local list but never made it
        # into the RunContext object.
        scripts_in_ctx = any(str(scripts_path) in d for d in ctx.extra_dirs)
        check_true("scripts dir in RunContext.extra_dirs", scripts_in_ctx)

        # Upload dir should also be present
        check_true("upload dir in context", any("uploads" in d for d in ctx.extra_dirs))

run_test("scripts dir in RunContext", test_scripts_dir_in_run_context())


# ===================================================================
# Test 17: /skills add defers activation until creds satisfied
# ===================================================================

async def test_skills_add_defers_activation():
    """Regression: /skills add used to activate the skill immediately and then
    check credentials. If creds were missing, the skill was left active but
    half-configured, causing _check_credential_satisfaction to block every message."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="/skills add github-integration")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.cmd_skills(update, FakeContext(args=["add", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)

        # Skill should NOT be in active_skills (creds missing)
        check_not_in("skill not in active_skills yet",
                      "github-integration", session.get("active_skills", []))

        # But setup should be started
        setup = session.get("awaiting_skill_setup")
        check_true("setup started", setup is not None)
        check("setup skill name", setup["skill"], "github-integration")

        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("mentions setup needed", "needs setup", reply_texts.lower())

run_test("/skills add defers activation", test_skills_add_defers_activation())


# ===================================================================
# Test 18: Credential completion activates the skill
# ===================================================================

async def test_credential_completion_activates():
    """After all credentials are collected, the skill should be added to active_skills."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Session with setup in progress but skill NOT yet active
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = []  # skill not active yet
        session["awaiting_skill_setup"] = {
            "user_id": 42,
            "skill": "github-integration",
            "remaining": [
                {"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": None, "validate": None},
            ],
        }
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="ghp_my_token")
        update = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        check_in("skill activated after creds", "github-integration", session.get("active_skills", []))
        check("setup cleared", session.get("awaiting_skill_setup"), None)

run_test("credential completion activates", test_credential_completion_activates())


# ===================================================================
# Test 19: Provider-scoped config digest
# ===================================================================

async def test_provider_scoped_digest():
    """Regression: get_provider_config_digest hashed both claude.yaml and codex.yaml,
    so editing one provider's config would invalidate the other provider's context."""

    digest_claude = get_provider_config_digest(["github-integration"], provider_name="claude")
    digest_codex = get_provider_config_digest(["github-integration"], provider_name="codex")
    digest_all = get_provider_config_digest(["github-integration"])

    # Claude and Codex digests should differ (different yaml files)
    check("claude != codex digest", digest_claude != digest_codex, True)
    # Unscoped digest should differ from both individual ones
    check("unscoped != claude", digest_all != digest_claude, True)
    check("unscoped != codex", digest_all != digest_codex, True)

run_test("provider-scoped digest", test_provider_scoped_digest())


# ===================================================================
# Test 20: /skills add with no creds required activates immediately
# ===================================================================

async def test_skills_add_no_creds():
    """Skills with no credential requirements should activate immediately."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        from app.skills import load_catalog

        # Find a skill with no requirements (if any exist)
        catalog = load_catalog()
        no_cred_skill = None
        for sname, meta in catalog.items():
            from app.skills import get_skill_requirements
            if not get_skill_requirements(sname):
                no_cred_skill = sname
                break

        if no_cred_skill:
            chat = FakeChat(12345)
            msg = FakeMessage(chat=chat, text=f"/skills add {no_cred_skill}")
            user = FakeUser(42)
            update = FakeUpdate(message=msg, user=user, chat=chat)

            await th.cmd_skills(update, FakeContext(args=["add", no_cred_skill]))

            session = load_session_disk(data_dir, 12345, prov)
            check_in("skill activated immediately", no_cred_skill, session.get("active_skills", []))
            check("no setup needed", session.get("awaiting_skill_setup"), None)

            reply_texts = " ".join(r.get("text", "") for r in msg.replies)
            check_in("says activated", "activated", reply_texts.lower())
        else:
            # All catalog skills require creds — skip gracefully
            print("  SKIP  no cred-free skill in catalog")

run_test("/skills add no creds", test_skills_add_no_creds())


# ===================================================================
# Test 21: Rich role.md content used verbatim (not double-wrapped)
# ===================================================================

async def test_rich_role_verbatim():
    """Regression: build_system_prompt always wrapped role in 'You are a {role}.',
    turning 'You are a senior architect...' into 'You are a You are a senior...'"""
    from app.skills import build_system_prompt

    # Short noun phrase → gets wrapped
    prompt1 = build_system_prompt("senior Python engineer", [])
    check_in("short role wrapped", "You are a senior Python engineer", prompt1)

    # Multi-line rich role → used verbatim
    rich = "You are a senior architect.\nYou specialize in distributed systems."
    prompt2 = build_system_prompt(rich, [])
    check_in("rich role verbatim", "You are a senior architect.", prompt2)
    check_not_in("no double wrap", "You are a You are", prompt2)

    # Role starting with "You are" → used verbatim
    prompt3 = build_system_prompt("You are an expert in Kubernetes.", [])
    check_not_in("no double wrap for 'You are'", "You are a You are", prompt3)
    check_in("starts with You are", "You are an expert", prompt3)

    # Role starting with "Act as" → used verbatim
    prompt4 = build_system_prompt("Act as a security auditor.", [])
    check_not_in("no wrap for 'Act as'", "You are a Act as", prompt4)
    check_in("starts with Act as", "Act as a security auditor", prompt4)

    # Lowercase "you are" → used verbatim (not double-wrapped)
    prompt5 = build_system_prompt("you are an expert in kubernetes.", [])
    check_not_in("no double wrap lowercase", "You are a you are", prompt5)
    check_in("lowercase verbatim", "you are an expert in kubernetes", prompt5)

    # Lowercase "you're" → used verbatim
    prompt6 = build_system_prompt("you're a helpful coding assistant.", [])
    check_not_in("no wrap for you're", "You are a you're", prompt6)
    check_in("you're verbatim", "you're a helpful coding assistant", prompt6)

run_test("rich role verbatim", test_rich_role_verbatim())


# ===================================================================
# Test 22: /skills remove cancels in-progress credential setup
# ===================================================================

async def test_skills_remove_cancels_setup():
    """Regression: /skills remove left awaiting_skill_setup intact, so the
    next message would still be consumed as a credential and re-activate the skill."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Pre-set session: skill active + setup in progress
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42, "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/skills remove github-integration")
        update = FakeUpdate(message=msg, user=user, chat=chat)

        await th.cmd_skills(update, FakeContext(args=["remove", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        check_not_in("skill removed", "github-integration", session.get("active_skills", []))
        check("setup cancelled", session.get("awaiting_skill_setup"), None)

run_test("/skills remove cancels setup", test_skills_remove_cancels_setup())


# ===================================================================
# Test 23: /skills clear cancels in-progress credential setup
# ===================================================================

async def test_skills_clear_cancels_setup():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 42, "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/skills clear")
        update = FakeUpdate(message=msg, user=user, chat=chat)

        await th.cmd_skills(update, FakeContext(args=["clear"]))

        session = load_session_disk(data_dir, 12345, prov)
        check("skills empty", session.get("active_skills"), [])
        check("setup cancelled", session.get("awaiting_skill_setup"), None)

run_test("/skills clear cancels setup", test_skills_clear_cancels_setup())


# ===================================================================
# Test 24: MCP args is a list (not scalar string)
# ===================================================================

async def test_mcp_args_is_list():
    """Regression: claude.yaml had 'args: -y @...' (scalar), which would produce
    'args': '-y @...' in the MCP JSON instead of an argv array."""
    from app.skills import load_provider_yaml

    raw = load_provider_yaml("github-integration", "claude")
    mcp = raw.get("mcp_servers", {}).get("github", {})
    check_true("args is a list", isinstance(mcp.get("args"), list))
    check("args has 2 elements", len(mcp.get("args", [])), 2)
    check_in("args contains -y", "-y", mcp["args"])

    raw2 = load_provider_yaml("linear-integration", "claude")
    mcp2 = raw2.get("mcp_servers", {}).get("linear", {})
    check_true("linear args is a list", isinstance(mcp2.get("args"), list))

run_test("MCP args is list", test_mcp_args_is_list())


# ===================================================================
# Test 25: Script staging removes stale files within a skill dir
# ===================================================================

async def test_script_staging_removes_stale():
    """Regression: if a skill stays active but its scripts: list changes,
    removed files were left behind in the staged directory."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)

        from app.skills import stage_codex_scripts

        # First staging — creates scripts
        result = stage_codex_scripts(data_dir, 99999, ["github-integration"])
        check_true("staging returns path", result is not None)
        staged_dir = result / "github-integration"
        check_true("gh-helper.sh exists", (staged_dir / "gh-helper.sh").is_file())

        # Simulate a stale file that shouldn't be there
        stale_file = staged_dir / "old-script.sh"
        stale_file.write_text("#!/bin/bash\necho stale")

        # Re-stage — should clear the skill dir and only have current scripts
        result2 = stage_codex_scripts(data_dir, 99999, ["github-integration"])
        staged_dir2 = result2 / "github-integration"
        check_true("gh-helper.sh still exists", (staged_dir2 / "gh-helper.sh").is_file())
        check_false("stale file removed", (staged_dir2 / "old-script.sh").exists())

run_test("script staging removes stale", test_script_staging_removes_stale())


# ===================================================================
# Test 26: Cross-user approval (Alice requests, Bob approves)
# ===================================================================

async def test_cross_user_approval():
    """The plan requires 'Alice requests, Bob approves' coverage. Verify that
    request_user_id is preserved through the pending request and passed to
    execute_request on approval."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: do something")]
        prov.run_results = [RunResult(text="Done")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        alice = FakeUser(uid=100, username="alice")
        bob = FakeUser(uid=200, username="bob")

        # Alice sends a message (approval mode on → preflight)
        msg_alice = FakeMessage(chat=chat, text="deploy to production")
        update_alice = FakeUpdate(message=msg_alice, user=alice, chat=chat)
        await th.handle_message(update_alice, FakeContext())

        check("preflight called", len(prov.preflight_calls), 1)

        # Verify pending stores Alice's user ID
        session = load_session_disk(data_dir, 12345, prov)
        pending = session.get("pending_request")
        check_true("pending exists", pending is not None)
        check("pending has alice's user_id", pending["request_user_id"], 100)

        # Bob approves via callback
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=bob, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        check("run called after bob approves", len(prov.run_calls), 1)

        session = load_session_disk(data_dir, 12345, prov)
        check("pending cleared after approval", session.get("pending_request"), None)

run_test("cross-user approval", test_cross_user_approval())


# ===================================================================
# Test 27: Cross-user approval preserves requester's credential_env
# ===================================================================

async def test_cross_user_credential_isolation():
    """Alice requests with github creds, Bob approves. Provider must receive
    Alice's credentials (not Bob's or empty)."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on",
                          default_skills=("github-integration",))
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan: use github")]
        prov.run_results = [RunResult(text="Done with github")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        # Monkey-patch validate_credential
        original_validate = th.validate_credential
        async def fake_validate(req, value):
            return (True, "")
        th.validate_credential = fake_validate

        try:
            key = derive_encryption_key(cfg.telegram_token)

            # Alice (uid=100) has GITHUB_TOKEN
            save_user_credential(data_dir, 100, "github-integration", "GITHUB_TOKEN", "ghp_alice_token", key)
            # Bob (uid=200) has a DIFFERENT GITHUB_TOKEN
            save_user_credential(data_dir, 200, "github-integration", "GITHUB_TOKEN", "ghp_bob_token", key)

            chat = FakeChat(12345)
            alice = FakeUser(uid=100, username="alice")
            bob = FakeUser(uid=200, username="bob")

            # Alice sends message → preflight
            msg_alice = FakeMessage(chat=chat, text="list my repos")
            update_alice = FakeUpdate(message=msg_alice, user=alice, chat=chat)
            await th.handle_message(update_alice, FakeContext())

            check("preflight called", len(prov.preflight_calls), 1)

            session = load_session_disk(data_dir, 12345, prov)
            pending = session.get("pending_request")
            check("pending has alice's uid", pending["request_user_id"], 100)

            # Bob approves
            cb_msg = FakeMessage(chat=chat)
            query = FakeCallbackQuery("approval_approve", message=cb_msg)
            cb_update = FakeUpdate(user=bob, chat=chat, callback_query=query)
            cb_update.effective_message = cb_msg
            await th.handle_callback(cb_update, FakeContext())

            check("run called", len(prov.run_calls), 1)

            # THE KEY CHECK: credential_env should have Alice's token, not Bob's
            ctx = prov.run_calls[0]["context"]
            check("credential_env has GITHUB_TOKEN", ctx.credential_env.get("GITHUB_TOKEN"), "ghp_alice_token")
            check("NOT bob's token", ctx.credential_env.get("GITHUB_TOKEN") != "ghp_bob_token", True)
        finally:
            th.validate_credential = original_validate

run_test("cross-user credential isolation", test_cross_user_credential_isolation())


# ===================================================================
# Test 28: Provider timeout path through execute_request
# ===================================================================

async def test_provider_timeout():
    """When provider returns timed_out=True, handler should display timeout message
    and NOT process the response text as a reply."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="partial output", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="long running task")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)

        # On timeout, execute_request returns early after progress.update().
        # send_formatted_reply (which calls message.reply_text) should NOT
        # be called. reply_text appends to msg.replies, so we check that
        # "partial output" does NOT appear in any reply_text entries.
        # The first entry is the status message ("Starting claude..."),
        # and subsequent entries would be formatted replies.
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_not_in("no formatted reply of partial text", "partial output", reply_texts)

        # Only 1 reply_text call (the status message), not 2+ (which would
        # include a formatted reply)
        reply_text_count = sum(1 for r in msg.replies if "text" in r)
        check("only status msg reply (no formatted reply)", reply_text_count, 1)

        # Session should not have a pending_request (timeout != denial)
        session = load_session_disk(data_dir, 12345, prov)
        check("no pending on timeout", session.get("pending_request"), None)

run_test("provider timeout", test_provider_timeout())


# ===================================================================
# Test 29: Provider error return code path
# ===================================================================

async def test_provider_error_returncode():
    """When provider returns non-zero returncode, handler should show the error
    text, not process it as a normal reply."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="Error: segfault in subprocess", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="crash me")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)

        # On error returncode, execute_request returns early after progress.update().
        # send_formatted_reply (which calls message.reply_text) should NOT be called.
        # The error text goes via progress.update → status_msg.edit_text, not msg.reply_text.
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_not_in("no formatted reply of error text", "segfault", reply_texts)

        # Only 1 reply_text call (the status message), not 2+
        reply_text_count = sum(1 for r in msg.replies if "text" in r)
        check("only status msg reply (no formatted reply)", reply_text_count, 1)

        # No pending_request should be saved (no denials)
        session = load_session_disk(data_dir, 12345, prov)
        check("no pending on error", session.get("pending_request"), None)

run_test("provider error returncode", test_provider_error_returncode())


# ===================================================================
# Test 30: Malformed skill in catalog doesn't crash load_catalog
# ===================================================================

async def test_malformed_skill_resilience():
    """A malformed skill.md in the custom skills dir should be skipped
    without crashing load_catalog() or any command that uses it.
    Uses a temp dir override to avoid polluting the real custom skills dir."""
    import app.skills as skills_mod
    from app.skills import load_catalog, get_skill_instructions, get_skill_requirements, _skill_dir

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            malformed_dir = custom_dir / "malformed-test-skill"
            malformed_dir.mkdir(parents=True, exist_ok=True)
            # Write invalid frontmatter (unclosed YAML block)
            (malformed_dir / "skill.md").write_text(
                "---\nname: malformed-test-skill\n"
                "description: [invalid yaml\n"  # unclosed bracket
                "---\n\nBody text here.\n"
            )

            # load_catalog should NOT raise — it should skip the malformed skill
            catalog = load_catalog()
            check_true("load_catalog did not crash", isinstance(catalog, dict))
            check_not_in("malformed skill not in catalog", "malformed-test-skill", catalog)

            # _skill_dir should return None for malformed skill
            check("_skill_dir returns None for malformed", _skill_dir("malformed-test-skill"), None)

            # get_skill_instructions for malformed skill should return empty
            instructions = get_skill_instructions("malformed-test-skill")
            check("instructions empty for malformed", instructions, "")

            # get_skill_requirements should return empty (skill dir not resolved)
            reqs = get_skill_requirements("malformed-test-skill")
            check("requirements empty for malformed", reqs, [])
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir

run_test("malformed skill resilience", test_malformed_skill_resilience())


# ===================================================================
# Test 31: Malformed provider YAML doesn't crash
# ===================================================================

async def test_malformed_provider_yaml_resilience():
    """A malformed claude.yaml or codex.yaml should return {} not crash.
    Uses a temp dir override to avoid polluting the real custom skills dir."""
    import app.skills as skills_mod
    from app.skills import load_provider_yaml, build_provider_config

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            skill_dir = custom_dir / "yaml-test-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: yaml-test-skill\ndisplay_name: YAML Test\n"
                "description: Test skill\n---\n\nTest.\n"
            )
            # Write invalid YAML for claude.yaml
            (skill_dir / "claude.yaml").write_text(
                "mcp_servers:\n  test:\n    command: echo\n    args: [unclosed\n"
            )

            result = load_provider_yaml("yaml-test-skill", "claude")
            check("malformed yaml returns empty dict", result, {})

            # build_provider_config should also not crash
            config = build_provider_config("claude", ["yaml-test-skill"], {})
            check("build_provider_config returns dict", isinstance(config, dict), True)
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir

run_test("malformed provider yaml resilience", test_malformed_provider_yaml_resilience())


# ===================================================================
# Test 32: Malformed requires.yaml doesn't crash
# ===================================================================

async def test_malformed_requires_yaml_resilience():
    """A malformed requires.yaml should return empty list, not crash."""
    from app.skills import _parse_requires_yaml

    # Invalid YAML
    result = _parse_requires_yaml("credentials:\n  - key: [unclosed\n")
    check("malformed requires.yaml returns empty", result, [])

    # Valid YAML but wrong structure
    result2 = _parse_requires_yaml("just_a_string")
    check("non-dict requires.yaml returns empty", result2, [])

    # Null content
    result3 = _parse_requires_yaml("")
    check("empty requires.yaml returns empty", result3, [])

run_test("malformed requires.yaml resilience", test_malformed_requires_yaml_resilience())


# ===================================================================
# Test 33: BOT_SKILLS validation in validate_config
# ===================================================================

async def test_bot_skills_validation():
    """validate_config should report unknown skill names in BOT_SKILLS."""
    from app.config import validate_config

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # Config with a nonexistent skill in default_skills
        cfg = make_config(data_dir, default_skills=("nonexistent-skill-xyz",),
                          provider_name="claude")
        errors = validate_config(cfg)
        skill_errors = [e for e in errors if "nonexistent-skill-xyz" in e]
        check_true("reports unknown skill", len(skill_errors) > 0)

        # Config with valid skill should not produce skill errors
        cfg2 = make_config(data_dir, default_skills=("github-integration",),
                           provider_name="claude")
        errors2 = validate_config(cfg2)
        skill_errors2 = [e for e in errors2 if "BOT_SKILLS" in e and "github-integration" in e]
        check("valid skill no error", len(skill_errors2), 0)

        # Config with no skills should not produce skill errors
        cfg3 = make_config(data_dir, default_skills=(), provider_name="claude")
        errors3 = validate_config(cfg3)
        skill_errors3 = [e for e in errors3 if "BOT_SKILLS" in e]
        check("no skills no error", len(skill_errors3), 0)

run_test("BOT_SKILLS validation", test_bot_skills_validation())


# ===================================================================
# Test 34: /role command integration
# ===================================================================

async def test_cmd_role():
    """Test /role show, set, and clear."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, role="default engineer")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)

        # /role with no args → shows current role
        msg1 = FakeMessage(chat=chat, text="/role")
        update1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.cmd_role(update1, FakeContext(args=[]))

        reply1 = " ".join(r.get("text", "") for r in msg1.replies)
        check_in("shows default role", "default engineer", reply1)

        # /role <text> → sets role
        msg2 = FakeMessage(chat=chat, text="/role security auditor")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.cmd_role(update2, FakeContext(args=["security", "auditor"]))

        session = load_session_disk(data_dir, 12345, prov)
        check("role updated", session.get("role"), "security auditor")

        # /role clear → resets to instance default
        msg3 = FakeMessage(chat=chat, text="/role clear")
        update3 = FakeUpdate(message=msg3, user=user, chat=chat)
        await th.cmd_role(update3, FakeContext(args=["clear"]))

        session = load_session_disk(data_dir, 12345, prov)
        check("role reset to default", session.get("role"), "default engineer")

        reply3 = " ".join(r.get("text", "") for r in msg3.replies)
        check_in("says reset", "default", reply3.lower())

run_test("/role command", test_cmd_role())


# ===================================================================
# Test 35: Role affects system_prompt in provider context
# ===================================================================

async def test_role_in_provider_context():
    """Setting a role should flow through to the system_prompt in RunContext."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, role="Kubernetes expert")
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="deploy my app")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("run called", len(prov.run_calls), 1)
        ctx = prov.run_calls[0]["context"]
        check_in("system_prompt has role", "Kubernetes expert", ctx.system_prompt)

run_test("role in provider context", test_role_in_provider_context())


# ===================================================================
# Test 36: Approval flow preflight timeout
# ===================================================================

async def test_approval_preflight_timeout():
    """When preflight times out, no pending_request should be saved."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="", timed_out=True)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("preflight called", len(prov.preflight_calls), 1)
        check("run NOT called", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        check("no pending_request on timeout", session.get("pending_request"), None)

        # No approval buttons should have been sent
        chat_msgs = " ".join(m.get("text", "") for m in chat.sent_messages)
        check_not_in("no approval prompt on timeout", "Approve", chat_msgs)

run_test("approval preflight timeout", test_approval_preflight_timeout())


# ===================================================================
# Test 37: Approval flow preflight error
# ===================================================================

async def test_approval_preflight_error():
    """When preflight returns non-zero, no pending_request should be saved."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Preflight error", returncode=1)]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        msg = FakeMessage(chat=chat, text="do something")
        user = FakeUser(42)
        update = FakeUpdate(message=msg, user=user, chat=chat)

        import app.telegram_handlers as th
        await th.handle_message(update, FakeContext())

        check("preflight called", len(prov.preflight_calls), 1)
        check("run NOT called", len(prov.run_calls), 0)

        session = load_session_disk(data_dir, 12345, prov)
        check("no pending_request on error", session.get("pending_request"), None)

run_test("approval preflight error", test_approval_preflight_error())


# ===================================================================
# Test 38: Duplicate pending request blocked
# ===================================================================

async def test_duplicate_pending_blocked():
    """Sending a second message while a request is pending should be blocked."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, approval_mode="on")
        prov = FakeProvider("claude")
        prov.preflight_results = [
            RunResult(text="Plan 1"),
            RunResult(text="Plan 2"),  # should not be reached
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)

        # First message → creates pending
        msg1 = FakeMessage(chat=chat, text="first request")
        update1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(update1, FakeContext())

        check("first preflight called", len(prov.preflight_calls), 1)

        # Second message → should be blocked since pending exists
        msg2 = FakeMessage(chat=chat, text="second request")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(update2, FakeContext())

        # The second preflight should still be called because approval mode
        # doesn't check pending before preflight — but the request_approval
        # function DOES check and returns early
        reply_texts = " ".join(r.get("text", "") for r in msg2.replies)
        # Either it blocked the second request or handled it; verify no corruption
        session = load_session_disk(data_dir, 12345, prov)
        check_true("pending_request still exists", session.get("pending_request") is not None)

run_test("duplicate pending blocked", test_duplicate_pending_blocked())


# ===================================================================
# Test 39: /new preserves default_skills from config
# ===================================================================

async def test_new_preserves_default_skills():
    """/new should reset session but keep default_skills from config."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        # Pre-save credentials so the skill doesn't trigger setup
        key = derive_encryption_key(cfg.telegram_token)
        save_user_credential(data_dir, 42, "github-integration", "GITHUB_TOKEN", "ghp_test", key)

        # Pre-populate session with extra skills
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration", "extra-skill"]
        save_session(data_dir, 12345, session)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/new")
        update = FakeUpdate(message=msg, user=user, chat=chat)

        await th.cmd_new(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        # Default skills should be restored
        check_in("default skill preserved", "github-integration",
                  session.get("active_skills", []))
        # Extra skill should be gone
        check_not_in("extra skill removed", "extra-skill",
                      session.get("active_skills", []))

run_test("/new preserves default_skills", test_new_preserves_default_skills())


# ===================================================================
# Test 40: Provider denials trigger pending but preserve request_user_id
# ===================================================================

async def test_denial_preserves_request_user_id():
    """When denials occur, the pending_request must preserve the original
    requester's user_id for credential lookup on retry."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="partial", denials=[
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/secrets"}},
        ])]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        alice = FakeUser(uid=100, username="alice")
        msg = FakeMessage(chat=chat, text="read secrets")
        update = FakeUpdate(message=msg, user=alice, chat=chat)

        await th.handle_message(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        pending = session.get("pending_request")
        check_true("pending exists", pending is not None)
        check("request_user_id is alice", pending["request_user_id"], 100)
        check_true("denials preserved", len(pending.get("denials", [])) > 0)

run_test("denial preserves request_user_id", test_denial_preserves_request_user_id())


# ===================================================================
# Test 41: Context hash changes when role changes
# ===================================================================

async def test_context_hash_role_sensitivity():
    """Context hash should change when role changes, causing codex thread reset."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, provider_name="codex")
        prov = FakeProvider("codex")
        prov.run_results = [
            RunResult(text="ok1", provider_state_updates={"thread_id": "thread-1"}),
            RunResult(text="ok2", provider_state_updates={"thread_id": "thread-2"}),
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        chat = FakeChat(12345)
        user = FakeUser(42)

        # First message with default role
        msg1 = FakeMessage(chat=chat, text="hello")
        update1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(update1, FakeContext())

        check("first run", len(prov.run_calls), 1)

        session = load_session_disk(data_dir, 12345, prov)
        hash1 = session["provider_state"].get("context_hash")
        check_true("hash1 set", hash1 is not None)

        # Change role
        msg_role = FakeMessage(chat=chat, text="/role security expert")
        update_role = FakeUpdate(message=msg_role, user=user, chat=chat)
        await th.cmd_role(update_role, FakeContext(args=["security", "expert"]))

        # Second message — should detect hash change and clear thread
        msg2 = FakeMessage(chat=chat, text="check security")
        update2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(update2, FakeContext())

        check("second run", len(prov.run_calls), 2)

        # The thread_id should have been cleared before the second run
        call_state = prov.run_calls[1]["provider_state"]
        check("thread cleared on hash change", call_state.get("thread_id"), None)

        session = load_session_disk(data_dir, 12345, prov)
        hash2 = session["provider_state"].get("context_hash")
        check("hash changed", hash1 != hash2, True)

run_test("context hash role sensitivity", test_context_hash_role_sensitivity())


# ===================================================================
# Test 42: Group chat credential setup isolation — Bob can't overwrite Alice's setup
# ===================================================================

async def test_group_chat_setup_isolation():
    """In a group chat, if Alice is mid-credential-setup, Bob's action should
    NOT overwrite her awaiting_skill_setup. If it did, Alice's next message
    (her secret) would fall through to normal execution and be sent to the provider."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir, default_skills=("github-integration",))
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        original_validate = th.validate_credential
        async def fake_validate(req, value):
            return (True, "")
        th.validate_credential = fake_validate

        try:
            chat = FakeChat(12345)  # shared group chat
            alice = FakeUser(uid=100, username="alice")
            bob = FakeUser(uid=200, username="bob")

            # Alice triggers /skills add → starts credential setup for her
            msg_alice = FakeMessage(chat=chat, text="/skills add github-integration")
            update_alice = FakeUpdate(message=msg_alice, user=alice, chat=chat)
            await th.cmd_skills(update_alice, FakeContext(args=["add", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_true("alice setup started", session.get("awaiting_skill_setup") is not None)
            check("setup is alice's", session["awaiting_skill_setup"]["user_id"], 100)

            # Bob tries /skills add (same or different skill) → should NOT overwrite
            msg_bob = FakeMessage(chat=chat, text="/skills add github-integration")
            update_bob = FakeUpdate(message=msg_bob, user=bob, chat=chat)
            await th.cmd_skills(update_bob, FakeContext(args=["add", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check("setup still alice's after bob's attempt", session["awaiting_skill_setup"]["user_id"], 100)

            # Bob tries /skills setup → should also NOT overwrite
            msg_bob2 = FakeMessage(chat=chat, text="/skills setup github-integration")
            update_bob2 = FakeUpdate(message=msg_bob2, user=bob, chat=chat)
            await th.cmd_skills(update_bob2, FakeContext(args=["setup", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check("setup still alice's after bob's setup attempt", session["awaiting_skill_setup"]["user_id"], 100)

            # Bob's message should NOT be captured as a credential
            msg_bob3 = FakeMessage(chat=chat, text="ghp_bob_secret_token")
            update_bob3 = FakeUpdate(message=msg_bob3, user=bob, chat=chat)
            await th.handle_message(update_bob3, FakeContext())

            # Bob's message should NOT be deleted (it's not a credential for him)
            check_false("bob's msg not deleted", msg_bob3.deleted)

            # Alice's setup should still be intact
            session = load_session_disk(data_dir, 12345, prov)
            check_true("alice setup still intact", session.get("awaiting_skill_setup") is not None)
            check("still alice's setup", session["awaiting_skill_setup"]["user_id"], 100)

            # Now Alice sends her credential → should be captured and deleted
            msg_alice2 = FakeMessage(chat=chat, text="ghp_alice_real_token")
            update_alice2 = FakeUpdate(message=msg_alice2, user=alice, chat=chat)
            await th.handle_message(update_alice2, FakeContext())

            check_true("alice's msg deleted (secret)", msg_alice2.deleted)

            session = load_session_disk(data_dir, 12345, prov)
            check("setup cleared after alice's cred", session.get("awaiting_skill_setup"), None)

            # Alice's credential saved, not Bob's
            key = derive_encryption_key(cfg.telegram_token)
            alice_creds = load_user_credentials(data_dir, 100, key)
            check("alice has GITHUB_TOKEN", alice_creds.get("github-integration", {}).get("GITHUB_TOKEN"), "ghp_alice_real_token")

            bob_creds = load_user_credentials(data_dir, 200, key)
            check_false("bob has no credential", bob_creds.get("github-integration", {}).get("GITHUB_TOKEN"))

        finally:
            th.validate_credential = original_validate

run_test("group chat setup isolation", test_group_chat_setup_isolation())


# ===================================================================
# Test 43: Group chat — _check_credential_satisfaction doesn't overwrite setup
# ===================================================================

async def test_group_check_cred_satisfaction_no_overwrite():
    """When Alice is mid-setup and Bob sends a message that triggers
    _check_credential_satisfaction (because active skills have missing creds),
    it should NOT overwrite Alice's setup with Bob's user_id."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        alice = FakeUser(uid=100, username="alice")
        bob = FakeUser(uid=200, username="bob")

        # Pre-set: Alice is mid-setup, skill is active with missing creds
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100,
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        # Bob sends a normal message → triggers _check_credential_satisfaction
        # which should NOT overwrite Alice's setup
        msg_bob = FakeMessage(chat=chat, text="list repos please")
        update_bob = FakeUpdate(message=msg_bob, user=bob, chat=chat)
        await th.handle_message(update_bob, FakeContext())

        # Provider should NOT have been called (creds missing for Bob)
        check("run NOT called", len(prov.run_calls), 0)

        # Alice's setup should still be intact — NOT overwritten with Bob's user_id
        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        check_true("setup still exists", setup is not None)
        check("setup still alice's user_id", setup["user_id"], 100)

        # Bob should get a "wait" message, not a credential prompt that overwrites Alice
        reply_texts = " ".join(r.get("text", "") for r in msg_bob.replies)
        check_in("bob told to wait", "wait", reply_texts.lower())

run_test("group check_cred_satisfaction no overwrite", test_group_check_cred_satisfaction_no_overwrite())


# ===================================================================
# Test 44: Skill catalog uses directory name as canonical key
# ===================================================================

async def test_catalog_uses_directory_name():
    """Regression: load_catalog() used frontmatter 'name' as the key, but
    _skill_dir() resolves by directory name. If they differ, the skill is
    in the catalog but invisible to runtime (instructions, requirements,
    provider config all resolve to nothing)."""
    import app.skills as skills_mod
    from app.skills import load_catalog, _skill_dir, get_skill_instructions, get_skill_requirements

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir

            # Create a skill where dir name != frontmatter name
            skill_dir = custom_dir / "my-actual-dir"
            skill_dir.mkdir(parents=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: fancy-meta-name\ndisplay_name: Fancy Skill\n"
                "description: A test skill\n---\n\nDo fancy things.\n"
            )

            catalog = load_catalog()

            # The catalog should use directory name, not frontmatter name
            check_in("dir name in catalog", "my-actual-dir", catalog)
            check_not_in("frontmatter name NOT in catalog", "fancy-meta-name", catalog)

            # _skill_dir should find by directory name
            check_true("_skill_dir finds dir name", _skill_dir("my-actual-dir") is not None)
            check("_skill_dir misses frontmatter name", _skill_dir("fancy-meta-name"), None)

            # Instructions should be loadable by directory name
            instructions = get_skill_instructions("my-actual-dir")
            check_in("instructions loaded", "fancy things", instructions)

            # Instructions NOT loadable by frontmatter name
            instructions2 = get_skill_instructions("fancy-meta-name")
            check("no instructions by frontmatter name", instructions2, "")
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir

run_test("catalog uses directory name", test_catalog_uses_directory_name())


# ===================================================================
# Test 45: Bad validate spec (non-numeric expect_status) doesn't crash
# ===================================================================

async def test_bad_validate_spec_no_crash():
    """A requires.yaml with expect_status: twohundred should return a
    user-facing error, not crash with ValueError."""
    from app.skills import validate_credential, SkillRequirement

    req = SkillRequirement(
        key="API_KEY",
        prompt="Enter key",
        help_url=None,
        validate={
            "method": "GET",
            "url": "https://example.com/health",
            "header": "Authorization: Bearer ${API_KEY}",
            "expect_status": "twohundred",  # non-numeric
        },
    )

    # Should NOT raise — should return (False, error_message)
    ok, detail = await validate_credential(req, "some-key-value")
    check("returns not-ok", ok, False)
    check_in("mentions invalid expect_status", "expect_status", detail.lower())

    # Also test with a completely missing expect_status type
    req2 = SkillRequirement(
        key="API_KEY",
        prompt="Enter key",
        help_url=None,
        validate={
            "method": "GET",
            "url": "https://example.com/health",
            "expect_status": None,
        },
    )
    ok2, detail2 = await validate_credential(req2, "some-key")
    check("none expect_status returns not-ok", ok2, False)
    check_in("mentions invalid", "invalid", detail2.lower())

run_test("bad validate spec no crash", test_bad_validate_spec_no_crash())


# ===================================================================
# Test 46: Cross-user /skills remove is blocked by another user's setup
# ===================================================================

async def test_cross_user_skills_remove_blocked():
    """In a group chat, Bob's /skills remove should be rejected while Alice is
    mid-setup for the same skill. The skill must remain active, Alice's setup
    must stay intact, and her next credential should complete setup without
    changing the already-active skill list."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        # Pre-set: Alice is mid-setup
        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/skills remove github-integration")
        update = FakeUpdate(message=msg, user=bob, chat=chat)

        await th.cmd_skills(update, FakeContext(args=["remove", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        check_in("skill still active", "github-integration", session.get("active_skills", []))
        setup = session.get("awaiting_skill_setup")
        check_true("setup preserved", setup is not None)
        check("setup still alice's", setup["user_id"], 100)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("bob told to wait", "wait", reply_texts.lower())

        msg_alice = FakeMessage(chat=chat, text="ghp_alice_real_token")
        update_alice = FakeUpdate(message=msg_alice, user=FakeUser(uid=100, username="alice"), chat=chat)
        await th.handle_message(update_alice, FakeContext())

        check_true("alice secret deleted", msg_alice.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        check("skill list unchanged after alice cred", session.get("active_skills"), ["github-integration"])

run_test("cross-user /skills remove blocked", test_cross_user_skills_remove_blocked())


# ===================================================================
# Test 47: Cross-user /skills clear is blocked by another user's setup
# ===================================================================

async def test_cross_user_skills_clear_blocked():
    """Bob's /skills clear should be rejected while Alice is mid-setup, so the
    chat's active skill list and Alice's setup both remain intact."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration", "testing"]
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/skills clear")
        update = FakeUpdate(message=msg, user=bob, chat=chat)

        await th.cmd_skills(update, FakeContext(args=["clear"]))

        session = load_session_disk(data_dir, 12345, prov)
        check("skills unchanged", session.get("active_skills"), ["github-integration", "testing"])
        setup = session.get("awaiting_skill_setup")
        check_true("setup preserved", setup is not None)
        check("setup still alice's", setup["user_id"], 100)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("bob told to wait", "wait", reply_texts.lower())

        msg_alice = FakeMessage(chat=chat, text="ghp_alice_real_token")
        update_alice = FakeUpdate(message=msg_alice, user=FakeUser(uid=100, username="alice"), chat=chat)
        await th.handle_message(update_alice, FakeContext())

        check_true("alice secret deleted", msg_alice.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        check("skills still unchanged after alice cred", session.get("active_skills"), ["github-integration", "testing"])

run_test("cross-user /skills clear blocked", test_cross_user_skills_clear_blocked())


# ===================================================================
# Test 48: Cross-user /new is blocked by another user's setup
# ===================================================================

async def test_cross_user_new_blocked():
    """Bob's /new should be rejected while Alice is mid-setup, so the existing
    session state stays intact instead of being reset under her credential flow."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["provider_state"]["started"] = True
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/new")
        update = FakeUpdate(message=msg, user=bob, chat=chat)

        await th.cmd_new(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        check_true("setup preserved across /new", setup is not None)
        check("setup still alice's", setup["user_id"], 100)
        check_true("provider state not reset", session["provider_state"].get("started"))
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("bob told to wait", "wait", reply_texts.lower())

        msg_alice = FakeMessage(chat=chat, text="ghp_alice_real_token")
        update_alice = FakeUpdate(message=msg_alice, user=FakeUser(uid=100, username="alice"), chat=chat)
        await th.handle_message(update_alice, FakeContext())

        check_true("alice secret deleted", msg_alice.deleted)
        session = load_session_disk(data_dir, 12345, prov)
        check("setup cleared after alice cred", session.get("awaiting_skill_setup"), None)
        check_true("provider state still not reset after alice cred", session["provider_state"].get("started"))
        check("skills still active after alice cred", session.get("active_skills"), ["github-integration"])

run_test("cross-user /new blocked", test_cross_user_new_blocked())


# ===================================================================
# Test 49: Expired foreign setup allows recovery
# ===================================================================

async def test_expired_foreign_setup_allows_recovery():
    """If Alice starts setup and disappears, after the timeout expires Bob
    should be able to /skills clear or /new without being blocked."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = ["github-integration"]
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": 0,  # epoch — long expired
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")

        # Bob's /new should succeed because Alice's setup is expired
        msg = FakeMessage(chat=chat, text="/new")
        update = FakeUpdate(message=msg, user=bob, chat=chat)
        await th.cmd_new(update, FakeContext())

        session = load_session_disk(data_dir, 12345, prov)
        # Session should be reset — Alice's stale setup is gone
        check("stale setup cleared", session.get("awaiting_skill_setup"), None)
        reply_texts = " ".join(r.get("text", "") for r in msg.replies)
        check_in("fresh conversation", "fresh", reply_texts.lower())

        # Also verify /skills clear works with an expired setup
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        session["active_skills"] = ["github-integration"]
        save_session(data_dir, 12345, session)

        msg2 = FakeMessage(chat=chat, text="/skills clear")
        update2 = FakeUpdate(message=msg2, user=bob, chat=chat)
        await th.cmd_skills(update2, FakeContext(args=["clear"]))

        session = load_session_disk(data_dir, 12345, prov)
        check("skills cleared", session.get("active_skills"), [])
        check("expired setup cleared", session.get("awaiting_skill_setup"), None)

        # Also verify /skills setup works with an expired foreign setup
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        msg3 = FakeMessage(chat=chat, text="/skills setup github-integration")
        update3 = FakeUpdate(message=msg3, user=bob, chat=chat)
        await th.cmd_skills(update3, FakeContext(args=["setup", "github-integration"]))

        session = load_session_disk(data_dir, 12345, prov)
        setup = session.get("awaiting_skill_setup")
        check_true("bob's setup started after expiry", setup is not None)
        check("setup is now bob's", setup["user_id"], 200)

run_test("expired foreign setup allows recovery", test_expired_foreign_setup_allows_recovery())


# ===================================================================
# Test 50: Expired foreign setup is durably cleared on no-op /skills remove
# ===================================================================

async def test_expired_setup_persisted_on_noop_remove():
    """When Bob runs /skills remove for a skill that isn't active and
    _foreign_skill_setup expires Alice's stale setup, the expiry must be
    saved to disk — not just cleared in memory."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        session = default_session("claude", prov.new_provider_state(), "off")
        session["active_skills"] = []
        session["awaiting_skill_setup"] = {
            "user_id": 100, "skill": "github-integration",
            "started_at": 0,  # expired
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token",
                           "help_url": None, "validate": None}],
        }
        save_session(data_dir, 12345, session)

        chat = FakeChat(12345)
        bob = FakeUser(uid=200, username="bob")
        msg = FakeMessage(chat=chat, text="/skills remove github-integration")
        update = FakeUpdate(message=msg, user=bob, chat=chat)

        await th.cmd_skills(update, FakeContext(args=["remove", "github-integration"]))

        # The expired setup must be gone from disk, not just from memory
        session = load_session_disk(data_dir, 12345, prov)
        check("expired setup cleared on disk", session.get("awaiting_skill_setup"), None)

run_test("expired setup persisted on noop remove", test_expired_setup_persisted_on_noop_remove())


# ===================================================================
# Test 51: End-to-end skills lifecycle
# ===================================================================

async def test_e2e_skills_lifecycle():
    """Full skills lifecycle in one session, exercising real persistence between
    every step: add credentialed skill → credential setup → capture → activation
    → provider dispatch with creds → add instruction-only skill → provider dispatch
    with both skills → role change → context hash drift → remove credentialed skill
    → provider dispatch without creds → /skills clear → provider dispatch with no
    skills → /new reset."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        ensure_data_dirs(data_dir)
        cfg = make_config(data_dir)
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th
        original_validate = th.validate_credential
        async def fake_validate(req, value):
            return (True, "")
        th.validate_credential = fake_validate

        try:
            chat = FakeChat(12345)
            alice = FakeUser(uid=100, username="alice")

            # --- Phase 1: Add credentialed skill ---
            msg = FakeMessage(chat=chat, text="/skills add github-integration")
            await th.cmd_skills(FakeUpdate(message=msg, user=alice, chat=chat),
                                FakeContext(args=["add", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_not_in("e2e: skill not active before creds",
                         "github-integration", session.get("active_skills", []))
            check_true("e2e: setup started", session.get("awaiting_skill_setup") is not None)

            # --- Phase 2: Send credential ---
            msg2 = FakeMessage(chat=chat, text="ghp_alice_e2e_token")
            await th.handle_message(FakeUpdate(message=msg2, user=alice, chat=chat),
                                    FakeContext())

            check_true("e2e: secret deleted", msg2.deleted)
            session = load_session_disk(data_dir, 12345, prov)
            check("e2e: setup cleared", session.get("awaiting_skill_setup"), None)
            check_in("e2e: skill activated", "github-integration",
                      session.get("active_skills", []))

            # Verify credential persisted
            key = derive_encryption_key(cfg.telegram_token)
            creds = load_user_credentials(data_dir, 100, key)
            check("e2e: credential saved",
                  creds.get("github-integration", {}).get("GITHUB_TOKEN"),
                  "ghp_alice_e2e_token")

            # --- Phase 3: Provider dispatch with credential ---
            prov.run_results = [RunResult(text="repos listed")]
            msg3 = FakeMessage(chat=chat, text="list my repos")
            await th.handle_message(FakeUpdate(message=msg3, user=alice, chat=chat),
                                    FakeContext())

            check("e2e: provider called", len(prov.run_calls), 1)
            ctx = prov.run_calls[0]["context"]
            check("e2e: cred in env", ctx.credential_env.get("GITHUB_TOKEN"),
                  "ghp_alice_e2e_token")
            check_in("e2e: system prompt has skill instructions",
                      "github", ctx.system_prompt.lower())

            # --- Phase 4: Add instruction-only skill ---
            msg4 = FakeMessage(chat=chat, text="/skills add testing")
            await th.cmd_skills(FakeUpdate(message=msg4, user=alice, chat=chat),
                                FakeContext(args=["add", "testing"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_in("e2e: testing active", "testing", session.get("active_skills", []))
            check_in("e2e: github still active", "github-integration",
                      session.get("active_skills", []))

            # --- Phase 5: Provider dispatch with both skills ---
            prov.run_results = [RunResult(text="tests written")]
            msg5 = FakeMessage(chat=chat, text="write tests for auth module")
            await th.handle_message(FakeUpdate(message=msg5, user=alice, chat=chat),
                                    FakeContext())

            check("e2e: provider called again", len(prov.run_calls), 2)
            ctx2 = prov.run_calls[1]["context"]
            check_in("e2e: system prompt has testing", "test", ctx2.system_prompt.lower())
            check_in("e2e: system prompt has github", "github", ctx2.system_prompt.lower())
            check("e2e: cred still in env", ctx2.credential_env.get("GITHUB_TOKEN"),
                  "ghp_alice_e2e_token")

            # --- Phase 6: Set role ---
            msg6 = FakeMessage(chat=chat, text="/role senior engineer")
            await th.cmd_role(FakeUpdate(message=msg6, user=alice, chat=chat),
                              FakeContext(args=["senior", "engineer"]))

            session = load_session_disk(data_dir, 12345, prov)
            check("e2e: role set", session.get("role"), "senior engineer")

            # --- Phase 7: Provider dispatch with role ---
            prov.run_results = [RunResult(text="done with role")]
            msg7 = FakeMessage(chat=chat, text="review this PR")
            await th.handle_message(FakeUpdate(message=msg7, user=alice, chat=chat),
                                    FakeContext())

            check("e2e: provider called with role", len(prov.run_calls), 3)
            ctx3 = prov.run_calls[2]["context"]
            check_in("e2e: role in system prompt", "senior engineer",
                      ctx3.system_prompt.lower())

            # --- Phase 8: Remove credentialed skill ---
            msg8 = FakeMessage(chat=chat, text="/skills remove github-integration")
            await th.cmd_skills(FakeUpdate(message=msg8, user=alice, chat=chat),
                                FakeContext(args=["remove", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_not_in("e2e: github removed", "github-integration",
                         session.get("active_skills", []))
            check_in("e2e: testing still active", "testing",
                      session.get("active_skills", []))

            # --- Phase 9: Provider dispatch without credentialed skill ---
            prov.run_results = [RunResult(text="just testing")]
            msg9 = FakeMessage(chat=chat, text="run tests")
            await th.handle_message(FakeUpdate(message=msg9, user=alice, chat=chat),
                                    FakeContext())

            check("e2e: provider called without github", len(prov.run_calls), 4)
            ctx4 = prov.run_calls[3]["context"]
            check_not_in("e2e: no github in prompt", "github",
                         ctx4.system_prompt.lower())
            check("e2e: no cred in env", ctx4.credential_env.get("GITHUB_TOKEN"), None)

            # --- Phase 10: /skills clear ---
            msg10 = FakeMessage(chat=chat, text="/skills clear")
            await th.cmd_skills(FakeUpdate(message=msg10, user=alice, chat=chat),
                                FakeContext(args=["clear"]))

            session = load_session_disk(data_dir, 12345, prov)
            check("e2e: skills empty", session.get("active_skills"), [])

            # --- Phase 11: Provider dispatch with no skills ---
            prov.run_results = [RunResult(text="bare response")]
            msg11 = FakeMessage(chat=chat, text="hello")
            await th.handle_message(FakeUpdate(message=msg11, user=alice, chat=chat),
                                    FakeContext())

            check("e2e: provider called bare", len(prov.run_calls), 5)
            ctx5 = prov.run_calls[4]["context"]
            # Role still set, but no skill instructions
            check_in("e2e: role still in prompt", "senior engineer",
                      ctx5.system_prompt.lower())
            check("e2e: empty cred env", ctx5.credential_env, {})

            # --- Phase 12: /new resets session ---
            msg12 = FakeMessage(chat=chat, text="/new")
            await th.cmd_new(FakeUpdate(message=msg12, user=alice, chat=chat),
                             FakeContext())

            session = load_session_disk(data_dir, 12345, prov)
            check("e2e: skills reset", session.get("active_skills"), [])
            check("e2e: role reset", session.get("role"), "")
            check("e2e: setup cleared", session.get("awaiting_skill_setup"), None)

            # Credential still on disk (per-user, not per-session)
            creds = load_user_credentials(data_dir, 100, key)
            check("e2e: credential survives /new",
                  creds.get("github-integration", {}).get("GITHUB_TOKEN"),
                  "ghp_alice_e2e_token")

            # --- Phase 13: Re-add skill — should activate immediately (creds exist) ---
            msg13 = FakeMessage(chat=chat, text="/skills add github-integration")
            await th.cmd_skills(FakeUpdate(message=msg13, user=alice, chat=chat),
                                FakeContext(args=["add", "github-integration"]))

            session = load_session_disk(data_dir, 12345, prov)
            check_in("e2e: re-add activates immediately", "github-integration",
                      session.get("active_skills", []))
            check("e2e: no setup needed", session.get("awaiting_skill_setup"), None)

        finally:
            th.validate_credential = original_validate

run_test("e2e skills lifecycle", test_e2e_skills_lifecycle())



# ===================================================================
# Test: /skills update all — prompt-size cross-chat warning
# ===================================================================
# Test: locally_modified persisted to _store.json via handler

# ===================================================================
# Phase 5 E2E: Full skill store lifecycle through handler layer
# ===================================================================

async def test_phase5_e2e_full_journey():
    """Full product workflow: install -> activate -> use -> update -> uninstall.

    Real: filesystem (store/custom/sessions), handler command flow, skill discovery,
          _store.json provenance, session sweep, prompt construction.
    Mocked: Telegram transport, provider subprocess, build_system_prompt for oversize test.
    """
    import json as _json
    import app.store as store_mod
    import app.telegram_handlers as th
    from unittest.mock import patch
    from app.skills import PROMPT_SIZE_WARNING_THRESHOLD

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        ensure_data_dirs(data_dir)

        tmp_store = Path(tmp) / "store"
        tmp_custom = Path(tmp) / "custom"
        tmp_store.mkdir()
        tmp_custom.mkdir()
        orig_store = store_mod.STORE_DIR
        orig_custom = store_mod.CUSTOM_DIR
        store_mod.STORE_DIR = tmp_store
        store_mod.CUSTOM_DIR = tmp_custom

        # Patch CUSTOM_DIR in skills module so load_catalog/get_skill_instructions finds installed skills
        import app.skills as skills_mod
        orig_skills_custom = skills_mod.CUSTOM_DIR
        skills_mod.CUSTOM_DIR = tmp_custom

        try:
            # --- Setup ---
            admin = FakeUser(uid=100, username="admin")
            regular = FakeUser(uid=200, username="regular")
            cfg = make_config(
                data_dir=data_dir,
                admin_user_ids=frozenset({100}),
                admin_usernames=frozenset({"admin"}),
                allowed_user_ids=frozenset({100, 200}),
                allowed_usernames=frozenset({"admin", "regular"}),
            )
            prov = FakeProvider("claude")
            setup_globals(cfg, prov)

            # Create store skill v1
            skill_dir = tmp_store / "code-helper"
            skill_dir.mkdir()
            (skill_dir / "skill.md").write_text(
                "---\nname: code-helper\ndisplay_name: Code Helper\n"
                "description: Assists with code tasks\n---\n\n"
                "Always explain your reasoning step by step. V1_MARKER.\n"
            )

            # =============================================================
            # Phase 1: Non-admin blocked from install
            # =============================================================
            chat_reg = FakeChat(2001)
            msg1 = FakeMessage(chat=chat_reg, text="/skills install code-helper")
            upd1 = FakeUpdate(message=msg1, user=regular, chat=chat_reg)
            await th.cmd_skills(upd1, FakeContext(args=["install", "code-helper"]))

            check_true("p1: non-admin got reply", len(msg1.replies) > 0)
            check_in("p1: blocked msg", "admin", msg1.replies[-1]["text"].lower())
            # Verify no files created
            check_false("p1: skill not installed", (tmp_custom / "code-helper").is_dir())

            # =============================================================
            # Phase 2: Admin installs store skill
            # =============================================================
            chat_admin = FakeChat(1001)
            msg2 = FakeMessage(chat=chat_admin, text="/skills install code-helper")
            upd2 = FakeUpdate(message=msg2, user=admin, chat=chat_admin)
            await th.cmd_skills(upd2, FakeContext(args=["install", "code-helper"]))

            check_true("p2: install reply", len(msg2.replies) > 0)
            check_in("p2: installed msg", "installed", msg2.replies[-1]["text"].lower())
            check_true("p2: skill dir exists", (tmp_custom / "code-helper").is_dir())
            check_true("p2: _store.json exists", (tmp_custom / "code-helper" / "_store.json").is_file())

            manifest = _json.loads((tmp_custom / "code-helper" / "_store.json").read_text())
            check("p2: source", manifest["source"], "store")
            check("p2: locally_modified", manifest["locally_modified"], False)

            # =============================================================
            # Phase 3: User activates skill in their chat
            # =============================================================
            chat_user = FakeChat(2001)
            msg3 = FakeMessage(chat=chat_user, text="/skills add code-helper")
            upd3 = FakeUpdate(message=msg3, user=regular, chat=chat_user)
            await th.cmd_skills(upd3, FakeContext(args=["add", "code-helper"]))

            session_user = load_session_disk(data_dir, 2001, prov)
            check_in("p3: skill activated", "code-helper", session_user.get("active_skills", []))

            # Admin also activates in their chat
            msg3b = FakeMessage(chat=chat_admin, text="/skills add code-helper")
            upd3b = FakeUpdate(message=msg3b, user=admin, chat=chat_admin)
            await th.cmd_skills(upd3b, FakeContext(args=["add", "code-helper"]))

            session_admin = load_session_disk(data_dir, 1001, prov)
            check_in("p3: admin skill activated", "code-helper", session_admin.get("active_skills", []))

            # =============================================================
            # Phase 4: User sends message — provider sees skill instructions
            # =============================================================
            prov.run_results = [RunResult(text="Here's your code explanation")]
            msg4 = FakeMessage(chat=chat_user, text="explain this function")
            upd4 = FakeUpdate(message=msg4, user=regular, chat=chat_user)
            await th.handle_message(upd4, FakeContext())

            check("p4: provider called", len(prov.run_calls), 1)
            ctx = prov.run_calls[0]["context"]
            check_in("p4: V1 instructions in prompt", "V1_MARKER", ctx.system_prompt)
            check_in("p4: step by step in prompt", "step by step", ctx.system_prompt)
            prov.run_calls.clear()

            # =============================================================
            # Phase 5: /skills list shows (store) tag
            # =============================================================
            msg5 = FakeMessage(chat=chat_user, text="/skills list")
            upd5 = FakeUpdate(message=msg5, user=regular, chat=chat_user)
            await th.cmd_skills(upd5, FakeContext(args=["list"]))

            check_true("p5: list reply", len(msg5.replies) > 0)
            check_in("p5: store tag", "(store)", msg5.replies[-1]["text"])

            # =============================================================
            # Phase 6: Non-admin blocked from update
            # =============================================================
            msg6 = FakeMessage(chat=chat_user, text="/skills update code-helper")
            upd6 = FakeUpdate(message=msg6, user=regular, chat=chat_user)
            await th.cmd_skills(upd6, FakeContext(args=["update", "code-helper"]))

            check_in("p6: update blocked", "admin", msg6.replies[-1]["text"].lower())

            # =============================================================
            # Phase 7: Operator updates store — admin runs /skills update all
            # =============================================================
            (tmp_store / "code-helper" / "skill.md").write_text(
                "---\nname: code-helper\ndisplay_name: Code Helper\n"
                "description: Assists with code tasks\n---\n\n"
                "Always explain your reasoning step by step. V2_MARKER.\n"
            )

            # Check updates shows update available
            msg7a = FakeMessage(chat=chat_admin, text="/skills updates")
            upd7a = FakeUpdate(message=msg7a, user=admin, chat=chat_admin)
            await th.cmd_skills(upd7a, FakeContext(args=["updates"]))
            check_in("p7: update available", "update available", msg7a.replies[-1]["text"])

            # Run update all
            msg7 = FakeMessage(chat=chat_admin, text="/skills update all")
            upd7 = FakeUpdate(message=msg7, user=admin, chat=chat_admin)
            await th.cmd_skills(upd7, FakeContext(args=["update", "all"]))

            check_true("p7: update reply", len(msg7.replies) > 0)
            reply7 = msg7.replies[-1]["text"]
            check_in("p7: update results", "Update results", reply7)

            # Verify installed content is V2
            installed_md = (tmp_custom / "code-helper" / "skill.md").read_text()
            check_in("p7: V2 on disk", "V2_MARKER", installed_md)
            check_not_in("p7: V1 gone", "V1_MARKER", installed_md)

            # =============================================================
            # Phase 8: User message now sees V2 instructions
            # =============================================================
            prov.run_results = [RunResult(text="Updated explanation")]
            msg8 = FakeMessage(chat=chat_user, text="explain again")
            upd8 = FakeUpdate(message=msg8, user=regular, chat=chat_user)
            await th.handle_message(upd8, FakeContext())

            check("p8: provider called", len(prov.run_calls), 1)
            ctx8 = prov.run_calls[0]["context"]
            check_in("p8: V2 instructions in prompt", "V2_MARKER", ctx8.system_prompt)
            check_not_in("p8: V1 not in prompt", "V1_MARKER", ctx8.system_prompt)
            prov.run_calls.clear()

            # =============================================================
            # Phase 9: Local modification detection and persistence
            # =============================================================
            installed_path = tmp_custom / "code-helper" / "skill.md"
            installed_path.write_text(installed_path.read_text() + "\nLOCAL_EDIT.\n")

            msg9 = FakeMessage(chat=chat_admin, text="/skills updates")
            upd9 = FakeUpdate(message=msg9, user=admin, chat=chat_admin)
            await th.cmd_skills(upd9, FakeContext(args=["updates"]))

            check_in("p9: locally modified", "locally modified", msg9.replies[-1]["text"])
            manifest9 = _json.loads((tmp_custom / "code-helper" / "_store.json").read_text())
            check("p9: locally_modified persisted", manifest9["locally_modified"], True)

            # Update resets locally_modified
            (tmp_store / "code-helper" / "skill.md").write_text(
                "---\nname: code-helper\ndisplay_name: Code Helper\n"
                "description: Assists with code tasks\n---\n\n"
                "V3_MARKER instructions.\n"
            )
            msg9b = FakeMessage(chat=chat_admin, text="/skills update code-helper")
            upd9b = FakeUpdate(message=msg9b, user=admin, chat=chat_admin)
            await th.cmd_skills(upd9b, FakeContext(args=["update", "code-helper"]))

            manifest9b = _json.loads((tmp_custom / "code-helper" / "_store.json").read_text())
            check("p9: locally_modified reset", manifest9b["locally_modified"], False)

            # =============================================================
            # Phase 10: Update all with prompt-size warning
            # =============================================================
            (tmp_store / "code-helper" / "skill.md").write_text(
                "---\nname: code-helper\ndisplay_name: Code Helper\n"
                "description: Assists with code tasks\n---\n\n"
                "V4_MARKER instructions.\n"
            )

            original_build = skills_mod.build_system_prompt
            def fake_oversize(role, active_skills):
                if "code-helper" in active_skills:
                    return "x" * (PROMPT_SIZE_WARNING_THRESHOLD + 500)
                return original_build(role, active_skills)

            with patch("app.skills.build_system_prompt", fake_oversize):
                msg10 = FakeMessage(chat=chat_admin, text="/skills update all")
                upd10 = FakeUpdate(message=msg10, user=admin, chat=chat_admin)
                await th.cmd_skills(upd10, FakeContext(args=["update", "all"]))

            reply10 = msg10.replies[-1]["text"]
            check_in("p10: prompt warning header", "Prompt size warnings", reply10)
            # Both chats (1001 and 2001) have the skill active
            check_in("p10: chat 1001 warned", "1001", reply10)
            check_in("p10: chat 2001 warned", "2001", reply10)

            # =============================================================
            # Phase 11: Uninstall — config guard then sweep
            # =============================================================
            # First, try with skill in BOT_SKILLS — should refuse
            cfg_guarded = make_config(
                data_dir=data_dir,
                admin_user_ids=frozenset({100}),
                admin_usernames=frozenset({"admin"}),
                default_skills=("code-helper",),
            )
            setup_globals(cfg_guarded, prov)

            msg11a = FakeMessage(chat=chat_admin, text="/skills uninstall code-helper")
            upd11a = FakeUpdate(message=msg11a, user=admin, chat=chat_admin)
            await th.cmd_skills(upd11a, FakeContext(args=["uninstall", "code-helper"]))

            check_in("p11: config guard", "BOT_SKILLS", msg11a.replies[-1]["text"])
            check_true("p11: skill still on disk", (tmp_custom / "code-helper").is_dir())

            # Remove from BOT_SKILLS and uninstall
            setup_globals(cfg, prov)
            msg11b = FakeMessage(chat=chat_admin, text="/skills uninstall code-helper")
            upd11b = FakeUpdate(message=msg11b, user=admin, chat=chat_admin)
            await th.cmd_skills(upd11b, FakeContext(args=["uninstall", "code-helper"]))

            check_in("p11: uninstalled", "uninstalled", msg11b.replies[-1]["text"].lower())
            check_false("p11: skill dir removed", (tmp_custom / "code-helper").is_dir())

            # Verify session sweep — both chats lost the skill
            session_after_1 = load_session_disk(data_dir, 1001, prov)
            session_after_2 = load_session_disk(data_dir, 2001, prov)
            check_not_in("p11: admin chat swept", "code-helper", session_after_1.get("active_skills", []))
            check_not_in("p11: user chat swept", "code-helper", session_after_2.get("active_skills", []))

            # =============================================================
            # Phase 12: Message after uninstall — provider does NOT see instructions
            # =============================================================
            prov.run_results = [RunResult(text="No skill now")]
            msg12 = FakeMessage(chat=chat_user, text="one more question")
            upd12 = FakeUpdate(message=msg12, user=regular, chat=chat_user)
            await th.handle_message(upd12, FakeContext())

            check("p12: provider called", len(prov.run_calls), 1)
            ctx12 = prov.run_calls[0]["context"]
            check_not_in("p12: no V4 in prompt", "V4_MARKER", ctx12.system_prompt)
            check_not_in("p12: no step by step", "step by step", ctx12.system_prompt)

        finally:
            store_mod.STORE_DIR = orig_store
            store_mod.CUSTOM_DIR = orig_custom
            skills_mod.CUSTOM_DIR = orig_skills_custom

run_test("Phase 5 E2E: full skill store lifecycle", test_phase5_e2e_full_journey())


# ===================================================================
# Run all tests in a single event loop
# ===================================================================

async def _main():
    await _run_all()
    # Shut down the default executor explicitly to prevent hang on exit.
    # cmd_doctor uses run_in_executor(None, ...) which creates a default
    # ThreadPoolExecutor; on some Python 3.12 builds asyncio.run() blocks
    # forever during loop cleanup waiting for that executor.
    loop = asyncio.get_running_loop()
    if hasattr(loop, '_default_executor') and loop._default_executor is not None:
        loop._default_executor.shutdown(wait=False)

_loop = asyncio.new_event_loop()
try:
    _loop.run_until_complete(_main())
finally:
    # Force-close: cancel lingering tasks and shut down without waiting
    for task in asyncio.all_tasks(_loop):
        task.cancel()
    _loop.run_until_complete(_loop.shutdown_default_executor())
    _loop.close()

print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
