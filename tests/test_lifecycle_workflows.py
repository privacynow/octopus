"""Lifecycle workflow tests for custom skills and provider guidance."""

from pathlib import Path

import app.content_store as content_store_mod
from app.content_store import init_content_store_for_config
from app.credential_store import init_credential_store_for_config
from app.identity import telegram_actor_key
from app.session_state import session_from_dict
from app.storage import close_db, default_session, ensure_data_dirs
from app.workflows.provider_guidance.management import get_provider_guidance_management_use_cases
from app.workflows.provider_guidance.preview import get_provider_guidance_use_cases
from app.workflows.runtime_skills.activation import get_runtime_skill_activation_use_cases
from app.workflows.runtime_skills.approval import get_runtime_skill_approval_use_cases
from app.workflows.runtime_skills.authoring import get_runtime_skill_authoring_use_cases
from tests.support.config_support import make_config


def _init_runtime_content(tmp_path: Path):
    data_dir = tmp_path / "data"
    ensure_data_dirs(data_dir)
    content_store_mod.reset_for_test()
    cfg = make_config(data_dir=data_dir, registry_url="https://registry.example.test/index.json")
    init_content_store_for_config(cfg)
    init_credential_store_for_config(cfg)
    return cfg, data_dir


def test_runtime_skill_lifecycle_workflow_requires_publish_before_activation(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        actor_key = telegram_actor_key(42)
        authoring = get_runtime_skill_authoring_use_cases()
        approval = get_runtime_skill_approval_use_cases()
        activation = get_runtime_skill_activation_use_cases()

        created = authoring.create_draft("workflow-draft", owner_actor=actor_key)
        assert created.ok is True
        assert created.detail is not None
        assert created.detail.lifecycle_status == "draft"
        assert created.detail.runtime_available is False

        session = session_from_dict(default_session("claude", {"session_id": "test", "started": False}, "on"))
        unavailable = activation.begin_activate(session, user_id=actor_key, skill_name="workflow-draft")
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

        activated = activation.begin_activate(session, user_id=actor_key, skill_name="workflow-draft")
        assert activated.status == "activated"
        assert "workflow-draft" in session.active_skills

        archived = authoring.archive("workflow-draft", actor_key="admin:1")
        assert archived.status == "archived"
        assert archived.detail is not None
        assert archived.detail.runtime_available is False

        session.active_skills = []
        unavailable_again = activation.begin_activate(session, user_id=actor_key, skill_name="workflow-draft")
        assert unavailable_again.status == "not_published"
    finally:
        close_db(data_dir)
        content_store_mod.reset_for_test()


def test_provider_guidance_lifecycle_workflow_separates_draft_and_runtime(tmp_path: Path):
    _, data_dir = _init_runtime_content(tmp_path)
    try:
        management = get_provider_guidance_management_use_cases()
        preview = get_provider_guidance_use_cases()

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
