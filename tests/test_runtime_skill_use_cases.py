"""Tests for the modular runtime-skill use-case boundary."""

import time
from pathlib import Path

import app.content_store as content_store_mod
import httpx
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from octopus_sdk.identity import telegram_actor_key
from octopus_sdk.workflows.runtime_skill_activation import RuntimeSkillActivationUseCases
from octopus_sdk.workflows.runtime_skill_catalog import RuntimeSkillCatalogUseCases
from octopus_sdk.workflows.runtime_skill_setup import RuntimeSkillSetupUseCases
from app.provider_guidance_service import get_provider_guidance_service
from app.skill_catalog_service import get_skill_catalog_service
from app.runtime import composition
from app.skill_activation_service import get_skill_activation_service
from app.skill_import_service import get_skill_import_service
from app.credential_service import get_credential_service
from app.credential_validation import validate_credential
from octopus_sdk.providers import ProviderStateRecord
from octopus_sdk.sessions import session_from_dict
from tests.support.skill_test_helpers import derive_encryption_key, load_user_credentials
from app.storage import close_db, default_session, ensure_data_dirs
from tests.support.config_support import make_config
from tests.support.runtime_skill_registry import FakeRuntimeSkillRegistry


REGISTRY_URL = "https://registry.example.test/index.json"


def _init_runtime_content(tmp_path: Path, *, default_skills: tuple[str, ...] = ()):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url=REGISTRY_URL, default_skills=default_skills)
    init_content_store_for_config(cfg)
    init_credential_store_for_config(cfg)
    composition.workflows.cache_clear()
    return cfg, data_dir


def _flows():
    return composition.workflows()


def test_catalog_use_cases_expose_clean_local_actions(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body="registry helper", version="1.0.0")
        registry.patch(monkeypatch)

        catalog = _flows().runtime_skills.catalog
        imports = _flows().runtime_skills.imports

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


