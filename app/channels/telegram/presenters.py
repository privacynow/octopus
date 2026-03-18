"""Telegram-channel presentation helpers."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app import user_messages as _msg
from app.approvals import format_denials_html
from app.workflows.provider_guidance.contracts import (
    ProviderGuidanceLifecycleDetail,
    ProviderGuidancePreview,
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
    return TelegramRenderedMessage(text=html.escape(message), parse_mode=ParseMode.HTML)
