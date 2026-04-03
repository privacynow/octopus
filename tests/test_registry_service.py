"""Tests for the FastAPI registry control-plane service."""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import app.content_store as content_store_mod
from app.execution_faults import LocalExecutionFaultState

os.environ.setdefault("REGISTRY_ALLOW_HTTP", "1")

from octopus_registry import auth as registry_auth
from octopus_registry.server import app
from octopus_registry import ingress
from octopus_registry.store import RegistrySQLiteStore
from app.runtime_health import (
    QueueSnapshot,
    RuntimeDiagnostic,
    RuntimeHealthReport,
    RuntimeHealthSummary,
    SharedRuntimeSnapshot,
    WorkerHeartbeat,
    report_to_dict,
)
from app.storage import default_session, ensure_data_dirs, save_session
from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key
from octopus_sdk.registry.management import (
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementRequest,
    ManagementResult,
)
from octopus_sdk.registry.management_executor import (
    ManagementExecutionContext,
    execute_management_request,
)
from octopus_sdk.providers import ProviderStateRecord

_FULL_MANAGEMENT_CAPABILITIES = [
    "skill_catalog",
    "skill_lifecycle",
    "provider_guidance",
    "conversation_skills",
    "agent_runtime",
]


def _configure_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")
    monkeypatch.delenv("REGISTRY_SESSION_SECRET", raising=False)
    registry_auth.reset_auth_attempt_limits_for_test()


def _configure_runtime_surface(monkeypatch, tmp_path: Path) -> Path:
    from app.runtime import composition as runtime_composition

    data_dir = tmp_path / "bot-data"
    monkeypatch.setenv("BOT_PROVIDER", "claude")
    monkeypatch.setenv("BOT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BOT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    ensure_data_dirs(data_dir)
    ingress.reset_for_test()
    runtime_composition.workflows.cache_clear()
    return data_dir


def _install_management_loopback(monkeypatch) -> None:
    from octopus_registry.management_client import RegistryManagementClient
    from app.config import load_config
    from app.runtime import composition

    async def _send(self, *, agent_id: str, payload, timeout_seconds: int = 30):
        self._assert_available(agent_id, str(payload.operation))
        request = ManagementRequest(
            agent_id=agent_id,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        config = load_config()
        result = await execute_management_request(
            request,
            context=ManagementExecutionContext(
                config=config,
                workflows=composition.workflows(),
                provider_state_factory=lambda _provider_name: ProviderStateRecord(
                    {"session_id": "registry-test", "started": False}
                ),
                execution_faults=LocalExecutionFaultState(config.data_dir),
            ),
        )
        return result

    monkeypatch.setattr(RegistryManagementClient, "send", _send)


def _login_ui(client: TestClient) -> None:
    response = client.post("/ui/login", data={"password": "ui-secret"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui"


def _ui_csrf_token(client: TestClient) -> str:
    response = client.get("/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _enroll_and_register(
    client: TestClient,
    name: str,
    slug: str,
    *,
    registry_scope: str = "full",
    management_capabilities: list[str] | None = None,
) -> tuple[str, str]:
    advertised_management_capabilities = management_capabilities or list(_FULL_MANAGEMENT_CAPABILITIES)
    bot_key = f"bot:{slug}"
    enroll = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "bot_key": bot_key,
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "registry_scope": registry_scope,
                "routing_skills": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "connectivity_state": "degraded",
                "channel_capabilities": ["telegram", "registry"],
                "management_capabilities": advertised_management_capabilities,
                "version": "test",
            },
        },
    )
    assert enroll.status_code == 200
    agent_id = enroll.json()["agent_id"]
    token = enroll.json()["agent_token"]
    register = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_card": {
                "bot_key": bot_key,
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "registry_scope": registry_scope,
                "routing_skills": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["telegram", "registry"],
                "management_capabilities": advertised_management_capabilities,
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    assert register.status_code == 200
    return agent_id, token


def _create_conversation(
    client: TestClient,
    token: str,
    agent_id: str,
    conversation_id: str,
    *,
    title: str = "Test conversation",
    origin_channel: str = "registry",
    external_conversation_ref: str = "",
) -> dict:
    """Create a conversation via the new API."""
    resp = client.post(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_agent_id": agent_id,
            "title": title,
            "origin_channel": origin_channel,
            "external_conversation_ref": external_conversation_ref or conversation_id,
        },
    )
    assert resp.status_code == 201, f"create_conversation failed: {resp.status_code} {resp.text}"
    return resp.json()


def _publish_events(
    client: TestClient,
    token: str,
    conversation_id: str,
    events: list[dict],
) -> dict:
    """Publish events to a conversation via the new API."""
    resp = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"events": events},
    )
    return resp.json() if resp.status_code == 200 else {"status_code": resp.status_code, "detail": resp.json().get("detail", "")}


def _runtime_health_payload() -> dict:
    report = RuntimeHealthReport(
        generated_at="2026-03-16T00:00:10+00:00",
        summary=RuntimeHealthSummary(
            status="degraded",
            healthy_worker_count=1,
            stale_worker_count=1,
            fresh_queued_count=2,
            claimed_count=1,
            pending_recovery_count=1,
            recovery_queued_count=0,
            oldest_claim_age_seconds=42,
            warning_count=1,
            error_count=0,
        ),
        snapshot=SharedRuntimeSnapshot(
            queue=QueueSnapshot(
                fresh_queued_count=2,
                claimed_count=1,
                pending_recovery_count=1,
                recovery_queued_count=0,
                oldest_claimed_at="2026-03-16T00:00:00+00:00",
            ),
            workers=(
                WorkerHeartbeat(
                    worker_id="worker-a",
                    process_role="worker",
                    started_at="2026-03-16T00:00:00+00:00",
                    last_seen_at="2026-03-16T00:00:10+00:00",
                    current_item_id="item-1",
                    current_conversation_key="tg:1",
                    current_kind="message",
                    items_processed=5,
                ),
                WorkerHeartbeat(
                    worker_id="worker-b",
                    process_role="worker",
                    started_at="2026-03-16T00:00:00+00:00",
                    last_seen_at="2026-03-16T00:00:00+00:00",
                    items_processed=1,
                ),
            ),
            healthy_worker_count=1,
            stale_worker_count=1,
        ),
        diagnostics=(
            RuntimeDiagnostic(
                level="warning",
                code="shared.pending_recovery_backlog",
                message="Shared Runtime has 1 item awaiting replay/discard.",
            ),
        ),
    )
    return report_to_dict(report)


def test_registry_enroll_register_heartbeat_and_search(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    heartbeat = client.post(
        "/v1/agents/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "connectivity_state": "connected",
            "current_capacity": 1,
            "max_capacity": 3,
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["agent"]["agent_id"] == agent_id

    search = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "developer", "skills": ["python"], "required_state": "connected"},
    )
    assert search.status_code == 200
    agents = search.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["slug"] == "dev-bot"
    assert agents[0]["connectivity_state"] == "connected"


