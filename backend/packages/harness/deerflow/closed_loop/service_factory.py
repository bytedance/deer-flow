"""Resolve a process-wide :class:`ClosureService` for in-process callers.

The Gateway constructs the canonical service in ``app/gateway/deps.py`` and
stashes it on ``app.state.closure_service``. Builtin tools that the LLM
invokes do not have access to the FastAPI request, so they need a way to get
hold of the same domain service inside the harness.

This module owns a lazy, thread-safe singleton that:

1. Returns whatever instance was injected via :func:`set_default_service`
   (the Gateway pushes its already-wired service into here at startup so
   tools and routes share repositories / event publishers).
2. Falls back to building a default service from
   :func:`deerflow.persistence.engine.get_session_factory` plus a fresh
   :class:`MemoryRunEventStore` when no instance has been injected. This
   keeps unit tests and the embedded ``DeerFlowClient`` working without
   booting Gateway.

The factory is intentionally lightweight — it never imports anything from
``app.*`` so the harness boundary stays clean.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.closed_loop.service import ClosureService

logger = logging.getLogger(__name__)


_service: ClosureService | None = None
_lock = threading.Lock()


def set_default_service(service: ClosureService | None) -> None:
    """Inject (or clear) the process-wide service instance.

    Gateway startup calls this so tools see the same repository and event
    publisher the routes use. Tests can pass ``None`` to force the lazy
    fallback path.
    """
    global _service
    with _lock:
        _service = service


def get_default_service() -> ClosureService | None:
    """Return the cached service, building a default when none was injected.

    Returns ``None`` when no DB session factory is available — callers
    should treat that as "closure subsystem not configured" and surface a
    helpful error to the LLM rather than crashing.
    """
    global _service
    if _service is not None:
        return _service
    with _lock:
        if _service is not None:
            return _service
        built = _build_default_service()
        if built is not None:
            _service = built
        return _service


def reset_default_service() -> None:
    """Clear the cached service (test hook)."""
    global _service
    with _lock:
        _service = None


def _build_default_service() -> ClosureService | None:
    from deerflow.closed_loop.events import ClosureEventPublisher
    from deerflow.closed_loop.repository import ClosureRepository
    from deerflow.closed_loop.service import ClosureService
    from deerflow.persistence.engine import get_session_factory
    from deerflow.runtime.events.store import make_run_event_store

    sf = get_session_factory()
    if sf is None:
        logger.debug("closure service factory: no session factory — service unavailable")
        return None
    publisher = ClosureEventPublisher(make_run_event_store(None))
    return ClosureService(repository=ClosureRepository(sf), event_publisher=publisher)


__all__ = [
    "get_default_service",
    "reset_default_service",
    "set_default_service",
]
