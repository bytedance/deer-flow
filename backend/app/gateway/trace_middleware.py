"""Gateway request trace middleware."""

from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from deerflow.trace_context import TRACE_ID_HEADER, request_trace_context


class TraceMiddleware:
    """Bind a trace id to every HTTP request and write it to the response.

    Deliberately ungated. The id has to exist on every path so that everything
    downstream -- the run worker's run metadata, delegated subagents, the
    background memory threads -- reads one ContextVar instead of branching on
    "there might be no trace id". ``logging.enhance.enabled`` only decides
    whether log records print it (``logging_config.configure_logging``), so
    this middleware reads no ``AppConfig`` and is not entangled with the
    restart-required contract on that field.

    The header is written at ``http.response.start`` rather than on the
    finished response, which covers SSE and other streaming responses without
    consuming the body. ``CORS_EXPOSED_HEADERS`` lists it so split-origin
    browser clients can read it back.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_trace_id = Headers(scope=scope).get(TRACE_ID_HEADER)

        with request_trace_context(incoming_trace_id) as trace_id:

            async def send_with_trace(message: Message) -> None:
                if message["type"] == "http.response.start":
                    MutableHeaders(scope=message)[TRACE_ID_HEADER] = trace_id
                await send(message)

            await self.app(scope, receive, send_with_trace)
