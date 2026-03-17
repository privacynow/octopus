"""Credential validation adapters."""

from __future__ import annotations

import re

import httpx

from app.skill_types import SkillRequirement


async def validate_credential(req: SkillRequirement, value: str) -> tuple[bool, str]:
    """Run HTTP validation if defined. Returns (ok, message)."""
    if not req.validate:
        return True, ""

    spec = req.validate
    url = spec.get("url", "")
    if not url:
        return True, ""

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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers)
            if resp.status_code == expect_status:
                return True, ""
            return False, _friendly_validation_error(resp.status_code, expect_status)
    except Exception as exc:
        return False, f"Validation request failed: {exc}"


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
