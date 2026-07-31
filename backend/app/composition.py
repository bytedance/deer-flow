"""Composition root -- the one place adapters are instantiated and wired.

Every application service is assembled here and nowhere else. Ports are
declared by the domain, implemented under ``app/adapters/``, and the two are
introduced to each other in this file; no router, middleware, or lifespan hook
constructs an adapter of its own.

**Why this is a pure function rather than part of the lifespan.** Wiring used
to live inline in ``deps.py::langgraph_runtime``, tangled with engine startup
and shutdown -- so the one rule that actually governs it ("no SQL backend
means no service, and the routes answer 503") could not be tested without
driving a full application startup. ``build_domain_services`` takes what it
needs and returns what it built, so that rule is an assertion in
``tests/test_composition.py`` instead.

**What "no SQL backend" means.** ``session_factory is None`` is how a
``database.backend: memory`` deployment presents itself. The feedback context
owns a table, so it cannot run on it; the service is ``None`` and the
dependency provider translates that into 503. This is deliberately not a
silent degradation to an in-memory implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deerflow.domain.feedback import FeedbackService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from deerflow.runtime.runs.store import RunStore


@dataclass(frozen=True)
class DomainServices:
    """Every application service the Gateway serves, or ``None`` where the
    configured backend cannot support one."""

    feedback: FeedbackService | None


def build_domain_services(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    run_store: RunStore,
) -> DomainServices:
    """Wire the domain services from already-built infrastructure.

    Takes infrastructure rather than building it: engines and stores have
    lifecycles (startup, recovery, shutdown) that belong to the lifespan,
    while deciding *what is assembled from them* is this function's only
    job. That split is what makes it callable from a test.
    """
    if session_factory is None:
        return DomainServices(feedback=None)

    # Imported here, not at module scope: these pull in SQLAlchemy, and the
    # composition root is imported by tests that only want the memory branch.
    from app.adapters.feedback.feedback_repository import SqlFeedbackRepository
    from app.adapters.feedback.run_lookup import RunStoreRunLookup

    return DomainServices(
        feedback=FeedbackService(
            repository=SqlFeedbackRepository(session_factory),
            runs=RunStoreRunLookup(run_store),
        ),
    )
