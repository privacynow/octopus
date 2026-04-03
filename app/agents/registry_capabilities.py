"""Shared registry authority/capability mapping helpers."""

from __future__ import annotations

from collections.abc import Sequence

from octopus_sdk.config import RegistryConnectionConfig


def registry_authority_ref(registry_id: str) -> str:
    return f"registry:{registry_id}"


def registry_id_from_authority_ref(authority_ref: str) -> str:
    prefix = "registry:"
    if not authority_ref.startswith(prefix) or not authority_ref[len(prefix):]:
        raise ValueError(f"unsupported registry authority_ref {authority_ref!r}")
    return authority_ref[len(prefix):]


def registry_authority_capabilities(
    registries: Sequence[RegistryConnectionConfig],
) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for registry in registries:
        capabilities: set[str] = set()
        if registry.registry_scope in {"channel", "full"}:
            capabilities.update({"conversation_projection", "health_publication", "mirror_retry"})
        if registry.registry_scope in {"coordination", "full"}:
            capabilities.update({"task_routing", "agent_directory", "health_publication", "registry_inspection"})
        mapping[registry_authority_ref(registry.registry_id)] = capabilities
    return mapping


__all__ = [
    "registry_authority_capabilities",
    "registry_authority_ref",
    "registry_id_from_authority_ref",
]
