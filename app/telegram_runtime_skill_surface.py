"""Telegram surface handlers for runtime-skill workflows."""

from __future__ import annotations

import asyncio
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode

from app import user_messages as _msg
from app.credential_flow import foreign_setup_message, format_credential_prompt
from app.runtime import composition


def _th():
    import app.telegram_handlers as th

    return th


def _flows():
    return composition.workflows()


async def skills_show(event, update: Update) -> None:
    catalog = {item.name: item for item in _flows().runtime_skills.catalog.list_skills()}
    th = _th()
    session = th._load(event.chat_id)
    resolved = th._resolve_context(session, trust_tier=th._trust_tier(event.user))
    active = _flows().runtime_skills.activation.list_conversation_skills(
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
    catalog = _flows().runtime_skills.catalog.list_skills()
    if not catalog:
        await update.effective_message.reply_text("No skills available.")
        return
    th = _th()
    session = th._load(event.chat_id)
    resolved = th._resolve_context(session, trust_tier=th._trust_tier(event.user))
    active = set(
        _flows().runtime_skills.activation.list_conversation_skills(
            list(resolved.active_skills)
        ).active_skills
    )
    user_creds = _flows().credentials.management.load_credentials(
        th._actor_key(event.user.id)
    )
    lines = ["<b>Available skills:</b>"]
    for item in sorted(catalog, key=lambda value: value.name):
        name = item.name
        if name in active:
            status = " [active]"
        else:
            if item.requirement_keys:
                skill_creds = user_creds.get(name, {})
                missing = _flows().runtime_skills.catalog.missing_requirements(name, skill_creds)
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
        desc = f" — {html.escape(item.description)}" if item.description else ""
        lines.append(f"  <code>{html.escape(name)}</code>{desc}{status}{custom_tag}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_add(event, update: Update, name: str) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    th = _th()
    chat_id = event.chat_id
    async with th._chat_lock(chat_id, message=update.effective_message) as _:
        session = th._load(chat_id)
        decision = lifecycle.begin_activate(
            session,
            user_id=event.user.id,
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
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return
    await update.effective_message.reply_text(
        f"Skill <code>{html.escape(name)}</code> activated.",
        parse_mode=ParseMode.HTML,
    )


async def skills_remove(event, update: Update, name: str) -> None:
    th = _th()
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with th._chat_lock(chat_id, message=update.effective_message) as _:
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
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> deactivated.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_message.reply_text(
            f"Skill <code>{html.escape(name)}</code> is not active.",
            parse_mode=ParseMode.HTML,
        )


async def skills_setup(event, update: Update, name: str) -> None:
    lifecycle = _flows().runtime_skills.activation
    if not _flows().runtime_skills.catalog.has_skill(name):
        await update.effective_message.reply_text(
            f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
            parse_mode=ParseMode.HTML,
        )
        return
    th = _th()
    chat_id = event.chat_id
    async with th._chat_lock(chat_id, message=update.effective_message) as _:
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
    lifecycle = _flows().runtime_skills.activation
    chat_id = event.chat_id
    async with th._chat_lock(chat_id, message=update.effective_message) as _:
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
        record = _flows().runtime_skills.catalog.create_custom_draft(
            name,
            owner_actor=str(event.user.id),
        )
        await update.effective_message.reply_text(
            f"Created custom skill <code>{html.escape(name)}</code>\n"
            f"Draft visibility: <code>{html.escape(record.visibility)}</code>\n"
            "Use the registry UI or upcoming guided edit flow to update its instructions.",
            parse_mode=ParseMode.HTML,
        )
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))


async def skills_search(event, update: Update, query: str) -> None:
    results = await asyncio.to_thread(
        _flows().runtime_skills.imports.search,
        query,
        registry_url=_th()._cfg().registry_url,
    )
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
        await update.effective_message.reply_text(
            f"No skills matching '{html.escape(query)}'.",
            parse_mode=ParseMode.HTML,
        )
        return
    lines.append("\nUse /skills info <name> for details, /skills install <name> to import from the registry.")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_info(event, update: Update, name: str) -> None:
    result = _flows().runtime_skills.catalog.get_skill(name)
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
    preview = result.body
    if len(preview) > 1000:
        cut = preview.rfind("\n\n", 0, 1000)
        if cut < 500:
            cut = 1000
        preview = preview[:cut] + "..."
    parts.append(f"\n<pre>{html.escape(preview)}</pre>")
    await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def skills_install(event, update: Update, name: str) -> None:
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can install skills.")
        return
    registry_url = th._cfg().registry_url
    if not registry_url:
        await update.effective_message.reply_text("No skill registry configured.", parse_mode=ParseMode.HTML)
        return
    try:
        result = await asyncio.to_thread(
            _flows().runtime_skills.imports.install_from_registry,
            name,
            registry_url,
        )
        msg = result.message
        size_warnings = th._check_prompt_size_cross_chat(th._cfg().data_dir, name) if result.ok else []
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
    except Exception as exc:
        await update.effective_message.reply_text(
            f"Registry install failed: {html.escape(str(exc)[:300])}",
            parse_mode=ParseMode.HTML,
        )


async def skills_uninstall(event, update: Update, name: str) -> None:
    th = _th()
    if not th.is_admin(event.user):
        await update.effective_message.reply_text("Only admins can uninstall imported skills.")
        return
    result = _flows().runtime_skills.imports.uninstall(name, default_skills=th._cfg().default_skills)
    await update.effective_message.reply_text(html.escape(result.message), parse_mode=ParseMode.HTML)


async def skills_updates(event, update: Update) -> None:
    updates = await asyncio.to_thread(_flows().runtime_skills.imports.list_updates)
    if not updates:
        await update.effective_message.reply_text("No imported skills found.")
        return
    lines = ["<b>Imported skill status:</b>"]
    for item in updates:
        label = "update available" if item.status == "update_available" else "up to date"
        override = " [custom override]" if item.has_custom_override else ""
        lines.append(f"  <code>{html.escape(item.name)}</code> — {label}{override}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def skills_diff(event, update: Update, name: str) -> None:
    diff_text = (await asyncio.to_thread(_flows().runtime_skills.imports.diff, name)).message
    if not diff_text.strip():
        diff_text = "No differences."
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n... (truncated)"
    await update.effective_message.reply_text(
        f"<pre>{html.escape(diff_text)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def skills_update(event, update: Update, target: str) -> None:
    th = _th()
    imports = _flows().runtime_skills.imports
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
            status = "✔" if result.ok else "✘"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(th._check_prompt_size_cross_chat(th._cfg().data_dir, result.name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for warning in all_size_warnings:
                lines.append(f"  {html.escape(warning)}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    result = await asyncio.to_thread(imports.update, target)
    msg = result.message
    if result.ok:
        size_warnings = th._check_prompt_size_cross_chat(th._cfg().data_dir, target)
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
    await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)


async def cmd_clear_credentials(event, update: Update, context) -> None:
    del context
    th = _th()
    if await th._public_guard(event, update):
        return
    user_id = th.telegram_numeric_id(th._actor_key(event.user.id)) or 0
    args = event.args
    skill_name = args[0] if args else None

    stored = list(_flows().credentials.management.list_stored_skills(th._actor_key(user_id)))

    if skill_name:
        if skill_name not in stored:
            await update.effective_message.reply_text(
                f"No stored credentials for <code>{html.escape(skill_name)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        affected = [skill_name]
        msg = (
            f"This will remove your credentials for "
            f"<code>{html.escape(skill_name)}</code> and deactivate it "
            f"in this chat. Continue?"
        )
        cb_data = f"clear_cred_confirm:{user_id}:{skill_name}"
    else:
        if not stored:
            await update.effective_message.reply_text("No stored credentials found.")
            return
        affected = stored
        names = html.escape(", ".join(affected))
        msg = (
            f"This will remove all your stored credentials "
            f"({names}) and deactivate affected skills. Continue?"
        )
        cb_data = f"clear_cred_confirm_all:{user_id}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, clear", callback_data=cb_data),
        InlineKeyboardButton("Cancel", callback_data=f"clear_cred_cancel:{user_id}"),
    ]])
    await update.effective_message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _execute_clear_credentials(query, chat_id: int, user_id: int, skill_name: str | None) -> None:
    th = _th()
    async with th._chat_lock(chat_id, query=query) as already_answered:
        if not already_answered:
            await query.answer()
        session = th._load(chat_id)
        outcome = _flows().credentials.management.clear_credentials(
            session,
            actor_key=th._actor_key(user_id),
            skill_name=skill_name,
        )
        if outcome.mutated:
            th._save(chat_id, session)

    parts = []
    if outcome.removed_skills:
        parts.append(f"Credentials cleared for: {html.escape(', '.join(outcome.removed_skills))}.")
    if outcome.setup_cleared:
        parts.append(_msg.credential_setup_cancelled())
    if outcome.deactivated_skills:
        parts.append(f"Deactivated in this chat: {html.escape(', '.join(outcome.deactivated_skills))}.")
    if not parts:
        parts.append("No credentials to clear (may have already been removed).")
    await query.edit_message_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def handle_clear_cred_callback(event, query) -> None:
    th = _th()
    chat_id = event.chat_id
    clicker_id = th.telegram_numeric_id(th._actor_key(event.user.id)) or 0
    parts = event.data.split(":")
    if len(parts) >= 2:
        try:
            owner_id = int(parts[1])
        except (ValueError, IndexError):
            owner_id = 0
        if owner_id and clicker_id != owner_id:
            await query.answer(_msg.callback_wrong_user(), show_alert=True)
            return

    if parts[0] == "clear_cred_cancel":
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(_msg.credential_clear_cancelled())
        return

    if parts[0] == "clear_cred_confirm_all":
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, None)
        return

    if parts[0] == "clear_cred_confirm" and len(parts) >= 3:
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, parts[2])


