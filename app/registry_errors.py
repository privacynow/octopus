"""Stable registry connectivity error codes and safe message mapping."""

from __future__ import annotations

from typing import Final, Literal

RegistryErrorCode = Literal[
    "registry_url_missing",
    "registry_enroll_token_missing",
    "registry_auth_failed",
    "registry_server_error",
    "registry_timeout",
    "registry_unreachable",
    "registry_request_failed",
]

_KNOWN_REGISTRY_ERROR_CODES: Final[set[str]] = {
    "registry_url_missing",
    "registry_enroll_token_missing",
    "registry_auth_failed",
    "registry_server_error",
    "registry_timeout",
    "registry_unreachable",
    "registry_request_failed",
}

_REGISTRY_ERROR_SUMMARIES: Final[dict[str, str]] = {
    "registry_url_missing": "This bot is not configured with a registry URL.",
    "registry_enroll_token_missing": "This bot is missing its registry enrollment token.",
    "registry_auth_failed": "The agent registry rejected this bot's credentials.",
    "registry_server_error": "The agent registry is temporarily unavailable.",
    "registry_timeout": "The agent registry did not respond in time.",
    "registry_unreachable": "The agent registry could not be reached.",
    "registry_request_failed": "The agent registry request failed.",
}


def is_registry_error_code(value: str) -> bool:
    return value in _KNOWN_REGISTRY_ERROR_CODES


def normalize_registry_error_code(value: str) -> RegistryErrorCode:
    if value in _KNOWN_REGISTRY_ERROR_CODES:
        return value
    return "registry_request_failed"


def normalize_registry_error_state(code: str, detail: str = "") -> tuple[str, str]:
    if not code:
        return "", detail
    if is_registry_error_code(code):
        return code, detail
    if not detail:
        detail = code
    return "registry_request_failed", detail


def registry_error_summary(code: str) -> str:
    normalized = normalize_registry_error_code(code)
    return _REGISTRY_ERROR_SUMMARIES[normalized]


def registry_error_detail(code: str, detail: str = "") -> str:
    if not code and not detail:
        return ""
    return detail or registry_error_summary(code)
