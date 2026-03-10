"""Telegram command handlers, message handler, progress display, and app wiring."""

import asyncio
import html
import logging
import re
import time
import uuid
from collections import defaultdict
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
from app.execution_context import ResolvedExecutionContext, resolve_execution_context
from app.providers.base import Provider, RunContext, PreflightContext
from app.request_flow import (
    build_setup_state,
    check_credential_satisfaction,
    extra_dirs_from_denials,
    foreign_setup_message,
    foreign_skill_setup,
    format_credential_prompt,
    pending_expired,
    validate_pending,
)
from app.session_state import (
    AwaitingSkillSetup,
    PendingApproval,
    PendingRetry,
    SessionState,
    session_from_dict,
    session_to_dict,
)
from app.skills import (
    build_run_context, build_preflight_context,
    get_provider_config_digest, get_skill_digests,
    get_skill_requirements, check_credentials, load_user_credentials,
    save_user_credential, delete_user_credentials, list_user_credential_skills,
    derive_encryption_key,
    build_credential_env,
    validate_credential,
    stage_codex_scripts, cleanup_codex_scripts,
    SkillRequirement,
)
from app.storage import (
    chat_upload_dir,
    default_session,
    is_image_path,
    load_session,
    resolve_allowed_path,
    save_session,
    session_exists,
    list_sessions,
)
from app.ratelimit import RateLimiter
from app.summarize import export_chat_history, load_raw, save_raw, summarize
from app.transport import (
    InboundAttachment,
    InboundUser,
    normalize_callback,
    normalize_command,
    normalize_message,
    normalize_user,
)

log = logging.getLogger(__name__)

CHAT_LOCKS: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# These get set by build_application()
_config: BotConfig | None = None
_provider: Provider | None = None
_boot_id: str = ""  # unique per process; detects restart to clear stale threads
_rate_limiter: RateLimiter | None = None
_seen_update_ids: set[int] = set()  # track processed update_ids for idempotency
_MAX_SEEN_IDS = 1000  # cap the set size to prevent memory growth


def _dedup_update(update: Update) -> bool:
    """Return True if this update_id was already processed (duplicate). Thread-safe for single-process."""
    uid = update.update_id
    if uid in _seen_update_ids:
        log.debug("Skipping duplicate update_id %d", uid)
        return True
    _seen_update_ids.add(uid)
    if len(_seen_update_ids) > _MAX_SEEN_IDS:
        sorted_ids = sorted(_seen_update_ids)
        _seen_update_ids.difference_update(sorted_ids[:len(sorted_ids) // 2])
    return False


def _cfg() -> BotConfig:
    assert _config is not None
    return _config


def _prov() -> Provider:
    assert _provider is not None
    return _provider


def _encryption_key() -> bytes:
    return derive_encryption_key(_cfg().telegram_token)


def _approval_mode_source(session: SessionState) -> str:
    return "chat override" if session.approval_mode_explicit else "instance default"


# -- Data classes ----------------------------------------------------------

# Attachment is now InboundAttachment from app.transport.
# Alias kept for internal signature compatibility.
Attachment = InboundAttachment


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

def _to_inbound_user(user) -> InboundUser | None:
    """Coerce a raw Telegram user or InboundUser to InboundUser."""
    if user is None:
        return None
    if isinstance(user, InboundUser):
        return user
    return normalize_user(user)


def is_allowed(user) -> bool:
    u = _to_inbound_user(user)
    if u is None:
        return False
    cfg = _cfg()
    # Open mode admits everyone (public users get restricted at execution layer)
    if cfg.allow_open:
        return True
    if not cfg.allowed_user_ids and not cfg.allowed_usernames:
        return False
    return u.id in cfg.allowed_user_ids or u.username in cfg.allowed_usernames


def is_admin(user) -> bool:
    """Check if user is an admin (can install/uninstall/update store skills)."""
    u = _to_inbound_user(user)
    if u is None:
        return False
    cfg = _cfg()
    return u.id in cfg.admin_user_ids or u.username in cfg.admin_usernames


def is_public_user(user) -> bool:
    """Check if user is a public (untrusted) user.

    A user is public when allow_open is true AND the user is not in
    any allowed-user set.  Returns False if allow_open is off (the user
    wouldn't have passed is_allowed at all).
    """
    u = _to_inbound_user(user)
    if u is None:
        return False
    cfg = _cfg()
    if not cfg.allow_open:
        return False
    # If there are no allowed lists, everyone is public
    if not cfg.allowed_user_ids and not cfg.allowed_usernames:
        return True
    return u.id not in cfg.allowed_user_ids and u.username not in cfg.allowed_usernames


def _trust_tier(user) -> str:
    """Resolve the trust tier for a user: 'trusted' or 'public'."""
    return "public" if is_public_user(user) else "trusted"


async def _public_guard(event, update: Update) -> bool:
    """Return True (and send denial) if the user is public. Use at top of restricted commands."""
    if is_public_user(event.user):
        await update.effective_message.reply_text("This command is not available in public mode.")
        return True
    return False


def _command_handler(fn):
    """Decorator: dedup → normalize_command → is_allowed gate → call fn(event, update, context)."""
    import functools
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _dedup_update(update):
            return
        event = normalize_command(update, context)
        if event is None or not is_allowed(event.user):
            return
        await fn(event, update, context)
    return wrapper


def _callback_handler(fn):
    """Decorator: dedup → normalize_callback → is_allowed gate → call fn(event, query).

    Does NOT call query.answer() — handlers control their own answer semantics
    (some need alerts, some need silent acks, some answer conditionally).
    """
    import functools
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if _dedup_update(update):
            return
        event = normalize_callback(update)
        if event is None:
            return
        query = update.callback_query
        if not is_allowed(event.user):
            await query.answer("Not authorized.", show_alert=True)
            return
        await fn(event, query)
    return wrapper


def _check_prompt_size_cross_chat(data_dir: Path, skill_name: str) -> list[str]:
    """Check prompt size in all chats where skill_name is active."""
    from app.doctor import check_prompt_size_cross_chat
    cfg = _cfg()
    return check_prompt_size_cross_chat(
        data_dir, skill_name, cfg.provider_name,
        _prov().new_provider_state, cfg.approval_mode,
    )


# -- Project helpers -------------------------------------------------------

def _resolve_project(session: SessionState) -> tuple[str, str, tuple[str, ...]] | None:
    """Return (name, root_dir, extra_dirs) for the session's bound project, or None."""
    project_id = session.project_id
    if not project_id:
        return None
    for name, root_dir, extra_dirs in _cfg().projects:
        if name == project_id:
            return (name, root_dir, extra_dirs)
    return None


def _project_working_dir(session: SessionState) -> str:
    """Return the working directory for this session's project, or empty string for default."""
    proj = _resolve_project(session)
    return proj[1] if proj else ""


def _resolve_context(session: SessionState, trust_tier: str = "trusted") -> ResolvedExecutionContext:
    """Build the single authoritative execution identity from session + config."""
    return resolve_execution_context(session, _cfg(), _prov().name, trust_tier=trust_tier)


# -- Helpers ---------------------------------------------------------------

def _allowed_roots(chat_id: int, resolved: ResolvedExecutionContext | None = None) -> list[Path]:
    """Return path roots this chat is allowed to access.

    Uses the resolved execution context for working_dir and extra_dirs,
    so public users get public roots and project-bound chats get project roots.
    Falls back to config defaults only when no resolved context is available.
    """
    cfg = _cfg()
    if resolved:
        roots: list[Path] = [Path(resolved.working_dir)]
        roots.extend(Path(d) for d in resolved.base_extra_dirs)
    else:
        roots = [cfg.working_dir]
        roots.extend(cfg.extra_dirs)
    roots.append(chat_upload_dir(cfg.data_dir, chat_id))
    return [r.resolve() for r in roots]


def build_user_prompt(text: str, attachments: list[InboundAttachment]) -> tuple[str, list[str]]:
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


def _extract_summary(text: str, max_lines: int = 4) -> tuple[str, str]:
    """Split text into a short summary (first few lines) and the rest."""
    lines = text.split("\n")
    # Take up to max_lines non-empty lines as summary
    summary_lines = []
    rest_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            summary_lines.append(line)
        if len(summary_lines) >= max_lines:
            rest_start = i + 1
            break
    else:
        rest_start = len(lines)

    summary = "\n".join(lines[:rest_start])
    rest = "\n".join(lines[rest_start:]).strip()
    return summary, rest


async def _send_compact_reply(message, text: str, chat_id: int, slot: int) -> None:
    """Send a compact response using expandable blockquote or expand button."""
    summary, detail = _extract_summary(text)
    formatted_summary = md_to_telegram_html(summary) if summary else ""

    if detail:
        # Use expandable blockquote for the detail
        formatted_detail = md_to_telegram_html(detail)
        compact_html = (
            f"{formatted_summary}\n\n"
            f"<blockquote expandable>{formatted_detail}</blockquote>"
        )

        # If the combined text fits in a single message, send with expandable blockquote
        if len(compact_html) <= 4000:
            try:
                await message.reply_text(
                    compact_html, parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return
            except BadRequest:
                pass  # Fall through to button approach

        # Too long for blockquote — send summary with "Show full" button
        button_text = f"{formatted_summary}\n\n<i>Response truncated</i>"
        try:
            await message.reply_text(
                button_text[:4000], parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "Show full answer",
                        callback_data=f"expand:{chat_id}:{slot}",
                    ),
                ]]),
            )
            return
        except BadRequest:
            pass

    # Fallback: send as regular formatted reply
    await send_formatted_reply(message, text)


