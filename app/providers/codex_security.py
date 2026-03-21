"""Shared security validation for Codex configuration input."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

ALLOWED_CODEX_SANDBOXES = frozenset(
    {
        "read-only",
        "workspace-write",
        "danger-full-access",
    }
)

# This allowlist is derived from current repo usage plus the security
# requirement that skills must not be able to weaken execution policy.
ALLOWED_CODEX_CONFIG_OVERRIDE_KEYS = frozenset(
    {
        "sandbox_permissions",
    }
)

_CONFIG_OVERRIDE_RE = re.compile(
    r"^(?P<key>[a-zA-Z][a-zA-Z0-9_.-]*)=(?P<value>.+)$"
)


def _allowed_sandbox_text() -> str:
    return ", ".join(sorted(ALLOWED_CODEX_SANDBOXES))


def validate_codex_sandbox(value: str) -> str:
    sandbox = value.strip()
    if sandbox not in ALLOWED_CODEX_SANDBOXES:
        raise ValueError(
            f"CODEX_SANDBOX must be one of {_allowed_sandbox_text()}, got '{value}'"
        )
    return sandbox


def _reject_override(
    override: Any,
    *,
    reason: str,
    logger: logging.Logger | None,
) -> None:
    sink = logger or log
    sink.warning("Rejected invalid Codex config override %r: %s", override, reason)


def validated_codex_config_overrides(
    raw_overrides: Any,
    *,
    logger: logging.Logger | None = None,
) -> list[str]:
    if not isinstance(raw_overrides, (list, tuple)):
        return []

    accepted: list[str] = []
    for raw in raw_overrides:
        if not isinstance(raw, str):
            _reject_override(raw, reason="override must be a string", logger=logger)
            continue

        override = raw.strip()
        if not override:
            _reject_override(raw, reason="override must not be blank", logger=logger)
            continue
        if override.startswith("-"):
            _reject_override(raw, reason="CLI flags are not allowed", logger=logger)
            continue

        match = _CONFIG_OVERRIDE_RE.match(override)
        if match is None:
            _reject_override(
                raw,
                reason="override must use key=value format",
                logger=logger,
            )
            continue

        key = match.group("key")
        value = match.group("value").lstrip()
        if key not in ALLOWED_CODEX_CONFIG_OVERRIDE_KEYS:
            _reject_override(
                raw,
                reason=f"key '{key}' is not allowlisted",
                logger=logger,
            )
            continue
        if value.startswith("-"):
            _reject_override(
                raw,
                reason="override value must not look like a CLI flag",
                logger=logger,
            )
            continue

        accepted.append(override)

    return accepted
