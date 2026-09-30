"""Request trace context helpers.

The value stored here is DeerFlow's request-level correlation id. It is
separate from Langfuse's own trace id and from DeerFlow run ids.

**This ContextVar is the only source of a trace id.** Every path that reaches a
run binds one first: the Gateway ``TraceMiddleware`` for HTTP, and
:func:`ensure_trace_context` for the entry points that never touch ASGI --
scheduled occurrences, MCP task notification runs, IM channel messages, and the
embedded :class:`~deerflow.client.DeerFlowClient`. Downstream code can therefore
treat the trace id as a plain ``str`` and use :func:`ensure_trace_id` or
:func:`resolve_trace_id` instead of the ``if trace_id:`` guards a nullable id
used to require.

Everything else that carries the id -- the ``X-Trace-Id`` response header,
``runtime.context[DEERFLOW_TRACE_METADATA_KEY]``, the run record's metadata,
log records -- is a **derived output, never read back as an input**. A caller
that sends ``metadata.deerflow_trace_id`` on a run request has it replaced
rather than honoured: reading it back would let the persisted run disagree with
the header the same request already returned, and a trace id you cannot trust
to match the logs is worse than no trace id at all. Callers that need to pin a
correlation id across services send ``X-Trace-Id``.

``logging.enhance.enabled`` gates log output only -- whether records carry a
``trace_id`` field, and in which format. It does not gate the id's existence,
the response header, or the run metadata.

Crossing execution boundaries
-----------------------------
The ContextVar is task-local and does not survive a bare thread hop, which is
why the id also travels as data. Code re-entering on the far side of such a
boundary rebinds with :func:`ensure_trace_context` and reads carriers through
:func:`resolve_trace_id`, keeping the fallback order in one place instead of
open-coding it per call site.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final

TRACE_ID_HEADER: Final[str] = "X-Trace-Id"
DEERFLOW_TRACE_METADATA_KEY: Final[str] = "deerflow_trace_id"
_MAX_TRACE_ID_LENGTH: Final[int] = 512

_current_trace_id: Final[ContextVar[str | None]] = ContextVar("deerflow_current_trace_id", default=None)


def generate_trace_id() -> str:
    """Return a fresh header-safe trace id."""
    return uuid.uuid4().hex


def normalize_trace_id(value: object) -> str | None:
    """Return a safe trace id string, or ``None`` when *value* is unusable.

    Only printable ASCII (0x20-0x7E) is accepted. Codepoints above 0x7E are
    rejected because the trace id round-trips through HTTP response headers,
    which Starlette encodes as latin-1: codepoints > 0xFF raise
    ``UnicodeEncodeError`` inside ``MutableHeaders.__setitem__`` (forcing a
    500 before the response body is even dispatched), and C1 controls
    (0x80-0x9F) technically encode but are stripped or rejected by hardened
    intermediaries (nginx / envoy / cloudfront), silently breaking the
    response. C0 controls (< 0x20) and DEL (0x7F) are rejected for the same
    header-safety reason plus log-injection defense.
    """
    if not isinstance(value, str):
        return None
    trace_id = value.strip()
    if not trace_id or len(trace_id) > _MAX_TRACE_ID_LENGTH:
        return None
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in trace_id):
        return None
    return trace_id


def get_current_trace_id() -> str | None:
    """Return the bound trace id, or ``None`` when nothing is bound.

    Prefer :func:`ensure_trace_id` or :func:`resolve_trace_id`, which honour
    the non-nullable contract. This nullable accessor exists for callers that
    must neither mutate context nor fabricate a value: the logging filter,
    which runs on records emitted before any entry point (import time,
    third-party threads) and renders those as ``trace_id=-``.
    """
    return _current_trace_id.get()


def ensure_trace_id() -> str:
    """Return the ambient trace id, minting and binding one when unset.

    Binding rather than returning a throwaway id is what makes repeated calls
    inside one context agree.
    """
    trace_id = _current_trace_id.get()
    if trace_id is None:
        trace_id = generate_trace_id()
        _current_trace_id.set(trace_id)
    return trace_id


def resolve_trace_id(*carriers: object) -> str:
    """Return the first usable value in *carriers*, else the ambient trace id.

    The single place that knows the carrier fallback order, so a consumer
    reading the id back out of ``runtime.context`` states its carriers and
    nothing else. Carriers are listed most authoritative first and validated
    with :func:`normalize_trace_id`, so an absent key and a malformed value
    fall through identically.
    """
    for carrier in carriers:
        normalized = normalize_trace_id(carrier)
        if normalized is not None:
            return normalized
    return ensure_trace_id()


def bind_trace_id(trace_id: str | None) -> Token[str | None]:
    """Bind *trace_id* in the current context; ``None`` clears the binding.

    The low-level pair for callers that cannot use the context managers: a
    sync generator that must bind per step (``DeerFlowClient.stream``), and
    test harnesses restoring an unbound baseline. Values are normalized, and
    an unusable one clears rather than fabricating an id -- every caller here
    has already resolved the value it means to bind.
    """
    return _current_trace_id.set(normalize_trace_id(trace_id))


def reset_trace_id(token: Token[str | None]) -> None:
    """Restore the binding captured by *token*."""
    _current_trace_id.reset(token)


@contextmanager
def request_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Open a trace scope for an HTTP request, always binding a fresh id.

    *trace_id* is the inbound ``X-Trace-Id``; an absent or unusable one is
    replaced by a generated id. Deliberately does **not** inherit the ambient
    context: a crafted header must not silently fall back to the id of
    whatever request ran before it on the same task.
    """
    normalized = normalize_trace_id(trace_id) or generate_trace_id()
    token = _current_trace_id.set(normalized)
    try:
        yield normalized
    finally:
        _current_trace_id.reset(token)


@contextmanager
def ensure_trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Open a trace scope that inherits the ambient one when there is one.

    Two callers, one rule -- *reuse the surrounding scope, otherwise start a
    self-contained one*:

    - Non-HTTP entry points (a scheduled occurrence, an MCP task notification
      run, an inbound IM message) called with no id: the scope mints one, and
      unbinds it on exit so the next unit of work on the same long-lived
      worker task does not inherit it. Reached from inside an HTTP request --
      a manual scheduled trigger, say -- it stays on the caller's trace
      instead of minting a competing id.
    - Crossing an execution boundary (a thread hop, a background task, a queue
      hand-off) where the ContextVar may not have survived: pass the id that
      travelled as data alongside the work.
    """
    normalized = normalize_trace_id(trace_id)
    inherited = _current_trace_id.get()
    if inherited is not None and (normalized is None or inherited == normalized):
        yield inherited
        return

    resolved = normalized or generate_trace_id()
    token = _current_trace_id.set(resolved)
    try:
        yield resolved
    finally:
        _current_trace_id.reset(token)