def test_registry_list_agents_supports_query_and_state_filters(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _login_ui(client)

    _alpha_id, _alpha_token = _enroll_and_register(client, "Alpha Reviewer", "alpha-reviewer")
    _beta_id, beta_token = _enroll_and_register(client, "Beta Builder", "beta-builder")
    client.post(
        "/v1/agents/deregister",
        headers={"Authorization": f"Bearer {beta_token}"},
    )

    filtered = client.get("/v1/agents?q=review&state=connected")
    assert filtered.status_code == 200
    assert [item["slug"] for item in filtered.json()["agents"]] == ["alpha-reviewer"]

    disconnected = client.get("/v1/agents?state=disconnected")
    assert disconnected.status_code == 200
    assert [item["slug"] for item in disconnected.json()["agents"]] == ["beta-builder"]


def test_registry_channel_only_agent_gets_403_on_discovery(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _agent_id, token = _enroll_and_register(
        client,
        "Channel Bot",
        "channel-bot",
        registry_scope="channel",
    )

    response = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "developer", "required_state": "connected"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "registry_scope_not_permitted"


def test_registry_catalog_and_provider_preview(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    listed = client.get(
        f"/v1/agents/{agent_id}/catalog/skills?q=github",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    listed_payload = listed.json()["skills"]
    names = {item["name"] for item in listed_payload}
    assert "github-integration" in names
    github_summary = next(item for item in listed_payload if item["name"] == "github-integration")
    assert github_summary["source_kind"] == "builtin"
    assert github_summary["source_label"] == "Core"
    assert github_summary["can_activate"] is True
    assert github_summary["can_update"] is False
    assert github_summary["can_uninstall"] is False
    assert github_summary["requires_credentials"] is True
    assert github_summary["runtime_available"] is True

    detail = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/github-integration",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["name"] == "github-integration"
    assert payload["source_kind"] == "builtin"
    assert payload["source_label"] == "Core"
    assert "GITHUB_TOKEN" in payload["requirement_keys"]

    preview = client.post(
        f"/v1/agents/{agent_id}/guidance/claude/preview",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "role": "Senior engineer",
            "active_skills": ["github-integration"],
            "compact_mode": True,
        },
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["provider"] == "claude"
    assert preview_payload["prompt_weight"] > 0
    assert "summary first" in preview_payload["system_prompt"].lower()


def test_registry_lifecycle_endpoints_cover_skill_and_guidance(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    headers = {"Authorization": "Bearer ui-secret"}
    agent_id, _token = _enroll_and_register(client, "Lifecycle Bot", "lifecycle-bot")

    created = client.put(
        f"/v1/agents/{agent_id}/catalog/skills/release-notes/draft",
        headers=headers,
        json={
            "actor_key": "reg:ui",
            "body": "Summarize release notes carefully.",
            "description": "Release notes helper",
            "changelog": "initial draft",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "draft_saved"

    before_publish = client.get(f"/v1/agents/{agent_id}/catalog/skills/release-notes", headers=headers)
    assert before_publish.status_code == 200
    assert before_publish.json()["can_activate"] is False

    detail = client.get(f"/v1/agents/{agent_id}/catalog/skills/release-notes/lifecycle", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["lifecycle_status"] == "draft"
    assert detail.json()["source_label"] == "Custom"

    for path in ("submit", "approve", "publish"):
        response = client.post(
            f"/v1/agents/{agent_id}/catalog/skills/release-notes/{path}",
            headers=headers,
            json={"actor_key": "reg:ui", "note": path},
        )
        assert response.status_code == 200

    after_publish = client.get(f"/v1/agents/{agent_id}/catalog/skills/release-notes", headers=headers)
    assert after_publish.status_code == 200
    assert after_publish.json()["can_activate"] is True

    guidance_edit = client.put(
        f"/v1/agents/{agent_id}/guidance/claude/draft",
        headers=headers,
        json={
            "actor_key": "reg:ui",
            "body": "# Registry Guidance\n\nUse the registry lifecycle path.",
            "scope_kind": "system",
            "scope_key": "",
        },
    )
    assert guidance_edit.status_code == 200
    assert guidance_edit.json()["status"] == "draft_saved"

    preview_before = client.post(
        f"/v1/agents/{agent_id}/guidance/claude/preview",
        headers=headers,
        json={"role": "", "active_skills": [], "compact_mode": False},
    )
    assert preview_before.status_code == 200
    assert "Registry Guidance" not in preview_before.json()["effective_guidance"]

    for path in ("submit", "approve", "publish"):
        response = client.post(
            f"/v1/agents/{agent_id}/guidance/claude/{path}",
            headers=headers,
            json={"actor_key": "reg:ui", "note": path},
        )
        assert response.status_code == 200

    guidance_detail = client.get(f"/v1/agents/{agent_id}/guidance/claude", headers=headers)
    assert guidance_detail.status_code == 200
    assert guidance_detail.json()["lifecycle_status"] == "published"

    preview_after = client.post(
        f"/v1/agents/{agent_id}/guidance/claude/preview",
        headers=headers,
        json={"role": "", "active_skills": [], "compact_mode": False},
    )
    assert preview_after.status_code == 200
    assert "Registry Guidance" in preview_after.json()["effective_guidance"]


def test_registry_skill_draft_endpoint_accepts_full_package_updates(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    headers = {"Authorization": "Bearer ui-secret"}
    agent_id, _token = _enroll_and_register(client, "Package Bot", "package-bot")

    created = client.put(
        f"/v1/agents/{agent_id}/catalog/skills/pkg-skill/draft",
        headers=headers,
        json={
            "actor_key": "reg:ui",
            "display_name": "Package Skill",
            "body": "Package-aware draft body.",
            "description": "Registry package test",
            "requirements": [
                {
                    "key": "API_TOKEN",
                    "prompt": "Enter token",
                    "help_url": "https://example.test/token",
                }
            ],
            "provider_config": {
                "claude": {
                    "allowed_tools": ["bash"],
                }
            },
            "files": [
                {
                    "relative_path": "helper.sh",
                    "content_type": "text/x-shellscript",
                    "executable": True,
                    "content_text": "echo package",
                }
            ],
            "changelog": "initial package",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "draft_saved"

    detail = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/pkg-skill/lifecycle",
        headers=headers,
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["display_name"] == "Package Skill"
    assert payload["publish_ready"] is True
    assert payload["requirements"][0]["key"] == "API_TOKEN"
    assert payload["provider_config"]["claude"]["allowed_tools"] == ["bash"]
    assert payload["files"][0]["relative_path"] == "helper.sh"


def test_provider_guidance_preview_404_hides_raw_validation_text(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(client, "Guidance Bot", "guidance-bot")

    response = client.post(
        f"/v1/agents/{agent_id}/guidance/not-a-provider/preview",
        headers={"Authorization": "Bearer ui-secret"},
        json={"role": "", "active_skills": [], "compact_mode": False},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown provider guidance preview target."


def test_agent_scoped_management_route_reports_agent_not_connected(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(client, "Offline Bot", "offline-bot")

    client.post(
        "/v1/agents/deregister",
        headers={"Authorization": f"Bearer {_token}"},
    )

    response = client.get(
        f"/v1/agents/{agent_id}/catalog/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )

    assert response.status_code == 503
    assert "not connected" in response.json()["detail"].lower()


def test_agent_scoped_management_route_reports_missing_capability(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(
        client,
        "No Guidance Bot",
        "no-guidance-bot",
        management_capabilities=["skill_catalog"],
    )

    response = client.get(
        f"/v1/agents/{agent_id}/guidance/claude",
        headers={"Authorization": "Bearer ui-secret"},
    )

    assert response.status_code == 409
    assert "provider_guidance" in response.json()["detail"]


def test_agent_scoped_management_route_reports_request_timeout(monkeypatch, tmp_path: Path):
    from octopus_registry.management_client import ManagementClientError, RegistryManagementClient

    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(client, "Slow Bot", "slow-bot")

    async def _timeout(self, *, agent_id: str, payload, timeout_seconds: int = 30):
        del self, agent_id, payload, timeout_seconds
        raise ManagementClientError(
            status_code=504,
            error_code="request_timeout",
            detail="Timed out waiting for preview_provider_guidance from agent.",
        )

    monkeypatch.setattr(RegistryManagementClient, "send", _timeout)

    response = client.post(
        f"/v1/agents/{agent_id}/guidance/claude/preview",
        headers={"Authorization": "Bearer ui-secret"},
        json={"role": "", "active_skills": [], "compact_mode": False},
    )

    assert response.status_code == 504
    assert "timed out" in response.json()["detail"].lower()


def test_registry_lifecycle_endpoints_are_replay_safe(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    headers = {"Authorization": "Bearer ui-secret"}
    agent_id, _token = _enroll_and_register(client, "Replay Bot", "replay-bot")

    created = client.put(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/draft",
        headers=headers,
        json={
            "actor_key": "reg:ui",
            "body": "Replay-safe skill body.",
            "description": "Replay test",
            "changelog": "initial draft",
        },
    )
    assert created.status_code == 200

    first_submit = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/submit",
        headers=headers,
        json={"actor_key": "reg:ui", "note": "submit"},
    )
    assert first_submit.status_code == 200
    assert first_submit.json()["status"] == "submitted"

    second_submit = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/submit",
        headers=headers,
        json={"actor_key": "reg:ui", "note": "submit-again"},
    )
    assert second_submit.status_code == 200
    assert second_submit.json()["status"] == "already_submitted"

    first_approve = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/approve",
        headers=headers,
        json={"actor_key": "reg:ui", "note": "approve"},
    )
    assert first_approve.status_code == 200
    assert first_approve.json()["status"] == "approved"

    second_approve = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/approve",
        headers=headers,
        json={"actor_key": "reg:ui", "note": "approve-again"},
    )
    assert second_approve.status_code == 200
    assert second_approve.json()["status"] == "already_approved"

    lifecycle_before_publish = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/lifecycle",
        headers=headers,
    )
    assert lifecycle_before_publish.status_code == 200
    active_revision_id = lifecycle_before_publish.json()["active_revision_id"]

    store = content_store_mod.get_content_store()
    store.set_skill_revision_status("replay-skill", active_revision_id, "published")

    repaired_publish = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/publish",
        headers=headers,
        json={"actor_key": "reg:ui", "note": "publish"},
    )
    assert repaired_publish.status_code == 200
    assert repaired_publish.json()["status"] == "published"

    lifecycle_after_publish = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/replay-skill/lifecycle",
        headers=headers,
    )
    assert lifecycle_after_publish.status_code == 200
    detail = lifecycle_after_publish.json()
    assert detail["published_revision_id"] == active_revision_id
    assert sum(1 for item in detail["approvals"] if item["action"] == "submitted") == 1
    assert sum(1 for item in detail["approvals"] if item["action"] == "approved") == 1
    assert sum(1 for item in detail["approvals"] if item["action"] == "published") == 1


def test_registry_conversation_skill_activation_surface(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    conversation_key = telegram_conversation_key(12345)
    session = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
    save_session(data_dir, conversation_key, session)
    conv = _create_conversation(client, token, agent_id, "telegram:dev-bot:12345", title="Telegram chat 12345", origin_channel="telegram")
    conversation_id = conv["conversation_id"]

    activate = client.post(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills/code-review/activate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": telegram_actor_key(42)},
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "activated"

    listed = client.get(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == ["code-review"]

    deactivate = client.post(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills/code-review/deactivate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": telegram_actor_key(42)},
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["status"] == "removed"


def test_registry_conversation_skill_state_filters_unresolvable_raw_skills(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    conv = _create_conversation(client, token, agent_id, "telegram:dev-bot:12346", title="Telegram chat 12346", origin_channel="telegram")
    conversation_id = conv["conversation_id"]
    # Save session using the originating transport identity, not the registry conversation id.
    from octopus_sdk.identity import conversation_key_for_ref
    conversation_key = conversation_key_for_ref("telegram:dev-bot:12346")
    session = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
    session["active_skills"] = ["code-review", "missing-skill"]
    save_session(data_dir, conversation_key, session)

    listed = client.get(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == ["code-review"]


def test_registry_conversation_skill_surface_lazy_loads_default_session(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")

    conv = _create_conversation(client, token, agent_id, "conv-runtime-1", title="Registry runtime conversation")
    conversation_id = conv["conversation_id"]

    listed = client.get(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == []

    activate = client.post(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills/code-review/activate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": "reg:ui"},
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "activated"

    listed = client.get(
        f"/v1/agents/{agent_id}/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == ["code-review"]


def test_registry_catalog_install_and_uninstall(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    monkeypatch.setenv("BOT_REGISTRY_URL", "https://registry.example.test/index.json")
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(client, "Import Bot", "import-bot")
    helper_dir = tmp_path / "registry-helper"
    helper_dir.mkdir()
    (helper_dir / "skill.md").write_text(
        "---\nname: helper\ndisplay_name: Helper\ndescription: registry test\n---\n\nbody\n",
        encoding="utf-8",
    )

    from app.registry import RegistrySkill, skill_artifact_digest
    import app.skill_import_service as import_service

    monkeypatch.setattr(
        import_service.registry_client,
        "fetch_index",
        lambda registry_url: {
            "helper": RegistrySkill(
                name="helper",
                display_name="Helper",
                description="registry test",
                version="1.0.0",
                publisher="tests",
                digest=skill_artifact_digest(helper_dir),
                artifact_url="https://registry.example.test/artifacts/helper.tar.gz",
            )
        },
    )
    monkeypatch.setattr(
        import_service.registry_client,
        "download_artifact",
        lambda artifact_url, dest_dir: shutil.copytree(helper_dir, dest_dir, dirs_exist_ok=True),
    )

    install = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/helper/install",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert install.status_code == 200
    assert install.json()["ok"] is True

    detail = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/helper",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert detail.status_code == 200
    assert detail.json()["source_kind"] == "imported"
    assert detail.json()["can_update"] is True
    assert detail.json()["can_uninstall"] is True

    diff = client.get(
        f"/v1/agents/{agent_id}/catalog/skills/helper/diff",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert diff.status_code == 200
    assert "no differences" in diff.json()["diff"].lower()

    uninstall = client.post(
        f"/v1/agents/{agent_id}/catalog/skills/helper/uninstall",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert uninstall.status_code == 200
    assert uninstall.json()["ok"] is True


def test_registry_create_conversation_requires_origin_channel(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot")
    bind = client.post(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_agent_id": agent_id,
            "title": "Telegram chat 999",
            "external_conversation_ref": "999",
        },
    )
    assert bind.status_code == 422
    detail = bind.json()["detail"]
    assert any("origin_channel" in str(item) for item in (detail if isinstance(detail, list) else [detail]))

    conversations = client.get(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    assert conversations.json()["conversations"] == []


def test_registry_enroll_requires_explicit_registry_scope(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "display_name": "No Scope Bot",
                "slug": "no-scope-bot",
                "role": "developer",
                "routing_skills": ["python"],
                "tags": ["backend"],
                "description": "Writes code",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "version": "test",
            },
        },
    )

    assert response.status_code == 422
    assert "registry_scope" in response.json()["detail"]


def test_registry_register_requires_agent_card(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot-register")

    response = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {token}"},
        json={"connectivity_state": "connected"},
    )

    assert response.status_code == 422
    assert "agent_card" in response.json()["detail"]


def test_registry_search_rejects_invalid_skills_shape(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _agent_id, token = _enroll_and_register(client, "Dev Bot", "dev-bot-search-invalid")

    response = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"required_state": "connected", "skills": "python"},
    )

    assert response.status_code == 422
    assert "skills" in response.json()["detail"]


def test_ui_requires_session_cookie_redirects_to_login(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/ui/login"


def test_ui_login_with_correct_password_sets_cookie_and_redirects(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/ui/login",
        data={"password": "ui-secret"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ui"
    assert "registry_session=" in response.headers.get("set-cookie", "")


def test_ui_login_with_wrong_password_returns_form_with_error(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post("/ui/login", data={"password": "wrong-secret"})
    assert response.status_code == 200
    assert "Incorrect password." in response.text


def test_registry_enroll_rate_limits_repeated_failed_attempts(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    payload = {
        "enrollment_token": "wrong-secret",
        "agent_card": {
            "bot_key": "bot:dev-bot",
            "display_name": "Dev Bot",
            "slug": "dev-bot",
            "role": "developer",
            "registry_scope": "full",
            "routing_skills": ["python"],
            "provider": "codex",
            "mode": "registry",
        },
    }

    for _ in range(5):
        response = client.post("/v1/agents/enroll", json=payload)
        assert response.status_code == 401

    limited = client.post("/v1/agents/enroll", json=payload)

    assert limited.status_code == 429
    assert limited.headers["retry-after"]


def test_registry_enroll_success_clears_failed_attempt_throttle(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    bad_payload = {
        "enrollment_token": "wrong-secret",
        "agent_card": {
            "bot_key": "bot:dev-bot",
            "display_name": "Dev Bot",
            "slug": "dev-bot",
            "role": "developer",
            "registry_scope": "full",
            "routing_skills": ["python"],
            "provider": "codex",
            "mode": "registry",
        },
    }

    for _ in range(4):
        response = client.post("/v1/agents/enroll", json=bad_payload)
        assert response.status_code == 401

    good = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "bot_key": "bot:dev-bot",
                "display_name": "Dev Bot",
                "slug": "dev-bot",
                "role": "developer",
                "registry_scope": "full",
                "routing_skills": ["python"],
                "provider": "codex",
                "mode": "registry",
            },
        },
    )

    assert good.status_code == 200

    response = client.post("/v1/agents/enroll", json=bad_payload)
    assert response.status_code == 401


def test_ui_login_rate_limits_repeated_failed_attempts(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    for _ in range(5):
        response = client.post("/ui/login", data={"password": "wrong-secret"})
        assert response.status_code == 200

    limited = client.post("/ui/login", data={"password": "wrong-secret"})

    assert limited.status_code == 429
    assert limited.headers["retry-after"]


def test_ui_login_success_clears_failed_attempt_throttle(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    for _ in range(4):
        response = client.post("/ui/login", data={"password": "wrong-secret"})
        assert response.status_code == 200

    good = client.post("/ui/login", data={"password": "ui-secret"}, follow_redirects=False)
    assert good.status_code == 303

    response = client.post("/ui/login", data={"password": "wrong-secret"})
    assert response.status_code == 200


def test_registry_openapi_title_is_channel_neutral(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Agent Registry"


def test_registry_http_module_stays_under_guard_threshold():
    repo_root = Path(__file__).resolve().parents[1]
    http_path = repo_root / "octopus_registry" / "server.py"
    text = http_path.read_text()

    assert len(text.splitlines()) <= 1800


def test_registry_auth_load_settings_reads_registry_env(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("REGISTRY_DISPLAY_NAME", "QA Registry")

    settings = registry_auth.load_settings()

    assert settings.db_path == tmp_path / "registry.sqlite3"
    assert settings.enroll_token == "enroll-secret"
    assert settings.ui_token == "ui-secret"
    assert settings.display_name == "QA Registry"


def test_registry_auth_validate_settings_rejects_missing_enroll_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.delenv("REGISTRY_ENROLL_TOKEN", raising=False)
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject a missing enroll token"
    except RuntimeError as exc:
        assert "REGISTRY_ENROLL_TOKEN must be set" in str(exc)


def test_registry_auth_validate_settings_rejects_missing_ui_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.delenv("REGISTRY_UI_TOKEN", raising=False)

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject a missing UI token"
    except RuntimeError as exc:
        assert "REGISTRY_UI_TOKEN must be set" in str(exc)


def test_registry_auth_validate_settings_rejects_default_tokens(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "dev-enroll-token")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "dev-ui-token")

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject known default tokens"
    except RuntimeError as exc:
        assert "must not use a known default token" in str(exc)


def test_registry_auth_session_cookie_is_secure_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.delenv("REGISTRY_ALLOW_HTTP", raising=False)
    local_app = FastAPI()

    registry_auth.configure_session_middleware(local_app)

    assert local_app.user_middleware[0].kwargs["https_only"] is True


def test_registry_auth_session_cookie_can_allow_http_for_local_dev(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")
    local_app = FastAPI()

    registry_auth.configure_session_middleware(local_app)

    assert local_app.user_middleware[0].kwargs["https_only"] is False


def test_registry_auth_session_secret_fallback_is_stable(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.delenv("REGISTRY_SESSION_SECRET", raising=False)

    settings = registry_auth.load_settings()

    assert registry_auth.session_secret(settings=settings) == registry_auth.session_secret(settings=settings)

    app_one = FastAPI()
    app_two = FastAPI()
    registry_auth.configure_session_middleware(app_one)
    registry_auth.configure_session_middleware(app_two)

    assert app_one.user_middleware[0].kwargs["secret_key"] == app_two.user_middleware[0].kwargs["secret_key"]


def test_registry_auth_explicit_session_secret_overrides_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_SESSION_SECRET", "explicit-secret")

    assert registry_auth.session_secret() == "explicit-secret"


def test_registry_login_page_has_security_headers(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/ui/login")

    assert response.status_code == 200
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_registry_healthz_is_minimal_liveness_contract(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_registry_http_module_delegates_auth_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    http_path = repo_root / "octopus_registry" / "server.py"
    text = http_path.read_text()

    assert "class RegistrySettings" not in text
    assert "SessionMiddleware" not in text
    assert "def require_agent_token" not in text
    assert "def require_ui_token" not in text
    assert "def _session_is_valid" not in text
    assert "def _require_session" not in text


def test_publish_events_stores_events(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")
    conv = _create_conversation(client, token, agent_id, "conv-timeline-1", title="Timeline conversation")
    conversation_id = conv["conversation_id"]

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                    {
                        "event_id": "evt-1",
                        "kind": "message.user",
                        "actor": "alice",
                        "content": "Hello bot",
                        "created_at": "2026-03-15T00:00:00+00:00",
                        "metadata": {},
                    },
                    {
                        "event_id": "evt-2",
                        "kind": "message.bot",
                        "actor": "bot",
                        "content": "Hello alice",
                        "created_at": "2026-03-15T00:00:01+00:00",
                        "metadata": {},
                    },
            ]
        },
    )
    assert publish.status_code == 200

    events_resp = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert events_resp.status_code == 200
    events = events_resp.json()["events"]
    evt_ids = [e["event_id"] for e in events if e["event_id"] in ("evt-1", "evt-2")]
    assert evt_ids == ["evt-1", "evt-2"]
    kinds = [e["kind"] for e in events if e["event_id"] in ("evt-1", "evt-2")]
    assert kinds == ["message.user", "message.bot"]
    contents = [e["content"] for e in events if e["event_id"] in ("evt-1", "evt-2")]
    assert contents == ["Hello bot", "Hello alice"]


def test_list_events_supports_latest_window_and_bidirectional_sequence_paging(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Timeline Bot", "timeline-bot")
    conv = _create_conversation(client, token, agent_id, "conv-page-1", title="Paging conversation")
    conversation_id = conv["conversation_id"]

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": f"evt-{idx}",
                    "kind": "message.bot" if idx % 2 == 0 else "message.user",
                    "actor": "bot" if idx % 2 == 0 else "operator",
                    "content": f"event {idx}",
                    "created_at": f"2026-03-15T00:00:0{idx}+00:00",
                    "metadata": {},
                }
                for idx in range(1, 6)
            ]
        },
    )
    assert publish.status_code == 200

    latest = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 2},
    )
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert [item["event_id"] for item in latest_payload["events"]] == ["evt-4", "evt-5"]
    assert latest_payload["has_more_before"] is True
    assert latest_payload["next_before_seq"] == latest_payload["events"][0]["seq"]
    assert latest_payload["next_after_seq"] == latest_payload["events"][-1]["seq"]

    older = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 2, "before_seq": latest_payload["next_before_seq"]},
    )
    assert older.status_code == 200
    older_payload = older.json()
    assert [item["event_id"] for item in older_payload["events"]] == ["evt-2", "evt-3"]
    assert older_payload["has_more_before"] is True

    newer = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 5, "after_seq": older_payload["next_after_seq"]},
    )
    assert newer.status_code == 200
    newer_payload = newer.json()
    assert [item["event_id"] for item in newer_payload["events"]] == ["evt-4", "evt-5"]
    assert newer_payload["has_more_before"] is False

    invalid = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params={"before_seq": 2, "after_seq": 3},
    )
    assert invalid.status_code == 422


def test_publish_events_requires_event_id(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot-invalid-event")
    conv = _create_conversation(client, token, agent_id, "conv-invalid-event", title="Timeline conversation")
    conversation_id = conv["conversation_id"]

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "kind": "task.status",
                    "content": "test",
                }
            ]
        },
    )

    assert publish.status_code == 422


def test_summary_endpoint_returns_canonical_dashboard_aggregates(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-summary")
    target_id, target_token = _enroll_and_register(client, "Target Bot", "target-summary")
    conv = _create_conversation(client, origin_token, origin_id, "conv-summary-1", title="Summary conversation")
    conversation_id = conv["conversation_id"]

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-summary-provider",
                    "kind": "provider.response",
                    "actor": "codex",
                    "content": "",
                    "created_at": now_iso,
                    "metadata": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "cached_prompt_tokens": 5,
                        "cost_usd": 0.25,
                        "provider": "codex",
                    },
                },
                {
                    "event_id": "evt-summary-provider-claude",
                    "kind": "provider.response",
                    "actor": "claude",
                    "content": "",
                    "created_at": now_iso,
                    "metadata": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "cost_usd": 0.5,
                        "provider": "claude",
                    },
                },
                {
                    "event_id": "evt-summary-approval",
                    "kind": "approval.requested",
                    "actor": "operator",
                    "content": "Need approval",
                    "created_at": now_iso,
                    "metadata": {
                        "request_kind": "preflight",
                        "actor_key": "telegram:123",
                        "trust_tier": "trusted",
                        "expires_at": "2026-03-15T00:05:00+00:00",
                    },
                },
            ]
        },
    )
    assert publish.status_code == 200

    running_task = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-summary-running",
            "parent_conversation_id": conversation_id,
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Running review",
            "instructions": "Start this work.",
            "created_at": now_iso,
        },
    )
    assert running_task.status_code == 200

    target_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert target_poll.status_code == 200

    status = client.post(
        "/v1/agents/routed-tasks/task-summary-running/status",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "status": "running",
            "transition_id": "task-summary-running-start",
            "summary": "In progress",
            "timeline_events": [],
        },
    )
    assert status.status_code == 200

    pending_task = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-summary-pending",
            "parent_conversation_id": conversation_id,
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Pending review",
            "instructions": "Queue this work.",
            "created_at": now_iso,
        },
    )
    assert pending_task.status_code == 200

    _login_ui(client)
    summary = client.get("/v1/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["agents"] == {
        "total": 2,
        "connected": 2,
        "degraded": 0,
        "disconnected": 0,
        "execution_faulted": 0,
    }
    assert payload["conversations"] == {
        "total": 3,
        "active": 3,
        "pending_approvals": 1,
    }
    assert payload["tasks"] == {
        "running": 1,
        "pending": 1,
        "failed_24h": 0,
    }
    assert payload["usage_24h"] == {
        "prompt_tokens": 14,
        "completion_tokens": 9,
        "cached_prompt_tokens": 5,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": True,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.5,
        "cost_available": True,
    }


def test_usage_endpoint_rolls_up_delegated_child_usage(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-usage-rollup")
    target_id, target_token = _enroll_and_register(client, "Target Bot", "target-usage-rollup")
    conv = _create_conversation(client, origin_token, origin_id, "conv-usage-rollup", title="Usage rollup conversation")
    conversation_id = conv["conversation_id"]

    created = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-usage-rollup",
            "parent_conversation_id": conversation_id,
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Usage rollup task",
            "instructions": "Return only the number 4.",
            "created_at": now_iso,
        },
    )
    assert created.status_code == 200

    target_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert target_poll.status_code == 200

    running = client.post(
        "/v1/agents/routed-tasks/task-usage-rollup/status",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "status": "running",
            "transition_id": "task-usage-rollup-start",
            "summary": "In progress",
            "timeline_events": [],
        },
    )
    assert running.status_code == 200

    completed = client.post(
        "/v1/agents/routed-tasks/task-usage-rollup/result",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "status": "completed",
            "transition_id": "task-usage-rollup-complete",
            "summary": "4",
            "full_text": "4",
            "prompt_tokens": 13,
            "completion_tokens": 5,
            "cached_prompt_tokens": 8,
            "cost_usd": 0.17,
            "provider": "codex",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert completed.status_code == 200

    _login_ui(client)
    usage = client.get("/v1/usage", params={"since": "1970-01-01T00:00:00+00:00"})
    assert usage.status_code == 200
    payload = usage.json()
    assert payload["daily_total"] == {
        "prompt_tokens": 13,
        "completion_tokens": 5,
        "cached_prompt_tokens": 8,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": True,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.0,
        "cost_available": False,
    }
    row = next(item for item in payload["by_conversation"] if item["conversation_id"] == conversation_id)
    assert row == {
        "conversation_id": conversation_id,
        "title": "Usage rollup conversation",
        "prompt_tokens": 13,
        "completion_tokens": 5,
        "cached_prompt_tokens": 8,
        "cached_completion_tokens": 0,
        "cached_prompt_tokens_available": True,
        "cached_completion_tokens_available": False,
        "cost_usd": 0.0,
        "cost_available": False,
    }


def test_approvals_endpoint_returns_only_pending_requests(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    agent_id, agent_token = _enroll_and_register(client, "Approval Bot", "approval-endpoint")
    pending = _create_conversation(client, agent_token, agent_id, "conv-approval-pending", title="Pending review")
    decided = _create_conversation(client, agent_token, agent_id, "conv-approval-decided", title="Already handled")

    pending_publish = client.post(
        f"/v1/conversations/{pending['conversation_id']}/events",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-approval-pending",
                    "kind": "approval.requested",
                    "actor": "operator",
                    "content": "Review the plan",
                    "created_at": now_iso,
                    "metadata": {
                        "request_kind": "preflight",
                        "actor_key": "reg:operator",
                        "trust_tier": "trusted",
                        "expires_at": "2026-04-16T00:05:00+00:00",
                    },
                },
            ],
        },
    )
    assert pending_publish.status_code == 200

    decided_publish = client.post(
        f"/v1/conversations/{decided['conversation_id']}/events",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-approval-decided",
                    "kind": "approval.requested",
                    "actor": "operator",
                    "content": "Approve the release",
                    "created_at": now_iso,
                    "metadata": {
                        "request_kind": "delegation",
                        "actor_key": "reg:operator",
                        "trust_tier": "trusted",
                        "expires_at": "2026-04-16T00:05:00+00:00",
                    },
                },
            ],
        },
    )
    assert decided_publish.status_code == 200

    _login_ui(client)
    csrf = _ui_csrf_token(client)
    decision = client.post(
        f"/v1/conversations/{decided['conversation_id']}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"action_id": "approval-action-1", "action": "approve", "payload": {"request_id": "evt-approval-decided"}},
    )
    assert decision.status_code == 200

    approvals = client.get("/v1/approvals")
    assert approvals.status_code == 200
    payload = approvals.json()
    assert payload["has_more"] is False
    assert [item["conversation_id"] for item in payload["approvals"]] == [pending["conversation_id"]]
    assert payload["approvals"][0]["request_id"] == "evt-approval-pending"
    assert payload["approvals"][0]["request_kind"] == "preflight"


