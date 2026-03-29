"""Async worker loop for processing durable work items.

Fresh plain-message execution is worker-owned: handlers call
record_and_admit_message() and return; this loop claims and dispatches
items via worker_dispatch (execute_request/request_approval). No
inline provider execution. Recovered items (dispatch_mode='recovery')
get a recovery notice and move to pending_recovery.

The loop runs as an asyncio task alongside the bot's event loop.
claim_next_any uses backend-specific serialization (e.g. BEGIN IMMEDIATE
on SQLite, advisory lock on Postgres) so only one worker claims a given
item.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable

from app import work_queue
from app.runtime_health import WorkerHeartbeat
from octopus_sdk.time_utils import utc_now
from octopus_sdk.inbound_types import (
    InboundAction,
    InboundCallback,
    InboundCommand,
    InboundMessage,
    deserialize_inbound,
)
from octopus_sdk.work_queue import TransportStateCorruption, WorkItemRecord

log = logging.getLogger(__name__)

# Default interval between queue polls (seconds).
POLL_INTERVAL = 1.0
SHARED_POLL_INTERVAL = 0.5
SWEEP_INTERVAL = 60.0
HEARTBEAT_INTERVAL = 30.0
USAGE_PURGE_INTERVAL_SECONDS = 3600.0
USAGE_PURGE_OLDER_THAN_HOURS = 168

# Maximum items to process per poll cycle before yielding.
BATCH_SIZE = 10


def poll_interval_for_runtime(runtime_mode: str) -> float:
    return SHARED_POLL_INTERVAL if runtime_mode == "shared" else POLL_INTERVAL


def _worker_error_code(exc: BaseException) -> str:
    if isinstance(exc, TransportStateCorruption):
        return "transport_state_corruption"
    return "dispatch_exception"


async def worker_loop(
    data_dir: Path,
    worker_id: str,
    dispatch,
    *,
    deserialize_failure_notifier: Callable[[WorkItemRecord], Awaitable[None]] | None = None,
    poll_interval: float = POLL_INTERVAL,
    lease_ttl: int = 300,
    sweep_interval: float = SWEEP_INTERVAL,
    process_role: str = "worker",
    heartbeat_enabled: bool = False,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously claim and dispatch work items the durable queue.

    Args:
        data_dir: Data directory containing transport.db.
        worker_id: Unique identifier for this worker (typically boot_id).
        dispatch: Async callable ``(kind, event, work_item) -> None``
            that processes a claimed work item.
        poll_interval: Seconds between queue polls when idle.
        stop_event: When set, the loop exits after the current cycle.
    """
    _stop = stop_event or asyncio.Event()
    log.info(
        "Worker %s starting (poll_interval=%.1fs lease_ttl=%ds sweep_interval=%.1fs)",
        worker_id,
        poll_interval,
        lease_ttl,
        sweep_interval,
    )
    last_sweep = 0.0
    started_at = utc_now().isoformat()
    items_processed_total = 0
    stale_recoveries_seen = 0
    current_item_id = ""
    current_conversation_key = ""
    current_kind = ""
    last_error = ""
    last_heartbeat = 0.0
    graceful_shutdown = False
    last_usage_purge = float("-inf")

    def _publish_heartbeat(*, force: bool = False) -> None:
        nonlocal last_heartbeat
        if not heartbeat_enabled:
            return
        now_mono = time.monotonic()
        if not force and last_heartbeat and (now_mono - last_heartbeat) < heartbeat_interval:
            return
        try:
            work_queue.upsert_worker_heartbeat(
                data_dir,
                WorkerHeartbeat(
                    worker_id=worker_id,
                    process_role=process_role,
                    started_at=started_at,
                    last_seen_at=utc_now().isoformat(),
                    current_item_id=current_item_id,
                    current_conversation_key=current_conversation_key,
                    current_kind=current_kind,
                    items_processed=items_processed_total,
                    stale_recoveries_seen=stale_recoveries_seen,
                    last_error=last_error,
                ),
            )
            last_heartbeat = now_mono
        except Exception:
            log.exception("Worker %s heartbeat update failed", worker_id)

    try:
        _publish_heartbeat(force=True)
        while not _stop.is_set():
            processed = 0
            try:
                _publish_heartbeat()
                now_mono = time.monotonic()
                if now_mono - last_sweep >= sweep_interval:
                    try:
                        recovered = work_queue.recover_stale_claims(
                            data_dir,
                            lease_ttl_seconds=lease_ttl,
                        )
                        if recovered:
                            stale_recoveries_seen += recovered
                            log.info(
                                "Recovered %d stale claims (lease_ttl=%ds)",
                                recovered,
                                lease_ttl,
                            )
                            _publish_heartbeat(force=True)
                    except Exception:
                        log.exception("Stale-claim sweep error")
                    if now_mono - last_usage_purge >= USAGE_PURGE_INTERVAL_SECONDS:
                        try:
                            work_queue.purge_old_usage(
                                data_dir,
                                older_than_seconds=USAGE_PURGE_OLDER_THAN_HOURS * 3600,
                            )
                            last_usage_purge = now_mono
                        except Exception:
                            log.exception("Usage-log purge error")
                    last_sweep = now_mono

                for _ in range(BATCH_SIZE):
                    item = work_queue.claim_next_any(data_dir, worker_id)
                    if item is None:
                        break

                    item_id = item.id
                    kind = item.kind or "unknown"
                    payload = item.payload or "{}"
                    current_item_id = item_id
                    current_conversation_key = item.conversation_key
                    current_kind = kind
                    last_error = ""
                    _publish_heartbeat(force=True)

                    try:
                        event = deserialize_inbound(kind, payload)
                    except Exception:
                        log.warning("Failed to deserialize work item %s (kind=%s), marking failed",
                                    item_id, kind)
                        work_queue.fail_work_item(data_dir, item_id, error="deserialize_error")
                        if deserialize_failure_notifier is not None:
                            try:
                                await deserialize_failure_notifier(item)
                            except Exception:
                                log.debug(
                                    "Failed to notify user about deserialize failure for item %s",
                                    item_id,
                                    exc_info=True,
                                )
                        current_item_id = ""
                        current_conversation_key = ""
                        current_kind = ""
                        items_processed_total += 1
                        processed += 1
                        _publish_heartbeat(force=True)
                        continue

                    try:
                        await dispatch(kind, event, item)
                        work_queue.complete_work_item(data_dir, item_id)
                    except work_queue.PendingRecovery:
                        log.info("Item %s moved to pending_recovery; user will replay or discard",
                                 item_id)
                    except work_queue.LeaveClaimed:
                        log.info("Worker interrupted processing item %s; leaving claimed for recovery",
                                 item_id)
                    except TransportStateCorruption as e:
                        log.exception(
                            "Transport state corruption for item %s (dispatch path): %s",
                            item_id, e,
                        )
                        last_error = _worker_error_code(e)
                        _publish_heartbeat(force=True)
                        raise
                    except Exception as exc:
                        # Dispatch code owns best-effort user/channel-facing
                        # error messages. This outer catch is the durable
                        # fallback that prevents the item staying claimed
                        # forever if dispatch fails unexpectedly.
                        log.exception("Worker failed processing item %s", item_id)
                        error_code = _worker_error_code(exc)
                        last_error = error_code
                        work_queue.fail_work_item(data_dir, item_id, error=error_code)
                    current_item_id = ""
                    current_conversation_key = ""
                    current_kind = ""
                    items_processed_total += 1
                    processed += 1
                    _publish_heartbeat(force=True)

            except TransportStateCorruption as e:
                log.exception("Transport state corruption in worker loop (claim path): %s", e)
                last_error = _worker_error_code(e)
                _publish_heartbeat(force=True)
                raise
            except Exception as exc:
                log.exception("Worker loop error")
                last_error = _worker_error_code(exc)
                _publish_heartbeat(force=True)

            if processed:
                log.debug("Worker %s processed %d items", worker_id, processed)
                # Immediately check for more work
                continue

            # Idle — wait for next poll or stop signal
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # normal poll cycle
        graceful_shutdown = True
        log.info("Worker %s stopped", worker_id)
    finally:
        if heartbeat_enabled and graceful_shutdown:
            try:
                work_queue.clear_worker_heartbeat(data_dir, worker_id)
            except Exception:
                log.exception("Worker %s heartbeat cleanup failed", worker_id)


def start_worker_task(
    data_dir: Path,
    worker_id: str,
    dispatch,
    *,
    deserialize_failure_notifier: Callable[[WorkItemRecord], Awaitable[None]] | None = None,
    poll_interval: float = POLL_INTERVAL,
    lease_ttl: int = 300,
    sweep_interval: float = SWEEP_INTERVAL,
    process_role: str = "worker",
    heartbeat_enabled: bool = False,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
) -> tuple[asyncio.Task, asyncio.Event]:
    """Start the worker loop as a background asyncio task.

    Returns (task, stop_event) so the caller can signal shutdown.
    """
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker_loop(data_dir, worker_id, dispatch,
                    deserialize_failure_notifier=deserialize_failure_notifier,
                    poll_interval=poll_interval,
                    lease_ttl=lease_ttl,
                    sweep_interval=sweep_interval,
                    process_role=process_role,
                    heartbeat_enabled=heartbeat_enabled,
                    heartbeat_interval=heartbeat_interval,
                    stop_event=stop_event),
        name="work_queue_worker",
    )
    return task, stop_event
