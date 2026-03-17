"""Subcommand handlers for /skills, extracted from telegram_handlers."""

import asyncio
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from app.request_flow import (
    foreign_setup_message,
    format_credential_prompt,
)
from app.skill_catalog_service import get_skill_catalog_service
from app.skill_import_service import get_skill_import_service
from app.skill_lifecycle_service import get_skill_lifecycle_service
from app.provider_guidance_service import get_provider_guidance_service
from app.skills import (
    load_user_credentials,
)


def _th():
    """Lazy import of telegram_handlers to avoid circular imports."""
    import app.telegram_handlers as th
    return th


async def skills_show(event, update: Update) -> None:
    catalog = get_skill_catalog_service().catalog()
    session = _th()._load(event.chat_id)
    active = get_skill_lifecycle_service().list_active(session)
    if active:
        lines = [f"<b>Active skills ({len(active)}):</b>"]
        for name in active:
            meta = catalog.get(name)
            display = meta.display_name if meta else name
            lines.append(f"  {html.escape(display)}")
    else:
        lines = ["<b>No active skills.</b>"]
    lines.append(f"\n{len(catalog)} skill(s) available. Use /skills list to see all.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_list(event, update: Update) -> None:
    catalog = get_skill_catalog_service().catalog()
    imports = get_skill_import_service()
    if not catalog:
        await update.effective_message.reply_text("No skills available.")
        return
    th = _th()
    session = th._load(event.chat_id)
    active = set(get_skill_lifecycle_service().list_active(session))
    req_user_id = event.user.id
    user_creds = load_user_credentials(th._cfg().data_dir, req_user_id, th._encryption_key())
    lines = ["<b>Available skills:</b>"]
    for name, meta in sorted(catalog.items()):
        requirements = get_skill_catalog_service().requirements(name)
        if name in active:
            status = " [active]"
        else:
            if requirements:
                skill_creds = user_creds.get(name, {})
                missing = [item for item in requirements if item.key not in skill_creds]
                status = " [needs setup]" if missing else " [ready]"
            else:
                status = ""
        if imports.has_custom_override(name):
            custom_tag = " [custom override]"
        elif meta.is_custom:
            custom_tag = " (custom)"
        elif imports.is_installed(name):
            custom_tag = " (imported)"
        else:
            custom_tag = ""
        desc = f" \u2014 {html.escape(meta.description)}" if meta.description else ""
        lines.append(f"  <code>{html.escape(name)}</code>{desc}{status}{custom_tag}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_add(event, update: Update, name: str) -> None:
    catalog = get_skill_catalog_service().catalog()
    lifecycle = get_skill_lifecycle_service()
    if name not in catalog:
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    th = _th()
    user_id = event.user.id
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        decision = lifecycle.begin_add(
            session,
            user_id=user_id,
            skill_name=name,
            data_dir=th._cfg().data_dir,
            encryption_key=th._encryption_key(),
        )
        if decision.mutated:
            th._save(chat_id, session)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.status == "needs_setup" and decision.first_requirement:
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> needs setup before activation.\n\n"
                f"{format_credential_prompt(decision.first_requirement)}",
                parse_mode=ParseMode.HTML,
            )
            return
        if decision.status == "needs_confirmation":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes", callback_data=f"skill_add_confirm:{name}"),
                InlineKeyboardButton("No", callback_data="skill_add_cancel"),
            ]])
            await update.effective_message.reply_text(
                f"Adding <code>{html.escape(name)}</code> would bring total "
                f"prompt context to ~{decision.projected_size:,} chars "
                f"(threshold: {decision.prompt_size_threshold:,}). "
                f"This may reduce response quality. Continue?",
                parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> activated.",
            parse_mode=ParseMode.HTML)


