"""Centralized user-facing copy for progress, recovery, approval, and trust clarity.

Milestone D: one small authoritative home for messages touched by this milestone.
Handlers and progress rendering import from here. No framework; no indirection
for its own sake. Preserves semantic distinctions (interrupted vs discarded vs
already handled, expired vs context-changed, etc.) while keeping wording plain.
"""

from __future__ import annotations

import html as _html

# ---------------------------------------------------------------------------
# Recovery / interruption / replay / discard
# ---------------------------------------------------------------------------

def recovery_notice_intro() -> str:
    """Main line for the interruption notice (before request preview)."""
    return "Your previous request was interrupted before it could finish."


def recovery_notice_prompt() -> str:
    """Question after the request preview."""
    return "You can run it again or skip it."


def recovery_button_run_again() -> str:
    """Label for the replay button."""
    return "Run again"


def recovery_button_skip() -> str:
    """Label for the discard button."""
    return "Skip"


def recovery_already_handled() -> str:
    """Toast when user taps replay/discard but the recovery was already handled."""
    return "This request was already handled."


def recovery_discarded_confirm() -> str:
    """Toast after user chooses discard."""
    return "Request skipped."


def recovery_discarded_edit() -> str:
    """Edit the notice message after discard (HTML)."""
    return "<i>Request skipped.</i>"


def recovery_replaying_toast() -> str:
    """Toast when user taps run again."""
    return "Running your request again…"


def recovery_blocked_replay_edit() -> str:
    """Edit when replay is blocked because another request is in progress (HTML)."""
    return "<i>Another request is in progress. Try again in a moment.</i>"


def recovery_already_handled_edit() -> str:
    """Edit when race: already handled between check and reclaim (HTML)."""
    return "<i>This request was already handled.</i>"


def recovery_payload_missing_edit() -> str:
    """Edit when original request payload cannot be retrieved (HTML)."""
    return "<i>Could not find the original request.</i>"


def recovery_replay_failed_edit() -> str:
    """Edit when replay fails (deserialize or wrong type) (HTML)."""
    return "<i>Could not run this request again.</i>"


def recovery_replaying_edit() -> str:
    """Edit to show replay in progress (HTML)."""
    return "<i>Running your request again…</i>"


def recovery_replay_failed_message() -> str:
    """New message when replay execution fails."""
    return "Running your request again failed. Please send your message again."


def recovery_orphaned_command(detail: str) -> str:
    """Message for orphaned command/callback that cannot be replayed (HTML). detail e.g. '/start' or 'a button action'."""
    return f"<i>Your {_html.escape(detail)} was interrupted and could not be run again.</i>"


def recovery_invalid_action() -> str:
    """Toast for invalid recovery callback data."""
    return "Invalid action."


def recovery_unknown_action() -> str:
    """Toast for unknown recovery action."""
    return "Unknown action."


def recovery_error_try_again() -> str:
    """Generic error toast (transport/state)."""
    return "Something went wrong. Please try again or contact support."


def recovery_error_discard_try_again() -> str:
    """Toast when discard hits corruption."""
    return "Something went wrong; please try again or contact support."


# ---------------------------------------------------------------------------
# Approval / retry / stale / expired
# ---------------------------------------------------------------------------

def approval_preparing() -> str:
    """Status while preflight is running."""
    return "Preparing your plan…"


def approval_required() -> str:
    """Status when plan is ready and waiting for user."""
    return "Review the plan below, then approve or reject."


def approval_plan_question() -> str:
    """Prompt with approve/reject buttons."""
    return "Approve this plan?"


def approval_button_approve() -> str:
    """Label for approve button."""
    return "Approve plan"


def approval_button_reject() -> str:
    """Label for reject button."""
    return "Reject plan"


def approval_already_waiting() -> str:
    """When user sends a message but an approval is already pending."""
    return "A plan is already waiting. Use /approve or /reject first."


