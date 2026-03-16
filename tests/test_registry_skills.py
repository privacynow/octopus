"""Tests for registry-managed skills overrides and discovery enforcement."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.registry_service.app import app
from app.registry_service.store import RegistrySQLiteStore


def _register_agent(store: RegistrySQLiteStore, *, name: str, slug: str, skills: list[str]) -> tuple[str, str]:
    enrolled = store.enroll(
        {
            "display_name": name,
            "slug": slug,
            "role": "developer",
            "skills": skills,
            "tags": ["registry"],
            "description": f"{name} description",
            "provider": "codex",
            "mode": "registry",
            "connectivity_state": "connected",
            "surface_capabilities": ["registry"],
            "version": "test",
        }
    )
    store.register(
        enrolled["agent_token"],
        {
            "agent_card": {
                "display_name": name,
                "slug": slug,
                "role": "developer",
                "skills": skills,
                "tags": ["registry"],
                "description": f"{name} description",
                "provider": "codex",
                "mode": "registry",
                "surface_capabilities": ["registry"],
                "version": "test",
            },
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 1,
        },
    )
    return enrolled["agent_id"], enrolled["agent_token"]


def _store(tmp_path: Path) -> RegistrySQLiteStore:
    return RegistrySQLiteStore(tmp_path / "registry.sqlite3")


def _configure_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REGISTRY_DB_PATH", str(tmp_path / "registry.sqlite3"))
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")


def test_list_skills_empty_when_no_agents(tmp_path: Path):
    store = _store(tmp_path)

    assert store.list_skills() == []


def test_list_skills_aggregates_declared(tmp_path: Path):
    store = _store(tmp_path)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search", "code_exec"])
    _register_agent(store, name="Beta Bot", slug="beta-bot", skills=["web_search", "file_read"])

    skills = {item["skill_name"]: item for item in store.list_skills()}

    assert set(skills) == {"code_exec", "file_read", "web_search"}
    assert skills["code_exec"]["declared_by_agents"] == ["alpha-bot"]
    assert skills["file_read"]["declared_by_agents"] == ["beta-bot"]
    assert skills["web_search"]["declared_by_agents"] == ["alpha-bot", "beta-bot"]
    assert skills["web_search"]["enabled"] is None


def test_set_and_get_override(tmp_path: Path):
    store = _store(tmp_path)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search"])

    store.set_skill_override("web_search", False)

    assert store.get_skill_override("web_search") is False
    skills = {item["skill_name"]: item for item in store.list_skills()}
    assert skills["web_search"]["enabled"] is False


def test_enable_override(tmp_path: Path):
    store = _store(tmp_path)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search"])

    store.set_skill_override("web_search", False)
    store.set_skill_override("web_search", True)

    assert store.get_skill_override("web_search") is True
    skills = {item["skill_name"]: item for item in store.list_skills()}
    assert skills["web_search"]["enabled"] is True


def test_override_row_survives_agent_deregistration(tmp_path: Path):
    store = _store(tmp_path)
    _, agent_token = _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search"])

    store.set_skill_override("web_search", False)
    store.deregister(agent_token)

    skills = {item["skill_name"]: item for item in store.list_skills()}
    assert skills["web_search"]["enabled"] is False
    assert skills["web_search"]["declared_by_agents"] == []


def test_disabled_skill_absent_from_search_results(tmp_path: Path):
    store = _store(tmp_path)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search"])

    assert [item["slug"] for item in store.search_agents({"skills": ["web_search"]})] == ["alpha-bot"]

    store.set_skill_override("web_search", False)

    assert store.search_agents({"skills": ["web_search"]}) == []


def test_ui_skills_endpoints_toggle_override_and_affect_search(monkeypatch, tmp_path: Path):
    _configure_registry(monkeypatch, tmp_path)
    client = TestClient(app)
    store = RegistrySQLiteStore(tmp_path / "registry.sqlite3")
    _, agent_token = _register_agent(store, name="Alpha Bot", slug="alpha-bot", skills=["web_search"])

    listed = client.get("/v1/ui/skills", headers={"Authorization": "Bearer ui-secret"})
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "skill_name": "web_search",
            "declared_by_agents": ["alpha-bot"],
            "enabled": None,
        }
    ]

    disabled = client.post(
        "/v1/ui/skills/web_search/disable",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {"skill_name": "web_search", "enabled": False}

    search = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"skills": ["web_search"]},
    )
    assert search.status_code == 200
    assert search.json() == {"agents": []}

    enabled = client.post(
        "/v1/ui/skills/web_search/enable",
        headers={"Authorization": "Bearer ui-secret"},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"skill_name": "web_search", "enabled": True}

    search = client.post(
        "/v1/agents/discovery/search",
        headers={"Authorization": f"Bearer {agent_token}"},
        json={"skills": ["web_search"]},
    )
    assert search.status_code == 200
    assert [item["slug"] for item in search.json()["agents"]] == ["alpha-bot"]
