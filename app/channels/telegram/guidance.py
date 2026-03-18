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
