"""Tests for the FastAPI registry control-plane service."""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3

from fastapi.testclient import TestClient

from app.registry_service.app import app
from app.registry_service import runtime_surface
from app.registry_service.store import RegistrySQLiteStore
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
from app.identity import telegram_actor_key, telegram_conversation_key


def _configure_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")


def _configure_runtime_surface(monkeypatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "bot-data"
    monkeypatch.setenv("BOT_PROVIDER", "claude")
    monkeypatch.setenv("BOT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BOT_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    ensure_data_dirs(data_dir)
    runtime_surface.reset_for_test()
    return data_dir


def _enroll_and_register(client: TestClient, name: str, slug: str) -> tuple[str, str]:
    enroll = client.post(
        "/v1/agents/enroll",
        json={
            "enrollment_token": "enroll-secret",
            "agent_card": {
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "capabilities": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "connectivity_state": "degraded",
                "surface_capabilities": ["telegram", "registry"],
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
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "capabilities": ["python", "tests"],
                "tags": ["backend"],
                "description": "Writes and tests code",
                "provider": "codex",
                "mode": "registry",
                "surface_capabilities": ["telegram", "registry"],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    assert register.status_code == 200
    return agent_id, token


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
        json={"role": "developer", "capabilities": ["python"], "required_state": "connected"},
    )
    assert search.status_code == 200
    agents = search.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["slug"] == "dev-bot"
    assert agents[0]["connectivity_state"] == "connected"


def test_registry_ui_exposes_runtime_health_summary_and_detail(monkeypatch, tmp_path: Path):
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
            "runtime_health": _runtime_health_payload(),
        },
    )
    assert heartbeat.status_code == 200

    bots = client.get(
        "/v1/ui/bots",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert bots.status_code == 200
    listed = bots.json()["bots"]
    assert listed[0]["runtime_health_summary"]["status"] == "degraded"
    assert listed[0]["runtime_health_summary"]["healthy_worker_count"] == 1

    detail = client.get(
        f"/v1/ui/bots/{agent_id}/health",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["report"]["summary"]["claimed_count"] == 1
    assert [row["worker_id"] for row in payload["workers"]] == ["worker-a", "worker-b"]


def test_registry_catalog_and_provider_preview(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    client = TestClient(app)

    listed = client.get(
        "/v1/catalog/skills?q=github",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    listed_payload = listed.json()["skills"]
    names = {item["name"] for item in listed_payload}
    assert "github-integration" in names
    github_summary = next(item for item in listed_payload if item["name"] == "github-integration")
    assert github_summary["source_kind"] == "builtin"
    assert github_summary["can_activate"] is True
    assert github_summary["can_update"] is False
    assert github_summary["can_uninstall"] is False

    detail = client.get(
        "/v1/catalog/skills/github-integration",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["name"] == "github-integration"
    assert payload["source_kind"] == "builtin"
    assert "GITHUB_TOKEN" in payload["requirement_keys"]

    preview = client.post(
        "/v1/provider-guidance/claude/preview",
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


def test_registry_conversation_skill_activation_surface(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    client = TestClient(app)
    _, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    conversation_key = telegram_conversation_key(12345)
    conversation_id = "telegram:dev-bot:12345"
    session = default_session("claude", {"session_id": "test", "started": False}, "on")
    save_session(data_dir, conversation_key, session)
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conversation_id,
            "title": "Telegram chat 12345",
            "origin_surface": "telegram",
            "external_id": "12345",
        },
    )
    assert bind.status_code == 200

    activate = client.post(
        f"/v1/conversations/{conversation_id}/skills/code-review/activate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": telegram_actor_key(42)},
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "activated"

    listed = client.get(
        f"/v1/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["conversation_key"] == conversation_key
    assert listed.json()["active_skills"] == ["code-review"]

    deactivate = client.post(
        f"/v1/conversations/{conversation_id}/skills/code-review/deactivate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": telegram_actor_key(42)},
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["status"] == "removed"


def test_registry_conversation_skill_state_filters_unresolvable_raw_skills(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    data_dir = _configure_runtime_surface(monkeypatch, tmp_path)
    client = TestClient(app)
    _, token = _enroll_and_register(client, "Dev Bot", "dev-bot")

    conversation_key = telegram_conversation_key(12346)
    conversation_id = "telegram:dev-bot:12346"
    session = default_session("claude", {"session_id": "test", "started": False}, "on")
    session["active_skills"] = ["code-review", "missing-skill"]
    save_session(data_dir, conversation_key, session)
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conversation_id,
            "title": "Telegram chat 12346",
            "origin_surface": "telegram",
            "external_id": "12346",
        },
    )
    assert bind.status_code == 200

    listed = client.get(
        f"/v1/conversations/{conversation_id}/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == ["code-review"]


def test_registry_conversation_skill_surface_lazy_loads_default_session(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    client = TestClient(app)
    _, token = _enroll_and_register(client, "Registry Bot", "registry-bot")

    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-runtime-1",
            "title": "Registry runtime conversation",
            "origin_surface": "registry",
            "external_id": "conv-runtime-1",
        },
    )
    assert bind.status_code == 200

    listed = client.get(
        "/v1/conversations/conv-runtime-1/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["conversation_key"] == "conv-runtime-1"
    assert listed.json()["active_skills"] == []

    activate = client.post(
        "/v1/conversations/conv-runtime-1/skills/code-review/activate",
        headers={"Authorization": "Bearer ui-secret"},
        json={"actor_key": "reg:ui"},
    )
    assert activate.status_code == 200
    assert activate.json()["status"] == "activated"

    listed = client.get(
        "/v1/conversations/conv-runtime-1/skills",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_skills"] == ["code-review"]


def test_registry_catalog_install_and_uninstall(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    _configure_runtime_surface(monkeypatch, tmp_path)
    monkeypatch.setenv("BOT_REGISTRY_URL", "https://registry.example.test/index.json")
    client = TestClient(app)
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
        "/v1/catalog/skills/helper/install",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert install.status_code == 200
    assert install.json()["ok"] is True

    detail = client.get(
        "/v1/catalog/skills/helper",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert detail.status_code == 200
    assert detail.json()["source_kind"] == "imported"
    assert detail.json()["can_update"] is True
    assert detail.json()["can_uninstall"] is True

    diff = client.get(
        "/v1/catalog/skills/helper/diff",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert diff.status_code == 200
    assert "no differences" in diff.json()["diff"].lower()

    uninstall = client.post(
        "/v1/catalog/skills/helper/uninstall",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert uninstall.status_code == 200
    assert uninstall.json()["ok"] is True


def test_registry_bind_conversation_is_visible_in_ui(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Dev Bot", "dev-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "telegram:dev-bot:123",
            "title": "Telegram chat 123",
            "origin_surface": "telegram",
            "external_id": "123",
        },
    )
    assert bind.status_code == 200
    assert bind.json()["conversation_id"] == "telegram:dev-bot:123"

    conversations = client.get(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert conversations.status_code == 200
    items = conversations.json()["conversations"]
    assert len(items) == 1
    assert items[0]["conversation_id"] == "telegram:dev-bot:123"
    assert items[0]["title"] == "Telegram chat 123"


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


def test_ui_shell_includes_runtime_skills_panel(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    login = client.post(
        "/ui/login",
        data={"password": "ui-secret"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    response = client.get("/ui")
    assert response.status_code == 200
    assert "Runtime Skills" in response.text
    assert "runtime-skill-search" in response.text
    assert "Catalog, prompt preview, and conversation activation" in response.text


def test_ui_bootstrap_still_accepts_bearer_token(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get(
        "/v1/ui/bootstrap",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert response.status_code == 200


def test_registry_ui_conversation_routes_surface_input_to_polled_bot(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-2")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Spec review",
            "message_text": "Please refine this PRD.",
        },
    )
    assert create.status_code == 201
    conversation_id = create.json()["conversation_id"]

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = poll.json()["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "surface_input"
    assert deliveries[0]["payload"]["conversation_id"] == conversation_id
    assert deliveries[0]["payload"]["text"] == "Please refine this PRD."

    ack = client.post(
        "/v1/agents/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={"delivery_ids": [deliveries[0]["delivery_id"]], "classification": "accepted"},
    )
    assert ack.status_code == 200

    timeline = client.get(
        f"/v1/ui/conversations/{conversation_id}/timeline",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert timeline.status_code == 200
    assert timeline.json()["events"][0]["title"] == "Conversation started"


def test_publish_timeline_stores_events(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Registry Bot", "registry-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-timeline-1",
            "title": "Timeline conversation",
            "origin_surface": "registry",
            "external_id": "conv-timeline-1",
        },
    )
    assert bind.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-1",
                    "conversation_id": "conv-timeline-1",
                    "kind": "started",
                    "title": "Conversation started",
                    "body": "",
                    "created_at": "2026-03-15T00:00:00+00:00",
                },
                {
                    "event_id": "evt-2",
                    "conversation_id": "conv-timeline-1",
                    "kind": "completed",
                    "title": "Done",
                    "body": "Finished work",
                    "created_at": "2026-03-15T00:00:01+00:00",
                },
            ]
        },
    )
    assert publish.status_code == 200

    timeline = client.get(
        "/v1/ui/conversations/conv-timeline-1/timeline",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert timeline.status_code == 200
    events = timeline.json()["events"]
    assert [event["event_id"] for event in events] == ["evt-1", "evt-2"]
    assert [event["kind"] for event in events] == ["started", "completed"]


def test_ui_bootstrap_includes_timeline_event_count(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Registry Bot", "registry-bot-count")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-count-1",
            "title": "Counted timeline",
            "origin_surface": "registry",
            "external_id": "conv-count-1",
        },
    )
    assert bind.status_code == 200
    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-count-1",
                    "conversation_id": "conv-count-1",
                    "kind": "started",
                    "title": "Conversation started",
                    "created_at": "2026-03-15T00:00:00+00:00",
                },
                {
                    "event_id": "evt-count-2",
                    "conversation_id": "conv-count-1",
                    "kind": "progress",
                    "title": "Working…",
                    "body": "Inspecting task",
                    "created_at": "2026-03-15T00:00:01+00:00",
                },
            ]
        },
    )
    assert publish.status_code == 200

    bootstrap = client.get(
        "/v1/ui/bootstrap",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert bootstrap.status_code == 200
    conversations = bootstrap.json()["conversations"]
    assert conversations[0]["conversation_id"] == "conv-count-1"
    assert conversations[0]["timeline_event_count"] == 2


def test_ui_search_returns_matching_conversations(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Search Bot", "search-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-search-1",
            "title": "Searchable conversation",
            "origin_surface": "registry",
            "external_id": "conv-search-1",
        },
    )
    assert bind.status_code == 200
    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-search-1",
                    "conversation_id": "conv-search-1",
                    "kind": "progress",
                    "title": "Working…",
                    "body": "Reviewing quarterly roadmap risks",
                    "created_at": "2026-03-16T00:00:00+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 200

    search = client.get(
        "/v1/ui/search",
        params={"q": "roadmap"},
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert search.status_code == 200
    assert search.json()["results"] == [
        {"conversation_id": "conv-search-1", "snippet": "Reviewing quarterly <b>roadmap</b> risks"}
    ]


def test_ui_search_returns_empty_results_for_malformed_query(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get(
        "/v1/ui/search",
        params={"q": "\"bad"},
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_ui_export_conversation_returns_markdown_and_missing_conversation_404(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Export Bot", "export-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-export-1",
            "title": "Exportable conversation",
            "origin_surface": "registry",
            "external_id": "conv-export-1",
        },
    )
    assert bind.status_code == 200
    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-export-1",
                    "conversation_id": "conv-export-1",
                    "kind": "started",
                    "title": "Conversation started",
                    "body": "Kick off export flow",
                    "created_at": "2026-03-16T00:00:00+00:00",
                },
                {
                    "event_id": "evt-export-2",
                    "conversation_id": "conv-export-1",
                    "kind": "completed",
                    "title": "Done",
                    "body": "Export finished",
                    "created_at": "2026-03-16T00:00:01+00:00",
                },
            ]
        },
    )
    assert publish.status_code == 200

    export = client.get(
        "/v1/ui/conversations/conv-export-1/export",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/markdown")
    assert (
        export.headers["content-disposition"]
        == 'attachment; filename="conversation-conv-export-1.md"'
    )
    assert "# Conversation: Exportable conversation" in export.text
    assert "Status: completed" in export.text
    assert "Bot: Export Bot" in export.text
    assert "## [2026-03-16T00:00:00+00:00] started" in export.text
    assert "Kick off export flow" in export.text
    assert "## [2026-03-16T00:00:01+00:00] completed" in export.text

    missing = client.get(
        "/v1/ui/conversations/does-not-exist/export",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Conversation not found"


def test_ui_usage_endpoint_returns_daily_totals(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, token = _enroll_and_register(client, "Usage Bot", "usage-bot")
    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": "conv-usage-1",
            "title": "Usage conversation",
            "origin_surface": "registry",
            "external_id": "conv-usage-1",
        },
    )
    assert bind.status_code == 200
    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-usage-1",
                    "conversation_id": "conv-usage-1",
                    "kind": "usage",
                    "title": "Token usage",
                    "body": "",
                    "metadata": {
                        "prompt_tokens": 120,
                        "completion_tokens": 30,
                        "cost_usd": 0.015,
                        "provider": "claude",
                    },
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
        },
    )
    assert publish.status_code == 200

    response = client.get(
        "/v1/ui/usage",
        headers={"Authorization": "Bearer ui-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["daily_total"] == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "cost_usd": 0.015,
    }
    assert payload["by_conversation"] == [
        {
            "conversation_id": "conv-usage-1",
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "cost_usd": 0.015,
        }
    ]


def test_create_conversation_api_success(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, _ = _enroll_and_register(client, "API Bot", "api-bot")
    response = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Programmatic trigger",
            "message_text": "Run the nightly report",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["conversation_id"]
    assert payload["target_agent_id"] == agent_id
    assert payload["title"] == "Programmatic trigger"


def test_create_conversation_api_missing_fields(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={},
    )

    assert response.status_code == 422


def test_create_conversation_api_unknown_agent(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": "does-not-exist",
            "message_text": "Run the nightly report",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown agent: does-not-exist"}


def test_create_conversation_api_empty_message(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, _ = _enroll_and_register(client, "API Bot", "api-bot-empty-message")
    response = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "message_text": "",
        },
    )

    assert response.status_code == 422


def test_create_conversation_api_unauthorized(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/ui/conversations",
        json={
            "target_agent_id": "any-agent",
            "message_text": "Run the nightly report",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid UI token"}


def test_ui_create_conversation_creates_delivery(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-delivery")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "UI created work",
            "message_text": "Start from the registry UI.",
        },
    )
    assert create.status_code == 201
    conversation_id = create.json()["conversation_id"]

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = poll.json()["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "surface_input"
    assert deliveries[0]["payload"]["conversation_id"] == conversation_id
    assert deliveries[0]["payload"]["text"] == "Start from the registry UI."


def test_ui_action_delivery_includes_conversation_ref(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-action")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Actionable work",
            "message_text": "Start this from the registry UI.",
        },
    )
    assert create.status_code == 201
    conversation_id = create.json()["conversation_id"]

    action = client.post(
        f"/v1/ui/conversations/{conversation_id}/actions",
        headers={"Authorization": "Bearer ui-secret"},
        json={"action": "approve_delegation"},
    )
    assert action.status_code == 200

    poll = client.get(
        "/v1/agents/poll",
        headers={"Authorization": f"Bearer {token}"},
        params={"cursor": "0", "limit": 20, "wait_seconds": 0},
    )
    assert poll.status_code == 200
    deliveries = [item for item in poll.json()["deliveries"] if item["kind"] == "surface_action"]
    assert len(deliveries) == 1
    assert deliveries[0]["payload"]["conversation_ref"] == conversation_id
    assert deliveries[0]["payload"]["action"] == "approve_delegation"


def test_cancel_conversation_marks_status_cancelling_and_late_progress_does_not_reopen(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    agent_id, token = _enroll_and_register(client, "Product Bot", "product-bot-cancel")
    create = client.post(
        "/v1/ui/conversations",
        headers={"Authorization": "Bearer ui-secret"},
        json={
            "target_agent_id": agent_id,
            "title": "Cancelable work",
            "message_text": "Start this task.",
        },
    )
    assert create.status_code == 201
    conversation_id = create.json()["conversation_id"]

    cancel = client.post(
        f"/v1/ui/conversations/{conversation_id}/actions",
        headers={"Authorization": "Bearer ui-secret"},
        json={"action": "cancel_conversation"},
    )
    assert cancel.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "event_id": "evt-cancel-progress",
                    "conversation_id": conversation_id,
                    "kind": "progress",
                    "title": "Working…",
                    "body": "Still winding down",
                    "created_at": "2026-03-15T00:00:02+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 200

    conversation = client.get(
        f"/v1/ui/conversations/{conversation_id}",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert conversation.status_code == 200
    assert conversation.json()["status"] == "cancelling"


def test_publish_timeline_rejects_foreign_conversation(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    _, owner_token = _enroll_and_register(client, "Owner Bot", "owner-bot")
    _, other_token = _enroll_and_register(client, "Other Bot", "other-bot")

    bind = client.post(
        "/v1/agents/conversations/bind",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "conversation_id": "conv-owner-1",
            "title": "Owner conversation",
            "origin_surface": "registry",
            "external_id": "conv-owner-1",
        },
    )
    assert bind.status_code == 200

    publish = client.post(
        "/v1/agents/timeline",
        headers={"Authorization": f"Bearer {other_token}"},
        json={
            "events": [
                {
                    "event_id": "evt-foreign-1",
                    "conversation_id": "conv-owner-1",
                    "kind": "started",
                    "title": "Should fail",
                    "created_at": "2026-03-15T00:00:00+00:00",
                }
            ]
        },
    )
    assert publish.status_code == 401
    assert "does not belong to agent" in publish.json()["detail"]


def test_registry_routed_result_returns_to_origin_agent(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)

    origin_id, origin_token = _enroll_and_register(client, "Product Bot", "product-origin")
    target_id, target_token = _enroll_and_register(client, "Reviewer Bot", "reviewer-target")

    routed = client.post(
        "/v1/agents/routed-tasks",
        headers={"Authorization": f"Bearer {origin_token}"},
        json={
            "routed_task_id": "task-1",
            "parent_conversation_id": "conv-1",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review test plan",
            "instructions": "Find missing test coverage.",
            "context": {},
            "constraints": {},
            "requested_capabilities": ["reviewer", "tests"],
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

    result = client.post(
        "/v1/agents/routed-tasks/task-1/result",
        headers={"Authorization": f"Bearer {target_token}"},
        json={
            "routed_task_id": "task-1",
            "status": "completed",
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


def test_registry_store_migrations_are_idempotent_and_add_skills_override_and_timeline_fts(tmp_path: Path):
    db_path = tmp_path / "registry.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY, target_agent_id TEXT NOT NULL, "
        "title TEXT NOT NULL DEFAULT '', origin_surface TEXT NOT NULL DEFAULT 'registry', "
        "status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    RegistrySQLiteStore(db_path)
    RegistrySQLiteStore(db_path)

    conn = sqlite3.connect(db_path)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    assert version == "3"
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    assert "skills_override" in tables
    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    assert "tl_ai" in triggers
    assert "tl_ad" in triggers
    assert "tl_au" in triggers
    fts_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='timeline_fts'"
    ).fetchone()
    assert fts_row is not None
    conn.close()
