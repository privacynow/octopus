"""Execution context — hash consistency, stale detection, and resolution.

Owner suite for:
- Context hash round-trips (approval, retry, stale detection)
- Inspect mode sandbox integrity
- ResolvedContext path parity (handler adapter vs authoritative builder)
- Hash sensitivity to identity fields
- Session state round-trips (PendingApproval, PendingRetry)
- Execution config digest completeness
- Extra_dirs forwarding to provider context
- Model profile resolution and hash impact
- Project + model/policy cross-invalidation

Migrated from tests/test_invariants.py invariants 1–12 and related
cross-feature checks.
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest

from app.execution_context import (
    ResolvedExecutionContext,
    _compute_execution_config_digest,
    resolve_execution_context,
)
from app.providers.base import (
    RunContext,
    RunResult,
)
from app.providers.codex import CodexProvider
from app.session_state import (
    PendingApproval,
    PendingRetry,
    SessionState,
    session_from_dict,
    session_to_dict,
)
from app.skills import get_provider_config_digest, get_skill_digests
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


# =====================================================================
# Context hash consistency
#
# A request created and immediately approved/retried without any
# intervening changes must never be treated as stale.
# This must hold for every combination of project/policy/role/skills.
# =====================================================================

_CONTEXT_COMBOS = [
    pytest.param({}, id="defaults"),
    pytest.param({"project": True}, id="with-project"),
    pytest.param({"file_policy": "inspect"}, id="inspect-mode"),
    pytest.param({"role": "security expert"}, id="custom-role"),
    pytest.param({"project": True, "file_policy": "inspect"}, id="project+inspect"),
    pytest.param({"project": True, "role": "devops"}, id="project+role"),
    pytest.param(
        {"project": True, "file_policy": "inspect", "role": "auditor"},
        id="project+inspect+role",
    ),
]


@pytest.mark.parametrize("combo", _CONTEXT_COMBOS)
async def test_approval_hash_round_trip(combo):
    """Request created in approval mode and immediately approved must succeed."""
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp() if combo.get("project") else None
        projects = (("frontend", project_dir, ()),) if project_dir else ()
        cfg = make_config(data_dir, approval_mode="on", projects=projects)
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan")]
        prov.run_results = [RunResult(text="Done")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Apply session overrides
        if project_dir:
            await th.cmd_project(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(["use", "frontend"]),
            )
        if combo.get("role"):
            words = combo["role"].split()
            await th.cmd_role(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(words),
            )
        if combo.get("file_policy"):
            await th.cmd_policy(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext([combo["file_policy"]]),
            )

        # Send message — triggers preflight
        msg = FakeMessage(chat=chat, text="do work")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert len(prov.preflight_calls) == 1

        # Approve immediately — must NOT say "Context changed"
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        reply_texts = " ".join(
            r.get("edit_text", r.get("text", "")) for r in cb_msg.replies
        )
        assert "Context changed" not in reply_texts, (
            f"Approval falsely rejected as stale with combo {combo}"
        )
        assert len(prov.run_calls) == 1, (
            f"Approval should execute request with combo {combo}"
        )


@pytest.mark.parametrize("combo", _CONTEXT_COMBOS)
async def test_retry_hash_round_trip(combo):
    """Denial retry without intervening changes must succeed."""
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp() if combo.get("project") else None
        projects = (("frontend", project_dir, ()),) if project_dir else ()
        cfg = make_config(data_dir, projects=projects)
        prov = FakeProvider("claude")
        prov.run_results = [
            RunResult(
                text="partial",
                denials=[{"tool_name": "Write", "tool_input": {"file_path": "/opt/x"}}],
            ),
            RunResult(text="Success"),
        ]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        if project_dir:
            await th.cmd_project(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(["use", "frontend"]),
            )
        if combo.get("role"):
            words = combo["role"].split()
            await th.cmd_role(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(words),
            )
        if combo.get("file_policy"):
            await th.cmd_policy(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext([combo["file_policy"]]),
            )

        msg = FakeMessage(chat=chat, text="edit config")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert len(prov.run_calls) == 1

        # Retry immediately
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("retry_allow", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        reply_texts = " ".join(
            r.get("edit_text", r.get("text", "")) for r in cb_msg.replies
        )
        assert "Context changed" not in reply_texts, (
            f"Retry falsely rejected as stale with combo {combo}"
        )
        assert len(prov.run_calls) == 2, (
            f"Retry should execute request with combo {combo}"
        )


# =====================================================================
# Stale detection
#
# If role, skills, project, or file_policy change between request
# creation and approval/retry, the request MUST be rejected as stale.
# =====================================================================

_STALENESS_CHANGES = [
    pytest.param("role", id="role-change"),
    pytest.param("file_policy", id="policy-change"),
    pytest.param("project", id="project-change"),
]


@pytest.mark.parametrize("change", _STALENESS_CHANGES)
async def test_approval_detects_stale_context(change):
    """Approval must reject if context drifted between request and approve."""
    with fresh_data_dir() as data_dir:
        project_dir_a = tempfile.mkdtemp()
        project_dir_b = tempfile.mkdtemp()
        cfg = make_config(
            data_dir, approval_mode="on",
            projects=(("proj-a", project_dir_a, ()), ("proj-b", project_dir_b, ())),
        )
        prov = FakeProvider("claude")
        prov.preflight_results = [RunResult(text="Plan")]
        prov.run_results = [RunResult(text="Done")]
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Send message to create pending request
        msg = FakeMessage(chat=chat, text="do work")
        await th.handle_message(FakeUpdate(message=msg, user=user, chat=chat), FakeContext())
        assert len(prov.preflight_calls) == 1

        # Now change context before approving
        if change == "role":
            await th.cmd_role(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(["new", "role"]),
            )
        elif change == "file_policy":
            await th.cmd_policy(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(["inspect"]),
            )
        elif change == "project":
            await th.cmd_project(
                FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
                FakeContext(["use", "proj-a"]),
            )

        # Approve — must detect stale context
        cb_msg = FakeMessage(chat=chat)
        query = FakeCallbackQuery("approval_approve", message=cb_msg)
        cb_update = FakeUpdate(user=user, chat=chat, callback_query=query)
        cb_update.effective_message = cb_msg
        await th.handle_callback(cb_update, FakeContext())

        assert len(prov.run_calls) == 0, (
            f"Stale approval should NOT execute (change={change})"
        )


def test_default_working_dir_affects_hash():
    """Different config.working_dir without project must produce different hashes."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg_a = _make_config(working_dir=Path("/home/alice"))
    cfg_b = _make_config(working_dir=Path("/home/bob"))

    hash_a = resolve_execution_context(session, cfg_a, "claude").context_hash
    hash_b = resolve_execution_context(session, cfg_b, "claude").context_hash

    assert hash_a != hash_b, (
        "Different default working_dir must produce different context hashes"
    )


