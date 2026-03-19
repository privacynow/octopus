"""Credential validation adapters."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from urllib.parse import urlparse

import httpx

from app.skill_types import SkillRequirement


log = logging.getLogger(__name__)

_DEFAULT_ALLOWED_VALIDATION_HOSTS = (
    "api.github.com",
    "api.openai.com",
    "*.openai.com",
    "api.anthropic.com",
    "*.anthropic.com",
    "googleapis.com",
    "*.googleapis.com",
)


def credential_validation_target_host(req: SkillRequirement) -> str:
    """Return the configured validation host for *req*, or an empty string."""
    validate = req.validate if isinstance(req.validate, dict) else None
    if not validate:
        return ""
    url = str(validate.get("url", "")).strip()
    if not url:
        return ""
    return (urlparse(url).hostname or "").lower()


def _allowed_validation_hosts() -> tuple[str, ...]:
    raw = os.environ.get("BOT_CREDENTIAL_VALIDATION_ALLOWED_HOSTS", "")
    configured = tuple(
        pattern.strip().lower()
        for pattern in raw.split(",")
        if pattern.strip()
    )
    return _DEFAULT_ALLOWED_VALIDATION_HOSTS + configured


def _is_allowed_validation_host(host: str) -> bool:
    normalized = host.strip().lower()
    return bool(normalized) and any(
        fnmatch.fnmatch(normalized, pattern)
        for pattern in _allowed_validation_hosts()
    )


async def validate_credential(
    req: SkillRequirement,
    value: str,
    *,
    skill_name: str | None = None,
) -> tuple[bool, str]:
    """Run HTTP validation if defined. Returns (ok, message)."""
    if not req.validate:
        return True, ""

    spec = req.validate
    url = spec.get("url", "")
    if not url:
        return True, ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    skill_label = skill_name or "<unknown>"
    if parsed.scheme not in {"http", "https"} or not host:
        log.warning(
            "Credential validation rejected for %s (skill: %s): invalid URL",
            req.key,
            skill_label,
        )
        return (
            False,
            "This credential cannot be validated because the skill uses an invalid validation URL.",
        )
    if not _is_allowed_validation_host(host):
        log.warning(
            "Credential validation rejected for %s against %s (skill: %s): host not allowed",
            req.key,
            host,
            skill_label,
        )
        return (
            False,
            "This credential cannot be validated because the skill points to an unapproved host. Contact the bot operator.",
        )
    if parsed.scheme != "https":
        log.warning(
            "Credential validation rejected for %s against %s (skill: %s): plaintext HTTP is not allowed",
            req.key,
            host,
            skill_label,
        )
        return (
            False,
            "This credential cannot be validated because the skill uses an insecure HTTP validation endpoint. Contact the bot operator.",
        )

    method = spec.get("method", "GET").upper()
    header_template = spec.get("header", "")
    try:
        expect_status = int(spec.get("expect_status", "200"))
    except (ValueError, TypeError):
        return False, f"Invalid expect_status in validate spec: {spec.get('expect_status')!r}"

    header_value = re.sub(
        r"\$\{" + re.escape(req.key) + r"\}",
        lambda _m: value,
        header_template,
    )

    headers: dict[str, str] = {}
    if header_value and ":" in header_value:
        hname, _, hval = header_value.partition(":")
        headers[hname.strip()] = hval.strip()
    elif header_value:
        headers["Authorization"] = header_value

    log.info(
        "Validating credential %s against %s (skill: %s)",
        req.key,
        host,
        skill_label,
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers)
            if resp.status_code == expect_status:
                return True, ""
            return False, _friendly_validation_error(resp.status_code, expect_status)
    except Exception as exc:
        log.warning(
            "Credential validation request failed for %s against %s (skill: %s): %s",
            req.key,
            host,
            skill_label,
            exc.__class__.__name__,
            exc_info=True,
        )
        return False, "Could not validate this credential. Check the value and try again."


def _friendly_validation_error(got: int, expected: int) -> str:
    if got in (401, 403):
        hint = (
            "Token was rejected. Double-check you copied the full token "
            "and that it has the required permissions."
        )
    elif got == 404:
        hint = "The validation endpoint was not found. The service may have changed its API."
    elif 500 <= got < 600:
        hint = "The service is temporarily unavailable. Try again in a few minutes."
    else:
        hint = "Unexpected response from the service."
    return f"{hint} (HTTP {got}, expected {expected})"
