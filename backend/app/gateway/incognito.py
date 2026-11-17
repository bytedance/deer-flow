"""Incognito thread lifetime: the background expiry sweep.

The Gateway starts :func:`run_incognito_sweep_loop` beside the other lifespan
background tasks. It polls the thread store for incognito rows whose deadline
passed and deletes their data through the same orchestration as
``DELETE /api/threads/{thread_id}``, under the same durable reservation, so a
sweep can never race an in-flight run.

Ordering matters: the store tombstone (``status="expired"``, content cleared)
is written before any delete, so a purge that fails halfway still leaves the
thread unreadable; and the row's ``expires_at`` is cleared only after every
store has been cleaned, which is what makes a failed purge retry on the next
pass. The row itself is never deleted: the thread id must not be reusable as
an ordinary thread, and read routes must report it as gone rather than as an
empty 200.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.gateway.utils import sanitize_log_param
from deerflow.runtime import ThreadOperationKind
from deerflow.runtime.goal import goal_thread_lock
from deerflow.runtime.runs.manager import ConflictError

logger = logging.getLogger(__name__)

# Fallback poll cadence when the live config cannot be read (a broken
# config.yaml must not turn the sweep into a busy loop).
_SWEEP_RETRY_SECONDS = 60


async def sweep_expired_incognito_threads(app: Any, *, now: datetime | None = None, batch_size: int = 100) -> int:
    """Purge one batch of expired incognito threads; return how many finished.

    A thread with work in flight is skipped: its reservation refuses the
    delete, its data stays intact, and the next sweep retries it. A batch
    entry whose deadline was renewed after the due list was read is skipped
    too, and every other failure leaves the tombstone in place and is retried
    the same way.
    """
    store = getattr(app.state, "thread_store", None)
    run_manager = getattr(app.state, "run_manager", None)
    if store is None or run_manager is None:
        return 0

    due = await store.list_due_incognito(now=now, limit=batch_size)
    purged = 0
    for record in due:
        thread_id = record.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            continue
        user_id = record.get("user_id")
        try:
            async with goal_thread_lock(thread_id):
                async with run_manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.delete, user_id=user_id):
                    # The due list is a snapshot; a run admission or completion
                    # may have renewed the deadline since it was read. The
                    # store rechecks under its row lock and reports whether the
                    # row is still due, so a renewed thread is left alone.
                    if not await store.begin_incognito_expiry(thread_id):
                        continue
                    # Imported lazily: the delete core lives with the threads
                    # router, and importing that module here would pull the
                    # whole router graph into app startup before it is needed.
                    from app.gateway.routers.threads import purge_thread_data

                    await purge_thread_data(thread_id, app_state=app.state, user_id=user_id, delete_meta_row=False, require_complete=True)
                    await store.finish_incognito_expiry(thread_id)
            purged += 1
        except ConflictError:
            logger.info("Incognito thread %s has work in flight; expiry deferred to the next sweep", sanitize_log_param(thread_id))
        except Exception:
            logger.warning("Failed to purge expired incognito thread %s; retrying on the next sweep", sanitize_log_param(thread_id), exc_info=True)
    return purged


async def run_incognito_sweep_loop(app: Any) -> None:
    """Sweep until cancelled; the lifespan owns the task and its shutdown.

    Runs even when ``incognito.enabled`` is false: the switch stops clients
    from creating new incognito threads, but threads created before the
    operator flipped it must still be deleted on schedule.
    """
    from deerflow.config import get_app_config

    while True:
        try:
            settings = (await asyncio.to_thread(get_app_config)).incognito
        except Exception:
            logger.warning("Incognito sweep could not read config.yaml; retrying in %ss", _SWEEP_RETRY_SECONDS, exc_info=True)
            await asyncio.sleep(_SWEEP_RETRY_SECONDS)
            continue
        try:
            purged = await sweep_expired_incognito_threads(app, batch_size=settings.sweep_batch_size)
            if purged:
                logger.info("Incognito lifetime sweep purged %d thread(s)", purged)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Incognito lifetime sweep failed", exc_info=True)
        await asyncio.sleep(settings.sweep_interval_seconds)
