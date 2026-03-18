"""Telegram-channel presentation helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app import user_messages as _msg
from app.approvals import format_denials_html
from app.credential_flow import foreign_setup_message, format_credential_prompt
from app.formatting import md_to_telegram_html, split_html
from app.session_state import PendingDelegation
from app.workflows.provider_guidance.contracts import (
    ProviderGuidanceLifecycleDetail,
    ProviderGuidancePreview,
)
from app.workflows.runtime_skills.contracts import (
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


def retry_prompt(denials: Iterable[dict[str, Any]]) -> TelegramRenderedMessage:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 " + _msg.retry_button_grant(), callback_data="retry_allow"),
        InlineKeyboardButton("\u274c " + _msg.retry_button_skip(), callback_data="retry_skip"),
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


def approval_prompt() -> TelegramRenderedMessage:
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 " + _msg.approval_button_approve(), callback_data="approval_approve"),
        InlineKeyboardButton("\u274c " + _msg.approval_button_reject(), callback_data="approval_reject"),
    ]])
    return TelegramRenderedMessage(
        text=_msg.approval_plan_question(),
        reply_markup=keyboard,
    )


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
        lines = [f"<b>Active skills ({len(active_display_names)}):</b>"]
        for display in active_display_names:
            lines.append(f"  {html.escape(display)}")
    else:
        lines = ["<b>No active skills.</b>"]
    lines.append(f"\n{catalog_count} skill(s) available. Use /skills list to see all.")
    return _html_message("\n".join(lines))


def runtime_skill_catalog_message(
    catalog: list[RuntimeSkillCatalogItem],
    status_by_name: dict[str, str],
) -> TelegramRenderedMessage:
    if not catalog:
        return TelegramRenderedMessage(text="No skills available.")
    lines = ["<b>Available skills:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        if item.has_custom_override:
            custom_tag = " [custom override]"
        elif item.source_kind == "custom":
            custom_tag = " (custom)"
        elif item.source_kind == "imported":
            custom_tag = " (imported)"
        else:
            custom_tag = ""
        desc = f" — {html.escape(item.description)}" if item.description else ""
        lines.append(
            f"  <code>{html.escape(item.name)}</code>{desc}"
            f"{status_by_name.get(item.name, '')}{custom_tag}"
        )
    return _html_message("\n".join(lines))


def runtime_skill_unknown_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Unknown skill: {html.escape(name)}. Use /skills list to see available.")


def runtime_skill_foreign_setup_message(setup) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=foreign_setup_message(setup))


def runtime_skill_needs_setup_message(name: str, first_requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(
        f"Skill <code>{html.escape(name)}</code> needs setup before activation.\n\n"
        f"{format_credential_prompt(first_requirement)}"
    )


def runtime_skill_not_published_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is not published yet.")


def runtime_skill_activated_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> activated.")


def runtime_skill_deactivated_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> deactivated.")


def runtime_skill_not_active_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> is not active.")


def runtime_skill_no_requirements_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill <code>{html.escape(name)}</code> has no credential requirements.")


def runtime_skill_setup_could_not_start_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="Setup could not be started.")


def runtime_skill_setup_started_message(name: str, first_requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(
        f"Setting up <code>{html.escape(name)}</code>.\n\n"
        f"{format_credential_prompt(first_requirement)}"
    )


def runtime_skill_all_removed_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text="All skills removed.")


def runtime_skill_create_success_message(name: str, visibility: str) -> TelegramRenderedMessage:
    return _html_message(
        f"Created custom skill <code>{html.escape(name)}</code>\n"
        f"Draft visibility: <code>{html.escape(visibility)}</code>\n"
        "Use /skills edit, /skills submit, and /skills history to continue the lifecycle."
    )


def runtime_skill_history_not_found_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Custom skill <code>{html.escape(name)}</code> not found.")


def runtime_skill_history_message(detail: RuntimeSkillLifecycleDetail) -> TelegramRenderedMessage:
    lines = [
        f"<b>{html.escape(detail.display_name)}</b>",
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
        lines.append(f"<b>Catalog skills matching '{html.escape(query)}':</b>")
        for info in results.catalog:
            desc = f" — {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")
    if results.registry:
        local_names = {item.name for item in results.catalog}
        reg_only = [item for item in results.registry if item.name not in local_names]
        if reg_only:
            lines.append(f"\n<b>Registry skills matching '{html.escape(query)}':</b>")
            for skill in reg_only:
                desc = f" — {html.escape(skill.description)}" if skill.description else ""
                pub = f" (by {html.escape(skill.publisher)})" if skill.publisher else ""
                lines.append(f"  <code>{html.escape(skill.name)}</code>{desc}{pub}")
    if results.registry_error:
        lines.append(f"\n<i>Registry search failed: {html.escape(results.registry_error)}</i>")
    if not lines:
        return _html_message(f"No skills matching '{html.escape(query)}'.")
    lines.append("\nUse /skills info <name> for details, /skills install <name> to import from the registry.")
    return _html_message("\n".join(lines))


def runtime_skill_info_not_found_message(name: str) -> TelegramRenderedMessage:
    return _html_message(f"Skill '{html.escape(name)}' not found.")


def runtime_skill_info_message(detail: RuntimeSkillDetail) -> TelegramRenderedMessage:
    parts = [f"<b>{html.escape(detail.display_name)}</b>"]
    if detail.description:
        parts.append(html.escape(detail.description))
    if detail.requirement_keys:
        parts.append(f"Requires: {html.escape(', '.join(detail.requirement_keys))}")
    if detail.providers:
        parts.append(f"Providers: {', '.join(sorted(detail.providers))}")
    parts.append(f"Resolves to: {detail.source_kind}")
    preview = detail.body
    if len(preview) > 1000:
        cut = preview.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = preview[:cut] + "..."
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    return _html_message("\n".join(parts))


def runtime_skill_install_error_message(error_text: str) -> TelegramRenderedMessage:
    return _html_message(f"Registry install failed: {html.escape(error_text[:300])}")


def runtime_skill_updates_message(
    updates: tuple[RuntimeSkillUpdateStatusItem, ...],
) -> TelegramRenderedMessage:
    if not updates:
        return TelegramRenderedMessage(text="No imported skills found.")
    lines = ["<b>Imported skill status:</b>"]
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


def delegation_plan_message(delegation: PendingDelegation) -> TelegramRenderedMessage:
    lines = [
        "<b>Delegation plan</b>",
        "",
        "I'd like to delegate the following to specialist bots:",
        "",
    ]
    for index, task in enumerate(delegation.tasks, start=1):
        lines.extend([
            f"<b>{index}. {html.escape(task.title or task.routed_task_id)}</b>",
            f"\u2192 {html.escape(task.target_agent_id or 'unassigned')}",
            "",
        ])
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
