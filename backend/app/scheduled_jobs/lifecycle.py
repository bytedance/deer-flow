"""Gateway lifespan hooks for the scheduler.

The Gateway calls ``start_scheduler(app, bus=...)`` in its ``lifespan``
and ``stop_scheduler()`` in the finally block. This is the **only**
wiring point between the application and the harness ``Scheduler`` —
keeping the integration footprint to a single line each.

Singleton state lives at module level because FastAPI lifespan runs
once per worker and the Gateway is currently single-worker (see the
``GATEWAY_WORKERS`` note in ``docker-compose.yaml``).
"""

from __future__ import annotations

import logging
from typing import Any

from app.scheduled_jobs.delivery import DeliveryDispatcher, InAppNotifier
from app.scheduled_jobs.executor import AgentJobExecutor
from app.scheduled_jobs.im_pusher import IMPusher
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_job_runs import ScheduledJobRunRepository
from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
from deerflow.scheduler.core import DEFAULT_MAX_CONCURRENT, Scheduler

logger = logging.getLogger(__name__)

# Module-level singleton — set by start_scheduler, cleared by stop_scheduler.
_scheduler: Scheduler | None = None


async def start_scheduler(
    app: Any | None = None,
    *,
    bus: Any | None = None,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
) -> None:
    """Build and start the scheduler singleton.

    Args:
        app: FastAPI app instance (unused for now, reserved for future
            wiring such as binding a shutdown handler).
        bus: optional ``MessageBus`` from the running ``ChannelService``.
            When provided, the scheduler's delivery dispatcher routes
            IM results to ``bus.publish_outbound``. When None (channels
            disabled), IM deliveries degrade to log-only.
        max_concurrent: hard cap on simultaneous job executions.

    Idempotent — calling twice is a no-op.
    """
    global _scheduler
    if _scheduler is not None:
        return

    session_factory = get_session_factory()
    if session_factory is None:
        logger.warning("persistence engine not initialised — scheduler will not start")
        return

    jobs_repo = ScheduledJobRepository(session_factory)
    runs_repo = ScheduledJobRunRepository(session_factory)

    # Wire up delivery: IM via shared bus (if available), Web via log-only notifier
    im_pusher = IMPusher(bus) if bus is not None else None
    dispatcher = DeliveryDispatcher(im_pusher=im_pusher, in_app=InAppNotifier())

    executor = AgentJobExecutor(jobs_repo, runs_repo, delivery=dispatcher)

    _scheduler = Scheduler(
        jobs_repo,
        executor,
        max_concurrent=max_concurrent,
    )
    await _scheduler.start()
    logger.info(
        "scheduled_jobs: scheduler wired into Gateway lifespan (im_bus=%s)",
        "attached" if bus is not None else "none",
    )


async def stop_scheduler() -> None:
    """Stop the scheduler singleton if running. Safe to call multiple times."""
    global _scheduler
    if _scheduler is None:
        return
    await _scheduler.stop()
    _scheduler = None
    logger.info("scheduled_jobs: scheduler stopped")


def get_scheduler() -> Scheduler | None:
    """Test/diagnostic accessor for the running scheduler singleton."""
    return _scheduler
