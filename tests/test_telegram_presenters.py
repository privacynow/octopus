from telegram.constants import ParseMode

from octopus_sdk.work_queue import UserAccessRecord
from app.presentation.telegram import (
    access_overrides_message,
    admin_sessions_summary_message,
    approval_prompt,
    retry_prompt,
    compact_mode_status,
    compact_reply_blockquote_message,
    compact_reply_button_message,
    collapsed_response_message,
    conversation_role_current_message,
    delegation_plan_message,
    discover_degraded_message,
    discover_failed_message,
    discover_results_message,
    extract_summary,
    formatted_reply_messages,
    guidance_admin_only_message,
    ingress_setup_prompt_message,
    main_help_message,
    pending_plain_outcome_message,
    provider_guidance_history_message,
    provider_guidance_mutation_message,
    provider_guidance_preview_message,
    recovery_notice_markup,
    pending_html_outcome_message,
    raw_missing_message,
    raw_usage_message,
    runtime_skill_active_summary_message,
    runtime_skill_history_message,
    runtime_skill_setup_started_message,
    session_overview_message,
    settings_overview,
    skill_add_confirmation,
    welcome_message,
)
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleApproval,
    ProviderGuidanceLifecycleDetail,
    ProviderGuidanceLifecycleRevision,
    ProviderGuidancePreview,
)
from octopus_sdk.providers import ProviderConfigRecord
from octopus_sdk.sessions import DelegatedTask, PendingDelegation
from octopus_sdk.workflows.delegation import DelegationTargetPreview
from octopus_sdk.workflows.skills import (
    RuntimeSkillLifecycleApproval,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillLifecycleRevision,
)


def test_approval_prompt_renders_expected_buttons():
    rendered = approval_prompt()

    assert rendered.text
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "approval_approve"
    assert rendered.reply_markup.inline_keyboard[0][1].callback_data == "approval_reject"


def test_pending_prompts_render_request_bound_callback_tokens():
    approval = approval_prompt("abc123")
    retry = retry_prompt((), "def456")

    assert approval.reply_markup.inline_keyboard[0][0].callback_data == "approval_approve:abc123"
    assert approval.reply_markup.inline_keyboard[0][1].callback_data == "approval_reject:abc123"
    assert retry.reply_markup.inline_keyboard[0][0].callback_data == "retry_allow:def456"
    assert retry.reply_markup.inline_keyboard[0][1].callback_data == "retry_skip:def456"


def test_collapsed_response_message_renders_expand_button():
    rendered = collapsed_response_message("<b>Summary</b>", 42, 7)

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.disable_web_page_preview is True
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "expand:42:7"


def test_settings_overview_renders_channel_buttons():
    rendered = settings_overview(
        project_display="backend",
        working_dir="/tmp/backend",
        policy="edit",
        compact=True,
        approval="off",
        model_display="fast",
        effective_model="gpt-5.4",
        trust_public=False,
        project_names=["backend", "frontend"],
        current_project="backend",
        model_available=["fast", "best"],
        has_model_override=True,
        has_policy_override=True,
    )

    callbacks = [
        button.callback_data
        for row in rendered.reply_markup.inline_keyboard
        for button in row
    ]
    assert "setting_project:backend" in callbacks
    assert "setting_policy:edit" in callbacks
    assert "setting_compact:on" in callbacks
    assert "setting_approval:off" in callbacks


def test_skill_add_confirmation_renders_expected_buttons():
    rendered = skill_add_confirmation("helper", 9000, 8000)

    assert rendered.parse_mode == ParseMode.HTML
    assert "helper" in rendered.text
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "skill_add_confirm:helper"
    assert rendered.reply_markup.inline_keyboard[0][1].callback_data == "skill_add_cancel"


def test_recovery_notice_markup_renders_expected_buttons():
    markup = recovery_notice_markup("tg:601", "Run again", "Skip")

    assert markup.inline_keyboard[0][0].callback_data == "recovery_replay:tg:601"
    assert markup.inline_keyboard[0][1].callback_data == "recovery_discard:tg:601"


def test_provider_guidance_preview_message_renders_expected_html():
    preview = ProviderGuidancePreview(
        provider="claude",
        effective_guidance="Use careful guidance",
        system_prompt="",
        capability_summary="",
        provider_config=ProviderConfigRecord(),
        prompt_weight=1,
    )

    rendered = provider_guidance_preview_message("claude", preview)

    assert rendered.parse_mode == ParseMode.HTML
    assert "<b>claude</b>" in rendered.text
    assert "<pre>Use careful guidance</pre>" in rendered.text


def test_provider_guidance_history_message_renders_revisions_and_approvals():
    detail = ProviderGuidanceLifecycleDetail(
        provider="claude",
        scope_kind="system",
        scope_key="",
        body="body",
        lifecycle_status="published",
        active_revision_id="rev-current",
        published_revision_id="rev-current",
        runtime_available=True,
        revisions=(
            ProviderGuidanceLifecycleRevision(
                revision_id="rev-current",
                status="published",
                created_by="admin",
                created_at="2026-03-18T00:00:00+00:00",
                is_published=True,
            ),
        ),
        approvals=(
            ProviderGuidanceLifecycleApproval(
                revision_id="rev-current",
                action="approved",
                actor="admin",
                note="ship it",
                created_at="2026-03-18T00:00:00+00:00",
            ),
        ),
    )

    rendered = provider_guidance_history_message("claude", detail)

    assert rendered.parse_mode == ParseMode.HTML
    assert "Status: <code>published</code>" in rendered.text
    assert "approved by admin" in rendered.text
    assert "[published]" in rendered.text


