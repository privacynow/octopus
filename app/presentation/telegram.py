"""Telegram-channel presentation helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app import user_messages as _msg
from app.approvals import format_denials_html
from app.credential_flow import foreign_setup_message, format_credential_prompt
from app.formatting import md_to_telegram_html, split_html
from app.registry_errors import registry_error_summary
from octopus_sdk.sessions import PendingDelegation
from octopus_sdk.work_queue import UserAccessRecord
from octopus_sdk.workflows.delegation import DelegationTargetPreview
from octopus_sdk.workflows.provider_guidance import (
    ProviderGuidanceLifecycleDetail,
    ProviderGuidancePreview,
)
from octopus_sdk.workflows.skills import (
    RuntimeSkillCatalogItem,
    RuntimeSkillDetail,
    RuntimeSkillLifecycleDetail,
    RuntimeSkillMutationOutcome,
    RuntimeSkillSearchResults,
    RuntimeSkillUpdateStatusItem,
)


@dataclass(frozen=True)
class TelegramRenderedMessage:
    text: str
    parse_mode: str | None = None
    reply_markup: Any | None = None
    disable_web_page_preview: bool = False

    def kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.parse_mode is not None:
            kwargs["parse_mode"] = self.parse_mode
        if self.reply_markup is not None:
            kwargs["reply_markup"] = self.reply_markup
        if self.disable_web_page_preview:
            kwargs["disable_web_page_preview"] = True
        return kwargs


def extract_summary(text: str, max_lines: int = 4) -> tuple[str, str]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ("", "")
    summary_lines = lines[:max_lines]
    summary = "\n".join(summary_lines)
    detail = "\n".join(lines[max_lines:]).strip()
    return (summary, detail)


def _html_message(text: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=text, parse_mode=ParseMode.HTML)


def _escaped_html_message(text: str) -> TelegramRenderedMessage:
    return _html_message(html.escape(text))


_PENDING_CALLBACK_ACTIONS = frozenset({
    "approval_approve",
    "approval_reject",
    "retry_allow",
    "retry_skip",
})


def pending_callback_data(action: str, callback_token: str = "") -> str:
    if action not in _PENDING_CALLBACK_ACTIONS:
        raise ValueError(f"Unknown pending callback action: {action}")
    token = str(callback_token or "").strip()
    return f"{action}:{token}" if token else action


def parse_pending_callback_data(data: str) -> tuple[str, str] | None:
    text = str(data or "").strip()
    if text in _PENDING_CALLBACK_ACTIONS:
        return (text, "")
    action, sep, callback_token = text.partition(":")
    if not sep or action not in _PENDING_CALLBACK_ACTIONS:
        return None
    callback_token = callback_token.strip()
    if not callback_token:
        return None
    return (action, callback_token)


def retry_prompt(denials: Iterable[dict[str, Any]], callback_token: str = "") -> TelegramRenderedMessage:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "\u2705 " + _msg.retry_button_grant(),
            callback_data=pending_callback_data("retry_allow", callback_token),
        ),
        InlineKeyboardButton(
            "\u274c " + _msg.retry_button_skip(),
            callback_data=pending_callback_data("retry_skip", callback_token),
        ),
    ]])
    return TelegramRenderedMessage(
        text=(
            f"\u26a0\ufe0f <b>{_msg.retry_permission_prompt()}</b>\n"
            f"{format_denials_html(list(denials))}\n\n"
            f"{_msg.retry_grant_and_retry_question()}"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


def approval_prompt(callback_token: str = "") -> TelegramRenderedMessage:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "\u2705 " + _msg.approval_button_approve(),
            callback_data=pending_callback_data("approval_approve", callback_token),
        ),
        InlineKeyboardButton(
            "\u274c " + _msg.approval_button_reject(),
            callback_data=pending_callback_data("approval_reject", callback_token),
        ),
    ]])
    return TelegramRenderedMessage(
        text=_msg.approval_plan_question(),
        reply_markup=keyboard,
    )


def recovery_notice_markup(
    recovery_id: str,
    run_again_label: str,
    skip_label: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\u25b6\ufe0f " + run_again_label, callback_data=f"recovery_replay:{recovery_id}"),
        InlineKeyboardButton("\u2716 " + skip_label, callback_data=f"recovery_discard:{recovery_id}"),
    ]])


def delegation_reply_markup(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("\u25b6\ufe0f Approve delegation", callback_data=f"delegation_approve:{chat_id}"),
        InlineKeyboardButton("\u2716 Cancel", callback_data=f"delegation_cancel:{chat_id}"),
    ]])


def collapsed_response_message(formatted_summary: str, chat_id: int, slot: int) -> TelegramRenderedMessage:
    button_text = f"{formatted_summary}\n\n<i>Response truncated</i>"
    return TelegramRenderedMessage(
        text=button_text[:4000],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Show full answer", callback_data=f"expand:{chat_id}:{slot}"),
        ]]),
        disable_web_page_preview=True,
    )


def missing_collapsed_response_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="<i>Response no longer available (ring buffer rotated). Use /raw to check.</i>",
        parse_mode=ParseMode.HTML,
    )


def expanded_response_reply_markup(chat_id: int, slot: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Collapse", callback_data=f"collapse:{chat_id}:{slot}"),
    ]])


def _settings_model_buttons(
    available: list[str],
    current: str,
    *,
    has_explicit_override: bool,
) -> list[InlineKeyboardButton]:
    buttons = [
        InlineKeyboardButton(
            f"\u2705 {profile}" if profile == current else profile,
            callback_data=f"setting_model:{profile}",
        )
        for profile in available
    ]
    if has_explicit_override:
        buttons.append(InlineKeyboardButton("Inherit", callback_data="setting_model:inherit"))
    return buttons


def _settings_project_buttons(project_names: list[str], current_project: str | None) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    if not project_names:
        return rows
    row = [
        InlineKeyboardButton(
            f"\u2705 {name}" if name == current_project else name,
            callback_data=f"setting_project:{name}",
        )
        for name in project_names
    ]
    if row:
        rows.append(row)
    if current_project:
        rows.append([InlineKeyboardButton("Clear project", callback_data="setting_project:clear")])
    return rows


def _settings_policy_buttons(policy: str, *, has_explicit_override: bool) -> list[InlineKeyboardButton]:
    buttons = [
        InlineKeyboardButton(
            "\u2705 Read only" if policy == "inspect" else "Read only",
            callback_data="setting_policy:inspect",
        ),
        InlineKeyboardButton(
            "\u2705 Read & write" if policy == "edit" else "Read & write",
            callback_data="setting_policy:edit",
        ),
    ]
    if has_explicit_override:
        buttons.append(InlineKeyboardButton("Inherit", callback_data="setting_policy:inherit"))
    return buttons


def _settings_compact_buttons(compact: bool) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            "\u2705 Short answers" if compact else "Short answers",
            callback_data="setting_compact:on",
        ),
        InlineKeyboardButton(
            "\u2705 Full answers" if not compact else "Full answers",
            callback_data="setting_compact:off",
        ),
    ]


def _settings_approval_buttons(approval: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            "\u2705 Review first" if approval == "on" else "Review first",
            callback_data="setting_approval:on",
        ),
        InlineKeyboardButton(
            "\u2705 Run immediately" if approval == "off" else "Run immediately",
            callback_data="setting_approval:off",
        ),
    ]


def approval_mode_status(mode: str, source: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=f"Approval mode is <b>{mode}</b> ({source}).",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([_settings_approval_buttons(mode)]),
    )


def compact_mode_status(current: bool) -> TelegramRenderedMessage:
    state = "on" if current else "off"
    return TelegramRenderedMessage(
        text=f"Compact mode is <b>{state}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([_settings_compact_buttons(current)]),
    )


def model_profile_status(
    available: list[str],
    current: str,
    effective_model: str,
    *,
    has_explicit_override: bool,
) -> TelegramRenderedMessage:
    text = (
        f"Model profile: <b>{html.escape(current)}</b>\n"
        f"Effective model: <code>{html.escape(effective_model)}</code>"
    )
    buttons = _settings_model_buttons(
        available,
        current,
        has_explicit_override=has_explicit_override,
    )
    if buttons:
        text += "\n\n" + _msg.model_choose_profile_hint()
        return TelegramRenderedMessage(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
    return TelegramRenderedMessage(text=text, parse_mode=ParseMode.HTML)


def project_status(project_names: list[str], current_project: str | None, working_dir: str) -> TelegramRenderedMessage:
    project_label = current_project or "No project"
    lines = [
        f"Project: <b>{html.escape(project_label)}</b>",
        f"Working dir: <code>{html.escape(working_dir)}</code>",
        _msg.project_use_buttons_or_list_hint(),
    ]
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(_settings_project_buttons(project_names, current_project)),
    )


def settings_overview(
    *,
    project_display: str,
    working_dir: str,
    policy: str,
    compact: bool,
    approval: str,
    model_display: str,
    effective_model: str,
    trust_public: bool,
    project_names: list[str],
    current_project: str | None,
    model_available: list[str],
    has_model_override: bool,
    has_policy_override: bool,
) -> TelegramRenderedMessage:
    compact_label = "on" if compact else "off"
    lines = [
        "<b>Chat settings</b>",
        f"Project: <code>{html.escape(project_display)}</code> → "
        f"<code>{html.escape(working_dir)}</code>",
        f"Model profile: <code>{html.escape(model_display)}</code>",
        f"File policy: <code>{html.escape(policy)}</code>",
        f"Compact mode: <b>{compact_label}</b>",
        f"Approval mode: <b>{approval}</b>",
        _msg.settings_use_buttons_hint(),
    ]
    if effective_model:
        lines.insert(3, f"Effective model: <code>{html.escape(effective_model)}</code>")
    if trust_public:
        lines.append(_msg.trust_settings_managed_public())

    keyboard: list[list[Any]] = []
    if not trust_public:
        keyboard.extend(_settings_project_buttons(project_names, current_project))
        if policy:
            keyboard.append(
                _settings_policy_buttons(policy, has_explicit_override=has_policy_override)
            )
    if model_available:
        keyboard.append(
            _settings_model_buttons(
                model_available,
                model_display,
                has_explicit_override=has_model_override,
            )
        )
    elif has_model_override:
        keyboard.append(
            [InlineKeyboardButton("Clear model override", callback_data="setting_model:inherit")]
        )
    keyboard.append(_settings_compact_buttons(compact))
    keyboard.append(_settings_approval_buttons(approval))

    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def policy_status(policy: str, *, has_explicit_override: bool) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=f"File policy: <b>{html.escape(policy)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [_settings_policy_buttons(policy, has_explicit_override=has_explicit_override)]
        ),
    )


def skill_add_confirmation(name: str, projected_size: int, prompt_size_threshold: int) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=(
            f"Adding <code>{html.escape(name)}</code> would bring total "
            f"prompt context to ~{projected_size:,} chars "
            f"(threshold: {prompt_size_threshold:,}). "
            f"This may reduce response quality. Continue?"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes", callback_data=f"skill_add_confirm:{name}"),
            InlineKeyboardButton("No", callback_data="skill_add_cancel"),
        ]]),
    )


def clear_credentials_confirmation(
    message: str,
    *,
    confirm_callback: str,
    cancel_callback: str,
) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes, clear", callback_data=confirm_callback),
            InlineKeyboardButton("Cancel", callback_data=cancel_callback),
        ]]),
    )


def provider_guidance_preview_message(
    provider_name: str,
    preview: ProviderGuidancePreview,
) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=(
            f"<b>{html.escape(provider_name)}</b>\n"
            f"<pre>{html.escape(preview.effective_guidance)}</pre>"
        ),
        parse_mode=ParseMode.HTML,
    )


def provider_guidance_not_found_message(provider_name: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=f"Provider guidance <code>{html.escape(provider_name)}</code> not found.",
        parse_mode=ParseMode.HTML,
    )


def provider_guidance_history_message(
    provider_name: str,
    detail: ProviderGuidanceLifecycleDetail,
) -> TelegramRenderedMessage:
    lines = [
        f"<b>{html.escape(provider_name)}</b>",
        f"Status: <code>{html.escape(detail.lifecycle_status)}</code>",
        f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>",
        "",
        "<b>Revisions</b>",
    ]
    for item in detail.revisions[:8]:
        pub = " [published]" if item.is_published else ""
        lines.append(
            f"  <code>{html.escape(item.revision_id[:12])}</code> — "
            f"{html.escape(item.status)}{pub}"
        )
    if detail.approvals:
        lines.append("")
        lines.append("<b>Approvals</b>")
        for item in detail.approvals[:8]:
            note = f" — {html.escape(item.note)}" if item.note else ""
            lines.append(f"  {html.escape(item.action)} by {html.escape(item.actor)}{note}")
    return TelegramRenderedMessage(text="\n".join(lines), parse_mode=ParseMode.HTML)


def provider_guidance_mutation_message(message: str) -> TelegramRenderedMessage:
    return _escaped_html_message(message)


def runtime_skill_active_summary_message(active_display_names: list[str], catalog_count: int) -> TelegramRenderedMessage:
    if active_display_names:
        lines = [f"<b>Active in this conversation ({len(active_display_names)}):</b>"]
        for display in active_display_names:
            lines.append(f"  {html.escape(display)}")
    else:
        lines = ["<b>No skills active in this conversation.</b>"]
    lines.append(
        f"\nInstalled on this bot: {catalog_count} skill(s). "
        "Use /skills list for the bot catalog and /skills add <name> to activate one here."
    )
    return _html_message("\n".join(lines))


def runtime_skill_catalog_message(
    catalog: list[RuntimeSkillCatalogItem],
    status_by_name: dict[str, str],
) -> TelegramRenderedMessage:
    if not catalog:
        return TelegramRenderedMessage(text="No skills are installed on this bot.")
    lines = ["<b>Installed on this bot:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        extra: list[str] = [item.source_label]
        if item.has_custom_override:
            extra.append("custom override")
        if item.requires_credentials:
            extra.append("setup required")
        desc = f" — {html.escape(item.description)}" if item.description else ""
        lines.append(
            f"  <code>{html.escape(item.name)}</code>{desc}"
            f"{status_by_name.get(item.name, '')} ({html.escape(', '.join(extra))})"
        )
    return _html_message("\n".join(lines))


def runtime_skill_unknown_message(name: str) -> TelegramRenderedMessage:
    return _html_message(
        f"Unknown skill: {html.escape(name)}. Use /skills list to see what is installed on this bot."
    )


def runtime_skill_foreign_setup_message(setup) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=foreign_setup_message(setup))


def runtime_skill_needs_setup_message(name: str, first_requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(
        f"Skill <code>{html.escape(name)}</code> is installed on this bot but needs setup before it can be active in this conversation.\n\n"
        f"{format_credential_prompt(first_requirement)}"
    )


def runtime_skill_not_published_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is not published yet.")


def runtime_skill_activated_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is now active in this conversation.")


def runtime_skill_deactivated_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is no longer active in this conversation.")


def runtime_skill_not_active_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is not active in this conversation.")


def runtime_skill_no_requirements_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> does not require setup credentials.")


def runtime_skill_setup_could_not_start_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Setup could not be started.")


def runtime_skill_setup_started_message(name: str, first_requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(
        f"Setting up <code>{html.escape(name)}</code> for this conversation.\n\n"
        f"{format_credential_prompt(first_requirement)}"
    )


def runtime_skill_all_removed_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="All conversation skills removed.")


def runtime_skill_create_success_message(name: str, visibility: str) -> TelegramRenderedMessage:
    return _html_message(
        f"Created custom draft <code>{html.escape(name)}</code>\n"
        f"Draft visibility: <code>{html.escape(visibility)}</code>\n"
        "Use /skills edit, /skills submit, and /skills history to continue the lifecycle."
    )


def runtime_skill_history_not_found_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Custom skill <code>{html.escape(name)}</code> not found.")


def runtime_skill_history_message(detail: RuntimeSkillLifecycleDetail) -> TelegramRenderedMessage:
    lines = [
        f"<b>{html.escape(detail.display_name)}</b>",
        f"Source: <code>{html.escape(detail.source_label)}</code>",
        f"Status: <code>{html.escape(detail.lifecycle_status)}</code>",
        f"Runtime available: {'yes' if detail.runtime_available else 'no'}",
        f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>",
        "",
        "<b>Revisions</b>",
    ]
    for item in detail.revisions[:8]:
        pub = " [published]" if item.is_published else ""
        lines.append(
            f"  <code>{html.escape(item.revision_id[:12])}</code> — "
            f"{html.escape(item.status)}{pub}"
        )
    if detail.approvals:
        lines.append("")
        lines.append("<b>Approvals</b>")
        for item in detail.approvals[:8]:
            note = f" — {html.escape(item.note)}" if item.note else ""
            lines.append(f"  {html.escape(item.action)} by {html.escape(item.actor)}{note}")
    return _html_message("\n".join(lines))


def runtime_skill_admin_only_message(text: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=text)


def public_command_not_available_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.trust_command_not_available_public())


def trust_not_authorized_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.trust_not_authorized())


def conversation_plain_outcome_message(message: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=message)


def conversation_html_outcome_message(message: str) -> TelegramRenderedMessage:
    return _html_message(message)


def conversation_foreign_setup_message(setup) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=foreign_setup_message(setup))


def conversation_approval_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.approval_usage())


def conversation_compact_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /compact on|off")


def conversation_role_current_message(role: str) -> TelegramRenderedMessage:
    return _html_message(f"Current role: <code>{html.escape(role)}</code>")


def conversation_role_default_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="No role set (using instance default).")


def conversation_projects_list_message(projects, current_project: str | None) -> TelegramRenderedMessage:
    lines = ["<b>Available projects:</b>"]
    for proj in projects:
        marker = " (active)" if proj.name == current_project else ""
        lines.append(
            f"  <code>{html.escape(proj.name)}</code> → "
            f"{html.escape(str(proj.root_dir))}{marker}"
        )
    return _html_message("\n".join(lines))


def no_projects_configured_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.no_projects_configured())


def trust_project_public_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.trust_project_public())


def trust_file_policy_public_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.trust_file_policy_public())


def conversation_policy_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.policy_usage())


def runtime_skill_mutation_message(message: str) -> TelegramRenderedMessage:
    return _escaped_html_message(message)


def runtime_skill_search_results_message(
    query: str,
    results: RuntimeSkillSearchResults,
) -> TelegramRenderedMessage:
    lines: list[str] = []
    if results.catalog:
        lines.append(f"<b>Installed on this bot matching '{html.escape(query)}':</b>")
        for info in results.catalog:
            desc = f" — {html.escape(info.description)}" if info.description else ""
            lines.append(
                f"  <code>{html.escape(info.name)}</code>{desc} "
                f"({html.escape(info.source_label)})"
            )
    if results.registry:
        local_names = {item.name for item in results.catalog}
        reg_only = [item for item in results.registry if item.name not in local_names]
        if reg_only:
            lines.append(f"\n<b>Skill store matches for '{html.escape(query)}':</b>")
            for skill in reg_only:
                desc = f" — {html.escape(skill.description)}" if skill.description else ""
                pub = f" (by {html.escape(skill.publisher)})" if skill.publisher else ""
                lines.append(f"  <code>{html.escape(skill.name)}</code>{desc}{pub}")
    if results.registry_error:
        lines.append(f"\n<i>Skill store search failed: {html.escape(results.registry_error)}</i>")
    if not lines:
        return _html_message(f"No skills matching '{html.escape(query)}'.")
    lines.append("\nUse /skills info <name> for details, /skills install <name> to install a store skill on this bot.")
    return _html_message("\n".join(lines))


def runtime_skill_info_not_found_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill '{html.escape(name)}' not found.")


def runtime_skill_info_message(detail: RuntimeSkillDetail) -> TelegramRenderedMessage:
    parts = [f"<b>{html.escape(detail.display_name)}</b>"]
    if detail.description:
        parts.append(html.escape(detail.description))
    parts.append(f"Source: <code>{html.escape(detail.source_label)}</code>")
    parts.append(
        "State: "
        + ("ready to activate in a conversation" if detail.runtime_available else "not ready for activation until published")
    )
    if detail.requirement_keys:
        parts.append(f"Setup: {html.escape(', '.join(detail.requirement_keys))}")
    else:
        parts.append("Setup: none")
    if detail.providers:
        parts.append(f"Providers: {', '.join(sorted(detail.providers))}")
    parts.append("Use /skills add <name> to activate it in this conversation.")
    preview = detail.body
    if len(preview) > 1000:
        cut = preview.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = preview[:cut] + "..."
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    return _html_message("\n".join(parts))


def runtime_skill_install_error_message(error_text: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill store install failed: {html.escape(error_text[:300])}")


def runtime_skill_updates_message(
    updates: tuple[RuntimeSkillUpdateStatusItem, ...],
) -> TelegramRenderedMessage:
    if not updates:
        return TelegramRenderedMessage(text="No store-installed skills found on this bot.")
    lines = ["<b>Store-installed skills on this bot:</b>"]
    for item in updates:
        label = "update available" if item.status == "update_available" else "up to date"
        override = " [custom override]" if item.has_custom_override else ""
        lines.append(f"  <code>{html.escape(item.name)}</code> — {label}{override}")
    return _html_message("\n".join(lines))


def runtime_skill_diff_message(diff_text: str) -> TelegramRenderedMessage:
    rendered = diff_text.strip() or "No differences."
    if len(rendered) > 4000:
        rendered = rendered[:4000] + "\n... (truncated)"
    return _html_message(f"<pre>{html.escape(rendered)}</pre>")


def runtime_skill_update_results_message(
    results: tuple[RuntimeSkillMutationOutcome, ...],
    warnings: list[str],
) -> TelegramRenderedMessage:
    if not results:
        return TelegramRenderedMessage(text="No imported skills need updating.")
    lines = ["<b>Update results:</b>"]
    for result in results:
        status = "✔" if result.ok else "✘"
        lines.append(f"  {status} {html.escape(result.message)}")
    if warnings:
        lines.append("")
        lines.append("<b>Prompt size warnings:</b>")
        for warning in warnings:
            lines.append(f"  {html.escape(warning)}")
    return _html_message("\n".join(lines))


def clear_credentials_missing_message(skill_name: str) -> TelegramRenderedMessage:
    return _html_message(f"No stored credentials for <code>{html.escape(skill_name)}</code>.")


def clear_credentials_none_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="No stored credentials found.")


def clear_credentials_single_message(skill_name: str) -> str:
    return (
        f"This will remove your credentials for "
        f"<code>{html.escape(skill_name)}</code> and deactivate it "
        f"in this chat. Continue?"
    )


def clear_credentials_all_message(affected: list[str]) -> str:
    names = html.escape(", ".join(affected))
    return (
        f"This will remove all your stored credentials "
        f"({names}) and deactivate affected skills. Continue?"
    )


def clear_credentials_result_message(
    removed_skills: tuple[str, ...],
    setup_cleared: bool,
    deactivated_skills: tuple[str, ...],
) -> TelegramRenderedMessage:
    parts = []
    if removed_skills:
        parts.append(f"Credentials cleared for: {html.escape(', '.join(removed_skills))}.")
    if setup_cleared:
        parts.append(_msg.credential_setup_cancelled())
    if deactivated_skills:
        parts.append(f"Deactivated in this chat: {html.escape(', '.join(deactivated_skills))}.")
    if not parts:
        parts.append("No credentials to clear (may have already been removed).")
    return _html_message("\n".join(parts))


def credential_clear_cancelled_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.credential_clear_cancelled())


def skill_activation_cancelled_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Skill activation cancelled.")


def runtime_skill_update_cancelled_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Update cancelled.")


def runtime_skill_enter_credential_value_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Please send the credential value as a text message.")


def runtime_skill_validation_failed_message(validation_key: str, validation_error: str) -> TelegramRenderedMessage:
    return _html_message(
        f"Credential validation failed for <code>{html.escape(validation_key)}</code>: "
        f"{html.escape(validation_error)}\nPlease try again."
    )


def runtime_skill_next_requirement_message(requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(format_credential_prompt(requirement))


def runtime_skill_ready_message(skill_name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(skill_name)}</code> is ready.")


def pending_plain_outcome_message(message: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=message)


def pending_html_outcome_message(message: str) -> TelegramRenderedMessage:
    return _html_message(message)


def recovery_invalid_action_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.recovery_invalid_action())


def recovery_failed_edit_message() -> TelegramRenderedMessage:
    return _html_message(_msg.recovery_replay_failed_edit())


def ingress_setup_prompt_message(missing_skill: str, first_requirement: dict[str, object]) -> TelegramRenderedMessage:
    return _html_message(
        f"Skill <code>{html.escape(missing_skill)}</code> needs setup.\n\n"
        f"{format_credential_prompt(first_requirement)}"
    )


def formatted_reply_messages(text: str) -> list[TelegramRenderedMessage]:
    formatted = md_to_telegram_html(text) if text else "<i>[empty]</i>"
    return [
        TelegramRenderedMessage(
            text=chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        for chunk in split_html(formatted, 4096)
    ]


def formatted_reply_fallback_text(rendered_chunk: str) -> str:
    return re.sub(r"<[^>]+>", "", rendered_chunk)[:4096]


def compact_reply_blockquote_message(text: str) -> TelegramRenderedMessage | None:
    summary, detail = extract_summary(text)
    formatted_summary = md_to_telegram_html(summary) if summary else ""
    if not detail:
        return None
    formatted_detail = md_to_telegram_html(detail)
    compact_html = (
        f"{formatted_summary}\n\n"
        f"<blockquote expandable>{formatted_detail}</blockquote>"
    )
    if len(compact_html) > 4000:
        return None
    return TelegramRenderedMessage(
        text=compact_html,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def compact_reply_button_message(text: str, chat_id: int, slot: int) -> TelegramRenderedMessage:
    summary, _ = extract_summary(text)
    formatted_summary = md_to_telegram_html(summary) if summary else ""
    return collapsed_response_message(formatted_summary, chat_id, slot)


def expanded_response_message(text: str, chat_id: int, slot: int) -> TelegramRenderedMessage | None:
    formatted = md_to_telegram_html(text)
    if len(formatted) > 4000:
        return None
    return TelegramRenderedMessage(
        text=formatted,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=expanded_response_reply_markup(chat_id, slot),
    )


def cannot_send_path_message(raw_path: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"[Cannot send: {raw_path}]")


def _delegation_preview_lines(preview: DelegationTargetPreview | None) -> list[str]:
    if preview is None:
        return []
    if preview.status == "resolved":
        if not preview.authority_ref:
            return []
        return [f"Status: ready via <code>{html.escape(preview.authority_ref)}</code>"]
    if preview.status == "missing_target":
        lines = ["Status: <b>missing target agent</b>"]
    elif preview.status == "unavailable":
        lines = ["Status: <b>registry unavailable</b>"]
    else:
        lines = ["Status: <b>target not available yet</b>"]
    if preview.detail:
        lines.append(html.escape(preview.detail))
    return lines


def delegation_plan_message(
    delegation: PendingDelegation,
    *,
    previews: Iterable[DelegationTargetPreview] | None = None,
) -> TelegramRenderedMessage:
    preview_items = list(previews or ())
    has_blockers = any(item.status != "resolved" for item in preview_items)
    lines = [
        "<b>Delegation plan</b>",
        "",
        "I'd like to delegate the following to specialist bots:",
        "",
    ]
    for index, task in enumerate(delegation.tasks, start=1):
        preview = preview_items[index - 1] if index - 1 < len(preview_items) else None
        lines.extend([
            f"<b>{index}. {html.escape(task.title or task.routed_task_id)}</b>",
            f"\u2192 {html.escape(task.target_agent_id or 'unassigned')}",
        ])
        lines.extend(_delegation_preview_lines(preview))
        lines.append("")
    if has_blockers:
        lines.append(
            "Some targets are not ready yet. Approval will check ownership again"
            " before sending any requests."
        )
        lines.append("")
    lines.append("Approve to send these requests, or cancel to continue without delegation.")
    return _html_message("\n".join(lines))


def welcome_message(*, approval_mode: str, compact_mode: bool) -> TelegramRenderedMessage:
    text = "I'm ready. Send me a message or type /help to see what I can do."
    if approval_mode == "on":
        text += "\nApproval mode is on — I'll show a plan before acting."
    if compact_mode:
        text += "\nCompact mode is on — long answers are summarized. Use /compact off for full answers."
    return TelegramRenderedMessage(text=text)


def raw_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /raw [N] — N is the Nth most recent response (default: 1)")


def raw_missing_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="No stored responses found.")


HELP_SKILLS = (
    "<b>Skills</b>\n\n"
    "Skills have three layers: what is installed on this bot, what needs setup, and what is active in this conversation.\n\n"
    "/skills list — show the bot catalog with conversation status\n"
    "/skills add &lt;name&gt; — activate an installed skill in this conversation\n"
    "/skills remove &lt;name&gt; — deactivate a skill in this conversation\n"
    "/skills setup &lt;name&gt; — re-enter setup credentials for a skill\n"
    "/skills info &lt;name&gt; — view skill details\n"
    "/skills search &lt;query&gt; — search the skill store\n"
    "/skills install &lt;name&gt; — install a store skill on this bot\n"
    "/skills clear — deactivate all skills in this conversation\n"
    "/skills create &lt;name&gt; — create a custom draft skill on this bot\n"
    "/skills edit &lt;name&gt; &lt;body&gt; — replace the current draft body\n"
    "/skills history &lt;name&gt; — show revision and approval history\n"
    "/skills submit &lt;name&gt; — submit the draft for review\n"
    "/skills approve|reject|publish|archive &lt;name&gt; — lifecycle admin actions\n\n"
    "/guidance preview &lt;provider&gt; — show effective provider guidance\n"
    "/guidance edit|history|submit|approve|reject|publish|archive &lt;provider&gt; — provider guidance lifecycle"
)

HELP_APPROVAL = (
    "<b>Approval Mode</b>\n\n"
    "When approval mode is on, the AI shows a plan before executing. "
    "You review and approve or reject it.\n\n"
    "If a request needs approval, retry, or recovery (e.g. interrupted or blocked), "
    "use the in-chat buttons on the status message — Run again or Skip — no separate command needed.\n\n"
    "/approval on — require approval before execution\n"
    "/approval off — execute immediately\n"
    "/approval status — check current setting\n"
    "/approve — approve the pending plan\n"
    "/reject — reject the pending plan\n"
    "/cancel — cancel a pending request"
)

HELP_CREDENTIALS = (
    "<b>Credentials</b>\n\n"
    "Some skills need API tokens or keys. When you activate such a skill, "
    "the bot asks for each credential in a private message and encrypts it.\n\n"
    "/skills setup &lt;name&gt; — re-enter credentials for a skill\n"
    "/clear_credentials — remove all your stored credentials\n"
    "/clear_credentials &lt;skill&gt; — remove credentials for one skill\n\n"
    "Your credential messages are deleted after capture for safety."
)

_HELP_TOPICS = {
    "skills": HELP_SKILLS,
    "approval": HELP_APPROVAL,
    "credentials": HELP_CREDENTIALS,
}


def _help_command_lines(
    *,
    has_model_profiles: bool,
    agent_mode: str,
    is_public: bool,
    has_projects: bool,
    is_admin: bool,
) -> list[str]:
    lines = [
        "/new — start a fresh conversation",
        "/skills — inspect the bot catalog and manage what is active in this conversation",
        "/guidance — inspect and manage provider guidance",
        "/role &lt;text&gt; — set the AI's persona (e.g. <code>/role Python expert</code>)",
        "/approval on|off — show a plan before executing, or run immediately",
        "/approve / /reject — act on a pending plan",
        "/cancel — cancel a running task, credential setup, or a pending request",
        "/clear_credentials — remove your stored credentials",
        "/send &lt;path&gt; — retrieve a file the server",
        "/compact on|off — toggle short/full answers",
    ]
    if has_model_profiles:
        lines.append("/model — switch model profile (fast/balanced/best)")
    if agent_mode == "registry":
        lines.append("/discover — find available specialist bots by role, skill, or tag")
    if not is_public:
        lines.append("/policy inspect|edit — set file access policy")
    lines.append("/settings — view and change chat settings")
    if not is_public and has_projects:
        lines.append("/project — show or change project binding")
    lines.extend([
        "/session — show current session info",
        "/id — show your Telegram user ID",
        "/doctor — run full app health check (DB, config, Telegram)",
        "/export — download recent conversation history",
    ])
    if is_admin:
        lines.append("/admin sessions — session overview (admin only)")
    return lines


def main_help_message(
    *,
    instance: str,
    provider_name: str,
    has_model_profiles: bool,
    agent_mode: str,
    is_public: bool,
    has_projects: bool,
    is_admin: bool,
) -> TelegramRenderedMessage:
    header = (
        f"<b>Agent Bot</b> (instance: <code>{html.escape(instance)}</code>, "
        f"provider: {html.escape(provider_name)})\n\n"
        "Send a message, photo, or document and the AI will respond.\n\n"
        "<b>Commands:</b>\n"
    )
    command_block = "\n".join(
        _help_command_lines(
            has_model_profiles=has_model_profiles,
            agent_mode=agent_mode,
            is_public=is_public,
            has_projects=has_projects,
            is_admin=is_admin,
        )
    )
    control_parts = ["/settings", "/session"]
    if has_model_profiles:
        control_parts.append("/model")
    if not is_public and has_projects:
        control_parts.append("/project")
    controls_line = "Chat options: " + " · ".join(control_parts) + "."
    recovery_line = "Interrupted? Use Run again or Skip on the status message."
    footer = (
        controls_line
        + "\n"
        + recovery_line
        + "\n\nType /help skills, /help approval, or /help credentials for details."
    )
    return _html_message(header + command_block + "\n\n" + footer)


def help_topic_message(topic: str) -> TelegramRenderedMessage | None:
    text = _HELP_TOPICS.get(topic)
    if text is None:
        return None
    return _html_message(text)


def unknown_help_topic_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="Unknown help topic. Try: /help skills, /help approval, or /help credentials."
    )


def session_overview_message(
    *,
    provider_name: str,
    instance: str,
    working_dir_display: str,
    file_policy: str,
    model_profile: str,
    model_id: str,
    compact_display: str,
    prompt_weight: str,
    session_label: str,
    session_value: str,
    session_active: str | None,
    approval_mode: str,
    approval_source: str,
    role_display: str,
    skills_display: str,
    pending: str,
    trust_public: bool,
    session_commands: list[str],
) -> TelegramRenderedMessage:
    lines = [
        f"Provider: <code>{html.escape(provider_name)}</code>",
        f"Instance: <code>{html.escape(instance)}</code>",
        f"Working dir: <code>{html.escape(working_dir_display)}</code>",
        f"File policy: <code>{html.escape(file_policy)}</code>",
        f"Model: <code>{html.escape(model_profile)}</code> ({html.escape(model_id)})",
        f"Compact: <code>{compact_display}</code>",
        f"Prompt weight: <code>{html.escape(prompt_weight)}</code>",
        f"{html.escape(session_label)}: <code>{html.escape(session_value)}</code>",
    ]
    if session_active is not None:
        lines.append(f"Active: <code>{html.escape(session_active)}</code>")
    lines.extend(
        [
            f"Approval mode: <code>{html.escape(approval_mode)}</code> ({html.escape(approval_source)})",
            f"Role: <code>{html.escape(role_display)}</code>",
            f"Skills: <code>{html.escape(skills_display)}</code>",
            f"Pending: <code>{html.escape(pending)}</code>",
        ]
    )
    if trust_public:
        lines.extend(["", _msg.trust_settings_managed_public()])
    if session_commands:
        if len(session_commands) == 1:
            command_hint = session_commands[0]
        elif len(session_commands) == 2:
            command_hint = session_commands[0] + " or " + session_commands[1]
        else:
            command_hint = ", ".join(session_commands[:-1]) + ", or " + session_commands[-1]
        lines.extend(["", "Use " + command_hint + " to change chat settings."])
    return _html_message("\n".join(lines))


def send_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /send <path>")


def send_path_not_allowed_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Path is missing or outside allowed roots.")


def user_identity_message(user_id: str, username: str) -> TelegramRenderedMessage:
    return _html_message(
        f"Your user ID: <code>{html.escape(str(user_id))}</code>\n"
        f"Your username: <code>{html.escape(username)}</code>"
    )


def doctor_report_message(lines: Iterable[str], prompt_weight_count: int | None) -> TelegramRenderedMessage:
    parts: list[str] = []
    for line in lines:
        if line.startswith("INFO: "):
            parts.append(f"\u2139\ufe0f {html.escape(line[6:])}")
        elif line.startswith("FAIL: "):
            parts.append(f"\u274c {html.escape(line[6:])}")
        elif line.startswith("WARN: "):
            parts.append(f"\u26a0\ufe0f {html.escape(line[6:])}")
        else:
            parts.append(html.escape(line))
    if prompt_weight_count:
        parts.append(f"Prompt weight: ~{prompt_weight_count} chars")
    if parts:
        return _html_message("\n".join(parts))
    return TelegramRenderedMessage(text="\u2705 All checks passed.")


def discover_usage_message() -> TelegramRenderedMessage:
    return _html_message(
        "Usage: /discover <query> [role:<role>] [capability:<capability>] [tag:<tag>] [state:<connected|degraded|standalone|disconnected>]\n"
        "Example: <code>/discover role:developer capability:python tag:backend schema review</code>"
    )


def discover_unavailable_standalone_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Agent discovery is unavailable in standalone mode.")


def discover_degraded_message(last_error_code: str) -> TelegramRenderedMessage:
    detail = f" {registry_error_summary(last_error_code)}" if last_error_code else ""
    return TelegramRenderedMessage(
        text="Agent discovery is unavailable because registry connectivity is degraded." + detail
    )


def discover_not_enrolled_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="Agent discovery is unavailable because this bot has not finished registry enrollment."
    )


def discover_failed_message(error_code: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"Agent discovery failed. {registry_error_summary(error_code)}")


def _agent_view(agent: Any) -> dict[str, Any]:
    if is_dataclass(agent):
        return asdict(agent)
    if hasattr(agent, "model_dump"):
        return agent.model_dump()
    if isinstance(agent, dict):
        return agent
    return {}


def discover_results_message(agents: list[Any]) -> TelegramRenderedMessage:
    if not agents:
        return TelegramRenderedMessage(text="No matching agents found.")
    lines = ["<b>Matching agents</b>"]
    for raw_agent in agents[:8]:
        agent = _agent_view(raw_agent)
        display_name = html.escape(
            agent.get("display_name") or agent.get("slug") or agent.get("agent_id") or "Unnamed agent"
        )
        authority_ref = html.escape(str(agent.get("authority_ref", "") or ""))
        role = html.escape(agent.get("role") or "(unspecified)")
        state = html.escape(agent.get("connectivity_state") or "unknown")
        current_capacity = int(agent.get("current_capacity", 0) or 0)
        max_capacity = int(agent.get("max_capacity", 1) or 1)
        lines.append(f"\n<b>{display_name}</b> — <code>{role}</code>")
        lines.append(
            f"State: <code>{state}</code> · Capacity: <code>{current_capacity}/{max_capacity}</code>"
        )
        if authority_ref:
            lines.append(f"Authority: <code>{authority_ref}</code>")
        capabilities = [str(value) for value in agent.get("capabilities", []) if value]
        if capabilities:
            lines.append(f"Capabilities: <code>{html.escape(', '.join(capabilities))}</code>")
        tags = [str(value) for value in agent.get("tags", []) if value]
        if tags:
            lines.append(f"Tags: <code>{html.escape(', '.join(tags))}</code>")
        description = str(agent.get("description", "") or "").strip()
        if description:
            lines.append(html.escape(description))
    if len(agents) > 8:
        lines.append(f"\nShowing first 8 of {len(agents)} matches.")
    return _html_message("\n".join(lines))


def admin_required_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.admin_required())


def no_sessions_found_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.no_sessions_found())


def admin_sessions_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /admin sessions [conversation_key]")


def admin_invalid_conversation_key_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Invalid conversation key.")


def admin_session_not_found_message(target_key: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"No session found for conversation {target_key}.")


def admin_session_detail_message(target_key: str, match: dict[str, Any]) -> TelegramRenderedMessage:
    skills = match["active_skills"]
    skill_list = ", ".join(skills) if skills else "none"
    lines = [
        f"<b>Session {html.escape(target_key)}</b>",
        f"Provider: {html.escape(match['provider'])}",
        f"Approval: {html.escape(match['approval_mode'])}",
        f"Skills ({len(skills)}): {html.escape(skill_list)}",
        f"Pending request: {'yes' if match['has_pending'] else 'no'}",
        f"Credential setup: {'in progress' if match['has_setup'] else 'no'}",
        f"Created: {html.escape(match['created_at'][:19])}",
        f"Updated: {html.escape(match['updated_at'][:19])}",
    ]
    return _html_message("\n".join(lines))


def admin_sessions_summary_message(
    *,
    total: int,
    pending: int,
    setup: int,
    top_skills: list[tuple[str, int]],
    most_recent_key: str,
    most_recent_updated_at: str,
) -> TelegramRenderedMessage:
    lines = [f"<b>Sessions: {total}</b>"]
    if pending:
        lines.append(f"Pending approval: {pending}")
    if setup:
        lines.append(f"Credential setup: {setup}")
    if top_skills:
        lines.extend(["", "<b>Top skills:</b>"])
        for skill_name, count in top_skills:
            lines.append(f"  {html.escape(skill_name)}: {count}")
    lines.extend(["", f"Most recent: {html.escape(most_recent_key)}"])
    if most_recent_updated_at:
        lines.append(f"  updated {html.escape(most_recent_updated_at[:19])}")
    return _html_message("\n".join(lines))


def skills_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="Usage: /skills [list|add|remove|setup|create|edit|history|submit|approve|reject|publish|archive|clear|search|info|install|uninstall|updates|update|diff]"
    )


def guidance_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="Usage: /guidance [preview|edit|history|submit|approve|reject|publish|archive] <provider> [body]"
    )


def guidance_admin_only_message(action: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"Only admins can {action} provider guidance.")


def no_conversation_to_export_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=_msg.no_conversation_to_export())


def admin_access_required_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="This command requires admin access.")


def allowuser_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /allowuser <actor_key|user_id> [reason]")


def allowuser_success_message(actor_key: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"Actor {actor_key} added to allowed list.")


def blockuser_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Usage: /blockuser <actor_key|user_id> [reason]")


def blockuser_success_message(actor_key: str) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"Actor {actor_key} blocked.")


def listaccess_empty_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="No access overrides set.")


def access_overrides_message(rows: list[UserAccessRecord]) -> TelegramRenderedMessage:
    lines = ["<b>Access overrides</b>"]
    for row in rows:
        status = "\u2705 allowed" if row.access == "allowed" else "\ud83d\udeab blocked"
        reason = f" — {html.escape(row.reason)}" if row.reason else ""
        lines.append(f"\u2022 <code>{row.actor_key}</code> {status}{reason}")
    return _html_message("\n".join(lines))


def queue_busy_message() -> TelegramRenderedMessage:
    return _html_message(f"<i>{_msg.queue_busy()}</i>")


def queue_accepted_message() -> TelegramRenderedMessage:
    return _html_message(f"<i>{_msg.queue_accepted()}</i>")


def generic_error_try_again_message() -> TelegramRenderedMessage:
    return _html_message(f"<i>{_msg.generic_error_try_again()}</i>")


def rate_limit_message(retry_after: int) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=f"Rate limit reached. Please wait {retry_after} seconds.")


def recovery_orphaned_command_message(detail: str) -> TelegramRenderedMessage:
    return _html_message(_msg.recovery_orphaned_command(detail))
