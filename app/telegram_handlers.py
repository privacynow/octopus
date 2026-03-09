"""Telegram command handlers, message handler, progress display, and app wiring."""

import asyncio
import dataclasses
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
    format_denials_html,
)
from app.config import BotConfig
from app.formatting import extract_send_directives, md_to_telegram_html, split_html, trim_text
from app.providers.base import PendingRequest, Provider, RunContext, PreflightContext, compute_context_hash
from app.skills import (
    build_run_context, build_preflight_context, build_provider_config,
    get_provider_config_digest, get_skill_digests, load_catalog,
    get_skill_requirements, check_credentials, load_user_credentials,
    save_user_credential, derive_encryption_key, build_credential_env,
    scaffold_skill, validate_active_skills, validate_credential,
    check_prompt_size,
    stage_codex_scripts, cleanup_codex_scripts,
    SkillRequirement,
)
from app.storage import (
    build_upload_path,
    chat_upload_dir,
    default_session,
    is_image_path,
    load_session,
    resolve_allowed_path,
    save_session,
    sweep_skill_from_sessions,
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


def _encryption_key() -> bytes:
    return derive_encryption_key(_cfg().telegram_token)


def _approval_mode_source(session: dict[str, Any]) -> str:
    return "chat override" if session.get("approval_mode_explicit") else "instance default"


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


def is_admin(user) -> bool:
    """Check if user is an admin (can install/uninstall/update store skills)."""
    cfg = _cfg()
    uid = getattr(user, "id", None)
    uname = (getattr(user, "username", None) or "").lower()
    return uid in cfg.admin_user_ids or uname in cfg.admin_usernames


def _check_prompt_size_cross_chat(data_dir: Path, skill_name: str) -> list[str]:
    """Check prompt size in all chats where skill_name is active.

    Returns list of warning strings for chats over threshold.
    """
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.is_dir():
        return []
    warnings: list[str] = []
    for session_path in sessions_dir.glob("*.json"):
        try:
            import json as _json
            session = _json.loads(session_path.read_text())
        except Exception:
            continue
        active = session.get("active_skills", [])
        if skill_name not in active:
            continue
        role = session.get("role", "")
        warning = check_prompt_size(role, active)
        if warning:
            chat_id = session_path.stem
            warnings.append(f"  Chat {chat_id}: {warning}")
    return warnings


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
        cfg.role, cfg.default_skills,
    )


def _save(chat_id: int, session: dict[str, Any]) -> None:
    save_session(_cfg().data_dir, chat_id, session)


# -- Credential helpers ----------------------------------------------------

def _build_setup_state(user_id: int, skill_name: str, missing: list[SkillRequirement]) -> dict:
    """Build the awaiting_skill_setup dict for conversational credential input."""
    return {
        "user_id": user_id,
        "skill": skill_name,
        "started_at": time.time(),
        "remaining": [
            {"key": r.key, "prompt": r.prompt, "help_url": r.help_url,
             "validate": r.validate}
            for r in missing
        ],
    }


def _format_credential_prompt(req: dict) -> str:
    """Format a credential prompt for a single requirement."""
    text = req["prompt"]
    if req.get("help_url"):
        text += f"\n(See: {req['help_url']})"
    return text


# Foreign setup is considered expired after this many seconds.
_SETUP_TIMEOUT_SECONDS = 600  # 10 minutes


def _foreign_skill_setup(
    session: dict,
    user_id: int,
    skill_name: str | None = None,
) -> dict | None:
    """Return another user's in-progress setup, optionally filtered by skill.

    Auto-expires setups older than _SETUP_TIMEOUT_SECONDS so a disappeared
    user can't wedge a shared chat indefinitely.
    """
    setup = session.get("awaiting_skill_setup")
    if not setup or setup.get("user_id") == user_id:
        return None
    if skill_name is not None and setup.get("skill") != skill_name:
        return None
    # Expire stale setups — the owner may have abandoned the flow.
    # Missing started_at (pre-existing sessions) is treated as expired.
    started_at = setup.get("started_at")
    if started_at is None or (time.time() - started_at) > _SETUP_TIMEOUT_SECONDS:
        session["awaiting_skill_setup"] = None
        return None
    return setup


