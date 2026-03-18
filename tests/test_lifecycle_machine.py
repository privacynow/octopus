"""Lifecycle state-machine tests."""

from app.workflows.lifecycle_machine import LifecycleSnapshot, decide_lifecycle_action


def test_submit_from_draft_enters_review_and_records_submission():
    decision = decide_lifecycle_action(
        LifecycleSnapshot(
            revision_status="draft",
            latest_action="",
            has_published_revision=False,
            published_revision_matches_active=False,
        ),
        "submit",
    )

    assert decision.status == "submitted"
    assert decision.ok is True
    assert decision.effects.set_status == "review"
    assert decision.effects.approval_action == "submitted"


def test_duplicate_submit_is_idempotent():
    decision = decide_lifecycle_action(
        LifecycleSnapshot(
            revision_status="review",
            latest_action="submitted",
            has_published_revision=False,
            published_revision_matches_active=False,
        ),
        "submit",
    )

    assert decision.status == "already_submitted"
    assert decision.ok is True
    assert decision.effects.approval_action is None


def test_publish_repairs_partial_transition_when_status_already_changed():
    decision = decide_lifecycle_action(
        LifecycleSnapshot(
            revision_status="published",
            latest_action="approved",
            has_published_revision=False,
            published_revision_matches_active=False,
        ),
        "publish",
    )

    assert decision.status == "published"
    assert decision.ok is True
    assert decision.effects.set_status is None
    assert decision.effects.published_pointer == "set_active"
    assert decision.effects.approval_action == "published"


def test_reject_repairs_interrupted_rejection_when_draft_was_already_written():
    decision = decide_lifecycle_action(
        LifecycleSnapshot(
            revision_status="draft",
            latest_action="approved",
            has_published_revision=False,
            published_revision_matches_active=False,
        ),
        "reject",
    )

    assert decision.status == "rejected"
    assert decision.ok is True
    assert decision.effects.set_status is None
    assert decision.effects.approval_action == "rejected"


def test_archive_repairs_pointer_and_history_when_already_archived():
    decision = decide_lifecycle_action(
        LifecycleSnapshot(
            revision_status="archived",
            latest_action="published",
            has_published_revision=True,
            published_revision_matches_active=True,
        ),
        "archive",
    )

    assert decision.status == "archived"
    assert decision.ok is True
    assert decision.effects.set_status is None
    assert decision.effects.published_pointer == "clear"
    assert decision.effects.approval_action == "archived"