async def send_path_to_chat(message, path: Path, *, force_image: bool | None = None) -> None:
    should_image = force_image if force_image is not None else is_image_path(path)
    with path.open("rb") as f:
        if should_image:
            await message.reply_photo(photo=f)
        else:
            await message.reply_document(document=f)


async def send_directed_artifacts(
    chat_id: int, message, directives: list[tuple[str, str]],
    resolved_ctx: ResolvedExecutionContext | None = None,
) -> None:
    for dtype, raw_path in directives:
        allowed_path = resolve_allowed_path(raw_path, _allowed_roots(chat_id, resolved_ctx))
        if not allowed_path:
            await message.reply_text(f"[Cannot send: {raw_path}]")
            continue
        await send_path_to_chat(message, allowed_path, force_image=(dtype == "IMAGE"))


async def keep_typing(chat) -> None:
    try:
        while True:
            await chat.send_action(ChatAction.TYPING)
            await asyncio.sleep(_cfg().typing_interval_seconds)
    except asyncio.CancelledError:
        pass


def _load(chat_id: int) -> SessionState:
    cfg = _cfg()
    raw = load_session(
        cfg.data_dir, chat_id, _prov().name,
        _prov().new_provider_state, cfg.approval_mode,
        cfg.role, cfg.default_skills,
    )
    session = session_from_dict(raw)
    # Self-heal: prune active skills whose refs/dirs no longer exist
    from app.skills import normalize_active_skills
    normalize_active_skills(session, save_fn=lambda s: _save(chat_id, s))
    return session


def _save(chat_id: int, session: SessionState) -> None:
    save_session(_cfg().data_dir, chat_id, session_to_dict(session))


# -- Credential helpers ----------------------------------------------------

async def _check_credential_satisfaction(
    chat_id: int, user_id: int, session: SessionState, message,
    resolved: ResolvedExecutionContext | None = None,
) -> dict[str, str] | None:
    """Check credentials for active skills. Returns credential_env if satisfied, None if not.

    Uses resolved.active_skills (not raw session.active_skills) so public users
    with no resolved skills skip credential checks entirely.

    Delegates to request_flow.check_credential_satisfaction for pure logic,
    then handles transport (message sending, session saving).
    """
    active_skills = resolved.active_skills if resolved else session.active_skills
    result = check_credential_satisfaction(
        active_skills, session, user_id, _cfg().data_dir, _encryption_key(),
    )
    if result.satisfied:
        return result.credential_env

    if result.foreign_setup:
        await message.reply_text(foreign_setup_message(result.foreign_setup))
        return None

    # Start credential setup for missing skill
    session.awaiting_skill_setup = result.setup_state
    _save(chat_id, session)
    first_req = result.setup_state.remaining[0]
    await message.reply_text(
        f"Skill <code>{html.escape(result.missing_skill)}</code> needs setup.\n\n"
        f"{format_credential_prompt(first_req)}",
        parse_mode=ParseMode.HTML,
    )
    return None


# -- Core execution --------------------------------------------------------

