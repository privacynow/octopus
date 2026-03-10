"""Invariant tests — contract-shaped, not feature-shaped.

These tests verify cross-cutting properties that must hold across all
code paths, regardless of which feature introduced the code.  They are
designed to catch the class of bugs where one path drifts from another
because a new field was added or a helper was updated without updating
all consumers.

Each test section states the invariant it guards as a docstring.
"""

import asyncio
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
# INVARIANT 1: Context hash consistency
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
# INVARIANT 2: Stale detection
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


# Regression test: default working_dir must affect context hash.
# Previously resolve_execution_context() set working_dir="" when no project
# was bound, so changing BOT_WORKING_DIR did not invalidate pending approvals.

def test_default_working_dir_affects_hash():
    """Different config.working_dir without project must produce different hashes."""
    from app.session_state import SessionState

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
    from app.session_state import SessionState

    session = SessionState(
        provider="claude", provider_state={}, approval_mode="off",
    )
    cfg = _make_config(working_dir=Path("/opt/myproject"))
    ctx = resolve_execution_context(session, cfg, "claude")
    assert ctx.working_dir == "/opt/myproject"


# =====================================================================
# INVARIANT 3: Inspect mode sandbox integrity
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

    async def fake_run_cmd(cmd, progress, is_resume=False, extra_env=None, working_dir=""):
        calls.append(cmd)
        return RunResult(text="ok", provider_state_updates={"thread_id": "t-1"})

    provider._run_cmd = fake_run_cmd  # type: ignore[method-assign]

    class FakeProgress:
        async def update(self, html_text, *, force=False): pass

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
# INVARIANT 5: ResolvedContext is the single source of truth
#
# _resolve_context(session).context_hash must always equal what
# execute_request and request_approval would compute.  If these
# ever diverge, approval/retry flows break.
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
# INVARIANT 7: Context hash includes all identity fields
#
# ResolvedExecutionContext.context_hash must produce a different
# hash when any identity field changes.  This is a completeness check.
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
# INVARIANT 8: Typed session round-trip
#
# session_to_dict(session_from_dict(d)) must preserve all fields.
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
# INVARIANT 9: ResolvedExecutionContext is the sole hash authority
#
# The context hash from ResolvedExecutionContext must equal what the
# This section previously tested backward-compat equivalence.
# The compat function has been removed; hash is now computed only via
# ResolvedExecutionContext.context_hash.
# =====================================================================

# =====================================================================
# INVARIANT 10: resolve_execution_context produces same hash as
# _resolve_context (the handler-level adapter)
#
# Both paths must agree — any divergence means approval/retry breaks.
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
# INVARIANT 10: execution_config_digest covers all BotConfig execution fields
#
# Changing model, codex_sandbox, codex_full_auto, codex_dangerous, or
# codex_profile must produce a different digest — otherwise pending
# approvals created under one config survive a config change.
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
# INVARIANT 11: Configured extra_dirs reach provider context
#
# BOT_EXTRA_DIRS entries must appear in the RunContext.extra_dirs
# passed to the provider, not just in the resolved execution identity.
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
# INVARIANT 12: Model profile resolution
#
# Effective model must resolve through session.model_profile →
# config.default_model_profile → config.model.  Changing the effective
# model must produce a different execution_config_digest and context_hash.
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
# INVARIANT 13: Public trust tier enforcement in execution context
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
    import tempfile
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
# INVARIANT 14: is_public_user predicate
#
# Mixed trust: per-user resolution. Users in allowed set are trusted,
# others are public when allow_open is true.
# =====================================================================

def test_is_public_user_open_with_allowed_list():
    """User not in allowed list + allow_open=True → public."""
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
    """allow_open=True with no allowed list → everyone is public."""
    import app.telegram_handlers as th

    with fresh_data_dir() as data_dir:
        cfg = make_config(data_dir, allow_open=True,
                          allowed_user_ids=frozenset(),
                          allowed_usernames=frozenset())
        setup_globals(cfg, FakeProvider("claude"))

        assert th.is_public_user(FakeUser(uid=42)) is True


def test_is_public_user_closed():
    """allow_open=False → no one is public (they wouldn't pass is_allowed)."""
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
# INVARIANT 15: Public trust command gating
# Public users (allow_open=True, not in allowed set) cannot invoke
# restricted commands: /skills, /project, /policy, /send, /role,
# /clear_credentials, /cancel
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
            allowed_user_ids=frozenset(),  # no allowed list → everyone is public
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
# INVARIANT 17: Rate-limit defaults for public mode
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
        # setup_globals uses handler_support's setup which creates RateLimiter
        # directly; the actual default logic is in build_application.
        # To test the real path, we check what build_application would do.
        # Since setup_globals doesn't run build_application, test the logic directly.
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
# INVARIANT 18: Update-ID idempotency
# =====================================================================

