"""Approval flow data shaping. No Telegram I/O — pure functions only."""

import html
import json
from typing import Any


def build_preflight_prompt(user_prompt: str, provider_name: str) -> str:
    return (
        f"Preflight this user request for a Telegram bridge that runs {provider_name} CLI.\n"
        "Do not modify files. Do not run shell commands.\n"
        "Respond briefly in Markdown with these sections exactly:\n"
        "## Tool use\n"
        "- whether shell commands are likely needed\n"
        "- whether file edits are likely needed\n"
        "- whether risky actions are likely needed\n"
        "## Planned actions\n"
        "- short bullets\n"
        "## Approval advice\n"
        "- Approve or Reject / ask for clarification\n\n"
        f"User request:\n{user_prompt}"
    )


def serialize_pending_request(
    prompt: str,
    image_paths: list[str],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "image_paths": image_paths,
        "attachments": attachments,
    }


def clear_pending_request(session: dict[str, Any]) -> dict[str, Any]:
    session["pending_request"] = None
    return session


def format_denials_html(denials: list[dict[str, Any]]) -> str:
    lines = []
    for d in denials:
        tool = html.escape(d.get("tool_name", "?"))
        inp = html.escape(json.dumps(d.get("tool_input", {}))[:200])
        lines.append(f"\u2022 <b>{tool}</b>: <code>{inp}</code>")
    return "\n".join(lines)
