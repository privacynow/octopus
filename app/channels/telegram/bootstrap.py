"""Telegram channel bootstrap ownership."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.channels.telegram import ingress
from app.channels.telegram.state import TelegramRuntime, build_telegram_runtime
from app.config import BotConfig
from app.providers.base import Provider


@dataclass(frozen=True)
class TelegramBootstrap:
    """Bootstrap-owned Telegram channel bundle."""

    application: Application
    runtime: TelegramRuntime
    worker_dispatch: Callable[[str, Any, dict], Awaitable[None]]


def build_application(runtime: TelegramRuntime) -> Application:
    from app.content_store import init_content_store_for_config
    from app.credential_store import init_credential_store_for_config

    config = runtime.config
    init_content_store_for_config(config)
    init_credential_store_for_config(config)
    if config.allow_open and config.rate_limit_per_minute == 0 and config.rate_limit_per_hour == 0:
        ingress.log.info("Public mode: applying default rate limits (5/min, 30/hr)")

    builder = Application.builder().token(config.telegram_token)
    if config.telegram_api_base_url:
        builder = builder.base_url(config.telegram_api_base_url)
    if config.telegram_file_api_base_url:
        builder = builder.base_file_url(config.telegram_file_api_base_url)
    app = builder.build()
    runtime.bot_instance = app.bot
    app.bot_data["telegram_boot_id"] = runtime.boot_id
    app.bot_data["telegram_runtime"] = runtime

    if config.runtime_mode == "shared":
        app.add_handler(CommandHandler("start", ingress.cmd_start))
        app.add_handler(CommandHandler("help", ingress.cmd_help))
        app.add_handler(CommandHandler("session", ingress.cmd_session))
        app.add_handler(CommandHandler("clear_credentials", ingress.cmd_clear_credentials))
        app.add_handler(CommandHandler("raw", ingress.cmd_raw))
        app.add_handler(CommandHandler("send", ingress.cmd_send))
        app.add_handler(CommandHandler("id", ingress.cmd_id))
        app.add_handler(CommandHandler("doctor", ingress.cmd_doctor))
        app.add_handler(CommandHandler("discover", ingress.cmd_discover))
        app.add_handler(CommandHandler("settings", ingress.cmd_settings))
        app.add_handler(CommandHandler("allowuser", ingress.cmd_allowuser))
        app.add_handler(CommandHandler("blockuser", ingress.cmd_blockuser))
        app.add_handler(CommandHandler("listaccess", ingress.cmd_listaccess))
        app.add_handler(CommandHandler("export", ingress.cmd_export))
        app.add_handler(CommandHandler("admin", ingress.cmd_admin))
        for command in (
            "new",
            "approval",
            "approve",
            "reject",
            "skills",
            "cancel",
            "role",
            "compact",
            "project",
            "policy",
            "model",
        ):
            app.add_handler(CommandHandler(command, ingress._shared_command_dispatch))
        app.add_handler(CallbackQueryHandler(ingress._shared_callback_dispatch, pattern=r"^(retry_|approval_)"))
        app.add_handler(CallbackQueryHandler(ingress._shared_callback_dispatch, pattern=r"^delegation_"))
        app.add_handler(CallbackQueryHandler(ingress._shared_callback_dispatch, pattern=r"^recovery_"))
        app.add_handler(CallbackQueryHandler(ingress._shared_callback_dispatch, pattern=r"^setting_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_expand_callback, pattern=r"^expand:"))
        app.add_handler(CallbackQueryHandler(ingress.handle_collapse_callback, pattern=r"^collapse:"))
        app.add_handler(CallbackQueryHandler(ingress._shared_callback_dispatch, pattern=r"^skill_add_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_skill_update_callback, pattern=r"^skill_update_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_clear_cred_callback, pattern=r"^clear_cred_"))
    else:
        app.add_handler(CommandHandler("start", ingress.cmd_start))
        app.add_handler(CommandHandler("help", ingress.cmd_help))
        app.add_handler(CommandHandler("new", ingress.cmd_new))
        app.add_handler(CommandHandler("session", ingress.cmd_session))
        app.add_handler(CommandHandler("approval", ingress.cmd_approval))
        app.add_handler(CommandHandler("approve", ingress.cmd_approve))
        app.add_handler(CommandHandler("reject", ingress.cmd_reject))
        app.add_handler(CommandHandler("skills", ingress.cmd_skills))
        app.add_handler(CommandHandler("guidance", ingress.cmd_guidance))
        app.add_handler(CommandHandler("cancel", ingress.cmd_cancel))
        app.add_handler(CommandHandler("clear_credentials", ingress.cmd_clear_credentials))
        app.add_handler(CommandHandler("role", ingress.cmd_role))
        app.add_handler(CommandHandler("compact", ingress.cmd_compact))
        app.add_handler(CommandHandler("raw", ingress.cmd_raw))
        app.add_handler(CommandHandler("send", ingress.cmd_send))
        app.add_handler(CommandHandler("id", ingress.cmd_id))
        app.add_handler(CommandHandler("doctor", ingress.cmd_doctor))
        app.add_handler(CommandHandler("discover", ingress.cmd_discover))
        app.add_handler(CommandHandler("settings", ingress.cmd_settings))
        app.add_handler(CommandHandler("project", ingress.cmd_project))
        app.add_handler(CommandHandler("policy", ingress.cmd_policy))
        app.add_handler(CommandHandler("model", ingress.cmd_model))
        app.add_handler(CommandHandler("allowuser", ingress.cmd_allowuser))
        app.add_handler(CommandHandler("blockuser", ingress.cmd_blockuser))
        app.add_handler(CommandHandler("listaccess", ingress.cmd_listaccess))
        app.add_handler(CommandHandler("export", ingress.cmd_export))
        app.add_handler(CommandHandler("admin", ingress.cmd_admin))
        app.add_handler(CallbackQueryHandler(ingress.handle_callback, pattern=r"^(retry_|approval_)"))
        app.add_handler(CallbackQueryHandler(ingress.handle_delegation_callback, pattern=r"^delegation_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_recovery_callback, pattern=r"^recovery_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_settings_callback, pattern=r"^setting_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_expand_callback, pattern=r"^expand:"))
        app.add_handler(CallbackQueryHandler(ingress.handle_collapse_callback, pattern=r"^collapse:"))
        app.add_handler(CallbackQueryHandler(ingress.handle_skill_add_callback, pattern=r"^skill_add_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_skill_update_callback, pattern=r"^skill_update_"))
        app.add_handler(CallbackQueryHandler(ingress.handle_clear_cred_callback, pattern=r"^clear_cred_"))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND,
            ingress.handle_message,
        )
    )
    app.add_error_handler(ingress._global_error_handler)
    return app


def build_bootstrap(config: BotConfig, provider: Provider) -> TelegramBootstrap:
    """Construct the Telegram runtime, PTB application, and worker dispatch."""

    runtime = build_telegram_runtime(config, provider)
    application = build_application(runtime)
    return TelegramBootstrap(
        application=application,
        runtime=runtime,
        worker_dispatch=functools.partial(ingress.worker_dispatch, runtime=runtime),
    )
