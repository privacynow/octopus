"""Background registry connectivity for agent-mode bots."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.registry_errors import registry_error_detail
from app.agents.state import (
    load_bot_identity_state,
    load_runtime_registry_connection_state,
    save_registry_connection_state,
)
from app.agents.types import AgentCard, RegistryConnectionConfig, RegistryConnectionState, utcnow_iso
from app.config import BotConfig
from app.runtime_health import (
    RuntimeHealthJsonProjector,
    RuntimeHealthProjector,
    RuntimeHealthProvider,
)

log = logging.getLogger(__name__)


class AgentRuntime:
    """Maintains bot identity and heartbeat against the central registry."""

    def __init__(
        self,
        config: BotConfig,
        *,
        delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None = None,
        runtime_health_provider: RuntimeHealthProvider | None = None,
        runtime_health_projector: RuntimeHealthProjector[dict[str, Any]] | None = None,
        provider=None,
        registry: RegistryConnectionConfig | None = None,
        channel_capabilities_resolver: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.config = config
        self._delivery_handler = delivery_handler
        if registry is None and config.agent_mode == "registry":
            raise ValueError("AgentRuntime requires an explicit registry connection in registry mode")
        self._registry = registry
        self._channel_capabilities_resolver = channel_capabilities_resolver
        if self._registry is None:
            self._state = RegistryConnectionState(registry_id="", registry_scope="full")
        else:
            self._state = load_runtime_registry_connection_state(
                config.data_dir,
                self._registry.registry_id,
                registry_scope=self._registry.registry_scope,
            )
        self._runtime_health_provider = runtime_health_provider
        self._runtime_health_projector = runtime_health_projector or RuntimeHealthJsonProjector()
        self._provider = provider

    @property
    def state(self) -> RegistryConnectionState:
        return self._state

    def _channel_capabilities(self) -> tuple[str, ...]:
        if self._channel_capabilities_resolver is not None:
            return self._channel_capabilities_resolver()
        channels: list[str] = []
        if self.config.telegram_token:
            channels.append("telegram")
        if any(registry.registry_scope in {"channel", "full"} for registry in self.config.agent_registries):
            channels.append("registry")
        return tuple(channels)

    def _configured_registry_url(self) -> str:
        if self._registry is None:
            return ""
        return self._registry.url

    def _configured_enroll_token(self) -> str:
        if self._registry is None:
            return ""
        return self._registry.enroll_token

    def requested_card(self) -> AgentCard:
        capabilities = self._effective_capabilities()
        return AgentCard(
            agent_id=self._state.agent_id,
            display_name=self.config.agent_display_name or self.config.instance,
            slug=self._state.registered_slug or self.config.agent_slug,
            role=self.config.agent_role or self.config.role,
            registry_scope=self._state.registry_scope or (self._registry.registry_scope if self._registry is not None else "full"),
            capabilities=capabilities,
            tags=self.config.agent_tags,
            description=self.config.agent_description,
            provider=self.config.provider_name,
            mode=self.config.agent_mode,
            connectivity_state=self._state.connectivity_state,
            current_capacity=0,
            max_capacity=1,
            channel_capabilities=self._channel_capabilities(),
            version="",
            bot_key=load_bot_identity_state(self.config.data_dir).bot_id,
        )

    def _effective_capabilities(self) -> tuple[str, ...]:
        """Return explicitly configured capabilities only.

        No auto-detection from provider/skills — capabilities advertised to
        the registry should be intentional, not inferred.
        """
        return self.config.agent_capabilities

    def _client(self) -> AgentRegistryClient:
        return AgentRegistryClient(
            self._configured_registry_url(),
            agent_token=self._state.agent_token,
        )

    async def _runtime_health_payload(self) -> dict[str, Any] | None:
        if self._runtime_health_provider is None or self._provider is None:
            return None
        report = await self._runtime_health_provider.collect(
            self.config,
            self._provider,
            caller_is_bot=True,
            session_context=None,
        )
        return self._runtime_health_projector.project(report)

    def _save_state(self) -> None:
        if self._registry is None:
            return
        save_registry_connection_state(self.config.data_dir, self._state)

    def _mark_state(
        self,
        connectivity_state: str,
        *,
        error: str = "",
        detail: str = "",
    ) -> None:
        self._state.connectivity_state = connectivity_state
        self._state.last_error = error
        self._state.last_error_detail = detail
        if connectivity_state == "connected":
            self._state.last_successful_contact_at = utcnow_iso()
        self._save_state()

    async def sync_once(self) -> str:
        if self.config.agent_mode == "standalone":
            self._mark_state("standalone")
            return "standalone"

        if not self._configured_registry_url():
            self._mark_state(
                "degraded",
                error="registry_url_missing",
                detail="Registry URL not configured.",
            )
            return "degraded"

        try:
            if not self._state.agent_id or not self._state.agent_token:
                enroll_token = self._configured_enroll_token()
                if not enroll_token:
                    self._mark_state(
                        "degraded",
                        error="registry_enroll_token_missing",
                        detail="Registry enrollment token not configured.",
                    )
                    return "degraded"
                enroll = await AgentRegistryClient(self._configured_registry_url()).enroll(
                    self.requested_card(),
                    enroll_token,
                )
                self._state.agent_id = str(enroll.get("agent_id", ""))
                self._state.agent_token = str(enroll.get("agent_token", ""))
                self._state.registered_slug = str(enroll.get("slug", self.config.agent_slug))
                self._state.poll_cursor = str(enroll.get("poll_cursor", "0"))
                self._save_state()

            card = replace(
                self.requested_card(),
                agent_id=self._state.agent_id,
                slug=self._state.registered_slug or self.config.agent_slug,
                connectivity_state="connected",
            )
            client = self._client()
            await client.register(
                card,
                connectivity_state="connected",
                current_capacity=0,
                max_capacity=1,
            )
            runtime_health_payload = None
            try:
                runtime_health_payload = await self._runtime_health_payload()
            except Exception:
                log.exception(
                    "Runtime health collection failed for %s; continuing without mirrored health",
                    self.config.instance,
                )
            heartbeat_kwargs = {
                "connectivity_state": "connected",
                "current_capacity": 0,
                "max_capacity": 1,
            }
            if runtime_health_payload is not None:
                heartbeat_kwargs["runtime_health"] = runtime_health_payload
            await client.heartbeat(**heartbeat_kwargs)
        except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
            if isinstance(exc, RegistryClientError):
                error_code = exc.error_code
                detail = exc.operator_detail
            elif isinstance(exc, asyncio.TimeoutError):
                error_code = "registry_timeout"
                detail = "Registry sync timed out."
            else:
                error_code = "registry_unreachable"
                detail = f"Registry sync failed with {exc.__class__.__name__}."
            log.warning(
                "Agent registry sync degraded for %s: %s",
                self.config.instance,
                registry_error_detail(error_code, detail),
            )
            self._mark_state("degraded", error=error_code, detail=detail)
            return "degraded"

        self._mark_state("connected")
        return "connected"

    async def poll_once(self, *, kind_filter: Sequence[str] | None = None) -> int:
        if self._delivery_handler is None or self._state.connectivity_state != "connected":
            return 0
        client = self._client()
        poll_kwargs: dict[str, object] = {
            "cursor": self._state.poll_cursor or "0",
            "limit": 20,
            "wait_seconds": 0,
        }
        if kind_filter is not None:
            poll_kwargs["kind_filter"] = tuple(kind_filter)
        result = await client.poll(
            **poll_kwargs,
        )
        deliveries = list(result.get("deliveries", []))
        if not deliveries:
            self._state.poll_cursor = str(result.get("next_cursor", self._state.poll_cursor or "0"))
            self._save_state()
            return 0

        accepted: list[str] = []
        rejected: list[str] = []
        retry_later: list[str] = []
        for delivery in deliveries:
            delivery_id = str(delivery.get("delivery_id", ""))
            try:
                classification = await self._delivery_handler(delivery)
            except Exception:
                # Delivery failures are acknowledged as rejected below so the
                # registry can record them explicitly instead of leaving the
                # delivery invisible in the poll loop.
                log.exception(
                    "Agent delivery handler failed for %s on %s",
                    self.config.instance,
                    delivery_id,
                )
                rejected.append(delivery_id)
                continue
            if classification == "accepted":
                accepted.append(delivery_id)
            elif classification == "retry_later":
                retry_later.append(delivery_id)
            else:
                rejected.append(delivery_id)

        if accepted:
            await client.ack(accepted, classification="accepted")
        if rejected:
            await client.ack(rejected, classification="rejected")
        if retry_later:
            await client.ack(retry_later, classification="retry_later")

        self._state.poll_cursor = str(result.get("next_cursor", self._state.poll_cursor or "0"))
        self._save_state()
        return len(deliveries)

    async def run_forever(
        self,
        stop_event: asyncio.Event,
        *,
        kind_filter: Sequence[str] | None = None,
    ) -> None:
        import random

        base = max(1.0, self.config.agent_poll_interval_seconds)
        max_backoff = min(300.0, base * 32)
        current_backoff = base
        while not stop_event.is_set():
            state = await self.sync_once()
            if state == "connected":
                try:
                    if kind_filter is None:
                        await self.poll_once()
                    else:
                        await self.poll_once(kind_filter=kind_filter)
                except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
                    if isinstance(exc, RegistryClientError):
                        error_code = exc.error_code
                        detail = exc.operator_detail
                    elif isinstance(exc, asyncio.TimeoutError):
                        error_code = "registry_timeout"
                        detail = "Registry poll timed out."
                    else:
                        error_code = "registry_unreachable"
                        detail = f"Registry poll failed with {exc.__class__.__name__}."
                    log.warning(
                        "Agent registry poll degraded for %s: %s",
                        self.config.instance,
                        registry_error_detail(error_code, detail),
                    )
                    self._mark_state("degraded", error=error_code, detail=detail)
                except Exception:
                    log.exception("Unexpected registry poll failure for %s", self.config.instance)
            if self._state.connectivity_state == "connected":
                current_backoff = base
            else:
                current_backoff = min(current_backoff * 2, max_backoff)
            sleep_time = random.uniform(0, current_backoff)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                continue


def start_agent_runtime_task(
    config: BotConfig,
    *,
    delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None = None,
    runtime_health_provider: RuntimeHealthProvider | None = None,
    runtime_health_projector: RuntimeHealthProjector[dict[str, Any]] | None = None,
    provider=None,
    kind_filter: Sequence[str] | None = None,
) -> tuple[asyncio.Task[None], asyncio.Event]:
    stop_event = asyncio.Event()
    runtime = AgentRuntime(
        config,
        delivery_handler=delivery_handler,
        runtime_health_provider=runtime_health_provider,
        runtime_health_projector=runtime_health_projector,
        provider=provider,
    )
    task = asyncio.create_task(runtime.run_forever(stop_event, kind_filter=kind_filter))
    return task, stop_event
