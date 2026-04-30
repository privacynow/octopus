"""Registry projection interface coverage helpers."""

from __future__ import annotations

from collections.abc import Sequence

from octopus_sdk.config import RegistryConnectionConfig


def registry_implementation_ref(registry_id: str) -> str:
    return f"registry:{registry_id}"


def registry_id_from_implementation_ref(implementation_ref: str) -> str:
    prefix = "registry:"
    if not implementation_ref.startswith(prefix) or not implementation_ref[len(prefix):]:
        raise ValueError(f"unsupported registry implementation_ref {implementation_ref!r}")
    return implementation_ref[len(prefix):]


def registry_projection_interfaces_by_implementation_ref(
    registries: Sequence[RegistryConnectionConfig],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for registry in registries:
        projection_interfaces: set[str] = set()
        if registry.registry_scope in {"channel", "full"}:
            projection_interfaces.update({"conversation_projection", "health_publication"})
        if registry.registry_scope in {"coordination", "full"}:
            projection_interfaces.update({"task_routing", "agent_directory", "health_publication", "registry_inspection"})
        mapping[registry_implementation_ref(registry.registry_id)] = projection_interfaces
    return mapping


__all__ = [
    "registry_projection_interfaces_by_implementation_ref",
    "registry_implementation_ref",
    "registry_id_from_implementation_ref",
]
