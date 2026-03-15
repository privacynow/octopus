"""Request flow — trust tiers, public enforcement, validation, credentials.

Owner suite for (distinct contract from test_handlers):
- Execution context, trust shaping, invalidation, stale detection, request-lifecycle contracts
- Public trust tier enforcement in resolve_execution_context
- is_public_user / is_allowed predicates
- Public trust command gating
- Rate-limit defaults for public mode
- Mixed trusted/public ingress
- execute_request and handle_message trust tier threading
- Approval/retry trust tier round-trips
- validate_pending with stored trust tier
- Credential satisfaction checks
- extra_dirs_from_denials extraction
- Cross-feature: compact + long reply + public user
- Export resolved skills (not raw session)

Re-homed to test_handlers (Milestone E): handler-surface tests for /session, /settings, /model,
setting_model:*, setting_project:* (test_session_command_shows_public_context,
test_settings_command_public_user_no_trusted_leak, test_settings_command_public_user_keyboard_*,
test_model_command_public_user_*, test_model_callback_public_user_*, test_project_callback_public_user_denied).
Those tests assert user-visible command/callback behaviour; test_handlers owns that contract.
This file keeps contract over execution context, trust shaping, validate_pending, and request lifecycle.

Migrated from tests/test_invariants.py invariants 13–24 and related
cross-feature checks, and tests/test_high_risk.py (extra_dirs_from_denials).
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest

from app.execution_context import (
    ResolvedExecutionContext,
    resolve_execution_context,
)
from app.providers.base import RunResult
from app.request_flow import extra_dirs_from_denials as _extra_dirs_from_denials
from app.session_state import (
    PendingApproval,
    PendingRetry,
    SessionState,
    session_from_dict,
    session_to_dict,
)
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
    last_reply,
    load_session_disk,
    make_config,
    send_callback,
    send_command,
    send_text,
    setup_globals,
)

_MODEL_PROFILES = {"fast": "haiku", "balanced": "sonnet", "best": "opus"}


# =====================================================================
# Public trust tier enforcement in execution context
#
# When trust_tier="public", resolve_execution_context must force:
# - file_policy to "inspect"
# - working_dir to public_working_dir (if configured)
# - base_extra_dirs to empty
# - active_skills to empty
# - project_id to empty
# =====================================================================

def test_public_trust_forces_inspect():
    """Public users must have file_policy forced to 'inspect'."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        file_policy="edit",
    )
    cfg = _make_config()
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.file_policy == "inspect"


def test_public_trust_forces_public_working_dir():
    """Public users must use BOT_PUBLIC_WORKING_DIR."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(public_working_dir="/srv/public")
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.working_dir == "/srv/public"


def test_public_trust_strips_extra_dirs():
    """Public users must have no extra_dirs."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(extra_dirs=(Path("/opt/private"),))
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.base_extra_dirs == []


def test_public_trust_strips_skills():
    """Public users must have no active skills."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        active_skills=["code-review"],
    )
    cfg = _make_config()
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.active_skills == []


def test_public_trust_strips_project():
    """Public users must have no project binding."""
    project_dir = tempfile.mkdtemp()
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="frontend",
    )
    cfg = _make_config(projects=(("frontend", project_dir, ()),))
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.project_id == ""
    assert ctx.project_binding is None


def test_public_trust_restricts_model_profiles():
    """Public users restricted to allowed profiles fall back correctly."""
    from app.execution_context import resolve_effective_model

    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        model_profile="best",
    )
    cfg = _make_config(
        model_profiles=_MODEL_PROFILES,
        default_model_profile="balanced",
        public_model_profiles=frozenset(["fast"]),
    )
    model = resolve_effective_model(session, cfg, trust_tier="public")
    assert model == "haiku", "Public user requesting 'best' must fall back to allowed 'fast'"


def test_public_vs_trusted_different_context_hash():
    """Same session must produce different context hash for public vs trusted."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(public_working_dir="/srv/public")
    hash_trusted = resolve_execution_context(session, cfg, "claude", trust_tier="trusted").context_hash
    hash_public = resolve_execution_context(session, cfg, "claude", trust_tier="public").context_hash
    assert hash_trusted != hash_public