def test_default_working_dir_in_resolved_context():
    """Resolved context must carry config.working_dir when no project is bound."""
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(working_dir=Path("/opt/myproject"))
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.working_dir == "/opt/myproject"


# =====================================================================
# Inspect mode sandbox integrity
#
# In inspect mode, no combination of provider config may produce a
# sandbox value other than "read-only" for Codex.
# =====================================================================

_SANDBOX_OVERRIDES = [
    pytest.param({}, id="no-provider-config"),
    pytest.param({"sandbox": "workspace-write"}, id="sandbox-workspace-write"),
    pytest.param({"sandbox": "off"}, id="sandbox-off"),
    pytest.param({"sandbox": "read-only"}, id="sandbox-read-only"),
    pytest.param(
        {"sandbox": "workspace-write", "config_overrides": ["x=y"]},
        id="sandbox+overrides",
    ),
]


@pytest.mark.parametrize("provider_config", _SANDBOX_OVERRIDES)
async def test_inspect_mode_always_readonly(provider_config):
    """file_policy=inspect must force sandbox=read-only regardless of provider_config."""
    provider = CodexProvider(_make_config(codex_sandbox="workspace-write"))
    calls: list[list[str]] = []

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir="", cancel=None):
        calls.append(cmd)
        return RunResult(text="ok", provider_state_updates={"thread_id": "t-1"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]

    context = RunContext(
        extra_dirs=[], system_prompt="", capability_summary="",
        provider_config=provider_config, credential_env={},
        file_policy="inspect",
    )
    await provider.run({"thread_id": None}, "analyze", [], FakeProgress(), context=context)

    cmd = calls[-1]
    sandbox_idx = cmd.index("--sandbox")
    assert cmd[sandbox_idx + 1] == "read-only", (
        f"Inspect mode must be read-only, got {cmd[sandbox_idx + 1]} "
        f"with provider_config={provider_config}"
    )


# =====================================================================
# ResolvedContext is the single source of truth
#
# _resolve_context(session).context_hash must always equal what
# execute_request and request_approval would compute.
# =====================================================================

async def test_resolve_context_matches_all_paths():
    """ResolvedContext.context_hash must match what execute and approval paths produce."""
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp()
        cfg = make_config(
            data_dir,
            projects=(("myproj", project_dir, ()),),
        )
        prov = FakeProvider("claude")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Set up a non-trivial session
        await th.cmd_project(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["use", "myproj"]),
        )
        await th.cmd_role(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["security", "auditor"]),
        )
        await th.cmd_policy(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["inspect"]),
        )

        session_dict = load_session_disk(data_dir, 12345, prov)
        session = session_from_dict(session_dict)

        # Path 1: handler adapter (_resolve_context)
        handler_hash = th._resolve_context(session).context_hash

        # Path 2: authoritative builder directly
        direct_hash = resolve_execution_context(session, cfg, prov.name).context_hash

        # Path 3: request_flow.current_context_hash helper
        from app.request_flow import current_context_hash
        helper_hash = current_context_hash(session, cfg, prov.name)

        assert handler_hash == direct_hash, (
            "Handler adapter diverged from direct resolve_execution_context"
        )
        assert handler_hash == helper_hash, (
            "Handler adapter diverged from current_context_hash()"
        )


