"""Shared service layer for registry routing capabilities.

This service keeps capability lifecycle terminology separate from runtime
skill-catalog terminology. The backing registry store can evolve without
forcing UI handlers to speak storage-centric names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.registry_service.store_base import AbstractRegistryStore


@dataclass(frozen=True)
class CapabilityRecord:
    capability_name: str
    declared_by_agents: tuple[str, ...]
    enabled: bool | None


class CapabilityService:
    """Surface-neutral capability lifecycle service."""

    def __init__(self, store: AbstractRegistryStore) -> None:
        self._store = store

    def list_capabilities(self) -> list[CapabilityRecord]:
        return [
            CapabilityRecord(
                capability_name=str(item.get("capability_name", "")),
                declared_by_agents=tuple(item.get("declared_by_agents", [])),
                enabled=item.get("enabled"),
            )
            for item in self._store.list_capabilities()
        ]

    def set_enabled(
        self,
        capability_name: str,
        *,
        enabled: bool,
        set_by: str = "ui",
    ) -> CapabilityRecord:
        self._store.set_capability_override(capability_name, enabled=enabled, set_by=set_by)
        record = next(
            (
                item
                for item in self.list_capabilities()
                if item.capability_name.lower() == capability_name.strip().lower()
            ),
            None,
        )
        if record is not None:
            return record
        return CapabilityRecord(
            capability_name=capability_name.strip().lower(),
            declared_by_agents=(),
            enabled=enabled,
        )


def declared_capabilities(card: dict[str, Any]) -> list[str]:
    """Return capability names from a registry card payload.

    Accept legacy ``skills`` payloads at the edge while keeping the internal
    concept named as capabilities.
    """

    raw = card.get("capabilities")
    if raw is None:
        raw = card.get("skills", [])
    return [str(item).strip() for item in raw if str(item).strip()]


def query_capabilities(query: dict[str, Any]) -> set[str]:
    """Return requested capability filters from a discovery query payload."""

    raw = query.get("capabilities")
    if raw is None:
        raw = query.get("skills", [])
    return {
        str(item).strip().lower()
        for item in raw
        if str(item).strip()
    }


def requested_routed_capabilities(request: dict[str, Any]) -> tuple[str, ...]:
    """Return the capabilities requested by a routed task payload.

    ``requested_capabilities`` is canonical. A legacy single ``skill`` field is
    still tolerated at the API edge for transition safety.
    """

    raw = request.get("requested_capabilities")
    if isinstance(raw, (list, tuple)):
        caps = [str(item).strip() for item in raw if str(item).strip()]
        if caps:
            return tuple(caps)
    legacy = str(request.get("skill") or "").strip()
    return (legacy,) if legacy else ()
