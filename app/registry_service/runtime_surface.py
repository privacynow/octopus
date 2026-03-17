"""Shared runtime-surface access for registry skill and guidance APIs.

The registry remains the only public HTTP API, but it should call the same
runtime services in-process rather than forcing the bot through HTTP for
catalog/guidance/session-backed lifecycle work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.content_store import init_content_store_for_config, reset_for_test as reset_content_store_for_test
from app import runtime_backend
from app.config import BotConfig, load_config_provider_health
from app.providers.claude import ClaudeProvider
from app.providers.codex import CodexProvider

ProviderStateFactory = Callable[[], dict[str, Any]]

_context: "RuntimeSurfaceContext | None" = None


@dataclass(frozen=True)
class RuntimeSurfaceContext:
    config: BotConfig
    provider_state_factory: ProviderStateFactory


def get_runtime_surface_context() -> RuntimeSurfaceContext:
    global _context
    if _context is None:
        config = load_config_provider_health()
        runtime_backend.init(config)
        init_content_store_for_config(config)
        if config.provider_name == "codex":
            provider_state_factory = CodexProvider(config).new_provider_state
        else:
            provider_state_factory = ClaudeProvider(config).new_provider_state
        _context = RuntimeSurfaceContext(
            config=config,
            provider_state_factory=provider_state_factory,
        )
    return _context


def reset_for_test() -> None:
    global _context
    _context = None
    runtime_backend.reset_for_test()
    reset_content_store_for_test()
