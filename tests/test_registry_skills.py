"""Tests for registry-managed routing-skill policy and discovery enforcement."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("REGISTRY_ALLOW_HTTP", "1")

from octopus_registry.server import app
from octopus_registry.store_postgres import RegistryPostgresStore
from octopus_sdk.registry.models import AgentCard, AgentDiscoveryQuery, AgentRegisterRequest


def _register_agent(store: RegistryPostgresStore, *, name: str, slug: str, routing_skills: list[str]) -> tuple[str, str]:
    card = AgentCard(
        bot_key=f"bot:{slug}",
        display_name=name,
        slug=slug,
        role="developer",
        registry_scope="full",
        routing_skills=routing_skills,
        tags=["registry"],
        description=f"{name} description",
        provider="codex",
        mode="registry",
        connectivity_state="connected",
        channel_capabilities=["registry"],
        version="test",
    )
    enrolled = store.enroll(card)
    store.register(
        enrolled.agent_token,
        AgentRegisterRequest(
            agent_card=card,
            connectivity_state="connected",
            current_capacity=0,
            max_capacity=1,
        ),
    )
    return enrolled.agent_id, enrolled.agent_token


def _store(postgres_db_url: str) -> RegistryPostgresStore:
    return RegistryPostgresStore(postgres_db_url)


def _configure_registry(monkeypatch, postgres_db_url: str) -> None:
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", postgres_db_url)
    monkeypatch.setenv("REGISTRY_ENROLL_TOKEN", "enroll-secret")
    monkeypatch.setenv("REGISTRY_UI_TOKEN", "ui-secret")
    monkeypatch.setenv("REGISTRY_ALLOW_HTTP", "1")


def test_list_routing_skills_empty_when_no_agents(postgres_db_url: str):
    store = _store(postgres_db_url)

    assert store.list_routing_skills() == []


def test_list_routing_skills_aggregates_declared(postgres_db_url: str):
    store = _store(postgres_db_url)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search", "code_exec"])
    _register_agent(store, name="Beta Bot", slug="beta-bot", routing_skills=["web_search", "file_read"])

    skills = {item.skill_name: item for item in store.list_routing_skills()}

    assert set(skills) == {"code_exec", "file_read", "web_search"}
    assert skills["code_exec"].advertised_by_agents == ["alpha-bot"]
    assert skills["file_read"].advertised_by_agents == ["beta-bot"]
    assert skills["web_search"].advertised_by_agents == ["alpha-bot", "beta-bot"]


def test_search_agents_free_text_handles_disabled_routing_skills(postgres_db_url: str):
    store = _store(postgres_db_url)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    hits = store.search_agents(AgentDiscoveryQuery(free_text="web", required_state="connected"))
    store.set_routing_skill_override("web_search", enabled=False)
    misses = store.search_agents(AgentDiscoveryQuery(free_text="web", required_state="connected"))

    assert [item.slug for item in hits] == ["alpha-bot"]
    assert misses == []


def test_set_and_get_override(postgres_db_url: str):
    store = _store(postgres_db_url)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    store.set_routing_skill_override("web_search", False)

    assert store.get_routing_skill_override("web_search") is False
    skills = {item.skill_name: item for item in store.list_routing_skills()}
    assert skills["web_search"].enabled is False


def test_enable_override(postgres_db_url: str):
    store = _store(postgres_db_url)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    store.set_routing_skill_override("web_search", False)
    store.set_routing_skill_override("web_search", True)

    assert store.get_routing_skill_override("web_search") is True
    skills = {item.skill_name: item for item in store.list_routing_skills()}
    assert skills["web_search"].enabled is True


def test_override_row_survives_agent_deregistration(postgres_db_url: str):
    store = _store(postgres_db_url)
    _, agent_token = _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    store.set_routing_skill_override("web_search", False)
    store.deregister(agent_token)

    skills = {item.skill_name: item for item in store.list_routing_skills()}
    assert skills["web_search"].enabled is False
    assert skills["web_search"].advertised_by_agents == []


def test_disabled_skill_absent_from_search_results(postgres_db_url: str):
    store = _store(postgres_db_url)
    _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    assert [
        item.slug for item in store.search_agents(
            AgentDiscoveryQuery(skills=["web_search"])
        )
    ] == ["alpha-bot"]

    store.set_routing_skill_override("web_search", False)

    assert store.search_agents(AgentDiscoveryQuery(skills=["web_search"])) == []


def test_ui_routing_skill_endpoints_toggle_override_and_affect_search(
    monkeypatch,
    postgres_db_url: str,
):
    _configure_registry(monkeypatch, postgres_db_url)
    client = TestClient(app)
    store = RegistryPostgresStore(postgres_db_url)
    _, agent_token = _register_agent(store, name="Alpha Bot", slug="alpha-bot", routing_skills=["web_search"])

    # Authenticate as operator
    client.post("/ui/login", data={"password": "ui-secret"})
    csrf = client.get("/v1/auth/csrf").json().get("csrf_token", "")

    listed = client.get("/v1/routing/skills")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "skill_name": "web_search",
            "selector": "@skill:web_search",
            "advertised_by_agents": ["alpha-bot"],
            "enabled": None,
        }
    ]

    disabled = client.post(
        "/v1/routing/skills/web_search/disable",
        headers={"X-CSRF-Token": csrf},
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
        "/v1/routing/skills/web_search/enable",
        headers={"X-CSRF-Token": csrf},
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