def test_cancel_conversation_marks_status_cancelling_and_late_progress_does_not_reopen(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-cancel")
    conv = _create_conversation(client, token, agent_id, "conv-cancel-1", title="Cancelable work")
    conversation_id = conv["conversation_id"]

    _login_ui(client)
    csrf_token = _ui_csrf_token(client)

    cancel = client.post(
        f"/v1/conversations/{conversation_id}/actions",
        headers={"X-CSRF-Token": csrf_token},
        json={"action_id": "cancel-action-1", "action": "cancel_conversation", "payload": {}},
    )
    assert cancel.status_code == 200

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                    {
                        "event_id": "evt-cancel-progress",
                        "kind": "task.status",
                        "content": "Still winding down",
                        "created_at": "2026-03-15T00:00:02+00:00",
                        "metadata": {"routed_task_id": "task-cancel-progress", "status": "running"},
                    }
                ]
            },
        )
    assert publish.status_code == 200

    conversation = client.get(
        f"/v1/conversations/{conversation_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversation.status_code == 200
    assert conversation.json()["status"] == "cancelling"


def test_agent_token_can_submit_action_for_own_conversation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-actions")
    conv = _create_conversation(client, token, agent_id, "conv-action-1", title="Actionable work")

    response = client.post(
        f"/v1/conversations/{conv['conversation_id']}/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"action_id": "cancel-action-agent", "action": "cancel_conversation", "payload": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["action"] == "cancel_conversation"


def test_agent_token_cannot_submit_action_for_other_agents_conversation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    owner_agent_id, owner_token = _enroll_and_register(client, "Owner Bot", "owner-bot-actions")
    _other_agent_id, other_token = _enroll_and_register(client, "Other Bot", "other-bot-actions")
    conv = _create_conversation(
        client,
        owner_token,
        owner_agent_id,
        "conv-action-foreign",
        title="Foreign conversation",
    )

    response = client.post(
        f"/v1/conversations/{conv['conversation_id']}/actions",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"action_id": "cancel-action-foreign", "action": "cancel_conversation", "payload": {}},
    )

    assert response.status_code == 403


def test_agent_resource_endpoints_round_trip(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Endpoint Bot", "endpoint-bot")
    conv = _create_conversation(
        client,
        token,
        agent_id,
        "conv-endpoint-1",
        title="Endpoint audit conversation",
    )
    conversation_id = conv["conversation_id"]

    _login_ui(client)
    csrf_token = _ui_csrf_token(client)
    add_message = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf_token},
        json={"text": "Operator note"},
    )
    assert add_message.status_code == 200

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-endpoint-1",
                    "kind": "message.bot",
                    "content": "Bot reply",
                    "created_at": "2026-03-28T07:00:00+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 200

    task_create = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "routed_task_id": "endpoint-task-1",
            "parent_conversation_id": conversation_id,
            "origin_agent_id": agent_id,
            "target_agent_id": agent_id,
            "title": "Endpoint task",
            "instructions": "Verify detail route",
        },
    )
    assert task_create.status_code == 200

    agent_status = client.get(
        f"/v1/agents/{agent_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent_status.status_code == 200
    assert agent_status.json()["agent_id"] == agent_id

    agent_conversations = client.get(
        f"/v1/agents/{agent_id}/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent_conversations.status_code == 200
    conversations = agent_conversations.json()["conversations"]
    conversation_ids = {item["conversation_id"] for item in conversations}
    titles = {item["title"] for item in conversations}
    assert conversation_id in conversation_ids
    assert len(conversations) >= 2
    assert titles >= {"Endpoint audit conversation", "Endpoint task"}

    listed_events = client.get(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed_events.status_code == 200
    assert any(item["event_id"] == "evt-endpoint-1" for item in listed_events.json()["events"])

    listed_messages = client.get(
        f"/v1/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed_messages.status_code == 200
    assert listed_messages.json()["events"][0]["content"] == "Operator note"

    exported = client.get(
        f"/v1/conversations/{conversation_id}/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "Endpoint audit conversation" in exported.text
    assert "Operator note" in exported.text

    task_detail = client.get(
        "/v1/tasks/endpoint-task-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_detail.status_code == 200
    assert task_detail.json()["routed_task_id"] == "endpoint-task-1"


def test_management_result_endpoint_and_ui_logout(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Management Bot", "management-bot")
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
    request = store.create_management_request(
        ManagementRequest(
            agent_id=agent_id,
            payload=ListCatalogSkillsRequest(query="github"),
            timeout_seconds=5,
        )
    )

    report = client.post(
        f"/v1/agents/management-requests/{request.request_id}/result",
        headers={"Authorization": f"Bearer {token}"},
        json=ManagementResult(
            request_id=request.request_id,
            agent_id=agent_id,
            success=True,
            payload=ListCatalogSkillsResult(items=()),
        ).model_dump(mode="json", by_alias=True),
    )
    assert report.status_code == 200
    assert report.json()["request_id"] == request.request_id

    stored = store.get_management_result(request.request_id)
    assert stored is not None
    assert stored.success is True
    assert stored.payload is not None
    assert stored.payload.operation == "list_catalog_skills"

    _login_ui(client)
    shell = client.get("/ui")
    assert shell.status_code == 200

    logout = client.get("/ui/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/ui/login"

    logged_out_shell = client.get("/ui", follow_redirects=False)
    assert logged_out_shell.status_code == 302
    assert logged_out_shell.headers["location"] == "/ui/login"


def test_publish_events_rejects_foreign_conversation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    owner_id, owner_token = _enroll_and_register(client, "Owner Bot", "owner-bot")
    _other_id, other_token = _enroll_and_register(client, "Other Bot", "other-bot")

    conv = _create_conversation(client, owner_token, owner_id, "conv-owner-1", title="Owner conversation")
    conversation_id = conv["conversation_id"]

    publish = client.post(
        f"/v1/conversations/{conversation_id}/events",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-foreign-1",
                    "kind": "task.status",
                    "content": "Should fail",
                }
            ]
        },
    )
    assert publish.status_code == 403


def test_agent_api_invalid_token_uses_generic_401_detail(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/agents/register",
        headers={"Authorization": "Bearer bad-token"},
        json={
            "agent_card": {
                "display_name": "Bot",
                "slug": "bot",
                "role": "developer",
                "routing_skills": ["python"],
                "tags": [],
                "description": "Writes code",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["telegram", "registry"],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired agent token."}


def test_registry_routed_result_returns_to_origin_agent(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin")
    target_id, target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target")
    conversation = _create_conversation(
        client,
        origin_token,
        origin_id,
        "conv-1",
        title="Delegation parent",
    )

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-1",
            "parent_conversation_id": conversation["conversation_id"],
            "origin_transport_ref": "telegram:product-origin:12345",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review test plan",
            "instructions": "Find missing test coverage.",
            "context": {},
            "constraints": {},
            "requested_skills": ["reviewer", "tests"],
            "priority": "normal",
            "created_at": "2026-03-15T00:00:00+00:00",
        },
    )
    assert routed.status_code == 200

    target_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert target_poll.status_code == 200
    assert target_poll.json()["deliveries"][0]["kind"] == "routed_task"

    started = client.post(
        "/v1/agents/routed-tasks/task-1/status",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "status": "running",
            "transition_id": "task-1-start",
            "summary": "In progress",
            "timeline_events": [],
        },
    )
    assert started.status_code == 200

    result = client.post(
        "/v1/agents/routed-tasks/task-1/result",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "status": "completed",
            "transition_id": "task-1-complete",
            "summary": "Added missing tests",
            "full_text": "Test plan updated with edge cases.",
            "artifacts": [],
            "follow_up_questions": [],
            "completed_at": "2026-03-15T00:01:00+00:00",
        },
    )
    assert result.status_code == 200

    origin_poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {origin_token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert origin_poll.status_code == 200
    origin_deliveries = origin_poll.json()["deliveries"]
    assert any(item["kind"] == "routed_result" for item in origin_deliveries)
    routed_result = next(item for item in origin_deliveries if item["kind"] == "routed_result")
    assert routed_result["payload"]["parent_transport_ref"] == "telegram:product-origin:12345"
    assert routed_result["payload"]["parent_external_conversation_ref"] == "conv-1"


def test_registry_conversation_endpoints_expose_and_filter_conversation_type(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-bot")
    target_id, target_token = _enroll_and_register(client, "Target Bot", "target-bot")
    regular = _create_conversation(
        client,
        target_token,
        target_id,
        "registry-conversation",
        title="Regular conversation",
        origin_channel="telegram",
        external_conversation_ref="telegram:origin:12345",
    )
    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-type-filter",
            "parent_conversation_id": regular["conversation_id"],
            "origin_transport_ref": "telegram:origin:12345",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Task projection",
            "instructions": "Inspect routing.",
        },
    )
    assert routed.status_code == 200

    all_conversations = client.get(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {target_token}"},
    )
    assert all_conversations.status_code == 200
    assert any(item["conversation_type"] == "task_thread" for item in all_conversations.json()["conversations"])

    task_threads = client.get(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"conversation_type": "task_thread"},
    )
    assert task_threads.status_code == 200
    assert task_threads.json()["conversations"]
    assert all(item["conversation_type"] == "task_thread" for item in task_threads.json()["conversations"])

    agent_conversations = client.get(
        f"/v1/agents/{target_id}/conversations",
        headers={"Authorization": f"Bearer {target_token}"},
        params={"conversation_type": "task_thread"},
    )
    assert agent_conversations.status_code == 200
    assert agent_conversations.json()["conversations"]
    assert all(item["conversation_type"] == "task_thread" for item in agent_conversations.json()["conversations"])


def test_registry_enroll_and_poll_expose_registry_epoch(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    enroll = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "bot_key": "bot:epoch-bot",
                "display_name": "Epoch Bot",
                "slug": "epoch-bot",
                "role": "developer",
                "registry_scope": "full",
                "routing_skills": ["python"],
                "tags": ["backend"],
                "description": "Epoch test bot",
                "provider": "codex",
                "mode": "registry",
                "connectivity_state": "degraded",
                "channel_capabilities": ["registry"],
                "management_capabilities": [],
                "version": "test",
            },
        },
    )
    assert enroll.status_code == 200
    registry_epoch = enroll.json()["registry_epoch"]
    token = enroll.json()["agent_token"]
    agent_id = enroll.json()["agent_id"]

    register = client.post(
        "/v1/agents/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_card": {
                "bot_key": "bot:epoch-bot",
                "display_name": "Epoch Bot",
                "slug": "epoch-bot",
                "role": "developer",
                "registry_scope": "full",
                "routing_skills": ["python"],
                "tags": ["backend"],
                "description": "Epoch test bot",
                "provider": "codex",
                "mode": "registry",
                "channel_capabilities": ["registry"],
                "management_capabilities": [],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )
    assert register.status_code == 200

    _create_conversation(
        client,
        token,
        agent_id,
        "epoch-conv-1",
        title="Epoch conversation",
    )
    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    assert poll.json()["registry_epoch"] == registry_epoch


def test_registry_list_tasks_can_filter_by_parent_conversation_id(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _login_ui(client)

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-bot")
    target_id, _target_token = _enroll_and_register(client, "Target Bot", "target-bot")
    first = _create_conversation(client, origin_token, origin_id, "conv-filter-1", title="First parent")
    second = _create_conversation(client, origin_token, origin_id, "conv-filter-2", title="Second parent")

    for task_id, parent_id in (
        ("task-filter-1", first["conversation_id"]),
        ("task-filter-2", second["conversation_id"]),
    ):
        response = client.post(
            "/v1/agents/routed-tasks",
            headers={"Authorization": f"Bearer {origin_token}"},
            json={
                "routed_task_id": task_id,
                "parent_conversation_id": parent_id,
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": f"Task {task_id}",
                "instructions": "Do work.",
                "created_at": "2026-03-25T00:00:00+00:00",
            },
        )
        assert response.status_code == 200

    filtered = client.get(
        "/v1/tasks",
        params={"parent_conversation_id": first["conversation_id"], "limit": 10},
    )
    assert filtered.status_code == 200
    assert [task["routed_task_id"] for task in filtered.json()["tasks"]] == ["task-filter-1"]


def test_registry_list_tasks_can_filter_by_completed_since_iso(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _login_ui(client)

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-bot-completed-filter")
    target_id, target_token = _enroll_and_register(client, "Target Bot", "target-bot-completed-filter")
    conversation = _create_conversation(client, origin_token, origin_id, "conv-completed-filter", title="Completed filter")

    for task_id, completed_at in (
        ("task-completed-old", "2026-03-15T00:00:00+00:00"),
        ("task-completed-recent", "2026-03-16T00:30:00+00:00"),
    ):
        routed = client.post(
            "/v1/agents/routed-tasks",
            headers={"Authorization": f"Bearer {origin_token}"},
            json={
                "routed_task_id": task_id,
                "parent_conversation_id": conversation["conversation_id"],
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": f"Task {task_id}",
                "instructions": "Do work.",
                "created_at": "2026-03-15T00:00:00+00:00",
            },
        )
        assert routed.status_code == 200

        poll = client.get(
            "/v1/agents/poll",
            headers={"Authorization": f"Bearer {target_token}"},
            params={"cursor": "0", "limit": 20, "wait_seconds": 0},
        )
        assert poll.status_code == 200

        started = client.post(
            f"/v1/agents/routed-tasks/{task_id}/status",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "running",
                "transition_id": f"{task_id}-running",
                "summary": "In progress",
                "timeline_events": [],
            },
        )
        assert started.status_code == 200

        completed = client.post(
            f"/v1/agents/routed-tasks/{task_id}/result",
            headers={"Authorization": f"Bearer {target_token}"},
            json={
                "status": "completed",
                "transition_id": f"{task_id}-complete",
                "summary": "Done",
                "full_text": "Finished",
                "completed_at": completed_at,
            },
        )
        assert completed.status_code == 200

    filtered = client.get(
        "/v1/tasks",
        params={
            "status": "completed",
            "completed_since_iso": "2026-03-16T00:00:00+00:00",
            "limit": 10,
        },
    )
    assert filtered.status_code == 200
    assert [task["routed_task_id"] for task in filtered.json()["tasks"]] == ["task-completed-recent"]


def test_registry_create_routed_task_requires_title(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin-invalid-task")
    target_id, _target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target-invalid-task")
    conversation = _create_conversation(
        client,
        origin_token,
        origin_id,
        "conv-1",
        title="Delegation validation",
    )

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-invalid",
            "parent_conversation_id": conversation["conversation_id"],
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "instructions": "Find missing test coverage.",
        },
    )

    assert routed.status_code == 422
    assert "title" in routed.json()["detail"]


def test_registry_ack_rejects_invalid_classification(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Ack Bot", "ack-bot")
    conv = _create_conversation(client, token, agent_id, "conv-ack-1", title="Ack conversation")
    conversation_id = conv["conversation_id"]

    _login_ui(client)
    csrf_token = _ui_csrf_token(client)
    msg = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf_token},
        json={"text": "hello"},
    )
    assert msg.status_code == 200

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    delivery_id = poll.json()["deliveries"][0]["delivery_id"]

    ack = client.post(
        "/v1/agents/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={"delivery_ids": [delivery_id], "classification": "later"},
    )

    assert ack.status_code == 422
    assert "classification" in ack.json()["detail"]


def test_registry_routed_task_status_requires_explicit_status(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin-status")
    target_id, target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target-status")
    conversation = _create_conversation(
        client,
        origin_token,
        origin_id,
        "conv-1",
        title="Delegation status validation",
    )

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-status-1",
            "parent_conversation_id": conversation["conversation_id"],
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review test plan",
            "instructions": "Find missing test coverage.",
            "created_at": "2026-03-15T00:00:00+00:00",
        },
    )
    assert routed.status_code == 200

    status = client.post(
        "/v1/agents/routed-tasks/task-status-1/status",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"summary": "missing status"},
    )

    assert status.status_code == 422
    assert "status" in status.json()["detail"]


