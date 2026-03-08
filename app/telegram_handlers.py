"""Telegram command handlers, message handler, progress display, and app wiring."""

import asyncio
import html
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.approvals import (
    build_preflight_prompt,
    clear_pending_request,
    format_denials_html,
    serialize_pending_request,
)
from app.config import BotConfig
from app.formatting import extract_send_directives, md_to_telegram_html, split_html, trim_text
from app.providers.base import Provider
from app.storage import (
    build_upload_path,
    chat_upload_dir,
    default_session,
    is_image_path,
    load_session,
    resolve_allowed_path,
    save_session,
)

log = logging.getLogger(__name__)

CHAT_LOCKS: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# These get set by build_application()
_config: BotConfig | None = None
_provider: Provider | None = None


def _cfg() -> BotConfig:
    assert _config is not None
    return _config


def _prov() -> Provider:
    assert _provider is not None
    return _provider


# -- Data classes ----------------------------------------------------------

@dataclass
class Attachment:
    path: Path
    original_name: str
    is_image: bool
    mime_type: str | None = None


# -- TelegramProgress (rate-limited HTML editor) ---------------------------

class TelegramProgress:
    def __init__(self, message, config: BotConfig) -> None:
        self.message = message
        self.last_text = ""
        self.last_update = 0.0
        self._interval = config.stream_update_interval_seconds

    async def update(self, html_text: str, *, force: bool = False) -> None:
        html_text = trim_text(html_text, 3500)
        if not html_text or html_text == self.last_text:
            return
        now = time.monotonic()
        if not force and now - self.last_update < self._interval:
            return
        try:
            await self.message.edit_text(html_text, parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.debug("progress update failed: %s", exc)
                return
        self.last_text = html_text
        self.last_update = now


# -- Auth ------------------------------------------------------------------

def is_allowed(user) -> bool:
    cfg = _cfg()
    if cfg.allow_open and not cfg.allowed_user_ids and not cfg.allowed_usernames:
        return True
    if not cfg.allowed_user_ids and not cfg.allowed_usernames:
        return False
    uid = getattr(user, "id", None)
    uname = (getattr(user, "username", None) or "").lower()
    return uid in cfg.allowed_user_ids or uname in cfg.allowed_usernames


# -- Helpers ---------------------------------------------------------------

def _allowed_roots(chat_id: int) -> list[Path]:
    """Return path roots this chat is allowed to access.

    Uses the chat-specific upload dir (not the shared uploads tree)
    so one chat cannot read another chat's uploaded files.
    """
    cfg = _cfg()
    roots = [cfg.working_dir, chat_upload_dir(cfg.data_dir, chat_id)]
    roots.extend(cfg.extra_dirs)
    return [r.resolve() for r in roots]


def build_user_prompt(text: str, attachments: list[Attachment]) -> tuple[str, list[str]]:
    prompt = text.strip() or "Inspect the attached files or images and help with them."
    image_paths: list[str] = []
    if attachments:
        lines = []
        for a in attachments:
            kind = "image" if a.is_image else "file"
            lines.append(f"- {a.path} ({kind}, original name: {a.original_name})")
            if a.is_image:
                image_paths.append(str(a.path))
        prompt = f"{prompt}\n\nAttached local files:\n" + "\n".join(lines)
    return prompt, image_paths


async def download_attachments(chat_id: int, update: Update) -> list[Attachment]:
    cfg = _cfg()
    message = update.effective_message
    attachments: list[Attachment] = []

    if message.photo:
        photo = message.photo[-1]
        path = build_upload_path(cfg.data_dir, chat_id, "photo.jpg")
        tf = await photo.get_file()
        await tf.download_to_drive(custom_path=str(path))
        attachments.append(
            Attachment(path=path, original_name="photo.jpg", is_image=True, mime_type="image/jpeg")
        )

    if message.document:
        doc = message.document
        name = doc.file_name or "document"
        path = build_upload_path(cfg.data_dir, chat_id, name)
        tf = await doc.get_file()
        await tf.download_to_drive(custom_path=str(path))
        is_img = (doc.mime_type or "").startswith("image/") or is_image_path(path)
        attachments.append(
            Attachment(path=path, original_name=name, is_image=is_img, mime_type=doc.mime_type)
        )

    return attachments


async def send_formatted_reply(message, text: str) -> None:
    formatted = md_to_telegram_html(text) if text else "<i>[empty]</i>"
    for chunk in split_html(formatted, 4096):
        try:
            await message.reply_text(
                chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        except BadRequest:
            # Strip HTML tags so the fallback doesn't show raw markup
            plain = re.sub(r"<[^>]+>", "", chunk)
            await message.reply_text(plain[:4096])


async def send_path_to_chat(message, path: Path, *, force_image: bool | None = None) -> None:
    should_image = force_image if force_image is not None else is_image_path(path)
    with path.open("rb") as f:
        if should_image:
            await message.reply_photo(photo=f)
        else:
            await message.reply_document(document=f)


async def send_directed_artifacts(chat_id: int, message, directives: list[tuple[str, str]]) -> None:
    for dtype, raw_path in directives:
        resolved = resolve_allowed_path(raw_path, _allowed_roots(chat_id))
        if not resolved:
            await message.reply_text(f"[Cannot send: {raw_path}]")
            continue
        await send_path_to_chat(message, resolved, force_image=(dtype == "IMAGE"))


async def keep_typing(chat) -> None:
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(_cfg().typing_interval_seconds)
    except asyncio.CancelledError:
        pass


def _load(chat_id: int) -> dict[str, Any]:
    cfg = _cfg()
    return load_session(
        cfg.data_dir, chat_id, _prov().name,
        _prov().new_provider_state, cfg.approval_mode,
    )


def _save(chat_id: int, session: dict[str, Any]) -> None:
    save_session(_cfg().data_dir, chat_id, session)


# -- Core execution --------------------------------------------------------

async def execute_request(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    message,
    extra_dirs: list[str] | None = None,
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    # Always include the chat-specific upload dir (not the shared uploads tree)
    upload_dir = str(chat_upload_dir(cfg.data_dir, chat_id))
    all_extra_dirs = [upload_dir] + (extra_dirs or [])

    is_resume = bool(session["provider_state"].get("thread_id") or session["provider_state"].get("started"))
    label = f"Resuming {prov.name}..." if is_resume else f"Starting {prov.name}..."
    status_msg = await message.reply_text(label)
    progress = TelegramProgress(status_msg, cfg)
    typing_task = asyncio.create_task(keep_typing(message.chat))

    try:
        result = await prov.run(session["provider_state"], prompt, image_paths, progress, extra_dirs=all_extra_dirs)
    finally:
        typing_task.cancel()

    # Re-load session to pick up any changes made while the provider was running
    # (e.g. /approval or /new issued concurrently), then merge provider state.
    session = _load(chat_id)
    session["provider_state"].update(result.provider_state_updates)
    _save(chat_id, session)

    if result.timed_out:
        await progress.update(
            f"{prov.name} timed out after {cfg.timeout_seconds} seconds.", force=True
        )
        return

    if result.returncode != 0:
        await progress.update(trim_text(result.text, 3000), force=True)
        return

    await progress.update("Done.", force=True)

    cleaned_reply, directives = extract_send_directives(result.text)
    await send_formatted_reply(message, cleaned_reply)
    await send_directed_artifacts(chat_id, message, directives)

    # Claude denial/retry flow
    if result.denials:
        session = _load(chat_id)
        session["pending_request"] = {"prompt": prompt, "image_paths": image_paths, "denials": result.denials}
        _save(chat_id, session)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("\u2705 Allow & retry", callback_data="retry_allow"),
            InlineKeyboardButton("\u274c Skip", callback_data="retry_skip"),
        ]])
        await message.chat.send_message(
            f"\u26a0\ufe0f <b>Permission denied:</b>\n{format_denials_html(result.denials)}\n\n"
            "Allow these tools and retry?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


async def request_approval(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    attachments: list[Attachment],
    message,
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    if session.get("pending_request"):
        await message.reply_text("A request is already waiting for approval. Use /approve or /reject first.")
        return

    status_msg = await message.reply_text("<i>Preparing approval plan\u2026</i>", parse_mode=ParseMode.HTML)
    progress = TelegramProgress(status_msg, cfg)
    typing_task = asyncio.create_task(keep_typing(message.chat))

    preflight_prompt = build_preflight_prompt(prompt, prov.name)
    try:
        plan_result = await prov.run_preflight(preflight_prompt, image_paths, progress)
    finally:
        typing_task.cancel()

    if plan_result.timed_out:
        await progress.update("Approval preflight timed out.", force=True)
        return

    if plan_result.returncode != 0:
        await progress.update(
            f"Approval preflight failed:\n{trim_text(plan_result.text, 3000)}", force=True
        )
        return

    attachment_dicts = [
        {"path": str(a.path), "original_name": a.original_name, "is_image": a.is_image}
        for a in attachments
    ]
    session["pending_request"] = serialize_pending_request(prompt, image_paths, attachment_dicts)
    _save(chat_id, session)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 Approve", callback_data="approval_approve"),
        InlineKeyboardButton("\u274c Reject", callback_data="approval_reject"),
    ]])
    await progress.update("Approval required.", force=True)
    await send_formatted_reply(message, "**Approval plan:**\n\n" + (plan_result.text or "[empty plan]"))
    await message.chat.send_message("Approve this request?", reply_markup=keyboard)


