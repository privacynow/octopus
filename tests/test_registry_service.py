"""Tests for the FastAPI registry control-plane service."""

import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import app.content_store as content_store_mod
from app.execution_faults import LocalExecutionFaultState

os.environ.setdefault("REGISTRY_ALLOW_HTTP", "1")

from octopus_registry import auth as registry_auth
from octopus_registry import server as registry_server
from octopus_registry import protocol_http as registry_protocol_http
from octopus_registry import protocol_store as protocol_store_mod
from octopus_registry.server import app
from octopus_registry import ingress
from octopus_registry.backend import get_registry_store
from app.runtime_health import (
    QueueSnapshot,
    RuntimeDiagnostic,
    RuntimeHealthReport,
    RuntimeHealthSummary,
    SharedRuntimeSnapshot,
    WorkerHeartbeat,
    report_to_dict,
)
from app.storage import default_session, ensure_data_dirs, load_session, save_session, session_exists
from octopus_sdk.identity import telegram_actor_key, telegram_conversation_key
from octopus_sdk.protocols import (
    ProtocolArtifactRecord,
    ProtocolArtifactRuntimeActionResultRecord,
    ProtocolArtifactRuntimeInstanceRecord,
    ProtocolArtifactRuntimeManifestRecord,
    ProtocolAccessContextRecord,
    ProtocolAutoDesignModelResponseRecord,
    ProtocolAutoDesignRequestRecord,
    ProtocolAutoDesignWorkPackageRecord,
    ProtocolDefinitionRecord,
    ProtocolDefinitionVersionRecord,
    ProtocolMutationRecord,
    ProtocolRunDetailRecord,
    ProtocolRunMutationRecord,
    ProtocolRunRecord,
    generate_auto_protocol_session,
)
from octopus_sdk.registry.management import (
    ALL_MANAGEMENT_OPERATIONS,
    DesignAutoProtocolResult,
    ListCatalogSkillsRequest,
    ListCatalogSkillsResult,
    ManagementRequest,
    ManagementResult,
    StopArtifactRuntimeResult,
)
from octopus_sdk.registry.models import AgentRecord, RegistryJsonRecord, TaskRecord
from octopus_sdk.registry.management_executor import (
    ManagementExecutionContext,
    execute_management_request,
)
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.skill_packages import SkillPackageRecord, skill_document_to_text, skill_package_document

_FULL_MANAGEMENT_OPERATIONS = list(ALL_MANAGEMENT_OPERATIONS)


def _auto_design_model_response(*package_keys: str) -> ProtocolAutoDesignModelResponseRecord:
    return ProtocolAutoDesignModelResponseRecord(
        requirement_summary="Create the requested protocol.",
        domain="requirement-specific",
        work_packages=[
            ProtocolAutoDesignWorkPackageRecord(
                package_key=key,
                display_name=key.replace("_", " ").title(),
                rationale=f"{key} is needed for the requested outcome.",
                purpose=f"Produce {key.replace('_', ' ')} for the requested outcome.",
                quality_bar="The artifact is concrete, inspectable, and ready for downstream use.",
                required_skills=[key.replace("_", " ")],
            )
            for key in (package_keys or ("experience_design",))
        ],
        acceptance_criteria=["Primary artifact exists, opens, and has release evidence."],
    )


@pytest.fixture(autouse=True)
def _close_registry_test_clients(monkeypatch):
    original_init = TestClient.__init__
    created: list[TestClient] = []

    def _tracked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(TestClient, "__init__", _tracked_init)
    yield
    while created:
        client = created.pop()
        with contextlib.suppress(Exception):
            client.close()


def _configure_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")
    monkeypatch.delenv("REGISTRY_SESSION_SECRET", raising=False)
    registry_auth.reset_auth_attempt_limits_for_test()


def _configure_runtime_surface(monkeypatch, tmp_path: Path) -> Path:
    from app.db.postgres import get_connection
    from app.runtime import composition as runtime_composition
    from app.config import load_config
    from app.runtime.startup import initialize_runtime_health_startup
    from tests.support.handler_support import reset_handler_test_runtime
    from tests.support.postgres_support import (
        truncate_content_tables,
        truncate_credential_tables,
        truncate_registry_tables,
        truncate_runtime_tables,
    )

    data_dir = tmp_path / "bot-data"
    monkeypatch.setenv("BOT_PROVIDER", "claude")
    monkeypatch.setenv("BOT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BOT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv("BOT_CREDENTIAL_KEY", "registry-test-credential-key")
    reset_handler_test_runtime()
    ingress.reset_for_test()
    database_url = os.environ["OCTOPUS_DATABASE_URL"]
    with get_connection(database_url) as conn:
        truncate_runtime_tables(conn)
        truncate_registry_tables(conn)
        truncate_content_tables(conn)
        truncate_credential_tables(conn)
    initialize_runtime_health_startup(load_config())
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
    supported_admin_operations: list[str] | None = None,
) -> tuple[str, str]:
    advertised_supported_admin_operations = supported_admin_operations or list(_FULL_MANAGEMENT_OPERATIONS)
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
                "transport_implementations": ["telegram", "registry"],
                "supported_admin_operations": advertised_supported_admin_operations,
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
                "transport_implementations": ["telegram", "registry"],
                "supported_admin_operations": advertised_supported_admin_operations,
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
    assert filtered.json()["agents"][0]["selector"] == "@alpha-reviewer"
    assert filtered.json()["agents"][0]["selector_aliases"] == ["@alpha-reviewer"]
    assert filtered.json()["agents"][0]["role_selector"] == "@role:developer"

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
    assert "summary first" in preview_payload["composed_prompt"].lower()


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
    assert "Registry Guidance" not in preview_before.json()["published_guidance"]

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
    assert "Registry Guidance" in preview_after.json()["published_guidance"]
    assert "Registry Guidance" in preview_after.json()["composed_prompt"]


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


def test_agent_scoped_management_route_reports_missing_admin_operation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    agent_id, _token = _enroll_and_register(
        client,
        "No Guidance Bot",
        "no-guidance-bot",
        supported_admin_operations=["list_catalog_skills"],
    )

    response = client.get(
        f"/v1/agents/{agent_id}/guidance/claude",
        headers={"Authorization": "Bearer ui-secret"},
    )

    assert response.status_code == 409
    assert "provider_guidance_detail" in response.json()["detail"]


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
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")

    conv = _create_conversation(
        client,
        token,
        agent_id,
        "conv-runtime-1",
        title="Registry runtime conversation",
        origin_channel="registry",
        external_conversation_ref="ui-runtime-1",
    )
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
    canonical_key = f"registry:conversation:{conversation_id}"
    stored = load_session(
        data_dir,
        canonical_key,
        "claude",
        lambda _conversation_key="": {"session_id": "test", "started": False},
        "on",
    )
    assert stored["active_skills"] == ["code-review"]
    assert session_exists(data_dir, canonical_key) is True
    assert session_exists(data_dir, "ui-runtime-1") is False


