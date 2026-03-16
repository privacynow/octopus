"""Background registry connectivity for agent-mode bots."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Awaitable, Callable

from app.agents.client import AgentRegistryClient, RegistryClientError
from app.agents.state import AgentRuntimeState, load_agent_runtime_state, save_agent_runtime_state
from app.agents.types import AgentCard, utcnow_iso
from app.config import BotConfig

log = logging.getLogger(__name__)


class AgentRuntime:
    """Maintains bot identity and heartbeat against the central registry."""

    def __init__(
        self,
        config: BotConfig,
        *,
        delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None = None,
    ) -> None:
        self.config = config
        self._delivery_handler = delivery_handler
        self._state = load_agent_runtime_state(config.data_dir)

    @property
    def state(self) -> AgentRuntimeState:
        return self._state

    def requested_card(self) -> AgentCard:
        return AgentCard(
            agent_id=self._state.agent_id,
            display_name=self.config.agent_display_name or self.config.instance,
            slug=self._state.registered_slug or self.config.agent_slug,
            role=self.config.agent_role or self.config.role,
            skills=self.config.agent_skills or self.config.default_skills,
            tags=self.config.agent_tags,
            description=self.config.agent_description,
            provider=self.config.provider_name,
            mode=self.config.agent_mode,
            connectivity_state=self._state.connectivity_state,
            current_capacity=0,
            max_capacity=1,
            surface_capabilities=("telegram", "registry") if self.config.agent_mode == "registry" else ("telegram",),
            version="phase-19-foundation",
        )

    def _client(self) -> AgentRegistryClient:
        return AgentRegistryClient(
            self.config.agent_registry_url,
            agent_token=self._state.agent_token,
        )

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
            await client.heartbeat(
                connectivity_state="connected",
                current_capacity=0,
                max_capacity=1,
                active_work_count=0,
            )
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
        interval = max(1.0, self.config.agent_poll_interval_seconds)
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
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue


def start_agent_runtime_task(
    config: BotConfig,
    *,
    delivery_handler: Callable[[dict[str, object]], Awaitable[str]] | None = None,
) -> tuple[asyncio.Task[None], asyncio.Event]:
    stop_event = asyncio.Event()
    runtime = AgentRuntime(config, delivery_handler=delivery_handler)
    task = asyncio.create_task(runtime.run_forever(stop_event))
    return task, stop_event