def _extra_dirs_from_denials(denials: list[dict]) -> list[str]:
    """Extract directory paths from permission denial tool_input fields.

    For file paths (file_path, path): add the parent directory.
    For directory values: add the directory itself (not its parent).
    For commands: add "/" (needs broad access).
    """
    dirs: set[str] = set()
    for d in denials:
        inp = d.get("tool_input", {})
        # File paths → parent directory
        for key in ("file_path", "path"):
            val = inp.get(key, "")
            if val:
                dirs.add(str(Path(val).parent))
        # Directory → the directory itself
        dir_val = inp.get("directory", "")
        if dir_val:
            dirs.add(str(Path(dir_val)))
        if "command" in inp:
            dirs.add("/")
    return list(dirs)


async def approve_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    pending = session.get("pending_request")
    if not pending:
        await message.reply_text("No pending request to approve.")
        return
    denials = pending.get("denials", [])
    extra_dirs = _extra_dirs_from_denials(denials) if denials else None
    session["pending_request"] = None
    _save(chat_id, session)
    await execute_request(
        chat_id, pending["prompt"], pending.get("image_paths", []), message,
        extra_dirs=extra_dirs,
    )


async def reject_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    if not session.get("pending_request"):
        await message.reply_text("No pending request to reject.")
        return
    session["pending_request"] = None
    _save(chat_id, session)
    await message.reply_text("Pending request rejected.")


