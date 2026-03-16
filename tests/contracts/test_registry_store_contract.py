"""Registry store contract: backend-neutral behavior for SQLite and Postgres."""

from pathlib import Path

import pytest

from app.registry_service.store import RegistrySQLiteStore
from app.registry_service.store_base import SkillDisabledError


def _card(slug: str, skills: list[str] | None = None) -> dict:
    return {
        "display_name": slug,
        "slug": slug,
        "role": "developer",
        "skills": skills or ["python"],
        "tags": ["backend"],
        "description": f"{slug} description",
        "provider": "codex",
        "mode": "registry",
        "connectivity_state": "connected",
        "surface_capabilities": ["registry"],
        "version": "test",
    }


def _enroll(store, slug: str, skills: list[str] | None = None) -> tuple[str, str]:
    enrolled = store.enroll(_card(slug, skills))
    store.register(
        enrolled["agent_token"],
        {
            "agent_card": _card(slug, skills),
            "connectivity_state": "connected",
            "current_capacity": 0,
            "max_capacity": 2,
        },
    )
    return enrolled["agent_id"], enrolled["agent_token"]


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path: Path):
    if request.param == "sqlite":
        yield RegistrySQLiteStore(tmp_path / "registry.sqlite3")
        return

    postgres_url = request.getfixturevalue("postgres_registry_truncated")
    from app.registry_service.store_postgres import RegistryPostgresStore

    yield RegistryPostgresStore(postgres_url)


