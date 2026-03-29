"""Registry-specific configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
_KNOWN_DEFAULT_TOKENS = {"dev-enroll-token", "dev-ui-token", "changeme"}


@dataclass(frozen=True)
class RegistryConfig:
    db_path: Path
    database_url: str
    enroll_token: str
    ui_token: str
    display_name: str
    allow_http: bool
    bind_host: str
    port: int


def registry_allows_http() -> bool:
    value = os.environ.get("REGISTRY_ALLOW_HTTP", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def load_registry_config() -> RegistryConfig:
    return RegistryConfig(
        db_path=Path(os.environ.get("REGISTRY_DB_PATH", "/tmp/octopus-registry/registry.sqlite3")),
        database_url=os.environ.get("REGISTRY_DATABASE_URL", "").strip(),
        enroll_token=os.environ.get("REGISTRY_ENROLL_TOKEN", "").strip(),
        ui_token=os.environ.get("REGISTRY_UI_TOKEN", "").strip(),
        display_name=os.environ.get("REGISTRY_DISPLAY_NAME", "").strip(),
        allow_http=registry_allows_http(),
        bind_host=os.environ.get("REGISTRY_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=int(os.environ.get("REGISTRY_PORT", "8787") or "8787"),
    )


def validate_registry_config(config: RegistryConfig | None = None) -> RegistryConfig:
    current = config or load_registry_config()
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
