"""Credential setup flow helpers shared by runtime-skill use cases and adapters."""

from __future__ import annotations

import html

from app.session_state import AwaitingSkillSetup, SessionState
from app.skill_types import SkillRequirement
from app.time_utils import age_seconds, utc_now, utc_now_timestamp

SETUP_TIMEOUT_SECONDS = 300


def build_setup_state(
    user_id: str,
    skill_name: str,
    missing: list[SkillRequirement | dict[str, object]],
) -> AwaitingSkillSetup:
    remaining: list[dict[str, object]] = []
    for item in missing:
        if isinstance(item, dict):
            key = str(item.get("key", "") or "")
            if not key:
                continue
            remaining.append(
                {
                    "key": key,
                    "prompt": str(item.get("prompt", "") or ""),
                    "help_url": item.get("help_url"),
                    "validate": item.get("validate"),
                }
            )
            continue
        remaining.append(
            {
                "key": item.key,
                "prompt": item.prompt,
                "help_url": item.help_url,
                "validate": item.validate,
            }
        )
    return AwaitingSkillSetup(
        user_id=user_id,
        skill=skill_name,
        started_at=utc_now_timestamp(),
        remaining=remaining,
    )


def format_credential_prompt(req: dict) -> str:
    text = html.escape(req["prompt"])
    if req.get("help_url"):
        url = html.escape(req["help_url"])
        text += f'\n(<a href="{url}">setup guide</a>)'
    return text


def foreign_setup_message(setup: AwaitingSkillSetup) -> str:
    uid = setup.user_id
    elapsed = int(age_seconds(setup.started_at, now=utc_now()) or 0)
    minutes = elapsed // 60
    time_str = f"{minutes} min ago" if minutes >= 1 else "just now"
    return (
        f"User {uid} is completing credential setup (started {time_str}). "
        f"Please wait or ask them to finish. An admin can use /cancel to clear it."
    )


def foreign_skill_setup(
    session: SessionState,
    user_id: str,
    skill_name: str | None = None,
) -> AwaitingSkillSetup | None:
    setup = session.awaiting_skill_setup
    if not setup or setup.user_id == user_id:
        return None
    if skill_name is not None and setup.skill != skill_name:
        return None
    age = age_seconds(setup.started_at, now=utc_now())
    if age is None or age > SETUP_TIMEOUT_SECONDS:
        session.awaiting_skill_setup = None
        return None
    return setup
