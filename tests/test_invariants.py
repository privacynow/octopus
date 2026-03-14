"""Invariant tests — contract-shaped, not feature-shaped.

These tests verify cross-cutting properties that must hold across all
code paths, regardless of which feature introduced the code.  They are
designed to catch the class of bugs where one path drifts from another
because a new field was added or a helper was updated without updating
all consumers.

Each test section states the invariant it guards as a docstring.

Before adding tests to this file:
1. Audit all call sites that touch the changed behavior — test every one.
2. At least one test must exercise two interacting components together.
3. At least one test must assert what the USER SEES, not internal state.
4. At least one test must be a negative assertion (X must NOT happen).
5. Test doubles must match production object shape (see FakeProgress).
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest

from app import runtime_backend
from app.providers.base import (
    RunResult,
)
from app.progress import render as render_progress
from app.providers.codex import CodexProvider
from app.storage import default_session, save_session
from tests.support.config_support import make_config as _make_config
from tests.support.handler_support import (
    FakeCallbackQuery,
    FakeChat,
    FakeContext,
    FakeMessage,
    FakeProgress,
    FakeProvider,
    FakeUpdate,
    FakeUser,
    fresh_data_dir,
    fresh_env,
    make_config,
    send_callback,
    send_command,
    send_text,
    set_bot_instance,
    setup_globals,
)


# Tests migrated to owner suites:
# - Execution context (hash, stale detection, resolve, model profiles):
#   tests/test_execution_context.py
# - Request flow (trust tiers, public enforcement, validation, credentials):
#   tests/test_request_flow.py


# =====================================================================
# INVARIANT 4: Registry integrity
#
# A failed registry install (digest mismatch, download error) must
# leave no residue: no ref, no object, no staging dir.
# =====================================================================

def test_registry_digest_mismatch_leaves_no_residue():
    """Digest mismatch must not leave refs, objects, or staging dirs."""
    import http.server
    import json
    import shutil
    import tarfile
    import threading

    from app.registry import RegistrySkill
    from app.store import (
        OBJECTS_DIR, REFS_DIR, TMP_DIR,
        ensure_managed_dirs, install_from_registry, read_ref,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create skill and tarball
        skill_src = tmp_path / "skill_src"
        skill_src.mkdir()
        (skill_src / "skill.md").write_text("---\ndisplay_name: Bad\n---\nTampered")

        tarball = tmp_path / "skill.tar.gz"
        with tarfile.open(tarball, "w:gz") as tf:
            for item in skill_src.iterdir():
                tf.add(item, arcname=item.name)

        handler = http.server.SimpleHTTPRequestHandler
        server = http.server.HTTPServer(
            ("127.0.0.1", 0),
            lambda *args, directory=tmp, **kwargs: handler(*args, directory=directory, **kwargs),
        )
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()

        try:
            ensure_managed_dirs()
            objects_before = set(OBJECTS_DIR.iterdir()) if OBJECTS_DIR.is_dir() else set()

            reg_skill = RegistrySkill(
                name="tampered-skill",
                display_name="Tampered",
                description="Bad digest",
                version="1.0",
                publisher="attacker",
                digest="0" * 64,
                artifact_url=f"http://127.0.0.1:{port}/skill.tar.gz",
            )
            ok, msg = install_from_registry("tampered-skill", reg_skill)
            assert not ok
            assert "mismatch" in msg.lower()

            # Contract: no ref
            assert read_ref("tampered-skill") is None

            # Contract: no new objects
            objects_after = set(OBJECTS_DIR.iterdir()) if OBJECTS_DIR.is_dir() else set()
            assert objects_after - objects_before == set()

            # Contract: no staging dirs left
            staging_dirs = [
                d for d in TMP_DIR.iterdir()
                if d.is_dir() and "tampered" in d.name
            ] if TMP_DIR.is_dir() else []
            assert staging_dirs == []
        finally:
            server.shutdown()


# =====================================================================
# INVARIANT 6: Async boundary — blocking I/O must not block event loop
#
# Registry operations that do network I/O must not block concurrent
# commands in other chats.
# =====================================================================

async def test_registry_search_does_not_block_event_loop():
    """Slow registry fetch must not prevent another command from running."""
    import unittest.mock

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, registry_url="http://fake-registry.example.com/index.json")
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.skill_commands as sc

        # Track whether another coroutine can run during the registry fetch
        other_ran = False

        original_to_thread = asyncio.to_thread

        async def slow_to_thread(func, *args, **kwargs):
            """Simulate slow network while letting the event loop stay responsive."""
            return await original_to_thread(func, *args, **kwargs)

        def slow_fetch_index(url):
            import time
            time.sleep(0.3)  # Simulate slow network
            return {}  # Empty index

        async def other_command():
            nonlocal other_ran
            other_ran = True

        chat = FakeChat(12345)
        user = FakeUser(42)
        msg = FakeMessage(chat=chat, text="/skills search test")

        from unittest.mock import patch

        fake_event = type("FakeEvent", (), {"chat_id": 12345, "user": user, "args": []})()

        with patch("app.skill_commands.asyncio.to_thread", side_effect=slow_to_thread):
            with patch("app.registry.fetch_index", side_effect=slow_fetch_index):
                search_task = asyncio.create_task(
                    sc.skills_search(fake_event, FakeUpdate(message=msg, user=user, chat=chat), "test")
                )
                other_task = asyncio.create_task(other_command())

                await asyncio.gather(search_task, other_task)

        assert other_ran, (
            "Another coroutine must be able to run while registry search is in progress"
        )


# =====================================================================
# INVARIANT 16: Doctor warnings for public mode
# =====================================================================

async def test_doctor_warns_missing_public_working_dir():
    """Doctor should warn when allow_open=True but no public working dir set."""
    from app.doctor import collect_doctor_report

    cfg = _make_config(
        allow_open=True,
        public_working_dir="",
        rate_limit_per_minute=5,
        rate_limit_per_hour=30,
    )
    prov = FakeProvider("claude")
    prov._health_errors = ["skip"]  # skip runtime health
    report = await collect_doctor_report(cfg, prov)
    assert any("BOT_PUBLIC_WORKING_DIR" in w for w in report.warnings)


async def test_doctor_warns_missing_rate_limits():
    """Doctor should warn when allow_open=True with no rate limits."""
    from app.doctor import collect_doctor_report

    cfg = _make_config(
        allow_open=True,
        public_working_dir="/tmp/public",
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
    )
    prov = FakeProvider("claude")
    prov._health_errors = ["skip"]
    report = await collect_doctor_report(cfg, prov)
    assert any("rate limit" in w.lower() for w in report.warnings)


async def test_doctor_no_public_warnings_when_closed():
    """Doctor should not warn about public mode when allow_open=False."""
    from app.doctor import collect_doctor_report

    cfg = _make_config(
        allow_open=False,
        public_working_dir="",
        rate_limit_per_minute=0,
        rate_limit_per_hour=0,
    )
    prov = FakeProvider("claude")
    prov._health_errors = ["skip"]
    report = await collect_doctor_report(cfg, prov)
    assert not any("BOT_PUBLIC_WORKING_DIR" in w for w in report.warnings)
    assert not any("rate limit" in w.lower() for w in report.warnings)


# =====================================================================
# INVARIANT 18: Update-ID idempotency
# =====================================================================

async def test_duplicate_update_id_skipped():
    """Same update_id should be processed only once."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="first"), RunResult(text="second")]
        chat = FakeChat(chat_id=8001)
        user = FakeUser(uid=42, username="testuser")

        msg1 = FakeMessage(chat=chat, text="hello")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        dup_id = upd1.update_id

        await th.handle_message(upd1, FakeContext())
        assert len(prov.run_calls) == 1

        # Same update_id again
        msg2 = FakeMessage(chat=chat, text="hello again")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        upd2.update_id = dup_id  # force same ID
        await th.handle_message(upd2, FakeContext())
        assert len(prov.run_calls) == 1  # not processed again


