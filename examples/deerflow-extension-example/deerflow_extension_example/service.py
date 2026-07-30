"""The service and its router -- one object, two roles.

Routers must be constructed eagerly, during ``install()``, so the host can
detect path conflicts and freeze its OpenAPI surface before it serves. But
``install()`` is capability-free by design: there is nothing to talk to yet.

The resolution is the pattern below. The same object registers as an
``ExtensionService`` and provides the router's FastAPI dependency: paths and the
dependency graph are fixed at import time, while the actual host capabilities
arrive later in ``start()`` and are resolved per request through ``Depends()``.

That makes the 503 window explicit rather than accidental. Before ``start()``,
after ``stop()``, and when ``start()`` failed and the host fail-opened past it,
the route reports unavailable instead of serving a half-built answer.
"""

# NOTE: no `from __future__ import annotations` in this module, on purpose.
# PEP 563 turns every annotation into a string, and FastAPI resolves those
# strings against *module* globals -- so a marker like
# `Annotated[..., Depends(service.require_deps)]`, whose `service` is local to
# `build_router()`, fails to resolve. FastAPI's resolution is lenient: it keeps
# the raw string instead of raising, the `Depends` is silently lost, and the
# parameter degrades into a required query parameter answering 422 where you
# expected 503. Either drop the future import here (this file) or use the
# `deps: X = Depends(...)` default-value form, which is evaluated eagerly.

from dataclasses import asdict
from typing import Annotated, Any

from deerflow_extension_api import ExtensionRuntimeDeps
from fastapi import APIRouter, Depends, HTTPException

from deerflow_extension_example.stats import RunStats, StatsAccess

ROUTE_PREFIX = "/api/extension-example"


class ExampleService:
    """Binds host runtime dependencies for the lifetime of the Gateway."""

    def __init__(self, access: StatsAccess) -> None:
        self._access = access
        self._deps: ExtensionRuntimeDeps | None = None

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._deps = deps
        if deps.app_store is not None:
            # The host's enforced limits, projected. Recorded rather than acted
            # on here because this example only observes; a real extension would
            # size its buffers or skip work the host already caps.
            self._access.of(deps.app_store).note_host_policy(asdict(deps.policy))

    async def stop(self) -> None:
        # Unbinding is the point: the router stays mounted for the rest of the
        # shutdown sequence, and it must stop answering with stale capabilities.
        self._deps = None

    def require_deps(self) -> ExtensionRuntimeDeps:
        """FastAPI dependency. Resolved per request, never captured at import."""
        deps = self._deps
        if deps is None or deps.app_store is None:
            raise HTTPException(status_code=503, detail="extension-example is not started yet")
        return deps


def build_router(service: ExampleService, access: StatsAccess) -> APIRouter:
    """Construct the router eagerly. No host capabilities are touched here."""
    router = APIRouter(prefix=ROUTE_PREFIX, tags=["extension-example"])

    @router.get("/stats")
    async def read_stats(deps: Annotated[ExtensionRuntimeDeps, Depends(service.require_deps)]) -> dict[str, Any]:
        assert deps.app_store is not None  # require_deps() already refused None
        stats: RunStats = access.of(deps.app_store)
        return {
            "scope_id": deps.app_store.scope_id,
            # Reported, not used: this example stores nothing. Persistence for
            # extensions (a shared declarative Base and its migration chain) is
            # a separate concern from the observation contract.
            "session_factory_available": deps.session_factory is not None,
            **stats.snapshot(),
        }

    return router
