"""Telegram provider-guidance lifecycle commands."""

from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ParseMode

from app.runtime import composition


def _flows():
    return composition.workflows()


async def guidance_preview(event, update: Update, provider_name: str) -> None:
    preview = _flows().provider_guidance.preview.preview(
        provider_name,
        role="",
        active_skills=[],
        compact_mode=False,
    )
    await update.effective_message.reply_text(
        f"<b>{html.escape(provider_name)}</b>\n<pre>{html.escape(preview.effective_guidance)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def guidance_history(event, update: Update, provider_name: str) -> None:
    detail = _flows().provider_guidance.management.detail(provider_name)
    if detail is None:
        await update.effective_message.reply_text(
            f"Provider guidance <code>{html.escape(provider_name)}</code> not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines = [
        f"<b>{html.escape(provider_name)}</b>",
        f"Status: <code>{html.escape(detail.lifecycle_status)}</code>",
        f"Published revision: <code>{html.escape(detail.published_revision_id or '(none)')}</code>",
        "",
        "<b>Revisions</b>",
    ]
    for item in detail.revisions[:8]:
        pub = " [published]" if item.is_published else ""
        lines.append(f"  <code>{html.escape(item.revision_id[:12])}</code> — {html.escape(item.status)}{pub}")
    if detail.approvals:
        lines.append("")
        lines.append("<b>Approvals</b>")
        for item in detail.approvals[:8]:
            note = f" — {html.escape(item.note)}" if item.note else ""
            lines.append(f"  {html.escape(item.action)} by {html.escape(item.actor)}{note}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def guidance_edit(event, update: Update, provider_name: str, body: str) -> None:
    result = _flows().provider_guidance.management.edit_draft(
        provider_name,
        actor_key=str(event.user.id),
        body=body,
    )
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def guidance_submit(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.submit(provider_name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def guidance_approve(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.approve(provider_name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def guidance_reject(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.reject(provider_name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def guidance_publish(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.publish(provider_name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def guidance_archive(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.archive(provider_name, actor_key=str(event.user.id))
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)