def approval_no_pending_approve() -> str:
    """When user runs /approve but there is no pending request."""
    return "No pending request to approve."


def approval_no_pending_reject() -> str:
    """When user runs /reject but there is no pending request."""
    return "No pending request to reject."


def approval_rejected() -> str:
    """After user rejects."""
    return "Request rejected."


def approval_timeout() -> str:
    """When preflight times out."""
    return "Preparing the plan took too long."


def approval_check_failed_prefix() -> str:
    """Prefix before provider error when preflight fails."""
    return "Plan check failed:"


def approval_request_no_longer_valid() -> str:
    """Fallback when approve/reject path says request is no longer valid."""
    return "This request is no longer valid."


def approval_expired(minutes: int) -> str:
    """When pending request has expired (created N minutes ago)."""
    return f"This request has expired (it was created {minutes} minutes ago). Please send your message again."


def approval_expired_fallback() -> str:
    """Fallback if pending_expired returns None for expired."""
    return "This request has expired."


def approval_context_changed() -> str:
    """When execution context (role, skills, project, settings, etc.) changed since request was made.
    Must match the real invalidation rule (context hash), not only settings/project."""
    return "This request can't continue because the chat context changed. Please send your message again."


def retry_skip_confirmation() -> str:
    """Edit text when user chooses skip retry (clear retry without running again)."""
    return "Retry skipped. Nothing to run again."


def retry_nothing_pending() -> str:
    """When user triggers retry but no retry is waiting."""
    return "No retry is waiting."


def retry_permission_prompt() -> str:
    """Heading for denial/retry block (HTML)."""
    return "Permission needed"


def retry_grant_and_retry_question() -> str:
    """Question after listing denials."""
    return "Grant access and run again from the start?"


def retry_button_grant() -> str:
    """Label for grant & retry button."""
    return "Grant access & retry"


def retry_button_skip() -> str:
    """Label for skip retry button."""
    return "Skip retry"


# ---------------------------------------------------------------------------
# Progress (status line and renderer)
# ---------------------------------------------------------------------------

def progress_working() -> str:
    """Initial status when starting a fresh run."""
    return "Working…"


def progress_resuming() -> str:
    """Initial status when resuming a session."""
    return "Resuming…"


def progress_still_working(elapsed_seconds: int) -> str:
    """Heartbeat during long run (HTML)."""
    return f"<i>Still working… ({elapsed_seconds}s)</i>"


def progress_completed() -> str:
    """When run completed successfully."""
    return "Completed."


def progress_completed_with_blocked() -> str:
    """When run completed but some actions were blocked (denials)."""
    return "Completed, but some actions were blocked."


def progress_request_timed_out(seconds: int) -> str:
    """When request times out."""
    return f"Request timed out after {seconds} seconds."


def progress_session_not_resumed() -> str:
    """Appended when resume failed and we are starting fresh (HTML)."""
    return "\n\n<i>Session could not be resumed — your next message will start fresh.</i>"


# Progress renderer wording (provider-neutral; progress.py builds HTML and escapes)
def progress_thinking() -> str:
    return "Thinking…"


def progress_running_command() -> str:
    return "Running a command…"


def progress_running_command_with_command() -> str:
    return "Running a command:"


def progress_command_finished() -> str:
    return "Command finished."


def progress_command_finished_exit(exit_code: int) -> str:
    return f"Command finished (exit {exit_code}):"


def progress_output() -> str:
    return "Output:"


def progress_using_tool() -> str:
    return "Using tool:"


def progress_tool_finished() -> str:
    return "Tool finished:"


def progress_reply_received() -> str:
    return "Reply received."


def progress_draft_reply_received() -> str:
    return "Draft reply received:"


def progress_blocked() -> str:
    return "Blocked:"


def progress_action_blocked() -> str:
    return "Action blocked."


def progress_liveness() -> str:
    """Liveness text is passed through from provider; this is the wrapper meaning."""
    return ""  # caller uses event.detail


