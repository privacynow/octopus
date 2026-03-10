"""Subcommand handlers for /skills, extracted from telegram_handlers."""

import asyncio
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from app.request_flow import (
    build_setup_state,
    foreign_setup_message,
    foreign_skill_setup,
    format_credential_prompt,
)
from app.skills import (
    build_system_prompt,
    check_credentials,
    estimate_prompt_size,
    get_skill_requirements,
    load_catalog,
    load_user_credentials,
    scaffold_skill,
    SkillRequirement,
)


def _th():
    """Lazy import of telegram_handlers to avoid circular imports."""
    import app.telegram_handlers as th
    return th


async def skills_show(event, update: Update) -> None:
    catalog = load_catalog()
    session = _th()._load(event.chat_id)
    active = session.active_skills
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
    catalog = load_catalog()
    if not catalog:
        await update.effective_message.reply_text("No skills available.")
        return
    th = _th()
    session = th._load(event.chat_id)
    active = set(session.active_skills)
    req_user_id = event.user.id
    user_creds = load_user_credentials(th._cfg().data_dir, req_user_id, th._encryption_key())
    lines = ["<b>Available skills:</b>"]
    for name, meta in sorted(catalog.items()):
        from app.store import is_store_installed, has_custom_override
        if name in active:
            status = " [active]"
        else:
            reqs = get_skill_requirements(name)
            if reqs:
                missing = check_credentials(name, user_creds)
                status = " [needs setup]" if missing else " [ready]"
            else:
                status = ""
        if has_custom_override(name):
            custom_tag = " [custom override]"
        elif meta.is_custom:
            custom_tag = " (custom)"
        elif is_store_installed(name):
            custom_tag = " (managed)"
        else:
            custom_tag = ""
        desc = f" \u2014 {html.escape(meta.description)}" if meta.description else ""
        lines.append(f"  <code>{html.escape(name)}</code>{desc}{status}{custom_tag}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_add(event, update: Update, name: str) -> None:
    catalog = load_catalog()
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
        active = session.active_skills

        requirements = get_skill_requirements(name)
        if requirements:
            key = th._encryption_key()
            user_creds = load_user_credentials(th._cfg().data_dir, user_id, key)
            missing = check_credentials(name, user_creds)
            if missing:
                if foreign_skill_setup(session, user_id):
                    await update.effective_message.reply_text(
                        foreign_setup_message(session.awaiting_skill_setup),
                    )
                    return
                setup = build_setup_state(user_id, name, missing)
                session.awaiting_skill_setup = setup
                th._save(chat_id, session)
                first_req = setup.remaining[0]
                await update.effective_message.reply_text(
                    f"Skill <code>{html.escape(name)}</code> needs setup before activation.\n\n"
                    f"{format_credential_prompt(first_req)}",
                    parse_mode=ParseMode.HTML,
                )
                return

        if name not in active:
            projected_size, over = estimate_prompt_size(
                session.role, active, name)
            if over:
                from app.skills import PROMPT_SIZE_WARNING_THRESHOLD
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Yes", callback_data=f"skill_add_confirm:{name}"),
                    InlineKeyboardButton("No", callback_data="skill_add_cancel"),
                ]])
                await update.effective_message.reply_text(
                    f"Adding <code>{html.escape(name)}</code> would bring total "
                    f"prompt context to ~{projected_size:,} chars "
                    f"(threshold: {PROMPT_SIZE_WARNING_THRESHOLD:,}). "
                    f"This may reduce response quality. Continue?",
                    parse_mode=ParseMode.HTML, reply_markup=kb)
                return
            active.append(name)
            th._save(chat_id, session)
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> activated.",
            parse_mode=ParseMode.HTML)


async def skills_remove(event, update: Update, name: str) -> None:
    th = _th()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        req_user_id = event.user.id
        had_setup = session.awaiting_skill_setup is not None
        if foreign_skill_setup(session, req_user_id, skill_name=name):
            await update.effective_message.reply_text(
                foreign_setup_message(session.awaiting_skill_setup),
            )
            return
        setup_expired = had_setup and session.awaiting_skill_setup is None
        active = session.active_skills
        removed = False
        if name in active:
            active.remove(name)
            removed = True
        setup = session.awaiting_skill_setup
        setup_cleared = False
        if setup and setup.skill == name:
            if setup.user_id == req_user_id:
                session.awaiting_skill_setup = None
                setup_cleared = True
        if removed or setup_cleared or setup_expired:
            th._save(chat_id, session)
        if removed:
            await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> deactivated.", parse_mode=ParseMode.HTML)
        else:
            await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> is not active.", parse_mode=ParseMode.HTML)


async def skills_setup(event, update: Update, name: str) -> None:
    catalog = load_catalog()
    if name not in catalog:
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    requirements = get_skill_requirements(name)
    if not requirements:
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> has no credential requirements.",
            parse_mode=ParseMode.HTML,
        )
        return
    th = _th()
    user_id = event.user.id
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        if foreign_skill_setup(session, user_id):
            await update.effective_message.reply_text(
                foreign_setup_message(session.awaiting_skill_setup),
            )
            return
        setup = build_setup_state(user_id, name, requirements)
        session.awaiting_skill_setup = setup
        th._save(chat_id, session)
    first_req = setup.remaining[0]
    await update.effective_message.reply_text(
        f"Setting up <code>{html.escape(name)}</code>.\n\n"
        f"{format_credential_prompt(first_req)}",
        parse_mode=ParseMode.HTML,
    )