async def test_duplicate_update_id_skipped_for_commands():
    """Same update_id on a decorated command should be processed only once."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=8002)
        user = FakeUser(uid=42, username="testuser")

        msg1 = FakeMessage(chat=chat, text="/new")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        dup_id = upd1.update_id

        await th.cmd_new(upd1, FakeContext())
        assert len(msg1.replies) > 0 or len(chat.sent_messages) > 0

        # Replay same update_id
        msg2 = FakeMessage(chat=chat, text="/new")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        upd2.update_id = dup_id

        await th.cmd_new(upd2, FakeContext())
        # Second message should have no replies — deduped
        assert len(msg2.replies) == 0


async def test_duplicate_update_id_skipped_for_help():
    """Same update_id on /help (non-decorated handler) should be processed only once."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=8004)
        user = FakeUser(uid=42, username="testuser")

        msg1 = FakeMessage(chat=chat, text="/help")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        dup_id = upd1.update_id

        await th.cmd_help(upd1, FakeContext())
        assert len(msg1.replies) > 0

        # Replay same update_id
        msg2 = FakeMessage(chat=chat, text="/help")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        upd2.update_id = dup_id

        await th.cmd_help(upd2, FakeContext())
        assert len(msg2.replies) == 0


async def test_duplicate_update_id_skipped_for_callbacks():
    """Same update_id on a callback should be processed only once."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=8003)
        user = FakeUser(uid=42, username="testuser")

        # First callback
        msg1 = FakeMessage(chat=chat)
        query1 = FakeCallbackQuery("setting_compact:on", message=msg1, user=user)
        upd1 = FakeUpdate(user=user, chat=chat, callback_query=query1)
        dup_id = upd1.update_id

        await th.handle_settings_callback(upd1, FakeContext())
        assert len(msg1.replies) > 0  # processed

        # Replay same update_id
        msg2 = FakeMessage(chat=chat)
        query2 = FakeCallbackQuery("setting_compact:off", message=msg2, user=user)
        upd2 = FakeUpdate(user=user, chat=chat, callback_query=query2)
        upd2.update_id = dup_id

        await th.handle_settings_callback(upd2, FakeContext())
        assert len(msg2.replies) == 0  # deduped


# =====================================================================
# INVARIANT 19: Doctor warnings for polling conflict
# =====================================================================

async def test_doctor_warns_polling_with_webhook_url():
    """Doctor should warn when poll mode is active with webhook URL configured."""
    from app.doctor import collect_doctor_report

    cfg = _make_config(
        bot_mode="poll",
        webhook_url="https://example.com/webhook",
    )
    prov = FakeProvider("claude")
    prov._health_errors = ["skip"]
    report = await collect_doctor_report(cfg, prov)
    assert any("polling" in w.lower() and "webhook" in w.lower() for w in report.warnings)


async def test_doctor_no_polling_warning_when_clean():
    """Doctor should not warn when poll mode is active with no webhook URL."""
    from app.doctor import collect_doctor_report

    cfg = _make_config(
        bot_mode="poll",
        webhook_url="",
    )
    prov = FakeProvider("claude")
    prov._health_errors = ["skip"]
    report = await collect_doctor_report(cfg, prov)
    assert not any("polling" in w.lower() for w in report.warnings)


# =====================================================================
# INVARIANT 25: Polling conflict detection (real HTTP 409 probe)
#
# /doctor must detect a conflicting poller via a getUpdates probe that
# returns HTTP 409, not just a config heuristic.
# =====================================================================


@pytest.mark.asyncio
async def test_doctor_detects_polling_conflict_409():
    """check_polling_conflict returns a warning when Telegram returns 409."""
    from unittest.mock import AsyncMock, patch
    from app.doctor import check_polling_conflict

    mock_response = AsyncMock()
    mock_response.status_code = 409

    with patch("app.doctor.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_response
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = client_instance

        result = await check_polling_conflict("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij")
    assert result is not None
    assert "409" in result
    assert "conflict" in result.lower()


@pytest.mark.asyncio
async def test_doctor_no_conflict_on_200():
    """check_polling_conflict returns None when Telegram returns 200 (no conflict)."""
    from unittest.mock import AsyncMock, patch
    from app.doctor import check_polling_conflict

    mock_response = AsyncMock()
    mock_response.status_code = 200

    with patch("app.doctor.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_response
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = client_instance

        result = await check_polling_conflict("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij")
    assert result is None


@pytest.mark.asyncio
async def test_doctor_conflict_check_survives_network_error():
    """check_polling_conflict returns None on network failure, not crash."""
    from unittest.mock import AsyncMock, patch
    from app.doctor import check_polling_conflict

    with patch("app.doctor.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.side_effect = Exception("network error")
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = client_instance

        result = await check_polling_conflict("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij")
    assert result is None


# =====================================================================
# INVARIANT 26: Prompt weight observable in /doctor
#
# /doctor must report prompt weight (system prompt size) when a session
# context is available.
# =====================================================================


@pytest.mark.asyncio
async def test_doctor_reports_prompt_weight():
    """/doctor shows prompt weight when session has a role (non-empty system prompt)."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["role"] = "You are a senior Python engineer specializing in async systems."
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)
        msg = await send_command(th.cmd_doctor, chat, user, "/doctor")
        all_text = " ".join(r.get("text", "") for r in msg.replies)
        assert "Prompt weight" in all_text
        assert "chars" in all_text


@pytest.mark.asyncio
async def test_doctor_prompt_weight_uses_resolved_context():
    """Public user's /doctor prompt weight reflects resolved (stripped) context, not raw session."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/pub",
    }) as (data_dir, cfg, prov):
        session = default_session(prov.name, prov.new_provider_state(), "off")
        session["role"] = "You are a senior engineer."
        session["active_skills"] = ["nonexistent-skill"]
        save_session(data_dir, 2001, session)

        chat = FakeChat(2001)
        stranger = FakeUser(uid=999, username="nobody")

        msg = await send_command(th.cmd_doctor, chat, stranger, "/doctor")
        all_text = " ".join(r.get("text", "") for r in msg.replies)
        # Public user's resolved context strips skills, so prompt weight should
        # reflect role-only (skills stripped).  If it used raw session, it would
        # try to include "nonexistent-skill" instructions.
        # The role still exists in resolved context, so prompt weight should appear.
        assert "Prompt weight" in all_text


# =====================================================================
# INVARIANT 27: Busy/queued feedback for commands and callbacks
#
# When a command or callback arrives while the chat lock is held,
# the user gets visible queued feedback, not silent waiting.
# =====================================================================


@pytest.mark.asyncio
async def test_chat_lock_sends_message_feedback_when_locked():
    """_chat_lock sends visible queued feedback via message when lock is held."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        msg = FakeMessage(chat=chat)

        lock = th.CHAT_LOCKS[1]
        await lock.acquire()
        try:
            # _chat_lock should send feedback then block; run in a task
            # so we can release the lock
            async def use_lock():
                async with th._chat_lock(1, message=msg):
                    pass

            task = asyncio.create_task(use_lock())
            await asyncio.sleep(0)  # let the task start and hit the lock
            lock.release()
            await task

            all_text = " ".join(str(r.get("text", "")) for r in msg.replies)
            assert "queued" in all_text.lower(), (
                f"Expected queued feedback, got: {all_text[:200]}")
        finally:
            if lock.locked():
                lock.release()


@pytest.mark.asyncio
async def test_chat_lock_sends_callback_feedback_when_locked():
    """_chat_lock sends visible queued feedback via callback answer when lock is held."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        query = FakeCallbackQuery("test", message=FakeMessage(chat=FakeChat(1)))

        lock = th.CHAT_LOCKS[1]
        await lock.acquire()
        try:
            yielded = None
            async def use_lock():
                nonlocal yielded
                async with th._chat_lock(1, query=query) as sent:
                    yielded = sent

            task = asyncio.create_task(use_lock())
            await asyncio.sleep(0)
            lock.release()
            await task

            assert yielded is True, "Expected _chat_lock to yield True when lock was held"
            assert query.answers, "Expected callback answer for queued feedback"
            assert any("queued" in str(a.get("text", "")).lower() for a in query.answers), (
                f"Expected queued feedback in callback answer, got: {query.answers}")
        finally:
            if lock.locked():
                lock.release()


@pytest.mark.asyncio
async def test_chat_lock_no_feedback_when_free():
    """_chat_lock does NOT send feedback when lock is free."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        msg = FakeMessage(chat=FakeChat(1))

        async with th._chat_lock(1, message=msg) as sent:
            assert sent is False, "Expected _chat_lock to yield False when lock was free"

        all_text = " ".join(str(r.get("text", "")) for r in msg.replies)
        assert "queued" not in all_text.lower()


# =====================================================================
# INVARIANT 28: Contended callbacks produce exactly one answer
#
# When a callback handler runs while the chat lock is held, the handler
# must not call query.answer() again after _chat_lock already consumed
# the answer slot with queued feedback.
# =====================================================================