# =====================================================================
# Context hash includes all identity fields
#
# ResolvedExecutionContext.context_hash must produce a different
# hash when any identity field changes.
# =====================================================================

_HASH_FIELD_CHANGES = [
    pytest.param({"role": "changed"}, id="role"),
    pytest.param({"active_skills": ["new-skill"]}, id="skills"),
    pytest.param({"skill_digests": {"s": "changed"}}, id="skill-digests"),
    pytest.param({"provider_config_digest": "changed"}, id="provider-config"),
    pytest.param({"execution_config_digest": "changed"}, id="execution-config"),
    pytest.param({"base_extra_dirs": ["/new/dir"]}, id="extra-dirs"),
    pytest.param({"project_id": "some-project"}, id="project-id"),
    pytest.param({"file_policy": "inspect"}, id="file-policy"),
    pytest.param({"working_dir": "/opt/other"}, id="working-dir"),
    pytest.param({"provider_name": "codex"}, id="provider-name"),
]

_BASELINE_CTX = dict(
    role="engineer",
    active_skills=["code-review"],
    skill_digests={"code-review": "aaa"},
    provider_config_digest="pcd",
    execution_config_digest="ecd",
    base_extra_dirs=["/opt/repo"],
    project_id="",
    file_policy="",
    working_dir="",
    provider_name="",
)


@pytest.mark.parametrize("change", _HASH_FIELD_CHANGES)
def test_hash_sensitive_to_field(change):
    """Every identity field must affect the context hash."""
    baseline_hash = ResolvedExecutionContext(**_BASELINE_CTX).context_hash

    modified = {**_BASELINE_CTX, **change}
    modified_hash = ResolvedExecutionContext(**modified).context_hash

    assert baseline_hash != modified_hash, (
        f"Context hash must change when {list(change.keys())} changes"
    )


# =====================================================================
# Typed session round-trip
#
# PendingApproval and PendingRetry must survive a full round-trip
# through dict serialization and be reconstructed as the correct type.
# =====================================================================

def test_session_round_trip_approval():
    """PendingApproval survives dict serialization round-trip."""
    original = SessionState(
        provider="claude",
        provider_state={"thread_id": "t1"},
        approval_mode="on",
        active_skills=["deploy"],
        role="engineer",
        project_id="frontend",
        file_policy="inspect",
        pending_approval=PendingApproval(
            request_user_id=42,
            prompt="deploy to prod",
            image_paths=["/tmp/img.png"],
            attachment_dicts=[{"path": "/tmp/f", "original_name": "f", "is_image": False}],
            context_hash="abc123",
            created_at=1700000000.0,
        ),
    )
    d = session_to_dict(original)
    restored = session_from_dict(d)

    assert restored.pending_approval is not None
    assert restored.pending_retry is None
    assert restored.pending_approval.request_user_id == 42
    assert restored.pending_approval.prompt == "deploy to prod"
    assert restored.pending_approval.context_hash == "abc123"
    assert restored.pending_approval.attachment_dicts == original.pending_approval.attachment_dicts
    assert restored.role == "engineer"
    assert restored.project_id == "frontend"
    assert restored.file_policy == "inspect"