async def skills_clear(event, update: Update) -> None:
    th = _th()
    chat_id = event.chat_id
    async with th.CHAT_LOCKS[chat_id]:
        session = th._load(chat_id)
        req_user_id = event.user.id
        if foreign_skill_setup(session, req_user_id):
            await update.effective_message.reply_text(
                foreign_setup_message(session.awaiting_skill_setup),
            )
            return
        session.active_skills = []
        session.awaiting_skill_setup = None
        th._save(chat_id, session)
    await update.effective_message.reply_text("All skills removed.")


async def skills_create(event, update: Update, name: str) -> None:
    try:
        skill_dir = scaffold_skill(name)
        await update.effective_message.reply_text(
            f"Created custom skill <code>{html.escape(name)}</code>\n"
            f"Edit: <code>{html.escape(str(skill_dir / 'skill.md'))}</code>",
            parse_mode=ParseMode.HTML,
        )
    except ValueError as e:
        await update.effective_message.reply_text(str(e))


async def skills_search(event, update: Update, query: str) -> None:
    from app.store import search as store_search
    results = store_search(query)
    lines: list[str] = []
    if results:
        lines.append(f"<b>Store skills matching '{html.escape(query)}':</b>")
        for info in results:
            desc = f" \u2014 {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")

    # Search registry if configured
    registry_url = _th()._cfg().registry_url
    if registry_url:
        try:
            from app.registry import fetch_index, search_index
            index = await asyncio.to_thread(fetch_index, registry_url)
            reg_results = search_index(index, query)
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
    lines.append("\nUse /skills info <name> for details, /skills install <name> to install.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_info(event, update: Update, name: str) -> None:
    from app.skills import skill_info_resolved
    result = skill_info_resolved(name)
    if not result:
        await update.effective_message.reply_text(
            f"Skill '{html.escape(name)}' not found.",
            parse_mode=ParseMode.HTML,
        )
        return
    meta, body, source, skill_path = result
    display_name = meta.get("display_name", name)
    description = meta.get("description", "")
    parts = [f"<b>{html.escape(display_name)}</b>"]
    if description:
        parts.append(html.escape(description))
    reqs = get_skill_requirements(name)
    if reqs:
        req_keys = ", ".join(r.key for r in reqs)
        parts.append(f"Requires: {html.escape(req_keys)}")
    elif source == "store (not installed)":
        from app.store import get_store_skill_requirements
        store_keys = get_store_skill_requirements(name)
        if store_keys:
            parts.append(f"Requires: {html.escape(', '.join(store_keys))}")
    providers = []
    if (skill_path / "claude.yaml").is_file():
        providers.append("Claude")
    if (skill_path / "codex.yaml").is_file():
        providers.append("Codex")
    if providers:
        parts.append(f"Providers: {', '.join(providers)}")
    parts.append(f"Resolves to: {source}")
    if len(body) > 1000:
        cut = body.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = body[:cut] + "..."
    else:
        preview = body
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def skills_install(event, update: Update, name: str) -> None:
    from app.store import install as store_install, STORE_DIR
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can install skills.")
        return

    # Try bundled store first
    store_path = STORE_DIR / name
    if store_path.is_dir() and (store_path / "skill.md").is_file():
        ok, msg = store_install(name)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    # Fall back to registry
    registry_url = th._cfg().registry_url
    if not registry_url:
        await update.effective_message.reply_text(
            f"Skill '{html.escape(name)}' not found in bundled store and no registry configured.",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        from app.registry import fetch_index
        from app.store import install_from_registry
        index = await asyncio.to_thread(fetch_index, registry_url)
        if name not in index:
            await update.effective_message.reply_text(
                f"Skill '{html.escape(name)}' not found in store or registry.",
                parse_mode=ParseMode.HTML,
            )
            return
        ok, msg = await asyncio.to_thread(install_from_registry, name, index[name])
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.effective_message.reply_text(
            f"Registry install failed: {html.escape(str(e)[:300])}",
            parse_mode=ParseMode.HTML,
        )


async def skills_uninstall(event, update: Update, name: str) -> None:
    from app.store import uninstall as store_uninstall
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can uninstall store skills.")
        return
    cfg = th._cfg()
    ok, msg = store_uninstall(name, cfg.default_skills)
    await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)


async def skills_updates(event, update: Update) -> None:
    from app.store import check_updates as store_check_updates, has_custom_override
    updates = store_check_updates()
    if not updates:
        await update.effective_message.reply_text("No store-installed skills found.")
        return
    lines = ["<b>Store skill status:</b>"]
    for name, status in updates:
        label = "update available" if status == "update_available" else "up to date"
        override = " [custom override]" if has_custom_override(name) else ""
        lines.append(f"  <code>{html.escape(name)}</code> \u2014 {label}{override}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_diff(event, update: Update, name: str) -> None:
    from app.store import diff_skill
    ok, diff_text = diff_skill(name)
    if not diff_text.strip():
        diff_text = "No differences."
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n... (truncated)"
    await update.effective_message.reply_text(
        f"<pre>{html.escape(diff_text)}</pre>", parse_mode=ParseMode.HTML)


async def skills_update(event, update: Update, target: str) -> None:
    from app.store import update_skill as store_update_skill, update_all as store_update_all
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can update store skills.")
        return
    if target == "all":
        results = store_update_all()
        if not results:
            await update.effective_message.reply_text("No store skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        cfg = th._cfg()
        all_size_warnings: list[str] = []
        for name, ok, msg in results:
            status = "\u2714" if ok else "\u2718"
            lines.append(f"  {status} {html.escape(msg)}")
            if ok:
                all_size_warnings.extend(th._check_prompt_size_cross_chat(cfg.data_dir, name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for w in all_size_warnings:
                lines.append(f"  {html.escape(w)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    else:
        ok, msg = store_update_skill(target)
        if ok:
            cfg = th._cfg()
            size_warnings = th._check_prompt_size_cross_chat(cfg.data_dir, target)
            if size_warnings:
                msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
