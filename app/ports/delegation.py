"""Delegation intent parser port — pluggable by composition on ExecutionRuntime."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DelegationIntentParser(Protocol):
    """Parse delegation intent from a provider response.

    available_agents is a list of dicts with keys: slug, agent_id, display_name, etc.
    Returns a list of task dicts with keys: routed_task_id, target_agent_id, title, instructions.
    """
    def parse(self, response_text: str, available_agents: list[dict[str, str]]) -> list[dict[str, str]]: ...
