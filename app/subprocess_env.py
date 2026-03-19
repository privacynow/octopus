"""Allowlisted subprocess environments for provider/runtime child processes."""

from __future__ import annotations

import os
from typing import Iterable

_BASE_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "SHELL",
    "TMPDIR",
    "TZ",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "CODEX_HOME",
    "SSH_AUTH_SOCK",
    "GIT_SSH_COMMAND",
    "GIT_ASKPASS",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)


def build_subprocess_env(
    *,
    allowed_keys: Iterable[str] = (),
    extra_env: dict[str, str] | None = None,
    blocked_keys: Iterable[str] = (),
) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in (*_BASE_ENV_KEYS, *tuple(allowed_keys)):
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key in blocked_keys:
        env.pop(key, None)
    if extra_env:
        for key, value in extra_env.items():
            if value:
                env[str(key)] = str(value)
    return env