def test_provider_guidance_mutation_message_escapes_html():
    rendered = provider_guidance_mutation_message("<saved>")

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.text == "&lt;saved&gt;"


def test_discover_degraded_message_uses_safe_error_summary():
    rendered = discover_degraded_message("registry_unreachable")

    assert rendered.parse_mode is None
    assert "could not be reached" in rendered.text.lower()
    assert "registry_unreachable" not in rendered.text


def test_discover_failed_message_does_not_echo_unknown_text():
    rendered = discover_failed_message("<html>secret stack trace</html>")

    assert rendered.parse_mode is None
    assert "Agent discovery failed." in rendered.text
    assert "request failed" in rendered.text.lower()
    assert "stack trace" not in rendered.text.lower()


def test_conversation_role_current_message_renders_expected_html():
    rendered = conversation_role_current_message("Python expert")

    assert rendered.parse_mode == ParseMode.HTML
    assert "<code>Python expert</code>" in rendered.text


def test_pending_html_outcome_message_renders_expected_html():
    rendered = pending_html_outcome_message("<b>Replay queued</b>")

    assert rendered.parse_mode == ParseMode.HTML
    assert "<b>" in rendered.text
    assert "queued" in rendered.text.lower()


def test_ingress_setup_prompt_message_renders_expected_html():
    rendered = ingress_setup_prompt_message(
        "planner",
        {"kind": "token", "key": "API_TOKEN", "prompt": "Enter API_TOKEN"},
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "planner" in rendered.text
    assert "API_TOKEN" in rendered.text


def test_formatted_reply_messages_render_html_chunks():
    rendered = formatted_reply_messages("**hello**")

    assert rendered
    assert all(item.parse_mode == ParseMode.HTML for item in rendered)
    assert any("hello" in item.text for item in rendered)


def test_compact_reply_blockquote_message_renders_expandable_detail_when_short_enough():
    rendered = compact_reply_blockquote_message(
        "Summary line one\nSummary line two\nSummary line three\nSummary line four\nDetail line one\nDetail line two"
    )

    assert rendered is not None
    assert rendered.parse_mode == ParseMode.HTML
    assert "<blockquote expandable>" in rendered.text
    assert "Detail line one" in rendered.text


def test_compact_reply_button_message_renders_expand_callback():
    rendered = compact_reply_button_message("Summary line\n\nDetail line", 42, 7)

    assert rendered.parse_mode == ParseMode.HTML
    assert rendered.reply_markup is not None
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "expand:42:7"


def test_extract_summary_splits_at_line_boundary():
    summary, rest = extract_summary(
        "Line one\nLine two\nLine three\nLine four\nLine five\nLine six",
        max_lines=3,
    )

    assert "Line one" in summary
    assert "Line three" in summary
    assert "Line five" in rest


def test_delegation_plan_message_renders_expected_html():
    rendered = delegation_plan_message(
        PendingDelegation(
            conversation_ref="conv-1",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    title="Review docs",
                    target_agent_id="agent-reviewer",
                ),
            ],
        ),
        previews=[
            DelegationTargetPreview(
                routed_task_id="task-1",
                status="resolved",
                authority_ref="registry:default",
            )
        ],
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Delegation plan" in rendered.text
    assert "Review docs" in rendered.text
    assert "agent-reviewer" in rendered.text
    assert "ready via" in rendered.text
    assert "registry:default" in rendered.text


def test_delegation_plan_message_marks_unavailable_targets_before_approval():
    rendered = delegation_plan_message(
        PendingDelegation(
            conversation_ref="conv-1",
            tasks=[
                DelegatedTask(
                    routed_task_id="task-1",
                    title="Review docs",
                    target_agent_id="agent-reviewer",
                ),
            ],
        ),
        previews=[
            DelegationTargetPreview(
                routed_task_id="task-1",
                status="unavailable",
                detail="The agent registry could not be reached.",
            )
        ],
    )

    assert "registry unavailable" in rendered.text.lower()
    assert "could not be reached" in rendered.text.lower()
    assert "approval will check ownership again" in rendered.text.lower()


def test_welcome_message_mentions_current_modes():
    rendered = welcome_message(approval_mode="on", compact_mode=True)

    assert "Approval mode is on" in rendered.text
    assert "Compact mode is on" in rendered.text


def test_raw_messages_render_expected_text():
    assert "Usage: /raw [N]" in raw_usage_message().text
    assert raw_missing_message().text == "No stored responses found."


