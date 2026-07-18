"""Gateway request trace middleware."""

from __future__ import annotations

import logging
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deerflow.config.app_config import is_trace_correlation_enabled
from deerflow.trace_context import TRACE_ID_HEADER, request_trace_context

logger = logging.getLogger(__name__)


class TraceMiddleware:
    """Bind a request-level trace id and write it to HTTP response headers.

    The ``enabled`` flag is a **startup snapshot** rather than a per-request
    live read: ``logging`` is registered as restart-required in
    ``deerflow.config.reload_boundary.STARTUP_ONLY_FIELDS`` because
    ``configure_logging()`` only installs the trace-context filter and
    formatter during app.py lifespan startup. Reading ``logging.enhance.enabled``
    live here would let a runtime config edit surface the response
    ``X-Trace-Id`` header and Langfuse ``deerflow_trace_id`` immediately while
    the log formatter stays on its startup value, contradicting the
    restart-required contract IDE hover surfaces on ``AppConfig.logging``.
    """

    def __init__(self, app: ASGIApp, *, enabled: bool):
        self.app = app
        self.enabled = bool(enabled)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming_trace_id = headers.get(TRACE_ID_HEADER)

        with request_trace_context(incoming_trace_id) as trace_id:

            async def send_with_trace(message: Message) -> None:
                if message["type"] == "http.response.start":
                    response_headers = MutableHeaders(scope=message)
                    response_headers[TRACE_ID_HEADER] = trace_id
                await send(message)

            await self.app(scope, receive, send_with_trace)


def resolve_trace_enabled(config: Any) -> bool:
    """Read ``logging.enhance.enabled`` from an ``AppConfig``-like object.

    Thin backwards-compatible alias around
    :func:`deerflow.config.app_config.is_trace_correlation_enabled`, kept so
    existing gateway callers and tests do not have to switch imports. Both
    the Gateway middleware and the embedded ``DeerFlowClient`` resolve the
    gate through the same harness helper so their behaviour cannot drift.
    """
    return is_trace_correlation_enabled(config)