async def execute_request(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    message,
    extra_dirs: list[str] | None = None,
    request_user_id: int = 0,
    skip_permissions: bool = False,
    trust_tier: str = "trusted",
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    # Resolve the authoritative execution identity once
    resolved = _resolve_context(session, trust_tier=trust_tier)

    # Check credential satisfaction using resolved active_skills
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message, resolved=resolved,
    )
    if credential_env is None:
        return

    # Always include the chat-specific upload dir (not the shared uploads tree)
    # plus resolved extra_dirs from execution context and any denial dirs from retries
    upload_dir = str(chat_upload_dir(cfg.data_dir, chat_id))
    all_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs) + (extra_dirs or [])

    # Stage Codex scripts before building context so scripts_dir is in extra_dirs
    if prov.name == "codex":
        scripts_dir = stage_codex_scripts(cfg.data_dir, chat_id, resolved.active_skills)
        if scripts_dir:
            all_extra_dirs.append(str(scripts_dir))

    # Build execution context (includes all extra_dirs, including staged scripts)
    context = build_run_context(
        resolved.role, resolved.active_skills, all_extra_dirs,
        provider_name=prov.name,
        credential_env=credential_env, working_dir=resolved.working_dir,
        file_policy=resolved.file_policy,
        effective_model=resolved.effective_model,
    )
    context.skip_permissions = skip_permissions

    # Compact mode: add summary-first instruction to system prompt
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and context.system_prompt:
        context.system_prompt += (
            "\n\nIMPORTANT: Structure your response with a 2-4 line summary first, "
            "then provide detailed explanation below. Lead with the answer."
        )
    elif compact:
        context.system_prompt = (
            "Structure your response with a 2-4 line summary first, "
            "then provide detailed explanation below. Lead with the answer."
        )

    # Use the single authoritative context hash
    context_hash = resolved.context_hash

    # Codex thread invalidation: start fresh thread when context drifted or bot restarted.
    if prov.name == "codex":
        stored_hash = session.provider_state.get("context_hash")
        stored_boot = session.provider_state.get("boot_id")
        stale_thread = (
            (stored_hash and stored_hash != context_hash)
            or (stored_boot and stored_boot != _boot_id)
        )
        if stale_thread and session.provider_state.get("thread_id"):
            log.info("Clearing stale codex thread for chat %d (hash_match=%s, boot_match=%s)",
                     chat_id, stored_hash == context_hash, stored_boot == _boot_id)
            session.provider_state["thread_id"] = None
        session.provider_state["context_hash"] = context_hash
        session.provider_state["boot_id"] = _boot_id
        _save(chat_id, session)

    is_resume = bool(session.provider_state.get("thread_id") or session.provider_state.get("started"))
    label = f"Resuming {prov.name}..." if is_resume else f"Starting {prov.name}..."
    status_msg = await message.reply_text(label)
    progress = TelegramProgress(status_msg, cfg)
    typing_task = asyncio.create_task(keep_typing(message.chat))

    try:
        result = await prov.run(session.provider_state, prompt, image_paths, progress, context=context)
    finally:
        typing_task.cancel()

    # Re-load session to pick up any changes made while the provider was running
    session = _load(chat_id)
    session.provider_state.update(result.provider_state_updates)

    resume_errored = (
        prov.name == "codex"
        and is_resume
        and not result.timed_out
        and result.returncode and result.returncode != 0
    )
    if resume_errored:
        log.warning("Codex resume error (rc=%s) for chat %d — clearing thread",
                     result.returncode, chat_id)
        session.provider_state["thread_id"] = None

    _save(chat_id, session)

    if result.timed_out:
        await progress.update(
            f"{prov.name} timed out after {cfg.timeout_seconds} seconds.", force=True
        )
        return

    if result.returncode != 0:
        error_text = trim_text(result.text, 3000)
        if resume_errored:
            error_text += "\n\n<i>Thread could not be resumed — next message starts a fresh session.</i>"
        await progress.update(error_text, force=True)
        return

    # Claude denial/retry flow — show denials BEFORE output so the user
    # understands the result is partial before reading it.
    if result.denials:
        await progress.update("Completed with blocked actions.", force=True)

        session = _load(chat_id)
        session.pending_retry = PendingRetry(
            request_user_id=request_user_id,
            prompt=prompt,
            image_paths=image_paths,
            context_hash=context_hash,
            denials=result.denials,
            trust_tier=trust_tier,
            created_at=time.time(),
        )
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
            await send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)
        return

    await progress.update("Done.", force=True)

    cleaned_reply, directives = extract_send_directives(result.text)

    # Save raw response to ring buffer for /raw retrieval
    from app.summarize import load_raw_by_slot
    slot = save_raw(cfg.data_dir, chat_id, prompt, cleaned_reply)

    # Compact mode: use expandable blockquote or inline expand for long responses
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    if compact and len(cleaned_reply) > 800:
        await _send_compact_reply(message, cleaned_reply, chat_id, slot)
    else:
        await send_formatted_reply(message, cleaned_reply)
    await send_directed_artifacts(chat_id, message, directives, resolved_ctx=resolved)


async def request_approval(
    chat_id: int,
    prompt: str,
    image_paths: list[str],
    attachments: list[Attachment],
    message,
    request_user_id: int = 0,
    trust_tier: str = "trusted",
) -> None:
    cfg = _cfg()
    prov = _prov()
    session = _load(chat_id)

    if session.has_pending:
        await message.reply_text(
            "A preflight approval is already waiting. Use /approve or /reject first."
        )
        return

    # Resolve the authoritative execution identity once
    resolved = _resolve_context(session, trust_tier=trust_tier)

    # Check credential satisfaction using resolved active_skills
    credential_env = await _check_credential_satisfaction(
        chat_id, request_user_id, session, message, resolved=resolved,
    )
    if credential_env is None:
        return

    # Build preflight context (include config extra_dirs + upload dir)
    upload_dir = str(chat_upload_dir(cfg.data_dir, chat_id))
    preflight_extra_dirs = [upload_dir] + list(resolved.base_extra_dirs)
    preflight_context = build_preflight_context(
        resolved.role, resolved.active_skills, preflight_extra_dirs,
        provider_name=prov.name,
        working_dir=resolved.working_dir, file_policy=resolved.file_policy,
    )

    # Use the single authoritative context hash
    context_hash = resolved.context_hash

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
    session.pending_approval = PendingApproval(
        request_user_id=request_user_id,
        prompt=prompt,
        image_paths=image_paths,
        attachment_dicts=attachment_dicts,
        context_hash=context_hash,
        trust_tier=trust_tier,
        created_at=time.time(),
    )
    _save(chat_id, session)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("\u2705 Approve plan", callback_data="approval_approve"),
        InlineKeyboardButton("\u274c Reject plan", callback_data="approval_reject"),
    ]])
    await progress.update("Preflight approval required.", force=True)
    plan_text = plan_result.text or "[empty plan]"
    save_raw(cfg.data_dir, chat_id, prompt, plan_text, kind="approval")
    await send_formatted_reply(
        message,
        "**Preflight approval plan:**\n\n" + plan_text,
    )
    await message.chat.send_message("Approve this preflight plan?", reply_markup=keyboard)


async def approve_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    pending = session.pending_approval or session.pending_retry
    if not pending:
        await message.reply_text("No pending request to approve.")
        return

    error = validate_pending(pending, session, _cfg(), _prov().name)
    if error:
        session.clear_pending()
        _save(chat_id, session)
        await message.reply_text(error)
        return

    denials = getattr(pending, 'denials', None) or []
    denial_dirs = extra_dirs_from_denials(denials) if denials else None
    request_user_id = pending.request_user_id
    trust_tier = getattr(pending, 'trust_tier', 'trusted')
    session.clear_pending()
    _save(chat_id, session)
    await execute_request(
        chat_id, pending.prompt, pending.image_paths, message,
        extra_dirs=denial_dirs,
        request_user_id=request_user_id,
        skip_permissions=True,
        trust_tier=trust_tier,
    )


async def reject_pending(chat_id: int, message) -> None:
    session = _load(chat_id)
    if not session.has_pending:
        await message.reply_text("No pending request to reject.")
        return
    session.clear_pending()
    _save(chat_id, session)
    await message.reply_text("Pending request rejected.")


# -- Command handlers ------------------------------------------------------

HELP_TEMPLATE = (
    "<b>Agent Bot</b> (instance: <code>{instance}</code>, provider: {provider})\n\n"
    "Send a message, photo, or document and the AI will respond.\n\n"
    "<b>Commands:</b>\n"
    "/new — start a fresh conversation\n"
    "/skills — browse and activate skills (e.g. <code>/skills list</code>)\n"
    "/role &lt;text&gt; — set the AI's persona (e.g. <code>/role Python expert</code>)\n"
    "/approval on|off — show a plan before executing, or run immediately\n"
    "/approve / /reject — act on a pending plan\n"
    "/cancel — cancel credential setup or a pending request\n"
    "/clear_credentials — remove your stored credentials\n"
    "/send &lt;path&gt; — retrieve a file from the server\n"
    "/model — switch model profile (fast/balanced/best)\n"
    "/compact on|off — toggle short/full answers\n"
    "/policy inspect|edit — set file access policy\n"
    "/session — show current session info\n"
    "/id — show your Telegram user ID\n"
    "/doctor — run health checks\n""/export — download recent conversation history\n""/admin sessions — session overview (admin only)\n\n"
    "Type /help skills, /help approval, or /help credentials for details."
)