async def _check_credential_satisfaction(
    chat_id: int, user_id: int, session: dict, message,
) -> dict[str, str] | None:
    """Check credentials for active skills. Returns credential_env if satisfied, None if not."""
    cfg = _cfg()
    active_skills = session.get("active_skills", [])
    if not active_skills:
        return {}

    key = _encryption_key()
    user_creds = load_user_credentials(cfg.data_dir, user_id, key)

    all_missing: list[tuple[str, list[SkillRequirement]]] = []
    for skill_name in active_skills:
        missing = check_credentials(skill_name, user_creds)
        if missing:
            all_missing.append((skill_name, missing))

    if all_missing:
        # Don't overwrite another user's in-progress setup (group chat safety).
        # Their next message would fall through to normal execution, leaking a secret.
        if _foreign_skill_setup(session, user_id):
            await message.reply_text(
                "Another user is completing credential setup. Please wait and try again.",
            )
            return None

        # Start setup for the first skill with missing credentials
        skill_name, missing = all_missing[0]
        setup = _build_setup_state(user_id, skill_name, missing)
        session["awaiting_skill_setup"] = setup
        _save(chat_id, session)
        first_req = setup["remaining"][0]
        await message.reply_text(
            f"Skill <code>{html.escape(skill_name)}</code> needs setup.\n\n"
            f"{html.escape(_format_credential_prompt(first_req))}",
            parse_mode=ParseMode.HTML,
        )
        return None

    return build_credential_env(active_skills, user_creds)


# -- Core execution --------------------------------------------------------