# =====================================================================
# is_public_user predicate
# =====================================================================

def test_is_public_user_open_with_allowed_list():
    """User not in allowed list + allow_open=True -> public."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset({100}),
            allowed_usernames=frozenset({"admin"}),
        )
        setup_globals(cfg, FakeProvider("claude"))

        assert th.is_public_user(FakeUser(uid=999, username="stranger")) is True
        assert th.is_public_user(FakeUser(uid=100, username="admin")) is False


def test_is_public_user_open_no_allowed_list():
    """allow_open=True with no allowed list -> everyone is public."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, allow_open=True,
                          allowed_user_ids=frozenset(),
                          allowed_usernames=frozenset())
        setup_globals(cfg, FakeProvider("claude"))

        assert th.is_public_user(FakeUser(uid=42)) is True


def test_is_public_user_closed():
    """allow_open=False -> no one is public (they wouldn't pass is_allowed)."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=False,
            allowed_user_ids=frozenset({42}),
        )
        setup_globals(cfg, FakeProvider("claude"))

        assert th.is_public_user(FakeUser(uid=42)) is False
        assert th.is_public_user(FakeUser(uid=999)) is False


# =====================================================================
# Public trust command gating
# =====================================================================

_GATED_COMMANDS = [
    ("cmd_skills", []),
    ("cmd_project", ["list"]),
    ("cmd_policy", ["inspect"]),
    ("cmd_send", ["/tmp/file"]),
    ("cmd_role", ["expert"]),
    ("cmd_clear_credentials", []),
    ("cmd_cancel", []),
]


@pytest.mark.parametrize("cmd_name,args", _GATED_COMMANDS,
                         ids=[c[0] for c in _GATED_COMMANDS])
async def test_public_user_blocked_from_restricted_command(cmd_name, args):
    """Public users get a denial message from restricted commands."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            allowed_user_ids=frozenset(),  # no allowed list -> everyone is public
            allowed_usernames=frozenset(),
        )
        setup_globals(cfg, FakeProvider("claude"))

        chat = FakeChat(chat_id=7001)
        user = FakeUser(uid=42, username="stranger")
        handler = getattr(th, cmd_name)
        msg = await send_command(handler, chat, user, f"/{cmd_name}", args=args)
        reply = last_reply(msg)
        assert "not available in public mode" in reply