# ---------------------------------------------------------------------------
# Trust / profile / settings (restrictions and clarity)
# ---------------------------------------------------------------------------

def trust_not_authorized() -> str:
    """Toast when user is not allowed."""
    return "Not authorized."


def trust_command_not_available_public() -> str:
    """When public user uses a restricted command."""
    return "This command is not available in public mode."


def trust_file_policy_public() -> str:
    """When public user tries to change file policy."""
    return "File policy is managed by the operator in public mode."


def trust_project_public() -> str:
    """When public user tries to change project."""
    return "Project selection is managed by the operator in public mode."


def trust_unknown_or_restricted_profile(profile: str) -> str:
    """When model profile is unknown or not allowed for this user."""
    return f"Unknown or restricted profile: {_html.escape(profile)}"


def trust_model_profile_set(profile: str, model_id: str) -> str:
    """Confirmation when model profile is set (HTML)."""
    return f"Model profile set to <b>{_html.escape(profile)}</b> (<code>{_html.escape(model_id)}</code>)."


def trust_no_project_active() -> str:
    """When user clears project but none was set (HTML)."""
    return "No project is active."


def trust_project_cleared(default_dir: str) -> str:
    """When project is cleared (HTML)."""
    return f"Project cleared. Using instance default: <code>{_html.escape(default_dir)}</code>\nProvider session reset."


def trust_unknown_project(name: str) -> str:
    """When project name is unknown (HTML)."""
    return f"Unknown project: <code>{_html.escape(name)}</code>. Use /project list to see available projects."


def trust_already_using_project(name: str) -> str:
    """When already on that project (HTML)."""
    return f"Already using project <code>{_html.escape(name)}</code>."


def trust_switched_project(name: str, root: str) -> str:
    """When project is switched (HTML)."""
    return (
        f"Switched to project <code>{_html.escape(name)}</code>\n"
        f"Working dir: <code>{_html.escape(root)}</code>\n"
        "Provider session reset."
    )


def trust_file_policy_set(value: str) -> str:
    """When file policy is set (HTML)."""
    return f"File policy set to <code>{_html.escape(value)}</code>. Provider session reset."


def trust_no_model_profiles() -> str:
    """When no model profiles are configured."""
    return "No model profiles configured. Set BOT_MODEL_PROFILES."


def trust_unknown_profile_available(available: list[str]) -> str:
    """When profile argument is unknown. available is list of profile names."""
    return f"Unknown profile. Available: {', '.join(available)}"


def trust_settings_managed_public() -> str:
    """Line in /settings for public users."""
    return "Project selection and file policy are managed by the operator in public mode."


# ---------------------------------------------------------------------------
# Generic / shared
# ---------------------------------------------------------------------------

def generic_error_try_again() -> str:
    """Generic error for callbacks (e.g. transport corruption)."""
    return "Something went wrong. Please try again or contact support."


def queue_busy() -> str:
    """When user's request is queued because another is in progress. Do not tell them to try again — it will run next."""
    return "Another request is already running. Yours is queued and will run next."


def callback_wrong_user() -> str:
    """When callback was for another user (e.g. approval, clear credentials)."""
    return "This button is only for the person who started the request."


def nothing_to_cancel() -> str:
    """When user runs /cancel but there is nothing to cancel."""
    return "Nothing to cancel."


def cancel_pending_request() -> str:
    """When user cancels a pending approval/retry request."""
    return "Pending request cancelled."


def credential_setup_cancelled() -> str:
    """When user (or admin) cancels credential setup."""
    return "Credential setup cancelled."


def credential_setup_another_user_in_progress() -> str:
    """When user runs /cancel but another user's credential setup is in progress."""
    return "Another user's credential setup is in progress. Only they or an admin can cancel it."


def credential_clear_cancelled() -> str:
    """When user cancels the clear-credentials confirmation (callback)."""
    return "Credential clear cancelled."