def test_main_help_message_renders_expected_sections():
    rendered = main_help_message(
        instance="prod",
        provider_name="Claude",
        has_model_profiles=True,
        agent_mode="registry",
        is_public=False,
        has_projects=True,
        is_admin=True,
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Agent Bot" in rendered.text
    assert "/discover" in rendered.text
    assert "/admin sessions" in rendered.text


def test_session_overview_message_renders_expected_html():
    rendered = session_overview_message(
        provider_name="claude",
        instance="prod",
        working_dir_display="/tmp/project",
        file_policy="edit",
        model_profile="fast",
        model_id="gpt-5.4",
        compact_display="on",
        prompt_weight="~123 chars",
        session_label="Session",
        session_value="abc123…",
        session_active="True",
        approval_mode="on",
        approval_source="chat override",
        role_display="Python expert",
        skills_display="planner, reviewer",
        pending="no",
        trust_public=False,
        session_commands=["/settings", "/project"],
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Working dir" in rendered.text
    assert "Python expert" in rendered.text
    assert "/settings or /project" in rendered.text


def test_discover_results_message_renders_matching_agents():
    rendered = discover_results_message(
        [
            {
                "authority_ref": "registry:prod",
                "display_name": "Reviewer",
                "role": "developer",
                "connectivity_state": "connected",
                "current_capacity": 1,
                "max_capacity": 4,
                "routing_skills": ["python", "review"],
                "tags": ["backend"],
                "description": "Reviews code changes.",
            }
        ]
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Matching agents" in rendered.text
    assert "Reviewer" in rendered.text
    assert "registry:prod" in rendered.text
    assert "Routing skills" in rendered.text
    assert "backend" in rendered.text


def test_access_overrides_message_renders_expected_html():
    rendered = access_overrides_message(
        [
            UserAccessRecord(actor_key="telegram:42", access="allowed", reason="trusted"),
            UserAccessRecord(actor_key="telegram:99", access="blocked", reason=""),
        ]
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Access overrides" in rendered.text
    assert "telegram:42" in rendered.text
    assert "allowed" in rendered.text


def test_admin_sessions_summary_message_renders_expected_html():
    rendered = admin_sessions_summary_message(
        total=3,
        pending=1,
        setup=1,
        top_skills=[("planner", 2)],
        most_recent_key="telegram:123",
        most_recent_updated_at="2026-03-18T00:00:00+00:00",
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "Sessions: 3" in rendered.text
    assert "planner: 2" in rendered.text
    assert "telegram:123" in rendered.text


def test_compact_mode_status_renders_toggle_buttons():
    rendered = compact_mode_status(True)

    assert rendered.parse_mode == ParseMode.HTML
    assert "Compact mode is <b>on</b>." in rendered.text
    assert rendered.reply_markup.inline_keyboard[0][0].callback_data == "setting_compact:on"
    assert rendered.reply_markup.inline_keyboard[0][1].callback_data == "setting_compact:off"


def test_runtime_skill_active_summary_message_renders_expected_html():
    rendered = runtime_skill_active_summary_message(["Planner", "Reviewer"], 7)

    assert rendered.parse_mode == ParseMode.HTML
    assert "<b>Active in this conversation (2):</b>" in rendered.text
    assert "Planner" in rendered.text
    assert "Available on this bot: 7 skill(s)" in rendered.text


def test_runtime_skill_history_message_renders_revisions_and_approvals():
    detail = RuntimeSkillLifecycleDetail(
        name="release-notes",
        display_name="Release Notes",
        description="Summarize releases",
        source_label="Custom",
        visibility="private",
        body="body",
        lifecycle_status="published",
        active_revision_id="rev-current",
        published_revision_id="rev-current",
        runtime_available=True,
        revisions=(
            RuntimeSkillLifecycleRevision(
                revision_id="rev-current",
                version_label="v1",
                status="published",
                changelog="First version",
                created_by="owner",
                created_at="2026-03-18T00:00:00+00:00",
                is_published=True,
            ),
        ),
        approvals=(
            RuntimeSkillLifecycleApproval(
                revision_id="rev-current",
                action="approved",
                actor="admin",
                note="ship it",
                created_at="2026-03-18T00:00:00+00:00",
            ),
        ),
    )

    rendered = runtime_skill_history_message(detail)

    assert rendered.parse_mode == ParseMode.HTML
    assert "Status: <code>published</code>" in rendered.text
    assert "approved by admin" in rendered.text
    assert "[published]" in rendered.text


def test_guidance_admin_only_message_renders_action_name():
    rendered = guidance_admin_only_message("approve")

    assert "admin" in rendered.text.lower()
    assert "approve" in rendered.text.lower()
    assert "provider guidance" in rendered.text.lower()


def test_runtime_skill_setup_started_message_renders_requirement_prompt():
    rendered = runtime_skill_setup_started_message(
        "helper",
        {"kind": "token", "key": "API_TOKEN", "prompt": "Enter API token"},
    )

    assert rendered.parse_mode == ParseMode.HTML
    assert "helper" in rendered.text
    assert "Enter API token" in rendered.text


def test_pending_plain_outcome_message_renders_plain_text():
    rendered = pending_plain_outcome_message("rejected")

    assert rendered.parse_mode is None
    assert rendered.text == "rejected"