HELP_SKILLS = (
    "<b>Skills</b>\n\n"
    "Skills add domain knowledge and tools to the AI.\n\n"
    "/skills list — see all available skills with status\n"
    "/skills add &lt;name&gt; — activate a skill (prompts for credentials if needed)\n"
    "/skills remove &lt;name&gt; — deactivate a skill\n"
    "/skills setup &lt;name&gt; — re-enter credentials for a skill\n"
    "/skills info &lt;name&gt; — view skill details\n"
    "/skills search &lt;query&gt; — search the skill store\n"
    "/skills clear — deactivate all skills"
)

HELP_APPROVAL = (
    "<b>Approval Mode</b>\n\n"
    "When approval mode is on, the AI shows a plan before executing. "
    "You review and approve or reject it.\n\n"
    "/approval on — require approval before execution\n"
    "/approval off — execute immediately\n"
    "/approval status — check current setting\n"
    "/approve — approve the pending plan\n"
    "/reject — reject the pending plan\n"
    "/cancel — cancel a pending request"
)

HELP_CREDENTIALS = (
    "<b>Credentials</b>\n\n"
    "Some skills need API tokens or keys. When you activate such a skill, "
    "the bot asks for each credential in a private message and encrypts it.\n\n"
    "/skills setup &lt;name&gt; — re-enter credentials for a skill\n"
    "/clear_credentials — remove all your stored credentials\n"
    "/clear_credentials &lt;skill&gt; — remove credentials for one skill\n\n"
    "Your credential messages are deleted after capture for safety."
)

_HELP_TOPICS = {
    "skills": HELP_SKILLS,
    "approval": HELP_APPROVAL,
    "credentials": HELP_CREDENTIALS,
}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — always show main help (ignores deep-link payloads)."""
    if _dedup_update(update):
        return
    event = normalize_command(update, context)
    if event is None or not is_allowed(event.user):
        await update.effective_message.reply_text("Not authorized.")
        return
    cfg = _cfg()
    text = HELP_TEMPLATE.format(provider=_prov().name.capitalize(), instance=cfg.instance)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help [topic] — main help or topic-specific detail."""
    if _dedup_update(update):
        return
    event = normalize_command(update, context)
    if event is None or not is_allowed(event.user):
        await update.effective_message.reply_text("Not authorized.")
        return
    cfg = _cfg()
    args = event.args

    if args:
        topic = args[0].lower()
        topic_text = _HELP_TOPICS.get(topic)
        if topic_text:
            await update.effective_message.reply_text(topic_text, parse_mode=ParseMode.HTML)
            return
        await update.effective_message.reply_text(
            "Unknown help topic. Try: /help skills, /help approval, or /help credentials."
        )
        return

    text = HELP_TEMPLATE.format(provider=_prov().name.capitalize(), instance=cfg.instance)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


