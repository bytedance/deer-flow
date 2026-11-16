"""Resolve the server-owned ``deerflow_origin`` of a run request.

Only two sources are trusted:

1. a server-side launcher that sets ``request.state.run_origin`` on the
   request object it builds (the scheduler, MCP notifications, extension
   handles). HTTP input can never reach ``request.state``;
2. an internal HTTP caller (the IM channel manager, authenticated with the
   internal token) that declares it in ``body.metadata``.

Every other caller gets ``None``, and run admission drops any client copy of
the key (``services.start_run``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, admit_origin


def resolve_request_origin(request: Any, body_metadata: Mapping | None) -> dict[str, str] | None:
    """The origin to stamp on this run, or ``None`` for interactive callers."""
    state = getattr(request, "state", None)
    host = getattr(state, "run_origin", None)
    if host is not None:
        return admit_origin(host)
    if getattr(state, "auth_source", None) == AUTH_SOURCE_INTERNAL and isinstance(body_metadata, Mapping):
        return admit_origin(body_metadata.get(DEERFLOW_ORIGIN_KEY))
    return None


__all__ = ["resolve_request_origin"]