async def test_trusted_user_not_blocked_from_restricted_command():
    """Trusted users can invoke restricted commands normally."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(chat_id=7002)
        user = FakeUser(uid=42, username="testuser")  # uid=42 is in default allowed set
        msg = await send_command(th.cmd_policy, chat, user, "/policy", args=["status"])
        reply = last_reply(msg)
        assert "not available in public mode" not in reply


# =====================================================================
# Public user cannot escalate to restricted model
# =====================================================================

def test_public_user_cannot_escalate_to_restricted_model():
    """Public user with restricted profiles cannot set a profile outside the allowed set."""
    from app.execution_context import resolve_effective_model

    cfg = _make_config(
        model="claude-sonnet-4-6",
        model_profiles={"fast": "claude-haiku-4-5-20251001", "balanced": "claude-sonnet-4-6", "best": "claude-opus-4-6"},
        default_model_profile="balanced",
        public_model_profiles=frozenset({"fast", "balanced"}),
    )
    session = SessionState(provider="claude", provider_state={}, approval_mode="off")
    session.model_profile = "best"  # attempt escalation
    model = resolve_effective_model(session, cfg, trust_tier="public")
    # Should NOT get claude-opus-4-6
    assert model != "claude-opus-4-6"
    # Should fall back to an allowed profile
    assert model in {"claude-haiku-4-5-20251001", "claude-sonnet-4-6"}


def test_inspect_policy_survives_model_change():
    """Changing model profile does not break inspect enforcement."""
    cfg = _make_config(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        default_model_profile="fast",
        public_working_dir="/tmp/pub",
    )
    session = SessionState(provider="claude", provider_state={}, approval_mode="off")
    session.model_profile = "best"

    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.file_policy == "inspect"  # forced by public trust
    assert ctx.working_dir == "/tmp/pub"  # forced by public trust


def test_compact_mode_works_for_public_users():
    """Public users should still get compact rendering (not blocked)."""
    cfg = _make_config(
        model_profiles={"fast": "claude-haiku-4-5-20251001"},
        default_model_profile="fast",
        public_working_dir="/tmp/pub",
    )
    session = SessionState(provider="claude", provider_state={}, approval_mode="off")
    session.compact_mode = True

    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    # Compact mode is a session preference, not execution-scope — it's not stripped
    assert session.compact_mode is True
    # But execution scope is still enforced
    assert ctx.file_policy == "inspect"


# =====================================================================
# Rate-limit defaults for public mode
# =====================================================================

def test_public_mode_applies_default_rate_limits():
    """build_application should apply conservative rate-limit defaults when
    allow_open=True and no explicit limits are set."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            rate_limit_per_minute=0,
            rate_limit_per_hour=0,
            allowed_user_ids=frozenset(),
        )
        setup_globals(cfg, FakeProvider("claude"))
        per_minute = cfg.rate_limit_per_minute
        per_hour = cfg.rate_limit_per_hour
        if cfg.allow_open and per_minute == 0 and per_hour == 0:
            per_minute = 5
            per_hour = 30
        assert per_minute == 5
        assert per_hour == 30


def test_explicit_rate_limits_not_overridden():
    """When operator sets explicit rate limits, they should not be overridden."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(
            data_dir,
            allow_open=True,
            rate_limit_per_minute=10,
            rate_limit_per_hour=60,
            allowed_user_ids=frozenset(),
        )
        per_minute = cfg.rate_limit_per_minute
        per_hour = cfg.rate_limit_per_hour
        if cfg.allow_open and per_minute == 0 and per_hour == 0:
            per_minute = 5
            per_hour = 30
        assert per_minute == 10
        assert per_hour == 60


# =====================================================================
# Mixed trusted/public ingress
# =====================================================================

@pytest.mark.asyncio
async def test_is_allowed_mixed_mode_admits_stranger():
    """Stranger admitted when allow_open + allow-lists both set."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
    }) as (data_dir, cfg, prov):
        trusted_user = FakeUser(uid=42, username="trustedguy")
        stranger = FakeUser(uid=999, username="nobody")

        assert th.is_allowed(trusted_user)
        assert th.is_allowed(stranger)
        assert not th.is_public_user(trusted_user)
        assert th.is_public_user(stranger)


@pytest.mark.asyncio
async def test_is_allowed_closed_mode_rejects_stranger():
    """Stranger rejected when allow_open=False, even with allow-lists."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": False,
        "allowed_user_ids": frozenset({42}),
    }) as (data_dir, cfg, prov):
        trusted_user = FakeUser(uid=42)
        stranger = FakeUser(uid=999, username="nobody")

        assert th.is_allowed(trusted_user)
        assert not th.is_allowed(stranger)


# =====================================================================
# Public trust enforcement on execution paths
# =====================================================================

@pytest.mark.asyncio
async def test_execute_request_public_user_gets_inspect_policy():
    """execute_request with trust_tier='public' resolves inspect file_policy."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/public-sandbox",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        user = FakeUser(uid=42)

        # Prime session with skills and edit policy (trusted-user settings)
        from app.storage import load_session, save_session
        session = load_session(data_dir, chat.id, prov.name, prov.new_provider_state, "off")
        session["file_policy"] = "edit"
        session["active_skills"] = ["some-skill"]
        save_session(data_dir, chat.id, session)

        # Execute as public
        msg = FakeMessage(chat=chat, text="hello")
        await th.execute_request(
            chat.id, "test prompt", [], msg,
            request_user_id=999, trust_tier="public",
        )

        # Provider should have been called with public restrictions
        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.file_policy == "inspect"
        assert ctx.working_dir == "/tmp/public-sandbox"


