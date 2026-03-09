"""Handler integration tests for rate limiting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.providers.base import RunResult
from app.storage import default_session, save_session
from tests.support.assertions import Checks
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    last_reply,
    make_config,
    send_text,
    setup_globals,
    test_data_dir,
)

checks = Checks()
run_test = checks.add_test


async def test_rate_limit_blocks_after_threshold():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, rate_limit_per_minute=2, rate_limit_per_hour=0)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        msg1 = await send_text(chat, user, "first")
        msg2 = await send_text(chat, user, "second")
        msg3 = await send_text(chat, user, "third")

        checks.check("provider called twice", len(prov.run_calls), 2)
        all_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg3.replies)
        checks.check_in("rate limit message", "Rate limit", all_replies)
        checks.check_in("retry seconds in message", "seconds", all_replies)


run_test("rate limit blocks after threshold", test_rate_limit_blocks_after_threshold())


async def test_rate_limit_admin_exempt():
    with test_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            admin_user_ids=frozenset({42}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        admin = FakeUser(42)

        await send_text(chat, admin, "first")
        await send_text(chat, admin, "second")
        await send_text(chat, admin, "third")

        checks.check("admin not rate limited", len(prov.run_calls), 3)


run_test("rate limit admin exempt", test_rate_limit_admin_exempt())


async def test_rate_limit_disabled_by_default():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir)  # defaults: per_minute=0, per_hour=0
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 10
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        for i in range(5):
            await send_text(chat, user, f"msg {i}")

        checks.check("all 5 requests went through", len(prov.run_calls), 5)


run_test("rate limit disabled by default", test_rate_limit_disabled_by_default())


async def test_rate_limit_per_user_isolation():
    with test_data_dir() as data_dir:
        cfg = make_config(data_dir, rate_limit_per_minute=1)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 10
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user_a = FakeUser(100)
        user_b = FakeUser(200)

        await send_text(chat, user_a, "hello")
        await send_text(chat, user_b, "hello")
        msg_a2 = await send_text(chat, user_a, "again")
        msg_b2 = await send_text(chat, user_b, "again")

        checks.check("2 provider calls (one per user)", len(prov.run_calls), 2)
        a2_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg_a2.replies)
        b2_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg_b2.replies)
        checks.check_in("user a blocked", "Rate limit", a2_replies)
        checks.check_in("user b blocked", "Rate limit", b2_replies)


run_test("rate limit per-user isolation", test_rate_limit_per_user_isolation())




async def test_rate_limit_implicit_admin_not_exempt():
    """When BOT_ADMIN_USERS is not set, the fallback makes everyone admin,
    but rate limiting should still apply since admin was not explicit."""
    with test_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            allowed_user_ids=frozenset({42}),
            admin_user_ids=frozenset({42}),  # same as allowed (fallback)
            admin_users_explicit=False,       # not explicitly set
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        await send_text(chat, user, "first")
        msg2 = await send_text(chat, user, "second")

        checks.check("implicit admin still rate limited", len(prov.run_calls), 1)
        all_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg2.replies)
        checks.check_in("rate limit message shown", "Rate limit", all_replies)


run_test("implicit admin not rate limit exempt", test_rate_limit_implicit_admin_not_exempt())


async def test_rate_limit_explicit_admin_equal_to_allowed_still_exempt():
    """If operator explicitly sets BOT_ADMIN_USERS equal to BOT_ALLOWED_USERS,
    admins should be exempt from rate limiting."""
    with test_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            allowed_user_ids=frozenset({42}),
            admin_user_ids=frozenset({42}),
            admin_users_explicit=True,  # explicitly set
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        await send_text(chat, user, "first")
        await send_text(chat, user, "second")

        checks.check("explicit admin exempt even if equal sets", len(prov.run_calls), 2)


run_test("explicit admin equal sets still exempt", test_rate_limit_explicit_admin_equal_to_allowed_still_exempt())

if __name__ == "__main__":
    checks.run_async_and_exit()