def test_registry_routed_task_result_requires_explicit_status(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin-result")
    target_id, target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target-result")
    conversation = _create_conversation(
        client,
        origin_token,
        origin_id,
        "conv-1",
        title="Delegation result validation",
    )

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-result-1",
            "parent_conversation_id": conversation["conversation_id"],
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review test plan",
            "instructions": "Find missing test coverage.",
            "created_at": "2026-03-15T00:00:00+00:00",
        },
    )
    assert routed.status_code == 200

    result = client.post(
        "/v1/agents/routed-tasks/task-result-1/result",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"summary": "missing status"},
    )

    assert result.status_code == 422
    assert "status" in result.json()["detail"]


# ---------------------------------------------------------------------------
# Phase 2: Deterministic conversation ID contract tests
# ---------------------------------------------------------------------------


def test_create_conversation_returns_deterministic_id(monkeypatch, tmp_path: Path):
    """Creating a conversation with the same canonical fields must return the same conversation_id."""
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Det Bot", "det-bot")

    conv1 = _create_conversation(
        client,
        token,
        agent_id,
        "ext-ref-1",
        title="First title",
        origin_channel="telegram",
        external_conversation_ref="ext-ref-1",
    )
    conv2 = _create_conversation(
        client,
        token,
        agent_id,
        "ext-ref-1",
        title="Second title",
        origin_channel="telegram",
        external_conversation_ref="ext-ref-1",
    )
    assert conv1["conversation_id"] == conv2["conversation_id"]


