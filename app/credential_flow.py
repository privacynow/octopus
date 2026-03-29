"""Credential setup rendering helpers shared by runtime-skill channels."""

from __future__ import annotations

import html
from urllib.parse import urlparse

from octopus_sdk.sessions import AwaitingSkillSetup
from octopus_sdk.time_utils import age_seconds, utc_now


def format_credential_prompt(req: dict) -> str:
    text = html.escape(req["prompt"])
    validate = req.get("validate")
    if isinstance(validate, dict):
        url = str(validate.get("url", "")).strip()
        host = (urlparse(url).hostname or "").strip()
        if host:
            text += f"\nValidation host: <code>{html.escape(host)}</code>"
    if req.get("help_url"):
        url = html.escape(req["help_url"])
        text += f'\n(<a href="{url}">setup guide</a>)'
    return text


def foreign_setup_message(setup: AwaitingSkillSetup) -> str:
    uid = setup.actor_key
    elapsed = int(age_seconds(setup.started_at, now=utc_now()) or 0)
    minutes = elapsed // 60
    time_str = f"{minutes} min ago" if minutes >= 1 else "just now"
    return (
        f"User {uid} is completing credential setup (started {time_str}). "
        f"Please wait or ask them to finish. An admin can use /cancel to clear it."
    )
