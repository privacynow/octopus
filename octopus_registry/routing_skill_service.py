"""Shared service layer for registry routing-skill policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .store_base import AbstractRegistryStore


@dataclass(frozen=True)
class RoutingSkillRecord:
    skill_name: str
    advertised_by_agents: tuple[str, ...]
    enabled: bool | None


class RoutingSkillService:
    """Channel-neutral registry routing-skill policy service."""

    def __init__(self, store: AbstractRegistryStore) -> None:
        self._store = store

    def list_routing_skills(self) -> list[RoutingSkillRecord]:
        return [
            RoutingSkillRecord(
                skill_name=str(item.get("skill_name", "")),
                advertised_by_agents=tuple(item.get("advertised_by_agents", [])),
                enabled=item.get("enabled"),
            )
            for item in self._store.list_routing_skills()
        ]

    def set_enabled(
        self,
        skill_name: str,
        *,
        enabled: bool,
        set_by: str = "ui",
    ) -> RoutingSkillRecord:
        self._store.set_routing_skill_override(skill_name, enabled=enabled, set_by=set_by)
        record = next(
            (
                item
                for item in self.list_routing_skills()
                if item.skill_name.lower() == skill_name.strip().lower()
            ),
            None,
        )
        if record is not None:
            return record
        return RoutingSkillRecord(
            skill_name=skill_name.strip().lower(),
            advertised_by_agents=(),
            enabled=enabled,
        )


def declared_routing_skills(card: dict[str, Any]) -> list[str]:
    """Return routing skill names from a registry card payload."""

    raw = card.get("routing_skills", [])
    return [str(item).strip() for item in raw if str(item).strip()]


def query_routing_skills(query: dict[str, Any]) -> set[str]:
    """Return requested routing-skill filters from a discovery query payload."""

    raw = query.get("skills", [])
    return {
        str(item).strip().lower()
        for item in raw
        if str(item).strip()
    }


def requested_routed_skills(request: dict[str, Any]) -> tuple[str, ...]:
    """Return the routing skills requested by a routed task payload."""

    raw = request.get("requested_skills")
    if isinstance(raw, (list, tuple)):
        caps = [str(item).strip() for item in raw if str(item).strip()]
        if caps:
            return tuple(caps)
    return ()
