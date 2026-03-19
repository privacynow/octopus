"""Tests for the modular runtime-skill use-case boundary."""

import time
from pathlib import Path

import app.content_store as content_store_mod
import httpx
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from app.identity import telegram_actor_key
from app.workflows.provider_guidance.preview import get_provider_guidance_use_cases
from app.workflows.runtime_skills.activation import get_runtime_skill_activation_use_cases
from app.workflows.runtime_skills.catalog import get_runtime_skill_catalog_use_cases
from app.workflows.runtime_skills.importing import get_runtime_skill_import_use_cases
from app.workflows.runtime_skills.setup import get_runtime_skill_setup_use_cases
from app.session_state import session_from_dict
from tests.support.skill_test_helpers import derive_encryption_key, load_user_credentials
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
    init_credential_store_for_config(cfg)
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
        assert catalog.filter_resolvable(["code-review", "missing", "helper"]) == ["code-review", "helper"]
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
        )
        assert outcome.status == "activated"
        assert outcome.mutated is True

        listing = activation.list_conversation_skills(["code-review"])
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


def test_import_search_use_case_hides_registry_exception(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        monkeypatch.setattr(
            "app.skill_import_service.registry_client.fetch_index",
            lambda registry_url: (_ for _ in ()).throw(RuntimeError("internal registry URL with secret")),
        )

        results = get_runtime_skill_import_use_cases().search("helper", registry_url=cfg.registry_url)

        assert results.registry == ()
        assert results.registry_error == "Registry search unavailable. Try again later."
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


async def test_setup_use_case_submits_credential_and_activates_skill(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        activation = get_runtime_skill_activation_use_cases()
        setup = get_runtime_skill_setup_use_cases()
        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))

        decision = activation.begin_activate(
            session,
            user_id=actor_key,
            skill_name="github-integration",
        )
        assert decision.status == "needs_setup"

        async def fake_validator(req, value):
            return True, ""

        outcome = await setup.submit_credential_value(
            session,
            user_id=actor_key,
            raw_value="ghp_test_token",
            validator=fake_validator,
        )
        assert outcome.status == "ready"
        assert "github-integration" in session.active_skills

        creds = load_user_credentials(data_dir, actor_key, derive_encryption_key(cfg.telegram_token))
        assert creds["github-integration"]["GITHUB_TOKEN"] == "ghp_test_token"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


async def test_setup_use_case_logs_validation_host_with_skill_name(monkeypatch, caplog, tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        activation = get_runtime_skill_activation_use_cases()
        setup = get_runtime_skill_setup_use_cases()
        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))

        decision = activation.begin_activate(
            session,
            user_id=actor_key,
            skill_name="github-integration",
        )
        assert decision.status == "needs_setup"

        async def fake_request(self, method, url, *, headers=None):
            del self
            return httpx.Response(
                200,
                request=httpx.Request(method, url, headers=headers),
            )

        monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
        monkeypatch.delenv("BOT_CREDENTIAL_VALIDATION_ALLOWED_HOSTS", raising=False)

        caplog.set_level("INFO")
        outcome = await setup.submit_credential_value(
            session,
            user_id=actor_key,
            raw_value="ghp_test_token",
        )

        assert outcome.status == "ready"
        assert "api.github.com" in caplog.text
        assert "github-integration" in caplog.text
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_setup_use_case_cancel_and_clear_credential_effects(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        activation = get_runtime_skill_activation_use_cases()
        setup = get_runtime_skill_setup_use_cases()
        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))

        decision = activation.begin_activate(
            session,
            user_id=actor_key,
            skill_name="github-integration",
        )
        assert decision.status == "needs_setup"

        cancelled = setup.cancel(session, user_id=actor_key)
        assert cancelled.status == "cancelled"
        assert session.awaiting_skill_setup is None

        session.active_skills = ["github-integration"]
        session.awaiting_skill_setup = None
        cleared = setup.apply_cleared_credentials(
            session,
            user_id=actor_key,
            removed_skills=["github-integration"],
            skill_name="github-integration",
        )
        assert cleared.deactivated_skills == ("github-integration",)
        assert session.active_skills == []
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_setup_use_case_starts_missing_credential_flow(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        setup = get_runtime_skill_setup_use_cases()
        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))
        session.active_skills = ["github-integration"]

        outcome = setup.check_satisfaction(
            session,
            user_id=actor_key,
            active_skills=["github-integration"],
        )

        assert outcome.status == "needs_setup"
        assert outcome.mutated is True
        assert outcome.missing_skill == "github-integration"
        assert outcome.first_requirement is not None
        assert session.awaiting_skill_setup is not None
        assert session.awaiting_skill_setup.skill == "github-integration"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_setup_use_case_detects_foreign_setup_without_skill_filter(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        setup = get_runtime_skill_setup_use_cases()
        raw = default_session("claude", {"session_id": "test", "started": False}, "on")
        raw["awaiting_skill_setup"] = {
            "user_id": telegram_actor_key(7),
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = setup.foreign_setup(session, user_id=telegram_actor_key(42))

        assert outcome.status == "foreign_setup"
        assert outcome.setup is not None
        assert outcome.setup.user_id == telegram_actor_key(7)
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_case_blocks_active_foreign_setup_until_stale(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        activation = get_runtime_skill_activation_use_cases()
        raw = default_session("claude", {"session_id": "test", "started": False}, "on")
        raw["awaiting_skill_setup"] = {
            "user_id": telegram_actor_key(7),
            "skill": "code-review",
            "started_at": time.time(),
            "remaining": [{"key": "OTHER_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = activation.begin_setup(
            session,
            user_id=telegram_actor_key(42),
            skill_name="github-integration",
        )

        assert outcome.status == "foreign_setup"
        assert session.awaiting_skill_setup is not None
        assert session.awaiting_skill_setup.user_id == telegram_actor_key(7)
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_case_replaces_stale_foreign_setup(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        activation = get_runtime_skill_activation_use_cases()
        raw = default_session("claude", {"session_id": "test", "started": False}, "on")
        raw["awaiting_skill_setup"] = {
            "user_id": telegram_actor_key(7),
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "OLD_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = activation.begin_setup(
            session,
            user_id=telegram_actor_key(42),
            skill_name="github-integration",
        )

        assert outcome.status == "needs_setup"
        assert outcome.mutated is True
        assert session.awaiting_skill_setup is not None
        assert session.awaiting_skill_setup.user_id == telegram_actor_key(42)
        assert session.awaiting_skill_setup.skill == "github-integration"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()
