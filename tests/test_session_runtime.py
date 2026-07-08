from app import runtime_backend
from pathlib import Path

from app.runtime.session_runtime import LocalSessionRuntime, save_runtime_session
from app.storage import ensure_data_dirs
from octopus_sdk.sessions import PendingApproval, SessionState
from tests.support.config_support import make_config
from tests.support.handler_support import FakeProvider


def _session(
    *,
    provider: str,
    approval_mode: str,
    thread_id: str,
    project_id: str = "",
) -> SessionState:
    return SessionState(
        provider=provider,
        provider_state={"thread_id": thread_id, "started": True},
        approval_mode=approval_mode,
        project_id=project_id,
        pending_approval=PendingApproval(
            actor_key="tg:42",
            prompt="run",
            image_paths=[],
            attachment_dicts=[],
            context_hash="ctx",
            created_at=0,
        ),
    )


def test_local_session_runtime_load_normalizes_single_project(tmp_path: Path) -> None:
    ensure_data_dirs(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        projects=(("workspace", str(workspace), ()),),
    )
    provider = FakeProvider("codex")
    runtime = LocalSessionRuntime(cfg)
    conversation_key = "tg:12345"
    runtime_backend.init(cfg)
    try:
        save_runtime_session(
            tmp_path,
            conversation_key,
            _session(provider="codex", approval_mode="off", thread_id="thread-123"),
        )

        loaded = runtime.load(
            conversation_key,
            provider_name="codex",
            provider_state_factory=provider.new_provider_state,
            approval_mode="off",
        )

        assert loaded.project_id == "workspace"
        assert loaded.provider_state.get("thread_id") is None
        assert loaded.pending_approval is None
    finally:
        runtime_backend.reset_for_test()


def test_local_session_runtime_load_resets_provider_mismatch(tmp_path: Path) -> None:
    ensure_data_dirs(tmp_path)
    cfg = make_config(data_dir=tmp_path, provider_name="claude")
    provider = FakeProvider("claude")
    runtime = LocalSessionRuntime(cfg)
    conversation_key = "tg:provider-switch"
    runtime_backend.init(cfg)
    try:
        save_runtime_session(
            tmp_path,
            conversation_key,
            _session(provider="codex", approval_mode="off", thread_id="thread-123"),
        )

        loaded = runtime.load(
            conversation_key,
            provider_name="claude",
            provider_state_factory=provider.new_provider_state,
            approval_mode="off",
        )

        assert loaded.provider == "claude"
        assert loaded.provider_state.get("thread_id") is None
        assert loaded.provider_state.get("session_id")
        assert loaded.provider_state.get("started") is False
        assert loaded.pending_approval is None
    finally:
        runtime_backend.reset_for_test()


def test_local_session_runtime_recover_after_crash_normalizes_single_project(tmp_path: Path) -> None:
    ensure_data_dirs(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = make_config(
        data_dir=tmp_path,
        provider_name="codex",
        projects=(("workspace", str(workspace), ()),),
    )
    provider = FakeProvider("codex")
    runtime = LocalSessionRuntime(cfg)
    conversation_key = "tg:67890"
    runtime_backend.init(cfg)
    try:
        save_runtime_session(
            tmp_path,
            conversation_key,
            _session(provider="codex", approval_mode="off", thread_id="thread-456"),
        )

        loaded = runtime.recover_after_crash(
            conversation_key,
            provider_name="codex",
            provider_state_factory=provider.new_provider_state,
            approval_mode="off",
        )

        assert loaded is not None
        assert loaded.project_id == "workspace"
        assert loaded.provider_state.get("thread_id") is None
        assert loaded.pending_approval is None
    finally:
        runtime_backend.reset_for_test()
