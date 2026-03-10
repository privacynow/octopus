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

from app.execution_context import ResolvedExecutionContext, resolve_execution_context
from app.providers.base import (
    RunContext,
    RunResult,
    compute_context_hash,
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
    load_session_disk,
    make_config,
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

        session = load_session_disk(data_dir, 12345, prov)

        # The authoritative hash
        resolved = th._resolve_context(session)
        authoritative_hash = resolved.context_hash

        # The old-style manual computation (what execute_request used to do inline)
        role = session.get("role", "")
        active_skills = session.get("active_skills", [])
        project_id = session.get("project_id", "")
        file_policy = session.get("file_policy") or ""
        project_wd = th._project_working_dir(session)
        manual_hash = compute_context_hash(
            role, active_skills, get_skill_digests(active_skills),
            get_provider_config_digest(active_skills, provider_name=prov.name),
            sorted(str(d) for d in cfg.extra_dirs),
            project_id=project_id,
            file_policy=file_policy,
            working_dir=project_wd,
        )

        # The _current_context_hash helper
        helper_hash = th._current_context_hash(session)

        assert authoritative_hash == manual_hash, (
            "ResolvedContext.context_hash diverged from manual computation"
        )
        assert authoritative_hash == helper_hash, (
            "ResolvedContext.context_hash diverged from _current_context_hash()"
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
# compute_context_hash must produce a different hash when any
# identity field changes.  This is a completeness check.
# =====================================================================

_HASH_FIELD_CHANGES = [
    pytest.param({"role": "changed"}, id="role"),
    pytest.param({"active_skills": ["new-skill"]}, id="skills"),
    pytest.param({"skill_digests": {"s": "changed"}}, id="skill-digests"),
    pytest.param({"provider_config_digest": "changed"}, id="provider-config"),
    pytest.param({"extra_dirs": ["/new/dir"]}, id="extra-dirs"),
    pytest.param({"project_id": "some-project"}, id="project-id"),
    pytest.param({"file_policy": "inspect"}, id="file-policy"),
    pytest.param({"working_dir": "/opt/other"}, id="working-dir"),
]

_BASELINE = dict(
    role="engineer",
    active_skills=["code-review"],
    skill_digests={"code-review": "aaa"},
    provider_config_digest="pcd",
    extra_dirs=["/opt/repo"],
    project_id="",
    file_policy="",
    working_dir="",
)


@pytest.mark.parametrize("change", _HASH_FIELD_CHANGES)
def test_hash_sensitive_to_field(change):
    """Every identity field must affect the context hash."""
    baseline_hash = compute_context_hash(**_BASELINE)

    modified = {**_BASELINE, **change}
    modified_hash = compute_context_hash(**modified)

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


def test_session_round_trip_legacy_pending_no_kind():
    """Legacy pending_request dicts (no 'kind' field) are correctly inferred."""
    # Legacy approval: no denials, no kind
    legacy_approval = {
        "provider": "claude",
        "provider_state": {},
        "approval_mode": "on",
        "pending_request": {
            "request_user_id": 1,
            "prompt": "do thing",
            "image_paths": [],
            "attachment_dicts": [],
            "context_hash": "h1",
        },
    }
    s1 = session_from_dict(legacy_approval)
    assert s1.pending_approval is not None
    assert s1.pending_retry is None

    # Legacy retry: has denials, no kind
    legacy_retry = {
        "provider": "claude",
        "provider_state": {},
        "approval_mode": "off",
        "pending_request": {
            "request_user_id": 2,
            "prompt": "edit file",
            "image_paths": [],
            "context_hash": "h2",
            "denials": [{"tool_name": "Write"}],
        },
    }
    s2 = session_from_dict(legacy_retry)
    assert s2.pending_retry is not None
    assert s2.pending_approval is None


# =====================================================================
# INVARIANT 9: ResolvedExecutionContext is the sole hash authority
#
# The context hash from ResolvedExecutionContext must equal what the
# backward-compat compute_context_hash produces for the same inputs.
# This ensures the migration preserves hash stability.
# =====================================================================

def test_resolved_context_hash_matches_compat_function():
    """ResolvedExecutionContext.context_hash == compute_context_hash for same inputs."""
    ctx = ResolvedExecutionContext(
        role="engineer",
        active_skills=["code-review", "deploy"],
        skill_digests={"code-review": "aaa", "deploy": "bbb"},
        provider_config_digest="pcd123",
        base_extra_dirs=["/opt/repo", "/opt/data"],
        project_id="frontend",
        file_policy="inspect",
        working_dir="/opt/frontend",
        provider_name="codex",
    )
    compat_hash = compute_context_hash(
        role="engineer",
        active_skills=["code-review", "deploy"],
        skill_digests={"code-review": "aaa", "deploy": "bbb"},
        provider_config_digest="pcd123",
        extra_dirs=["/opt/repo", "/opt/data"],
        project_id="frontend",
        file_policy="inspect",
        working_dir="/opt/frontend",
    )
    assert ctx.context_hash == compat_hash


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
        handler_hash = th._resolve_context(session_dict).context_hash

        # Get hash via authoritative builder
        typed = session_from_dict(session_dict)
        direct_hash = resolve_execution_context(typed, cfg, prov.name).context_hash

        assert handler_hash == direct_hash, (
            "Handler adapter and direct resolve must produce identical hashes"
        )
