from pathlib import Path


def test_router_uses_atomic_route_swaps_without_preclearing_content() -> None:
    router_path = (
        Path(__file__).resolve().parents[1]
        / "octopus_registry"
        / "ui"
        / "js"
        / "router.js"
    )
    text = router_path.read_text(encoding="utf-8")

    assert "contentEl.textContent = ''" not in text
    assert "contentEl.replaceChildren(inner);" in text


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