@_command_handler
async def cmd_new(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _cfg()
    prov = _prov()
    async with CHAT_LOCKS[chat_id]:
        old_session = _load(chat_id)
        user_id = event.user.id
        if foreign_skill_setup(old_session, user_id):
            await update.effective_message.reply_text(
                foreign_setup_message(old_session.awaiting_skill_setup),
            )
            return
        if old_session.approval_mode_explicit:
            approval_mode = old_session.approval_mode
        else:
            approval_mode = cfg.approval_mode
        session = session_from_dict(default_session(prov.name, prov.new_provider_state(), approval_mode, cfg.role, cfg.default_skills))
        if old_session.approval_mode_explicit:
            session.approval_mode_explicit = True
        _save(chat_id, session)
        # Clean up any staged Codex scripts for this chat
        cleanup_codex_scripts(cfg.data_dir, chat_id)
    await update.effective_message.reply_text(f"Fresh {prov.name} conversation started.")


@_command_handler
async def cmd_session(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _load(event.chat_id)
    cfg = _cfg()
    pstate = session.provider_state

    # Show provider-relevant session ID
    if _prov().name == "claude":
        sid = pstate.get("session_id", "[none]")
        active = pstate.get("started", False)
        session_line = f"Session: <code>{html.escape(sid[:12])}\u2026</code>\nActive: <code>{active}</code>"
    else:
        tid = pstate.get("thread_id") or "[none yet]"
        session_line = f"Thread: <code>{html.escape(str(tid))}</code>"

    pending = "yes" if session.has_pending else "no"
    resolved = _resolve_context(session, trust_tier=_trust_tier(event.user))
    role_display = resolved.role or "(default)"
    skills_display = ", ".join(resolved.active_skills) if resolved.active_skills else "(none)"
    approval_mode = session.approval_mode
    approval_source = _approval_mode_source(session)

    # Resolve effective working directory for display
    if resolved.project_id:
        wd_display = f"{resolved.working_dir} (project: {resolved.project_id})"
    else:
        wd_display = resolved.working_dir

    file_policy = resolved.file_policy or "edit"
    model_profile = session.model_profile or cfg.default_model_profile or "(default)"
    model_id = resolved.effective_model or cfg.model or "(default)"
    compact = session.compact_mode if session.compact_mode is not None else cfg.compact_mode
    compact_display = "on" if compact else "off"

    # Prompt weight estimate (chars of system prompt)
    from app.skills import build_system_prompt
    sys_prompt = build_system_prompt(resolved.role, resolved.active_skills)
    prompt_weight = f"~{len(sys_prompt)} chars" if sys_prompt else "minimal"

    await update.effective_message.reply_text(
        f"Provider: <code>{html.escape(_prov().name)}</code>\n"
        f"Instance: <code>{html.escape(cfg.instance)}</code>\n"
        f"Working dir: <code>{html.escape(wd_display)}</code>\n"
        f"File policy: <code>{html.escape(file_policy)}</code>\n"
        f"Model: <code>{html.escape(model_profile)}</code> ({html.escape(model_id)})\n"
        f"Compact: <code>{compact_display}</code>\n"
        f"Prompt weight: <code>{html.escape(prompt_weight)}</code>\n"
        f"{session_line}\n"
        f"Preflight approval mode: <code>{approval_mode}</code> ({approval_source})\n"
        f"Role: <code>{html.escape(role_display)}</code>\n"
        f"Skills: <code>{html.escape(skills_display)}</code>\n"
        f"Pending: <code>{pending}</code>",
        parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_approval(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    arg = (event.args[0].lower() if event.args else "status")
    if arg not in {"on", "off", "status"}:
        await update.effective_message.reply_text("Use /approval on, /approval off, or /approval status.")
        return
    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        if arg == "status":
            mode = session.approval_mode
            source = _approval_mode_source(session)
            buttons = [
                InlineKeyboardButton(
                    f"\u2705 Review first" if mode == "on" else "Review first",
                    callback_data="setting_approval:on"),
                InlineKeyboardButton(
                    f"\u2705 Run immediately" if mode == "off" else "Run immediately",
                    callback_data="setting_approval:off"),
            ]
            await update.effective_message.reply_text(
                f"Preflight approval mode is <b>{mode}</b> ({source}).",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([buttons]),
            )
            return
        session.approval_mode = arg
        session.approval_mode_explicit = True
        _save(chat_id, session)
    await update.effective_message.reply_text(
        f"Preflight approval mode set to {arg} for this chat."
    )


@_command_handler
async def cmd_approve(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with CHAT_LOCKS[event.chat_id]:
        await approve_pending(event.chat_id, update.effective_message)


@_command_handler
async def cmd_reject(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with CHAT_LOCKS[event.chat_id]:
        await reject_pending(event.chat_id, update.effective_message)


@_command_handler
async def cmd_send(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    if not event.args:
        await update.effective_message.reply_text("Usage: /send <path>")
        return
    raw_path = " ".join(event.args)
    session = _load(event.chat_id)
    resolved_ctx = _resolve_context(session, trust_tier=_trust_tier(event.user))
    resolved = resolve_allowed_path(raw_path, _allowed_roots(event.chat_id, resolved_ctx))
    if not resolved:
        await update.effective_message.reply_text("Path is missing or outside allowed roots.")
        return
    await send_path_to_chat(update.effective_message, resolved)


@_command_handler
async def cmd_id(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = event.user.username or "[none]"
    await update.effective_message.reply_text(
        f"Your user ID: <code>{event.user.id}</code>\n"
        f"Your username: <code>{html.escape(username)}</code>",
        parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_doctor(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import sqlite3
    from app.doctor import collect_doctor_report
    try:
        session = _load(event.chat_id)
    except (sqlite3.DatabaseError, sqlite3.OperationalError, RuntimeError):
        session = None
    kwargs: dict[str, Any] = {}
    if session is not None:
        kwargs.update(session=session_to_dict(session), user_id=event.user.id,
                      encryption_key=_encryption_key())
    report = await collect_doctor_report(_cfg(), _prov(), **kwargs)
    parts: list[str] = []
    if report.errors:
        parts.extend(f"\u274c {html.escape(e)}" for e in report.errors)
    if report.warnings:
        parts.extend(f"\u26a0\ufe0f {html.escape(w)}" for w in report.warnings)
    if parts:
        await update.effective_message.reply_text(
            "\n".join(parts), parse_mode=ParseMode.HTML)
    else:
        await update.effective_message.reply_text("\u2705 All checks passed.")



@_command_handler
async def cmd_export(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _cfg()

    history = export_chat_history(cfg.data_dir, chat_id)
    if not history:
        await update.effective_message.reply_text("No conversation history to export.")
        return

    # Add session metadata header
    session = _load(chat_id)
    skills = session.active_skills
    header_lines = [
        f"Chat ID: {chat_id}",
        f"Provider: {session.provider}",
        f"Approval mode: {session.approval_mode}",
        f"Active skills: {', '.join(skills) if skills else 'none'}",
        f"Created: {(session.created_at or 'unknown')[:19]}",
        "",
        "Note: This export contains up to 50 recent turns — only successful",
        "model responses and approval plans. Denied, timed-out, or failed",
        "requests, command replies, and older history are not captured.",
        "",
        "=" * 40,
        "",
    ]
    full_text = "\n".join(header_lines) + history

    # Send as document
    import io
    doc = io.BytesIO(full_text.encode("utf-8"))
    doc.name = f"chat_{chat_id}_export.txt"
    await update.effective_message.reply_document(document=doc)


@_command_handler
async def cmd_admin(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(event.user):
        await update.effective_message.reply_text("Admin access required.")
        return

    args = event.args
    sub = args[0].lower() if args else ""

    if sub != "sessions":
        await update.effective_message.reply_text(
            "Usage: /admin sessions [chat_id]")
        return

    cfg = _cfg()
    sessions = list_sessions(cfg.data_dir)

    if not sessions:
        await update.effective_message.reply_text("No sessions found.")
        return

    # Filter stale active_skills that no longer resolve
    from app.skills import filter_resolvable_skills
    for s in sessions:
        s["active_skills"] = filter_resolvable_skills(s["active_skills"])

    # Detail view for a specific chat
    if len(args) >= 2:
        try:
            target_id = int(args[1])
        except ValueError:
            await update.effective_message.reply_text("Invalid chat ID.")
            return
        match = next((s for s in sessions if s["chat_id"] == target_id), None)
        if not match:
            await update.effective_message.reply_text(
                f"No session found for chat {target_id}.")
            return
        skills = match["active_skills"]
        skill_list = ", ".join(skills) if skills else "none"
        lines = [
            f"<b>Session {target_id}</b>",
            f"Provider: {html.escape(match['provider'])}",
            f"Approval: {html.escape(match['approval_mode'])}",
            f"Skills ({len(skills)}): {html.escape(skill_list)}",
            f"Pending request: {'yes' if match['has_pending'] else 'no'}",
            f"Credential setup: {'in progress' if match['has_setup'] else 'no'}",
            f"Created: {html.escape(match['created_at'][:19])}",
            f"Updated: {html.escape(match['updated_at'][:19])}",
        ]
        await update.effective_message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML)
        return

    # Summary view
    total = len(sessions)
    pending = sum(1 for s in sessions if s["has_pending"])
    setup = sum(1 for s in sessions if s["has_setup"])
    skill_counts: dict[str, int] = {}
    for s in sessions:
        for sk in s["active_skills"]:
            skill_counts[sk] = skill_counts.get(sk, 0) + 1

    lines = [f"<b>Sessions: {total}</b>"]
    if pending:
        lines.append(f"Pending approval: {pending}")
    if setup:
        lines.append(f"Credential setup: {setup}")
    if skill_counts:
        top = sorted(skill_counts.items(), key=lambda x: -x[1])[:5]
        lines.append("")
        lines.append("<b>Top skills:</b>")
        for sk, count in top:
            lines.append(f"  {html.escape(sk)}: {count}")
    lines.append("")
    lines.append(f"Most recent: chat {sessions[0]['chat_id']}")
    if sessions[0]["updated_at"]:
        lines.append(f"  updated {sessions[0]['updated_at'][:19]}")

    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML)


@_command_handler
async def cmd_skills(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    from app.skill_commands import (
        skills_show, skills_list, skills_add, skills_remove,
        skills_setup, skills_clear, skills_create, skills_search,
        skills_info, skills_install, skills_uninstall, skills_updates,
        skills_diff, skills_update,
    )
    args = event.args
    if not args:
        await skills_show(event, update)
        return

    sub = args[0].lower()
    _SUBS_WITH_ARG = {
        "add": skills_add, "remove": skills_remove, "setup": skills_setup,
        "create": skills_create, "info": skills_info, "install": skills_install,
        "uninstall": skills_uninstall, "diff": skills_diff,
    }
    if sub in _SUBS_WITH_ARG and len(args) >= 2:
        await _SUBS_WITH_ARG[sub](event, update, args[1])
        return
    if sub == "list":
        await skills_list(event, update)
        return
    if sub == "clear":
        await skills_clear(event, update)
        return
    if sub == "search" and len(args) >= 2:
        await skills_search(event, update, " ".join(args[1:]))
        return
    if sub == "updates":
        await skills_updates(event, update)
        return
    if sub == "update" and len(args) >= 2:
        await skills_update(event, update, args[1])
        return

    await update.effective_message.reply_text(
        "Usage: /skills [list|add|remove|setup|create|clear|search|info|install|uninstall|updates|update|diff]"
    )


@_command_handler
async def cmd_cancel(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    chat_id = event.chat_id
    user_id = event.user.id

    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)

        setup = session.awaiting_skill_setup
        if setup:
            if setup.user_id == user_id or is_admin(event.user):
                session.awaiting_skill_setup = None
                _save(chat_id, session)
                await update.effective_message.reply_text("Credential setup cancelled.")
                return
            else:
                await update.effective_message.reply_text(
                    "Another user's credential setup is in progress. Only they or an admin can cancel it.",
                )
                return

        if session.has_pending:
            session.clear_pending()
            _save(chat_id, session)
            await update.effective_message.reply_text("Pending request cancelled.")
            return

    await update.effective_message.reply_text("Nothing to cancel.")


@_command_handler
async def cmd_clear_credentials(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    user_id = event.user.id
    args = event.args
    skill_name = args[0] if args else None

    cfg = _cfg()
    stored = list_user_credential_skills(cfg.data_dir, user_id)

    if skill_name:
        if skill_name not in stored:
            await update.effective_message.reply_text(
                f"No stored credentials for <code>{html.escape(skill_name)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return
        affected = [skill_name]
        msg = (f"This will remove your credentials for "
               f"<code>{html.escape(skill_name)}</code> and deactivate it "
               f"in this chat. Continue?")
        cb_data = f"clear_cred_confirm:{user_id}:{skill_name}"
    else:
        if not stored:
            await update.effective_message.reply_text("No stored credentials found.")
            return
        affected = stored
        names = html.escape(", ".join(affected))
        msg = (f"This will remove all your stored credentials "
               f"({names}) and deactivate affected skills. Continue?")
        cb_data = f"clear_cred_confirm_all:{user_id}"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes, clear", callback_data=cb_data),
        InlineKeyboardButton("Cancel", callback_data=f"clear_cred_cancel:{user_id}"),
    ]])
    await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML,
                                              reply_markup=keyboard)


async def _execute_clear_credentials(
    query, chat_id: int, user_id: int, skill_name: str | None,
) -> None:
    """Shared logic for clearing credentials after confirmation."""
    cfg = _cfg()
    key = _encryption_key()
    removed = delete_user_credentials(cfg.data_dir, user_id, key, skill_name)

    # Clear in-progress setup even if no credentials were saved yet
    setup_cleared = False
    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        setup = session.awaiting_skill_setup
        if setup and setup.user_id == user_id:
            if skill_name is None or setup.skill == skill_name:
                session.awaiting_skill_setup = None
                setup_cleared = True

        active = session.active_skills
        deactivated = []
        for name in removed:
            if name in active and get_skill_requirements(name):
                active.remove(name)
                deactivated.append(name)
        if deactivated or setup_cleared:
            _save(chat_id, session)

    parts = []
    if removed:
        parts.append(f"Credentials cleared for: {html.escape(', '.join(removed))}.")
    if setup_cleared:
        parts.append("Credential setup cancelled.")
    if deactivated:
        parts.append(f"Deactivated in this chat: {html.escape(', '.join(deactivated))}.")
    if not parts:
        parts.append("No credentials to clear (may have already been removed).")
    await query.edit_message_text("\n".join(parts), parse_mode=ParseMode.HTML)


@_callback_handler
async def handle_clear_cred_callback(event, query) -> None:
    chat_id = event.chat_id
    clicker_id = event.user.id

    # All callback data encodes the initiating user: clear_cred_<action>:<uid>[:<skill>]
    # Reject if a different user clicks the button.
    parts = event.data.split(":")
    # parts[0] = "clear_cred_cancel" | "clear_cred_confirm" | "clear_cred_confirm_all"
    if len(parts) >= 2:
        try:
            owner_id = int(parts[1])
        except (ValueError, IndexError):
            owner_id = 0
        if owner_id and clicker_id != owner_id:
            await query.answer("This button is for another user.", show_alert=True)
            return

    await query.answer()

    if parts[0] == "clear_cred_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Credential clear cancelled.")
        return

    if parts[0] == "clear_cred_confirm_all":
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, None)
        return

    if parts[0] == "clear_cred_confirm" and len(parts) >= 3:
        skill_name = parts[2]
        await query.edit_message_reply_markup(reply_markup=None)
        await _execute_clear_credentials(query, chat_id, clicker_id, skill_name)
        return


@_command_handler
async def cmd_compact(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(chat_id)
        current = session.compact_mode if session.compact_mode is not None else _cfg().compact_mode
        state = "on" if current else "off"
        buttons = [
            InlineKeyboardButton(
                "\u2705 Short answers" if current else "Short answers",
                callback_data="setting_compact:on"),
            InlineKeyboardButton(
                "\u2705 Full answers" if not current else "Full answers",
                callback_data="setting_compact:off"),
        ]
        await update.effective_message.reply_text(
            f"Compact mode is <b>{state}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
        return

    mode = args[0].lower()
    if mode not in {"on", "off"}:
        await update.effective_message.reply_text("Usage: /compact on|off")
        return

    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        session.compact_mode = mode == "on"
        _save(chat_id, session)

    label = "on — long responses will be summarized" if mode == "on" else "off"
    await update.effective_message.reply_text(
        f"Compact mode set to <b>{label}</b>.", parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_raw(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = event.chat_id
    cfg = _cfg()
    args = event.args

    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            await update.effective_message.reply_text("Usage: /raw [N] — N is the Nth most recent response (default: 1)")
            return

    raw_text = load_raw(cfg.data_dir, chat_id, n)
    if raw_text is None:
        await update.effective_message.reply_text("No stored responses found.")
        return

    await send_formatted_reply(update.effective_message, raw_text)


@_command_handler
async def cmd_role(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    chat_id = event.chat_id
    args = event.args

    if not args:
        session = _load(chat_id)
        role = session.role
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
            session.role = cfg.role
            _save(chat_id, session)
        await update.effective_message.reply_text("Role reset to instance default.")
        return

    role_text = " ".join(args)
    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)
        session.role = role_text
        _save(chat_id, session)
    await update.effective_message.reply_text(
        f"Role set to: <code>{html.escape(role_text)}</code>", parse_mode=ParseMode.HTML,
    )


@_command_handler
async def cmd_model(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg()
    msg = update.effective_message
    chat_id = event.chat_id

    if not cfg.model_profiles:
        await msg.reply_text("No model profiles configured. Set BOT_MODEL_PROFILES.")
        return

    # Determine available profiles
    trust = _trust_tier(event.user)
    if trust == "public" and cfg.public_model_profiles:
        available = sorted(cfg.public_model_profiles & cfg.model_profiles.keys())
    else:
        available = sorted(cfg.model_profiles.keys())

    arg = event.args[0].lower() if event.args else ""

    if arg and arg != "status":
        if arg not in available:
            await msg.reply_text(
                f"Unknown profile. Available: {', '.join(available)}")
            return
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            session.model_profile = arg
            _save(chat_id, session)
        await msg.reply_text(
            f"Model profile set to <b>{html.escape(arg)}</b> "
            f"(<code>{html.escape(cfg.model_profiles[arg])}</code>).",
            parse_mode=ParseMode.HTML,
        )
        return

    # Show current + inline keyboard
    session = _load(chat_id)
    current = session.model_profile or cfg.default_model_profile or "(none)"
    from app.execution_context import resolve_effective_model
    effective = resolve_effective_model(session, cfg, trust)

    buttons = []
    for profile in available:
        label = f"\u2705 {profile}" if profile == current else profile
        buttons.append(InlineKeyboardButton(label, callback_data=f"setting_model:{profile}"))

    text = (
        f"Model profile: <b>{html.escape(current)}</b>\n"
        f"Effective model: <code>{html.escape(effective or cfg.model or '(default)')}</code>"
    )
    if buttons:
        await msg.reply_text(text, parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup([buttons]))
    else:
        await msg.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _dedup_update(update):
        return

    user = normalize_user(update.effective_user)
    if user is None or not is_allowed(user):
        return

    # Rate limit check (admins exempt)
    if _rate_limiter and _rate_limiter.enabled and not (_cfg().admin_users_explicit and is_admin(user)):
        allowed, retry_after = _rate_limiter.check(user.id)
        if not allowed:
            await update.effective_message.reply_text(
                f"Rate limit reached. Please wait {retry_after} seconds.")
            return

    msg = await normalize_message(update, context, _cfg().data_dir)
    if msg is None:
        return

    message = update.effective_message
    chat_id = msg.chat_id
    prompt, image_paths = build_user_prompt(msg.text, list(msg.attachments))

    user_id = user.id

    # First-run welcome for plain messages only (commands like /start and /help
    # already provide orientation, so the welcome is only needed when a user
    # sends a plain message without knowing what the bot does).
    cfg = _cfg()
    if not session_exists(cfg.data_dir, chat_id):
        welcome = "I'm ready. Send me a message or type /help to see what I can do."
        if cfg.approval_mode == "on":
            welcome += "\nApproval mode is on \u2014 I'll show a plan before acting."
        await message.chat.send_message(welcome)

    # Busy/queued feedback: if another request is in-flight for this chat, acknowledge
    lock = CHAT_LOCKS[chat_id]
    if lock.locked():
        await message.reply_text("<i>Working on your previous request \u2014 yours is queued.</i>",
                                 parse_mode=ParseMode.HTML)

    async with lock:
        await message.chat.send_action(ChatAction.TYPING)
        session = _load(chat_id)

        setup = session.awaiting_skill_setup
        if setup and setup.user_id == user_id:
            cfg = _cfg()
            key = _encryption_key()
            req = setup.remaining[0]
            raw_value = (message.text or "").strip()
            if not raw_value:
                await message.reply_text("Please send the credential value as a text message.")
                return

            if req.get("validate"):
                ok, detail = await validate_credential(
                    SkillRequirement(key=req["key"], prompt=req["prompt"],
                                     help_url=req.get("help_url"), validate=req["validate"]),
                    raw_value,
                )
                if not ok:
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
                cfg.data_dir, user_id, setup.skill, req["key"], raw_value, key,
            )

            try:
                await message.delete()
            except Exception:
                log.warning("Could not delete credential message for user %d", user_id)

            setup.remaining.pop(0)
            if setup.remaining:
                next_req = setup.remaining[0]
                _save(chat_id, session)
                await message.reply_text(
                    format_credential_prompt(next_req),
                    parse_mode=ParseMode.HTML,
                )
            else:
                skill_name = setup.skill
                session.awaiting_skill_setup = None
                if skill_name not in session.active_skills:
                    session.active_skills.append(skill_name)
                _save(chat_id, session)
                await message.reply_text(
                    f"Skill <code>{html.escape(skill_name)}</code> is ready.",
                    parse_mode=ParseMode.HTML,
                )
            return

        trust = _trust_tier(user)

        if session.approval_mode == "on":
            await request_approval(chat_id, prompt, image_paths, list(msg.attachments), message, request_user_id=user_id, trust_tier=trust)
            return
        await execute_request(chat_id, prompt, image_paths, message, request_user_id=user_id, trust_tier=trust)


@_callback_handler
async def handle_callback(event, query) -> None:
    await query.answer()
    chat_id = event.chat_id

    async with CHAT_LOCKS[chat_id]:
        if event.data == "approval_approve":
            await query.edit_message_reply_markup(reply_markup=None)
            await approve_pending(chat_id, query.message)
            return

        if event.data == "approval_reject":
            await query.edit_message_reply_markup(reply_markup=None)
            await reject_pending(chat_id, query.message)
            return

        if event.data == "retry_skip":
            session = _load(chat_id)
            session.clear_pending()
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.edit_text("Skipped.")
            return

        if event.data == "retry_allow":
            session = _load(chat_id)
            pending = session.pending_retry
            if not pending:
                await query.message.edit_text("Nothing to retry.")
                return

            error = validate_pending(pending, session, _cfg(), _prov().name)
            if error:
                session.clear_pending()
                _save(chat_id, session)
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.edit_text(error)
                return

            prompt = pending.prompt
            denials = pending.denials or []
            request_user_id = pending.request_user_id
            trust_tier = getattr(pending, 'trust_tier', 'trusted')
            session.clear_pending()

            denial_dirs = extra_dirs_from_denials(denials)

            if denial_dirs and _prov().name == "codex":
                session.provider_state["thread_id"] = None

            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)

            await execute_request(
                chat_id, prompt, pending.image_paths,
                query.message, denial_dirs,
                request_user_id=request_user_id,
                skip_permissions=True,
                trust_tier=trust_tier,
            )


# -- Expand/collapse callback handler --------------------------------------


@_callback_handler
async def handle_expand_callback(event, query) -> None:
    """Handle 'Show full answer' button presses."""
    await query.answer()
    data = event.data  # e.g. "expand:12345:42"
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, chat_id_str, slot_str = parts
    try:
        target_chat = int(chat_id_str)
        slot = int(slot_str)
    except ValueError:
        return

    from app.summarize import load_raw_by_slot
    cfg = _cfg()
    raw_text = load_raw_by_slot(cfg.data_dir, target_chat, slot)
    if raw_text is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.edit_text(
            "<i>Response no longer available (ring buffer rotated). Use /raw to check.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Replace the compact message with the full response
    await query.edit_message_reply_markup(reply_markup=None)
    formatted = md_to_telegram_html(raw_text)
    # If it fits in one message, edit in-place
    if len(formatted) <= 4000:
        try:
            await query.message.edit_text(
                formatted, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return
        except BadRequest:
            pass
    # Too long to edit — send as new messages
    for chunk in split_html(formatted, 4096):
        try:
            await query.message.chat.send_message(
                chunk, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except BadRequest:
            plain = re.sub(r"<[^>]+>", "", chunk)
            await query.message.chat.send_message(plain[:4096])


# -- Settings callback handler ---------------------------------------------


@_callback_handler
async def handle_settings_callback(event, query) -> None:
    """Handle inline-keyboard callbacks for session settings."""
    await query.answer()
    chat_id = event.chat_id
    data = event.data  # e.g. "setting_model:fast", "setting_approval:on"

    if not data.startswith("setting_"):
        return

    _, rest = data.split("_", 1)
    if ":" not in rest:
        return
    setting, value = rest.split(":", 1)

    async with CHAT_LOCKS[chat_id]:
        session = _load(chat_id)

        if setting == "model":
            cfg = _cfg()
            # Use the same availability logic as /model command
            trust = _trust_tier(event.user)
            if trust == "public" and cfg.public_model_profiles:
                available = cfg.public_model_profiles & cfg.model_profiles.keys()
            else:
                available = set(cfg.model_profiles.keys())
            if value not in available:
                await query.edit_message_text(f"Unknown or restricted profile: {value}")
                return
            session.model_profile = value
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"Model profile set to <b>{html.escape(value)}</b> "
                f"(<code>{html.escape(cfg.model_profiles[value])}</code>).",
                parse_mode=ParseMode.HTML,
            )

        elif setting == "approval":
            if value not in {"on", "off"}:
                return
            session.approval_mode = value
            session.approval_mode_explicit = True
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"Preflight approval mode set to {value} for this chat.")

        elif setting == "compact":
            session.compact_mode = value == "on"
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            label = "on — long responses will be summarized" if value == "on" else "off"
            await query.edit_message_text(
                f"Compact mode set to <b>{label}</b>.",
                parse_mode=ParseMode.HTML,
            )

        elif setting == "policy":
            if is_public_user(event.user):
                await query.edit_message_text("File policy cannot be changed in public mode.")
                return
            if value not in {"inspect", "edit"}:
                return
            session.file_policy = value
            session.provider_state = _prov().new_provider_state()
            session.clear_pending()
            _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"File policy set to <code>{html.escape(value)}</code>. Provider session reset.",
                parse_mode=ParseMode.HTML,
            )


# -- Application builder ---------------------------------------------------


@_callback_handler
async def handle_skill_add_callback(event, query) -> None:
    await query.answer()
    chat_id = event.chat_id

    if event.data == "skill_add_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Skill activation cancelled.")
        return

    if event.data.startswith("skill_add_confirm:"):
        name = event.data.split(":", 1)[1]
        async with CHAT_LOCKS[chat_id]:
            session = _load(chat_id)
            if name not in session.active_skills:
                session.active_skills.append(name)
                _save(chat_id, session)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(
                f"Skill <code>{html.escape(name)}</code> activated.",
                parse_mode=ParseMode.HTML)


@_callback_handler
async def handle_skill_update_callback(event, query) -> None:
    if not is_admin(event.user):
        await query.answer("Only admins can update skills.", show_alert=True)
        return

    await query.answer()

    if event.data == "skill_update_cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("Update cancelled.")
        return

    if event.data.startswith("skill_update_confirm:"):
        from app.store import update_skill as store_update_skill
        name = event.data.split(":", 1)[1]
        ok, msg = store_update_skill(name)
        if ok:
            cfg = _cfg()
            size_warnings = _check_prompt_size_cross_chat(cfg.data_dir, name)
            if size_warnings:
                msg += "\n\nPrompt size warnings:\n" + "\n".join(size_warnings)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(html.escape(msg), parse_mode=ParseMode.HTML)
        return

    if event.data == "skill_update_all_confirm":
        from app.store import update_all as store_update_all
        results = store_update_all()
        if not results:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text("No store skills need updating.")
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
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

@_command_handler
async def cmd_project(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    cfg = _cfg()
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    if arg == "list":
        if not cfg.projects:
            await msg.reply_text("No projects configured. Set BOT_PROJECTS in your instance config.")
            return
        session = _load(event.chat_id)
        current = session.project_id
        lines = ["<b>Available projects:</b>"]
        for name, root_dir, _ in cfg.projects:
            marker = " (active)" if name == current else ""
            lines.append(f"  <code>{html.escape(name)}</code> \u2192 {html.escape(root_dir)}{marker}")
        await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if arg == "use" and len(event.args) >= 2:
        project_name = event.args[1]
        found = any(name == project_name for name, _, _ in cfg.projects)
        if not found:
            await msg.reply_text(
                f"Unknown project: <code>{html.escape(project_name)}</code>\n"
                f"Use /project list to see available projects.",
                parse_mode=ParseMode.HTML,
            )
            return
        session = _load(event.chat_id)
        old_project = session.project_id
        if old_project == project_name:
            await msg.reply_text(f"Already using project <code>{html.escape(project_name)}</code>.", parse_mode=ParseMode.HTML)
            return
        session.project_id = project_name
        session.provider_state = _prov().new_provider_state()
        session.clear_pending()
        _save(event.chat_id, session)
        proj_root = next(root for name, root, _ in cfg.projects if name == project_name)
        await msg.reply_text(
            f"Switched to project <code>{html.escape(project_name)}</code>\n"
            f"Working dir: <code>{html.escape(proj_root)}</code>\n"
            f"Provider session reset.",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "clear":
        session = _load(event.chat_id)
        if not session.project_id:
            await msg.reply_text("No project is active.")
            return
        session.project_id = ""
        session.provider_state = _prov().new_provider_state()
        session.clear_pending()
        _save(event.chat_id, session)
        await msg.reply_text(
            f"Project cleared. Using instance default: <code>{html.escape(str(cfg.working_dir))}</code>\n"
            f"Provider session reset.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Default: show current project
    session = _load(event.chat_id)
    proj = _resolve_project(session)
    if proj:
        await msg.reply_text(
            f"Project: <code>{html.escape(proj[0])}</code>\n"
            f"Working dir: <code>{html.escape(proj[1])}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.reply_text(
            f"No project active. Using instance default: <code>{html.escape(str(cfg.working_dir))}</code>",
            parse_mode=ParseMode.HTML,
        )


@_command_handler
async def cmd_policy(event, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _public_guard(event, update):
        return
    msg = update.effective_message
    arg = event.args[0].lower() if event.args else ""

    if arg in ("inspect", "edit"):
        session = _load(event.chat_id)
        old_policy = session.file_policy or "edit"
        if old_policy == arg:
            await msg.reply_text(f"File policy is already <code>{html.escape(arg)}</code>.", parse_mode=ParseMode.HTML)
            return
        session.file_policy = arg
        session.provider_state = _prov().new_provider_state()
        session.clear_pending()
        _save(event.chat_id, session)
        await msg.reply_text(
            f"File policy set to <code>{html.escape(arg)}</code>.\nProvider session reset.",
            parse_mode=ParseMode.HTML,
        )
        return

    if arg == "" or arg == "status":
        session = _load(event.chat_id)
        policy = session.file_policy or "edit"
        buttons = [
            InlineKeyboardButton(
                "\u2705 Read only" if policy == "inspect" else "Read only",
                callback_data="setting_policy:inspect"),
            InlineKeyboardButton(
                "\u2705 Read & write" if policy == "edit" else "Read & write",
                callback_data="setting_policy:edit"),
        ]
        await msg.reply_text(
            f"File policy: <b>{html.escape(policy)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
        return

    await msg.reply_text("Use /policy inspect, /policy edit, or /policy status.")


def build_application(config: BotConfig, provider: Provider) -> Application:
    global _config, _provider, _boot_id, _rate_limiter
    _config = config
    _provider = provider
    _boot_id = uuid.uuid4().hex
    # Apply conservative rate-limit defaults for public mode
    per_minute = config.rate_limit_per_minute
    per_hour = config.rate_limit_per_hour
    if config.allow_open and per_minute == 0 and per_hour == 0:
        per_minute = 5
        per_hour = 30
        log.info("Public mode: applying default rate limits (5/min, 30/hr)")
    _rate_limiter = RateLimiter(per_minute=per_minute, per_hour=per_hour)

    app = Application.builder().token(config.telegram_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("session", cmd_session))
    app.add_handler(CommandHandler("approval", cmd_approval))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("reject", cmd_reject))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("clear_credentials", cmd_clear_credentials))
    app.add_handler(CommandHandler("role", cmd_role))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(CommandHandler("raw", cmd_raw))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("doctor", cmd_doctor))
    app.add_handler(CommandHandler("project", cmd_project))
    app.add_handler(CommandHandler("policy", cmd_policy))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(retry_|approval_)"))
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern=r"^setting_"))
    app.add_handler(CallbackQueryHandler(handle_expand_callback, pattern=r"^expand:"))
    app.add_handler(CallbackQueryHandler(handle_skill_add_callback, pattern=r"^skill_add_"))
    app.add_handler(CallbackQueryHandler(handle_skill_update_callback, pattern=r"^skill_update_"))
    app.add_handler(CallbackQueryHandler(handle_clear_cred_callback, pattern=r"^clear_cred_"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
            handle_message,
        )
    )
    return app