async def execute_request(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    message,
    extra_dirs: list[str] | None = None,
    request_user_id: int = 0,
    skip_permissions: bool = False,
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    role = session.get("role", "")
    active_skills = session.get("active_skills", [])

    # Check credential satisfaction before proceeding
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message,
    )
    if credential_env is None:
        return

    # Always include the chat-specific upload dir (not the shared uploads tree)
    upload_dir = str(chat_upload_dir(cfg.data_dir, chat_id))
    all_extra_dirs = [upload_dir] + (extra_dirs or [])

    # Stage Codex scripts before building context so scripts_dir is in extra_dirs
    if prov.name == "codex":
        scripts_dir = stage_codex_scripts(cfg.data_dir, chat_id, active_skills)
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    # Build execution context (includes all extra_dirs, including staged scripts)
    context = build_run_context(role, active_skills, all_extra_dirs, provider_name=prov.name, credential_env=credential_env)
    context.skip_permissions = skip_permissions

    # Compute context hash using BASE dirs (from config, not upload or denial dirs)
    context_hash = compute_context_hash(
        role, active_skills, get_skill_digests(active_skills),
        get_provider_config_digest(active_skills, provider_name=prov.name),
        sorted(str(d) for d in cfg.extra_dirs),
    )

    # Codex thread invalidation (§8.3): if base context drifted, start fresh thread
    if prov.name == "codex":
        stored_hash = session["provider_state"].get("context_hash")
        if stored_hash and stored_hash != context_hash:
            session["provider_state"]["thread_id"] = None
        session["provider_state"]["context_hash"] = context_hash
        _save(chat_id, session)

    is_resume = bool(session["provider_state"].get("thread_id") or session["provider_state"].get("started"))
    label = f"Resuming {prov.name}..." if is_resume else f"Starting {prov.name}..."
    status_msg = await message.reply_text(label)
    progress = TelegramProgress(status_msg, cfg)
    typing_task = asyncio.create_task(keep_typing(message.chat))

    try:
        result = await prov.run(session["provider_state"], prompt, image_paths, progress, context=context)
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

    # Claude denial/retry flow — show denials BEFORE output so the user
    # understands the result is partial before reading it.
    if result.denials:
        await progress.update("Completed with blocked actions.", force=True)

        session = _load(chat_id)
        pending = PendingRequest(
            request_user_id=request_user_id,
            prompt=prompt,
            image_paths=image_paths,
            attachment_dicts=[],
            context_hash=context_hash,
            denials=result.denials,
        )
        session["pending_request"] = dataclasses.asdict(pending)
        _save(chat_id, session)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("\u2705 Grant access & retry", callback_data="retry_allow"),
            InlineKeyboardButton("\u274c Skip retry", callback_data="retry_skip"),
        ]])
        await message.chat.send_message(
            f"\u26a0\ufe0f <b>Permission needed:</b>\n"
            f"{format_denials_html(result.denials)}\n\n"
            "Grant access and retry from the beginning?",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

        cleaned_reply, directives = extract_send_directives(result.text)
        if cleaned_reply.strip():
            await send_formatted_reply(message, cleaned_reply)
            await send_directed_artifacts(chat_id, message, directives)
        return

    await progress.update("Done.", force=True)

    cleaned_reply, directives = extract_send_directives(result.text)
    await send_formatted_reply(message, cleaned_reply)
    await send_directed_artifacts(chat_id, message, directives)


async def request_approval(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    attachments: list[Attachment],
    message,
    request_user_id: int = 0,
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    if session.get("pending_request"):
        await message.reply_text(
            "A preflight approval is already waiting. Use /approve or /reject first."
        )
        return

    role = session.get("role", "")
    active_skills = session.get("active_skills", [])

    # Check credential satisfaction before proceeding
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message,
    )
    if credential_env is None:
        return

    # Build preflight context
    upload_dir = str(chat_upload_dir(cfg.data_dir, chat_id))
    preflight_context = build_preflight_context(role, active_skills, [upload_dir], provider_name=prov.name)

    # Compute context hash using BASE dirs (from config)
    context_hash = compute_context_hash(
        role, active_skills, get_skill_digests(active_skills),
        get_provider_config_digest(active_skills, provider_name=prov.name),
        sorted(str(d) for d in cfg.extra_dirs),
    )

    status_msg = await message.reply_text(
        "<i>Preparing preflight approval plan\u2026</i>",
        parse_mode=ParseMode.HTML,
    )
    progress = TelegramProgress(status_msg, cfg)
    typing_task = asyncio.create_task(keep_typing(message.chat))

    preflight_prompt = build_preflight_prompt(prompt, prov.name)
    try:
        plan_result = await prov.run_preflight(preflight_prompt, image_paths, progress, context=preflight_context)
    finally:
        typing_task.cancel()

    if plan_result.timed_out:
        await progress.update("Preflight approval timed out.", force=True)
        return

    if plan_result.returncode != 0:
        await progress.update(
            f"Preflight approval failed:\n{trim_text(plan_result.text, 3000)}",
            force=True,
        )
        return

    attachment_dicts = [
        {"path": str(a.path), "original_name": a.original_name, "is_image": a.is_image}
        for a in attachments
    ]
    pending = PendingRequest(
        request_user_id=request_user_id,
        prompt=prompt,
        image_paths=image_paths,
        attachment_dicts=attachment_dicts,
        context_hash=context_hash,
    )
    session["pending_request"] = dataclasses.asdict(pending)
    _save(chat_id, session)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 Approve plan", callback_data="approval_approve"),
        InlineKeyboardButton("\u274c Reject plan", callback_data="approval_reject"),
    ]])
    await progress.update("Preflight approval required.", force=True)
    await send_formatted_reply(
        message,
        "**Preflight approval plan:**\n\n" + (plan_result.text or "[empty plan]"),
    )
    await message.chat.send_message("Approve this preflight plan?", reply_markup=keyboard)


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


def _current_context_hash(session: dict[str, Any]) -> str:
    """Compute the current context hash from session state and config."""
    cfg = _cfg()
    prov = _prov()
    role = session.get("role", "")
    active_skills = session.get("active_skills", [])
    return compute_context_hash(
        role, active_skills, get_skill_digests(active_skills),
        get_provider_config_digest(active_skills, provider_name=prov.name),
        sorted(str(d) for d in cfg.extra_dirs),
    )