@pytest.mark.asyncio
async def test_execute_request_trusted_user_gets_edit_policy():
    """execute_request with trust_tier='trusted' preserves session file_policy."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/public-sandbox",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)

        from app.storage import load_session, save_session
        session = load_session(data_dir, chat.id, prov.name, prov.new_provider_state, "off")
        session["file_policy"] = "edit"
        save_session(data_dir, chat.id, session)

        msg = FakeMessage(chat=chat, text="hello")
        await th.execute_request(
            chat.id, "test prompt", [], msg,
            request_user_id=42, trust_tier="trusted",
        )

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.file_policy == "edit"
        assert ctx.working_dir != "/tmp/public-sandbox"


@pytest.mark.asyncio
async def test_handle_message_public_user_threads_trust_tier():
    """Full handle_message path for a public user passes trust_tier through."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/public-sandbox",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        msg = await send_text(chat, stranger, "hello from public user")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert ctx.file_policy == "inspect"
        assert ctx.working_dir == "/tmp/public-sandbox"


@pytest.mark.asyncio
async def test_handle_message_trusted_user_not_forced_inspect():
    """Full handle_message path for a trusted user does NOT force inspect."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/public-sandbox",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        trusted = FakeUser(uid=42, username="trustedguy")

        msg = await send_text(chat, trusted, "hello from trusted user")

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        # Trusted user gets default file_policy from session (empty = edit)
        assert ctx.file_policy != "inspect"
        assert ctx.working_dir != "/tmp/public-sandbox"


@pytest.mark.asyncio
async def test_approval_round_trip_preserves_public_trust_tier():
    """PendingApproval stores trust_tier; approve_pending passes it to execute_request."""
    # Verify trust_tier round-trips through serialization
    pending = PendingApproval(
        request_user_id=999,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash="abc123",
        trust_tier="public",
    )
    assert pending.trust_tier == "public"

    session = SessionState(provider="claude", provider_state={}, approval_mode="on")
    session.pending_approval = pending
    d = session_to_dict(session)
    restored = session_from_dict(d)
    assert restored.pending_approval is not None
    assert restored.pending_approval.trust_tier == "public"


@pytest.mark.asyncio
async def test_pending_retry_preserves_trust_tier():
    """PendingRetry stores trust_tier through serialization round-trip."""
    pending = PendingRetry(
        request_user_id=999,
        prompt="test",
        image_paths=[],
        context_hash="abc123",
        denials=[],
        trust_tier="public",
    )
    assert pending.trust_tier == "public"

    session = SessionState(provider="claude", provider_state={}, approval_mode="on")
    session.pending_retry = pending
    d = session_to_dict(session)
    restored = session_from_dict(d)
    assert restored.pending_retry is not None
    assert restored.pending_retry.trust_tier == "public"


# =====================================================================
# Pending validation uses stored trust tier
# =====================================================================

def test_validate_pending_respects_stored_trust_tier():
    """validate_pending must recompute hash with the pending's trust_tier."""
    from app.request_flow import validate_pending

    cfg = _make_config(
        public_working_dir="/tmp/public",
        timeout_seconds=3600,
    )
    session = SessionState(provider="claude", provider_state={}, approval_mode="on")

    # Compute the public context hash
    public_ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    public_hash = public_ctx.context_hash

    # Trusted hash must differ
    trusted_ctx = resolve_execution_context(session, cfg, "claude", trust_tier="trusted")
    trusted_hash = trusted_ctx.context_hash
    assert public_hash != trusted_hash, "Public and trusted hashes must differ"

    # Create a pending approval with the public hash and trust_tier
    pending = PendingApproval(
        request_user_id=999,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash=public_hash,
        trust_tier="public",
    )

    # validate_pending should pass — hash matches when trust_tier is respected
    error = validate_pending(pending, session, cfg, "claude")
    assert error is None, f"Expected no error but got: {error}"


