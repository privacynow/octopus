"""Telegram provider-guidance lifecycle commands."""

from __future__ import annotations

from telegram import Update

from app.channels.telegram import presenters as telegram_presenters
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
    rendered = telegram_presenters.provider_guidance_preview_message(provider_name, preview)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_history(event, update: Update, provider_name: str) -> None:
    detail = _flows().provider_guidance.management.detail(provider_name)
    if detail is None:
        rendered = telegram_presenters.provider_guidance_not_found_message(provider_name)
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    rendered = telegram_presenters.provider_guidance_history_message(provider_name, detail)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_edit(event, update: Update, provider_name: str, body: str) -> None:
    result = _flows().provider_guidance.management.edit_draft(
        provider_name,
        actor_key=str(event.user.id),
        body=body,
    )
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_submit(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.submit(provider_name, actor_key=str(event.user.id))
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_approve(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.approve(provider_name, actor_key=str(event.user.id))
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_reject(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.reject(provider_name, actor_key=str(event.user.id))
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_publish(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.publish(provider_name, actor_key=str(event.user.id))
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def guidance_archive(event, update: Update, provider_name: str) -> None:
    result = _flows().provider_guidance.management.archive(provider_name, actor_key=str(event.user.id))
    rendered = telegram_presenters.provider_guidance_mutation_message(result.message)
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())


async def handle_guidance_command(
    event,
    update: Update,
    *,
    is_admin: bool,
) -> None:
    args = event.args
    if len(args) < 2:
        rendered = telegram_presenters.guidance_usage_message()
        await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
        return
    sub = args[0].lower()
    provider_name = args[1]
    if sub == "preview":
        await guidance_preview(event, update, provider_name)
        return
    if sub == "history":
        await guidance_history(event, update, provider_name)
        return
    if sub == "edit" and len(args) >= 3:
        await guidance_edit(event, update, provider_name, " ".join(args[2:]))
        return
    if sub == "submit":
        await guidance_submit(event, update, provider_name)
        return
    if sub == "approve":
        if not is_admin:
            rendered = telegram_presenters.guidance_admin_only_message("approve")
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        await guidance_approve(event, update, provider_name)
        return
    if sub == "reject":
        if not is_admin:
            rendered = telegram_presenters.guidance_admin_only_message("reject")
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        await guidance_reject(event, update, provider_name)
        return
    if sub == "publish":
        if not is_admin:
            rendered = telegram_presenters.guidance_admin_only_message("publish")
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        await guidance_publish(event, update, provider_name)
        return
    if sub == "archive":
        if not is_admin:
            rendered = telegram_presenters.guidance_admin_only_message("archive")
            await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
            return
        await guidance_archive(event, update, provider_name)
        return
    rendered = telegram_presenters.guidance_usage_message()
    await update.effective_message.reply_text(rendered.text, **rendered.kwargs())