# -- Command handlers ------------------------------------------------------

HELP_TEMPLATE = (
    "<b>{provider} CLI Bridge</b> (instance: <code>{instance}</code>)\n\n"
    "Send text, photos, or documents to chat with {provider}.\n\n"
    "<b>Commands:</b>\n"
    "/new \u2014 fresh conversation\n"
    "/session \u2014 show current session info\n"
    "/approval on|off|status \u2014 toggle preflight approval mode\n"
    "/approve \u2014 approve pending request\n"
    "/reject \u2014 reject pending request\n"
    "/send &lt;path&gt; \u2014 retrieve a file from the filesystem\n"
    "/id \u2014 show your Telegram user ID\n"
    "/doctor \u2014 run health checks\n\n"
    "{provider} can send files back by including lines like:\n"
    "<code>SEND_FILE: /path/to/file</code>\n"
    "<code>SEND_IMAGE: /path/to/image</code>"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        await update.effective_message.reply_text("Not authorized.")
        return
    cfg = _cfg()
    text = HELP_TEMPLATE.format(provider=_prov().name.capitalize(), instance=cfg.instance)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    chat_id = update.effective_chat.id
    cfg = _cfg()
    prov = _prov()
    async with CHAT_LOCKS[chat_id]:
        # Preserve the chat's current approval mode (don't reset to instance default)
        old_session = _load(chat_id)
        approval_mode = old_session.get("approval_mode", cfg.approval_mode)
        session = default_session(prov.name, prov.new_provider_state(), approval_mode)
        _save(chat_id, session)
    await update.effective_message.reply_text(f"Fresh {prov.name} conversation started.")


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    session = _load(update.effective_chat.id)
    cfg = _cfg()
    pstate = session.get("provider_state", {})

    # Show provider-relevant session ID
    if _prov().name == "claude":
        sid = pstate.get("session_id", "[none]")
        active = pstate.get("started", False)
        session_line = f"Session: <code>{html.escape(sid[:12])}\u2026</code>\nActive: <code>{active}</code>"
    else:
        tid = pstate.get("thread_id") or "[none yet]"
        session_line = f"Thread: <code>{html.escape(str(tid))}</code>"

    pending = "yes" if session.get("pending_request") else "no"
    await update.effective_message.reply_text(
        f"Provider: <code>{html.escape(_prov().name)}</code>\n"
        f"Instance: <code>{html.escape(cfg.instance)}</code>\n"
        f"Working dir: <code>{html.escape(str(cfg.working_dir))}</code>\n"
        f"{session_line}\n"
        f"Approval mode: <code>{session.get('approval_mode', 'off')}</code>\n"
        f"Pending: <code>{pending}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    chat_id = update.effective_chat.id
    arg = (context.args[0].lower() if context.args else "status")
    if arg not in {"on", "off", "status"}:
        await update.effective_message.reply_text("Use /approval on, /approval off, or /approval status.")
        return
    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        if arg == "status":
            await update.effective_message.reply_text(
                f"Approval mode is {session.get('approval_mode', 'off')}."
            )
            return
        session["approval_mode"] = arg
        _save(chat_id, session)
    await update.effective_message.reply_text(f"Approval mode set to {arg}.")


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    async with CHAT_LOCKS[update.effective_chat.id]:
        await approve_pending(update.effective_chat.id, update.effective_message)


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    async with CHAT_LOCKS[update.effective_chat.id]:
        await reject_pending(update.effective_chat.id, update.effective_message)


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /send <path>")
        return
    raw_path = " ".join(context.args)
    resolved = resolve_allowed_path(raw_path, _allowed_roots(update.effective_chat.id))
    if not resolved:
        await update.effective_message.reply_text("Path is missing or outside allowed roots.")
        return
    await send_path_to_chat(update.effective_message, resolved)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    username = update.effective_user.username or "[none]"
    await update.effective_message.reply_text(
        f"Your user ID: <code>{update.effective_user.id}</code>\n"
        f"Your username: <code>{html.escape(username)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    from app.config import validate_config
    loop = asyncio.get_running_loop()
    cfg_errors = validate_config(_cfg())
    # Run blocking health checks in a thread to avoid stalling the event loop
    prov_errors = await loop.run_in_executor(None, _prov().check_health)
    all_errors = cfg_errors + prov_errors
    if all_errors:
        lines = "\n".join(f"\u274c {html.escape(e)}" for e in all_errors)
        await update.effective_message.reply_text(lines, parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("\u2705 All checks passed.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    message = update.effective_message
    chat_id = update.effective_chat.id
    attachments = await download_attachments(chat_id, update)
    text = message.text or message.caption or ""
    if not text and not attachments:
        return

    prompt, image_paths = build_user_prompt(text, attachments)

    async with CHAT_LOCKS[chat_id]:
        await message.chat.send_action(ChatAction.TYPING)
        session = _load(chat_id)
        if session.get("approval_mode") == "on":
            await request_approval(chat_id, prompt, image_paths, attachments, message)
            return
        await execute_request(chat_id, prompt, image_paths, message)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_allowed(update.effective_user):
        await query.answer("Not authorized.", show_alert=True)
        return

    await query.answer()
    chat_id = update.effective_chat.id

    async with CHAT_LOCKS[chat_id]:
        if query.data == "approval_approve":
            await query.edit_message_reply_markup(reply_markup=None)
            await approve_pending(chat_id, query.message)
            return

        if query.data == "approval_reject":
            await query.edit_message_reply_markup(reply_markup=None)
            await reject_pending(chat_id, query.message)
            return

        if query.data == "retry_skip":
            session = _load(chat_id)
            session["pending_request"] = None
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.edit_text("Skipped.")
            return

        if query.data == "retry_allow":
            session = _load(chat_id)
            pending = session.get("pending_request")
            if not pending:
                await query.message.edit_text("Nothing to retry.")
                return

            prompt = pending["prompt"]
            denials = pending.get("denials", [])
            session["pending_request"] = None
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)

            extra_dirs = _extra_dirs_from_denials(denials)

            await execute_request(
                chat_id, prompt, pending.get("image_paths", []),
                query.message, extra_dirs,
            )


# -- Application builder ---------------------------------------------------

def build_application(config: BotConfig, provider: Provider) -> Application:
    global _config, _provider
    _config = config
    _provider = provider

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("approval", cmd_approval))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("doctor", cmd_doctor))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(retry_|approval_)"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
            handle_message,
        )
    )
    return app