def test_create_conversation_rejects_empty_origin_channel(monkeypatch, tmp_path: Path):
    """Creating a conversation with an empty origin_channel must fail validation."""
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Det Bot", "det-bot-oc")

    resp = client.post(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_agent_id": agent_id,
            "title": "bad",
            "origin_channel": "",
            "external_conversation_ref": "ref-1",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("origin_channel" in str(item) for item in (detail if isinstance(detail, list) else [detail]))


def test_create_conversation_rejects_empty_external_ref(monkeypatch, tmp_path: Path):
    """Creating a conversation with an empty external_conversation_ref must fail validation."""
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Det Bot", "det-bot-er")

    resp = client.post(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_agent_id": agent_id,
            "title": "bad",
            "origin_channel": "telegram",
            "external_conversation_ref": "",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("external_conversation_ref" in str(item) for item in (detail if isinstance(detail, list) else [detail]))


def test_create_conversation_idempotent_on_same_agent(monkeypatch, tmp_path: Path):
    """Creating twice with identical canonical fields returns the same row."""
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Idem Bot", "idem-bot")

    conv1 = _create_conversation(
        client,
        token,
        agent_id,
        "idem-ref",
        title="Original",
        origin_channel="telegram",
        external_conversation_ref="idem-ref",
    )
    conv2 = _create_conversation(
        client,
        token,
        agent_id,
        "idem-ref",
        title="Updated title",
        origin_channel="telegram",
        external_conversation_ref="idem-ref",
    )
    assert conv1["conversation_id"] == conv2["conversation_id"]
    # Title should be updated by the second call
    assert conv2["title"] == "Updated title"


def test_agent_status_endpoint_returns_typed_agent_status(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Status Bot", "status-bot")

    response = client.get(
        f"/v1/agents/{agent_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == agent_id
    assert payload["workers"] == []
    assert payload["active_conversations"] == 0
    assert payload["recent_errors"] == 0


def test_agent_execution_reset_clears_faulted_state(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        agent_id, _token = _enroll_and_register(client, "Reset Bot", "reset-bot")

        fault_state = LocalExecutionFaultState(data_dir)
        latched = fault_state.record_provider_failure(
            provider_name="claude",
            error_text="Not logged in · Please run /login",
            returncode=1,
        )
        assert latched is not None
        assert latched.state == "faulted"

        response = client.post(
            f"/v1/agents/{agent_id}/execution/reset",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["state"]["state"] == "healthy"
        assert payload["state"]["detail"] == ""
        assert fault_state.load().state == "healthy"
