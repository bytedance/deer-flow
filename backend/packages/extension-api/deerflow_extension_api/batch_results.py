"""Optional request-bound, read-only access to native durable batch results."""

from collections.abc import Callable
from typing import Any, Protocol

BATCH_RESULTS_RESOLVER_KEY = "deerflow_extension_batch_results_resolver"


class BatchResultError(Exception):
    """A public admission/availability error; handlers can preserve its status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class BatchResultReader(Protocol):
    """Host-bound principal; no user override, execution spec or write methods.

    Returned dictionaries are detached public projections. An inaccessible
    thread/batch/item is absent, not a globally readable resource. Detail reads
    return one saved report, verdict and evidence snapshot together with a
    revision covering that projection. Worker availability does not gate reads.
    """

    async def list_batches(self, *, thread_id: str, limit: int = 20) -> list[dict[str, Any]]: ...

    async def list_items(self, *, thread_id: str, batch_id: str, offset: int = 0, limit: int = 50) -> list[dict[str, Any]] | None: ...

    async def read_item(self, *, thread_id: str, batch_id: str, position: int) -> dict[str, Any] | None: ...


def resolve_batch_results(request: object) -> BatchResultReader | None:
    """Resolve from the actual request, never a caller-supplied owner.

    Unsupported hosts return None. Denied callers raise BatchResultError.
    Resolver exceptions propagate without a global-reader fallback.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    resolver: Callable | None = getattr(state, BATCH_RESULTS_RESOLVER_KEY, None)
    return resolver(request) if callable(resolver) else None


def require_batch_results(request: object) -> BatchResultReader:
    reader = resolve_batch_results(request)
    if reader is None:
        raise BatchResultError(503, "Durable batch storage is unavailable")
    return reader