def test_session_round_trip_retry():
    """PendingRetry survives dict serialization round-trip."""
    original = SessionState(
        provider="claude",
        provider_state={},
        approval_mode="off",
        pending_retry=PendingRetry(
            request_user_id=99,
            prompt="edit config",
            image_paths=[],
            context_hash="def456",
            denials=[{"tool_name": "Write", "tool_input": {"file_path": "/etc/x"}}],
            created_at=1700000001.0,
        ),
    )
    d = session_to_dict(original)
    restored = session_from_dict(d)

    assert restored.pending_retry is not None
    assert restored.pending_approval is None
    assert restored.pending_retry.request_user_id == 99
    assert restored.pending_retry.denials == original.pending_retry.denials
    assert restored.pending_retry.context_hash == "def456"


def test_session_round_trip_no_pending():
    """Session with no pending request round-trips cleanly."""
    original = SessionState(
        provider="codex",
        provider_state={"thread_id": None},
        approval_mode="on",
        approval_mode_explicit=True,
        active_skills=["lint", "deploy"],
        role="devops",
    )
    d = session_to_dict(original)
    restored = session_from_dict(d)

    assert not restored.has_pending
    assert restored.approval_mode_explicit is True
    assert restored.active_skills == ["lint", "deploy"]


# =====================================================================
# resolve_execution_context produces same hash as _resolve_context
# =====================================================================

async def test_resolve_execution_context_matches_handler_adapter():
    """resolve_execution_context must produce same hash as handler _resolve_context."""
    with fresh_data_dir() as data_dir:
        project_dir = tempfile.mkdtemp()
        cfg = make_config(
            data_dir,
            projects=(("proj", project_dir, ()),),
        )
        prov = FakeProvider("codex")
        setup_globals(cfg, prov)

        import app.telegram_handlers as th

        chat = FakeChat(12345)
        user = FakeUser(42)

        # Set up session with project + policy
        await th.cmd_project(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["use", "proj"]),
        )
        await th.cmd_policy(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["inspect"]),
        )
        await th.cmd_role(
            FakeUpdate(message=FakeMessage(chat=chat), user=user, chat=chat),
            FakeContext(["architect"]),
        )

        # Get hash via handler adapter
        session_dict = load_session_disk(data_dir, 12345, prov)
        typed = session_from_dict(session_dict)
        handler_hash = th._resolve_context(typed).context_hash

        # Get hash via authoritative builder
        direct_hash = resolve_execution_context(typed, cfg, prov.name).context_hash

        assert handler_hash == direct_hash, (
            "Handler adapter and direct resolve must produce identical hashes"
        )


# =====================================================================
# execution_config_digest covers all BotConfig execution fields
# =====================================================================

_EXEC_CONFIG_FIELDS = [
    pytest.param("model", "gpt-4", "gpt-3.5", id="model"),
    pytest.param("codex_sandbox", "networking", "off", id="codex-sandbox"),
    pytest.param("codex_full_auto", True, False, id="codex-full-auto"),
    pytest.param("codex_dangerous", True, False, id="codex-dangerous"),
    pytest.param("codex_profile", "fast", "", id="codex-profile"),
]


@pytest.mark.parametrize("field_name, val_a, val_b", _EXEC_CONFIG_FIELDS)
def test_execution_config_digest_sensitive_to_field(field_name, val_a, val_b):
    """Every BotConfig execution field must affect the execution config digest."""
    cfg_a = _make_config(**{field_name: val_a})
    cfg_b = _make_config(**{field_name: val_b})
    digest_a = _compute_execution_config_digest(cfg_a)
    digest_b = _compute_execution_config_digest(cfg_b)
    assert digest_a != digest_b, (
        f"execution_config_digest must change when {field_name} changes"
    )


# =====================================================================
# Configured extra_dirs reach provider context
# =====================================================================

async def test_configured_extra_dirs_forwarded_to_provider():
    """extra_dirs from BotConfig must reach prov.run_calls[0]['context'].extra_dirs."""
    with fresh_data_dir() as data_dir:
        extra = Path(data_dir / "configured-extra")
        extra.mkdir()
        cfg = make_config(data_dir, extra_dirs=(extra,))
        prov = FakeProvider("claude")
        prov.run_results = [RunResult(text="ok")]
        setup_globals(cfg, prov)

        chat = FakeChat(12345)
        user = FakeUser(42)

        import app.telegram_handlers as th

        await th.handle_message(
            FakeUpdate(message=FakeMessage(chat=chat, text="hello"), user=user, chat=chat),
            FakeContext(),
        )

        assert len(prov.run_calls) == 1
        ctx = prov.run_calls[0]["context"]
        assert any(str(extra) in d for d in ctx.extra_dirs), (
            f"Configured extra_dirs not found in provider context: {ctx.extra_dirs}"
        )


