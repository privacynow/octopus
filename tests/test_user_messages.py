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