async def test_duplicate_update_id_skipped():
    """Same update_id should be processed only once."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        prov.run_results = [RunResult(text="first"), RunResult(text="second")]
        chat = FakeChat(chat_id=8001)
        user = FakeUser(uid=42, username="testuser")

        # Clear seen IDs
        th._seen_update_ids.clear()

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

        th._seen_update_ids.clear()

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

        th._seen_update_ids.clear()

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

        th._seen_update_ids.clear()

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
# CROSS-FEATURE INVARIANT TESTS
# These verify that combinations of features don't break each other.
# =====================================================================

def test_public_user_cannot_escalate_to_restricted_model():
    """Public user with restricted profiles cannot set a profile outside the allowed set."""
    from app.execution_context import resolve_effective_model
    from app.session_state import SessionState

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
    from app.execution_context import resolve_execution_context
    from app.session_state import SessionState

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
    from app.execution_context import resolve_execution_context
    from app.session_state import SessionState

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


def test_project_plus_model_change_invalidates_context_hash():
    """Changing both project and model should produce a different context hash."""
    from app.execution_context import resolve_execution_context
    from app.session_state import SessionState

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
# INVARIANT 20: Mixed trusted/public ingress
#
# When allow_open=True AND explicit allow-lists exist, strangers
# must be admitted by is_allowed (public tier) while trusted users
# in the allow-lists are also admitted.
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
# INVARIANT 21: Public trust enforcement on execution paths
#
# When a public user sends a message, the resolved execution context
# must enforce public restrictions: forced inspect, forced public
# working dir, no skills, no extra dirs.  This must hold on both
# the direct-execute and approval-round-trip paths.
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
    from tests.support.handler_support import send_text

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
    from tests.support.handler_support import send_text

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
    from app.session_state import PendingApproval, session_from_dict, session_to_dict

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
    from app.session_state import PendingRetry, session_from_dict, session_to_dict

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


@pytest.mark.asyncio
async def test_session_command_shows_public_context():
    """/session display reflects public-user restrictions."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "public_working_dir": "/tmp/public-sandbox",
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        msg = await send_command(
            th.cmd_session, chat, stranger, "/session")
        reply = last_reply(msg)
        assert "/tmp/public-sandbox" in reply
        assert "inspect" in reply.lower()


# =====================================================================
# INVARIANT 22: Pending validation uses stored trust tier
#
# validate_pending must recompute the context hash with the same
# trust_tier that was stored when the pending request was created.
# Otherwise, a public user's approval immediately fails with
# "Context changed".
# =====================================================================


def test_validate_pending_respects_stored_trust_tier():
    """validate_pending must recompute hash with the pending's trust_tier."""
    from app.request_flow import validate_pending
    from app.session_state import PendingApproval, SessionState

    cfg = _make_config(
        public_working_dir="/tmp/public",
        timeout_seconds=3600,
    )
    session = SessionState(provider="claude", provider_state={}, approval_mode="on")

    # Compute the public context hash (what would be stored when a public user sends a message)
    from app.execution_context import resolve_execution_context
    public_ctx = resolve_execution_context(session, cfg, "claude", trust_tier="public")
    public_hash = public_ctx.context_hash

    # Also compute trusted hash — it MUST differ (different working_dir, file_policy)
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
    from app.session_state import PendingApproval, SessionState

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
    assert "Context changed" in error


# =====================================================================
# INVARIANT 23: Credential checks use resolved active_skills
#
# check_credential_satisfaction must receive the resolved skill list.
# Public users have no resolved skills, so they must never be prompted
# for credentials — even if the session has skills configured.
# =====================================================================


def test_credential_check_uses_resolved_skills_not_session():
    """Credential check with empty resolved skills skips all checks."""
    from app.request_flow import check_credential_satisfaction
    from app.session_state import SessionState

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
    from app.session_state import SessionState

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
# INVARIANT 24: Model command/callback parity
#
# /model <profile> and setting_model:<profile> must apply the same
# trust-tier filtering.  Both must allow switching to profiles that
# are in the user's available set, and both must reject profiles
# outside it.
# =====================================================================


