"""Tests that Milestone D user-facing copy is present and consistent.

Pins key phrases so centralized wording is not accidentally removed or emptied.
All messages must remain provider-neutral and preserve semantic distinctions.
"""

import pytest

from app import user_messages as msg


# ---------------------------------------------------------------------------
# A. Recovery wording
# ---------------------------------------------------------------------------

def test_recovery_notice_intro_plain_and_actionable():
    text = msg.recovery_notice_intro()
    assert text
    assert "interrupted" in text.lower() or "request" in text.lower()


def test_recovery_buttons_run_again_and_skip():
    assert msg.recovery_button_run_again()
    assert msg.recovery_button_skip()
    assert "run" in msg.recovery_button_run_again().lower() or "again" in msg.recovery_button_run_again().lower()
    assert "skip" in msg.recovery_button_skip().lower()


def test_recovery_already_handled_and_discarded():
    assert "handled" in msg.recovery_already_handled().lower() or "already" in msg.recovery_already_handled().lower()
    assert "skip" in msg.recovery_discarded_confirm().lower() or "discard" in msg.recovery_discarded_confirm().lower()


def test_recovery_blocked_replay_editable():
    html = msg.recovery_blocked_replay_edit()
    assert "request" in html.lower() and ("progress" in html.lower() or "moment" in html.lower())


def test_recovery_replay_failed_message():
    text = msg.recovery_replay_failed_message()
    assert "again" in text.lower() or "send" in text.lower()
    assert "request" in text.lower() or "message" in text.lower()


# ---------------------------------------------------------------------------
# B. Approval / retry wording
# ---------------------------------------------------------------------------

def test_approval_required_and_plan_question():
    assert "review" in msg.approval_required().lower() or "approve" in msg.approval_required().lower()
    assert "plan" in msg.approval_plan_question().lower() or "approve" in msg.approval_plan_question().lower()


def test_approval_buttons_approve_reject():
    assert "approve" in msg.approval_button_approve().lower()
    assert "reject" in msg.approval_button_reject().lower()


def test_approval_expired_and_context_changed():
    assert "expired" in msg.approval_expired(5).lower() or "request" in msg.approval_expired(5).lower()
    # Stale/invalidated message must describe execution-context change, not only settings/project
    ctx_msg = msg.approval_context_changed()
    assert "context" in ctx_msg.lower()
    assert "changed" in ctx_msg.lower()
    assert "request" in ctx_msg.lower() or "can't continue" in ctx_msg.lower()
    assert "settings or project" not in ctx_msg.lower()


def test_retry_permission_prompt_and_grant():
    assert "permission" in msg.retry_permission_prompt().lower() or "access" in msg.retry_permission_prompt().lower()
    assert "grant" in msg.retry_button_grant().lower() or "retry" in msg.retry_button_grant().lower()


# ---------------------------------------------------------------------------
# C. Progress wording (provider-neutral)
# ---------------------------------------------------------------------------

def test_progress_thinking_and_working():
    assert "thinking" in msg.progress_thinking().lower()
    assert "work" in msg.progress_working().lower() or "working" in msg.progress_working().lower()


def test_progress_command_and_tool_labels():
    assert "command" in msg.progress_running_command().lower() or "running" in msg.progress_running_command().lower()
    assert "finished" in msg.progress_command_finished().lower() or "command" in msg.progress_command_finished().lower()
    assert "tool" in msg.progress_using_tool().lower()
    assert "blocked" in msg.progress_action_blocked().lower() or "blocked" in msg.progress_blocked().lower()


def test_progress_completed_and_still_working():
    assert "complet" in msg.progress_completed().lower()
    assert "work" in msg.progress_still_working(10).lower() or "working" in msg.progress_still_working(10).lower()


# ---------------------------------------------------------------------------
# D. Trust / profile wording
# ---------------------------------------------------------------------------

def test_trust_not_authorized_and_public_mode():
    assert "authorized" in msg.trust_not_authorized().lower() or "not" in msg.trust_not_authorized().lower()
    assert "public" in msg.trust_command_not_available_public().lower()


def test_trust_file_policy_and_project_public():
    assert "public" in msg.trust_file_policy_public().lower() or "managed" in msg.trust_file_policy_public().lower()
    assert "public" in msg.trust_project_public().lower() or "managed" in msg.trust_project_public().lower()


def test_trust_settings_managed_public():
    text = msg.trust_settings_managed_public()
    assert "project" in text.lower() or "policy" in text.lower()
    assert "public" in text.lower() or "managed" in text.lower()


def test_trust_model_profile_set_contains_placeholders():
    out = msg.trust_model_profile_set("fast", "claude-3-5-haiku")
    assert "fast" in out and "claude" in out


# ---------------------------------------------------------------------------
# E. Bucket C — no-op / busy / wrong-user clarity
# ---------------------------------------------------------------------------

def test_queue_busy_plain_and_actionable():
    """queue_busy: request is queued and will run next; must not tell user to try again."""
    text = msg.queue_busy()
    assert "queued" in text.lower()
    assert "try again" not in text.lower(), "queued request runs automatically; do not encourage resubmit"
    assert "request" in text.lower()
    # Implies waiting / automatic next execution
    assert "run" in text.lower() or "next" in text.lower() or "wait" in text.lower()


def test_callback_wrong_user_specific_to_button_owner():
    """callback_wrong_user: must indicate button is for the person who started the request."""
    text = msg.callback_wrong_user()
    assert "button" in text.lower() or "request" in text.lower()
    assert "person" in text.lower() or "started" in text.lower() or "another" in text.lower()


def test_nothing_to_cancel_and_cancel_pending_request():
    """No-op cancel paths: clear and distinct."""
    nothing = msg.nothing_to_cancel()
    cancelled = msg.cancel_pending_request()
    assert "cancel" in nothing.lower()
    assert "nothing" in nothing.lower() or "cancel" in nothing.lower()
    assert "pending" in cancelled.lower() or "cancelled" in cancelled.lower() or "request" in cancelled.lower()


def test_credential_cancellation_messages():
    """Bucket C Option 2: credential setup/clear cancellation centralized."""
    assert "credential" in msg.credential_setup_cancelled().lower()
    assert "cancelled" in msg.credential_setup_cancelled().lower() or "cancel" in msg.credential_setup_cancelled().lower()
    assert "another" in msg.credential_setup_another_user_in_progress().lower() or "admin" in msg.credential_setup_another_user_in_progress().lower()
    assert "clear" in msg.credential_clear_cancelled().lower() or "credential" in msg.credential_clear_cancelled().lower()


def test_settings_and_admin_messages_bucket_e():
    """Bucket E: settings/admin/usage messages centralized and non-empty."""
    assert "summarized" in msg.settings_compact_on_label().lower() or "long" in msg.settings_compact_on_label().lower()
    assert msg.settings_compact_off_label() == "off"
    assert "admin" in msg.admin_required().lower()
    assert "session" in msg.no_sessions_found().lower() or "found" in msg.no_sessions_found().lower()
    assert "conversation" in msg.no_conversation_to_export().lower() or "export" in msg.no_conversation_to_export().lower()
    assert "project" in msg.no_projects_configured().lower() or "BOT_PROJECTS" in msg.no_projects_configured()
    assert "/approval" in msg.approval_usage()
    assert "/policy" in msg.policy_usage()
