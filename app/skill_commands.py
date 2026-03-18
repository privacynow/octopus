"""Telegram /skills adapter entrypoints."""

import asyncio

from app.telegram_runtime_skill_surface import (
    skills_add,
    skills_clear,
    skills_create,
    skills_diff,
    skills_info,
    skills_install,
    skills_list,
    skills_remove,
    skills_search,
    skills_setup,
    skills_show,
    skills_uninstall,
    skills_update,
    skills_updates,
)

__all__ = [
    "skills_add",
    "skills_clear",
    "skills_create",
    "skills_diff",
    "skills_info",
    "skills_install",
    "skills_list",
    "skills_remove",
    "skills_search",
    "skills_setup",
    "skills_show",
    "skills_uninstall",
    "skills_update",
    "skills_updates",
]