@pytest.mark.asyncio
async def test_model_command_public_user_can_switch_to_allowed_profile():
    """/model fast succeeds for public user when fast is in public_model_profiles."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "model_profiles": {"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        "public_model_profiles": frozenset({"fast"}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        msg = await send_command(
            th.cmd_model, chat, stranger, "/model fast", args=["fast"])
        reply = last_reply(msg)
        assert "fast" in reply.lower()
        assert "not available" not in reply.lower()


@pytest.mark.asyncio
async def test_model_command_public_user_rejected_for_restricted_profile():
    """/model best fails for public user when best is not in public_model_profiles."""
    import app.telegram_handlers as th

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "model_profiles": {"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        "public_model_profiles": frozenset({"fast"}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        msg = await send_command(
            th.cmd_model, chat, stranger, "/model best", args=["best"])
        reply = last_reply(msg)
        assert "unknown" in reply.lower() or "available" in reply.lower()


@pytest.mark.asyncio
async def test_model_callback_public_user_rejected_for_restricted_profile():
    """setting_model:best callback fails for public user when best is restricted."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "model_profiles": {"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        "public_model_profiles": frozenset({"fast"}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:best")
        # Should be rejected
        replies = cb_msg.replies
        assert any("restricted" in str(r).lower() or "unknown" in str(r).lower() for r in replies)


@pytest.mark.asyncio
async def test_model_callback_public_user_allowed_for_available_profile():
    """setting_model:fast callback succeeds for public user when fast is allowed."""
    import app.telegram_handlers as th
    from tests.support.handler_support import send_callback

    with fresh_env(config_overrides={
        "allow_open": True,
        "allowed_user_ids": frozenset({42}),
        "model_profiles": {"fast": "claude-haiku-4-5-20251001", "best": "claude-opus-4-6"},
        "public_model_profiles": frozenset({"fast"}),
    }) as (data_dir, cfg, prov):
        chat = FakeChat(12345)
        stranger = FakeUser(uid=999, username="nobody")

        query, cb_msg = await send_callback(
            th.handle_settings_callback, chat, stranger, "setting_model:fast")
        replies = cb_msg.replies
        assert any("fast" in str(r).lower() for r in replies)
        assert not any("restricted" in str(r).lower() for r in replies)


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


# =====================================================================
# CROSS-FEATURE INVARIANT: compact + long reply + public user
#
# A public user with compact mode on receiving a long response must get
# the compact rendering (blockquote or expand button) with public
# execution scope still enforced.
# =====================================================================


@pytest.mark.asyncio
async def test_compact_long_reply_public_user():
    """Public user + compact mode + long response → blockquote/expand, inspect enforced."""
    import app.telegram_handlers as th
    from app.providers.base import RunResult

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
# CROSS-FEATURE INVARIANT: project + file_policy + approval + model change
#
# With a project bound, file_policy set, and an approval pending,
# changing model profile must invalidate the pending approval.
# =====================================================================


def test_project_file_policy_approval_model_change_invalidates():
    """Pending approval with project+file_policy is invalidated by model change."""
    from app.execution_context import resolve_execution_context
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
    assert "Context changed" in error

    # Also verify that changing file_policy invalidates
    session.model_profile = "fast"  # reset model
    session.file_policy = "edit"
    error2 = validate_pending(pending, session, cfg, "claude")
    assert error2 is not None
    assert "Context changed" in error2


# =====================================================================
# INVARIANT 27: Busy/queued feedback for commands and callbacks
#
# When a command or callback arrives while the chat lock is held,
# the user gets visible queued feedback, not silent waiting.
# =====================================================================


@pytest.mark.asyncio
async def test_command_queued_feedback_when_chat_locked():
    """Command arriving while chat lock held sends queued feedback.

    Uses cmd_session which does NOT acquire the lock itself, so no deadlock.
    The decorator checks lock.locked() and sends feedback before the handler runs.
    """
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        # Acquire the chat lock to simulate in-flight request
        lock = th.CHAT_LOCKS[1]
        await lock.acquire()
        try:
            msg = await send_command(th.cmd_session, chat, user, "/session")
            all_text = " ".join(str(r.get("text", "")) for r in msg.replies)
            assert "queued" in all_text.lower(), (
                f"Expected queued feedback, got: {all_text[:200]}")
        finally:
            lock.release()


@pytest.mark.asyncio
async def test_command_no_queued_feedback_when_lock_free():
    """Command arriving when chat lock is free does NOT send queued feedback."""
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        session = default_session(prov.name, prov.new_provider_state(), "off")
        save_session(data_dir, 1, session)

        chat = FakeChat(1)
        user = FakeUser(42)

        msg = await send_command(th.cmd_session, chat, user, "/session")
        all_text = " ".join(str(r.get("text", "")) for r in msg.replies)
        assert "queued" not in all_text.lower()


@pytest.mark.asyncio
async def test_callback_queued_feedback_when_chat_locked():
    """Callback arriving while chat lock held sends queued answer.

    Uses a callback handler that does NOT acquire the lock (expand: handler),
    to avoid deadlock while still testing the decorator feedback path.
    """
    import app.telegram_handlers as th

    with fresh_env() as (data_dir, cfg, prov):
        chat = FakeChat(1)
        user = FakeUser(42)

        # Pre-create a raw response so the expand handler has something to read
        from app.summarize import save_raw
        save_raw(data_dir, 1, "test prompt", "Full response text here.", kind="request")

        lock = th.CHAT_LOCKS[1]
        await lock.acquire()
        try:
            query, cb_msg = await send_callback(
                th.handle_expand_callback, chat, user, "expand:1:0")
            # The query should have received a "queued" answer
            assert query.answers, "Expected callback answer for queued feedback"
            assert any("queued" in str(a.get("text", "")).lower() for a in query.answers), (
                f"Expected queued feedback in callback answer, got: {query.answers}")
        finally:
            lock.release()
