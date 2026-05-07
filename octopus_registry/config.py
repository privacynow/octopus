"""Registry-specific configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)
_KNOWN_DEFAULT_TOKENS = {"dev-enroll-token", "dev-ui-token", "changeme"}


@dataclass(frozen=True)
class RegistryConfig:
    database_url: str
    enroll_token: str
    ui_token: str
    display_name: str
    allow_http: bool
    bind_host: str
    port: int
    operator_org_id: str
    operator_roles: tuple[str, ...]
    protocol_registry_templates_enabled: bool
    artifact_store_dir: str = "/tmp/octopus-registry-artifacts"


def registry_operator_roles() -> tuple[str, ...]:
    raw = os.environ.get("REGISTRY_OPERATOR_ROLES", "").strip()
    if not raw:
        return ("author", "publisher", "operator", "auditor", "admin")
    roles: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        role = str(part or "").strip().lower()
        if not role or role in seen:
            continue
        seen.add(role)
        roles.append(role)
    return tuple(roles) or ("author", "publisher", "operator", "auditor", "admin")


def registry_allows_http() -> bool:
    value = os.environ.get("REGISTRY_ALLOW_HTTP", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def registry_protocol_templates_enabled() -> bool:
    value = os.environ.get("REGISTRY_PROTOCOL_TEMPLATES_ENABLED", "").strip().lower()
    if not value:
        return True
    return value in {"1", "true", "yes", "on"}


def load_registry_config() -> RegistryConfig:
    return RegistryConfig(
        database_url=os.environ.get("OCTOPUS_DATABASE_URL", "").strip(),
        enroll_token=os.environ.get("REGISTRY_ENROLL_TOKEN", "").strip(),
        ui_token=os.environ.get("REGISTRY_UI_TOKEN", "").strip(),
        display_name=os.environ.get("REGISTRY_DISPLAY_NAME", "").strip(),
        allow_http=registry_allows_http(),
        bind_host=os.environ.get("REGISTRY_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.environ.get("REGISTRY_PORT", "8787") or "8787"),
        operator_org_id=os.environ.get("REGISTRY_OPERATOR_ORG_ID", "local").strip() or "local",
        operator_roles=registry_operator_roles(),
        protocol_registry_templates_enabled=registry_protocol_templates_enabled(),
        artifact_store_dir=os.environ.get("REGISTRY_ARTIFACT_STORE_DIR", "/tmp/octopus-registry-artifacts").strip()
        or "/tmp/octopus-registry-artifacts",
    )


def validate_registry_config(config: RegistryConfig | None = None) -> RegistryConfig:
    current = config or load_registry_config()
    if not current.database_url:
        raise RuntimeError("OCTOPUS_DATABASE_URL must be set before the registry can start.")
    if not current.enroll_token:
        raise RuntimeError("REGISTRY_ENROLL_TOKEN must be set before the registry can start.")
    if not current.ui_token:
        raise RuntimeError("REGISTRY_UI_TOKEN must be set before the registry can start.")
    if current.enroll_token in _KNOWN_DEFAULT_TOKENS:
        raise RuntimeError("REGISTRY_ENROLL_TOKEN must not use a known default token.")
    if current.ui_token in _KNOWN_DEFAULT_TOKENS:
        raise RuntimeError("REGISTRY_UI_TOKEN must not use a known default token.")
    if current.allow_http:
        log.warning(
            "REGISTRY_ALLOW_HTTP=1 is enabled; session cookies may be sent over HTTP. "
            "Use this only for local development."
        )
    return current
