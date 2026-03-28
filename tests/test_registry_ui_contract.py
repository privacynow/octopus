from pathlib import Path


def test_router_uses_async_prerender_route_swaps_without_preclearing_content() -> None:
    router_path = (
        Path(__file__).resolve().parents[1]
        / "octopus_registry"
        / "ui"
        / "js"
        / "router.js"
    )
    text = router_path.read_text(encoding="utf-8")

    assert "contentEl.textContent = ''" not in text
    assert "async function _render" in text
    assert "Promise.race" in text
    assert "ROUTE_PRERENDER_TIMEOUT_MS = 3000" in text
    assert "contentEl.replaceChildren(inner);" in text


def test_data_fetching_route_components_use_async_prerender_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected = {
        "dashboard.js": "async function renderDashboard(",
        "agent-list.js": "async function renderAgentList(",
        "agent-detail.js": "async function renderAgentDetail(",
        "conversation-list.js": "async function renderConversationList(",
        "conversation-detail.js": "async function renderConversationDetail(",
        "task-list.js": "async function renderTaskList(",
        "approval-list.js": "async function renderApprovalList(",
        "capability-list.js": "async function renderCapabilityList(",
        "usage-view.js": "async function renderUsageView(",
        "skill-catalog.js": "async function renderSkillCatalog(",
        "guidance-editor.js": "async function renderGuidanceEditor(",
    }

    for name, marker in expected.items():
        text = (
            repo_root
            / "octopus_registry"
            / "ui"
            / "js"
            / "components"
            / name
        ).read_text(encoding="utf-8")
        assert marker in text, f"{name} must use async pre-render"


def test_conversation_views_distinguish_task_threads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")

    assert "conversation_type" in conversation_list
    assert "Task thread" in conversation_list
    assert "conversation_type" in agent_detail
    assert "Task thread" in agent_detail