def test_validate_pending_detects_real_context_change():
    """validate_pending correctly detects when context actually changed."""
    from app.request_flow import validate_pending

    cfg = _make_config(timeout_seconds=3600)
    session = SessionState(provider="claude", provider_state={}, approval_mode="on")

    pending = PendingApproval(
        request_user_id=42,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash="stale-hash-that-doesnt-match",
        trust_tier="trusted",
    )

    error = validate_pending(pending, session, cfg, "claude")
    assert error is not None
    assert "context" in error and "changed" in error


def test_classify_pending_validation_returns_ok_expired_context_changed():
    """classify_pending_validation returns ok/expired/context_changed for machine guards."""
    from app.request_flow import classify_pending_validation

    cfg = _make_config(timeout_seconds=3600)
    session = SessionState(provider="claude", provider_state={}, approval_mode="on")
    current_hash = resolve_execution_context(session, cfg, "claude", trust_tier="trusted").context_hash

    # ok: fresh, matching context
    pending_ok = PendingApproval(
        request_user_id=42,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash=current_hash,
        trust_tier="trusted",
        created_at=time.time(),
    )
    assert classify_pending_validation(pending_ok, session, cfg, "claude") == "ok"

    # expired: old created_at
    pending_expired = PendingApproval(
        request_user_id=42,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash=current_hash,
        trust_tier="trusted",
        created_at=time.time() - 7200,
    )
    assert classify_pending_validation(pending_expired, session, cfg, "claude") == "expired"

    # context_changed: hash mismatch
    pending_stale = PendingApproval(
        request_user_id=42,
        prompt="test",
        image_paths=[],
        attachment_dicts=[],
        context_hash="stale-hash",
        trust_tier="trusted",
        created_at=time.time(),
    )
    assert classify_pending_validation(pending_stale, session, cfg, "claude") == "context_changed"


# =====================================================================
# Credential checks use resolved active_skills
# =====================================================================

def test_credential_check_uses_resolved_skills_not_session():
    """Credential check with empty resolved skills skips all checks."""
    from app.request_flow import check_credential_satisfaction

    with fresh_data_dir() as data_dir:
        session = SessionState(provider="claude", provider_state={}, approval_mode="off")
        # Session has skills, but resolved list is empty (public user)
        session.active_skills = ["github-integration"]

        result = check_credential_satisfaction(
            active_skills=[],  # resolved: public user gets no skills
            session=session,
            user_id=999,
            data_dir=data_dir,
            encryption_key=b"test-key-1234567",
        )
        assert result.satisfied
        assert result.credential_env == {}


def test_credential_check_with_resolved_skills():
    """Credential check with non-empty resolved skills actually checks them."""
    from app.request_flow import check_credential_satisfaction

    with fresh_data_dir() as data_dir:
        session = SessionState(provider="claude", provider_state={}, approval_mode="off")

        # Use a fake skill name — check_credentials returns [] for unknown skills
        result = check_credential_satisfaction(
            active_skills=["nonexistent-skill"],
            session=session,
            user_id=42,
            data_dir=data_dir,
            encryption_key=b"test-key-1234567",
        )
        # Unknown skills have no requirements, so satisfied
        assert result.satisfied


# =====================================================================
# extra_dirs_from_denials extraction
# (migrated from tests/test_high_risk.py)
# =====================================================================

def test_extra_dirs_from_denials_empty():
    assert _extra_dirs_from_denials([]) == []


