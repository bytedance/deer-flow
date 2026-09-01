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

    Unhandled exceptions get their own 500 here rather than in Starlette's
    ``ServerErrorMiddleware``: that middleware sits outside every user
    middleware and emits through the raw send, so its 500 -- the one response
    a user most needs to correlate with a log line -- would be the only one
    without the header.

    That fallback 500 is CORS-opaque: this middleware sits outside
    ``CORSMiddleware``, so the exception has already unwound past it and the
    500 carries no ``Access-Control-Allow-Origin`` -- a split-origin browser
    client cannot read the id on this one response, unchanged from the
    ``ServerErrorMiddleware`` 500 it replaces. Deliberately not fixed here:
    replicating the origin allowlist outside ``CORSMiddleware`` would let the
    two policies drift.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_trace_id = Headers(scope=scope).get(TRACE_ID_HEADER)

        with request_trace_context(incoming_trace_id) as trace_id:
            response_started = False

            async def send_with_trace(message: Message) -> None:
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    MutableHeaders(scope=message)[TRACE_ID_HEADER] = trace_id
                await send(message)

            try:
                await self.app(scope, receive, send_with_trace)
            except Exception:
                # Before the response has started, ship a plain 500 carrying
                # the header and re-raise: the outer ServerErrorMiddleware sees
                # the response already started and only re-raises too, so the
                # server's exception logging is untouched. Mid-stream failures
                # propagate unchanged -- a second response start cannot be
                # sent, and the already-written header stands. The id is
                # printable ASCII by construction (``normalize_trace_id`` /
                # ``generate_trace_id``), which makes the raw latin-1 header
                # encoding safe.
                if not response_started:
                    body = b"Internal Server Error"
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            # content-length keeps the framing byte-identical
                            # to the ServerErrorMiddleware response this
                            # replaces; without it the ASGI server picks
                            # (chunked on HTTP/1.1, close-delimited on 1.0).
                            "headers": [
                                (b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode("latin-1")),
                                (TRACE_ID_HEADER.encode("latin-1"), trace_id.encode("latin-1")),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                raise