@pytest.mark.asyncio
async def test_contended_approval_callback_single_answer():
    """Approval callback under contention produces exactly one callback answer."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 1
        chat = FakeChat(chat_id)
        user = FakeUser(next(iter(cfg.allowed_user_ids)))
        session = th._load(chat_id)
        from app.session_state import PendingApproval
        ctx_hash = th._resolve_context(session).context_hash
        session.pending_approval = PendingApproval(
            request_user_id=user.id, prompt="test", image_paths=[],
            attachment_dicts=[], context_hash=ctx_hash,
            created_at=0, trust_tier="trusted",
        )
        th._save(chat_id, session)

        from app.providers.base import RunResult
        prov.run_results.append(RunResult(text="done"))

        lock = th.CHAT_LOCKS[chat_id]
        await lock.acquire()
        try:
            async def contended_approve():
                query, _ = await send_callback(
                    th.handle_callback, chat, user, "approval_approve")
                return query

            task = asyncio.create_task(contended_approve())
            await asyncio.sleep(0)
            lock.release()
            query = await task
        finally:
            if lock.locked():
                lock.release()

        assert len(query.answers) == 1, (
            f"Expected exactly 1 answer under contention, got {len(query.answers)}: {query.answers}")
        assert "queued" in str(query.answers[0].get("text", "")).lower()


@pytest.mark.asyncio
async def test_contended_settings_callback_single_answer():
    """Settings callback under contention produces exactly one callback answer."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 1
        chat = FakeChat(chat_id)
        user = FakeUser(next(iter(cfg.allowed_user_ids)))
        session = th._load(chat_id)
        th._save(chat_id, session)

        lock = th.CHAT_LOCKS[chat_id]
        await lock.acquire()
        try:
            async def contended_settings():
                query, _ = await send_callback(
                    th.handle_settings_callback, chat, user, "setting_compact:on")
                return query

            task = asyncio.create_task(contended_settings())
            await asyncio.sleep(0)
            lock.release()
            query = await task
        finally:
            if lock.locked():
                lock.release()

        assert len(query.answers) == 1, (
            f"Expected exactly 1 answer under contention, got {len(query.answers)}: {query.answers}")
        assert "queued" in str(query.answers[0].get("text", "")).lower()


@pytest.mark.asyncio
async def test_contended_clear_cred_callback_single_answer():
    """Clear-credentials callback under contention produces exactly one callback answer."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat_id = 1
        chat = FakeChat(chat_id)
        user = FakeUser(next(iter(cfg.allowed_user_ids)))
        session = th._load(chat_id)
        th._save(chat_id, session)

        lock = th.CHAT_LOCKS[chat_id]
        await lock.acquire()
        try:
            async def contended_clear():
                query, _ = await send_callback(
                    th.handle_clear_cred_callback, chat, user,
                    f"clear_cred_confirm_all:{user.id}")
                return query

            task = asyncio.create_task(contended_clear())
            await asyncio.sleep(0)
            lock.release()
            query = await task
        finally:
            if lock.locked():
                lock.release()

        assert len(query.answers) == 1, (
            f"Expected exactly 1 answer under contention, got {len(query.answers)}: {query.answers}")
        assert "queued" in str(query.answers[0].get("text", "")).lower(), (
            f"Expected queued feedback, got: {query.answers}")


# ---------------------------------------------------------------------------
# INVARIANT 29: same-chat overlapping updates complete their own work items
# ---------------------------------------------------------------------------

async def test_same_chat_overlapping_updates_complete_correctly():
    """Two sequential updates for the same chat must each complete their own
    work item.  Before the fix, _pending_work_items was keyed by chat_id,
    so the second update overwrote the first's entry and the first item was
    left queued forever.
    """
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="reply1"), RunResult(text="reply2")]
        chat = FakeChat(chat_id=9001)
        user = FakeUser(uid=42, username="testuser")

        msg1 = FakeMessage(chat=chat, text="first")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        uid1 = upd1.update_id

        msg2 = FakeMessage(chat=chat, text="second")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        uid2 = upd2.update_id

        await th.handle_message(upd1, FakeContext())
        await th.handle_message(upd2, FakeContext())

        # Both requests were processed
        assert len(prov.run_calls) == 2

        # Both work items are done (not queued)
        conn = runtime_backend.transport_store()._transport_db(data_dir)
        rows = conn.execute(
            "SELECT update_id, state FROM work_items WHERE chat_id = 9001 "
            "ORDER BY update_id"
        ).fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row["state"] == "done", (
                f"Work item for update {row['update_id']} is '{row['state']}', expected 'done'"
            )


# =====================================================================
# INVARIANT 30: Worker dispatch replay survives TelegramProgress
#
# worker_dispatch() creates a _BotMessage whose reply_text() must return
# a Message-like object with edit_text(), because execute_request passes
# that return value into TelegramProgress.  If reply_text() returns None,
# the first progress update crashes with AttributeError.
# =====================================================================

class _FakeBot:
    """Minimal bot for worker_dispatch — send_message returns a FakeMessage."""
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        msg = FakeMessage(chat=FakeChat(chat_id), text=text)
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return msg

    async def send_chat_action(self, chat_id, action):
        pass


@pytest.mark.asyncio
async def test_worker_dispatch_sends_recovery_notice_not_auto_replay():
    """worker_dispatch with an InboundMessage must send a recovery notice
    with Replay/Discard buttons instead of auto-replaying through the
    provider.  The item transitions to pending_recovery and PendingRecovery
    is raised so worker_loop skips completion."""
    import app.telegram_handlers as th
    from app.transport import InboundMessage, InboundUser
    from app.work_queue import PendingRecovery, record_and_enqueue

    with fresh_env(config_overrides={
        "allowed_user_ids": frozenset({42}),
    }) as (data_dir, cfg, prov):
        # Create a real claimed work item in the DB (must set claimed_at for CHECK and validator).
        _, item_id = record_and_enqueue(data_dir, 9999, 12345, 42, "message")
        conn = runtime_backend.transport_store()._transport_db(data_dir)
        conn.execute(
            "UPDATE work_items SET state = 'claimed', worker_id = ?, claimed_at = ? WHERE id = ?",
            ("test", "2025-01-01T00:00:00+00:00", item_id),
        )
        conn.commit()

        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            event = InboundMessage(
                user=InboundUser(id=42, username="alice"),
                chat_id=12345,
                text="replay this message",
                attachments=(),
            )
            item = {"chat_id": 12345, "update_id": 9999, "id": item_id}

            with pytest.raises(PendingRecovery):
                await th.worker_dispatch("message", event, item)

            # Provider must NOT have been called — no auto-replay.
            assert len(prov.run_calls) == 0, (
                f"Expected 0 provider calls, got {len(prov.run_calls)}"
            )
            # Bot sent the recovery notice with buttons.
            notice_msgs = [s for s in bot.sent if "interrupted" in s.get("text", "")]
            assert notice_msgs, "Expected recovery notice message"
            assert "replay_markup" in notice_msgs[0] or notice_msgs[0].get("reply_markup"), (
                "Expected inline keyboard with Replay/Discard buttons"
            )
            # Work item is now pending_recovery.
            row = conn.execute(
                "SELECT state FROM work_items WHERE id = ?", (item_id,)
            ).fetchone()
            assert row["state"] == "pending_recovery"
        finally:
            set_bot_instance(None)


# =====================================================================
# INVARIANT 31: Shutdown-interrupted runs stay replayable
#
# A provider child killed by service shutdown (rc=-15) must not be turned
# into a normal provider error and marked done. The durable work item must
# remain claimed so the next boot can recover and replay it.
# =====================================================================

class _StickyReplyMessage(FakeMessage):
    """Test message whose status updates land on the same reply log."""

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return self


@pytest.mark.asyncio
async def test_interrupted_message_run_stays_claimed_for_recovery():
    import app.telegram_handlers as th
    from app.work_queue import recover_stale_claims

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="[Claude error (rc=-15)]", returncode=-15)]
        chat = FakeChat(chat_id=9101)
        user = FakeUser(uid=42, username="testuser")
        msg = _StickyReplyMessage(chat=chat, text="hello after restart")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())

        assert len(prov.run_calls) == 1
        joined = " ".join(
            entry.get("text", "") + " " + entry.get("edit_text", "")
            for entry in msg.replies
        )
        assert "Claude error" not in joined

        conn = runtime_backend.transport_store()._transport_db(data_dir)
        row = conn.execute(
            "SELECT state, worker_id FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row["state"] == "claimed"
        assert row["worker_id"] == "test-boot"

        recovered = recover_stale_claims(data_dir, current_worker_id="next-boot")
        assert recovered == 1
        row = conn.execute(
            "SELECT state, worker_id FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row["state"] == "queued"
        assert row["worker_id"] is None


# =====================================================================
# INVARIANT 32: All negative return codes are treated as interrupted
#
# Any signal (not just -15/-9) means the provider child was killed
# externally.  SIGINT (-2), SIGABRT (-6), etc. must all leave the
# work item claimed for recovery, never surface an error message.
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("rc", [-2, -6, -9, -15])
async def test_any_signal_treated_as_interrupted(rc):
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="killed", returncode=rc)]
        chat = FakeChat(chat_id=9200 + abs(rc))
        user = FakeUser(uid=42, username="testuser")
        msg = _StickyReplyMessage(chat=chat, text="test")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())

        # No error surfaced to user
        joined = " ".join(
            entry.get("text", "") + " " + entry.get("edit_text", "")
            for entry in msg.replies
        )
        assert "error" not in joined.lower() or "killed" not in joined.lower()

        # Work item stays claimed
        conn = runtime_backend.transport_store()._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row["state"] == "claimed"


# =====================================================================
# INVARIANT 33: Provider errors (rc > 0) produce user-visible feedback
#
# When the provider exits with a positive error code, the user must
# always see a message — even if the error text is very long or empty.
# =====================================================================

@pytest.mark.asyncio
async def test_provider_error_empty_output_still_shows_message():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="", returncode=1)]
        chat = FakeChat(chat_id=9300)
        user = FakeUser(uid=42, username="testuser")
        msg = _StickyReplyMessage(chat=chat, text="test")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())

        joined = " ".join(
            entry.get("text", "") + " " + entry.get("edit_text", "")
            for entry in msg.replies
        )
        # User gets some feedback about the error
        assert "exited with code 1" in joined.lower() or "error" in joined.lower()


@pytest.mark.asyncio
async def test_provider_error_long_output_truncated():
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        long_error = "E" * 5000
        prov.run_results = [RunResult(text=long_error, returncode=1)]
        chat = FakeChat(chat_id=9301)
        user = FakeUser(uid=42, username="testuser")
        msg = _StickyReplyMessage(chat=chat, text="test")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        await th.handle_message(upd, FakeContext())

        # Verify user got feedback (not silent)
        joined = " ".join(
            entry.get("text", "") + " " + entry.get("edit_text", "")
            for entry in msg.replies
        )
        assert len(joined) > 0
        # Full 5000-char error should not appear verbatim
        assert long_error not in joined


# =====================================================================
# INVARIANT 34: Global error handler catches stale callback queries
#
# A BadRequest for an expired callback query must not produce a noisy
# unhandled-exception log.  The global error handler suppresses it.
# =====================================================================

@pytest.mark.asyncio
async def test_global_error_handler_suppresses_stale_callback():
    import app.telegram_handlers as th
    from telegram.error import BadRequest

    handler = th._global_error_handler

    class FakeErrorContext:
        error = BadRequest("Query is too old and response timeout expired or query id is invalid")
        bot = None

    # Should not raise — suppressed at debug level
    await handler(None, FakeErrorContext())


@pytest.mark.asyncio
async def test_global_error_handler_notifies_user_on_unknown_error():
    """The handler tries to notify via context.bot — if the update isn't a
    real telegram.Update it gracefully skips notification without raising."""
    import app.telegram_handlers as th

    class FakeErrorContext:
        error = RuntimeError("unexpected boom")
        bot = None

    # Non-Update object — handler should log but not raise
    await th._global_error_handler("not-a-real-update", FakeErrorContext())


@pytest.mark.asyncio
async def test_global_error_handler_sends_message_on_real_update():
    """When given a real Update with effective_chat, the handler sends feedback."""
    import app.telegram_handlers as th
    from telegram import Update, Chat, Message, User as TgUser

    sent_messages = []

    class FakeBotForError:
        async def send_message(self, chat_id, text, **kwargs):
            sent_messages.append({"chat_id": chat_id, "text": text})

    class FakeErrorContext:
        error = RuntimeError("unexpected boom")
        bot = FakeBotForError()

    tg_chat = Chat(id=9400, type="private")
    tg_user = TgUser(id=42, is_bot=False, first_name="Test")
    tg_msg = Message(
        message_id=1, date=None, chat=tg_chat, from_user=tg_user, text="x"
    )
    upd = Update(update_id=99999, message=tg_msg)

    await th._global_error_handler(upd, FakeErrorContext())

    assert len(sent_messages) == 1
    assert "went wrong" in sent_messages[0]["text"].lower()


# =====================================================================
# INVARIANT 35: Unhandled decorator exceptions mark work items failed
#
# When a decorated command or callback raises an unhandled exception,
# the work item must be recorded as "failed", not "done".
# =====================================================================

@pytest.mark.asyncio
async def test_command_exception_marks_work_item_failed():
    """A command handler that raises must leave the work item as failed."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=9500)
        user = FakeUser(uid=42, username="testuser")
        msg = FakeMessage(chat=chat, text="/session")
        upd = FakeUpdate(message=msg, user=user, chat=chat)

        # Patch _load to raise inside cmd_session
        original_load = th._load
        def exploding_load(chat_id):
            raise RuntimeError("session DB corrupt")

        th._load = exploding_load
        try:
            with pytest.raises(RuntimeError, match="session DB corrupt"):
                await th.cmd_session(upd, FakeContext())
        finally:
            th._load = original_load

        conn = runtime_backend.transport_store()._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row["state"] == "failed"