# =====================================================================
# Model profile resolution
# =====================================================================

_MODEL_PROFILES = {"fast": "haiku", "balanced": "sonnet", "best": "opus"}


def test_model_profile_session_override():
    """Session model_profile overrides config default_model_profile."""
    from app.execution_context import resolve_effective_model

    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        model_profile="fast",
    )
    cfg = _make_config(model_profiles=_MODEL_PROFILES, default_model_profile="balanced")
    assert resolve_effective_model(session, cfg) == "haiku"


def test_model_profile_config_default():
    """Config default_model_profile is used when session has no override."""
    from app.execution_context import resolve_effective_model

    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(model_profiles=_MODEL_PROFILES, default_model_profile="best")
    assert resolve_effective_model(session, cfg) == "opus"


def test_model_profile_fallback_to_raw_model():
    """Falls back to config.model when no profiles configured."""
    from app.execution_context import resolve_effective_model

    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(model="claude-sonnet-4-6")
    assert resolve_effective_model(session, cfg) == "claude-sonnet-4-6"


def test_model_profile_changes_context_hash():
    """Changing session model_profile must change context hash."""
    cfg = _make_config(model_profiles=_MODEL_PROFILES, default_model_profile="balanced")

    session_a = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        model_profile="fast",
    )
    session_b = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        model_profile="best",
    )
    hash_a = resolve_execution_context(session_a, cfg, "claude").context_hash
    hash_b = resolve_execution_context(session_b, cfg, "claude").context_hash
    assert hash_a != hash_b, "Different model profiles must produce different context hashes"


def test_model_profile_session_round_trip():
    """model_profile survives session dict serialization."""
    original = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        model_profile="fast",
    )
    d = session_to_dict(original)
    restored = session_from_dict(d)
    assert restored.model_profile == "fast"


# =====================================================================
# Cross-feature: project + model change invalidation
# =====================================================================

def test_project_plus_model_change_invalidates_context_hash():
    """Changing both project and model should produce a different context hash."""
    cfg = _make_config(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        default_model_profile="fast",
        projects=(("proj-a", "/opt/a", []),),
    )

    session1 = SessionState(provider="claude", provider_state={}, approval_mode="off")
    session1.model_profile = "fast"
    session1.project_id = "proj-a"
    ctx1 = resolve_execution_context(session1, cfg, "claude")

    session2 = SessionState(provider="claude", provider_state={}, approval_mode="off")
    session2.model_profile = "best"
    session2.project_id = ""  # no project
    ctx2 = resolve_execution_context(session2, cfg, "claude")

    assert ctx1.context_hash != ctx2.context_hash


# =====================================================================
# Cross-feature: project + file_policy + approval + model change
# =====================================================================

def test_project_file_policy_approval_model_change_invalidates():
    """Pending approval with project+file_policy is invalidated by model change."""
    from app.request_flow import validate_pending

    cfg = _make_config(
        model_profiles={"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        default_model_profile="fast",
        projects=(("proj-a", "/opt/a", []),),
    )

    # Create session with project + file_policy + model=fast
    session = SessionState(provider="claude", provider_state={}, approval_mode="on")
    session.project_id = "proj-a"
    session.file_policy = "inspect"
    session.model_profile = "fast"

    ctx = resolve_execution_context(session, cfg, "claude")
    pending = PendingApproval(
        request_user_id=42,
        prompt="do work",
        image_paths=[],
        attachment_dicts=[],
        context_hash=ctx.context_hash,
        trust_tier="trusted",
    )

    # Validate immediately — should pass
    assert validate_pending(pending, session, cfg, "claude") is None

    # Change model profile
    session.model_profile = "best"
    error = validate_pending(pending, session, cfg, "claude")
    assert error is not None
    assert "context changed" in error.lower()

    # Also verify that changing file_policy invalidates
    session.model_profile = "fast"  # reset model
    session.file_policy = "edit"
    error2 = validate_pending(pending, session, cfg, "claude")
    assert error2 is not None
    assert "context changed" in error2.lower()


# =====================================================================
# Project extra_dirs folded into resolved context
# =====================================================================

def test_project_extra_dirs_folded_into_resolved_context():
    """Project extra_dirs appear in resolved base_extra_dirs."""
    with fresh_env(config_overrides={
        "projects": (("myproj", "/tmp/myproj", ("/tmp/proj-extra",)),),
    }) as (data_dir, cfg, prov):
        import app.telegram_handlers as th
        session = th._load(8006)
        session.project_id = "myproj"
        th._save(8006, session)

        resolved = resolve_execution_context(session, cfg, "claude")
        assert "/tmp/proj-extra" in resolved.base_extra_dirs, (
            f"Project extra_dirs should be in base_extra_dirs: {resolved.base_extra_dirs}"
        )


# =====================================================================
# Phase 15: Project-level file_policy and model_profile inheritance
#
# Resolution order:
#   file_policy:   session explicit > project default > ""
#   model_profile: session explicit > project default > config.default_model_profile > config.model
# =====================================================================


def test_file_policy_inherits_from_project():
    """Empty session file_policy inherits project default."""
    from app.session_state import ProjectBinding
    cfg = _make_config(projects=(
        ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),
    ))
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.file_policy == "inspect"


