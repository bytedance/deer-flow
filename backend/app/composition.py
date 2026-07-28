"""Composition root -- the one place adapters are instantiated and wired.

Every application service is assembled here and nowhere else. Ports are
declared by the domain, implemented under ``app/adapters/``, and the two are
introduced to each other in this file; no router, middleware, or lifespan hook
constructs an adapter of its own.

**Why this is a pure function rather than part of the lifespan.** Wiring used
to live inside ``deps.py::langgraph_runtime``, tangled with engine startup,
orphan recovery, and graceful shutdown -- so the one rule that actually
governs it ("no SQL backend means no service, and the routes answer 503")
could not be tested without driving a full application startup, and was held
up by a single comment. ``build_domain_services`` takes what it needs and
returns what it built, so that rule is an assertion in
``tests/test_composition.py`` instead.

**What "no SQL backend" means.** ``session_factory is None`` is how a
``database.backend: memory`` deployment presents itself. Both contexts own
tables, so neither can run on it; each service is ``None`` and the dependency
providers translate that into 503. This is deliberately not a silent
degradation to an in-memory implementation -- scheduled work that vanishes on
restart is worse than scheduled work that is refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from deerflow.domain.feedback.service import FeedbackService
from deerflow.domain.schedule.model import SchedulePolicy
from deerflow.domain.schedule.service import ScheduleService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from deerflow.config.scheduler_config import SchedulerConfig
    from deerflow.persistence.thread_meta.base import ThreadMetaStore
    from deerflow.runtime.runs.store import RunStore


@dataclass(frozen=True)
class DomainServices:
    """Every application service the Gateway serves, or ``None`` where the
    configured backend cannot support one."""

    feedback: FeedbackService | None
    schedule: ScheduleService | None


def build_domain_services(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    run_store: RunStore,
    thread_store: ThreadMetaStore,
    launch_run: Callable[..., Awaitable[Mapping[str, Any]]],
    scheduler_config: SchedulerConfig,
) -> DomainServices:
    """Wire the domain services from already-built infrastructure.

    Takes infrastructure rather than building it: engines, stores and the run
    launcher have lifecycles (startup, recovery, shutdown) that belong to the
    lifespan, while deciding *what is assembled from them* is this function's
    only job. That split is what makes it callable from a test.
    """
    if session_factory is None:
        return DomainServices(feedback=None, schedule=None)

    # Imported here, not at module scope: these pull in SQLAlchemy and the
    # Gateway run path, and the composition root is imported by tests that
    # only want the memory-backend branch.
    from app.adapters.feedback.feedback_repository import SqlFeedbackRepository
    from app.adapters.feedback.run_lookup import RunStoreRunLookup
    from app.adapters.schedule.run_launcher import GatewayRunLauncher
    from app.adapters.schedule.scheduled_run_repository import SqlScheduledRunRepository
    from app.adapters.schedule.scheduled_task_repository import SqlScheduledTaskRepository
    from app.adapters.schedule.thread_lookup import ThreadStoreThreadLookup

    return DomainServices(
        feedback=FeedbackService(
            repository=SqlFeedbackRepository(session_factory),
            runs=RunStoreRunLookup(run_store),
        ),
        schedule=ScheduleService(
            tasks=SqlScheduledTaskRepository(session_factory),
            runs=SqlScheduledRunRepository(session_factory),
            launcher=GatewayRunLauncher(launch_run),
            threads=ThreadStoreThreadLookup(thread_store),
            policy=build_schedule_policy(scheduler_config),
        ),
    )


def build_run_completion_hook(
    schedule_service: ScheduleService | None,
) -> Callable[[Any], Awaitable[None]] | None:
    """Install the schedule context on the run runtime's completion callback.

    The inbound half of the wiring, and nothing more: which runs the context
    cares about and what it does with them belongs to the adapter, not here.
    This function's only decision is the same one the rest of this module
    makes -- what to assemble, and what to leave unassembled.

    Returns ``None`` when there is no service, so the runtime installs no hook
    at all rather than one that always declines.
    """
    if schedule_service is None:
        return None

    from app.adapters.schedule.run_completion import ScheduleRunCompletionListener

    return ScheduleRunCompletionListener(schedule_service)


def build_schedule_policy(scheduler_config: SchedulerConfig) -> SchedulePolicy:
    """Project the operator's scheduler config onto the domain's policy.

    Separate from the wiring above because it is the whole of the
    configuration-to-domain translation: the domain declares which thresholds
    it needs, and this names where each one comes from. `poll_interval_seconds`
    is deliberately absent -- how often to look is the poller's business, not a
    rule any task is subject to.
    """
    return SchedulePolicy(
        min_once_delay_seconds=scheduler_config.min_once_delay_seconds,
        max_concurrent_runs=scheduler_config.max_concurrent_runs,
        lease_seconds=scheduler_config.lease_seconds,
    )