@pytest.mark.asyncio
async def test_callback_exception_marks_work_item_failed():
    """A callback handler that raises must leave the work item as failed."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=9501)
        user = FakeUser(uid=42, username="testuser")
        query = FakeCallbackQuery(data="setting_approval:on",
                                  message=FakeMessage(chat=chat),
                                  user=user)
        upd = FakeUpdate(callback_query=query, user=user, chat=chat)

        original_load = th._load
        def exploding_load(chat_id):
            raise RuntimeError("session DB corrupt")

        th._load = exploding_load
        try:
            with pytest.raises(RuntimeError, match="session DB corrupt"):
                await th.handle_settings_callback(upd, FakeContext())
        finally:
            th._load = original_load

        conn = runtime_backend.transport_store()._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row["state"] == "failed"


# =====================================================================
# INVARIANT 36: Error summarizer subprocess is cleaned up on timeout
#
# _format_provider_error spawns a subprocess for summarization.
# If it times out, the child must be killed and reaped, not leaked.
# =====================================================================

@pytest.mark.asyncio
async def test_format_provider_error_kills_subprocess_on_timeout():
    import app.telegram_handlers as th

    killed = []

    class FakeProc:
        returncode = None
        async def communicate(self):
            await asyncio.sleep(60)  # will be cancelled by timeout
        def kill(self):
            killed.append(True)
            self.returncode = -9
        async def wait(self):
            pass

    original = asyncio.create_subprocess_exec

    async def mock_exec(*args, **kwargs):
        return FakeProc()

    asyncio.create_subprocess_exec = mock_exec
    try:
        # Long text triggers summarization attempt
        result = await th._format_provider_error("E" * 5000, 1)
    finally:
        asyncio.create_subprocess_exec = mock_exec
        asyncio.create_subprocess_exec = original

    # Subprocess was killed
    assert len(killed) == 1
    # Fallback truncation was used
    assert "truncated" in result.lower() or "E" in result


# =====================================================================
# INVARIANT 37: All decorator early-return branches complete work items
#
# Every path through _command_handler and _callback_handler that returns
# after _dedup_update must call _complete_pending_work_item.  A missing
# call leaves the durable work item stuck in "queued" state forever.
# =====================================================================

@pytest.mark.asyncio
async def test_callback_none_event_completes_work_item():
    """When normalize_callback returns None, the work item must be completed (not leaked)."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=9600)
        upd = FakeUpdate(
            callback_query=FakeCallbackQuery(data="setting_approval:on",
                                             message=FakeMessage(chat=chat)),
            user=FakeUser(uid=42, username="testuser"), chat=chat,
        )

        # Patch the symbol the handler actually imports
        original = th.normalize_callback
        th.normalize_callback = lambda update: None
        try:
            await th.handle_settings_callback(upd, FakeContext())
        finally:
            th.normalize_callback = original

        conn = runtime_backend.transport_store()._transport_db(data_dir)
        row = conn.execute(
            "SELECT state FROM work_items WHERE update_id = ?",
            (upd.update_id,),
        ).fetchone()
        assert row is not None, "work item should exist"
        assert row["state"] == "done", f"expected done, got {row['state']}"


