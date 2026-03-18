"""Subcommand handlers for /skills, extracted from telegram_handlers."""

import asyncio
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from app.credential_flow import (
    foreign_setup_message,
    format_credential_prompt,
)
from app.inbound_use_case_factory import (
    get_credential_management_use_cases,
    get_runtime_skill_activation_use_cases,
    get_runtime_skill_catalog_use_cases,
    get_runtime_skill_import_use_cases,
)


def _th():
    """Lazy import of telegram_handlers to avoid circular imports."""
    import app.telegram_handlers as th
    return th


async def skills_show(event, update: Update) -> None:
    catalog = {item.name: item for item in get_runtime_skill_catalog_use_cases().list_skills()}
    th = _th()
    session = th._load(event.chat_id)
    resolved = th._resolve_context(session, trust_tier=th._trust_tier(event.user))
    active = get_runtime_skill_activation_use_cases().list_conversation_skills(
        list(resolved.active_skills)
    ).active_skills
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
    catalog = get_runtime_skill_catalog_use_cases().list_skills()
    if not catalog:
        await update.effective_message.reply_text("No skills available.")
        return
    th = _th()
    session = th._load(event.chat_id)
    resolved = th._resolve_context(session, trust_tier=th._trust_tier(event.user))
    active = set(
        get_runtime_skill_activation_use_cases().list_conversation_skills(
            list(resolved.active_skills)
        ).active_skills
    )
    req_user_id = event.user.id
    user_creds = get_credential_management_use_cases().load_credentials(
        th._actor_key(req_user_id)
    )
    lines = ["<b>Available skills:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        name = item.name
        if name in active:
            status = " [active]"
        else:
            if item.requirement_keys:
                skill_creds = user_creds.get(name, {})
                missing = get_runtime_skill_catalog_use_cases().missing_requirements(name, skill_creds)
                status = " [needs setup]" if missing else " [ready]"
            else:
                status = ""
        if item.has_custom_override:
            custom_tag = " [custom override]"
        elif item.source_kind == "custom":
            custom_tag = " (custom)"
        elif item.source_kind == "imported":
            custom_tag = " (imported)"
        else:
            custom_tag = ""
        desc = f" \u2014 {html.escape(item.description)}" if item.description else ""
        lines.append(f"  <code>{html.escape(name)}</code>{desc}{status}{custom_tag}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_add(event, update: Update, name: str) -> None:
    lifecycle = get_runtime_skill_activation_use_cases()
    if not get_runtime_skill_catalog_use_cases().has_skill(name):
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
        decision = lifecycle.begin_activate(
            session,
            user_id=user_id,
            skill_name=name,
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
    lifecycle = get_runtime_skill_activation_use_cases()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        decision = lifecycle.deactivate(session, user_id=event.user.id, skill_name=name)
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
    lifecycle = get_runtime_skill_activation_use_cases()
    if not get_runtime_skill_catalog_use_cases().has_skill(name):
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
    lifecycle = get_runtime_skill_activation_use_cases()
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
        record = get_runtime_skill_catalog_use_cases().create_custom_draft(
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
    results = await asyncio.to_thread(
        get_runtime_skill_import_use_cases().search,
        query,
        registry_url=_th()._cfg().registry_url,
    )
    lines: list[str] = []
    if results.catalog:
        lines.append(f"<b>Catalog skills matching '{html.escape(query)}':</b>")
        for info in results.catalog:
            desc = f" \u2014 {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")
    if results.registry:
        local_names = {item.name for item in results.catalog}
        reg_only = [item for item in results.registry if item.name not in local_names]
        if reg_only:
            lines.append(f"\n<b>Registry skills matching '{html.escape(query)}':</b>")
            for skill in reg_only:
                desc = f" \u2014 {html.escape(skill.description)}" if skill.description else ""
                pub = f" (by {html.escape(skill.publisher)})" if skill.publisher else ""
                lines.append(f"  <code>{html.escape(skill.name)}</code>{desc}{pub}")
    if results.registry_error:
        lines.append(f"\n<i>Registry search failed: {html.escape(results.registry_error)}</i>")

    if not lines:
        await update.effective_message.reply_text(
            f"No skills matching '{html.escape(query)}'.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines.append("\nUse /skills info <name> for details, /skills install <name> to import from the registry.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_info(event, update: Update, name: str) -> None:
    result = get_runtime_skill_catalog_use_cases().get_skill(name)
    if not result:
        await update.effective_message.reply_text(
            f"Skill '{html.escape(name)}' not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    parts = [f"<b>{html.escape(result.display_name)}</b>"]
    if result.description:
        parts.append(html.escape(result.description))
    if result.requirement_keys:
        req_keys = ", ".join(result.requirement_keys)
        parts.append(f"Requires: {html.escape(req_keys)}")
    if result.providers:
        parts.append(f"Providers: {', '.join(sorted(result.providers))}")
    parts.append(f"Resolves to: {result.source_kind}")
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
    imports = get_runtime_skill_import_use_cases()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can install skills.")
        return

    # Fall back to registry
    registry_url = th._cfg().registry_url
    if not registry_url:
        await update.effective_message.reply_text("No skill registry configured.", parse_mode=ParseMode.HTML)
        return

    try:
        result = await asyncio.to_thread(
            imports.install_from_registry,
            name,
            registry_url,
        )
        msg = result.message
        size_warnings = th._check_prompt_size_cross_chat(th._cfg().data_dir, name) if result.ok else []
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
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
    result = get_runtime_skill_import_use_cases().uninstall(name, default_skills=cfg.default_skills)
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_updates(event, update: Update) -> None:
    updates = await asyncio.to_thread(get_runtime_skill_import_use_cases().list_updates)
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
    diff_text = (await asyncio.to_thread(get_runtime_skill_import_use_cases().diff, name)).message
    if not diff_text.strip():
        diff_text = "No differences."
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n... (truncated)"
    await update.effective_message.reply_text(
        f"<pre>{html.escape(diff_text)}</pre>", parse_mode=ParseMode.HTML)


async def skills_update(event, update: Update, target: str) -> None:
    th = _th()
    imports = get_runtime_skill_import_use_cases()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can update imported skills.")
        return
    if target == "all":
        results = await asyncio.to_thread(imports.update_all)
        if not results:
            await update.effective_message.reply_text("No imported skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        all_size_warnings: list[str] = []
        for result in results:
            status = "\u2714" if result.ok else "\u2718"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(th._check_prompt_size_cross_chat(th._cfg().data_dir, result.name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for w in all_size_warnings:
                lines.append(f"  {html.escape(w)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    else:
        result = await asyncio.to_thread(imports.update, target)
        msg = result.message
        if result.ok:
            size_warnings = th._check_prompt_size_cross_chat(th._cfg().data_dir, target)
            if size_warnings:
                msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
