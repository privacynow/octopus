import logging
from types import SimpleNamespace

from app.channels.registry import ingress as registry_ingress


def test_prompt_warning_context_logs_when_runtime_context_unavailable(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("bad context")

    monkeypatch.setattr(registry_ingress, "get_runtime_channel_context", _boom)

    with caplog.at_level(logging.WARNING):
        result = registry_ingress.prompt_warning_context()

    assert result is None
    assert "Registry runtime context unavailable for prompt warnings" in caplog.text


def test_uninstall_catalog_skill_logs_and_falls_back_when_runtime_context_missing(monkeypatch, caplog):
    seen: dict[str, object] = {}

    def _boom():
        raise RuntimeError("bad context")

    def _uninstall(skill_name: str, *, default_skills):
        seen["skill_name"] = skill_name
        seen["default_skills"] = default_skills
        return SimpleNamespace(ok=True, message="ok")

    flows = SimpleNamespace(
        runtime_skills=SimpleNamespace(
            imports=SimpleNamespace(uninstall=_uninstall),
        ),
    )

    monkeypatch.setattr(registry_ingress, "get_runtime_channel_context", _boom)
    monkeypatch.setattr(registry_ingress, "_flows", lambda: flows)
    monkeypatch.setattr(registry_ingress.presenters, "mutation_result", lambda result: {"ok": result.ok})

    with caplog.at_level(logging.WARNING):
        result = registry_ingress.uninstall_catalog_skill("sample-skill")

    assert result == {"ok": True}
    assert seen == {"skill_name": "sample-skill", "default_skills": ()}
    assert "Registry runtime context unavailable for uninstall default-skill check" in caplog.text
