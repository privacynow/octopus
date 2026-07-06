"""Shared security validation for Codex configuration input."""

from __future__ import annotations

import shutil
import subprocess
import logging
import re
import sys
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

ALLOWED_CODEX_SANDBOXES = frozenset(
    {
        "read-only",
        "workspace-write",
        "danger-full-access",
    }
)

ALLOWED_CODEX_REASONING_EFFORTS = frozenset(
    {
        "minimal",
        "low",
        "medium",
        "high",
    }
)

# This allowlist is derived current repo usage plus the security
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


def _allowed_reasoning_effort_text() -> str:
    return ", ".join(sorted(ALLOWED_CODEX_REASONING_EFFORTS))


def validate_codex_reasoning_effort(value: str) -> str:
    effort = value.strip()
    if not effort:
        return ""
    if effort not in ALLOWED_CODEX_REASONING_EFFORTS:
        raise ValueError(
            "CODEX_REASONING_EFFORT must be one of "
            f"{_allowed_reasoning_effort_text()}, got '{value}'"
        )
    return effort


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


def codex_runtime_requires_sandbox(config: Any, *, approval_mode: str) -> bool:
    if str(getattr(config, "provider_name", "") or "") != "codex":
        return False
    if approval_mode != "on":
        return False
    if bool(getattr(config, "codex_dangerous", False)):
        return False
    return str(getattr(config, "codex_sandbox", "") or "") != "danger-full-access"


@lru_cache(maxsize=1)
def probe_codex_sandbox_support() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    unshare = shutil.which("unshare")
    if not unshare:
        return "the Linux 'unshare' command is not available"
    try:
        completed = subprocess.run(
            [unshare, "--user", "--map-root-user", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "the sandbox feature probe timed out"
    except OSError as exc:
        return str(exc)
    if completed.returncode == 0:
        return None
    detail = (completed.stderr or "").strip()
    return detail or f"probe exited with code {completed.returncode}"


def codex_sandbox_support_error(config: Any, *, approval_mode: str) -> str | None:
    if not codex_runtime_requires_sandbox(config, approval_mode=approval_mode):
        return None
    detail = probe_codex_sandbox_support()
    if detail is None:
        return None
    return (
        "Approval mode 'on' requires Codex sandboxing, but this host cannot provide it: "
        f"{detail}"
    )


def reset_codex_sandbox_probe_cache() -> None:
    probe_codex_sandbox_support.cache_clear()
