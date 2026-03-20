"""Startup-built authority/capability directory for control-plane routing."""

from __future__ import annotations


class ControlPlaneDirectory:
    def __init__(self) -> None:
        self._by_capability: dict[str, set[str]] = {}

    def register(self, *, capability: str, authority_ref: str) -> None:
        self._by_capability.setdefault(capability, set()).add(authority_ref)

    def authorities_for_capability(self, capability: str) -> set[str]:
        return set(self._by_capability.get(capability, set()))

    def all_capabilities(self) -> set[str]:
        return set(self._by_capability.keys())

    def all_authorities(self) -> set[str]:
        authorities: set[str] = set()
        for refs in self._by_capability.values():
            authorities.update(refs)
        return authorities

    def all_pairs(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for capability, authorities in self._by_capability.items():
            for authority_ref in authorities:
                pairs.add((authority_ref, capability))
        return pairs