def test_file_policy_session_overrides_project():
    """Explicit session file_policy wins over project default."""
    from app.session_state import ProjectBinding
    cfg = _make_config(projects=(
        ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect"),
    ))
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe", file_policy="edit",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.file_policy == "edit"


def test_file_policy_no_project_no_session():
    """No project, no session file_policy → empty string."""
    cfg = _make_config()
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.file_policy == ""


def test_file_policy_project_default_empty_falls_through():
    """Project with empty file_policy does not override session empty."""
    from app.session_state import ProjectBinding
    cfg = _make_config(projects=(
        ProjectBinding(name="fe", root_dir="/tmp", file_policy=""),
    ))
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.file_policy == ""


def test_model_profile_inherits_from_project():
    """Empty session model_profile inherits project default."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        model_profiles=_MODEL_PROFILES,
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.effective_model == "haiku"


def test_model_profile_session_overrides_project():
    """Session model_profile wins over project default."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        model_profiles=_MODEL_PROFILES,
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe", model_profile="best",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.effective_model == "opus"


def test_model_profile_project_falls_through_to_global_default():
    """Project with empty model_profile falls through to config.default_model_profile."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", model_profile=""),),
        model_profiles=_MODEL_PROFILES,
        default_model_profile="balanced",
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.effective_model == "sonnet"


def test_project_defaults_change_context_hash():
    """Switching to a project with different defaults must change the context hash."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(
            ProjectBinding(name="fe", root_dir="/tmp", file_policy="inspect", model_profile="fast"),
            ProjectBinding(name="be", root_dir="/tmp", file_policy="edit", model_profile="best"),
        ),
        model_profiles=_MODEL_PROFILES,
    )
    session_a = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    session_b = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="be",
    )
    hash_a = resolve_execution_context(session_a, cfg, "claude").context_hash
    hash_b = resolve_execution_context(session_b, cfg, "claude").context_hash
    assert hash_a != hash_b


def test_public_trust_ignores_project_file_policy():
    """Public users are always forced to inspect, regardless of project default."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", file_policy="edit"),),
        public_working_dir="/tmp",
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    assert ctx.file_policy == "inspect"
    # Public users also get no project binding
    assert ctx.project_binding is None


def test_public_trust_ignores_project_model_profile():
    """Public users don't get project binding, so project model_profile is ignored."""
    from app.session_state import ProjectBinding
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", model_profile="best"),),
        model_profiles=_MODEL_PROFILES,
        public_working_dir="/tmp",
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )
    ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    # Project binding is None for public, so project profile is not used
    assert ctx.project_binding is None
    # Model falls through to config.model (no default_model_profile set)
    assert ctx.effective_model == cfg.model


def test_phantom_profile_not_displayed_when_no_profiles_configured():
    """When model_profiles is empty, display must show (default), not project profile name.

    This is a display-level guard: even if a project somehow has a model_profile
    set without any model_profiles configured, the UI must not show a phantom name.
    """
    from app.session_state import ProjectBinding
    # Note: this config would fail validation, but we test display resilience
    cfg = _make_config(
        projects=(ProjectBinding(name="fe", root_dir="/tmp", model_profile="fast"),),
        model_profiles={},  # no profiles
    )
    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
        project_id="fe",
    )

    # Import the display helper
    import app.telegram_handlers as th
    available, current = th._settings_model_profile_state(session, cfg, "trusted", cfg.model)
    assert available == []
    assert current == "(default)", f"Expected '(default)' but got '{current}'"
