"""Handler integration tests for rate limiting."""

from app.providers.base import RunResult
from app.storage import default_session, save_session
from app.identity import telegram_actor_key, telegram_conversation_key, telegram_event_id
from tests.support.handler_support import (
    FakeChat,
    FakeProvider,
    FakeUser,
    drain_one_worker_item,
    last_reply,
    make_config,
    send_text,
    setup_globals,
    fresh_data_dir,
)


async def test_rate_limit_blocks_after_threshold():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, rate_limit_per_minute=2, rate_limit_per_hour=0)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        user = FakeUser(42)

        msg1 = await send_text(chat, user, "first")
        await drain_one_worker_item(data_dir)
        msg2 = await send_text(chat, user, "second")
        await drain_one_worker_item(data_dir)
        msg3 = await send_text(chat, user, "third")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 2
        all_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg3.replies)
        assert "Rate limit" in all_replies
        assert "seconds" in all_replies


async def test_rate_limit_admin_exempt():
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            admin_actor_keys=frozenset({"tg:42"}),
            admin_users_explicit=True,
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        admin = FakeUser(42)

        await send_text(chat, admin, "first")
        await drain_one_worker_item(data_dir)
        await send_text(chat, admin, "second")
        await drain_one_worker_item(data_dir)
        await send_text(chat, admin, "third")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 3


async def test_rate_limit_disabled_by_default():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir)  # defaults: per_minute=0, per_hour=0
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 10
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        user = FakeUser(42)

        for i in range(5):
            await send_text(chat, user, f"msg {i}")
            await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 5


async def test_rate_limit_per_user_isolation():
    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, rate_limit_per_minute=1)
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 10
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        user_a = FakeUser(100)
        user_b = FakeUser(200)

        await send_text(chat, user_a, "hello")
        await drain_one_worker_item(data_dir)
        await send_text(chat, user_b, "hello")
        await drain_one_worker_item(data_dir)
        msg_a2 = await send_text(chat, user_a, "again")
        await drain_one_worker_item(data_dir)
        msg_b2 = await send_text(chat, user_b, "again")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 2
        a2_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg_a2.replies)
        b2_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg_b2.replies)
        assert "Rate limit" in a2_replies
        assert "Rate limit" in b2_replies


async def test_rate_limit_implicit_admin_not_exempt():
    """When BOT_ADMIN_USERS is not set, the fallback makes everyone admin,
    but rate limiting should still apply since admin was not explicit."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            allowed_actor_keys=frozenset({"tg:42"}),
            admin_actor_keys=frozenset({"tg:42"}),  # same as allowed (fallback)
            admin_users_explicit=False,       # not explicitly set
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        user = FakeUser(42)

        await send_text(chat, user, "first")
        await drain_one_worker_item(data_dir)
        msg2 = await send_text(chat, user, "second")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 1
        all_replies = " ".join(r.get("text", r.get("edit_text", "")) for r in msg2.replies)
        assert "Rate limit" in all_replies


async def test_rate_limit_explicit_admin_equal_to_allowed_still_exempt():
    """If operator explicitly sets BOT_ADMIN_USERS equal to BOT_ALLOWED_USERS,
    admins should be exempt from rate limiting."""
    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            rate_limit_per_minute=1,
            allowed_actor_keys=frozenset({"tg:42"}),
            admin_actor_keys=frozenset({"tg:42"}),
            admin_users_explicit=True,  # explicitly set
        )
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")] * 5
        setup_globals(cfg, prov)

        session = default_session("claude", prov.new_provider_state("tg:test"), "off")
        save_session(data_dir, telegram_conversation_key(1), session)

        chat = FakeChat(1)
        user = FakeUser(42)

        await send_text(chat, user, "first")
        await drain_one_worker_item(data_dir)
        await send_text(chat, user, "second")
        await drain_one_worker_item(data_dir)

        assert len(prov.run_calls) == 2