def test_registry_conversation_skill_state_uses_canonical_registry_key(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    _install_management_loopback(monkeypatch)
    client = TestClient(app)
    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")

    conv = _create_conversation(
        client,
        token,
        agent_id,
        "conv-runtime-2",
        title="Registry runtime conversation",
        origin_channel="registry",
        external_conversation_ref="ui-runtime-2",
    )
    conversation_id = conv["conversation_id"]
    canonical_key = f"registry:conversation:{conversation_id}"
    session = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
    session["active_skills"] = ["code-review"]
    save_session(data_dir, canonical_key, session)

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
                "transport_implementations": ["registry"],
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
    cookie = response.headers.get("set-cookie", "")
    assert "registry_session=" in cookie
    assert "samesite=lax" in cookie.lower()


def test_ui_login_with_wrong_password_returns_form_with_error(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post("/ui/login", data={"password": "wrong-secret"})
    assert response.status_code == 200
    assert "Incorrect password." in response.text


def test_ui_shell_renders_versioned_assets_with_no_store_headers(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _login_ui(client)

    response = client.get("/ui")

    assert response.status_code == 200
    assert "__UI_ASSET_VERSION__" not in response.text
    assert "/ui/js/api.js?v=" in response.text
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_ui_static_assets_are_served_with_no_store_headers(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/ui/js/api.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


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


def test_protocol_openapi_exposes_archive_and_created_after_filter(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/protocols/{protocol_id}/archive" in paths
    assert "/v1/protocol-authoring/options" in paths
    assert "/v1/protocol-authoring/manifest" not in paths
    assert "/v1/protocol-drafts" in paths
    protocol_list_parameters = {
        item["name"]
        for item in paths["/v1/protocols"]["get"].get("parameters", [])
    }
    assert "created_after" in protocol_list_parameters
    assert "/v1/protocol-runs/issues" in paths


def test_protocol_openapi_exposes_parse_export_diff_and_run_filters(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/protocol-templates" in paths
    assert "/v1/protocol-templates/{slug}" in paths
    assert "/v1/protocols/parse" in paths
    assert "/v1/protocols/{protocol_id}/draft/export" in paths
    assert "/v1/protocols/{protocol_id}/package/export" in paths
    assert "/v1/protocols/package/import/plan" in paths
    assert "/v1/protocols/package/import/apply" in paths
    assert "/v1/protocols/{protocol_id}/diff" in paths
    assert "/v1/protocols/{protocol_id}/template" not in paths
    assert paths["/v1/protocol-drafts"]["post"]["requestBody"]
    run_list_parameters = {
        item["name"]
        for item in paths["/v1/protocol-runs"]["get"].get("parameters", [])
    }
    assert "entry_agent_id" in run_list_parameters
    assert "root_conversation_id" in run_list_parameters
    assert "origin_channel" in run_list_parameters
    task_list_parameters = {
        item["name"]
        for item in paths["/v1/tasks"]["get"].get("parameters", [])
    }
    assert "protocol_run_id" in task_list_parameters
    assert "/v1/tasks/{routed_task_id}/artifacts/{artifact_key}/content" in paths
    assert "/v1/protocol-runs/{run_id}/artifacts/{artifact_key}/content" in paths


def test_registry_openapi_asset_matches_generated_schema(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    expected_path = Path(__file__).resolve().parents[1] / "docs" / "registry-openapi.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json() == expected


def test_protocol_document_routes_round_trip_parse_export_and_diff(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def parse_protocol_document_text(self, *, access, definition_text: str, format: str = "json", validation_mode: str = "strict"):
            assert format == "yaml"
            assert validation_mode == "strict"
            assert "schema_version: 1" in definition_text
            return {
                "format": "yaml",
                "text": "schema_version: 1\nmetadata:\n  slug: demo\n",
                "document": {
                    "schema_version": 1,
                    "metadata": {"slug": "demo"},
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                    "policies": {"single_active_writer": True, "max_review_rounds": 5},
                },
                "validation": {
                    "mode": "strict",
                    "ok": True,
                    "errors": [],
                    "issues": [],
                    "next_required_actions": [],
                    "content_hash": "hash-1",
                },
            }

        def export_protocol_draft(self, protocol_id: str, *, access, format: str = "json"):
            assert protocol_id == "protocol-1"
            assert format == "yaml"
            return {
                "format": "yaml",
                "text": "schema_version: 1\nmetadata:\n  slug: demo\n",
                "document": {
                    "schema_version": 1,
                    "metadata": {"slug": "demo"},
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                    "policies": {"single_active_writer": True, "max_review_rounds": 5},
                },
                "validation": {
                    "mode": "draft",
                    "ok": True,
                    "errors": [],
                    "issues": [],
                    "next_required_actions": [],
                    "content_hash": "hash-1",
                },
            }

        def diff_protocol_draft(self, protocol_id: str, *, access, format: str = "json"):
            assert protocol_id == "protocol-1"
            assert format == "json"
            return {
                "protocol_id": protocol_id,
                "protocol_definition_version_id": "version-1",
                "diff": "--- draft\n+++ published\n@@\n-description: next\n+description: current\n",
                "left_label": "draft",
                "right_label": "published",
            }

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "publisher", "author"),
    )
    try:
        parse_response = client.post(
            "/v1/protocols/parse",
            json={"definition_text": "schema_version: 1\nmetadata:\n  slug: demo\n", "format": "yaml"},
        )
        export_response = client.get("/v1/protocols/protocol-1/draft/export?format=yaml")
        diff_response = client.get("/v1/protocols/protocol-1/diff?format=json")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert parse_response.status_code == 200
    assert parse_response.json()["format"] == "yaml"
    assert export_response.status_code == 200
    assert export_response.json()["text"].startswith("schema_version: 1")
    assert diff_response.status_code == 200
    assert diff_response.json()["left_label"] == "draft"


def test_protocol_package_export_composes_required_skill_document(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    protocol_document = {
        "schema_version": 1,
        "metadata": {"slug": "handoff", "display_name": "Handoff", "description": "Customer package"},
        "participants": [{"participant_key": "worker", "display_name": "Worker", "instructions": ""}],
        "artifacts": [{"artifact_key": "handoff", "display_name": "Handoff", "kind": "workspace_file", "path": "handoff.md", "verify": True}],
        "stages": [{
            "stage_key": "prepare",
            "display_name": "Prepare",
            "participant_key": "worker",
            "selector": {"kind": "skill", "value": "handoff-skill", "preferred_agent_id": "agent-1"},
            "stage_kind": "work",
            "instructions": "Prepare it.",
            "inputs": [],
            "outputs": ["handoff"],
            "transitions": {"completed": "__complete__"},
            "write_capable": True,
        }],
        "policies": {"single_active_writer": True, "max_review_rounds": 5},
    }
    skill_text = skill_document_to_text(
        skill_package_document(
            SkillPackageRecord(
                skill_name="handoff-skill",
                display_name="Handoff Skill",
                description="Write handoffs.",
                body="Write handoff material.",
                skill_kind="prompt",
            )
        ),
        format="json",
    )

    class _Store:
        def get_protocol(self, protocol_id: str, *, access):
            assert protocol_id == "protocol-1"
            return ProtocolMutationRecord(
                ok=True,
                status="loaded",
                protocol=ProtocolDefinitionRecord(
                    protocol_id="protocol-1",
                    slug="handoff",
                    display_name="Handoff",
                    current_version_id="version-1",
                ),
                draft_definition_json=RegistryJsonRecord.model_validate(protocol_document),
                version=ProtocolDefinitionVersionRecord(
                    protocol_definition_version_id="version-1",
                    protocol_id="protocol-1",
                    version=1,
                    definition_json=RegistryJsonRecord.model_validate(protocol_document),
                    content_hash="hash",
                ),
            )

        def list_agents(self, *, for_agent_id=None, cursor=0, limit=25, q="", connectivity_state="", include_soft_deleted=False):
            assert connectivity_state == "connected"
            return [
                AgentRecord(
                    agent_id="agent-1",
                    display_name="M1",
                    slug="m1",
                    provider="codex",
                    role="worker",
                    routing_skills=["handoff-skill"],
                    connectivity_state="connected",
                )
            ]

    async def _export_skill(store, agent_id, skill_name, *, revision_scope="draft", format="json"):
        assert agent_id == "agent-1"
        assert skill_name == "handoff-skill"
        return {
            "name": skill_name,
            "display_name": "Handoff Skill",
            "file_name": "handoff-skill-draft.skill.json",
            "content_type": "application/json",
            "document_text": skill_text,
            "format": "json",
            "revision_scope": revision_scope,
            "revision_id": "rev-1",
        }

    monkeypatch.setattr(registry_protocol_http, "export_catalog_skill_package", _export_skill)
    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "publisher", "author"),
    )
    try:
        response = client.get("/v1/protocols/protocol-1/package/export?format=yaml&revision=published")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["format"] == "yaml"
    assert payload["file_name"] == "handoff.octopus-protocol.yaml"
    assert payload["package"]["kind"] == "octopus.protocol_package"
    assert payload["package"]["skills"][0]["skill"]["name"] == "handoff-skill"


def test_protocol_auto_routes_create_apply_publish_and_run(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def __init__(self):
            self.session = None

        def list_agents(self, *, for_agent_id=None, cursor=0, limit=25, q="", connectivity_state="", include_soft_deleted=False):
            assert connectivity_state == "connected"
            return [
                AgentRecord(
                    agent_id="agent-1",
                    display_name="Builder",
                    slug="builder",
                    provider="codex",
                    role="worker",
                    routing_skills=["game", "testing"],
                    supported_admin_operations=["design_auto_protocol"],
                    connectivity_state="connected",
                )
            ]

        def get_agent_status(self, agent_id: str):
            assert agent_id == "agent-1"
            return AgentRecord(
                agent_id="agent-1",
                display_name="Builder",
                connectivity_state="connected",
                supported_admin_operations=["design_auto_protocol"],
            )

        def create_management_request(self, request: ManagementRequest) -> ManagementRequest:
            return request

        def get_management_result(self, request_id: str):
            return ManagementResult(
                request_id=request_id,
                agent_id="agent-1",
                success=True,
                payload=DesignAutoProtocolResult(
                    response=_auto_design_model_response("experience_design", "domain_grounding", "supporting_assets")
                ),
            )

        def list_routing_skills(self):
            return []

        def create_protocol_auto_design_session(self, payload, *, access):
            self.session = generate_auto_protocol_session(
                payload,
                session_id="auto-1",
                created_at="2026-04-16T00:00:00+00:00",
                updated_at="2026-04-16T00:00:00+00:00",
            )
            return self.session

        def get_protocol_auto_design_session(self, session_id: str, *, access):
            assert session_id == "auto-1"
            if self.session is None:
                raise KeyError(session_id)
            return self.session

        def update_protocol_auto_design_session(self, session, *, access, event_kind: str = "updated"):
            assert event_kind in {"applied", "published", "run_started"}
            self.session = session
            return session

        def save_protocol_draft(
            self,
            *,
            access,
            protocol_id,
            slug,
            display_name,
            description,
            definition_json,
            authoring_surface="standard",
            expected_revision=None,
        ):
            assert authoring_surface == "standard"
            assert slug
            return ProtocolMutationRecord(
                ok=True,
                status="saved",
                protocol=ProtocolDefinitionRecord(
                    protocol_id="protocol-auto",
                    slug=slug,
                    display_name=display_name,
                    draft_revision=2,
                ),
                draft_definition_json=definition_json,
                validation={"ok": True, "errors": [], "issues": [], "next_required_actions": []},
            )

        def publish_protocol(self, protocol_id: str, *, access):
            assert protocol_id == "protocol-auto"
            return ProtocolMutationRecord(
                ok=True,
                status="published",
                protocol=ProtocolDefinitionRecord(
                    protocol_id="protocol-auto",
                    slug="auto-game",
                    display_name="Auto Game",
                    current_version_id="version-1",
                    draft_revision=2,
                ),
            )

        def get_protocol(self, protocol_id: str, *, access):
            assert protocol_id == "protocol-auto"
            return ProtocolMutationRecord(
                ok=True,
                status="loaded",
                protocol=ProtocolDefinitionRecord(
                    protocol_id="protocol-auto",
                    slug="auto-game",
                    display_name="Auto Game",
                    current_version_id="version-1",
                    draft_revision=2,
                ),
                draft_definition_json=self.session.draft_definition_json,
            )

        def create_protocol_run(self, payload, *, access, idempotency_key=""):
            assert payload.protocol_id == "protocol-auto"
            assert payload.entry_agent_id == "agent-1"
            assert payload.origin_channel == "registry"
            return ProtocolRunMutationRecord.model_validate(
                {
                    "ok": True,
                    "status": "created",
                    "run": {
                        "protocol_run_id": "run-auto",
                        "protocol_id": "protocol-auto",
                        "protocol_definition_version_id": "version-1",
                        "entry_agent_id": "agent-1",
                        "root_conversation_id": "",
                        "origin_channel": "registry",
                        "workspace_ref": "",
                        "run_org_id": "local",
                        "status": "running",
                        "problem_statement": "Build a browser game.",
                        "constraints_json": {},
                        "created_at": "2026-04-16T00:00:00+00:00",
                        "updated_at": "2026-04-16T00:00:00+00:00",
                        "current_stage_key": "plan_requirements",
                        "version": 1,
                    },
                }
            )

    store = _Store()
    app.dependency_overrides[registry_server.get_store] = lambda: store
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author", "publisher"),
    )
    try:
        create_response = client.post(
            "/v1/protocol-auto/sessions",
            json={
                "surface": "registry",
                "requirement_text": "Build a 2D browser fighting game with historical figures, playtesting, and release evidence.",
            },
        )
        apply_response = client.post("/v1/protocol-auto/sessions/auto-1/apply")
        publish_response = client.post("/v1/protocol-auto/sessions/auto-1/publish")
        run_response = client.post("/v1/protocol-auto/sessions/auto-1/run", json={"origin_channel": "registry"})
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert create_response.status_code == 200
    assert create_response.json()["analysis"]["domain"] == "requirement-specific"
    assert apply_response.status_code == 200
    assert apply_response.json()["target_protocol_id"] == "protocol-auto"
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert run_response.status_code == 200
    assert run_response.json()["run_result"]["run"]["protocol_run_id"] == "run-auto"


def test_protocol_auto_apply_uses_generated_copy_slug_on_duplicate(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def __init__(self):
            self.session = None
            self.saved_slugs: list[str] = []

        def list_agents(self, *, for_agent_id=None, cursor=0, limit=25, q="", connectivity_state="", include_soft_deleted=False):
            return [
                AgentRecord(
                    agent_id="agent-1",
                    display_name="Builder",
                    slug="builder",
                    provider="codex",
                    role="worker",
                    routing_skills=[],
                    supported_admin_operations=["design_auto_protocol"],
                    connectivity_state="connected",
                )
            ]

        def get_agent_status(self, agent_id: str):
            assert agent_id == "agent-1"
            return AgentRecord(
                agent_id="agent-1",
                display_name="Builder",
                connectivity_state="connected",
                supported_admin_operations=["design_auto_protocol"],
            )

        def create_management_request(self, request: ManagementRequest) -> ManagementRequest:
            return request

        def get_management_result(self, request_id: str):
            return ManagementResult(
                request_id=request_id,
                agent_id="agent-1",
                success=True,
                payload=DesignAutoProtocolResult(
                    response=_auto_design_model_response("experience_design", "supporting_assets")
                ),
            )

        def list_routing_skills(self):
            return []

        def list_protocols(self, *, access, limit=100, offset=0, include_drafts=False, lifecycle_state="", q=""):
            return [
                ProtocolDefinitionRecord(
                    protocol_id="existing",
                    slug="build-a-compact-browser-runnable-2d-historical-platform-fighter",
                    display_name="Existing Auto Protocol",
                )
            ]

        def create_protocol_auto_design_session(self, payload, *, access):
            self.session = generate_auto_protocol_session(
                payload,
                session_id="auto-duplicate",
                created_at="2026-04-16T00:00:00+00:00",
                updated_at="2026-04-16T00:00:00+00:00",
            )
            return self.session

        def get_protocol_auto_design_session(self, session_id: str, *, access):
            assert session_id == "auto-duplicate"
            if self.session is None:
                raise KeyError(session_id)
            return self.session

        def update_protocol_auto_design_session(self, session, *, access, event_kind: str = "updated"):
            assert event_kind == "applied"
            self.session = session
            return session

        def save_protocol_draft(
            self,
            *,
            access,
            protocol_id,
            slug,
            display_name,
            description,
            definition_json,
            authoring_surface="standard",
            expected_revision=None,
        ):
            self.saved_slugs.append(slug)
            if slug == "build-a-compact-browser-runnable-2d-historical-platform-fighter":
                return ProtocolMutationRecord(ok=False, status="duplicate_slug", message=f"Protocol slug {slug!r} already exists.")
            return ProtocolMutationRecord(
                ok=True,
                status="saved",
                protocol=ProtocolDefinitionRecord(
                    protocol_id="protocol-generated-copy",
                    slug=slug,
                    display_name=display_name,
                    draft_revision=1,
                ),
                draft_definition_json=definition_json,
                validation={"ok": True, "errors": [], "issues": [], "next_required_actions": []},
            )

    store = _Store()
    app.dependency_overrides[registry_server.get_store] = lambda: store
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author", "publisher"),
    )
    try:
        create_response = client.post(
            "/v1/protocol-auto/sessions",
            json={
                "surface": "registry",
                "requirement_text": "Build a compact browser-runnable 2D historical platform fighter prototype.",
            },
        )
        apply_response = client.post("/v1/protocol-auto/sessions/auto-duplicate/apply")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert create_response.status_code == 200
    assert apply_response.status_code == 200
    assert store.saved_slugs == [
        "build-a-compact-browser-runnable-2d-historical-platform-fighter",
        "build-a-compact-browser-runnable-2d-historical-platform-fighter-generated-2",
    ]
    payload = apply_response.json()
    assert payload["target_protocol_id"] == "protocol-generated-copy"
    assert payload["draft_definition_json"]["metadata"]["slug"] == "build-a-compact-browser-runnable-2d-historical-platform-fighter-generated-2"
    assert payload["draft_definition_json"]["metadata"]["display_name"].endswith("(Generated 2)")


def test_protocol_auto_publish_blocks_unresolved_assignments(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    blocked_session = generate_auto_protocol_session(
        ProtocolAutoDesignRequestRecord(
            surface="registry",
            requirement_text="Build a useful analytics dashboard.",
            available_agents=[],
        ),
        session_id="auto-blocked",
        created_at="2026-04-16T00:00:00+00:00",
        updated_at="2026-04-16T00:00:00+00:00",
    )

    class _Store:
        def get_protocol_auto_design_session(self, session_id: str, *, access):
            assert session_id == "auto-blocked"
            return blocked_session

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author", "publisher"),
    )
    try:
        response = client.post("/v1/protocol-auto/sessions/auto-blocked/publish")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "PROTOCOL_AUTO_PUBLISH_BLOCKED"
    assert response.json()["detail"]["details"]["unresolved_decisions"]


def test_protocol_auto_route_rejects_alias_fields(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_agents(self, *, for_agent_id=None, cursor=0, limit=25, q="", connectivity_state="", include_soft_deleted=False):
            return []

        def list_routing_skills(self):
            return []

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author", "publisher"),
    )
    try:
        response = client.post(
            "/v1/protocol-auto/sessions",
            json={
                "surface": "registry",
                "change_request": "Build a protocol.",
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "PROTOCOL_AUTO_INVALID_FIELD"


def test_protocol_auto_route_rejects_unimplemented_explain_mode(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_agents(self, *, for_agent_id=None, cursor=0, limit=25, q="", connectivity_state="", include_soft_deleted=False):
            return []

        def list_routing_skills(self):
            return []

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author", "publisher"),
    )
    try:
        response = client.post(
            "/v1/protocol-auto/sessions",
            json={
                "mode": "explain",
                "surface": "registry",
                "requirement_text": "Explain this protocol.",
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "PROTOCOL_AUTO_INVALID_MODE"


def test_protocol_parse_route_accepts_draft_mode_for_incomplete_protocols(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def parse_protocol_document_text(self, *, access, definition_text: str, format: str = "json", validation_mode: str = "strict"):
            assert format == "json"
            assert validation_mode == "draft"
            return {
                "format": "json",
                "text": "{\"schema_version\": 1}",
                "document": {
                    "schema_version": 1,
                    "metadata": {"slug": "draft-protocol", "display_name": "Draft Protocol", "description": ""},
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                    "policies": {"single_active_writer": True, "max_review_rounds": 5},
                },
                "validation": {
                    "mode": "draft",
                    "ok": False,
                    "errors": ["Add at least one stage before review or publish."],
                    "issues": [
                        {
                            "code": "stages.required",
                            "message": "Add at least one stage before review or publish.",
                            "section": "stages",
                            "entity_kind": "",
                            "entity_key": "",
                            "path": "stages",
                            "blocking": True,
                        }
                    ],
                    "next_required_actions": ["stages.add_first"],
                    "content_hash": "hash-draft",
                },
            }

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        response = client.post(
            "/v1/protocols/parse",
            json={
                "definition_text": "{\"schema_version\":1,\"metadata\":{\"slug\":\"draft-protocol\"},\"participants\":[],\"artifacts\":[],\"stages\":[]}",
                "format": "json",
                "validation_mode": "draft",
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["validation"]["mode"] == "draft"
    assert payload["validation"]["next_required_actions"] == ["stages.add_first"]
    assert payload["document"]["stages"] == []


def test_protocol_authoring_options_and_template_routes_use_consistent_resources(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def get_protocol_authoring_options(self, *, access):
            return {
                "sections": ["design", "review"],
                "stage_kind_options": ["work", "review", "acceptance"],
                "artifact_kind_options": ["workspace_file", "control_plane_text"],
                "selector_kind_options": ["agent", "skill", "role"],
                "default_surface": "standard",
                "operator_surface_available": True,
            }

        def list_protocol_templates(self, *, access):
            return [
                {
                    "slug": "demo-template",
                    "display_name": "Demo Template",
                    "description": "Reusable protocol template.",
                    "featured": False,
                    "participant_count": 2,
                    "artifact_count": 1,
                    "stage_count": 3,
                    "stage_kind_sequence": ["work", "review", "acceptance"],
                }
            ]

        def get_protocol_template(self, slug, *, access):
            assert slug == "demo-template"
            return {
                "schema_version": 1,
                "metadata": {
                    "slug": "demo-template",
                    "display_name": "Demo Template",
                    "description": "Reusable protocol template.",
                },
                "participants": [],
                "artifacts": [],
                "stages": [],
                "policies": {"single_active_writer": True, "max_review_rounds": 5},
            }

        def publish_protocol_template(self, protocol_id, *, access, slug="", display_name="", description=""):
            assert protocol_id == "source-protocol"
            assert slug == "demo-template-copy"
            return ProtocolMutationRecord(
                ok=True,
                status="template_published",
                message="Protocol template published.",
                protocol={
                    "protocol_id": "template-protocol",
                    "slug": slug,
                    "display_name": display_name,
                    "description": description,
                    "lifecycle_state": "published",
                    "current_version_id": "template-version",
                    "owner_org_id": "local",
                    "visibility": "registry_template",
                    "created_by": "operator",
                    "updated_by": "operator",
                    "draft_revision": 1,
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                },
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        options_response = client.get("/v1/protocol-authoring/options")
        templates_response = client.get("/v1/protocol-templates")
        template_response = client.get("/v1/protocol-templates/demo-template")
        create_response = client.post(
            "/v1/protocol-templates",
            json={
                "source_protocol_id": "source-protocol",
                "slug": "demo-template-copy",
                "display_name": "Demo Template Copy",
                "description": "Reusable copy.",
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert options_response.status_code == 200
    options_payload = options_response.json()
    assert "templates" not in options_payload
    assert "advanced" not in options_payload["sections"]
    assert "review" in options_payload["stage_kind_options"]
    assert options_payload["default_surface"] == "standard"
    assert options_payload["operator_surface_available"] is True
    assert templates_response.status_code == 200
    assert templates_response.json()[0]["slug"] == "demo-template"
    assert template_response.status_code == 200
    assert template_response.json()["metadata"]["slug"] == "demo-template"
    assert create_response.status_code == 200
    assert create_response.json()["protocol"]["visibility"] == "registry_template"


def test_protocol_draft_create_route_accepts_blank_source(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def create_protocol_draft(self, payload, *, access):
            assert payload.source_kind == "blank"
            return ProtocolMutationRecord(
                ok=True,
                status="saved",
                message="Protocol draft saved.",
                protocol={
                    "protocol_id": "protocol-blank",
                    "slug": "protocol-blank",
                    "display_name": "",
                    "description": "",
                    "lifecycle_state": "draft",
                    "current_version_id": "",
                    "owner_org_id": "local",
                    "visibility": "org_shared",
                    "created_by": "operator",
                    "updated_by": "operator",
                    "draft_revision": 1,
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                },
                draft_definition_json={
                    "schema_version": 1,
                    "metadata": {
                        "slug": "",
                        "display_name": "",
                        "description": "",
                    },
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                    "policies": {"single_active_writer": True, "max_review_rounds": 5},
                },
                validation={
                    "ok": False,
                    "errors": ["At least one stage is required."],
                    "content_hash": "",
                },
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        response = client.post("/v1/protocol-drafts", json={"source_kind": "blank"})
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["protocol"]["protocol_id"] == "protocol-blank"
    assert payload["protocol"]["draft_revision"] == 1
    assert payload["draft_definition_json"]["metadata"]["slug"] == ""
    assert payload["draft_definition_json"]["metadata"]["display_name"] == ""


def test_protocol_draft_save_route_returns_conflict_for_revision_mismatch(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def save_protocol_draft(
            self,
            *,
            access,
            protocol_id,
            slug,
            display_name,
            description,
            definition_json,
            authoring_surface="standard",
            expected_revision=None,
        ):
            assert protocol_id == "protocol-1"
            assert expected_revision == 3
            assert authoring_surface == "operator"
            return ProtocolMutationRecord(
                ok=False,
                status="conflict",
                message="Protocol draft revision conflict: expected 3, found 4.",
                protocol={
                    "protocol_id": "protocol-1",
                    "slug": "protocol-1",
                    "display_name": "Conflict Protocol",
                    "description": "Server draft",
                    "lifecycle_state": "draft",
                    "current_version_id": "",
                    "owner_org_id": "local",
                    "visibility": "org_shared",
                    "created_by": "operator",
                    "updated_by": "operator",
                    "draft_revision": 4,
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:05+00:00",
                },
                draft_definition_json={
                    "schema_version": 1,
                    "metadata": {
                        "slug": "protocol-1",
                        "display_name": "Conflict Protocol",
                        "description": "Server draft",
                    },
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                },
                validation={
                    "ok": False,
                    "errors": ["Add at least one participant before adding a stage."],
                    "content_hash": "",
                },
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        response = client.put(
            "/v1/protocols/protocol-1/draft",
            headers={
                "If-Match": "3",
                "X-Protocol-Authoring-Surface": "operator",
            },
            json={
                "slug": "protocol-1",
                "display_name": "Conflict Protocol",
                "description": "Local draft",
                "definition_json": {"schema_version": 1, "metadata": {"slug": "protocol-1"}},
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 409
    payload = response.json()["detail"]
    assert payload["error_code"] == "PROTOCOL_DRAFT_CONFLICT"
    assert payload["details"]["protocol"]["draft_revision"] == 4
    assert payload["details"]["draft_definition_json"]["metadata"]["description"] == "Server draft"


def test_protocol_draft_create_route_rejects_template_without_slug(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        response = client.post("/v1/protocol-drafts", json={"source_kind": "template"})
    finally:
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "PROTOCOL_INVALID"
    assert "template_slug is required" in response.json()["detail"]["message"]


def test_protocol_delete_route_discards_unpublished_draft(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def delete_protocol(self, protocol_id, *, access):
            assert protocol_id == "protocol-blank"
            return ProtocolMutationRecord(
                ok=True,
                status="deleted",
                message="Protocol draft discarded.",
                protocol={
                    "protocol_id": "protocol-blank",
                    "slug": "protocol-blank",
                    "display_name": "",
                    "description": "",
                    "lifecycle_state": "draft",
                    "current_version_id": "",
                    "owner_org_id": "local",
                    "visibility": "org_shared",
                    "created_by": "operator",
                    "updated_by": "operator",
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                },
                draft_definition_json={
                    "schema_version": 1,
                    "metadata": {
                        "slug": "",
                        "display_name": "",
                        "description": "",
                    },
                    "participants": [],
                    "artifacts": [],
                    "stages": [],
                    "policies": {"single_active_writer": True, "max_review_rounds": 5},
                },
                validation={
                    "ok": False,
                    "errors": ["At least one stage is required."],
                    "content_hash": "",
                },
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator", "author"),
    )
    try:
        response = client.delete("/v1/protocols/protocol-blank")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "deleted"
    assert payload["protocol"]["protocol_id"] == "protocol-blank"


def test_protocol_run_list_route_accepts_entry_agent_and_origin_channel_filters(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_protocol_runs(
            self,
            *,
            access,
            limit=25,
            cursor=0,
            status="",
            protocol_id="",
            entry_agent_id="",
            root_conversation_id="",
            origin_channel="",
            include_generated=True,
        ):
            assert entry_agent_id == "agent-2"
            assert root_conversation_id == ""
            assert origin_channel == "telegram"
            assert include_generated is True
            return [
                {
                    "protocol_run_id": "run-2",
                    "protocol_id": "protocol-1",
                    "protocol_definition_version_id": "version-1",
                    "entry_agent_id": "agent-2",
                    "origin_channel": "telegram",
                    "run_org_id": "local",
                    "status": "running",
                    "workspace_ref": "workspace-a",
                    "problem_statement": "Build the thing.",
                    "constraints_json": {},
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                }
            ]

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs?entry_agent_id=agent-2&origin_channel=telegram")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"][0]["entry_agent_id"] == "agent-2"
    assert payload["runs"][0]["origin_channel"] == "telegram"


def test_protocol_run_list_route_accepts_root_conversation_filter(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_protocol_runs(
            self,
            *,
            access,
            limit=25,
            cursor=0,
            status="",
            protocol_id="",
            entry_agent_id="",
            root_conversation_id="",
            origin_channel="",
            include_generated=True,
        ):
            assert root_conversation_id == "conv-9"
            assert include_generated is True
            return [
                {
                    "protocol_run_id": "run-9",
                    "protocol_id": "protocol-1",
                    "protocol_definition_version_id": "version-1",
                    "entry_agent_id": "agent-2",
                    "root_conversation_id": "conv-9",
                    "origin_channel": "registry",
                    "run_org_id": "local",
                    "status": "running",
                    "workspace_ref": "workspace-a",
                    "problem_statement": "Build the thing.",
                    "constraints_json": {},
                    "created_at": "2026-04-16T00:00:00+00:00",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                }
            ]

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs?root_conversation_id=conv-9")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"][0]["root_conversation_id"] == "conv-9"


def test_default_work_list_routes_pass_generated_visibility_filter(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    seen: dict[str, bool] = {}

    class _Store:
        def list_conversations(self, **kwargs):
            seen["conversations"] = kwargs["include_generated"]
            return []

        def list_tasks(self, **kwargs):
            seen["tasks"] = kwargs["include_generated"]
            return []

        def list_protocol_runs(self, **kwargs):
            seen["runs"] = kwargs["include_generated"]
            return []

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        assert client.get("/v1/conversations?include_generated=0").status_code == 200
        assert client.get("/v1/tasks?include_generated=0").status_code == 200
        assert client.get("/v1/protocol-runs?include_generated=0").status_code == 200
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert seen == {"conversations": False, "tasks": False, "runs": False}


def test_protocol_run_store_default_visibility_keeps_human_originated_runs(monkeypatch):
    adapter = protocol_store_mod.ProtocolPostgresAdapter.__new__(protocol_store_mod.ProtocolPostgresAdapter)
    captured: dict[str, object] = {}

    class _Connection:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fetchall(conn, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(adapter, "_connect", lambda: _Connection())
    monkeypatch.setattr(adapter, "_assert_protocol_run_visible", lambda row, *, access: row)
    monkeypatch.setattr(adapter, "_decorate_protocol_run_row_with_review_state", lambda conn, row: row)
    monkeypatch.setattr(adapter, "_protocol_run_from_row", lambda row: row)
    monkeypatch.setattr(protocol_store_mod.POSTGRES_STORE_DIALECT, "fetchall", _fetchall)

    adapter.list_protocol_runs(
        access=ProtocolAccessContextRecord(actor_ref="operator:test", org_id="local", roles=["operator"]),
        include_generated=False,
    )

    sql = str(captured["sql"])
    assert "pr.hidden_from_default_views = FALSE" in sql
    assert "NULLIF(BTRIM(COALESCE(pr.problem_statement, '')), '') IS NOT NULL" in sql
    assert "pr.origin_channel IN ('registry', 'telegram')" in sql


def test_protocol_run_create_route_returns_invalid_for_missing_entry_agent(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def create_protocol_run(self, payload, *, access, idempotency_key=""):
            assert payload.entry_agent_id == ""
            return ProtocolRunMutationRecord(
                ok=False,
                status="invalid",
                message="entry_agent_id is required to start a protocol run.",
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.post(
            "/v1/protocol-runs",
            json={
                "protocol_id": "protocol-1",
                "entry_agent_id": "",
                "origin_channel": "registry",
                "workspace_ref": "workspace-a",
                "problem_statement": "Build the thing.",
                "constraints_json": {},
            },
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "PROTOCOL_INVALID"
    assert "entry_agent_id is required" in response.json()["detail"]["message"]


def test_protocol_run_create_route_uses_rehearsal_manager_agent_when_rehearsing(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def create_protocol_run(self, payload, *, access, idempotency_key=""):
            assert payload.is_rehearsal is True
            assert payload.entry_agent_id == "agent-rehearsal"
            return ProtocolRunMutationRecord(
                ok=True,
                status="created",
                run=ProtocolRunRecord(
                    protocol_run_id="run-rehearsal",
                    protocol_id="protocol-1",
                    protocol_definition_version_id="version-1",
                    entry_agent_id="agent-rehearsal",
                    entry_authority_ref="rehearsal",
                    origin_channel="registry",
                    workspace_ref="workspace-a",
                    problem_statement="Dry run the thing.",
                    constraints_json={},
                    run_org_id="local",
                    status="queued",
                    created_at="2026-04-17T00:00:00+00:00",
                    updated_at="2026-04-17T00:00:00+00:00",
                    is_rehearsal=True,
                ),
            )

    class _RehearsalManager:
        agent_id = ""

        def ensure_agent(self):
            return ("agent-rehearsal", "token-rehearsal")

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    previous_manager = getattr(registry_server, "_rehearsal_manager", None)
    registry_server._rehearsal_manager = _RehearsalManager()
    try:
        response = client.post(
            "/v1/protocol-runs",
            json={
                "protocol_id": "protocol-1",
                "entry_agent_id": "",
                "origin_channel": "registry",
                "workspace_ref": "workspace-a",
                "problem_statement": "Dry run the thing.",
                "constraints_json": {},
                "is_rehearsal": True,
            },
        )
    finally:
        registry_server._rehearsal_manager = previous_manager
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["entry_agent_id"] == "agent-rehearsal"
    assert payload["run"]["is_rehearsal"] is True


def test_protocol_run_route_returns_not_visible_for_hidden_run(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            raise PermissionError("Protocol run is not visible to this actor.")

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "PROTOCOL_NOT_VISIBLE"
    assert "details" in response.json()["detail"]


def test_protocol_definition_route_returns_not_visible_for_hidden_protocol(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def get_protocol(self, protocol_id: str, *, access):
            return ProtocolMutationRecord(
                ok=False,
                status="not_visible",
                message="Protocol is not visible to this actor.",
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocols/protocol-1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "PROTOCOL_NOT_VISIBLE"
    assert "details" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "store_method", "args"),
    [
        ("/v1/protocols/protocol-1/versions/version-1", "get_protocol_version", ("protocol-1", "version-1")),
        ("/v1/protocols/protocol-1/draft/export", "export_protocol_draft", ("protocol-1",)),
        ("/v1/protocols/protocol-1/diff", "diff_protocol_draft", ("protocol-1",)),
    ],
)
def test_protocol_definition_subresources_return_not_visible_for_hidden_protocol(
    monkeypatch,
    tmp_path: Path,
    path: str,
    store_method: str,
    args: tuple[str, ...],
):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def __getattr__(self, name: str):
            if name != store_method:
                raise AttributeError(name)

            def _handler(*handler_args, **handler_kwargs):
                assert handler_args == args
                raise PermissionError("Protocol is not visible to this actor.")

            return _handler

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    try:
        response = client.get(path)
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "PROTOCOL_NOT_VISIBLE"
    assert "details" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "store_method"),
    [
        ("/v1/protocol-runs/run-1/participants", "get_protocol_run_participants"),
        ("/v1/protocol-runs/run-1/artifacts", "get_protocol_run_artifacts"),
        ("/v1/protocol-runs/run-1/timeline", "get_protocol_run_timeline"),
        ("/v1/protocol-runs/run-1/export", "export_protocol_run"),
    ],
)
def test_protocol_run_subresources_return_not_visible_for_hidden_run(
    monkeypatch,
    tmp_path: Path,
    path: str,
    store_method: str,
):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def __getattr__(self, name: str):
            if name != store_method:
                raise AttributeError(name)

            def _handler(run_id: str, *, access):
                raise PermissionError("Protocol run is not visible to this actor.")

            return _handler

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    try:
        response = client.get(path)
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "PROTOCOL_NOT_VISIBLE"
    assert "details" in response.json()["detail"]


def test_protocol_run_export_route_accepts_visible_agent_auth(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def export_protocol_run(self, run_id: str, *, access):
            assert run_id == "run-1"
            assert access.actor_ref == "agent:agent-1"
            assert access.has_role("agent")
            return {
                "run": {"protocol_run_id": run_id, "status": "completed"},
                "definition": {"protocol_id": "protocol-1"},
                "version": {"protocol_definition_version_id": "version-1"},
                "definition_document": {"schema_version": 1, "metadata": {"slug": "demo"}},
                "participants": [],
                "stage_executions": [],
                "tasks": [],
                "artifacts": [],
                "transitions": [],
            }

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_agent=True,
        agent_id="agent-1",
        org_id="local",
        roles=("agent",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/export")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.json()["run"]["protocol_run_id"] == "run-1"


def test_protocol_run_action_route_returns_conflict_for_version_mismatch(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def act_on_protocol_run(self, run_id: str, *, access, action: str, reason: str, idempotency_key: str = "", expected_version=None):
            assert run_id == "run-1"
            assert action == "retry"
            assert expected_version == 4
            return ProtocolRunMutationRecord(
                ok=False,
                status="concurrent_modification",
                message="Protocol run version conflict: expected 4, found 5.",
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.post(
            "/v1/protocol-runs/run-1/actions/retry",
            headers={"If-Match": "4", "Idempotency-Key": "idem-1"},
            json={"reason": "Retry after fix."},
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "CONCURRENT_MODIFICATION"
    assert "details" in response.json()["detail"]


def test_protocol_run_action_route_returns_idempotency_replay(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def act_on_protocol_run(self, run_id: str, *, access, action: str, reason: str, idempotency_key: str = "", expected_version=None):
            return ProtocolRunMutationRecord(
                ok=False,
                status="idempotency_conflict",
                message="Idempotency key was already used for a different protocol action.",
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.post(
            "/v1/protocol-runs/run-1/actions/retry",
            headers={"Idempotency-Key": "idem-1"},
            json={"reason": "Retry after fix."},
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "IDEMPOTENCY_REPLAY"
    assert "details" in response.json()["detail"]


def test_protocol_run_action_route_returns_not_visible_for_hidden_run(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def act_on_protocol_run(self, run_id: str, *, access, action: str, reason: str, idempotency_key: str = "", expected_version=None):
            return ProtocolRunMutationRecord(
                ok=False,
                status="not_visible",
                message="Protocol run is not visible to this actor.",
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="foreign-org",
        roles=("operator",),
    )
    try:
        response = client.post(
            "/v1/protocol-runs/run-1/actions/retry",
            headers={"Idempotency-Key": "idem-1"},
            json={"reason": "Retry after fix."},
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "PROTOCOL_NOT_VISIBLE"
    assert "details" in response.json()["detail"]


def test_protocol_stage_result_broadcasts_protocol_run_invalidation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    captured: list[set[str]] = []

    class _Authority:
        def report_routed_result_for_agent(self, agent_token: str, payload):
            assert agent_token == "agent-token"
            assert payload["routed_task_id"] == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                target_agent_id="agent-1",
                request=RegistryJsonRecord.model_validate(
                    {
                        "context": {
                            "protocol_run_id": "run-1",
                        }
                    }
                ),
            )

    async def _capture_invalidations(*, topics, reason, conversation_id="", agent_id="", routed_task_id=""):
        captured.append(set(topics))

    monkeypatch.setattr(registry_server, "_broadcast_invalidations", _capture_invalidations)
    app.dependency_overrides[registry_server.get_authority] = lambda: _Authority()
    try:
        response = client.post(
            "/v1/agents/routed-tasks/protocol-stage:stage-1/result",
            headers={"Authorization": "Bearer agent-token"},
            json={"status": "completed", "summary": "done"},
        )
    finally:
        app.dependency_overrides.pop(registry_server.get_authority, None)

    assert response.status_code == 200
    assert captured
    assert {"tasks", "conversations", "summary", "protocols", "protocol-run:run-1"} in captured


def test_protocol_issues_route_returns_issue_rows(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_protocol_issues(self, *, access, limit=25, cursor=0, issue_kind="", protocol_run_id="", protocol_id=""):
            assert issue_kind == "blocked_run"
            assert protocol_run_id == ""
            assert protocol_id == ""
            return [
                {
                    "issue_kind": "blocked_run",
                    "protocol_run_id": "run-1",
                    "protocol_id": "protocol-1",
                    "protocol_display_name": "Software Engineering",
                    "stage_execution_id": "stage-1",
                    "stage_key": "planning",
                    "participant_key": "worker",
                    "run_status": "blocked",
                    "stage_status": "blocked",
                    "issue_code": "artifact_missing",
                    "issue_detail": "Artifact missing.",
                    "lease_expires_at": "",
                    "timeout_at": "",
                    "updated_at": "2026-04-16T00:00:00+00:00",
                }
            ]

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/issues?issue_kind=blocked_run")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["issues"][0]["protocol_run_id"] == "run-1"


def test_protocol_issues_route_accepts_protocol_filters(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    class _Store:
        def list_protocol_issues(self, *, access, limit=25, cursor=0, issue_kind="", protocol_run_id="", protocol_id=""):
            assert issue_kind == ""
            assert protocol_run_id == "run-9"
            assert protocol_id == "protocol-9"
            return []

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_operator_session] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/issues?protocol_run_id=run-9&protocol_id=protocol-9")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_operator_session, None)

    assert response.status_code == 200
    assert response.json()["issues"] == []


def test_registry_auth_load_settings_reads_registry_env(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    monkeypatch.setenv("REGISTRY_DISPLAY_NAME", "QA Registry")

    settings = registry_auth.load_settings()

    assert settings.database_url == os.environ["OCTOPUS_DATABASE_URL"]
    assert settings.enroll_token == "enroll-secret"
    assert settings.ui_token == "ui-secret"
    assert settings.display_name == "QA Registry"


def test_registry_auth_validate_settings_rejects_missing_enroll_token(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("REGISTRY_ENROLL_TOKEN", raising=False)
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject a missing enroll token"
    except RuntimeError as exc:
        assert "REGISTRY_ENROLL_TOKEN must be set" in str(exc)


def test_registry_auth_validate_settings_rejects_missing_ui_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.delenv("REGISTRY_UI_TOKEN", raising=False)

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject a missing UI token"
    except RuntimeError as exc:
        assert "REGISTRY_UI_TOKEN must be set" in str(exc)


def test_registry_auth_validate_settings_rejects_default_tokens(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "dev-enroll-token")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "dev-ui-token")

    try:
        registry_auth.validate_settings()
        assert False, "validate_settings should reject known default tokens"
    except RuntimeError as exc:
        assert "must not use a known default token" in str(exc)


def test_registry_auth_session_cookie_is_secure_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.delenv("REGISTRY_ALLOW_HTTP", raising=False)
    local_app = FastAPI()

    registry_auth.configure_session_middleware(local_app)

    assert local_app.user_middleware[0].kwargs["https_only"] is True


def test_registry_auth_session_cookie_can_allow_http_for_local_dev(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")
    local_app = FastAPI()

    registry_auth.configure_session_middleware(local_app)

    assert local_app.user_middleware[0].kwargs["https_only"] is False


def test_registry_auth_session_secret_fallback_is_stable(monkeypatch, tmp_path: Path):
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
    assert payload["protocols"]["runs_started_24h"] == 0
    assert payload["protocols"]["runs_completed_24h"] == 0
    assert payload["protocols"]["operator_interventions_24h"] == 0
    assert payload["protocols"]["completion_rate_24h"] == 0.0
    assert payload["protocols"]["mean_completion_seconds_24h"] == 0.0
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
        "conversation_type": "conversation",
        "origin_channel": "registry",
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
        json={"action_id": "approval-action-1", "action": "approve_pending", "payload": {"request_id": "evt-approval-decided"}},
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


def test_conversation_message_endpoint_rejects_selector_only_direct_assignment(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Selector Bot", "selector-bot")
    conv = _create_conversation(
        client,
        token,
        agent_id,
        "conv-selector-only",
        title="Selector only conversation",
    )

    _login_ui(client)
    csrf_token = _ui_csrf_token(client)
    response = client.post(
        f"/v1/conversations/{conv['conversation_id']}/messages",
        headers={"X-CSRF-Token": csrf_token},
        json={"text": "@m2"},
    )

    assert response.status_code == 422
    assert "Add instructions after the target selector" in response.json()["detail"]


def test_management_result_endpoint_and_ui_logout(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Management Bot", "management-bot")
    store = get_registry_store()
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
                "transport_implementations": ["telegram", "registry"],
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
                "transport_implementations": ["registry"],
                "supported_admin_operations": [],
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
                "transport_implementations": ["registry"],
                "supported_admin_operations": [],
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


def test_registry_list_tasks_can_filter_by_protocol_run_id(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    _login_ui(client)

    origin_id, origin_token = _enroll_and_register(client, "Origin Bot", "origin-bot-run-filter")
    target_id, _target_token = _enroll_and_register(client, "Target Bot", "target-bot-run-filter")
    conversation = _create_conversation(client, origin_token, origin_id, "conv-run-filter", title="Run filter")

    for task_id, protocol_run_id in (
        ("task-run-1", "run-1"),
        ("task-run-2", "run-2"),
    ):
        response = client.post(
            "/v1/agents/routed-tasks",
            headers={"Authorization": f"Bearer {origin_token}"},
            json={
                "routed_task_id": task_id,
                "parent_conversation_id": conversation["conversation_id"],
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": f"Task {task_id}",
                "instructions": "Do work.",
                "context": {"protocol_run_id": protocol_run_id, "stage_key": "planning"},
                "created_at": "2026-03-25T00:00:00+00:00",
            },
        )
        assert response.status_code == 200

    filtered = client.get(
        "/v1/tasks",
        params={"protocol_run_id": "run-1", "limit": 10},
    )
    assert filtered.status_code == 200
    payload = filtered.json()
    assert [task["routed_task_id"] for task in payload["tasks"]] == ["task-run-1"]
    assert payload["tasks"][0]["protocol_run_id"] == "run-1"


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


def test_task_artifact_content_route_streams_local_file(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "artifact.txt"
    artifact_file.write_text("artifact body", encoding="utf-8")

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "task-1"
            return TaskRecord(
                routed_task_id="task-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                working_dir=str(tmp_path),
                result=RegistryJsonRecord.model_validate(
                    {
                        "artifacts": [
                            {
                                "artifact_key": "report",
                                "path": "artifact.txt",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ]
                    }
                ),
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/tasks/task-1/artifacts/report/content")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "artifact body"


def test_task_artifact_content_route_falls_back_to_protocol_run_workspace(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "workspace" / "artifact.txt"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("artifact body", encoding="utf-8")

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                protocol_stage_execution_id="stage-1",
                working_dir="/workspace/workspace",
                request=RegistryJsonRecord.model_validate({
                    "context": {
                        "protocol_run_id": "run-1",
                    },
                }),
                result=RegistryJsonRecord.model_validate(
                    {
                        "working_dir": "/workspace/workspace",
                        "artifacts": [
                            {
                                "artifact_key": "report",
                                "path": "artifact.txt",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ]
                    }
                ),
            )

        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", workspace_ref=str(artifact_file.parent)),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                        working_dir="/workspace/workspace",
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="report",
                        artifact_kind="workspace_file",
                        location="artifact.txt",
                        workspace_path="artifact.txt",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/report/content")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "artifact body"


def test_task_payloads_merge_protocol_run_artifacts_for_all_task_surfaces(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    task = TaskRecord(
        routed_task_id="protocol-stage:stage-1",
        origin_agent_id="agent-1",
        target_agent_id="agent-2",
        status="completed",
        protocol_run_id="run-1",
        stage_key="implementation",
        working_dir="/workspace/workspace",
        request=RegistryJsonRecord.model_validate({
            "context": {
                "protocol_run_id": "run-1",
                "protocol_stage_execution_id": "stage-1",
            },
            "internal_context": {
                "protocol_stage_contract": {
                    "output_artifacts": [
                        {"artifact_key": "report", "path": "protocol/report.md"},
                    ],
                },
            },
        }),
        result=RegistryJsonRecord.model_validate({
            "summary": "Created [report.md](/workspace/workspace/protocol/report.md).",
        }),
    )

    class _Store:
        def list_tasks(self, **kwargs):
            return [task]

        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return task

        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(
                    protocol_definition_version_id="ver-1",
                    protocol_id="protocol-1",
                ),
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="report",
                        artifact_kind="workspace_file",
                        location="/workspace/workspace/protocol/report.md",
                        workspace_path="protocol/report.md",
                        exists=True,
                        size_bytes=128,
                        content_hash="abc123",
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        listed = client.get("/v1/tasks")
        detail = client.get("/v1/tasks/protocol-stage%3Astage-1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert listed.status_code == 200
    assert detail.status_code == 200
    for payload in (listed.json()["tasks"][0], detail.json()):
        assert payload["artifact_count"] == 1
        artifacts = payload["result"]["artifacts"]
        assert len(artifacts) == 1
        assert artifacts[0]["artifact_key"] == "report"
        assert artifacts[0]["path"] == "/workspace/workspace/protocol/report.md"
        assert artifacts[0]["verification_state"] == "verified"


def test_protocol_artifact_content_route_streams_local_file(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "protocol" / "plan.md"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("plan body", encoding="utf-8")

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                        working_dir=str(tmp_path),
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="plan",
                        artifact_kind="workspace_file",
                        location=str(artifact_file),
                        workspace_path="protocol/plan.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/plan/content")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "plan body"


def test_protocol_artifact_content_route_falls_back_to_mounted_workspace(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "workspace" / "protocol" / "document.md"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("document body", encoding="utf-8")
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: (str(tmp_path / "workspace"),))

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/document/content")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "document body"


def test_protocol_artifact_content_route_renders_markdown_preview(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "workspace" / "protocol" / "document.md"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("# Review\n\n- one\n- two", encoding="utf-8")
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: (str(tmp_path / "workspace"),))

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/document/content?preview=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<h2>Review</h2>" in response.text
    assert "<li>one</li>" in response.text


def test_task_artifact_content_route_falls_back_to_mounted_workspace(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    artifact_file = tmp_path / "workspace" / "protocol" / "document.md"
    artifact_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_file.write_text("document body", encoding="utf-8")
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: (str(tmp_path / "workspace"),))

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                protocol_stage_execution_id="stage-1",
                request=RegistryJsonRecord.model_validate({
                    "context": {
                        "protocol_run_id": "run-1",
                    },
                }),
                result=RegistryJsonRecord.model_validate(
                    {
                        "artifacts": [
                            {
                                "artifact_key": "document",
                                "path": "protocol/document.md",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ]
                    }
                ),
            )

        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/document/content")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "document body"


def test_task_artifact_content_route_opens_directory_index_and_downloads_zip(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "index.html").write_text(
        '<!doctype html><title>Offline app</title><link rel="stylesheet" href="./styles.css">',
        encoding="utf-8",
    )
    (package_dir / "styles.css").write_text("body{background:#10131a;color:#fff}", encoding="utf-8")
    samples = package_dir / "samples"
    samples.mkdir()
    (samples / "cells.csv").write_text("cell_id,value\nC-1,10\n", encoding="utf-8")

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                protocol_stage_execution_id="stage-1",
                working_dir=str(tmp_path),
                result=RegistryJsonRecord.model_validate(
                    {
                        "artifacts": [
                            {
                                "artifact_key": "package",
                                "path": "package",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ]
                    }
                ),
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        open_response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/package/content")
        asset_response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/package/content/styles.css")
        browse_response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/package/content?browse=1")
        member_response = client.get(
            "/v1/tasks/protocol-stage:stage-1/artifacts/package/content?path=samples%2Fcells.csv"
        )
        download_response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/package/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert open_response.status_code == 200
    assert "<title>Offline app</title>" in open_response.text
    assert "text/html" in open_response.headers.get("content-type", "")
    assert str(open_response.url).endswith("/v1/tasks/protocol-stage:stage-1/artifacts/package/content/")
    assert asset_response.status_code == 200
    assert asset_response.text == "body{background:#10131a;color:#fff}"
    assert "text/css" in asset_response.headers.get("content-type", "")
    assert browse_response.status_code == 200
    assert "Directory artifact contents" in browse_response.text
    assert "samples/cells.csv" in browse_response.text
    assert member_response.status_code == 200
    assert member_response.text == "cell_id,value\nC-1,10\n"
    assert download_response.status_code == 200
    assert "application/zip" in download_response.headers.get("content-type", "")
    assert 'filename="package.zip"' in download_response.headers.get("content-disposition", "")
    with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
        assert sorted(archive.namelist()) == ["index.html", "samples/cells.csv", "styles.css"]


def test_protocol_artifact_content_route_uses_rehearsal_text_when_file_unavailable(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: ())

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", is_rehearsal=True),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                        result=RegistryJsonRecord.model_validate(
                            {
                                "full_text": "Drafted the revised document.\nPROTOCOL_SUMMARY: Draft completed."
                            }
                        ),
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/document/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "Drafted the revised document."
    assert 'filename="document.md"' in response.headers.get("content-disposition", "")


def test_protocol_artifact_content_route_prefers_inline_artifact_contents_when_file_unavailable(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: ())

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", is_rehearsal=True),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                        result=RegistryJsonRecord.model_validate(
                            {
                                "full_text": "Drafted the revised document.\nPROTOCOL_SUMMARY: Draft completed.",
                                "artifact_contents": [
                                    {
                                        "artifact_key": "document",
                                        "path": "protocol/document.md",
                                        "content": "# Quarterly Risk Summary\n\n## Executive summary\nBelievable rehearsal body.",
                                    }
                                ],
                            }
                        ),
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/document/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "# Quarterly Risk Summary\n\n## Executive summary\nBelievable rehearsal body."
    assert 'filename="document.md"' in response.headers.get("content-disposition", "")


def test_protocol_artifact_content_route_opens_directory_index_and_downloads_zip(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    package_dir = tmp_path / "offline-package"
    package_dir.mkdir()
    (package_dir / "index.html").write_text(
        '<!doctype html><title>Offline package</title><script src="./app.js"></script>',
        encoding="utf-8",
    )
    (package_dir / "app.js").write_text("window.packageLoaded=true;", encoding="utf-8")
    samples = package_dir / "samples"
    samples.mkdir()
    (samples / "panels.csv").write_text("panel_id,value\nP-1,20\n", encoding="utf-8")

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="package",
                        artifact_kind="workspace_file",
                        location=str(package_dir),
                        workspace_path="offline-package",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        open_response = client.get("/v1/protocol-runs/run-1/artifacts/package/content")
        asset_response = client.get("/v1/protocol-runs/run-1/artifacts/package/content/app.js")
        browse_response = client.get("/v1/protocol-runs/run-1/artifacts/package/content?browse=1")
        member_response = client.get(
            "/v1/protocol-runs/run-1/artifacts/package/content?path=samples%2Fpanels.csv"
        )
        download_response = client.get("/v1/protocol-runs/run-1/artifacts/package/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert open_response.status_code == 200
    assert "<title>Offline package</title>" in open_response.text
    assert "text/html" in open_response.headers.get("content-type", "")
    assert str(open_response.url).endswith("/v1/protocol-runs/run-1/artifacts/package/content/")
    assert asset_response.status_code == 200
    assert asset_response.text == "window.packageLoaded=true;"
    assert "text/javascript" in asset_response.headers.get("content-type", "")
    assert browse_response.status_code == 200
    assert "Directory artifact contents" in browse_response.text
    assert "samples/panels.csv" in browse_response.text
    assert member_response.status_code == 200
    assert member_response.text == "panel_id,value\nP-1,20\n"
    assert download_response.status_code == 200
    assert "application/zip" in download_response.headers.get("content-type", "")
    assert 'filename="offline-package.zip"' in download_response.headers.get("content-disposition", "")
    with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
        assert sorted(archive.namelist()) == ["app.js", "index.html", "samples/panels.csv"]


def test_protocol_artifact_runtime_status_detects_static_package(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    package_dir = tmp_path / "offline-package"
    package_dir.mkdir()
    (package_dir / "index.html").write_text("<!doctype html><title>App</title>", encoding="utf-8")

    class _Store:
        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", entry_agent_id="agent-1"),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="package",
                        artifact_kind="workspace_file",
                        location=str(package_dir),
                        workspace_path="offline-package",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

        def get_protocol_artifact_runtime(self, run_id: str, artifact_key: str, *, access):
            del run_id, artifact_key, access
            return None

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/protocol-runs/run-1/artifacts/package/runtime")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest_available"] is True
    assert payload["runtime"]["status"] == "stopped"
    assert payload["runtime"]["manifest"]["runtime_kind"] == "static"
    assert payload["runtime"]["runtime_url"] == "/runtime/protocol-runs/run-1/artifacts/package/app/"
    assert payload["package_url"].endswith("/v1/protocol-runs/run-1/artifacts/package/content?download=1")


def test_protocol_artifact_runtime_stop_preserves_typed_manifest(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    manifest = ProtocolArtifactRuntimeManifestRecord(runtime_kind="static", ui_path="/", health_path="/")
    existing_runtime = ProtocolArtifactRuntimeInstanceRecord(
        runtime_instance_id="runtime-1",
        protocol_run_id="run-1",
        artifact_key="package",
        agent_id="agent-1",
        status="running",
        manifest=manifest,
        manifest_path="package/octopus-runtime.json",
        artifact_path=str(tmp_path / "package"),
        runtime_url="/runtime/protocol-runs/run-1/artifacts/package/app/",
        ui_url="/runtime/protocol-runs/run-1/artifacts/package/app/",
        health_url="/v1/protocol-runs/run-1/artifacts/package/runtime/health",
    )
    saved_runtime: ProtocolArtifactRuntimeInstanceRecord | None = None

    class _Store:
        def get_protocol_artifact_runtime(self, run_id: str, artifact_key: str, *, access):
            del access
            assert run_id == "run-1"
            assert artifact_key == "package"
            return existing_runtime

        def save_protocol_artifact_runtime(self, runtime: ProtocolArtifactRuntimeInstanceRecord, *, access):
            del access
            nonlocal saved_runtime
            assert isinstance(runtime.manifest, ProtocolArtifactRuntimeManifestRecord)
            saved_runtime = runtime
            return runtime

        def append_protocol_artifact_runtime_event(self, event, *, access):
            del access
            return event

    from octopus_registry.management_client import RegistryManagementClient

    async def _send(self, *, agent_id: str, payload, timeout_seconds: int = 30):
        del self, timeout_seconds
        assert agent_id == "agent-1"
        assert payload.operation == "stop_artifact_runtime"
        stopped = ProtocolArtifactRuntimeInstanceRecord(
            runtime_instance_id="runtime-1",
            protocol_run_id="run-1",
            artifact_key="package",
            status="stopped",
            stopped_by="operator",
            stopped_at="2026-05-06T04:00:00Z",
        )
        return ManagementResult(
            request_id="mgmt-1",
            agent_id="agent-1",
            success=True,
            payload=StopArtifactRuntimeResult(
                result=ProtocolArtifactRuntimeActionResultRecord(
                    ok=True,
                    status="stopped",
                    message="Runtime stopped.",
                    runtime=stopped,
                )
            ),
        )

    monkeypatch.setattr(RegistryManagementClient, "send", _send)
    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.post("/v1/protocol-runs/run-1/artifacts/package/runtime/stop")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert saved_runtime is not None
    assert saved_runtime.status == "stopped"
    assert saved_runtime.agent_id == "agent-1"
    assert saved_runtime.manifest == manifest
    assert saved_runtime.runtime_url == "/runtime/protocol-runs/run-1/artifacts/package/app/"


def test_task_artifact_content_route_uses_rehearsal_text_when_file_unavailable(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: ())

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                protocol_stage_execution_id="stage-1",
                request=RegistryJsonRecord.model_validate({
                    "context": {
                        "protocol_run_id": "run-1",
                    },
                }),
                result=RegistryJsonRecord.model_validate(
                    {
                        "full_text": "Drafted the revised document.\nPROTOCOL_SUMMARY: Draft completed.",
                        "artifacts": [
                            {
                                "artifact_key": "document",
                                "path": "protocol/document.md",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ],
                    }
                ),
            )

        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", is_rehearsal=True),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/document/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "Drafted the revised document."
    assert 'filename="document.md"' in response.headers.get("content-disposition", "")


def test_task_artifact_content_route_prefers_inline_artifact_contents_when_file_unavailable(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    monkeypatch.setattr("octopus_registry.artifact_paths._mounted_workspace_roots", lambda: ())

    class _Store:
        def get_task(self, routed_task_id: str):
            assert routed_task_id == "protocol-stage:stage-1"
            return TaskRecord(
                routed_task_id="protocol-stage:stage-1",
                origin_agent_id="agent-1",
                target_agent_id="agent-2",
                protocol_stage_execution_id="stage-1",
                request=RegistryJsonRecord.model_validate({
                    "context": {
                        "protocol_run_id": "run-1",
                    },
                }),
                result=RegistryJsonRecord.model_validate(
                    {
                        "full_text": "Drafted the revised document.\nPROTOCOL_SUMMARY: Draft completed.",
                        "artifact_contents": [
                            {
                                "artifact_key": "document",
                                "path": "protocol/document.md",
                                "content": "# Quarterly Risk Summary\n\n## Executive summary\nBelievable rehearsal body.",
                            }
                        ],
                        "artifacts": [
                            {
                                "artifact_key": "document",
                                "path": "protocol/document.md",
                                "exists": True,
                                "verification_state": "verified",
                            }
                        ],
                    }
                ),
            )

        def get_protocol_run(self, run_id: str, *, access):
            del access
            assert run_id == "run-1"
            return ProtocolRunDetailRecord(
                run=ProtocolRunRecord(protocol_run_id="run-1", protocol_id="protocol-1", is_rehearsal=True),
                definition=ProtocolDefinitionRecord(protocol_id="protocol-1", slug="demo"),
                version=ProtocolDefinitionVersionRecord(protocol_definition_version_id="ver-1", protocol_id="protocol-1"),
                tasks=[
                    TaskRecord(
                        routed_task_id="protocol-stage:stage-1",
                        protocol_stage_execution_id="stage-1",
                    )
                ],
                artifacts=[
                    ProtocolArtifactRecord(
                        protocol_artifact_id="artifact-1",
                        protocol_run_id="run-1",
                        artifact_key="document",
                        artifact_kind="workspace_file",
                        location="protocol/document.md",
                        workspace_path="protocol/document.md",
                        exists=True,
                        produced_by_stage_execution_id="stage-1",
                        verification_state="verified",
                    )
                ],
            )

    app.dependency_overrides[registry_server.get_store] = lambda: _Store()
    app.dependency_overrides[registry_server.require_authenticated] = lambda: registry_auth.AuthContext(
        is_operator=True,
        org_id="local",
        roles=("operator",),
    )
    try:
        response = client.get("/v1/tasks/protocol-stage:stage-1/artifacts/document/content?download=1")
    finally:
        app.dependency_overrides.pop(registry_server.get_store, None)
        app.dependency_overrides.pop(registry_server.require_authenticated, None)

    assert response.status_code == 200
    assert response.text == "# Quarterly Risk Summary\n\n## Executive summary\nBelievable rehearsal body."
    assert 'filename="document.md"' in response.headers.get("content-disposition", "")


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


def test_agent_trust_tier_update_persists_and_hides_for_anonymous(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        agent_id, _token = _enroll_and_register(client, "Trust Bot", "trust-bot")

        bumped = client.patch(
            f"/v1/agents/{agent_id}/trust-tier",
            headers={"X-CSRF-Token": csrf_token},
            json={"trust_tier": "trusted"},
        )
        assert bumped.status_code == 200, bumped.text
        assert bumped.json()["trust_tier"] == "trusted"

        rejected = client.patch(
            f"/v1/agents/{agent_id}/trust-tier",
            headers={"X-CSRF-Token": csrf_token},
            json={"trust_tier": "platinum"},
        )
        assert rejected.status_code in (400, 422)


def test_agent_capacity_override_updates_current_and_max(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        agent_id, _token = _enroll_and_register(client, "Capacity Bot", "capacity-bot")

        response = client.patch(
            f"/v1/agents/{agent_id}/capacity",
            headers={"X-CSRF-Token": csrf_token},
            json={"current_capacity": 2, "max_capacity": 5},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["current_capacity"] == 2
        assert payload["max_capacity"] == 5


def test_agent_rotate_token_invalidates_old_bearer(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        agent_id, old_token = _enroll_and_register(client, "Rotate Bot", "rotate-bot")

        rotated = client.post(
            f"/v1/agents/{agent_id}/rotate-token",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        assert rotated.status_code == 200, rotated.text
        new_token = rotated.json().get("bearer_token") or rotated.json().get("agent_token")
        assert new_token
        assert new_token != old_token

        # Old token must no longer authorize polling.
        old_poll = client.get(
            "/v1/agents/poll",
            headers={"Authorization": f"Bearer {old_token}"},
            params={"cursor": 0, "limit": 5},
        )
        assert old_poll.status_code in (401, 403)

        # New token works.
        new_poll = client.get(
            "/v1/agents/poll",
            headers={"Authorization": f"Bearer {new_token}"},
            params={"cursor": 0, "limit": 5},
        )
        assert new_poll.status_code == 200


def test_agent_soft_delete_hides_from_default_listing(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        agent_id, _token = _enroll_and_register(client, "Tombstone Bot", "tombstone-bot")

        response = client.delete(
            f"/v1/agents/{agent_id}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["soft_deleted_at"]
        assert payload["connectivity_state"] == "disconnected"

        listing = client.get("/v1/agents").json()
        agents = listing.get("agents") or listing
        agent_ids = [agent["agent_id"] for agent in agents]
        assert agent_id not in agent_ids


def test_selector_preview_returns_matching_candidates(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _login_ui(client)
        csrf_token = _ui_csrf_token(client)
        _enroll_and_register(client, "Pyth A", "pyth-a")
        _enroll_and_register(client, "Pyth B", "pyth-b")

        response = client.post(
            "/v1/selector/preview",
            headers={"X-CSRF-Token": csrf_token},
            json={"selector": "@skill:python"},
        )
        assert response.status_code == 200, response.text
        candidates = response.json().get("candidates", [])
        slugs = sorted(item["slug"] for item in candidates)
        assert "pyth-a" in slugs
        assert "pyth-b" in slugs