async def handle_skill_add_callback(event, query) -> None:
    th = _th()
    chat_id = event.chat_id

    if event.data == "skill_add_cancel":
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Skill activation cancelled.")
        return

    if event.data.startswith("skill_add_confirm:"):
        name = event.data.split(":", 1)[1]
        async with th._chat_lock(chat_id, query=query) as already_answered:
            if not already_answered:
                await query.answer()
            session = th._load(chat_id)
            if _flows().runtime_skills.activation.confirm_activate(session, name).mutated:
                th._save(chat_id, session)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(
            f"Skill <code>{html.escape(name)}</code> activated.",
            parse_mode=ParseMode.HTML,
        )


async def handle_skill_update_callback(event, query) -> None:
    th = _th()
    if not th.is_admin(event.user):
        await query.answer("Only admins can update skills.", show_alert=True)
        return

    await query.answer()

    if event.data == "skill_update_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Update cancelled.")
        return

    if event.data.startswith("skill_update_confirm:"):
        name = event.data.split(":", 1)[1]
        result = await asyncio.to_thread(
            _flows().runtime_skills.imports.update,
            name,
        )
        msg = result.message
        size_warnings = th._check_prompt_size_cross_chat(th._cfg().data_dir, name) if result.ok else []
        if size_warnings:
            msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if event.data == "skill_update_all_confirm":
        results = await asyncio.to_thread(
            _flows().runtime_skills.imports.update_all,
        )
        if not results:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text("No imported skills need updating.")
            return
        lines = ["<b>Update results:</b>"]
        all_size_warnings: list[str] = []
        for result in results:
            status = "✔" if result.ok else "✘"
            lines.append(f"  {status} {html.escape(result.message)}")
            if result.ok:
                all_size_warnings.extend(th._check_prompt_size_cross_chat(th._cfg().data_dir, result.name))
        if all_size_warnings:
            lines.append("")
            lines.append("<b>Prompt size warnings:</b>")
            for warning in all_size_warnings:
                lines.append(f"  {html.escape(warning)}")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def maybe_handle_setup_message(update: Update, msg, payload: str) -> bool:
    th = _th()
    message = update.effective_message
    chat_id = msg.chat_id
    user_id = msg.user.id
    data_dir = th._cfg().data_dir
    session = th._load(chat_id)
    setup = session.awaiting_skill_setup
    if not setup or setup.user_id != th._actor_key(user_id):
        return False
    if not th.work_queue.record_update(
        data_dir,
        th._event_key(update.update_id),
        th._conversation_key(chat_id),
        th._actor_key(user_id),
        "message",
        payload=payload,
    ):
        return True
    async with th._chat_lock(chat_id, message=message, update_id=update.update_id, supersede_recovery=True):
        session = th._load(chat_id)
        setup = session.awaiting_skill_setup
        if not setup or setup.user_id != th._actor_key(user_id):
            return True
        await message.chat.send_action(ChatAction.TYPING)
        raw_value = (message.text or "").strip()
        if not raw_value:
            await message.reply_text("Please send the credential value as a text message.")
            return True
        outcome = await _flows().runtime_skills.setup.submit_credential_value(
            session,
            user_id=th._actor_key(user_id),
            raw_value=raw_value,
            validator=th.validate_credential,
        )
        if outcome.status == "validation_failed":
            try:
                await message.delete()
            except Exception:
                th.log.warning("Could not delete credential message for user %d", user_id)
            await message.reply_text(
                f"Credential validation failed for <code>{html.escape(outcome.validation_key)}</code>: "
                f"{html.escape(outcome.validation_error)}\nPlease try again.",
                parse_mode=ParseMode.HTML,
            )
            return True
        try:
            await message.delete()
        except Exception:
            th.log.warning("Could not delete credential message for user %d", user_id)
        skill_name = outcome.skill_name or setup.skill
        th._save(chat_id, session)
        if outcome.status == "next_requirement" and outcome.next_requirement:
            await message.reply_text(
                format_credential_prompt(outcome.next_requirement),
                parse_mode=ParseMode.HTML,
            )
            return True
        await message.reply_text(
            f"Skill <code>{html.escape(skill_name)}</code> is ready.",
            parse_mode=ParseMode.HTML,
        )
        return True


class _WorkerSkillEvent:
    def __init__(self, chat_id, user):
        self.chat_id = chat_id
        self.user = user


class _WorkerSkillUpdate:
    def __init__(self, surface):
        self.effective_message = surface


async def handle_worker_skill_action(event, surface) -> bool:
    th = _th()
    if th.is_public_user(event.user):
        await surface.reply_text(_msg.trust_command_not_available_public())
        return True
    proxy_event = _WorkerSkillEvent(chat_id=event.chat_id if hasattr(event, "chat_id") else event.conversation_key, user=event.user)
    proxy_update = _WorkerSkillUpdate(surface)
    action = event.action
    name = str(event.params.get("name", ""))
    if action == "skills_add":
        await skills_add(proxy_event, proxy_update, name)
        return True
    if action == "skills_remove":
        await skills_remove(proxy_event, proxy_update, name)
        return True
    if action == "skills_setup":
        await skills_setup(proxy_event, proxy_update, name)
        return True
    if action == "skills_clear":
        await skills_clear(proxy_event, proxy_update)
        return True
    return False
