"""Approval flow data shaping. No channel I/O — pure functions only."""

import html
import json
from typing import Any

from octopus_sdk.approvals import build_preflight_prompt


def format_denials_html(denials: list[dict[str, Any]]) -> str:
    lines = []
    for d in denials:
        tool = html.escape(d.get("tool_name", "?"))
        inp = html.escape(json.dumps(d.get("tool_input", {}))[:200])
        lines.append(f"\u2022 <b>{tool}</b>: <code>{inp}</code>")
    return "\n".join(lines)
