"""Delegation contracts and the default XML-tag parser."""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable
from uuid import uuid4

log = logging.getLogger(__name__)

_DELEGATION_OPEN = "<delegation>"
_DELEGATION_CLOSE = "</delegation>"


@runtime_checkable
class DelegationIntentParser(Protocol):
    """Parse delegation intent from a provider response."""

    def parse(self, response_text: str, available_agents: list[dict[str, str]]) -> list[dict[str, str]]: ...


class XmlTagDelegationParser:
    """Parse <delegation>{\"tasks\": [...]}</delegation> blocks from provider output."""

    def parse(self, response_text: str, available_agents: list[dict[str, str]]) -> list[dict[str, str]]:
        if not response_text or not available_agents:
            return []
        start = response_text.find(_DELEGATION_OPEN)
        if start < 0:
            return []
        end = response_text.find(_DELEGATION_CLOSE, start)
        if end < 0:
            return []
        raw_json = response_text[start + len(_DELEGATION_OPEN):end].strip()
        if not raw_json:
            return []
        try:
            parsed = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            log.warning("Failed to parse delegation JSON from provider response")
            return []
        raw_tasks = parsed.get("tasks")
        if not isinstance(raw_tasks, list):
            return []
        slug_to_agent = {a["slug"]: a for a in available_agents if a.get("slug")}
        tasks: list[dict[str, str]] = []
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            target_slug = str(task.get("target", "")).strip()
            agent = slug_to_agent.get(target_slug)
            if not agent:
                log.warning("Delegation target slug '%s' not found in available agents", target_slug)
                continue
            tasks.append(
                {
                    "routed_task_id": uuid4().hex,
                    "target_agent_id": agent["agent_id"],
                    "title": str(task.get("title", "")).strip() or "Delegated task",
                    "instructions": str(task.get("instructions", "")).strip(),
                }
            )
        return tasks