async def skills_remove(event, update: Update, name: str) -> None:
    th = _th()
    lifecycle = get_skill_lifecycle_service()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        decision = lifecycle.remove(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.mutated:
            th._save(chat_id, session)
        if decision.status == "removed":
            await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> deactivated.", parse_mode=ParseMode.HTML)
        else:
            await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> is not active.", parse_mode=ParseMode.HTML)


async def skills_setup(event, update: Update, name: str) -> None:
    lifecycle = get_skill_lifecycle_service()
    if not get_skill_catalog_service().has_skill(name):
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    th = _th()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        decision = lifecycle.begin_setup(session, user_id=event.user.id, skill_name=name)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.status == "no_requirements":
            await update.effective_message.reply_text(
                f"Skill <code>{html.escape(name)}</code> has no credential requirements.",
                parse_mode=ParseMode.HTML,
            )
            return
        if decision.mutated:
            th._save(chat_id, session)
    first_req = decision.first_requirement
    if not first_req:
        await update.effective_message.reply_text("Setup could not be started.")
        return
    await update.effective_message.reply_text(
        f"Setting up <code>{html.escape(name)}</code>.\n\n"
        f"{format_credential_prompt(first_req)}",
        parse_mode=ParseMode.HTML,
    )


async def skills_clear(event, update: Update) -> None:
    th = _th()
    lifecycle = get_skill_lifecycle_service()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        decision = lifecycle.clear(session, user_id=event.user.id)
        if decision.status == "foreign_setup":
            await update.effective_message.reply_text(
                foreign_setup_message(decision.foreign_setup or session.awaiting_skill_setup),
            )
            return
        if decision.mutated:
            th._save(chat_id, session)
    await update.effective_message.reply_text("All skills removed.")


async def skills_create(event, update: Update, name: str) -> None:
    try:
        record = get_skill_catalog_service().create_custom_draft(
            name,
            owner_actor=str(event.user.id),
        )
        await update.effective_message.reply_text(
            f"Created custom skill <code>{html.escape(name)}</code>\n"
            f"Draft visibility: <code>{html.escape(record.visibility)}</code>\n"
            "Use the registry UI or upcoming guided edit flow to update its instructions.",
            parse_mode=ParseMode.HTML,
        )
    except ValueError as e:
        await update.effective_message.reply_text(str(e))


async def skills_search(event, update: Update, query: str) -> None:
    imports = get_skill_import_service()
    results = imports.bundled_search(query)
    lines: list[str] = []
    if results:
        lines.append(f"<b>Catalog skills matching '{html.escape(query)}':</b>")
        for info in results:
            desc = f" \u2014 {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")

    # Search registry if configured
    registry_url = _th()._cfg().registry_url
    if registry_url:
        try:
            reg_results = await asyncio.to_thread(imports.registry_search, registry_url, query)
            # Exclude skills already in store results
            store_names = {r.name for r in results}
            reg_only = [r for r in reg_results if r.name not in store_names]
            if reg_only:
                lines.append(f"\n<b>Registry skills matching '{html.escape(query)}':</b>")
                for skill in reg_only:
                    desc = f" \u2014 {html.escape(skill.description)}" if skill.description else ""
                    pub = f" (by {html.escape(skill.publisher)})" if skill.publisher else ""
                    lines.append(f"  <code>{html.escape(skill.name)}</code>{desc}{pub}")
        except Exception as e:
            lines.append(f"\n<i>Registry search failed: {html.escape(str(e)[:200])}</i>")

    if not lines:
        await update.effective_message.reply_text(
            f"No skills matching '{html.escape(query)}'.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines.append("\nUse /skills info <name> for details, /skills install <name> to import from the registry.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_info(event, update: Update, name: str) -> None:
    result = get_skill_catalog_service().resolve_info(name)
    if not result:
        await update.effective_message.reply_text(
            f"Skill '{html.escape(name)}' not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    display_name = result.meta.get("display_name", name)
    description = result.meta.get("description", "")
    parts = [f"<b>{html.escape(display_name)}</b>"]
    if description:
        parts.append(html.escape(description))
    if result.requirement_keys:
        req_keys = ", ".join(result.requirement_keys)
        parts.append(f"Requires: {html.escape(req_keys)}")
    if result.providers:
        parts.append(f"Providers: {', '.join(sorted(result.providers))}")
    parts.append(f"Resolves to: {result.source}")
    if len(result.body) > 1000:
        cut = result.body.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = result.body[:cut] + "..."
    else:
        preview = result.body
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def skills_install(event, update: Update, name: str) -> None:
    th = _th()
    imports = get_skill_import_service()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can install skills.")
        return

    # Fall back to registry
    registry_url = th._cfg().registry_url
    if not registry_url:
        await update.effective_message.reply_text("No skill registry configured.", parse_mode=ParseMode.HTML)
        return

    try:
        result = await asyncio.to_thread(imports.install_from_registry, name, registry_url)
        await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.effective_message.reply_text(
            f"Registry install failed: {html.escape(str(e)[:300])}",
            parse_mode=ParseMode.HTML,
        )


async def skills_uninstall(event, update: Update, name: str) -> None:
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can uninstall imported skills.")
        return
    cfg = th._cfg()
    result = get_skill_import_service().uninstall(name, cfg.default_skills)
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_updates(event, update: Update) -> None:
    updates = get_skill_import_service().list_updates()
    if not updates:
        await update.effective_message.reply_text("No imported skills found.")
        return
    lines = ["<b>Imported skill status:</b>"]
    for item in updates:
        name = item.name
        status = item.status
        label = "update available" if status == "update_available" else "up to date"
        override = " [custom override]" if item.has_custom_override else ""
        lines.append(f"  <code>{html.escape(name)}</code> \u2014 {label}{override}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_diff(event, update: Update, name: str) -> None:
    diff_text = get_skill_import_service().diff(name).message
    if not diff_text.strip():
        diff_text = "No differences."
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n... (truncated)"
    await update.effective_message.reply_text(
        f"<pre>{html.escape(diff_text)}</pre>", parse_mode=ParseMode.HTML)


async def skills_update(event, update: Update, target: str) -> None:
    th = _th()
    guidance = get_provider_guidance_service()
    imports = get_skill_import_service()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can update imported skills.")
        return
    if target == "all":
        results = imports.update_all()
        if not results:
            await update.effective_message.reply_text("No imported skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        cfg = th._cfg()
        all_size_warnings: list[str] = []
        for result in results:
            status = "\u2714" if result.ok else "\u2718"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(
                    guidance.check_prompt_size_cross_chat(
                        cfg.data_dir,
                        result.name,
                        cfg.provider_name,
                        th._prov().new_provider_state,
                        cfg.approval_mode,
                    )
                )
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for w in all_size_warnings:
                lines.append(f"  {html.escape(w)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    else:
        result = imports.update(target)
        msg = result.message
        if result.ok:
            cfg = th._cfg()
            size_warnings = guidance.check_prompt_size_cross_chat(
                cfg.data_dir,
                target,
                cfg.provider_name,
                th._prov().new_provider_state,
                cfg.approval_mode,
            )
            if size_warnings:
                msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
