"""Background overdue-scan job for the closed-loop subsystem.

Runs a single asyncio task in the Gateway process that wakes every
``DEFAULT_INTERVAL_SECONDS`` (5 minutes) and asks the
:class:`ClosureService` to flip ``is_overdue=True`` on tickets whose
``due_at`` has lapsed.

Concurrency safety across multiple Gateway replicas:

* On PostgreSQL we hold a transactional ``pg_try_advisory_lock`` for the
  duration of the scan. If a peer holds it, this replica skips the cycle
  cleanly — no error, no retry storm.
* On SQLite or backend=memory there is only one writer process by
  definition, so we fall back to a process-local :class:`asyncio.Lock`
  to coordinate against the (vanishingly unlikely) re-entrant case where
  the previous tick is still running when the next one fires.

The loop catches and logs every exception so a transient repository
fault never kills the periodic task — the next cycle will retry.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from deerflow.closed_loop.service import ClosureService

logger = logging.getLogger(__name__)


DEFAULT_INTERVAL_SECONDS: float = 300.0  # 5 minutes


# 64-bit signed key picked from the closed-loop subsystem's "cl-osvd" mnemonic
# (no collision audit needed — advisory locks are scoped to keys you choose).
_PG_ADVISORY_KEY: int = 0x4C53435F4F564452  # "LSC_OVDR" → "closure overdue"


_SCANNER_TASK_ATTR = "_closure_overdue_scanner_task"
_SCANNER_STOP_ATTR = "_closure_overdue_scanner_stop"
_SCANNER_LOCK_ATTR = "_closure_overdue_scanner_lock"


async def _try_pg_advisory_lock(session: AsyncSession) -> bool:
    """Attempt to acquire the cross-replica advisory lock on PostgreSQL.

    Returns True if this replica owns the lock for the current
    transaction, False if a peer holds it. The lock is auto-released
    when the transaction ends, so callers MUST keep the session open
    for the duration of the work they want to serialize.
    """
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)").bindparams(k=_PG_ADVISORY_KEY)
    )
    return bool(result.scalar())


def _is_postgres(session_factory: async_sessionmaker[AsyncSession] | None) -> bool:
    if session_factory is None:
        return False
    bind = session_factory.kw.get("bind")
    if bind is None:
        return False
    name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    return name.lower().startswith("postgres")


async def _run_one_cycle(
    *,
    service: ClosureService,
    session_factory: async_sessionmaker[AsyncSession] | None,
    process_lock: asyncio.Lock,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[dict[str, Any]] | None:
    """Run a single overdue-scan cycle.

    Returns the list of newly-flipped overdue rows, or ``None`` when the
    cycle was skipped because a peer replica held the advisory lock or
    the previous in-process tick was still running.
    """
    if _is_postgres(session_factory):
        assert session_factory is not None  # narrows for type checker
        async with session_factory() as session:
            async with session.begin():
                acquired = await _try_pg_advisory_lock(session)
                if not acquired:
                    logger.debug("closure.overdue_scan: peer holds advisory lock, skipping cycle")
                    return None
                # Hold the lock for the duration of the scan. The scan itself
                # opens its own short-lived sessions via the repository, which
                # is fine — the advisory lock lives on `session`.
                return await service.scan_overdue_once(now=now_factory())
    else:
        if process_lock.locked():
            logger.debug("closure.overdue_scan: previous cycle still running, skipping")
            return None
        async with process_lock:
            return await service.scan_overdue_once(now=now_factory())


async def _scanner_loop(
    *,
    service: ClosureService,
    session_factory: async_sessionmaker[AsyncSession] | None,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    """Periodic overdue-scan loop.

    Sleeps for ``interval`` seconds between cycles. A short initial delay
    lets the rest of the Gateway finish startup before the first scan
    fires. Exits cleanly when ``stop_event`` is set.
    """
    process_lock = asyncio.Lock()

    # Short startup delay so the periodic task does not race with
    # repositories still being wired up by the lifespan context.
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=min(interval, 30.0))
        return
    except TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            published = await _run_one_cycle(
                service=service,
                session_factory=session_factory,
                process_lock=process_lock,
            )
            if published:
                logger.info(
                    "closure.overdue_scan: marked %d ticket(s) overdue", len(published)
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — never let scanner die on a transient fault
            logger.exception("closure.overdue_scan: cycle failed; will retry next interval")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return  # stop_event fired
        except TimeoutError:
            continue


def start_overdue_scanner(
    app: Any,
    *,
    service: ClosureService | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> bool:
    """Register and start the periodic overdue-scanner on ``app.state``.

    Idempotent: a second call while the task is alive is a no-op. Returns
    ``True`` if the scanner was started, ``False`` when no service was
    available (e.g. backend=memory) or the scanner was already running.
    """
    existing = getattr(app.state, _SCANNER_TASK_ATTR, None)
    if existing is not None and not existing.done():
        logger.debug("closure.overdue_scan: scanner already running, ignoring start request")
        return False

    if service is None:
        service = getattr(app.state, "closure_service", None)
    if service is None:
        logger.info(
            "closure.overdue_scan: no closure_service on app.state — scanner not started"
        )
        return False

    if session_factory is None:
        from deerflow.persistence.engine import get_session_factory

        session_factory = get_session_factory()

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _scanner_loop(
            service=service,
            session_factory=session_factory,
            interval=interval_seconds,
            stop_event=stop_event,
        ),
        name="closure.overdue_scanner",
    )
    setattr(app.state, _SCANNER_TASK_ATTR, task)
    setattr(app.state, _SCANNER_STOP_ATTR, stop_event)
    setattr(app.state, _SCANNER_LOCK_ATTR, asyncio.Lock())
    logger.info(
        "closure.overdue_scan: scanner started (interval=%.1fs, postgres=%s)",
        interval_seconds,
        _is_postgres(session_factory),
    )
    return True


async def stop_overdue_scanner(app: Any, *, timeout: float = 5.0) -> None:
    """Signal the scanner loop to exit and await termination.

    Bounded by ``timeout`` so a stuck task cannot hang Gateway shutdown.
    Safe to call when the scanner was never started.
    """
    task: asyncio.Task | None = getattr(app.state, _SCANNER_TASK_ATTR, None)
    stop_event: asyncio.Event | None = getattr(app.state, _SCANNER_STOP_ATTR, None)
    if task is None:
        return
    if stop_event is not None:
        stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError:
        logger.warning("closure.overdue_scan: scanner did not stop within %.1fs; cancelling", timeout)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        logger.exception("closure.overdue_scan: scanner exited with an error")
    finally:
        setattr(app.state, _SCANNER_TASK_ATTR, None)
        setattr(app.state, _SCANNER_STOP_ATTR, None)
        setattr(app.state, _SCANNER_LOCK_ATTR, None)
        logger.info("closure.overdue_scan: scanner stopped")


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "start_overdue_scanner",
    "stop_overdue_scanner",
    "_run_one_cycle",  # exposed for unit tests
]