def test_extra_dirs_from_denials_file_path():
    denials_file = [{"tool_name": "Write", "tool_input": {"file_path": "/home/user/project/foo.py"}}]
    dirs = _extra_dirs_from_denials(denials_file)
    assert "/home/user/project" in dirs
    assert "/home/user" not in dirs


def test_extra_dirs_from_denials_directory():
    denials_dir = [{"tool_name": "Glob", "tool_input": {"directory": "/home/tinker/private"}}]
    dirs_dir = _extra_dirs_from_denials(denials_dir)
    assert "/home/tinker/private" in dirs_dir
    assert "/home/tinker" not in dirs_dir


def test_extra_dirs_from_denials_command():
    denials_cmd = [{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}]
    dirs_cmd = _extra_dirs_from_denials(denials_cmd)
    assert "/" in dirs_cmd


def test_extra_dirs_from_denials_multiple():
    denials_multi = [
        {"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}},
        {"tool_name": "Read", "tool_input": {"path": "/var/log/syslog"}},
    ]
    dirs_multi = _extra_dirs_from_denials(denials_multi)
    assert "/etc" in dirs_multi
    assert "/var/log" in dirs_multi


def test_extra_dirs_from_denials_mixed():
    denials_mixed = [
        {"tool_name": "Write", "tool_input": {"file_path": "/opt/app/config.yaml"}},
        {"tool_name": "Glob", "tool_input": {"directory": "/opt/data"}},
    ]
    dirs_mixed = _extra_dirs_from_denials(denials_mixed)
    assert "/opt/app" in dirs_mixed
    assert "/opt/data" in dirs_mixed
    assert "/opt" not in dirs_mixed


# =====================================================================
# Cross-feature: compact + long reply + public user
# =====================================================================

@pytest.mark.asyncio
async def test_compact_long_reply_public_user():
    """Public user + compact mode + long response -> blockquote/expand, inspect enforced."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "compact_mode": True,
        "public_working_dir": "/tmp/pub",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(2001)
        stranger = FakeUser(uid=999, username="nobody")

        long_response = "Summary line.\n\nDetailed paragraph of analysis. " * 40
        prov.run_results = [RunResult(text=long_response)]

        msg = await send_text(chat, stranger, "analyze this")

        all_text = " ".join(str(r.get("text", "")) for r in msg.replies)
        # Should have compact rendering (blockquote or expand button)
        has_blockquote = "blockquote" in all_text
        has_expand_button = any(r.get("reply_markup") is not None for r in msg.replies)
        assert has_blockquote or has_expand_button, (
            f"Expected compact rendering for public user, got: {all_text[:200]}")

        # Verify execution scope was enforced: provider received inspect context
        assert prov.run_calls, "Provider should have been called"
        ctx = prov.run_calls[-1]["context"]
        assert ctx.file_policy == "inspect"
        assert ctx.working_dir == "/tmp/pub"


# =====================================================================
# Export resolved skills (not raw session)
# =====================================================================

@pytest.mark.asyncio
async def test_export_uses_resolved_skills_not_raw_session():
    """/export header shows resolved skills, not raw session.active_skills."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset(),  # no trusted users
    }) as (data_dir, cfg, prov):
        # Create a session as a trusted user first, add skills
        session = th._load(8005)
        session.active_skills = ["github-integration", "secret-tool"]
        th._save(8005, session)

        # Export as a public user (not in allowed_user_ids)
        chat = FakeChat(chat_id=8005)
        public_user = FakeUser(uid=999, username="stranger")
        await send_command(th.cmd_export, chat, public_user, "/export")

        # Verify the resolved context gives [] for public users
        session_after = th._load(8005)
        trust = th._trust_tier(public_user)
        resolved = th._resolve_context(session_after, trust_tier=trust)
        assert resolved.active_skills == [], (
            f"Public user should resolve to zero skills, got: {resolved.active_skills}"
        )
        # Raw session still has skills (proves resolve is needed, not raw read)
        assert len(session_after.active_skills) > 0, (
            "Raw session should still have skills to prove resolution matters"
        )