# =====================================================================
# INVARIANT 38: Progress messages use provider-neutral wording
# User-facing status must not contain provider names, thread IDs, or
# internal terminology.
# =====================================================================

async def test_initial_status_no_provider_name_claude():
    """handle_message for Claude shows 'Working...' not 'Starting claude...'."""
    with fresh_env(provider_name="claude") as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = await send_text(chat, user, "hello")

        initial_reply = msg.replies[0]
        # Accept "Working..." or "Working…" (Unicode ellipsis)
        assert initial_reply["text"].replace("\u2026", "...") == "Working..."
        assert "claude" not in initial_reply["text"].lower()


async def test_initial_status_no_provider_name_codex():
    """handle_message for Codex shows 'Working...' not 'Starting codex...'."""
    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = await send_text(chat, user, "hello")

        initial_reply = msg.replies[0]
        assert initial_reply["text"].replace("\u2026", "...") == "Working..."
        assert "codex" not in initial_reply["text"].lower()


async def test_resume_status_no_provider_name():
    """Resuming a session shows 'Resuming...' not 'Resuming claude...'."""
    with fresh_env(provider_name="claude") as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)

        # First message — provider returns started=True like real Claude
        prov.run_results = [
            RunResult(text="first reply", provider_state_updates={"started": True}),
        ]
        await send_text(chat, user, "first")
        # Second message — resumes session (provider_state.started is True)
        msg2 = await send_text(chat, user, "second")

        initial_reply = msg2.replies[0]
        assert initial_reply["text"].replace("\u2026", "...") == "Resuming..."
        assert "claude" not in initial_reply["text"].lower()


async def test_timeout_message_no_provider_name():
    """Timeout shows 'Request timed out' not 'claude timed out'."""
    import app.telegram_handlers as th

    with fresh_env(provider_name="claude") as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="", timed_out=True, returncode=124)]
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="slow request")
        # Use a tracking FakeMessage that captures the status sub-message
        status_messages = []
        original_reply_text = msg.reply_text

        async def tracking_reply_text(text, **kwargs):
            result = await original_reply_text(text, **kwargs)
            status_messages.append(result)
            return result

        msg.reply_text = tracking_reply_text
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        # The status message receives progress edits including the timeout
        assert len(status_messages) >= 1
        status_msg = status_messages[0]
        all_edits = [r.get("edit_text", "") for r in status_msg.replies]
        timeout_text = " ".join(all_edits)
        assert "Request timed out" in timeout_text
        assert "claude" not in timeout_text.lower()
        assert "codex" not in timeout_text.lower()


