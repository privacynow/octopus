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
from pathlib import Path

from app import work_queue
from app.transport import deserialize_inbound, InboundMessage, InboundCommand, InboundCallback
from app.workflows.results import TransportStateCorruption

log = logging.getLogger(__name__)

# Default interval between queue polls (seconds).
POLL_INTERVAL = 1.0

# Maximum items to process per poll cycle before yielding.
BATCH_SIZE = 10


async def worker_loop(
    data_dir: Path,
    worker_id: str,
    dispatch,
    *,
    poll_interval: float = POLL_INTERVAL,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously claim and dispatch work items from the durable queue.

    Args:
        data_dir: Data directory containing transport.db.
        worker_id: Unique identifier for this worker (typically boot_id).
        dispatch: Async callable ``(kind, event, work_item) -> None``
            that processes a claimed work item.
        poll_interval: Seconds between queue polls when idle.
        stop_event: When set, the loop exits after the current cycle.
    """
    _stop = stop_event or asyncio.Event()
    log.info("Worker %s starting (poll_interval=%.1fs)", worker_id, poll_interval)

    while not _stop.is_set():
        processed = 0
        try:
            for _ in range(BATCH_SIZE):
                item = work_queue.claim_next_any(data_dir, worker_id)
                if item is None:
                    break

                item_id = item["id"]
                kind = item.get("kind", "unknown")
                payload = item.get("payload", "{}")

                try:
                    event = deserialize_inbound(kind, payload)
                except Exception:
                    log.warning("Failed to deserialize work item %s (kind=%s), marking failed",
                                item_id, kind)
                    work_queue.fail_work_item(data_dir, item_id, error="deserialize_error")
                    processed += 1
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
                    raise
                except Exception as exc:
                    log.exception("Worker failed processing item %s", item_id)
                    work_queue.fail_work_item(data_dir, item_id, error=str(exc)[:500])
                processed += 1

        except TransportStateCorruption as e:
            log.exception("Transport state corruption in worker loop (claim path): %s", e)
            raise
        except Exception:
            log.exception("Worker loop error")

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

    log.info("Worker %s stopped", worker_id)


def start_worker_task(
    data_dir: Path,
    worker_id: str,
    dispatch,
    *,
    poll_interval: float = POLL_INTERVAL,
) -> tuple[asyncio.Task, asyncio.Event]:
    """Start the worker loop as a background asyncio task.

    Returns (task, stop_event) so the caller can signal shutdown.
    """
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker_loop(data_dir, worker_id, dispatch,
                    poll_interval=poll_interval, stop_event=stop_event),
        name="work_queue_worker",
    )
    return task, stop_event
