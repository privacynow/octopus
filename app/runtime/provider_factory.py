"""Provider selection for runtime entrypoints."""

from __future__ import annotations

import sys

from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider
from octopus_sdk.providers import Provider

PROVIDERS: dict[str, type] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}


def make_provider(config) -> Provider:
    provider_cls = PROVIDERS.get(config.provider_name)
    if provider_cls is None:
        print(f"Unknown provider: {config.provider_name}", file=sys.stderr)
        raise SystemExit(1)
    return provider_cls(config)
