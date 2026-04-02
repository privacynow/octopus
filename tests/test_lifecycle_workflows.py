"""Lifecycle workflow tests for custom skills and provider guidance."""

from pathlib import Path
import sqlite3

import pytest
import app.content_store as content_store_mod
from app.content_store import get_content_store, init_content_store_for_config
from app.content_store_postgres import PostgresContentStore
from app.credential_store import init_credential_store_for_config
from octopus_sdk.content_models import SkillFileRecord
from octopus_sdk.identity import telegram_actor_key
from octopus_sdk.providers import ProviderConfigRecord, ProviderStateRecord
from octopus_sdk.sessions import session_from_dict
from octopus_sdk.skill_types import SkillRequirement
from app.runtime import composition
from app.storage import close_db, default_session, ensure_data_dirs
from tests.support.config_support import make_config


def _init_runtime_content(tmp_path: Path):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url="https://registry.example.test/index.json")
    init_content_store_for_config(cfg)
    init_credential_store_for_config(cfg)
    composition.workflows.cache_clear()
    return cfg, data_dir


def test_runtime_skill_lifecycle_workflow_requires_publish_before_activation(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        flows = composition.workflows()
        authoring = flows.runtime_skills.authoring
        approval = flows.runtime_skills.approval
        activation = flows.runtime_skills.activation

        created = authoring.create_draft("workflow-draft", owner_actor=actor_key)
        assert created.ok is True
        assert created.detail is not None
        assert created.detail.lifecycle_status == "draft"
        assert created.detail.runtime_available is False

        session = session_from_dict(
            default_session("claude", ProviderStateRecord({"session_id": "test", "started": False}), "on")
        )
        unavailable = activation.begin_activate(session, actor_key=actor_key, skill_name="workflow-draft")
        assert unavailable.status == "not_published"

        edited = authoring.edit_draft(
            "workflow-draft",
            actor_key=actor_key,
            body="Use this draft for workflow testing.",
            changelog="Initial draft",
        )
        assert edited.ok is True
        assert edited.detail is not None
        assert edited.detail.body == "Use this draft for workflow testing."

        submitted = authoring.submit("workflow-draft", actor_key=actor_key, note="Ready for review")
        assert submitted.status == "submitted"
        assert submitted.detail is not None
        assert submitted.detail.lifecycle_status == "review"

        rejected = approval.reject("workflow-draft", actor_key="admin:1", note="Needs one more edit")
        assert rejected.status == "rejected"
        assert rejected.detail is not None
        assert rejected.detail.lifecycle_status == "draft"

        resubmitted = authoring.submit("workflow-draft", actor_key=actor_key, note="Updated")
        assert resubmitted.status == "submitted"

        approved = approval.approve("workflow-draft", actor_key="admin:1", note="Looks good")
        assert approved.status == "approved"
        assert approved.detail is not None

        published = authoring.publish("workflow-draft", actor_key="admin:1")
        assert published.status == "published"
        assert published.detail is not None
        assert published.detail.runtime_available is True
        assert any(item.action == "approved" for item in published.detail.approvals)
        assert any(item.is_published for item in published.detail.revisions)

        activated = activation.begin_activate(session, actor_key=actor_key, skill_name="workflow-draft")
        assert activated.status == "activated"
        assert "workflow-draft" in session.active_skills

        archived = authoring.archive("workflow-draft", actor_key="admin:1")
        assert archived.status == "archived"
        assert archived.detail is not None
        assert archived.detail.runtime_available is False

        session.active_skills = []
        unavailable_again = activation.begin_activate(session, actor_key=actor_key, skill_name="workflow-draft")
        assert unavailable_again.status == "not_published"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_runtime_skill_create_draft_returns_safe_validation_messages(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        authoring = composition.workflows().runtime_skills.authoring

        invalid = authoring.create_draft("Bad Name", owner_actor=actor_key)
        duplicate = authoring.create_draft("existing-skill", owner_actor=actor_key)
        second_duplicate = authoring.create_draft("existing-skill", owner_actor=actor_key)

        assert invalid.ok is False
        assert "lowercase letters" in invalid.message
        assert "digits" in invalid.message
        assert "hyphens" in invalid.message
        assert "Bad Name" not in invalid.message
        assert duplicate.ok is True
        assert second_duplicate.ok is False
        assert second_duplicate.message == "Skill 'existing-skill' already exists."
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_runtime_skill_draft_package_roundtrip_and_validation(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        authoring = composition.workflows().runtime_skills.authoring

        created = authoring.create_draft("package-skill", owner_actor=actor_key)
        assert created.ok is True

        invalid = authoring.edit_draft(
            "package-skill",
            actor_key=actor_key,
            display_name="",
            body="",
            requirements=(
                SkillRequirement(key="API_TOKEN", prompt=""),
            ),
            files=(
                SkillFileRecord(relative_path="../bad.sh", content_text="echo nope", executable=True),
            ),
        )
        assert invalid.ok is False
        assert invalid.detail is not None
        assert any(item.field_path == "display_name" for item in invalid.detail.validation_problems)
        assert any(item.field_path == "body" for item in invalid.detail.validation_problems)
        assert any(item.field_path == "requirements[0].prompt" for item in invalid.detail.validation_problems)
        assert any(item.field_path == "files[0].relative_path" for item in invalid.detail.validation_problems)

        edited = authoring.edit_draft(
            "package-skill",
            actor_key=actor_key,
            display_name="Package Skill",
            description="Structured package draft",
            body="Use the package-aware draft.",
            requirements=(
                SkillRequirement(key="API_TOKEN", prompt="Enter API token"),
            ),
            provider_config=ProviderConfigRecord({"claude": {"allowed_tools": ["bash"]}}),
            files=(
                SkillFileRecord(relative_path="helper.sh", content_text="echo ready", executable=True),
            ),
            changelog="package update",
        )
        assert edited.ok is True
        assert edited.detail is not None
        assert edited.detail.publish_ready is True
        assert edited.detail.display_name == "Package Skill"
        assert edited.detail.requirements[0].key == "API_TOKEN"
        assert edited.detail.provider_config["claude"]["allowed_tools"] == ["bash"]
        assert edited.detail.files[0].relative_path == "helper.sh"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_lifecycle_workflow_separates_draft_and_runtime(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        flows = composition.workflows()
        management = flows.provider_guidance.management
        preview = flows.provider_guidance.preview

        original = preview.preview("claude", role="", active_skills=[], compact_mode=False)
        assert "Claude Runtime Guidance" in original.effective_guidance

        edited = management.edit_draft(
            "claude",
            actor_key="admin:1",
            body="# Edited Guidance\n\nUse the edited workflow guidance.",
        )
        assert edited.status == "draft_saved"
        assert edited.detail is not None
        assert edited.detail.lifecycle_status == "draft"
        assert edited.detail.runtime_available is True

        preview_before_publish = preview.preview("claude", role="", active_skills=[], compact_mode=False)
        assert "Edited Guidance" not in preview_before_publish.effective_guidance

        submitted = management.submit("claude", actor_key="admin:1")
        assert submitted.status == "submitted"
        approved = management.approve("claude", actor_key="admin:2")
        assert approved.status == "approved"
        published = management.publish("claude", actor_key="admin:2")
        assert published.status == "published"

        preview_after_publish = preview.preview("claude", role="", active_skills=[], compact_mode=False)
        assert "Edited Guidance" in preview_after_publish.effective_guidance

        archived = management.archive("claude", actor_key="admin:2")
        assert archived.status == "archived"
        preview_after_archive = preview.preview("claude", role="", active_skills=[], compact_mode=False)
        assert preview_after_archive.effective_guidance == ""
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_runtime_skill_lifecycle_replay_and_repair_paths(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        flows = composition.workflows()
        authoring = flows.runtime_skills.authoring
        approval = flows.runtime_skills.approval
        store = get_content_store()

        authoring.create_draft("repair-skill", owner_actor=actor_key)
        authoring.edit_draft(
            "repair-skill",
            actor_key=actor_key,
            body="Repair me.",
            changelog="initial",
        )

        submitted = authoring.submit("repair-skill", actor_key=actor_key)
        assert submitted.status == "submitted"
        submitted_again = authoring.submit("repair-skill", actor_key=actor_key)
        assert submitted_again.status == "already_submitted"
        assert sum(1 for item in submitted_again.detail.approvals if item.action == "submitted") == 1

        approved = approval.approve("repair-skill", actor_key="admin:1")
        assert approved.status == "approved"
        approved_again = approval.approve("repair-skill", actor_key="admin:1")
        assert approved_again.status == "already_approved"
        assert sum(1 for item in approved_again.detail.approvals if item.action == "approved") == 1

        track = content_store_mod.get_content_store().resolve_skill("repair-skill")
        assert track is not None
        store.set_skill_revision_status("repair-skill", track.active_revision_id, "published")

        repaired_publish = authoring.publish("repair-skill", actor_key="admin:1")
        assert repaired_publish.status == "published"
        assert repaired_publish.detail is not None
        assert repaired_publish.detail.runtime_available is True
        assert repaired_publish.detail.published_revision_id == repaired_publish.detail.active_revision_id
        assert sum(1 for item in repaired_publish.detail.approvals if item.action == "published") == 1

        store.set_skill_revision_status("repair-skill", track.active_revision_id, "archived")
        repaired_archive = authoring.archive("repair-skill", actor_key="admin:1")
        assert repaired_archive.status == "archived"
        assert repaired_archive.detail is not None
        assert repaired_archive.detail.runtime_available is False
        assert repaired_archive.detail.published_revision_id == ""
        assert sum(1 for item in repaired_archive.detail.approvals if item.action == "archived") == 1

        archived_again = authoring.archive("repair-skill", actor_key="admin:1")
        assert archived_again.status == "already_archived"
        assert sum(1 for item in archived_again.detail.approvals if item.action == "archived") == 1
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_lifecycle_replay_and_repair_paths(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        management = composition.workflows().provider_guidance.management
        store = get_content_store()

        management.edit_draft(
            "claude",
            actor_key="admin:1",
            body="# Replay Guidance\n\nUse the repaired path.",
        )

        submitted = management.submit("claude", actor_key="admin:1")
        assert submitted.status == "submitted"
        submitted_again = management.submit("claude", actor_key="admin:1")
        assert submitted_again.status == "already_submitted"
        assert sum(1 for item in submitted_again.detail.approvals if item.action == "submitted") == 1

        approved = management.approve("claude", actor_key="admin:2")
        assert approved.status == "approved"
        approved_again = management.approve("claude", actor_key="admin:2")
        assert approved_again.status == "already_approved"
        assert sum(1 for item in approved_again.detail.approvals if item.action == "approved") == 1

        detail = management.detail("claude")
        assert detail is not None
        store.set_provider_guidance_revision_status("claude", detail.active_revision_id, "published")

        repaired_publish = management.publish("claude", actor_key="admin:2")
        assert repaired_publish.status == "published"
        assert repaired_publish.detail is not None
        assert repaired_publish.detail.published_revision_id == repaired_publish.detail.active_revision_id
        assert sum(1 for item in repaired_publish.detail.approvals if item.action == "published") == 1
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_sqlite_atomic_skill_transition_rolls_back_when_insert_fails(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(7)
        authoring = composition.workflows().runtime_skills.authoring
        store = get_content_store()

        authoring.create_draft("atomic-skill", owner_actor=actor_key)
        authoring.edit_draft("atomic-skill", actor_key=actor_key, body="atomic")
        detail = authoring.detail("atomic-skill")
        assert detail is not None

        with pytest.raises((sqlite3.IntegrityError, TypeError)):
            store.apply_skill_lifecycle_transition(
                "atomic-skill",
                detail.active_revision_id,
                set_status="review",
                approval_action="submitted",
                actor=None,
            )

        after = authoring.detail("atomic-skill")
        assert after is not None
        assert after.lifecycle_status == "draft"
        assert after.approvals == ()
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_postgres_atomic_transition_rolls_back_on_failure(monkeypatch):
    class FakeCursor:
        def __init__(self):
            self.queries: list[tuple[str, tuple | None]] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "INSERT INTO" in sql and "skill_approval_records" in sql:
                raise RuntimeError("boom")

    class FakeConn:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.committed = False
            self.rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self, **kwargs):
            return self.cursor_obj

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    store = PostgresContentStore("postgresql://unused")
    fake_conn = FakeConn()

    monkeypatch.setattr(store, "_custom_track_row", lambda slug: {"track_id": "track-1"})

    def fake_connect():
        return fake_conn

    monkeypatch.setattr(store, "_connect", fake_connect)

    with pytest.raises(RuntimeError, match="boom"):
        store.apply_skill_lifecycle_transition(
            "atomic-skill",
            "rev-1",
            set_status="review",
            approval_action="submitted",
            actor="admin:1",
        )

    assert fake_conn.committed is False
    assert fake_conn.rolled_back is True
