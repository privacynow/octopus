"""Telegram-channel presentation helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from dataclasses import asdict, is_dataclass
from collections.abc import Mapping
from typing import Any, Iterable
from urllib.parse import urlparse

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


def _telegram_url_button(url: str, label: str) -> InlineKeyboardButton | None:
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    if host in {"registry", "localhost", "127.0.0.1", "::1"}:
        return None
    if "." not in host and not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return None
    return InlineKeyboardButton(label, url=url)


def _telegram_named_link(url: str, label: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return ""
    return f'<a href="{html.escape(str(url), quote=True)}">{html.escape(label)}</a>'


def _telegram_button_label(action: str, subject: str, max_length: int = 48) -> str:
    action_text = str(action or "").strip()
    subject_text = re.sub(r"\s+", " ", str(subject or "").strip())
    text = f"{action_text} {subject_text}".strip() if subject_text else action_text
    if len(text) <= max_length:
        return text
    suffix = "..."
    keep = max(max_length - len(suffix), 1)
    return text[:keep].rstrip() + suffix


def _short_run_id(run_id: str) -> str:
    value = str(run_id or "").strip()
    return value[:8] if len(value) > 8 else value


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

_PROTOCOL_CALLBACK_ACTIONS = frozenset({
    "auto_summary",
    "auto_stages",
    "auto_artifacts",
    "auto_warnings",
    "auto_apply",
    "auto_publish",
    "auto_run",
    "status",
    "artifacts",
    "preview",
    "open",
    "download",
    "runtime_start",
    "runtime_stop",
    "runtime_status",
    "export",
    "watch",
    "unwatch",
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


def protocol_callback_data(action: str, run_ref: str, artifact_ref: str = "") -> str:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _PROTOCOL_CALLBACK_ACTIONS:
        raise ValueError(f"Unknown protocol callback action: {action}")
    run_token = str(run_ref or "").strip()
    if not run_token:
        raise ValueError("Protocol callback run reference is required")
    artifact_token = str(artifact_ref or "").strip()
    parts = ["protocol", normalized_action, run_token]
    if artifact_token:
        parts.append(artifact_token)
    return ":".join(parts)


def parse_protocol_callback_data(data: str) -> tuple[str, str, str] | None:
    text = str(data or "").strip()
    parts = text.split(":", 3)
    if len(parts) < 3 or parts[0] != "protocol":
        return None
    action = parts[1].strip().lower()
    run_ref = parts[2].strip()
    artifact_ref = parts[3].strip() if len(parts) >= 4 else ""
    if action not in _PROTOCOL_CALLBACK_ACTIONS or not run_ref:
        return None
    return (action, run_ref, artifact_ref)


def _callback_button(label: str, action: str, run_ref: str, artifact_ref: str = "") -> InlineKeyboardButton | None:
    try:
        return InlineKeyboardButton(label, callback_data=protocol_callback_data(action, run_ref, artifact_ref))
    except ValueError:
        return None


def _append_button(row: list[InlineKeyboardButton], label: str, action: str, run_ref: str, artifact_ref: str = "") -> None:
    button = _callback_button(label, action, run_ref, artifact_ref)
    if button is not None:
        row.append(button)


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
    source_label = "current draft" if preview.preview_source == "draft" else "published policy"
    return TelegramRenderedMessage(
        text=(
            f"<b>{html.escape(provider_name)} runtime preview</b>\n"
            f"Preview source: <code>{html.escape(source_label)}</code>\n\n"
            f"<pre>{html.escape(preview.composed_prompt)}</pre>"
        ),
        parse_mode=ParseMode.HTML,
    )


def provider_guidance_show_message(
    provider_name: str,
    detail: ProviderGuidanceLifecycleDetail,
) -> TelegramRenderedMessage:
    published = detail.published_body.strip() or "(nothing published)"
    return TelegramRenderedMessage(
        text=(
            f"<b>{html.escape(provider_name)} published policy</b>\n"
            f"Status: <code>{html.escape(detail.lifecycle_status)}</code>\n"
            f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>\n\n"
            f"<pre>{html.escape(published)}</pre>"
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
        f"Published policy: {'yes' if detail.published_body else 'no'}",
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


def runtime_skill_active_summary_message(
    active_display_names: list[str],
    catalog_count: int,
    default_count: int = 0,
) -> TelegramRenderedMessage:
    if active_display_names:
        lines = [f"<b>Active in this conversation ({len(active_display_names)}):</b>"]
        for display in active_display_names:
            lines.append(f"  {html.escape(display)}")
    else:
        lines = ["<b>No skills active in this conversation.</b>"]
    lines.append(
        f"\nAvailable on this bot: {catalog_count} skill(s). "
        "Use /skills list for the bot catalog and /skills add <name> to activate one here."
    )
    if default_count:
        lines.append(
            f"Default for new conversations: {default_count} skill(s). "
            "Defaults seed new sessions only; they do not activate every existing conversation."
        )
    return _html_message("\n".join(lines))


def runtime_skill_catalog_message(
    catalog: list[RuntimeSkillCatalogItem],
    status_by_name: dict[str, str],
) -> TelegramRenderedMessage:
    if not catalog:
        return TelegramRenderedMessage(text="No skills are available on this bot.")
    lines = ["<b>Available on this bot:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        extra: list[str] = [item.source_label]
        if item.has_custom_override:
            extra.append("custom override")
        if item.default_for_new_conversations:
            extra.append("default for new conversations")
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
        f"Unknown skill: {html.escape(name)}. Use /skills list to see what is available on this bot."
    )


def runtime_skill_foreign_setup_message(setup) -> TelegramRenderedMessage:
    return TelegramRenderedMessage(text=foreign_setup_message(setup))


def runtime_skill_needs_setup_message(name: str, first_requirement: dict[str, Any]) -> TelegramRenderedMessage:
    return _html_message(
        f"Skill <code>{html.escape(name)}</code> is available on this bot but needs setup before it can be active in this conversation.\n\n"
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
        f"Publish ready: {'yes' if detail.publish_ready else 'no'}",
        f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>",
        f"Requirements: <code>{html.escape(', '.join(item.key for item in detail.requirements) or '(none)')}</code>",
        f"Files: <code>{len(detail.files)}</code>",
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
    if detail.validation_problems:
        lines.append("")
        lines.append("<b>Validation</b>")
        for item in detail.validation_problems[:8]:
            field_label = f"{item.field_path}: " if item.field_path else ""
            lines.append(f"  {html.escape(field_label + item.message)}")
    return _html_message("\n".join(lines))


def runtime_skill_package_export_message(name: str, revision_scope: str) -> TelegramRenderedMessage:
    scope = "published" if str(revision_scope or "").strip().lower() == "published" else "draft"
    return _html_message(
        f"Exported the <code>{html.escape(scope)}</code> package for <code>{html.escape(name)}</code>.\n"
        "Send a JSON/YAML skill package with the caption <code>/skills import</code>, or reply to a package with "
        "<code>/skills import &lt;target-name&gt;</code> to replace a specific custom draft."
    )


def runtime_skill_import_usage_message() -> TelegramRenderedMessage:
    return _html_message(
        "Attach or reply to a skill package JSON/YAML document, then use <code>/skills import</code>.\n"
        "Optionally add a target draft name: <code>/skills import &lt;target-name&gt;</code>."
    )


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
        lines.append(f"<b>Available on this bot matching '{html.escape(query)}':</b>")
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
        "Default for new conversations: "
        + ("yes" if detail.default_for_new_conversations else "no")
    )
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
    if detail.files:
        parts.append(f"Files: {len(detail.files)} attached")
    if detail.validation_problems:
        parts.append(f"Validation: {len(detail.validation_problems)} problem(s)")
    elif detail.publish_ready:
        parts.append("Validation: ready")
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
    "Skills have three runtime states: available on this bot, default for new conversations, and active in this conversation.\n\n"
    "/skills list — show what is available on this bot and what is active here\n"
    "/skills add &lt;name&gt; — activate an available skill in this conversation\n"
    "/skills remove &lt;name&gt; — deactivate a skill in this conversation\n"
    "/skills setup &lt;name&gt; — re-enter setup credentials for a skill\n"
    "/skills info &lt;name&gt; — view skill details\n"
    "/skills search &lt;query&gt; — search the skill store\n"
    "/skills install &lt;name&gt; — install a store skill on this bot\n"
    "/skills clear — deactivate all skills in this conversation\n"
    "/skills create &lt;name&gt; — create a custom draft skill on this bot\n"
    "/skills edit &lt;name&gt; &lt;body&gt; — replace the current draft body\n"
    "/skills export &lt;name&gt; [draft|published] — export a custom skill package document\n"
    "/skills import [&lt;target-name&gt;] — import a package document from the attached or replied file\n"
    "/skills history &lt;name&gt; — show revision and approval history\n"
    "/skills submit &lt;name&gt; — submit the draft for review\n"
    "/skills approve|reject|publish|archive &lt;name&gt; — lifecycle admin actions\n\n"
    "/guidance show &lt;provider&gt; — show the published provider policy\n"
    "/guidance preview &lt;provider&gt; — show the composed runtime prompt from the current draft\n"
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
        "Usage: /discover <query> [role:<role>] [skill:<skill>] [tag:<tag>] [state:<connected|degraded|standalone|disconnected>]\n"
        "Example: <code>/discover role:developer skill:architecture tag:backend schema review</code>"
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
        routing_skills = [str(value) for value in agent.get("routing_skills", []) if value]
        if routing_skills:
            lines.append(f"Routing skills: <code>{html.escape(', '.join(routing_skills))}</code>")
        tags = [str(value) for value in agent.get("tags", []) if value]
        if tags:
            lines.append(f"Tags: <code>{html.escape(', '.join(tags))}</code>")
        description = str(agent.get("description", "") or "").strip()
        if description:
            lines.append(html.escape(description))
    if len(agents) > 8:
        lines.append(f"\nShowing first 8 of {len(agents)} matches.")
    return _html_message("\n".join(lines))


def protocol_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text=(
            "Usage:\n"
            "/protocol list\n"
            "/protocol recent\n"
            "/protocol auto <requirement>\n"
            "/protocol auto modify latest|<session_id> <change request>\n"
            "/protocol auto status latest|<session_id>\n"
            "/protocol improve <slug> <change request>\n"
            "/protocol start <slug> <problem statement> [--context <text>] [--constraints <text>] [--workspace <ref>]\n"
            "/protocol status latest|<number|short_id>\n"
            "/protocol artifacts latest|<number|short_id>\n"
            "/protocol artifacts <run> download <artifact_number|artifact_key>\n"
            "/protocol preview <run> <artifact_number|artifact_key>\n"
            "/protocol export latest|<number|short_id>\n"
            "/protocol watch latest|<number|short_id>\n"
            "/protocol unwatch latest|<number|short_id>\n"
            "/protocol cancel <run> [reason]\n"
            "/protocol retry <run> [reason]\n"
            "/protocol accept <run> [reason]\n"
            "/protocol send-back <run> [reason]\n\n"
            "/protocol archive <run> [reason]\n"
            "/protocol restore <run> [reason]\n"
            "/protocol delete <run> confirm [reason]\n\n"
            "Tip: use <code>latest</code> or a number from <code>/protocol recent</code>; you do not need to copy a full run id."
        )
    )


def protocol_list_message(protocols: list[Any]) -> TelegramRenderedMessage:
    if not protocols:
        return TelegramRenderedMessage(text="No protocols are published in the registry yet.")
    lines = ["<b>Protocols</b>"]
    for raw in protocols[:12]:
        item = raw.model_dump() if hasattr(raw, "model_dump") else raw
        label = html.escape(str(item.get("display_name") or item.get("slug") or item.get("protocol_id") or "Protocol"))
        token = html.escape(str(item.get("slug") or item.get("protocol_id") or ""))
        lines.append(f"- {label} (<code>{token}</code>)")
    return _html_message("\n".join(lines))


def protocol_auto_session_message(
    session: Any,
    *,
    registry_link: str = "",
    view: str = "summary",
) -> TelegramRenderedMessage:
    data = session.model_dump(mode="json") if hasattr(session, "model_dump") else dict(session or {})
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    validation = data.get("validation") if isinstance(data.get("validation"), dict) else {}
    session_id = str(data.get("session_id") or "")
    title = html.escape(str(plan.get("protocol_name") or "Generated protocol"))
    focus = html.escape(str(analysis.get("focus") or analysis.get("domain") or "requirement-specific"))
    skills = analysis.get("skills") if isinstance(analysis.get("skills"), list) else []
    work_packages = analysis.get("work_packages") if isinstance(analysis.get("work_packages"), list) else []
    status = html.escape(str(data.get("status") or "draft"))
    planning = str(data.get("status") or "") == "planning"
    stages = plan.get("stages") if isinstance(plan.get("stages"), list) else []
    artifacts = plan.get("artifacts") if isinstance(plan.get("artifacts"), list) else []
    primary = plan.get("primary_artifact") if isinstance(plan.get("primary_artifact"), dict) else {}
    review_count = sum(1 for stage in stages if isinstance(stage, dict) and str(stage.get("stage_kind") or "") == "review")
    unresolved = list(data.get("unresolved_decisions") if isinstance(data.get("unresolved_decisions"), list) else [])
    warnings = [
        *unresolved,
        *list(data.get("warnings") if isinstance(data.get("warnings"), list) else []),
    ]
    ready = bool(validation.get("ok")) and not unresolved
    normalized_view = str(view or "summary").strip().lower()
    lines = [
        "<b>Auto Protocol</b>",
        f"Protocol: <code>{title}</code>",
        f"Focus: <code>{focus}</code>",
        f"Design: <code>{html.escape(str(analysis.get('domain') or 'requirement-specific'))}</code>",
        f"Status: <code>{status}</code>",
        f"Work packages: <code>{len(work_packages)}</code> · Reviews: <code>{review_count}</code>",
        f"Stages: <code>{len(stages)}</code> · Artifacts: <code>{len(artifacts)}</code>",
        f"Validation: <code>{'ready' if validation.get('ok') else 'needs attention'}</code>",
    ]
    if planning:
        lines.append("Planner status: analyzing requirements, lessons, stages, artifacts, assignments, review gates, and runtime evidence.")
    primary_label = html.escape(str(primary.get("display_name") or primary.get("artifact_key") or "Produced Outcome"))
    primary_key = html.escape(str(primary.get("artifact_key") or "produced_outcome"))
    lines.append(f"Primary outcome: {primary_label} <code>{primary_key}</code>")
    if skills:
        skill_text = ", ".join(html.escape(str(item)) for item in skills[:5])
        lines.append(f"Skills: {skill_text}")
    if normalized_view == "summary" and work_packages:
        lines.append("\n<b>Work packages</b>")
        for index, package in enumerate(work_packages[:6], start=1):
            label = html.escape(str(package.get("display_name") or package.get("package_key") or "Work package"))
            rationale = re.sub(r"\s+", " ", str(package.get("rationale") or package.get("purpose") or "").strip())
            if len(rationale) > 140:
                rationale = rationale[:137].rstrip() + "..."
            lines.append(f"{index}. {label}")
            if rationale:
                lines.append(f"   {html.escape(rationale)}")
    if normalized_view == "artifacts":
        lines.append("\n<b>Artifacts</b>")
        for index, artifact in enumerate(artifacts[:12], start=1):
            label = html.escape(str(artifact.get("display_name") or artifact.get("artifact_key") or "Artifact"))
            path = html.escape(str(artifact.get("path") or ""))
            lines.append(f"{index}. {label}" + (f" <code>{path}</code>" if path else ""))
        if not artifacts:
            lines.append("No artifacts were declared.")
    elif normalized_view == "warnings":
        lines.append("\n<b>Warnings</b>")
        if warnings:
            for warning in warnings[:8]:
                item = warning if isinstance(warning, dict) else {}
                message = html.escape(str(item.get("message") or item.get("code") or "Review before publishing."))
                lines.append(f"- {message}")
        else:
            lines.append("No blocking warnings.")
    else:
        lines.append("\n<b>Stages</b>")
        limit = 12 if normalized_view == "stages" else 8
        for index, stage in enumerate(stages[:limit], start=1):
            label = html.escape(str(stage.get("display_name") or stage.get("stage_key") or "Stage"))
            kind = html.escape(str(stage.get("stage_kind") or "work"))
            role = html.escape(str(stage.get("role_key") or ""))
            role_text = f" · <code>{role}</code>" if role else ""
            lines.append(f"{index}. {label} <code>{kind}</code>{role_text}")
            if normalized_view == "stages":
                purpose = re.sub(r"\s+", " ", str(stage.get("purpose") or "").strip())
                if len(purpose) > 180:
                    purpose = purpose[:177].rstrip() + "..."
                outputs = stage.get("outputs") if isinstance(stage.get("outputs"), list) else []
                output_text = ", ".join(str(item) for item in outputs if str(item or "").strip()) or "none"
                if purpose:
                    lines.append(f"   {html.escape(purpose)}")
                lines.append(f"   Outputs: <code>{html.escape(output_text)}</code>")
        if len(stages) > limit:
            lines.append(f"...and {len(stages) - limit} more stages.")
        if warnings:
            first = warnings[0] if isinstance(warnings[0], dict) else {}
            message = html.escape(str(first.get("message") or first.get("code") or "Review warnings before publishing."))
            lines.append(f"Note: {message}")
    if session_id:
        lines.append(f"Modify: <code>/protocol auto modify latest &lt;change&gt;</code>")
    if registry_link:
        lines.append(f"<a href=\"{html.escape(registry_link)}\">Open in Registry</a>")
    keyboard: list[list[InlineKeyboardButton]] = []
    if session_id:
        keyboard.append([
            InlineKeyboardButton("Summary", callback_data=protocol_callback_data("auto_summary", session_id)),
            InlineKeyboardButton("Stages", callback_data=protocol_callback_data("auto_stages", session_id)),
        ])
        keyboard.append([
            InlineKeyboardButton("Artifacts", callback_data=protocol_callback_data("auto_artifacts", session_id)),
            InlineKeyboardButton("Warnings", callback_data=protocol_callback_data("auto_warnings", session_id)),
        ])
        if not planning:
            keyboard.append([
                InlineKeyboardButton("Apply draft", callback_data=protocol_callback_data("auto_apply", session_id)),
            ])
        if ready:
            keyboard.append([
                InlineKeyboardButton("Publish", callback_data=protocol_callback_data("auto_publish", session_id)),
                InlineKeyboardButton("Publish & Run", callback_data=protocol_callback_data("auto_run", session_id)),
            ])
        if registry_link:
            keyboard.append([InlineKeyboardButton("Open in Registry", url=registry_link)])
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        disable_web_page_preview=True,
    )


def protocol_run_started_message(
    *,
    run_id: str,
    protocol_label: str,
    current_stage: str,
    deep_link: str = "",
    watching: bool,
) -> TelegramRenderedMessage:
    run_short = _short_run_id(run_id)
    lines = [
        "<b>Protocol run started</b>",
        f"Run: <code>{html.escape(run_short)}</code> (also available as <code>latest</code>)",
        f"Protocol: <code>{html.escape(protocol_label)}</code>",
        f"Current stage: <code>{html.escape(current_stage or 'queued')}</code>",
        f"Notifications: <code>{'watching' if watching else 'not watching'}</code>",
        "Next: tap Status or Artifacts below.",
    ]
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    action_row: list[InlineKeyboardButton] = []
    _append_button(action_row, "Status", "status", run_id)
    _append_button(action_row, "Artifacts", "artifacts", run_id)
    if watching:
        _append_button(action_row, "Stop updates", "unwatch", run_id)
    else:
        _append_button(action_row, "Watch", "watch", run_id)
    if action_row:
        keyboard_rows.append(action_row)
    if deep_link:
        button = _telegram_url_button(deep_link, "Open in Registry")
        if button is not None:
            lines.append("Open the run in Registry from the button below.")
            keyboard_rows.append([button])
        else:
            fallback = _telegram_named_link(deep_link, "Registry run")
            if fallback:
                lines.append(f"Open in Registry: {fallback}")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
        disable_web_page_preview=True,
    )


def protocol_recent_runs_message(runs: list[Any], *, run_links: Mapping[str, str] | None = None) -> TelegramRenderedMessage:
    if not runs:
        return TelegramRenderedMessage(text="No recent protocol runs are visible yet.")
    links = run_links or {}
    lines = [
        "<b>Recent protocol runs</b>",
        "Tap a run action below. You can also use the number, <code>latest</code>, or the short id in commands.",
    ]
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for index, raw in enumerate(runs[:10], start=1):
        item = raw.model_dump() if hasattr(raw, "model_dump") else raw
        run_id = str(item.get("protocol_run_id") or "").strip()
        short_id = run_id[:8] if len(run_id) > 8 else run_id
        protocol = str(item.get("protocol_display_name") or item.get("protocol_id") or "Protocol").strip()
        status = str(item.get("status") or "queued").strip()
        stage = str(item.get("current_stage_key") or "no active stage").strip()
        lines.append(f"{index}. {html.escape(protocol)} · <code>{html.escape(status)}</code> · {html.escape(stage)} · <code>{html.escape(short_id)}</code>")
        if run_id and len(keyboard_rows) < 10:
            row: list[InlineKeyboardButton] = []
            _append_button(row, f"Run {index} status", "status", run_id)
            _append_button(row, f"Run {index} artifacts", "artifacts", run_id)
            if row:
                keyboard_rows.append(row)
        link = str(links.get(run_id) or "").strip()
        if link:
            button = _telegram_url_button(link, f"Open run {index}")
            if button is not None:
                keyboard_rows.append([button])
            else:
                fallback = _telegram_named_link(link, "Open")
                if fallback:
                    lines[-1] += f" · {fallback}"
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard_rows[:6]) if keyboard_rows else None,
        disable_web_page_preview=True,
    )


def protocol_run_status_message(
    detail,
    *,
    deep_link: str = "",
    watching: bool = False,
) -> TelegramRenderedMessage:
    run = detail.run
    run_short = run.protocol_run_id[:8] if len(run.protocol_run_id) > 8 else run.protocol_run_id
    run_id = str(run.protocol_run_id or "").strip()
    lines = [
        f"Run: <code>{html.escape(run_short)}</code>",
        f"Status: <code>{html.escape(run.status)}</code>",
        f"Version: <code>{html.escape(str(run.version or 1))}</code>",
        (
            f"Final stage: <code>{html.escape(run.current_stage_key or 'n/a')}</code>"
            if str(run.status or "").strip().lower() in {"completed", "failed", "cancelled", "canceled"}
            else f"Current stage: <code>{html.escape(run.current_stage_key or 'n/a')}</code>"
        ),
        f"Workspace: <code>{html.escape(run.workspace_ref or 'default')}</code>",
        f"Notifications: <code>{'watching' if watching else 'not watching'}</code>",
    ]
    if run.termination_summary:
        lines.append(f"Summary: {html.escape(run.termination_summary)}")
    if run.blocked_detail:
        lines.append(f"Blocked: {html.escape(run.blocked_detail)}")
    if detail.participants:
        participants = ", ".join(
            f"{html.escape(item.participant_key)}:{html.escape(item.state or item.resolution_outcome or 'queued')}"
            for item in detail.participants[:6]
        )
        lines.append(f"Participants: <code>{participants}</code>")
    if detail.artifacts:
        artifacts = ", ".join(
            f"{index + 1}.{html.escape(item.artifact_key)}:{html.escape(item.verification_state or item.state or 'declared')}"
            for index, item in enumerate(detail.artifacts[:6])
        )
        lines.append(f"Artifacts: <code>{artifacts}</code>")
        lines.append("Artifacts: tap Artifacts below.")
    if str(run.status or "").strip().lower() in {"completed", "failed", "cancelled", "archived"}:
        lines.append("Lifecycle: archive/delete controls are available in Registry; Telegram commands use the same Registry API.")
    if detail.stage_executions:
        latest = detail.stage_executions[0]
        lines.append(f"Latest stage: <code>{html.escape(latest.stage_key)} ({html.escape(latest.status)})</code>")
        if latest.decision_summary:
            lines.append(f"Latest summary: {html.escape(latest.decision_summary)}")
        elif latest.failure_detail:
            lines.append(f"Latest failure: {html.escape(latest.failure_detail)}")
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    action_row: list[InlineKeyboardButton] = []
    _append_button(action_row, "Artifacts", "artifacts", run_id)
    _append_button(action_row, "Export", "export", run_id)
    if watching:
        _append_button(action_row, "Stop updates", "unwatch", run_id)
    else:
        _append_button(action_row, "Watch", "watch", run_id)
    if action_row:
        keyboard_rows.append(action_row)
    if deep_link:
        button = _telegram_url_button(deep_link, "Open in Registry")
        if button is not None:
            lines.append("Open the run in Registry from the button below.")
            keyboard_rows.append([button])
        else:
            fallback = _telegram_named_link(deep_link, "Registry run")
            if fallback:
                lines.append(f"Open in Registry: {fallback}")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
        disable_web_page_preview=True,
    )


def protocol_run_artifacts_message(
    detail,
    *,
    deep_link: str = "",
    artifact_links: dict[str, str | Mapping[str, str]] | None = None,
) -> TelegramRenderedMessage:
    run = detail.run
    links = artifact_links or {}
    if not detail.artifacts:
        run_short = _short_run_id(run.protocol_run_id)
        lines = [
            "<b>Protocol artifacts</b>",
            f"Run: <code>{html.escape(run_short)}</code>",
            "No artifacts are declared for this run yet.",
        ]
        keyboard_rows: list[list[InlineKeyboardButton]] = []
        action_row: list[InlineKeyboardButton] = []
        _append_button(action_row, "Status", "status", run.protocol_run_id)
        _append_button(action_row, "Export", "export", run.protocol_run_id)
        if action_row:
            keyboard_rows.append(action_row)
        if deep_link:
            button = _telegram_url_button(deep_link, "Open in Registry")
            if button is not None:
                lines.append("Open the run in Registry from the button below.")
                keyboard_rows.append([button])
            else:
                fallback = _telegram_named_link(deep_link, "Registry run")
                if fallback:
                    lines.append(f"Open in Registry: {fallback}")
        return TelegramRenderedMessage(
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
            disable_web_page_preview=True,
        )

    run_short = _short_run_id(run.protocol_run_id)
    lines = [
        "<b>Protocol artifacts</b>",
        f"Run: <code>{html.escape(run_short)}</code>",
        "Tap an artifact action below. Numbers are shown only as command fallbacks.",
    ]
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    if deep_link:
        button = _telegram_url_button(deep_link, "Open Run in Registry")
        if button is not None:
            keyboard_rows.append([button])
    featured_artifact: dict[str, str] | None = None
    for index, item in enumerate(detail.artifacts[:12], start=1):
        key = str(getattr(item, "artifact_key", "") or "artifact").strip()
        display_name = str(getattr(item, "display_name", "") or "").strip()
        state = str(
            getattr(item, "verification_state", "")
            or getattr(item, "state", "")
            or "declared"
        ).strip()
        exists = bool(getattr(item, "exists", False))
        path = str(
            getattr(item, "workspace_path", "")
            or getattr(item, "location", "")
            or ""
        ).strip()
        size = int(getattr(item, "size_bytes", 0) or 0)
        status = state or ("available" if exists else "declared")
        if exists and status == "declared":
            status = "available"
        basename = path.rsplit("/", 1)[-1] if path else ""
        label = display_name or basename or key
        line = f"{index}. {html.escape(label)}: <code>{html.escape(status)}</code>"
        if path:
            line += f" · {html.escape(basename or path)}"
        if size > 0:
            line += f" · {html.escape(str(size))} bytes"
        raw_links = links.get(key, "")
        preview_link = ""
        open_link = ""
        browse_link = ""
        runtime_link = ""
        download_link = ""
        if isinstance(raw_links, Mapping):
            preview_link = str(raw_links.get("preview") or "")
            open_link = str(raw_links.get("open") or "")
            browse_link = str(raw_links.get("browse") or "")
            runtime_link = str(raw_links.get("runtime") or "")
            download_link = str(raw_links.get("download") or "")
        else:
            download_link = str(raw_links or "")
        if exists and (open_link or download_link):
            actions: list[str] = []
            if preview_link:
                fallback = _telegram_named_link(preview_link, "Preview")
                if fallback:
                    actions.append(fallback)
            if browse_link:
                open_fallback = _telegram_named_link(open_link, "Open app")
                browse_fallback = _telegram_named_link(browse_link, "Contents")
                if open_fallback:
                    actions.append(open_fallback)
                if browse_fallback:
                    actions.append(browse_fallback)
            elif open_link and not preview_link:
                fallback = _telegram_named_link(open_link, "Open")
                if fallback:
                    actions.append(fallback)
            if download_link:
                fallback = _telegram_named_link(download_link, "Download")
                if fallback:
                    actions.append(fallback)
            if actions:
                line += " · " + " · ".join(actions)
            if not (browse_link or runtime_link):
                artifact_row: list[InlineKeyboardButton] = []
                if preview_link:
                    button = _telegram_url_button(
                        preview_link,
                        _telegram_button_label("Preview", label),
                    )
                    if button is not None:
                        artifact_row.append(button)
                if open_link:
                    button = _telegram_url_button(
                        open_link,
                        _telegram_button_label("Open", label),
                    )
                    if button is not None:
                        artifact_row.append(button)
                if download_link:
                    _append_button(
                        artifact_row,
                        _telegram_button_label("Send", label),
                        "download",
                        run.protocol_run_id,
                        str(index),
                    )
                if artifact_row:
                    keyboard_rows.append(artifact_row)
            if featured_artifact is None and (browse_link or runtime_link):
                featured_artifact = {
                    "artifact_ref": str(index),
                    "download_link": download_link,
                }
        elif not exists:
            line += " · not produced yet"
        lines.append(line)
    if featured_artifact:
        runtime_row: list[InlineKeyboardButton] = []
        artifact_ref = featured_artifact["artifact_ref"]
        _append_button(runtime_row, "Start app", "runtime_start", run.protocol_run_id, artifact_ref)
        if runtime_row:
            keyboard_rows.append(runtime_row)
        secondary_row: list[InlineKeyboardButton] = []
        if featured_artifact.get("download_link"):
            _append_button(secondary_row, "Send package", "download", run.protocol_run_id, artifact_ref)
        if secondary_row:
            keyboard_rows.append(secondary_row)
    if len(detail.artifacts) > 12:
        lines.append(f"Showing first 12 of {len(detail.artifacts)} artifacts.")
    if deep_link:
        has_run_button = bool(
            keyboard_rows
            and any(getattr(button, "text", "") == "Open Run in Registry" for button in keyboard_rows[0])
        )
        if has_run_button:
            lines.append("Open the full run in Registry from the button below.")
        else:
            fallback = _telegram_named_link(deep_link, "Registry run")
            if fallback:
                lines.append(f"Open full run: {fallback}")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None,
        disable_web_page_preview=True,
    )


def protocol_artifact_preview_message(
    *,
    run_id: str,
    artifact_label: str,
    preview_link: str = "",
    open_link: str = "",
    runtime_link: str = "",
    download_link: str = "",
    artifact_ref: str = "",
    open_label: str = "Open",
) -> TelegramRenderedMessage:
    short_id = _short_run_id(run_id)
    lines = [
        "<b>Artifact preview</b>",
        f"Run: <code>{html.escape(short_id)}</code>",
        f"Artifact: {html.escape(artifact_label)}",
    ]
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    if preview_link:
        button = _telegram_url_button(preview_link, "Rendered Preview")
        if button is not None:
            row.append(button)
        else:
            fallback = _telegram_named_link(preview_link, "Rendered preview")
            if fallback:
                lines.append(f"Rendered preview: {fallback}")
    if open_link:
        button = _telegram_url_button(open_link, open_label)
        if button is not None:
            row.append(button)
        else:
            fallback = _telegram_named_link(open_link, open_label)
            if fallback:
                lines.append(f"{html.escape(open_label)}: {fallback}")
    if runtime_link:
        if artifact_ref:
            _append_button(row, "Start app", "runtime_start", run_id, artifact_ref)
        if not artifact_ref:
            fallback = _telegram_named_link(runtime_link, "Running app")
            if fallback:
                lines.append(f"Running app: {fallback}")
    if download_link:
        if artifact_ref:
            _append_button(
                row,
                _telegram_button_label("Send", artifact_label),
                "download",
                run_id,
                artifact_ref,
            )
        fallback = _telegram_named_link(download_link, "Download")
        if fallback:
            lines.append(f"Download: {fallback}")
    if artifact_ref:
        _append_button(row, "Artifacts", "artifacts", run_id)
    if row:
        keyboard.append(row)
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        disable_web_page_preview=True,
    )


def protocol_artifact_runtime_message(
    *,
    run_id: str,
    artifact_label: str,
    status: str,
    message: str,
    runtime_link: str = "",
    package_link: str = "",
    artifact_ref: str = "",
) -> TelegramRenderedMessage:
    short_id = _short_run_id(run_id)
    lines = [
        "<b>Artifact app</b>",
        f"Run: <code>{html.escape(short_id)}</code>",
        f"Artifact: {html.escape(artifact_label)}",
        f"Status: <code>{html.escape(status or 'unknown')}</code>",
    ]
    if message:
        lines.append(html.escape(message))
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    normalized_status = str(status or "").strip().lower()
    if runtime_link and normalized_status == "running":
        button = _telegram_url_button(runtime_link, "Open app")
        if button is not None:
            row.append(button)
        else:
            fallback = _telegram_named_link(runtime_link, "Open app")
            if fallback:
                lines.append(f"Open app: {fallback}")
    if artifact_ref:
        if normalized_status not in {"running", "starting"}:
            _append_button(row, "Start app", "runtime_start", run_id, artifact_ref)
        _append_button(row, "Status", "runtime_status", run_id, artifact_ref)
        if normalized_status in {"running", "starting"}:
            _append_button(row, "Stop", "runtime_stop", run_id, artifact_ref)
        _append_button(row, "Artifacts", "artifacts", run_id)
    if package_link:
        fallback = _telegram_named_link(package_link, "Download package")
        if fallback:
            lines.append(f"Download: {fallback}")
    if row:
        keyboard.append(row)
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        disable_web_page_preview=True,
    )


def protocol_action_confirmation_message(
    *,
    action: str,
    run_id: str,
    reason: str,
    deep_link: str = "",
) -> TelegramRenderedMessage:
    run_short = _short_run_id(run_id)
    reason_text = html.escape(reason or "No reason provided.")
    lines = [
        f"<b>Confirm protocol action</b>",
        f"Action: <code>{html.escape(action)}</code>",
        f"Run: <code>{html.escape(run_short)}</code>",
        f"Reason: {reason_text}",
        "",
        "Repeat the command with <code>confirm</code> before the reason to apply it.",
        f"<code>/protocol {html.escape(action)} {html.escape(run_short)} confirm {reason_text}</code>",
    ]
    if deep_link:
        lines.append(f"<a href=\"{html.escape(deep_link)}\">Open in registry</a>")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def protocol_run_updated_message(
    *,
    run_id: str,
    status: str,
    current_stage: str,
    deep_link: str = "",
) -> TelegramRenderedMessage:
    run_short = _short_run_id(run_id)
    lines = [
        "<b>Protocol run updated</b>",
        f"Run: <code>{html.escape(run_short)}</code>",
        f"Status: <code>{html.escape(status)}</code>",
        f"Current stage: <code>{html.escape(current_stage or 'n/a')}</code>",
    ]
    if deep_link:
        lines.append(f"<a href=\"{html.escape(deep_link)}\">Open in registry</a>")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def protocol_watch_changed_message(
    *,
    run_id: str,
    watching: bool,
    deep_link: str = "",
) -> TelegramRenderedMessage:
    run_short = _short_run_id(run_id)
    lines = [
        f"Protocol notifications <b>{'enabled' if watching else 'disabled'}</b>.",
        f"Run: <code>{html.escape(run_short)}</code>",
    ]
    if deep_link:
        lines.append(f"<a href=\"{html.escape(deep_link)}\">Open in registry</a>")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


def protocol_run_notification_message(detail, *, deep_link: str = "") -> TelegramRenderedMessage:
    run = detail.run
    latest = detail.stage_executions[0] if detail.stage_executions else None
    run_short = _short_run_id(run.protocol_run_id)
    lines = [
        "<b>Protocol run update</b>",
        f"Run: <code>{html.escape(run_short)}</code>",
        f"Status: <code>{html.escape(run.status)}</code>",
        f"Current stage: <code>{html.escape(run.current_stage_key or 'n/a')}</code>",
    ]
    if latest is not None:
        lines.append(f"Latest stage: <code>{html.escape(latest.stage_key)} ({html.escape(latest.status)})</code>")
        if latest.decision_summary:
            lines.append(f"Summary: {html.escape(latest.decision_summary)}")
        elif latest.failure_detail:
            lines.append(f"Failure: {html.escape(latest.failure_detail)}")
    if run.blocked_detail:
        lines.append(f"Blocked: {html.escape(run.blocked_detail)}")
    if run.termination_summary:
        lines.append(f"Outcome: {html.escape(run.termination_summary)}")
    if deep_link:
        lines.append(f"<a href=\"{html.escape(deep_link)}\">Open in registry</a>")
    return TelegramRenderedMessage(
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


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
        text="Usage: /skills [list|add|remove|setup|create|edit|export|import|history|submit|approve|reject|publish|archive|clear|search|info|install|uninstall|updates|update|diff]"
    )


def guidance_usage_message() -> TelegramRenderedMessage:
    return TelegramRenderedMessage(
        text="Usage: /guidance [show|preview|edit|history|submit|approve|reject|publish|archive] <provider> [body]"
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