async def approve_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    pending = session.get("pending_request")
    if not pending:
        await message.reply_text("No pending request to approve.")
        return

    # Validate context hash — reject if stale
    if pending.get("context_hash") and pending["context_hash"] != _current_context_hash(session):
        session["pending_request"] = None
        _save(chat_id, session)
        await message.reply_text("Context changed since this request was made. Please resend.")
        return

    denials = pending.get("denials") or []
    extra_dirs = _extra_dirs_from_denials(denials) if denials else None
    request_user_id = pending.get("request_user_id", 0)
    session["pending_request"] = None
    _save(chat_id, session)
    await execute_request(
        chat_id, pending["prompt"], pending.get("image_paths", []), message,
        extra_dirs=extra_dirs,
        request_user_id=request_user_id,
        skip_permissions=True,
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
    "/skills \u2014 manage active skills\n"
    "/role \u2014 view or set the chat role\n"
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
        # Preserve approval_mode only if explicitly set via /approval command
        old_session = _load(chat_id)
        user_id = update.effective_user.id if update.effective_user else 0
        if _foreign_skill_setup(old_session, user_id):
            await update.effective_message.reply_text(
                "Another user is completing credential setup. Please wait and try again.",
            )
            return
        # Only preserve approval_mode if the user explicitly set it via /approval
        if old_session.get("approval_mode_explicit"):
            approval_mode = old_session.get("approval_mode", cfg.approval_mode)
        else:
            approval_mode = cfg.approval_mode
        session = default_session(prov.name, prov.new_provider_state(), approval_mode, cfg.role, cfg.default_skills)
        if old_session.get("approval_mode_explicit"):
            session["approval_mode_explicit"] = True
        _save(chat_id, session)
        # Clean up any staged Codex scripts for this chat
        cleanup_codex_scripts(cfg.data_dir, chat_id)
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
    role = session.get("role", "") or "(default)"
    active_skills = session.get("active_skills", [])
    skills_display = ", ".join(active_skills) if active_skills else "(none)"
    approval_mode = session.get("approval_mode", "off")
    approval_source = _approval_mode_source(session)
    await update.effective_message.reply_text(
        f"Provider: <code>{html.escape(_prov().name)}</code>\n"
        f"Instance: <code>{html.escape(cfg.instance)}</code>\n"
        f"Working dir: <code>{html.escape(str(cfg.working_dir))}</code>\n"
        f"{session_line}\n"
        f"Preflight approval mode: <code>{approval_mode}</code> ({approval_source})\n"
        f"Role: <code>{html.escape(role)}</code>\n"
        f"Skills: <code>{html.escape(skills_display)}</code>\n"
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
            mode = session.get("approval_mode", "off")
            source = _approval_mode_source(session)
            await update.effective_message.reply_text(
                f"Preflight approval mode is {mode} ({source})."
            )
            return
        session["approval_mode"] = arg
        session["approval_mode_explicit"] = True
        _save(chat_id, session)
    await update.effective_message.reply_text(
        f"Preflight approval mode set to {arg} for this chat."
    )


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
    # Validate active skills for this chat
    session = _load(update.effective_chat.id)
    user_id = update.effective_user.id if update.effective_user else 0
    skill_errors = validate_active_skills(
        session.get("active_skills", []),
        user_id=user_id,
        data_dir=_cfg().data_dir,
        encryption_key=_encryption_key(),
    )
    all_errors = cfg_errors + prov_errors + skill_errors
    if all_errors:
        lines = "\n".join(f"\u274c {html.escape(e)}" for e in all_errors)
        await update.effective_message.reply_text(lines, parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("\u2705 All checks passed.")


async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    chat_id = update.effective_chat.id
    args = context.args or []
    catalog = load_catalog()

    if not args:
        # /skills — show active skills and available count
        session = _load(chat_id)
        active = session.get("active_skills", [])
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
        return

    sub = args[0].lower()

    if sub == "list":
        if not catalog:
            await update.effective_message.reply_text("No skills available.")
            return
        session = _load(chat_id)
        active = set(session.get("active_skills", []))
        lines = ["<b>Available skills:</b>"]
        for name, meta in sorted(catalog.items()):
            marker = " [active]" if name in active else ""
            from app.store import is_store_installed
            if meta.is_custom and is_store_installed(name):
                custom_tag = " (store)"
            elif meta.is_custom:
                custom_tag = " (custom)"
            else:
                custom_tag = ""
            desc = f" \u2014 {html.escape(meta.description)}" if meta.description else ""
            lines.append(f"  <code>{html.escape(name)}</code>{desc}{marker}{custom_tag}")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if sub == "add" and len(args) >= 2:
        name = args[1]
        if name not in catalog:
            await update.effective_message.reply_text(
                f"Unknown skill: {html.escape(name)}. Use /skills list to see available.",
                parse_mode=ParseMode.HTML,
            )
            return
        user_id = update.effective_user.id if update.effective_user else 0
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            active = session.get("active_skills", [])

            # Check credential requirements before activating
            requirements = get_skill_requirements(name)
            if requirements:
                key = _encryption_key()
                user_creds = load_user_credentials(_cfg().data_dir, user_id, key)
                missing = check_credentials(name, user_creds)
                if missing:
                    # Don't overwrite another user's in-progress setup
                    if _foreign_skill_setup(session, user_id):
                        await update.effective_message.reply_text(
                            "Another user is completing credential setup. Please wait and try again.",
                        )
                        return

                    # Don't add to active_skills yet — start credential setup first
                    setup = _build_setup_state(user_id, name, missing)
                    session["awaiting_skill_setup"] = setup
                    _save(chat_id, session)
                    first_req = setup["remaining"][0]
                    await update.effective_message.reply_text(
                        f"Skill <code>{html.escape(name)}</code> needs setup before activation.\n\n"
                        f"{html.escape(_format_credential_prompt(first_req))}",
                        parse_mode=ParseMode.HTML,
                    )
                    return

            # Credentials satisfied (or none required) — activate
            if name not in active:
                active.append(name)
                session["active_skills"] = active
                _save(chat_id, session)
            msg = f"Skill <code>{html.escape(name)}</code> activated."
            warning = check_prompt_size(session.get("role", ""), active)
            if warning:
                msg += f"\n\n\u26a0\ufe0f {html.escape(warning)}"
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if sub == "remove" and len(args) >= 2:
        name = args[1]
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            req_user_id = update.effective_user.id if update.effective_user else 0
            had_setup = session.get("awaiting_skill_setup") is not None
            if _foreign_skill_setup(session, req_user_id, skill_name=name):
                await update.effective_message.reply_text(
                    "Another user is completing credential setup. Please wait and try again.",
                )
                return
            # _foreign_skill_setup may have expired a stale setup (had_setup but now None).
            setup_expired = had_setup and session.get("awaiting_skill_setup") is None
            active = session.get("active_skills", [])
            removed = False
            if name in active:
                active.remove(name)
                session["active_skills"] = active
                removed = True
            setup = session.get("awaiting_skill_setup")
            setup_cleared = False
            if setup and setup.get("skill") == name:
                if setup.get("user_id") == req_user_id:
                    session["awaiting_skill_setup"] = None
                    setup_cleared = True
            if removed or setup_cleared or setup_expired:
                _save(chat_id, session)
            if removed:
                await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> deactivated.", parse_mode=ParseMode.HTML)
            else:
                await update.effective_message.reply_text(f"Skill <code>{html.escape(name)}</code> is not active.", parse_mode=ParseMode.HTML)
        return

    if sub == "setup" and len(args) >= 2:
        name = args[1]
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
        user_id = update.effective_user.id if update.effective_user else 0
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            # Don't overwrite another user's in-progress setup
            if _foreign_skill_setup(session, user_id):
                await update.effective_message.reply_text(
                    "Another user is completing credential setup. Please wait and try again.",
                )
                return
            setup = _build_setup_state(user_id, name, requirements)
            session["awaiting_skill_setup"] = setup
            _save(chat_id, session)
        first_req = setup["remaining"][0]
        await update.effective_message.reply_text(
            f"Setting up <code>{html.escape(name)}</code>.\n\n"
            f"{html.escape(_format_credential_prompt(first_req))}",
            parse_mode=ParseMode.HTML,
        )
        return

    if sub == "clear":
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            req_user_id = update.effective_user.id if update.effective_user else 0
            if _foreign_skill_setup(session, req_user_id):
                await update.effective_message.reply_text(
                    "Another user is completing credential setup. Please wait and try again.",
                )
                return
            session["active_skills"] = []
            session["awaiting_skill_setup"] = None
            _save(chat_id, session)
        await update.effective_message.reply_text("All skills removed.")
        return

    if sub == "create" and len(args) >= 2:
        name = args[1]
        try:
            skill_dir = scaffold_skill(name)
            await update.effective_message.reply_text(
                f"Created custom skill <code>{html.escape(name)}</code>\n"
                f"Edit: <code>{html.escape(str(skill_dir / 'skill.md'))}</code>",
                parse_mode=ParseMode.HTML,
            )
        except ValueError as e:
            await update.effective_message.reply_text(str(e))
        return

    if sub == "search" and len(args) >= 2:
        from app.store import search as store_search
        query = " ".join(args[1:])
        results = store_search(query)
        if not results:
            await update.effective_message.reply_text(
                f"No store skills matching '{html.escape(query)}'.",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [f"<b>Store skills matching '{html.escape(query)}':</b>"]
        for info in results:
            desc = f" \u2014 {html.escape(info.description)}" if info.description else ""
            lines.append(f"  <code>{html.escape(info.name)}</code>{desc}")
        lines.append("\nUse /skills info <name> for details, /skills install <name> to install.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if sub == "info" and len(args) >= 2:
        from app.store import skill_info as store_skill_info
        name = args[1]
        result = store_skill_info(name)
        if not result:
            await update.effective_message.reply_text(
                f"Skill '{html.escape(name)}' not found in store.",
                parse_mode=ParseMode.HTML,
            )
            return
        info, body = result
        parts = [f"<b>{html.escape(info.display_name)}</b>"]
        if info.description:
            parts.append(html.escape(info.description))
        features = []
        if info.has_requirements:
            features.append("credentials required")
        if info.has_claude_config:
            features.append("Claude config")
        if info.has_codex_config:
            features.append("Codex config")
        if features:
            parts.append(f"Features: {', '.join(features)}")
        # Show a preview of the instructions (first 500 chars)
        preview = body[:500]
        if len(body) > 500:
            preview += "..."
        parts.append(f"\n<pre>{html.escape(preview)}</pre>")
        await update.effective_message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)
        return

    if sub == "install" and len(args) >= 2:
        from app.store import install as store_install
        if not is_admin(update.effective_user):
            await update.effective_message.reply_text("Only admins can install store skills.")
            return
        name = args[1]
        ok, msg = store_install(name)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if sub == "uninstall" and len(args) >= 2:
        from app.store import uninstall as store_uninstall
        if not is_admin(update.effective_user):
            await update.effective_message.reply_text("Only admins can uninstall store skills.")
            return
        name = args[1]
        cfg = _cfg()
        def _sweep(skill_name):
            return sweep_skill_from_sessions(cfg.data_dir, skill_name)
        ok, msg = store_uninstall(name, cfg.default_skills, session_sweep_fn=_sweep)
        await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if sub == "updates":
        from app.store import check_updates as store_check_updates
        updates = store_check_updates()
        if not updates:
            await update.effective_message.reply_text("No store-installed skills found.")
            return
        lines = ["<b>Store skill status:</b>"]
        for name, status in updates:
            if status == "update_available":
                lines.append(f"  <code>{html.escape(name)}</code> \u2014 update available")
            elif status == "locally_modified":
                lines.append(f"  <code>{html.escape(name)}</code> \u2014 locally modified")
            else:
                lines.append(f"  <code>{html.escape(name)}</code> \u2014 up to date")
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if sub == "update" and len(args) >= 2:
        from app.store import update_skill as store_update_skill, update_all as store_update_all
        if not is_admin(update.effective_user):
            await update.effective_message.reply_text("Only admins can update store skills.")
            return
        target = args[1]
        if target == "all":
            results = store_update_all()
            if not results:
                await update.effective_message.reply_text("No store skills need updating.")
                return
            lines = ["<b>Update results:</b>"]
            cfg = _cfg()
            all_size_warnings: list[str] = []
            for name, ok, msg in results:
                status = "\u2714" if ok else "\u2718"
                lines.append(f"  {status} {html.escape(msg)}")
                if ok:
                    all_size_warnings.extend(_check_prompt_size_cross_chat(cfg.data_dir, name))
            if all_size_warnings:
                lines.append("")
                lines.append("<b>Prompt size warnings:</b>")
                for w in all_size_warnings:
                    lines.append(f"  {html.escape(w)}")
            await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        else:
            ok, msg = store_update_skill(target)
            if ok:
                # Check prompt size in all chats where this skill is active
                cfg = _cfg()
                size_warnings = _check_prompt_size_cross_chat(cfg.data_dir, target)
                if size_warnings:
                    msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
            await update.effective_message.reply_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    await update.effective_message.reply_text(
        "Usage: /skills [list|add|remove|setup|create|clear|search|info|install|uninstall|updates|update]"
    )


async def cmd_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user):
        return
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        # /role — show current role
        session = _load(chat_id)
        role = session.get("role", "")
        if role:
            await update.effective_message.reply_text(
                f"Current role: <code>{html.escape(role)}</code>", parse_mode=ParseMode.HTML,
            )
        else:
            await update.effective_message.reply_text("No role set (using instance default).")
        return

    if args[0].lower() == "clear":
        cfg = _cfg()
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            session["role"] = cfg.role
            _save(chat_id, session)
        await update.effective_message.reply_text("Role reset to instance default.")
        return

    # /role <text> — set role
    role_text = " ".join(args)
    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        session["role"] = role_text
        _save(chat_id, session)
    await update.effective_message.reply_text(
        f"Role set to: <code>{html.escape(role_text)}</code>", parse_mode=ParseMode.HTML,
    )


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

    user_id = update.effective_user.id if update.effective_user else 0

    async with CHAT_LOCKS[chat_id]:
        await message.chat.send_action(ChatAction.TYPING)
        session = _load(chat_id)

        # Credential capture (§8.1: before approval mode check)
        setup = session.get("awaiting_skill_setup")
        if setup and setup.get("user_id") == user_id:
            cfg = _cfg()
            key = _encryption_key()
            req = setup["remaining"][0]
            raw_value = (message.text or "").strip()
            if not raw_value:
                await message.reply_text("Please send the credential value as a text message.")
                return

            # Validate credential if a validate spec exists
            if req.get("validate"):
                ok, detail = await validate_credential(
                    SkillRequirement(key=req["key"], prompt=req["prompt"],
                                     help_url=req.get("help_url"), validate=req["validate"]),
                    raw_value,
                )
                if not ok:
                    # Delete the message containing the secret before reporting failure
                    try:
                        await message.delete()
                    except Exception:
                        log.warning("Could not delete credential message for user %d", user_id)
                    await message.reply_text(
                        f"Credential validation failed for <code>{html.escape(req['key'])}</code>: "
                        f"{html.escape(detail)}\nPlease try again.",
                        parse_mode=ParseMode.HTML,
                    )
                    return

            save_user_credential(
                cfg.data_dir, user_id, setup["skill"], req["key"], raw_value, key,
            )

            # Step 20: delete the message containing the secret
            try:
                await message.delete()
            except Exception:
                log.warning("Could not delete credential message for user %d", user_id)

            setup["remaining"].pop(0)
            if setup["remaining"]:
                # Prompt for the next credential
                next_req = setup["remaining"][0]
                session["awaiting_skill_setup"] = setup
                _save(chat_id, session)
                await message.reply_text(
                    html.escape(_format_credential_prompt(next_req)),
                    parse_mode=ParseMode.HTML,
                )
            else:
                # All credentials collected — activate skill now
                skill_name = setup["skill"]
                session.pop("awaiting_skill_setup", None)
                active = session.get("active_skills", [])
                if skill_name not in active:
                    active.append(skill_name)
                    session["active_skills"] = active
                _save(chat_id, session)
                await message.reply_text(
                    f"Skill <code>{html.escape(skill_name)}</code> is ready.",
                    parse_mode=ParseMode.HTML,
                )
            return

        if session.get("approval_mode") == "on":
            await request_approval(chat_id, prompt, image_paths, attachments, message, request_user_id=user_id)
            return
        await execute_request(chat_id, prompt, image_paths, message, request_user_id=user_id)


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

            # Validate context hash — reject if stale
            if pending.get("context_hash") and pending["context_hash"] != _current_context_hash(session):
                session["pending_request"] = None
                _save(chat_id, session)
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.edit_text("Context changed since this request was made. Please resend.")
                return

            prompt = pending["prompt"]
            denials = pending.get("denials") or []
            request_user_id = pending.get("request_user_id", 0)
            session["pending_request"] = None

            # Derive execution dirs: base extra_dirs + approved dirs from denials
            denial_dirs = _extra_dirs_from_denials(denials)

            # For Codex: clear thread_id when there are approved dirs so the
            # retry starts a fresh exec with --add-dir (resume doesn't support it)
            if denial_dirs and _prov().name == "codex":
                session["provider_state"]["thread_id"] = None

            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)

            await execute_request(
                chat_id, prompt, pending.get("image_paths", []),
                query.message, denial_dirs,
                request_user_id=request_user_id,
                skip_permissions=True,
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
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("role", cmd_role))
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