def test_enroll_and_register_returns_agent_id(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    assert agent_id
    assert agent_token
    agents = store.list_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == agent_id


def test_poll_delivers_to_enrolled_agent(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    delivery = store.create_delivery(
        target_agent_id=agent_id,
        kind="surface_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )

    polled = store.poll(agent_token, cursor=0, limit=20)

    assert delivery["delivery_id"]
    assert len(polled["deliveries"]) == 1
    assert polled["deliveries"][0]["kind"] == "surface_input"
    assert polled["deliveries"][0]["payload"]["text"] == "hello"


def test_ack_marks_delivery_done(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")
    store.create_delivery(
        target_agent_id=agent_id,
        kind="surface_input",
        payload={"conversation_id": "conv-1", "text": "hello"},
    )

    polled = store.poll(agent_token, cursor=0, limit=20)
    delivery_id = polled["deliveries"][0]["delivery_id"]
    store.ack(agent_token, delivery_ids=[delivery_id], classification="accepted")

    assert store.poll(agent_token, cursor=0, limit=20)["deliveries"] == []


def test_search_agents_by_skill(store):
    _enroll(store, "rust-bot", ["rust"])

    hits = store.search_agents({"skills": ["rust"], "required_state": "connected"})
    misses = store.search_agents({"skills": ["python"], "required_state": "connected"})

    assert [item["slug"] for item in hits] == ["rust-bot"]
    assert misses == []


def test_search_agents_excludes_offline(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.deregister(agent_token)

    assert store.search_agents({"required_state": "connected"}) == []


def test_create_routed_task_and_lookup(store):
    origin_id, _ = _enroll(store, "origin-bot")
    target_id, target_token = _enroll(store, "target-bot", ["reviewer"])

    routed = store.create_routed_task(
        {
            "routed_task_id": "task-1",
            "parent_conversation_id": "conv-1",
            "origin_agent_id": origin_id,
            "target_agent_id": target_id,
            "title": "Review task",
            "instructions": "Review the spec.",
            "context": {},
            "constraints": {},
            "requested_capabilities": ["reviewer"],
            "priority": "normal",
            "created_at": "2026-03-16T00:00:00+00:00",
        }
    )

    deliveries = store.poll(target_token, cursor=0, limit=20)["deliveries"]

    assert routed["routed_task_id"] == "task-1"
    assert routed["delivery_id"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "routed_task"


def test_create_routed_task_disabled_skill_raises(store):
    origin_id, _ = _enroll(store, "origin-bot")
    target_id, _ = _enroll(store, "target-bot", ["reviewer"])
    store.set_skill_override("reviewer", enabled=False)

    with pytest.raises(SkillDisabledError):
        store.create_routed_task(
            {
                "routed_task_id": "task-disabled",
                "parent_conversation_id": "conv-1",
                "origin_agent_id": origin_id,
                "target_agent_id": target_id,
                "title": "Disabled review task",
                "skill": "reviewer",
                "instructions": "Review the spec.",
                "context": {},
                "constraints": {},
                "priority": "normal",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        )


def test_bind_conversation_is_visible(store):
    _, agent_token = _enroll(store, "alpha-bot")

    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "c1",
            "title": "Conversation 1",
            "origin_surface": "telegram",
        },
    )

    conversations = store.list_conversations()
    assert [item["conversation_id"] for item in conversations] == ["c1"]


def test_create_conversation_delivers_surface_input(store):
    agent_id, agent_token = _enroll(store, "alpha-bot")

    conversation = store.create_conversation(
        target_agent_id=agent_id,
        title="Registry conversation",
        message_text="hello from registry",
    )
    deliveries = store.poll(agent_token, cursor=0, limit=20)["deliveries"]

    assert conversation["conversation_id"]
    assert len(deliveries) == 1
    assert deliveries[0]["kind"] == "surface_input"
    assert deliveries[0]["payload"]["text"] == "hello from registry"


def test_timeline_publish_and_retrieve(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-1",
            "title": "Bound conversation",
            "origin_surface": "registry",
        },
    )

    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-1",
                "conversation_id": "conv-1",
                "kind": "progress",
                "title": "Working",
                "body": "Doing the work",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    events = store.get_conversation_timeline("conv-1")
    assert len(events) == 1
    assert events[0]["kind"] == "progress"
    assert events[0]["body"] == "Doing the work"


def test_usage_summary_from_timeline(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-usage",
            "title": "Usage conversation",
            "origin_surface": "registry",
        },
    )
    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-usage",
                "conversation_id": "conv-usage",
                "kind": "usage",
                "title": "Token usage",
                "body": "",
                "metadata": {
                    "prompt_tokens": 123,
                    "completion_tokens": 45,
                    "cost_usd": 0.0123,
                    "provider": "claude",
                },
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    rows = store.get_usage_summary("2026-03-15T00:00:00+00:00")

    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "conv-usage"
    assert rows[0]["metadata"]["prompt_tokens"] == 123
    assert rows[0]["metadata"]["completion_tokens"] == 45


def test_search_conversations_fts(store):
    _, agent_token = _enroll(store, "alpha-bot")
    store.bind_conversation(
        agent_token,
        {
            "conversation_id": "conv-search",
            "title": "Search conversation",
            "origin_surface": "registry",
        },
    )
    store.publish_timeline(
        agent_token,
        [
            {
                "event_id": "evt-search",
                "conversation_id": "conv-search",
                "kind": "progress",
                "title": "Search body",
                "body": "the quick brown fox",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
        ],
    )

    results = store.search_conversations("quick")

    assert len(results) == 1
    assert results[0]["conversation_id"] == "conv-search"
    assert results[0]["snippet"]


def test_skill_override_disabled_excludes_from_search(store):
    _enroll(store, "rust-bot", ["rust"])
    store.set_skill_override("rust", enabled=False)

    assert store.search_agents({"skills": ["rust"], "required_state": "connected"}) == []


def test_list_skills_aggregates_declared(store):
    _enroll(store, "alpha-bot", ["python"])
    _enroll(store, "beta-bot", ["python"])

    skills = {item["skill_name"]: item for item in store.list_skills()}

    assert "python" in skills
    assert skills["python"]["declared_by_agents"] == ["alpha-bot", "beta-bot"]


def test_skill_override_survives_agent_deregistration(store):
    _, agent_token = _enroll(store, "go-bot", ["go"])
    store.set_skill_override("go", enabled=False)
    store.deregister(agent_token)

    skills = {item["skill_name"]: item for item in store.list_skills()}

    assert skills["go"]["enabled"] is False
    assert skills["go"]["declared_by_agents"] == []
