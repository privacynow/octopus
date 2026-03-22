"""Generic claim loop for control-plane processors."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.control_plane.bus import ControlPlaneBus
from app.control_plane.models import ControlCommand
from app.control_plane.processor_base import ControlProcessor

log = logging.getLogger(__name__)


def _allowed_pairs(capabilities: dict[str, set[str]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for authority_ref, authority_capabilities in capabilities.items():
        for capability in authority_capabilities:
            pairs.add((authority_ref, capability))
    return pairs


class ProcessorRunner:
    """Claim control-plane commands and dispatch them to registered processors."""

    def __init__(
        self,
        bus: ControlPlaneBus,
        *,
        claim_limit: int = 20,
        poll_interval_seconds: float = 0.1,
        reclaim_interval_seconds: float = 1.0,
        lease_extension_seconds: float = 30.0,
        lease_renewal_interval_seconds: float | None = None,
    ) -> None:
        self._bus = bus
        self._claim_limit = max(1, claim_limit)
        self._poll_interval_seconds = max(0.01, poll_interval_seconds)
        self._reclaim_interval_seconds = max(0.01, reclaim_interval_seconds)
        self._lease_extension_seconds = max(0.1, lease_extension_seconds)
        self._lease_renewal_interval_seconds = (
            max(0.01, lease_renewal_interval_seconds)
            if lease_renewal_interval_seconds is not None
            else max(0.05, self._lease_extension_seconds / 2.0)
        )
        self._processors: list[ControlProcessor] = []
        self._processor_by_pair: dict[tuple[str, str], ControlProcessor] = {}
        self._inflight: dict[str, asyncio.Task[None]] = {}
        self._stop_requested = asyncio.Event()

    def register(self, processor: ControlProcessor) -> None:
        capabilities = processor.authority_capabilities()
        for pair in _allowed_pairs(capabilities):
            existing = self._processor_by_pair.get(pair)
            if existing is not None and existing is not processor:
                raise ValueError(f"duplicate control-plane processor ownership for {pair}")
            self._processor_by_pair[pair] = processor
        if processor not in self._processors:
            self._processors.append(processor)

    async def run(self, *, stop_event: asyncio.Event) -> None:
        self._stop_requested.clear()
        last_reclaim = 0.0

        try:
            while not self._should_stop(stop_event):
                try:
                    now = monotonic()
                    if now - last_reclaim >= self._reclaim_interval_seconds:
                        await self._bus.reclaim_expired()
                        await self._bus.purge_old_commands()
                        last_reclaim = now

                    available_slots = self._claim_limit - len(self._inflight)
                    if available_slots > 0:
                        claimed = await self._bus.poll_commands(
                            allowed_pairs=set(self._processor_by_pair.keys()),
                            limit=available_slots,
                        )
                        for command in claimed:
                            task = asyncio.create_task(self._run_command(command))
                            self._inflight[command.command_id] = task
                            task.add_done_callback(
                                lambda done, command_id=command.command_id: self._inflight.pop(
                                    command_id,
                                    None,
                                )
                            )
                        if claimed:
                            await asyncio.sleep(0)
                            continue

                    await self._wait_for_stop(stop_event, timeout=self._poll_interval_seconds)
                except Exception:
                    log.exception("Control-plane processor loop iteration failed")
                    if self._should_stop(stop_event):
                        break
                    await self._wait_for_stop(stop_event, timeout=self._poll_interval_seconds)
        finally:
            if self._inflight:
                await asyncio.gather(*self._inflight.values(), return_exceptions=True)

    async def stop(self) -> None:
        self._stop_requested.set()
        if self._inflight:
            await asyncio.gather(*self._inflight.values(), return_exceptions=True)

    def allowed_pairs(self) -> set[tuple[str, str]]:
        return set(self._processor_by_pair.keys())

    def _should_stop(self, stop_event: asyncio.Event) -> bool:
        return stop_event.is_set() or self._stop_requested.is_set()

    async def _wait_for_stop(self, stop_event: asyncio.Event, *, timeout: float) -> None:
        external_wait = asyncio.create_task(stop_event.wait())
        local_wait = asyncio.create_task(self._stop_requested.wait())
        try:
            done, pending = await asyncio.wait(
                {external_wait, local_wait},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            del done
        finally:
            for task in (external_wait, local_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(external_wait, local_wait, return_exceptions=True)

    async def _run_command(self, command: ControlCommand) -> None:
        processor = self._processor_by_pair.get((command.authority_ref, command.capability))
        if processor is None:
            log.warning(
                "Dead-lettering control-plane command %s: no processor registered for %s/%s",
                command.command_id,
                command.authority_ref,
                command.capability,
            )
            await self._bus.dead_letter(
                command.command_id,
                claimed_at=command.claimed_at,
                reason=(
                    "no control-plane processor registered for "
                    f"{command.authority_ref}/{command.capability}"
                ),
            )
            return

        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_lease(
                command.command_id,
                command.claimed_at,
                heartbeat_stop,
            )
        )
        try:
            reply = await processor.process(command)
        except Exception as exc:
            log.exception(
                "Control-plane processor crashed for command %s (%s/%s)",
                command.command_id,
                command.authority_ref,
                command.capability,
            )
            await self._bus.fail(
                command.command_id,
                claimed_at=command.claimed_at,
                error=str(exc) or exc.__class__.__name__,
            )
            return
        finally:
            heartbeat_stop.set()
            await asyncio.gather(heartbeat_task, return_exceptions=True)

        if reply.status == "completed":
            await self._bus.complete(
                command.command_id,
                claimed_at=command.claimed_at,
                result_json=reply.result_json,
            )
            return
        await self._bus.fail(
            command.command_id,
            claimed_at=command.claimed_at,
            error=reply.error or "control-plane processor failed",
        )

    async def _heartbeat_lease(
        self,
        command_id: str,
        claimed_at: str,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._lease_renewal_interval_seconds,
                )
                return
            except asyncio.TimeoutError:
                renewed = await self._bus.renew_lease(
                    command_id,
                    claimed_at=claimed_at,
                    extension_seconds=self._lease_extension_seconds,
                )
                if not renewed:
                    return


__all__ = [
    "ProcessorRunner",
    "ControlProcessor",
]
