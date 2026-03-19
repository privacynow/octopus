"""Background registry connectivity for agent-mode bots."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import AgentRuntimeState, load_agent_runtime_state, save_agent_runtime_state
from app.agents.types import AgentCard, utcnow_iso
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
    ) -> None:
        self.config = config
        self._delivery_handler = delivery_handler
        self._state = load_agent_runtime_state(config.data_dir)
        self._runtime_health_provider = runtime_health_provider
        self._runtime_health_projector = runtime_health_projector or RuntimeHealthJsonProjector()
        self._provider = provider

    @property
    def state(self) -> AgentRuntimeState:
        return self._state

    def requested_card(self) -> AgentCard:
        return AgentCard(
            agent_id=self._state.agent_id,
            display_name=self.config.agent_display_name or self.config.instance,
            slug=self._state.registered_slug or self.config.agent_slug,
            role=self.config.agent_role or self.config.role,
            capabilities=self.config.agent_capabilities,
            tags=self.config.agent_tags,
            description=self.config.agent_description,
            provider=self.config.provider_name,
            mode=self.config.agent_mode,
            connectivity_state=self._state.connectivity_state,
            current_capacity=0,
            max_capacity=1,
            channel_capabilities=("telegram", "registry") if self.config.agent_mode == "registry" else ("telegram",),
            version="phase-19-foundation",
        )

    def _client(self) -> AgentRegistryClient:
        return AgentRegistryClient(
            self.config.agent_registry_url,
            agent_token=self._state.agent_token,
        )

    async def _runtime_health_payload(self) -> tuple[dict[str, Any] | None, int]:
        if self._runtime_health_provider is None or self._provider is None:
            return None, 0
        report = await self._runtime_health_provider.collect(
            self.config,
            self._provider,
            caller_is_bot=True,
            session_context=None,
        )
        payload = self._runtime_health_projector.project(report)
        active_work_count = report.summary.claimed_count
        return payload, active_work_count

    def _save_state(self) -> None:
        save_agent_runtime_state(self.config.data_dir, self._state)

    def _mark_state(self, connectivity_state: str, *, error: str = "") -> None:
        self._state.connectivity_state = connectivity_state
        self._state.last_error = error
        if connectivity_state == "connected":
            self._state.last_successful_contact_at = utcnow_iso()
        self._save_state()

    async def sync_once(self) -> str:
        if self.config.agent_mode == "standalone":
            self._mark_state("standalone")
            return "standalone"

        if not self.config.agent_registry_url:
            self._mark_state("degraded", error="Registry URL not configured")
            return "degraded"

        try:
            if not self._state.agent_id or not self._state.agent_token:
                if not self.config.agent_registry_enroll_token:
                    self._mark_state("degraded", error="Enrollment token not configured")
                    return "degraded"
                enroll = await AgentRegistryClient(self.config.agent_registry_url).enroll(
                    self.requested_card(),
                    self.config.agent_registry_enroll_token,
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
            active_work_count = 0
            try:
                runtime_health_payload, active_work_count = await self._runtime_health_payload()
            except Exception:
                log.exception(
                    "Runtime health collection failed for %s; continuing without mirrored health",
                    self.config.instance,
                )
            heartbeat_kwargs = {
                "connectivity_state": "connected",
                "current_capacity": 0,
                "max_capacity": 1,
                "active_work_count": active_work_count,
            }
            if runtime_health_payload is not None:
                heartbeat_kwargs["runtime_health"] = runtime_health_payload
            await client.heartbeat(**heartbeat_kwargs)
        except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
            log.warning("Agent registry sync degraded for %s: %s", self.config.instance, exc)
            self._mark_state("degraded", error=str(exc))
            return "degraded"

        self._mark_state("connected")
        return "connected"

    async def poll_once(self) -> int:
        if self._delivery_handler is None or self._state.connectivity_state != "connected":
            return 0
        client = self._client()
        result = await client.poll(
            cursor=self._state.poll_cursor or "0",
            limit=20,
            wait_seconds=0,
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

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        import random

        base = max(1.0, self.config.agent_poll_interval_seconds)
        max_backoff = min(300.0, base * 32)
        current_backoff = base
        while not stop_event.is_set():
            state = await self.sync_once()
            if state == "connected":
                try:
                    await self.poll_once()
                except (RegistryClientError, OSError, asyncio.TimeoutError) as exc:
                    log.warning("Agent registry poll degraded for %s: %s", self.config.instance, exc)
                    self._mark_state("degraded", error=str(exc))
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
) -> tuple[asyncio.Task[None], asyncio.Event]:
    stop_event = asyncio.Event()
    runtime = AgentRuntime(
        config,
        delivery_handler=delivery_handler,
        runtime_health_provider=runtime_health_provider,
        runtime_health_projector=runtime_health_projector,
        provider=provider,
    )
    task = asyncio.create_task(runtime.run_forever(stop_event))
    return task, stop_event