def test_catalog_use_cases_mark_defaults_for_new_conversations(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path, default_skills=("code-review",))
    try:
        catalog = RuntimeSkillCatalogUseCases(
            catalog_service=get_skill_catalog_service(),
            import_service=get_skill_import_service(),
            default_skills=("code-review",),
        )

        items = {item.name: item for item in catalog.list_skills()}
        assert items["code-review"].default_for_new_conversations is True
        assert items["testing"].default_for_new_conversations is False

        detail = catalog.get_skill("code-review")
        assert detail is not None
        assert detail.default_for_new_conversations is True
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_cases_list_and_activate_skill(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )
        activation = _flows().runtime_skills.activation

        outcome = activation.begin_activate(
            session,
            actor_key=telegram_actor_key(42),
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

        results = _flows().runtime_skills.imports.search("helper", registry_url=cfg.registry_url)

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

        results = _flows().runtime_skills.imports.search("helper", registry_url=cfg.registry_url)

        assert results.registry == ()
        assert results.registry_error == "Registry search unavailable. Try again later."
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_preview_use_case_returns_effective_prompt(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        preview = _flows().provider_guidance.preview.preview(
            "claude",
            role="Senior engineer",
            active_skills=["code-review"],
            compact_mode=True,
        )
        assert preview.provider == "claude"
        assert preview.prompt_weight > 0
        assert "summary first" in preview.composed_prompt.lower()
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_preflight_context_excludes_raw_skill_instruction_bodies(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        guidance = get_provider_guidance_service()
        track = get_skill_catalog_service().resolve_runtime_track("code-review")
        assert track is not None

        run_ctx = guidance.build_run_context("Senior engineer", ["code-review"], ["/tmp/uploads"])
        preflight_ctx = guidance.build_preflight_context(
            "Senior engineer",
            ["code-review"],
            ["/tmp/uploads"],
        )

        assert track.revision.instruction_body in run_ctx.system_prompt
        assert track.revision.instruction_body not in preflight_ctx.system_prompt
        assert track.display_name in preflight_ctx.system_prompt
        assert "Senior engineer" in preflight_ctx.system_prompt
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_codex_context_uses_octopus_skill_semantics(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        guidance = get_provider_guidance_service()

        run_ctx = guidance.build_run_context(
            "Senior engineer",
            ["code-review"],
            ["/tmp/uploads"],
            provider_name="codex",
        )
        preflight_ctx = guidance.build_preflight_context(
            "Senior engineer",
            ["code-review"],
            ["/tmp/uploads"],
            provider_name="codex",
        )

        for prompt in (run_ctx.system_prompt, preflight_ctx.system_prompt):
            assert "Octopus Skill Semantics" in prompt
            assert "Do not answer in terms of Codex-native skills" in prompt
            assert "available on this bot" in prompt
            assert "active in this conversation" in prompt
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


async def test_setup_use_case_submits_credential_and_activates_skill(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        activation = _flows().runtime_skills.activation
        setup = _flows().runtime_skills.setup
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )

        decision = activation.begin_activate(
            session,
            actor_key=actor_key,
            skill_name="github-integration",
        )
        assert decision.status == "needs_setup"

        async def fake_validator(req, value):
            return True, ""

        outcome = await setup.submit_credential_value(
            session,
            actor_key=actor_key,
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
        activation = _flows().runtime_skills.activation
        setup = _flows().runtime_skills.setup
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )

        decision = activation.begin_activate(
            session,
            actor_key=actor_key,
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
            actor_key=actor_key,
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
        activation = _flows().runtime_skills.activation
        setup = _flows().runtime_skills.setup
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )

        decision = activation.begin_activate(
            session,
            actor_key=actor_key,
            skill_name="github-integration",
        )
        assert decision.status == "needs_setup"

        cancelled = setup.cancel(session, actor_key=actor_key)
        assert cancelled.status == "cancelled"
        assert session.awaiting_skill_setup is None

        session.active_skills = ["github-integration"]
        session.awaiting_skill_setup = None
        cleared = setup.apply_cleared_credentials(
            session,
            actor_key=actor_key,
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
        setup = _flows().runtime_skills.setup
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )
        session.active_skills = ["github-integration"]

        outcome = setup.check_satisfaction(
            session,
            actor_key=actor_key,
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


def test_activation_use_case_loads_credentials_only_for_requested_skill(monkeypatch, tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )
        calls: list[tuple[str, tuple[str, ...]]] = []

        class FakeCredentials:
            def load(self, actor_key):
                raise AssertionError(f"unexpected full credential load for {actor_key}")

            def load_for_skills(self, actor_key, skill_names):
                calls.append((actor_key, tuple(skill_names)))
                return {"github-integration": {}}

            def missing_requirements(self, requirements, credential_values):
                del credential_values
                return list(requirements)

        outcome = RuntimeSkillActivationUseCases(
            catalog=_flows().runtime_skills.catalog,
            activation=get_skill_activation_service(),
            credentials=FakeCredentials(),
            guidance=get_provider_guidance_service(),
            setup=_flows().runtime_skills.setup,
            prompt_size_warning_threshold=0,
        ).begin_activate(
            session,
            actor_key=telegram_actor_key(42),
            skill_name="github-integration",
        )

        assert outcome.status == "needs_setup"
        assert calls == [(telegram_actor_key(42), ("github-integration",))]
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_setup_use_case_checks_credentials_only_for_active_skills(monkeypatch, tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )
        session.active_skills = ["github-integration"]
        calls: list[tuple[str, tuple[str, ...]]] = []

        class FakeCredentials:
            def load(self, actor_key):
                raise AssertionError(f"unexpected full credential load for {actor_key}")

            def load_for_skills(self, actor_key, skill_names):
                calls.append((actor_key, tuple(skill_names)))
                return {"github-integration": {}}

            def missing_requirements(self, requirements, credential_values):
                del credential_values
                return list(requirements)

            def build_env(self, active_skills, user_credentials):
                del active_skills, user_credentials
                return {}

        outcome = RuntimeSkillSetupUseCases(
            catalog=_flows().runtime_skills.catalog,
            credentials=FakeCredentials(),
            activation=get_skill_activation_service(),
            default_validator=validate_credential,
        ).check_satisfaction(
            session,
            actor_key=telegram_actor_key(42),
            active_skills=["github-integration"],
        )

        assert outcome.status == "needs_setup"
        assert calls == [(telegram_actor_key(42), ("github-integration",))]
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_setup_use_case_detects_foreign_setup_without_skill_filter(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        setup = _flows().runtime_skills.setup
        raw = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        raw["awaiting_skill_setup"] = {
            "actor_key": telegram_actor_key(7),
            "skill": "github-integration",
            "started_at": time.time(),
            "remaining": [{"key": "GITHUB_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = setup.foreign_setup(session, actor_key=telegram_actor_key(42))

        assert outcome.status == "foreign_setup"
        assert outcome.setup is not None
        assert outcome.setup.actor_key == telegram_actor_key(7)
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_case_blocks_active_foreign_setup_until_stale(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        activation = _flows().runtime_skills.activation
        raw = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        raw["awaiting_skill_setup"] = {
            "actor_key": telegram_actor_key(7),
            "skill": "code-review",
            "started_at": time.time(),
            "remaining": [{"key": "OTHER_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = activation.begin_setup(
            session,
            actor_key=telegram_actor_key(42),
            skill_name="github-integration",
        )

        assert outcome.status == "foreign_setup"
        assert session.awaiting_skill_setup is not None
        assert session.awaiting_skill_setup.actor_key == telegram_actor_key(7)
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_activation_use_case_replaces_stale_foreign_setup(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        activation = _flows().runtime_skills.activation
        raw = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        raw["awaiting_skill_setup"] = {
            "actor_key": telegram_actor_key(7),
            "skill": "github-integration",
            "started_at": 0,
            "remaining": [{"key": "OLD_TOKEN", "prompt": "Paste token"}],
        }
        session = session_from_dict(raw)

        outcome = activation.begin_setup(
            session,
            actor_key=telegram_actor_key(42),
            skill_name="github-integration",
        )

        assert outcome.status == "needs_setup"
        assert outcome.mutated is True
        assert session.awaiting_skill_setup is not None
        assert session.awaiting_skill_setup.actor_key == telegram_actor_key(42)
        assert session.awaiting_skill_setup.skill == "github-integration"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()
