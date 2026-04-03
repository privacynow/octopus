"""Tests for runtime skill catalog services over the shared content store."""

from pathlib import Path

import app.content_store as content_store_mod
from octopus_sdk.content_models import RuntimeSkillTrackRecord, SkillFileRecord, SkillRevisionRecord
from app.content_store import get_content_store, init_content_store_for_config
from octopus_sdk.execution_context import resolve_execution_context
from octopus_sdk.providers import ProviderStateRecord
from app.provider_guidance_service import get_provider_guidance_service
from octopus_sdk.sessions import session_from_dict
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.storage import close_db, default_session, ensure_data_dirs
from tests.support.config_support import make_config
from tests.support.runtime_skill_registry import FakeRuntimeSkillRegistry


REGISTRY_URL = "https://registry.example.test/index.json"
MARKER_V1 = "STORE_SERVICE_MARKER_V1_7d11"
MARKER_V2 = "STORE_SERVICE_MARKER_V2_2c93"
MARKER_CUSTOM = "STORE_SERVICE_MARKER_CUSTOM_9af5"


def _init_runtime_content(tmp_path: Path):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url=REGISTRY_URL)
    init_content_store_for_config(cfg)
    return cfg, data_dir


def _custom_track(name: str, *, body: str) -> RuntimeSkillTrackRecord:
    return RuntimeSkillTrackRecord(
        slug=name,
        display_name=name.title(),
        description="custom fixture",
        source_kind="custom",
        source_uri=f"custom/{name}",
        owner_actor="tg:42",
        visibility="private",
        is_mutable=True,
        revision=SkillRevisionRecord(
            instruction_body=body,
            version_label="draft",
            created_by="tests",
        ),
    )


def _scripted_track(name: str) -> RuntimeSkillTrackRecord:
    return RuntimeSkillTrackRecord(
        slug=name,
        display_name=name.title(),
        description="scripted fixture",
        source_kind="custom",
        source_uri=f"custom/{name}",
        owner_actor="tg:42",
        visibility="private",
        is_mutable=True,
        revision=SkillRevisionRecord(
            instruction_body="Use the helper script.",
            provider_config={
                "codex": {
                    "sandbox": "workspace-write",
                    "scripts": [{"name": "helper.sh", "source": "bin/helper.sh"}],
                }
            },
            files=(
                SkillFileRecord(
                    relative_path="bin/helper.sh",
                    content_text="#!/bin/sh\necho scripted\n",
                    content_type="text/x-shellscript",
                    executable=True,
                ),
            ),
            version_label="draft",
            created_by="tests",
        ),
    )


def test_content_store_bootstrap_seeds_builtin_skills_and_guidance(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        catalog = get_skill_catalog_service()
        guidance = get_provider_guidance_service()

        assert catalog.has_skill("code-review")
        assert catalog.resolve_track("code-review") is not None
        assert guidance.effective_guidance("claude") is not None
        assert guidance.effective_guidance("codex") is not None
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_registry_install_update_diff_and_uninstall_round_trip(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body=MARKER_V1, version="1.0.0", description="registry helper")
        registry.patch(monkeypatch)

        imports = get_skill_import_service()
        catalog = get_skill_catalog_service()

        installed = imports.install_from_registry("helper", cfg.registry_url)
        assert installed.ok is True
        assert MARKER_V1 in catalog.resolve_info("helper").body
        assert catalog.resolve_track("helper").source_kind == "imported"

        registry.add_skill("helper", body=MARKER_V2, version="2.0.0", description="registry helper")
        statuses = {item.name: item.status for item in imports.list_updates()}
        assert statuses["helper"] == "update_available"

        diff = imports.diff("helper").message
        assert MARKER_V1 in diff
        assert MARKER_V2 in diff

        updated = imports.update("helper")
        assert updated.ok is True
        resolved = catalog.resolve_track("helper")
        assert resolved is not None
        assert resolved.revision.instruction_body == MARKER_V2

        removed = imports.uninstall("helper")
        assert removed.ok is True
        assert imports.is_installed("helper") is False
        assert catalog.resolve_track("helper") is None
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_custom_override_shadows_imported_track_and_survives_uninstall(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body=MARKER_V1)
        registry.patch(monkeypatch)

        store = get_content_store()
        imports = get_skill_import_service()
        catalog = get_skill_catalog_service()

        assert imports.install_from_registry("helper", cfg.registry_url).ok is True
        store.replace_skill_track(_custom_track("helper", body=MARKER_CUSTOM))

        resolved = catalog.resolve_track("helper")
        assert resolved is not None
        assert resolved.source_kind == "custom"
        assert resolved.revision.instruction_body == MARKER_CUSTOM
        assert imports.has_custom_override("helper") is True

        assert imports.uninstall("helper").ok is True
        resolved_after = catalog.resolve_track("helper")
        assert resolved_after is not None
        assert resolved_after.source_kind == "custom"
        assert resolved_after.revision.instruction_body == MARKER_CUSTOM
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_registry_digest_mismatch_leaves_no_content_residue(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("tampered", body="tampered body", digest="0" * 64)
        registry.patch(monkeypatch)

        store = get_content_store()
        imports = get_skill_import_service()
        before = {item.slug for item in store.list_skill_summaries()}

        result = imports.install_from_registry("tampered", cfg.registry_url)
        assert result.ok is False
        assert result.message == "Could not reach the skill store. Try again later."
        assert get_skill_catalog_service().resolve_track("tampered") is None
        assert store.list_skill_tracks("tampered") == []
        assert {item.slug for item in store.list_skill_summaries()} == before
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_service_uses_content_store_tracks_for_codex_scripts(tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        store = get_content_store()
        store.replace_skill_track(_scripted_track("scripted"))

        guidance = get_provider_guidance_service()
        provider_config = guidance.provider_config("codex", ["scripted"])

        assert provider_config["sandbox"] == "workspace-write"
        assert provider_config["scripts"] == [{"name": "helper.sh", "source": "bin/helper.sh"}]

        staged = guidance.stage_codex_scripts(data_dir, "conv:1", ["scripted"])
        assert staged is not None
        helper = staged / "scripted" / "helper.sh"
        assert helper.read_text(encoding="utf-8") == "#!/bin/sh\necho scripted\n"
        assert helper.stat().st_mode & 0o111
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_execution_context_hash_tracks_content_store_updates(monkeypatch, tmp_path: Path):
    cfg, data_dir = _init_runtime_content(tmp_path)
    try:
        registry = FakeRuntimeSkillRegistry(tmp_path / "registry")
        registry.add_skill("helper", body=MARKER_V1, version="1.0.0")
        registry.patch(monkeypatch)

        imports = get_skill_import_service()
        assert imports.install_from_registry("helper", cfg.registry_url).ok is True

        session = default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "off")
        session["active_skills"] = ["helper"]
        ctx_v1 = resolve_execution_context(
            session_from_dict(session),
            cfg,
            "claude",
            catalog=get_skill_catalog_service(),
        )

        registry.add_skill("helper", body=MARKER_V2, version="2.0.0")
        assert imports.update("helper").ok is True
        ctx_v2 = resolve_execution_context(
            session_from_dict(session),
            cfg,
            "claude",
            catalog=get_skill_catalog_service(),
        )

        assert ctx_v1.skill_digests["helper"] != ctx_v2.skill_digests["helper"]
        assert ctx_v1.context_hash != ctx_v2.context_hash
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()