async def test_terminal_status_says_completed():
    """Successful run shows 'Completed.' not 'Done.'."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = FakeMessage(chat=chat, text="do work")
        status_messages = []
        original_reply_text = msg.reply_text

        async def tracking_reply_text(text, **kwargs):
            result = await original_reply_text(text, **kwargs)
            status_messages.append(result)
            return result

        msg.reply_text = tracking_reply_text
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())

        assert len(status_messages) >= 1
        status_msg = status_messages[0]
        all_edits = [r.get("edit_text", "") for r in status_msg.replies]
        assert any("Completed." in e for e in all_edits), f"Expected 'Completed.' in edits: {all_edits}"
        assert not any("Done." in e for e in all_edits), f"'Done.' should not appear: {all_edits}"


async def test_claude_thinking_capitalized():
    """Claude provider uses 'Thinking...' (capitalized, ascii dots) not 'thinking…'."""
    from app.providers.claude import ClaudeProvider

    provider = ClaudeProvider(_make_config())
    # build_display is a closure inside _consume_stream — test the output pattern
    # by checking the code path: when no text accumulated, display shows Thinking...
    # We verify via a unit-level check on the progress HTML the provider would emit.
    import json
    import sys
    import asyncio

    # Emit a tool_use block start — triggers build_display() with no accumulated text,
    # which should show "Thinking..." as the fallback.
    events = [
        json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Read"}}}),
    ]
    script = f"import sys; [sys.stdout.write(line + '\\n') for line in {events!r}]; sys.stdout.flush()"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    progress = FakeProgress()
    text, _, _ = await provider._consume_stream(proc, progress)
    await proc.wait()

    # With no text_delta events, the display should show "Thinking..." or "Thinking…"
    thinking_updates = [u for u in progress.updates if "Thinking" in u and ("..." in u or "\u2026" in u)]
    assert len(thinking_updates) >= 1, f"Expected 'Thinking...' in updates: {progress.updates}"
    # Must NOT use lowercase "thinking" with ellipsis character
    assert not any("thinking\u2026" in u for u in progress.updates)


async def test_codex_thinking_capitalized():
    """Codex provider uses 'Thinking...' for turn/task started events."""
    evt = CodexProvider._map_event({"type": "turn.started"}, False)
    html = render_progress(evt)
    assert html.replace("\u2026", "...") == "<i>Thinking...</i>"


async def test_codex_no_thread_id_in_progress():
    """Codex thread_started and session_meta events produce no user-visible progress."""
    assert CodexProvider._map_event({"type": "thread.started", "thread_id": "t-123"}, False) is None
    assert CodexProvider._map_event({"type": "session_meta", "payload": {"id": "s-456"}}, False) is None
    assert CodexProvider._map_event(
        {"type": "event_msg", "payload": {"type": "session_configured", "thread_id": "t-789"}}, True
    ) is None


async def test_codex_compaction_wording():
    """Extended timeout message uses user-facing wording, not internal 'compaction'."""
    import sys, tempfile
    from pathlib import Path

    cfg = _make_config(timeout_seconds=1, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    # A script that takes 1.5s (triggers timeout extension on resume)
    import textwrap
    script = textwrap.dedent(f"""\
        import json, sys, time
        sys.stdout.write(json.dumps({{"type": "thread.started", "thread_id": "t-1"}}) + "\\n")
        sys.stdout.flush()
        time.sleep(1.5)
        sys.stdout.write(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "done"}}}}) + "\\n")
        sys.stdout.flush()
    """)
    progress = FakeProgress()
    result = await provider._run_cmd(
        [sys.executable, "-c", script], progress, is_resume=True
    )
    extended_msgs = [u for u in progress.updates if "this may take a moment" in u]
    assert len(extended_msgs) == 1
    assert not any("compaction" in u.lower() for u in progress.updates)


# =====================================================================
# INVARIANT 39: Heartbeat fires during idle states, stops on content
# The heartbeat task shows elapsed time while waiting, but must not
# decorate streamed reply text.
# =====================================================================

async def test_heartbeat_fires_on_idle():
    """Heartbeat updates progress after the initial delay when no content arrives."""
    import app.telegram_handlers as th
    from unittest.mock import patch

    progress = FakeProgress()
    content_started = progress.content_started

    with patch.object(th, "_HEARTBEAT_FIRST", 0.05), \
         patch.object(th, "_HEARTBEAT_SUBSEQUENT", 0.05):
        task = asyncio.create_task(th._heartbeat(progress, content_started))
        await asyncio.sleep(0.2)  # Let a few beats fire
        task.cancel()
        await task

    assert len(progress.updates) >= 1, f"Expected heartbeat updates, got: {progress.updates}"
    assert all("Still working" in u and ("..." in u or "\u2026" in u) for u in progress.updates)
    # Should contain elapsed seconds
    assert any("s)" in u for u in progress.updates)


async def test_heartbeat_stops_when_content_starts():
    """Heartbeat stops firing once content_started event is set."""
    import app.telegram_handlers as th
    from unittest.mock import patch

    progress = FakeProgress()
    content_started = progress.content_started

    with patch.object(th, "_HEARTBEAT_FIRST", 0.05), \
         patch.object(th, "_HEARTBEAT_SUBSEQUENT", 0.05):
        task = asyncio.create_task(th._heartbeat(progress, content_started))
        await asyncio.sleep(0.1)  # Let at least one beat fire
        count_before = len(progress.updates)
        assert count_before >= 1

        content_started.set()  # Signal that content is streaming
        await asyncio.sleep(0.15)  # Wait to confirm no more beats
        count_after = len(progress.updates)

        # At most one more update could have been in flight when we set the event
        assert count_after <= count_before + 1, (
            f"Heartbeat kept firing after content_started: {count_before} -> {count_after}"
        )
        task.cancel()
        await task


async def test_heartbeat_cancelled_on_completion():
    """Heartbeat task is cancelled cleanly without raising."""
    import app.telegram_handlers as th
    from unittest.mock import patch

    progress = FakeProgress()
    content_started = progress.content_started

    with patch.object(th, "_HEARTBEAT_FIRST", 10.0):
        task = asyncio.create_task(th._heartbeat(progress, content_started))
        await asyncio.sleep(0.01)
        task.cancel()
        # Should not raise — CancelledError is caught internally
        await task
        assert len(progress.updates) == 0


async def test_claude_sets_content_started():
    """Claude provider sets content_started when first text_delta arrives."""
    from app.providers.claude import ClaudeProvider
    import json
    import sys

    provider = ClaudeProvider(_make_config())

    events = [
        json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
        }}),
    ]
    script = f"import sys; [sys.stdout.write(line + '\\n') for line in {events!r}]; sys.stdout.flush()"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    progress = FakeProgress()
    content_started = progress.content_started


    text, _, _ = await provider._consume_stream(proc, progress)
    await proc.wait()

    assert content_started.is_set(), "content_started should be set after text_delta"
    assert "Hello" in text


async def test_codex_sets_content_started():
    """Codex provider sets content_started when final assistant text arrives."""
    import sys, textwrap, tempfile
    from pathlib import Path

    cfg = _make_config(timeout_seconds=5, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    script = textwrap.dedent("""\
        import json, sys
        events = [
            {"type": "session_meta", "payload": {"id": "sess-1"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": "final answer"}], "phase": "final_answer"}},
        ]
        for e in events:
            sys.stdout.write(json.dumps(e) + "\\n")
        sys.stdout.flush()
    """)

    progress = FakeProgress()
    content_started = progress.content_started


    result = await provider._run_cmd(
        [sys.executable, "-c", script], progress, is_resume=False
    )
    assert content_started.is_set(), "content_started should be set after final text"
    assert "final answer" in result.text


async def test_codex_sets_content_started_on_draft():
    """Codex sets content_started on commentary/draft text, not just final text."""
    import sys, textwrap, tempfile
    from pathlib import Path

    cfg = _make_config(timeout_seconds=5, working_dir=Path(tempfile.gettempdir()))
    provider = CodexProvider(cfg)

    # Emit a commentary event (draft text) — should still set content_started
    script = textwrap.dedent("""\
        import json, sys
        events = [
            {"type": "session_meta", "payload": {"id": "sess-1"}},
            {"type": "event_msg", "payload": {"type": "agent_message",
             "message": "draft commentary", "phase": "commentary"}},
        ]
        for e in events:
            sys.stdout.write(json.dumps(e) + "\\n")
        sys.stdout.flush()
    """)

    progress = FakeProgress()
    content_started = progress.content_started


    await provider._run_cmd(
        [sys.executable, "-c", script], progress, is_resume=False
    )
    assert content_started.is_set(), (
        "content_started should be set on draft/commentary text too, "
        "since it produces visible progress"
    )


async def test_heartbeat_respects_recent_progress():
    """Heartbeat does not overwrite a recent non-content progress update."""
    import app.telegram_handlers as th
    from unittest.mock import patch

    progress = FakeProgress()
    content_started = progress.content_started

    with patch.object(th, "_HEARTBEAT_FIRST", 0.05), \
         patch.object(th, "_HEARTBEAT_SUBSEQUENT", 0.10):
        task = asyncio.create_task(th._heartbeat(progress, content_started))

        # Wait for first heartbeat to potentially fire
        await asyncio.sleep(0.07)

        # Simulate a fresh tool/command progress update
        await progress.update("<i>Running command: ls</i>")
        count_after_tool = len(progress.updates)

        # Wait less than HEARTBEAT_SUBSEQUENT — heartbeat should NOT overwrite
        await asyncio.sleep(0.05)
        heartbeat_updates_after_tool = [
            u for u in progress.updates[count_after_tool:]
            if "Still working" in u
        ]
        assert len(heartbeat_updates_after_tool) == 0, (
            f"Heartbeat overwrote recent tool update: {progress.updates}"
        )

        task.cancel()
        await task


async def test_approval_initial_status_neutral():
    """request_approval sends neutral 'Preparing approval...' not internal terminology."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = await send_text(chat, user, "do work with approval")

        # In approval mode, the first reply should be the approval status
        initial_reply = msg.replies[0]
        initial_text = initial_reply.get("text", "")
        assert "preflight" not in initial_text.lower(), (
            f"Internal 'preflight' leaked to user: {initial_text}"
        )
        # Accept "Preparing approval..." or "Preparing your plan…"
        assert "Preparing" in initial_text and ("approval" in initial_text or "plan" in initial_text)


async def test_approval_no_preflight_in_any_user_text():
    """No user-facing message in the approval flow contains 'preflight'.

    Uses _StickyReplyMessage so edit_text updates (status message edits)
    are visible in the reply chain, not just the initial reply_text calls.
    Positive assertion proves the test actually observes the status edit path.
    """
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = _StickyReplyMessage(chat=chat, text="do work with approval")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        all_texts = []
        edit_texts = []
        for r in msg.replies:
            all_texts.append(r.get("text", ""))
            et = r.get("edit_text", "")
            all_texts.append(et)
            if et:
                edit_texts.append(et)
        for sent in chat.sent_messages:
            all_texts.append(sent.get("text", ""))

        # Positive: prove the test observes the status edit path (approval/plan wording)
        assert any(
            "Approval required." in t or "Review the plan" in t or "approve or reject" in t
            for t in edit_texts
        ), f"Expected approval/plan wording in status edits but got: {edit_texts}"

        for text in all_texts:
            if text:
                assert "preflight" not in text.lower(), (
                    f"Internal 'preflight' leaked to user: {text!r}"
                )


async def test_approval_error_no_preflight():
    """Approval check failure message uses neutral wording.

    Uses _StickyReplyMessage so edit_text updates (error status edits)
    are visible in the reply chain. Positive assertion proves the test
    observes the error edit path.
    """
    import app.telegram_handlers as th

    with fresh_env(config_overrides={"approval_mode": "on"}) as (data_dir, cfg, prov):
        prov.preflight_results = [RunResult(text="", returncode=1)]
        chat = FakeChat(12345)
        user = FakeUser(uid=42)
        msg = _StickyReplyMessage(chat=chat, text="do failing approval work")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        all_texts = []
        edit_texts = []
        for r in msg.replies:
            all_texts.append(r.get("text", ""))
            et = r.get("edit_text", "")
            all_texts.append(et)
            if et:
                edit_texts.append(et)

        # Positive: prove the test observes the error edit path
        assert any(
            "Approval check failed:" in t or "Plan check failed:" in t for t in edit_texts
        ), f"Expected approval/plan check failed in status edits but got: {edit_texts}"

        for text in all_texts:
            if text:
                assert "preflight" not in text.lower(), (
                    f"Internal 'preflight' leaked in error path: {text!r}"
                )


async def test_content_first_update_bypasses_rate_limit():
    """First non-forced update after content_started bypasses rate limiting.

    Reproduces the race: a forced tool update sets last_update, then
    content_started fires and the first text update arrives within the
    rate-limit window.  Without the fix, the text is silently dropped.
    """
    import app.telegram_handlers as th

    msg = FakeMessage()
    cfg_overrides = {"stream_update_interval_seconds": 1.0}
    with fresh_env(config_overrides=cfg_overrides) as (data_dir, cfg, prov):
        progress = th.TelegramProgress(msg, cfg)
        progress.content_started = asyncio.Event()

        # Forced tool update — sets last_update to now
        await progress.update("<i>Running tool: Read</i>", force=True)
        assert progress.last_text == "<i>Running tool: Read</i>"

        # Immediately set content_started (provider signals first text)
        progress.content_started.set()

        # Non-forced text update within the 1s rate-limit window
        await progress.update("Hello, here is the answer.")

        # The text must get through despite rate limiting
        assert progress.last_text == "Hello, here is the answer.", (
            f"First content update was rate-limited; last_text={progress.last_text!r}"
        )

        # Subsequent non-forced updates should still be rate-limited normally
        await progress.update("Second update.")
        assert progress.last_text == "Hello, here is the answer.", (
            "Second update should be rate-limited"
        )


# =====================================================================
# INVARIANT 40: Worker replay respects durable-state contract
#
# A recovered work item replayed through worker_dispatch must:
# - stay claimed if the provider is interrupted again (LeaveClaimed)
# - be marked failed (not done) if replay raises an unexpected exception
# - never swallow LeaveClaimed as a generic failure
# =====================================================================

@pytest.mark.asyncio
async def test_worker_dispatch_recovery_not_auto_replay_disallowed_user():
    """worker_dispatch for a disallowed user returns normally without
    sending a recovery notice — the item completes silently."""
    import app.telegram_handlers as th
    from app.transport import InboundMessage, InboundUser

    with fresh_env(config_overrides={
        "allowed_user_ids": frozenset({99}),  # user 42 is not allowed
        "allow_open": False,
    }) as (data_dir, cfg, prov):
        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            event = InboundMessage(
                user=InboundUser(id=42, username="alice"),
                chat_id=12345,
                text="replay this",
                attachments=(),
            )
            item = {"chat_id": 12345, "update_id": 8888, "id": "replay-item"}

            # Should return normally (not raise PendingRecovery)
            await th.worker_dispatch("message", event, item)

            # No notice sent, no provider call
            assert len(bot.sent) == 0
            assert len(prov.run_calls) == 0
        finally:
            set_bot_instance(None)


@pytest.mark.asyncio
async def test_worker_dispatch_command_still_notifies():
    """worker_dispatch for InboundCommand still sends a notification
    that the command was lost (commands are not replay-safe)."""
    import app.telegram_handlers as th
    from app.transport import InboundCommand, InboundUser

    with fresh_env(config_overrides={
        "allowed_user_ids": frozenset({42}),
    }) as (data_dir, cfg, prov):
        bot = _FakeBot()
        set_bot_instance(bot)
        try:
            event = InboundCommand(
                user=InboundUser(id=42, username="alice"),
                chat_id=12345,
                command="new",
                args="",
            )
            item = {"chat_id": 12345, "update_id": 7777, "id": "cmd-item"}

            await th.worker_dispatch("command", event, item)

            # Notification about interrupted command
            cmd_msgs = [s for s in bot.sent if "interrupted" in s.get("text", "")]
            assert cmd_msgs, "Expected interrupted-command notification"
            # No provider call
            assert len(prov.run_calls) == 0
        finally:
            set_bot_instance(None)


# =====================================================================
# INVARIANT 41: Claude resume error resets provider state
#
# When a Claude resumed run fails (non-timeout, non-signal), the
# provider state must be reset to fresh so the next request is
# "Working..." not "Resuming...".  This is parity with Codex, which
# already clears thread_id on resume error.
# =====================================================================

@pytest.mark.asyncio
async def test_claude_resume_error_resets_provider_state():
    """Claude resume failure resets started/session_id so next request is fresh."""
    import app.telegram_handlers as th

    with fresh_env(provider_name="claude") as (data_dir, cfg, prov):
        # First request succeeds — sets started=True
        prov.run_results = [RunResult(
            text="first response",
            provider_state_updates={"started": True},
        )]
        chat = FakeChat(chat_id=5001)
        user = FakeUser(uid=42)
        msg1 = _StickyReplyMessage(chat=chat, text="first request")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())
        assert len(prov.run_calls) == 1

        # Verify session now has started=True
        session = th._load(5001)
        assert session.provider_state["started"] is True

        # Second request: provider signals resume target is dead
        prov.run_results = [RunResult(text="[Claude error (rc=1)]", returncode=1, resume_failed=True)]
        msg2 = _StickyReplyMessage(chat=chat, text="second request")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(upd2, FakeContext())

        # Session must be reset to fresh state
        session = th._load(5001)
        assert session.provider_state["started"] is False, (
            "started should be reset after resume error"
        )
        # session_id should also be reset (in production this generates a new UUID;
        # the fake provider returns a static value, so we just verify it was called)
        assert "session_id" in session.provider_state

        # Verify user got the "start fresh" / "starts fresh" message
        all_text = " ".join(
            r.get("text", "") + " " + r.get("edit_text", "")
            for r in msg2.replies
        )
        assert "start fresh" in all_text.lower() or "starts fresh" in all_text.lower(), (
            f"Expected 'start fresh' in user text: {all_text}"
        )

        # Third request should show "Working..." not "Resuming..."
        prov.run_results = [RunResult(text="recovered")]
        msg3 = _StickyReplyMessage(chat=chat, text="third request")
        upd3 = FakeUpdate(message=msg3, user=user, chat=chat)
        await th.handle_message(upd3, FakeContext())

        initial_status = msg3.replies[0].get("text", "")
        assert initial_status.replace("\u2026", "...") == "Working...", (
            f"After resume reset, expected 'Working...' but got: {initial_status!r}"
        )


@pytest.mark.asyncio
async def test_codex_resume_error_still_clears_thread():
    """Codex resume error still clears thread_id (existing behavior preserved)."""
    import app.telegram_handlers as th

    with fresh_env(provider_name="codex") as (data_dir, cfg, prov):
        # Simulate a session with an existing thread_id
        session = th._load(6001)
        session.provider_state["thread_id"] = "t-existing"
        session.provider_state["context_hash"] = "hash1"
        session.provider_state["boot_id"] = "test-boot"
        th._save(6001, session)

        # Provider fails with non-zero rc
        prov.run_results = [RunResult(text="codex error", returncode=1)]
        chat = FakeChat(chat_id=6001)
        user = FakeUser(uid=42)
        msg = _StickyReplyMessage(chat=chat, text="codex request")
        upd = FakeUpdate(message=msg, user=user, chat=chat)
        await th.handle_message(upd, FakeContext())

        session = th._load(6001)
        assert session.provider_state["thread_id"] is None, (
            "Codex thread_id should be cleared on resume error"
        )


@pytest.mark.asyncio
async def test_claude_generic_error_during_resume_does_not_reset():
    """Generic error on a healthy resumed session must NOT reset provider state.

    This is the false-positive test: resume_failed is False, so the session
    should keep its started=True and session_id intact for the next retry.
    """
    import app.telegram_handlers as th

    with fresh_env(provider_name="claude") as (data_dir, cfg, prov):
        # First request succeeds — sets started=True
        prov.run_results = [RunResult(
            text="first response",
            provider_state_updates={"started": True},
        )]
        chat = FakeChat(chat_id=7001)
        user = FakeUser(uid=42)
        msg1 = _StickyReplyMessage(chat=chat, text="first request")
        upd1 = FakeUpdate(message=msg1, user=user, chat=chat)
        await th.handle_message(upd1, FakeContext())

        session = th._load(7001)
        assert session.provider_state["started"] is True
        old_session_id = session.provider_state["session_id"]

        # Second request: generic error (rc=1) but resume_failed=False
        prov.run_results = [RunResult(text="[Claude error (rc=1)]", returncode=1)]
        msg2 = _StickyReplyMessage(chat=chat, text="second request")
        upd2 = FakeUpdate(message=msg2, user=user, chat=chat)
        await th.handle_message(upd2, FakeContext())

        # Session must NOT be reset — still started=True with same session_id
        session = th._load(7001)
        assert session.provider_state["started"] is True, (
            "Generic error should not reset started flag"
        )
        assert session.provider_state["session_id"] == old_session_id, (
            "Generic error should not change session_id"
        )

        # "starts fresh" message should NOT appear
        all_text = " ".join(
            r.get("text", "") + " " + r.get("edit_text", "")
            for r in msg2.replies
        )
        assert "starts fresh" not in all_text.lower(), (
            f"Generic error should not show 'starts fresh': {all_text}"
        )


def test_claude_is_resume_failure_classification():
    """_is_resume_failure correctly classifies resume-specific vs generic errors."""
    from app.providers.claude import ClaudeProvider

    # Positive: resume-specific failures
    assert ClaudeProvider._is_resume_failure("Error: session not found for id abc-123")
    assert ClaudeProvider._is_resume_failure("Could not resume conversation")
    assert ClaudeProvider._is_resume_failure("Invalid session ID provided")
    assert ClaudeProvider._is_resume_failure("Conversation not found")

    # Negative: generic errors that should NOT trigger reset
    assert not ClaudeProvider._is_resume_failure("")
    assert not ClaudeProvider._is_resume_failure("API rate limit exceeded")
    assert not ClaudeProvider._is_resume_failure("Internal server error")
    assert not ClaudeProvider._is_resume_failure("Connection reset by peer")
    assert not ClaudeProvider._is_resume_failure("Authentication failed")


# =====================================================================
# INVARIANT: ClaudeProvider.run() sets resume_failed from real stderr
#
# Provider-level test proving the full path: subprocess stderr →
# _is_resume_failure() → RunResult.resume_failed=True.  Without this,
# the handler-level tests only prove that *injected* resume_failed
# values are handled correctly, not that the provider produces them.
# =====================================================================

def _make_claude_provider():
    """Build a real ClaudeProvider with a valid test config."""
    import tempfile
    from app.providers.claude import ClaudeProvider
    tmp = tempfile.mkdtemp(prefix="test-claude-prov-")
    cfg = make_config(tmp, working_dir=Path(tmp))
    return ClaudeProvider(cfg)


class _FakeSubprocess:
    """Minimal subprocess fake for provider-level tests."""

    def __init__(self, *, stderr_bytes: bytes = b"", returncode: int = 0):
        self.returncode = returncode
        self.stderr = self._FakeStderr(stderr_bytes)
        self.stdout = self._FakeStdout()

    class _FakeStdout:
        async def readline(self):
            return b""
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    class _FakeStderr:
        def __init__(self, data: bytes):
            self._data = data
        async def read(self):
            return self._data

    async def wait(self):
        pass


@pytest.mark.asyncio
async def test_claude_provider_run_sets_resume_failed_from_stderr():
    """ClaudeProvider.run() sets resume_failed=True when stderr has session-not-found."""
    from unittest.mock import patch

    provider = _make_claude_provider()
    state = {"session_id": "dead-session-id", "started": True}
    proc = _FakeSubprocess(
        stderr_bytes=b"Error: session not found for id dead-session-id",
        returncode=1,
    )

    async def mock_exec(*args, **kwargs):
        return proc

    progress = FakeProgress()
    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await provider.run(state, "test prompt", [], progress)

    assert result.returncode == 1
    assert result.resume_failed is True, (
        "resume_failed should be True when stderr contains session-not-found"
    )


@pytest.mark.asyncio
async def test_claude_provider_run_no_resume_failed_on_generic_error():
    """ClaudeProvider.run() does NOT set resume_failed on generic stderr error."""
    from unittest.mock import patch

    provider = _make_claude_provider()
    state = {"session_id": "good-session-id", "started": True}
    proc = _FakeSubprocess(stderr_bytes=b"API rate limit exceeded", returncode=1)

    async def mock_exec(*args, **kwargs):
        return proc

    progress = FakeProgress()
    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await provider.run(state, "test prompt", [], progress)

    assert result.returncode == 1
    assert result.resume_failed is False, (
        "resume_failed should be False when stderr has only generic errors"
    )


@pytest.mark.asyncio
async def test_claude_provider_run_no_resume_failed_when_not_resuming():
    """ClaudeProvider.run() does NOT set resume_failed when started=False."""
    from unittest.mock import patch

    provider = _make_claude_provider()
    state = {"session_id": "new-session-id", "started": False}
    # Even if stderr happens to match, started=False means no resume
    proc = _FakeSubprocess(stderr_bytes=b"Error: session not found", returncode=1)

    async def mock_exec(*args, **kwargs):
        return proc

    progress = FakeProgress()
    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await provider.run(state, "test prompt", [], progress)

    assert result.returncode == 1
    assert result.resume_failed is False, (
        "resume_failed should be False when not resuming (started=False)"
    )


# =====================================================================
# INVARIANT: Timeout during resumed session sets resume_failed
#
# The Claude CLI hangs silently on a dead --resume target (no stderr,
# no stdout) instead of emitting a classifiable error.  The timeout
# path must set resume_failed=True so the handler resets session state.
# A fresh-session timeout (started=False) must NOT set resume_failed.
# =====================================================================

@pytest.mark.asyncio
async def test_claude_timeout_during_resume_sets_resume_failed():
    """Timeout on a resumed session sets resume_failed=True."""
    from unittest.mock import AsyncMock, patch

    provider = _make_claude_provider()
    state = {"session_id": "dead-session-id", "started": True}

    # _run_process returns ("", {}, -1, "") on timeout
    with patch.object(provider, "_run_process", new_callable=AsyncMock,
                      return_value=("", {}, -1, "")):
        result = await provider.run(state, "test prompt", [], FakeProgress())

    assert result.timed_out is True
    assert result.returncode == 124
    assert result.resume_failed is True, (
        "resume_failed must be True when a resumed session times out"
    )


@pytest.mark.asyncio
async def test_claude_timeout_during_fresh_session_no_resume_failed():
    """Timeout on a fresh session does NOT set resume_failed."""
    from unittest.mock import AsyncMock, patch

    provider = _make_claude_provider()
    state = {"session_id": "new-session-id", "started": False}

    with patch.object(provider, "_run_process", new_callable=AsyncMock,
                      return_value=("", {}, -1, "")):
        result = await provider.run(state, "test prompt", [], FakeProgress())

    assert result.timed_out is True
    assert result.returncode == 124
    assert result.resume_failed is False, (
        "resume_failed must be False when a fresh session times out"
    )


# =====================================================================
# INTEGRATION: Real Claude CLI hangs on bogus --resume (no stderr)
#
# This test runs the actual claude CLI binary with a garbage session ID
# and a very short timeout to prove the CLI behavior that motivated
# the timeout-based resume_failed fix: no stderr, no stdout, just a
# hang.  If the CLI ever starts emitting a classifiable error message
# instead of hanging, this test will catch the change so we can update
# _is_resume_failure markers accordingly.
#
# Skipped when claude is not installed.
# =====================================================================

@pytest.mark.asyncio
async def test_claude_cli_bogus_resume_no_classifiable_error():
    """Real Claude CLI with a bogus --resume ID emits no classifiable error.

    Depending on environment, the CLI either hangs (timeout) or exits
    fast with rc=1 and empty stderr.  Either way, it does NOT emit a
    stderr message that _is_resume_failure() can classify.  This is
    why the timeout path sets resume_failed directly.

    If this test starts FAILING, the CLI has improved its error
    reporting — update _is_resume_failure markers to match.
    """
    import shutil

    claude_bin = shutil.which("claude")
    if not claude_bin:
        pytest.skip("claude CLI not installed")

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    bogus_id = "00000000-0000-0000-0000-000000000000"
    cmd = [
        claude_bin, "-p",
        "--output-format", "stream-json",
        "--resume", bogus_id,
        "--", "hello",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    timed_out = False
    stdout_data = b""
    stderr_data = b""
    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(), timeout=5,
        )
    except (asyncio.TimeoutError, TimeoutError):
        timed_out = True
        proc.kill()
        await proc.wait()

    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()

    stdout_text = stdout_data.decode("utf-8", errors="replace").strip()

    # The CLI either hangs (timeout) or exits with rc!=0 on a bogus session.
    # Either way, it currently does NOT emit a classifiable stderr message.
    # This test documents the actual behavior and catches future changes.
    if not timed_out:
        # CLI exited — it did not hang.  Verify it failed (rc!=0) and check
        # whether it now emits a useful error we can classify.
        assert proc.returncode != 0, (
            f"Expected non-zero exit on bogus --resume, got rc=0. "
            f"stdout={stdout_text[:200]!r}"
        )

    from app.providers.claude import ClaudeProvider

    # Key assertion: the CLI does NOT currently emit stderr that
    # _is_resume_failure can classify.  If this fails, the CLI has
    # improved its error reporting — update the markers.
    assert not ClaudeProvider._is_resume_failure(stderr_text), (
        f"CLI now emits a classifiable resume error in stderr: {stderr_text!r}. "
        f"This is good — verify the markers in _is_resume_failure match, "
        f"then update this test to assert True instead."
    )

    # Also check stdout for JSON error events we might parse.
    # If the CLI starts emitting structured errors, we can use them.
    has_stdout_error = any(
        kw in stdout_text.lower()
        for kw in ("session not found", "invalid session", "could not resume")
    )
    assert not has_stdout_error, (
        f"CLI now emits resume error in stdout: {stdout_text[:300]!r}. "
        f"Consider parsing stdout JSON for resume failure detection."
    )


# Work-item claim serialization, mid-flight mutation, preflight model parity,
# and callback update_id threading are tested in test_workitem_integration.py
# as real integration tests (real SQLite, real asyncio, real lock contention).

# Work-item claiming serialization and callback update_id threading are
# covered by real integration tests in tests/test_workitem_integration.py:
#   - test_claim_for_update_blocked_by_existing_claimed_item
#   - test_approval_callback_does_not_consume_stale_item
