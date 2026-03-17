"""Tests for the modular runtime-skill use-case boundary."""

from pathlib import Path

import app.content_store as content_store_mod
from app.content_store import init_content_store_for_config
from app.identity import telegram_actor_key
from app.provider_guidance_use_cases import get_provider_guidance_use_cases
from app.runtime_skill_activation_use_cases import get_runtime_skill_activation_use_cases
from app.runtime_skill_catalog_use_cases import get_runtime_skill_catalog_use_cases
from app.runtime_skill_import_use_cases import get_runtime_skill_import_use_cases
from app.session_state import session_from_dict
from app.storage import close_db, default_session, ensure_data_dirs
from tests.support.config_support import make_config
from tests.support.runtime_skill_registry import FakeRuntimeSkillRegistry


REGISTRY_URL = "https://registry.example.test/index.json"


def _init_runtime_content(tmp_path: Path):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url=REGISTRY_URL)
    init_content_store_for_config(cfg)
    return cfg, data_dir


def test_catalog_use_cases_expose_clean_local_actions(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body="registry helper", version="1.0.0")
        registry.patch(monkeypatch)

        catalog = get_runtime_skill_catalog_use_cases()
        imports = get_runtime_skill_import_use_cases()

        builtin = catalog.get_skill("code-review")
        assert builtin is not None
        assert builtin.source_kind == "builtin"
        assert builtin.can_activate is True
        assert builtin.can_update is False
        assert builtin.can_uninstall is False

        assert imports.install_from_registry("helper", cfg.registry_url).ok is True
        imported = catalog.get_skill("helper")
        assert imported is not None
        assert imported.source_kind == "imported"
        assert imported.can_activate is True
        assert imported.can_update is True
        assert imported.can_uninstall is True
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_cases_list_and_activate_skill(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))
        activation = get_runtime_skill_activation_use_cases()

        outcome = activation.begin_activate(
            session,
            user_id=telegram_actor_key(42),
            skill_name="code-review",
            data_dir=data_dir,
            encryption_key=b"test-key",
        )
        assert outcome.status == "activated"
        assert outcome.mutated is True

        listing = activation.list_conversation_skills(session)
        assert listing.active_skills == ("code-review",)
        assert listing.active_skill_details[0].source_kind == "builtin"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_import_search_use_case_returns_registry_hits(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body="registry helper", version="1.0.0", description="use-case test")
        registry.patch(monkeypatch)

        results = get_runtime_skill_import_use_cases().search("helper", registry_url=cfg.registry_url)

        assert any(item.name == "helper" for item in results.registry)
        assert results.registry[0].can_import is True
        assert results.registry_error == ""
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_preview_use_case_returns_effective_prompt(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        preview = get_provider_guidance_use_cases().preview(
            "claude",
            role="Senior engineer",
            active_skills=["code-review"],
            compact_mode=True,
        )
        assert preview.provider == "claude"
        assert preview.prompt_weight > 0
        assert "summary first" in preview.system_prompt.lower()
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()
